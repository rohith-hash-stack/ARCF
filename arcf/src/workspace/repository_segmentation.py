"""RepositorySegmenter (ARCF architecture hardening §4) — deterministic
repository/workspace boundary detection for monorepos.

Reuses structure_analyzer.py's MANIFEST_FILENAMES (the same manifest-
detection heuristic that already powers "monorepo" layout inference)
plus monorepo-tool workspace-config filenames not covered there (already
recognized elsewhere in this codebase, in contracts/evidence_contract.py's
"project metadata" category), to compute segment roots: the nearest
enclosing directory containing a manifest or workspace-config file.

Retrieval scoping (context/evidence_validator.py) uses this to keep
evidence expansion within the segment a query is actually about, in a
monorepo with multiple unrelated services. Graph-driven candidates (real
call/import/inheritance edges — code_intelligence/context_resolver.py)
are never filtered by segment: a real dependency edge crossing segments
is exactly the case where cross-segment retrieval should happen, per the
hardening brief's own wording.
"""

from collections import Counter

from workspace.scanner import ScannedFile
from workspace.structure_analyzer import MANIFEST_FILENAMES

WORKSPACE_CONFIG_FILENAMES: frozenset[str] = frozenset(
    {"lerna.json", "pnpm-workspace.yaml", "turbo.json", "nx.json"}
)

_SEGMENT_MARKER_FILENAMES = MANIFEST_FILENAMES | WORKSPACE_CONFIG_FILENAMES

ROOT_SEGMENT = ""
"""The whole-repository segment — always a valid fallback, used when no
narrower marker directory contains a given file."""


class RepositorySegmenter:
    def __init__(self, files: list[ScannedFile]) -> None:
        self._segment_roots = self._compute_segment_roots(files)

    @staticmethod
    def _compute_segment_roots(files: list[ScannedFile]) -> list[str]:
        roots: set[str] = {ROOT_SEGMENT}
        for file in files:
            parts = file.relative_path.split("/")
            filename = parts[-1]
            directory = "/".join(parts[:-1])
            if filename in _SEGMENT_MARKER_FILENAMES:
                roots.add(directory)
        # Longest (most specific / innermost) directory first, so a
        # nested manifest wins over an outer one; alphabetical tie-break
        # keeps this fully deterministic regardless of scan order.
        return sorted(roots, key=lambda root: (-len(root), root))

    def segment_of(self, file_path: str) -> str:
        """Nearest enclosing segment root for `file_path` — the deepest
        registered marker directory that is a prefix of the file's own
        directory, or ROOT_SEGMENT if none matches."""
        directory = "/".join(file_path.split("/")[:-1])
        for root in self._segment_roots:
            if root == ROOT_SEGMENT:
                continue
            if directory == root or directory.startswith(root + "/"):
                return root
        return ROOT_SEGMENT

    def dominant_segment(self, file_paths: list[str]) -> str:
        """The most common segment among `file_paths` — deterministic
        tie-break by segment name. ROOT_SEGMENT when `file_paths` is
        empty."""
        if not file_paths:
            return ROOT_SEGMENT
        counts = Counter(self.segment_of(path) for path in file_paths)
        top_count = max(counts.values())
        return min(segment for segment, count in counts.items() if count == top_count)

    @property
    def segment_roots(self) -> list[str]:
        return list(self._segment_roots)
