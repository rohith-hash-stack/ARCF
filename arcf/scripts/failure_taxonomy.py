"""failure_taxonomy.py -- checklist item #14 (arcf/CHECKLIST.md, Failure
Taxonomy), harness-only, zero `src/` changes.

Classifies WHY a real ground-truth file failed to make it into a
packaged result, given the same real pipeline objects item #4's
grounding harness and item #13's TelemetryCollector already produce
(`ContextResolutionResult`, `list[RankedFile]`, the final packaged
file-path list) -- no new production instrumentation, no new
TelemetryEvent fields.

Grounded directly in the real `ContextBudgetManager.select()` mechanism
(`src/context/budget_manager.py`), read before writing this, not
assumed:

1. Relative score falloff gate (`_RELATIVE_FALLOFF_GAMMA`, imported not
   duplicated): a candidate scoring below 45% of the top candidate's
   score is cut before the "does it fit" question is ever asked --
   independent of size or budget.
2. Task-type budget tiering (`_BUDGET_TIER_BY_TASK_TYPE`, imported not
   duplicated): the EFFECTIVE ceiling a file competes against is often
   far tighter than the caller's nominal `max_tokens` (e.g. UNKNOWN/
   BUG_FIX = 4500, not 8000).
3. Greedy fill order: a file that clears both of the above can still be
   excluded because higher-ranked candidates already consumed the
   budget before its turn -- distinct from the file's own size being
   the problem.

Each of the 5 `FailureCategory` values maps to one real, observable
branch of that mechanism -- not a guess. `ambiguity_confidence` (Feature
A, `< 1.0` iff the resolved target had >1 same-named competing match)
and `origin_stage == SCOPED_GRAPH_EXPANSION` (item #10) are read
straight off the already-computed `RankedFile`/`FileReference`, not
re-derived.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from context.budget_manager import _BUDGET_TIER_BY_TASK_TYPE, _DEFAULT_BUDGET_TIER, _RELATIVE_FALLOFF_GAMMA
from context.relevance_ranker import RankedFile
from context.task_profile import RetrievalTaskType
from domain.context_resolution import ContextResolutionResult, OriginStage


class FailureCategory(StrEnum):
    OVERSIZED_FILE_EXCLUDED = "oversized_file_excluded"
    """Ground-truth file's own token_count exceeds the EFFECTIVE budget
    ceiling (after task-type tiering) on its own -- it could not have
    fit even ranked first."""
    AMBIGUITY_DECAY_DROPPED = "ambiguity_decay_dropped"
    """Ground-truth file's relevance_score was suppressed by Feature A's
    ambiguity_confidence multiplier (its resolved target name had >1
    same-named competing match repo-wide), dropping it below the
    relative falloff gate or far enough down rank order to lose the
    budget race to smaller, less-relevant files."""
    PROBABILISTIC_EDGE_DISCARD = "probabilistic_edge_discard"
    """Ground-truth file was reached via real call-graph expansion
    (OriginStage.SCOPED_GRAPH_EXPANSION) but its hop/reason-verb-weighted
    score fell below the relative falloff gate -- the edge was real, but
    its weight decayed it out before packaging."""
    ZERO_CANDIDATE_EXTRACTION = "zero_candidate_extraction"
    """Ground-truth file never appeared in candidate_files at all -- no
    real candidate was ever produced for it, whether because upstream
    entity extraction never named the right target, or (observably
    identical from harness-level data) disambiguation resolved an
    ambiguous target name to a different same-named symbol entirely.
    When `ambiguous_targets` is non-empty, that's real corroborating
    evidence for the latter, surfaced as a secondary tag rather than
    silently assumed."""
    CONTEXT_BUDGET_OVERFLOW = "context_budget_overflow"
    """Ground-truth file cleared both the falloff gate and its own size
    ceiling, but lower-ranked candidates still filled the budget before
    its turn in the greedy fill order -- a crowding failure, not a
    size or ambiguity failure of the file itself."""


@dataclass(frozen=True)
class FailureDiagnosis:
    file_path: str
    primary: FailureCategory
    secondary: FailureCategory | None
    detail: str


def _effective_max_tokens(caller_max_tokens: int, task_type: RetrievalTaskType | None) -> int:
    """Byte-identical to ContextBudgetManager.select()'s own tiering --
    imported constants, not a duplicated table that could drift."""
    if task_type is None:
        return caller_max_tokens
    return min(caller_max_tokens, _BUDGET_TIER_BY_TASK_TYPE.get(task_type, _DEFAULT_BUDGET_TIER))


def classify_grounding_failure(
    file_path: str,
    result: ContextResolutionResult,
    ranked_files: list[RankedFile],
    packaged_files: list[str],
    caller_max_tokens: int,
    task_type: RetrievalTaskType | None = None,
) -> FailureDiagnosis | None:
    """Returns None if file_path is actually present in packaged_files
    (no failure to classify). Deterministic, pure function of already-
    computed pipeline objects -- no LLM calls, no randomness."""
    if file_path in packaged_files:
        return None

    effective_max_tokens = _effective_max_tokens(caller_max_tokens, task_type)
    candidate = next((f for f in result.candidate_files if f.file_path == file_path), None)

    if candidate is None:
        secondary = FailureCategory.AMBIGUITY_DECAY_DROPPED if result.ambiguous_targets else None
        return FailureDiagnosis(
            file_path, FailureCategory.ZERO_CANDIDATE_EXTRACTION, secondary,
            detail=(
                f"never appeared in candidate_files (candidate_count={len(result.candidate_files)}, "
                f"ambiguous_targets={result.ambiguous_targets!r})"
            ),
        )

    ranked = next((r for r in ranked_files if r.file_path == file_path), None)
    if ranked is None:
        # Every real candidate is ranked by RelevanceRanker.rank() -- this
        # branch means the caller passed mismatched result/ranked_files,
        # not a real pipeline state. Reported honestly rather than guessed.
        return FailureDiagnosis(
            file_path, FailureCategory.CONTEXT_BUDGET_OVERFLOW, None,
            detail="present in candidate_files but absent from ranked_files -- mismatched inputs",
        )

    top_score = ranked_files[0].relevance_score if ranked_files else 0.0
    falloff_threshold = round(_RELATIVE_FALLOFF_GAMMA * top_score, 4)
    is_ambiguity_decayed = ranked.ambiguity_confidence is not None and ranked.ambiguity_confidence < 1.0
    is_graph_expanded = candidate.origin_stage == OriginStage.SCOPED_GRAPH_EXPANSION

    if ranked.relevance_score < falloff_threshold:
        detail = (
            f"cut by the relative score falloff gate: score={ranked.relevance_score} < "
            f"threshold={falloff_threshold} (top_score={top_score}); "
            f"ambiguity_confidence={ranked.ambiguity_confidence}, origin_stage={candidate.origin_stage}"
        )
        if is_ambiguity_decayed:
            secondary = FailureCategory.PROBABILISTIC_EDGE_DISCARD if is_graph_expanded else None
            return FailureDiagnosis(file_path, FailureCategory.AMBIGUITY_DECAY_DROPPED, secondary, detail)
        if is_graph_expanded:
            return FailureDiagnosis(file_path, FailureCategory.PROBABILISTIC_EDGE_DISCARD, None, detail)
        return FailureDiagnosis(file_path, FailureCategory.CONTEXT_BUDGET_OVERFLOW, None, detail)

    if ranked.token_count > effective_max_tokens:
        secondary = FailureCategory.AMBIGUITY_DECAY_DROPPED if is_ambiguity_decayed else None
        detail = (
            f"token_count={ranked.token_count} exceeds the effective budget ceiling "
            f"{effective_max_tokens} (task_type={task_type}) on its own, independent of rank position"
        )
        return FailureDiagnosis(file_path, FailureCategory.OVERSIZED_FILE_EXCLUDED, secondary, detail)

    secondary = FailureCategory.AMBIGUITY_DECAY_DROPPED if is_ambiguity_decayed else None
    detail = (
        f"fits within the {effective_max_tokens}-token ceiling alone and cleared the falloff gate "
        f"(score={ranked.relevance_score} >= threshold={falloff_threshold}), but lower-ranked "
        f"candidates filled the budget before its turn"
    )
    return FailureDiagnosis(file_path, FailureCategory.CONTEXT_BUDGET_OVERFLOW, secondary, detail)


def aggregate_failure_distribution(diagnoses: list[FailureDiagnosis]) -> dict:
    """Diagnostic Aggregation Report: primary-category distribution
    across a batch of real diagnoses -- e.g. a full benchmark run's
    worth of missing ground-truth files."""
    total = len(diagnoses)
    if total == 0:
        return {"total_failures": 0, "by_primary_category": {}}
    counts: dict[str, int] = {}
    for d in diagnoses:
        counts[d.primary.value] = counts.get(d.primary.value, 0) + 1
    return {
        "total_failures": total,
        "by_primary_category": {
            category: {"count": count, "pct": round(100 * count / total, 1)}
            for category, count in sorted(counts.items(), key=lambda kv: -kv[1])
        },
    }
