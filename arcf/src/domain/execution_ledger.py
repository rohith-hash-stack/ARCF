"""ExecutionLedgerEntry — Phase 9's per-execution audit record. Stage 4
of the v2.3 migration plan (see arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md
Sec. 2.6/5.2/6/7), extended per the v2.3 Validation Baseline request
(see arcf/docs/ARCF_V2.3_VALIDATION_READINESS_REPORT.md) to carry the
full field set a comparative Direct-vs-ARCF benchmark needs: files
changed, lines changed, a build result, and a test result, in addition
to the fields Sec. 5.2 already specified.

files_changed/lines_changed/build_result/test_result are caller-
supplied, not derived by this layer: Phase 8's Composer imposes no
output schema on artifact_content (prose, a diff, or full files are
all valid), so parsing a reliable file/line-change count out of it
here would mean silently assuming a format ARCF itself doesn't
enforce. benchmark/src/benchmark/quality.py's extract_modified_files
and suite/verifier.py's run_verification already do this correctly for
the benchmark harness's own fenced/diff output convention — a caller
(the benchmark, or any future orchestration layer) computes these
values with the format knowledge it has and passes them in when
constructing (or patching) an entry. Left at their empty defaults for
any caller that hasn't computed them, rather than guessed.

execution_status describes whether the run itself completed, not code
quality — "success" for a normal Composer/FinalGenerationRunner
completion; "timeout"/"provider_error"/"validation_error"/
"execution_error" classify why it didn't, per the ARCF v2.3 Execution
Directive's requested taxonomy (a provider/LLM-call failure is
distinguished from a validation failure — e.g. a workspace path
rejected by a permission check — which is distinguished from anything
else, caught generically as "execution_error"). build_result/
test_result are a separate, later judgment about the artifact's
correctness, normally set after the fact (e.g. via
PATCH /api/v1/executions/{request_id}) once a caller has actually
attempted a build/test cycle — nothing in this layer runs one
automatically. manual_rating remains nullable and opt-in for the same
reason.

provider/metadata are also new: provider names which BenchmarkProvider
(openai/anthropic/gemini/groq/ollama/...) resolved `model`, when the
caller used that registry — None for any caller that passed a raw
model string directly, which remains fully supported. metadata is an
open dict for anything worth recording that isn't worth a first-class
column: an execution contract summary, context package metadata, or
error detail for a failed run — kept generic rather than embedding
full domain objects (Contract, ContextPackage) here and repeating the
bloat concern those models' own docstrings already raise about
embedding each other.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from domain.predicted_response import PredictedResponseHint
from shared.clock import utc_now

ExecutionMode = Literal["direct", "arcf"]
ExecutionStatus = Literal[
    "success", "timeout", "provider_error", "validation_error", "execution_error"
]
VerificationResult = Literal["passed", "failed", "not_run"]


class ExecutionLedgerEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: UUID = Field(default_factory=uuid4)
    workspace_id: str
    contract_id: str
    mode: ExecutionMode
    model: str
    provider: str | None = None

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

    execution_status: ExecutionStatus = "success"
    """Whether the run itself completed — not a judgment on the
    generated artifact's correctness. See build_result/test_result for
    that."""

    files_changed: list[str] = Field(default_factory=list)
    lines_changed: int = Field(default=0, ge=0)
    build_result: VerificationResult | None = None
    test_result: VerificationResult | None = None
    manual_rating: int | None = Field(default=None, ge=1, le=5)

    metadata: dict[str, Any] = Field(default_factory=dict)

    created_at: datetime = Field(default_factory=utc_now)

    def with_manual_rating(self, rating: int) -> "ExecutionLedgerEntry":
        return self.model_copy(update={"manual_rating": rating})

    def with_build_result(self, result: VerificationResult) -> "ExecutionLedgerEntry":
        return self.model_copy(update={"build_result": result})

    def with_test_result(self, result: VerificationResult) -> "ExecutionLedgerEntry":
        return self.model_copy(update={"test_result": result})
