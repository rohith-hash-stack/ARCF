"""BenchmarkController — orchestrates one benchmark invocation (Direct,
ARCF, or both) and hands the results to BenchmarkAnalyzer.
"""

from benchmark.analyzer import BenchmarkAnalyzer
from benchmark.domain.models import BenchmarkMode, ComparisonResult, RunResult
from benchmark.local_slm.errors import LocalSLMUnavailableError
from benchmark.repository import LoadedRepository
from benchmark.runners.arcf_runner import ArcfRunner
from benchmark.runners.direct_llm_runner import DirectLLMRunner


class BenchmarkController:
    def __init__(
        self,
        direct_runner: DirectLLMRunner,
        arcf_runner: ArcfRunner,
        analyzer: BenchmarkAnalyzer,
        arcf_local_runner: ArcfRunner | None = None,
    ) -> None:
        self._direct_runner = direct_runner
        self._arcf_runner = arcf_runner
        self._arcf_local_runner = arcf_local_runner
        """None when no local SLM is available (e.g. Ollama unreachable
        or none of the priority candidates installed) — Mode C is then
        simply not offered, Direct/Remote are unaffected."""
        self._analyzer = analyzer

    async def run(
        self,
        repo: LoadedRepository,
        task: str,
        model: str,
        modes: list[BenchmarkMode],
        max_context_tokens: int,
        max_output_tokens: int,
    ) -> ComparisonResult:
        direct: RunResult | None = None
        arcf: RunResult | None = None
        arcf_local: RunResult | None = None

        if BenchmarkMode.DIRECT in modes:
            direct = await self._direct_runner.run(
                repo.root, repo.scan, task, model, max_context_tokens, max_output_tokens
            )
        if BenchmarkMode.ARCF in modes:
            arcf = await self._arcf_runner.run(
                repo.root,
                len(repo.scan.files),
                task,
                model,
                max_context_tokens,
                max_output_tokens,
            )
        if BenchmarkMode.ARCF_LOCAL in modes:
            if self._arcf_local_runner is None:
                raise LocalSLMUnavailableError(
                    "Mode C (arcf_local) was requested but no local SLM runner is configured "
                    "— see startup logs for why local SLM resolution failed."
                )
            arcf_local = await self._arcf_local_runner.run(
                repo.root,
                len(repo.scan.files),
                task,
                model,
                max_context_tokens,
                max_output_tokens,
            )

        return self._analyzer.compare(
            task=task,
            repository=str(repo.root),
            model=model,
            direct=direct,
            arcf=arcf,
            arcf_local=arcf_local,
        )
