"""ArcfRunner — Mode B (remote SLM-1) and Mode C (local SLM-1): drives
ARCF's actual Phase 1-6 pipeline via the exact same classes
interfaces/api/app.py wires together (ExecutionContractManager ->
WorkspaceContractService -> CodeIntelligenceContractService ->
ContextPackager), then compiles a prompt from the resulting
ContextPackage and calls the LLM — the one step ARCF doesn't have yet
(Phase 7/8's prompt compiler + reasoning).

Modes B and C are two instances of this SAME class: bootstrap.py
constructs one with a remote slm_model/contract_manager and one with a
local one (resolved via local_slm.OllamaProvider), both sharing the
same workspace_service/code_intelligence_service/context_packager/
llm_client. The `mode` constructor arg only labels the RunResult; it
changes nothing about how the pipeline runs.

SLM-2 (ContextUnderstandingAnalyzer) is intentionally not exercised
here: the ContextPackager instance this runner is given should be
constructed with understanding_analyzer=None by the caller. It never
affects file selection (see context/packager.py's own docstring), so
leaving it out keeps the token/cost comparison clean without changing
what's actually sent to the LLM. Timing/latency code below still
handles the case where it IS enabled, for when that's toggled on later.

target_names for code intelligence resolution come from
UserIntent.entities (SLM-1's own extraction) — if a task doesn't
mention any existing named symbol (a green-field task, or one phrased
without specifics), entities may be empty and candidate selection can
legitimately return nothing. That is not papered over here: it is a
real, measurable characteristic of ARCF's current pipeline, and
surfacing it honestly is the point of the benchmark.
"""

import time
from pathlib import Path

from code_intelligence.service import CodeIntelligenceContractService
from context.packager import ContextPackager
from contracts.manager import ExecutionContractManager
from infrastructure.cost import CostEstimator
from infrastructure.llm_client import LiteLLMClient
from workspace.service import WorkspaceContractService

from benchmark.domain.models import (
    BenchmarkMode,
    ContextMetrics,
    CostMetrics,
    LatencyMetrics,
    RunResult,
    StageLatencies,
    TokenMetrics,
)
from benchmark.quality import build_quality_metrics
from benchmark.runners.base import FileContext, compile_prompt, generate


class ArcfRunner:
    def __init__(
        self,
        contract_manager: ExecutionContractManager,
        workspace_service: WorkspaceContractService,
        code_intelligence_service: CodeIntelligenceContractService,
        context_packager: ContextPackager,
        llm_client: LiteLLMClient,
        cost_estimator: CostEstimator,
        slm_model: str,
        mode: BenchmarkMode = BenchmarkMode.ARCF,
    ) -> None:
        self._contract_manager = contract_manager
        self._workspace_service = workspace_service
        self._code_intelligence_service = code_intelligence_service
        self._context_packager = context_packager
        self._llm_client = llm_client
        self._cost_estimator = cost_estimator
        self._slm_model = slm_model
        self._mode = mode
        """ARCF (Mode B, remote SLM-1) or ARCF_LOCAL (Mode C, local
        SLM-1) — this class's pipeline logic is identical either way;
        only the slm_model string and the intent_extractor inside
        contract_manager differ between the two callers that construct
        it (see bootstrap.py)."""

    async def run(
        self,
        repository_root: Path,
        repository_file_count: int,
        task: str,
        model: str,
        max_context_tokens: int,
        max_output_tokens: int,
    ) -> RunResult:
        start = time.perf_counter()
        root_str = str(repository_root)

        stage_start = time.perf_counter()
        living, intent_response = await self._contract_manager.create_contract(task, root_str)
        intent_ms = self._elapsed_ms(stage_start)
        intent_cost = self._actual_cost(
            intent_response.prompt_tokens, intent_response.completion_tokens
        )

        stage_start = time.perf_counter()
        living = await self._workspace_service.attach_workspace(living.contract_id, root_str)
        workspace_ms = self._elapsed_ms(stage_start)

        stage_start = time.perf_counter()
        target_names = living.contract.intent.entities
        living, resolution = await self._code_intelligence_service.attach_code_intelligence(
            living.contract_id, target_names, root_str
        )
        code_intelligence_ms = self._elapsed_ms(stage_start)

        stage_start = time.perf_counter()
        package, understanding_response = await self._context_packager.package(
            resolution, task, max_context_tokens
        )
        packaging_ms = self._elapsed_ms(stage_start)
        understanding_cost = 0.0
        if understanding_response is not None:
            understanding_cost = self._actual_cost(
                understanding_response.prompt_tokens, understanding_response.completion_tokens
            )

        files = [
            FileContext(file_path=f.file_path, content=f.content) for f in package.relevant_files
        ]
        prompt = compile_prompt(task, files)

        llm_start = time.perf_counter()
        response, estimated_cost, actual_cost = await generate(
            self._llm_client, self._cost_estimator, prompt, model, max_output_tokens
        )
        llm_ms = self._elapsed_ms(llm_start)
        total_ms = self._elapsed_ms(start)

        # Packaging is deterministic only when SLM-2 didn't run this call.
        packaging_is_deterministic = understanding_response is None
        deterministic_ms = workspace_ms + code_intelligence_ms + (
            packaging_ms if packaging_is_deterministic else 0.0
        )
        pipeline_overhead_ms = intent_ms + (0.0 if packaging_is_deterministic else packaging_ms)
        pipeline_overhead_cost = intent_cost + understanding_cost

        return RunResult(
            mode=self._mode,
            model=model,
            generated_output=response.content,
            token_metrics=TokenMetrics(
                input_tokens=response.prompt_tokens,
                output_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
            ),
            latency_metrics=LatencyMetrics(
                total_ms=total_ms,
                llm_ms=llm_ms,
                deterministic_ms=deterministic_ms,
                pipeline_overhead_ms=pipeline_overhead_ms,
                stages=StageLatencies(
                    intent_extraction_ms=intent_ms,
                    workspace_scan_ms=workspace_ms,
                    code_intelligence_ms=code_intelligence_ms,
                    context_resolution_ms=code_intelligence_ms,
                    context_packaging_ms=packaging_ms,
                    final_llm_ms=llm_ms,
                    total_pipeline_ms=total_ms,
                ),
            ),
            cost_metrics=CostMetrics(
                estimated_cost_usd=estimated_cost,
                actual_cost_usd=actual_cost,
                pipeline_overhead_cost_usd=pipeline_overhead_cost,
            ),
            context_metrics=ContextMetrics(
                repository_files=repository_file_count,
                candidate_files=len(resolution.candidate_files),
                files_sent_to_llm=len(package.relevant_files),
            ),
            quality_metrics=build_quality_metrics(response.content),
            contract=living.contract,
            context_resolution=resolution,
            context_package=package,
        )

    def _actual_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return self._cost_estimator.actual_cost(prompt_tokens, completion_tokens, self._slm_model)

    @staticmethod
    def _elapsed_ms(since: float) -> float:
        return (time.perf_counter() - since) * 1000
