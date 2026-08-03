from code_intelligence.call_graph import CallGraph
from code_intelligence.reference_resolver import ReferenceResolver
from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import CallReference, SourceLocation, Symbol, SymbolKind


def _function(name: str, file_path: str = "a.py") -> Symbol:
    return Symbol(
        id=f"{file_path}::{name}",
        name=name,
        qualified_name=name,
        kind=SymbolKind.FUNCTION,
        file_path=file_path,
        location=SourceLocation(file_path=file_path, start_line=1, end_line=1),
    )


def _call(caller_id: str | None, callee_name: str, file_path: str = "a.py") -> CallReference:
    return CallReference(
        caller_id=caller_id,
        callee_name=callee_name,
        file_path=file_path,
        location=SourceLocation(file_path=file_path, start_line=5, end_line=5),
    )


def test_finds_the_example_query_caller_case() -> None:
    authenticate = _function("authenticate", file_path="auth.py")
    check = _function("check", file_path="login.py")
    resolver = ReferenceResolver(SymbolIndex([authenticate, check]))
    call = _call(check.id, "authenticate", file_path="login.py")
    graph = CallGraph([call], resolver)

    assert graph.caller_symbols_of(authenticate.id) == {check.id}
    assert graph.caller_files_of(authenticate.id) == {"login.py"}
    assert graph.callee_symbols_of(check.id) == {authenticate.id}


def test_module_level_call_counted_in_files_not_symbols() -> None:
    authenticate = _function("authenticate")
    resolver = ReferenceResolver(SymbolIndex([authenticate]))
    call = _call(None, "authenticate", file_path="script.py")
    graph = CallGraph([call], resolver)

    assert graph.caller_files_of(authenticate.id) == {"script.py"}
    assert graph.caller_symbols_of(authenticate.id) == set()


def test_unresolved_call_recorded_not_dropped() -> None:
    resolver = ReferenceResolver(SymbolIndex([]))
    call = _call(None, "some_external_builtin")
    graph = CallGraph([call], resolver)

    assert graph.unresolved_calls == [call]


def test_ambiguous_callee_creates_edges_to_all_candidates() -> None:
    a = _function("helper", file_path="a.py")
    b = _function("helper", file_path="b.py")
    caller = _function("main", file_path="main.py")
    resolver = ReferenceResolver(SymbolIndex([a, b, caller]))
    call = _call(caller.id, "helper", file_path="main.py")
    graph = CallGraph([call], resolver)

    assert graph.callee_symbols_of(caller.id) == {a.id, b.id}
