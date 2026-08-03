from code_intelligence.languages.typescript_analyzer import TypeScriptLanguageAnalyzer
from domain.code_intelligence import FileAnalysis, SymbolKind


def _analyze(
    source: str,
    file_path: str = "app/module.ts",
    workspace_files: frozenset[str] | None = None,
) -> FileAnalysis:
    analyzer = TypeScriptLanguageAnalyzer()
    return analyzer.analyze_file(file_path, source, workspace_files or frozenset())


def test_handles_ts_tsx_js_jsx_extensions() -> None:
    analyzer = TypeScriptLanguageAnalyzer()
    assert analyzer.handles("a.ts") is True
    assert analyzer.handles("a.tsx") is True
    assert analyzer.handles("a.js") is True
    assert analyzer.handles("a.jsx") is True
    assert analyzer.handles("a.py") is False


def test_language_property() -> None:
    assert TypeScriptLanguageAnalyzer().language == "typescript"


def test_extracts_top_level_function() -> None:
    result = _analyze("function foo() {\n  return 1;\n}\n")
    assert len(result.symbols) == 1
    symbol = result.symbols[0]
    assert symbol.name == "foo"
    assert symbol.qualified_name == "foo"
    assert symbol.kind is SymbolKind.FUNCTION
    assert symbol.parent_id is None


def test_extracts_class_with_methods() -> None:
    source = """
class BasePage {
  render() {
    return null;
  }

  helper() {}
}
"""
    result = _analyze(source)
    classes = [s for s in result.symbols if s.kind is SymbolKind.CLASS]
    methods = [s for s in result.symbols if s.kind is SymbolKind.METHOD]
    assert [c.name for c in classes] == ["BasePage"]
    assert {m.name for m in methods} == {"render", "helper"}
    assert all(m.parent_id == classes[0].id for m in methods)


def test_extracts_base_class_and_interface_names() -> None:
    source = "class LoginPage extends BasePage implements Cloneable, Comparable {}\n"
    result = _analyze(source)
    login_page = next(s for s in result.symbols if s.name == "LoginPage")
    assert login_page.base_names == ["BasePage", "Cloneable", "Comparable"]


def test_interface_extends_multiple_base_names() -> None:
    source = "interface Sub extends Base, Other {\n  x: number;\n}\n"
    result = _analyze(source)
    sub = next(s for s in result.symbols if s.name == "Sub")
    assert sub.kind is SymbolKind.INTERFACE
    assert sub.base_names == ["Base", "Other"]


def test_abstract_class_and_method_signature() -> None:
    source = "abstract class Shape {\n  abstract area(): number;\n}\n"
    result = _analyze(source)
    shape = next(s for s in result.symbols if s.name == "Shape")
    assert shape.kind is SymbolKind.CLASS
    area = next(s for s in result.symbols if s.name == "area")
    assert area.kind is SymbolKind.METHOD
    assert area.parent_id == shape.id


def test_class_field_arrow_function_is_a_method() -> None:
    source = """
class Comp {
  handleClick = () => {
    doThing();
  };
}
"""
    result = _analyze(source)
    handle_click = next(s for s in result.symbols if s.name == "handleClick")
    assert handle_click.kind is SymbolKind.METHOD
    call = next(c for c in result.calls if c.callee_name == "doThing")
    assert call.caller_id == handle_click.id


def test_variable_bound_arrow_function_is_a_function() -> None:
    source = "const named = () => {\n  doSomething();\n};\n"
    result = _analyze(source)
    named = next(s for s in result.symbols if s.name == "named")
    assert named.kind is SymbolKind.FUNCTION
    call = next(c for c in result.calls if c.callee_name == "doSomething")
    assert call.caller_id == named.id


def test_concise_arrow_body_call_is_recorded() -> None:
    source = "const named = () => doSomething();\n"
    result = _analyze(source)
    named = next(s for s in result.symbols if s.name == "named")
    call = next(c for c in result.calls if c.callee_name == "doSomething")
    assert call.caller_id == named.id


def test_nested_function_is_function_not_method() -> None:
    source = """
function outer() {
  function inner() {}
  return inner;
}
"""
    result = _analyze(source)
    inner = next(s for s in result.symbols if s.name == "inner")
    assert inner.kind is SymbolKind.FUNCTION
    outer = next(s for s in result.symbols if s.name == "outer")
    assert inner.parent_id == outer.id


def test_records_plain_call() -> None:
    source = "function a() {\n  b();\n}\n"
    result = _analyze(source)
    assert len(result.calls) == 1
    call = result.calls[0]
    assert call.callee_name == "b"
    caller = next(s for s in result.symbols if s.name == "a")
    assert call.caller_id == caller.id


def test_records_member_call_by_simple_name() -> None:
    source = """
class Foo {
  method() {
    this.helper();
  }
}
"""
    result = _analyze(source)
    call = next(c for c in result.calls if c.callee_name == "helper")
    caller = next(s for s in result.symbols if s.name == "method")
    assert call.caller_id == caller.id


def test_records_nested_call_in_arguments() -> None:
    source = "function a() {\n  outer(inner());\n}\n"
    result = _analyze(source)
    callee_names = {c.callee_name for c in result.calls}
    assert callee_names == {"outer", "inner"}


def test_module_level_call_has_no_caller() -> None:
    source = "doSomething();\n"
    result = _analyze(source)
    assert result.calls[0].caller_id is None


def test_named_import_unresolved_when_external() -> None:
    result = _analyze("import { foo } from 'external-pkg';\n")
    assert len(result.imports) == 1
    assert result.imports[0].raw_module == "external-pkg"
    assert result.imports[0].imported_names == ["foo"]
    assert result.imports[0].resolved_file_path is None


def test_named_import_with_alias_records_original_name() -> None:
    result = _analyze("import { foo as bar } from 'external-pkg';\n")
    assert result.imports[0].imported_names == ["foo"]


def test_default_import_records_local_name() -> None:
    workspace_files = frozenset({"app/module.ts", "app/other.ts"})
    result = _analyze(
        "import Default from '../other';\n",
        file_path="app/pages/module.ts",
        workspace_files=workspace_files,
    )
    assert result.imports[0].imported_names == ["Default"]


def test_namespace_import_recorded_as_wildcard() -> None:
    result = _analyze("import * as ns from 'external-pkg';\n")
    assert result.imports[0].imported_names == ["*"]


def test_relative_import_resolves_to_workspace_file() -> None:
    workspace_files = frozenset({"app/module.ts", "app/utils.ts"})
    result = _analyze("import { helper } from './utils';\n", workspace_files=workspace_files)
    assert result.imports[0].resolved_file_path == "app/utils.ts"


def test_relative_import_resolves_index_file() -> None:
    workspace_files = frozenset({"app/module.ts", "app/services/index.ts"})
    result = _analyze(
        "import { login } from './services';\n", workspace_files=workspace_files
    )
    assert result.imports[0].resolved_file_path == "app/services/index.ts"


def test_parent_relative_import_goes_up_a_level() -> None:
    workspace_files = frozenset({"app/pages/login.ts", "app/pkg/sub.ts"})
    result = _analyze(
        "import { thing } from '../pkg/sub';\n",
        file_path="app/pages/login.ts",
        workspace_files=workspace_files,
    )
    assert result.imports[0].resolved_file_path == "app/pkg/sub.ts"


def test_tsx_file_parses_jsx_syntax() -> None:
    source = """
export function Component() {
  doSomething();
  return null;
}
"""
    result = _analyze(source, file_path="app/Component.tsx")
    assert result.parse_errors == []
    assert any(s.name == "Component" for s in result.symbols)


def test_syntax_error_recorded_but_partial_results_returned() -> None:
    result = _analyze("function foo( {\n  return 1;\n}\n")
    assert result.parse_errors != []


def test_valid_source_has_no_parse_errors() -> None:
    result = _analyze("function foo() {\n  return 1;\n}\n")
    assert result.parse_errors == []
