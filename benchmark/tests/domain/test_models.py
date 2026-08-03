import pytest
from pydantic import ValidationError

from benchmark.domain.models import (
    BenchmarkMode,
    ComparisonResult,
    ContextMetrics,
    CostMetrics,
    LatencyMetrics,
    QualityMetrics,
    RunResult,
    StageLatencies,
    TokenMetrics,
)


def _run_result(
    mode: BenchmarkMode = BenchmarkMode.DIRECT, stages: StageLatencies | None = None
) -> RunResult:
    return RunResult(
        mode=mode,
        model="gpt-4o-mini",
        generated_output="diff --git a/x b/x",
        token_metrics=TokenMetrics(input_tokens=100, output_tokens=50, total_tokens=150),
        latency_metrics=LatencyMetrics(
            total_ms=1000.0,
            llm_ms=800.0,
            deterministic_ms=0.0,
            pipeline_overhead_ms=0.0,
            stages=stages,
        ),
        cost_metrics=CostMetrics(
            estimated_cost_usd=0.01, actual_cost_usd=0.009, pipeline_overhead_cost_usd=0.0
        ),
        context_metrics=ContextMetrics(
            repository_files=10, candidate_files=10, files_sent_to_llm=5
        ),
        quality_metrics=QualityMetrics(answer_length=20, modified_files=["x"]),
    )


def test_run_result_defaults_have_no_arcf_objects() -> None:
    run = _run_result()
    assert run.contract is None
    assert run.context_resolution is None
    assert run.context_package is None


def test_run_result_is_frozen() -> None:
    run = _run_result()
    with pytest.raises(ValidationError):
        run.model = "gpt-4o"


def test_benchmark_mode_values() -> None:
    assert BenchmarkMode.DIRECT.value == "direct"
    assert BenchmarkMode.ARCF.value == "arcf"
    assert BenchmarkMode.ARCF_LOCAL.value == "arcf_local"


def test_stage_latencies_defaults_to_none_on_latency_metrics() -> None:
    run = _run_result()
    assert run.latency_metrics.stages is None


def test_stage_latencies_populated_for_arcf_modes() -> None:
    stages = StageLatencies(
        intent_extraction_ms=50.0,
        workspace_scan_ms=10.0,
        code_intelligence_ms=30.0,
        context_resolution_ms=30.0,
        context_packaging_ms=5.0,
        final_llm_ms=900.0,
        total_pipeline_ms=995.0,
    )
    run = _run_result(mode=BenchmarkMode.ARCF_LOCAL, stages=stages)
    assert run.latency_metrics.stages is not None
    assert run.latency_metrics.stages.intent_extraction_ms == 50.0
    assert (
        run.latency_metrics.stages.code_intelligence_ms
        == run.latency_metrics.stages.context_resolution_ms
    )


def test_quality_metrics_defaults_leave_compilation_and_test_unset() -> None:
    q = QualityMetrics(answer_length=10, modified_files=["a.py"])
    assert q.compilation_success is None
    assert q.test_success is None


def test_comparison_result_defaults_to_no_runs_and_no_metrics() -> None:
    result = ComparisonResult(task="fix bug", repository="/repo", model="gpt-4o-mini")
    assert result.direct is None
    assert result.arcf is None
    assert result.arcf_local is None
    assert result.token_reduction_pct is None
    assert result.context_efficiency_ratio is None
    assert result.local_token_reduction_pct is None
    assert result.local_vs_remote_latency_reduction_pct is None


def test_comparison_result_holds_all_three_runs() -> None:
    direct = _run_result(BenchmarkMode.DIRECT)
    arcf = _run_result(BenchmarkMode.ARCF)
    arcf_local = _run_result(BenchmarkMode.ARCF_LOCAL)
    result = ComparisonResult(
        task="fix bug",
        repository="/repo",
        model="gpt-4o-mini",
        direct=direct,
        arcf=arcf,
        arcf_local=arcf_local,
    )
    assert result.arcf_local is arcf_local


def test_comparison_result_holds_both_runs() -> None:
    direct = _run_result(BenchmarkMode.DIRECT)
    arcf = _run_result(BenchmarkMode.ARCF)
    result = ComparisonResult(
        task="fix bug",
        repository="/repo",
        model="gpt-4o-mini",
        direct=direct,
        arcf=arcf,
        token_reduction_pct=90.9,
    )
    assert result.direct is direct
    assert result.arcf is arcf
    assert result.token_reduction_pct == 90.9


def test_ids_are_unique() -> None:
    a = ComparisonResult(task="x", repository="/repo", model="gpt-4o-mini")
    b = ComparisonResult(task="x", repository="/repo", model="gpt-4o-mini")
    assert a.id != b.id
