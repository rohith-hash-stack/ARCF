"""DRP experimental extension — repo-local PMI word association.

Answers the question raised directly by the real Traefik benchmark
failure: the query word "restarting" has zero document frequency
anywhere in the file corpus (confirmed — see drp_resolver.py's own
history), so no amount of TF-IDF weighting or aggregation can ever let
it discriminate anything, no matter which file it's compared against.
This module builds a small, fully repo-native "did these two words tend
to appear in the same files" graph and uses it ONLY to expand query
terms that have NO footing in the codebase at all — terms that already
match real vocabulary are never touched (see `expand_query_terms`).

Deliberately Pointwise Mutual Information, not raw co-occurrence counts:
a naive "these two words appeared in the same file N times" graph is
vulnerable to exactly the "monster community" hub-domination problem
`subsystem_graph.py` already had to solve at the file-graph level — a
near-ubiquitous word like "configuration" would swamp every other
word's neighbor list purely by being everywhere, the same failure mode
in a different layer. PMI corrects for this by normalizing each pair's
co-occurrence against how common each word is INDEPENDENTLY:
`PMI(x,y) = log( P(x,y) / (P(x)*P(y)) )` — a hub word's PMI with
anything stays low even though its raw co-occurrence count is huge,
because P(x) is large in the denominator. Only positive PMI is kept
(PPMI — negative values mean "these words specifically avoid each
other," which isn't a useful association signal on a corpus this small
and is typically noisy to trust; Church & Hanks 1990 is the standard
reference for this technique, decades older than and independent of any
neural embedding method).

Every neighbor this module ever returns is, by construction, real
vocabulary already present somewhere in the repository's own text —
unlike an external synonym source, there is no way for it to invent a
word the codebase doesn't already use. What it CAN get wrong is
surfacing a real word that co-occurred for a coincidental, unrelated
reason (two words that happened to both appear in one changelog-style
comment) — `_MIN_CO_DOCUMENT_FREQUENCY` guards against trusting a
single-file coincidence, not against topical irrelevance in general.

Co-occurrence window is "appeared anywhere in the same file's pooled
text" (reusing `text_corpus.gather_file_text`'s existing per-file
blobs, zero extra I/O) — coarser than sentence/comment-block level,
which would be more precise but requires preserving block boundaries
`gather_file_text` currently flattens away. Documented trade-off, not
an oversight: a finer window is a legitimate future refinement, not
attempted here to keep this addition scoped and testable against the
same real benchmark that motivated it.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from code_intelligence.drp.tfidf import SubsystemTfIdfIndex, tokenize

# A file contributing more unique tokens than this to the co-occurrence
# corpus is capped (not skipped — the file's own TF-IDF document is
# untouched) at its most frequent tokens: pairwise counting is O(n^2)
# per file, and an outsized vocabulary (a giant generated/fixture file)
# would dominate build time for a diagnostic signal, not a correctness-
# critical one. 250 keeps a typical file's real vocabulary intact while
# bounding worst-case cost on repos with thousands of files.
_MAX_TOKENS_PER_FILE = 250

# A word pair that co-occurred in only one file is exactly the
# "coincidental changelog mention" risk named in this module's own
# docstring — require independent corroboration across at least two
# files before trusting the pair as a real association, not a fluke.
_MIN_CO_DOCUMENT_FREQUENCY = 2

# How many top-PPMI neighbors are retained per term. Bounds memory on
# large vocabularies; comfortably above any realistic expansion top_k.
_MAX_NEIGHBORS_STORED = 10

# How many PMI-derived neighbor terms an uncovered query term expands
# into by default — mirrors the same "a handful, not everything" intent
# as ContextResolver's own _MAX_CANDIDATES_TO_EXPAND.
_DEFAULT_EXPANSION_TOP_K = 3


@dataclass
class PmiWordGraph:
    neighbors: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    """term -> up to `_MAX_NEIGHBORS_STORED` (neighbor, ppmi) pairs,
    sorted descending by ppmi, ties broken lexicographically by
    neighbor — deterministic regardless of dict/set iteration order."""
    document_count: int = 0

    def top_neighbors(self, term: str, k: int) -> list[tuple[str, float]]:
        return self.neighbors.get(term, [])[:k]


def build_pmi_word_graph(file_texts: dict[str, str]) -> PmiWordGraph:
    """`file_texts` is the same per-file corpus `text_corpus.
    gather_file_text` already produces for Stage 2 — no new file reads.
    Iterates in sorted file-path order so the resulting graph is
    byte-identical across runs regardless of dict iteration order."""
    document_frequency: Counter[str] = Counter()
    co_document_frequency: Counter[tuple[str, str]] = Counter()
    document_count = 0

    for file_path in sorted(file_texts):
        tokens = sorted(set(tokenize(file_texts[file_path])))[:_MAX_TOKENS_PER_FILE]
        if not tokens:
            continue
        document_count += 1
        for token in tokens:
            document_frequency[token] += 1
        for i, first in enumerate(tokens):
            for second in tokens[i + 1 :]:
                co_document_frequency[(first, second)] += 1

    if document_count == 0:
        return PmiWordGraph(document_count=0)

    candidate_neighbors: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (first, second), co_df in sorted(co_document_frequency.items()):
        if co_df < _MIN_CO_DOCUMENT_FREQUENCY:
            continue
        # PPMI = log( P(x,y) / (P(x)*P(y)) ), clipped at 0 — negative
        # values (co-occur less than chance) aren't a useful "these are
        # related" signal and are discarded rather than surfaced as a
        # weak/misleading association.
        p_pair = co_df / document_count
        p_first = document_frequency[first] / document_count
        p_second = document_frequency[second] / document_count
        ppmi = math.log(p_pair / (p_first * p_second))
        if ppmi <= 0.0:
            continue
        candidate_neighbors[first].append((second, ppmi))
        candidate_neighbors[second].append((first, ppmi))

    neighbors: dict[str, list[tuple[str, float]]] = {}
    for term, scored in candidate_neighbors.items():
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        neighbors[term] = scored[:_MAX_NEIGHBORS_STORED]

    return PmiWordGraph(neighbors=neighbors, document_count=document_count)


@dataclass
class QueryExpansion:
    original_tokens: list[str]
    expanded_terms: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    """uncovered_term -> the PMI neighbors it expanded into, kept
    separate from original_tokens so DrpDiagnostics can report exactly
    which words were inferred and why — auditability, not a black box."""

    def all_tokens(self) -> list[str]:
        expansion = [
            neighbor for neighbors in self.expanded_terms.values() for neighbor, _ in neighbors
        ]
        return self.original_tokens + expansion


def expand_query_terms(
    query_tokens: list[str],
    file_tfidf: SubsystemTfIdfIndex,
    pmi_graph: PmiWordGraph,
    top_k: int = _DEFAULT_EXPANSION_TOP_K,
) -> QueryExpansion:
    """Coverage-gated expansion: a query term with ANY real presence in
    the file corpus (file_tfidf.idf has an entry for it) is left alone —
    it's already doing real, precise TF-IDF work, and expanding it would
    only add noise for no benefit. Only a term with zero document
    frequency anywhere (file_tfidf.idf.get(term) is None — it could
    never discriminate any file on its own regardless of query wording)
    is looked up in the PMI graph."""
    expanded_terms: dict[str, list[tuple[str, float]]] = {}
    for term in query_tokens:
        if file_tfidf.idf.get(term) is not None:
            continue
        neighbors = pmi_graph.top_neighbors(term, top_k)
        if neighbors:
            expanded_terms[term] = neighbors

    return QueryExpansion(original_tokens=list(query_tokens), expanded_terms=expanded_terms)
