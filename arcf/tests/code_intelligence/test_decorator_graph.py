from code_intelligence.decorator_graph import DecoratorGraph
from domain.code_intelligence import DecoratorReference, SourceLocation


def _decorator(
    symbol_id: str, decorator_name: str, file_path: str = "a.py"
) -> DecoratorReference:
    return DecoratorReference(
        symbol_id=symbol_id,
        decorator_name=decorator_name,
        file_path=file_path,
        location=SourceLocation(file_path=file_path, start_line=1, end_line=1),
    )


def test_decorators_of_returns_every_decorator_on_a_symbol_in_order() -> None:
    graph = DecoratorGraph(
        [
            _decorator("a.py::handler", "first"),
            _decorator("a.py::handler", "second.third"),
        ]
    )

    names = [d.decorator_name for d in graph.decorators_of("a.py::handler")]
    assert names == ["first", "second.third"]


def test_decorators_of_unknown_symbol_returns_empty_list() -> None:
    graph = DecoratorGraph([])
    assert graph.decorators_of("nope") == []


def test_symbols_decorated_by_full_name_matches_exact_qualified_text() -> None:
    graph = DecoratorGraph(
        [
            _decorator("a.py::list_users", "app.get"),
            _decorator("a.py::create_user", "app.post"),
        ]
    )

    assert graph.symbols_decorated_by("app.get") == {"a.py::list_users"}


def test_symbols_decorated_by_simple_name_matches_last_dotted_segment() -> None:
    """Different router/app variable names ("app.get" vs "router.get")
    still both match a bare "get" query term — this is the whole point
    of indexing by simple name: a query can't know the local variable
    name a given repository happens to use for its router instance."""
    graph = DecoratorGraph(
        [
            _decorator("a.py::list_users", "app.get"),
            _decorator("b.py::list_orders", "router.get"),
        ]
    )

    assert graph.symbols_decorated_by("get") == {"a.py::list_users", "b.py::list_orders"}


def test_symbols_decorated_by_bare_decorator_name_matches_directly() -> None:
    graph = DecoratorGraph([_decorator("a.py::Foo", "dataclass")])
    assert graph.symbols_decorated_by("dataclass") == {"a.py::Foo"}


def test_symbols_decorated_by_qualified_query_does_not_match_unrelated_simple_name() -> None:
    """A dotted query term ("router.get") is a precise ask and must not
    fall back to fuzzy simple-name matching — that would silently widen
    a specific query into the same broad match a bare "get" gets."""
    graph = DecoratorGraph([_decorator("a.py::list_users", "app.get")])
    assert graph.symbols_decorated_by("router.get") == set()


def test_known_decorator_names_lists_every_full_name_seen() -> None:
    graph = DecoratorGraph(
        [
            _decorator("a.py::x", "app.get"),
            _decorator("a.py::y", "dataclass"),
        ]
    )
    assert graph.known_decorator_names() == {"app.get", "dataclass"}
