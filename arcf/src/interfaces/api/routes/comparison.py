"""Comparison endpoints (Phase 11 surface). Stage 5 of the v2.3
migration plan (see arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md
Sec. 2.4/5.1/7).

POST /api/v1/compare references two already-persisted Execution Ledger
entries (one "direct", one "arcf") rather than driving a Direct/ARCF
run itself. Actually running that comparison — invoking a direct LLM
call and the full ARCF pipeline for the same task — is what benchmark/'s
ArcfRunner/DirectLLMRunner already do well; duplicating that here would
be exactly the "Comparison UI scope balloons" risk the review doc's
Sec. 8 risk table calls out, whose stated mitigation is "extend it,
don't replace it." This route's job is making the RESULT a first-class,
persisted ARCF capability (readable via GET /api/v1/compare/{id}) once
whatever ran the comparison has already logged both runs to the
Execution Ledger — not becoming a second place that drives LLM calls.

No LLM/SLM call happens on these routes themselves (mirrors
execution_ledger.py's routes) — only auth applies.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from domain.comparison_result import ComparisonResult
from domain.execution_ledger import ExecutionLedgerEntry
from domain.principal import Principal
from infrastructure.comparison_store import ComparisonStore
from infrastructure.execution_ledger_db import ExecutionLedgerStore
from interfaces.api.dependencies import (
    get_comparison_aggregator,
    get_comparison_store,
    get_current_principal,
    get_execution_ledger_store,
)
from interfaces.api.schemas import CreateComparisonRequest
from telemetry.comparison_aggregator import ComparisonAggregator

router = APIRouter(prefix="/api/v1", tags=["comparison"])


def _get_entry_or_404(store: ExecutionLedgerStore, request_id: UUID) -> ExecutionLedgerEntry:
    entry = store.get(request_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No execution found with id {request_id}")
    return entry


@router.post("/compare", response_model=ComparisonResult)
async def create_comparison(
    payload: CreateComparisonRequest,
    _principal: Annotated[Principal, Depends(get_current_principal)],
    ledger_store: Annotated[ExecutionLedgerStore, Depends(get_execution_ledger_store)],
    comparison_store: Annotated[ComparisonStore, Depends(get_comparison_store)],
    aggregator: Annotated[ComparisonAggregator, Depends(get_comparison_aggregator)],
) -> ComparisonResult:
    direct_entry = _get_entry_or_404(ledger_store, payload.direct_request_id)
    arcf_entry = _get_entry_or_404(ledger_store, payload.arcf_request_id)

    if direct_entry.mode != "direct":
        raise HTTPException(
            status_code=400,
            detail=f"Execution {direct_entry.request_id} has mode '{direct_entry.mode}', "
            "expected 'direct'",
        )
    if arcf_entry.mode != "arcf":
        raise HTTPException(
            status_code=400,
            detail=f"Execution {arcf_entry.request_id} has mode '{arcf_entry.mode}', "
            "expected 'arcf'",
        )

    result = aggregator.compare(payload.task, payload.repository, direct_entry, arcf_entry)
    comparison_store.save(result)
    return result


@router.get("/compare/{comparison_id}", response_model=ComparisonResult)
async def get_comparison(
    comparison_id: UUID,
    _principal: Annotated[Principal, Depends(get_current_principal)],
    comparison_store: Annotated[ComparisonStore, Depends(get_comparison_store)],
) -> ComparisonResult:
    result = comparison_store.get(comparison_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"No comparison found with id {comparison_id}"
        )
    return result
