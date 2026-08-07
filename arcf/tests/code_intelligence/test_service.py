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


async def test_non_repository_scoped_request_recovers_via_lexical_symbol_probe(
    tmp_path: Path,
) -> None:
    """Classifier-gap fix, layer 3 (§4.3 of the 2026-08-06 handoff): a
    feature-implementation query naming no exact symbol, no repository
    noun, and no filename would previously stay empty (as
    test_non_repository_scoped_request_with_no_entities_stays_empty
    still correctly proves for a query with truly nothing to latch onto)
    — but this one's wording shares a lexical root with a real symbol,
    `Dependant`, so lexical probing should recover it via the full
    resolution pipeline, not just an evidence-fallback file dump."""
    _write(
        tmp_path,
        "deps.py",
        "class Dependant:\n    def solve(self):\n        ...\n",
    )
    _write(tmp_path, "package.json", '{"name": "demo"}')

    service, contract_store = _service()
    living = _seed_contract(
        contract_store,
        "Add support for a custom dependency cache invalidation strategy",
    )

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    assert [ref.file_path for ref in resolution.candidate_files] == ["deps.py"]
    assert resolution.candidate_files[0].reason == "defines Dependant"
    assert "Lexical symbol probing" in resolution.resolution_reason


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


async def test_retrieval_completeness_metadata_is_populated(tmp_path: Path) -> None:
    _write(tmp_path, "auth.py", "def authenticate(user):\n    return True\n")
    _write(tmp_path, "worker.go", "package main\n\nfunc main() {}\n")

    service, contract_store = _service()
    living = _seed_contract(contract_store, "Explain this repository's authenticate() function")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=["authenticate"], workspace_root=str(tmp_path)
    )

    assert resolution.files_scanned == 2
    assert resolution.files_analyzed == 1
    assert resolution.analyzer_coverage == 0.5
    assert "Python" in resolution.languages_detected
    assert "Go" in resolution.languages_unsupported
    assert resolution.repository_segment == ""


async def test_unresolved_target_name_surfaced(tmp_path: Path) -> None:
    _write(tmp_path, "auth.py", "def authenticate(user):\n    return True\n")

    service, contract_store = _service()
    living = _seed_contract(contract_store, "Explain does_not_exist()")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=["does_not_exist"], workspace_root=str(tmp_path)
    )

    assert resolution.unresolved_symbols == ("does_not_exist",)


async def test_repository_with_no_supported_language_short_circuits(tmp_path: Path) -> None:
    # Only the Python analyzer is registered (see _service()); a Ruby-only
    # repository should never reach the full parse. A request that isn't
    # repository-scoped and matches no evidence contract gets a genuinely
    # empty, honestly-explained result — nothing to fall back to.
    _write(tmp_path, "app.rb", "def hello\n  puts 'hi'\nend\n")

    service, contract_store = _service()
    living = _seed_contract(contract_store, "Rename this variable")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    assert resolution.candidate_files == []
    assert resolution.files_analyzed == 0
    assert resolution.analyzer_coverage == 0.0
    assert "Ruby" in resolution.languages_unsupported
    assert "skipped full indexing" in resolution.resolution_reason


async def test_unsupported_language_repository_still_gets_evidence_fallback(
    tmp_path: Path,
) -> None:
    # The short-circuit skips the expensive full parse, but evidence-
    # contract matching is a glob match over the scan, not a parse — a
    # repository-scoped request still gets a real, non-empty result even
    # when nothing in it can be analyzed.
    _write(tmp_path, "app.rb", "def hello\n  puts 'hi'\nend\n")

    service, contract_store = _service()
    living = _seed_contract(contract_store, "Please explain this repository")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=[], workspace_root=str(tmp_path)
    )

    assert len(resolution.candidate_files) > 0
    assert resolution.files_analyzed == 0
    assert "Ruby" in resolution.languages_unsupported


async def test_bug_fix_query_uses_shallow_traversal(tmp_path: Path) -> None:
    _write(tmp_path, "repository.py", "def authenticate(user):\n    return True\n")
    _write(
        tmp_path,
        "service.py",
        "from .repository import authenticate\n\ndef login(user):\n    return authenticate(user)\n",
    )
    _write(
        tmp_path,
        "controller.py",
        "from .service import login\n\ndef handle_login(user):\n    return login(user)\n",
    )

    service, contract_store = _service()
    living = _seed_contract(contract_store, "Fix the bug in authenticate()")

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=["authenticate"], workspace_root=str(tmp_path)
    )

    file_paths = {ref.file_path for ref in resolution.candidate_files}
    assert "controller.py" not in file_paths
    assert resolution.retrieval_depth_used <= 1


async def test_full_retrieval_completeness_metadata_end_to_end(tmp_path: Path) -> None:
    """Stage 10 completion pass (brief §11): a single, realistic
    resolution that populates every deterministic retrieval-completeness
    field this hardening effort added, proving they're wired end to end
    through CodeIntelligenceContractService — not just modeled on
    ContextResolutionResult."""
    _write(tmp_path, "package.json", '{"name": "demo"}')
    _write(tmp_path, "auth/repository.py", "def authenticate(user):\n    return True\n")
    _write(
        tmp_path,
        "auth/login_service.py",
        "import requests\n\n"
        "from .repository import authenticate\n\n"
        "def login(user):\n    return authenticate(user)\n",
    )
    _write(
        tmp_path,
        "auth/controller_pb2.py",
        "from .login_service import login\n\ndef handle_login(user):\n    return login(user)\n",
    )
    _write(
        tmp_path,
        "auth/session.py",
        "def make_session(user):\n    return getattr(user, 'id', None)\n",
    )
    _write(tmp_path, "auth/middleware.py", "def auth_middleware():\n    pass\n")
    _write(tmp_path, "config.py", "SETTING = 1\n")
    _write(tmp_path, "worker.go", "package main\n\nfunc main() {}\n")
    _write(tmp_path, "bad.py", "def broken(:\n    pass\n")

    service, contract_store = _service()
    living = _seed_contract(
        contract_store,
        "Refactor the login() authentication flow and analyze the impact across the call chain.",
    )

    _, resolution = await service.attach_code_intelligence(
        living.contract_id, target_names=["authenticate"], workspace_root=str(tmp_path)
    )

    file_paths = {ref.file_path for ref in resolution.candidate_files}

    # §1 adaptive traversal: depth-3 (refactor/impact-analysis profile)
    # reaches the renamed outermost caller two hops out.
    assert "auth/controller_pb2.py" in file_paths
    assert resolution.retrieval_depth_used >= 2

    # §2 symbol disambiguation: a single, unambiguous "authenticate"
    # resolves cleanly — correctly empty, not silently omitted.
    assert resolution.unresolved_symbols == ()
    assert resolution.ambiguous_targets == ()

    # §2/§11: evidence sufficiency — the authentication contract's
    # login/session/middleware/configuration categories are satisfied via
    # deterministic expansion (credential source legitimately stays
    # missing, since it's a sensitive-file pattern this must never read).
    assert "login implementation" in resolution.evidence_categories_satisfied
    assert "session persistence" in resolution.evidence_categories_satisfied
    assert "authentication middleware" in resolution.evidence_categories_satisfied
    assert "configuration" in resolution.evidence_categories_satisfied
    assert "credential source" in resolution.evidence_categories_missing

    # §4 repository boundary awareness: single-project repo => root segment.
    assert resolution.repository_segment == ""

    # §5/§11 language capability registry.
    assert resolution.files_scanned >= 8
    assert resolution.files_analyzed >= 1
    assert 0.0 < resolution.analyzer_coverage < 1.0
    assert "Python" in resolution.languages_detected
    assert "Go" in resolution.languages_unsupported

    # §13 unsupported-condition surfacing.
    assert "bad.py" in resolution.parse_error_files
    assert "auth/controller_pb2.py" in resolution.generated_files
    assert "auth/session.py" in resolution.dynamic_dispatch_hints
    assert "requests" in resolution.unresolved_imports
