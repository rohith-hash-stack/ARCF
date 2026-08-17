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

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from domain.context_package import ContextPackage
from domain.context_resolution import ContextResolutionResult
from domain.contract import Contract
from domain.enums import ContractStatus
from domain.execution_ledger import ExecutionLedgerEntry, VerificationResult
from domain.execution_result import ArcfExecutionResult


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
    target_names: list[str] = Field(default_factory=list)
    """Architecture closure (2026-08-16): may be omitted/empty -- when
    empty, CodeIntelligenceContractService.attach_code_intelligence
    defaults to the contract's own SLM-1-extracted
    intent.entities, so a client is no longer required to duplicate
    entity extraction by hand. Still accepted explicitly for debugging/
    override use; every existing caller that supplies names keeps
    identical behavior."""
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


class GroundedExecutionRequest(BaseModel):
    """Architecture closure (2026-08-16): the canonical entry point.
    Replaces the client-driven code-intelligence -> context-package ->
    (nothing) chain with one server-side orchestrated call that reaches
    Generation, Verification, and bounded Recovery. target_names is now
    optional -- when omitted, retrieval defaults to the contract's own
    SLM-1-extracted intent.entities (see
    code_intelligence/service.py's attach_code_intelligence)."""

    target_names: list[str] = Field(default_factory=list)
    workspace_root: str | None = None
    max_tokens: int = Field(default=8000, ge=1, le=1_000_000)


class GroundedExecutionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    trace_id: str
    remaining_budget_usd: float
    result: ArcfExecutionResult


class PatchExecutionLedgerRequest(BaseModel):
    """All fields are opt-in and nullable — see domain/execution_ledger.py.
    At least one must be provided; omitting all of them is a 400, not a
    no-op."""

    manual_rating: int | None = Field(default=None, ge=1, le=5)
    build_result: VerificationResult | None = None
    test_result: VerificationResult | None = None


class ExecutionComparisonResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    entry_a: ExecutionLedgerEntry
    entry_b: ExecutionLedgerEntry
    total_tokens_delta: int
    """entry_b.total_tokens - entry_a.total_tokens."""
    estimated_cost_delta_usd: float
    """entry_b.estimated_cost_usd - entry_a.estimated_cost_usd."""
    latency_delta_ms: float
    """entry_b.latency_ms - entry_a.latency_ms."""
    artifact_diff: str
    """Unified diff of artifact_content, a -> b. Purely textual — makes
    no assumption about whether either artifact is prose, a patch, or
    full file contents, since Phase 8 imposes no output schema."""


class CreateComparisonRequest(BaseModel):
    """References two already-persisted Execution Ledger entries rather
    than driving a Direct/ARCF run itself — see
    interfaces/api/routes/comparison.py's module docstring for why."""

    task: str = Field(min_length=1, max_length=2_000)
    repository: str = Field(min_length=1)
    direct_request_id: UUID
    arcf_request_id: UUID
