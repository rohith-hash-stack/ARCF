"""InheritanceGraph (Phase 5 deliverable) — subclass/superclass edges
between CLASS symbols, resolved via ReferenceResolver.

Answers half of the playbook's example query directly: "every class
extending BasePage" is all_subclasses_of(BasePage's symbol id).
A base name that doesn't resolve to any known CLASS symbol (external
base class, or a name ReferenceResolver couldn't match) is recorded in
unresolved_bases rather than silently dropped.
"""

from collections import defaultdict, deque

from code_intelligence.reference_resolver import ReferenceResolver
from domain.code_intelligence import Symbol, SymbolKind


class InheritanceGraph:
    def __init__(self, symbols: list[Symbol], resolver: ReferenceResolver) -> None:
        self._subclasses: dict[str, set[str]] = defaultdict(set)
        self._superclasses: dict[str, set[str]] = defaultdict(set)
        self._unresolved_bases: dict[str, list[str]] = defaultdict(list)

        for symbol in symbols:
            if symbol.kind is not SymbolKind.CLASS:
                continue
            for base_name in symbol.base_names:
                bases = resolver.resolve(base_name, kinds=(SymbolKind.CLASS,))
                if not bases:
                    self._unresolved_bases[symbol.id].append(base_name)
                    continue
                for base in bases:
                    self._subclasses[base.id].add(symbol.id)
                    self._superclasses[symbol.id].add(base.id)

    def direct_subclasses_of(self, class_id: str) -> set[str]:
        return set(self._subclasses.get(class_id, set()))

    def direct_superclasses_of(self, class_id: str) -> set[str]:
        return set(self._superclasses.get(class_id, set()))

    def unresolved_bases_of(self, class_id: str) -> list[str]:
        return list(self._unresolved_bases.get(class_id, []))

    def all_subclasses_of(self, class_id: str, max_depth: int | None = None) -> set[str]:
        """Every class transitively extending `class_id`. `max_depth=None`
        (the default, unchanged from before ARCF hardening) expands the
        full hierarchy; an int caps how many inheritance hops to follow."""
        visited: set[str] = set()
        frontier: set[str] = set(self._subclasses.get(class_id, set()))
        depth = 1
        while frontier and (max_depth is None or depth <= max_depth):
            visited |= frontier
            next_frontier: set[str] = set()
            for current in frontier:
                next_frontier |= self._subclasses.get(current, set()) - visited
            frontier = next_frontier
            depth += 1
        return visited

    def all_superclasses_of(self, class_id: str) -> set[str]:
        visited: set[str] = set()
        queue: deque[str] = deque(self._superclasses.get(class_id, set()))
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            queue.extend(self._superclasses.get(current, set()) - visited)
        return visited
