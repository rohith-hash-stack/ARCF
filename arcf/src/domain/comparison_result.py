"""ComparisonResult — Phase 11's cross-mode (direct vs. ARCF) comparison
record. Stage 5 of the v2.3 migration plan (see
arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md Sec. 2.4/5.1/6/7).

Generalizes benchmark/src/benchmark/domain/models.py's ComparisonResult
shape into arcf/src, built directly from two already-persisted
ExecutionLedgerEntry records (one "direct", one "arcf") rather than
re-deriving a parallel set of run objects — the Ledger entry already
carries everything a comparison needs (tokens, latency, cost, selected
files, artifact content).

context_efficiency_ratio (CER) is None whenever the direct entry has no
selected_files — the normal case, since Direct mode does no context
selection under this schema and there is no repository-wide file count
in ExecutionLedgerEntry to use as a baseline denominator. Reporting
None here is the same choice benchmark/domain/models.py's
QualityMetrics docstring already made for compilation_success/
test_success: an explicit, visible gap instead of a faked ratio.
prompt_compression_ratio (PCR) has no such gap — every entry has a
non-zero prompt_tokens count regardless of mode.
"""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from domain.execution_ledger import ExecutionLedgerEntry
from shared.clock import utc_now


class ComparisonResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    task: str
    repository: str

    direct: ExecutionLedgerEntry
    arcf: ExecutionLedgerEntry

    token_reduction_pct: float | None = None
    latency_reduction_pct: float | None = None
    cost_reduction_pct: float | None = None
    context_efficiency_ratio: float | None = None
    """CER = len(arcf.selected_files) / len(direct.selected_files)."""
    prompt_compression_ratio: float | None = None
    """PCR = direct.prompt_tokens / arcf.prompt_tokens."""

    generated_at: datetime = Field(default_factory=utc_now)
