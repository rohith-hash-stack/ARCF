"""PredictedResponseHint — PRHL (Predictive Response Hinting Layer)
domain model. Stage 2 of the v2.3 migration plan (see
arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md Sec. 2.2/6/7).

Advisory-only, modeled directly on ContextUnderstandingNote's (SLM-2,
context/understanding.py) shape: a small LLM call's structured output
about a ContextPackage, never feeding back into selection or
constraining a final generation prompt. Stored as a sibling artifact
(future Execution Ledger entry, surfaced by a future Comparison UI) —
enforced structurally by giving execution/prhl.py, which produces this,
no channel back into whatever assembles the final prompt (Phase 8's
Context + Goal Composer), only a sibling output alongside it.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DiffScope = Literal["small", "medium", "large"]


class PredictedResponseHint(BaseModel):
    model_config = ConfigDict(frozen=True)

    likely_direction: str
    """Short (1-2 sentence) prediction of how the task will likely be
    solved, e.g. "add a new method to AuthService and wire it into the
    login route"."""
    probable_touchpoints: list[str] = Field(default_factory=list)
    """File paths the model expects will need to change, drawn from
    (but not limited to) the ContextPackage's relevant_files."""
    expected_diff_scope: DiffScope
    anticipated_dependencies: list[str] = Field(default_factory=list)
    """New imports/packages/modules the model expects the change will
    introduce that aren't already part of the selected context."""
    risk_flags: list[str] = Field(default_factory=list)
    """Short warnings, e.g. "may require a schema migration" or "touches
    code with no test coverage" — advisory only, never blocks anything."""
