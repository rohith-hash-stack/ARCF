from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import SourceLocation, Symbol, SymbolKind


def _symbol(
    name: str, kind: SymbolKind, file_path: str = "a.py", qualified_name: str | None = None
) -> Symbol:
    return Symbol(
        id=f"{file_path}::{qualified_name or name}",
        name=name,
        qualified_name=qualified_name or name,
        kind=kind,
        file_path=file_path,
        location=SourceLocation(file_path=file_path, start_line=1, end_line=1),
    )


def test_find_by_name_and_qualified_name() -> None:
    foo = _symbol("foo", SymbolKind.FUNCTION)
    index = SymbolIndex([foo])
    assert index.find_by_name("foo") == [foo]
    assert index.find_by_qualified_name("foo") == [foo]
    assert index.find_by_name("bar") == []


def test_get_by_id() -> None:
    foo = _symbol("foo", SymbolKind.FUNCTION)
    index = SymbolIndex([foo])
    assert index.get(foo.id) == foo
    assert index.get("nonexistent") is None


def test_by_file() -> None:
    a = _symbol("a", SymbolKind.FUNCTION, file_path="x.py")
    b = _symbol("b", SymbolKind.FUNCTION, file_path="y.py")
    index = SymbolIndex([a, b])
    assert index.by_file("x.py") == [a]
    assert index.by_file("y.py") == [b]


def test_kind_filters() -> None:
    cls = _symbol("Foo", SymbolKind.CLASS)
    fn = _symbol("bar", SymbolKind.FUNCTION)
    method = _symbol("baz", SymbolKind.METHOD)
    iface = _symbol("Iface", SymbolKind.INTERFACE)
    index = SymbolIndex([cls, fn, method, iface])

    assert index.classes() == [cls]
    assert index.functions() == [fn]
    assert index.methods() == [method]
    assert index.interfaces() == [iface]


def test_multiple_symbols_same_name_across_files() -> None:
    a = _symbol("helper", SymbolKind.FUNCTION, file_path="a.py")
    b = _symbol("helper", SymbolKind.METHOD, file_path="b.py", qualified_name="Foo.helper")
    index = SymbolIndex([a, b])
    assert {s.id for s in index.find_by_name("helper")} == {a.id, b.id}


def test_len_and_all() -> None:
    symbols = [_symbol("a", SymbolKind.FUNCTION), _symbol("b", SymbolKind.FUNCTION)]
    index = SymbolIndex(symbols)
    assert len(index) == 2
    assert {s.id for s in index.all()} == {s.id for s in symbols}
