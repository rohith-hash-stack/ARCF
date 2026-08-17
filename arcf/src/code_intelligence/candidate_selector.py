"""CandidateFileSelector (Phase 5 deliverable) — deterministic
impacted-file discovery.

`callers_of`/`transitive_callers_of` (name-based call-site lookup) were
removed in the architecture closure (2026-08-16): both were dead in
production and were the exact same-named-symbol-fan-out risk
`locality.py`'s `locality_filtered_callers_of_name` was purpose-built to
fix (a bare "New" query previously matched 159 symbols across 156
unrelated subsystems on real Consul, 2026-08-11) -- `ContextResolver`
already uses that locality-filtered replacement, never this class's
name-based lookup, for call-graph expansion. `subclasses_of` remains
genuinely wired (context_resolver.py's `_expand_subclasses`);
`impacted_files` remains as an unused-but-not-superseded "blast radius"
capability (see the closure checklist's Orphaned Components section).
"""

from code_intelligence.call_graph import CallGraph
from code_intelligence.dependency_graph import DependencyGraph
from code_intelligence.inheritance_graph import InheritanceGraph
from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import SymbolKind


class CandidateFileSelector:
    def __init__(
        self,
        symbol_index: SymbolIndex,
        call_graph: CallGraph,
        inheritance_graph: InheritanceGraph,
        dependency_graph: DependencyGraph,
    ) -> None:
        self._symbol_index = symbol_index
        self._call_graph = call_graph
        self._inheritance_graph = inheritance_graph
        self._dependency_graph = dependency_graph

    def subclasses_of(self, class_name: str, max_depth: int | None = None) -> set[str]:
        """Files defining `class_name` or any class transitively extending
        it. `max_depth` caps how many inheritance hops are followed
        (`None` = unbounded, the pre-hardening default)."""
        files: set[str] = set()
        for symbol in self._symbol_index.find_by_name(class_name):
            if symbol.kind is not SymbolKind.CLASS:
                continue
            files.add(symbol.file_path)
            for subclass_id in self._inheritance_graph.all_subclasses_of(symbol.id, max_depth):
                subclass = self._symbol_index.get(subclass_id)
                if subclass is not None:
                    files.add(subclass.file_path)
        return files

    def impacted_files(self, file_path: str, max_depth: int | None = None) -> set[str]:
        """Every file that would need re-consideration if `file_path`
        changes: itself plus every file that transitively imports it."""
        return {file_path} | self._dependency_graph.impacted_by(file_path, max_depth)
