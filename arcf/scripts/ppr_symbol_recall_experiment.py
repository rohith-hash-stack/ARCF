"""ppr_symbol_recall_experiment.py — falsification experiment, read-only,
touches no ARCF source. Builds a real CodeIntelligenceIndex per repo via
the real engine, then tests whether Personalized PageRank seeded from
strict declaration-name matches recovers real, query-relevant symbols
that classic_decomposition_experiment.py's 4 lexical-only variants
couldn't cleanly separate from noise (Consul's "agent" case: bare
`Agent` is invisible to the 6-char probe floor; naive decomposition
finds it but mixes in generic-token noise like TEST/RUN_ALL_TESTS;
frequency-based filtering destroys it because "agent" is common WITHIN
Consul precisely because Consul is about agents).

Design (per the 2026-08-11 review, both my own critique and the user's
refinement addressing it):

1. Seeding is STRICT identifier equality (lowercased), not substring or
   decomposed-token overlap — `SymbolIndex` only ever holds DECLARED
   symbols (SymbolKind is CLASS/FUNCTION/METHOD/INTERFACE, confirmed by
   reading domain/code_intelligence.py — there is no separate "usage
   site" node in this data model at all, so "restrict seeds to
   declarations" is automatically true by construction, not something
   this script has to enforce).
2. Multi-token queries: union of every query token's own seed set into
   one flat teleport vector (uniform mass per seed, no weighted
   combination) — deliberately avoids the "5-signal weighted formula"
   tuning trap this project's own history already rejected once
   (arcf-repo-sweep-50's "Rejected proposal: multi-signal deterministic
   retrieval").
3. A NEW symbol-granularity graph is built here (not reused from
   subsystem_graph.py, which is FILE-granularity — confirmed by reading
   its own _build_adjacency: every edge is a file-path pair). Edges:
   CallGraph.caller_symbols_of/callee_symbols_of (real symbol-to-symbol
   call edges) plus Symbol.parent_id (method <-> enclosing class/
   interface containment, confirmed present in the domain model).
4. PPR runs LOCALLY on a k=2-hop BFS neighborhood around the seeds, not
   the whole graph — capped iterations, pure Python (no numpy — matches
   this codebase's own "no libraries, deterministic, auditable"
   restraint, same choice subsystem_graph.py's Label Propagation already
   made).

Two things flagged as real, unverified risks before trusting this design,
both checked here rather than assumed:
- Does k=2 actually stay small? subsystem_graph.py's own docstring
  documents a REAL, measured "646/763-file monster community" on a real
  Traefik run, caused by extreme fan-in hub files — the same repo is
  tested here specifically for neighborhood-size blowup, not just Consul.
- Does seeding from a bare type name (`Agent`) actually reach its own
  "AgentRead"/"AgentWrite"-style methods via parent_id, or are those
  separate top-level functions with no real containment edge? Measured
  directly, not assumed.

Success criteria (stated up front, matching the user's own proposed
bar): on Consul's real "agent requests" query, Agent-family symbols
(Agent, AgentRead, AgentWrite, checkAllowAgentRead, ...) must appear in
the top 10 PPR-ranked nodes, TEST/RUN_ALL_TESTS-style generic-token noise
must NOT appear in the top 10, k=2 neighborhood size must stay under
~2000 nodes even on Traefik (a looser, honest bound than the "<500
typically" claim, to be measured not assumed), and local PPR computation
must complete in well under 1 second per query (loosened from the
proposed 15ms bar, which was for the matrix-multiply alone, not full
Python graph-BFS-plus-iteration wall time).
"""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path

from code_intelligence.drp.tfidf import tokenize as drp_tokenize
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from domain.code_intelligence import Symbol
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner

SCRATCH_B = Path(
    "C:/Users/VASIGA~1/AppData/Local/Temp/claude/C--Users-VasiganiRohitBabu-Desktop-Claude/"
    "9e0bfde9-a14d-4265-b142-a579ae3668d3/scratchpad/pmi_repos"
)

_ALPHA = 0.15
_MAX_ITER = 8
_TOL = 1e-4
_K_HOPS = 2
_GENERIC_NOISE_TOKENS = {"test", "run", "request"}  # observed noise class from the prior experiment


def _build_index(root: Path) -> CodeIntelligenceIndex:
    engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(root)
    return engine.build_index(root, scan.files)


def _build_symbol_graph(index: CodeIntelligenceIndex) -> dict[str, dict[str, int]]:
    """NEW symbol-granularity adjacency, not reused from subsystem_graph.py
    (which is file-granularity). Two edge types: real call-graph edges
    (symbol calls symbol) and parent_id containment (method belongs to
    its enclosing type)."""
    graph: dict[str, dict[str, int]] = {}

    def add_edge(a: str, b: str, weight: int = 1) -> None:
        if a == b:
            return
        graph.setdefault(a, {})[b] = graph.get(a, {}).get(b, 0) + weight
        graph.setdefault(b, {})[a] = graph.get(b, {}).get(a, 0) + weight

    all_symbols = index.symbol_index.all()
    for symbol in all_symbols:
        for callee_id in index.call_graph.callee_symbols_of(symbol.id):
            add_edge(symbol.id, callee_id)
        if symbol.parent_id is not None:
            add_edge(symbol.id, symbol.parent_id, weight=2)  # containment is a strong signal

    return graph


def _find_declaration_seeds(query: str, all_symbols: list[Symbol]) -> dict[str, list[str]]:
    """Strict identifier equality (case-insensitive), per query token.
    Returns {query_token: [symbol_id, ...]} so we can see which tokens
    actually produced seeds and which didn't (empty list = safe no-op
    per the union design, not a crash)."""
    query_tokens = sorted(set(drp_tokenize(query)))
    by_lower_name: dict[str, list[Symbol]] = {}
    for symbol in all_symbols:
        by_lower_name.setdefault(symbol.name.lower(), []).append(symbol)

    seeds: dict[str, list[str]] = {}
    for token in query_tokens:
        matches = by_lower_name.get(token, [])
        seeds[token] = [s.id for s in matches]
    return seeds


def _k_hop_subgraph(
    graph: dict[str, dict[str, int]], seeds: set[str], k: int
) -> dict[str, dict[str, int]]:
    visited = set(seeds)
    frontier = set(seeds)
    for _ in range(k):
        next_frontier: set[str] = set()
        for node in frontier:
            for neighbor in graph.get(node, {}):
                if neighbor not in visited:
                    next_frontier.add(neighbor)
        visited |= next_frontier
        frontier = next_frontier
        if not frontier:
            break
    return {node: dict(graph.get(node, {})) for node in visited}


def _personalized_pagerank(
    subgraph: dict[str, dict[str, int]], seeds: set[str], alpha: float, max_iter: int, tol: float
) -> dict[str, float]:
    nodes = sorted(subgraph)
    if not nodes:
        return {}
    seed_set = seeds & set(nodes)
    if not seed_set:
        return dict.fromkeys(nodes, 0.0)

    teleport = {n: (1.0 / len(seed_set) if n in seed_set else 0.0) for n in nodes}
    degree = {n: sum(subgraph.get(n, {}).values()) for n in nodes}
    r = dict(teleport)

    for _ in range(max_iter):
        new_r: dict[str, float] = dict.fromkeys(nodes, 0.0)
        for node in nodes:
            d = degree[node]
            if d == 0:
                continue
            share = r[node] / d
            for neighbor, weight in subgraph.get(node, {}).items():
                new_r[neighbor] = new_r.get(neighbor, 0.0) + share * weight
        for n in nodes:
            new_r[n] = (1 - alpha) * new_r.get(n, 0.0) + alpha * teleport[n]
        delta = sum(abs(new_r[n] - r[n]) for n in nodes)
        r = new_r
        if delta < tol:
            break
    return r


def run_case(repo_name: str, query: str) -> None:
    root = SCRATCH_B / repo_name
    if not root.is_dir():
        print(f"SKIP {repo_name}: not cloned")
        return

    index = _build_index(root)
    all_symbols = index.symbol_index.all()
    symbol_by_id = {s.id: s for s in all_symbols}

    seed_map = _find_declaration_seeds(query, all_symbols)
    all_seed_ids = {sid for ids in seed_map.values() for sid in ids}
    print(f"\n=== {repo_name} | {query!r} ===")
    print(f"  seeds found per token: { {t: len(ids) for t, ids in seed_map.items()} }")
    if not all_seed_ids:
        print("  NO SEEDS FOUND AT ALL — falls back to existing pipeline, not a crash.")
        return

    start = time.perf_counter()
    graph = _build_symbol_graph(index)
    subgraph = _k_hop_subgraph(graph, all_seed_ids, _K_HOPS)
    scores = _personalized_pagerank(subgraph, all_seed_ids, _ALPHA, _MAX_ITER, _TOL)
    elapsed = time.perf_counter() - start

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    print(f"  k={_K_HOPS} neighborhood size: {len(subgraph)} nodes")
    print(f"  PPR wall time: {elapsed*1000:.1f}ms")
    print(f"  top 15 by PPR score:")
    for symbol_id, score in ranked:
        sym = symbol_by_id.get(symbol_id)
        name = sym.name if sym else symbol_id
        print(f"      {score:.4f}  {name}")


def stress_test_neighborhood_size(repo_name: str, sample_seed_names: list[str]) -> None:
    """Traefik-specific: check k=2 neighborhood size around several real
    symbols directly (not gated on a query matching), since the concern
    is hub-file blowup, not recall quality, for this repo."""
    root = SCRATCH_B / repo_name
    if not root.is_dir():
        print(f"SKIP {repo_name}: not cloned")
        return
    index = _build_index(root)
    graph = _build_symbol_graph(index)
    by_name: dict[str, list[str]] = {}
    for s in index.symbol_index.all():
        by_name.setdefault(s.name.lower(), []).append(s.id)

    print(f"\n=== {repo_name} neighborhood-size stress test ===")
    for name in sample_seed_names:
        ids = by_name.get(name.lower(), [])
        if not ids:
            print(f"  {name!r}: not found as a symbol, skipping")
            continue
        start = time.perf_counter()
        sub = _k_hop_subgraph(graph, set(ids), _K_HOPS)
        elapsed = time.perf_counter() - start
        print(f"  seed={name!r} matches={len(ids)}  k=2 neighborhood={len(sub)} nodes  ({elapsed*1000:.1f}ms)")


def main() -> None:
    # Primary test: the real, known Consul case from
    # classic_decomposition_experiment.py.
    run_case("consul", "How is authentication handled for agent requests?")

    # Second real data point: Consul's actual DRP ground-truth query
    # (docs/drp_benchmark_data/drp_vs_classic_consul.json), target file
    # agent/consul/catalog_endpoint.go — checks PPR isn't overfit to one
    # hand-picked query.
    run_case("consul", "How does Consul add a new service instance to the catalog when an agent registers it?")

    # Traefik-specific neighborhood-size stress test (the repo already
    # documented to have extreme fan-in hub files in subsystem_graph.py).
    stress_test_neighborhood_size(
        "traefik",
        ["Provider", "Router", "Config", "Manager", "Handler", "Server"],
    )


if __name__ == "__main__":
    main()
