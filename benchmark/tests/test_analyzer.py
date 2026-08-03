import pytest

from benchmark.analyzer import BenchmarkAnalyzer
from benchmark.domain.models import (
    BenchmarkMode,
    ContextMetrics,
    CostMetrics,
    LatencyMetrics,
    QualityMetrics,
    RunResult,
    TokenMetrics,
)


def _run(
    mode: BenchmarkMode,
    input_tokens: int,
    output_tokens: int,
    total_ms: float,
    actual_cost: float,
    files_sent: int,
    repo_files: int = 37,
) -> RunResult:
    return RunResult(
        mode=mode,
        model="claude-sonnet",
        generated_output="output",
        token_metrics=TokenMetrics(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
        latency_metrics=LatencyMetrics(
            total_ms=total_ms, llm_ms=total_ms, deterministic_ms=0.0, pipeline_overhead_ms=0.0
        ),
        cost_metrics=CostMetrics(
            estimated_cost_usd=actual_cost, actual_cost_usd=actual_cost,
            pipeline_overhead_cost_usd=0.0,
        ),
        context_metrics=ContextMetrics(
            repository_files=repo_files, candidate_files=files_sent, files_sent_to_llm=files_sent
        ),
        quality_metrics=QualityMetrics(answer_length=len("output"), modified_files=[]),
    )


def test_matches_the_playbook_report_example() -> None:
    """Task: Fix Playwright login test — the exact numbers from the spec's
    example report."""
    direct = _run(BenchmarkMode.DIRECT, 18_240, 612, 5800.0, 0.12, files_sent=37)
    arcf = _run(BenchmarkMode.ARCF, 1_124, 598, 2900.0, 0.014, files_sent=3)

    result = BenchmarkAnalyzer().compare(
        task="Fix Playwright login test", repository="automation-framework", model="claude-sonnet",
        direct=direct, arcf=arcf,
    )

    assert result.token_reduction_pct == pytest.approx(90.87)  # (18852-1722)/18852 * 100
    assert result.latency_reduction_pct == pytest.approx(50.0)
    assert result.cost_reduction_pct == pytest.approx(88.33)
    assert result.context_efficiency_ratio == pytest.approx(3 / 37, abs=1e-3)
    assert result.prompt_compression_ratio == pytest.approx(18_240 / 1_124, abs=1e-2)


def test_single_mode_run_produces_no_comparison_metrics() -> None:
    direct = _run(BenchmarkMode.DIRECT, 1000, 100, 500.0, 0.01, files_sent=10)
    result = BenchmarkAnalyzer().compare(
        task="x", repository="/repo", model="gpt-4o-mini", direct=direct, arcf=None
    )
    assert result.token_reduction_pct is None
    assert result.context_efficiency_ratio is None
    assert result.direct is direct
    assert result.arcf is None


def test_zero_direct_cost_yields_no_reduction_percentage() -> None:
    direct = _run(BenchmarkMode.DIRECT, 1000, 100, 500.0, 0.0, files_sent=10)
    arcf = _run(BenchmarkMode.ARCF, 100, 50, 200.0, 0.001, files_sent=2)
    result = BenchmarkAnalyzer().compare(
        task="x", repository="/repo", model="gpt-4o-mini", direct=direct, arcf=arcf
    )
    assert result.cost_reduction_pct is None


def test_zero_files_sent_by_direct_yields_no_cer() -> None:
    direct = _run(BenchmarkMode.DIRECT, 1000, 100, 500.0, 0.01, files_sent=0)
    arcf = _run(BenchmarkMode.ARCF, 100, 50, 200.0, 0.001, files_sent=2)
    result = BenchmarkAnalyzer().compare(
        task="x", repository="/repo", model="gpt-4o-mini", direct=direct, arcf=arcf
    )
    assert result.context_efficiency_ratio is None


def test_three_way_comparison_computes_local_deltas_and_hypothesis_metric() -> None:
    direct = _run(BenchmarkMode.DIRECT, 18_240, 612, 5800.0, 0.12, files_sent=37)
    arcf = _run(BenchmarkMode.ARCF, 1_124, 598, 2900.0, 0.014, files_sent=3)
    arcf_local = _run(BenchmarkMode.ARCF_LOCAL, 1_124, 598, 2000.0, 0.0, files_sent=3)

    result = BenchmarkAnalyzer().compare(
        task="x",
        repository="/repo",
        model="claude-sonnet",
        direct=direct,
        arcf=arcf,
        arcf_local=arcf_local,
    )

    assert result.arcf_local is arcf_local
    assert result.local_token_reduction_pct == pytest.approx(result.token_reduction_pct)
    assert result.local_context_efficiency_ratio == pytest.approx(3 / 37, abs=1e-3)
    assert result.local_prompt_compression_ratio == pytest.approx(18_240 / 1_124, abs=1e-2)
    # local (2000ms) is faster than remote (2900ms) -> positive reduction
    assert result.local_vs_remote_latency_reduction_pct == pytest.approx(
        (2900.0 - 2000.0) / 2900.0 * 100, abs=1e-2
    )


def test_arcf_local_absent_yields_no_local_metrics_or_hypothesis_metric() -> None:
    direct = _run(BenchmarkMode.DIRECT, 1000, 100, 500.0, 0.01, files_sent=10)
    arcf = _run(BenchmarkMode.ARCF, 100, 50, 200.0, 0.001, files_sent=2)
    result = BenchmarkAnalyzer().compare(
        task="x", repository="/repo", model="gpt-4o-mini", direct=direct, arcf=arcf, arcf_local=None
    )
    assert result.local_token_reduction_pct is None
    assert result.local_context_efficiency_ratio is None
    assert result.local_vs_remote_latency_reduction_pct is None
