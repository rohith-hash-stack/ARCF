"""Workspace attach endpoint — Phase 4's contribution to the same
Living Contract lineage Phase 3 established.

No LLM/SLM call happens here (workspace analysis is fully
deterministic), so unlike /execute and /contracts there is no cost
guardrail to check and nothing to spend against ExecutionContext's
budget — only auth and rate limiting apply. That asymmetry is
intentional: cost tracking is opt-in per stage, not a blanket
requirement of using ExecutionContext.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from domain.execution_context import ExecutionContext
from infrastructure.rate_limit import RateLimiter
from interfaces.api.dependencies import (
    get_execution_context,
    get_rate_limiter,
    get_workspace_service,
)
from interfaces.api.schemas import AttachWorkspaceRequest, ContractResponse
from shared.errors import (
    ContractNotFoundError,
    RateLimitExceededError,
    WorkspaceNotAllowedError,
    WorkspacePathError,
)
from workspace.service import WorkspaceContractService

router = APIRouter(prefix="/api/v1", tags=["workspace"])


@router.post("/contracts/{contract_id}/workspace", response_model=ContractResponse)
async def attach_workspace(
    contract_id: UUID,
    payload: AttachWorkspaceRequest,
    context: Annotated[ExecutionContext, Depends(get_execution_context)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    workspace_service: Annotated[WorkspaceContractService, Depends(get_workspace_service)],
) -> ContractResponse:
    try:
        rate_limiter.enforce(context.principal.id)
    except RateLimitExceededError as exc:
        capped_retry_after = min(exc.retry_after_seconds, 3600.0)
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(int(capped_retry_after) + 1)},
        ) from exc

    try:
        living = await workspace_service.attach_workspace(contract_id, payload.workspace_root)
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkspaceNotAllowedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except WorkspacePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ContractResponse(
        request_id=str(context.request_id),
        trace_id=context.trace_id or "",
        remaining_budget_usd=context.budget.remaining_usd,
        contract_id=str(living.contract_id),
        version=living.version,
        status=living.status,
        needs_clarification=living.contract.intent.needs_clarification,
        clarifying_questions=living.contract.intent.clarifications,
        contract=living.contract,
    )
