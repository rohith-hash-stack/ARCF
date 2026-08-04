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
from benchmark.suite.models import ModeVerification, SuiteTaskResult, TaskCategory
from benchmark.suite.report import render_executive_summary, render_suite_report, summarize

_analyzer = BenchmarkAnalyzer()


def _run(mode: BenchmarkMode, tokens: int, latency_ms: float, files_sent: int = 2) -> RunResult:
    return RunResult(
        mode=mode,
        model="m",
        generated_output="out",
        token_metrics=TokenMetrics(input_tokens=tokens, output_tokens=10, total_tokens=tokens + 10),
        latency_metrics=LatencyMetrics(
            total_ms=latency_ms, llm_ms=latency_ms, deterministic_ms=0.0, pipeline_overhead_ms=0.0
        ),
        cost_metrics=CostMetrics(
            estimated_cost_usd=0.01, actual_cost_usd=0.01, pipeline_overhead_cost_usd=0.0
        ),
        context_metrics=ContextMetrics(
            repository_files=100, candidate_files=files_sent, files_sent_to_llm=files_sent
        ),
        quality_metrics=QualityMetrics(answer_length=3, modified_files=[]),
    )


def _verification(
    tests_passed: bool | None, accuracy: float | None, unrelated: int = 0
) -> ModeVerification:
    return ModeVerification(
        tests_passed=tests_passed,
        patch_applied=tests_passed is not None,
        accuracy_score=accuracy,
        unrelated_file_modifications=unrelated,
    )


def _task_result(task_id: str, direct_tokens: int, arcf_tokens: int,
                  direct_latency: float, arcf_latency: float,
                  direct_acc: float, arcf_acc: float) -> SuiteTaskResult:
    direct = _run(BenchmarkMode.DIRECT, direct_tokens, direct_latency, files_sent=100)
    arcf = _run(BenchmarkMode.ARCF, arcf_tokens, arcf_latency, files_sent=2)
    comparison = _analyzer.compare(
        task="x", repository="arcf", model="m", direct=direct, arcf=arcf
    )
    return SuiteTaskResult(
        task_id=task_id,
        category=TaskCategory.BUG_FIXING,
        subcategory="x",
        comparison=comparison,
        direct_verification=_verification(True, direct_acc),
        arcf_verification=_verification(True, arcf_acc),
    )


def test_summarize_computes_averages_and_verdict() -> None:
    results = [
        _task_result("t1", 10_000, 1_000, 2000.0, 1000.0, direct_acc=1.0, arcf_acc=1.0),
        _task_result("t2", 20_000, 2_000, 3000.0, 1500.0, direct_acc=1.0, arcf_acc=1.0),
    ]
    summary = summarize("pilot", results)
    assert summary.task_count == 2
    assert summary.avg_token_reduction_pct is not None and summary.avg_token_reduction_pct > 50
    assert summary.avg_accuracy_delta == 0.0
    assert summary.tasks_won_by_arcf + summary.tasks_won_by_direct + summary.tasks_tied == 2
    assert summary.verdict in {"continue", "pivot", "stop"}


def test_arcf_wins_when_more_accurate() -> None:
    results = [_task_result("t1", 1000, 100, 500.0, 400.0, direct_acc=0.0, arcf_acc=1.0)]
    summary = summarize("pilot", results)
    assert summary.tasks_won_by_arcf == 1
    assert summary.tasks_won_by_direct == 0


def test_direct_wins_when_more_accurate() -> None:
    results = [_task_result("t1", 1000, 100, 500.0, 400.0, direct_acc=1.0, arcf_acc=0.0)]
    summary = summarize("pilot", results)
    assert summary.tasks_won_by_direct == 1


def test_tie_broken_by_latency() -> None:
    faster_arcf = _task_result("t1", 1000, 100, 500.0, 400.0, direct_acc=1.0, arcf_acc=1.0)
    summary = summarize("pilot", [faster_arcf])
    assert summary.tasks_won_by_arcf == 1


def test_missing_accuracy_excluded_from_win_tally() -> None:
    direct = _run(BenchmarkMode.DIRECT, 1000, 500.0)
    arcf = _run(BenchmarkMode.ARCF, 100, 400.0)
    comparison = _analyzer.compare(task="x", repository="arcf", model="m", direct=direct, arcf=arcf)
    result = SuiteTaskResult(
        task_id="t1", category=TaskCategory.REPOSITORY_UNDERSTANDING, subcategory="x",
        comparison=comparison,
        direct_verification=_verification(None, None),
        arcf_verification=_verification(None, None),
    )
    summary = summarize("pilot", [result])
    assert summary.tasks_won_by_arcf == 0
    assert summary.tasks_won_by_direct == 0
    assert summary.tasks_tied == 0


def test_grounding_score_averaged_only_over_repository_understanding_tasks() -> None:
    direct = _run(BenchmarkMode.DIRECT, 1000, 500.0)
    arcf = _run(BenchmarkMode.ARCF, 100, 400.0)
    comparison = _analyzer.compare(task="x", repository="arcf", model="m", direct=direct, arcf=arcf)
    understanding_result = SuiteTaskResult(
        task_id="t1", category=TaskCategory.REPOSITORY_UNDERSTANDING, subcategory="x",
        comparison=comparison,
        direct_verification=_verification(None, 0.5),
        arcf_verification=_verification(None, 1.0),
    )
    # A bug-fixing task's accuracy_score means "tests passed", not grounding —
    # it must NOT be blended into the grounding average.
    bug_fixing_result = _task_result("t2", 1000, 100, 500.0, 400.0, direct_acc=0.0, arcf_acc=0.0)

    summary = summarize("pilot", [understanding_result, bug_fixing_result])
    assert summary.avg_direct_grounding_score == 0.5
    assert summary.avg_arcf_grounding_score == 1.0


def test_grounding_score_none_when_no_understanding_tasks() -> None:
    results = [_task_result("t1", 1000, 100, 500.0, 400.0, direct_acc=1.0, arcf_acc=1.0)]
    summary = summarize("pilot", results)
    assert summary.avg_direct_grounding_score is None
    assert summary.avg_arcf_grounding_score is None


def test_render_suite_report_includes_grounding_score() -> None:
    direct = _run(BenchmarkMode.DIRECT, 1000, 500.0)
    arcf = _run(BenchmarkMode.ARCF, 100, 400.0)
    comparison = _analyzer.compare(task="x", repository="arcf", model="m", direct=direct, arcf=arcf)
    result = SuiteTaskResult(
        task_id="t1", category=TaskCategory.REPOSITORY_UNDERSTANDING, subcategory="x",
        comparison=comparison,
        direct_verification=_verification(None, 0.5),
        arcf_verification=_verification(None, 1.0),
    )
    report = render_suite_report("pilot", [result])
    assert "repository grounding score" in report.lower()


def test_render_executive_summary_contains_all_requested_metrics() -> None:
    results = [
        _task_result("t1", 10_000, 1_000, 2000.0, 1000.0, direct_acc=1.0, arcf_acc=1.0),
    ]
    summary = summarize("pilot", results)
    text = render_executive_summary(summary)

    assert "Executive Summary" in text
    assert "Average token reduction" in text
    assert "Average cost reduction" in text
    assert "Average latency difference" in text
    assert "Context Efficiency Ratio" in text
    assert "Prompt Compression Ratio" in text
    assert "repository grounding score" in text
    assert "Tasks won by ARCF" in text
    assert "Tasks won by Direct LLM" in text
    assert "Tasks tied" in text
    assert "Statistical significance" in text
    assert "Final Recommendation" in text
    assert summary.verdict.upper() in text
    # No per-task detail table — that's what distinguishes this from
    # render_suite_report's full technical report.
    assert "Detailed Table" not in text


def test_render_suite_report_contains_key_sections() -> None:
    results = [_task_result("t1", 10_000, 1_000, 2000.0, 1000.0, direct_acc=1.0, arcf_acc=1.0)]
    report = render_suite_report("pilot", results)
    assert "# ARCF Benchmark Validation Report — pilot" in report
    assert "## Executive Summary" in report
    assert "## Detailed Table" in report
    assert "## Final Verdict" in report
    assert "t1" in report
