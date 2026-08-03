"""DependencyGraph (Phase 5 deliverable) — transitive closure over
ImportGraph's direct edges.

This is what makes "deterministic impacted-file discovery" possible:
impacted_by(file_path) answers "if this file changes, which other
files transitively depend on it and might need re-consideration" —
without any LLM, per the Phase 5 goal.
"""

from collections import deque
from collections.abc import Callable

from code_intelligence.import_graph import ImportGraph


class DependencyGraph:
    def __init__(self, import_graph: ImportGraph) -> None:
        self._import_graph = import_graph

    def transitive_dependencies(self, file_path: str) -> set[str]:
        """Every file `file_path` depends on, directly or indirectly."""
        return self._bfs(file_path, self._import_graph.imports_of)

    def impacted_by(self, file_path: str) -> set[str]:
        """Every file that would need re-consideration if `file_path`
        changes: every file that transitively imports it."""
        return self._bfs(file_path, self._import_graph.importers_of)

    @staticmethod
    def _bfs(start: str, neighbors_fn: Callable[[str], set[str]]) -> set[str]:
        visited: set[str] = set()
        queue: deque[str] = deque(neighbors_fn(start))
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            queue.extend(n for n in neighbors_fn(current) if n not in visited)
        return visited
