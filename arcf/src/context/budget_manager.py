"""ContextBudgetManager (Phase 6 deliverable: Budget-aware context) —
greedy selection over RelevanceRanker's output against a token budget.

Deterministic, like the ranker: files are taken in ranked order until
the budget runs out. A file that doesn't fit in full falls back to
SymbolRangeCompressor's line-range extraction before being excluded
outright — compression is tried before exclusion, exclusion is the
last resort, and the returned excluded count makes that visible rather
than silent.

Resolution and packaging can happen as two separate API calls, so a
file present at resolution time may be gone (or unreadable) by the time
packaging runs — that's a real race, not a hypothetical, and is treated
the same as "didn't fit": excluded, not a hard failure of the whole
package.
"""

from collections import defaultdict

from context.compressor import SymbolRangeCompressor
from context.relevance_ranker import RankedFile
from domain.context_package import PackagedFile
from domain.context_resolution import ContextResolutionResult, SymbolReference
from infrastructure.cost import CostEstimator
from shared.errors import WorkspacePathError
from workspace.permissions import PermissionManager

_TOKEN_ESTIMATE_MODEL = "gpt-4o-mini"
_READ_ERRORS: tuple[type[Exception], ...] = (OSError, WorkspacePathError)


class ContextBudgetManager:
    def __init__(
        self,
        permissions: PermissionManager,
        token_estimator: CostEstimator,
        compressor: SymbolRangeCompressor,
    ) -> None:
        self._permissions = permissions
        self._token_estimator = token_estimator
        self._compressor = compressor

    def select(
        self,
        ranked_files: list[RankedFile],
        result: ContextResolutionResult,
        max_tokens: int,
    ) -> tuple[list[PackagedFile], int, int]:
        """Returns (packaged_files, tokens_used, excluded_file_count)."""
        symbols_by_file = self._symbols_by_file(result)

        packaged: list[PackagedFile] = []
        used = 0
        excluded = 0

        for ranked in ranked_files:
            remaining = max_tokens - used
            if remaining <= 0:
                excluded += 1
                continue

            if ranked.token_count <= remaining:
                try:
                    content = self._permissions.safe_read_text(ranked.file_path)
                except _READ_ERRORS:
                    excluded += 1
                    continue
                packaged.append(
                    PackagedFile(
                        file_path=ranked.file_path,
                        content=content,
                        relevance_score=ranked.relevance_score,
                        reason=ranked.reason,
                        token_count=ranked.token_count,
                        truncated=False,
                    )
                )
                used += ranked.token_count
                continue

            symbols_in_file = symbols_by_file.get(ranked.file_path, [])
            try:
                excerpt = self._compressor.extract(ranked.file_path, symbols_in_file)
            except _READ_ERRORS:
                excluded += 1
                continue
            if not excerpt:
                excluded += 1
                continue

            excerpt_tokens = self._token_estimator.count_tokens(excerpt, _TOKEN_ESTIMATE_MODEL)
            if excerpt_tokens > remaining:
                excluded += 1
                continue

            packaged.append(
                PackagedFile(
                    file_path=ranked.file_path,
                    content=excerpt,
                    relevance_score=ranked.relevance_score,
                    reason=ranked.reason,
                    token_count=excerpt_tokens,
                    truncated=True,
                )
            )
            used += excerpt_tokens

        return packaged, used, excluded

    @staticmethod
    def _symbols_by_file(result: ContextResolutionResult) -> dict[str, list[SymbolReference]]:
        by_file: dict[str, list[SymbolReference]] = defaultdict(list)
        for symbol in (*result.entry_points, *result.impacted_symbols):
            by_file[symbol.file_path].append(symbol)
        return by_file
