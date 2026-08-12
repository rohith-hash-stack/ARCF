from pathlib import Path

import pytest

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from context.packager import ContextPackager
from context.relevance_ranker import RelevanceRanker
from context.task_profile import RetrievalTaskType
from infrastructure.cost import CostEstimator
from infrastructure.telemetry import (
    ConfidenceLabel,
    OriginStageBreakdown,
    TelemetryCollector,
    TelemetryEvent,
)
from workspace.scanner import RepositoryScanner


def _build_index(tmp_path: Path) -> CodeIntelligenceIndex:
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(tmp_path)
    return engine.build_index(tmp_path, scan.files)


def _write_call_chain_fixture(tmp_path: Path) -> None:
    (tmp_path / "repository.py").write_text("def authenticate(user):\n    return True\n")
    (tmp_path / "service.py").write_text(
        "from .repository import authenticate\n\ndef login(user):\n    return authenticate(user)\n"
    )
    (tmp_path / "controller.py").write_text(
        "from .service import login\n\ndef handle_login(user):\n    return login(user)\n"
    )


def test_origin_breakdown_counts_real_candidate_files(tmp_path: Path) -> None:
    _write_call_chain_fixture(tmp_path)
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "c1", str(tmp_path), ["authenticate"], traversal_depth=None
    )
    collector = TelemetryCollector()

    event = collector.record(result, resolve_latency_ms=1.0)

    assert event.origin_breakdown.untagged == 0
    assert event.origin_breakdown.ast_direct == 1  # repository.py
    assert event.origin_breakdown.scoped_graph_expansion == 2  # service.py, controller.py
    assert event.origin_breakdown.total == len(result.candidate_files)


def test_record_captures_query_id_and_traversal_depth(tmp_path: Path) -> None:
    _write_call_chain_fixture(tmp_path)
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "c1", str(tmp_path), ["authenticate"], traversal_depth=None
    )
    collector = TelemetryCollector()

    event = collector.record(
        result, resolve_latency_ms=5.5, classified_task=RetrievalTaskType.BUG_FIX
    )

    assert event.query_id == result.id
    assert event.traversal_depth == result.retrieval_depth_used
    assert event.traversal_depth == 2  # repository <- service <- controller, 2 real hops
    assert event.classified_task is RetrievalTaskType.BUG_FIX
    assert event.package_latency_ms is None
    assert event.token_budget_capacity is None


async def test_record_with_package_captures_budget_signals(tmp_path: Path) -> None:
    _write_call_chain_fixture(tmp_path)
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "c1", str(tmp_path), ["authenticate"], traversal_depth=None
    )
    packager = ContextPackager(RelevanceRanker(), CostEstimator())
    package, _ = await packager.package(result, "how does login work", max_tokens=5000)
    collector = TelemetryCollector()

    event = collector.record(
        result, resolve_latency_ms=1.0, package=package, package_latency_ms=2.0
    )

    assert event.package_latency_ms == 2.0
    assert event.token_budget_capacity == 5000
    assert event.tokens_utilized == package.budget_used_tokens
    assert event.utilization_ratio == round(package.budget_used_tokens / 5000, 4)


def test_get_run_summary_empty_collector() -> None:
    summary = TelemetryCollector().get_run_summary()
    assert summary["event_count"] == 0
    assert summary["resolve_latency_ms"] is None
    assert summary["overall_fallback_ratio"] == 0.0
    assert summary["quality_data_available"] is False
    assert summary["mean_precision"] is None
    assert summary["mean_recall"] is None


def test_quality_data_available_false_when_no_precision_or_recall_supplied(tmp_path: Path) -> None:
    _write_call_chain_fixture(tmp_path)
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "c1", str(tmp_path), ["authenticate"], traversal_depth=None
    )
    collector = TelemetryCollector()
    collector.record(result, resolve_latency_ms=1.0)  # no precision/recall -- the real-world default

    summary = collector.get_run_summary()
    assert summary["quality_data_available"] is False
    assert summary["mean_precision"] is None
    assert summary["mean_recall"] is None


def test_quality_data_aggregates_when_caller_supplies_ground_truth(tmp_path: Path) -> None:
    _write_call_chain_fixture(tmp_path)
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "c1", str(tmp_path), ["authenticate"], traversal_depth=None
    )
    collector = TelemetryCollector()
    collector.record(result, resolve_latency_ms=1.0, precision=0.8, recall=1.0)
    collector.record(result, resolve_latency_ms=1.0, precision=0.6, recall=0.5)

    summary = collector.get_run_summary()
    assert summary["quality_data_available"] is True
    assert summary["mean_precision"] == 0.7
    assert summary["mean_recall"] == 0.75
    assert summary["min_recall"] == 0.5


def test_get_run_summary_aggregates_across_multiple_events(tmp_path: Path) -> None:
    _write_call_chain_fixture(tmp_path)
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "c1", str(tmp_path), ["authenticate"], traversal_depth=None
    )
    collector = TelemetryCollector()
    collector.record(result, resolve_latency_ms=10.0)
    collector.record(result, resolve_latency_ms=20.0)
    collector.record(result, resolve_latency_ms=30.0)

    summary = collector.get_run_summary()

    assert summary["event_count"] == 3
    assert summary["resolve_latency_ms"]["mean"] == 20.0
    assert summary["resolve_latency_ms"]["max"] == 30.0
    assert summary["origin_breakdown_totals"]["ast_direct"] == 3  # 1 per event x 3
    assert summary["origin_breakdown_totals"]["scoped_graph_expansion"] == 6  # 2 per event x 3


def test_assert_no_fallbacks_passes_when_no_fallback_origin(tmp_path: Path) -> None:
    _write_call_chain_fixture(tmp_path)
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "c1", str(tmp_path), ["authenticate"], traversal_depth=None
    )
    collector = TelemetryCollector()
    collector.record(result, resolve_latency_ms=1.0)

    collector.assert_no_fallbacks()  # must not raise


def test_assert_no_fallbacks_raises_when_fallback_present(tmp_path: Path) -> None:
    # module-level raw call -> RAW_STRING_FALLBACK, per test_context_resolver.py's own
    # test_module_level_raw_call_tagged_raw_string_fallback fixture shape.
    (tmp_path / "target.py").write_text("def middleware():\n    pass\n")
    (tmp_path / "registration.py").write_text(
        "from .target import middleware\n\nmiddleware()\n"
    )
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "c1", str(tmp_path), ["middleware"], traversal_depth=1
    )
    collector = TelemetryCollector()
    collector.record(result, resolve_latency_ms=1.0)

    with pytest.raises(AssertionError, match="fallback ratio"):
        collector.assert_no_fallbacks()


def test_assert_no_fallbacks_respects_custom_threshold(tmp_path: Path) -> None:
    (tmp_path / "target.py").write_text("def middleware():\n    pass\n")
    (tmp_path / "registration.py").write_text(
        "from .target import middleware\n\nmiddleware()\n"
    )
    index = _build_index(tmp_path)
    result = ContextResolver(index).resolve(
        "ws1", "c1", str(tmp_path), ["middleware"], traversal_depth=1
    )
    collector = TelemetryCollector()
    collector.record(result, resolve_latency_ms=1.0)
    ratio = collector.get_run_summary()["overall_fallback_ratio"]

    collector.assert_no_fallbacks(max_fallback_ratio=ratio)  # must not raise at exactly the ratio
    with pytest.raises(AssertionError):
        collector.assert_no_fallbacks(max_fallback_ratio=ratio - 0.0001)


def test_telemetry_event_schema_requires_query_id() -> None:
    with pytest.raises(Exception):  # pydantic ValidationError
        TelemetryEvent(
            traversal_depth=1,
            resolve_latency_ms=1.0,
            origin_breakdown=OriginStageBreakdown(),
        )


def test_origin_stage_breakdown_untagged_signals_a_real_coverage_gap() -> None:
    # untagged should always be 0 on a real resolve() result (item #10 tags every
    # real construction site) -- this test documents that a nonzero value here
    # is a real signal, not a legitimate "no stage" case, by exercising the
    # property math directly rather than trying to force a real gap.
    breakdown = OriginStageBreakdown(ast_direct=2, untagged=1)
    assert breakdown.total == 3
    assert breakdown.fallback_count == 0


def _event_with_breakdown(**kwargs) -> TelemetryEvent:
    from uuid import uuid4
    return TelemetryEvent(
        query_id=uuid4(), traversal_depth=0, resolve_latency_ms=1.0,
        origin_breakdown=OriginStageBreakdown(**kwargs),
    )


def test_confidence_label_empty_candidate_set() -> None:
    event = _event_with_breakdown()
    assert event.confidence_label is ConfidenceLabel.EMPTY_CANDIDATE_SET


def test_confidence_label_low_confidence_when_only_fallback_candidates() -> None:
    event = _event_with_breakdown(raw_string_fallback=2, evidence_fallback_match=1)
    assert event.confidence_label is ConfidenceLabel.LOW_CONFIDENCE


def test_confidence_label_confident_match_when_any_non_fallback_candidate() -> None:
    event = _event_with_breakdown(ast_direct=1, raw_string_fallback=5)
    assert event.confidence_label is ConfidenceLabel.CONFIDENT_MATCH

    event2 = _event_with_breakdown(scoped_graph_expansion=1)
    assert event2.confidence_label is ConfidenceLabel.CONFIDENT_MATCH
