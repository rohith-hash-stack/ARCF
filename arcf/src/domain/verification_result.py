"""Deterministic Grounding Verification result — the architecture-closure
contract between Generation and Recovery (see
arcf/docs/ARCF_ARCHITECTURE_CLOSURE_PLAN_2026-08-16.md Sec. I).

Deliberately named GroundingVerificationResult, not VerificationResult:
domain/execution_ledger.py already defines VerificationResult as a
Literal["passed","failed","not_run"] for caller-supplied build/test
outcomes (an unrelated concept — external tool results patched in after
the fact). Reusing that name for this, structurally different concept
would recreate exactly the same-field-name-different-meaning conflation
the architecture audit already flagged for
ContextResolutionResult.confidence (two producers, one field, no
provenance marker) — see the closure plan's confidence inventory.

This type answers only the questions the current architecture can
honestly support without inventing new capability (closure plan Sec. I):
- Was evidence available? (evidence_sufficient)
- Was required evidence missing? (missing_evidence_categories)
- Does the generated artifact reference a file that was never retrieved?
  (unsupported_file_references) -- a deterministic path/text check, not
  a semantic claim-by-claim fact-check.

It deliberately does NOT claim semantic contradiction detection.
contradictions_checked is always False -- an explicit, honest "not
supported today" rather than a fabricated always-passing field or a
silently omitted one.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class GroundingVerificationStatus(StrEnum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNSUPPORTED_REFERENCES = "unsupported_references"


class GroundingVerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: GroundingVerificationStatus
    evidence_sufficient: bool
    missing_evidence_categories: tuple[str, ...] = Field(default_factory=tuple)
    unsupported_file_references: tuple[str, ...] = Field(default_factory=tuple)
    contradictions_checked: bool = False
    recovery_eligible: bool
