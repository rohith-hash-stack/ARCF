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
"""

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.engine import CodeIntelligenceEngine
from domain.context_resolution import ContextResolutionResult
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import ContextResolutionStore
from infrastructure.contract_store import ContractStore
from shared.errors import ContractNotFoundError, NoWorkspaceAttachedError, WorkspacePathError
from workspace.scanner import RepositoryScanner


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
            self._resolve, Path(root), str(latest.contract_id), target_names
        )
        await asyncio.to_thread(self._resolution_store.save, result)

        new_contract = latest.contract.model_copy(
            update={"id": uuid4(), "context_resolution_id": result.id}
        )
        evolved = latest.evolve(new_contract)
        await asyncio.to_thread(self._contract_store.save, evolved)
        return evolved, result

    def _resolve(
        self, root_path: Path, contract_id: str, target_names: list[str]
    ) -> ContextResolutionResult:
        if not root_path.is_dir():
            raise WorkspacePathError(f"{root_path} is not an existing directory")

        scan = RepositoryScanner().scan(root_path)
        index = self._engine.build_index(root_path, scan.files)
        resolved_root = str(root_path.resolve())
        return ContextResolver(index).resolve(
            resolved_root, contract_id, resolved_root, target_names
        )
