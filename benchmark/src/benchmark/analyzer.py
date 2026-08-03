"""BenchmarkAnalyzer — computes cross-mode reduction percentages and the
benchmark-level CER/PCR (ARCF vs. Direct — not to be confused with
ContextResolutionResult.token_estimate.compression_ratio, which is
ARCF's own internal, whole-workspace-relative view; these two are
deliberately different denominators for different questions).

CER = arcf.files_sent_to_llm / direct.files_sent_to_llm
PCR = direct.input_tokens / arcf.input_tokens
matching the report example's exact formulas. arcf_local (Mode C) gets
the identical pair of formulas against direct, plus one comparison
that's the actual point of Mode C's existence:
local_vs_remote_latency_reduction_pct, i.e. did local SLM-1 make the
ARCF pipeline faster than remote SLM-1 did.
"""

from benchmark.domain.models import ComparisonResult, RunResult


class BenchmarkAnalyzer:
    def compare(
        self,
        task: str,
        repository: str,
        model: str,
        direct: RunResult | None,
        arcf: RunResult | None,
        arcf_local: RunResult | None = None,
    ) -> ComparisonResult:
        token_reduction = None
        latency_reduction = None
        cost_reduction = None
        cer = None
        pcr = None

        if direct is not None and arcf is not None:
            token_reduction = self._reduction_pct(
                direct.token_metrics.total_tokens, arcf.token_metrics.total_tokens
            )
            latency_reduction = self._reduction_pct(
                direct.latency_metrics.total_ms, arcf.latency_metrics.total_ms
            )
            cost_reduction = self._reduction_pct(
                direct.cost_metrics.actual_cost_usd, arcf.cost_metrics.actual_cost_usd
            )
            cer = self._ratio(
                arcf.context_metrics.files_sent_to_llm, direct.context_metrics.files_sent_to_llm
            )
            pcr = self._ratio(direct.token_metrics.input_tokens, arcf.token_metrics.input_tokens)

        local_token_reduction = None
        local_latency_reduction = None
        local_cost_reduction = None
        local_cer = None
        local_pcr = None
        local_vs_remote_latency_reduction = None

        if direct is not None and arcf_local is not None:
            local_token_reduction = self._reduction_pct(
                direct.token_metrics.total_tokens, arcf_local.token_metrics.total_tokens
            )
            local_latency_reduction = self._reduction_pct(
                direct.latency_metrics.total_ms, arcf_local.latency_metrics.total_ms
            )
            local_cost_reduction = self._reduction_pct(
                direct.cost_metrics.actual_cost_usd, arcf_local.cost_metrics.actual_cost_usd
            )
            local_cer = self._ratio(
                arcf_local.context_metrics.files_sent_to_llm,
                direct.context_metrics.files_sent_to_llm,
            )
            local_pcr = self._ratio(
                direct.token_metrics.input_tokens, arcf_local.token_metrics.input_tokens
            )

        if arcf is not None and arcf_local is not None:
            local_vs_remote_latency_reduction = self._reduction_pct(
                arcf.latency_metrics.total_ms, arcf_local.latency_metrics.total_ms
            )

        return ComparisonResult(
            task=task,
            repository=repository,
            model=model,
            direct=direct,
            arcf=arcf,
            arcf_local=arcf_local,
            token_reduction_pct=token_reduction,
            latency_reduction_pct=latency_reduction,
            cost_reduction_pct=cost_reduction,
            context_efficiency_ratio=cer,
            prompt_compression_ratio=pcr,
            local_token_reduction_pct=local_token_reduction,
            local_latency_reduction_pct=local_latency_reduction,
            local_cost_reduction_pct=local_cost_reduction,
            local_context_efficiency_ratio=local_cer,
            local_prompt_compression_ratio=local_pcr,
            local_vs_remote_latency_reduction_pct=local_vs_remote_latency_reduction,
        )

    @staticmethod
    def _reduction_pct(direct_value: float, other_value: float) -> float | None:
        if direct_value <= 0:
            return None
        return round((direct_value - other_value) / direct_value * 100, 2)

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float | None:
        if denominator <= 0:
            return None
        return round(numerator / denominator, 4)
