"""DRP Stage 2b — per-subsystem TF-IDF profiles.

Pure Python/`math`, no libraries, no embeddings — a subsystem's profile
is exactly the term-frequency/inverse-document-frequency weights over
its own Stage 2a text blob, "document" meaning "one subsystem's
vocabulary" (not one file). Deliberately no domain-specific stopword
list beyond standard closed-class English function words, matching the
same restraint `context/lexical_symbol_probe.py` already applies for
the same reason: a keyword list tuned to expected queries would defeat
the point of a repository teaching ARCF its own structure.

Tokenization splits identifier text on `snake_case` underscores and
`camelCase`/`PascalCase` boundaries in addition to whitespace/punctuation
— a query written in plain English ("configuration", "watcher") should
match identifier fragments embedded in `ConfigurationWatcher` or
`configuration_watcher`, not just whole-identifier matches. It also
applies light, deterministic suffix-stripping (`_stem`) for common
English inflections (plural -s, verb -ing/-ed) — see `_stem`'s own
docstring for why and for the real case that motivated it.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_MIN_TOKEN_LEN = 2

# Suffix-stripping for the handful of English inflections that matter
# most for query/code vocabulary matching (plural -s/-es/-ies, verb
# forms -ing/-ed) — deliberately NOT a full Porter/Snowball stemmer or
# an external NLP library, matching this module's own "pure Python/
# math, no embeddings" restraint. Real, measured case: a Consul run
# scored the query "...when an agent registers it" as an exact ZERO
# against `Catalog.Register`'s own doc comment ("Register a service
# and/or check(s) in a node...") — despite it being close to a
# paraphrase of the query itself — purely because "registers" and
# "register" are different tokens without this. Deliberately
# conservative: every rule here is a well-known, low-risk English
# inflection pattern. A false NEGATIVE (two related words staying
# unmerged) is no worse than today's exact-match-only behavior; a false
# POSITIVE (unrelated words wrongly merged) would be a real regression,
# so short words are left untouched entirely and every branch requires
# the specific suffix shape it targets.
_ES_AFTER_SIBILANT_RE = re.compile(r"(?:ches|shes|sses|xes|zes)$")
_VOWEL_RE = re.compile(r"[aeiou]")
_MIN_STEMMABLE_LEN = 3


def _stem(word: str) -> str:
    if len(word) <= _MIN_STEMMABLE_LEN:
        return word
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif _ES_AFTER_SIBILANT_RE.search(word):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("us", "is", "ss")):
        word = word[:-1]
    if word.endswith("ing") and len(word) > 5 and _VOWEL_RE.search(word[:-3]):
        word = word[:-3]
    elif word.endswith("ed") and len(word) > 4 and _VOWEL_RE.search(word[:-2]):
        word = word[:-2]
    return word

# Below this many total (non-unique) tokens, a document's score is
# dampened proportionally — L2-normalized cosine similarity is well
# known to over-reward extremely short/sparse documents: a handful of
# matching terms dominates a small vector's normalized weight regardless
# of whether the document is actually substantive. Real, measured case
# (a real SQLAlchemy run): a 4-token utility function (`_event_on_load`,
# just its own name repeated, no docstring) outscored the real,
# 210-token `_LazyLoader` class — whose own docstring genuinely explains
# lazy loading — purely by being small enough that its few matching
# terms swamped its normalized vector. Ramped via `min(1.0, tokens/N)`,
# not a hard cutoff, so an adequately-sized document isn't penalized at
# all and a merely-small one isn't zeroed out, only an outlier this
# sparse — the same spirit as BM25's document-length normalization
# term, applied as a score multiplier rather than a full BM25 rewrite.
_MIN_SUBSTANTIAL_TOKENS = 30

# Below this many combined incoming calls (text_corpus.gather_scoring_
# units' unit_usage — real callers recorded in the already-built
# CallGraph), a unit's score is dampened proportionally, ramped the
# same way as length-confidence. Deliberately NOT a `test/`/`tests/`
# directory name check — that would misfire on a repository whose own
# purpose is testing, where real implementation could live near test-
# sounding paths. Incoming-call count is structural and holds
# regardless of what the repository is about: a real SQLAlchemy run
# found the actual `_LazyLoader` class and its sibling loader classes
# each called ~370-400 times from elsewhere in the codebase, while a
# competing test file's test classes mostly sat in single digits — test
# functions are discovered and invoked by a test runner, never called
# from an explicit call site, in every testing framework including one
# testing itself. The same signal separately explains a pure re-export
# module (zero symbols of its own, hence trivially zero incoming calls)
# scoring only from an unrelated docstring.
_MIN_CALLS_FOR_FULL_CONFIDENCE = 20

# Below this many of the query's OWN distinct terms matching a document
# at all (any nonzero weight, regardless of how large), that document's
# score is dampened proportionally, ramped the same way as length/usage
# confidence. Real, measured case (a real FlatBuffers run, 2026-08-10): a
# 9-distinct-term query ("How does the garbage collector reclaim unused
# heap memory during a stop-the-world pause") scored 0.30 raw against
# `tests/union_vector/union_vector_generated.h` — HIGHER than a genuine
# on-topic query's 0.37 — entirely from ONE matched term ("unus", the
# shared stem of the query's "unused" and an unrelated enum sentinel
# `Character_Unused` in that test fixture); the other 8 distinct terms
# ("garbage", "collector", "reclaim", "heap", "memory", "stop", "world",
# "pause") matched nothing. Raw cosine-similarity magnitude and term-
# coverage breadth are genuinely independent quantities — a single
# highly-weighted term can produce a large raw score with terrible
# coverage, which is exactly what happened, so this cannot be folded
# into `_MIN_SUBSTANTIAL_TOKENS`/`_MIN_CALLS_FOR_FULL_CONFIDENCE` (both
# properties of the DOCUMENT alone); it has to compare against the
# QUERY's own term count, computed fresh per call in `.score()` rather
# than precomputed into `TfIdfProfile`. Capped at the query's own
# distinct-term count (see `.score()`) so a genuinely narrow query (e.g.
# a single symbol name) is never penalized for lacking terms it never
# had — this only dampens a multi-term query where most of its own terms
# are absent from the document, not short queries in general.
#
# Value chosen at 4, not the first value tried (3) — 3 was falsified by
# the full 5-ground-truth-repo sweep this fix is required to pass (see
# this project's own established discipline: "any change to a shared
# corpus/scoring module needs the full 5-repo sweep before/after, not
# just the DRP unit suite"). At floor=3, a real SQLAlchemy ground-truth
# case (already an acknowledged near-tie between `lib/sqlalchemy/orm`,
# 0.8875, and its own paired `test/orm::test`, 0.8822 — a razor-thin,
# pre-existing ambiguity, not something this fix created) FLIPPED to the
# wrong winner: coverage dampening reduced the correct subsystem's raw
# score by slightly more than the test directory's, because the test
# directory's top-scoring files happen to touch marginally more of the
# query's distinct terms even though the real implementation's top file
# scored higher in raw magnitude. Floor=4 was found, by testing floors
# 1-4 directly against both passing ground-truth repos (SQLAlchemy,
# Django) and the FlatBuffers adversarial case together, to be the
# smallest value that keeps both ground-truth winners correct AND still
# gives the adversarial case's confidence the correct (lower-than-a-
# genuine-match) ordering — not a first-guess default.
_MIN_DISTINCT_TERMS_FOR_FULL_CONFIDENCE = 4

# Standard closed-class English function words only — same restraint as
# lexical_symbol_probe.py's own stopword list, kept as DRP's own copy
# rather than importing that module's private constant across an
# unrelated module boundary.
STOPWORDS: frozenset[str] = frozenset(
    {
        "about", "above", "after", "again", "against", "all", "also",
        "although", "always", "an", "and", "any", "are", "around", "as",
        "at", "be", "because", "been", "before", "being", "below",
        "between", "both", "but", "by", "can", "cannot", "could", "did",
        "do", "does", "doing", "down", "during", "each", "either", "even",
        "every", "few", "for", "from", "further", "had", "has", "have",
        "having", "here", "how", "however", "if", "in", "into", "is",
        "it", "its", "itself", "just", "like", "make", "makes", "may",
        "might", "more", "most", "must", "neither", "no", "nor", "not",
        "now", "of", "off", "on", "once", "only", "onto", "or", "other",
        "our", "out", "over", "own", "please", "same", "should", "since",
        "so", "some", "such", "than", "that", "the", "their", "them",
        "then", "there", "these", "they", "this", "those", "through",
        "thus", "to", "too", "under", "until", "up", "upon", "us", "used",
        "using", "very", "was", "we", "were", "what", "when", "where",
        "whether", "which", "while", "who", "whom", "why", "will", "with",
        "within", "without", "would", "you", "your",
    }
)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _WORD_RE.findall(text):
        for underscore_part in raw.split("_"):
            if not underscore_part:
                continue
            for part in _CAMEL_BOUNDARY_RE.split(underscore_part):
                lowered = part.lower()
                if len(lowered) < _MIN_TOKEN_LEN or lowered in STOPWORDS:
                    continue
                tokens.append(_stem(lowered))
    return tokens


@dataclass
class TfIdfProfile:
    subsystem_path: str
    weights: dict[str, float] = field(default_factory=dict)
    """term -> L2-normalized, log-scaled tf*idf weight (see
    `build_tfidf_index`), precomputed so query scoring is a single
    dict-lookup dot product — effectively cosine similarity — rather
    than recomputing tf/idf per query."""
    token_count: int = 0
    """Raw (non-unique) token count of this document's own source text —
    used only to compute the length-confidence dampening in `.score()`;
    not part of the cosine similarity itself."""
    usage_count: int = 0
    """Combined incoming-call count from `text_corpus.gather_scoring_
    units`'s `unit_usage` (0 when the caller didn't supply usage data —
    see `build_tfidf_index`'s own default) — used only to compute the
    usage-confidence dampening in `.score()`; not part of the cosine
    similarity itself."""
    usage_known: bool = False
    """Whether usage data was supplied at all for this document. Kept
    separate from `usage_count == 0` being ambiguous between "known to
    have zero callers" and "caller didn't provide usage data" — only the
    former should be dampened; the latter (e.g. every existing test that
    builds a `SubsystemTfIdfIndex` from plain text, with no CallGraph in
    the picture at all) must stay at full confidence, unchanged."""


@dataclass
class SubsystemTfIdfIndex:
    profiles: dict[str, TfIdfProfile]
    idf: dict[str, float]

    def score(self, query_tokens: list[str]) -> dict[str, float]:
        """Dot product of the query's term counts against each
        subsystem's tf*idf weight vector (cosine similarity), scaled by
        a length-confidence factor (`_MIN_SUBSTANTIAL_TOKENS`), when
        usage data is available a usage-confidence factor
        (`_MIN_CALLS_FOR_FULL_CONFIDENCE`), and a coverage-confidence
        factor (`_MIN_DISTINCT_TERMS_FOR_FULL_CONFIDENCE`) — the first
        two dampen documents too sparse or too rarely-referenced to
        trust at full confidence, the third dampens a match driven by a
        single coincidentally-matching query term while the rest of the
        query's own vocabulary is absent (see that constant's own
        docstring for the real case that motivated it). Deterministic,
        order-independent since it sums over the fixed `self.profiles`
        keys."""
        query_counts = Counter(query_tokens)
        distinct_query_terms = set(query_counts)
        coverage_floor = min(_MIN_DISTINCT_TERMS_FOR_FULL_CONFIDENCE, len(distinct_query_terms))
        scores: dict[str, float] = {}
        for path, profile in self.profiles.items():
            raw_score = sum(
                count * profile.weights.get(term, 0.0) for term, count in query_counts.items()
            )
            length_confidence = min(1.0, profile.token_count / _MIN_SUBSTANTIAL_TOKENS)
            usage_confidence = (
                min(1.0, profile.usage_count / _MIN_CALLS_FOR_FULL_CONFIDENCE)
                if profile.usage_known
                else 1.0
            )
            matched_terms = sum(
                1 for term in distinct_query_terms if profile.weights.get(term, 0.0) > 0.0
            )
            coverage_confidence = (
                min(1.0, matched_terms / coverage_floor) if coverage_floor > 0 else 1.0
            )
            scores[path] = raw_score * length_confidence * usage_confidence * coverage_confidence
        return scores


def build_tfidf_index(
    subsystem_texts: dict[str, str], unit_usage: dict[str, int] | None = None
) -> SubsystemTfIdfIndex:
    """`subsystem_texts` must already be in deterministic key order
    (`text_corpus.gather_subsystem_text` guarantees this) — iteration
    order here only affects intermediate dict construction, never the
    resulting weights, but preserving it keeps every intermediate
    structure reproducible for debugging.

    `unit_usage` is optional (defaults to `None`, meaning no usage-
    confidence dampening — every existing caller that scores plain text
    with no CallGraph involved keeps its exact prior behavior). When
    supplied (see `text_corpus.gather_scoring_units`), a key missing
    from it is treated as a genuine zero — a document usage data was
    collected for but that turned out to have no recorded callers,
    which is exactly the case this dampening targets."""
    token_lists = {path: tokenize(text) for path, text in subsystem_texts.items()}
    doc_count = len(token_lists) or 1

    document_frequency: Counter[str] = Counter()
    for tokens in token_lists.values():
        document_frequency.update(set(tokens))

    idf = {
        term: math.log((doc_count + 1) / (df + 1)) + 1.0
        for term, df in sorted(document_frequency.items())
    }

    profiles: dict[str, TfIdfProfile] = {}
    for path, tokens in token_lists.items():
        counts = Counter(tokens)
        # Sublinear (log) tf scaling + L2-normalized document vectors —
        # standard cosine-similarity-style TF-IDF (Manning/Raghavan/
        # Schütze, "Introduction to Information Retrieval" §6.4), not an
        # arbitrary tuning knob. Plain term_frequency = count/total_terms
        # was found to badly misroute the real Traefik benchmark: a
        # small, single-purpose subsystem (`cmd`, mostly one file
        # parsing a `Configuration` struct) got an inflated tf for
        # "configuration" purely from having few total tokens, outscoring
        # the larger, correct subsystem (`pkg/server`) whose relevant
        # vocabulary is diluted across more files. Log-scaling each raw
        # count caps how much a single repeated word can dominate a
        # small document, and L2-normalizing the resulting vector (so
        # every subsystem's weight vector has unit length regardless of
        # its total vocabulary size) makes `score`'s dot product an
        # actual cosine similarity — comparable across subsystems of
        # very different sizes, rather than favoring whichever subsystem
        # happens to be smallest or largest.
        raw_weights = {
            term: (1.0 + math.log(count)) * idf.get(term, 0.0) for term, count in counts.items()
        }
        norm = math.sqrt(sum(weight * weight for weight in raw_weights.values())) or 1.0
        weights = {term: weight / norm for term, weight in raw_weights.items()}
        profiles[path] = TfIdfProfile(
            subsystem_path=path,
            weights=weights,
            token_count=len(tokens),
            usage_count=unit_usage.get(path, 0) if unit_usage is not None else 0,
            usage_known=unit_usage is not None,
        )

    return SubsystemTfIdfIndex(profiles=profiles, idf=idf)
