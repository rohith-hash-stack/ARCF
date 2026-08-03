from benchmark.domain.models import (
    BenchmarkMode,
    ContextMetrics,
    CostMetrics,
    LatencyMetrics,
    QualityMetrics,
    RunResult,
    TokenMetrics,
)
from benchmark.suite.models import SuiteTask, TaskCategory
from benchmark.suite.patcher import PatchResult
from benchmark.suite.scoring import score
from benchmark.suite.verifier import VerificationResult


def _run(generated_output: str, modified_files: list[str]) -> RunResult:
    return RunResult(
        mode=BenchmarkMode.DIRECT,
        model="m",
        generated_output=generated_output,
        token_metrics=TokenMetrics(input_tokens=1, output_tokens=1, total_tokens=2),
        latency_metrics=LatencyMetrics(
            total_ms=1.0, llm_ms=1.0, deterministic_ms=0.0, pipeline_overhead_ms=0.0
        ),
        cost_metrics=CostMetrics(
            estimated_cost_usd=0, actual_cost_usd=0, pipeline_overhead_cost_usd=0
        ),
        context_metrics=ContextMetrics(
            repository_files=10, candidate_files=10, files_sent_to_llm=1
        ),
        quality_metrics=QualityMetrics(
            answer_length=len(generated_output), modified_files=modified_files
        ),
    )


def _analysis_task(expected_grounding: list[str]) -> SuiteTask:
    return SuiteTask(
        id="t1", category=TaskCategory.REPOSITORY_UNDERSTANDING, subcategory="x",
        repo_key="arcf", task_prompt="explain", expected_grounding=expected_grounding,
    )


def _execution_task(expected_path_prefixes: list[str]) -> SuiteTask:
    return SuiteTask(
        id="t2", category=TaskCategory.BUG_FIXING, subcategory="x", repo_key="arcf",
        task_prompt="fix it", expected_path_prefixes=expected_path_prefixes,
        verify_command="pytest", verify_cwd=".",
    )


def test_analysis_full_grounding_scores_one() -> None:
    task = _analysis_task(["auth.py", "Authenticator"])
    run = _run("It's handled in auth.py by the Authenticator class.", [])
    verification = score(task, run)
    assert verification.accuracy_score == 1.0
    assert verification.tests_passed is None
    assert verification.unrelated_file_modifications == 0


def test_analysis_partial_grounding() -> None:
    task = _analysis_task(["auth.py", "Authenticator", "missing_term"])
    run = _run("It's handled in auth.py by the Authenticator class.", [])
    verification = score(task, run)
    assert verification.accuracy_score == 2 / 3


def test_analysis_any_modification_counts_unrelated() -> None:
    task = _analysis_task(["auth.py"])
    run = _run("auth.py explanation", ["some/other/file.py"])
    verification = score(task, run)
    assert verification.unrelated_file_modifications == 1


def test_execution_unapplied_patch_fails() -> None:
    task = _execution_task(["src/x.py"])
    run = _run("no parseable blocks here", [])
    patch = PatchResult(applied=False, written_paths=[], skipped_protected_paths=[])
    verification = score(task, run, patch, None)
    assert verification.tests_passed is False
    assert verification.patch_applied is False
    assert verification.accuracy_score == 0.0


def test_execution_applied_and_passing() -> None:
    task = _execution_task(["src/x.py"])
    run = _run("### src/x.py\n```\nfixed\n```", ["src/x.py"])
    patch = PatchResult(applied=True, written_paths=["src/x.py"], skipped_protected_paths=[])
    verification_result = VerificationResult(passed=True, output_tail="ok")
    verification = score(task, run, patch, verification_result)
    assert verification.tests_passed is True
    assert verification.accuracy_score == 1.0
    assert verification.unrelated_file_modifications == 0


def test_execution_unrelated_file_counted() -> None:
    task = _execution_task(["src/x.py"])
    run = _run("### src/x.py\n```\nfixed\n```", ["src/x.py", "src/unrelated.py"])
    patch = PatchResult(
        applied=True, written_paths=["src/x.py", "src/unrelated.py"], skipped_protected_paths=[]
    )
    verification_result = VerificationResult(passed=True, output_tail="ok")
    verification = score(task, run, patch, verification_result)
    assert verification.unrelated_file_modifications == 1
