"""Proves the language-agnostic architecture requirement directly: a
brand-new LanguageAnalyzer for a made-up ".toy" language (regex-based,
not tree-sitter) plugs into CodeIntelligenceEngine, SymbolIndex, and
every graph with ZERO changes to any file in code_intelligence/ outside
languages/ — only a new analyzer class (toy_language_analyzer.py, kept
in tests/ since it's not a real language) and a LanguageRegistry entry.

The strongest test here mixes Python and toy files in one index and
resolves a call FROM the toy language against a symbol DEFINED in
Python — that only works if the graphs operate purely on shared IR
with no per-language branching anywhere.
"""

from pathlib import Path

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner

from .toy_language_analyzer import ToyLanguageAnalyzer


def _toy_engine() -> CodeIntelligenceEngine:
    return CodeIntelligenceEngine(LanguageRegistry([ToyLanguageAnalyzer()]), CostEstimator())


def test_toy_language_symbols_indexed_like_any_other(tmp_path: Path) -> None:
    (tmp_path / "pages.toy").write_text("class BasePage\nclass LoginPage extends BasePage\n")
    scan = RepositoryScanner().scan(tmp_path)
    index = _toy_engine().build_index(tmp_path, scan.files)

    assert {s.name for s in index.symbol_index.classes()} == {"BasePage", "LoginPage"}


def test_toy_language_inheritance_answers_example_query(tmp_path: Path) -> None:
    (tmp_path / "pages.toy").write_text(
        "class BasePage\nclass LoginPage extends BasePage\nclass AdminPage extends LoginPage\n"
    )
    scan = RepositoryScanner().scan(tmp_path)
    index = _toy_engine().build_index(tmp_path, scan.files)

    assert index.candidate_selector.subclasses_of("BasePage") == {"pages.toy"}
    base = next(s for s in index.symbol_index.classes() if s.name == "BasePage")
    assert index.inheritance_graph.all_subclasses_of(base.id) == {
        "pages.toy::LoginPage",
        "pages.toy::AdminPage",
    }


def test_toy_language_call_graph_answers_example_query(tmp_path: Path) -> None:
    (tmp_path / "auth.toy").write_text("func authenticate\nfunc check calls authenticate\n")
    scan = RepositoryScanner().scan(tmp_path)
    index = _toy_engine().build_index(tmp_path, scan.files)

    assert index.candidate_selector.callers_of("authenticate") == {"auth.toy"}


def test_toy_language_import_and_dependency_graph(tmp_path: Path) -> None:
    (tmp_path / "utils.toy").write_text("func helper\n")
    (tmp_path / "app.toy").write_text("import utils.toy\nfunc main calls helper\n")
    scan = RepositoryScanner().scan(tmp_path)
    index = _toy_engine().build_index(tmp_path, scan.files)

    assert index.import_graph.imports_of("app.toy") == {"utils.toy"}
    assert index.dependency_graph.impacted_by("utils.toy") == {"app.toy"}


def test_incremental_indexing_works_for_toy_language_too(tmp_path: Path) -> None:
    (tmp_path / "a.toy").write_text("func a\n")
    scan = RepositoryScanner().scan(tmp_path)
    first = _toy_engine().build_index(tmp_path, scan.files)
    second = _toy_engine().build_index(tmp_path, scan.files, previous_index=first)

    assert second.file_analyses["a.toy"] is first.file_analyses["a.toy"]


def test_python_and_toy_symbols_coexist_and_cross_resolve(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (tmp_path / "pages.toy").write_text("func login calls authenticate\n")
    scan = RepositoryScanner().scan(tmp_path)

    engine = CodeIntelligenceEngine(
        LanguageRegistry([PythonLanguageAnalyzer(), ToyLanguageAnalyzer()]), CostEstimator()
    )
    index = engine.build_index(tmp_path, scan.files)

    # A call written in the toy language resolves against a symbol defined
    # in Python — only possible if CallGraph/ReferenceResolver/SymbolIndex
    # never branch on language, only on the shared IR.
    assert index.candidate_selector.callers_of("authenticate") == {"auth.py", "pages.toy"}
    assert {"python", "toy"} <= {a.language for a in index.file_analyses.values()}
