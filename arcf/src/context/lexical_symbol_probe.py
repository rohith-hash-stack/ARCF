"""Lexical/stemmed symbol probing (ARCF classifier-gap fix, layer 3 of the
2026-08-06 session handoff's §4.3) — deterministic, keyword-list-free
recovery for queries that name no concrete symbol and no file/path, so
neither target_names-based symbol resolution nor evidence_fallback's tier 1
query-referenced-file matching finds anything, but whose wording still
shares an obvious lexical root with a real symbol or file in the
repository.

Concretely: "Add support for a custom dependency cache invalidation
strategy" names no exact symbol, but "dependency" shares a 6-character
prefix with real symbols like `Dependant`/`Depends`/`solve_dependencies`.
This module tokenizes the raw request, drops closed-class stopwords and
short tokens, and prefix-substring-probes what remains against every real
symbol name and scanned file basename — never against a token's raw form
(too noisy for anything shorter) and never a full stemmer (out of scope;
would add a dependency and false precision this tool doesn't need). A
fixed 6-character prefix is a conservative, deterministic, easily-audited
stand-in for stemming: long enough to avoid matching unrelated short
words, short enough to survive common suffixes (dependency/dependencies/
depends/dependent all share it).

Every name/path this module returns is real — read directly off the
already-built SymbolIndex or already-scanned file list — never a guess or
a fabricated identifier; this only changes what existing exact-match
machinery gets asked to look up, not how lookups themselves work.

Deliberately no domain-specific/task-verb stopword list beyond standard
closed-class function words: filtering on "what SWE tasks tend to say"
would just be keyword-tuning this module to whatever query set it was
built against, the opposite of the deterministic-and-general goal this
whole layered fix (§4 of the handoff) is going for.
"""

import re
from collections import defaultdict
from pathlib import Path

from code_intelligence.symbol_index import SymbolIndex
from workspace.scanner import ScannedFile

_MIN_TOKEN_LEN = 6
_PROBE_PREFIX_LEN = 6
_MAX_MATCHED_NAMES = 20
_MAX_MATCHED_FILES = 8
# A probed name that exactly matches this many or fewer real symbols is a
# precise signal (e.g. "Dependant"/"Depends"); one matching dozens of
# unrelated symbols across a large repository (e.g. a generic name like
# "middleware" recurring across many unrelated example apps in a monorepo)
# carries no real signal and, worse, turns into one independent call-graph
# traversal per match — real, measured cost: probing a 59k-symbol
# monorepo's index surfaced a 79-way-ambiguous name that alone caused a
# MemoryError once fed through to full resolution.
_MAX_MATCHES_PER_NAME = 5

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")

# Standard closed-class English function words only (articles,
# prepositions, conjunctions, auxiliary/modal verbs, pronouns) — not
# tuned to any particular query set.
_STOPWORDS: frozenset[str] = frozenset(
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


def _probe_prefixes(raw_request: str) -> list[str]:
    seen: set[str] = set()
    prefixes: list[str] = []
    for match in _WORD_RE.finditer(raw_request):
        word = match.group(0).lower()
        if len(word) < _MIN_TOKEN_LEN or word in _STOPWORDS:
            continue
        prefix = word[:_PROBE_PREFIX_LEN]
        if prefix not in seen:
            seen.add(prefix)
            prefixes.append(prefix)
    return prefixes


def probe_symbol_names(raw_request: str, symbol_index: SymbolIndex) -> list[str]:
    """Real, exact Symbol.name values whose lowercased form contains one
    of the query's probe prefixes as a substring — safe to feed straight
    into ContextResolver.resolve()'s target_names, since every returned
    name already exists in this repository's real symbol table."""
    prefixes = _probe_prefixes(raw_request)
    if not prefixes:
        return []

    # Two passes, deliberately: ambiguity (how many real symbols share a
    # name) can only be known after scanning every symbol, so a name can't
    # be judged safe to return until the full count is in — a single pass
    # that stopped at the first occurrence would let a 79-way-ambiguous
    # name straight through on its first (innocent-looking) sighting.
    counts: dict[str, int] = defaultdict(int)
    first_seen_order: list[str] = []
    for symbol in symbol_index.all():
        if len(symbol.name) < _PROBE_PREFIX_LEN:
            continue
        lowered = symbol.name.lower()
        if not any(prefix in lowered for prefix in prefixes):
            continue
        if counts[symbol.name] == 0:
            first_seen_order.append(symbol.name)
        counts[symbol.name] += 1

    matched: list[str] = []
    for name in first_seen_order:
        if counts[name] > _MAX_MATCHES_PER_NAME:
            continue
        matched.append(name)
        if len(matched) >= _MAX_MATCHED_NAMES:
            break
    return matched


def probe_file_paths(raw_request: str, files: list[ScannedFile]) -> list[str]:
    """Same probing, against scanned file basenames (extension stripped)
    rather than symbol names — catches cases where the relevant unit is a
    whole file (an unsupported language, a config file) rather than a
    parsed Symbol."""
    prefixes = _probe_prefixes(raw_request)
    if not prefixes:
        return []

    matched: list[str] = []
    for file in files:
        basename = Path(file.relative_path).stem.lower()
        if len(basename) < _PROBE_PREFIX_LEN:
            continue
        if any(prefix in basename for prefix in prefixes):
            matched.append(file.relative_path)
            if len(matched) >= _MAX_MATCHED_FILES:
                break
    return matched
