from code_intelligence.inheritance_graph import InheritanceGraph
from code_intelligence.reference_resolver import ReferenceResolver
from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import SourceLocation, Symbol, SymbolKind


def _class(name: str, bases: list[str] | None = None, file_path: str = "a.py") -> Symbol:
    return Symbol(
        id=f"{file_path}::{name}",
        name=name,
        qualified_name=name,
        kind=SymbolKind.CLASS,
        file_path=file_path,
        location=SourceLocation(file_path=file_path, start_line=1, end_line=1),
        base_names=bases or [],
    )


def test_finds_the_example_query_class_extending_case() -> None:
    base_page = _class("BasePage")
    login_page = _class("LoginPage", bases=["BasePage"], file_path="b.py")
    resolver = ReferenceResolver(SymbolIndex([base_page, login_page]))
    graph = InheritanceGraph([base_page, login_page], resolver)

    assert graph.direct_subclasses_of(base_page.id) == {login_page.id}
    assert graph.direct_superclasses_of(login_page.id) == {base_page.id}


def test_transitive_subclasses() -> None:
    a = _class("A")
    b = _class("B", bases=["A"])
    c = _class("C", bases=["B"])
    resolver = ReferenceResolver(SymbolIndex([a, b, c]))
    graph = InheritanceGraph([a, b, c], resolver)

    assert graph.all_subclasses_of(a.id) == {b.id, c.id}
    assert graph.all_superclasses_of(c.id) == {a.id, b.id}


def test_all_subclasses_of_respects_max_depth() -> None:
    a = _class("A")
    b = _class("B", bases=["A"])
    c = _class("C", bases=["B"])
    resolver = ReferenceResolver(SymbolIndex([a, b, c]))
    graph = InheritanceGraph([a, b, c], resolver)

    assert graph.all_subclasses_of(a.id, max_depth=1) == {b.id}
    assert graph.all_subclasses_of(a.id, max_depth=2) == {b.id, c.id}


def test_all_subclasses_of_caps_unbounded_traversal_on_a_wide_hierarchy() -> None:
    """Final closure pass (2026-08-17), Final Issue 2 / NEW-2: with
    max_depth=None (a real, reachable input via
    RetrievalTaskType.LARGE_STRUCTURAL_CHANGE), this materializes the
    full `visited` set before any caller-side cap gets a chance to
    apply -- the same unbounded-growth risk class already fixed
    elsewhere in this closure. Proves the fix: 800 direct subclasses of
    one base stay bounded well under 800."""
    base = _class("Base")
    subclasses = [_class(f"Sub{i}", bases=["Base"], file_path=f"sub{i}.py") for i in range(800)]
    symbols = [base, *subclasses]
    resolver = ReferenceResolver(SymbolIndex(symbols))
    graph = InheritanceGraph(symbols, resolver)

    result = graph.all_subclasses_of(base.id, max_depth=None)

    assert len(result) <= 500
    assert len(result) < 800


def test_external_base_class_recorded_as_unresolved() -> None:
    contract = _class("Contract", bases=["BaseModel"])
    resolver = ReferenceResolver(SymbolIndex([contract]))
    graph = InheritanceGraph([contract], resolver)

    assert graph.direct_subclasses_of(contract.id) == set()
    assert graph.unresolved_bases_of(contract.id) == ["BaseModel"]


def test_non_class_symbols_ignored() -> None:
    fn = Symbol(
        id="a.py::foo",
        name="foo",
        qualified_name="foo",
        kind=SymbolKind.FUNCTION,
        file_path="a.py",
        location=SourceLocation(file_path="a.py", start_line=1, end_line=1),
    )
    resolver = ReferenceResolver(SymbolIndex([fn]))
    graph = InheritanceGraph([fn], resolver)
    assert graph.direct_subclasses_of(fn.id) == set()
