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
from pathlib import Path
from uuid import UUID, uuid4

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.language_coverage import compute_language_coverage
from code_intelligence.unsupported_conditions import has_dynamic_dispatch_hint, is_generated_file
from context.evidence_fallback import expand_with_evidence
from context.evidence_validator import validate_sufficiency
from context.lexical_symbol_probe import probe_symbol_names
from context.task_profile import TRAVERSAL_DEPTH, classify_retrieval_task
from contracts.evidence_contract import build_evidence_contract, detect_task_type_for_evidence
from contracts.repository_scope_classifier import RepositoryScopeClassifier
from contracts.task_classifier import TaskClassifier
from domain.context_resolution import ContextResolutionResult, FileReference, TokenEstimate
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import ContextResolutionStore
from infrastructure.contract_store import ContractStore
from shared.errors import ContractNotFoundError, NoWorkspaceAttachedError, WorkspacePathError
from workspace.permissions import PermissionManager
from workspace.repository_segmentation import RepositorySegmenter
from workspace.scanner import RepositoryScanner

_logger = logging.getLogger("arcf.retrieval")


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
    ) -> tuple[LivingContract, ContextResolutionResult]:
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
        self, root_path: Path, contract_id: str, target_names: list[str], raw_request: str
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
            )

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

        # Classifier-gap fix, layer 3 (§4.3 of the 2026-08-06 handoff): the
        # true last resort, only tried once symbol resolution AND
        # expand_with_evidence's own tiers have all already come back
        # empty — same "last-resort tier only" ordering constraint the
        # handoff's design established, so a query whose target_names or
        # evidence-fallback already found real matches never has those
        # additive results (e.g. a debugging query's referenced file PLUS
        # its evidence contract) suppressed by this coarser signal running
        # first. A query naming no exact symbol ("Add support for a custom
        # dependency cache invalidation strategy") still often shares a
        # lexical root with a real symbol (Dependant/Depends). Re-resolving
        # through the full pipeline (not just adding files directly) means
        # call-graph traversal, locality disambiguation, and justification
        # chains all still apply to what this finds.
        if not result.candidate_files and index is not None:
            lexical_names = probe_symbol_names(raw_request, index.symbol_index)
            if lexical_names:
                lexical_result = ContextResolver(index).resolve(
                    resolved_root,
                    contract_id,
                    resolved_root,
                    [*target_names, *lexical_names],
                    traversal_depth=traversal_depth,
                )
                if lexical_result.candidate_files:
                    shown = ", ".join(lexical_names[:5])
                    more = "..." if len(lexical_names) > 5 else ""
                    result = lexical_result.model_copy(
                        update={
                            "resolution_reason": (
                                f"{lexical_result.resolution_reason} Lexical symbol probing "
                                f"matched {len(lexical_names)} real symbol name(s) from "
                                f"the query's wording ({shown}{more})."
                            )
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
