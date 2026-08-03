"""Integration test for SuiteRunner — exercises the real RepoPool,
fixtures, patcher, verifier, and scoring together, with only the LLM
call itself mocked (same rationale as tests/api/test_routes.py's
patched_llm: proves the real wiring works on a controlled response).
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import litellm
import pytest
from infrastructure.cost import CostEstimator
from infrastructure.llm_client import LiteLLMClient
from workspace.analyzer import WorkspaceAnalyzer
from workspace.git_discovery import GitRepositoryDiscovery
from workspace.language_detection import LanguageDetector
from workspace.scanner import RepositoryScanner
from workspace.structure_analyzer import ProjectStructureAnalyzer

from benchmark.domain.models import BenchmarkMode
from benchmark.runners.direct_llm_runner import DirectLLMRunner
from benchmark.suite.models import BugFixture, SuiteTask, TaskCategory
from benchmark.suite.repo_pool import RepoPool
from benchmark.suite.runner import SuiteRunner


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )


@pytest.fixture
def repo_pool(tmp_path: Path) -> RepoPool:
    arcf_root = tmp_path / "arcf"
    (arcf_root / "src").mkdir(parents=True)
    (arcf_root / "src" / "mod.py").write_text("def add(a, b):\n    return a + b\n")
    pool = RepoPool(arcf_root=arcf_root, suite_repos_root=tmp_path / "suite_repos")
    pool.ensure_arcf_base()
    return pool


def _runner(repo_pool: RepoPool) -> SuiteRunner:
    llm_client = LiteLLMClient(max_retries=1, base_delay_seconds=0.01)
    cost_estimator = CostEstimator()
    workspace_analyzer = WorkspaceAnalyzer(
        git_discovery=GitRepositoryDiscovery(),
        scanner=RepositoryScanner(),
        language_detector=LanguageDetector(),
        structure_analyzer=ProjectStructureAnalyzer(),
    )
    return SuiteRunner(
        repo_pool=repo_pool,
        direct_runner=DirectLLMRunner(llm_client=llm_client, cost_estimator=cost_estimator),
        arcf_runner=None,  # type: ignore[arg-type]
        arcf_local_runner=None,
        workspace_analyzer=workspace_analyzer,
        scanner=RepositoryScanner(),
        model="gpt-4o-mini",
        max_context_tokens=10_000,
        max_output_tokens=512,
    )


async def test_bug_fixing_task_full_flow(
    monkeypatch: pytest.MonkeyPatch, repo_pool: RepoPool
) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("### src/mod.py\n```\ndef add(a, b):\n    return a + b\n```")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(type(repo_pool), "arcf_venv_python", property(lambda self: sys.executable))

    task = SuiteTask(
        id="bug1",
        category=TaskCategory.BUG_FIXING,
        subcategory="off_by_one",
        repo_key="arcf",
        task_prompt="add() is off by one, fix it",
        expected_path_prefixes=["src/mod.py"],
        bug_fixture=BugFixture(
            file_path="src/mod.py", find="return a + b", replace="return a + b + 1"
        ),
        verify_command=(
            '"{python}" -c '
            '"import sys; sys.path.insert(0, \'src\'); from mod import add; '
            'assert add(2, 3) == 5"'
        ),
        verify_cwd=".",
        verify_timeout_seconds=30,
    )

    runner = _runner(repo_pool)
    run, verification = await runner.run_task_mode(task, BenchmarkMode.DIRECT)

    assert verification.patch_applied is True
    assert verification.tests_passed is True
    assert verification.accuracy_score == 1.0
    assert verification.unrelated_file_modifications == 0
    assert run.generated_output.startswith("### src/mod.py")


async def test_bug_fixing_task_still_broken_fails_verification(
    monkeypatch: pytest.MonkeyPatch, repo_pool: RepoPool
) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        # "fix" that doesn't actually fix anything
        return _fake_response("### src/mod.py\n```\ndef add(a, b):\n    return a + b + 1\n```")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(type(repo_pool), "arcf_venv_python", property(lambda self: sys.executable))

    task = SuiteTask(
        id="bug1",
        category=TaskCategory.BUG_FIXING,
        subcategory="off_by_one",
        repo_key="arcf",
        task_prompt="add() is off by one, fix it",
        expected_path_prefixes=["src/mod.py"],
        bug_fixture=BugFixture(
            file_path="src/mod.py", find="return a + b", replace="return a + b + 1"
        ),
        verify_command=(
            '"{python}" -c '
            '"import sys; sys.path.insert(0, \'src\'); from mod import add; '
            'assert add(2, 3) == 5"'
        ),
        verify_cwd=".",
        verify_timeout_seconds=30,
    )

    runner = _runner(repo_pool)
    _, verification = await runner.run_task_mode(task, BenchmarkMode.DIRECT)

    assert verification.patch_applied is True
    assert verification.tests_passed is False
    assert verification.accuracy_score == 0.0


async def test_repository_understanding_task_no_patch_or_verify(
    monkeypatch: pytest.MonkeyPatch, repo_pool: RepoPool
) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("The add function lives in src/mod.py.")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    task = SuiteTask(
        id="understand1",
        category=TaskCategory.REPOSITORY_UNDERSTANDING,
        subcategory="x",
        repo_key="arcf",
        task_prompt="Where does add() live?",
        expected_grounding=["src/mod.py"],
    )

    runner = _runner(repo_pool)
    _, verification = await runner.run_task_mode(task, BenchmarkMode.DIRECT)

    assert verification.tests_passed is None
    assert verification.accuracy_score == 1.0
    assert verification.unrelated_file_modifications == 0
