"""classic_decomposition_experiment.py — falsification experiment,
read-only, does not modify context/lexical_symbol_probe.py or any other
ARCF source. Builds a real SymbolIndex per repo via the real engine, then
compares two candidate-selection strategies against the SAME real symbols.

Hypothesis: classic's lexical_symbol_probe.py's fixed 6-character
prefix-substring matching (never splits camelCase/snake_case, never
stems — see that module's own docstring, a deliberate choice: "never a
full stemmer... would add a dependency and false precision this tool
doesn't need") under-recalls real, query-relevant symbols in two
specific, mechanically-identifiable ways a decomposition+stemming
approach (reusing drp/tfidf.py's ALREADY-VALIDATED tokenize(), not a new
implementation) would catch:

  (a) query words under 6 characters never become probe prefixes at all
      (_MIN_TOKEN_LEN = 6) — e.g. "cache", "route", "auth", "hash" are
      silently invisible to probing regardless of how directly they
      name something real in the repository.
  (b) a query word whose probe prefix is LONGER than the matching
      identifier itself can never substring-match it at all, e.g. query
      "caching" -> prefix "cachin" (6 chars) cannot be found inside the
      5-character identifier "Cache" no matter how related the words
      are — the substring-in-string check is directionally blind to
      this shape.

Success criterion (stated up front): the decomposition approach must (a)
recover at least one REAL, symbol that actually exists and is plausibly
query-relevant that the current probe misses entirely, on at least 2 of
the tested repos, AND (b) not flood the results with obviously
irrelevant matches (eyeballed, not just counted) — a large increase in
match COUNT alone is not success if most of the increase is noise.
Failure is an equally valid, reportable outcome.
"""

from __future__ import annotations

from pathlib import Path

from code_intelligence.drp.tfidf import tokenize as drp_tokenize
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.cpp_analyzer import CppLanguageAnalyzer
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.symbol_index import SymbolIndex
from context.lexical_symbol_probe import probe_symbol_names_ranked
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner

SCRATCH_A = Path(
    "C:/Users/VASIGA~1/AppData/Local/Temp/claude/C--Users-VasiganiRohitBabu-Desktop-Claude/"
    "9e0bfde9-a14d-4265-b142-a579ae3668d3/scratchpad/repos"
)
SCRATCH_B = Path(
    "C:/Users/VASIGA~1/AppData/Local/Temp/claude/C--Users-VasiganiRohitBabu-Desktop-Claude/"
    "9e0bfde9-a14d-4265-b142-a579ae3668d3/scratchpad/pmi_repos"
)

_MAX_MATCHED_NAMES = 20


def _decomposed_probe(raw_request: str, symbol_index: SymbolIndex) -> list[tuple[str, set[str]]]:
    """v1 (2026-08-11 first pass): tokenize the query with DRP's real,
    already-validated tokenize() (camelCase/snake_case split + light
    stemming), then tokenize the SAME WAY every real symbol name, and
    match on shared tokens (any overlap) rather than raw-string
    substring containment. FALSIFIED-with-caveat: found real recall
    gains (consul's "agent" case) but also matched on generic
    single-token overlaps ("test", "result", "run") that carry weak
    discriminating signal. Kept for comparison against v2 below."""
    query_tokens = set(drp_tokenize(raw_request))
    if not query_tokens:
        return []

    matched: list[tuple[str, set[str]]] = []
    seen: set[str] = set()
    for symbol in symbol_index.all():
        if symbol.name in seen:
            continue
        name_tokens = set(drp_tokenize(symbol.name))
        overlap = query_tokens & name_tokens
        if overlap:
            seen.add(symbol.name)
            matched.append((symbol.name, overlap))
        if len(matched) >= _MAX_MATCHED_NAMES:
            break
    return matched


# A token appearing in more distinct symbols than this, repo-wide, is
# treated as too generic to be a standalone match signal — mirrors
# lexical_symbol_probe.py's own _MAX_MATCHES_PER_NAME precedent ("one
# matching dozens of unrelated symbols... carries no real signal"),
# applied to TOKENS instead of whole probed NAMES. Self-derived from
# each repo's own vocabulary, not a hardcoded English word list — same
# "let the repo teach ARCF its own structure" discipline as everywhere
# else in this codebase. A symbol still counts as a match if its ONLY
# overlapping token is generic, as long as 2+ distinct query tokens
# overlap (compound signal) — this only blocks a match resting on a
# single, ubiquitous word alone.
_MAX_SYMBOLS_PER_TOKEN = 40


def _token_frequencies(symbol_index: SymbolIndex) -> dict[str, int]:
    freq: dict[str, int] = {}
    seen: set[str] = set()
    for symbol in symbol_index.all():
        if symbol.name in seen:
            continue
        seen.add(symbol.name)
        for token in set(drp_tokenize(symbol.name)):
            freq[token] = freq.get(token, 0) + 1
    return freq


def _decomposed_probe_v2(raw_request: str, symbol_index: SymbolIndex) -> list[tuple[str, set[str]]]:
    """v2, FALSIFIED same session: adds the token-ubiquity guard above
    on top of v1's matching mechanism, as a binary include/exclude gate.
    Failed for a structural reason, not a bad threshold value: "agent"
    is genuinely common within Consul's OWN symbol vocabulary (Consul is
    fundamentally about agents), so a fixed-count cutoff can't tell that
    apart from a truly generic filler word (test/result in googletest) —
    both are "common within this repo" by the same measure. A binary
    gate has no way to let a legitimate-but-frequent domain term still
    count for something. Kept for comparison; see v3 for the fix."""
    query_tokens = set(drp_tokenize(raw_request))
    if not query_tokens:
        return []
    token_freq = _token_frequencies(symbol_index)

    matched: list[tuple[str, set[str]]] = []
    seen: set[str] = set()
    for symbol in symbol_index.all():
        if symbol.name in seen:
            continue
        name_tokens = set(drp_tokenize(symbol.name))
        overlap = query_tokens & name_tokens
        if not overlap:
            continue
        specific_overlap = {t for t in overlap if token_freq.get(t, 0) <= _MAX_SYMBOLS_PER_TOKEN}
        if not specific_overlap and len(overlap) < 2:
            continue  # only generic tokens matched, and only one of them
        seen.add(symbol.name)
        matched.append((symbol.name, overlap))
        if len(matched) >= _MAX_MATCHED_NAMES:
            break
    return matched


def _token_idf(symbol_index: SymbolIndex) -> dict[str, float]:
    """Same formula DRP's own tfidf.py already uses and has already
    validated (log((N+1)/(df+1)) + 1), applied to symbol-name tokens
    instead of file text blobs — not a new scoring idea, a reuse of one."""
    import math

    freq = _token_frequencies(symbol_index)
    seen: set[str] = set()
    total = 0
    for symbol in symbol_index.all():
        if symbol.name in seen:
            continue
        seen.add(symbol.name)
        total += 1
    return {token: math.log((total + 1) / (df + 1)) + 1.0 for token, df in freq.items()}


def _decomposed_probe_v3(raw_request: str, symbol_index: SymbolIndex) -> list[tuple[str, set[str], float]]:
    """v3: replaces v2's binary include/exclude gate with a continuous
    IDF-weighted RANKING score (sum of matched tokens' idf), same shape
    as DRP's own cosine-similarity-style scoring — every symbol with
    ANY overlap stays a candidate (nothing hard-excluded), but the
    _MAX_MATCHED_NAMES cap is filled by highest SCORE, not scan order or
    a pass/fail gate. Tests whether a generic word (low idf everywhere)
    naturally gets outranked by a specific one in aggregate, without
    needing to decide in advance which words don't count at all."""
    query_tokens = set(drp_tokenize(raw_request))
    if not query_tokens:
        return []
    idf = _token_idf(symbol_index)

    scored: list[tuple[str, set[str], float]] = []
    seen: set[str] = set()
    for symbol in symbol_index.all():
        if symbol.name in seen:
            continue
        name_tokens = set(drp_tokenize(symbol.name))
        overlap = query_tokens & name_tokens
        if not overlap:
            continue
        seen.add(symbol.name)
        score = sum(idf.get(t, 0.0) for t in overlap)
        scored.append((symbol.name, overlap, score))

    scored.sort(key=lambda row: (-row[2], row[0]))
    return scored[:_MAX_MATCHED_NAMES]


def _decomposed_probe_v4(raw_request: str, symbol_index: SymbolIndex) -> list[tuple[str, set[str], float]]:
    """v4: a genuinely different axis from v2/v3 — both of those weighted
    by how rare the matched TOKEN is ACROSS THE REPO, which structurally
    penalizes a repo's own defining vocabulary (Consul's "agent"). This
    instead weights by what fraction of the SYMBOL's OWN tokens the
    query covers: bare `Agent` (1 token, fully covered) scores 1.0;
    `RunSetUpTestSuite` (5 tokens, 2 covered) scores 0.4; `ACLAuthMethod
    BatchDeleteRequest` (6 tokens, 1 covered) scores ~0.17. No repo-wide
    frequency statistics computed at all — purely a property of each
    candidate symbol's own name shape, favoring short/precise symbols
    over long compound names that merely CONTAIN a matching word."""
    query_tokens = set(drp_tokenize(raw_request))
    if not query_tokens:
        return []

    scored: list[tuple[str, set[str], float]] = []
    seen: set[str] = set()
    for symbol in symbol_index.all():
        if symbol.name in seen:
            continue
        name_tokens = set(drp_tokenize(symbol.name))
        if not name_tokens:
            continue
        overlap = query_tokens & name_tokens
        if not overlap:
            continue
        seen.add(symbol.name)
        fraction = len(overlap) / len(name_tokens)
        scored.append((symbol.name, overlap, fraction))

    scored.sort(key=lambda row: (-row[2], row[0]))
    return scored[:_MAX_MATCHED_NAMES]


def _build_index(root: Path, analyzer_cls) -> SymbolIndex:
    engine = CodeIntelligenceEngine(LanguageRegistry([analyzer_cls()]), CostEstimator())
    scan = RepositoryScanner().scan(root)
    index = engine.build_index(root, scan.files)
    return index.symbol_index


CASES = [
    # (repo dir, analyzer, query) — both googletest and flatbuffers are
    # C++; traefik and consul are Go.
    (SCRATCH_A / "googletest", CppLanguageAnalyzer, "How does the test cache results between runs?"),
    (SCRATCH_A / "flatbuffers", CppLanguageAnalyzer, "Explain the caching strategy for parsed schemas."),
    (SCRATCH_B / "traefik", GoLanguageAnalyzer, "How does routing decide which backend to use?"),
    (SCRATCH_B / "consul", GoLanguageAnalyzer, "How is authentication handled for agent requests?"),
]


_KNOWN_GENERIC_WORDS = {"test", "result", "run", "request"}  # observed noise in v1, for reporting only
# The real gains v1 found that v2 destroyed — the decisive evidence to
# check v3 against: does it recover these, and does it still keep
# generic-only matches out of the top _MAX_MATCHED_NAMES?
_KNOWN_REAL_GAINS = {
    "consul": {
        "Agent", "AgentRead", "AgentWrite", "AgentReadAllowed", "AgentWriteAllowed",
        "AgentLocalMember", "AgentRule", "checkAllowAgentRead", "checkAllowAgentWrite",
        "agentServiceFillAuthzContext",
    },
}


def main() -> None:
    for root, analyzer_cls, query in CASES:
        if not root.is_dir():
            print(f"SKIP {root.name}: not cloned")
            continue
        symbol_index = _build_index(root, analyzer_cls)

        current = set(probe_symbol_names_ranked(query, symbol_index))
        v1 = _decomposed_probe(query, symbol_index)
        v1_names = {name for name, _ in v1}
        v4 = _decomposed_probe_v4(query, symbol_index)
        v4_names = {name for name, _, _ in v4}

        v1_only = v1_names - current
        v4_only = v4_names - current
        v1_generic_only = {
            name for name, tokens in v1 if name in v1_only and tokens <= _KNOWN_GENERIC_WORDS
        }
        expected_gains = _KNOWN_REAL_GAINS.get(root.name, set())

        print(f"\n=== {root.name} | {query!r} ===")
        print(f"  current probe: n={len(current)}")
        print(f"  v1 new candidates: n={len(v1_only)}, generic-only (noise): n={len(v1_generic_only)}")
        print(f"  v4 (match-fraction-ranked) new candidates: n={len(v4_only)}, top-scored:")
        for name, tokens, score in v4[:10]:
            marker = " <- real gain" if name in expected_gains else ""
            print(f"      {score:5.3f}  {name!r}  tokens={sorted(tokens)}{marker}")
        if expected_gains:
            recovered = expected_gains & v4_only
            print(f"  real gains recovered by v4: {len(recovered)}/{len(expected_gains)}: {sorted(recovered)}")
            missed = expected_gains - v4_only
            if missed:
                print(f"  real gains v4 STILL MISSED: {sorted(missed)}")
        v4_generic_only = {
            name for name, tokens, _ in v4 if name in v4_only and tokens <= _KNOWN_GENERIC_WORDS
        }
        print(f"  generic-only matches still in v4's top {_MAX_MATCHED_NAMES}: {sorted(v4_generic_only)}")


if __name__ == "__main__":
    main()
