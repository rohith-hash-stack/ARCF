"""LanguageAnalyzer — the one interface every language plugin implements.

Everything downstream (SymbolIndex, ImportGraph, DependencyGraph,
InheritanceGraph, CallGraph, CandidateFileSelector) operates purely on
the IR types this method returns (Symbol, CallReference,
ImportReference) — none of it imports tree-sitter, knows Python/
TypeScript/Java/Go syntax, or otherwise depends on any specific
language. Adding a new language means writing one new class satisfying
this Protocol and registering it with LanguageRegistry; no other file
in code_intelligence/ changes.
"""

from typing import Protocol

from domain.code_intelligence import FileAnalysis


class LanguageAnalyzer(Protocol):
    @property
    def language(self) -> str:
        """Short language identifier, e.g. "python", "typescript"."""
        ...

    def handles(self, file_path: str) -> bool:
        """True if this analyzer should parse `file_path` (typically by
        extension)."""
        ...

    def analyze_file(
        self, file_path: str, source_text: str, workspace_files: frozenset[str]
    ) -> FileAnalysis:
        """Parse one file's source into language-independent IR facts.

        workspace_files is the full set of relative paths in the scan,
        so import resolution — inherently language-specific (Python's
        dotted modules vs. TypeScript's relative/bare specifiers vs.
        Go's import paths) — can happen here, once, at the point where
        language-specific knowledge already lives, rather than needing
        a second per-language hook in the orchestration layer.
        """
        ...
