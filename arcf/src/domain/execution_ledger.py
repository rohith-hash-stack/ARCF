"""ExecutionLedgerEntry — Phase 9's per-execution audit record. Stage 4
of the v2.3 migration plan (see arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md
Sec. 2.6/5.2/6/7).

Every field is sourced from an object Phases 1-8 already produce (see
the field-source table in Sec. 5.2) — nothing here invents new
tracking. One field the table lists is deliberately omitted:
"files/lines changed". Deriving that requires parsing the Artifact's
content as a diff — benchmark/suite/quality.py's extract_modified_files
does exactly that, but only because the benchmark's own harness forces
a "### path" + fenced-block output convention on every mode purely so
its own automated verification can apply a patch (see
context_goal_composer.py's docstring). Phase 8's Composer imposes no
such schema — an Artifact's content may be prose, a diff, or full
files — so a line-diff count can't be derived here without silently
assuming a format ARCF itself doesn't enforce. That stays a
benchmark-suite concern, not a Ledger concern.

manual_rating and build_test_result are nullable and opt-in — nothing
in this layer sets them automatically; a caller fills them in after
the fact (e.g. via PATCH /api/v1/executions/{request_id}).
"""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from domain.predicted_response import PredictedResponseHint
from shared.clock import utc_now

ExecutionMode = Literal["direct", "arcf"]


class ExecutionLedgerEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: UUID = Field(default_factory=uuid4)
    workspace_id: str
    contract_id: str
    mode: ExecutionMode
    model: str

    repository_root: str | None = None
    branch: str | None = None

    prompt: str
    selected_files: list[str] = Field(default_factory=list)
    selected_symbols: list[str] = Field(default_factory=list)

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)
    estimated_cost_usd: float = Field(ge=0.0)

    artifact_content: str
    predicted_response: PredictedResponseHint | None = None

    build_test_result: str | None = None
    manual_rating: int | None = Field(default=None, ge=1, le=5)

    created_at: datetime = Field(default_factory=utc_now)

    def with_manual_rating(self, rating: int) -> "ExecutionLedgerEntry":
        return self.model_copy(update={"manual_rating": rating})

    def with_build_test_result(self, result: str) -> "ExecutionLedgerEntry":
        return self.model_copy(update={"build_test_result": result})
