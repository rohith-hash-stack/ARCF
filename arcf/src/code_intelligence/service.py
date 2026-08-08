"""CodeIntelligenceContractService — Phase 5's contribution to the same
Living Contract lineage Phase 3/4 established: builds a
CodeIntelligenceIndex for the contract's workspace, resolves it via
ContextResolver, persists the resulting ContextResolutionResult, and
evolves the contract to reference it by id.

Mirrors workspace/service.py's WorkspaceContractService exactly — same
evolve-and-persist pattern, same reasoning for not embedding the
(potentially large) result directly in Contract. This is the retroactive
wiring Phase 5 deferred: "its query patterns will be clearer once Phase
6 exists to need them." Phase 6's context-package endpoint is what
needs it now.

ARCF v2.3 retrieval-context stabilization patch: also classifies the
contract's raw request via RepositoryScopeClassifier and, only when
symbol-based resolution comes back with zero candidate_files for a
repository-scoped request, falls back to evidence-based file collection
(context/evidence_fallback.py) using the same scan already performed
below — see RepositoryScopeClassifier's own docstring for why this is
the module that owns that decision.

Repository debugging routing fix, Change 6 (diagnostic logging): emits
one DEBUG-level JSON log line per request via the "arcf.retrieval"
logger — routing decision fields only (task_type, repository_scope,
evidence_contract, detected_language, detected_frameworks,
candidate_files), keyed by contract_id. This is the earliest point every
one of those fields is known together. files_sent_to_llm isn't known
yet here — resolution and packaging are separate phases (Phase 5 vs.
Phase 6; see context/budget_manager.py's own docstring on why they can
be two separate API calls) — so context/packager.py emits its own
correlated line, keyed by context_resolution_id, once packaging
actually happens. Internal/DEBUG only: never returned in any API
response, never shown to an end user.
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from uuid import UUID, uuid4

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.language_coverage import compute_language_coverage
from code_intelligence.symbol_index import SymbolIndex
from code_intelligence.unsupported_conditions import has_dynamic_dispatch_hint, is_generated_file
from context.anchor_classifier import (
    TIER_CONFIDENCE,
    AnchorTier,
    classify_file_anchors,
    classify_symbol_anchors,
    decay_confidence,
    hop_from_reason,
)
from context.evidence_fallback import expand_with_evidence
from context.evidence_validator import validate_sufficiency
from context.lexical_symbol_probe import probe_symbol_names, probe_symbol_names_ranked
from context.query_decomposition import decompose_query
from context.relevance_ranker import RelevanceRanker
from context.subsystem_localizer import localize_subsystems
from context.task_profile import TRAVERSAL_DEPTH, classify_retrieval_task
from contracts.evidence_contract import build_evidence_contract, detect_task_type_for_evidence
from contracts.repository_scope_classifier import RepositoryScopeClassifier
from contracts.task_classifier import TaskClassifier
from domain.code_intelligence import SymbolKind
from domain.context_resolution import (
    ContextResolutionResult,
    EvidenceTier,
    FileReference,
    TokenEstimate,
)
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import ContextResolutionStore
from infrastructure.contract_store import ContractStore
from infrastructure.cost import CostEstimator
from shared.errors import ContractNotFoundError, NoWorkspaceAttachedError, WorkspacePathError
from workspace.permissions import PermissionManager
from workspace.repository_segmentation import RepositorySegmenter
from workspace.scanner import RepositoryScanner, ScanResult

_logger = logging.getLogger("arcf.retrieval")

# See the call site's comment (lexical symbol probing recovery, below):
# a fixed, conservative traversal depth for re-resolving probe-matched
# names — independent of the query's own RetrievalTaskType-derived depth.
_LEXICAL_PROBE_RECOVERY_DEPTH = 1

# ARCF Pre-Expansion Anchor Classification experiment (2026-08-08):
# Tier 3 (lexical-guess) anchors expand with this token budget, activating
# ContextResolver's existing `_TokenBudget` gate on the previously-
# unbounded `callers_of()` fan-out path. Deliberately larger than the real
# API's final packaging default (8,000 tokens, schemas.
# CreateContextPackageRequest) — this bounds Phase 5 EXPANSION, a
# different, earlier budget than Phase 6's final packaging budget, and
# constraining it to the same number would double-bound the same
# candidate set for no reason. Sized to be a real, felt constraint
# relative to the unbounded case (which measured 1.86M tokens on a real
# SQLAlchemy run) without being tuned to that one repo's specific numbers.
_TIER3_EXPANSION_TOKEN_BUDGET = 50_000

# ARCF Tier 1 expansion budget fix (2026-08-08), found the same day as
# the Tier 1 ambiguity guard above: the ambiguity guard stops a NAME
# that matches many different symbols from being trusted, but it does
# nothing to bound a single, precisely-matched symbol that is itself
# heavily called/referenced — the original brief's "Tier 1: normal
# 1-hop expansion" was written as unrestricted, and a real Consul run
# showed that's unsafe in practice: even after the ambiguity fix, Tier 1
# alone still added 66 files from a handful of precisely-matched but
# highly-connected symbols. Larger than Tier 3's budget (Tier 1 is a
# strictly higher-confidence signal and still deserves more room), but
# no longer unbounded.
_TIER1_EXPANSION_TOKEN_BUDGET = 100_000

# A class's own method is only added to Tier 1 if its bare NAME isn't
# itself wildly ambiguous across the whole repo — ContextResolver resolves
# by name only, with no class-scoping, so an unfiltered `__init__` (shared
# by every class that has one) matched 268 unrelated files on the real
# SQLAlchemy run, a severe regression discovered empirically, not assumed.
# Same threshold as the two other ambiguity guards already in this
# codebase (lexical_symbol_probe._MAX_MATCHES_PER_NAME,
# context_resolver._MAX_CANDIDATES_TO_EXPAND) — a name matching this many
# or fewer real symbols is still a precise enough signal to trust.
_CLASS_METHOD_AMBIGUITY_CAP = 5

# ARCF Multi-Axis Query Decomposition experiment (2026-08-08): how many
# files each independently-retrieved axis contributes to the merged
# candidate set — the brief's own example ("1 file from Strategy and 1
# file from Execution"). A strict per-axis cap, not a shared budget: the
# whole point under test is whether a small, GUARANTEED slot per axis
# beats one pooled ranking where an axis-specific file has to outcompete
# every other axis's noise too.
_MULTI_AXIS_QUOTA_PER_AXIS = 1

# Recovers the anchor name from a ContextResolver reason string
# ("defines X", "calls X (hop N)", "called by X (hop N)", "extends X") —
# "called by" is two words, so naive whitespace splitting misidentifies
# it; this matches all four verb shapes explicitly instead.
_ANCHOR_NAME_RE = re.compile(r"^(?:defines|calls|called by|extends) (.+?)(?:\s\(hop \d+\))?$")


class CodeIntelligenceContractService:
    def __init__(
        self,
        engine: CodeIntelligenceEngine,
        contract_store: ContractStore,
        resolution_store: ContextResolutionStore,
    ) -> None:
        self._engine = engine
        self._contract_store = contract_store
        self._resolution_store = resolution_store
        self._scope_classifier = RepositoryScopeClassifier()
        self._task_classifier = TaskClassifier()

    async def attach_code_intelligence(
        self,
        contract_id: UUID,
        target_names: list[str],
        workspace_root: str | None,
        enable_subsystem_localization: bool = False,
        enable_ranked_seed_selection: bool = False,
        enable_anchor_classification: bool = False,
        enable_confidence_propagation: bool = False,
        enable_multi_axis_decomposition: bool = False,
    ) -> tuple[LivingContract, ContextResolutionResult]:
        """`enable_subsystem_localization` — ARCF root-cause validation
        experiment (context/subsystem_localizer.py), defaulted to False:
        every existing caller, and every existing test, gets today's
        exact behavior unchanged. When True, the lexical-probe-recovery
        step below (see its own comment) restricts its candidate names to
        the query's highest-confidence subsystem(s) before re-resolving,
        instead of searching the whole symbol index unrestricted. This
        is an explicit, isolated A/B toggle for one specific experiment —
        not a general pipeline setting; do not default it to True without
        the experiment's own success criteria being met first.

        `enable_ranked_seed_selection` — ARCF candidate-ranking follow-up
        experiment (2026-08-08, `probe_symbol_names_ranked`), defaulted
        to False, only has any effect when `enable_subsystem_localization`
        is also True: the real SQLAlchemy run of the localization
        experiment found that scoping the probe to the right subsystem
        wasn't enough on its own — the existing 20-name cap still filled
        with generically-matched names in raw scan order, dropping
        `orm/loading.py`'s own symbols before they ever got a slot. This
        flag swaps the localized probe's selection rule from scan-order
        to ranked-by-signal (see `probe_symbol_names_ranked`'s own
        docstring). Independent, narrowly-scoped A/B toggle, same
        experimental status as `enable_subsystem_localization` — not a
        general setting.

        `enable_anchor_classification` / `enable_confidence_propagation`
        — ARCF Pre-Expansion Anchor Classification experiment
        (2026-08-08, context/anchor_classifier.py), both defaulted to
        False. When `enable_anchor_classification` is True, it REPLACES
        the lexical-probe-recovery / subsystem-localization / ranked-
        seed-selection logic below (the two flags above have no effect
        when this one is True) with a tiered classification: Tier 1
        (exact real-symbol-name match, confidence 1.0), Tier 3 (the same
        prefix/substring probe as before, confidence 0.5), Tier 4
        (filename-only match, confidence recalibrated to 0.35 after a
        real SQLAlchemy run — see anchor_classifier.TIER_CONFIDENCE's own
        comment for why — no graph expansion at all). `enable_confidence_propagation`, independent of the other
        three flags, additionally decays each anchor's confidence once
        per traversal hop (see anchor_classifier.decay_confidence) and
        attaches it to FileReference.anchor_confidence, which
        RelevanceRanker then multiplies into its existing role-weight
        score — additive to that scoring system, not a replacement of
        it. Both default False: every existing caller and test gets
        today's exact behavior unchanged.

        `enable_multi_axis_decomposition` — ARCF Multi-Axis Query
        Decomposition experiment (2026-08-08, context/
        query_decomposition.py), defaulted to False, mutually exclusive
        with `enable_anchor_classification` (takes priority if both are
        somehow set — deliberately NOT composable with any of the other
        experimental flags on this method, per that experiment's own
        explicit scope). Splits a comparative/cross-cutting query
        ("X differs from Y...") into independent retrieval axes at a
        general English marker, runs today's existing lexical-probe +
        ContextResolver pipeline independently per axis, and merges in
        only each axis's own top-`_MULTI_AXIS_QUOTA_PER_AXIS` ranked
        file(s) (via the existing, unmodified RelevanceRanker) — instead
        of pooling every axis's candidates into one ranking, each axis
        gets a small guaranteed slot. A query with no comparative marker
        decomposes to a single axis, so this flag has no effect on it."""
        latest = await asyncio.to_thread(self._contract_store.get_latest, contract_id)
        if latest is None:
            raise ContractNotFoundError(f"No contract found with id {contract_id}")

        root = workspace_root or latest.contract.workspace_root
        if root is None:
            raise NoWorkspaceAttachedError(
                "No workspace_root available; attach a workspace first or provide one"
            )

        result = await asyncio.to_thread(
            self._resolve,
            Path(root),
            str(latest.contract_id),
            target_names,
            latest.contract.intent.raw_request,
            enable_subsystem_localization,
            enable_ranked_seed_selection,
            enable_anchor_classification,
            enable_confidence_propagation,
            enable_multi_axis_decomposition,
        )
        self._log_retrieval_diagnostics(latest, result)
        await asyncio.to_thread(self._resolution_store.save, result)

        new_contract = latest.contract.model_copy(
            update={"id": uuid4(), "context_resolution_id": result.id}
        )
        evolved = latest.evolve(new_contract)
        await asyncio.to_thread(self._contract_store.save, evolved)
        return evolved, result

    def _resolve(
        self,
        root_path: Path,
        contract_id: str,
        target_names: list[str],
        raw_request: str,
        enable_subsystem_localization: bool = False,
        enable_ranked_seed_selection: bool = False,
        enable_anchor_classification: bool = False,
        enable_confidence_propagation: bool = False,
        enable_multi_axis_decomposition: bool = False,
    ) -> ContextResolutionResult:
        if not root_path.is_dir():
            raise WorkspacePathError(f"{root_path} is not an existing directory")

        # ARCF hardening §12 (pipeline ordering): lightweight deterministic
        # checks — language/analyzer-coverage detection, repository
        # segmentation, and task classification — run off the scan alone,
        # before paying the cost of a full parse. A repository with zero
        # analyzable files skips straight to evidence-contract matching
        # (a glob match over scan.files, not a parse) instead of indexing
        # nothing usefully — CI/CD- or config-only repositories still get
        # a real evidence-backed result this way, not an empty one.
        scan = RepositoryScanner().scan(root_path)
        coverage = compute_language_coverage(scan.files, self._engine.registry)
        segmenter = RepositorySegmenter(scan.files)
        files_scanned = len(scan.files)
        resolved_root = str(root_path.resolve())

        classification = self._scope_classifier.classify(raw_request)
        task_classifier_task = self._task_classifier.classify(raw_request)
        retrieval_task_type = classify_retrieval_task(
            raw_request, task_classifier_task, classification.task_type
        )
        traversal_depth = TRAVERSAL_DEPTH[retrieval_task_type]

        fully_unsupported = bool(files_scanned) and coverage.files_skipped_count == files_scanned
        if fully_unsupported:
            index = None
            result = self._empty_resolution(resolved_root, contract_id)
        else:
            index = self._engine.build_index(root_path, scan.files)
            result = ContextResolver(index).resolve(
                resolved_root,
                contract_id,
                resolved_root,
                target_names,
                traversal_depth=traversal_depth,
                # ARCF Issue #7 fix (2026-08-08): this is the primary,
                # most-trusted resolution path (confident target names),
                # and it had NO token-budget gate at all — for
                # RetrievalTaskType.LARGE_STRUCTURAL_CHANGE specifically,
                # traversal_depth is None ("expand until max_expansion_
                # tokens is reached", per TRAVERSAL_DEPTH's own comment),
                # meaning that task type could expand genuinely
                # unbounded with no budget ever supplied to stop it — a
                # more severe version of the same uncapped-callers_of()
                # gap found and fixed for Tier 1/3 in the anchor-
                # classification path. Same generous budget as Tier 1's
                # (this path is equally or more trusted).
                max_expansion_tokens=_TIER1_EXPANSION_TOKEN_BUDGET,
            )

        # Captured before expand_with_evidence runs: whether the query
        # named a real symbol at all. This — not whatever candidate_files
        # ends up holding after the broader evidence-fallback tiers run —
        # is what should gate lexical symbol probing below. Evidence-
        # contract matching (tier 2/3) is a coarse, generic category match
        # ("test directories", "CI/workflow files") that says nothing
        # about whether it found anything actually relevant to the query;
        # gating probing on its output let a query like "explain how
        # context locals work" (no quoted/backticked entity, so
        # target_names is empty) settle for README/CI/test-config filler
        # while a real match — `AppContext`, sharing the lexical root
        # "contex" — sat unprobed in the very module the question was
        # about, because evidence-fallback had already produced a
        # non-empty (just irrelevant) candidate_files list.
        symbol_resolution_found_nothing = not result.candidate_files

        # Called unconditionally, not just when classification.repository_scope
        # — expand_with_evidence's tier 1 (query-referenced filename/path
        # matching) is precise and cheap enough to run regardless of whether
        # the classifier recognized this query's shape; tiers 2/3 (evidence
        # contract, root-level fallback) stay internally gated on
        # repository_scope, same behavior as before for those.
        result = expand_with_evidence(
            result,
            scan.files,
            root_path,
            classification.task_type,
            raw_request,
            repository_scope=classification.repository_scope,
        )

        # Classifier-gap fix, layer 3 (§4.3 of the 2026-08-06 handoff),
        # re-gated: runs whenever the *original* exact-symbol resolution
        # found nothing, regardless of whether expand_with_evidence's
        # coarser categories already filled candidate_files in the
        # meantime — a precise lexical-root match against a real symbol
        # name is a stronger signal than a generic evidence category and
        # should never be pre-empted by one. Results are merged additively
        # (new file paths only, existing entries and their reasons kept
        # as-is) rather than replacing `result` outright, so this can only
        # ever add candidate files on top of tier 1's query-referenced
        # matches — never relabel or drop them (see
        # test_repository_debugging_prioritizes_query_referenced_file).
        # Re-resolving through the full pipeline (not just adding files
        # directly) means call-graph traversal, locality disambiguation,
        # and justification chains all still apply to what this finds.
        # ARCF Pre-Expansion Anchor Classification experiment (2026-08-08):
        # a separate, earlier branch rather than nested inside the block
        # below — `enable_anchor_classification` REPLACES that block's
        # logic entirely for this call (see attach_code_intelligence's
        # own docstring), so the block below is explicitly gated OFF
        # (`and not enable_anchor_classification`) instead of restructured,
        # keeping its own 180 lines of tested, unrelated logic untouched.
        # ARCF Multi-Axis Query Decomposition experiment (2026-08-08):
        # same "separate, earlier, mutually-exclusive branch" pattern as
        # anchor classification above — checked FIRST so it takes
        # priority if both flags were somehow set, though the experiment
        # is explicitly scoped to never be combined with the others.
        if (
            symbol_resolution_found_nothing
            and index is not None
            and enable_multi_axis_decomposition
        ):
            result = self._resolve_via_multi_axis_decomposition(
                result, index, raw_request, contract_id, resolved_root, target_names
            )
        elif symbol_resolution_found_nothing and index is not None and enable_anchor_classification:
            result = self._resolve_via_anchor_classification(
                result,
                index,
                scan,
                raw_request,
                contract_id,
                resolved_root,
                target_names,
                enable_confidence_propagation,
            )

        if (
            symbol_resolution_found_nothing
            and index is not None
            and not enable_anchor_classification
            and not enable_multi_axis_decomposition
        ):
            localization_note = ""
            lexical_names: list[str] = []
            used_localized_probe = False
            if enable_subsystem_localization:
                # Root-cause validation experiment: scope the lexical
                # probe itself to whichever repository subsystem(s) the
                # query's wording actually concentrates in — see
                # context/subsystem_localizer.py's own docstring for the
                # hypothesis this tests. Deliberately probes WITHIN the
                # subsystem from the start (probe_symbol_names'
                # restrict_to_prefixes) rather than probing unrestricted
                # and filtering after: the real SQLAlchemy experiment
                # (2026-08-08) found that filtering an already-computed,
                # already-capped unrestricted probe result could exclude
                # the correct in-subsystem symbol before restriction ever
                # got a chance to matter, silently making the flag a
                # no-op even when localization correctly identified the
                # right subsystem.
                subsystems = localize_subsystems(raw_request, scan.files, index.symbol_index)
                if subsystems:
                    # Only the highest-confidence subsystem(s) — ties
                    # included, everything else excluded. localize_subsystems
                    # ranks every subsystem that matched *any* query prefix,
                    # which includes low-signal subsystems a generic word
                    # happens to also touch (e.g. one shared 6-char prefix)
                    # alongside the real match; scoping to the *whole*
                    # ranked list would probe their union instead of
                    # actually localizing, silently defeating this
                    # experiment's own purpose.
                    top = subsystems[0]
                    top_subsystems = [c for c in subsystems if c.confidence == top.confidence]
                    directory_prefixes = tuple(f"{c.directory}/" for c in top_subsystems)
                    # Candidate-ranking follow-up experiment: when also
                    # enabled, the localized probe's selection rule
                    # changes from "first _MAX_MATCHED_NAMES encountered
                    # during a raw symbol-index scan" to "highest-signal
                    # _MAX_MATCHED_NAMES" (see probe_symbol_names_ranked's
                    # own docstring) — same eligibility, different tie-
                    # break when the cap binds.
                    probe_fn = (
                        probe_symbol_names_ranked
                        if enable_ranked_seed_selection
                        else probe_symbol_names
                    )
                    localized_names = probe_fn(
                        raw_request, index.symbol_index, restrict_to_prefixes=directory_prefixes
                    )
                    ranking_label = " (ranked selection)" if enable_ranked_seed_selection else ""
                    localization_note = (
                        f" Subsystem localization selected \"{top.directory}\" "
                        f"(confidence {top.confidence}, matched terms: "
                        f"{', '.join(top.matched_terms)}), scoping lexical{ranking_label} "
                        f"symbol probing to {len(top_subsystems)} "
                        f"subsystem(s), finding {len(localized_names)} "
                        "in-subsystem name(s)."
                    )
                    if localized_names:
                        lexical_names = localized_names
                        used_localized_probe = True
                    else:
                        localization_note += " Falling back to unrestricted probing."
            if not used_localized_probe:
                lexical_names = probe_symbol_names(raw_request, index.symbol_index)
            if lexical_names:
                # Fixed, conservative depth — deliberately NOT the caller's
                # own `traversal_depth` — regardless of retrieval task type.
                # A prefix/substring lexical match is inherently a weaker
                # signal than an exact-name match (probe_symbol_names can
                # return up to 20 names off one query, e.g. "context locals"
                # substring-matching AppContext/has_request_context/
                # request_context/... in a real codebase), so letting each
                # independently fan out to the same depth confident exact
                # matches get (2 hops for e.g. REPOSITORY_EXPLANATION)
                # compounds 20x uncertainty into breadth: measured, this
                # merge alone grew a real flask query's candidate set to 35
                # files / ~105K tokens at depth 2 vs 30 files / ~86K at
                # depth 1 — both still find the actually-relevant files
                # (ctx.py, globals.py), depth 1 just does it with less
                # unrelated call-graph fan-out riding along.
                lexical_result = ContextResolver(index).resolve(
                    resolved_root,
                    contract_id,
                    resolved_root,
                    [*target_names, *lexical_names],
                    traversal_depth=_LEXICAL_PROBE_RECOVERY_DEPTH,
                    # ARCF Issue #7 fix (2026-08-08): this default-path
                    # lexical-probe-recovery call had no token-budget
                    # gate either — same uncapped-callers_of() exposure
                    # as the anchor-classification path had before its
                    # own Tier 1/3 fixes, just never patched here since
                    # this is the plain fallback used when none of the
                    # experimental flags are set. Same budget as Tier 3's
                    # (this is the same lexical-probe mechanism, same
                    # trust level).
                    max_expansion_tokens=_TIER3_EXPANSION_TOKEN_BUDGET,
                    # Evidence-preserving context packaging: even the file
                    # that directly defines a probe-matched name is a
                    # weaker signal than an exact target-name match (the
                    # probe is a 6-char prefix/substring guess — see
                    # lexical_symbol_probe.py), so ContextBudgetManager
                    # should feel free to compress it to its relevant
                    # symbol range rather than treat it as automatically
                    # worth its full size, however large the file it
                    # happens to live in is.
                    entry_point_tier=EvidenceTier.SUPPORTING,
                )
                existing_paths = {ref.file_path for ref in result.candidate_files}
                new_refs = [
                    ref
                    for ref in lexical_result.candidate_files
                    if ref.file_path not in existing_paths
                ]
                if new_refs:
                    # Deliberately additive, not a replacement of the
                    # generic "evidence: <category>" entries: a downstream,
                    # independent guarantee (context/evidence_validator.py's
                    # validate_sufficiency, called a few lines below this
                    # method) re-adds any evidence category that isn't
                    # covered by *some* candidate file, evidence-tagged or
                    # not — dropping them here just made it add them
                    # straight back (proven by
                    # test_query_referenced_file_survives_evidence_category_trim
                    # failing when this tried to drop them). That
                    # completeness guarantee is a separate, deliberate
                    # design decision ("the final LLM should never receive
                    # an incomplete evidence package") this method doesn't
                    # own and shouldn't quietly undermine.
                    shown = ", ".join(lexical_names[:5])
                    more = "..." if len(lexical_names) > 5 else ""
                    merged_files = sorted(
                        [*result.candidate_files, *new_refs], key=lambda ref: ref.file_path
                    )
                    selected_tokens = sum(ref.token_count for ref in merged_files)
                    raw_tokens = result.token_estimate.raw_context_tokens
                    # Evidence-preserving context packaging needs these
                    # merged too, not just candidate_files: ContextBudget
                    # Manager only knows where to compress a SUPPORTING
                    # file *around* via entry_points/impacted_symbols
                    # (see ContextBudgetManager._symbols_by_file). Without
                    # this, the lexical-probe recovery's own resolved
                    # symbols would vanish at the merge boundary and every
                    # file it found — evidence_tier=SUPPORTING or not —
                    # would have no symbol location to compress against,
                    # silently falling back to full-file-if-it-fits (the
                    # actual root cause of a real measured regression: a
                    # 49K-token file correctly tagged SUPPORTING was still
                    # sent in full, because this dict was empty).
                    existing_symbol_ids = {s.symbol_id for s in result.entry_points}
                    merged_entry_points = [
                        *result.entry_points,
                        *(
                            s
                            for s in lexical_result.entry_points
                            if s.symbol_id not in existing_symbol_ids
                        ),
                    ]
                    existing_impacted_ids = {s.symbol_id for s in result.impacted_symbols}
                    merged_impacted_symbols = [
                        *result.impacted_symbols,
                        *(
                            s
                            for s in lexical_result.impacted_symbols
                            if s.symbol_id not in existing_impacted_ids
                        ),
                    ]
                    result = result.model_copy(
                        update={
                            "candidate_files": merged_files,
                            "entry_points": merged_entry_points,
                            "impacted_symbols": merged_impacted_symbols,
                            "resolution_reason": (
                                f"{result.resolution_reason} Lexical symbol probing "
                                f"matched {len(lexical_names)} real symbol name(s) from "
                                f"the query's wording ({shown}{more}), adding "
                                f"{len(new_refs)} file(s) evidence-category matching missed."
                                f"{localization_note}"
                            ),
                            "token_estimate": result.token_estimate.model_copy(
                                update={
                                    "selected_context_tokens": selected_tokens,
                                    "compression_ratio": (
                                        round(selected_tokens / raw_tokens, 4)
                                        if raw_tokens
                                        else 0.0
                                    ),
                                }
                            ),
                        }
                    )

        evidence_task_type = detect_task_type_for_evidence(raw_request) or classification.task_type
        contract = build_evidence_contract(evidence_task_type)
        if contract:
            result, _ = validate_sufficiency(result, contract, scan.files, root_path)

        dominant_segment = segmenter.dominant_segment(
            [file_ref.file_path for file_ref in result.candidate_files]
        )
        files_analyzed = len(index.file_analyses) if index is not None else 0
        analyzer_coverage = round(files_analyzed / files_scanned, 4) if files_scanned else 1.0
        parse_error_files = tuple(index.parse_error_files) if index is not None else ()

        generated_files, dynamic_dispatch_hints = self._scan_candidates_for_unsupported_conditions(
            root_path, result.candidate_files
        )

        resolution_reason = result.resolution_reason
        if fully_unsupported:
            detected = ", ".join(coverage.languages_detected) or "no recognized language"
            resolution_reason += (
                f" No registered LanguageAnalyzer covers any scanned file (detected: "
                f"{detected}); skipped full indexing rather than parsing files with zero "
                "possible candidates."
            )

        result = result.model_copy(
            update={
                "repository_segment": dominant_segment,
                "files_scanned": files_scanned,
                "files_analyzed": files_analyzed,
                "languages_detected": coverage.languages_detected,
                "languages_unsupported": coverage.languages_unsupported,
                "analyzer_coverage": analyzer_coverage,
                "parse_error_files": parse_error_files,
                "generated_files": generated_files,
                "dynamic_dispatch_hints": dynamic_dispatch_hints,
                "resolution_reason": resolution_reason,
            }
        )
        return result

    def _resolve_via_anchor_classification(
        self,
        result: ContextResolutionResult,
        index: CodeIntelligenceIndex,
        scan: ScanResult,
        raw_request: str,
        contract_id: str,
        resolved_root: str,
        target_names: list[str],
        enable_confidence_propagation: bool,
    ) -> ContextResolutionResult:
        """ARCF Pre-Expansion Anchor Classification experiment
        (2026-08-08, context/anchor_classifier.py) — see
        attach_code_intelligence's own docstring for the tier
        definitions. Replaces (not composes with) the lexical-probe-
        recovery / subsystem-localization / ranked-seed-selection block
        this method's caller skips when this path is taken.

        Per-tier expansion policy (the brief's own wording, refined
        2026-08-08 after a real Consul run showed "normal" needed its own
        bound too — see `_TIER1_EXPANSION_TOKEN_BUDGET`'s own comment):
        Tier 1 — 1-hop expansion, ambiguity-guarded at classification
          (`_is_precise_match`) AND token-budget-gated during expansion
          — a name matching too many symbols is never trusted in the
          first place, and even a precisely-matched but highly-connected
          symbol's fan-out is now bounded, just at a larger budget than
          Tier 3's (Tier 1 is still the higher-confidence signal).
        Tier 3 — restricted 1-hop expansion WITH token-budget gating
          (`_TIER3_EXPANSION_TOKEN_BUDGET` below activates
          ContextResolver's existing, previously-dormant `_TokenBudget`
          gate on the uncapped `callers_of()` fan-out path — see that
          class's own docstring; this is the same mechanism identified
          as unused in this session's code review, now actually invoked).
        Tier 4 — no graph expansion at all: added directly as a
          low-confidence candidate file, bypassing ContextResolver
          entirely for these names.
        """
        symbol_anchors = classify_symbol_anchors(raw_request, index.symbol_index)
        file_anchors = classify_file_anchors(raw_request, scan.files)

        tier1_names = [a.name for a in symbol_anchors if a.tier is AnchorTier.EXACT]
        tier1_names = self._expand_class_anchors_to_methods(tier1_names, index.symbol_index)
        tier3_names = [a.name for a in symbol_anchors if a.tier is AnchorTier.LEXICAL]
        confidence_by_name = {a.name: a.confidence for a in symbol_anchors}
        # Newly-added method names (see _expand_class_anchors_to_methods)
        # weren't in symbol_anchors, so they'd otherwise have no confidence
        # entry — they're exactly as confirmed-real as the class anchor
        # that produced them, so they inherit Tier 1's own confidence.
        for name in tier1_names:
            confidence_by_name.setdefault(name, TIER_CONFIDENCE[AnchorTier.EXACT])

        merged_files: dict[str, FileReference] = {ref.file_path: ref for ref in result.candidate_files}
        merged_entry_points = list(result.entry_points)
        merged_impacted = list(result.impacted_symbols)
        existing_entry_ids = {s.symbol_id for s in merged_entry_points}
        existing_impacted_ids = {s.symbol_id for s in merged_impacted}
        tier_notes: list[str] = []

        def _merge_resolution(sub_result: ContextResolutionResult, force: bool = False) -> int:
            """`force=True` (Tier 1 only): a Tier 1 exact-identifier match
            is ARCF's strongest possible signal (confidence 1.0) and must
            win even when `expand_with_evidence` (which runs unconditionally
            before this method, regardless of these flags) already added
            the same file under a weaker reason — e.g. its own "lexical
            file-name probing" tier can independently match a file's
            basename and add it as "references: lexical-match" before
            anchor classification ever runs. Tier 3/Tier 4 keep the
            original, more conservative "first claim wins" rule — those
            are comparable in strength to expand_with_evidence's own
            tiers, so there's no principled reason to prefer one over the
            other."""
            nonlocal merged_entry_points, merged_impacted, existing_entry_ids, existing_impacted_ids
            added = 0
            for ref in sub_result.candidate_files:
                if ref.file_path in merged_files and not force:
                    continue
                if enable_confidence_propagation:
                    name_match = _ANCHOR_NAME_RE.match(ref.reason)
                    anchor_name = name_match.group(1) if name_match else ""
                    origin_confidence = confidence_by_name.get(anchor_name)
                    if origin_confidence is not None:
                        hop = hop_from_reason(ref.reason)
                        ref = ref.model_copy(
                            update={"anchor_confidence": decay_confidence(origin_confidence, hop)}
                        )
                merged_files[ref.file_path] = ref
                added += 1
            for s in sub_result.entry_points:
                if s.symbol_id not in existing_entry_ids:
                    existing_entry_ids.add(s.symbol_id)
                    merged_entry_points.append(s)
            for s in sub_result.impacted_symbols:
                if s.symbol_id not in existing_impacted_ids:
                    existing_impacted_ids.add(s.symbol_id)
                    merged_impacted.append(s)
            return added

        if tier1_names:
            tier1_result = ContextResolver(index).resolve(
                resolved_root,
                contract_id,
                resolved_root,
                [*target_names, *tier1_names],
                traversal_depth=1,
                max_expansion_tokens=_TIER1_EXPANSION_TOKEN_BUDGET,
                entry_point_tier=EvidenceTier.PRIMARY,
            )
            added = _merge_resolution(tier1_result, force=True)
            tier_notes.append(
                f"Tier 1 (exact match, confidence {TIER_CONFIDENCE[AnchorTier.EXACT]}): "
                f"{len(tier1_names)} anchor(s) ({', '.join(tier1_names[:5])}), "
                f"{added} file(s) added."
            )

        if tier3_names:
            tier3_result = ContextResolver(index).resolve(
                resolved_root,
                contract_id,
                resolved_root,
                [*target_names, *tier3_names],
                traversal_depth=1,
                max_expansion_tokens=_TIER3_EXPANSION_TOKEN_BUDGET,
                entry_point_tier=EvidenceTier.SUPPORTING,
            )
            added = _merge_resolution(tier3_result)
            tier_notes.append(
                f"Tier 3 (lexical guess, confidence {TIER_CONFIDENCE[AnchorTier.LEXICAL]}, "
                f"budget-gated at {_TIER3_EXPANSION_TOKEN_BUDGET} tokens): "
                f"{len(tier3_names)} anchor(s), {added} file(s) added."
            )

        if file_anchors:
            permissions = PermissionManager(Path(resolved_root))
            token_estimator = CostEstimator()
            added = 0
            for anchor in file_anchors:
                if anchor.file_path in merged_files:
                    continue
                try:
                    content = permissions.safe_read_text(anchor.file_path)
                except (OSError, WorkspacePathError):
                    continue
                analysis = index.file_analyses.get(anchor.file_path)
                language = analysis.language if analysis is not None else "unknown"
                ref = FileReference(
                    file_path=anchor.file_path,
                    # "references:" (not a made-up "tier4:" verb) — reuses
                    # the SAME role-weight key evidence_fallback.py's own
                    # "references: lexical-match" tier already has an
                    # entry for in every RANKING_PROFILES table, since
                    # this is the same kind of signal (a filename/path
                    # lexical match), just now carrying an explicit tier
                    # confidence. A made-up verb with no table entry falls
                    # through to the generic default weight, double-
                    # penalizing this tier on top of its confidence
                    # multiplier — exactly the bug the real SQLAlchemy
                    # validation run (2026-08-08) surfaced.
                    reason="references: tier4 incidental filename/path match",
                    language=language,
                    token_count=token_estimator.count_tokens(content, "gpt-4o-mini"),
                    evidence_tier=EvidenceTier.EXPERIMENTAL,
                    anchor_confidence=anchor.confidence if enable_confidence_propagation else None,
                )
                merged_files[ref.file_path] = ref
                added += 1
            if added:
                tier_notes.append(
                    f"Tier 4 (incidental, confidence "
                    f"{TIER_CONFIDENCE[AnchorTier.INCIDENTAL]}, no graph expansion): "
                    f"{added} file(s) added."
                )

        if not tier_notes:
            return result

        final_files = sorted(merged_files.values(), key=lambda ref: ref.file_path)
        selected_tokens = sum(ref.token_count for ref in final_files)
        raw_tokens = result.token_estimate.raw_context_tokens
        return result.model_copy(
            update={
                "candidate_files": final_files,
                "entry_points": merged_entry_points,
                "impacted_symbols": merged_impacted,
                "resolution_reason": (
                    f"{result.resolution_reason} Pre-expansion anchor classification: "
                    f"{' '.join(tier_notes)}"
                ),
                "token_estimate": result.token_estimate.model_copy(
                    update={
                        "selected_context_tokens": selected_tokens,
                        "compression_ratio": (
                            round(selected_tokens / raw_tokens, 4) if raw_tokens else 0.0
                        ),
                    }
                ),
            }
        )

    def _resolve_via_multi_axis_decomposition(
        self,
        result: ContextResolutionResult,
        index: CodeIntelligenceIndex,
        raw_request: str,
        contract_id: str,
        resolved_root: str,
        target_names: list[str],
    ) -> ContextResolutionResult:
        """ARCF Multi-Axis Query Decomposition experiment (2026-08-08) —
        see attach_code_intelligence's own docstring and context/
        query_decomposition.py's module docstring for the hypothesis.
        Deliberately reuses today's existing lexical-probe-recovery
        mechanism (probe_symbol_names + ContextResolver.resolve, same
        traversal depth as that path) and the existing, unmodified
        RelevanceRanker — no new ranking mechanism, no new symbol-
        matching mechanism, only new orchestration: run that mechanism
        independently per axis, keep only each axis's own top-
        `_MULTI_AXIS_QUOTA_PER_AXIS` ranked file(s), instead of pooling
        every axis into one ranking the way a single whole-query
        resolution would."""
        axes = decompose_query(raw_request)
        if len(axes) < 2:
            return result

        merged_files: dict[str, FileReference] = {
            ref.file_path: ref for ref in result.candidate_files
        }
        merged_entry_points = list(result.entry_points)
        merged_impacted = list(result.impacted_symbols)
        existing_entry_ids = {s.symbol_id for s in merged_entry_points}
        existing_impacted_ids = {s.symbol_id for s in merged_impacted}
        axis_notes: list[str] = []

        for axis in axes:
            lexical_names = probe_symbol_names(axis.text, index.symbol_index)
            axis_label = axis.text[:40] + ("..." if len(axis.text) > 40 else "")
            if not lexical_names:
                axis_notes.append(f'axis "{axis_label}": no lexical match, skipped.')
                continue

            axis_result = ContextResolver(index).resolve(
                resolved_root,
                contract_id,
                resolved_root,
                [*target_names, *lexical_names],
                traversal_depth=_LEXICAL_PROBE_RECOVERY_DEPTH,
                # ARCF Issue #7 fix (2026-08-08): same uncapped-
                # callers_of() exposure as every other lexical-probe
                # resolve() call in this file, closed for consistency
                # even though this experiment isn't part of the
                # currently-recommended configuration.
                max_expansion_tokens=_TIER3_EXPANSION_TOKEN_BUDGET,
                entry_point_tier=EvidenceTier.SUPPORTING,
            )
            ranked = RelevanceRanker().rank(axis_result)
            axis_files_by_path = {ref.file_path: ref for ref in axis_result.candidate_files}
            added_paths: list[str] = []
            for ranked_file in ranked:
                if len(added_paths) >= _MULTI_AXIS_QUOTA_PER_AXIS:
                    break
                if ranked_file.file_path in merged_files:
                    continue
                merged_files[ranked_file.file_path] = axis_files_by_path[ranked_file.file_path]
                added_paths.append(ranked_file.file_path)

            for s in axis_result.entry_points:
                if s.symbol_id not in existing_entry_ids:
                    existing_entry_ids.add(s.symbol_id)
                    merged_entry_points.append(s)
            for s in axis_result.impacted_symbols:
                if s.symbol_id not in existing_impacted_ids:
                    existing_impacted_ids.add(s.symbol_id)
                    merged_impacted.append(s)

            axis_notes.append(
                f'axis "{axis_label}": {len(lexical_names)} lexical match(es), '
                f"quota {_MULTI_AXIS_QUOTA_PER_AXIS}, added "
                f"{', '.join(added_paths) if added_paths else '(none, already covered)'}."
            )

        if not axis_notes:
            return result

        final_files = sorted(merged_files.values(), key=lambda ref: ref.file_path)
        selected_tokens = sum(ref.token_count for ref in final_files)
        raw_tokens = result.token_estimate.raw_context_tokens
        return result.model_copy(
            update={
                "candidate_files": final_files,
                "entry_points": merged_entry_points,
                "impacted_symbols": merged_impacted,
                "resolution_reason": (
                    f"{result.resolution_reason} Multi-axis query decomposition: "
                    f"{len(axes)} axes. {' '.join(axis_notes)}"
                ),
                "token_estimate": result.token_estimate.model_copy(
                    update={
                        "selected_context_tokens": selected_tokens,
                        "compression_ratio": (
                            round(selected_tokens / raw_tokens, 4) if raw_tokens else 0.0
                        ),
                    }
                ),
            }
        )

    @staticmethod
    def _expand_class_anchors_to_methods(names: list[str], symbol_index: SymbolIndex) -> list[str]:
        """ARCF Pre-Expansion Anchor Classification experiment (2026-08-08)
        follow-up: a Tier 1 anchor that resolves to a CLASS gets its own
        METHOD-kind children added too.

        Why: ContextResolver.resolve() only runs call-graph expansion
        (_expand_calls) for FUNCTION/METHOD-kind symbols — a CLASS-kind
        symbol goes through inheritance expansion (_expand_subclasses)
        instead (see that method's own kind branching). So a class-level
        Tier 1 anchor's own methods' real call edges are never explored
        at all unless the methods themselves are also seeded. Verified
        against the real SQLAlchemy case, not assumed: SQLAlchemy's
        `_LazyLoader` class (orm/strategies.py) has a method that calls
        `loading._load_on_pk_identity` — a real, direct edge into
        orm/loading.py — invisible to class-only expansion, since the
        class itself never triggers _expand_calls.

        Every added name is a real symbol read directly off the already-
        built SymbolIndex (a class's own `parent_id`-linked children) —
        never a guess, same "every name this module returns is real"
        standard the rest of this experiment holds itself to.

        Ambiguity-gated (`_CLASS_METHOD_AMBIGUITY_CAP`): a method's bare
        NAME must not itself match more than a handful of real symbols
        repo-wide before it's added — ContextResolver resolves by name
        only, with no class-scoping, so an unguarded `__init__` (shared
        by nearly every class) matched 268 unrelated files on the real
        SQLAlchemy run, a severe regression found empirically and fixed
        by reusing the exact same ambiguity threshold two other probes
        in this codebase already rely on."""
        expanded = list(names)
        seen = set(names)
        for name in names:
            for symbol in symbol_index.find_by_name(name):
                if symbol.kind is not SymbolKind.CLASS:
                    continue
                for candidate in symbol_index.by_file(symbol.file_path):
                    if (
                        candidate.kind is SymbolKind.METHOD
                        and candidate.parent_id == symbol.id
                        and candidate.name not in seen
                        and len(symbol_index.find_by_name(candidate.name))
                        <= _CLASS_METHOD_AMBIGUITY_CAP
                    ):
                        seen.add(candidate.name)
                        expanded.append(candidate.name)
        return expanded

    @staticmethod
    def _empty_resolution(resolved_root: str, contract_id: str) -> ContextResolutionResult:
        """Base result for a workspace with zero analyzable files — no
        registered LanguageAnalyzer can index anything here, so there is
        nothing for ContextResolver to run. Evidence-contract matching
        (this method's caller) still runs against it below, since that
        only needs the scan, not a parsed index."""
        return ContextResolutionResult(
            workspace_id=resolved_root,
            contract_id=contract_id,
            repository_root=resolved_root,
            language="unknown",
            confidence=0.0,
            token_estimate=TokenEstimate(
                raw_context_tokens=0, selected_context_tokens=0, compression_ratio=0.0
            ),
            resolution_reason=(
                "No target names resolved; no file in this workspace could be analyzed."
            ),
        )

    @staticmethod
    def _scan_candidates_for_unsupported_conditions(
        root_path: Path, candidate_files: list[FileReference]
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Best-effort generated-code / dynamic-dispatch detection (ARCF
        hardening §13), scoped to the already-selected candidate set
        rather than the whole repository — bounded cost, and these flags
        only matter for files that would actually reach the final LLM."""
        permissions = PermissionManager(root_path)
        generated: list[str] = []
        dynamic_dispatch: list[str] = []
        for file_ref in candidate_files:
            if is_generated_file(file_ref.file_path):
                generated.append(file_ref.file_path)
                continue
            try:
                content = permissions.safe_read_text(file_ref.file_path)
            except (OSError, WorkspacePathError):
                continue
            if is_generated_file(file_ref.file_path, content):
                generated.append(file_ref.file_path)
            if has_dynamic_dispatch_hint(content):
                dynamic_dispatch.append(file_ref.file_path)
        return tuple(generated), tuple(dynamic_dispatch)

    def _log_retrieval_diagnostics(
        self, latest: LivingContract, result: ContextResolutionResult
    ) -> None:
        if not _logger.isEnabledFor(logging.DEBUG):
            return
        classification = self._scope_classifier.classify(latest.contract.intent.raw_request)
        frameworks: list[str] = []
        if latest.contract.workspace_metadata is not None:
            frameworks = [match.name for match in latest.contract.workspace_metadata.frameworks]
        _logger.debug(
            json.dumps(
                {
                    "contract_id": str(latest.contract_id),
                    "task_type": classification.task_type,
                    "repository_scope": classification.repository_scope,
                    "evidence_contract": (
                        classification.task_type if classification.repository_scope else None
                    ),
                    "detected_language": result.language,
                    "detected_frameworks": frameworks,
                    "candidate_files": len(result.candidate_files),
                }
            )
        )
