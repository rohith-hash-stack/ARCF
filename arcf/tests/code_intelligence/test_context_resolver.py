from pathlib import Path

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from domain.code_intelligence import SymbolKind
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner


def _build_index(tmp_path: Path) -> CodeIntelligenceIndex:
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(tmp_path)
    return engine.build_index(tmp_path, scan.files)


def test_resolves_the_example_query_caller_case(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (tmp_path / "login.py").write_text(
        "from .auth import authenticate\n\ndef login(user):\n    return authenticate(user)\n"
    )
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve("ws1", "contract1", str(tmp_path), ["authenticate"])

    assert result.workspace_id == "ws1"
    assert result.contract_id == "contract1"
    assert result.language == "python"
    assert {f.file_path for f in result.candidate_files} == {"auth.py", "login.py"}
    assert result.entry_points[0].name == "authenticate"
    assert result.entry_points[0].kind is SymbolKind.FUNCTION
    assert result.confidence == 1.0


def test_candidate_file_token_counts_match_index(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve("ws1", "contract1", str(tmp_path), ["authenticate"])

    auth_ref = next(f for f in result.candidate_files if f.file_path == "auth.py")
    assert auth_ref.token_count == index.token_counts["auth.py"]
    assert auth_ref.token_count > 0


def test_resolves_the_example_query_subclass_case(tmp_path: Path) -> None:
    (tmp_path / "base.py").write_text("class BasePage:\n    pass\n")
    (tmp_path / "login.py").write_text(
        "from .base import BasePage\n\nclass LoginPage(BasePage):\n    pass\n"
    )
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve("ws1", "contract1", str(tmp_path), ["BasePage"])

    assert {f.file_path for f in result.candidate_files} == {"base.py", "login.py"}
    assert any(s.name == "LoginPage" for s in result.impacted_symbols)


def test_partial_resolution_reflected_in_confidence(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def known():\n    pass\n")
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "contract1", str(tmp_path), ["known", "does_not_exist"]
    )
    assert result.confidence == 0.5


def test_no_target_names_yields_zero_confidence_and_empty_result(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def known():\n    pass\n")
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve("ws1", "contract1", str(tmp_path), [])

    assert result.confidence == 0.0
    assert result.candidate_files == []
    assert "No target names" in result.resolution_reason


def test_token_estimate_reflects_real_compression(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (tmp_path / "unrelated.py").write_text("def something_else():\n    " + "x = 1\n    " * 200)
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve("ws1", "contract1", str(tmp_path), ["authenticate"])

    estimate = result.token_estimate
    assert estimate.raw_context_tokens > estimate.selected_context_tokens > 0
    assert 0.0 < estimate.compression_ratio < 1.0


def test_dependency_chain_only_includes_edges_among_candidates(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (tmp_path / "login.py").write_text(
        "from .auth import authenticate\nimport os\n\n"
        "def login(user):\n    return authenticate(user)\n"
    )
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve("ws1", "contract1", str(tmp_path), ["authenticate"])

    assert any(
        edge.from_file == "login.py" and edge.to_file == "auth.py"
        for edge in result.dependency_chain
    )
    # os isn't a workspace file and isn't a candidate, so no edge references it
    assert all(edge.to_file != "os" for edge in result.dependency_chain)


def test_call_chain_includes_both_callers_and_callees(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "def helper():\n    pass\n\n"
        "def authenticate(user):\n    helper()\n    return True\n\n"
        "def login(user):\n    return authenticate(user)\n"
    )
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve("ws1", "contract1", str(tmp_path), ["authenticate"])

    callee_names = {e.callee_symbol_id.split("::")[-1] for e in result.call_chain}
    assert any("authenticate" in name for name in callee_names)
