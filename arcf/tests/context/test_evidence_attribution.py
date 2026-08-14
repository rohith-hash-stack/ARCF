from code_intelligence.call_graph import CallGraph
from code_intelligence.reference_resolver import ReferenceResolver
from code_intelligence.symbol_index import SymbolIndex
from context.evidence_attribution import attribute_citations, resolves_cleanly
from domain.code_intelligence import (
    CallReference,
    FileAnalysis,
    ImportReference,
    ImportResolutionKind,
    SourceLocation,
    Symbol,
    SymbolKind,
)
from domain.context_package import PackagedFile


def _function(name: str, file_path: str) -> Symbol:
    return Symbol(
        id=f"{file_path}::{name}",
        name=name,
        qualified_name=name,
        kind=SymbolKind.FUNCTION,
        file_path=file_path,
        location=SourceLocation(file_path=file_path, start_line=1, end_line=5),
    )


def _call(caller_id: str | None, callee_name: str, file_path: str) -> CallReference:
    return CallReference(
        caller_id=caller_id,
        callee_name=callee_name,
        file_path=file_path,
        location=SourceLocation(file_path=file_path, start_line=3, end_line=3),
    )


def _packaged(file_path: str) -> PackagedFile:
    return PackagedFile(
        file_path=file_path,
        content="...",
        relevance_score=0.9,
        reason="matched query",
        token_count=42,
        truncated=False,
    )


def test_attribute_citations_unions_evidence_across_symbols_in_file() -> None:
    login = _function("login", "service.py")
    authenticate = _function("authenticate", "auth.py")
    symbol_index = SymbolIndex([login, authenticate])
    resolver = ReferenceResolver(symbol_index)
    calls = [_call(login.id, "authenticate", "service.py")]
    graph = CallGraph(calls, resolver)

    requests_import = ImportReference(
        source_file="service.py",
        raw_module="requests",
        location=SourceLocation(file_path="service.py", start_line=1, end_line=1),
        resolved_kind=ImportResolutionKind.EXTERNAL,
        resolved_library="requests",
    )
    file_analyses = {
        "service.py": FileAnalysis(
            file_path="service.py", language="python", imports=[requests_import]
        )
    }

    [enriched] = attribute_citations(
        [_packaged("service.py")], symbol_index, graph, file_analyses
    )
    assert authenticate.id in enriched.citations
    assert requests_import.id in enriched.citations
    assert "requests" in enriched.citations
    assert enriched.ambiguous_evidence_ids == []


def test_attribute_citations_does_not_mutate_input() -> None:
    login = _function("login", "service.py")
    symbol_index = SymbolIndex([login])
    graph = CallGraph([], ReferenceResolver(symbol_index))
    original = _packaged("service.py")

    [enriched] = attribute_citations([original], symbol_index, graph, {})
    assert original.citations == []
    assert enriched is not original


def test_attribute_citations_preserves_input_order() -> None:
    a = _function("a", "a.py")
    b = _function("b", "b.py")
    symbol_index = SymbolIndex([a, b])
    graph = CallGraph([], ReferenceResolver(symbol_index))

    packaged = [_packaged("b.py"), _packaged("a.py")]
    enriched = attribute_citations(packaged, symbol_index, graph, {})
    assert [p.file_path for p in enriched] == ["b.py", "a.py"]


def test_ambiguous_evidence_surfaced_only_with_mandatory_disambiguation() -> None:
    tied_a = _function("helper", "pkg1/a.go")
    tied_b = _function("helper", "pkg2/b.go")
    caller = _function("Run", "pkg3/main.go")
    symbol_index = SymbolIndex([tied_a, tied_b, caller])
    resolver = ReferenceResolver(symbol_index)
    calls = [_call(caller.id, "helper", "pkg3/main.go")]

    default_graph = CallGraph(calls, resolver)
    [default_enriched] = attribute_citations(
        [_packaged("pkg3/main.go")], symbol_index, default_graph, {}
    )
    assert default_enriched.ambiguous_evidence_ids == []

    disambiguated_graph = CallGraph(calls, resolver, mandatory_disambiguation=True)
    [enriched] = attribute_citations(
        [_packaged("pkg3/main.go")], symbol_index, disambiguated_graph, {}
    )
    assert enriched.ambiguous_evidence_ids != []
    assert set(enriched.ambiguous_evidence_ids) <= set(enriched.citations)


def test_resolves_cleanly_true_when_no_ambiguous_citations() -> None:
    login = _function("login", "service.py")
    authenticate = _function("authenticate", "auth.py")
    symbol_index = SymbolIndex([login, authenticate])
    resolver = ReferenceResolver(symbol_index)
    calls = [_call(login.id, "authenticate", "service.py")]
    graph = CallGraph(calls, resolver, mandatory_disambiguation=True)

    [enriched] = attribute_citations([_packaged("service.py")], symbol_index, graph, {})
    assert resolves_cleanly(enriched, graph) is True


def test_resolves_cleanly_false_when_citations_include_ambiguous_call() -> None:
    tied_a = _function("helper", "pkg1/a.go")
    tied_b = _function("helper", "pkg2/b.go")
    caller = _function("Run", "pkg3/main.go")
    symbol_index = SymbolIndex([tied_a, tied_b, caller])
    resolver = ReferenceResolver(symbol_index)
    calls = [_call(caller.id, "helper", "pkg3/main.go")]
    graph = CallGraph(calls, resolver, mandatory_disambiguation=True)

    [enriched] = attribute_citations([_packaged("pkg3/main.go")], symbol_index, graph, {})
    assert resolves_cleanly(enriched, graph) is False


def test_deterministic_across_independent_calls() -> None:
    login = _function("login", "service.py")
    authenticate = _function("authenticate", "auth.py")
    symbol_index = SymbolIndex([login, authenticate])
    resolver = ReferenceResolver(symbol_index)
    calls = [_call(login.id, "authenticate", "service.py")]
    graph = CallGraph(calls, resolver)

    first = attribute_citations([_packaged("service.py")], symbol_index, graph, {})
    second = attribute_citations([_packaged("service.py")], symbol_index, graph, {})
    assert [p.model_dump() for p in first] == [p.model_dump() for p in second]
