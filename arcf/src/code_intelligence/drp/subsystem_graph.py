"""DRP Stage 3 — Graph Communities.

Builds a file-level undirected weighted graph purely from the existing,
already-built `ImportGraph` and `CallGraph` (read-only queries via their
public methods only — `imports_of` and `caller_files_of` — no
subclassing, no mutation, no re-parsing) and partitions it with a
hand-rolled, deterministic, degree-damped **Label Propagation**
algorithm.

Louvain is not implemented: per the experiment's own spec, Label
Propagation is an explicit, allowed substitute, and it fits ARCF's
existing determinism discipline more directly than Louvain's randomized
tie-breaking would (see `call_graph.py`'s `_layered_bfs`, which solves
the exact same "don't depend on Python's hash-randomized set iteration"
problem this module has for graph traversal).

Updates are asynchronous (Gauss-Seidel style: each node's new label is
written in place immediately, so later nodes in the same pass already
see it), not synchronous/Jacobi-style — a synchronous variant was tried
first and rejected: reading every node's label from a frozen previous-
pass snapshot causes the textbook period-2 oscillation on path-shaped
graphs (a 3-node import chain A-imports-B-imports-C never converges,
flipping between two different-but-equally-valid partitions forever).
Determinism comes from visiting nodes in a fixed sorted path order each
pass and breaking weight ties by the lexicographically smallest label —
the same discipline used throughout `code_intelligence/`'s five existing
graph classes. A fixed iteration cap guarantees termination even if some
pathological graph never quite converges.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from code_intelligence.index import CodeIntelligenceIndex

# Empirically enough passes for label propagation to converge (or nearly
# so) on repository-sized import/call graphs — LP typically stabilizes
# within single-digit passes; this is a safety cap against oscillation
# on adversarial graphs, not a tuned performance knob.
_MAX_ITERATIONS = 20


@dataclass
class CommunityMetrics:
    community_id: str
    """The lexicographically-smallest file path among this file's final
    community members — a stable id derived from group membership, not
    from whichever arbitrary label Label Propagation happened to
    converge on for that pocket of the graph."""
    modularity_contribution: float
    """This file's approximate additive share of the partition's global
    modularity score (see `SubsystemGraphResult.modularity`) — a
    diagnostic breakdown, not independently normalized."""
    bridge_score: float
    """Fraction of this file's edge weight that crosses to a different
    community (0.0 = every neighbor is in the same community, 1.0 = none
    are). 0.0 for an isolated file (no edges)."""
    intra_community_degree: int
    """Total edge weight to neighbors within the same community."""
    centrality: float
    """Weighted degree centrality, normalized by the graph's maximum
    node degree (0.0-1.0) — a simple, fully deterministic centrality
    measure; no eigenvector/betweenness computation, which would add
    real algorithmic cost and complexity this diagnostic doesn't need."""


@dataclass
class SubsystemGraphResult:
    metrics: dict[str, CommunityMetrics] = field(default_factory=dict)
    """file_path -> CommunityMetrics, for every file in the index (files
    with no import/call edges still get an entry: their own singleton
    community)."""
    communities: dict[str, list[str]] = field(default_factory=dict)
    """community_id -> sorted member file paths."""
    modularity: float = 0.0
    iterations_run: int = 0
    algorithm: str = "label_propagation"


def _build_adjacency(index: CodeIntelligenceIndex) -> dict[str, dict[str, int]]:
    adjacency: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def add_edge(a: str, b: str, weight: int) -> None:
        if a == b:
            return
        adjacency[a][b] += weight
        adjacency[b][a] += weight

    for file_path in index.file_analyses:
        for imported in index.import_graph.imports_of(file_path):
            add_edge(file_path, imported, 1)

    for symbol in index.symbol_index.functions() + index.symbol_index.methods():
        for caller_file in index.call_graph.caller_files_of(symbol.id):
            add_edge(caller_file, symbol.file_path, 1)

    return {node: dict(neighbors) for node, neighbors in adjacency.items()}


def _run_label_propagation(
    all_files: list[str], adjacency: dict[str, dict[str, int]], max_iterations: int
) -> tuple[dict[str, str], int]:
    labels: dict[str, str] = {f: f for f in all_files}

    # Static (pre-computed once, never recomputed mid-run — recomputing
    # from labels-in-flux would make convergence order-dependent) weighted
    # degree per node. A real-world import/call graph almost always has a
    # handful of extreme-fan-in hub files (a shared config/types/util
    # module every package imports); plain unweighted label voting lets
    # such a hub's label flood outward and swallow most of the graph into
    # one "monster community" — a well-documented LP failure mode, and the
    # actual cause of a 646/763-file monster community observed on a real
    # Traefik run. Dividing each neighbor's vote by sqrt(its own degree)
    # (a standard LP mitigation) means a hub's vote counts for much less
    # per-edge than a normal node's — it still gets heard, just not
    # allowed to dominate purely by being connected to everything.
    degree: dict[str, float] = {f: float(sum(adjacency.get(f, {}).values())) for f in all_files}

    for iteration in range(1, max_iterations + 1):
        changed = False
        for node in all_files:
            neighbors = adjacency.get(node)
            if not neighbors:
                continue
            label_weight: dict[str, float] = defaultdict(float)
            for neighbor, weight in neighbors.items():
                # Reads `labels` as it stands right now, not a frozen
                # per-pass snapshot — a neighbor already visited earlier
                # in THIS pass contributes its brand-new label. This is
                # what makes the pass converge instead of oscillating
                # (see module docstring).
                neighbor_degree = degree[neighbor]
                damped_weight = weight / math.sqrt(neighbor_degree) if neighbor_degree > 0 else 0.0
                label_weight[labels[neighbor]] += damped_weight
            max_weight = max(label_weight.values())
            best_label = min(
                label for label, weight in label_weight.items() if weight == max_weight
            )
            if best_label != labels[node]:
                labels[node] = best_label
                changed = True
        if not changed:
            return labels, iteration

    return labels, max_iterations


def build_subsystem_graph(
    index: CodeIntelligenceIndex, max_iterations: int = _MAX_ITERATIONS
) -> SubsystemGraphResult:
    all_files = sorted(index.file_analyses)
    if not all_files:
        return SubsystemGraphResult()

    adjacency = _build_adjacency(index)
    labels, iterations_run = _run_label_propagation(all_files, adjacency, max_iterations)

    groups: dict[str, list[str]] = defaultdict(list)
    for file_path, label in labels.items():
        groups[label].append(file_path)
    communities: dict[str, list[str]] = {}
    community_of: dict[str, str] = {}
    for member_files in groups.values():
        member_files.sort()
        community_id = member_files[0]
        communities[community_id] = member_files
        for file_path in member_files:
            community_of[file_path] = community_id

    degree: dict[str, int] = {f: sum(adjacency.get(f, {}).values()) for f in all_files}
    intra_degree: dict[str, int] = {
        f: sum(
            weight
            for neighbor, weight in adjacency.get(f, {}).items()
            if community_of[neighbor] == community_of[f]
        )
        for f in all_files
    }
    sum_tot: dict[str, int] = defaultdict(int)
    for f in all_files:
        sum_tot[community_of[f]] += degree[f]

    two_m = sum(degree.values())
    max_degree = max(degree.values(), default=0)

    if two_m == 0:
        modularity = 0.0
        contributions = dict.fromkeys(all_files, 0.0)
    else:
        sum_in: dict[str, int] = defaultdict(int)
        for f in all_files:
            sum_in[community_of[f]] += intra_degree[f]
        modularity = sum(
            (sum_in[c] / two_m) - (sum_tot[c] / two_m) ** 2 for c in communities
        )
        contributions = {
            f: (
                intra_degree[f] - degree[f] * (sum_tot[community_of[f]] - degree[f]) / two_m
            )
            / two_m
            for f in all_files
        }

    metrics: dict[str, CommunityMetrics] = {}
    for f in all_files:
        d = degree[f]
        bridge_score = 0.0 if d == 0 else (d - intra_degree[f]) / d
        centrality = 0.0 if max_degree == 0 else d / max_degree
        metrics[f] = CommunityMetrics(
            community_id=community_of[f],
            modularity_contribution=contributions[f],
            bridge_score=bridge_score,
            intra_community_degree=intra_degree[f],
            centrality=centrality,
        )

    return SubsystemGraphResult(
        metrics=metrics,
        communities=communities,
        modularity=modularity,
        iterations_run=iterations_run,
    )
