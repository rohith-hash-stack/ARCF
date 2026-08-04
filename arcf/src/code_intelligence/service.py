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
from context.evidence_fallback import expand_with_evidence
from contracts.repository_scope_classifier import RepositoryScopeClassifier
from domain.context_resolution import ContextResolutionResult
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import ContextResolutionStore
from infrastructure.contract_store import ContractStore
from shared.errors import ContractNotFoundError, NoWorkspaceAttachedError, WorkspacePathError
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

        scan = RepositoryScanner().scan(root_path)
        index = self._engine.build_index(root_path, scan.files)
        resolved_root = str(root_path.resolve())
        result = ContextResolver(index).resolve(
            resolved_root, contract_id, resolved_root, target_names
        )

        classification = self._scope_classifier.classify(raw_request)
        if classification.repository_scope:
            result = expand_with_evidence(
                result, scan.files, root_path, classification.task_type, raw_request
            )
        return result

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
