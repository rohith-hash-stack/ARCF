"""SymbolRangeCompressor (Phase 6 deliverable: Prompt Compression) —
deterministic compression via line-range extraction.

When a file doesn't fit the remaining token budget, extracting just the
line ranges around its relevant symbols is a purely mechanical, fully
reproducible compression technique — no SLM needed. This is the
PRIMARY compression mechanism; SLM-2 (ContextUnderstandingAnalyzer)
only ever adds commentary on top, never replaces this.

Uses workspace.permissions.PermissionManager (Phase 4's safe-read
utility, not a code_intelligence internal) — reading actual file
content for packaging is legitimate work for Phase 6 to do itself,
since ContextResolutionResult deliberately never carries raw content.
"""

import re

from domain.code_intelligence import SymbolKind
from domain.context_resolution import SymbolReference
from workspace.permissions import PermissionManager

DEFAULT_MARGIN_LINES = 2

# Feature C (AST Enclosing Scope Slicing, 2026-08-11): a wider buffer than
# DEFAULT_MARGIN_LINES, deliberately kept separate rather than changing
# the shared default -- this mode is opt-in, used only for SUPPORTING/
# EXPERIMENTAL ("secondary") candidates in ContextBudgetManager, and the
# task spec calls for 5 lines specifically, independent of whatever
# margin the plain extract() path uses elsewhere.
_AST_SCOPE_MARGIN_LINES = 5

# Text heuristic for "file header & package/import statements" -- this
# module is Phase 6 (domain-only, no code_intelligence/tree-sitter
# access, see domain/context_resolution.py's own module docstring on
# that boundary), so this can't re-parse the file; it scans from line 1
# and keeps whatever looks like a leading run of comments/package/import
# lines, stopping at the first line that doesn't match. Deliberately
# permissive across languages (Python/Go/Java/C#/TS import/package/using
# forms, plus block/line comments and blank lines) rather than
# language-specific, since SymbolReference carries no language-grammar
# detail Phase 6 could dispatch on beyond the file's own extension.
_HEADER_LINE_PATTERN = re.compile(
    r'^\s*($|#|//|/\*|\*|"""|\'\'\'|package\s|import\s|from\s+\S+\s+import|using\s)'
)
_MAX_HEADER_SCAN_LINES = 50


class SymbolRangeCompressor:
    def __init__(
        self, permissions: PermissionManager, margin_lines: int = DEFAULT_MARGIN_LINES
    ) -> None:
        self._permissions = permissions
        self._margin_lines = margin_lines

    def extract(self, file_path: str, symbols: list[SymbolReference]) -> str:
        """Returns the file's content restricted to line ranges around
        `symbols` (merged where they overlap or touch), each range
        prefixed with its line numbers so the excerpt stays interpretable
        out of context. Empty string if `symbols` is empty — there is
        nothing to extract.
        """
        if not symbols:
            return ""

        text = self._permissions.safe_read_text(file_path)
        lines = text.splitlines()
        total_lines = len(lines)

        raw_ranges = sorted(
            (
                max(1, symbol.start_line - self._margin_lines),
                min(total_lines, symbol.end_line + self._margin_lines),
            )
            for symbol in symbols
        )
        merged = self._merge(raw_ranges)

        excerpts = [
            f"# lines {start}-{end}\n" + "\n".join(lines[start - 1 : end]) for start, end in merged
        ]
        return "\n\n".join(excerpts)

    def extract_with_ast_scope(self, file_path: str, symbols: list[SymbolReference]) -> str:
        """Feature C (AST Enclosing Scope Slicing) -- like `extract`, but
        instead of a flat margin around every symbol, builds three
        distinct kinds of range per the task spec:

        1. File header & package/import statements (see
           `_HEADER_LINE_PATTERN`'s own comment for the exact heuristic
           and why it's text-based, not a live tree-sitter parse).
        2. Enclosing type/struct/class declaration -- for a CLASS-kind
           symbol in `symbols` (ContextResolver._enrich_with_constructors
           adds a selected method's own parent class here specifically
           for this), only its OWN declaration line (start_line), never
           its full body range -- the class's other members are exactly
           the "unreferenced sibling methods" the task says to omit.
        3. Target function/method implementation body + 5 lines context
           buffer (`_AST_SCOPE_MARGIN_LINES`) -- everything that isn't
           CLASS-kind, same range-extraction shape as `extract` but with
           the wider margin.

        Every range still only ever comes from `symbols` actually passed
        in (ContextBudgetManager's `_symbols_by_file`, which only holds
        symbols this file was actually resolved/impacted for) -- an
        unreferenced sibling method never gets its own range just for
        living in the same file, exactly like `extract` already
        guarantees today."""
        if not symbols:
            return ""

        text = self._permissions.safe_read_text(file_path)
        lines = text.splitlines()
        total_lines = len(lines)

        raw_ranges: list[tuple[int, int]] = []
        header_end = self._header_end_line(lines)
        if header_end > 0:
            raw_ranges.append((1, header_end))
        for symbol in symbols:
            if symbol.kind is SymbolKind.CLASS:
                raw_ranges.append((symbol.start_line, symbol.start_line))
            else:
                raw_ranges.append(
                    (
                        max(1, symbol.start_line - _AST_SCOPE_MARGIN_LINES),
                        min(total_lines, symbol.end_line + _AST_SCOPE_MARGIN_LINES),
                    )
                )
        merged = self._merge(sorted(raw_ranges))

        excerpts = [
            f"# lines {start}-{end}\n" + "\n".join(lines[start - 1 : end]) for start, end in merged
        ]
        return "\n\n".join(excerpts)

    @staticmethod
    def _header_end_line(lines: list[str]) -> int:
        end = 0
        for line_number, line in enumerate(lines[:_MAX_HEADER_SCAN_LINES], start=1):
            if _HEADER_LINE_PATTERN.match(line):
                end = line_number
            else:
                break
        return end

    @staticmethod
    def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
        merged: list[tuple[int, int]] = []
        for start, end in ranges:
            if merged and start <= merged[-1][1] + 1:
                previous_start, previous_end = merged[-1]
                merged[-1] = (previous_start, max(previous_end, end))
            else:
                merged.append((start, end))
        return merged
