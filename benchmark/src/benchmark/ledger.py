"""ledger.py — Action 2 of the ARCF v2.3 Execution Directive: automatic
Execution Ledger writes. This is the single place a benchmark run
becomes a persisted ExecutionLedgerEntry, for both success and failure.

Lives here, not inside DirectLLMRunner/ArcfRunner: those two classes
stay focused on "run one execution and return a RunResult," the same
responsibility they had before this file existed. LedgerRecorder is
used by the two orchestration seams that actually invoke a runner —
BenchmarkController.run() (used by `benchmark compare` and the
benchmark API's /benchmark/run) and SuiteRunner.run_task_mode() (used
by `benchmark suite run`) — so every execution path funnels through
one recorder instead of four copies of the same wiring.

No result is ever lost: record_failure() is called from a caller's
except block, classifying the exception into ExecutionStatus's
timeout/provider_error/validation_error/execution_error taxonomy and
writing a Ledger entry even though there's no RunResult to draw
token/latency/cost figures from for a run that never completed —
those fields are recorded as zero, not omitted, so the entry always
validates against the same schema a successful run produces.
"""

from pathlib import Path

from domain.execution_ledger import ExecutionLedgerEntry, ExecutionMode, ExecutionStatus
from infrastructure.execution_ledger_db import ExecutionLedgerStore
from shared.errors import (
    ContextUnderstandingError,
    IntentExtractionError,
    LLMInvocationError,
    NoWorkspaceAttachedError,
    WorkspaceNotAllowedError,
    WorkspacePathError,
)

from benchmark.domain.models import BenchmarkMode, RunResult
from benchmark.local_slm.errors import LocalSLMUnavailableError

_MODE_TO_LEDGER_MODE: dict[BenchmarkMode, ExecutionMode] = {
    BenchmarkMode.DIRECT: "direct",
    BenchmarkMode.ARCF: "arcf",
    # The Ledger's ExecutionMode has no distinct "local" value — ARCF Local
    # is still fundamentally the "arcf" pipeline; which SLM-1 it used
    # (remote vs. local) is recorded in `provider`/`metadata` instead of a
    # third mode value, so CER/PCR aggregation (keyed on direct vs. arcf)
    # doesn't need a third branch.
    BenchmarkMode.ARCF_LOCAL: "arcf",
}

_VALIDATION_ERRORS = (
    WorkspacePathError,
    WorkspaceNotAllowedError,
    NoWorkspaceAttachedError,
    IntentExtractionError,
    ContextUnderstandingError,
)


def classify_exception(exc: Exception) -> ExecutionStatus:
    """Maps a runner-raised exception to one of ExecutionStatus's
    failure categories. Falls back to "execution_error" for anything
    not specifically recognized — an unclassified failure is still
    recorded, never silently dropped.
    """
    if isinstance(exc, LocalSLMUnavailableError):
        return "provider_error"
    if isinstance(exc, LLMInvocationError):
        message = str(exc).lower()
        if "timeout" in message or "timed out" in message:
            return "timeout"
        return "provider_error"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, _VALIDATION_ERRORS):
        return "validation_error"
    return "execution_error"


class LedgerRecorder:
    def __init__(self, store: ExecutionLedgerStore) -> None:
        self._store = store

    @property
    def store(self) -> ExecutionLedgerStore:
        """Read access to the underlying store — for callers (e.g. a
        future dashboard's history endpoint) that need to list/query
        recorded entries, not just write new ones."""
        return self._store

    def record_success(
        self,
        *,
        mode: BenchmarkMode,
        run: RunResult,
        repository_root: Path,
        branch: str | None,
        prompt: str,
        provider: str | None = None,
    ) -> ExecutionLedgerEntry:
        """`prompt` is a fallback only, used when `run.prompt` is empty
        (e.g. a RunResult built before that field existed) — the
        fully-compiled prompt the runner actually sent to the LLM is
        preferred over the caller's raw task text whenever it's
        available, since that's the more accurate record of what was
        actually asked."""
        entry = ExecutionLedgerEntry(
            workspace_id=str(repository_root),
            contract_id=str(run.contract.id) if run.contract is not None else "direct-mode",
            mode=_MODE_TO_LEDGER_MODE[mode],
            model=run.model,
            provider=provider,
            repository_root=str(repository_root),
            branch=branch,
            prompt=run.prompt or prompt,
            selected_files=run.referenced_files,
            selected_symbols=self._selected_symbols(run),
            prompt_tokens=run.token_metrics.input_tokens,
            completion_tokens=run.token_metrics.output_tokens,
            total_tokens=run.token_metrics.total_tokens,
            latency_ms=run.latency_metrics.total_ms,
            # actual_cost_usd (real, post-call, from measured token usage) is used
            # here rather than cost_metrics.estimated_cost_usd (a pre-call guess) —
            # this is a historical record, not a live guardrail, so the more
            # accurate number is the more useful one, despite the field's name
            # (inherited from the Ledger's original spec) saying "estimated."
            estimated_cost_usd=run.cost_metrics.actual_cost_usd,
            artifact_content=run.generated_output,
            execution_status="success",
            files_changed=run.quality_metrics.modified_files,
            lines_changed=run.quality_metrics.lines_changed,
            metadata=self._metadata_for(mode, run),
        )
        self._store.save(entry)
        return entry

    def record_failure(
        self,
        *,
        mode: BenchmarkMode,
        exc: Exception,
        repository_root: Path,
        branch: str | None,
        prompt: str,
        model: str,
        provider: str | None = None,
    ) -> ExecutionLedgerEntry:
        entry = ExecutionLedgerEntry(
            workspace_id=str(repository_root),
            contract_id="failed-run",
            mode=_MODE_TO_LEDGER_MODE[mode],
            model=model,
            provider=provider,
            repository_root=str(repository_root),
            branch=branch,
            prompt=prompt,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=0.0,
            estimated_cost_usd=0.0,
            artifact_content="",
            execution_status=classify_exception(exc),
            metadata={"error": str(exc), "error_type": type(exc).__name__},
        )
        self._store.save(entry)
        return entry

    @staticmethod
    def _selected_symbols(run: RunResult) -> list[str]:
        if run.context_resolution is None:
            return []
        return [s.qualified_name for s in run.context_resolution.entry_points]

    @staticmethod
    def _metadata_for(mode: BenchmarkMode, run: RunResult) -> dict[str, object]:
        metadata: dict[str, object] = {"benchmark_mode": mode.value}
        if run.contract is not None:
            metadata["execution_contract"] = {
                "id": str(run.contract.id),
                "intent": run.contract.intent.intent,
                "success_criteria": run.contract.success_criteria,
            }
        if run.context_package is not None:
            metadata["context_package"] = {
                "id": str(run.context_package.id),
                "budget_used_tokens": run.context_package.budget_used_tokens,
                "prompt_compression_ratio": run.context_package.prompt_compression_ratio,
                "excluded_file_count": run.context_package.excluded_file_count,
            }
        if mode in (BenchmarkMode.ARCF, BenchmarkMode.ARCF_LOCAL):
            # ExecutionLedgerEntry.total_tokens/estimated_cost_usd (below)
            # are drawn from run.token_metrics/run.cost_metrics, which for
            # ArcfRunner cover the final generation call only — SLM-1's
            # intent-extraction call (and SLM-2's, if it ran) is real spend
            # that isn't in either figure. Recorded here, in metadata,
            # rather than folded into total_tokens/estimated_cost_usd
            # directly, so a historical Ledger comparison can show it
            # without silently changing what those two fields have always
            # meant for every entry recorded before this existed.
            metadata["pipeline_overhead_cost_usd"] = run.cost_metrics.pipeline_overhead_cost_usd
            metadata["pipeline_overhead_ms"] = run.latency_metrics.pipeline_overhead_ms
        return metadata
