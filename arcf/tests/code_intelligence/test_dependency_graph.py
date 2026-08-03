from code_intelligence.dependency_graph import DependencyGraph
from code_intelligence.import_graph import ImportGraph
from domain.code_intelligence import ImportReference, SourceLocation


def _import(source: str, resolved: str) -> ImportReference:
    return ImportReference(
        source_file=source,
        raw_module="whatever",
        resolved_file_path=resolved,
        location=SourceLocation(file_path=source, start_line=1, end_line=1),
    )


def test_transitive_dependencies_follow_chain() -> None:
    # a -> b -> c
    graph = ImportGraph([_import("a.py", "b.py"), _import("b.py", "c.py")])
    dep_graph = DependencyGraph(graph)
    assert dep_graph.transitive_dependencies("a.py") == {"b.py", "c.py"}


def test_impacted_by_follows_chain_in_reverse() -> None:
    # a -> b -> c ; changing c impacts b and a
    graph = ImportGraph([_import("a.py", "b.py"), _import("b.py", "c.py")])
    dep_graph = DependencyGraph(graph)
    assert dep_graph.impacted_by("c.py") == {"a.py", "b.py"}


def test_handles_cycles_without_infinite_loop() -> None:
    graph = ImportGraph([_import("a.py", "b.py"), _import("b.py", "a.py")])
    dep_graph = DependencyGraph(graph)
    assert dep_graph.transitive_dependencies("a.py") == {"a.py", "b.py"}


def test_leaf_file_has_no_dependencies() -> None:
    graph = ImportGraph([_import("a.py", "b.py")])
    dep_graph = DependencyGraph(graph)
    assert dep_graph.transitive_dependencies("b.py") == set()


def test_unimported_file_has_no_impact() -> None:
    graph = ImportGraph([_import("a.py", "b.py")])
    dep_graph = DependencyGraph(graph)
    assert dep_graph.impacted_by("a.py") == set()
