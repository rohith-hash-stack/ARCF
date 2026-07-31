"""ReferenceResolver (Phase 5 deliverable) — best-effort name -> Symbol
resolution shared by CallGraph and InheritanceGraph.

Without full type inference, resolution is by exact qualified-name
match first, falling back to simple-name match — which can return
multiple candidates when several symbols across the codebase share a
name. That ambiguity is returned to the caller rather than silently
guessing one, per the Golden Rule: software governs, nothing here
pretends to know more than the raw text actually says.
"""

from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import Symbol, SymbolKind


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
