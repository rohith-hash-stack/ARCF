"""BenchmarkController — orchestrates one benchmark invocation (Direct,
ARCF, or both) and hands the results to BenchmarkAnalyzer.

Also the seam where every execution gets recorded to the Execution
Ledger (Action 2 of the ARCF v2.3 Execution Directive) — success or
failure, per mode. Each mode's runner call is wrapped individually: a
failure is logged to the Ledger via LedgerRecorder and that mode's
result stays None in the returned ComparisonResult, exactly the shape
BenchmarkAnalyzer.compare() already tolerates for a missing mode. This
is a deliberate change from the previous all-or-nothing behavior —
previously, ANY single mode raising aborted the whole comparison and
lost every mode's data, including ones that had already succeeded.

Only if EVERY requested mode fails does .run() still raise (the last
exception), so callers that convert exceptions to HTTP errors
(api/routes.py's 502 on a fully-failed run) keep working unchanged —
a partially-failed multi-mode run now returns whatever succeeded
instead of losing it, which is strictly more information, never less.
"""

import logging

from domain.workspace import RepositoryMetadata

from benchmark.analyzer import BenchmarkAnalyzer
from benchmark.domain.models import BenchmarkMode, ComparisonResult, RunResult
from benchmark.ledger import LedgerRecorder
from benchmark.local_slm.errors import LocalSLMUnavailableError
from benchmark.repository import LoadedRepository
from benchmark.runners.arcf_runner import ArcfRunner
from benchmark.runners.direct_llm_runner import DirectLLMRunner

logger = logging.getLogger(__name__)


class BenchmarkController:
    def __init__(
        self,
        direct_runner: DirectLLMRunner,
        arcf_runner: ArcfRunner,
        analyzer: BenchmarkAnalyzer,
        ledger_recorder: LedgerRecorder,
        arcf_local_runner: ArcfRunner | None = None,
    ) -> None:
        self._direct_runner = direct_runner
        self._arcf_runner = arcf_runner
        self._arcf_local_runner = arcf_local_runner
        """None when no local SLM is available (e.g. Ollama unreachable
        or none of the priority candidates installed) — Mode C is then
        simply not offered, Direct/Remote are unaffected."""
        self._analyzer = analyzer
        self._ledger_recorder = ledger_recorder

    async def run(
        self,
        repo: LoadedRepository,
        task: str,
        model: str,
        modes: list[BenchmarkMode],
        max_context_tokens: int,
        max_output_tokens: int,
        provider: str | None = None,
    ) -> ComparisonResult:
        branch = self._branch_of(repo)
        direct: RunResult | None = None
        arcf: RunResult | None = None
        arcf_local: RunResult | None = None
        last_exc: Exception | None = None

        if BenchmarkMode.DIRECT in modes:
            direct, last_exc = await self._execute_mode(
                BenchmarkMode.DIRECT, self._direct_runner, repo, task, model,
                max_context_tokens, max_output_tokens, provider, branch,
            )
        if BenchmarkMode.ARCF in modes:
            arcf, exc = await self._execute_mode(
                BenchmarkMode.ARCF, self._arcf_runner, repo, task, model,
                max_context_tokens, max_output_tokens, provider, branch,
            )
            last_exc = exc or last_exc
        if BenchmarkMode.ARCF_LOCAL in modes:
            if self._arcf_local_runner is None:
                raise LocalSLMUnavailableError(
                    "Mode C (arcf_local) was requested but no local SLM runner is configured "
                    "— see startup logs for why local SLM resolution failed."
                )
            arcf_local, exc = await self._execute_mode(
                BenchmarkMode.ARCF_LOCAL, self._arcf_local_runner, repo, task, model,
                max_context_tokens, max_output_tokens, provider, branch,
            )
            last_exc = exc or last_exc

        all_requested_modes_failed = (
            modes and direct is None and arcf is None and arcf_local is None
        )
        if all_requested_modes_failed and last_exc is not None:
            raise last_exc

        return self._analyzer.compare(
            task=task,
            repository=str(repo.root),
            model=model,
            direct=direct,
            arcf=arcf,
            arcf_local=arcf_local,
        )

    async def _execute_mode(
        self,
        mode: BenchmarkMode,
        runner: DirectLLMRunner | ArcfRunner,
        repo: LoadedRepository,
        task: str,
        model: str,
        max_context_tokens: int,
        max_output_tokens: int,
        provider: str | None,
        branch: str | None,
    ) -> tuple[RunResult | None, Exception | None]:
        try:
            if isinstance(runner, DirectLLMRunner):
                run = await runner.run(
                    repo.root, repo.scan, task, model, max_context_tokens, max_output_tokens
                )
            else:
                run = await runner.run(
                    repo.root,
                    len(repo.scan.files),
                    task,
                    model,
                    max_context_tokens,
                    max_output_tokens,
                )
        except Exception as exc:  # noqa: BLE001 — no benchmark result may ever be lost
            logger.warning("%s mode failed for task %r: %s", mode.value, task, exc)
            self._ledger_recorder.record_failure(
                mode=mode,
                exc=exc,
                repository_root=repo.root,
                branch=branch,
                prompt=task,
                model=model,
                provider=provider,
            )
            return None, exc

        self._ledger_recorder.record_success(
            mode=mode,
            run=run,
            repository_root=repo.root,
            branch=branch,
            prompt=task,
            provider=provider,
        )
        return run, None

    @staticmethod
    def _branch_of(repo: LoadedRepository) -> str | None:
        repository: RepositoryMetadata = repo.metadata.repository
        return repository.current_branch
