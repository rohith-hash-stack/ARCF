"""Grounded Execution endpoint — the canonical entry point (architecture
closure, 2026-08-16).

Before this, a client had to manually drive three separate HTTP calls
(/code-intelligence -> /context-package) and then hit a dead end -- no
endpoint accepted the resulting ContextPackage and returned a generated,
verified answer. This route calls ArcfExecutionOrchestrator, which runs
the complete pipeline server-side: retrieval -> evidence check ->
context packaging -> generation -> deterministic grounding verification
-> bounded deterministic recovery -> canonical result -> execution
ledger.

Requires /contracts to have run first (same precondition
/code-intelligence and /context-package already have). The lower-level
endpoints remain available unchanged for debugging/inspection -- this
route doesn't replace them, it adds the missing final step.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from application.execute_use_case import ArcfExecutionOrchestrator
from context.understanding import DEFAULT_MAX_PARSE_RETRIES
from contracts.manager import ExecutionContractManager
from domain.execution_context import ExecutionContext
from infrastructure.cost import CostGuardrail
from infrastructure.rate_limit import RateLimiter
from interfaces.api.dependencies import (
    get_app_settings,
    get_arcf_orchestrator,
    get_contract_manager,
    get_cost_guardrail,
    get_execution_context,
    get_rate_limiter,
)
from interfaces.api.schemas import GroundedExecutionRequest, GroundedExecutionResponse
from shared.config import Settings
from shared.errors import (
    ContractNotFoundError,
    CostGuardrailExceededError,
    LLMInvocationError,
    NoWorkspaceAttachedError,
    RateLimitExceededError,
    WorkspacePathError,
)

router = APIRouter(prefix="/api/v1", tags=["grounded-execution"])


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
    "/contracts/{contract_id}/grounded-execution",
    response_model=GroundedExecutionResponse,
    # 2026-08-17 hardening (adversarial re-verification): llm_responses
    # carries raw content from EVERY real LLM call the orchestrator made,
    # including a discarded/hallucinating attempt-0 generation on a
    # recovery retry and SLM-2's internal understanding-notes JSON --
    # neither was ever meant to be client-facing (packager.py's own
    # docstring: understanding_notes is advisory, internal). Excluded
    # from the HTTP response only; still real, still used internally for
    # cost accounting just below, and still fully recorded in the
    # execution ledger (GET /api/v1/executions/{request_id}).
    response_model_exclude={"result": {"llm_responses"}},
)
async def run_grounded_execution(
    contract_id: UUID,
    payload: GroundedExecutionRequest,
    context: Annotated[ExecutionContext, Depends(get_execution_context)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    cost_guardrail: Annotated[CostGuardrail, Depends(get_cost_guardrail)],
    contract_manager: Annotated[ExecutionContractManager, Depends(get_contract_manager)],
    orchestrator: Annotated[ArcfExecutionOrchestrator, Depends(get_arcf_orchestrator)],
) -> GroundedExecutionResponse:
    _enforce_rate_limit(rate_limiter, context)

    living = await contract_manager.get_contract(contract_id)
    if living is None:
        raise HTTPException(status_code=404, detail=f"No contract found with id {contract_id}")

    # Pre-flight proxy estimate. 2026-08-17 hardening, second pass
    # (independent verification report, G-new-1): the FIRST hardening
    # pass (adversarial re-verification) scaled completion tokens by "2
    # real LLM calls (SLM-2 + generation) per attempt" -- but neither of
    # those 2 calls is really a single network call. Traced against the
    # actual implementation, not assumed:
    #   - context/understanding.py's ContextUnderstandingAnalyzer (SLM-2)
    #     retries up to DEFAULT_MAX_PARSE_RETRIES times on a parse
    #     failure (context/packager.py swallows both ContextUnderstandingError
    #     and LLMInvocationError, so packaging always proceeds regardless
    #     -- these retries genuinely can all happen without aborting the
    #     pipeline).
    #   - EVERY one of those, and the one generation call
    #     (execution/final_generation.py, a single unwrapped
    #     llm_client.complete() call), each internally retries up to
    #     settings.max_retries times on a transient provider failure
    #     (infrastructure/llm_client.py's LiteLLMClient.complete()) before
    #     either succeeding or giving up.
    #   - application/execute_use_case.py's run() loop can reach
    #     packaging+generation up to (arcf_max_recovery_attempts + 1)
    #     times: Case B (evidence missing) is checked BEFORE packaging so
    #     it costs nothing extra, but once `attempt` reaches the
    #     configured max, the loop no longer early-exits on Case B, so
    #     the final pass always reaches packaging+generation regardless
    #     of outcome.
    # True worst case per pass: (DEFAULT_MAX_PARSE_RETRIES * max_retries)
    # SLM-2 network calls + max_retries generation network calls. Total
    # worst case: that, times (arcf_max_recovery_attempts + 1) passes --
    # 18 real network calls at this project's own default settings
    # (2*3 + 3 = 9 per pass, times 2 passes), not the 4 the original
    # formula assumed. Both the proxy prompt SIZE and the assumed
    # completion tokens are now scaled by this same real call count (the
    # original version only scaled completion tokens, leaving prompt cost
    # priced as if only one of these calls' prompts existed at all) --
    # each retry genuinely re-sends a real prompt, so pricing only one
    # while completion is priced for all of them was an inconsistency in
    # the guardrail's own favor, not a documented design choice. The
    # proxy prompt's per-call size is still capped at 8000 tokens' worth
    # so a caller-requested huge max_tokens can't make this pre-check
    # itself expensive to compute. Overestimating here remains the safe
    # direction for a guardrail -- the real spend actually applied below
    # comes from the orchestrator's own accumulated llm_responses,
    # unaffected by this proxy's precision either way.
    llm_calls_per_pass = (DEFAULT_MAX_PARSE_RETRIES * settings.max_retries) + settings.max_retries
    worst_case_calls = llm_calls_per_pass * (settings.arcf_max_recovery_attempts + 1)
    prompt_tokens_per_call = min(payload.max_tokens, 8000)
    prompt_size_proxy = "word " * (prompt_tokens_per_call * worst_case_calls)
    try:
        estimate = cost_guardrail.check(
            prompt_size_proxy,
            settings.default_model,
            assumed_completion_tokens=800 * worst_case_calls,
        )
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
        result = await orchestrator.run(
            contract_id, payload.target_names, payload.workspace_root, payload.max_tokens
        )
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NoWorkspaceAttachedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkspacePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMInvocationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    actual_cost = sum(
        cost_guardrail.estimator.actual_cost(r.prompt_tokens, r.completion_tokens, r.model)
        for r in result.llm_responses
    )
    total_tokens = sum(r.total_tokens for r in result.llm_responses)
    context = context.spend(actual_cost, total_tokens)

    return GroundedExecutionResponse(
        request_id=str(context.request_id),
        trace_id=context.trace_id or "",
        remaining_budget_usd=context.budget.remaining_usd,
        result=result,
    )
