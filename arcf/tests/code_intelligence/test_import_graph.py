from code_intelligence.import_graph import ImportGraph
from domain.code_intelligence import ImportReference, SourceLocation


def _import(source: str, resolved: str | None) -> ImportReference:
    return ImportReference(
        source_file=source,
        raw_module="whatever",
        resolved_file_path=resolved,
        location=SourceLocation(file_path=source, start_line=1, end_line=1),
    )


def test_direct_edges_both_directions() -> None:
    graph = ImportGraph([_import("a.py", "b.py")])
    assert graph.imports_of("a.py") == {"b.py"}
    assert graph.importers_of("b.py") == {"a.py"}


def test_unresolved_imports_produce_no_edge() -> None:
    graph = ImportGraph([_import("a.py", None)])
    assert graph.imports_of("a.py") == set()


def test_multiple_importers_of_same_file() -> None:
    graph = ImportGraph([_import("a.py", "c.py"), _import("b.py", "c.py")])
    assert graph.importers_of("c.py") == {"a.py", "b.py"}


def test_unknown_file_returns_empty_set() -> None:
    graph = ImportGraph([])
    assert graph.imports_of("nowhere.py") == set()
    assert graph.importers_of("nowhere.py") == set()
