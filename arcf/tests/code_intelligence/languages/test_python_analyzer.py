from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from domain.code_intelligence import FileAnalysis, SymbolKind


def _analyze(
    source: str,
    file_path: str = "app/module.py",
    workspace_files: frozenset[str] | None = None,
) -> FileAnalysis:
    analyzer = PythonLanguageAnalyzer()
    return analyzer.analyze_file(file_path, source, workspace_files or frozenset())


def test_handles_py_and_pyi_extensions() -> None:
    analyzer = PythonLanguageAnalyzer()
    assert analyzer.handles("a.py") is True
    assert analyzer.handles("a.pyi") is True
    assert analyzer.handles("a.js") is False


def test_language_property() -> None:
    assert PythonLanguageAnalyzer().language == "python"


def test_extracts_top_level_function() -> None:
    result = _analyze("def foo():\n    pass\n")
    assert len(result.symbols) == 1
    symbol = result.symbols[0]
    assert symbol.name == "foo"
    assert symbol.qualified_name == "foo"
    assert symbol.kind is SymbolKind.FUNCTION
    assert symbol.parent_id is None


def test_extracts_class_with_methods() -> None:
    source = """
class BasePage:
    def render(self):
        pass

    def helper(self):
        pass
"""
    result = _analyze(source)
    classes = [s for s in result.symbols if s.kind is SymbolKind.CLASS]
    methods = [s for s in result.symbols if s.kind is SymbolKind.METHOD]
    assert [c.name for c in classes] == ["BasePage"]
    assert {m.name for m in methods} == {"render", "helper"}
    assert all(m.parent_id == classes[0].id for m in methods)


def test_extracts_base_class_names() -> None:
    source = "class LoginPage(BasePage):\n    pass\n"
    result = _analyze(source)
    login_page = next(s for s in result.symbols if s.name == "LoginPage")
    assert login_page.base_names == ["BasePage"]


def test_extracts_multiple_base_names_ignoring_keyword_args() -> None:
    source = "class Foo(Base1, Base2, metaclass=Meta):\n    pass\n"
    result = _analyze(source)
    foo = next(s for s in result.symbols if s.name == "Foo")
    assert foo.base_names == ["Base1", "Base2"]


def test_nested_function_is_function_not_method() -> None:
    source = """
def outer():
    def inner():
        pass
    return inner
"""
    result = _analyze(source)
    inner = next(s for s in result.symbols if s.name == "inner")
    assert inner.kind is SymbolKind.FUNCTION
    outer = next(s for s in result.symbols if s.name == "outer")
    assert inner.parent_id == outer.id


def test_records_plain_call() -> None:
    source = "def a():\n    b()\n"
    result = _analyze(source)
    assert len(result.calls) == 1
    call = result.calls[0]
    assert call.callee_name == "b"
    caller = next(s for s in result.symbols if s.name == "a")
    assert call.caller_id == caller.id


def test_records_attribute_call_by_simple_name() -> None:
    source = """
class Foo:
    def method(self):
        self.helper()
"""
    result = _analyze(source)
    call = next(c for c in result.calls if c.callee_name == "helper")
    caller = next(s for s in result.symbols if s.name == "method")
    assert call.caller_id == caller.id


def test_records_nested_call_in_arguments() -> None:
    source = "def a():\n    outer(inner())\n"
    result = _analyze(source)
    callee_names = {c.callee_name for c in result.calls}
    assert callee_names == {"outer", "inner"}


def test_module_level_call_has_no_caller() -> None:
    source = "do_something()\n"
    result = _analyze(source)
    assert result.calls[0].caller_id is None


def test_plain_import_unresolved_when_external() -> None:
    result = _analyze("import os\n")
    assert len(result.imports) == 1
    assert result.imports[0].raw_module == "os"
    assert result.imports[0].resolved_file_path is None


def test_plain_import_with_alias_uses_module_text() -> None:
    result = _analyze("import os.path as op\n")
    assert result.imports[0].raw_module == "os.path"


def test_plain_import_resolves_to_workspace_file() -> None:
    workspace_files = frozenset({"app/module.py", "app/utils.py"})
    result = _analyze("import app.utils\n", workspace_files=workspace_files)
    assert result.imports[0].resolved_file_path == "app/utils.py"


def test_absolute_from_import_resolves_to_workspace_file() -> None:
    workspace_files = frozenset({"app/module.py", "app/services/auth.py"})
    result = _analyze(
        "from app.services.auth import authenticate\n", workspace_files=workspace_files
    )
    imp = result.imports[0]
    assert imp.resolved_file_path == "app/services/auth.py"
    assert imp.imported_names == ["authenticate"]


def test_relative_import_single_dot_resolves_sibling_module() -> None:
    workspace_files = frozenset({"app/pages/login.py", "app/pages/utils.py"})
    result = _analyze(
        "from . import utils\n", file_path="app/pages/login.py", workspace_files=workspace_files
    )
    assert result.imports[0].resolved_file_path == "app/pages/utils.py"


def test_relative_import_with_module_name_resolves() -> None:
    workspace_files = frozenset({"app/pages/login.py", "app/pages/helpers.py"})
    result = _analyze(
        "from .helpers import authenticate\n",
        file_path="app/pages/login.py",
        workspace_files=workspace_files,
    )
    assert result.imports[0].resolved_file_path == "app/pages/helpers.py"


def test_relative_import_double_dot_goes_up_a_level() -> None:
    workspace_files = frozenset({"app/pages/login.py", "app/pkg/sub.py"})
    result = _analyze(
        "from ..pkg.sub import thing\n",
        file_path="app/pages/login.py",
        workspace_files=workspace_files,
    )
    assert result.imports[0].resolved_file_path == "app/pkg/sub.py"


def test_relative_import_falls_back_to_init_py() -> None:
    workspace_files = frozenset({"app/pages/login.py", "app/pages/__init__.py"})
    result = _analyze(
        "from . import SOME_CONSTANT\n",
        file_path="app/pages/login.py",
        workspace_files=workspace_files,
    )
    assert result.imports[0].resolved_file_path == "app/pages/__init__.py"


def test_from_import_multiple_names_from_same_module() -> None:
    workspace_files = frozenset({"app/module.py", "app/services/auth.py"})
    result = _analyze(
        "from app.services.auth import login, logout\n", workspace_files=workspace_files
    )
    assert len(result.imports) == 1
    assert set(result.imports[0].imported_names) == {"login", "logout"}


def test_from_import_names_resolve_independently_when_module_is_package() -> None:
    workspace_files = frozenset(
        {"app/pages/login.py", "app/pages/foo.py", "app/pages/bar.py"}
    )
    result = _analyze(
        "from . import foo, bar\n",
        file_path="app/pages/login.py",
        workspace_files=workspace_files,
    )
    resolved = {imp.imported_names[0]: imp.resolved_file_path for imp in result.imports}
    assert resolved == {"foo": "app/pages/foo.py", "bar": "app/pages/bar.py"}


def test_syntax_error_recorded_but_partial_results_returned() -> None:
    result = _analyze("def foo(:\n    pass\n")
    assert result.parse_errors != []


def test_valid_source_has_no_parse_errors() -> None:
    result = _analyze("def foo():\n    pass\n")
    assert result.parse_errors == []


def test_decorated_function_records_symbol_and_decorator_reference() -> None:
    result = _analyze('@app.get("/users")\ndef list_users():\n    pass\n')

    assert [s.name for s in result.symbols] == ["list_users"]
    assert len(result.decorators) == 1
    decorator = result.decorators[0]
    assert decorator.decorator_name == "app.get"
    assert decorator.symbol_id == result.symbols[0].id


def test_bare_decorator_with_no_call_is_recorded() -> None:
    result = _analyze("@dataclass\nclass Foo:\n    pass\n")

    assert [s.name for s in result.symbols] == ["Foo"]
    assert result.decorators[0].decorator_name == "dataclass"


def test_decorated_method_inside_class_is_linked_to_the_method_not_the_class() -> None:
    source = (
        "class Router:\n"
        '    @app.post("/login")\n'
        "    async def login(self, request):\n"
        "        return authenticate(request)\n"
    )
    result = _analyze(source)

    login = next(s for s in result.symbols if s.name == "login")
    assert login.kind is SymbolKind.METHOD
    assert len(result.decorators) == 1
    assert result.decorators[0].symbol_id == login.id
    assert result.decorators[0].decorator_name == "app.post"
    # the call inside the decorated method body must still be captured —
    # decorator handling must not swallow the rest of the function body.
    assert any(c.callee_name == "authenticate" for c in result.calls)


def test_undecorated_function_has_no_decorator_references() -> None:
    result = _analyze("def undecorated():\n    pass\n")
    assert result.decorators == []


def test_multiple_decorators_on_one_symbol_are_all_recorded() -> None:
    source = "@first\n@second.third()\ndef handler():\n    pass\n"
    result = _analyze(source)

    names = {d.decorator_name for d in result.decorators}
    assert names == {"first", "second.third"}
    assert all(d.symbol_id == result.symbols[0].id for d in result.decorators)
