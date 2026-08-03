"""ExecutionContext — request/session metadata threaded through every
pipeline stage.

Deliberately separate from Contract/LivingContract: Contract carries
*what* is being done (intent, workspace, strategy); ExecutionContext
carries *who/how/how-much* around the doing (identity, correlation ids,
spend so far). Phase 9's Execution Ledger keys entries off it, Phase
10's LangGraph state wraps it alongside a LivingContract, and Phase 11's
Token Intelligence Engine correlates usage records by its request_id.

Frozen, like Contract/LivingContract — a spend is recorded by producing
a new ExecutionContext via .spend(), never by mutating one in place,
so a chain of contexts is as auditable as a chain of contract versions.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from domain.principal import Principal
from shared.clock import utc_now


class TokenBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_usd: float = Field(ge=0.0)
    spent_usd: float = Field(default=0.0, ge=0.0)
    spent_tokens: int = Field(default=0, ge=0)

    @property
    def remaining_usd(self) -> float:
        return self.max_usd - self.spent_usd

    def has_remaining(self, estimated_usd: float) -> bool:
        return self.spent_usd + estimated_usd <= self.max_usd

    def spend(self, usd: float, tokens: int) -> "TokenBudget":
        return self.model_copy(
            update={
                "spent_usd": self.spent_usd + usd,
                "spent_tokens": self.spent_tokens + tokens,
            }
        )


class ExecutionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: UUID = Field(default_factory=uuid4)
    trace_id: str | None = None
    principal: Principal
    idempotency_key: str | None = None
    budget: TokenBudget
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def with_trace_id(self, trace_id: str) -> "ExecutionContext":
        return self.model_copy(update={"trace_id": trace_id})

    def spend(self, usd: float, tokens: int) -> "ExecutionContext":
        return self.model_copy(update={"budget": self.budget.spend(usd, tokens)})
