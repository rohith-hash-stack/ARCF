from code_intelligence.symbol_index import SymbolIndex
from context.lexical_symbol_probe import (
    probe_file_paths,
    probe_symbol_names,
    probe_symbol_names_ranked,
    shares_lexical_root,
)
from domain.code_intelligence import SourceLocation, Symbol, SymbolKind
from workspace.scanner import ScannedFile


def _symbol(name: str, file_path: str = "a.py") -> Symbol:
    return Symbol(
        id=f"{file_path}::{name}#1",
        name=name,
        qualified_name=name,
        kind=SymbolKind.FUNCTION,
        file_path=file_path,
        location=SourceLocation(file_path=file_path, start_line=1, end_line=1),
    )


def test_probe_symbol_names_matches_via_shared_prefix() -> None:
    index = SymbolIndex([_symbol("Dependant"), _symbol("Depends"), _symbol("unrelated_thing")])

    matched = probe_symbol_names(
        "Add support for a custom dependency cache invalidation strategy", index
    )

    assert set(matched) == {"Dependant", "Depends"}


def test_probe_symbol_names_returns_nothing_for_only_short_or_stopword_tokens() -> None:
    index = SymbolIndex([_symbol("Dependant")])

    matched = probe_symbol_names("How does it work", index)

    assert matched == []


def test_probe_symbol_names_returns_real_names_only() -> None:
    index = SymbolIndex([_symbol("Dependant")])

    matched = probe_symbol_names("Explain how dependency injection works", index)

    assert matched == ["Dependant"]
    assert all(name in {s.name for s in index.all()} for name in matched)


def test_probe_symbol_names_is_capped() -> None:
    symbols = [_symbol(f"dependency_helper_{i}") for i in range(50)]
    index = SymbolIndex(symbols)

    matched = probe_symbol_names("Fix the dependency handling", index)

    assert len(matched) <= 20


def test_probe_symbol_names_excludes_wildly_ambiguous_names() -> None:
    """Real repro from an actual crash: a lexically-probed name that
    exactly matches dozens of unrelated symbols across a large monorepo
    (e.g. "middleware" recurring in many unrelated example apps) is not a
    precise signal — it's noise, and feeding it through to full
    resolution turned into one independent call-graph traversal per
    match, which alone caused a MemoryError on a 59k-symbol real
    repository. A handful of same-named overloads/re-exports (a
    genuinely common, benign pattern) should still pass through."""
    ambiguous = [_symbol("middleware", file_path=f"app_{i}/middleware.py") for i in range(10)]
    precise = [_symbol("Dependant"), _symbol("Depends")]
    index = SymbolIndex([*ambiguous, *precise])

    matched = probe_symbol_names(
        "Add a new middleware option for custom dependency handling", index
    )

    assert "middleware" not in matched
    assert set(matched) == {"Dependant", "Depends"}


def test_probe_symbol_names_allows_a_small_number_of_same_named_overloads() -> None:
    index = SymbolIndex(
        [_symbol("Depends", file_path=f"m{i}.py") for i in range(3)]
    )

    matched = probe_symbol_names("Explain how dependency injection works", index)

    assert matched == ["Depends"]


def test_probe_symbol_names_ranked_prefers_multi_prefix_match_over_scan_order() -> None:
    """ARCF candidate-ranking experiment (2026-08-08): real repro of the
    SQLAlchemy localization run's failure — 25 noise symbols matching
    only one query prefix precede, in scan order, a single symbol
    matching two. The unranked cap (first-20-encountered) drops it;
    ranked selection (more distinct prefixes matched wins) keeps it."""
    noise = [_symbol(f"dependency_helper_{i}") for i in range(25)]
    target = _symbol("dependency_handling_util")
    index = SymbolIndex([*noise, target])
    query = "Fix the dependency handling issue please"

    unranked = probe_symbol_names(query, index)
    ranked = probe_symbol_names_ranked(query, index)

    assert "dependency_handling_util" not in unranked
    assert "dependency_handling_util" in ranked


def test_probe_symbol_names_ranked_still_excludes_wildly_ambiguous_names() -> None:
    ambiguous = [_symbol("middleware", file_path=f"app_{i}/middleware.py") for i in range(10)]
    precise = [_symbol("Dependant"), _symbol("Depends")]
    index = SymbolIndex([*ambiguous, *precise])

    matched = probe_symbol_names_ranked(
        "Add a new middleware option for custom dependency handling", index
    )

    assert "middleware" not in matched
    assert set(matched) == {"Dependant", "Depends"}


def test_probe_symbol_names_ranked_respects_restrict_to_prefixes() -> None:
    index = SymbolIndex(
        [_symbol("load_strategy", file_path="orm/strategies.py"),
         _symbol("apply_strategy_workaround", file_path="dialects/mssql.py")]
    )

    matched = probe_symbol_names_ranked(
        "Explain the loading strategies used internally.",
        index,
        restrict_to_prefixes=("orm/",),
    )

    assert matched == ["load_strategy"]


def test_probe_symbol_names_ranked_empty_request_returns_nothing() -> None:
    index = SymbolIndex([_symbol("Dependant")])

    assert probe_symbol_names_ranked("", index) == []


def test_probe_file_paths_matches_basename_not_directory() -> None:
    files = [
        ScannedFile(relative_path="src/deps/dependency_resolver.py", extension=".py", size_bytes=1),
        ScannedFile(relative_path="src/dependencies/resolver.py", extension=".py", size_bytes=1),
    ]

    matched = probe_file_paths("Add a custom dependency cache invalidation strategy", files)

    assert matched == ["src/deps/dependency_resolver.py"]


def test_probe_file_paths_no_match_returns_empty() -> None:
    files = [ScannedFile(relative_path="src/widgets/checkout.py", extension=".py", size_bytes=1)]

    matched = probe_file_paths("Explain how logging works", files)

    assert matched == []


def test_probe_empty_request_returns_nothing() -> None:
    index = SymbolIndex([_symbol("Dependant")])
    files = [ScannedFile(relative_path="dependency_resolver.py", extension=".py", size_bytes=1)]

    assert probe_symbol_names("", index) == []
    assert probe_file_paths("", files) == []


def test_shares_lexical_root_matches_via_shared_prefix() -> None:
    assert shares_lexical_root("app.middleware", "Explain the middleware pipeline") is True


def test_shares_lexical_root_no_match_returns_false() -> None:
    assert shares_lexical_root("app.get", "Explain how logging works") is False


def test_shares_lexical_root_empty_request_returns_false() -> None:
    assert shares_lexical_root("app.route", "") is False
