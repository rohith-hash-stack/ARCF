"""ImportGraph (Phase 5 deliverable) — direct file-to-file edges.

Built purely from ImportReference.resolved_file_path — every
language-specific resolution decision already happened inside the
LanguageAnalyzer that produced these facts, so this class has zero
knowledge of any language's import syntax. An unresolved import
(resolved_file_path is None — stdlib, third-party, or genuinely
missing) simply contributes no edge.
"""

from collections import defaultdict

from domain.code_intelligence import ImportReference


class ImportGraph:
    def __init__(self, imports: list[ImportReference]) -> None:
        self._imports_of: dict[str, set[str]] = defaultdict(set)
        self._importers_of: dict[str, set[str]] = defaultdict(set)

        for imp in imports:
            if imp.resolved_file_path is not None:
                self._imports_of[imp.source_file].add(imp.resolved_file_path)
                self._importers_of[imp.resolved_file_path].add(imp.source_file)

    def imports_of(self, file_path: str) -> set[str]:
        """Files that `file_path` directly imports."""
        return set(self._imports_of.get(file_path, set()))

    def importers_of(self, file_path: str) -> set[str]:
        """Files that directly import `file_path`."""
        return set(self._importers_of.get(file_path, set()))
