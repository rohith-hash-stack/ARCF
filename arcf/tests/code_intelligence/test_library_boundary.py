from code_intelligence.library_boundary import LibraryBoundaryClassifier
from domain.code_intelligence import (
    DeclaredDependency,
    ImportReference,
    ImportResolutionKind,
    SourceLocation,
)


def _loc(file_path: str = "a.py") -> SourceLocation:
    return SourceLocation(file_path=file_path, start_line=1, end_line=1)


def _dep(name: str, ecosystem: str) -> DeclaredDependency:
    return DeclaredDependency(name=name, ecosystem=ecosystem, manifest_location=_loc("manifest"))


def test_already_resolved_import_is_repository_regardless_of_declared_deps() -> None:
    imp = ImportReference(
        source_file="a.py",
        raw_module="./sibling",
        resolved_file_path="pkg/sibling.py",
        location=_loc(),
    )
    classifier = LibraryBoundaryClassifier(dependencies=[])
    [result] = classifier.classify([imp], language="python")
    assert result.resolved_kind is ImportResolutionKind.REPOSITORY


def test_python_stdlib_module_classified_without_any_manifest() -> None:
    imp = ImportReference(source_file="a.py", raw_module="os.path", location=_loc())
    classifier = LibraryBoundaryClassifier(dependencies=[])
    [result] = classifier.classify([imp], language="python")
    assert result.resolved_kind is ImportResolutionKind.STDLIB


def test_python_import_matching_declared_dependency_is_external() -> None:
    imp = ImportReference(source_file="a.py", raw_module="requests", location=_loc())
    classifier = LibraryBoundaryClassifier(dependencies=[_dep("requests", "pip")])
    [result] = classifier.classify([imp], language="python")
    assert result.resolved_kind is ImportResolutionKind.EXTERNAL
    assert result.resolved_library == "requests"


def test_python_import_matching_nothing_is_unresolved() -> None:
    imp = ImportReference(source_file="a.py", raw_module="some_internal_thing", location=_loc())
    classifier = LibraryBoundaryClassifier(dependencies=[_dep("requests", "pip")])
    [result] = classifier.classify([imp], language="python")
    assert result.resolved_kind is ImportResolutionKind.UNRESOLVED
    assert result.resolved_library is None


def test_npm_scoped_subpath_import_matches_declared_scoped_package() -> None:
    imp = ImportReference(
        source_file="a.ts", raw_module="@playwright/test/reporter", location=_loc("a.ts")
    )
    classifier = LibraryBoundaryClassifier(dependencies=[_dep("@playwright/test", "npm")])
    [result] = classifier.classify([imp], language="typescript")
    assert result.resolved_kind is ImportResolutionKind.EXTERNAL
    assert result.resolved_library == "@playwright/test"


def test_node_builtin_module_classified_as_stdlib() -> None:
    imp = ImportReference(source_file="a.ts", raw_module="fs", location=_loc("a.ts"))
    classifier = LibraryBoundaryClassifier(dependencies=[])
    [result] = classifier.classify([imp], language="typescript")
    assert result.resolved_kind is ImportResolutionKind.STDLIB


def test_node_prefixed_builtin_module_classified_as_stdlib() -> None:
    imp = ImportReference(source_file="a.ts", raw_module="node:fs", location=_loc("a.ts"))
    classifier = LibraryBoundaryClassifier(dependencies=[])
    [result] = classifier.classify([imp], language="typescript")
    assert result.resolved_kind is ImportResolutionKind.STDLIB


def test_go_stdlib_import_has_no_dot_in_first_segment() -> None:
    imp = ImportReference(source_file="a.go", raw_module="net/http", location=_loc("a.go"))
    classifier = LibraryBoundaryClassifier(dependencies=[])
    [result] = classifier.classify([imp], language="go")
    assert result.resolved_kind is ImportResolutionKind.STDLIB


def test_go_subpackage_import_matches_declared_module_root_by_longest_prefix() -> None:
    imp = ImportReference(
        source_file="a.go",
        raw_module="github.com/hashicorp/consul/agent/cache",
        location=_loc("a.go"),
    )
    classifier = LibraryBoundaryClassifier(
        dependencies=[_dep("github.com/hashicorp/consul", "go"), _dep("github.com/hashicorp", "go")]
    )
    [result] = classifier.classify([imp], language="go")
    assert result.resolved_kind is ImportResolutionKind.EXTERNAL
    assert result.resolved_library == "github.com/hashicorp/consul"


def test_go_import_with_dotted_domain_but_no_declared_dependency_is_unresolved() -> None:
    imp = ImportReference(
        source_file="a.go", raw_module="github.com/unknown/pkg", location=_loc("a.go")
    )
    classifier = LibraryBoundaryClassifier(dependencies=[])
    [result] = classifier.classify([imp], language="go")
    assert result.resolved_kind is ImportResolutionKind.UNRESOLVED


def test_language_without_manifest_support_never_guesses_external() -> None:
    imp = ImportReference(
        source_file="a.java", raw_module="com.fasterxml.jackson.core", location=_loc("a.java")
    )
    classifier = LibraryBoundaryClassifier(
        dependencies=[_dep("com.fasterxml.jackson.core", "maven")]
    )
    [result] = classifier.classify([imp], language="java")
    assert result.resolved_kind is ImportResolutionKind.UNRESOLVED


def test_classify_does_not_mutate_input_and_returns_frozen_copies() -> None:
    imp = ImportReference(source_file="a.py", raw_module="requests", location=_loc())
    classifier = LibraryBoundaryClassifier(dependencies=[_dep("requests", "pip")])
    [result] = classifier.classify([imp], language="python")
    assert imp.resolved_kind is None
    assert result is not imp
    assert result.resolved_kind is ImportResolutionKind.EXTERNAL
