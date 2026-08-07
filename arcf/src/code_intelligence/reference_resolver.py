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
"""

from dataclasses import dataclass

from code_intelligence.import_graph import ImportGraph
from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import Symbol, SymbolKind


@dataclass(frozen=True)
class DisambiguationResult:
    resolved: list[Symbol]
    """Every candidate symbol matching the name (post kind-filter),
    regardless of ambiguity — same population `resolve()` would return."""
    ambiguous: bool
    """True when more than one candidate remains after applying every
    deterministic locality signal available — i.e. disambiguation could
    not narrow it further and the caller should treat this as genuinely
    ambiguous rather than silently picking one."""
    preferred: Symbol | None
    """The single best candidate by locality score, or the sole match
    when there's no ambiguity to begin with. `None` when unresolved or
    still ambiguous."""


class ReferenceResolver:
    def __init__(self, symbol_index: SymbolIndex) -> None:
        self._symbol_index = symbol_index

    def resolve(self, raw_name: str, kinds: tuple[SymbolKind, ...] | None = None) -> list[Symbol]:
        candidates = self._symbol_index.find_by_qualified_name(raw_name)
        if not candidates:
            simple_name = raw_name.rsplit(".", 1)[-1]
            candidates = self._symbol_index.find_by_name(simple_name)
        if kinds is not None:
            candidates = [candidate for candidate in candidates if candidate.kind in kinds]
        return candidates

    def resolve_with_disambiguation(
        self,
        raw_name: str,
        kinds: tuple[SymbolKind, ...] | None = None,
        context_files: frozenset[str] = frozenset(),
        import_graph: ImportGraph | None = None,
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
        only orders/narrows what `resolve()` already found."""
        candidates = self.resolve(raw_name, kinds=kinds)
        if len(candidates) <= 1:
            return DisambiguationResult(
                resolved=candidates,
                ambiguous=False,
                preferred=candidates[0] if candidates else None,
            )

        scored = [
            (self._locality_score(candidate, context_files, import_graph), candidate)
            for candidate in candidates
        ]
        best_score = max(score for score, _ in scored)
        best_candidates = [candidate for score, candidate in scored if score == best_score]

        if len(best_candidates) == 1:
            return DisambiguationResult(
                resolved=candidates, ambiguous=False, preferred=best_candidates[0]
            )
        return DisambiguationResult(resolved=candidates, ambiguous=True, preferred=None)

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
