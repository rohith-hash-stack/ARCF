"""EvidenceSummary (ARCF-DI Phase 5) — the output of evidence-constrained
summarization: rendered text, the evidence ids actually cited, and how
it was produced and verified. Pure data; the generation/verification
logic lives in context/evidence_summarizer.py, which is also the only
place in this phase that touches infrastructure.llm_client — this
module has no such dependency, matching domain/behavioral_record.py's
own "pure data" discipline.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SummarySource(StrEnum):
    TEMPLATE = "template"
    """Zero LLM involvement — composed directly from BehavioralRecord
    fields. Always fully cited by construction: every clause is a direct
    rendering of a field that is itself already-verified evidence."""
    SLM = "slm"
    """LLM-generated, then passed through citation/denylist verification.
    Used only when the record has enough evidence that template
    rendering would be unwieldy — see BLUEPRINT.md Phase 5's "small
    records skip the SLM entirely" design."""


class SummaryConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RejectedClaim(BaseModel):
    """A generated sentence that failed verification and was dropped
    rather than kept — the audit trail for what the SLM produced that
    didn't survive the "never create evidence" check, not just a count."""

    model_config = ConfigDict(frozen=True)

    text: str
    reason: str


class EvidenceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol_id: str
    text: str
    """Final, verified summary text with citation tags stripped for
    readability. Empty when `insufficient_evidence` is True."""
    citations: list[str] = Field(default_factory=list)
    """Evidence ids actually cited in `text`, deduplicated and sorted —
    every one of these resolves back to a real field on the
    BehavioralRecord this summary was built from."""
    source: SummarySource
    confidence: SummaryConfidence
    """Computed mechanically from the record (disambiguation_aware,
    presence of ambiguous_calls, dependency_depth.truncated) — never
    self-reported by the model. See context/evidence_summarizer.py's
    `_confidence`."""
    insufficient_evidence: bool = False
    """True when the record had evidence but the summarizer could not
    produce any sentence that passed verification — an honest "nothing
    to safely say," not a silently empty summary that looks the same as
    "there was nothing to summarize.\""""
    rejected_claims: list[RejectedClaim] = Field(default_factory=list)
