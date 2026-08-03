"""POST /api/v1/execute — the Secure Fast Path.

Guardrail order: authenticate + build ExecutionContext (FastAPI
dependency) -> rate limit -> idempotency check -> cost guardrail ->
LLM call. Rate limiting runs first since it's the cheapest check and
should shed load before any other work happens; a replayed request
still consumes rate-limit budget since it is still real inbound traffic.

The cost guardrail runs twice: once against the per-call cap (Settings,
via CostGuardrail — unchanged from before) and once against the
ExecutionContext's cumulative per-request budget. With one call per
request today those coincide, but the cumulative check is what will
matter once Phase 3+ chains multiple SLM/LLM calls under one context.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from domain.execution_context import ExecutionContext
from infrastructure.cost import CostGuardrail
from infrastructure.idempotency import IdempotencyGuard, hash_payload
from infrastructure.llm_client import LiteLLMClient
from infrastructure.rate_limit import RateLimiter
from interfaces.api.dependencies import (
    get_app_settings,
    get_cost_guardrail,
    get_execution_context,
    get_idempotency_guard,
    get_llm_client,
    get_rate_limiter,
)
from interfaces.api.schemas import ExecuteRequest, ExecuteResponse, UsageInfo
from shared.config import Settings
from shared.errors import (
    CostGuardrailExceededError,
    IdempotencyConflictError,
    LLMInvocationError,
    RateLimitExceededError,
)

router = APIRouter(prefix="/api/v1", tags=["execute"])


@router.post("/execute", response_model=ExecuteResponse)
async def execute(
    payload: ExecuteRequest,
    context: Annotated[ExecutionContext, Depends(get_execution_context)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    idempotency_guard: Annotated[IdempotencyGuard, Depends(get_idempotency_guard)],
    cost_guardrail: Annotated[CostGuardrail, Depends(get_cost_guardrail)],
    llm_client: Annotated[LiteLLMClient, Depends(get_llm_client)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExecuteResponse:
    try:
        rate_limiter.enforce(context.principal.id)
    except RateLimitExceededError as exc:
        capped_retry_after = min(exc.retry_after_seconds, 3600.0)
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(int(capped_retry_after) + 1)},
        ) from exc

    model = payload.model or settings.default_model
    request_hash = hash_payload(payload.model_dump())

    if idempotency_key:
        try:
            cached = idempotency_guard.check(idempotency_key, request_hash)
        except IdempotencyConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if cached is not None:
            return ExecuteResponse(**cached.body, idempotent_replay=True)

    try:
        estimate = cost_guardrail.check(payload.prompt, model, payload.max_tokens)
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

    try:
        completion = await llm_client.complete(payload.prompt, model, payload.max_tokens)
    except LLMInvocationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    actual_cost = cost_guardrail.estimator.actual_cost(
        completion.prompt_tokens, completion.completion_tokens, model
    )
    context = context.spend(actual_cost, completion.total_tokens)

    response = ExecuteResponse(
        request_id=str(context.request_id),
        trace_id=context.trace_id or "",
        model=model,
        content=completion.content,
        usage=UsageInfo(
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            total_tokens=completion.total_tokens,
        ),
        estimated_cost_usd=estimate.estimated_cost_usd,
        actual_cost_usd=actual_cost,
        remaining_budget_usd=context.budget.remaining_usd,
        attempts=completion.attempts,
    )

    if idempotency_key:
        idempotency_guard.save(
            idempotency_key,
            request_hash,
            status_code=200,
            body=response.model_dump(exclude={"idempotent_replay"}),
        )

    return response
