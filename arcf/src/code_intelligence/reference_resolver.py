"""ReferenceResolver (Phase 5 deliverable) — best-effort name -> Symbol
resolution shared by CallGraph and InheritanceGraph.

Without full type inference, resolution is by exact qualified-name
match first, falling back to simple-name match — which can return
multiple candidates when several symbols across the codebase share a
name. That ambiguity is returned to the caller rather than silently
guessing one, per the Golden Rule: software governs, nothing here
pretends to know more than the raw text actually says.

ARCF hardening §3 (symbol disambiguation): `resolve_with_disambiguation`
adds a second, opt-in resolution path that narrows an ambiguous
simple-name match using deterministic locality signals (same file, same
directory/"package", reachable via the import graph) from the caller's
own execution-path context, preferring the symbol reachable from that
context over the first match. Scoped to ContextResolver's top-level
target-name lookup only — `resolve()` itself (used by CallGraph and
InheritanceGraph, whose fan-out-to-all-candidates behavior is already
well tested) is unchanged.

Path-aware filtering and identifier-permutation fallback (2026-08-11,
arcf-grounding-validation-entity-extraction-gap): a real Consul
benchmark found two related SLM-1 failure modes that plain `resolve()`
has no recovery from — both handled here, in `resolve_with
_disambiguation` only, for the same reason the locality scoring above
is scoped there and not into `resolve()` itself (this module's whole
discipline: extend the opt-in target-name lookup, never the shared
edges CallGraph/InheritanceGraph depend on).

(1) `path_hints`: when the caller has directory/path signals for a
name (ContextResolver splits them out of path-qualified entities like
"agent/cache" before calling this), candidates outside every hint are
dropped from the returned population itself — a deliberate departure
from `resolved`'s "always the full match set" contract above, but a
narrower, more trustworthy signal than locality scoring: the caller
told us the directory, we didn't have to guess it from already-resolved
files. A candidate matching ANY hint in the set passes (union, not
intersection) — deliberately permissive, since hints usually come from
different entities in the same query describing different concepts,
not multiple constraints on the same one. Falls back to the unfiltered
set if no hint matches anything (a hint that doesn't help shouldn't
have the power to make an otherwise-resolvable name un-resolve);
`path_hint_matched` on the result records whether the hard filter
actually took effect, so a caller doing query-wide masking (2026-08-11,
Feature 1, Real-Time Payload Optimization) can fall back to a soft
score penalty instead of treating a failed-to-help hint as if it never
existed.

(2) Identifier-permutation fallback: when `resolve()` finds nothing at
all AND the raw name looks like prose (contains a space — a clean
single-token name that simply doesn't exist is left alone, not forced
through permutation), `_permutation_candidates` generates PascalCase/
camelCase/snake_case joins plus adjacent-word-pair and single-word
candidates from the phrase's own tokens, tried in that order until one
resolves. Real example this fixes: SLM-1 extracting "New function"
where `resolve("New function")` finds nothing, but `resolve("New")`
(one of the generated candidates) finds the real symbol.

ARCF-DI Phase 3: `resolve_tiered` is a new, additive method `resolve()`
is now defined in terms of (identical behavior, identical signature —
every existing caller of `resolve()` is unaffected) that also reports
whether the simple-name fallback tier was used. It exists so CallGraph's
opt-in `mandatory_disambiguation` mode (see call_graph.py) can tag each
CallReference's resolution_confidence honestly — this module's own
`resolve_with_disambiguation` is untouched, so ContextResolver's existing
behavior is unaffected too.
"""

import re
from dataclasses import dataclass

from code_intelligence.import_graph import ImportGraph
from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import Symbol, SymbolKind

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")


def _tokenize_prose(phrase: str) -> list[str]:
    return [w.lower() for w in _TOKEN_PATTERN.findall(phrase)]


def _singularize(word: str) -> str:
    # Light heuristic, not real lemmatization -- deliberately guarded
    # against "class"/"address"-style words ending in a doubled "s" or
    # too short to safely assume a plural.
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _pascal(words: list[str]) -> str:
    return "".join(w.capitalize() for w in words)


def _camel(words: list[str]) -> str:
    if not words:
        return ""
    return words[0] + "".join(w.capitalize() for w in words[1:])


def _snake(words: list[str]) -> str:
    return "_".join(words)


def _permutation_candidates(raw_name: str) -> list[str]:
    """Deterministic, ordered candidate identifiers generated from a
    prose phrase's own words — most-specific (the whole phrase) first,
    down to single words, so a real multi-word compound identifier is
    preferred over an accidental single-word match when both exist."""
    words = [_singularize(w) for w in _tokenize_prose(raw_name)]
    if len(words) < 2:
        return []

    candidates = [_pascal(words)]
    candidates.extend(_pascal(words[i : i + 2]) for i in range(len(words) - 1))
    candidates.extend(w.capitalize() for w in words)
    candidates.append(_camel(words))
    candidates.append(_snake(words))

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


@dataclass(frozen=True)
class ResolutionTier:
    """ARCF-DI Phase 3: which of `resolve()`'s two internal attempts
    actually produced `candidates` — exact-qualified-name match, or the
    simple-name fallback. `resolve()` itself stays unchanged (still
    returns just the candidate list, every existing caller untouched);
    this is purely additive so CallGraph's mandatory-disambiguation path
    can tag CallReference.resolution_confidence honestly instead of
    guessing which tier matched from the outside."""

    candidates: list[Symbol]
    used_simple_name_fallback: bool


@dataclass(frozen=True)
class DisambiguationResult:
    resolved: list[Symbol]
    """Every candidate symbol matching the name (post kind-filter and
    post path_hint-filter, when a path_hint was given and matched
    something), regardless of ambiguity — same population `resolve()`
    would return absent a path_hint."""
    ambiguous: bool
    """True when more than one candidate remains after applying every
    deterministic locality signal available — i.e. disambiguation could
    not narrow it further and the caller should treat this as genuinely
    ambiguous rather than silently picking one."""
    preferred: Symbol | None
    """The single best candidate by locality score, or the sole match
    when there's no ambiguity to begin with. `None` when unresolved or
    still ambiguous."""
    permutation_matched: str | None = None
    """The generated identifier candidate that actually resolved, when
    the raw name itself matched nothing and permutation fallback
    recovered a result — `None` whenever the raw name resolved directly
    (the overwhelmingly common case) or nothing resolved at all. Purely
    for auditability, matching this project's justification_chain-style
    "never a silent black box" discipline."""
    path_hint_matched: bool = False
    """True when `path_hints` was non-empty AND at least one candidate
    satisfied it, i.e. the hard filter actually narrowed `resolved`.
    False whenever no hints were given, or hints were given but matched
    nothing (the unfiltered-fallback case) -- the caller needs to
    distinguish these to know whether a soft penalty should apply to
    off-hint candidates it kept."""


class ReferenceResolver:
    def __init__(self, symbol_index: SymbolIndex) -> None:
        self._symbol_index = symbol_index

    def resolve(self, raw_name: str, kinds: tuple[SymbolKind, ...] | None = None) -> list[Symbol]:
        return self.resolve_tiered(raw_name, kinds=kinds).candidates

    def resolve_tiered(
        self, raw_name: str, kinds: tuple[SymbolKind, ...] | None = None
    ) -> ResolutionTier:
        """Same resolution as `resolve()`, plus which tier produced the
        result. `resolve()` is defined in terms of this method, not the
        other way around, so there is exactly one place this logic lives."""
        candidates = self._symbol_index.find_by_qualified_name(raw_name)
        used_simple_name_fallback = False
        if not candidates:
            simple_name = raw_name.rsplit(".", 1)[-1]
            candidates = self._symbol_index.find_by_name(simple_name)
            used_simple_name_fallback = True
        if kinds is not None:
            candidates = [candidate for candidate in candidates if candidate.kind in kinds]
        return ResolutionTier(
            candidates=candidates, used_simple_name_fallback=used_simple_name_fallback
        )

    def resolve_with_disambiguation(
        self,
        raw_name: str,
        kinds: tuple[SymbolKind, ...] | None = None,
        context_files: frozenset[str] = frozenset(),
        import_graph: ImportGraph | None = None,
        path_hints: frozenset[str] = frozenset(),
    ) -> DisambiguationResult:
        """Like `resolve()`, but when the name resolves to more than one
        candidate, deterministically narrows it using locality relative to
        `context_files` (the files already established as relevant — the
        caller's "detected execution path"), in order of decreasing
        specificity: same file > same directory > reachable via a direct
        import edge from a context file. If exactly one candidate achieves
        the highest locality score, it's `preferred` and `ambiguous` is
        False; otherwise every tied candidate remains and `ambiguous` is
        True. Never invents a symbol that isn't a real name match — this
        only orders/narrows what `resolve()` already found (except
        `path_hints`, a deliberate exception — see this module's own
        docstring).

        `path_hints`, when given, is applied FIRST: candidates matching
        none of the hints are dropped from the population entirely,
        before either the empty-result permutation fallback or locality
        scoring ever runs (caller-provided directories are stronger
        evidence than anything this method could infer on its own)."""
        candidates = self.resolve(raw_name, kinds=kinds)
        permutation_matched: str | None = None

        if not candidates and " " in raw_name.strip():
            for candidate_name in _permutation_candidates(raw_name):
                permuted = self.resolve(candidate_name, kinds=kinds)
                if permuted:
                    candidates = permuted
                    permutation_matched = candidate_name
                    break

        path_hint_matched = False
        if path_hints:
            path_filtered = [
                c for c in candidates
                if any(c.file_path.startswith(hint) for hint in path_hints)
            ]
            if path_filtered:
                candidates = path_filtered
                path_hint_matched = True

        if len(candidates) <= 1:
            return DisambiguationResult(
                resolved=candidates,
                ambiguous=False,
                preferred=candidates[0] if candidates else None,
                permutation_matched=permutation_matched,
                path_hint_matched=path_hint_matched,
            )

        scored = [
            (self._locality_score(candidate, context_files, import_graph), candidate)
            for candidate in candidates
        ]
        best_score = max(score for score, _ in scored)
        best_candidates = [candidate for score, candidate in scored if score == best_score]

        if len(best_candidates) == 1:
            return DisambiguationResult(
                resolved=candidates,
                ambiguous=False,
                preferred=best_candidates[0],
                permutation_matched=permutation_matched,
                path_hint_matched=path_hint_matched,
            )
        return DisambiguationResult(
            resolved=candidates, ambiguous=True, preferred=None,
            permutation_matched=permutation_matched,
            path_hint_matched=path_hint_matched,
        )

    @staticmethod
    def _locality_score(
        candidate: Symbol,
        context_files: frozenset[str],
        import_graph: ImportGraph | None,
    ) -> int:
        if not context_files:
            return 0
        if candidate.file_path in context_files:
            return 3
        if any(
            SymbolIndex.same_package(candidate.file_path, context_file)
            for context_file in context_files
        ):
            return 2
        if import_graph is not None and any(
            candidate.file_path in import_graph.imports_of(context_file)
            or context_file in import_graph.importers_of(candidate.file_path)
            for context_file in context_files
        ):
            return 1
        return 0
