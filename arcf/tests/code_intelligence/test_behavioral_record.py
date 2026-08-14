from code_intelligence.behavioral_record import BehavioralRecordBuilder
from code_intelligence.call_graph import CallGraph
from code_intelligence.reference_resolver import ReferenceResolver
from code_intelligence.symbol_index import SymbolIndex
from domain.behavioral_record import DependencyDepth
from domain.code_intelligence import (
    CallReference,
    FileAnalysis,
    ImportReference,
    ImportResolutionKind,
    SourceLocation,
    Symbol,
    SymbolKind,
)


def _function(name: str, file_path: str, qualified_name: str | None = None) -> Symbol:
    return Symbol(
        id=f"{file_path}::{qualified_name or name}",
        name=name,
        qualified_name=qualified_name or name,
        kind=SymbolKind.FUNCTION,
        file_path=file_path,
        location=SourceLocation(file_path=file_path, start_line=10, end_line=14),
    )


def _call(caller_id: str | None, callee_name: str, file_path: str) -> CallReference:
    return CallReference(
        caller_id=caller_id,
        callee_name=callee_name,
        file_path=file_path,
        location=SourceLocation(file_path=file_path, start_line=12, end_line=12),
    )


def test_build_returns_none_for_unknown_symbol() -> None:
    empty_index = SymbolIndex([])
    builder = BehavioralRecordBuilder(
        empty_index, CallGraph([], ReferenceResolver(empty_index)), {}
    )
    assert builder.build("nope") is None


def test_build_returns_none_for_non_callable_symbol() -> None:
    cls = Symbol(
        id="a.py::Foo",
        name="Foo",
        qualified_name="Foo",
        kind=SymbolKind.CLASS,
        file_path="a.py",
        location=SourceLocation(file_path="a.py", start_line=1, end_line=1),
    )
    symbol_index = SymbolIndex([cls])
    builder = BehavioralRecordBuilder(
        symbol_index, CallGraph([], ReferenceResolver(symbol_index)), {}
    )
    assert builder.build(cls.id) is None


def test_line_count_and_direct_call_count_are_structural() -> None:
    login = _function("login", "service.py")
    authenticate = _function("authenticate", "auth.py")
    symbol_index = SymbolIndex([login, authenticate])
    resolver = ReferenceResolver(symbol_index)
    calls = [_call(login.id, "authenticate", "service.py")]
    graph = CallGraph(calls, resolver)
    builder = BehavioralRecordBuilder(symbol_index, graph, {})

    record = builder.build(login.id)
    assert record is not None
    assert record.complexity.line_count == 5  # 14 - 10 + 1
    assert record.complexity.direct_call_count == 1
    assert record.direct_callees == [authenticate.id]


def test_direct_callers_reflects_reverse_edge() -> None:
    login = _function("login", "service.py")
    authenticate = _function("authenticate", "auth.py")
    symbol_index = SymbolIndex([login, authenticate])
    resolver = ReferenceResolver(symbol_index)
    calls = [_call(login.id, "authenticate", "service.py")]
    graph = CallGraph(calls, resolver)
    builder = BehavioralRecordBuilder(symbol_index, graph, {})

    record = builder.build(authenticate.id)
    assert record is not None
    assert record.direct_callers == [login.id]


def test_indirect_callees_bounded_by_max_hops_and_flags_truncation() -> None:
    a = _function("a", "a.py")
    b = _function("b", "b.py")
    c = _function("c", "c.py")
    d = _function("d", "d.py")
    symbol_index = SymbolIndex([a, b, c, d])
    resolver = ReferenceResolver(symbol_index)
    calls = [
        _call(a.id, "b", "a.py"),
        _call(b.id, "c", "b.py"),
        _call(c.id, "d", "c.py"),
    ]
    graph = CallGraph(calls, resolver)

    unbounded = BehavioralRecordBuilder(symbol_index, graph, {}, max_indirect_hops=10).build(a.id)
    assert unbounded is not None
    assert [t.symbol_id for t in unbounded.indirect_callees] == [b.id, c.id, d.id]
    assert unbounded.dependency_depth == DependencyDepth(hops=3, truncated=False)

    bounded = BehavioralRecordBuilder(symbol_index, graph, {}, max_indirect_hops=2).build(a.id)
    assert bounded is not None
    assert [t.symbol_id for t in bounded.indirect_callees] == [b.id, c.id]
    assert bounded.dependency_depth.hops == 2
    assert bounded.dependency_depth.truncated is True


def test_ambiguous_calls_empty_and_not_disambiguation_aware_on_default_graph() -> None:
    a = _function("helper", "a.py")
    b = _function("helper", "b.py")
    caller = _function("run", "main.py")
    symbol_index = SymbolIndex([a, b, caller])
    resolver = ReferenceResolver(symbol_index)
    calls = [_call(caller.id, "helper", "main.py")]
    graph = CallGraph(calls, resolver)  # default path, no disambiguation

    record = BehavioralRecordBuilder(symbol_index, graph, {}).build(caller.id)
    assert record is not None
    assert record.ambiguous_calls == []
    assert record.disambiguation_aware is False


def test_ambiguous_calls_populated_and_disambiguation_aware_when_flag_used() -> None:
    tied_a = _function("helper", "pkg1/a.go")
    tied_b = _function("helper", "pkg2/b.go")
    caller = _function("run", "pkg3/main.go")
    symbol_index = SymbolIndex([tied_a, tied_b, caller])
    resolver = ReferenceResolver(symbol_index)
    calls = [_call(caller.id, "helper", "pkg3/main.go")]
    graph = CallGraph(calls, resolver, mandatory_disambiguation=True)

    record = BehavioralRecordBuilder(symbol_index, graph, {}).build(caller.id)
    assert record is not None
    assert record.disambiguation_aware is True
    [ambiguous] = record.ambiguous_calls
    assert ambiguous.callee_name == "helper"
    assert ambiguous.candidates == sorted([tied_a.id, tied_b.id])


def test_file_imports_and_external_libraries_are_file_scoped() -> None:
    caller = _function("run", "service.py")
    symbol_index = SymbolIndex([caller])
    resolver = ReferenceResolver(symbol_index)
    graph = CallGraph([], resolver)

    requests_import = ImportReference(
        source_file="service.py",
        raw_module="requests",
        location=SourceLocation(file_path="service.py", start_line=1, end_line=1),
        resolved_kind=ImportResolutionKind.EXTERNAL,
        resolved_library="requests",
    )
    unresolved_import = ImportReference(
        source_file="service.py",
        raw_module="mystery",
        location=SourceLocation(file_path="service.py", start_line=2, end_line=2),
    )
    file_analyses = {
        "service.py": FileAnalysis(
            file_path="service.py",
            language="python",
            imports=[requests_import, unresolved_import],
        )
    }

    record = BehavioralRecordBuilder(symbol_index, graph, file_analyses).build(caller.id)
    assert record is not None
    assert record.language == "python"
    assert record.file_import_ids == [requests_import.id, unresolved_import.id]
    assert record.external_libraries_used == ["requests"]


def test_language_defaults_to_unknown_without_file_analysis() -> None:
    caller = _function("run", "service.py")
    symbol_index = SymbolIndex([caller])
    graph = CallGraph([], ReferenceResolver(symbol_index))
    record = BehavioralRecordBuilder(symbol_index, graph, {}).build(caller.id)
    assert record is not None
    assert record.language == "unknown"
    assert record.file_import_ids == []
    assert record.external_libraries_used == []


def test_build_all_only_includes_functions_and_methods_sorted_by_id() -> None:
    cls = Symbol(
        id="a.py::Foo",
        name="Foo",
        qualified_name="Foo",
        kind=SymbolKind.CLASS,
        file_path="a.py",
        location=SourceLocation(file_path="a.py", start_line=1, end_line=1),
    )
    zeta = _function("zeta", "a.py")
    alpha = _function("alpha", "a.py")
    symbol_index = SymbolIndex([cls, zeta, alpha])
    graph = CallGraph([], ReferenceResolver(symbol_index))

    records = BehavioralRecordBuilder(symbol_index, graph, {}).build_all()
    assert [r.symbol_id for r in records] == sorted([zeta.id, alpha.id])


def test_build_all_deterministic_across_independent_builders() -> None:
    """Same acceptance test as earlier phases, applied here: identical
    input, independently constructed, byte-identical output."""
    a = _function("a", "a.py")
    b = _function("b", "b.py")
    symbol_index = SymbolIndex([a, b])
    resolver = ReferenceResolver(symbol_index)
    calls = [_call(a.id, "b", "a.py")]

    first = BehavioralRecordBuilder(symbol_index, CallGraph(calls, resolver), {}).build_all()
    second = BehavioralRecordBuilder(symbol_index, CallGraph(calls, resolver), {}).build_all()
    assert [r.model_dump() for r in first] == [r.model_dump() for r in second]
