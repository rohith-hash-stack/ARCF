"""DRP Stage 4 — Query Routing.

Combines three independent, deterministic signals per subsystem — its
own TF-IDF relevance (Stage 2), the query-relevance of the graph
communities that dominate it (Stage 3), and a direct taxonomy
path-segment match (Stage 1) — into one subsystem confidence score, then
expands the winning subsystem's best entry files via the existing
`ImportGraph`, restricted to that subsystem's own file set.

Both the TF-IDF and community signals are aggregated UP from per-file
scores (top-K mean of a subsystem's/community's own member files),
never down from one document pooled across every file in a subsystem or
community. A pooled-document version was tried first, against a real
Traefik run, and found to systematically favor small, single-purpose
directories over large, correct-but-multi-concern ones: pooling
`pkg/server`'s ~50 files into one TF-IDF document diluted the one file
actually relevant to a query ("dynamic configuration updates... without
restarting") behind unrelated router/TCP/middleware vocabulary, while a
small directory whose few files happened to share surface words with
the query scored higher purely by not being diluted. Top-K aggregation
lets a subsystem's score be driven by its best-matching files
regardless of how many unrelated neighbors sit alongside them — and, as
a side benefit, makes the community signal robust to Label
Propagation's "monster community" failure mode (see subsystem_graph.py)
too: a giant community's relevance is still driven by its few truly
matching members, not diluted by the hundreds of unrelated files
Label Propagation happened to lump in with them.

No embeddings, no LLM calls, no hardcoded concept dictionary: every
signal here is either a TF-IDF dot product already built from the
repository's own text, or a structural graph/path fact.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from code_intelligence.drp.subsystem_graph import SubsystemGraphResult
from code_intelligence.drp.taxonomy import SubsystemTaxonomy
from code_intelligence.drp.tfidf import SubsystemTfIdfIndex, tokenize
from code_intelligence.import_graph import ImportGraph
from code_intelligence.index import CodeIntelligenceIndex

# Starting weights for combining the three routing signals — an
# empirical starting point (tfidf is the strongest, most direct signal;
# community and taxonomy are corroborating), tunable against the Traefik
# benchmark. Kept as named constants with this comment rather than
# config, matching context_resolver.py's own "constant + empirical
# justification" convention (e.g. _MAX_CANDIDATES_TO_EXPAND).
_TFIDF_WEIGHT = 0.55
_COMMUNITY_WEIGHT = 0.30
_TAXONOMY_WEIGHT = 0.15

# How many of a subsystem's/community's own best-matching member files
# drive its aggregate relevance score (mean of their file-level scores,
# not just the single best file) — enough that a subsystem where several
# files are genuinely relevant scores higher than one with only a single
# coincidental match, without reintroducing the dilution a full pooled-
# document average caused (see module docstring).
_TOP_K_FILES_FOR_AGGREGATE_SCORE = 3

# How many of the winning subsystem's own files seed graph expansion —
# mirrors the intent (not the exact value) of ContextResolver's
# _MAX_CANDIDATES_TO_EXPAND: a handful of the most relevant files, not
# every file in a large subsystem.
_MAX_ENTRY_FILES = 5

# A subsystem scoring within this fraction of the winner's combined_score
# is treated as a genuine near-tie, not a loss — winner-take-all with no
# margin was found, against two real repositories, to completely exclude
# the correct subsystem's files from candidates purely because it came a
# couple of percent behind: Consul's real answer (agent/consul, 0.847)
# lost to agent/structs (0.865, ~2.1% ahead); Django's (django/db/models,
# 0.847) lost to django/db/backends/base (0.867, ~2.3% ahead). 3% gives
# both real cases headroom without pulling in subsystems that are
# genuinely, meaningfully behind.
_NEAR_TIE_MARGIN = 0.03

# Caps how many near-tied runners-up get their own entry files considered
# (winner + this many) — bounds packaging cost; a near-tie is specifically
# about not excluding a close second place, not about broadening to every
# subsystem that scored reasonably.
_MAX_NEAR_TIE_SUBSYSTEMS = 2


@dataclass
class SubsystemScore:
    subsystem_path: str
    tfidf_score: float
    community_score: float
    taxonomy_score: float
    combined_score: float


@dataclass
class DrpRouting:
    query_tokens: list[str]
    subsystem_scores: list[SubsystemScore] = field(default_factory=list)
    """Sorted descending by combined_score, ties broken by
    subsystem_path — index 0 is the winner."""
    winning_subsystem: str = ""
    winning_confidence: float = 0.0
    """combined_score of the winner, normalized by the sum of every
    subsystem's combined_score (0.0 when every subsystem scored zero —
    an honestly "found nothing" result, not a fabricated confidence)."""
    top_community_id: str | None = None
    entry_files: list[str] = field(default_factory=list)
    expansion: dict[str, tuple[int, str]] = field(default_factory=dict)
    """file_path -> (hop, parent_file_path) for every file reached by
    expanding beyond entry_files, same shape as CallGraph._layered_bfs's
    own result so `drp_resolver.py` can build justification chains the
    same way ContextResolver already does."""
    near_tied_subsystems: list[str] = field(default_factory=list)
    """Subsystems within `_NEAR_TIE_MARGIN` of the winner's combined
    score (excluding the winner itself), ranked order — see the
    constant's own comment for the real cases that motivated this."""
    near_tied_entry_files: dict[str, list[str]] = field(default_factory=dict)
    """subsystem_path -> its own top-ranked entry files, for every
    subsystem in `near_tied_subsystems`. Deliberately no further graph
    expansion for these (unlike the winner's own `entry_files`/
    `expansion`) — the goal is giving a close runner-up's best files a
    chance to appear as candidates at all, not a second full expansion
    pass."""


def _top_k_mean(scores: list[float], k: int) -> float:
    if not scores:
        return 0.0
    top = sorted(scores, reverse=True)[:k]
    return sum(top) / len(top)


def _taxonomy_score(subsystem_path: str, node_namespaces: set[str], query_terms: set[str]) -> float:
    if not query_terms:
        return 0.0
    path_text = subsystem_path.replace("/", " ") + " " + " ".join(node_namespaces)
    path_terms = set(tokenize(path_text))
    matched = query_terms & path_terms
    return len(matched) / len(query_terms)


def _subsystem_tfidf_scores(
    taxonomy: SubsystemTaxonomy, file_scores: dict[str, float]
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for subsystem_path, node in taxonomy.nodes.items():
        member_scores = [file_scores.get(f, 0.0) for f in node.files]
        scores[subsystem_path] = _top_k_mean(member_scores, _TOP_K_FILES_FOR_AGGREGATE_SCORE)
    return scores


def _community_relevance_scores(
    subsystem_graph: SubsystemGraphResult, file_scores: dict[str, float]
) -> dict[str, float]:
    relevance: dict[str, float] = {}
    for community_id, member_files in subsystem_graph.communities.items():
        member_scores = [file_scores.get(f, 0.0) for f in member_files]
        relevance[community_id] = _top_k_mean(member_scores, _TOP_K_FILES_FOR_AGGREGATE_SCORE)
    return relevance


def _community_scores_by_subsystem(
    taxonomy: SubsystemTaxonomy,
    subsystem_graph: SubsystemGraphResult,
    community_relevance: dict[str, float],
) -> tuple[dict[str, float], str | None]:
    top_community_id = (
        max(community_relevance, key=lambda c: (community_relevance[c], c))
        if community_relevance
        else None
    )

    scores: dict[str, float] = {}
    for subsystem_path, node in taxonomy.nodes.items():
        if not node.files:
            scores[subsystem_path] = 0.0
            continue
        community_counts: Counter[str] = Counter(
            subsystem_graph.metrics[f].community_id
            for f in node.files
            if f in subsystem_graph.metrics
        )
        total = len(node.files)
        scores[subsystem_path] = sum(
            (count / total) * community_relevance.get(community_id, 0.0)
            for community_id, count in community_counts.items()
        )
    return scores, top_community_id


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    max_score = max(scores.values(), default=0.0)
    if max_score <= 0.0:
        return dict.fromkeys(scores, 0.0)
    return {path: score / max_score for path, score in scores.items()}


def _rank_entry_files(
    subsystem_files: list[str],
    file_scores: dict[str, float],
    subsystem_graph: SubsystemGraphResult,
) -> list[str]:
    if not subsystem_files:
        return []

    def file_rank_key(file_path: str) -> tuple[float, float, str]:
        metrics = subsystem_graph.metrics.get(file_path)
        centrality = metrics.centrality if metrics is not None else 0.0
        # Sorted descending by (tfidf score, centrality), ascending by
        # path as the final deterministic tie-break.
        return (-file_scores.get(file_path, 0.0), -centrality, file_path)

    ranked = sorted(subsystem_files, key=file_rank_key)
    return ranked[:_MAX_ENTRY_FILES]


def _expand_within_subsystem(
    entry_files: list[str],
    subsystem_files: set[str],
    import_graph: ImportGraph,
    traversal_depth: int,
) -> dict[str, tuple[int, str]]:
    result: dict[str, tuple[int, str]] = {}
    visited: set[str] = set(entry_files)
    frontier: set[str] = set(entry_files)
    depth = 1

    while frontier and depth <= traversal_depth:
        candidates: dict[str, set[str]] = defaultdict(set)
        for node in sorted(frontier):
            all_neighbors = import_graph.imports_of(node) | import_graph.importers_of(node)
            neighbors = all_neighbors & subsystem_files
            for neighbor in neighbors:
                if neighbor not in visited:
                    candidates[neighbor].add(node)
        if not candidates:
            break
        for neighbor, parents in candidates.items():
            result[neighbor] = (depth, min(parents))
            visited.add(neighbor)
        frontier = set(candidates.keys())
        depth += 1

    return result


def _file_level_scores(
    file_to_units: dict[str, list[str]], unit_scores: dict[str, float]
) -> dict[str, float]:
    """Reduces per-unit scores (file_tfidf.profiles may be split per
    top-level symbol for a large file — see text_corpus.gather_scoring_
    units) back up to one score per FILE, by taking the max across its
    own units. Max, not a mean or sum: a file is relevant if ANY part of
    it addresses the query — a file with 17 unrelated classes shouldn't
    need all 17 to look relevant just because it was split, only its
    single best-matching one. Everything downstream of this function
    (subsystem/entry-file scoring) works with these file-level scores
    exactly as it did before symbol-level splitting existed."""
    return {
        file_path: max((unit_scores.get(unit, 0.0) for unit in units), default=0.0)
        for file_path, units in file_to_units.items()
    }


def route_query(
    query: str,
    taxonomy: SubsystemTaxonomy,
    file_tfidf: SubsystemTfIdfIndex,
    file_to_units: dict[str, list[str]],
    subsystem_graph: SubsystemGraphResult,
    index: CodeIntelligenceIndex,
    traversal_depth: int = 2,
) -> DrpRouting:
    query_tokens = tokenize(query)
    query_terms = set(query_tokens)

    # file_tfidf.profiles may be keyed by scoring UNIT (a whole file, or
    # one top-level symbol within a large one — see drp_index.py) rather
    # than always by file path; reduce to one score per file immediately
    # so every subsystem/community aggregate below is derived from a
    # single, familiar, file-keyed source, unaware that splitting ever
    # happened.
    unit_scores = file_tfidf.score(query_tokens)
    file_scores = _file_level_scores(file_to_units, unit_scores)

    tfidf_scores = _subsystem_tfidf_scores(taxonomy, file_scores)
    community_relevance = _community_relevance_scores(subsystem_graph, file_scores)
    community_scores, top_community_id = _community_scores_by_subsystem(
        taxonomy, subsystem_graph, community_relevance
    )
    taxonomy_scores = {
        path: _taxonomy_score(path, node.package_namespaces, query_terms)
        for path, node in taxonomy.nodes.items()
    }

    norm_tfidf = _normalize(tfidf_scores)
    norm_community = _normalize(community_scores)

    subsystem_scores: list[SubsystemScore] = []
    for path in taxonomy.nodes:
        combined = (
            _TFIDF_WEIGHT * norm_tfidf.get(path, 0.0)
            + _COMMUNITY_WEIGHT * norm_community.get(path, 0.0)
            + _TAXONOMY_WEIGHT * taxonomy_scores.get(path, 0.0)
        )
        subsystem_scores.append(
            SubsystemScore(
                subsystem_path=path,
                tfidf_score=tfidf_scores.get(path, 0.0),
                community_score=community_scores.get(path, 0.0),
                taxonomy_score=taxonomy_scores.get(path, 0.0),
                combined_score=combined,
            )
        )
    subsystem_scores.sort(key=lambda s: (-s.combined_score, s.subsystem_path))

    routing = DrpRouting(
        query_tokens=query_tokens,
        subsystem_scores=subsystem_scores,
        top_community_id=top_community_id,
    )
    if not subsystem_scores:
        return routing

    total_combined = sum(s.combined_score for s in subsystem_scores)
    winner = subsystem_scores[0]
    routing.winning_subsystem = winner.subsystem_path
    routing.winning_confidence = (
        winner.combined_score / total_combined if total_combined > 0 else 0.0
    )

    subsystem_files = taxonomy.files_in(winner.subsystem_path)
    entry_files = _rank_entry_files(subsystem_files, file_scores, subsystem_graph)
    routing.entry_files = entry_files
    routing.expansion = _expand_within_subsystem(
        entry_files, set(subsystem_files), index.import_graph, traversal_depth
    )

    if winner.combined_score > 0:
        near_tie_threshold = winner.combined_score * (1 - _NEAR_TIE_MARGIN)
        near_tied = [
            s for s in subsystem_scores[1:] if s.combined_score >= near_tie_threshold
        ][:_MAX_NEAR_TIE_SUBSYSTEMS]
        routing.near_tied_subsystems = [s.subsystem_path for s in near_tied]
        for s in near_tied:
            runner_up_files = taxonomy.files_in(s.subsystem_path)
            routing.near_tied_entry_files[s.subsystem_path] = _rank_entry_files(
                runner_up_files, file_scores, subsystem_graph
            )

    return routing
