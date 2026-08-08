"""ContextBudgetManager (Phase 6 deliverable: Budget-aware context) —
greedy selection over RelevanceRanker's output against a token budget.

Deterministic, like the ranker: files are taken in ranked order until
the budget runs out. A file that doesn't fit in full falls back to
SymbolRangeCompressor's line-range extraction before being excluded
outright — compression is tried before exclusion, exclusion is the
last resort, and the returned excluded count makes that visible rather
than silent.

Evidence-preserving context packaging: that "doesn't fit -> compress"
trigger is *also*, independently, driven by evidence_tier now — not
just remaining budget. A SUPPORTING file (call-graph/inheritance/
lexical-probe/repository-scope expansion — see domain.
context_resolution.EvidenceTier's own docstring) with a known symbol
location is compressed to that symbol's range up front, regardless of
whether the full file would fit: a fan-out match shouldn't spend the
same budget as the thing actually being asked about just because it
happens to live in a large file (the motivating case: a lexically-
probed symbol defined inside a framework's 49K-token core routing
module, when the file that actually answers the question is 400
tokens). PRIMARY evidence (a confident direct match, or a file the
query itself named) keeps the plain full-if-it-fits behavior described
above unchanged — this is strictly an additional, earlier trigger for
compression, not a replacement of the existing one, and reuses the same
SymbolRangeCompressor either way.

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
from domain.context_resolution import ContextResolutionResult, EvidenceTier, SymbolReference
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

            symbols_in_file = symbols_by_file.get(ranked.file_path, [])

            # Evidence-preserving context packaging (see this class's own
            # docstring): SUPPORTING evidence with a known symbol location
            # is compressed up front, before ever checking whether the
            # full file would fit — deliberately NOT gated on remaining
            # budget the way the fallback compression below is. A file
            # with no symbol location (e.g. a glob-matched "evidence:
            # <category>" file — README, pyproject.toml — nothing here to
            # extract a range *around*) falls through to the same
            # full-if-fits behavior PRIMARY evidence gets, since there is
            # no narrower "relevant part" to prefer over the whole file.
            compress_first_tiers = (EvidenceTier.SUPPORTING, EvidenceTier.EXPERIMENTAL)
            if ranked.evidence_tier in compress_first_tiers and symbols_in_file:
                compressed = self._compress(ranked, symbols_in_file, remaining)
                if compressed is not None:
                    packaged.append(compressed)
                    used += compressed.token_count
                else:
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

            compressed = self._compress(ranked, symbols_in_file, remaining)
            if compressed is not None:
                packaged.append(compressed)
                used += compressed.token_count
            else:
                excluded += 1

        return packaged, used, excluded

    def _compress(
        self, ranked: RankedFile, symbols_in_file: list[SymbolReference], remaining: int
    ) -> PackagedFile | None:
        """Shared by both compression triggers above (evidence-tier-driven
        and doesn't-fit-in-full): `None` means "couldn't produce a
        compressed excerpt that fits" — the caller counts that as
        excluded, same as it always has for the doesn't-fit path."""
        try:
            excerpt = self._compressor.extract(ranked.file_path, symbols_in_file)
        except _READ_ERRORS:
            return None
        if not excerpt:
            return None

        excerpt_tokens = self._token_estimator.count_tokens(excerpt, _TOKEN_ESTIMATE_MODEL)
        if excerpt_tokens > remaining:
            return None

        return PackagedFile(
            file_path=ranked.file_path,
            content=excerpt,
            relevance_score=ranked.relevance_score,
            reason=ranked.reason,
            token_count=excerpt_tokens,
            truncated=True,
        )

    @staticmethod
    def _symbols_by_file(result: ContextResolutionResult) -> dict[str, list[SymbolReference]]:
        by_file: dict[str, list[SymbolReference]] = defaultdict(list)
        for symbol in (*result.entry_points, *result.impacted_symbols):
            by_file[symbol.file_path].append(symbol)
        return by_file
