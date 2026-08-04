"""Proves the 40-task suite (ARCF v2.3 Execution Directive, Action 3)
is structurally sound and actually drivable through the real
SuiteRunner + LedgerRecorder pipeline — without spending real money on
LLM calls (litellm is mocked, same technique as tests/suite/
test_runner.py). Two things are proven here that a plain JSON-schema
check can't:

1. The suite loads, has the right shape (40 tasks, 8 per category,
   unique ids), and every code-change task has a verify_command (a
   patch that happens to apply with no verify_command crashes
   score_execution — see suite/scoring.py).
2. The two Bug Fixing tasks with a real, hand-written bug_fixture
   (401 auth bypass, JWT signature bypass) apply cleanly and uniquely
   against the actual arcf/src/infrastructure/auth.py this repository
   ships today — proven both statically here (exact-one-match, valid
   Python after patching) and, in this session's own verification
   (not an automated test — see the conversation), dynamically: with
   the fixture applied, `pytest tests/infrastructure/test_auth.py`
   genuinely fails on the exact tests you'd expect, and passes again
   once reverted.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import litellm
import pytest
from infrastructure.cost import CostEstimator
from infrastructure.execution_ledger_db import InMemoryExecutionLedgerStore
from infrastructure.llm_client import LiteLLMClient
from workspace.analyzer import WorkspaceAnalyzer
from workspace.git_discovery import GitRepositoryDiscovery
from workspace.language_detection import LanguageDetector
from workspace.scanner import RepositoryScanner
from workspace.structure_analyzer import ProjectStructureAnalyzer

from benchmark.domain.models import BenchmarkMode
from benchmark.ledger import LedgerRecorder
from benchmark.runners.direct_llm_runner import DirectLLMRunner
from benchmark.suite.loader import load_suite
from benchmark.suite.models import SuiteTask, TaskCategory
from benchmark.suite.repo_pool import RepoPool
from benchmark.suite.runner import SuiteRunner

_SUITE_PATH = Path(__file__).resolve().parents[2] / "suites" / "v23_baseline_40.json"
_ARCF_ROOT = Path(__file__).resolve().parents[3] / "arcf"
_AUTH_SOURCE = _ARCF_ROOT / "src" / "infrastructure" / "auth.py"


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )


# --- 1. Structural shape -----------------------------------------------------


def test_suite_has_exactly_forty_tasks_eight_per_category() -> None:
    tasks = load_suite(_SUITE_PATH)
    assert len(tasks) == 40

    counts: dict[str, int] = {}
    for task in tasks:
        counts[task.category.value] = counts.get(task.category.value, 0) + 1
    assert counts == {category.value: 8 for category in TaskCategory}


def test_suite_task_ids_are_unique() -> None:
    tasks = load_suite(_SUITE_PATH)
    ids = [t.id for t in tasks]
    assert len(set(ids)) == len(ids)


def test_every_non_understanding_task_has_a_verify_command() -> None:
    """A patch that applies with verify_command=None crashes
    score_execution (see suite/scoring.py) — every code-change-category
    task in the suite must set one, or a lucky/well-behaved model
    output would crash the run instead of scoring it."""
    tasks = load_suite(_SUITE_PATH)
    for task in tasks:
        if task.category is TaskCategory.REPOSITORY_UNDERSTANDING:
            continue
        assert task.verify_command, f"{task.id} has no verify_command"


def test_repository_understanding_tasks_have_expected_grounding() -> None:
    tasks = load_suite(_SUITE_PATH)
    for task in tasks:
        if task.category is TaskCategory.REPOSITORY_UNDERSTANDING:
            assert task.expected_grounding, f"{task.id} has no expected_grounding terms"


def test_only_two_repo_keys_used_matching_registered_repo_pool_bases() -> None:
    tasks = load_suite(_SUITE_PATH)
    assert {t.repo_key for t in tasks} <= {"arcf", "todomvc"}


# --- 2. The two real bug fixtures, proven against the actual auth.py --------


def _bug_fixing_tasks_with_fixtures() -> list[SuiteTask]:
    return [t for t in load_suite(_SUITE_PATH) if t.bug_fixture is not None]


def test_at_least_two_bug_fixing_tasks_have_a_real_fixture() -> None:
    assert len(_bug_fixing_tasks_with_fixtures()) >= 2


@pytest.mark.parametrize(
    "task", _bug_fixing_tasks_with_fixtures(), ids=lambda t: t.id
)
def test_bug_fixture_applies_uniquely_and_stays_valid_python(task: SuiteTask) -> None:
    assert task.bug_fixture is not None
    assert _AUTH_SOURCE.exists(), (
        "This test assumes it runs from within the arcf/benchmark sibling-directory "
        "layout this session used — adjust _ARCF_ROOT if that's changed."
    )
    original = _AUTH_SOURCE.read_text(encoding="utf-8")
    match_count = original.count(task.bug_fixture.find)
    assert match_count == 1, (
        f"{task.id}: bug_fixture.find matched {match_count} times in "
        f"{task.bug_fixture.file_path}, expected exactly 1"
    )

    patched = original.replace(task.bug_fixture.find, task.bug_fixture.replace)
    assert patched != original
    compile(patched, str(_AUTH_SOURCE), "exec")  # raises SyntaxError if invalid


# --- 3. End-to-end through the real SuiteRunner + LedgerRecorder ------------


@pytest.fixture
def toy_arcf_repo_pool(tmp_path: Path) -> RepoPool:
    arcf_root = tmp_path / "arcf"
    (arcf_root / "src").mkdir(parents=True)
    (arcf_root / "src" / "mod.py").write_text("def add(a, b):\n    return a + b\n")
    pool = RepoPool(arcf_root=arcf_root, suite_repos_root=tmp_path / "suite_repos")
    pool.ensure_arcf_base()
    return pool


async def test_repository_understanding_task_runs_end_to_end_and_writes_ledger(
    monkeypatch: pytest.MonkeyPatch, toy_arcf_repo_pool: RepoPool
) -> None:
    """Loads the REAL 'repo-understanding-auth-flow' task from the suite
    file (not a hand-rewritten duplicate) and drives it through
    SuiteRunner exactly as `benchmark suite run` would, proving Action 2's
    automatic Ledger write also fires for suite-mode runs of this suite,
    not just ad-hoc `benchmark compare` runs.
    """
    task = next(t for t in load_suite(_SUITE_PATH) if t.id == "repo-understanding-auth-flow")

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        # Mentions every expected_grounding term so scoring is unambiguous —
        # this test is about the pipeline wiring, not the scoring math
        # (see tests/suite/test_scoring.py for that).
        answer = " ".join(task.expected_grounding) + " handles authentication."
        return _fake_response(answer)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    llm_client = LiteLLMClient(max_retries=1, base_delay_seconds=0.01)
    cost_estimator = CostEstimator()
    workspace_analyzer = WorkspaceAnalyzer(
        git_discovery=GitRepositoryDiscovery(),
        scanner=RepositoryScanner(),
        language_detector=LanguageDetector(),
        structure_analyzer=ProjectStructureAnalyzer(),
    )
    ledger_store = InMemoryExecutionLedgerStore()
    runner = SuiteRunner(
        repo_pool=toy_arcf_repo_pool,
        direct_runner=DirectLLMRunner(llm_client=llm_client, cost_estimator=cost_estimator),
        arcf_runner=None,  # type: ignore[arg-type]
        arcf_local_runner=None,
        workspace_analyzer=workspace_analyzer,
        scanner=RepositoryScanner(),
        model="gpt-4o-mini",
        max_context_tokens=10_000,
        max_output_tokens=512,
        ledger_recorder=LedgerRecorder(ledger_store),
    )

    run, verification = await runner.run_task_mode(task, BenchmarkMode.DIRECT)

    assert verification.tests_passed is None  # no execution oracle for this category
    assert verification.accuracy_score == 1.0  # every expected_grounding term was mentioned

    entries = ledger_store.list_recent(limit=10)
    assert len(entries) == 1
    assert entries[0].mode == "direct"
    assert entries[0].execution_status == "success"
    assert task.task_prompt in entries[0].prompt


def test_suite_file_is_valid_json_with_a_tasks_array() -> None:
    data = json.loads(_SUITE_PATH.read_text(encoding="utf-8"))
    assert isinstance(data["tasks"], list)
    assert len(data["tasks"]) == 40
