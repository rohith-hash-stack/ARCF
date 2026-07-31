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


def test_deleted_file_between_resolution_and_packaging_is_excluded_not_fatal(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    ranked = [_ranked("gone.py", token_count=10)]

    packaged, used, excluded = manager.select(ranked, _empty_result(), max_tokens=1000)

    assert packaged == []
    assert used == 0
    assert excluded == 1
