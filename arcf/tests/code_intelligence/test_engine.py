from pathlib import Path

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner


def _engine() -> CodeIntelligenceEngine:
    return CodeIntelligenceEngine(
        LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator()
    )


def test_build_index_from_real_files(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (tmp_path / "login.py").write_text(
        "from .auth import authenticate\n\ndef login(user):\n    return authenticate(user)\n"
    )
    scan = RepositoryScanner().scan(tmp_path)

    index = _engine().build_index(tmp_path, scan.files)

    assert len(index.symbol_index) == 2
    assert index.candidate_selector.callers_of("authenticate") == {"auth.py", "login.py"}


def test_non_source_files_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "readme.md").write_text("# hello")
    scan = RepositoryScanner().scan(tmp_path)
    index = _engine().build_index(tmp_path, scan.files)
    assert index.file_analyses == {}


def test_incremental_indexing_reuses_unchanged_file_analysis(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a():\n    pass\n")
    (tmp_path / "b.py").write_text("def b():\n    pass\n")
    scan = RepositoryScanner().scan(tmp_path)
    first = _engine().build_index(tmp_path, scan.files)

    (tmp_path / "a.py").write_text("def a():\n    pass\n\ndef a2():\n    pass\n")
    scan2 = RepositoryScanner().scan(tmp_path)
    second = _engine().build_index(tmp_path, scan2.files, previous_index=first)

    assert second.file_analyses["b.py"] is first.file_analyses["b.py"]
    assert second.file_analyses["a.py"] is not first.file_analyses["a.py"]
    assert len(second.symbol_index) == 3  # a, a2, b


def test_incremental_indexing_with_no_changes_reuses_everything(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a():\n    pass\n")
    scan = RepositoryScanner().scan(tmp_path)
    first = _engine().build_index(tmp_path, scan.files)
    second = _engine().build_index(tmp_path, scan.files, previous_index=first)

    assert second.file_analyses["a.py"] is first.file_analyses["a.py"]


def test_cross_file_inheritance_and_calls_resolved(tmp_path: Path) -> None:
    (tmp_path / "base.py").write_text("class BasePage:\n    pass\n")
    (tmp_path / "login.py").write_text(
        "from .base import BasePage\n\nclass LoginPage(BasePage):\n    pass\n"
    )
    scan = RepositoryScanner().scan(tmp_path)
    index = _engine().build_index(tmp_path, scan.files)

    assert index.candidate_selector.subclasses_of("BasePage") == {"base.py", "login.py"}
    assert index.import_graph.imports_of("login.py") == {"base.py"}


def test_token_counts_populated_per_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a():\n    pass\n")
    scan = RepositoryScanner().scan(tmp_path)
    index = _engine().build_index(tmp_path, scan.files)

    assert index.token_counts["a.py"] > 0


def test_token_counts_reused_for_unchanged_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a():\n    pass\n")
    (tmp_path / "b.py").write_text("def b():\n    pass\n")
    scan = RepositoryScanner().scan(tmp_path)
    first = _engine().build_index(tmp_path, scan.files)

    (tmp_path / "a.py").write_text("def a():\n    pass\n\ndef a2():\n    pass\n")
    scan2 = RepositoryScanner().scan(tmp_path)
    second = _engine().build_index(tmp_path, scan2.files, previous_index=first)

    assert second.token_counts["b.py"] == first.token_counts["b.py"]
    assert second.token_counts["a.py"] > first.token_counts["a.py"]
