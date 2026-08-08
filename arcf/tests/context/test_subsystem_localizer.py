from pathlib import Path

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from context.subsystem_localizer import localize_subsystems, restrict_names_to_subsystems
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner


def _build_index(tmp_path: Path) -> CodeIntelligenceIndex:
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(tmp_path)
    return engine.build_index(tmp_path, scan.files)


def _write_sqlalchemy_shaped_fixture(tmp_path: Path) -> None:
    # Mirrors the real shape closely enough to be a fair proxy: a
    # loading-strategy module under orm/, and an unrelated module under
    # dialects/ that happens to define a generically-named cache helper —
    # exactly the kind of symbol a bare lexical probe latches onto.
    (tmp_path / "orm").mkdir()
    (tmp_path / "orm" / "strategies.py").write_text(
        "class LazyLoader:\n"
        "    def load_strategy(self):\n"
        "        pass\n\n"
        "class EagerLoader:\n"
        "    def load_strategy(self):\n"
        "        pass\n"
    )
    (tmp_path / "orm" / "loading.py").write_text(
        "def load_on_ident():\n    pass\n"
    )
    (tmp_path / "dialects").mkdir()
    (tmp_path / "dialects" / "oracle.py").write_text(
        "def _generate_cache_key():\n    pass\n"
    )


def test_localize_subsystems_ranks_the_query_relevant_directory_highest(tmp_path: Path) -> None:
    _write_sqlalchemy_shaped_fixture(tmp_path)
    index = _build_index(tmp_path)

    candidates = localize_subsystems(
        "Explain how lazy loading differs from eager loading internally.",
        list(RepositoryScanner().scan(tmp_path).files),
        index.symbol_index,
    )

    assert candidates
    assert candidates[0].directory == "orm"
    assert candidates[0].confidence > 0
    assert any("LazyLoader" in line or "loading" in line for line in candidates[0].evidence)


def test_localize_subsystems_returns_empty_for_unprobeable_query(tmp_path: Path) -> None:
    _write_sqlalchemy_shaped_fixture(tmp_path)
    index = _build_index(tmp_path)

    candidates = localize_subsystems(
        "fix it",  # no word >= 6 chars, nothing to probe — mirrors
        # lexical_symbol_probe.py's own empty-prefix case
        list(RepositoryScanner().scan(tmp_path).files),
        index.symbol_index,
    )

    assert candidates == []


def test_localize_subsystems_respects_top_n(tmp_path: Path) -> None:
    _write_sqlalchemy_shaped_fixture(tmp_path)
    index = _build_index(tmp_path)

    candidates = localize_subsystems(
        "Explain how loading strategies work.",
        list(RepositoryScanner().scan(tmp_path).files),
        index.symbol_index,
        top_n=1,
    )

    assert len(candidates) <= 1


def test_restrict_names_to_subsystems_keeps_only_in_scope_symbols(tmp_path: Path) -> None:
    _write_sqlalchemy_shaped_fixture(tmp_path)
    index = _build_index(tmp_path)
    candidates = localize_subsystems(
        "Explain how lazy loading differs from eager loading internally.",
        list(RepositoryScanner().scan(tmp_path).files),
        index.symbol_index,
    )
    orm_candidate = next(c for c in candidates if c.directory == "orm")

    restricted = restrict_names_to_subsystems(
        ["load_strategy", "_generate_cache_key"], [orm_candidate], index.symbol_index
    )

    assert "load_strategy" in restricted
    assert "_generate_cache_key" not in restricted


def test_restrict_names_to_subsystems_empty_subsystems_returns_empty() -> None:
    from code_intelligence.symbol_index import SymbolIndex

    assert restrict_names_to_subsystems(["anything"], [], SymbolIndex([])) == []
