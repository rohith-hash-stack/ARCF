from code_intelligence.symbol_index import SymbolIndex
from context.anchor_classifier import (
    AnchorTier,
    TIER_CONFIDENCE,
    classify_file_anchors,
    classify_morphological_anchors,
    classify_symbol_anchors,
    decay_confidence,
    generate_morphological_candidates,
    hop_from_reason,
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


def test_exact_identifier_promotes_to_tier1() -> None:
    index = SymbolIndex([_symbol("LazyLoader"), _symbol("load_strategy")])

    anchors = classify_symbol_anchors("Explain how LazyLoader works internally", index)

    tier1 = [a for a in anchors if a.tier is AnchorTier.EXACT]
    assert {a.name for a in tier1} == {"LazyLoader"}
    assert tier1[0].confidence == 1.0


def test_tier1_excludes_name_from_tier3() -> None:
    index = SymbolIndex([_symbol("load_strategy")])

    anchors = classify_symbol_anchors("Explain how load_strategy works", index)

    names_by_tier = {a.tier: a.name for a in anchors}
    assert names_by_tier[AnchorTier.EXACT] == "load_strategy"
    assert AnchorTier.LEXICAL not in names_by_tier


def test_quoted_token_can_promote_to_tier1() -> None:
    index = SymbolIndex([_symbol("LazyLoader")])

    anchors = classify_symbol_anchors("Explain `LazyLoader` briefly", index)

    assert any(a.tier is AnchorTier.EXACT and a.name == "LazyLoader" for a in anchors)


def test_lexical_only_match_lands_in_tier3() -> None:
    # "load_strategy" shares a 6-char prefix with "strategies" but never
    # appears as its own literal token in the query, so it's a Tier 3
    # (prefix/substring) match, not a Tier 1 (exact word) one.
    index = SymbolIndex([_symbol("load_strategy")])

    anchors = classify_symbol_anchors("Explain the loading strategies used internally.", index)

    tier3 = [a for a in anchors if a.tier is AnchorTier.LEXICAL]
    assert any(a.name == "load_strategy" for a in tier3)
    assert all(a.confidence == 0.5 for a in tier3)


def test_no_probeable_words_returns_no_symbol_anchors() -> None:
    index = SymbolIndex([_symbol("LazyLoader")])

    assert classify_symbol_anchors("fix it", index) == []


def test_file_anchors_match_filenames_only() -> None:
    files = [
        ScannedFile(relative_path="orm/loading.py", extension=".py", size_bytes=1),
        ScannedFile(relative_path="dialects/mssql.py", extension=".py", size_bytes=1),
    ]

    anchors = classify_file_anchors("Explain how loading works.", files)

    assert [a.file_path for a in anchors] == ["orm/loading.py"]
    assert anchors[0].tier is AnchorTier.INCIDENTAL
    assert anchors[0].confidence == 0.35


def test_generate_morphological_candidates_reconstructs_lazyloader() -> None:
    candidates = generate_morphological_candidates("Explain how lazy loading works")

    assert "LazyLoader" in candidates


def test_generate_morphological_candidates_reconstructs_eagerloader() -> None:
    candidates = generate_morphological_candidates(
        "Explain how eager loading differs from lazy loading"
    )

    assert "EagerLoader" in candidates
    assert "LazyLoader" in candidates


def test_generate_morphological_candidates_reconstructs_leading_underscore_variant() -> None:
    # Real bug found against the actual cloned SQLAlchemy repo
    # (2026-08-08): the internal class is `_LazyLoader` (PEP 8 "internal
    # use" convention), not `LazyLoader` — a bare capitalize-and-join
    # never reaches it.
    candidates = generate_morphological_candidates("Explain how lazy loading works")

    assert "_LazyLoader" in candidates


def test_classify_morphological_anchors_finds_underscore_prefixed_real_symbol() -> None:
    index = SymbolIndex([_symbol("_LazyLoader")])

    anchors = classify_morphological_anchors("Explain how lazy loading works internally", index)

    assert any(a.name == "_LazyLoader" for a in anchors)


def test_generate_morphological_candidates_is_bounded() -> None:
    long_query = " ".join(f"wordnumber{i}ing" for i in range(200))

    candidates = generate_morphological_candidates(long_query)

    assert len(candidates) <= 100


def test_classify_morphological_anchors_only_keeps_real_symbols() -> None:
    index = SymbolIndex([_symbol("LazyLoader"), _symbol("EagerLoader")])

    anchors = classify_morphological_anchors(
        "Explain how lazy loading differs from eager loading internally.", index
    )

    names = {a.name for a in anchors}
    assert names == {"LazyLoader", "EagerLoader"}
    assert all(a.tier is AnchorTier.EXACT and a.confidence == 1.0 for a in anchors)


def test_classify_morphological_anchors_finds_nothing_when_no_real_match() -> None:
    index = SymbolIndex([_symbol("SomeUnrelatedThing")])

    anchors = classify_morphological_anchors("Explain how lazy loading works", index)

    assert anchors == []


def test_classify_symbol_anchors_promotes_morphological_match_to_tier1() -> None:
    # No literal word in the query equals "LazyLoader" exactly, and no
    # quoted/backtick token names it either — only the morphological
    # reconstruction path can find it.
    index = SymbolIndex([_symbol("LazyLoader"), _symbol("apply_strategy_workaround")])

    anchors = classify_symbol_anchors(
        "Explain how lazy loading differs from eager loading for strategies.", index
    )

    tier1_names = {a.name for a in anchors if a.tier is AnchorTier.EXACT}
    assert "LazyLoader" in tier1_names
    # apply_strategy_workaround only lexically matches ("strate" prefix),
    # never gets morphologically reconstructed — stays Tier 3.
    tier3_names = {a.name for a in anchors if a.tier is AnchorTier.LEXICAL}
    assert "apply_strategy_workaround" in tier3_names


def test_classify_symbol_anchors_excludes_ambiguous_exact_match() -> None:
    # Real regression found on the actual Consul repo (2026-08-08): the
    # literal word "request" is a real exact identifier match, but so
    # generic it's shared by many unrelated classes across a real
    # codebase — trusting it at Tier 1 confidence added 66 unrelated
    # files on that run. 6 unrelated symbols here (over the 5-match cap)
    # reproduces the same shape.
    ambiguous = [_symbol("request", file_path=f"pkg_{i}/thing.py") for i in range(6)]
    precise = [_symbol("LazyLoader")]
    index = SymbolIndex([*ambiguous, *precise])

    anchors = classify_symbol_anchors("Explain how the request and LazyLoader interact.", index)

    tier1_names = {a.name for a in anchors if a.tier is AnchorTier.EXACT}
    assert "request" not in tier1_names
    assert "LazyLoader" in tier1_names


def test_classify_symbol_anchors_keeps_exact_match_at_the_ambiguity_boundary() -> None:
    # Exactly 5 matches (the cap itself) must still be trusted — only
    # matches strictly beyond the cap should be excluded.
    index = SymbolIndex([_symbol("Depends", file_path=f"m{i}.py") for i in range(5)])

    anchors = classify_symbol_anchors("Explain how Depends works", index)

    assert any(a.name == "Depends" and a.tier is AnchorTier.EXACT for a in anchors)


def test_classify_morphological_anchors_excludes_ambiguous_reconstruction() -> None:
    ambiguous = [_symbol("LazyLoader", file_path=f"pkg_{i}/thing.py") for i in range(6)]
    index = SymbolIndex(ambiguous)

    anchors = classify_morphological_anchors("Explain how lazy loading works", index)

    assert anchors == []


def test_tier_confidence_ordering_preserved_after_recalibration() -> None:
    # Tier 4's value was recalibrated from the brief's original 0.15 to
    # 0.35 after a real SQLAlchemy run showed it made canonical-file
    # ranking worse than doing nothing (see TIER_CONFIDENCE's own
    # comment) — the exact number may be revisited again, but the
    # intended ordering (exact > lexical > incidental) must hold.
    assert TIER_CONFIDENCE[AnchorTier.EXACT] == 1.0
    assert TIER_CONFIDENCE[AnchorTier.LEXICAL] == 0.5
    assert (
        0.0
        < TIER_CONFIDENCE[AnchorTier.INCIDENTAL]
        < TIER_CONFIDENCE[AnchorTier.LEXICAL]
        < TIER_CONFIDENCE[AnchorTier.EXACT]
    )


def test_hop_from_reason_defines_is_hop_zero() -> None:
    assert hop_from_reason("defines LazyLoader") == 0


def test_hop_from_reason_reads_explicit_hop_number() -> None:
    assert hop_from_reason("calls LazyLoader (hop 2)") == 2
    assert hop_from_reason("called by LazyLoader (hop 3)") == 3


def test_hop_from_reason_defaults_to_one_without_explicit_hop() -> None:
    assert hop_from_reason("calls LazyLoader") == 1
    assert hop_from_reason("extends LazyLoader") == 1


def test_decay_confidence_hop_zero_is_unchanged() -> None:
    assert decay_confidence(1.0, 0) == 1.0


def test_decay_confidence_decays_multiplicatively_per_hop() -> None:
    assert decay_confidence(1.0, 1) == 0.6
    assert decay_confidence(1.0, 2) == 0.36
    assert decay_confidence(0.5, 1) == 0.3
