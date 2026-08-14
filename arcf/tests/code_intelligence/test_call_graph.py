from code_intelligence.call_graph import CallGraph
from code_intelligence.import_graph import ImportGraph
from code_intelligence.reference_resolver import ReferenceResolver
from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import (
    CallReference,
    CallResolutionConfidence,
    ImportReference,
    SourceLocation,
    Symbol,
    SymbolKind,
)


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


def _chain_graph() -> tuple[CallGraph, Symbol, Symbol, Symbol]:
    # Controller.handle_login -> Service.login -> Repository.authenticate
    repository_authenticate = _function("authenticate", file_path="repository.py")
    service_login = _function("login", file_path="service.py")
    controller_handle = _function("handle_login", file_path="controller.py")
    resolver = ReferenceResolver(
        SymbolIndex([repository_authenticate, service_login, controller_handle])
    )
    calls = [
        _call(service_login.id, "authenticate", file_path="service.py"),
        _call(controller_handle.id, "login", file_path="controller.py"),
    ]
    graph = CallGraph(calls, resolver)
    return graph, repository_authenticate, service_login, controller_handle


def test_transitive_caller_symbols_of_reaches_full_chain_when_unbounded() -> None:
    graph, authenticate, login, handle_login = _chain_graph()
    result = graph.transitive_caller_symbols_of(authenticate.id)
    assert result == {
        login.id: (1, authenticate.id),
        handle_login.id: (2, login.id),
    }


def test_transitive_caller_symbols_of_respects_max_depth() -> None:
    graph, authenticate, login, handle_login = _chain_graph()
    result = graph.transitive_caller_symbols_of(authenticate.id, max_depth=1)
    assert result == {login.id: (1, authenticate.id)}


def test_transitive_callee_symbols_of_is_the_reverse_direction() -> None:
    graph, authenticate, login, handle_login = _chain_graph()
    result = graph.transitive_callee_symbols_of(handle_login.id)
    assert result == {
        login.id: (1, handle_login.id),
        authenticate.id: (2, login.id),
    }


def test_transitive_traversal_terminates_on_cycles() -> None:
    a = _function("a", file_path="a.py")
    b = _function("b", file_path="b.py")
    resolver = ReferenceResolver(SymbolIndex([a, b]))
    calls = [_call(a.id, "b", file_path="a.py"), _call(b.id, "a", file_path="b.py")]
    graph = CallGraph(calls, resolver)

    result = graph.transitive_caller_symbols_of(a.id)
    assert set(result.keys()) == {b.id}
    assert result[b.id][0] == 1


# --- ARCF-DI Phase 3: mandatory_disambiguation (opt-in, default False) ----


def test_default_path_leaves_resolution_confidence_unset() -> None:
    """Unchanged behavior is the whole point of the flag defaulting to
    False -- resolved_calls exists, but every entry stays at Phase 1's
    schema defaults until a caller opts in."""
    authenticate = _function("authenticate", file_path="auth.py")
    resolver = ReferenceResolver(SymbolIndex([authenticate]))
    call = _call(None, "authenticate", file_path="script.py")
    graph = CallGraph([call], resolver)

    [resolved] = graph.resolved_calls
    assert resolved.resolution_confidence is None
    assert resolved.candidates == []


def test_mandatory_disambiguation_single_candidate_tagged_exact_qualified() -> None:
    symbol = Symbol(
        id="a.py::AuthService.authenticate",
        name="authenticate",
        qualified_name="AuthService.authenticate",
        kind=SymbolKind.METHOD,
        file_path="a.py",
        location=SourceLocation(file_path="a.py", start_line=1, end_line=1),
    )
    resolver = ReferenceResolver(SymbolIndex([symbol]))
    call = _call(None, "AuthService.authenticate", file_path="caller.py")
    graph = CallGraph([call], resolver, mandatory_disambiguation=True)

    [resolved] = graph.resolved_calls
    assert resolved.resolution_confidence is CallResolutionConfidence.EXACT_QUALIFIED
    assert graph.caller_files_of(symbol.id) == {"caller.py"}


def test_mandatory_disambiguation_single_candidate_tagged_simple_name_fallback() -> None:
    # qualified_name != the bare "authenticate" being called, so the
    # exact-match tier misses and the simple-name fallback finds it --
    # same setup test_reference_resolver.py's own fallback test uses.
    symbol = Symbol(
        id="auth.py::AuthService.authenticate",
        name="authenticate",
        qualified_name="AuthService.authenticate",
        kind=SymbolKind.METHOD,
        file_path="auth.py",
        location=SourceLocation(file_path="auth.py", start_line=1, end_line=1),
    )
    resolver = ReferenceResolver(SymbolIndex([symbol]))
    call = _call(None, "authenticate", file_path="caller.py")
    graph = CallGraph([call], resolver, mandatory_disambiguation=True)

    [resolved] = graph.resolved_calls
    assert resolved.resolution_confidence is CallResolutionConfidence.SIMPLE_NAME_FALLBACK


def test_mandatory_disambiguation_narrows_via_same_file_locality() -> None:
    """The New()-collision scenario, but with a real locality signal this
    time: the caller lives in the same file as one of the two same-named
    candidates. Default path fans out to both; mandatory_disambiguation
    narrows to just the local one."""
    local_helper = _function("helper", file_path="pkg/main.py")
    unrelated_helper = _function("helper", file_path="other/thing.py")
    caller = _function("run", file_path="pkg/main.py")
    resolver = ReferenceResolver(SymbolIndex([local_helper, unrelated_helper, caller]))
    call = _call(caller.id, "helper", file_path="pkg/main.py")

    default_graph = CallGraph([call], resolver)
    assert default_graph.callee_symbols_of(caller.id) == {local_helper.id, unrelated_helper.id}

    disambiguated_graph = CallGraph([call], resolver, mandatory_disambiguation=True)
    assert disambiguated_graph.callee_symbols_of(caller.id) == {local_helper.id}
    [resolved] = disambiguated_graph.resolved_calls
    assert resolved.resolution_confidence is CallResolutionConfidence.LOCALITY_DISAMBIGUATED
    assert resolved.candidates == []


def test_mandatory_disambiguation_preserves_fan_out_when_genuinely_ambiguous() -> None:
    """No locality signal distinguishes either candidate from the caller's
    own file/directory, and there's no import graph -- mandatory_
    disambiguation must NOT sacrifice recall it has no evidence to
    justify narrowing. Topology stays identical to the default path;
    only the audit trail (candidates/resolution_confidence) is new."""
    a = _function("helper", file_path="pkg1/a.go")
    b = _function("helper", file_path="pkg2/b.go")
    caller = _function("Run", file_path="pkg3/main.go")
    resolver = ReferenceResolver(SymbolIndex([a, b, caller]))
    call = _call(caller.id, "helper", file_path="pkg3/main.go")

    default_graph = CallGraph([call], resolver)
    disambiguated_graph = CallGraph([call], resolver, mandatory_disambiguation=True)

    assert (
        default_graph.callee_symbols_of(caller.id)
        == disambiguated_graph.callee_symbols_of(caller.id)
        == {a.id, b.id}
    )
    [resolved] = disambiguated_graph.resolved_calls
    assert resolved.resolution_confidence is CallResolutionConfidence.AMBIGUOUS_MULTI
    assert resolved.candidates == sorted([a.id, b.id])


def test_mandatory_disambiguation_uses_import_graph_locality_when_no_file_signal() -> None:
    local_helper = _function("helper", file_path="pkg/impl.py")
    unrelated_helper = _function("helper", file_path="other/thing.py")
    caller = _function("run", file_path="pkg/main.py")
    resolver = ReferenceResolver(SymbolIndex([local_helper, unrelated_helper, caller]))
    call = _call(caller.id, "helper", file_path="pkg/main.py")
    import_ref = ImportReference(
        source_file="pkg/main.py",
        raw_module="pkg.impl",
        resolved_file_path="pkg/impl.py",
        location=SourceLocation(file_path="pkg/main.py", start_line=1, end_line=1),
    )
    import_graph = ImportGraph([import_ref])

    graph = CallGraph(
        [call], resolver, import_graph=import_graph, mandatory_disambiguation=True
    )
    assert graph.callee_symbols_of(caller.id) == {local_helper.id}
    [resolved] = graph.resolved_calls
    assert resolved.resolution_confidence is CallResolutionConfidence.LOCALITY_DISAMBIGUATED


def test_ablation_mandatory_disambiguation_matches_default_topology_except_where_narrowed() -> None:
    """Same-process ablation, this project's own established verification
    discipline for a ranking/resolution change: identical calls/resolver,
    flag on vs off, one process. Narrower only where locality actually
    had something to work with; byte-identical everywhere else."""
    local_helper = _function("helper", file_path="pkg/main.py")
    unrelated_helper = _function("helper", file_path="other/thing.py")
    caller_with_locality = _function("run", file_path="pkg/main.py")

    tied_a = _function("Ambiguous", file_path="pkg1/a.go")
    tied_b = _function("Ambiguous", file_path="pkg2/b.go")
    caller_without_locality = _function("Run", file_path="pkg3/main.go")

    resolver = ReferenceResolver(
        SymbolIndex(
            [
                local_helper, unrelated_helper, caller_with_locality,
                tied_a, tied_b, caller_without_locality,
            ]
        )
    )
    calls = [
        _call(caller_with_locality.id, "helper", file_path="pkg/main.py"),
        _call(caller_without_locality.id, "Ambiguous", file_path="pkg3/main.go"),
    ]

    default_graph = CallGraph(calls, resolver)
    disambiguated_graph = CallGraph(calls, resolver, mandatory_disambiguation=True)

    # Genuinely ambiguous call: identical topology, both modes.
    assert (
        default_graph.callee_symbols_of(caller_without_locality.id)
        == disambiguated_graph.callee_symbols_of(caller_without_locality.id)
        == {tied_a.id, tied_b.id}
    )
    # Locality-resolvable call: narrower under mandatory_disambiguation.
    assert default_graph.callee_symbols_of(caller_with_locality.id) == {
        local_helper.id,
        unrelated_helper.id,
    }
    assert disambiguated_graph.callee_symbols_of(caller_with_locality.id) == {local_helper.id}


# --- ARCF-DI Phase 7: transitive_*_trace (graph traversal audit log) ----


def test_trace_agrees_with_the_untraced_result_it_wraps() -> None:
    graph, authenticate, login, handle_login = _chain_graph()
    result = graph.transitive_caller_symbols_of(authenticate.id)
    trace = graph.transitive_caller_trace(authenticate.id)

    assert {step.node_visited: (step.hop, step.reached_via) for step in trace} == result


def test_trace_steps_are_sequential_and_hop_ordered() -> None:
    graph, authenticate, login, handle_login = _chain_graph()
    trace = graph.transitive_caller_trace(authenticate.id)

    assert [step.step for step in trace] == list(range(1, len(trace) + 1))
    assert [step.hop for step in trace] == sorted(step.hop for step in trace)


def test_trace_records_reached_via_matching_the_chain() -> None:
    graph, authenticate, login, handle_login = _chain_graph()
    trace = graph.transitive_caller_trace(authenticate.id)

    by_node = {step.node_visited: step for step in trace}
    assert by_node[login.id].reached_via == authenticate.id
    assert by_node[handle_login.id].reached_via == login.id


def test_trace_respects_max_depth() -> None:
    graph, authenticate, login, handle_login = _chain_graph()
    trace = graph.transitive_caller_trace(authenticate.id, max_depth=1)

    assert [step.node_visited for step in trace] == [login.id]


def test_callee_trace_is_the_reverse_direction() -> None:
    graph, authenticate, login, handle_login = _chain_graph()
    trace = graph.transitive_callee_trace(handle_login.id)

    assert [step.node_visited for step in trace] == [login.id, authenticate.id]


def test_trace_terminates_on_cycles_same_as_untraced() -> None:
    a = _function("a", file_path="a.py")
    b = _function("b", file_path="b.py")
    resolver = ReferenceResolver(SymbolIndex([a, b]))
    calls = [_call(a.id, "b", file_path="a.py"), _call(b.id, "a", file_path="b.py")]
    graph = CallGraph(calls, resolver)

    trace = graph.transitive_caller_trace(a.id)
    assert [step.node_visited for step in trace] == [b.id]


def test_trace_deterministic_across_independent_calls() -> None:
    """Same acceptance test as every prior phase: identical graph,
    independently queried, byte-identical trace."""
    graph, authenticate, _login, _handle_login = _chain_graph()
    first = graph.transitive_caller_trace(authenticate.id)
    second = graph.transitive_caller_trace(authenticate.id)
    assert first == second


def test_layered_bfs_public_behavior_unchanged_by_the_traced_refactor() -> None:
    """_layered_bfs is now a thin wrapper over _layered_bfs_traced --
    this pins its return value to exactly what it was before Phase 7,
    on top of the existing transitive_*_symbols_of tests above."""
    graph, authenticate, login, handle_login = _chain_graph()
    assert graph.transitive_caller_symbols_of(authenticate.id) == {
        login.id: (1, authenticate.id),
        handle_login.id: (2, login.id),
    }
