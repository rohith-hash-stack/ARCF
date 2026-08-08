"""EvidenceValidator (ARCF architecture hardening §2) — deterministic
evidence-sufficiency validation.

Distinct from context/evidence_fallback.py, which only fires when
ContextResolver's candidate_files came back completely empty:
`validate_sufficiency` runs whenever a task type has a registered
evidence contract (contracts/evidence_contract.py) and checks whether
the ALREADY-resolved candidate set — however it was assembled, symbol-
based or otherwise — covers each required evidence category. Categories
already covered by a graph-driven candidate are left untouched;
categories with no coverage are expanded via the same deterministic
glob-matching primitive evidence_fallback.py already uses
(`contracts.evidence_contract.match_evidence`), never an LLM call.

The final LLM should never receive an incomplete evidence package when
deterministic expansion can close the gap — but a category that
genuinely has no matching file in the repository (e.g. no CI workflow
exists at all) stays honestly reported as missing rather than
fabricated.
"""

from dataclasses import dataclass
from pathlib import Path

from context.lexical_symbol_probe import shares_lexical_root
from contracts.evidence_contract import EvidenceCategory, category_matches, match_evidence
from domain.context_resolution import ContextResolutionResult, EvidenceTier, FileReference
from infrastructure.cost import CostEstimator
from shared.errors import WorkspacePathError
from workspace.permissions import PermissionManager
from workspace.repository_segmentation import ROOT_SEGMENT, RepositorySegmenter
from workspace.scanner import ScannedFile

_TOKEN_ESTIMATE_MODEL = "gpt-4o-mini"
_READ_ERRORS: tuple[type[Exception], ...] = (OSError, WorkspacePathError)


@dataclass(frozen=True)
class EvidenceSufficiencyReport:
    satisfied: tuple[str, ...]
    missing: tuple[str, ...]


def validate_sufficiency(
    result: ContextResolutionResult,
    contract: tuple[EvidenceCategory, ...],
    files: list[ScannedFile],
    workspace_root: Path,
) -> tuple[ContextResolutionResult, EvidenceSufficiencyReport]:
    """Returns `result` (expanded if needed) plus a report of which
    evidence categories ended up satisfied vs. still missing. A no-op
    (returns `result` unchanged except for the two metadata fields) when
    `contract` is empty — most task types have no registered contract."""
    if not contract:
        return result, EvidenceSufficiencyReport(satisfied=(), missing=())

    existing_paths = [ref.file_path for ref in result.candidate_files]
    already_satisfied = [
        category.name
        for category in contract
        if any(category_matches(path, category) for path in existing_paths)
    ]
    missing_categories = [
        category for category in contract if category.name not in already_satisfied
    ]

    if not missing_categories:
        return (
            result.model_copy(
                update={
                    "evidence_categories_satisfied": tuple(already_satisfied),
                    "evidence_categories_missing": (),
                }
            ),
            EvidenceSufficiencyReport(satisfied=tuple(already_satisfied), missing=()),
        )

    permissions = PermissionManager(workspace_root)
    token_estimator = CostEstimator()

    # ARCF hardening §4 (repository boundary awareness): when the query
    # already has established candidates, scope expansion to the segment
    # they're dominantly in — a monorepo bug-fix in services/api shouldn't
    # pull in services/web's unrelated CI config. No established
    # candidates yet means no segment to scope by, so the full file list
    # is used unfiltered (same as before segmentation existed).
    segmenter = RepositorySegmenter(files)
    dominant_segment = segmenter.dominant_segment(existing_paths)
    if dominant_segment == ROOT_SEGMENT:
        scoped_files = files
    else:
        # Root-level files (shared CI/config with no closer manifest) stay
        # in scope alongside the dominant segment itself — only OTHER
        # segments are excluded.
        scoped_files = [
            file
            for file in files
            if segmenter.segment_of(file.relative_path) in (dominant_segment, ROOT_SEGMENT)
        ]
    matched = match_evidence(scoped_files, tuple(missing_categories))

    seen = set(existing_paths)
    new_refs: list[FileReference] = []
    newly_satisfied: list[str] = []
    still_missing: list[str] = []
    for category in missing_categories:
        category_added = False
        for relative_path in matched.get(category.name, []):
            if relative_path in seen:
                continue
            ref = _to_file_reference(relative_path, category.name, permissions, token_estimator)
            if ref is None:
                continue
            seen.add(relative_path)
            new_refs.append(ref)
            category_added = True
        if category_added:
            newly_satisfied.append(category.name)
        else:
            still_missing.append(category.name)

    satisfied = (*already_satisfied, *newly_satisfied)

    if not new_refs:
        return (
            result.model_copy(
                update={
                    "evidence_categories_satisfied": satisfied,
                    "evidence_categories_missing": tuple(still_missing),
                }
            ),
            EvidenceSufficiencyReport(satisfied=satisfied, missing=tuple(still_missing)),
        )

    all_candidate_files = sorted(
        [*result.candidate_files, *new_refs], key=lambda ref: ref.file_path
    )
    selected_tokens = sum(ref.token_count for ref in all_candidate_files)
    raw_tokens = result.token_estimate.raw_context_tokens
    compression_ratio = round(selected_tokens / raw_tokens, 4) if raw_tokens else 0.0

    updated = result.model_copy(
        update={
            "candidate_files": all_candidate_files,
            "token_estimate": result.token_estimate.model_copy(
                update={
                    "selected_context_tokens": selected_tokens,
                    "compression_ratio": compression_ratio,
                }
            ),
            "resolution_reason": (
                f"{result.resolution_reason} Evidence sufficiency check added "
                f"{len(new_refs)} file(s) to cover: {', '.join(newly_satisfied)}."
            ),
            "evidence_categories_satisfied": satisfied,
            "evidence_categories_missing": tuple(still_missing),
        }
    )
    return updated, EvidenceSufficiencyReport(satisfied=satisfied, missing=tuple(still_missing))


_MAX_EXPERIMENTAL_SURVIVORS = 8
"""Same order of magnitude as this codebase's other deterministic caps on
a single widening tier (_QUERY_REFERENCE_MAX_FILES, _MAX_MATCHED_FILES in
lexical_symbol_probe.py) — a relationship type surviving corroboration/
relevance in more files than this is too broad a signal to trust without
ranking, the same judgment call those existing caps already make."""


@dataclass(frozen=True)
class ExperimentalPruneReport:
    proposed: int
    """How many EvidenceTier.EXPERIMENTAL candidates were in `result`
    before pruning."""
    kept: tuple[str, ...]
    pruned: tuple[str, ...]


def prune_experimental_candidates(
    result: ContextResolutionResult,
    raw_request: str,
    max_survivors: int = _MAX_EXPERIMENTAL_SURVIVORS,
) -> tuple[ContextResolutionResult, ExperimentalPruneReport]:
    """ARCF Phase 7 spike (Language Semantic Enrichment) — the inverse of
    validate_sufficiency above: that function ADDS files to satisfy
    missing evidence-contract coverage; this one REMOVES
    EvidenceTier.EXPERIMENTAL candidates (files reached only via an LSE
    graph — e.g. context/decorator_graph.py via multi_hop_orchestrator.py
    — see domain.context_resolution.EvidenceTier's own docstring) that
    don't earn their place, before they're ever allowed to expand further
    or reach packaging. This is the piece that keeps multi-hop LSE
    traversal from repeating this session's FastAPI fan-out blowup: it
    must run BEFORE a survivor is allowed to seed another hop, not just
    filter the final candidate set after the fact.

    Stays inside ARCF's no-embeddings/no-scoring constraint — every check
    here is a real structural fact already computed elsewhere in the
    pipeline, not a new inference mechanism:

    1. Independent-relationship corroboration: does this candidate also
       sit in the same directory as an already-established
       (non-EXPERIMENTAL) candidate, or connect to one via
       `result.dependency_chain`? A file an LSE relationship alone
       reached, with nothing else connecting it to anything ARCF's
       stable pipeline already trusted, is exactly the shape of a
       spurious match. Known limitation: directory-based corroboration
       degenerates for root-level files (everything at "" trivially
       "corroborates") — acceptable for this first spike, worth scoping
       via workspace.repository_segmentation if this proves out.
    2. Query-lexical relevance (`shares_lexical_root` — the exact
       prefix-substring technique lexical_symbol_probe.py already uses
       elsewhere in ARCF, reused rather than reimplemented) against the
       candidate's `reason` string.

    A candidate surviving EITHER check is kept; surviving neither is
    pruned. Survivors are then capped at `max_survivors` (deterministic,
    sorted by file_path) — even a corroborated/relevant relationship that
    fires too broadly (a decorator used by every handler in the repo)
    isn't a precise signal for THIS query.

    Non-EXPERIMENTAL candidates (PRIMARY, SUPPORTING) are never touched —
    this function's blast radius is exactly the LSE candidates it exists
    to gate, nothing else in `result`.
    """
    experimental = [
        ref for ref in result.candidate_files if ref.evidence_tier is EvidenceTier.EXPERIMENTAL
    ]
    if not experimental:
        return result, ExperimentalPruneReport(proposed=0, kept=(), pruned=())

    established = [
        ref for ref in result.candidate_files if ref.evidence_tier is not EvidenceTier.EXPERIMENTAL
    ]
    established_dirs = {_directory_of(ref.file_path) for ref in established}
    established_paths = {ref.file_path for ref in established}
    connected_to_established = {
        edge.from_file for edge in result.dependency_chain if edge.to_file in established_paths
    } | {
        edge.to_file for edge in result.dependency_chain if edge.from_file in established_paths
    }

    survivors: list[FileReference] = []
    pruned: list[FileReference] = []
    for candidate in experimental:
        corroborated = (
            _directory_of(candidate.file_path) in established_dirs
            or candidate.file_path in connected_to_established
        )
        relevant = shares_lexical_root(candidate.reason, raw_request)
        (survivors if corroborated or relevant else pruned).append(candidate)

    if len(survivors) > max_survivors:
        survivors = sorted(survivors, key=lambda ref: ref.file_path)
        pruned.extend(survivors[max_survivors:])
        survivors = survivors[:max_survivors]

    if len(pruned) == 0:
        return (
            result,
            ExperimentalPruneReport(
                proposed=len(experimental),
                kept=tuple(sorted(ref.file_path for ref in survivors)),
                pruned=(),
            ),
        )

    final_files = sorted([*established, *survivors], key=lambda ref: ref.file_path)
    selected_tokens = sum(ref.token_count for ref in final_files)
    raw_tokens = result.token_estimate.raw_context_tokens
    compression_ratio = round(selected_tokens / raw_tokens, 4) if raw_tokens else 0.0
    pruned_paths = tuple(sorted(ref.file_path for ref in pruned))

    updated = result.model_copy(
        update={
            "candidate_files": final_files,
            "token_estimate": result.token_estimate.model_copy(
                update={
                    "selected_context_tokens": selected_tokens,
                    "compression_ratio": compression_ratio,
                }
            ),
            "resolution_reason": (
                f"{result.resolution_reason} LSE candidate pruning: "
                f"{len(experimental)} experimental candidate(s) proposed, "
                f"{len(pruned)} pruned for lacking corroboration or query "
                f"relevance."
            ),
        }
    )
    return updated, ExperimentalPruneReport(
        proposed=len(experimental),
        kept=tuple(sorted(ref.file_path for ref in survivors)),
        pruned=pruned_paths,
    )


def _directory_of(file_path: str) -> str:
    return file_path.rsplit("/", 1)[0] if "/" in file_path else ""


def _to_file_reference(
    relative_path: str,
    category_name: str,
    permissions: PermissionManager,
    token_estimator: CostEstimator,
) -> FileReference | None:
    try:
        content = permissions.safe_read_text(relative_path)
    except _READ_ERRORS:
        return None
    return FileReference(
        file_path=relative_path,
        reason=f"evidence: {category_name}",
        language="unknown",
        token_count=token_estimator.count_tokens(content, _TOKEN_ESTIMATE_MODEL),
        # Same reasoning as evidence_fallback.py's own "evidence: " tier:
        # a completeness-guarantee addition, not primary evidence.
        evidence_tier=EvidenceTier.SUPPORTING,
    )
