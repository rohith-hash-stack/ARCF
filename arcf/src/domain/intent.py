"""User intent — the output of SLM-1 Intent Extraction (Phase 3).

Field set matches the Intent & Contract Layer's documented outputs:
Intent, Domain, Task, Entities, Constraints, Assumptions, Confidence,
Clarifications, Strategy Hints.
"""

from pydantic import BaseModel, ConfigDict, Field

from domain.complexity import ComplexityScore


class UserIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_request: str
    intent: str
    domain: str
    task: str
    entities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    clarifications: list[str] = Field(default_factory=list)
    strategy_hints: list[str] = Field(default_factory=list)
    complexity: ComplexityScore | None = None

    @property
    def needs_clarification(self) -> bool:
        return len(self.clarifications) > 0
