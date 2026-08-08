"""RelevanceRanker (Phase 6 deliverable) — deterministic scoring of
ContextResolutionResult.candidate_files.

Selection is never made by an SLM: this is a fixed, reproducible
function of signals already present in the contract (reason type,
whether the file contains an entry point, how many impacted symbols it
holds) — the same "software governs, SLM only assists" posture as
Phase 3's ConfidenceEngine.

ARCF architecture hardening §7 (task-aware deterministic ranking):
`rank()` takes an optional reason-verb weight `profile` — see
context/task_profile.py's RANKING_PROFILES, one per RetrievalTaskType —
so a bug-fix query and an architecture-explanation query over the same
candidate set can prioritize differently (direct callers vs.
configuration/dependency roots) without either becoming probabilistic:
every profile is still a fixed, reproducible weight table, just a
different one. `profile=None` (the default) reproduces the exact
pre-hardening weights below, unchanged.
"""

from collections import Counter
from dataclasses import dataclass

from domain.context_resolution import ContextResolutionResult, EvidenceTier

# "references:" is context/evidence_fallback.py's tag for a query-
# referenced file (one the raw request itself named) — weighted one
# tier above its generic "evidence: <category>" fallback files (which
# fall through to _DEFAULT_REASON_WEIGHT below), so a file the user
# actually asked about survives ContextBudgetManager's token cutoff
# ahead of baseline diagnostic evidence when both can't fit.
_REASON_WEIGHTS: dict[str, float] = {
    "defines": 1.0,
    "calls": 0.7,
    # ARCF Issue #9 fix (2026-08-08): ContextResolver emits "called by X
    # (hop N)" for transitive callees (see context_resolver.py's
    # _expand_calls), whose first word is "called", not "calls" — this
    # table had no entry for it, so every hop-N caller-chain file was
    # silently scored at the generic default weight instead of the
    # "calls" weight actually intended for call-graph relationships.
    # Same value as "calls": both represent the same kind of evidence
    # (a call-graph edge), just labelled by direction in the reason
    # string. Found via real SQLAlchemy data (2026-08-08 Phase 6
    # activation check) where this silently suppressed both canonical
    # files' scores.
    "called": 0.7,
    "extends": 0.6,
    "references:": 0.8,
}
_DEFAULT_REASON_WEIGHT = 0.3
_ENTRY_POINT_BONUS = 0.2
_IMPACT_BONUS_MAX = 0.1
_IMPACT_BONUS_CAP = 5


@dataclass(frozen=True)
class RankedFile:
    file_path: str
    relevance_score: float
    reason: str
    language: str
    token_count: int
    evidence_tier: EvidenceTier = EvidenceTier.PRIMARY
    """Carried straight through from FileReference — see EvidenceTier's
    own docstring. Drives ContextBudgetManager's compress-vs-keep-full
    decision; relevance_score (ranking order) and evidence_tier
    (compression policy) are deliberately independent axes."""


class RelevanceRanker:
    def rank(
        self, result: ContextResolutionResult, profile: dict[str, float] | None = None
    ) -> list[RankedFile]:
        entry_point_files = {symbol.file_path for symbol in result.entry_points}
        impacted_counts = Counter(symbol.file_path for symbol in result.impacted_symbols)

        ranked = [
            RankedFile(
                file_path=file_ref.file_path,
                relevance_score=self._score(
                    file_ref.reason,
                    file_ref.file_path,
                    entry_point_files,
                    impacted_counts,
                    profile,
                    file_ref.anchor_confidence,
                ),
                reason=file_ref.reason,
                language=file_ref.language,
                token_count=file_ref.token_count,
                evidence_tier=file_ref.evidence_tier,
            )
            for file_ref in result.candidate_files
        ]
        return sorted(ranked, key=lambda ranked_file: ranked_file.relevance_score, reverse=True)

    @staticmethod
    def _score(
        reason: str,
        file_path: str,
        entry_point_files: set[str],
        impacted_counts: Counter[str],
        profile: dict[str, float] | None,
        anchor_confidence: float | None = None,
    ) -> float:
        weights = profile if profile is not None else _REASON_WEIGHTS
        verb = reason.split(" ", 1)[0]
        base = weights.get(verb, weights.get("*", _DEFAULT_REASON_WEIGHT))
        entry_bonus = _ENTRY_POINT_BONUS if file_path in entry_point_files else 0.0
        impact_count = min(impacted_counts.get(file_path, 0), _IMPACT_BONUS_CAP)
        impact_bonus = impact_count / _IMPACT_BONUS_CAP * _IMPACT_BONUS_MAX
        role_score = min(base + entry_bonus + impact_bonus, 1.0)
        # ARCF Pre-Expansion Anchor Classification experiment
        # (2026-08-08): final_score = anchor_confidence * role_score,
        # only when a confidence was actually computed
        # (`enable_confidence_propagation`) — `None` (every existing
        # caller, and this flag off) multiplies by 1.0, i.e. no change
        # to role_score at all. This is additive to the existing
        # role-weight system, not a replacement of it: role_score above
        # is computed exactly as before, unconditionally.
        confidence_factor = anchor_confidence if anchor_confidence is not None else 1.0
        return round(min(role_score * confidence_factor, 1.0), 4)
