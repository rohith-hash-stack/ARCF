from pathlib import Path

import pytest

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from context.packager import ContextPackager
from context.relevance_ranker import RelevanceRanker
from infrastructure.cost import CostEstimator
from infrastructure.production_gate import (
    GateName,
    ReleaseGateConfig,
    compare_collectors,
    evaluate_release,
)
from infrastructure.telemetry import TelemetryCollector
from workspace.scanner import RepositoryScanner


def _good_summary() -> dict:
    """A clean, real-shaped RunSummary with no fallback, modest
    utilization, no quality data -- what a normal production run's
    get_run_summary() looks like when nothing is wrong."""
    return {
        "event_count": 10,
        "resolve_latency_ms": {"mean": 100.0, "p50": 98.0, "p95": 120.0, "max": 130.0},
        "package_latency_ms": {"mean": 50.0, "p50": 49.0, "p95": 60.0, "max": 65.0},
        "origin_breakdown_totals": {
            "ast_direct": 10, "scoped_graph_expansion": 20, "raw_string_fallback": 0,
            "evidence_fallback_match": 0, "untagged": 0,
        },
        "overall_fallback_ratio": 0.0,
        "mean_utilization_ratio": 0.5,
        "quality_data_available": False,
        "mean_precision": None,
        "mean_recall": None,
        "min_recall": None,
    }


def _good_summary_with_quality(precision: float = 0.9, min_recall: float = 1.0) -> dict:
    summary = _good_summary()
    summary["quality_data_available"] = True
    summary["mean_precision"] = precision
    summary["mean_recall"] = min_recall
    summary["min_recall"] = min_recall
    return summary


def test_clean_run_with_no_baseline_approves_release() -> None:
    decision = evaluate_release(_good_summary())

    assert decision.approved is True
    assert decision.status == "RELEASE_APPROVED"
    for gate in decision.gate_results:
        assert gate.passed is True
    # latency/quality gates SKIP (no baseline/no ground truth), not silently pass unnoticed
    skipped_names = {g.gate_name for g in decision.gate_results if g.skipped}
    assert GateName.LATENCY in skipped_names
    assert GateName.QUALITY in skipped_names


def test_fallback_gate_rejects_synthetic_regression_only_that_gate_fails() -> None:
    summary = _good_summary()
    summary["overall_fallback_ratio"] = 0.5  # injected regression

    decision = evaluate_release(summary)

    assert decision.approved is False
    by_name = {g.gate_name: g for g in decision.gate_results}
    assert by_name[GateName.FALLBACK].passed is False
    assert "0.5" in by_name[GateName.FALLBACK].detail
    # every OTHER gate is unaffected -- passed or legitimately skipped, never failed
    assert by_name[GateName.TOKEN_BUDGET].passed is True
    assert by_name[GateName.QUALITY].skipped is True


def test_fallback_gate_skips_when_no_events_recorded() -> None:
    summary = _good_summary()
    summary["event_count"] = 0

    decision = evaluate_release(summary)

    by_name = {g.gate_name: g for g in decision.gate_results}
    assert by_name[GateName.FALLBACK].skipped is True


def test_latency_gate_rejects_synthetic_overhead_regression_vs_baseline() -> None:
    baseline = _good_summary()
    candidate = _good_summary()
    candidate["resolve_latency_ms"] = {"mean": 110.0, "p50": 108.0, "p95": 130.0, "max": 140.0}
    # (110 - 100) / 100 * 100 = 10% overhead, exceeds default 5% ceiling

    decision = evaluate_release(candidate, baseline_summary=baseline)

    assert decision.approved is False
    by_name = {g.gate_name: g for g in decision.gate_results}
    assert by_name[GateName.LATENCY].passed is False
    assert by_name[GateName.LATENCY].measured_value == 10.0
    assert by_name[GateName.FALLBACK].passed is True


def test_latency_gate_accepts_overhead_within_ceiling() -> None:
    baseline = _good_summary()
    candidate = _good_summary()
    candidate["resolve_latency_ms"] = {"mean": 103.0, "p50": 101.0, "p95": 120.0, "max": 130.0}
    # 3% overhead, within default 5% ceiling

    decision = evaluate_release(candidate, baseline_summary=baseline)

    by_name = {g.gate_name: g for g in decision.gate_results}
    assert by_name[GateName.LATENCY].passed is True
    assert decision.approved is True


def test_latency_gate_skips_when_no_baseline_supplied() -> None:
    decision = evaluate_release(_good_summary(), baseline_summary=None)
    by_name = {g.gate_name: g for g in decision.gate_results}
    assert by_name[GateName.LATENCY].skipped is True


def test_token_budget_gate_rejects_synthetic_utilization_regression() -> None:
    summary = _good_summary()
    summary["mean_utilization_ratio"] = 0.99  # exceeds default 0.95 ceiling

    decision = evaluate_release(summary)

    assert decision.approved is False
    by_name = {g.gate_name: g for g in decision.gate_results}
    assert by_name[GateName.TOKEN_BUDGET].passed is False
    assert by_name[GateName.FALLBACK].passed is True


def test_token_budget_gate_skips_when_no_utilization_data() -> None:
    summary = _good_summary()
    summary["mean_utilization_ratio"] = None

    decision = evaluate_release(summary)
    by_name = {g.gate_name: g for g in decision.gate_results}
    assert by_name[GateName.TOKEN_BUDGET].skipped is True


def test_quality_gate_rejects_synthetic_recall_regression() -> None:
    summary = _good_summary_with_quality(precision=0.9, min_recall=0.7)  # below required 1.0

    decision = evaluate_release(summary)

    assert decision.approved is False
    by_name = {g.gate_name: g for g in decision.gate_results}
    assert by_name[GateName.QUALITY].passed is False
    assert "BELOW" in by_name[GateName.QUALITY].detail
    assert by_name[GateName.FALLBACK].passed is True


def test_quality_gate_skips_when_no_ground_truth_supplied() -> None:
    decision = evaluate_release(_good_summary())
    by_name = {g.gate_name: g for g in decision.gate_results}
    assert by_name[GateName.QUALITY].skipped is True


def test_quality_gate_rejects_synthetic_precision_drop_vs_baseline() -> None:
    baseline = _good_summary_with_quality(precision=0.9, min_recall=1.0)
    candidate = _good_summary_with_quality(precision=0.5, min_recall=1.0)  # real drop

    decision = evaluate_release(candidate, baseline_summary=baseline)

    assert decision.approved is False
    by_name = {g.gate_name: g for g in decision.gate_results}
    assert by_name[GateName.QUALITY].passed is False
    assert "drop" in by_name[GateName.QUALITY].detail


def test_quality_gate_accepts_when_recall_perfect_and_no_baseline_to_compare_precision() -> None:
    summary = _good_summary_with_quality(precision=0.6, min_recall=1.0)
    decision = evaluate_release(summary)  # no baseline -- precision-drop check can't run
    by_name = {g.gate_name: g for g in decision.gate_results}
    assert by_name[GateName.QUALITY].passed is True


def test_custom_config_thresholds_are_respected() -> None:
    summary = _good_summary()
    summary["overall_fallback_ratio"] = 0.1
    strict_config = ReleaseGateConfig(max_fallback_ratio=0.0)
    lenient_config = ReleaseGateConfig(max_fallback_ratio=0.2)

    assert evaluate_release(summary, config=strict_config).approved is False
    assert evaluate_release(summary, config=lenient_config).approved is True


def test_release_decision_is_immutable() -> None:
    decision = evaluate_release(_good_summary())
    with pytest.raises(Exception):
        decision.approved = False  # frozen pydantic model


def test_failure_report_lists_exact_violations() -> None:
    summary = _good_summary()
    summary["overall_fallback_ratio"] = 0.3
    decision = evaluate_release(summary)

    report = decision.failure_report()
    assert "RELEASE_REJECTED" in report
    assert "fallback" in report
    assert "0.3" in report


def test_failure_report_clean_when_approved() -> None:
    decision = evaluate_release(_good_summary())
    assert "no gate failures" in decision.failure_report()


def test_compare_collectors_is_evaluate_release_with_baseline() -> None:
    baseline = _good_summary()
    candidate = _good_summary()
    candidate["overall_fallback_ratio"] = 0.9

    decision = compare_collectors(baseline, candidate)

    assert decision.approved is False


def _build_index(tmp_path: Path) -> CodeIntelligenceIndex:
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(tmp_path)
    return engine.build_index(tmp_path, scan.files)


async def test_evaluate_release_round_trips_with_a_real_telemetry_collector(tmp_path: Path) -> None:
    """Checklist item #11's own gate 4: 100% of inputs must trace back to a
    real TelemetryCollector.get_run_summary() output, verified end to end,
    no adapter layer -- real resolve()+package() call, real collector,
    fed straight into evaluate_release()."""
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve("ws1", "c1", str(tmp_path), ["authenticate"])
    packager = ContextPackager(RelevanceRanker(), CostEstimator())
    package, _ = await packager.package(result, "how does auth work", max_tokens=5000)

    collector = TelemetryCollector()
    collector.record(result, resolve_latency_ms=1.0, package=package, package_latency_ms=1.0)

    decision = evaluate_release(collector.get_run_summary())

    assert decision.approved is True  # a clean synthetic fixture has no fallback, low utilization
