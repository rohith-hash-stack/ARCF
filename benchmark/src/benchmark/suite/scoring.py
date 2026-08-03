"""Turns a RunResult (+ patch/verification outcome, for code-change
categories) into a ModeVerification, per the four category-specific
strategies described in the suite plan. Reuses
quality.extract_modified_files (already parses the same "### path"
headers FORMAT_ADDENDUM asks for) rather than re-deriving modified
files from scratch.
"""

from benchmark.domain.models import RunResult
from benchmark.suite.models import ModeVerification, SuiteTask, TaskCategory
from benchmark.suite.patcher import PatchResult
from benchmark.suite.verifier import VerificationResult


def _unrelated_count(modified_files: list[str], expected_path_prefixes: list[str]) -> int:
    if not expected_path_prefixes:
        return len(modified_files)
    return sum(
        1
        for path in modified_files
        if not any(path.startswith(prefix) for prefix in expected_path_prefixes)
    )


def score_analysis(task: SuiteTask, run: RunResult) -> ModeVerification:
    text_lower = run.generated_output.lower()
    matched = sum(1 for term in task.expected_grounding if term.lower() in text_lower)
    accuracy = matched / len(task.expected_grounding) if task.expected_grounding else None

    return ModeVerification(
        tests_passed=None,
        patch_applied=False,
        accuracy_score=accuracy,
        unrelated_file_modifications=_unrelated_count(run.quality_metrics.modified_files, []),
    )


def score_execution(
    task: SuiteTask,
    run: RunResult,
    patch: PatchResult,
    verification: VerificationResult | None,
) -> ModeVerification:
    unrelated = _unrelated_count(run.quality_metrics.modified_files, task.expected_path_prefixes)

    if not patch.applied:
        return ModeVerification(
            tests_passed=False,
            patch_applied=False,
            accuracy_score=0.0,
            unrelated_file_modifications=unrelated,
            verification_output_tail="No parseable '### path' file blocks in generated_output.",
        )

    if verification is None:
        raise ValueError("verification is required when patch.applied is True")

    return ModeVerification(
        tests_passed=verification.passed,
        patch_applied=True,
        accuracy_score=1.0 if verification.passed else 0.0,
        unrelated_file_modifications=unrelated,
        verification_output_tail=verification.output_tail,
    )


def score(
    task: SuiteTask,
    run: RunResult,
    patch: PatchResult | None = None,
    verification: VerificationResult | None = None,
) -> ModeVerification:
    if task.category is TaskCategory.REPOSITORY_UNDERSTANDING:
        return score_analysis(task, run)
    if patch is None:
        raise ValueError(f"patch is required for category {task.category}")
    return score_execution(task, run, patch, verification)
