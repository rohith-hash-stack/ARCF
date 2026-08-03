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

from domain.context_resolution import SymbolReference
from workspace.permissions import PermissionManager

DEFAULT_MARGIN_LINES = 2


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
