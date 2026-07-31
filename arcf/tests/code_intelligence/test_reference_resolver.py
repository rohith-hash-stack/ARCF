from code_intelligence.reference_resolver import ReferenceResolver
from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import SourceLocation, Symbol, SymbolKind


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
