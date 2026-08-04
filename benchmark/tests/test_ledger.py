from pathlib import Path
from uuid import uuid4

import pytest
from domain.execution_ledger import ExecutionLedgerEntry
from infrastructure.execution_ledger_db import InMemoryExecutionLedgerStore
from shared.errors import LLMInvocationError, WorkspacePathError

from benchmark.domain.models import (
    BenchmarkMode,
    ContextMetrics,
    CostMetrics,
    LatencyMetrics,
    QualityMetrics,
    RunResult,
    TokenMetrics,
)
from benchmark.ledger import LedgerRecorder, classify_exception
from benchmark.local_slm.errors import LocalSLMUnavailableError


def _run_result(**overrides: object) -> RunResult:
    defaults: dict[str, object] = {
        "mode": BenchmarkMode.ARCF,
        "model": "gpt-4o-mini",
        "generated_output": "### auth.py\n```\nfixed\n```",
        "token_metrics": TokenMetrics(input_tokens=100, output_tokens=50, total_tokens=150),
        "latency_metrics": LatencyMetrics(
            total_ms=500.0, llm_ms=400.0, deterministic_ms=50.0, pipeline_overhead_ms=50.0
        ),
        "cost_metrics": CostMetrics(
            estimated_cost_usd=0.02, actual_cost_usd=0.018, pipeline_overhead_cost_usd=0.001
        ),
        "context_metrics": ContextMetrics(
            repository_files=10, candidate_files=3, files_sent_to_llm=2
        ),
        "quality_metrics": QualityMetrics(
            answer_length=30, modified_files=["auth.py"], lines_changed=4
        ),
        "referenced_files": ["auth.py", "login.py"],
    }
    defaults.update(overrides)
    return RunResult(**defaults)  # type: ignore[arg-type]


def _recorder() -> tuple[LedgerRecorder, InMemoryExecutionLedgerStore]:
    store = InMemoryExecutionLedgerStore()
    return LedgerRecorder(store), store


def test_record_success_persists_a_ledger_entry(tmp_path: Path) -> None:
    recorder, store = _recorder()
    run = _run_result()

    entry = recorder.record_success(
        mode=BenchmarkMode.ARCF,
        run=run,
        repository_root=tmp_path,
        branch="main",
        prompt="fix the bug",
        provider="openai",
    )

    fetched = store.get(entry.request_id)
    assert fetched is not None
    assert fetched.mode == "arcf"
    assert fetched.model == "gpt-4o-mini"
    assert fetched.provider == "openai"
    assert fetched.branch == "main"
    assert fetched.execution_status == "success"
    assert fetched.prompt_tokens == 100
    assert fetched.total_tokens == 150
    assert fetched.latency_ms == 500.0
    assert fetched.estimated_cost_usd == 0.018  # actual, not the pre-call estimate
    assert fetched.selected_files == ["auth.py", "login.py"]
    assert fetched.files_changed == ["auth.py"]
    assert fetched.lines_changed == 4
    assert fetched.artifact_content == run.generated_output


def test_record_success_prefers_run_prompt_over_caller_prompt(tmp_path: Path) -> None:
    recorder, store = _recorder()
    run = _run_result(prompt="the fully compiled prompt sent to the LLM")

    entry = recorder.record_success(
        mode=BenchmarkMode.ARCF, run=run, repository_root=tmp_path,
        branch=None, prompt="raw task text",
    )

    fetched = store.get(entry.request_id)
    assert fetched is not None
    assert fetched.prompt == "the fully compiled prompt sent to the LLM"


def test_record_success_falls_back_to_caller_prompt_when_run_prompt_empty(
    tmp_path: Path,
) -> None:
    recorder, store = _recorder()
    run = _run_result(prompt="")

    entry = recorder.record_success(
        mode=BenchmarkMode.ARCF, run=run, repository_root=tmp_path,
        branch=None, prompt="raw task text",
    )

    fetched = store.get(entry.request_id)
    assert fetched is not None
    assert fetched.prompt == "raw task text"


def test_record_success_maps_arcf_local_to_arcf_mode(tmp_path: Path) -> None:
    recorder, store = _recorder()
    run = _run_result(mode=BenchmarkMode.ARCF_LOCAL)

    entry = recorder.record_success(
        mode=BenchmarkMode.ARCF_LOCAL,
        run=run,
        repository_root=tmp_path,
        branch=None,
        prompt="task",
    )

    fetched = store.get(entry.request_id)
    assert fetched is not None
    assert fetched.mode == "arcf"
    assert fetched.metadata["benchmark_mode"] == "arcf_local"


def test_record_success_direct_mode_has_no_contract_but_still_persists(tmp_path: Path) -> None:
    recorder, store = _recorder()
    run = _run_result(mode=BenchmarkMode.DIRECT, contract=None, context_resolution=None)

    entry = recorder.record_success(
        mode=BenchmarkMode.DIRECT,
        run=run,
        repository_root=tmp_path,
        branch="main",
        prompt="task",
    )

    fetched = store.get(entry.request_id)
    assert fetched is not None
    assert fetched.mode == "direct"
    assert fetched.selected_symbols == []


def test_record_success_arcf_metadata_carries_pipeline_overhead(tmp_path: Path) -> None:
    """total_tokens/estimated_cost_usd cover the final generation call
    only (see ledger.py's own docstring) — SLM-1's real cost/latency
    must still be recoverable from metadata, or a historical comparison
    of two Ledger entries silently understates ARCF's true spend."""
    recorder, store = _recorder()
    run = _run_result()

    entry = recorder.record_success(
        mode=BenchmarkMode.ARCF, run=run, repository_root=tmp_path, branch=None, prompt="task"
    )

    fetched = store.get(entry.request_id)
    assert fetched is not None
    assert fetched.metadata["pipeline_overhead_cost_usd"] == 0.001
    assert fetched.metadata["pipeline_overhead_ms"] == 50.0


def test_record_success_direct_mode_metadata_has_no_pipeline_overhead(tmp_path: Path) -> None:
    recorder, store = _recorder()
    run = _run_result(mode=BenchmarkMode.DIRECT, contract=None, context_resolution=None)

    entry = recorder.record_success(
        mode=BenchmarkMode.DIRECT, run=run, repository_root=tmp_path, branch=None, prompt="task"
    )

    fetched = store.get(entry.request_id)
    assert fetched is not None
    assert "pipeline_overhead_cost_usd" not in fetched.metadata
    assert "pipeline_overhead_ms" not in fetched.metadata


def test_record_failure_persists_zeroed_entry_with_error_metadata(tmp_path: Path) -> None:
    recorder, store = _recorder()

    entry = recorder.record_failure(
        mode=BenchmarkMode.DIRECT,
        exc=ValueError("something broke"),
        repository_root=tmp_path,
        branch="main",
        prompt="task",
        model="gpt-4o-mini",
    )

    fetched = store.get(entry.request_id)
    assert fetched is not None
    assert fetched.execution_status == "execution_error"
    assert fetched.total_tokens == 0
    assert fetched.latency_ms == 0.0
    assert fetched.artifact_content == ""
    assert fetched.metadata["error"] == "something broke"
    assert fetched.metadata["error_type"] == "ValueError"


def test_no_result_is_ever_lost_success_and_failure_both_land_in_ledger(tmp_path: Path) -> None:
    recorder, store = _recorder()
    recorder.record_success(
        mode=BenchmarkMode.ARCF, run=_run_result(), repository_root=tmp_path,
        branch=None, prompt="a",
    )
    recorder.record_failure(
        mode=BenchmarkMode.DIRECT, exc=RuntimeError("x"), repository_root=tmp_path,
        branch=None, prompt="b", model="gpt-4o-mini",
    )

    assert len(store.list_recent(limit=10)) == 2


class TestClassifyException:
    def test_llm_invocation_error_with_timeout_wording_is_timeout(self) -> None:
        assert classify_exception(LLMInvocationError("request timed out")) == "timeout"

    def test_llm_invocation_error_without_timeout_wording_is_provider_error(self) -> None:
        assert classify_exception(LLMInvocationError("rate limited")) == "provider_error"

    def test_python_timeout_error_is_timeout(self) -> None:
        assert classify_exception(TimeoutError("deadline exceeded")) == "timeout"

    def test_local_slm_unavailable_is_provider_error(self) -> None:
        assert classify_exception(LocalSLMUnavailableError("no ollama model")) == "provider_error"

    def test_workspace_path_error_is_validation_error(self) -> None:
        assert classify_exception(WorkspacePathError("escapes workspace")) == "validation_error"

    def test_unrecognized_exception_is_execution_error(self) -> None:
        assert classify_exception(KeyError("boom")) == "execution_error"


def test_record_success_returns_an_execution_ledger_entry_instance(tmp_path: Path) -> None:
    recorder, _store = _recorder()
    entry = recorder.record_success(
        mode=BenchmarkMode.ARCF, run=_run_result(), repository_root=tmp_path,
        branch=None, prompt="task",
    )
    assert isinstance(entry, ExecutionLedgerEntry)
    assert entry.request_id != uuid4()  # sanity: a real, non-placeholder id was assigned


@pytest.mark.parametrize(
    "mode",
    [BenchmarkMode.DIRECT, BenchmarkMode.ARCF, BenchmarkMode.ARCF_LOCAL],
)
def test_record_failure_works_for_every_mode(tmp_path: Path, mode: BenchmarkMode) -> None:
    recorder, store = _recorder()
    entry = recorder.record_failure(
        mode=mode, exc=RuntimeError("x"), repository_root=tmp_path,
        branch=None, prompt="task", model="gpt-4o-mini",
    )
    assert store.get(entry.request_id) is not None
