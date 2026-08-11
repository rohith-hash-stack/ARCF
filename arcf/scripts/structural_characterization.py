"""ARCF Issue #3 — structural characterization of dampening-sensitive files.

Not a fix. For each of the 8 files from the causal isolation experiment
(grouped by whether de-dampening flipped retrieval, improved rank
without fixing it, made subsystem rank worse, or didn't matter despite
an already-strong lexical rank), computes concrete, measurable
structural metrics from the repository's own call/import graph — no
narrative, no per-repo storytelling.

Reuses existing DRP/CallGraph/ImportGraph read-only. Betweenness
centrality is NOT already computed anywhere in this codebase
(`subsystem_graph.py`'s own docstring explains it deliberately skips
betweenness as unnecessary complexity for DRP's own purposes) and this
project has no `networkx` dependency, so it's implemented here, once,
as a standard unweighted Brandes' algorithm over the same file-level
adjacency graph `subsystem_graph.py` already builds (`_build_adjacency`,
reused read-only, not modified) — a documented simplification (treating
weighted edges as unweighted for shortest-path purposes) for
tractability, not a new production mechanism.
"""

from __future__ import annotations

import json
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_stage_diagnosis import build_repo_context
from code_intelligence.drp.subsystem_graph import _build_adjacency
from code_intelligence.drp.tfidf import tokenize

RESULTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "drp_benchmark_data"

# (repo, language, query used to select the "best unit" — same query as
# the causal isolation experiment, for traceability — target file, group)
_CASES = [
    ("consul", "go", "When a node joins the LAN gossip pool, what code on the server handles that join event?", "agent/consul/server_serf.go", "A"),
    ("consul", "go", "How does Consul turn a DNS query like myservice.service.consul into actual A/SRV records for healthy instances?", "agent/dns.go", "A"),
    ("vllm", "python", "How does vLLM set up the tensor-parallel and pipeline-parallel process groups across GPUs at startup?", "vllm/distributed/parallel_state.py", "A"),
    ("consul", "go", "What does a Consul server do right after it wins a Raft leadership election?", "agent/consul/leader.go", "B"),
    ("consul", "go", "How does Consul add a new service instance to the catalog when an agent registers it?", "agent/consul/catalog_endpoint.go", "B"),
    ("vllm", "python", "How does vLLM pick which tokenizer implementation to instantiate for a given model?", "vllm/tokenizers/registry.py", "C"),
    ("vllm", "python", "Where does vLLM's OpenAI-compatible HTTP server actually start up and begin serving requests?", "vllm/entrypoints/openai/api_server.py", "C"),
    ("django", "python", "When a request comes in, how does Django walk through nested URLconfs to find the view that matches the path?", "django/urls/resolvers.py", "D"),
]


def _betweenness_centrality(adjacency: dict[str, dict[str, int]]) -> dict[str, float]:
    """Standard unweighted Brandes' algorithm (Brandes 2001) over the
    file-level adjacency graph. O(V*E) — for these repo sizes (2.3k-4.1k
    nodes) this runs in low tens of seconds. Unweighted: shortest paths
    are by hop count, not edge weight — a documented simplification."""
    nodes = list(adjacency.keys())
    centrality: dict[str, float] = dict.fromkeys(nodes, 0.0)

    for s in nodes:
        stack: list[str] = []
        pred: dict[str, list[str]] = {v: [] for v in nodes}
        sigma: dict[str, float] = dict.fromkeys(nodes, 0.0)
        sigma[s] = 1.0
        dist: dict[str, int] = dict.fromkeys(nodes, -1)
        dist[s] = 0
        queue: deque[str] = deque([s])
        while queue:
            v = queue.popleft()
            stack.append(v)
            for w in adjacency.get(v, {}):
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    queue.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta: dict[str, float] = dict.fromkeys(nodes, 0.0)
        while stack:
            w = stack.pop()
            for v in pred[w]:
                delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w]) if sigma[w] else 0.0
            if w != s:
                centrality[w] += delta[w]

    # Undirected graph: each shortest path counted from both endpoints,
    # so raw accumulator is divided by 2 first; standard normalization
    # scale for undirected betweenness is 2/((n-1)(n-2)).
    n = len(nodes)
    scale = 2.0 / ((n - 1) * (n - 2)) if n > 2 else 0.0
    return {k: (v / 2.0) * scale for k, v in centrality.items()}


def _entry_point_distance(adjacency: dict[str, dict[str, int]], import_graph, target: str) -> int | None:
    """BFS distance (hops) from the nearest structural "entry point" —
    a file that nothing else in the repo imports (import_graph.
    importers_of(f) is empty) — to `target`, over the same file-level
    adjacency graph. Structural, not name-based (no "main.go"/"__main__"
    pattern matching)."""
    entry_points = {
        f for f in adjacency if not import_graph.importers_of(f)
    }
    if target in entry_points:
        return 0
    visited = {target}
    queue: deque[tuple[str, int]] = deque([(target, 0)])
    while queue:
        node, dist = queue.popleft()
        if node in entry_points:
            return dist
        for neighbor in adjacency.get(node, {}):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, dist + 1))
    return None


def analyze_case(ctx, query: str, target: str, group: str) -> dict:
    index = ctx.index
    drp_index = ctx.drp_index
    file_tfidf = drp_index.file_tfidf
    file_to_units = drp_index.file_to_units
    subsystem_graph = drp_index.subsystem_graph

    query_tokens = tokenize(query)
    query_counts: dict[str, int] = {}
    for t in query_tokens:
        query_counts[t] = query_counts.get(t, 0) + 1
    # RAW (undamped) score for selection — matches the causal isolation
    # experiment's own methodology exactly. Selecting by the DAMPED score
    # here would be circular: dampening is exactly what suppresses the
    # symbols under study, so it would silently pick a DIFFERENT,
    # undampened, coincidentally-higher-scoring unit in the same file
    # (confirmed as a real bug during a first pass — it picked the
    # `Catalog` class itself, or an unrelated `ConsulRegistrator`
    # interface, instead of `Catalog.Register`/`establishLeadership`).
    target_units = file_to_units.get(target, [])
    raw_scores = {
        u: sum(
            count * file_tfidf.profiles[u].weights.get(term, 0.0)
            for term, count in query_counts.items()
        )
        for u in target_units
        if u in file_tfidf.profiles
    }
    best_unit = max(raw_scores, key=lambda u: raw_scores[u], default=(target_units[0] if target_units else target))

    analysis = index.file_analyses.get(target)
    symbol = None
    if analysis is not None:
        for s in analysis.symbols:
            if s.id == best_unit:
                symbol = s
                break

    # `best_unit` is a real Symbol.id for a split file, but for an
    # UNSPLIT file (registry.py, here) it's the bare FILE PATH — which
    # is not a valid symbol id, so CallGraph queries against it silently
    # return empty sets (confirmed as a real bug during a first pass: it
    # reported registry.py as "0 incoming calls" when `get_tokenizer`
    # genuinely has 27 real call sites across the repo, per direct grep).
    # For that case, aggregate across every symbol actually defined in
    # the file — the same aggregate `_combined_call_count` itself uses
    # for an unsplit file's `unit_usage` in production — and separately
    # identify the single symbol whose name best matches the query for a
    # more granular supplementary data point.
    best_named_symbol = None
    if symbol is None and analysis is not None:
        query_term_set = set(query_tokens)
        def _name_overlap(s):
            return len(set(tokenize(s.qualified_name)) & query_term_set)
        candidates = [s for s in analysis.symbols if s.parent_id is None]
        if candidates:
            best_named_symbol = max(candidates, key=_name_overlap)

    if symbol is not None:
        call_target_ids = [best_unit]
    elif analysis is not None:
        call_target_ids = [s.id for s in analysis.symbols]
    else:
        call_target_ids = [best_unit]

    # Call graph metrics (raw, unfiltered — not the locality-filtered
    # usage_count DRP's own scoring uses; this is the underlying
    # structural signal before any DRP-side interpretation). For an
    # unsplit file this is summed across every symbol it defines.
    incoming_symbols = sum(len(index.call_graph.caller_symbols_of(i)) for i in call_target_ids)
    incoming_files = sum(len(index.call_graph.caller_files_of(i)) for i in call_target_ids)
    incoming_total = incoming_symbols + incoming_files
    outgoing = sum(len(index.call_graph.callee_symbols_of(i)) for i in call_target_ids)
    fan_ratio = (incoming_total / outgoing) if outgoing > 0 else (float("inf") if incoming_total > 0 else 0.0)
    transitive_callers = index.call_graph.transitive_caller_symbols_of(best_unit if symbol is not None else call_target_ids[0])
    deepest_caller_chain = max((hop for hop, _ in transitive_callers.values()), default=0)

    best_named_symbol_calls = None
    if best_named_symbol is not None:
        best_named_symbol_calls = len(index.call_graph.caller_symbols_of(best_named_symbol.id)) + len(
            index.call_graph.caller_files_of(best_named_symbol.id)
        )

    # Graph position
    metrics = subsystem_graph.metrics.get(target)
    community_id = metrics.community_id if metrics else None
    community_size = len(subsystem_graph.communities.get(community_id, [])) if community_id else 0
    degree_centrality = metrics.centrality if metrics else 0.0
    import_connections = len(index.import_graph.imports_of(target)) + len(
        index.import_graph.importers_of(target)
    )

    # Symbol characteristics
    file_stem_upper = symbol.name[0].isupper() if symbol and symbol.name else False
    is_private_python_convention = symbol.name.startswith("_") if symbol and symbol.name else False
    token_count = None
    prof = file_tfidf.profiles.get(best_unit)
    if prof is not None:
        token_count = prof.token_count

    return {
        "repo": ctx.repo,
        "group": group,
        "target": target,
        "best_unit": best_unit,
        "symbol_name": symbol.name if symbol else "(whole file, unsplit — aggregated across all symbols)",
        "symbol_kind": str(symbol.kind) if symbol else "file",
        "symbol_qualified_name": symbol.qualified_name if symbol else None,
        "best_named_symbol": best_named_symbol.qualified_name if best_named_symbol else None,
        "best_named_symbol_calls": best_named_symbol_calls,
        # call graph
        "incoming_direct_calls": incoming_total,
        "incoming_symbol_calls": incoming_symbols,
        "incoming_file_calls": incoming_files,
        "outgoing_calls": outgoing,
        "fan_in_out_ratio": fan_ratio if fan_ratio != float("inf") else None,
        "incoming_is_zero": incoming_total == 0,
        "deepest_known_caller_chain_hops": deepest_caller_chain,
        # graph position
        "community_id": community_id,
        "community_size": community_size,
        "degree_centrality": degree_centrality,
        "import_path_connections": import_connections,
        # symbol characteristics
        "exported_capitalized": file_stem_upper,
        "python_private_convention": is_private_python_convention,
        "unit_token_count": token_count,
        # filled in later (needs the shared adjacency/betweenness pass)
        "betweenness_centrality": None,
        "entry_point_distance_hops": None,
    }


def main() -> None:
    repos_root = Path(__file__).resolve().parent.parent.parent / ".benchmark_repos"
    by_repo: dict[str, list[tuple]] = {}
    for repo, language, query, target, group in _CASES:
        by_repo.setdefault(repo, []).append((language, query, target, group))

    all_results = []
    for repo, cases in by_repo.items():
        language = cases[0][0]
        print(f"\n{'=' * 90}\nBuilding index + adjacency + betweenness: {repo}\n{'=' * 90}")
        ctx = build_repo_context(repo, language, repos_root)
        adjacency = _build_adjacency(ctx.index)
        print(f"  adjacency graph: {len(adjacency)} nodes — computing betweenness centrality...")
        betweenness = _betweenness_centrality(adjacency)
        print(f"  done.")

        for _language, query, target, group in cases:
            r = analyze_case(ctx, query, target, group)
            r["betweenness_centrality"] = betweenness.get(target, 0.0)
            r["entry_point_distance_hops"] = _entry_point_distance(
                adjacency, ctx.index.import_graph, target
            )
            all_results.append(r)
            print(f"\n[{group}] {repo}/{target} ({r['symbol_name']}, {r['symbol_kind']})")
            print(
                f"  incoming={r['incoming_direct_calls']} (zero={r['incoming_is_zero']})  "
                f"outgoing={r['outgoing_calls']}  fan_ratio={r['fan_in_out_ratio']}"
            )
            print(
                f"  community_size={r['community_size']}  degree_centrality={r['degree_centrality']:.4f}  "
                f"betweenness={r['betweenness_centrality']:.6f}"
            )
            print(
                f"  entry_point_distance={r['entry_point_distance_hops']}  "
                f"import_connections={r['import_path_connections']}  "
                f"deepest_caller_chain={r['deepest_known_caller_chain_hops']}"
            )
            print(
                f"  exported={r['exported_capitalized']}  python_private={r['python_private_convention']}  "
                f"unit_tokens={r['unit_token_count']}"
            )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "structural_characterization.json"
    out_path.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    main()
