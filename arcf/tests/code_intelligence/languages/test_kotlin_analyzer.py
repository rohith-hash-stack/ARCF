from code_intelligence.languages.kotlin_analyzer import KotlinLanguageAnalyzer
from domain.code_intelligence import FileAnalysis, SymbolKind


def _analyze(
    source: str,
    file_path: str = "com/example/Module.kt",
    workspace_files: frozenset[str] | None = None,
) -> FileAnalysis:
    analyzer = KotlinLanguageAnalyzer()
    return analyzer.analyze_file(file_path, source, workspace_files or frozenset())


def test_handles_kt_and_kts_extensions() -> None:
    analyzer = KotlinLanguageAnalyzer()
    assert analyzer.handles("a.kt") is True
    assert analyzer.handles("a.kts") is True
    assert analyzer.handles("a.py") is False


def test_language_property() -> None:
    assert KotlinLanguageAnalyzer().language == "kotlin"


def test_extracts_class_with_methods() -> None:
    source = """
class BasePage {
    fun render() {}
    private fun helper() {}
}
"""
    result = _analyze(source)
    classes = [s for s in result.symbols if s.kind is SymbolKind.CLASS]
    methods = [s for s in result.symbols if s.kind is SymbolKind.METHOD]
    assert [c.name for c in classes] == ["BasePage"]
    assert {m.name for m in methods} == {"render", "helper"}
    assert all(m.parent_id == classes[0].id for m in methods)


def test_extracts_interface_with_method_signature() -> None:
    source = "interface Shape {\n    fun area(): Double\n}\n"
    result = _analyze(source)
    interfaces = [s for s in result.symbols if s.kind is SymbolKind.INTERFACE]
    methods = [s for s in result.symbols if s.kind is SymbolKind.METHOD]
    assert [i.name for i in interfaces] == ["Shape"]
    assert methods[0].name == "area"
    assert methods[0].parent_id == interfaces[0].id


def test_extracts_base_class_and_interfaces_as_base_names() -> None:
    source = (
        'class LoginPage : BasePage("x"), Shape, Comparable<LoginPage> {\n}\n'
    )
    result = _analyze(source)
    login_page = next(s for s in result.symbols if s.name == "LoginPage")
    assert login_page.base_names == ["BasePage", "Shape", "Comparable"]


def test_expression_body_function() -> None:
    source = "class Foo {\n    fun area(): Double = 0.0\n}\n"
    result = _analyze(source)
    area = next(s for s in result.symbols if s.name == "area")
    assert area.kind is SymbolKind.METHOD


def test_records_plain_call() -> None:
    source = "fun a() {\n    b()\n}\n"
    result = _analyze(source)
    call = next(c for c in result.calls if c.callee_name == "b")
    caller = next(s for s in result.symbols if s.name == "a")
    assert call.caller_id == caller.id


def test_records_this_call_by_simple_name() -> None:
    source = """
class Foo {
    fun method() {
        this.helper()
    }
    private fun helper() {}
}
"""
    result = _analyze(source)
    call = next(c for c in result.calls if c.callee_name == "helper")
    caller = next(s for s in result.symbols if s.name == "method")
    assert call.caller_id == caller.id


def test_records_nested_call_in_arguments() -> None:
    source = "fun a() {\n    outer(inner())\n}\n"
    result = _analyze(source)
    callee_names = {c.callee_name for c in result.calls}
    assert callee_names == {"outer", "inner"}


def test_lambda_bound_property_is_a_method_in_class_scope() -> None:
    source = """
class Foo {
    val handler = {
        doThing()
    }
}
"""
    result = _analyze(source)
    handler = next(s for s in result.symbols if s.name == "handler")
    assert handler.kind is SymbolKind.METHOD
    call = next(c for c in result.calls if c.callee_name == "doThing")
    assert call.caller_id == handler.id


def test_anonymous_function_bound_to_local_val_is_a_function() -> None:
    source = """
fun outer() {
    val nested = fun() {
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


def test_normal_import_unresolved_when_external() -> None:
    result = _analyze("import com.example.auth.Authenticator\n")
    assert len(result.imports) == 1
    assert result.imports[0].raw_module == "com.example.auth.Authenticator"
    assert result.imports[0].imported_names == ["Authenticator"]
    assert result.imports[0].resolved_file_path is None


def test_normal_import_resolves_to_workspace_file() -> None:
    workspace_files = frozenset(
        {"com/example/Module.kt", "com/example/auth/Authenticator.kt"}
    )
    result = _analyze(
        "import com.example.auth.Authenticator\n", workspace_files=workspace_files
    )
    assert result.imports[0].resolved_file_path == "com/example/auth/Authenticator.kt"


def test_wildcard_import_recorded_and_resolves_to_representative_file() -> None:
    workspace_files = frozenset(
        {"com/example/Module.kt", "com/example/util/Helpers.kt", "com/example/util/Other.kt"}
    )
    result = _analyze("import com.example.util.*\n", workspace_files=workspace_files)
    assert result.imports[0].imported_names == ["*"]
    assert result.imports[0].resolved_file_path == "com/example/util/Helpers.kt"


def test_aliased_import_records_alias_name() -> None:
    result = _analyze("import com.example.util.Helpers as helper\n")
    assert result.imports[0].imported_names == ["helper"]
    assert result.imports[0].raw_module == "com.example.util.Helpers"


def test_import_falls_back_to_package_directory_when_last_segment_is_a_member() -> None:
    workspace_files = frozenset({"com/example/Module.kt", "com/example/util/Helpers.kt"})
    result = _analyze(
        "import com.example.util.Helpers.helperFunction\n", workspace_files=workspace_files
    )
    assert result.imports[0].resolved_file_path == "com/example/util/Helpers.kt"


def test_syntax_error_recorded_but_partial_results_returned() -> None:
    result = _analyze("class Foo {\n    fun a( {\n")
    assert result.parse_errors != []


def test_valid_source_has_no_parse_errors() -> None:
    result = _analyze("class Foo {\n    fun a() {}\n}\n")
    assert result.parse_errors == []
