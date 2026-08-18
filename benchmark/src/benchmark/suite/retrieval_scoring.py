"""Rank-based retrieval metrics (Recall@1, Recall@5, MRR) and failure
classification for the semantic-layer experiment.

No Recall@k/MRR function existed anywhere in this codebase before this
module (confirmed by grepping both `arcf/` and `benchmark/`) — the
closest prior art is `arcf/scripts/qualified_id_falsification.py`'s
inline MRR computation and `code_intelligence/drp/diagnostics.py`'s
`compute_retrieval_rank`, the SAME 1-based-rank primitive
`arcf/scripts/drp_benchmark.py` already uses against
`resolution.candidate_files`. This module reuses that primitive rather
than inventing a second rank definition, and generalizes the inline MRR
pattern into a named, tested function.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from code_intelligence.drp.diagnostics import compute_retrieval_rank

__all__ = [
    "compute_retrieval_rank",
    "recall_at_k",
    "mean_recall_at_k",
    "reciprocal_rank",
    "mean_reciprocal_rank",
    "FailureClass",
    "TaskDiagnosis",
    "diagnose",
]


def recall_at_k(rank: int | None, k: int) -> bool:
    """True iff the target was retrieved AND ranked at or above k."""
    return rank is not None and rank <= k


def mean_recall_at_k(ranks: list[int | None], k: int) -> float:
    if not ranks:
        return 0.0
    return sum(1 for r in ranks if recall_at_k(r, k)) / len(ranks)


def reciprocal_rank(rank: int | None) -> float:
    return 0.0 if rank is None else 1.0 / rank


def mean_reciprocal_rank(ranks: list[int | None]) -> float:
    if not ranks:
        return 0.0
    return sum(reciprocal_rank(r) for r in ranks) / len(ranks)


class FailureClass(StrEnum):
    """The Step-6 diagnostic taxonomy. SUCCESS plus the six categories
    the experiment brief asks every failure be classified into:

        A -> TARGET_NOT_IN_POOL
        B -> TARGET_IN_POOL_RANKED_TOO_LOW
        C -> SLM_INTERPRETATION_LIKELY_WRONG
        D -> SLM_TERMS_UNRESOLVABLE_BY_ARCF_DI
        E -> QUERY_INHERENTLY_AMBIGUOUS
        F -> OTHER_DETERMINISTIC_LIMITATION

    C, D, and F are NOT fully automatable from rank/pool membership
    alone — distinguishing "the SLM's guess was wrong" (C) from "the
    guess was reasonable but the deterministic side couldn't use it" (D)
    from "neither — some other deterministic limitation" (F) needs a
    signal about whether the SLM's terms were topically reasonable. This
    module uses a best-effort heuristic (loose term overlap against a
    task's own `expected_grounding_terms`, when the caller supplies one
    — see `diagnose`'s docstring) and labels the result a HEURISTIC, not
    a certainty: it is explicitly weaker evidence than a human read of
    the actual SLM output, and callers/reports must say so rather than
    treat C vs D vs F as ground truth. E is never inferred automatically
    — it requires the task's own author to have flagged the query as
    inherently ambiguous ahead of time (a `known_ambiguous` task field),
    since "is this query ambiguous" is a judgment call this module has
    no basis to make post hoc from a single run's output."""

    SUCCESS = "success"
    TARGET_NOT_IN_POOL = "A_target_never_entered_candidate_pool"
    TARGET_IN_POOL_RANKED_TOO_LOW = "B_target_in_pool_ranked_too_low"
    SLM_INTERPRETATION_LIKELY_WRONG = "C_slm_interpretation_likely_wrong_heuristic"
    SLM_TERMS_UNRESOLVABLE_BY_ARCF_DI = "D_slm_terms_reasonable_but_unresolvable"
    QUERY_INHERENTLY_AMBIGUOUS = "E_query_inherently_ambiguous"
    OTHER_DETERMINISTIC_LIMITATION = "F_other_deterministic_limitation"


@dataclass(frozen=True)
class TaskDiagnosis:
    task_id: str
    rank: int | None
    retrieval_terms: list[str] = field(default_factory=list)
    candidate_count: int = 0
    failure_class: FailureClass = FailureClass.OTHER_DETERMINISTIC_LIMITATION
    note: str = ""


def _terms_overlap_expected(terms: list[str], expected_grounding_terms: list[str]) -> bool:
    """Loose, case-insensitive substring overlap — the same spirit as
    `arcf/scripts/validate_llm_grounding.py`'s existing `_key_term_check`
    (a separate, script-local function; not imported here to avoid a
    dependency on a one-off experiment script, but deliberately the same
    idea: a soft, non-authoritative overlap check, not exact matching).
    """
    if not terms or not expected_grounding_terms:
        return False
    lowered_expected = [e.lower() for e in expected_grounding_terms]
    for term in terms:
        term_lower = term.lower()
        if any(term_lower in exp or exp in term_lower for exp in lowered_expected):
            return True
    return False


def diagnose(
    task_id: str,
    rank: int | None,
    retrieval_terms: list[str],
    candidate_count: int,
    recall_threshold_k: int = 5,
    known_ambiguous: bool = False,
    expected_grounding_terms: list[str] | None = None,
) -> TaskDiagnosis:
    """Classify one task's outcome per `FailureClass`. See that enum's
    docstring for which categories are exact vs. heuristic."""
    if rank is not None and rank <= recall_threshold_k:
        return TaskDiagnosis(
            task_id=task_id,
            rank=rank,
            retrieval_terms=retrieval_terms,
            candidate_count=candidate_count,
            failure_class=FailureClass.SUCCESS,
        )

    if rank is not None:
        return TaskDiagnosis(
            task_id=task_id,
            rank=rank,
            retrieval_terms=retrieval_terms,
            candidate_count=candidate_count,
            failure_class=FailureClass.TARGET_IN_POOL_RANKED_TOO_LOW,
            note=f"rank={rank} exceeds threshold k={recall_threshold_k}",
        )

    if known_ambiguous:
        return TaskDiagnosis(
            task_id=task_id,
            rank=None,
            retrieval_terms=retrieval_terms,
            candidate_count=candidate_count,
            failure_class=FailureClass.QUERY_INHERENTLY_AMBIGUOUS,
            note="task author flagged this query as inherently ambiguous ahead of time",
        )

    if not retrieval_terms:
        return TaskDiagnosis(
            task_id=task_id,
            rank=None,
            retrieval_terms=retrieval_terms,
            candidate_count=candidate_count,
            failure_class=FailureClass.TARGET_NOT_IN_POOL,
            note="interpreter produced no retrieval terms at all",
        )

    if candidate_count == 0:
        return TaskDiagnosis(
            task_id=task_id,
            rank=None,
            retrieval_terms=retrieval_terms,
            candidate_count=candidate_count,
            failure_class=FailureClass.SLM_TERMS_UNRESOLVABLE_BY_ARCF_DI,
            note="retrieval terms existed but ARCF-DI resolved zero candidates from them",
        )

    if expected_grounding_terms and not _terms_overlap_expected(
        retrieval_terms, expected_grounding_terms
    ):
        return TaskDiagnosis(
            task_id=task_id,
            rank=None,
            retrieval_terms=retrieval_terms,
            candidate_count=candidate_count,
            failure_class=FailureClass.SLM_INTERPRETATION_LIKELY_WRONG,
            note=(
                "HEURISTIC: retrieval terms show no overlap with this task's "
                "expected_grounding_terms — not a certainty, see FailureClass docstring"
            ),
        )

    return TaskDiagnosis(
        task_id=task_id,
        rank=None,
        retrieval_terms=retrieval_terms,
        candidate_count=candidate_count,
        failure_class=FailureClass.OTHER_DETERMINISTIC_LIMITATION,
        note="terms were topically plausible and produced candidates, but not the target file",
    )
