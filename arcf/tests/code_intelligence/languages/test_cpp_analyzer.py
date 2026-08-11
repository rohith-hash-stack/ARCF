from code_intelligence.languages.cpp_analyzer import CppLanguageAnalyzer
from domain.code_intelligence import FileAnalysis, SymbolKind


def _analyze(
    source: str,
    file_path: str = "app/module.cpp",
    workspace_files: frozenset[str] | None = None,
) -> FileAnalysis:
    analyzer = CppLanguageAnalyzer()
    return analyzer.analyze_file(file_path, source, workspace_files or frozenset())


def test_handles_cpp_extensions() -> None:
    analyzer = CppLanguageAnalyzer()
    assert analyzer.handles("a.cpp") is True
    assert analyzer.handles("a.cc") is True
    assert analyzer.handles("a.hpp") is True
    assert analyzer.handles("a.h") is True
    assert analyzer.handles("a.c") is True
    assert analyzer.handles("a.py") is False


def test_language_property() -> None:
    assert CppLanguageAnalyzer().language == "cpp"


def test_extracts_top_level_function() -> None:
    result = _analyze("int foo() { return 1; }\n")
    funcs = [s for s in result.symbols if s.kind is SymbolKind.FUNCTION]
    assert len(funcs) == 1
    assert funcs[0].name == "foo"
    assert funcs[0].qualified_name == "foo"
    assert funcs[0].parent_id is None


def test_extracts_class_and_struct_as_class_kind() -> None:
    source = "class Foo {};\nstruct Bar { int x; };\n"
    result = _analyze(source)
    classes = [s for s in result.symbols if s.kind is SymbolKind.CLASS]
    assert {c.name for c in classes} == {"Foo", "Bar"}


def test_forward_declaration_is_not_a_symbol() -> None:
    source = "struct Point;\nvoid use(Point* p);\n"
    result = _analyze(source)
    classes = [s for s in result.symbols if s.kind is SymbolKind.CLASS]
    assert classes == []


def test_base_class_clause_is_base_names() -> None:
    source = "class Base {};\nclass Other {};\nclass Derived : public Base, private Other {};\n"
    result = _analyze(source)
    derived = next(s for s in result.symbols if s.name == "Derived")
    assert derived.base_names == ["Base", "Other"]


def test_no_base_clause_is_empty_base_names() -> None:
    result = _analyze("class Foo { int x; };\n")
    foo = next(s for s in result.symbols if s.name == "Foo")
    assert foo.base_names == []


def test_in_class_inline_method_resolves_parent() -> None:
    source = """class Derived {
public:
    int compute(int x) { return x + 1; }
};
"""
    result = _analyze(source)
    derived = next(s for s in result.symbols if s.name == "Derived")
    compute = next(s for s in result.symbols if s.name == "compute")
    assert compute.kind is SymbolKind.METHOD
    assert compute.parent_id == derived.id
    assert compute.qualified_name == "Derived::compute"


def test_in_class_method_prototype_resolves_parent() -> None:
    source = """class Derived {
public:
    void run();
};
"""
    result = _analyze(source)
    derived = next(s for s in result.symbols if s.name == "Derived")
    run = next(s for s in result.symbols if s.name == "run")
    assert run.kind is SymbolKind.METHOD
    assert run.parent_id == derived.id


def test_out_of_class_method_definition_resolves_parent() -> None:
    source = """class Derived {
public:
    int helper(int x);
};

int Derived::helper(int x) { return x * 2; }
"""
    result = _analyze(source)
    derived = next(s for s in result.symbols if s.name == "Derived")
    helpers = [s for s in result.symbols if s.name == "helper"]
    out_of_class = next(s for s in helpers if s.qualified_name == "Derived::helper")
    assert out_of_class.kind is SymbolKind.METHOD
    assert out_of_class.parent_id == derived.id


def test_destructor_is_a_method() -> None:
    source = """class Base {
public:
    virtual ~Base() = default;
};
"""
    result = _analyze(source)
    dtor = next(s for s in result.symbols if s.name == "~Base")
    assert dtor.kind is SymbolKind.METHOD
    base = next(s for s in result.symbols if s.name == "Base")
    assert dtor.parent_id == base.id


def test_namespace_qualifies_free_function_name() -> None:
    source = "namespace outer {\nnamespace inner {\nvoid run() {}\n}\n}\n"
    result = _analyze(source)
    run = next(s for s in result.symbols if s.name == "run")
    assert run.qualified_name == "outer::inner::run"
    assert run.parent_id is None


def test_namespace_qualifies_class_name() -> None:
    source = "namespace ns {\nclass Foo {};\n}\n"
    result = _analyze(source)
    foo = next(s for s in result.symbols if s.name == "Foo")
    assert foo.qualified_name == "ns::Foo"


def test_records_plain_call() -> None:
    source = "void b() {}\nvoid a() {\n  b();\n}\n"
    result = _analyze(source)
    call = next(c for c in result.calls if c.callee_name == "b")
    caller = next(s for s in result.symbols if s.name == "a")
    assert call.caller_id == caller.id


def test_records_dot_field_call_by_simple_name() -> None:
    source = """class Derived {
public:
    void run() { helper(); }
    void helper();
};
"""
    result = _analyze(source)
    call = next(c for c in result.calls if c.callee_name == "helper")
    run = next(s for s in result.symbols if s.name == "run")
    assert call.caller_id == run.id


def test_records_arrow_field_call_by_simple_name() -> None:
    source = "void a(Foo* f) {\n  f->run();\n}\n"
    result = _analyze(source)
    call = next(c for c in result.calls if c.callee_name == "run")
    caller = next(s for s in result.symbols if s.name == "a")
    assert call.caller_id == caller.id


def test_records_nested_call_in_arguments() -> None:
    source = "void a() {\n  outer(inner());\n}\n"
    result = _analyze(source)
    callee_names = {c.callee_name for c in result.calls}
    assert callee_names == {"outer", "inner"}


def test_top_level_call_has_no_caller() -> None:
    source = "int x = doSomething();\n"
    result = _analyze(source)
    assert result.calls[0].caller_id is None


def test_angle_bracket_include_is_unresolved() -> None:
    result = _analyze('#include <vector>\n')
    assert len(result.imports) == 1
    assert result.imports[0].raw_module == "<vector>"
    assert result.imports[0].resolved_file_path is None


def test_quoted_include_resolves_relative_to_current_file() -> None:
    workspace_files = frozenset({"app/module.cpp", "app/helper.h"})
    result = _analyze(
        '#include "helper.h"\n', file_path="app/module.cpp", workspace_files=workspace_files
    )
    assert result.imports[0].resolved_file_path == "app/helper.h"


def test_quoted_include_resolves_by_suffix_when_not_relative() -> None:
    workspace_files = frozenset({"src/lib/foo/bar.h"})
    result = _analyze(
        '#include "foo/bar.h"\n', file_path="app/module.cpp", workspace_files=workspace_files
    )
    assert result.imports[0].resolved_file_path == "src/lib/foo/bar.h"


def test_quoted_include_unresolved_when_no_match() -> None:
    result = _analyze('#include "nowhere.h"\n')
    assert result.imports[0].resolved_file_path is None


def test_syntax_error_recorded_but_partial_results_returned() -> None:
    result = _analyze("int foo( {\n")
    assert result.parse_errors != []


def test_valid_source_has_no_parse_errors() -> None:
    result = _analyze("int foo() { return 0; }\n")
    assert result.parse_errors == []


def test_c_file_parses_with_c_grammar() -> None:
    source = "struct Point { int x; int y; };\n\nint helper(int x) { return x * 2; }\n"
    result = _analyze(source, file_path="app/module.c")
    assert result.parse_errors == []
    assert {s.name for s in result.symbols} == {"Point", "helper"}
