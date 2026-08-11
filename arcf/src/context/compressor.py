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
#
# Tuned down 2026-08-11 after measuring real Consul token costs
# (scripts/measure_realtime_pipeline.py "Register" query): the original
# 50-line cap and unbounded trailing-blank tolerance were never actually
# the dominant cost (the 5-line AST-scope margin above was, ~3x more per
# file in the measured case) but were still real, avoidable waste --
# _MAX_HEADER_SCAN_LINES=50 was far more headroom than any real header
# in this codebase's own source needs, and the pattern's own trailing
# blank-line tolerance let a header "end" on a dangling `import (` line
# (Go's multi-line import syntax: none of the individual quoted import
# paths inside the parens match this pattern, so scanning always stops
# right at the opener) or a run of blank lines with nothing after
# them -- both cost tokens without adding any real content.
_HEADER_LINE_PATTERN = re.compile(
    r'^\s*($|#|//|/\*|\*|"""|\'\'\'|package\s|import\s|from\s+\S+\s+import|using\s)'
)
_MEANINGFUL_HEADER_LINE_PATTERN = re.compile(r"^\s*\S")  # excludes blank lines
# Go's multi-line `import (` block: none of the individual quoted import
# paths inside the parens match _HEADER_LINE_PATTERN, so the scan always
# stops right at the opener -- trimmed off specifically since a bare
# "import (" with nothing after it costs a line for zero real content.
_DANGLING_IMPORT_OPENER_PATTERN = re.compile(r"^\s*import\s*\(\s*$")
_MAX_HEADER_SCAN_LINES = 15

# Feature 2 (Two-Tier AST Snippet Rendering, 2026-08-11): placeholder
# text substituted for an omitted function/method body -- deliberately
# says WHY it's missing (not just "...") so a reader (human or LLM)
# doesn't mistake it for truncation/corruption and knows a fuller
# excerpt exists if this really is the symbol they need.
_OMITTED_BODY_PLACEHOLDER = "    // ... implementation omitted (secondary candidate; see focal candidate or a directly call-linked file for the body) ..."


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

    def extract_skeleton_only(self, file_path: str, symbols: list[SymbolReference]) -> str:
        """Feature 2 (Two-Tier AST Snippet Rendering) -- for RANK 2+
        ("secondary") candidates: same header + class-declaration-line
        treatment as `extract_with_ast_scope`, but a FUNCTION/METHOD
        symbol's own implementation body is stripped and replaced with
        `_OMITTED_BODY_PLACEHOLDER`, keeping only its signature (name,
        parameters, return type) plus the `_AST_SCOPE_MARGIN_LINES`
        buffer around it -- the struct/type CONTRACT a secondary file
        usually needs to convey, without paying for the body's tokens.
        Only the FOCAL (rank-1) candidate and any candidate directly
        (hop-1) call-graph-linked to it get the full body — see
        ContextBudgetManager's own docstring for that routing decision;
        this method only knows how to skeletonize, not which candidates
        should be.

        `_find_body_start_line`'s own docstring explains the signature/
        body boundary heuristic and its known limits — this is Phase 6
        (domain-only, no tree-sitter access), so it's text-based, same
        constraint `_header_end_line` already documents."""
        if not symbols:
            return ""

        text = self._permissions.safe_read_text(file_path)
        lines = text.splitlines()
        total_lines = len(lines)

        raw_ranges: list[tuple[int, int]] = []
        omissions: list[tuple[int, int]] = []
        header_end = self._header_end_line(lines)
        if header_end > 0:
            raw_ranges.append((1, header_end))
        for symbol in symbols:
            if symbol.kind is SymbolKind.CLASS:
                raw_ranges.append((symbol.start_line, symbol.start_line))
                continue
            raw_ranges.append(
                (
                    max(1, symbol.start_line - _AST_SCOPE_MARGIN_LINES),
                    min(total_lines, symbol.end_line + _AST_SCOPE_MARGIN_LINES),
                )
            )
            if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                body_start = self._find_body_start_line(lines, symbol.start_line, symbol.end_line)
                if body_start <= symbol.end_line:
                    omissions.append((body_start, symbol.end_line))
        merged = self._merge(sorted(raw_ranges))

        excerpts = [
            self._render_with_omissions(lines, start, end, omissions) for start, end in merged
        ]
        return "\n\n".join(excerpts)

    @staticmethod
    def _render_with_omissions(
        lines: list[str], start: int, end: int, omissions: list[tuple[int, int]]
    ) -> str:
        rendered: list[str] = []
        line_number = start
        while line_number <= end:
            omission = next((o for o in omissions if o[0] <= line_number <= o[1]), None)
            if omission is not None:
                rendered.append(_OMITTED_BODY_PLACEHOLDER)
                line_number = omission[1] + 1
                continue
            rendered.append(lines[line_number - 1])
            line_number += 1
        return f"# lines {start}-{end}\n" + "\n".join(rendered)

    @staticmethod
    def _find_body_start_line(lines: list[str], start_line: int, end_line: int) -> int:
        """Returns the 1-indexed line where a function/method BODY
        begins (the first line to omit) -- one past the signature's own
        last line. Heuristic, not a parser: tracks parenthesis depth
        across the declaration (so a parameter list spanning multiple
        lines, or containing its own nested parens, doesn't fool it into
        stopping early); once paren depth returns to zero, the first
        line from there on that contains `{` (brace languages, K&R or
        Allman style) or ends with `:` (Python) marks the signature's
        end. Returns `end_line + 1` (a sentinel guaranteed greater than
        `end_line`, so the caller's `body_start <= symbol.end_line`
        check is False and NOTHING gets omitted) if neither pattern
        appears within the symbol's own AST-derived range --
        under-omitting is the safe failure mode; a body left in by
        mistake just costs tokens, never loses information."""
        paren_depth = 0
        for line_number in range(start_line, min(end_line, len(lines)) + 1):
            line = lines[line_number - 1]
            for ch in line:
                if ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    paren_depth = max(0, paren_depth - 1)
            if paren_depth == 0:
                if "{" in line or line.rstrip().endswith(":"):
                    return line_number + 1
        return end_line + 1

    @staticmethod
    def _header_end_line(lines: list[str]) -> int:
        """Scans forward while lines look like header content, but the
        returned boundary is the LAST line that had real (non-blank)
        content, not wherever the scan happened to stop -- trims off a
        trailing run of blank lines or a dangling opener line (e.g. Go's
        `import (`, which nothing after it will ever match) that would
        otherwise cost tokens for nothing. A header that's entirely
        blank lines returns 0 (no header), same as never matching at
        all."""
        meaningful_line_numbers: list[int] = []
        for line_number, line in enumerate(lines[:_MAX_HEADER_SCAN_LINES], start=1):
            if not _HEADER_LINE_PATTERN.match(line):
                break
            if _MEANINGFUL_HEADER_LINE_PATTERN.match(line):
                meaningful_line_numbers.append(line_number)

        while meaningful_line_numbers and _DANGLING_IMPORT_OPENER_PATTERN.match(
            lines[meaningful_line_numbers[-1] - 1]
        ):
            meaningful_line_numbers.pop()

        return meaningful_line_numbers[-1] if meaningful_line_numbers else 0

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
