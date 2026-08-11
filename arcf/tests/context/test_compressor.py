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


def _class_symbol(file_path: str, start: int) -> SymbolReference:
    return SymbolReference(
        symbol_id=f"{file_path}::Cls#{start}",
        name="Cls",
        qualified_name="Cls",
        kind=SymbolKind.CLASS,
        file_path=file_path,
        start_line=start,
        end_line=start + 20,
    )


def test_ast_scope_includes_leading_import_header(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "import os\n"
        "from pkg import thing\n\n"
        + "\n".join(f"line {i}" for i in range(4, 30))
        + "\n"
    )
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path))

    excerpt = compressor.extract_with_ast_scope("a.py", [_symbol("a.py", 20, 20)])

    assert "import os" in excerpt
    assert "from pkg import thing" in excerpt


def test_ast_scope_uses_five_line_margin_not_default_two(tmp_path: Path) -> None:
    _make_file(tmp_path, "a.py", 30)
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path), margin_lines=2)

    excerpt = compressor.extract_with_ast_scope("a.py", [_symbol("a.py", 15, 15)])

    assert "line 10" in excerpt  # 15 - 5
    assert "line 20" in excerpt  # 15 + 5
    assert "line 9" not in excerpt


def test_ast_scope_includes_only_class_declaration_line_not_full_body(tmp_path: Path) -> None:
    _make_file(tmp_path, "a.py", 40)
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path))

    excerpt = compressor.extract_with_ast_scope(
        "a.py", [_class_symbol("a.py", 5), _symbol("a.py", 25, 26)]
    )

    assert "line 5" in excerpt  # class declaration line
    assert "line 15" not in excerpt  # inside the class body but not near the method -- omitted
    assert "line 20" in excerpt  # within the method's 5-line margin (25 - 5)


def test_ast_scope_omits_unreferenced_sibling_content(tmp_path: Path) -> None:
    _make_file(tmp_path, "a.py", 50)
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path))

    excerpt = compressor.extract_with_ast_scope("a.py", [_symbol("a.py", 40, 41)])

    assert "line 10" not in excerpt
    assert "line 46" in excerpt


def test_ast_scope_no_symbols_returns_empty_string(tmp_path: Path) -> None:
    _make_file(tmp_path, "a.py", 5)
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path))
    assert compressor.extract_with_ast_scope("a.py", []) == ""


def test_ast_scope_header_trims_dangling_go_import_opener(tmp_path: Path) -> None:
    # Real Consul regression (2026-08-11, measure_realtime_pipeline.py):
    # Go's `import (` block syntax means none of the individual quoted
    # import paths on the lines after it match the header pattern, so
    # the scan always used to stop right at the bare opener -- a line
    # with zero real content that still cost tokens. Trimmed back to the
    # last genuinely meaningful line instead.
    (tmp_path / "a.go").write_text(
        "package foo\n\nimport (\n\t\"fmt\"\n)\n\n"
        + "\n".join(f"line {i}" for i in range(7, 30))
        + "\n"
    )
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path))

    excerpt = compressor.extract_with_ast_scope("a.go", [_symbol("a.go", 20, 20)])

    assert "package foo" in excerpt
    assert "import (" not in excerpt


def test_ast_scope_header_ignores_trailing_blank_run(tmp_path: Path) -> None:
    lines = ["# a real header comment", ""] + [""] * 10 + [f"line {i}" for i in range(13, 30)]
    (tmp_path / "a.py").write_text("\n".join(lines) + "\n")
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path))

    header_end = compressor._header_end_line(lines)

    assert header_end == 1
