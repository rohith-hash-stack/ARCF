"""Suite domain models.

SuiteTask is loaded from a JSON suite file (benchmark/suites/*.json) —
data, not code, so growing from an 8-task pilot to the full 30-task
suite is a data change, not a rewrite.

SuiteTaskResult wraps a ComparisonResult UNCHANGED (see
benchmark/analyzer.py) rather than recomputing token/latency/cost/CER/
PCR — those are already correct. This module only adds what doesn't
exist yet: execution-based verification.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from benchmark.domain.models import BenchmarkMode, ComparisonResult, RunResult


class TaskCategory(StrEnum):
    REPOSITORY_UNDERSTANDING = "repository_understanding"
    BUG_FIXING = "bug_fixing"
    REFACTORING = "refactoring"
    TEST_GENERATION = "test_generation"
    FEATURE_IMPLEMENTATION = "feature_implementation"
    """Added for the 40-task suite (ARCF v2.3 Execution Directive,
    Action 3) — scored identically to REFACTORING/BUG_FIXING via
    score_execution (patch-applied + verify_command), since adding a
    feature is still a code-change category with the same "did it apply
    and did the suite still pass" oracle shape."""


class BugFixture(BaseModel):
    """A hand-written regression, applied to a scratch repo copy BEFORE
    the pipeline runs, so a Bug Fixing task has a real bug to find
    against a real, currently-passing test. find/replace must be exact
    substring matches — this is fixture code the task's author
    controls, not fuzzy patching, so ambiguity here is a fixture bug
    worth catching loudly rather than papering over."""

    model_config = ConfigDict(frozen=True)

    file_path: str
    """Relative to the repo root, e.g. 'src/infrastructure/auth.py'."""
    find: str
    replace: str


class SuiteTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    category: TaskCategory
    subcategory: str
    repo_key: str
    """'arcf' or 'todomvc' — see suite/repo_pool.py."""
    task_prompt: str

    expected_grounding: list[str] = Field(default_factory=list)
    """Repository Understanding only: terms (file paths, class names)
    the answer should mention to count as grounded."""
    expected_path_prefixes: list[str] = Field(default_factory=list)
    """Code-change categories: path prefixes a legitimate change is
    allowed to touch. A modified file matching no prefix counts toward
    unrelated_file_modifications. Empty list (Repository Understanding)
    means ANY modification is unrelated — nothing should change."""
    protected_path_prefixes: list[str] = Field(default_factory=list)
    """Paths the patcher refuses to write to even if the model's output
    names them — e.g. ['tests/'] for arcf bug-fixing/refactoring tasks,
    so a model can't "fix" a bug by rewriting the oracle test instead
    of the source. Not a scoring signal; a hard write-time guard."""

    bug_fixture: BugFixture | None = None
    verify_command: str | None = None
    """Shell command run inside the scratch repo root (or verify_cwd
    beneath it) to decide tests_passed. None for Repository
    Understanding (no execution oracle applies)."""
    verify_cwd: str = "."
    verify_timeout_seconds: int = 60


class ModeVerification(BaseModel):
    model_config = ConfigDict(frozen=True)

    tests_passed: bool | None
    """None = this task category has no execution oracle (Repository
    Understanding) or the patch could not be applied at all — the two
    are distinguished by patch_applied below, not conflated."""
    patch_applied: bool
    accuracy_score: float | None
    unrelated_file_modifications: int
    verification_output_tail: str = ""
    """Last ~2000 chars of the verify command's combined stdout+stderr,
    for debugging a failing run without re-executing it."""


class SuiteModeRunRecord(BaseModel):
    """The persisted unit of work: one task run through exactly one
    mode (`arcf-benchmark suite run --suite X --mode Y` runs and stores
    one of these per task). SuiteTaskResult below is assembled LATER,
    at report time, from whichever modes have been run so far — mode
    runs are independent CLI invocations by design, matching how
    `arcf benchmark run --suite ... --mode ...` is meant to be used.
    """

    model_config = ConfigDict(frozen=True)

    task_id: str
    category: TaskCategory
    subcategory: str
    mode: BenchmarkMode
    run: RunResult
    verification: ModeVerification


class SuiteTaskResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    category: TaskCategory
    subcategory: str
    comparison: ComparisonResult

    direct_verification: ModeVerification | None = None
    arcf_verification: ModeVerification | None = None
    arcf_local_verification: ModeVerification | None = None


class CategorySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: TaskCategory
    task_count: int
    arcf_wins: int
    direct_wins: int


class SuiteRunSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    suite_name: str
    task_count: int

    avg_token_reduction_pct: float | None
    avg_latency_reduction_pct: float | None
    avg_cost_reduction_pct: float | None
    avg_cer: float | None
    avg_pcr: float | None
    avg_accuracy_delta: float | None
    """mean(arcf.accuracy_score - direct.accuracy_score) across ALL
    tasks where both are non-null — blends grounding accuracy
    (Repository Understanding) with test-pass accuracy (every other
    category), since accuracy_score means different things per
    category. See avg_direct_grounding_score/avg_arcf_grounding_score
    below for the Repository-Understanding-only figure the v2.3
    Execution Directive's executive report asks for by name."""
    avg_direct_grounding_score: float | None
    """mean(direct.accuracy_score) over REPOSITORY_UNDERSTANDING tasks
    only — the fraction of expected_grounding terms Direct's answer
    mentioned, averaged. None if no such tasks have both modes' data."""
    avg_arcf_grounding_score: float | None
    """Same as avg_direct_grounding_score, for ARCF."""
    avg_unrelated_file_modifications_delta: float | None
    """mean(arcf.unrelated_file_modifications - direct.unrelated_file_modifications).
    <= 0 means ARCF touched no more unrelated files than Direct did."""

    tasks_won_by_arcf: int
    tasks_won_by_direct: int
    tasks_tied: int
    category_summaries: list[CategorySummary]

    latency_ttest_p_value: float | None
    """Paired t-test, Direct vs ARCF Remote latency."""
    token_ttest_p_value: float | None
    """Paired t-test, Direct vs ARCF Remote tokens."""
    latency_ttest_p_value_local: float | None
    """Paired t-test, Direct vs ARCF Local latency."""
    token_ttest_p_value_local: float | None
    """Paired t-test, Direct vs ARCF Local tokens."""

    verdict: str
    """'continue' | 'pivot' | 'stop' — computed mechanically from the
    stated Success Criteria in suite/report.py, never hand-written."""
