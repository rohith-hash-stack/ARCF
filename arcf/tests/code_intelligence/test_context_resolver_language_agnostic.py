"""Testing requirement #2 from the Context Resolution Contract
refinement: a second, completely different LanguageAnalyzer (the
regex-based toy language, not tree-sitter) produces the exact same
ContextResolutionResult shape as PythonLanguageAnalyzer — proving
ContextResolver (and the contract itself) is language-agnostic, not
just "happens to work for Python."
"""

from pathlib import Path

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.registry import LanguageRegistry
from domain.code_intelligence import SymbolKind
from domain.context_resolution import ContextResolutionResult
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner

from .toy_language_analyzer import ToyLanguageAnalyzer


def test_toy_language_produces_identical_contract_shape(tmp_path: Path) -> None:
    (tmp_path / "auth.toy").write_text("func authenticate\nfunc check calls authenticate\n")
    engine = CodeIntelligenceEngine(LanguageRegistry([ToyLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(tmp_path)
    index = engine.build_index(tmp_path, scan.files)

    result = ContextResolver(index).resolve("ws1", "contract1", str(tmp_path), ["authenticate"])

    assert isinstance(result, ContextResolutionResult)
    assert result.language == "toy"
    assert {f.file_path for f in result.candidate_files} == {"auth.toy"}
    assert result.entry_points[0].kind is SymbolKind.FUNCTION
    assert result.confidence == 1.0
    assert result.token_estimate.raw_context_tokens > 0


def test_toy_language_inheritance_produces_identical_shape(tmp_path: Path) -> None:
    (tmp_path / "pages.toy").write_text("class BasePage\nclass LoginPage extends BasePage\n")
    engine = CodeIntelligenceEngine(LanguageRegistry([ToyLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(tmp_path)
    index = engine.build_index(tmp_path, scan.files)

    result = ContextResolver(index).resolve("ws1", "contract1", str(tmp_path), ["BasePage"])

    assert result.entry_points[0].kind is SymbolKind.CLASS
    assert any(s.name == "LoginPage" for s in result.impacted_symbols)


def test_python_and_toy_results_are_structurally_identical(tmp_path: Path) -> None:
    """Same shape, same field types, regardless of which analyzer produced
    the underlying index — the whole point of the contract."""
    from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer

    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    py_engine = CodeIntelligenceEngine(
        LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator()
    )
    py_index = py_engine.build_index(tmp_path, RepositoryScanner().scan(tmp_path).files)
    py_result = ContextResolver(py_index).resolve("ws1", "c1", str(tmp_path), ["authenticate"])

    toy_dir = tmp_path / "toy_project"
    toy_dir.mkdir()
    (toy_dir / "auth.toy").write_text("func authenticate\n")
    toy_engine = CodeIntelligenceEngine(LanguageRegistry([ToyLanguageAnalyzer()]), CostEstimator())
    toy_index = toy_engine.build_index(toy_dir, RepositoryScanner().scan(toy_dir).files)
    toy_result = ContextResolver(toy_index).resolve("ws2", "c2", str(toy_dir), ["authenticate"])

    assert type(py_result) is type(toy_result)
    assert set(type(py_result).model_fields) == set(type(toy_result).model_fields)
    assert type(py_result.entry_points[0]) is type(toy_result.entry_points[0])
