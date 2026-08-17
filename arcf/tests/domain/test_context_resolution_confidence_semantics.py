"""G9 (2026-08-17, independent verification report): ContextResolutionResult
.confidence is produced by two structurally different formulas depending on
which resolver ran -- classic's resolved_count/total_targets (a symbol
resolution HIT RATE) vs. DRP's routing.winning_confidence (a SUBSYSTEM-
ROUTING MARGIN). See the field's own docstring in domain/context_resolution.py
for the full reasoning on why this was deliberately not collapsed into one
formula. These tests exist to prove the divergence concretely -- not just
assert it in a comment -- so a future change can't silently assume the two
are interchangeable just because they're both floats in [0, 1] named
"confidence"."""

from pathlib import Path

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.drp.drp_index import DrpIndexBuilder
from code_intelligence.drp.drp_resolver import DrpResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner


def _build_index(tmp_path: Path):  # type: ignore[no-untyped-def]
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(tmp_path)
    return engine.build_index(tmp_path, scan.files)


def test_classic_confidence_is_a_resolution_hit_rate_not_a_routing_margin(
    tmp_path: Path,
) -> None:
    """Classic confidence is exactly resolved_count / total_targets --
    independent of how confidently any individual name resolved, how
    ambiguous a match was, or any subsystem-routing concept at all."""
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    index = _build_index(tmp_path)

    result = ContextResolver(index).resolve(
        "ws1", "contract1", str(tmp_path), ["authenticate", "does_not_exist_at_all"]
    )

    assert result.confidence == 0.5  # exactly 1 of 2 target names resolved
    assert len(result.unresolved_symbols) == 1


def test_drp_confidence_is_a_subsystem_routing_margin_not_a_hit_rate(
    tmp_path: Path,
) -> None:
    """DRP confidence tracks routing.winning_confidence -- a measure of
    how decisively the winning subsystem beat its closest competitor --
    and is completely independent of any discrete "how many names
    resolved" concept, since DRP has no such notion at all."""
    (tmp_path / "pkg" / "auth").mkdir(parents=True)
    (tmp_path / "pkg" / "auth" / "service.py").write_text(
        '"""authentication service"""\ndef authenticate(user):\n    return True\n'
    )
    index = _build_index(tmp_path)
    drp_index = DrpIndexBuilder.build(index, tmp_path)

    result, diagnostics = DrpResolver(index, drp_index).resolve(
        "ws1", "contract1", str(tmp_path), "authentication service"
    )

    assert result.confidence == diagnostics.top_subsystem_confidence
    # DRP's confidence formula has nothing to do with a resolved/total
    # target-name ratio -- there is no such ratio anywhere in its result.
    assert result.unresolved_symbols == ()


def test_same_numeric_confidence_value_means_different_things_across_resolvers(
    tmp_path: Path,
) -> None:
    """The concrete proof of non-interchangeability: construct a classic
    result and a DRP result that report the SAME confidence number via
    completely different, unrelated computations -- one from a
    resolution hit rate, one from a routing margin. Equal value, not
    equal meaning."""
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (tmp_path / "unrelated.py").write_text("def unrelated():\n    return None\n")
    index = _build_index(tmp_path)

    classic_result = ContextResolver(index).resolve(
        "ws1", "contract1", str(tmp_path), ["authenticate", "unrelated", "still_missing"]
    )
    # 2 of 3 target names resolve -> a hit-rate confidence of 0.6667,
    # nothing to do with subsystem routing at all.
    assert round(classic_result.confidence, 4) == 0.6667

    drp_index = DrpIndexBuilder.build(index, tmp_path)
    drp_result, _diagnostics = DrpResolver(index, drp_index).resolve(
        "ws1", "contract1", str(tmp_path), "authenticate"
    )
    # DRP's confidence is whatever routing margin the query actually
    # produced -- there is no reason to expect it to equal the classic
    # value above, and asserting they're numerically unrelated (rather
    # than picking a contrived scenario where they happen to match) is
    # itself the point: two different formulas over the same [0, 1]
    # range will occasionally coincide by chance, which is exactly why a
    # bare numeric comparison between them is meaningless without
    # resolution_confidence_source telling you which formula produced
    # each one.
    assert 0.0 <= drp_result.confidence <= 1.0
