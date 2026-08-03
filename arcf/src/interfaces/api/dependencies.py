"""FastAPI dependency wiring.

Singletons (authenticator, rate limiter, idempotency store, cost
guardrail, LLM client, tracer) live on app.state, built once in
app.create_app(). These functions just fetch them off the request so
route handlers stay thin and the singletons stay swappable in tests.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from code_intelligence.service import CodeIntelligenceContractService
from context.packager import ContextPackager
from contracts.manager import ExecutionContractManager
from domain.execution_context import ExecutionContext, TokenBudget
from domain.principal import Principal
from infrastructure.auth import Authenticator
from infrastructure.comparison_store import ComparisonStore
from infrastructure.context_resolution_store import ContextResolutionStore
from infrastructure.cost import CostGuardrail
from infrastructure.execution_ledger_db import ExecutionLedgerStore
from infrastructure.idempotency import IdempotencyGuard
from infrastructure.llm_client import LiteLLMClient
from infrastructure.rate_limit import RateLimiter
from shared.config import Settings
from shared.errors import AuthenticationError
from telemetry.comparison_aggregator import ComparisonAggregator
from workspace.service import WorkspaceContractService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_authenticator(request: Request) -> Authenticator:
    return request.app.state.authenticator  # type: ignore[no-any-return]


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter  # type: ignore[no-any-return]


def get_idempotency_guard(request: Request) -> IdempotencyGuard:
    return request.app.state.idempotency_guard  # type: ignore[no-any-return]


def get_cost_guardrail(request: Request) -> CostGuardrail:
    return request.app.state.cost_guardrail  # type: ignore[no-any-return]


def get_llm_client(request: Request) -> LiteLLMClient:
    return request.app.state.llm_client  # type: ignore[no-any-return]


def get_contract_manager(request: Request) -> ExecutionContractManager:
    return request.app.state.contract_manager  # type: ignore[no-any-return]


def get_workspace_service(request: Request) -> WorkspaceContractService:
    return request.app.state.workspace_service  # type: ignore[no-any-return]


def get_code_intelligence_service(request: Request) -> CodeIntelligenceContractService:
    return request.app.state.code_intelligence_service  # type: ignore[no-any-return]


def get_context_resolution_store(request: Request) -> ContextResolutionStore:
    return request.app.state.context_resolution_store  # type: ignore[no-any-return]


def get_context_packager(request: Request) -> ContextPackager:
    return request.app.state.context_packager  # type: ignore[no-any-return]


def get_execution_ledger_store(request: Request) -> ExecutionLedgerStore:
    return request.app.state.execution_ledger_store  # type: ignore[no-any-return]


def get_comparison_store(request: Request) -> ComparisonStore:
    return request.app.state.comparison_store  # type: ignore[no-any-return]


def get_comparison_aggregator(request: Request) -> ComparisonAggregator:
    return request.app.state.comparison_aggregator  # type: ignore[no-any-return]


def get_current_principal(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> Principal:
    bearer_token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer_token = authorization[len("bearer ") :].strip()

    authenticator = get_authenticator(request)
    try:
        return authenticator.authenticate(api_key=x_api_key, bearer_token=bearer_token)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def get_execution_context(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
    principal: Annotated[Principal, Depends(get_current_principal)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ExecutionContext:
    """Built once per inbound request, after auth succeeds. Threaded through
    every guardrail (and, from Phase 3 on, every pipeline stage) instead of
    passing principal/trace_id/idempotency_key as separate parameters.
    """
    trace_id: str | None = getattr(request.state, "trace_id", None)
    return ExecutionContext(
        trace_id=trace_id,
        principal=principal,
        idempotency_key=idempotency_key,
        budget=TokenBudget(max_usd=settings.cost_guardrail_max_usd),
    )
