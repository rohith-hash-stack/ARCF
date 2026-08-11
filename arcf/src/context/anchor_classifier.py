"""Pre-Expansion Anchor Classification — ARCF experiment (2026-08-08).

Feature-flagged (code_intelligence/service.py's `enable_anchor_classification`
/ `enable_confidence_propagation`, both default False), deterministic,
no embeddings, no vector search, no new SLM stage. Tests whether tagging
each candidate anchor with an explicit confidence BEFORE graph expansion —
rather than treating every lexically-matched name as an equally valid
seed, as `probe_symbol_names` does today — improves canonical-file recall
without a redesign.

Tiers implemented (deliberately skipping the semantic/embedding tier the
brief excludes; tier numbering matches the brief's, not sequential):

  Tier 1 (EXACT, confidence 1.0)  — an exact, real Symbol.name found via a
    quoted/backtick token or a bare identifier-shaped word in the query, OR
    via a deterministic morphological reconstruction of the query's words
    (generate_morphological_candidates / classify_morphological_anchors,
    added 2026-08-08) — "an idea from the user, not synonym lookup: a
    generic thesaurus would be actively harmful for code identifiers
    ('loading' -> 'cargo' is meaningless), so this strips common suffixes
    (-ing/-ed/-es/-s) and recombines adjacent query words with common
    code-naming suffixes (-er/-or) and casing conventions, e.g. "lazy
    loading" -> stem "load" -> "LazyLoader". Every generated candidate is
    then checked against SymbolIndex.find_by_name() — only a REAL exact
    match is ever kept, so a wrong guess is silently discarded, never a
    false positive; this is what makes it safe to treat these as
    genuinely Tier 1 rather than a fuzzier, lower-confidence tier.
    "Exact" means SymbolIndex.find_by_name() directly, never the prefix/
    substring probe — a materially stronger signal than Tier 3. Ambiguity-
    gated (`_TIER1_AMBIGUITY_CAP`, added 2026-08-08 after a real Consul
    regression): an exact match is only trusted if the matched name isn't
    itself so generic it matches many unrelated symbols repo-wide (a word
    like "request" or "service" can be a real identifier in dozens of
    unrelated files) — see `_is_precise_match`'s own docstring.
  Tier 3 (LEXICAL, confidence 0.5) — reuses lexical_symbol_probe.
    probe_symbol_names_ranked() (prefix/substring/camelCase/snake_case
    overlap, same eligibility/ambiguity rules as the unranked
    probe_symbol_names), just tagged with a fixed confidence instead of
    being merged in as undifferentiated SUPPORTING evidence. Uses the
    RANKED selection rule, not scan order (2026-08-10 fix — a real
    FlatBuffers run found Tier 3's original probe_symbol_names call
    dropped a query-relevant class in favor of unrelated same-rooted
    names purely because of incidental symbol-scan order, the exact
    failure mode probe_symbol_names_ranked was already built and
    validated to fix elsewhere in this codebase, on a real SQLAlchemy
    regression, but had never been wired into Tier 3 itself — only into
    a separate, off-by-default ranked-seed-selection experiment that
    `enable_anchor_classification` (this module) bypasses entirely).
  Tier 4 (INCIDENTAL, confidence 0.35 — recalibrated, see TIER_CONFIDENCE's
    own comment) — filename/path matches only
    (lexical_symbol_probe.probe_file_paths). The brief also lists
    comments/docstrings/string literals under this tier; that half is
    NOT implemented here and should not be assumed present — no
    LanguageAnalyzer captures docstrings/comments in ARCF's IR today
    (Symbol has no docstring field, already documented as a known
    limitation in context/subsystem_localizer.py), so "appears only in
    a comment" isn't something this deterministic layer can check
    without new analyzer work, which is out of scope for this
    experiment ("reuse existing metadata", no new indexing).
  Tier 5 (TRANSITIVE) is not assigned here — it's a property of hop
    distance during expansion, computed post-hoc from
    ContextResolutionResult's own `reason`/`justification_chain` strings
    by `decay_confidence()` below, not during classification.
"""

import re
from dataclasses import dataclass
from enum import IntEnum

from code_intelligence.symbol_index import SymbolIndex
from context.lexical_symbol_probe import probe_file_paths, probe_symbol_names_ranked
from workspace.scanner import ScannedFile


class AnchorTier(IntEnum):
    EXACT = 1
    LEXICAL = 3
    INCIDENTAL = 4
    TRANSITIVE = 5


TIER_CONFIDENCE: dict[AnchorTier, float] = {
    AnchorTier.EXACT: 1.0,
    AnchorTier.LEXICAL: 0.5,
    # Recalibrated from the brief's original 0.15 after the real SQLAlchemy
    # validation run (2026-08-08): the brief's Tier 4 covers a broad bucket
    # ("comments, docstrings, string literals, filenames, README") where
    # 0.15 is a reasonable default for a genuinely incidental match. This
    # module only implements the filename/path slice of that bucket —
    # comments/docstrings aren't in ARCF's IR at all (see module docstring)
    # — and for the real benchmarked query, filename matching was the ONLY
    # tier (of four) that found either canonical file at all: neither
    # named an exact identifier (no Tier 1) and Tier 3's symbol-level probe
    # reproduced the same generic noise as every prior experiment this
    # session, never reaching either file. Scoring the one tier that
    # actually worked at the brief's original 0.15 made both files rank
    # WORSE than doing nothing (score collapsed 0.42/0.46 -> 0.063/0.069).
    # 0.35 keeps the intended ordering (1 > 3 > 4) while reflecting that a
    # file whose own name matches the query is real, if weaker, evidence —
    # not the same thing as a match buried in an unrelated file's comment.
    AnchorTier.INCIDENTAL: 0.35,
}
# child_confidence = parent_confidence * TRANSITIVE_DECAY_FACTOR, applied
# once per hop — see decay_confidence(). A fixed, hand-specified constant,
# not fitted; consistent with every other deterministic constant in this
# codebase (_MAX_MATCHES_PER_NAME, _LEXICAL_PROBE_RECOVERY_DEPTH, ...).
TRANSITIVE_DECAY_FACTOR = 0.6

# Tier 1 ambiguity guard (2026-08-08 fix): a literal or morphologically-
# reconstructed word that happens to match MANY real symbols repo-wide is
# not a precise signal — it's a generic identifier (e.g. "request",
# "service", "Add") coincidentally shared by many unrelated classes/
# functions, not evidence the query is about any one of them. Confirmed
# as a real, measured regression, not a hypothetical: on the real Consul
# run, Tier 1 anchors ("Add", "request", "service", "setQueryOptions",
# "setWriteOptions") added 66 files, none of them the actual target
# (agent/catalog_endpoint.go), because every exact match was trusted at
# full confidence regardless of how many unrelated symbols shared the
# name. Same threshold as every other ambiguity guard already in this
# codebase (lexical_symbol_probe._MAX_MATCHES_PER_NAME,
# context_resolver._MAX_CANDIDATES_TO_EXPAND,
# service._CLASS_METHOD_AMBIGUITY_CAP) — a name matching this many or
# fewer real symbols is still precise enough to trust; beyond it, an
# "exact" match carries no more real signal than a generic guess and
# must not receive Tier 1's unconditional confidence.
_TIER1_AMBIGUITY_CAP = 5

_HOP_RE = re.compile(r"\(hop (\d+)\)")
_QUOTED_OR_BACKTICK_RE = re.compile(r"[`'\"]([A-Za-z_][A-Za-z0-9_.]{1,80})[`'\"]")
_BARE_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,60}\b")

# Morphological candidate reconstruction (2026-08-08) — see module
# docstring's Tier 1 entry. Deliberately just suffix-stripping + agentive-
# suffix recombination, not a real stemmer (Porter/Snowball) and not a
# dictionary: small, auditable, and every output is verified against a
# real symbol before ever being trusted, so imprecision here costs
# nothing but a discarded candidate, never a wrong answer.
_MORPH_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_MIN_MORPH_WORD_LEN = 3
# Longest-suffix-first so "loading" strips to "load", not "loading" minus
# a shorter accidental match.
_SUFFIX_STRIP_ORDER: tuple[str, ...] = ("ing", "ed", "es", "s")
_AGENT_SUFFIXES: tuple[str, ...] = ("er", "or")
# Bounds candidate-generation cost the same way _MAX_MATCHED_NAMES bounds
# lexical_symbol_probe's own output — a long query shouldn't turn into an
# unbounded number of SymbolIndex lookups. Raised from an initial 40 after
# the real SQLAlchemy validation run (2026-08-08) found the leading-
# underscore variant (below) needed room too: SQLAlchemy's actual
# internal classes/functions are `_LazyLoader`/`_load_on_ident`, not
# `LazyLoader`/`load_on_ident` — PEP 8's "internal use" convention, a
# common real-world pattern, not specific to this one repo.
_MAX_MORPHOLOGICAL_CANDIDATES = 100


@dataclass(frozen=True)
class SymbolAnchor:
    name: str
    tier: AnchorTier
    confidence: float


@dataclass(frozen=True)
class FileAnchor:
    file_path: str
    tier: AnchorTier
    confidence: float


def _is_precise_match(name: str, symbol_index: SymbolIndex) -> bool:
    """True when `name` is a real symbol AND not so ambiguous (matching
    more than `_TIER1_AMBIGUITY_CAP` real symbols repo-wide) that an
    exact string match no longer carries real signal. Shared by both
    Tier 1 paths (literal-word and morphological) so a generic word
    can't earn full confidence through either route."""
    matches = symbol_index.find_by_name(name)
    return bool(matches) and len(matches) <= _TIER1_AMBIGUITY_CAP


def _stem(word: str) -> str:
    lowered = word.lower()
    for suffix in _SUFFIX_STRIP_ORDER:
        if lowered.endswith(suffix) and len(lowered) - len(suffix) >= _MIN_MORPH_WORD_LEN:
            return lowered[: -len(suffix)]
    return lowered


def generate_morphological_candidates(raw_request: str) -> list[str]:
    """Deterministic candidate *identifier strings* reconstructed from the
    query's own words — never verified against anything here, that's
    classify_morphological_anchors' job. Single-word candidates (stem +
    agentive suffix, both cased) and adjacent-word-pair candidates
    (CamelCase and snake_case joins, with and without an agentive
    suffix on the second word) — e.g. "lazy loading" yields "LazyLoader"
    among many other, mostly-wrong guesses; that's expected and fine,
    since nothing here is trusted until SymbolIndex.find_by_name()
    confirms it's real."""
    words = [w for w in _MORPH_WORD_RE.findall(raw_request) if len(w) >= _MIN_MORPH_WORD_LEN]
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(candidate: str) -> None:
        if candidate and candidate not in seen and len(candidates) < _MAX_MORPHOLOGICAL_CANDIDATES:
            seen.add(candidate)
            candidates.append(candidate)

    # Adjacent-word combinations FIRST, deliberately: they're the higher-
    # value candidates (a class-name-shaped join of two real query words
    # is far more likely to be a real symbol than a single stemmed word
    # plus a bare agentive suffix), and the cap above must not let a long
    # query's single-word noise crowd them out before they're ever tried.
    # Each CamelCase-shaped candidate's leading-underscore variant is
    # added immediately alongside it (not in a separate pass at the end)
    # so cap truncation can't separate them.
    for i in range(len(words) - 1):
        stem_a, stem_b = _stem(words[i]), _stem(words[i + 1])
        joined = stem_a.capitalize() + stem_b.capitalize()
        _add(joined)
        _add(f"_{joined}")
        _add(f"{stem_a}_{stem_b}")
        for suffix in _AGENT_SUFFIXES:
            agentive = joined + suffix
            _add(agentive)
            _add(f"_{agentive}")
            _add(f"{stem_a}_{stem_b}_{suffix}")

    for word in words:
        stem = _stem(word)
        for suffix in _AGENT_SUFFIXES:
            agentive = stem.capitalize() + suffix
            _add(agentive)
            _add(f"_{agentive}")
            _add(stem + suffix)
            _add(f"_{stem}{suffix}")

    return candidates


def classify_morphological_anchors(
    raw_request: str, symbol_index: SymbolIndex
) -> list[SymbolAnchor]:
    """Verifies generate_morphological_candidates' output against the real
    symbol table — only an exact SymbolIndex.find_by_name() hit survives,
    so every returned anchor is a confirmed real symbol, not a guess;
    that's what justifies Tier 1 confidence (1.0) rather than a
    discounted one, same standard as the literal-word Tier 1 path."""
    verified: list[SymbolAnchor] = []
    seen: set[str] = set()
    for candidate in generate_morphological_candidates(raw_request):
        if candidate in seen:
            continue
        if _is_precise_match(candidate, symbol_index):
            seen.add(candidate)
            verified.append(
                SymbolAnchor(candidate, AnchorTier.EXACT, TIER_CONFIDENCE[AnchorTier.EXACT])
            )
    return verified


def classify_symbol_anchors(raw_request: str, symbol_index: SymbolIndex) -> list[SymbolAnchor]:
    """Tier 1 (literal exact words, then verified morphological
    reconstructions) then Tier 3, in that order, each name appearing at
    most once (a name promoted to Tier 1 is excluded from Tier 3's list
    even if the unrestricted probe would also have matched it — the
    stronger signal wins, it doesn't stack)."""
    candidate_names: set[str] = set()
    for match in _QUOTED_OR_BACKTICK_RE.finditer(raw_request):
        candidate_names.add(match.group(1))
    for match in _BARE_IDENTIFIER_RE.finditer(raw_request):
        candidate_names.add(match.group(0))

    tier1: list[SymbolAnchor] = []
    seen: set[str] = set()
    # Sorted for deterministic output order — candidate_names is a set,
    # iteration order would otherwise depend on hash randomization.
    for name in sorted(candidate_names):
        if name in seen:
            continue
        if _is_precise_match(name, symbol_index):
            seen.add(name)
            tier1.append(SymbolAnchor(name, AnchorTier.EXACT, TIER_CONFIDENCE[AnchorTier.EXACT]))

    for anchor in classify_morphological_anchors(raw_request, symbol_index):
        if anchor.name in seen:
            continue
        seen.add(anchor.name)
        tier1.append(anchor)

    tier3 = [
        SymbolAnchor(name, AnchorTier.LEXICAL, TIER_CONFIDENCE[AnchorTier.LEXICAL])
        for name in probe_symbol_names_ranked(raw_request, symbol_index)
        if name not in seen
    ]
    return [*tier1, *tier3]


def classify_file_anchors(raw_request: str, files: list[ScannedFile]) -> list[FileAnchor]:
    """Tier 4 — filename/path matches only, see module docstring for why
    comments/docstrings/string literals are excluded from this
    implementation."""
    return [
        FileAnchor(path, AnchorTier.INCIDENTAL, TIER_CONFIDENCE[AnchorTier.INCIDENTAL])
        for path in probe_file_paths(raw_request, files)
    ]


def hop_from_reason(reason: str) -> int:
    """Extracts the hop number ContextResolver already embeds in its
    reason strings (e.g. "calls X (hop 2)") — reused, not re-derived.
    "defines X" is hop 0 (the anchor's own file, no decay). A reason with
    no explicit hop number ("calls X" from the module-level call-site
    path, "extends X" from subclass expansion) is a single structural
    step from the anchor and treated as hop 1."""
    match = _HOP_RE.search(reason)
    if match:
        return int(match.group(1))
    if reason.startswith("defines "):
        return 0
    return 1


def decay_confidence(anchor_confidence: float, hop: int) -> float:
    """child_confidence = parent_confidence * TRANSITIVE_DECAY_FACTOR,
    applied once per hop. hop=0 (the anchor's own defining file) returns
    the anchor's confidence unchanged."""
    return round(anchor_confidence * (TRANSITIVE_DECAY_FACTOR**hop), 6)
