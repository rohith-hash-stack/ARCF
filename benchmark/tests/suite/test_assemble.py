from benchmark.domain.models import (
    BenchmarkMode,
    ContextMetrics,
    CostMetrics,
    LatencyMetrics,
    QualityMetrics,
    RunResult,
    TokenMetrics,
)
from benchmark.suite.assemble import assemble_task_result
from benchmark.suite.models import ModeVerification, SuiteModeRunRecord, SuiteTask, TaskCategory


def _run(mode: BenchmarkMode) -> RunResult:
    return RunResult(
        mode=mode,
        model="m",
        generated_output="out",
        token_metrics=TokenMetrics(input_tokens=100, output_tokens=10, total_tokens=110),
        latency_metrics=LatencyMetrics(
            total_ms=100.0, llm_ms=100.0, deterministic_ms=0.0, pipeline_overhead_ms=0.0
        ),
        cost_metrics=CostMetrics(
            estimated_cost_usd=0, actual_cost_usd=0, pipeline_overhead_cost_usd=0
        ),
        context_metrics=ContextMetrics(
            repository_files=10, candidate_files=2, files_sent_to_llm=2
        ),
        quality_metrics=QualityMetrics(answer_length=3, modified_files=[]),
    )


def _record(mode: BenchmarkMode) -> SuiteModeRunRecord:
    return SuiteModeRunRecord(
        task_id="t1", category=TaskCategory.BUG_FIXING, subcategory="x", mode=mode,
        run=_run(mode),
        verification=ModeVerification(
            tests_passed=True,
            patch_applied=True,
            accuracy_score=1.0,
            unrelated_file_modifications=0,
        ),
    )


def _task() -> SuiteTask:
    return SuiteTask(
        id="t1", category=TaskCategory.BUG_FIXING, subcategory="x", repo_key="arcf",
        task_prompt="fix it",
    )


def test_assembles_with_only_direct_run() -> None:
    result = assemble_task_result(_task(), {BenchmarkMode.DIRECT: _record(BenchmarkMode.DIRECT)})
    assert result.comparison.direct is not None
    assert result.comparison.arcf is None
    assert result.direct_verification is not None
    assert result.arcf_verification is None


def test_assembles_with_all_three_modes() -> None:
    records = {
        BenchmarkMode.DIRECT: _record(BenchmarkMode.DIRECT),
        BenchmarkMode.ARCF: _record(BenchmarkMode.ARCF),
        BenchmarkMode.ARCF_LOCAL: _record(BenchmarkMode.ARCF_LOCAL),
    }
    result = assemble_task_result(_task(), records)
    assert result.comparison.direct is not None
    assert result.comparison.arcf is not None
    assert result.comparison.arcf_local is not None
    assert result.comparison.token_reduction_pct is not None


def test_assembles_with_no_records() -> None:
    result = assemble_task_result(_task(), {})
    assert result.comparison.direct is None
    assert result.comparison.arcf is None
    assert result.comparison.model == "unknown"
