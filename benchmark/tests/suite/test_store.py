from pathlib import Path

from benchmark.domain.models import (
    BenchmarkMode,
    ContextMetrics,
    CostMetrics,
    LatencyMetrics,
    QualityMetrics,
    RunResult,
    TokenMetrics,
)
from benchmark.suite.models import ModeVerification, SuiteModeRunRecord, TaskCategory
from benchmark.suite.store import SuiteResultStore


def _record(task_id: str, mode: BenchmarkMode) -> SuiteModeRunRecord:
    run = RunResult(
        mode=mode,
        model="m",
        generated_output="out",
        token_metrics=TokenMetrics(input_tokens=1, output_tokens=1, total_tokens=2),
        latency_metrics=LatencyMetrics(
            total_ms=1.0, llm_ms=1.0, deterministic_ms=0.0, pipeline_overhead_ms=0.0
        ),
        cost_metrics=CostMetrics(
            estimated_cost_usd=0, actual_cost_usd=0, pipeline_overhead_cost_usd=0
        ),
        context_metrics=ContextMetrics(
            repository_files=1, candidate_files=1, files_sent_to_llm=1
        ),
        quality_metrics=QualityMetrics(answer_length=3, modified_files=[]),
    )
    verification = ModeVerification(
        tests_passed=True, patch_applied=True, accuracy_score=1.0, unrelated_file_modifications=0
    )
    return SuiteModeRunRecord(
        task_id=task_id, category=TaskCategory.BUG_FIXING, subcategory="x",
        mode=mode, run=run, verification=verification,
    )


def test_save_and_list_for_suite(tmp_path: Path) -> None:
    store = SuiteResultStore(str(tmp_path / "runs.db"))
    store.save("pilot", _record("t1", BenchmarkMode.DIRECT))
    store.save("pilot", _record("t1", BenchmarkMode.ARCF))
    store.save("pilot", _record("t2", BenchmarkMode.DIRECT))

    records = store.list_for_suite("pilot")
    assert len(records) == 3


def test_rerunning_same_task_mode_overwrites(tmp_path: Path) -> None:
    store = SuiteResultStore(str(tmp_path / "runs.db"))
    store.save("pilot", _record("t1", BenchmarkMode.DIRECT))
    store.save("pilot", _record("t1", BenchmarkMode.DIRECT))
    assert len(store.list_for_suite("pilot")) == 1


def test_records_by_task_groups_by_mode(tmp_path: Path) -> None:
    store = SuiteResultStore(str(tmp_path / "runs.db"))
    store.save("pilot", _record("t1", BenchmarkMode.DIRECT))
    store.save("pilot", _record("t1", BenchmarkMode.ARCF))
    store.save("pilot", _record("t2", BenchmarkMode.ARCF_LOCAL))

    grouped = store.records_by_task("pilot")
    assert set(grouped["t1"]) == {BenchmarkMode.DIRECT, BenchmarkMode.ARCF}
    assert set(grouped["t2"]) == {BenchmarkMode.ARCF_LOCAL}


def test_different_suites_are_isolated(tmp_path: Path) -> None:
    store = SuiteResultStore(str(tmp_path / "runs.db"))
    store.save("pilot", _record("t1", BenchmarkMode.DIRECT))
    store.save("full", _record("t1", BenchmarkMode.DIRECT))
    assert len(store.list_for_suite("pilot")) == 1
    assert len(store.list_for_suite("full")) == 1
