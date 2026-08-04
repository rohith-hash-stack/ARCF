"""Benchmark JSON API — repository loading, running a benchmark, and
report retrieval. No auth/rate-limiting layer: see config.py's
docstring for why (a local tool, not a multi-tenant service).
"""

from typing import Annotated
from uuid import UUID

from domain.execution_ledger import ExecutionLedgerEntry
from fastapi import APIRouter, Depends, HTTPException, Query
from infrastructure.execution_ledger_db import ExecutionLedgerStore
from shared.errors import (
    ContractNotFoundError,
    IntentExtractionError,
    LLMInvocationError,
    NoWorkspaceAttachedError,
    WorkspacePathError,
)

from benchmark.api.dependencies import (
    get_controller,
    get_execution_ledger_store,
    get_local_slm_unavailable_reason,
    get_repository_loader,
    get_settings,
    get_store,
)
from benchmark.api.schemas import (
    LanguageStatResponse,
    LoadRepositoryRequest,
    LocalSlmStatusResponse,
    ProviderInfoResponse,
    RepositoryInfoResponse,
    RunBenchmarkRequest,
)
from benchmark.config import BenchmarkSettings
from benchmark.controller import BenchmarkController
from benchmark.domain.models import BenchmarkMode, ComparisonResult
from benchmark.local_slm.errors import LocalSLMUnavailableError
from benchmark.model_resolution import resolve_model
from benchmark.providers.errors import UnknownProviderError
from benchmark.providers.registry import default_provider_registry
from benchmark.repository import RepositoryLoader
from benchmark.storage import BenchmarkStore

router = APIRouter(prefix="/api")

_ARCF_PIPELINE_ERRORS: tuple[type[Exception], ...] = (
    ContractNotFoundError,
    NoWorkspaceAttachedError,
    WorkspacePathError,
    IntentExtractionError,
    LLMInvocationError,
    LocalSLMUnavailableError,
)


@router.get("/local-slm/status", response_model=LocalSlmStatusResponse)
async def local_slm_status(
    reason: Annotated[str | None, Depends(get_local_slm_unavailable_reason)],
) -> LocalSlmStatusResponse:
    return LocalSlmStatusResponse(available=reason is None, reason=reason)


@router.post("/repository/load", response_model=RepositoryInfoResponse)
async def load_repository(
    payload: LoadRepositoryRequest,
    loader: Annotated[RepositoryLoader, Depends(get_repository_loader)],
) -> RepositoryInfoResponse:
    try:
        if payload.source == "local":
            if not payload.path:
                raise HTTPException(status_code=400, detail="path is required for source=local")
            repo = loader.open_local(payload.path)
        else:
            if not payload.url:
                raise HTTPException(status_code=400, detail="url is required for source=clone")
            repo = loader.clone(payload.url, payload.ref)
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to load repository: {exc}") from exc

    return RepositoryInfoResponse(
        root=str(repo.root),
        is_git_repo=repo.metadata.repository.is_git_repo,
        current_branch=repo.metadata.repository.current_branch,
        file_count=repo.metadata.file_count,
        languages=[
            LanguageStatResponse(
                language=lang.language, file_count=lang.file_count, percentage=lang.percentage
            )
            for lang in repo.metadata.languages
        ],
        frameworks=[fw.name for fw in repo.metadata.frameworks],
    )


@router.post("/benchmark/run", response_model=ComparisonResult)
async def run_benchmark(
    payload: RunBenchmarkRequest,
    loader: Annotated[RepositoryLoader, Depends(get_repository_loader)],
    controller: Annotated[BenchmarkController, Depends(get_controller)],
    settings: Annotated[BenchmarkSettings, Depends(get_settings)],
    store: Annotated[BenchmarkStore, Depends(get_store)],
) -> ComparisonResult:
    try:
        repo = loader.open_local(payload.repository_root)
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    modes = [BenchmarkMode(mode) for mode in payload.modes] or [
        BenchmarkMode.DIRECT,
        BenchmarkMode.ARCF,
    ]

    try:
        model = resolve_model(
            payload.provider, payload.model, settings.default_model, settings.local_slm_base_url
        )
    except UnknownProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = await controller.run(
            repo=repo,
            task=payload.task,
            model=model,
            modes=modes,
            max_context_tokens=payload.max_context_tokens or settings.max_context_tokens,
            max_output_tokens=payload.max_output_tokens or settings.max_output_tokens,
            provider=payload.provider,
        )
    except _ARCF_PIPELINE_ERRORS as exc:
        raise HTTPException(status_code=502, detail=f"Benchmark run failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Unexpected error during benchmark run: {exc}"
        ) from exc

    store.save(result)
    return result


@router.get("/benchmark/reports", response_model=list[ComparisonResult])
async def list_reports(
    store: Annotated[BenchmarkStore, Depends(get_store)],
) -> list[ComparisonResult]:
    return store.list_all()


@router.get("/benchmark/reports/{report_id}", response_model=ComparisonResult)
async def get_report(
    report_id: UUID, store: Annotated[BenchmarkStore, Depends(get_store)]
) -> ComparisonResult:
    result = store.get(report_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No report found with id {report_id}")
    return result


@router.get("/providers", response_model=list[ProviderInfoResponse])
async def list_providers(
    settings: Annotated[BenchmarkSettings, Depends(get_settings)],
) -> list[ProviderInfoResponse]:
    registry = default_provider_registry(settings.local_slm_base_url)
    return [
        ProviderInfoResponse(name=name, available=registry.get(name).is_available())
        for name in registry.names()
    ]


@router.get("/executions", response_model=list[ExecutionLedgerEntry])
async def list_executions(
    store: Annotated[ExecutionLedgerStore, Depends(get_execution_ledger_store)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    mode: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
) -> list[ExecutionLedgerEntry]:
    """Execution History (Action 1 of the ARCF v2.3 Execution Directive):
    the dashboard's own read surface over the same Execution Ledger
    Action 2 now writes to automatically. `mode`/`search` are applied
    in-process, not pushed into SQL — this is a local tool's ledger
    (last 50 entries per workspace, per infrastructure/
    execution_ledger_db.py's retention), not a scale that needs a real
    query engine.
    """
    entries = store.list_recent(limit=200)
    if mode is not None:
        entries = [e for e in entries if e.mode == mode]
    if search:
        needle = search.lower()
        entries = [
            e
            for e in entries
            if needle in e.prompt.lower() or needle in (e.repository_root or "").lower()
        ]
    return entries[:limit]


@router.get("/executions/{request_id}", response_model=ExecutionLedgerEntry)
async def get_execution(
    request_id: UUID,
    store: Annotated[ExecutionLedgerStore, Depends(get_execution_ledger_store)],
) -> ExecutionLedgerEntry:
    entry = store.get(request_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No execution found with id {request_id}")
    return entry
