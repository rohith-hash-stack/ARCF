"""Contract endpoints — the start of the real ARCF pipeline.

Unlike /api/v1/execute (Phase 2's guarded direct call), these routes
run SLM-1 intent extraction and produce a versioned, persisted Contract.
They reuse the exact same ExecutionContext/rate-limit/cost-guardrail
machinery /execute uses, applied to a different pipeline stage — the
cumulative budget check on ExecutionContext.budget is what makes this
composable with future stages (SLM-2, the main LLM call) under one
request's budget, rather than each stage inventing its own guardrail.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from contracts.manager import ExecutionContractManager
from domain.execution_context import ExecutionContext
from domain.versioning import LivingContract
from infrastructure.cost import CostGuardrail
from infrastructure.llm_client import LLMResponse
from infrastructure.rate_limit import RateLimiter
from interfaces.api.dependencies import (
    get_app_settings,
    get_contract_manager,
    get_cost_guardrail,
    get_execution_context,
    get_rate_limiter,
)
from interfaces.api.schemas import ClarifyContractRequest, ContractResponse, CreateContractRequest
from shared.config import Settings
from shared.errors import (
    ContractNotFoundError,
    CostGuardrailExceededError,
    IntentExtractionError,
    LLMInvocationError,
    RateLimitExceededError,
)

router = APIRouter(prefix="/api/v1", tags=["contracts"])


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
        estimate = cost_guardrail.check(prompt, model, assumed_completion_tokens=512)
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


def _to_response(
    living: LivingContract,
    llm_response: LLMResponse,
    context: ExecutionContext,
    cost_guardrail: CostGuardrail,
) -> ContractResponse:
    actual_cost = cost_guardrail.estimator.actual_cost(
        llm_response.prompt_tokens, llm_response.completion_tokens, llm_response.model
    )
    context = context.spend(actual_cost, llm_response.total_tokens)
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


@router.post("/contracts", response_model=ContractResponse)
async def create_contract(
    payload: CreateContractRequest,
    context: Annotated[ExecutionContext, Depends(get_execution_context)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    cost_guardrail: Annotated[CostGuardrail, Depends(get_cost_guardrail)],
    contract_manager: Annotated[ExecutionContractManager, Depends(get_contract_manager)],
) -> ContractResponse:
    _enforce_rate_limit(rate_limiter, context)
    _check_budget(cost_guardrail, context, payload.raw_request, settings.slm_model)

    try:
        living, llm_response = await contract_manager.create_contract(
            payload.raw_request, payload.workspace_root
        )
    except (IntentExtractionError, LLMInvocationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _to_response(living, llm_response, context, cost_guardrail)


@router.post("/contracts/{contract_id}/clarify", response_model=ContractResponse)
async def clarify_contract(
    contract_id: UUID,
    payload: ClarifyContractRequest,
    context: Annotated[ExecutionContext, Depends(get_execution_context)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    cost_guardrail: Annotated[CostGuardrail, Depends(get_cost_guardrail)],
    contract_manager: Annotated[ExecutionContractManager, Depends(get_contract_manager)],
) -> ContractResponse:
    _enforce_rate_limit(rate_limiter, context)
    _check_budget(cost_guardrail, context, payload.answer, settings.slm_model)

    try:
        living, llm_response = await contract_manager.clarify(contract_id, payload.answer)
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (IntentExtractionError, LLMInvocationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _to_response(living, llm_response, context, cost_guardrail)


@router.get("/contracts/{contract_id}", response_model=ContractResponse)
async def get_contract(
    contract_id: UUID,
    context: Annotated[ExecutionContext, Depends(get_execution_context)],
    cost_guardrail: Annotated[CostGuardrail, Depends(get_cost_guardrail)],
    contract_manager: Annotated[ExecutionContractManager, Depends(get_contract_manager)],
) -> ContractResponse:
    living = await contract_manager.get_contract(contract_id)
    if living is None:
        raise HTTPException(status_code=404, detail=f"No contract found with id {contract_id}")

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
