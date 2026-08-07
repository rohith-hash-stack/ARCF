"""CandidateFileSelector (Phase 5 deliverable) — deterministic
impacted-file discovery.

This is the component that answers the playbook's example query
without any LLM: "find every caller of authenticate() and every class
extending BasePage" is exactly callers_of("authenticate") +
subclasses_of("BasePage").
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

    def callers_of(self, function_name: str) -> set[str]:
        """Files containing a call to any symbol named `function_name`,
        plus the file(s) defining it."""
        files: set[str] = set()
        for symbol in self._symbol_index.find_by_name(function_name):
            if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                files.add(symbol.file_path)
                files |= self._call_graph.caller_files_of(symbol.id)
        return files

    def transitive_callers_of(
        self, function_name: str, max_depth: int | None = None
    ) -> dict[str, int]:
        """Files containing a transitive caller of any symbol named
        `function_name` (callers, callers of callers, ...), mapped to the
        shallowest hop at which a caller of theirs was found. `max_depth`
        caps how many call-graph hops are followed (`None` = unbounded)."""
        files: dict[str, int] = {}
        for symbol in self._symbol_index.find_by_name(function_name):
            if symbol.kind not in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                continue
            for file_path in self._call_graph.caller_files_of(symbol.id):
                files[file_path] = min(files.get(file_path, 1), 1)
            for caller_id, (hop, _parent) in self._call_graph.transitive_caller_symbols_of(
                symbol.id, max_depth
            ).items():
                caller = self._symbol_index.get(caller_id)
                if caller is not None:
                    files[caller.file_path] = min(files.get(caller.file_path, hop), hop)
        return files

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
