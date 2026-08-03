from benchmark.analyzer import BenchmarkAnalyzer
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
from benchmark.report import render_text_report


def _stages(intent_ms: float, total_ms: float) -> StageLatencies:
    return StageLatencies(
        intent_extraction_ms=intent_ms,
        workspace_scan_ms=50.0,
        code_intelligence_ms=100.0,
        context_resolution_ms=100.0,
        context_packaging_ms=20.0,
        final_llm_ms=total_ms - intent_ms - 170.0,
        total_pipeline_ms=total_ms,
    )


def _direct() -> RunResult:
    return RunResult(
        mode=BenchmarkMode.DIRECT,
        model="gemini-flash",
        generated_output="### auth.py\n```\nfix\n```",
        token_metrics=TokenMetrics(input_tokens=98_000, output_tokens=500, total_tokens=98_500),
        latency_metrics=LatencyMetrics(
            total_ms=18_100.0, llm_ms=18_100.0, deterministic_ms=0.0, pipeline_overhead_ms=0.0
        ),
        cost_metrics=CostMetrics(
            estimated_cost_usd=0.5, actual_cost_usd=0.5, pipeline_overhead_cost_usd=0.0
        ),
        context_metrics=ContextMetrics(
            repository_files=100, candidate_files=100, files_sent_to_llm=99
        ),
        quality_metrics=QualityMetrics(answer_length=100, modified_files=["auth.py"]),
    )


def _arcf(mode: BenchmarkMode, total_ms: float, intent_ms: float) -> RunResult:
    return RunResult(
        mode=mode,
        model="gemini-flash",
        generated_output="### auth.py\n```\nfix\n```",
        token_metrics=TokenMetrics(input_tokens=2_300, output_tokens=500, total_tokens=2_800),
        latency_metrics=LatencyMetrics(
            total_ms=total_ms,
            llm_ms=total_ms - intent_ms - 170.0,
            deterministic_ms=170.0,
            pipeline_overhead_ms=intent_ms,
            stages=_stages(intent_ms, total_ms),
        ),
        cost_metrics=CostMetrics(
            estimated_cost_usd=0.02, actual_cost_usd=0.02, pipeline_overhead_cost_usd=0.001
        ),
        context_metrics=ContextMetrics(
            repository_files=100, candidate_files=3, files_sent_to_llm=2
        ),
        quality_metrics=QualityMetrics(answer_length=100, modified_files=["auth.py"]),
    )


def _build_comparison() -> ComparisonResult:
    direct = _direct()
    arcf = _arcf(BenchmarkMode.ARCF, total_ms=19_100.0, intent_ms=10_000.0)
    arcf_local = _arcf(BenchmarkMode.ARCF_LOCAL, total_ms=9_270.0, intent_ms=170.0)
    return BenchmarkAnalyzer().compare(
        task="Fix authentication test",
        repository="arcf",
        model="Gemini Flash",
        direct=direct,
        arcf=arcf,
        arcf_local=arcf_local,
    )


def test_report_contains_header_and_all_three_sections() -> None:
    report = render_text_report(_build_comparison())
    assert "Task: Fix authentication test" in report
    assert "Repository: arcf" in report
    assert "Model: Gemini Flash" in report
    assert "Direct LLM" in report
    assert "ARCF Remote" in report
    assert "ARCF Local" in report


def test_report_shows_stage_latencies_for_arcf_modes() -> None:
    report = render_text_report(_build_comparison())
    assert "Intent Extraction (SLM-1): 10000 ms" in report
    assert "Intent Extraction (SLM-1): 170 ms" in report


def test_report_shows_delta_and_hypothesis_metric() -> None:
    report = render_text_report(_build_comparison())
    assert "Local vs Remote Latency Reduction" in report
    assert "Delta" in report


def test_report_success_criteria_checklist_present() -> None:
    report = render_text_report(_build_comparison())
    assert "Success Criteria" in report
    assert "Local SLM latency < 1 s" in report
    assert "Total ARCF Local latency < Direct latency" in report


def test_report_without_local_mode_still_renders() -> None:
    direct = _direct()
    arcf = _arcf(BenchmarkMode.ARCF, total_ms=19_100.0, intent_ms=10_000.0)
    result = BenchmarkAnalyzer().compare(
        task="x", repository="/repo", model="m", direct=direct, arcf=arcf
    )
    report = render_text_report(result)
    assert "ARCF Local" not in report
    assert "Local SLM not run this comparison" in report
