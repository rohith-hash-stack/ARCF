from code_intelligence.languages.csharp_analyzer import CSharpLanguageAnalyzer
from domain.code_intelligence import FileAnalysis, SymbolKind


def _analyze(
    source: str,
    file_path: str = "MyApp/Module.cs",
    workspace_files: frozenset[str] | None = None,
) -> FileAnalysis:
    analyzer = CSharpLanguageAnalyzer()
    return analyzer.analyze_file(file_path, source, workspace_files or frozenset())


def test_handles_cs_extension() -> None:
    analyzer = CSharpLanguageAnalyzer()
    assert analyzer.handles("a.cs") is True
    assert analyzer.handles("a.py") is False


def test_language_property() -> None:
    assert CSharpLanguageAnalyzer().language == "csharp"


def test_extracts_class_with_methods() -> None:
    source = """
public class BasePage
{
    public void Render() {}
    private void Helper() {}
}
"""
    result = _analyze(source)
    classes = [s for s in result.symbols if s.kind is SymbolKind.CLASS]
    methods = [s for s in result.symbols if s.kind is SymbolKind.METHOD]
    assert [c.name for c in classes] == ["BasePage"]
    assert {m.name for m in methods} == {"Render", "Helper"}
    assert all(m.parent_id == classes[0].id for m in methods)


def test_extracts_interface_with_method_signature() -> None:
    source = "public interface IShape\n{\n    double Area();\n}\n"
    result = _analyze(source)
    interfaces = [s for s in result.symbols if s.kind is SymbolKind.INTERFACE]
    methods = [s for s in result.symbols if s.kind is SymbolKind.METHOD]
    assert [i.name for i in interfaces] == ["IShape"]
    assert methods[0].name == "Area"
    assert methods[0].parent_id == interfaces[0].id


def test_extracts_base_class_and_interfaces_as_base_names() -> None:
    source = (
        "public class LoginPage : BasePage, IShape, IComparable<LoginPage>\n{\n}\n"
    )
    result = _analyze(source)
    login_page = next(s for s in result.symbols if s.name == "LoginPage")
    assert login_page.base_names == ["BasePage", "IShape", "IComparable"]


def test_namespace_is_descended_but_not_a_symbol() -> None:
    source = """
namespace MyApp
{
    public class Foo
    {
        public void Method() {}
    }
}
"""
    result = _analyze(source)
    assert {s.name for s in result.symbols} == {"Foo", "Method"}


def test_records_plain_call() -> None:
    source = "public class Foo\n{\n    public void A()\n    {\n        B();\n    }\n}\n"
    result = _analyze(source)
    call = next(c for c in result.calls if c.callee_name == "B")
    caller = next(s for s in result.symbols if s.name == "A")
    assert call.caller_id == caller.id


def test_records_this_call_by_simple_name() -> None:
    source = """
public class Foo
{
    public void Method()
    {
        this.Helper();
    }
    private void Helper() {}
}
"""
    result = _analyze(source)
    call = next(c for c in result.calls if c.callee_name == "Helper")
    caller = next(s for s in result.symbols if s.name == "Method")
    assert call.caller_id == caller.id


def test_records_nested_call_in_arguments() -> None:
    source = "public class Foo\n{\n    public void A()\n    {\n        Outer(Inner());\n    }\n}\n"
    result = _analyze(source)
    callee_names = {c.callee_name for c in result.calls}
    assert callee_names == {"Outer", "Inner"}


def test_bare_using_directive_unresolved_when_external() -> None:
    result = _analyze("using System;\n")
    assert len(result.imports) == 1
    assert result.imports[0].raw_module == "System"
    assert result.imports[0].imported_names == ["System"]
    assert result.imports[0].resolved_file_path is None


def test_dotted_using_directive_resolves_to_representative_file() -> None:
    workspace_files = frozenset(
        {"MyApp/Module.cs", "MyApp/Auth/Authenticator.cs", "MyApp/Auth/Session.cs"}
    )
    result = _analyze("using MyApp.Auth;\n", workspace_files=workspace_files)
    assert result.imports[0].raw_module == "MyApp.Auth"
    assert result.imports[0].resolved_file_path == "MyApp/Auth/Authenticator.cs"


def test_aliased_using_directive_records_alias_name() -> None:
    result = _analyze("using Helper = MyApp.Util.Helpers;\n")
    assert result.imports[0].imported_names == ["Helper"]
    assert result.imports[0].raw_module == "MyApp.Util.Helpers"


def test_syntax_error_recorded_but_partial_results_returned() -> None:
    result = _analyze("public class Foo\n{\n    public void A( {\n")
    assert result.parse_errors != []


def test_valid_source_has_no_parse_errors() -> None:
    result = _analyze("public class Foo\n{\n    public void A() {}\n}\n")
    assert result.parse_errors == []
