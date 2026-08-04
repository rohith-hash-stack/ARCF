"""CodeIntelligenceContractService — proves the ARCF v2.3 retrieval-
context stabilization patch end to end: a repository-scoped request
with no named symbols (so target_names is empty and symbol-based
resolution alone would return zero candidate_files, exactly the
regression this patch fixes) still reaches attach_code_intelligence
with a non-empty, evidence-backed candidate_files list.
"""

import json
import logging
from pathlib import Path

import pytest

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from domain.contract import Contract
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator


def _write(tmp_path: Path, relative_path: str, content: str) -> None:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _service() -> tuple[CodeIntelligenceContractService, InMemoryContractStore]:
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )
    return service, contract_store


def _seed_contract(contract_store: InMemoryContractStore, raw_request: str) -> LivingContract:
    intent = UserIntent(
        raw_request=raw_request,
        intent="document the repository",
        domain="documentation",
        task="documentation",
        entities=[],
        confidence=0.9,
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)
    return living


async def test_repository_scoped_request_with_no_entities_still_gets_files(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "package.json", '{"name": "demo"}')
    _write(tmp_path, "tests/test_app.py", "def test_ok():\n    assert True\n")
    _write(tmp_path, "README.md", "# Demo\n")

    service, contract_store = _service()
    living = _seed_contract(
        contract_store,
        "Generate clear documentation for this repository's test suite, including setup, "
        "execution, and contribution guidelines.",
    )

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    assert len(resolution.candidate_files) > 0
    assert all(ref.reason.startswith("evidence: ") for ref in resolution.candidate_files)


async def test_non_repository_scoped_request_with_no_entities_stays_empty(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "package.json", '{"name": "demo"}')

    service, contract_store = _service()
    living = _seed_contract(contract_store, "Fix the off-by-one error somewhere")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    assert resolution.candidate_files == []


async def test_symbol_resolved_request_is_not_touched_by_fallback(tmp_path: Path) -> None:
    _write(tmp_path, "auth.py", "def authenticate(user):\n    return True\n")
    _write(tmp_path, "package.json", '{"name": "demo"}')

    service, contract_store = _service()
    living = _seed_contract(
        contract_store, "Explain this repository's authenticate() function"
    )

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=["authenticate"], workspace_root=str(tmp_path)
    )

    assert [ref.file_path for ref in resolution.candidate_files] == ["auth.py"]
    assert resolution.candidate_files[0].reason == "defines authenticate"


async def test_repository_debugging_query_with_no_entities_still_gets_files(
    tmp_path: Path,
) -> None:
    """The exact regression from the repository debugging routing fix
    brief: 'I'm seeing a failing test in this repo. Help me diagnose the
    likely cause and suggest the first places to inspect.' names no
    symbol SLM-1 could extract as an entity, so target_names is empty —
    proving candidate_files still ends up non-empty via the
    repository_debugging evidence contract, not the documentation one."""
    _write(tmp_path, "pytest.ini", "[pytest]\n")
    _write(tmp_path, "tests/test_checkout.py", "def test_checkout():\n    assert False\n")
    _write(tmp_path, "package.json", '{"name": "demo"}')

    service, contract_store = _service()
    living = _seed_contract(
        contract_store,
        "I'm seeing a failing test in this repo. Help me diagnose the likely cause and "
        "suggest the first places to inspect.",
    )

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    assert len(resolution.candidate_files) > 0
    file_paths = {ref.file_path for ref in resolution.candidate_files}
    assert "pytest.ini" in file_paths
    assert "tests/test_checkout.py" in file_paths


async def test_repository_debugging_prioritizes_query_referenced_file(tmp_path: Path) -> None:
    _write(tmp_path, "pytest.ini", "[pytest]\n")
    _write(tmp_path, "tests/test_checkout.py", "def test_checkout():\n    assert False\n")

    service, contract_store = _service()
    living = _seed_contract(
        contract_store,
        "Investigate why this test is failing: tests/test_checkout.py",
    )

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    referenced = next(
        ref for ref in resolution.candidate_files if ref.file_path == "tests/test_checkout.py"
    )
    assert referenced.reason == "references: query-referenced"


async def test_diagnostic_log_line_emitted_at_debug_level(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Change 6: routing diagnostics go to the dedicated "arcf.retrieval"
    logger at DEBUG level only — never part of the returned resolution
    or any API response, so this test reads pytest's log capture, not
    the method's return value."""
    _write(tmp_path, "pytest.ini", "[pytest]\n")
    _write(tmp_path, "tests/test_checkout.py", "def test_checkout():\n    assert False\n")

    service, contract_store = _service()
    living = _seed_contract(
        contract_store, "I'm seeing a failing test in this repo, help me diagnose it"
    )

    with caplog.at_level(logging.DEBUG, logger="arcf.retrieval"):
        await service.attach_code_intelligence(
            living.contract_id, target_names=[], workspace_root=str(tmp_path)
        )

    records = [r for r in caplog.records if r.name == "arcf.retrieval"]
    assert len(records) == 1
    payload = json.loads(records[0].getMessage())
    assert payload["task_type"] == "repository_debugging"
    assert payload["repository_scope"] is True
    assert payload["evidence_contract"] == "repository_debugging"
    assert payload["candidate_files"] > 0
