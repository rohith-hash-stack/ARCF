"""DirectLLMRunner — Mode A: no ARCF pipeline, no context optimization,
no deterministic analysis.

Dumps every scanned file's content (bounded by max_context_tokens) into
the prompt in scan order — a faithful "just send everything" baseline,
not a strawman: it uses the SAME RepositoryScanner ARCF uses, so both
modes start from an identical file inventory. The only thing being
measured is the effect of ARCF's selection logic, not a different file
listing.
"""

import time
from pathlib import Path

from infrastructure.cost import CostEstimator
from infrastructure.llm_client import LiteLLMClient
from workspace.permissions import PermissionManager
from workspace.scanner import ScanResult

from benchmark.domain.models import (
    BenchmarkMode,
    ContextMetrics,
    CostMetrics,
    LatencyMetrics,
    RunResult,
    TokenMetrics,
)
from benchmark.quality import build_quality_metrics
from benchmark.runners.base import FileContext, compile_prompt, generate

_TOKEN_COUNTING_MODEL = "gpt-4o-mini"


class DirectLLMRunner:
    def __init__(self, llm_client: LiteLLMClient, cost_estimator: CostEstimator) -> None:
        self._llm_client = llm_client
        self._cost_estimator = cost_estimator

    async def run(
        self,
        repository_root: Path,
        scan: ScanResult,
        task: str,
        model: str,
        max_context_tokens: int,
        max_output_tokens: int,
    ) -> RunResult:
        start = time.perf_counter()
        permissions = PermissionManager(repository_root)

        files: list[FileContext] = []
        used_tokens = 0
        for scanned in scan.files:
            if permissions.is_sensitive(scanned.relative_path):
                continue
            try:
                content = permissions.safe_read_text(scanned.relative_path)
            except OSError:
                continue

            token_count = self._cost_estimator.count_tokens(content, _TOKEN_COUNTING_MODEL)
            if used_tokens + token_count > max_context_tokens:
                continue

            files.append(FileContext(file_path=scanned.relative_path, content=content))
            used_tokens += token_count

        prompt = compile_prompt(task, files)

        llm_start = time.perf_counter()
        response, estimated_cost, actual_cost = await generate(
            self._llm_client, self._cost_estimator, prompt, model, max_output_tokens
        )
        llm_ms = (time.perf_counter() - llm_start) * 1000
        total_ms = (time.perf_counter() - start) * 1000

        return RunResult(
            mode=BenchmarkMode.DIRECT,
            model=model,
            prompt=prompt,
            generated_output=response.content,
            token_metrics=TokenMetrics(
                input_tokens=response.prompt_tokens,
                output_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
            ),
            latency_metrics=LatencyMetrics(
                total_ms=total_ms, llm_ms=llm_ms, deterministic_ms=0.0, pipeline_overhead_ms=0.0
            ),
            cost_metrics=CostMetrics(
                estimated_cost_usd=estimated_cost,
                actual_cost_usd=actual_cost,
                pipeline_overhead_cost_usd=0.0,
            ),
            context_metrics=ContextMetrics(
                repository_files=len(scan.files),
                candidate_files=len(scan.files),
                files_sent_to_llm=len(files),
            ),
            quality_metrics=build_quality_metrics(response.content),
            referenced_files=[f.file_path for f in files],
        )
