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


def probe_prefixes(raw_request: str) -> list[str]:
    """Public wrapper around this module's own prefix-extraction (see
    module docstring) — exposed for callers that need the actual prefix
    list, not just a boolean match (shares_lexical_root). Used by
    context/subsystem_localizer.py's ARCF root-cause validation
    experiment to score which repository subsystem a query's wording
    concentrates in, before restricting lexical symbol probing to it."""
    return _probe_prefixes(raw_request)


def shares_lexical_root(text: str, raw_request: str) -> bool:
    """Public wrapper around this module's own prefix-probing technique
    (see module docstring) for callers outside symbol/file-path probing —
    ARCF Phase 7's LSE candidate pruning (context/evidence_validator.py)
    reuses this rather than re-implementing prefix matching a second way,
    so "what counts as a lexical match" stays defined in exactly one
    place. True when `text`'s lowercased form contains any of
    `raw_request`'s probe prefixes as a substring."""
    prefixes = _probe_prefixes(raw_request)
    if not prefixes:
        return False
    lowered = text.lower()
    return any(prefix in lowered for prefix in prefixes)


def probe_symbol_names(
    raw_request: str,
    symbol_index: SymbolIndex,
    restrict_to_prefixes: tuple[str, ...] | None = None,
) -> list[str]:
    """Real, exact Symbol.name values whose lowercased form contains one
    of the query's probe prefixes as a substring — safe to feed straight
    into ContextResolver.resolve()'s target_names, since every returned
    name already exists in this repository's real symbol table.

    `restrict_to_prefixes` (ARCF subsystem-localization experiment,
    context/subsystem_localizer.py): when given, only names with at
    least one occurrence whose `file_path` starts with one of these
    directory prefixes are eligible for the returned list. Ambiguity is
    still counted globally (every real occurrence anywhere in the
    repository, restricted or not) — this only changes which NAMES are
    eligible to be returned, not the safety bound on how ambiguous a
    returned name is allowed to be (see _MAX_MATCHES_PER_NAME's own
    comment for why that bound exists and must stay global: a name fed
    into ContextResolver.resolve() still resolves against the WHOLE
    index regardless of why it was selected). Filtering happens before
    the _MAX_MATCHED_NAMES cap, not after: without this, a subsystem's
    own relevant symbol could already be excluded from the unrestricted
    top-20 by unrelated same-rooted symbols encountered earlier in
    symbol_index.all()'s iteration order, making restriction downstream
    of an unrestricted probe unable to ever recover it — this is exactly
    the gap the real SQLAlchemy experiment (2026-08-08) found."""
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
    in_scope: set[str] = set()
    for symbol in symbol_index.all():
        if len(symbol.name) < _PROBE_PREFIX_LEN:
            continue
        lowered = symbol.name.lower()
        if not any(prefix in lowered for prefix in prefixes):
            continue
        if counts[symbol.name] == 0:
            first_seen_order.append(symbol.name)
        counts[symbol.name] += 1
        if restrict_to_prefixes and symbol.file_path.startswith(restrict_to_prefixes):
            in_scope.add(symbol.name)

    candidates = first_seen_order
    if restrict_to_prefixes is not None:
        candidates = [name for name in first_seen_order if name in in_scope]

    matched: list[str] = []
    for name in candidates:
        if counts[name] > _MAX_MATCHES_PER_NAME:
            continue
        matched.append(name)
        if len(matched) >= _MAX_MATCHED_NAMES:
            break
    return matched


def probe_symbol_names_ranked(
    raw_request: str,
    symbol_index: SymbolIndex,
    restrict_to_prefixes: tuple[str, ...] | None = None,
) -> list[str]:
    """ARCF candidate-ranking experiment (2026-08-08, SQLAlchemy-only
    validation of the principal-architect design review's Stage A):
    same eligibility rules as `probe_symbol_names` (min name length,
    prefix-substring match, the same global `_MAX_MATCHES_PER_NAME`
    ambiguity cap, the same `restrict_to_prefixes` scoping) — the only
    difference is which names win the `_MAX_MATCHED_NAMES` slots when
    more eligible names exist than the cap allows.

    `probe_symbol_names` fills those slots in raw `symbol_index.all()`
    scan order — an accident of iteration, not a relevance judgment.
    This ranks eligible names by (a) how many *distinct* query prefixes
    the name matches — a name matching two or more of the query's own
    words ("load_strategy" matching both "loadin" and "strate") reflects
    more of the query's actual vocabulary than one matching a single
    coincidental 6-character overlap ("attr_is_internal_proxy" matching
    only "intern"); (b) global ambiguity count ascending — fewer
    repo-wide occurrences means a more specific, less generic name.
    Both signals are already computed by the unranked function; this
    only changes the selection rule applied to them, not what's
    eligible in the first place — see this repo's subsystem-localization
    experiment write-up (`docs/ARCF_SESSION_HANDOFF_2026-08-08.md`, §8)
    for the real run where the unranked cap dropped `orm/loading.py`'s
    own symbols in favor of unrelated same-rooted matches."""
    prefixes = _probe_prefixes(raw_request)
    if not prefixes:
        return []

    counts: dict[str, int] = defaultdict(int)
    matched_prefix_counts: dict[str, int] = defaultdict(int)
    first_seen_order: list[str] = []
    in_scope: set[str] = set()
    for symbol in symbol_index.all():
        if len(symbol.name) < _PROBE_PREFIX_LEN:
            continue
        lowered = symbol.name.lower()
        hits = sum(1 for prefix in prefixes if prefix in lowered)
        if not hits:
            continue
        if counts[symbol.name] == 0:
            first_seen_order.append(symbol.name)
            matched_prefix_counts[symbol.name] = hits
        counts[symbol.name] += 1
        if restrict_to_prefixes and symbol.file_path.startswith(restrict_to_prefixes):
            in_scope.add(symbol.name)

    candidates = first_seen_order
    if restrict_to_prefixes is not None:
        candidates = [name for name in first_seen_order if name in in_scope]

    eligible = [name for name in candidates if counts[name] <= _MAX_MATCHES_PER_NAME]
    # Tie-break on `name` itself only for determinism (stable output for
    # otherwise-equal scores) — not a relevance signal.
    ranked = sorted(eligible, key=lambda name: (-matched_prefix_counts[name], counts[name], name))
    return ranked[:_MAX_MATCHED_NAMES]


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
