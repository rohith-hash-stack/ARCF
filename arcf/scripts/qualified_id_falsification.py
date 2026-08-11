"""ARCF Issue #3 — falsification experiment for qualified-identifier
indexing.

Tests exactly one hypothesis: does adding a low-weight, PROJECT-LOCAL
qualified-identifier field (`qualifier.member` pairs resolvable through
this file's own imports — never stdlib/third-party) to each file's
scoring text improve target-file retrieval, without meaningfully
regressing other repositories?

Deliberately isolated:
- Reads `code_intelligence.drp.{text_corpus,tfidf,query_router}` and
  `DrpIndexBuilder` but calls every function READ-ONLY — nothing in
  `arcf/src/code_intelligence/drp/` is modified by this script. The
  BASELINE index is the real, unmodified production `DrpIndexBuilder.
  build()` output.
- The EXPERIMENTAL index reuses the exact same `unit_usage` (so length-/
  usage-confidence dampening, subsystem routing, community detection,
  and confidence propagation are all held constant) and only appends one
  additional text field to each unit's TF-IDF document, built via the
  already-public `tfidf.build_tfidf_index` — never a private code path.
- No Behavioral Semantic Index, co-invocation signatures, exception
  propagation, or local block analysis — this experiment measures ONE
  variable: does this one field help or hurt.

"Local" is determined structurally, via `ImportReference.
resolved_file_path` (set by the LanguageAnalyzer itself when an import
resolves to a real file within the scanned workspace) — never a
stdlib/third-party name list. This required first fixing a real,
pre-existing bug in `go_analyzer.py`'s import resolution (it never
stripped a Go module's own declared prefix before matching
workspace-relative paths, so 0/5931 Traefik imports ever resolved) —
see that module's own docstring for the fix; this script depends on it
being correct, not on any workaround here.

The field is deliberately "low-weight": each unique `qualifier.member`
pair contributes ONCE to a unit's text regardless of how many times it
appears in the file's body, bounding how much raw term-frequency it can
contribute relative to the existing comment/symbol-name text.

Usage:
    uv run python scripts/qualified_id_falsification.py [--repo NAME]
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from code_intelligence.drp.drp_index import DrpIndex, DrpIndexBuilder
from code_intelligence.drp.query_router import DrpRouting, _file_level_scores, route_query
from code_intelligence.drp.text_corpus import gather_scoring_units
from code_intelligence.drp.tfidf import SubsystemTfIdfIndex, build_tfidf_index, tokenize
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from domain.code_intelligence import FileAnalysis
from infrastructure.cost import CostEstimator
from shared.errors import WorkspacePathError
from workspace.permissions import PermissionManager
from workspace.scanner import RepositoryScanner

_ANALYZERS = {"python": PythonLanguageAnalyzer, "go": GoLanguageAnalyzer}
RESULTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "drp_benchmark_data"

# Matches a qualified reference (`qualifier.member`) anywhere in a
# file's raw body text — filtered down to project-local qualifiers by
# the caller, never used unfiltered.
_QUALIFIED_REF_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b")
# Splits a raw import module string on whichever separator its language
# uses (Go: "/", Python: ".") to derive the default bound name for an
# unaliased import.
_MODULE_SEGMENT_RE = re.compile(r"[/.]")
_MAX_SCAN_CHARS = 300_000

# Reporting-only heuristic (never a filter/gate on this experiment's own
# scoring — the whole point is to measure, honestly, whether noisy files
# rise in rank with this signal on) for labeling which top-ranked files
# are test/example/benchmark code.
_NON_PRODUCTION_PATH_SEGMENTS = frozenset(
    {"test", "tests", "testdata", "examples", "example", "benchmark", "benchmarks"}
)
_TEST_STEM_SUFFIX_RE = re.compile(r"(?:^|[_.])tests?$", re.IGNORECASE)
_TEST_STEM_CAMEL_RE = re.compile(r"[a-z0-9]Tests?$")


def _is_noisy_path(file_path: str) -> bool:
    parts = Path(file_path).parts
    if any(part.lower() in _NON_PRODUCTION_PATH_SEGMENTS for part in parts[:-1]):
        return True
    stem = Path(file_path).stem
    lowered = stem.lower()
    return bool(
        lowered.startswith("test_")
        or _TEST_STEM_SUFFIX_RE.search(stem)
        or _TEST_STEM_CAMEL_RE.search(stem)
        or lowered.endswith(".test")
        or lowered.endswith(".spec")
    )


def _local_qualifiers_for_file(analysis: FileAnalysis) -> set[str]:
    """Every name this file's own imports bind that resolves to a real
    workspace file — see `ImportReference.resolved_file_path`'s own
    docstring. Stdlib/third-party imports never resolve, so they never
    contribute a qualifier here; no name list of any kind is consulted."""
    qualifiers: set[str] = set()
    for imp in analysis.imports:
        if imp.resolved_file_path is None:
            continue
        if imp.imported_names:
            qualifiers.update(name for name in imp.imported_names if name and name != "*")
        elif imp.raw_module:
            parts = [p for p in _MODULE_SEGMENT_RE.split(imp.raw_module) if p]
            if parts:
                qualifiers.add(parts[-1])
    return qualifiers


def _extract_local_qualified_refs(content: str, local_qualifiers: set[str]) -> str:
    """Deduplicated (each unique pair counted once, not per-occurrence)
    text of every `qualifier.member` reference whose qualifier resolves
    locally — see module docstring for why deduplication is the
    "low-weight" mechanism."""
    if not local_qualifiers:
        return ""
    content = content[:_MAX_SCAN_CHARS]
    seen: set[str] = set()
    pairs: list[str] = []
    for qualifier, member in _QUALIFIED_REF_RE.findall(content):
        if qualifier not in local_qualifiers:
            continue
        pair = f"{qualifier}.{member}"
        if pair not in seen:
            seen.add(pair)
            pairs.append(pair)
    return "\n".join(pairs)


def _build_local_qualified_texts(
    index: CodeIntelligenceIndex, permissions: PermissionManager
) -> dict[str, str]:
    """One text blob per FILE (not per scoring unit) — the experimental
    field is inherently whole-file-body based, not symbol-scoped, so it
    stays independent of fix #10's per-method splitting (isolating
    exactly the one variable this experiment tests)."""
    texts: dict[str, str] = {}
    for file_path, analysis in index.file_analyses.items():
        local_qualifiers = _local_qualifiers_for_file(analysis)
        try:
            content = permissions.safe_read_text(file_path)
        except (OSError, WorkspacePathError):
            content = ""
        texts[file_path] = (
            _extract_local_qualified_refs(content, local_qualifiers) if content else ""
        )
    return texts


def _rank_of(target: str, ranking: list[tuple[str, float]]) -> int | None:
    return next((i + 1 for i, (f, _) in enumerate(ranking) if f == target), None)


def _terms_for_text(text: str) -> list[str]:
    return tokenize(text)


@dataclass
class RepoResult:
    repo: str
    query: str
    target: str
    baseline_rank: int | None
    experimental_rank: int | None
    baseline_top10: list[tuple[str, float]]
    experimental_top10: list[tuple[str, float]]
    baseline_score: float
    experimental_score: float
    baseline_margin: float
    """baseline_score minus the best-scoring non-target file's score."""
    experimental_margin: float
    target_experimental_terms: list[str]
    target_term_idfs: dict[str, float]
    neighbor_overlap: list[tuple[str, int, bool]]
    """(file, overlap token count with target's own experimental terms,
    is_noisy) for the experimental top 10, excluding the target."""
    noisy_newly_in_top10: list[tuple[str, int, float]]
    """(file, rank, score) for files matching `_is_noisy_path` that are
    in the experimental top 10 but were NOT in the baseline top 10."""
    baseline_winning_subsystem: str
    experimental_winning_subsystem: str
    baseline_candidates: list[str]
    """The real, final candidate-file list `DrpResolver` would produce —
    entry_files + graph expansion + near-tied entry files — from calling
    the actual, unmodified `route_query` (Stage 4). This is the
    "despite graph-locality weighting" comparison: subsystem/community/
    taxonomy aggregation is fully applied, unmodified, for both
    conditions."""
    experimental_candidates: list[str]
    baseline_target_in_candidates: bool
    experimental_target_in_candidates: bool
    noisy_newly_in_candidates: list[str]
    """Files matching `_is_noisy_path` present in `experimental_
    candidates` but absent from `baseline_candidates` — noisy files that
    graph-locality/community/taxonomy weighting did NOT keep out once
    this signal was added."""


def _score_and_rank(
    tfidf_index: SubsystemTfIdfIndex,
    file_to_units: dict[str, list[str]],
    query_tokens: list[str],
    top_n: int = 10,
) -> tuple[dict[str, float], list[tuple[str, float]]]:
    unit_scores = tfidf_index.score(query_tokens)
    file_scores = _file_level_scores(file_to_units, unit_scores)
    ranking = sorted(file_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return file_scores, ranking[:top_n]


def run_experiment(repo_path: Path, language: str, query: str, target: str) -> RepoResult:
    analyzer_cls = _ANALYZERS[language]
    engine = CodeIntelligenceEngine(LanguageRegistry([analyzer_cls()]), CostEstimator())
    scan = RepositoryScanner().scan(repo_path)
    index = engine.build_index(repo_path, scan.files)
    permissions = PermissionManager(repo_path)

    # Baseline: the real, unmodified production index — taxonomy,
    # subsystem_graph, file_to_units, and file_tfidf all exactly as
    # DrpResolver would build them.
    baseline_drp_index = DrpIndexBuilder.build(index, repo_path)
    file_to_units = baseline_drp_index.file_to_units
    baseline_tfidf = baseline_drp_index.file_tfidf

    # Experimental: baseline text + this file's local-qualified-ref text
    # appended to every one of its own scoring units, same unit_usage
    # (usage-confidence dampening unchanged) — only the TEXT changes.
    # Reuses the exact unit_texts baseline_tfidf was already built from
    # by re-deriving them from gather_scoring_units a second time (cheap,
    # deterministic, no caching complexity) rather than threading extra
    # state through DrpIndexBuilder.build.
    unit_texts, _file_to_units_again, unit_usage = gather_scoring_units(index, permissions)
    local_texts = _build_local_qualified_texts(index, permissions)
    experimental_unit_texts = dict(unit_texts)
    for file_path, units in file_to_units.items():
        extra = local_texts.get(file_path, "")
        if not extra:
            continue
        for unit_key in units:
            experimental_unit_texts[unit_key] = (
                experimental_unit_texts.get(unit_key, "") + "\n" + extra
            )
    experimental_tfidf = build_tfidf_index(experimental_unit_texts, unit_usage)

    # Same taxonomy/subsystem_graph/file_to_units as baseline (those
    # depend on file STRUCTURE and the import graph, never on file_tfidf
    # text) — only file_tfidf differs, so route_query (Stage 4, called
    # completely unmodified below) is the exact real subsystem/community/
    # taxonomy aggregation logic in both conditions.
    experimental_drp_index = DrpIndex(
        taxonomy=baseline_drp_index.taxonomy,
        file_tfidf=experimental_tfidf,
        file_to_units=file_to_units,
        subsystem_graph=baseline_drp_index.subsystem_graph,
    )

    query_tokens = tokenize(query)
    baseline_scores, baseline_top10 = _score_and_rank(baseline_tfidf, file_to_units, query_tokens)
    experimental_scores, experimental_top10 = _score_and_rank(
        experimental_tfidf, file_to_units, query_tokens
    )

    baseline_ranking_full = sorted(baseline_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    experimental_ranking_full = sorted(
        experimental_scores.items(), key=lambda kv: (-kv[1], kv[0])
    )
    baseline_rank = _rank_of(target, baseline_ranking_full)
    experimental_rank = _rank_of(target, experimental_ranking_full)

    baseline_score = baseline_scores.get(target, 0.0)
    experimental_score = experimental_scores.get(target, 0.0)

    def _margin(scores: dict[str, float], own_score: float) -> float:
        best_other = max((s for f, s in scores.items() if f != target), default=0.0)
        return own_score - best_other

    baseline_margin = _margin(baseline_scores, baseline_score)
    experimental_margin = _margin(experimental_scores, experimental_score)

    target_experimental_text = local_texts.get(target, "")
    target_experimental_terms = sorted(set(_terms_for_text(target_experimental_text)))
    target_term_idfs = {
        term: round(experimental_tfidf.idf.get(term, 0.0), 4) for term in target_experimental_terms
    }

    target_term_set = set(target_experimental_terms)
    neighbor_overlap: list[tuple[str, int, bool]] = []
    for file_path, _score in experimental_top10:
        if file_path == target:
            continue
        neighbor_terms = set(_terms_for_text(local_texts.get(file_path, "")))
        overlap = len(target_term_set & neighbor_terms)
        neighbor_overlap.append((file_path, overlap, _is_noisy_path(file_path)))

    baseline_top10_files = {f for f, _ in baseline_top10}
    noisy_newly_in_top10 = [
        (f, i + 1, s)
        for i, (f, s) in enumerate(experimental_top10)
        if _is_noisy_path(f) and f not in baseline_top10_files
    ]

    # The real, unmodified Stage 4 routing — subsystem/community/
    # taxonomy aggregation exactly as production DrpResolver runs it,
    # for both conditions. Answers "despite graph-locality weighting."
    baseline_routing = route_query(
        query,
        baseline_drp_index.taxonomy,
        baseline_drp_index.file_tfidf,
        baseline_drp_index.file_to_units,
        baseline_drp_index.subsystem_graph,
        index,
    )
    experimental_routing = route_query(
        query,
        experimental_drp_index.taxonomy,
        experimental_drp_index.file_tfidf,
        experimental_drp_index.file_to_units,
        experimental_drp_index.subsystem_graph,
        index,
    )

    def _candidate_files(routing: DrpRouting) -> list[str]:
        files = list(routing.entry_files) + sorted(routing.expansion.keys())
        for near_tied_files in routing.near_tied_entry_files.values():
            files.extend(near_tied_files)
        seen: set[str] = set()
        ordered: list[str] = []
        for f in files:
            if f not in seen:
                seen.add(f)
                ordered.append(f)
        return ordered

    baseline_candidates = _candidate_files(baseline_routing)
    experimental_candidates = _candidate_files(experimental_routing)
    baseline_candidate_set = set(baseline_candidates)
    noisy_newly_in_candidates = [
        f
        for f in experimental_candidates
        if _is_noisy_path(f) and f not in baseline_candidate_set
    ]

    return RepoResult(
        repo=repo_path.name,
        query=query,
        target=target,
        baseline_rank=baseline_rank,
        experimental_rank=experimental_rank,
        baseline_top10=baseline_top10,
        experimental_top10=experimental_top10,
        baseline_score=baseline_score,
        experimental_score=experimental_score,
        baseline_margin=baseline_margin,
        experimental_margin=experimental_margin,
        target_experimental_terms=target_experimental_terms,
        target_term_idfs=target_term_idfs,
        neighbor_overlap=neighbor_overlap,
        noisy_newly_in_top10=noisy_newly_in_top10,
        baseline_winning_subsystem=baseline_routing.winning_subsystem,
        experimental_winning_subsystem=experimental_routing.winning_subsystem,
        baseline_candidates=baseline_candidates,
        experimental_candidates=experimental_candidates,
        baseline_target_in_candidates=target in baseline_candidate_set,
        experimental_target_in_candidates=target in set(experimental_candidates),
        noisy_newly_in_candidates=noisy_newly_in_candidates,
    )


_CASES = {
    "traefik": (
        "go",
        "Explain how dynamic configuration updates propagate without restarting the server.",
        "pkg/server/configurationwatcher.go",
    ),
    "consul": (
        "go",
        "How does Consul add a new service instance to the catalog when an agent registers it?",
        "agent/consul/catalog_endpoint.go",
    ),
    "sqlalchemy": (
        "python",
        "How does SQLAlchemy decide whether to load a relationship immediately or wait "
        "until it's accessed?",
        "lib/sqlalchemy/orm/strategies.py",
    ),
    "django": (
        "python",
        "How does Django avoid hitting the database again when the same queryset is "
        "evaluated more than once?",
        "django/db/models/query.py",
    ),
    "vllm": (
        "python",
        "How does vLLM decide which request to pause when it runs out of memory for "
        "the KV cache during batching?",
        "vllm/v1/core/sched/scheduler.py",
    ),
}


def _print_report(result: RepoResult) -> None:
    print(f"\n{'=' * 70}\n{result.repo}\n{'=' * 70}")
    print(f"query:  {result.query}")
    print(f"target: {result.target}")
    print(f"--- pure lexical (file-level TF-IDF, no routing) ---")
    print(
        f"rank:   baseline={result.baseline_rank}  experimental={result.experimental_rank}"
        f"  (delta={_rank_delta(result)})"
    )
    print(
        f"score:  baseline={result.baseline_score:.4f}  experimental={result.experimental_score:.4f}"
    )
    print(
        f"margin (target - best competitor): baseline={result.baseline_margin:+.4f}"
        f"  experimental={result.experimental_margin:+.4f}"
        f"  ({'WIDENED' if result.experimental_margin > result.baseline_margin else 'NARROWED'})"
    )
    print(f"target's own experimental terms ({len(result.target_experimental_terms)}):")
    for term in result.target_experimental_terms[:15]:
        print(f"    {term:20s} idf={result.target_term_idfs.get(term, 0.0)}")
    if len(result.target_experimental_terms) > 15:
        print(f"    ... and {len(result.target_experimental_terms) - 15} more")

    print(f"\ntop 10 (experimental):")
    for i, (f, s) in enumerate(result.experimental_top10):
        marker = " <-- TARGET" if f == result.target else ""
        noisy = " [NOISY]" if _is_noisy_path(f) else ""
        print(f"  {i + 1:2d}. {s:.4f}  {f}{noisy}{marker}")

    overlapping = [n for n in result.neighbor_overlap if n[1] > 0]
    print(f"\nneighbors sharing >=1 experimental term with target: {len(overlapping)}/9")
    for f, overlap, noisy in sorted(result.neighbor_overlap, key=lambda t: -t[1])[:5]:
        print(f"    overlap={overlap:3d}  noisy={noisy!s:5s}  {f}")

    if result.noisy_newly_in_top10:
        print(f"\nWARNING: noisy files newly entering top 10 (weren't there in baseline):")
        for f, rank, score in result.noisy_newly_in_top10:
            print(f"    rank={rank:2d}  score={score:.4f}  {f}")
    else:
        print(f"\nNo noisy files newly entered the top 10.")

    print(f"\n--- full routing (Stage 4, unmodified — subsystem/community/taxonomy) ---")
    print(f"winning subsystem: baseline={result.baseline_winning_subsystem!r}")
    print(f"                   experimental={result.experimental_winning_subsystem!r}")
    print(
        f"target in final candidates: baseline={result.baseline_target_in_candidates}"
        f"  experimental={result.experimental_target_in_candidates}"
    )
    if result.noisy_newly_in_candidates:
        print(
            f"WARNING: noisy files newly entering the routed candidate list "
            f"despite graph-locality/community/taxonomy weighting:"
        )
        for f in result.noisy_newly_in_candidates:
            print(f"    {f}")
    else:
        print(f"No noisy files newly entered the routed candidate list.")


def _rank_delta(result: RepoResult) -> str:
    if result.baseline_rank is None or result.experimental_rank is None:
        return "n/a"
    return f"{result.baseline_rank - result.experimental_rank:+d}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", choices=sorted(_CASES.keys()), default=None)
    parser.add_argument(
        "--repos-root",
        default=str(Path(__file__).resolve().parent.parent.parent / ".benchmark_repos"),
    )
    args = parser.parse_args()

    repos_root = Path(args.repos_root)
    cases = {args.repo: _CASES[args.repo]} if args.repo else _CASES

    results: list[RepoResult] = []
    for repo_name, (language, query, target) in cases.items():
        repo_path = repos_root / repo_name
        result = run_experiment(repo_path, language, query, target)
        results.append(result)
        _print_report(result)

    print(f"\n{'=' * 70}\nSUMMARY\n{'=' * 70}")
    baseline_reciprocals = [1.0 / r.baseline_rank if r.baseline_rank else 0.0 for r in results]
    experimental_reciprocals = [
        1.0 / r.experimental_rank if r.experimental_rank else 0.0 for r in results
    ]
    baseline_mrr = sum(baseline_reciprocals) / len(results) if results else 0.0
    experimental_mrr = sum(experimental_reciprocals) / len(results) if results else 0.0
    print(f"MRR (pure lexical): baseline={baseline_mrr:.4f}  experimental={experimental_mrr:.4f}")
    for r in results:
        subsystem_changed = r.baseline_winning_subsystem != r.experimental_winning_subsystem
        print(
            f"  {r.repo:12s} lex_rank {r.baseline_rank!s:>5s} -> {r.experimental_rank!s:>5s}"
            f"   subsystem_changed={subsystem_changed}"
            f"   in_candidates {r.baseline_target_in_candidates!s:>5s} ->"
            f" {r.experimental_target_in_candidates!s:>5s}"
            f"   noisy_newly_in_top10={len(r.noisy_newly_in_top10)}"
            f"   noisy_newly_in_candidates={len(r.noisy_newly_in_candidates)}"
        )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "qualified_id_falsification.json"
    out_path.write_text(
        json.dumps(
            [
                {
                    "repo": r.repo,
                    "query": r.query,
                    "target": r.target,
                    "baseline_rank": r.baseline_rank,
                    "experimental_rank": r.experimental_rank,
                    "baseline_score": r.baseline_score,
                    "experimental_score": r.experimental_score,
                    "baseline_margin": r.baseline_margin,
                    "experimental_margin": r.experimental_margin,
                    "baseline_top10": r.baseline_top10,
                    "experimental_top10": r.experimental_top10,
                    "target_experimental_terms": r.target_experimental_terms,
                    "target_term_idfs": r.target_term_idfs,
                    "neighbor_overlap": r.neighbor_overlap,
                    "noisy_newly_in_top10": r.noisy_newly_in_top10,
                    "baseline_winning_subsystem": r.baseline_winning_subsystem,
                    "experimental_winning_subsystem": r.experimental_winning_subsystem,
                    "baseline_candidates": r.baseline_candidates,
                    "experimental_candidates": r.experimental_candidates,
                    "baseline_target_in_candidates": r.baseline_target_in_candidates,
                    "experimental_target_in_candidates": r.experimental_target_in_candidates,
                    "noisy_newly_in_candidates": r.noisy_newly_in_candidates,
                }
                for r in results
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
