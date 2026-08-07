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


def _write_call_chain_fixture(tmp_path: Path) -> None:
    # controller.py::handle_login -> service.py::login -> repository.py::authenticate
    (tmp_path / "repository.py").write_text("def authenticate(user):\n    return True\n")
    (tmp_path / "service.py").write_text(
        "from .repository import authenticate\n\ndef login(user):\n    return authenticate(user)\n"
    )
    (tmp_path / "controller.py").write_text(
        "from .service import login\n\ndef handle_login(user):\n    return login(user)\n"
    )


def test_traversal_depth_one_stops_at_direct_caller(tmp_path: Path) -> None:
    _write_call_chain_fixture(tmp_path)
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "contract1", str(tmp_path), ["authenticate"], traversal_depth=1
    )

    assert {f.file_path for f in result.candidate_files} == {"repository.py", "service.py"}
    assert result.retrieval_depth_used == 1


def test_traversal_depth_three_reaches_full_chain(tmp_path: Path) -> None:
    _write_call_chain_fixture(tmp_path)
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "contract1", str(tmp_path), ["authenticate"], traversal_depth=3
    )

    assert {f.file_path for f in result.candidate_files} == {
        "repository.py",
        "service.py",
        "controller.py",
    }
    assert result.retrieval_depth_used == 2


def test_unbounded_traversal_reaches_the_same_full_chain(tmp_path: Path) -> None:
    _write_call_chain_fixture(tmp_path)
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "contract1", str(tmp_path), ["authenticate"], traversal_depth=None
    )

    assert {f.file_path for f in result.candidate_files} == {
        "repository.py",
        "service.py",
        "controller.py",
    }


def test_justification_chain_records_the_hop_by_hop_path(tmp_path: Path) -> None:
    _write_call_chain_fixture(tmp_path)
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "contract1", str(tmp_path), ["authenticate"], traversal_depth=3
    )

    controller_ref = next(f for f in result.candidate_files if f.file_path == "controller.py")
    assert controller_ref.justification_chain == (
        "defines authenticate",
        "called by login",
        "called by handle_login",
    )


def test_unbounded_traversal_respects_max_expansion_tokens(tmp_path: Path) -> None:
    _write_call_chain_fixture(tmp_path)
    index = _build_index(tmp_path)
    tiny_budget = index.token_counts["repository.py"] + index.token_counts["service.py"]
    result = ContextResolver(index).resolve(
        "ws1",
        "contract1",
        str(tmp_path),
        ["authenticate"],
        traversal_depth=None,
        max_expansion_tokens=tiny_budget,
    )

    assert "controller.py" not in {f.file_path for f in result.candidate_files}


def test_ambiguous_target_name_flagged_without_locality_context(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "b.py").write_text("def helper():\n    return 2\n")
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve("ws1", "contract1", str(tmp_path), ["helper"])

    assert result.ambiguous_targets == ("helper",)
    # Still fans out to every same-named candidate — disambiguation
    # narrows to a preferred symbol when possible, it never drops matches.
    assert {f.file_path for f in result.candidate_files} == {"a.py", "b.py"}


def test_ambiguous_target_name_narrowed_by_prior_target_context(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "b.py").write_text("def helper():\n    return 2\n\nclass Marker:\n    pass\n")
    index = _build_index(tmp_path)
    # "Marker" only exists in b.py, so by the time "helper" is resolved,
    # b.py is already in the candidate set (exact-file locality score)
    # and should win over a.py's same-named function.
    result = ContextResolver(index).resolve(
        "ws1", "contract1", str(tmp_path), ["Marker", "helper"]
    )

    assert result.ambiguous_targets == ()
    assert "b.py" in {f.file_path for f in result.candidate_files}


def test_wildly_ambiguous_target_name_skips_expansion_but_keeps_all_files(
    tmp_path: Path,
) -> None:
    """Real crash repro (2026-08-07): a target name tied across dozens of
    unrelated same-named symbols in a large monorepo (e.g. a hyper-common
    identifier recurring in many unrelated files) previously spawned one
    independent call-graph traversal per match, which alone caused a
    MemoryError on a real 59k-symbol repository. Every matching file
    should still be recorded (never silently dropped) — only the
    expensive per-symbol expansion is skipped once the tie count crosses
    _MAX_CANDIDATES_TO_EXPAND."""
    for i in range(6):
        (tmp_path / f"h{i}.py").write_text(f"def helper():\n    return {i}\n")
    (tmp_path / "caller.py").write_text("import h0\n\ndef use():\n    return h0.helper()\n")
    index = _build_index(tmp_path)

    result = ContextResolver(index).resolve("ws1", "contract1", str(tmp_path), ["helper"])

    file_paths = {f.file_path for f in result.candidate_files}
    assert file_paths == {f"h{i}.py" for i in range(6)}
    assert "caller.py" not in file_paths
    assert all(f.reason == "defines helper" for f in result.candidate_files)
    assert result.ambiguous_targets == ("helper",)


def test_selected_method_pulls_in_its_class_constructor(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text(
        "class AuthService:\n"
        "    def __init__(self, db):\n"
        "        self.db = db\n\n"
        "    def authenticate(self, user):\n"
        "        return self.db.check(user)\n"
    )
    (tmp_path / "caller.py").write_text(
        "from .service import AuthService\n\n"
        "def handle(service):\n"
        "    return service.authenticate('bob')\n"
    )
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "contract1", str(tmp_path), ["authenticate"]
    )

    impacted_names = {s.name for s in result.impacted_symbols}
    assert "__init__" in impacted_names
    constructor = next(s for s in result.impacted_symbols if s.name == "__init__")
    assert constructor.file_path == "service.py"


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
