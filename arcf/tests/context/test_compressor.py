from pathlib import Path

import pytest

from context.compressor import SymbolRangeCompressor
from domain.code_intelligence import SymbolKind
from domain.context_resolution import SymbolReference
from shared.errors import WorkspacePathError
from workspace.permissions import PermissionManager


def _symbol(file_path: str, start: int, end: int) -> SymbolReference:
    return SymbolReference(
        symbol_id=f"{file_path}::sym#{start}",
        name="sym",
        qualified_name="sym",
        kind=SymbolKind.FUNCTION,
        file_path=file_path,
        start_line=start,
        end_line=end,
    )


def _make_file(tmp_path: Path, name: str, line_count: int) -> None:
    (tmp_path / name).write_text("\n".join(f"line {i}" for i in range(1, line_count + 1)) + "\n")


def test_extracts_range_with_margin(tmp_path: Path) -> None:
    _make_file(tmp_path, "a.py", 20)
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path), margin_lines=2)

    excerpt = compressor.extract("a.py", [_symbol("a.py", 10, 12)])

    assert "line 8" in excerpt  # 10 - 2 margin
    assert "line 14" in excerpt  # 12 + 2 margin
    assert "line 7" not in excerpt
    assert "line 15" not in excerpt


def test_merges_overlapping_ranges(tmp_path: Path) -> None:
    _make_file(tmp_path, "a.py", 30)
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path), margin_lines=1)

    excerpt = compressor.extract("a.py", [_symbol("a.py", 5, 8), _symbol("a.py", 9, 12)])

    assert excerpt.count("# lines") == 1  # merged into a single contiguous block


def test_keeps_disjoint_ranges_separate(tmp_path: Path) -> None:
    _make_file(tmp_path, "a.py", 50)
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path), margin_lines=1)

    excerpt = compressor.extract("a.py", [_symbol("a.py", 5, 6), _symbol("a.py", 40, 41)])

    assert excerpt.count("# lines") == 2


def test_range_clamped_to_file_bounds(tmp_path: Path) -> None:
    _make_file(tmp_path, "a.py", 5)
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path), margin_lines=10)

    excerpt = compressor.extract("a.py", [_symbol("a.py", 1, 5)])

    assert "line 1" in excerpt
    assert "line 5" in excerpt


def test_no_symbols_returns_empty_string(tmp_path: Path) -> None:
    _make_file(tmp_path, "a.py", 5)
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path))
    assert compressor.extract("a.py", []) == ""


def test_missing_file_raises(tmp_path: Path) -> None:
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path))
    with pytest.raises((OSError, WorkspacePathError)):
        compressor.extract("does_not_exist.py", [_symbol("does_not_exist.py", 1, 2)])
