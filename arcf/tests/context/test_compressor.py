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


def _method_symbol(file_path: str, start: int, end: int, kind: SymbolKind = SymbolKind.FUNCTION) -> SymbolReference:
    return SymbolReference(
        symbol_id=f"{file_path}::fn#{start}",
        name="fn",
        qualified_name="fn",
        kind=kind,
        file_path=file_path,
        start_line=start,
        end_line=end,
    )


def test_skeleton_strips_single_line_go_signature_body(tmp_path: Path) -> None:
    source = (
        "package foo\n\n"
        "func Register(name string) error {\n"
        "\tif name == \"\" {\n"
        "\t\treturn errors.New(\"empty\")\n"
        "\t}\n"
        "\treturn store.Save(name)\n"
        "}\n"
    )
    (tmp_path / "a.go").write_text(source)
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path))

    excerpt = compressor.extract_skeleton_only("a.go", [_method_symbol("a.go", 3, 7)])

    assert "func Register(name string) error {" in excerpt
    assert "implementation omitted" in excerpt
    assert "errors.New" not in excerpt
    assert "store.Save" not in excerpt


def test_skeleton_strips_multiline_python_signature_body(tmp_path: Path) -> None:
    source = (
        "def handle(\n"
        "    request,\n"
        "    context,\n"
        "):\n"
        "    validate(request)\n"
        "    return context.respond(request)\n"
    )
    (tmp_path / "a.py").write_text(source)
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path))

    excerpt = compressor.extract_skeleton_only("a.py", [_method_symbol("a.py", 1, 6)])

    assert "def handle(" in excerpt
    assert "context,\n" in excerpt or "context," in excerpt  # multi-line signature kept
    assert "):" in excerpt
    assert "implementation omitted" in excerpt
    assert "validate(request)" not in excerpt


def test_skeleton_keeps_class_declaration_line_only(tmp_path: Path) -> None:
    source = (
        "class Widget:\n"
        "    def method(self):\n"
        "        do_real_work()\n"
        "        return 1\n"
    )
    (tmp_path / "a.py").write_text(source)
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path))
    class_symbol = SymbolReference(
        symbol_id="a.py::Widget",
        name="Widget",
        qualified_name="Widget",
        kind=SymbolKind.CLASS,
        file_path="a.py",
        start_line=1,
        end_line=4,
    )

    excerpt = compressor.extract_skeleton_only(
        "a.py", [class_symbol, _method_symbol("a.py", 2, 4, kind=SymbolKind.METHOD)]
    )

    assert "class Widget:" in excerpt
    assert "def method(self):" in excerpt
    assert "implementation omitted" in excerpt
    assert "do_real_work" not in excerpt


def test_skeleton_falls_back_to_omitting_nothing_when_no_boundary_found(tmp_path: Path) -> None:
    # Pathological input with no `{` and no line ending in `:` --
    # _find_body_start_line can't locate a boundary, so it under-omits
    # (keeps everything) rather than guessing wrong.
    (tmp_path / "a.txt").write_text("weird_declaration(a, b)\nsome content\nmore content\n")
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path))

    excerpt = compressor.extract_skeleton_only("a.txt", [_method_symbol("a.txt", 1, 3)])

    assert "implementation omitted" not in excerpt
    assert "some content" in excerpt


def test_skeleton_no_symbols_returns_empty_string(tmp_path: Path) -> None:
    _make_file(tmp_path, "a.py", 5)
    compressor = SymbolRangeCompressor(PermissionManager(tmp_path))
    assert compressor.extract_skeleton_only("a.py", []) == ""


def _content(line_count: int) -> str:
    return "\n".join(f"line {i}" for i in range(1, line_count + 1)) + "\n"


def test_call_site_window_uses_default_eight_line_margin() -> None:
    excerpt = SymbolRangeCompressor.extract_call_site_window(_content(100), line_number=50)

    assert "line 42" in excerpt  # 50 - 8
    assert "line 58" in excerpt  # 50 + 8
    assert "line 41" not in excerpt
    assert "line 59" not in excerpt


def test_call_site_window_respects_custom_window_size() -> None:
    excerpt = SymbolRangeCompressor.extract_call_site_window(
        _content(100), line_number=50, window_size=3
    )

    assert "line 47" in excerpt
    assert "line 53" in excerpt
    assert "line 46" not in excerpt
    assert "line 54" not in excerpt


def test_call_site_window_clamped_to_file_start() -> None:
    excerpt = SymbolRangeCompressor.extract_call_site_window(_content(20), line_number=2)

    assert "line 1" in excerpt  # clamped, not a negative/zero line
    assert excerpt.startswith("# lines 1-")


def test_call_site_window_clamped_to_file_end() -> None:
    excerpt = SymbolRangeCompressor.extract_call_site_window(_content(20), line_number=19)

    assert "line 20" in excerpt  # clamped to the real last line
    assert "line 21" not in excerpt  # never fabricates lines past EOF


def test_call_site_window_empty_content_returns_empty_string() -> None:
    assert SymbolRangeCompressor.extract_call_site_window("", line_number=1) == ""


def test_call_site_window_line_number_below_one_returns_empty_string() -> None:
    assert SymbolRangeCompressor.extract_call_site_window(_content(10), line_number=0) == ""
    assert SymbolRangeCompressor.extract_call_site_window(_content(10), line_number=-5) == ""


def test_call_site_window_line_number_past_end_of_file_returns_empty_string() -> None:
    # A stale/mismatched line number (e.g. resolved against an older
    # version of the file) degrades to "no excerpt" rather than raising
    # an IndexError -- the caller falls back to a wider extraction.
    assert SymbolRangeCompressor.extract_call_site_window(_content(10), line_number=11) == ""
    assert SymbolRangeCompressor.extract_call_site_window(_content(10), line_number=500) == ""


def test_call_site_window_single_line_file() -> None:
    excerpt = SymbolRangeCompressor.extract_call_site_window("only line\n", line_number=1)

    assert "only line" in excerpt
    assert excerpt.startswith("# lines 1-1")
