from code_intelligence.languages.rust_analyzer import RustLanguageAnalyzer
from domain.code_intelligence import FileAnalysis, SymbolKind


def _analyze(
    source: str,
    file_path: str = "src/module.rs",
    workspace_files: frozenset[str] | None = None,
) -> FileAnalysis:
    analyzer = RustLanguageAnalyzer()
    return analyzer.analyze_file(file_path, source, workspace_files or frozenset())


def test_handles_rs_extension() -> None:
    analyzer = RustLanguageAnalyzer()
    assert analyzer.handles("a.rs") is True
    assert analyzer.handles("a.py") is False


def test_language_property() -> None:
    assert RustLanguageAnalyzer().language == "rust"


def test_extracts_top_level_function() -> None:
    result = _analyze("fn foo() {}\n")
    funcs = [s for s in result.symbols if s.kind is SymbolKind.FUNCTION]
    assert len(funcs) == 1
    assert funcs[0].name == "foo"
    assert funcs[0].qualified_name == "foo"
    assert funcs[0].parent_id is None


def test_extracts_struct_as_class() -> None:
    result = _analyze("struct Point { x: i32, y: i32 }\n")
    classes = [s for s in result.symbols if s.kind is SymbolKind.CLASS]
    assert [c.name for c in classes] == ["Point"]


def test_unit_struct_is_still_a_definition() -> None:
    result = _analyze("struct Marker;\n")
    classes = [s for s in result.symbols if s.kind is SymbolKind.CLASS]
    assert [c.name for c in classes] == ["Marker"]


def test_tuple_struct_is_still_a_definition() -> None:
    result = _analyze("struct Point(i32, i32);\n")
    classes = [s for s in result.symbols if s.kind is SymbolKind.CLASS]
    assert [c.name for c in classes] == ["Point"]


def test_extracts_enum_as_class() -> None:
    result = _analyze("enum Color { Red, Green, Blue }\n")
    classes = [s for s in result.symbols if s.kind is SymbolKind.CLASS]
    assert [c.name for c in classes] == ["Color"]


def test_extracts_trait_as_interface() -> None:
    source = "trait Shape {\n    fn area(&self) -> f64;\n}\n"
    result = _analyze(source)
    interfaces = [s for s in result.symbols if s.kind is SymbolKind.INTERFACE]
    assert [i.name for i in interfaces] == ["Shape"]
    methods = [s for s in result.symbols if s.kind is SymbolKind.METHOD]
    assert [m.name for m in methods] == ["area"]
    assert methods[0].parent_id == interfaces[0].id


def test_inherent_impl_method_resolves_parent() -> None:
    source = """struct Point { x: i32, y: i32 }

impl Point {
    fn dist(&self) -> i32 { self.x }
}
"""
    result = _analyze(source)
    point = next(s for s in result.symbols if s.name == "Point")
    dist = next(s for s in result.symbols if s.name == "dist")
    assert dist.kind is SymbolKind.METHOD
    assert dist.parent_id == point.id
    assert dist.qualified_name == "Point::dist"


def test_trait_impl_method_resolves_to_concrete_type_not_trait() -> None:
    source = """struct Point { x: i32, y: i32 }
trait Shape { fn area(&self) -> f64; }

impl Shape for Point {
    fn area(&self) -> f64 { 0.0 }
}
"""
    result = _analyze(source)
    point = next(s for s in result.symbols if s.name == "Point" and s.kind is SymbolKind.CLASS)
    areas = [s for s in result.symbols if s.name == "area"]
    impl_area = next(s for s in areas if s.parent_id == point.id)
    assert impl_area.qualified_name == "Point::area"


def test_mod_qualifies_free_function_name() -> None:
    source = "mod outer {\n    mod inner {\n        fn run() {}\n    }\n}\n"
    result = _analyze(source)
    run = next(s for s in result.symbols if s.name == "run")
    assert run.qualified_name == "outer::inner::run"
    assert run.parent_id is None


def test_records_plain_call() -> None:
    source = "fn b() {}\nfn a() {\n    b();\n}\n"
    result = _analyze(source)
    call = next(c for c in result.calls if c.callee_name == "b")
    caller = next(s for s in result.symbols if s.name == "a")
    assert call.caller_id == caller.id


def test_records_dot_field_call_by_simple_name() -> None:
    source = """struct Point { x: i32 }

impl Point {
    fn run(&self) { self.helper(); }
    fn helper(&self) {}
}
"""
    result = _analyze(source)
    call = next(c for c in result.calls if c.callee_name == "helper")
    run = next(s for s in result.symbols if s.name == "run")
    assert call.caller_id == run.id


def test_records_nested_call_in_arguments() -> None:
    source = "fn a() {\n    outer(inner());\n}\n"
    result = _analyze(source)
    callee_names = {c.callee_name for c in result.calls}
    assert callee_names == {"outer", "inner"}


def test_top_level_call_has_no_caller() -> None:
    result = _analyze("static X: i32 = do_something();\n")
    assert result.calls[0].caller_id is None


def test_use_of_external_crate_is_unresolved() -> None:
    result = _analyze("use std::collections::HashMap;\n")
    assert len(result.imports) == 1
    assert result.imports[0].raw_module == "std::collections::HashMap"
    assert result.imports[0].resolved_file_path is None


def test_use_as_clause_records_alias() -> None:
    result = _analyze("use foo::Bar as Baz;\n")
    assert result.imports[0].imported_names == ["Baz"]


def test_scoped_use_list_extracts_all_entries() -> None:
    result = _analyze("use std::{fmt, collections::HashMap};\n")
    raw_modules = {imp.raw_module for imp in result.imports}
    assert raw_modules == {"std::fmt", "std::collections::HashMap"}


def test_crate_relative_use_resolves_to_workspace_file() -> None:
    workspace_files = frozenset({"src/module.rs", "src/local/helper.rs"})
    result = _analyze(
        "use crate::local::helper;\n", workspace_files=workspace_files
    )
    assert result.imports[0].resolved_file_path == "src/local/helper.rs"


def test_crate_relative_use_resolves_to_mod_rs() -> None:
    workspace_files = frozenset({"src/module.rs", "src/local/mod.rs"})
    result = _analyze(
        "use crate::local;\n", workspace_files=workspace_files
    )
    assert result.imports[0].resolved_file_path == "src/local/mod.rs"


def test_syntax_error_recorded_but_partial_results_returned() -> None:
    result = _analyze("fn foo( {\n")
    assert result.parse_errors != []


def test_valid_source_has_no_parse_errors() -> None:
    result = _analyze("fn foo() {}\n")
    assert result.parse_errors == []
