"""ComparisonAggregator — computes cross-mode (direct vs. ARCF)
reduction percentages and CER/PCR from two ExecutionLedgerEntry
records. Stage 5 of the v2.3 migration plan (see
arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md Sec. 2.4/5.1/6/7).

Formulas generalized directly from benchmark/src/benchmark/analyzer.py's
BenchmarkAnalyzer, which this docstring quotes verbatim:

    CER = arcf.files_sent_to_llm / direct.files_sent_to_llm
    PCR = direct.input_tokens / arcf.input_tokens

translated to ExecutionLedgerEntry's fields: files_sent_to_llm ->
len(selected_files), input_tokens -> prompt_tokens. See
domain/comparison_result.py for why CER can legitimately be None.
"""

from domain.comparison_result import ComparisonResult
from domain.execution_ledger import ExecutionLedgerEntry


class ComparisonAggregator:
    def compare(
        self,
        task: str,
        repository: str,
        direct: ExecutionLedgerEntry,
        arcf: ExecutionLedgerEntry,
    ) -> ComparisonResult:
        return ComparisonResult(
            task=task,
            repository=repository,
            direct=direct,
            arcf=arcf,
            token_reduction_pct=self._reduction_pct(direct.total_tokens, arcf.total_tokens),
            latency_reduction_pct=self._reduction_pct(direct.latency_ms, arcf.latency_ms),
            cost_reduction_pct=self._reduction_pct(
                direct.estimated_cost_usd, arcf.estimated_cost_usd
            ),
            context_efficiency_ratio=self._ratio(
                len(arcf.selected_files), len(direct.selected_files)
            ),
            prompt_compression_ratio=self._ratio(direct.prompt_tokens, arcf.prompt_tokens),
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
