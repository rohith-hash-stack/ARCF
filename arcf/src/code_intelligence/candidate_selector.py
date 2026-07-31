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

    def subclasses_of(self, class_name: str) -> set[str]:
        """Files defining `class_name` or any class transitively extending it."""
        files: set[str] = set()
        for symbol in self._symbol_index.find_by_name(class_name):
            if symbol.kind is not SymbolKind.CLASS:
                continue
            files.add(symbol.file_path)
            for subclass_id in self._inheritance_graph.all_subclasses_of(symbol.id):
                subclass = self._symbol_index.get(subclass_id)
                if subclass is not None:
                    files.add(subclass.file_path)
        return files

    def impacted_files(self, file_path: str) -> set[str]:
        """Every file that would need re-consideration if `file_path`
        changes: itself plus every file that transitively imports it."""
        return {file_path} | self._dependency_graph.impacted_by(file_path)
