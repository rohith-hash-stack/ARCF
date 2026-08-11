"""ARCF Issue #3 — whole-pipeline root cause analysis, multi-query.

Not a fix. Walks the REAL DRP pipeline stage-by-stage, for many queries
per benchmark repo, and reports the first stage where the target file
becomes measurably disadvantaged relative to the eventual winner — using
only production, unmodified DRP functions (read-only), against the
CURRENT baseline (fixes #1-#13 landed, no qualified-identifier
extraction).

Maps the user's 8 conceptual stages onto DRP's real modules:
    1. Query normalization        -> tfidf.tokenize() on the query
    2. Token extraction           -> tfidf.tokenize() on corpus text (text_corpus.py)
    3. Lexical candidate gen      -> raw TF-IDF dot product, BEFORE confidence dampening
    4. Symbol-unit splitting      -> text_corpus.gather_scoring_units (fix #3/#10)
    5. Subsystem/community routing-> taxonomy.py + query_router's tfidf/community/taxonomy aggregation
    6. Graph-confidence weighting -> tfidf.py's length-/usage-confidence dampening (fix #5/#6/#9/#12)
    7. DRP reranking              -> query_router's weighted combine + near-tie expansion (fix #7)
    8. Final file selection       -> _rank_entry_files + drp_resolver's candidate assembly

The index is built ONCE per repo (the expensive part) and reused across
every query for that repo — scoring a query against an already-built
index is cheap.

`diagnose_query` returns a structured `QueryDiagnosis`, including an
automated `first_losing_stage` + `confidence` + `evidence` classification
(see `_classify` for the exact, stated thresholds — deliberately
conservative and printed alongside the raw numbers so a human can
disagree with the automated call).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from code_intelligence.drp.drp_index import DrpIndex, DrpIndexBuilder
from code_intelligence.drp.query_router import (
    _community_relevance_scores,
    _community_scores_by_subsystem,
    _file_level_scores,
    _normalize,
    _rank_entry_files,
    _subsystem_tfidf_scores,
    _taxonomy_score,
    _top_k_mean,
    route_query,
)
from code_intelligence.drp.text_corpus import gather_file_text
from code_intelligence.drp.tfidf import tokenize
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from infrastructure.cost import CostEstimator
from workspace.permissions import PermissionManager
from workspace.scanner import RepositoryScanner

_ANALYZERS = {"python": PythonLanguageAnalyzer, "go": GoLanguageAnalyzer}


@dataclass
class RepoContext:
    repo: str
    index: CodeIntelligenceIndex
    permissions: PermissionManager
    drp_index: DrpIndex


def build_repo_context(repo: str, language: str, repos_root: Path) -> RepoContext:
    repo_path = repos_root / repo
    analyzer_cls = _ANALYZERS[language]
    engine = CodeIntelligenceEngine(LanguageRegistry([analyzer_cls()]), CostEstimator())
    scan = RepositoryScanner().scan(repo_path)
    index = engine.build_index(repo_path, scan.files)
    permissions = PermissionManager(repo_path)
    drp_index = DrpIndexBuilder.build(index, repo_path)
    return RepoContext(repo=repo, index=index, permissions=permissions, drp_index=drp_index)


@dataclass
class QueryDiagnosis:
    repo: str
    query: str
    target: str
    category: str
    # Stage 1/2
    query_tokens: list[str]
    zero_idf_terms: list[str]
    overlap_terms: list[str]
    missing_terms: list[str]
    overlap_ratio: float
    # Stage 3
    raw_rank: int | None
    raw_total: int
    raw_score: float
    best_raw_file: str
    best_raw_score: float
    # Stage 4
    is_split: bool
    num_units: int
    # Stage 6
    best_unit: str | None
    unit_token_count: int
    unit_usage_count: int
    damped_score: float
    retained_fraction: float | None
    # Stage 5
    target_subsystem: str | None
    winner_subsystem: str
    subsystem_rank: int | None
    subsystem_total: int
    target_combined: float
    winner_combined: float
    tfidf_norm_ratio: float | None
    community_norm_ratio: float | None
    taxonomy_target: float
    taxonomy_winner: float
    # Stage 7
    near_tie_gap_pct: float
    within_near_tie: bool
    # Stage 8
    entry_files_top5: list[str]
    target_entry_rank: int | None
    in_final_candidates: bool
    # Verdict
    first_losing_stage: str = ""
    confidence: str = ""
    evidence: str = ""


def _classify(d: QueryDiagnosis) -> tuple[str, str, str]:
    """Deliberately conservative, stated thresholds — printed alongside
    the raw numbers so a human can independently disagree. Walks stages
    in pipeline order and returns the FIRST one exhibiting a real,
    quantified disadvantage."""
    # Already retrieved — no losing stage.
    if d.in_final_candidates:
        return "none (retrieved)", "n/a", "target reached the final candidate list"

    # Stage 1/2: vocabulary coverage
    if d.overlap_ratio < 0.5:
        conf = "High" if d.overlap_ratio < 0.3 else "Medium"
        return (
            "1/2 (vocabulary coverage)",
            conf,
            f"only {len(d.overlap_terms)}/{len(d.query_tokens)} query terms present in "
            f"target's own vocabulary; missing: {d.missing_terms}",
        )

    # Stage 3: raw lexical candidate generation — not competitive even
    # before any dampening/aggregation. "Competitive" defined as top 5%
    # of all files/units in the repo by raw score.
    raw_percentile = (d.raw_rank / d.raw_total) if (d.raw_rank and d.raw_total) else 1.0
    if raw_percentile > 0.05:
        conf = "High" if raw_percentile > 0.20 else "Medium"
        return (
            "3 (raw lexical rank)",
            conf,
            f"raw rank {d.raw_rank}/{d.raw_total} (top {raw_percentile * 100:.1f}%) despite "
            f"{len(d.overlap_terms)}/{len(d.query_tokens)} vocabulary overlap — vocabulary is "
            f"present but not concentrated/discriminative enough",
        )

    # Stage 6: confidence dampening meaningfully cut the score.
    if d.retained_fraction is not None and d.retained_fraction < 0.9:
        conf = "High" if d.retained_fraction < 0.6 else "Medium"
        return (
            "6 (confidence dampening)",
            conf,
            f"retained fraction {d.retained_fraction:.2f} "
            f"(token_count={d.unit_token_count}, usage_count={d.unit_usage_count})",
        )

    # Stage 5: subsystem/community aggregation gap.
    if d.winner_combined > 0:
        gap = (d.winner_combined - d.target_combined) / d.winner_combined
        if gap > 0.05:
            conf = "High" if gap > 0.20 else "Medium"
            return (
                "5 (subsystem/community aggregation)",
                conf,
                f"target subsystem combined={d.target_combined:.4f} vs winner "
                f"{d.winner_combined:.4f} (gap {gap * 100:.1f}%); rank {d.subsystem_rank}/"
                f"{d.subsystem_total}",
            )

    # Stage 8: entry-file selection within the (winning-ish) subsystem.
    if d.target_entry_rank is not None and d.target_entry_rank > 1:
        return (
            "8 (entry-file selection)",
            "Medium",
            f"target ranks #{d.target_entry_rank} within its own subsystem's entry files "
            f"({d.entry_files_top5})",
        )

    return (
        "unclear (all stages nominally close)",
        "Low",
        "no single stage showed a clear quantified disadvantage by these thresholds, "
        "yet target was not retrieved — needs manual inspection",
    )


def diagnose_query(ctx: RepoContext, query: str, target: str, category: str = "") -> QueryDiagnosis:
    taxonomy = ctx.drp_index.taxonomy
    file_tfidf = ctx.drp_index.file_tfidf
    file_to_units = ctx.drp_index.file_to_units
    subsystem_graph = ctx.drp_index.subsystem_graph
    index = ctx.index

    query_tokens = tokenize(query)
    query_terms = set(query_tokens)
    query_counts: dict[str, int] = {}
    for t in query_tokens:
        query_counts[t] = query_counts.get(t, 0) + 1

    zero_idf_terms = [t for t in query_terms if file_tfidf.idf.get(t) is None]

    target_units = file_to_units.get(target, [])
    is_split = len(target_units) > 1
    target_own_terms: set[str] = set()
    for unit in target_units:
        prof = file_tfidf.profiles.get(unit)
        if prof is not None:
            target_own_terms |= set(prof.weights.keys())
    overlap_terms = sorted(query_terms & target_own_terms)
    missing_terms = sorted(query_terms - target_own_terms)
    overlap_ratio = len(overlap_terms) / len(query_terms) if query_terms else 0.0

    # Stage 3: raw (undamped) scores
    raw_unit_scores: dict[str, float] = {}
    for unit_key, profile in file_tfidf.profiles.items():
        raw_unit_scores[unit_key] = sum(
            count * profile.weights.get(term, 0.0) for term, count in query_counts.items()
        )
    raw_file_scores = _file_level_scores(file_to_units, raw_unit_scores)
    raw_ranking = sorted(raw_file_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    raw_rank = next((i + 1 for i, (f, _) in enumerate(raw_ranking) if f == target), None)
    best_raw_file, best_raw_score = raw_ranking[0] if raw_ranking else ("", 0.0)
    target_raw_score = raw_file_scores.get(target, 0.0)

    # Stage 6: damped scores
    damped_unit_scores = file_tfidf.score(query_tokens)
    best_unit = max(target_units, key=lambda u: raw_unit_scores.get(u, 0.0), default=None)
    unit_token_count = 0
    unit_usage_count = 0
    retained_fraction = None
    damped_score = 0.0
    if best_unit is not None:
        prof = file_tfidf.profiles.get(best_unit)
        if prof is not None:
            unit_token_count = prof.token_count
            unit_usage_count = prof.usage_count
        raw = raw_unit_scores.get(best_unit, 0.0)
        damped_score = damped_unit_scores.get(best_unit, 0.0)
        retained_fraction = (damped_score / raw) if raw > 0 else None

    # Stage 5: subsystem/community/taxonomy aggregation
    file_scores = _file_level_scores(file_to_units, damped_unit_scores)
    tfidf_scores = _subsystem_tfidf_scores(taxonomy, file_scores)
    community_relevance = _community_relevance_scores(subsystem_graph, file_scores)
    community_scores, _top_comm = _community_scores_by_subsystem(
        taxonomy, subsystem_graph, community_relevance
    )
    taxonomy_scores = {
        path: _taxonomy_score(path, node.package_namespaces, query_terms)
        for path, node in taxonomy.nodes.items()
    }
    norm_tfidf = _normalize(tfidf_scores)
    norm_community = _normalize(community_scores)
    combined = {
        path: 0.55 * norm_tfidf.get(path, 0.0)
        + 0.30 * norm_community.get(path, 0.0)
        + 0.15 * taxonomy_scores.get(path, 0.0)
        for path in taxonomy.nodes
    }
    ranked_subsystems = sorted(combined.items(), key=lambda kv: (-kv[1], kv[0]))
    target_subsystem = next(
        (path for path, node in taxonomy.nodes.items() if target in node.files), None
    )
    winner_subsystem, winner_combined = ranked_subsystems[0] if ranked_subsystems else ("", 0.0)
    subsystem_rank = next(
        (i + 1 for i, (p, _) in enumerate(ranked_subsystems) if p == target_subsystem), None
    )
    target_combined = combined.get(target_subsystem, 0.0) if target_subsystem else 0.0
    tfidf_norm_ratio = (
        norm_tfidf.get(target_subsystem, 0.0) / norm_tfidf.get(winner_subsystem, 1.0)
        if target_subsystem and norm_tfidf.get(winner_subsystem, 0.0) > 0
        else None
    )
    community_norm_ratio = (
        norm_community.get(target_subsystem, 0.0) / norm_community.get(winner_subsystem, 1.0)
        if target_subsystem and norm_community.get(winner_subsystem, 0.0) > 0
        else None
    )

    # Stage 7: near-tie margin
    near_tie_threshold = winner_combined * 0.97
    within_near_tie = target_combined >= near_tie_threshold
    gap_pct = (
        (winner_combined - target_combined) / winner_combined * 100 if winner_combined else 0.0
    )

    # Stage 8: entry-file ranking + final candidates
    target_files_in_subsystem = (
        taxonomy.files_in(target_subsystem) if target_subsystem else []
    )
    entry_files = _rank_entry_files(target_files_in_subsystem, file_scores, subsystem_graph)
    target_entry_rank = entry_files.index(target) + 1 if target in entry_files else None

    routing = route_query(query, taxonomy, file_tfidf, file_to_units, subsystem_graph, index)
    candidate_files = (
        list(routing.entry_files)
        + list(routing.expansion.keys())
        + [f for files in routing.near_tied_entry_files.values() for f in files]
    )
    in_final_candidates = target in candidate_files

    d = QueryDiagnosis(
        repo=ctx.repo,
        query=query,
        target=target,
        category=category,
        query_tokens=query_tokens,
        zero_idf_terms=zero_idf_terms,
        overlap_terms=overlap_terms,
        missing_terms=missing_terms,
        overlap_ratio=overlap_ratio,
        raw_rank=raw_rank,
        raw_total=len(raw_ranking),
        raw_score=target_raw_score,
        best_raw_file=best_raw_file,
        best_raw_score=best_raw_score,
        is_split=is_split,
        num_units=len(target_units),
        best_unit=best_unit,
        unit_token_count=unit_token_count,
        unit_usage_count=unit_usage_count,
        damped_score=damped_score,
        retained_fraction=retained_fraction,
        target_subsystem=target_subsystem,
        winner_subsystem=winner_subsystem,
        subsystem_rank=subsystem_rank,
        subsystem_total=len(ranked_subsystems),
        target_combined=target_combined,
        winner_combined=winner_combined,
        tfidf_norm_ratio=tfidf_norm_ratio,
        community_norm_ratio=community_norm_ratio,
        taxonomy_target=taxonomy_scores.get(target_subsystem, 0.0) if target_subsystem else 0.0,
        taxonomy_winner=taxonomy_scores.get(winner_subsystem, 0.0),
        near_tie_gap_pct=gap_pct,
        within_near_tie=within_near_tie,
        entry_files_top5=entry_files[:5],
        target_entry_rank=target_entry_rank,
        in_final_candidates=in_final_candidates,
    )
    stage, conf, evidence = _classify(d)
    d.first_losing_stage = stage
    d.confidence = conf
    d.evidence = evidence
    return d


def print_diagnosis(d: QueryDiagnosis) -> None:
    print(f"\n{'-' * 78}")
    print(f"[{d.repo}] ({d.category}) {d.query}")
    print(f"target: {d.target}")
    print(
        f"  vocab overlap: {len(d.overlap_terms)}/{len(d.query_tokens)} "
        f"({d.overlap_ratio * 100:.0f}%)  missing={d.missing_terms}"
    )
    print(f"  raw lexical rank: {d.raw_rank}/{d.raw_total}  score={d.raw_score:.4f}")
    print(
        f"  split={d.is_split} ({d.num_units} units)  "
        f"retained_fraction={d.retained_fraction}"
    )
    print(
        f"  subsystem: target={d.target_subsystem!r} rank {d.subsystem_rank}/{d.subsystem_total}  "
        f"winner={d.winner_subsystem!r}  gap={d.near_tie_gap_pct:.1f}%"
    )
    print(
        f"  entry-file rank in own subsystem: {d.target_entry_rank}  "
        f"in_final_candidates={d.in_final_candidates}"
    )
    print(f"  >>> FIRST LOSING STAGE: {d.first_losing_stage}  [{d.confidence}]")
    print(f"      {d.evidence}")


if __name__ == "__main__":
    import sys

    print("This module is a library — see run_multi_query_diagnosis.py for the driver.")
    sys.exit(0)
