"""Context Package endpoint — Phase 6's deliverable over HTTP.

Requires /code-intelligence to have run first (Contract.context_resolution_id
must be set). Unlike that endpoint, this one does call an SLM (SLM-2,
supplementary only) so the same cost-guardrail treatment /execute and
/contracts use applies here too.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from context.packager import ContextPackager
from contracts.manager import ExecutionContractManager
from domain.execution_context import ExecutionContext
from infrastructure.context_resolution_store import ContextResolutionStore
from infrastructure.cost import CostGuardrail
from infrastructure.rate_limit import RateLimiter
from interfaces.api.dependencies import (
    get_app_settings,
    get_context_packager,
    get_context_resolution_store,
    get_contract_manager,
    get_cost_guardrail,
    get_execution_context,
    get_rate_limiter,
)
from interfaces.api.schemas import ContextPackageResponse, CreateContextPackageRequest
from shared.config import Settings
from shared.errors import CostGuardrailExceededError, RateLimitExceededError

router = APIRouter(prefix="/api/v1", tags=["context-package"])


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


def _check_budget(
    cost_guardrail: CostGuardrail, context: ExecutionContext, prompt: str, model: str
) -> None:
    try:
        estimate = cost_guardrail.check(prompt, model, assumed_completion_tokens=300)
    except CostGuardrailExceededError as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc

    if not context.budget.has_remaining(estimate.estimated_cost_usd):
        raise HTTPException(
            status_code=402,
            detail=(
                f"Estimated cost ${estimate.estimated_cost_usd:.4f} would exceed remaining "
                f"request budget ${context.budget.remaining_usd:.4f}"
            ),
        )


@router.post("/contracts/{contract_id}/context-package", response_model=ContextPackageResponse)
async def create_context_package(
    contract_id: UUID,
    payload: CreateContextPackageRequest,
    context: Annotated[ExecutionContext, Depends(get_execution_context)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    cost_guardrail: Annotated[CostGuardrail, Depends(get_cost_guardrail)],
    contract_manager: Annotated[ExecutionContractManager, Depends(get_contract_manager)],
    resolution_store: Annotated[ContextResolutionStore, Depends(get_context_resolution_store)],
    packager: Annotated[ContextPackager, Depends(get_context_packager)],
) -> ContextPackageResponse:
    _enforce_rate_limit(rate_limiter, context)

    living = await contract_manager.get_contract(contract_id)
    if living is None:
        raise HTTPException(status_code=404, detail=f"No contract found with id {contract_id}")

    resolution_id = living.contract.context_resolution_id
    if resolution_id is None:
        raise HTTPException(
            status_code=400,
            detail="Contract has no context resolution yet; call /code-intelligence first",
        )

    result = resolution_store.get(resolution_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"No context resolution found with id {resolution_id}"
        )

    raw_request = living.contract.intent.raw_request
    _check_budget(cost_guardrail, context, raw_request, settings.slm_model)

    package, llm_response = await packager.package(result, raw_request, payload.max_tokens)

    if llm_response is not None:
        actual_cost = cost_guardrail.estimator.actual_cost(
            llm_response.prompt_tokens, llm_response.completion_tokens, settings.slm_model
        )
        context = context.spend(actual_cost, llm_response.total_tokens)

    return ContextPackageResponse(
        request_id=str(context.request_id),
        trace_id=context.trace_id or "",
        remaining_budget_usd=context.budget.remaining_usd,
        package=package,
    )
