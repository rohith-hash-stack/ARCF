"""Benchmark JSON API — repository loading, running a benchmark, and
report retrieval. No auth/rate-limiting layer: see config.py's
docstring for why (a local tool, not a multi-tenant service).
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from shared.errors import (
    ContractNotFoundError,
    IntentExtractionError,
    LLMInvocationError,
    NoWorkspaceAttachedError,
    WorkspacePathError,
)

from benchmark.api.dependencies import (
    get_controller,
    get_local_slm_unavailable_reason,
    get_repository_loader,
    get_settings,
    get_store,
)
from benchmark.api.schemas import (
    LanguageStatResponse,
    LoadRepositoryRequest,
    LocalSlmStatusResponse,
    RepositoryInfoResponse,
    RunBenchmarkRequest,
)
from benchmark.config import BenchmarkSettings
from benchmark.controller import BenchmarkController
from benchmark.domain.models import BenchmarkMode, ComparisonResult
from benchmark.local_slm.errors import LocalSLMUnavailableError
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
        result = await controller.run(
            repo=repo,
            task=payload.task,
            model=payload.model or settings.default_model,
            modes=modes,
            max_context_tokens=payload.max_context_tokens or settings.max_context_tokens,
            max_output_tokens=payload.max_output_tokens or settings.max_output_tokens,
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
