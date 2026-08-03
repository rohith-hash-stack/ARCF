from code_intelligence.languages.java_analyzer import JavaLanguageAnalyzer
from domain.code_intelligence import FileAnalysis, SymbolKind


def _analyze(
    source: str,
    file_path: str = "com/example/Module.java",
    workspace_files: frozenset[str] | None = None,
) -> FileAnalysis:
    analyzer = JavaLanguageAnalyzer()
    return analyzer.analyze_file(file_path, source, workspace_files or frozenset())


def test_handles_java_extension() -> None:
    analyzer = JavaLanguageAnalyzer()
    assert analyzer.handles("a.java") is True
    assert analyzer.handles("a.py") is False


def test_language_property() -> None:
    assert JavaLanguageAnalyzer().language == "java"


def test_extracts_class_with_methods() -> None:
    source = """
class BasePage {
    public void render() {}
    private void helper() {}
}
"""
    result = _analyze(source)
    classes = [s for s in result.symbols if s.kind is SymbolKind.CLASS]
    methods = [s for s in result.symbols if s.kind is SymbolKind.METHOD]
    assert [c.name for c in classes] == ["BasePage"]
    assert {m.name for m in methods} == {"render", "helper"}
    assert all(m.parent_id == classes[0].id for m in methods)


def test_extracts_interface_with_method_signature() -> None:
    source = "interface Shape {\n    double area();\n}\n"
    result = _analyze(source)
    interfaces = [s for s in result.symbols if s.kind is SymbolKind.INTERFACE]
    methods = [s for s in result.symbols if s.kind is SymbolKind.METHOD]
    assert [i.name for i in interfaces] == ["Shape"]
    assert methods[0].name == "area"
    assert methods[0].parent_id == interfaces[0].id


def test_extracts_superclass_and_interfaces_as_base_names() -> None:
    source = "class LoginPage extends BasePage implements Shape, Comparable<LoginPage> {}\n"
    result = _analyze(source)
    login_page = next(s for s in result.symbols if s.name == "LoginPage")
    assert login_page.base_names == ["BasePage", "Shape", "Comparable"]


def test_interface_extends_multiple_interfaces() -> None:
    source = "interface Sub extends Base, Other {}\n"
    result = _analyze(source)
    sub = next(s for s in result.symbols if s.name == "Sub")
    assert sub.base_names == ["Base", "Other"]


def test_nested_class_qualified_name() -> None:
    source = """
class Outer {
    class Inner {
        public void method() {}
    }
}
"""
    result = _analyze(source)
    method = next(s for s in result.symbols if s.name == "method")
    assert method.qualified_name == "Outer.Inner.method"


def test_records_plain_call() -> None:
    source = "class Foo {\n    public void a() {\n        b();\n    }\n}\n"
    result = _analyze(source)
    call = next(c for c in result.calls if c.callee_name == "b")
    caller = next(s for s in result.symbols if s.name == "a")
    assert call.caller_id == caller.id


def test_records_this_call_by_simple_name() -> None:
    source = """
class Foo {
    public void method() {
        this.helper();
    }
    private void helper() {}
}
"""
    result = _analyze(source)
    call = next(c for c in result.calls if c.callee_name == "helper")
    caller = next(s for s in result.symbols if s.name == "method")
    assert call.caller_id == caller.id


def test_records_nested_call_in_arguments() -> None:
    source = "class Foo {\n    public void a() {\n        outer(inner());\n    }\n}\n"
    result = _analyze(source)
    callee_names = {c.callee_name for c in result.calls}
    assert callee_names == {"outer", "inner"}


def test_normal_import_unresolved_when_external() -> None:
    result = _analyze("import com.example.auth.Authenticator;\n")
    assert len(result.imports) == 1
    assert result.imports[0].raw_module == "com.example.auth.Authenticator"
    assert result.imports[0].imported_names == ["Authenticator"]
    assert result.imports[0].resolved_file_path is None


def test_normal_import_resolves_to_workspace_file() -> None:
    workspace_files = frozenset(
        {"com/example/Module.java", "com/example/auth/Authenticator.java"}
    )
    result = _analyze(
        "import com.example.auth.Authenticator;\n", workspace_files=workspace_files
    )
    assert result.imports[0].resolved_file_path == "com/example/auth/Authenticator.java"


def test_wildcard_import_recorded_as_wildcard() -> None:
    result = _analyze("import com.example.util.*;\n")
    assert result.imports[0].imported_names == ["*"]
    assert result.imports[0].raw_module == "com.example.util"


def test_wildcard_import_resolves_to_representative_file() -> None:
    workspace_files = frozenset(
        {"com/example/Module.java", "com/example/util/Helpers.java", "com/example/util/Other.java"}
    )
    result = _analyze("import com.example.util.*;\n", workspace_files=workspace_files)
    assert result.imports[0].resolved_file_path == "com/example/util/Helpers.java"


def test_static_import_records_member_name() -> None:
    result = _analyze("import static com.example.util.Helpers.helper;\n")
    assert result.imports[0].imported_names == ["helper"]


def test_static_import_resolves_via_class_minus_member() -> None:
    workspace_files = frozenset({"com/example/Module.java", "com/example/util/Helpers.java"})
    result = _analyze(
        "import static com.example.util.Helpers.helper;\n", workspace_files=workspace_files
    )
    assert result.imports[0].resolved_file_path == "com/example/util/Helpers.java"


def test_syntax_error_recorded_but_partial_results_returned() -> None:
    result = _analyze("class Foo {\n    public void a( {\n")
    assert result.parse_errors != []


def test_valid_source_has_no_parse_errors() -> None:
    result = _analyze("class Foo {\n    public void a() {}\n}\n")
    assert result.parse_errors == []
