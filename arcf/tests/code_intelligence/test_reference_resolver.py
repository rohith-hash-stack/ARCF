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


def test_path_hint_filters_out_directory_collision() -> None:
    # Real Consul regression: two files both named cache.go, only one in
    # the directory a path-qualified entity actually pointed at.
    real = _symbol("Cache", SymbolKind.CLASS, "Cache", file_path="agent/cache/cache.go")
    unrelated = _symbol(
        "Cache", SymbolKind.CLASS, "Cache", file_path="internal/controller/cache/cache.go"
    )
    resolver = ReferenceResolver(SymbolIndex([real, unrelated]))
    result = resolver.resolve_with_disambiguation("Cache", path_hints=frozenset({"agent/cache/"}))
    assert result.ambiguous is False
    assert result.preferred == real
    assert result.resolved == [real]
    assert result.path_hint_matched is True


def test_path_hint_falls_back_to_full_set_when_it_matches_nothing() -> None:
    a = _symbol("helper", SymbolKind.FUNCTION, "module_a.helper", file_path="a.py")
    b = _symbol("helper", SymbolKind.METHOD, "Foo.helper", file_path="b.py")
    resolver = ReferenceResolver(SymbolIndex([a, b]))
    result = resolver.resolve_with_disambiguation("helper", path_hints=frozenset({"nowhere/"}))
    assert result.ambiguous is True
    assert {s.id for s in result.resolved} == {a.id, b.id}
    assert result.path_hint_matched is False


def test_path_hint_combines_with_locality_scoring_when_still_ambiguous() -> None:
    same_dir = _symbol("helper", SymbolKind.FUNCTION, "pkg/a.py", file_path="pkg/a.py")
    other_pkg_dir = _symbol("helper", SymbolKind.METHOD, "pkg/b.py", file_path="pkg/b.py")
    outside = _symbol("helper", SymbolKind.CLASS, "outside.py", file_path="outside/c.py")
    resolver = ReferenceResolver(SymbolIndex([same_dir, other_pkg_dir, outside]))
    result = resolver.resolve_with_disambiguation(
        "helper", context_files=frozenset({"pkg/context.py"}), path_hints=frozenset({"pkg/"})
    )
    assert result.ambiguous is True
    assert {s.id for s in result.resolved} == {same_dir.id, other_pkg_dir.id}


def test_path_hints_union_semantics_multiple_hints() -> None:
    # Feature 1 (query-wide spatial masking): a candidate matching ANY
    # hint passes, not requiring all -- hints from different entities in
    # the same query describe different concepts, not compounding
    # constraints on the same one.
    in_a = _symbol("helper", SymbolKind.FUNCTION, "pkg_a/helper", file_path="pkg_a/x.py")
    in_b = _symbol("helper", SymbolKind.METHOD, "pkg_b/helper", file_path="pkg_b/x.py")
    elsewhere = _symbol("helper", SymbolKind.CLASS, "pkg_c/helper", file_path="pkg_c/x.py")
    resolver = ReferenceResolver(SymbolIndex([in_a, in_b, elsewhere]))
    result = resolver.resolve_with_disambiguation(
        "helper", path_hints=frozenset({"pkg_a/", "pkg_b/"})
    )
    assert result.ambiguous is True
    assert {s.id for s in result.resolved} == {in_a.id, in_b.id}
    assert result.path_hint_matched is True


def test_permutation_fallback_recovers_single_word_from_prose() -> None:
    new_fn = _symbol("New", SymbolKind.FUNCTION, "New", file_path="agent/cache/cache.go")
    resolver = ReferenceResolver(SymbolIndex([new_fn]))
    result = resolver.resolve_with_disambiguation("New function")
    assert result.resolved == [new_fn]
    assert result.preferred == new_fn
    assert result.permutation_matched == "New"


def test_permutation_fallback_recovers_pascal_case_compound() -> None:
    check_listener = _symbol(
        "CheckListener", SymbolKind.CLASS, "CheckListener", file_path="agent/checks/listener.go"
    )
    resolver = ReferenceResolver(SymbolIndex([check_listener]))
    result = resolver.resolve_with_disambiguation("service check listeners")
    assert result.preferred == check_listener
    assert result.permutation_matched == "CheckListener"


def test_permutation_fallback_not_attempted_for_single_word_names() -> None:
    # A clean, single-token name that just doesn't exist stays
    # unresolved -- permutation is only for prose (multi-word) input.
    resolver = ReferenceResolver(SymbolIndex([]))
    result = resolver.resolve_with_disambiguation("nonexistent")
    assert result.resolved == []
    assert result.permutation_matched is None


def test_permutation_fallback_leaves_directly_resolvable_names_untouched() -> None:
    symbol = _symbol("authenticate", SymbolKind.METHOD, "AuthService.authenticate")
    resolver = ReferenceResolver(SymbolIndex([symbol]))
    result = resolver.resolve_with_disambiguation("authenticate")
    assert result.permutation_matched is None
    assert result.preferred == symbol


def test_permutation_fallback_returns_unresolved_when_no_candidate_matches() -> None:
    resolver = ReferenceResolver(SymbolIndex([]))
    result = resolver.resolve_with_disambiguation("totally unrelated prose here")
    assert result.resolved == []
    assert result.preferred is None
    assert result.permutation_matched is None
