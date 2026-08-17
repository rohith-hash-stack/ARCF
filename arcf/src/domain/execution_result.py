"""ArcfExecutionResult -- the canonical execution result (architecture
closure, 2026-08-16, P0.9). Before this closure there was no single
object representing "what happened" for a grounded ARCF execution --
three separate HTTP responses (contract, code-intelligence,
context-package) and a structurally unrelated raw-prompt response
(/api/v1/execute). This is that missing, single contract.

resolution_confidence / resolution_confidence_source deliberately do
NOT blend into a combined score (closure Sec. F/§25-27 -- confidence
values with different meanings stay separate). This carries
ContextResolutionResult.confidence verbatim, but adds the provenance tag
that field itself still lacks (a real, pre-existing, deliberately
DEFERRED gap -- see the closure checklist Sec. 19/39): classic
resolution and DRP resolution compute this field with two structurally
different formulas, and nothing on the old field says which one ran.
This new result at least tells the caller which one produced the value
it's holding, without touching -- or further obscuring -- the old
field's own contract.
"""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from domain.artifact import Artifact
from domain.verification_result import GroundingVerificationResult
from infrastructure.llm_client import LLMResponse

ResolverStrategy = Literal["classic", "drp"]
FinalExecutionStatus = Literal["success", "low_confidence"]


class ArcfExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: UUID = Field(default_factory=uuid4)
    contract_id: str
    context_resolution_id: UUID | None = None
    context_package_id: UUID | None = None
    artifact: Artifact | None = None
    verification: GroundingVerificationResult | None = None
    recovery_attempts: int = 0
    strategy_used: ResolverStrategy = "classic"
    final_status: FinalExecutionStatus
    resolution_confidence: float
    resolution_confidence_source: ResolverStrategy
    llm_responses: tuple[LLMResponse, ...] = Field(default_factory=tuple)
