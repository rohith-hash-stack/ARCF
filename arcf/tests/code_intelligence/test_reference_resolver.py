from code_intelligence.import_graph import ImportGraph
from code_intelligence.reference_resolver import ReferenceResolver
from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import ImportReference, SourceLocation, Symbol, SymbolKind


def _symbol(name: str, kind: SymbolKind, qualified_name: str, file_path: str = "a.py") -> Symbol:
    return Symbol(
        id=f"{file_path}::{qualified_name}",
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        file_path=file_path,
        location=SourceLocation(file_path=file_path, start_line=1, end_line=1),
    )


def test_resolves_by_exact_qualified_name() -> None:
    symbol = _symbol("authenticate", SymbolKind.METHOD, "AuthService.authenticate")
    resolver = ReferenceResolver(SymbolIndex([symbol]))
    assert resolver.resolve("AuthService.authenticate") == [symbol]


def test_falls_back_to_simple_name() -> None:
    symbol = _symbol("authenticate", SymbolKind.METHOD, "AuthService.authenticate")
    resolver = ReferenceResolver(SymbolIndex([symbol]))
    assert resolver.resolve("authenticate") == [symbol]


def test_returns_multiple_ambiguous_candidates() -> None:
    # Neither qualified_name equals the bare "helper" being resolved, so the
    # exact-match tier misses for both and the simple-name fallback finds both.
    a = _symbol("helper", SymbolKind.FUNCTION, "module_a.helper", file_path="a.py")
    b = _symbol("helper", SymbolKind.METHOD, "Foo.helper", file_path="b.py")
    resolver = ReferenceResolver(SymbolIndex([a, b]))
    results = resolver.resolve("helper")
    assert {s.id for s in results} == {a.id, b.id}


def test_filters_by_kind() -> None:
    cls = _symbol("Base", SymbolKind.CLASS, "Base")
    fn = _symbol("Base", SymbolKind.FUNCTION, "Base_other", file_path="b.py")
    resolver = ReferenceResolver(SymbolIndex([cls, fn]))
    assert resolver.resolve("Base", kinds=(SymbolKind.CLASS,)) == [cls]


def test_unresolvable_name_returns_empty_list() -> None:
    resolver = ReferenceResolver(SymbolIndex([]))
    assert resolver.resolve("nonexistent") == []


def test_disambiguation_is_unambiguous_when_only_one_candidate() -> None:
    symbol = _symbol("authenticate", SymbolKind.METHOD, "AuthService.authenticate")
    resolver = ReferenceResolver(SymbolIndex([symbol]))
    result = resolver.resolve_with_disambiguation("authenticate")
    assert result.ambiguous is False
    assert result.preferred == symbol


def test_disambiguation_stays_ambiguous_with_no_locality_signal() -> None:
    a = _symbol("helper", SymbolKind.FUNCTION, "module_a.helper", file_path="a.py")
    b = _symbol("helper", SymbolKind.METHOD, "Foo.helper", file_path="b.py")
    resolver = ReferenceResolver(SymbolIndex([a, b]))
    result = resolver.resolve_with_disambiguation("helper")
    assert result.ambiguous is True
    assert result.preferred is None
    assert {s.id for s in result.resolved} == {a.id, b.id}


def test_disambiguation_prefers_symbol_in_same_file_as_context() -> None:
    a = _symbol("helper", SymbolKind.FUNCTION, "module_a.helper", file_path="a.py")
    b = _symbol("helper", SymbolKind.METHOD, "Foo.helper", file_path="b.py")
    resolver = ReferenceResolver(SymbolIndex([a, b]))
    result = resolver.resolve_with_disambiguation("helper", context_files=frozenset({"b.py"}))
    assert result.ambiguous is False
    assert result.preferred == b


def test_disambiguation_prefers_symbol_in_same_directory_as_context() -> None:
    a = _symbol("helper", SymbolKind.FUNCTION, "pkg_a/mod.py", file_path="pkg_a/mod.py")
    b = _symbol("helper", SymbolKind.METHOD, "pkg_b/mod.py", file_path="pkg_b/mod.py")
    resolver = ReferenceResolver(SymbolIndex([a, b]))
    result = resolver.resolve_with_disambiguation(
        "helper", context_files=frozenset({"pkg_b/other.py"})
    )
    assert result.ambiguous is False
    assert result.preferred == b


def test_disambiguation_prefers_symbol_reachable_via_import_graph() -> None:
    a = _symbol("helper", SymbolKind.FUNCTION, "unrelated/a.py", file_path="unrelated/a.py")
    b = _symbol("helper", SymbolKind.METHOD, "target/b.py", file_path="target/b.py")
    resolver = ReferenceResolver(SymbolIndex([a, b]))
    import_graph = ImportGraph(
        [
            ImportReference(
                source_file="caller.py",
                raw_module="target.b",
                resolved_file_path="target/b.py",
                location=SourceLocation(file_path="caller.py", start_line=1, end_line=1),
            )
        ]
    )
    result = resolver.resolve_with_disambiguation(
        "helper", context_files=frozenset({"caller.py"}), import_graph=import_graph
    )
    assert result.ambiguous is False
    assert result.preferred == b


def test_disambiguation_stays_ambiguous_when_multiple_candidates_tie_at_same_locality() -> None:
    a = _symbol("helper", SymbolKind.FUNCTION, "pkg/a.py", file_path="pkg/a.py")
    b = _symbol("helper", SymbolKind.METHOD, "pkg/b.py", file_path="pkg/b.py")
    resolver = ReferenceResolver(SymbolIndex([a, b]))
    result = resolver.resolve_with_disambiguation(
        "helper", context_files=frozenset({"pkg/other.py"})
    )
    assert result.ambiguous is True
    assert result.preferred is None


def test_disambiguation_unresolvable_name_is_not_ambiguous() -> None:
    resolver = ReferenceResolver(SymbolIndex([]))
    result = resolver.resolve_with_disambiguation("nonexistent")
    assert result.ambiguous is False
    assert result.preferred is None
    assert result.resolved == []
