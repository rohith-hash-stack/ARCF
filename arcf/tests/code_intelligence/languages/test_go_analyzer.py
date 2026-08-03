from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from domain.code_intelligence import FileAnalysis, SymbolKind


def _analyze(
    source: str,
    file_path: str = "app/module.go",
    workspace_files: frozenset[str] | None = None,
) -> FileAnalysis:
    analyzer = GoLanguageAnalyzer()
    return analyzer.analyze_file(file_path, source, workspace_files or frozenset())


def test_handles_go_extension() -> None:
    analyzer = GoLanguageAnalyzer()
    assert analyzer.handles("a.go") is True
    assert analyzer.handles("a.py") is False


def test_language_property() -> None:
    assert GoLanguageAnalyzer().language == "go"


def test_extracts_top_level_function() -> None:
    result = _analyze("package main\n\nfunc foo() {}\n")
    funcs = [s for s in result.symbols if s.kind is SymbolKind.FUNCTION]
    assert len(funcs) == 1
    assert funcs[0].name == "foo"
    assert funcs[0].qualified_name == "foo"
    assert funcs[0].parent_id is None


def test_extracts_struct_as_class() -> None:
    source = "package main\n\ntype BasePage struct {\n\tName string\n}\n"
    result = _analyze(source)
    classes = [s for s in result.symbols if s.kind is SymbolKind.CLASS]
    assert [c.name for c in classes] == ["BasePage"]


def test_extracts_interface() -> None:
    source = "package main\n\ntype Shape interface {\n\tArea() float64\n}\n"
    result = _analyze(source)
    interfaces = [s for s in result.symbols if s.kind is SymbolKind.INTERFACE]
    assert [i.name for i in interfaces] == ["Shape"]
    methods = [s for s in result.symbols if s.kind is SymbolKind.METHOD]
    assert [m.name for m in methods] == ["Area"]
    assert methods[0].parent_id == interfaces[0].id


def test_embedded_struct_field_is_a_base_name() -> None:
    source = """package main

type BasePage struct {
	Name string
}

type LoginPage struct {
	BasePage
}
"""
    result = _analyze(source)
    login_page = next(s for s in result.symbols if s.name == "LoginPage")
    assert login_page.base_names == ["BasePage"]


def test_named_field_is_not_a_base_name() -> None:
    source = "package main\n\ntype Foo struct {\n\tName string\n\tAge int\n}\n"
    result = _analyze(source)
    foo = next(s for s in result.symbols if s.name == "Foo")
    assert foo.base_names == []


def test_method_with_value_receiver_resolves_parent() -> None:
    source = """package main

type BasePage struct {
	Name string
}

func (b BasePage) Render() {}
"""
    result = _analyze(source)
    base_page = next(s for s in result.symbols if s.name == "BasePage")
    render = next(s for s in result.symbols if s.name == "Render")
    assert render.kind is SymbolKind.METHOD
    assert render.parent_id == base_page.id
    assert render.qualified_name == "BasePage.Render"


def test_method_with_pointer_receiver_resolves_parent() -> None:
    source = """package main

type BasePage struct {
	Name string
}

func (b *BasePage) Render() {}
"""
    result = _analyze(source)
    base_page = next(s for s in result.symbols if s.name == "BasePage")
    render = next(s for s in result.symbols if s.name == "Render")
    assert render.parent_id == base_page.id


def test_records_plain_call() -> None:
    source = "package main\n\nfunc a() {\n\tb()\n}\n"
    result = _analyze(source)
    assert len(result.calls) == 1
    call = result.calls[0]
    assert call.callee_name == "b"
    caller = next(s for s in result.symbols if s.name == "a")
    assert call.caller_id == caller.id


def test_records_selector_call_by_simple_name() -> None:
    source = """package main

type BasePage struct{}

func (b *BasePage) Render() {
	b.helper()
}

func (b *BasePage) helper() {}
"""
    result = _analyze(source)
    call = next(c for c in result.calls if c.callee_name == "helper")
    render = next(s for s in result.symbols if s.name == "Render")
    assert call.caller_id == render.id


def test_records_nested_call_in_arguments() -> None:
    source = "package main\n\nfunc a() {\n\touter(inner())\n}\n"
    result = _analyze(source)
    callee_names = {c.callee_name for c in result.calls}
    assert callee_names == {"outer", "inner"}


def test_module_level_call_has_no_caller() -> None:
    source = "package main\n\nvar _ = doSomething()\n"
    result = _analyze(source)
    assert result.calls[0].caller_id is None


def test_func_literal_bound_to_variable_is_a_function() -> None:
    source = """package main

func outer() {
	nested := func() {
		inner()
	}
	nested()
}
"""
    result = _analyze(source)
    nested = next(s for s in result.symbols if s.name == "nested")
    assert nested.kind is SymbolKind.FUNCTION
    outer = next(s for s in result.symbols if s.name == "outer")
    assert nested.parent_id == outer.id
    call = next(c for c in result.calls if c.callee_name == "inner")
    assert call.caller_id == nested.id


def test_import_unresolved_when_external() -> None:
    result = _analyze('package main\n\nimport "fmt"\n')
    assert len(result.imports) == 1
    assert result.imports[0].raw_module == "fmt"
    assert result.imports[0].resolved_file_path is None


def test_aliased_import_records_alias_name() -> None:
    result = _analyze('package main\n\nimport helper "myapp/helper"\n')
    assert result.imports[0].imported_names == ["helper"]


def test_grouped_imports_all_extracted() -> None:
    source = 'package main\n\nimport (\n\t"fmt"\n\t"myapp/auth"\n)\n'
    result = _analyze(source)
    assert {imp.raw_module for imp in result.imports} == {"fmt", "myapp/auth"}


def test_import_resolves_to_a_file_in_workspace_package_directory() -> None:
    workspace_files = frozenset({"app/module.go", "myapp/auth/service.go"})
    result = _analyze('package main\n\nimport "myapp/auth"\n', workspace_files=workspace_files)
    assert result.imports[0].resolved_file_path == "myapp/auth/service.go"


def test_syntax_error_recorded_but_partial_results_returned() -> None:
    result = _analyze("package main\n\nfunc foo( {\n")
    assert result.parse_errors != []


def test_valid_source_has_no_parse_errors() -> None:
    result = _analyze("package main\n\nfunc foo() {}\n")
    assert result.parse_errors == []
