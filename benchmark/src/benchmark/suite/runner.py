"""SuiteRunner — orchestrates one suite task through one mode: prepare
a scratch repo (+ bug fixture), run the SAME DirectLLMRunner/ArcfRunner
instances bootstrap.build_runtime already constructed (pointed at the
scratch repo instead of a real one), apply the model's output, verify,
score, and always discard the scratch copy afterward.

Nothing here re-implements ARCF's pipeline or the Direct/ARCF runners —
this module's only job is repo lifecycle + verification wiring around
calls that already exist.
"""

from pathlib import Path

from domain.workspace import WorkspaceMetadata
from workspace.analyzer import WorkspaceAnalyzer
from workspace.scanner import RepositoryScanner

from benchmark.domain.models import BenchmarkMode, RunResult
from benchmark.repository import LoadedRepository
from benchmark.runners.arcf_runner import ArcfRunner
from benchmark.runners.direct_llm_runner import DirectLLMRunner
from benchmark.suite.fixtures import apply_bug_fixture
from benchmark.suite.models import ModeVerification, SuiteTask, TaskCategory
from benchmark.suite.patcher import FORMAT_ADDENDUM, apply_output_to_repo
from benchmark.suite.repo_pool import RepoPool
from benchmark.suite.scoring import score
from benchmark.suite.verifier import VerificationResult, run_verification


class SuiteRunError(Exception):
    pass


class SuiteRunner:
    def __init__(
        self,
        repo_pool: RepoPool,
        direct_runner: DirectLLMRunner,
        arcf_runner: ArcfRunner,
        arcf_local_runner: ArcfRunner | None,
        workspace_analyzer: WorkspaceAnalyzer,
        scanner: RepositoryScanner,
        model: str,
        max_context_tokens: int,
        max_output_tokens: int,
    ) -> None:
        self._repo_pool = repo_pool
        self._runners: dict[BenchmarkMode, DirectLLMRunner | ArcfRunner | None] = {
            BenchmarkMode.DIRECT: direct_runner,
            BenchmarkMode.ARCF: arcf_runner,
            BenchmarkMode.ARCF_LOCAL: arcf_local_runner,
        }
        self._workspace_analyzer = workspace_analyzer
        self._scanner = scanner
        self._model = model
        self._max_context_tokens = max_context_tokens
        self._max_output_tokens = max_output_tokens

    async def run_task_mode(
        self, task: SuiteTask, mode: BenchmarkMode
    ) -> tuple[RunResult, ModeVerification]:
        runner = self._runners.get(mode)
        if runner is None:
            raise SuiteRunError(f"No runner configured for mode {mode} (arcf_local unavailable?)")

        scratch_dir = self._repo_pool.scratch_copy(task.repo_key)
        try:
            if task.bug_fixture is not None:
                apply_bug_fixture(scratch_dir, task.bug_fixture)

            repo = self._load_repo(scratch_dir)
            prompt_text = (
                task.task_prompt
                if task.category is TaskCategory.REPOSITORY_UNDERSTANDING
                else task.task_prompt + FORMAT_ADDENDUM
            )

            if isinstance(runner, DirectLLMRunner):
                run = await runner.run(
                    repo.root,
                    repo.scan,
                    prompt_text,
                    self._model,
                    self._max_context_tokens,
                    self._max_output_tokens,
                )
            else:
                run = await runner.run(
                    repo.root,
                    len(repo.scan.files),
                    prompt_text,
                    self._model,
                    self._max_context_tokens,
                    self._max_output_tokens,
                )

            verification = self._verify(task, scratch_dir, run)
            return run, verification
        finally:
            RepoPool.discard(scratch_dir)

    def _load_repo(self, scratch_dir: Path) -> LoadedRepository:
        metadata: WorkspaceMetadata = self._workspace_analyzer.analyze(scratch_dir)
        scan = self._scanner.scan(scratch_dir)
        return LoadedRepository(root=scratch_dir, metadata=metadata, scan=scan)

    def _verify(self, task: SuiteTask, scratch_dir: Path, run: RunResult) -> ModeVerification:
        if task.category is TaskCategory.REPOSITORY_UNDERSTANDING:
            return score(task, run)

        patch = apply_output_to_repo(
            scratch_dir, run.generated_output, task.protected_path_prefixes
        )
        verification: VerificationResult | None = None
        if patch.applied and task.verify_command:
            command = task.verify_command.format(python=self._repo_pool.arcf_venv_python)
            verification = run_verification(
                scratch_dir, command, task.verify_cwd, task.verify_timeout_seconds
            )
        return score(task, run, patch, verification)
