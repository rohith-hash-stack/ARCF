"""Complexity scoring.

Produced by the Execution Strategy Selector (Phase 3/7) to decide how a
request should be routed. The model only defines the shape; the scoring
algorithm itself belongs to that later phase.
"""

from pydantic import BaseModel, ConfigDict, Field

from domain.enums import ComplexityLevel


class ComplexityScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: float = Field(ge=0.0, le=1.0)
    level: ComplexityLevel
    signals: dict[str, float] = Field(default_factory=dict)
