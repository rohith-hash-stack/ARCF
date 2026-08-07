from code_intelligence.call_graph import CallGraph
from code_intelligence.candidate_selector import CandidateFileSelector
from code_intelligence.dependency_graph import DependencyGraph
from code_intelligence.import_graph import ImportGraph
from code_intelligence.inheritance_graph import InheritanceGraph
from code_intelligence.reference_resolver import ReferenceResolver
from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import (
    CallReference,
    ImportReference,
    SourceLocation,
    Symbol,
    SymbolKind,
)


def _loc(file_path: str) -> SourceLocation:
    return SourceLocation(file_path=file_path, start_line=1, end_line=1)


def _class(name: str, file_path: str, bases: list[str] | None = None) -> Symbol:
    return Symbol(
        id=f"{file_path}::{name}",
        name=name,
        qualified_name=name,
        kind=SymbolKind.CLASS,
        file_path=file_path,
        location=_loc(file_path),
        base_names=bases or [],
    )


def _function(name: str, file_path: str, kind: SymbolKind = SymbolKind.FUNCTION) -> Symbol:
    return Symbol(
        id=f"{file_path}::{name}",
        name=name,
        qualified_name=name,
        kind=kind,
        file_path=file_path,
        location=_loc(file_path),
    )


def test_playbook_example_query() -> None:
    """"Find every caller of authenticate() and every class extending
    BasePage" — answered with zero LLM involvement."""
    base_page = _class("BasePage", "pages/base.py")
    login_page = _class("LoginPage", "pages/login.py", bases=["BasePage"])
    authenticate = _function("authenticate", "auth.py", kind=SymbolKind.METHOD)
    test_login = _function("test_login", "tests/test_login.py")

    symbols = [base_page, login_page, authenticate, test_login]
    resolver = ReferenceResolver(SymbolIndex(symbols))
    call = CallReference(
        caller_id=test_login.id,
        callee_name="authenticate",
        file_path="tests/test_login.py",
        location=_loc("tests/test_login.py"),
    )

    symbol_index = SymbolIndex(symbols)
    call_graph = CallGraph([call], resolver)
    inheritance_graph = InheritanceGraph(symbols, resolver)
    dependency_graph = DependencyGraph(ImportGraph([]))
    selector = CandidateFileSelector(symbol_index, call_graph, inheritance_graph, dependency_graph)

    assert selector.callers_of("authenticate") == {"auth.py", "tests/test_login.py"}
    assert selector.subclasses_of("BasePage") == {"pages/base.py", "pages/login.py"}


def test_impacted_files_includes_the_file_itself() -> None:
    imports = [
        ImportReference(
            source_file="app.py",
            raw_module="utils",
            resolved_file_path="utils.py",
            location=_loc("app.py"),
        )
    ]
    selector = CandidateFileSelector(
        SymbolIndex([]),
        CallGraph([], ReferenceResolver(SymbolIndex([]))),
        InheritanceGraph([], ReferenceResolver(SymbolIndex([]))),
        DependencyGraph(ImportGraph(imports)),
    )
    assert selector.impacted_files("utils.py") == {"utils.py", "app.py"}


def test_callers_of_unknown_function_returns_empty_set() -> None:
    selector = CandidateFileSelector(
        SymbolIndex([]),
        CallGraph([], ReferenceResolver(SymbolIndex([]))),
        InheritanceGraph([], ReferenceResolver(SymbolIndex([]))),
        DependencyGraph(ImportGraph([])),
    )
    assert selector.callers_of("nonexistent") == set()


def test_transitive_callers_of_reaches_multi_hop_chain() -> None:
    # controller.py calls service.py calls repository.py::authenticate
    authenticate = _function("authenticate", "repository.py", kind=SymbolKind.METHOD)
    login = _function("login", "service.py", kind=SymbolKind.METHOD)
    handle_login = _function("handle_login", "controller.py", kind=SymbolKind.METHOD)
    symbols = [authenticate, login, handle_login]
    resolver = ReferenceResolver(SymbolIndex(symbols))
    calls = [
        CallReference(
            caller_id=login.id,
            callee_name="authenticate",
            file_path="service.py",
            location=_loc("service.py"),
        ),
        CallReference(
            caller_id=handle_login.id,
            callee_name="login",
            file_path="controller.py",
            location=_loc("controller.py"),
        ),
    ]
    call_graph = CallGraph(calls, resolver)
    selector = CandidateFileSelector(
        SymbolIndex(symbols),
        call_graph,
        InheritanceGraph(symbols, resolver),
        DependencyGraph(ImportGraph([])),
    )

    depth_one = selector.transitive_callers_of("authenticate", max_depth=1)
    assert depth_one == {"service.py": 1}

    unbounded = selector.transitive_callers_of("authenticate")
    assert unbounded == {"service.py": 1, "controller.py": 2}
