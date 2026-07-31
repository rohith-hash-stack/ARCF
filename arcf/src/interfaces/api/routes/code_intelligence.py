"""Code Intelligence trigger endpoint.

No LLM call happens here (Phase 5 is fully deterministic), so — like
the workspace-attach endpoint — only auth and rate limiting apply, no
cost guardrail. This is what produces the ContextResolutionResult that
/context-package (Phase 6) later consumes.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from code_intelligence.service import CodeIntelligenceContractService
from domain.execution_context import ExecutionContext
from infrastructure.rate_limit import RateLimiter
from interfaces.api.dependencies import (
    get_code_intelligence_service,
    get_execution_context,
    get_rate_limiter,
)
from interfaces.api.schemas import CodeIntelligenceResponse, CreateCodeIntelligenceRequest
from shared.errors import (
    ContractNotFoundError,
    NoWorkspaceAttachedError,
    RateLimitExceededError,
    WorkspacePathError,
)

router = APIRouter(prefix="/api/v1", tags=["code-intelligence"])


def _enforce_rate_limit(rate_limiter: RateLimiter, context: ExecutionContext) -> None:
    try:
        rate_limiter.enforce(context.principal.id)
    except RateLimitExceededError as exc:
        capped_retry_after = min(exc.retry_after_seconds, 3600.0)
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(int(capped_retry_after) + 1)},
        ) from exc


@router.post(
    "/contracts/{contract_id}/code-intelligence", response_model=CodeIntelligenceResponse
)
async def build_code_intelligence(
    contract_id: UUID,
    payload: CreateCodeIntelligenceRequest,
    context: Annotated[ExecutionContext, Depends(get_execution_context)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    service: Annotated[CodeIntelligenceContractService, Depends(get_code_intelligence_service)],
) -> CodeIntelligenceResponse:
    _enforce_rate_limit(rate_limiter, context)

    try:
        living, result = await service.attach_code_intelligence(
            contract_id, payload.target_names, payload.workspace_root
        )
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoWorkspaceAttachedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkspacePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CodeIntelligenceResponse(
        request_id=str(context.request_id),
        trace_id=context.trace_id or "",
        remaining_budget_usd=context.budget.remaining_usd,
        contract_id=str(living.contract_id),
        contract_version=living.version,
        resolution=result,
    )
