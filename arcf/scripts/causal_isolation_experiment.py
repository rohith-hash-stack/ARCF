"""ARCF Issue #3 — causal isolation experiment for dampening vs.
aggregation vs. lexical score.

Not a proposal. For every file the multi-query study classified as a
"dampening failure," computes ranking under four controlled conditions
to determine which component is actually causal, as opposed to merely
correlated with the failure:

    A. Baseline               — real, unmodified production pipeline
    B. Dampening disabled     — usage-/length-confidence neutralized,
                                 subsystem aggregation & routing untouched
    C. Aggregation disabled   — confidence dampening untouched, but
                                 ranking is the FLAT per-file score
                                 (no subsystem/community/taxonomy pooling)
    D. Both disabled          — flat ranking on undamped scores

Isolation: no production code is modified. "Dampening disabled" is
implemented by constructing a NEW `SubsystemTfIdfIndex` whose
`TfIdfProfile`s have `token_count`/`usage_count` overridden high enough
to force `tfidf.py`'s own, completely unmodified `.score()` confidence
multipliers to 1.0 — the real scoring formula runs unchanged, only its
two confidence INPUTS are neutralized before construction. "Aggregation
disabled" never calls `query_router.route_query` at all — it ranks
files directly by their own (real, unmodified) per-file score, which is
exactly what the pipeline would do if Stage 5's subsystem/community/
taxonomy pooling didn't exist. Conditions A and B DO call the real,
unmodified `route_query` for their subsystem-level numbers.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_stage_diagnosis import build_repo_context
from code_intelligence.drp.query_router import _file_level_scores, route_query
from code_intelligence.drp.tfidf import SubsystemTfIdfIndex, tokenize

RESULTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "drp_benchmark_data"

# Cases classified as "dampening failure" in the multi-query study —
# every Consul/vLLM instance, plus Django's URL-routing case.
_CASES: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "consul": (
        "go",
        [
            (
                "How does Consul add a new service instance to the catalog when an agent "
                "registers it?",
                "agent/consul/catalog_endpoint.go",
                "original",
            ),
            (
                "When a node joins the LAN gossip pool, what code on the server handles that "
                "join event?",
                "agent/consul/server_serf.go",
                "gossip/membership",
            ),
            (
                "How does Consul turn a DNS query like myservice.service.consul into actual "
                "A/SRV records for healthy instances?",
                "agent/dns.go",
                "service discovery/DNS",
            ),
            (
                "What does a Consul server do right after it wins a Raft leadership election?",
                "agent/consul/leader.go",
                "leader election/raft",
            ),
        ],
    ),
    "vllm": (
        "python",
        [
            (
                "How does vLLM pick which tokenizer implementation to instantiate for a given "
                "model?",
                "vllm/tokenizers/registry.py",
                "tokenization",
            ),
            (
                "How does vLLM set up the tensor-parallel and pipeline-parallel process groups "
                "across GPUs at startup?",
                "vllm/distributed/parallel_state.py",
                "distributed execution",
            ),
            (
                "Where does vLLM's OpenAI-compatible HTTP server actually start up and begin "
                "serving requests?",
                "vllm/entrypoints/openai/api_server.py",
                "API server entry point",
            ),
        ],
    ),
    "django": (
        "python",
        [
            (
                "When a request comes in, how does Django walk through nested URLconfs to "
                "find the view that matches the path?",
                "django/urls/resolvers.py",
                "URL routing",
            ),
        ],
    ),
}

_HUGE = 10_000


def _neutralize_dampening(file_tfidf: SubsystemTfIdfIndex) -> SubsystemTfIdfIndex:
    """New index, same idf, same weights — only token_count/usage_count
    bumped so `.score()`'s own, completely unmodified length-/usage-
    confidence multipliers evaluate to 1.0. `.score()` itself is never
    touched."""
    new_profiles = {
        key: dataclasses.replace(prof, token_count=_HUGE, usage_count=_HUGE)
        for key, prof in file_tfidf.profiles.items()
    }
    return SubsystemTfIdfIndex(profiles=new_profiles, idf=file_tfidf.idf)


def _flat_rank(
    file_tfidf: SubsystemTfIdfIndex, file_to_units: dict, query_tokens: list[str], target: str
) -> tuple[int | None, int, float]:
    """Rank of `target` among ALL files, scored directly (no subsystem/
    community/taxonomy pooling at all) — what Stage 5 would be skipped
    entirely."""
    unit_scores = file_tfidf.score(query_tokens)
    file_scores = _file_level_scores(file_to_units, unit_scores)
    ranking = sorted(file_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    rank = next((i + 1 for i, (f, _) in enumerate(ranking) if f == target), None)
    return rank, len(ranking), file_scores.get(target, 0.0)


def _subsystem_outcome(
    query: str,
    taxonomy,
    file_tfidf: SubsystemTfIdfIndex,
    file_to_units: dict,
    subsystem_graph,
    index,
    target: str,
) -> dict:
    """Real, unmodified `route_query` — the actual production Stage 4/5
    aggregation and routing, run against whichever `file_tfidf` is
    passed in (real for condition A, dampening-neutralized for B)."""
    routing = route_query(query, taxonomy, file_tfidf, file_to_units, subsystem_graph, index)
    target_subsystem = next(
        (path for path, node in taxonomy.nodes.items() if target in node.files), None
    )
    subsystem_rank = next(
        (i + 1 for i, s in enumerate(routing.subsystem_scores) if s.subsystem_path == target_subsystem),
        None,
    )
    target_combined = next(
        (s.combined_score for s in routing.subsystem_scores if s.subsystem_path == target_subsystem),
        0.0,
    )
    winner_combined = routing.subsystem_scores[0].combined_score if routing.subsystem_scores else 0.0
    candidate_files = (
        list(routing.entry_files)
        + list(routing.expansion.keys())
        + [f for files in routing.near_tied_entry_files.values() for f in files]
    )
    return {
        "winning_subsystem": routing.winning_subsystem,
        "target_subsystem": target_subsystem,
        "subsystem_rank": subsystem_rank,
        "subsystem_total": len(routing.subsystem_scores),
        "target_combined": target_combined,
        "winner_combined": winner_combined,
        "in_final_candidates": target in candidate_files,
    }


def run_case(ctx, query: str, target: str, category: str) -> dict:
    taxonomy = ctx.drp_index.taxonomy
    file_tfidf = ctx.drp_index.file_tfidf
    file_to_units = ctx.drp_index.file_to_units
    subsystem_graph = ctx.drp_index.subsystem_graph
    index = ctx.index

    query_tokens = tokenize(query)
    neutralized_tfidf = _neutralize_dampening(file_tfidf)

    # Real per-file damped/undamped scores for the target, for context.
    damped_unit_scores = file_tfidf.score(query_tokens)
    raw_unit_scores = neutralized_tfidf.score(query_tokens)
    target_units = file_to_units.get(target, [])
    best_unit = max(target_units, key=lambda u: raw_unit_scores.get(u, 0.0), default=None)
    retained_fraction = None
    if best_unit is not None:
        raw = raw_unit_scores.get(best_unit, 0.0)
        damped = damped_unit_scores.get(best_unit, 0.0)
        retained_fraction = (damped / raw) if raw > 0 else None

    # Condition A: baseline (real dampening, real aggregation)
    flat_rank_a, total_a, score_a = _flat_rank(file_tfidf, file_to_units, query_tokens, target)
    subsystem_a = _subsystem_outcome(
        query, taxonomy, file_tfidf, file_to_units, subsystem_graph, index, target
    )

    # Condition B: dampening disabled, real aggregation
    flat_rank_b, total_b, score_b = _flat_rank(
        neutralized_tfidf, file_to_units, query_tokens, target
    )
    subsystem_b = _subsystem_outcome(
        query, taxonomy, neutralized_tfidf, file_to_units, subsystem_graph, index, target
    )

    # Condition C: aggregation disabled, real dampening (flat rank IS the outcome)
    flat_rank_c, total_c, score_c = flat_rank_a, total_a, score_a  # same computation as A's flat rank

    # Condition D: both disabled (flat rank on undamped scores)
    flat_rank_d, total_d, score_d = flat_rank_b, total_b, score_b  # same computation as B's flat rank

    result = {
        "repo": ctx.repo,
        "category": category,
        "query": query,
        "target": target,
        "retained_fraction": retained_fraction,
        "A_baseline": {
            "flat_rank": flat_rank_a,
            "flat_total": total_a,
            "flat_score": score_a,
            **subsystem_a,
        },
        "B_no_dampening": {
            "flat_rank": flat_rank_b,
            "flat_total": total_b,
            "flat_score": score_b,
            **subsystem_b,
        },
        "C_no_aggregation": {
            "flat_rank": flat_rank_c,
            "flat_total": total_c,
            "flat_score": score_c,
            "top1": flat_rank_c == 1,
        },
        "D_neither": {
            "flat_rank": flat_rank_d,
            "flat_total": total_d,
            "flat_score": score_d,
            "top1": flat_rank_d == 1,
        },
    }
    return result


def _delta(baseline_rank, other_rank) -> str:
    if baseline_rank is None or other_rank is None:
        return "n/a"
    return f"{baseline_rank - other_rank:+d}"


def print_case(r: dict) -> None:
    print(f"\n{'-' * 90}")
    print(f"[{r['repo']}] ({r['category']}) {r['query']}")
    print(f"target: {r['target']}   retained_fraction={r['retained_fraction']}")
    a, b, c, d = r["A_baseline"], r["B_no_dampening"], r["C_no_aggregation"], r["D_neither"]
    print(
        f"  flat rank:  A(baseline)={a['flat_rank']}/{a['flat_total']}   "
        f"B(no damp)={b['flat_rank']}/{b['flat_total']} (delta={_delta(a['flat_rank'], b['flat_rank'])})   "
        f"C(no agg)={c['flat_rank']}/{c['flat_total']} (delta={_delta(a['flat_rank'], c['flat_rank'])})   "
        f"D(neither)={d['flat_rank']}/{d['flat_total']} (delta={_delta(a['flat_rank'], d['flat_rank'])})"
    )
    print(
        f"  subsystem:  A: rank={a['subsystem_rank']}/{a['subsystem_total']} "
        f"in_candidates={a['in_final_candidates']}   "
        f"B: rank={b['subsystem_rank']}/{b['subsystem_total']} in_candidates={b['in_final_candidates']}"
    )
    print(f"  top-1 (flat): A={a['flat_rank'] == 1}  B={b['flat_rank'] == 1}  C={c['top1']}  D={d['top1']}")

    # A and C share the SAME flat rank by construction (both use real,
    # damped per-file scores; C is just A's flat rank presented as its
    # own condition, since "aggregation disabled" IS "rank flat by the
    # real per-file score"). So the flat-rank delta A->B isolates
    # dampening's effect on the underlying LEXICAL score; whether that
    # translates into actually being retrieved is a SEPARATE question,
    # answered by comparing in_final_candidates between A and B (both of
    # which DO run the real, unmodified subsystem aggregation).
    print(
        f"  dampening's effect on lexical rank alone (A->B flat): "
        f"{_delta(a['flat_rank'], b['flat_rank'])}"
    )
    print(
        f"  dampening's effect on the REAL retrieval outcome (A->B in_final_candidates): "
        f"{a['in_final_candidates']} -> {b['in_final_candidates']}"
    )


def main() -> None:
    repos_root = Path(__file__).resolve().parent.parent.parent / ".benchmark_repos"
    all_results = []
    for repo, (language, cases) in _CASES.items():
        print(f"\n{'=' * 90}\nBuilding index: {repo}\n{'=' * 90}")
        ctx = build_repo_context(repo, language, repos_root)
        for query, target, category in cases:
            r = run_case(ctx, query, target, category)
            all_results.append(r)
            print_case(r)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "causal_isolation_experiment.json"
    out_path.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
