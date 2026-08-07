"""DependencyGraph (Phase 5 deliverable) — transitive closure over
ImportGraph's direct edges.

This is what makes "deterministic impacted-file discovery" possible:
impacted_by(file_path) answers "if this file changes, which other
files transitively depend on it and might need re-consideration" —
without any LLM, per the Phase 5 goal.
"""

from collections.abc import Callable

from code_intelligence.import_graph import ImportGraph


class DependencyGraph:
    def __init__(self, import_graph: ImportGraph) -> None:
        self._import_graph = import_graph

    def transitive_dependencies(self, file_path: str, max_depth: int | None = None) -> set[str]:
        """Every file `file_path` depends on, directly or indirectly.
        `max_depth=None` (default, unchanged from before ARCF hardening)
        follows the full closure; an int caps how many import hops."""
        return self._bfs(file_path, self._import_graph.imports_of, max_depth)

    def impacted_by(self, file_path: str, max_depth: int | None = None) -> set[str]:
        """Every file that would need re-consideration if `file_path`
        changes: every file that transitively imports it."""
        return self._bfs(file_path, self._import_graph.importers_of, max_depth)

    @staticmethod
    def _bfs(
        start: str, neighbors_fn: Callable[[str], set[str]], max_depth: int | None = None
    ) -> set[str]:
        visited: set[str] = set()
        frontier: set[str] = set(neighbors_fn(start))
        depth = 1
        while frontier and (max_depth is None or depth <= max_depth):
            visited |= frontier
            next_frontier: set[str] = set()
            for current in frontier:
                next_frontier |= neighbors_fn(current) - visited
            frontier = next_frontier
            depth += 1
        return visited
