"""Execution Ledger endpoints (Phase 9). Stage 4 of the v2.3 migration
plan (see arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md Sec. 2.6/5.2/7).

Read/manage only — there is no POST here. Entries are written by
whatever runs the Context + Goal Composer / FinalGenerationRunner
(Phase 8) and calls ExecutionLedgerStore.save() directly; wiring that
end-to-end orchestration is application/execute_use_case.py's job
(Sec. 6), not yet built. That keeps this router's scope to exactly what
Stage 4 asks for: persistence + the read/delete/rate surface over it.

No LLM/SLM call happens on any route here (mirrors workspace.py's
attach_workspace reasoning) — only auth applies, no cost guardrail, no
ExecutionContext budget to spend against. Response shapes are the raw
domain/schema shapes from Sec. 5.2's API sketch, not wrapped in a
request_id/trace_id/budget envelope like the LLM-calling routes,
because there is no per-call spend here to report.
"""

import difflib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from domain.execution_ledger import ExecutionLedgerEntry
from domain.principal import Principal
from infrastructure.execution_ledger_db import ExecutionLedgerStore
from interfaces.api.dependencies import get_current_principal, get_execution_ledger_store
from interfaces.api.schemas import ExecutionComparisonResult, PatchExecutionLedgerRequest

router = APIRouter(prefix="/api/v1", tags=["execution-ledger"])


def _get_or_404(store: ExecutionLedgerStore, request_id: UUID) -> ExecutionLedgerEntry:
    entry = store.get(request_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No execution found with id {request_id}")
    return entry


@router.get("/executions", response_model=list[ExecutionLedgerEntry])
async def list_executions(
    _principal: Annotated[Principal, Depends(get_current_principal)],
    store: Annotated[ExecutionLedgerStore, Depends(get_execution_ledger_store)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ExecutionLedgerEntry]:
    return store.list_recent(limit)


@router.get("/executions/compare", response_model=ExecutionComparisonResult)
async def compare_executions(
    _principal: Annotated[Principal, Depends(get_current_principal)],
    store: Annotated[ExecutionLedgerStore, Depends(get_execution_ledger_store)],
    a: UUID,
    b: UUID,
) -> ExecutionComparisonResult:
    entry_a = _get_or_404(store, a)
    entry_b = _get_or_404(store, b)
    return ExecutionComparisonResult(
        entry_a=entry_a,
        entry_b=entry_b,
        total_tokens_delta=entry_b.total_tokens - entry_a.total_tokens,
        estimated_cost_delta_usd=entry_b.estimated_cost_usd - entry_a.estimated_cost_usd,
        latency_delta_ms=entry_b.latency_ms - entry_a.latency_ms,
        artifact_diff=_unified_diff(entry_a, entry_b),
    )


@router.get("/executions/{request_id}", response_model=ExecutionLedgerEntry)
async def get_execution(
    request_id: UUID,
    _principal: Annotated[Principal, Depends(get_current_principal)],
    store: Annotated[ExecutionLedgerStore, Depends(get_execution_ledger_store)],
) -> ExecutionLedgerEntry:
    return _get_or_404(store, request_id)


@router.patch("/executions/{request_id}", response_model=ExecutionLedgerEntry)
async def patch_execution(
    request_id: UUID,
    payload: PatchExecutionLedgerRequest,
    _principal: Annotated[Principal, Depends(get_current_principal)],
    store: Annotated[ExecutionLedgerStore, Depends(get_execution_ledger_store)],
) -> ExecutionLedgerEntry:
    no_fields_provided = (
        payload.manual_rating is None
        and payload.build_result is None
        and payload.test_result is None
    )
    if no_fields_provided:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of manual_rating, build_result, test_result",
        )

    entry = _get_or_404(store, request_id)
    if payload.manual_rating is not None:
        entry = entry.with_manual_rating(payload.manual_rating)
    if payload.build_result is not None:
        entry = entry.with_build_result(payload.build_result)
    if payload.test_result is not None:
        entry = entry.with_test_result(payload.test_result)

    store.save(entry)
    return entry


@router.delete("/executions/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_execution(
    request_id: UUID,
    _principal: Annotated[Principal, Depends(get_current_principal)],
    store: Annotated[ExecutionLedgerStore, Depends(get_execution_ledger_store)],
) -> None:
    if not store.delete(request_id):
        raise HTTPException(status_code=404, detail=f"No execution found with id {request_id}")


def _unified_diff(entry_a: ExecutionLedgerEntry, entry_b: ExecutionLedgerEntry) -> str:
    diff = difflib.unified_diff(
        entry_a.artifact_content.splitlines(keepends=True),
        entry_b.artifact_content.splitlines(keepends=True),
        fromfile=str(entry_a.request_id),
        tofile=str(entry_b.request_id),
    )
    return "".join(diff)
