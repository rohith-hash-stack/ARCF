"""Workspace Contract Service — attaches a WorkspaceMetadata snapshot to
an existing LivingContract, evolving it. This is Phase 4's contribution
to the same versioning story Phase 3 established for intent extraction:
each pipeline stage produces a new contract version rather than
mutating one in place.

Enforces the workspace-root allowlist here, not in WorkspaceAnalyzer —
it's an access-policy decision about who's allowed to point ARCF at
what filesystem path, separate from the analysis itself.
"""

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

from domain.versioning import LivingContract
from infrastructure.contract_store import ContractStore
from shared.errors import ContractNotFoundError, WorkspaceNotAllowedError
from workspace.analyzer import WorkspaceAnalyzer


class WorkspaceContractService:
    def __init__(
        self,
        analyzer: WorkspaceAnalyzer,
        contract_store: ContractStore,
        allowed_roots: list[Path],
    ) -> None:
        self._analyzer = analyzer
        self._contract_store = contract_store
        self._allowed_roots = [root.resolve() for root in allowed_roots]

    def _check_allowed(self, workspace_root: Path) -> None:
        if not self._allowed_roots:
            return  # empty allowlist = unrestricted (local-dev-tool default)
        resolved = workspace_root.resolve()
        for allowed in self._allowed_roots:
            if resolved == allowed or allowed in resolved.parents:
                return
        raise WorkspaceNotAllowedError(
            f"{resolved} is not within the configured workspace allowlist"
        )

    async def attach_workspace(self, contract_id: UUID, workspace_root: str) -> LivingContract:
        root_path = Path(workspace_root)
        self._check_allowed(root_path)

        latest = await asyncio.to_thread(self._contract_store.get_latest, contract_id)
        if latest is None:
            raise ContractNotFoundError(f"No contract found with id {contract_id}")

        metadata = await asyncio.to_thread(self._analyzer.analyze, root_path)

        new_contract = latest.contract.model_copy(
            update={
                "id": uuid4(),
                "workspace_root": metadata.workspace_root,
                "workspace_metadata": metadata,
            }
        )
        evolved = latest.evolve(new_contract)
        await asyncio.to_thread(self._contract_store.save, evolved)
        return evolved
