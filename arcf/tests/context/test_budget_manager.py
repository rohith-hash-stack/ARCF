from pathlib import Path

from context.budget_manager import ContextBudgetManager
from context.compressor import SymbolRangeCompressor
from context.relevance_ranker import RankedFile
from domain.code_intelligence import SymbolKind
from domain.context_resolution import (
    ContextResolutionResult,
    SymbolReference,
    TokenEstimate,
)
from infrastructure.cost import CostEstimator
from workspace.permissions import PermissionManager


def _ranked(file_path: str, token_count: int, score: float = 0.9) -> RankedFile:
    return RankedFile(
        file_path=file_path,
        relevance_score=score,
        reason="defines foo",
        language="python",
        token_count=token_count,
    )


def _symbol(file_path: str, start: int, end: int) -> SymbolReference:
    return SymbolReference(
        symbol_id=f"{file_path}::foo",
        name="foo",
        qualified_name="foo",
        kind=SymbolKind.FUNCTION,
        file_path=file_path,
        start_line=start,
        end_line=end,
    )


def _empty_result(entry_points: list[SymbolReference] | None = None) -> ContextResolutionResult:
    return ContextResolutionResult(
        workspace_id="ws",
        contract_id="c1",
        repository_root="/repo",
        language="python",
        entry_points=entry_points or [],
        confidence=1.0,
        token_estimate=TokenEstimate(
            raw_context_tokens=0, selected_context_tokens=0, compression_ratio=0.0
        ),
        resolution_reason="test",
    )


def _manager(tmp_path: Path) -> ContextBudgetManager:
    permissions = PermissionManager(tmp_path)
    return ContextBudgetManager(permissions, CostEstimator(), SymbolRangeCompressor(permissions))


def test_includes_files_that_fit_in_full(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def foo():\n    pass\n")
    manager = _manager(tmp_path)
    ranked = [_ranked("a.py", token_count=10)]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=1000)

    assert len(packaged) == 1
    assert packaged[0].truncated is False
    assert used == 10
    assert excluded == 0


def test_compresses_file_that_does_not_fit_in_full(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("\n".join(f"line {i}" for i in range(1, 200)) + "\n")
    manager = _manager(tmp_path)
    ranked = [_ranked("a.py", token_count=100_000)]  # far larger than the real file's tokens
    result = _empty_result(entry_points=[_symbol("a.py", 50, 52)])

    packaged, used, excluded = manager.select(ranked, result, max_tokens=200)

    assert len(packaged) == 1
    assert packaged[0].truncated is True
    assert "line 50" in packaged[0].content
    assert excluded == 0


def test_excludes_file_with_no_symbols_when_it_does_not_fit(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    manager = _manager(tmp_path)
    ranked = [_ranked("a.py", token_count=100_000)]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=200)

    assert packaged == []
    assert used == 0
    assert excluded == 1


def test_stops_once_budget_exhausted(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def a(): pass\n")
    (tmp_path / "b.py").write_text("def b(): pass\n")
    manager = _manager(tmp_path)
    ranked = [_ranked("a.py", token_count=10), _ranked("b.py", token_count=10)]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=10)

    assert [p.file_path for p in packaged] == ["a.py"]
    assert excluded == 1


def test_compressed_excerpt_includes_a_constructor_symbol_added_by_context_resolver(
    tmp_path: Path,
) -> None:
    # Mirrors what ContextResolver._enrich_with_constructors now does: the
    # constructor symbol (near the top of the file) rides along in
    # impacted_symbols alongside the selected method far below it — the
    # compressor should pick up both ranges, proving the excerpt isn't
    # severed from its class's initialization context.
    lines = ["class AuthService:", "    def __init__(self, db):", "        self.db = db", ""]
    lines += [f"    # padding {i}" for i in range(1, 60)]
    lines += ["    def authenticate(self, user):", "        return self.db.check(user)"]
    (tmp_path / "service.py").write_text("\n".join(lines) + "\n")

    manager = _manager(tmp_path)
    ranked = [_ranked("service.py", token_count=100_000)]
    method_symbol = SymbolReference(
        symbol_id="service.py::authenticate",
        name="authenticate",
        qualified_name="AuthService.authenticate",
        kind=SymbolKind.METHOD,
        file_path="service.py",
        start_line=len(lines) - 1,
        end_line=len(lines),
        parent_symbol_id="service.py::AuthService",
    )
    constructor_symbol = SymbolReference(
        symbol_id="service.py::__init__",
        name="__init__",
        qualified_name="AuthService.__init__",
        kind=SymbolKind.METHOD,
        file_path="service.py",
        start_line=2,
        end_line=3,
        parent_symbol_id="service.py::AuthService",
    )
    result = _empty_result(entry_points=[method_symbol]).model_copy(
        update={"impacted_symbols": [constructor_symbol]}
    )

    packaged, _, _ = manager.select(ranked, result, max_tokens=1000)

    assert len(packaged) == 1
    assert packaged[0].truncated is True
    assert "def __init__" in packaged[0].content
    assert "def authenticate" in packaged[0].content


def test_deleted_file_between_resolution_and_packaging_is_excluded_not_fatal(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    ranked = [_ranked("gone.py", token_count=10)]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=1000)

    assert packaged == []
    assert used == 0
    assert excluded == 1
