"""BenchmarkController tests, focused on Action 2 of the ARCF v2.3
Execution Directive: every mode's run must be recorded to the
Execution Ledger, success or failure, and a single mode's failure
must not lose data from a mode that already succeeded.

Real DirectLLMRunner/ArcfRunner instances are constructed (with
placeholder constructor dependencies, since those aren't exercised —
only `.run` is monkeypatched) so `_execute_mode`'s `isinstance` dispatch
routes correctly, matching production code exactly rather than a fake
duck-typed stand-in.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from domain.workspace import ProjectStructure, RepositoryMetadata, WorkspaceMetadata
from infrastructure.cost import CostEstimator
from infrastructure.execution_ledger_db import InMemoryExecutionLedgerStore
from infrastructure.llm_client import LiteLLMClient
from shared.errors import LLMInvocationError
from workspace.scanner import ScanResult

from benchmark.analyzer import BenchmarkAnalyzer
from benchmark.controller import BenchmarkController
from benchmark.domain.models import (
    BenchmarkMode,
    ContextMetrics,
    CostMetrics,
    LatencyMetrics,
    QualityMetrics,
    RunResult,
    TokenMetrics,
)
from benchmark.ledger import LedgerRecorder
from benchmark.repository import LoadedRepository
from benchmark.runners.arcf_runner import ArcfRunner
from benchmark.runners.direct_llm_runner import DirectLLMRunner


def _run_result(mode: BenchmarkMode) -> RunResult:
    return RunResult(
        mode=mode,
        model="gpt-4o-mini",
        generated_output="ok",
        token_metrics=TokenMetrics(input_tokens=10, output_tokens=5, total_tokens=15),
        latency_metrics=LatencyMetrics(
            total_ms=100.0, llm_ms=80.0, deterministic_ms=10.0, pipeline_overhead_ms=10.0
        ),
        cost_metrics=CostMetrics(
            estimated_cost_usd=0.01, actual_cost_usd=0.009, pipeline_overhead_cost_usd=0.0
        ),
        context_metrics=ContextMetrics(repository_files=5, candidate_files=2, files_sent_to_llm=1),
        quality_metrics=QualityMetrics(answer_length=2, modified_files=[]),
    )


def _direct_runner() -> DirectLLMRunner:
    return DirectLLMRunner(llm_client=MagicMock(spec=LiteLLMClient), cost_estimator=CostEstimator())


def _arcf_runner() -> ArcfRunner:
    return ArcfRunner(
        contract_manager=MagicMock(),
        workspace_service=MagicMock(),
        code_intelligence_service=MagicMock(),
        context_packager=MagicMock(),
        llm_client=MagicMock(spec=LiteLLMClient),
        cost_estimator=CostEstimator(),
        slm_model="gpt-4o-mini",
        mode=BenchmarkMode.ARCF,
    )


def _repo(tmp_path: Path, branch: str | None = "main") -> LoadedRepository:
    return LoadedRepository(
        root=tmp_path,
        metadata=WorkspaceMetadata(
            workspace_root=str(tmp_path),
            repository=RepositoryMetadata(is_git_repo=True, current_branch=branch),
            structure=ProjectStructure(layout="flat-layout"),
            file_count=0,
        ),
        scan=ScanResult(files=[], truncated=False),
    )


_ControllerFixture = tuple[
    BenchmarkController, DirectLLMRunner, ArcfRunner, InMemoryExecutionLedgerStore
]


def _controller() -> _ControllerFixture:
    direct_runner = _direct_runner()
    arcf_runner = _arcf_runner()
    store = InMemoryExecutionLedgerStore()

    controller = BenchmarkController(
        direct_runner=direct_runner,
        arcf_runner=arcf_runner,
        analyzer=BenchmarkAnalyzer(),
        ledger_recorder=LedgerRecorder(store),
    )
    return controller, direct_runner, arcf_runner, store


async def test_successful_both_modes_records_two_ledger_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, direct_runner, arcf_runner, store = _controller()

    async def fake_direct_run(*args: object, **kwargs: object) -> RunResult:
        return _run_result(BenchmarkMode.DIRECT)

    async def fake_arcf_run(*args: object, **kwargs: object) -> RunResult:
        return _run_result(BenchmarkMode.ARCF)

    monkeypatch.setattr(direct_runner, "run", fake_direct_run)
    monkeypatch.setattr(arcf_runner, "run", fake_arcf_run)

    result = await controller.run(
        repo=_repo(tmp_path),
        task="fix the bug",
        model="gpt-4o-mini",
        modes=[BenchmarkMode.DIRECT, BenchmarkMode.ARCF],
        max_context_tokens=1000,
        max_output_tokens=512,
    )

    assert result.direct is not None
    assert result.arcf is not None
    entries = store.list_recent(limit=10)
    assert len(entries) == 2
    assert {e.mode for e in entries} == {"direct", "arcf"}
    assert all(e.execution_status == "success" for e in entries)
    assert all(e.branch == "main" for e in entries)


async def test_one_mode_failing_does_not_lose_the_other_modes_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, direct_runner, arcf_runner, store = _controller()

    async def fake_direct_run(*args: object, **kwargs: object) -> RunResult:
        return _run_result(BenchmarkMode.DIRECT)

    async def failing_arcf_run(*args: object, **kwargs: object) -> RunResult:
        raise LLMInvocationError("provider is down")

    monkeypatch.setattr(direct_runner, "run", fake_direct_run)
    monkeypatch.setattr(arcf_runner, "run", failing_arcf_run)

    result = await controller.run(
        repo=_repo(tmp_path),
        task="fix the bug",
        model="gpt-4o-mini",
        modes=[BenchmarkMode.DIRECT, BenchmarkMode.ARCF],
        max_context_tokens=1000,
        max_output_tokens=512,
    )

    # Direct's result is NOT lost even though ARCF failed.
    assert result.direct is not None
    assert result.arcf is None

    entries = store.list_recent(limit=10)
    assert len(entries) == 2
    direct_entry = next(e for e in entries if e.mode == "direct")
    arcf_entry = next(e for e in entries if e.mode == "arcf")
    assert direct_entry.execution_status == "success"
    assert arcf_entry.execution_status == "provider_error"
    assert "provider is down" in arcf_entry.metadata["error"]


async def test_all_modes_failing_raises_and_still_records_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, direct_runner, arcf_runner, store = _controller()

    async def failing_run(*args: object, **kwargs: object) -> RunResult:
        raise LLMInvocationError("down")

    monkeypatch.setattr(direct_runner, "run", failing_run)
    monkeypatch.setattr(arcf_runner, "run", failing_run)

    with pytest.raises(LLMInvocationError):
        await controller.run(
            repo=_repo(tmp_path),
            task="fix the bug",
            model="gpt-4o-mini",
            modes=[BenchmarkMode.DIRECT, BenchmarkMode.ARCF],
            max_context_tokens=1000,
            max_output_tokens=512,
        )

    entries = store.list_recent(limit=10)
    assert len(entries) == 2
    assert all(e.execution_status == "provider_error" for e in entries)


async def test_provider_is_threaded_into_ledger_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, direct_runner, _arcf_runner, store = _controller()

    async def fake_direct_run(*args: object, **kwargs: object) -> RunResult:
        return _run_result(BenchmarkMode.DIRECT)

    monkeypatch.setattr(direct_runner, "run", fake_direct_run)

    await controller.run(
        repo=_repo(tmp_path),
        task="task",
        model="gpt-4o-mini",
        modes=[BenchmarkMode.DIRECT],
        max_context_tokens=1000,
        max_output_tokens=512,
        provider="openai",
    )

    entry = store.list_recent(limit=1)[0]
    assert entry.provider == "openai"


async def test_branch_is_recorded_from_repo_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, direct_runner, _arcf_runner, store = _controller()

    async def fake_direct_run(*args: object, **kwargs: object) -> RunResult:
        return _run_result(BenchmarkMode.DIRECT)

    monkeypatch.setattr(direct_runner, "run", fake_direct_run)

    await controller.run(
        repo=_repo(tmp_path, branch="feature/foo"),
        task="task",
        model="gpt-4o-mini",
        modes=[BenchmarkMode.DIRECT],
        max_context_tokens=1000,
        max_output_tokens=512,
    )

    entry = store.list_recent(limit=1)[0]
    assert entry.branch == "feature/foo"
