from pathlib import Path
from uuid import uuid4

import pytest

from domain.contract import Contract
from domain.enums import ContractStatus
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.contract_store import ContractStore, InMemoryContractStore
from shared.errors import ContractNotFoundError, WorkspaceNotAllowedError
from workspace.analyzer import WorkspaceAnalyzer
from workspace.git_discovery import GitRepositoryDiscovery
from workspace.language_detection import LanguageDetector
from workspace.scanner import RepositoryScanner
from workspace.service import WorkspaceContractService
from workspace.structure_analyzer import ProjectStructureAnalyzer


def _make_living() -> LivingContract:
    intent = UserIntent(
        raw_request="fix the login bug",
        intent="fix_login_bug",
        domain="backend",
        task="bug_fix",
        confidence=0.9,
    )
    return LivingContract(contract=Contract(intent=intent), status=ContractStatus.APPROVED)


def _build_service(
    store: ContractStore, allowed_roots: list[Path] | None = None
) -> WorkspaceContractService:
    analyzer = WorkspaceAnalyzer(
        git_discovery=GitRepositoryDiscovery(),
        scanner=RepositoryScanner(),
        language_detector=LanguageDetector(),
        structure_analyzer=ProjectStructureAnalyzer(),
    )
    return WorkspaceContractService(
        analyzer=analyzer, contract_store=store, allowed_roots=allowed_roots or []
    )


async def test_attach_workspace_evolves_contract(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print(1)")
    store = InMemoryContractStore()
    living = _make_living()
    store.save(living)

    service = _build_service(store)
    evolved = await service.attach_workspace(living.contract_id, str(tmp_path))

    assert evolved.contract_id == living.contract_id
    assert evolved.version == 2
    assert evolved.contract.workspace_metadata is not None
    assert evolved.contract.workspace_root == str(tmp_path.resolve())
    assert evolved.contract.id != living.contract.id


async def test_attach_workspace_raises_for_unknown_contract(tmp_path: Path) -> None:
    store = InMemoryContractStore()
    service = _build_service(store)
    with pytest.raises(ContractNotFoundError):
        await service.attach_workspace(uuid4(), str(tmp_path))


async def test_attach_workspace_enforces_allowlist(tmp_path: Path) -> None:
    store = InMemoryContractStore()
    living = _make_living()
    store.save(living)

    other_dir = tmp_path / "elsewhere"
    other_dir.mkdir()
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()

    service = _build_service(store, allowed_roots=[allowed_dir])
    with pytest.raises(WorkspaceNotAllowedError):
        await service.attach_workspace(living.contract_id, str(other_dir))


async def test_attach_workspace_allows_path_within_allowlist(tmp_path: Path) -> None:
    store = InMemoryContractStore()
    living = _make_living()
    store.save(living)

    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    (allowed_dir / "app.py").write_text("print(1)")

    service = _build_service(store, allowed_roots=[allowed_dir])
    evolved = await service.attach_workspace(living.contract_id, str(allowed_dir))
    assert evolved.version == 2
