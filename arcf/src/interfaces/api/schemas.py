"""Request/response shapes for the HTTP API.

ExecuteRequest/Response are deliberately independent of Contract/
UserIntent — /api/v1/execute is the "direct" fast path, not the ARCF
pipeline. request_id/trace_id and remaining_budget_usd surface the
underlying ExecutionContext so a client (or the benchmark harness in
Phase 11) can correlate and observe cumulative spend without depending
on the domain model itself.

ContractResponse, by contrast, nests the domain Contract model directly
rather than re-declaring its fields — it *is* the pipeline's real
output, so there's no separate HTTP-shaped copy to keep in sync.
"""

from pydantic import BaseModel, ConfigDict, Field

from domain.context_package import ContextPackage
from domain.context_resolution import ContextResolutionResult
from domain.contract import Contract
from domain.enums import ContractStatus


class ExecuteRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=50_000)
    model: str | None = None
    max_tokens: int = Field(default=1024, ge=1, le=8192)


class UsageInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ExecuteResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    trace_id: str
    model: str
    content: str
    usage: UsageInfo
    estimated_cost_usd: float
    actual_cost_usd: float
    remaining_budget_usd: float
    attempts: int
    idempotent_replay: bool = False


class CreateContractRequest(BaseModel):
    raw_request: str = Field(min_length=1, max_length=10_000)
    workspace_root: str | None = None


class ClarifyContractRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=10_000)


class AttachWorkspaceRequest(BaseModel):
    workspace_root: str = Field(min_length=1)


class ContractResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    trace_id: str
    remaining_budget_usd: float
    contract_id: str
    version: int
    status: ContractStatus
    needs_clarification: bool
    clarifying_questions: list[str]
    contract: Contract


class CreateCodeIntelligenceRequest(BaseModel):
    target_names: list[str] = Field(min_length=1)
    workspace_root: str | None = None
    """Falls back to the contract's already-attached workspace_root
    (Phase 4) if omitted; a 400 is returned if neither is available."""


class CodeIntelligenceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    trace_id: str
    remaining_budget_usd: float
    contract_id: str
    contract_version: int
    resolution: ContextResolutionResult


class CreateContextPackageRequest(BaseModel):
    max_tokens: int = Field(default=8000, ge=1, le=1_000_000)


class ContextPackageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    trace_id: str
    remaining_budget_usd: float
    package: ContextPackage
