"""ContextPackager — orchestrates Phase 6's pipeline into one
ContextPackage: RelevanceRanker -> ContextBudgetManager -> (optional)
ContextUnderstandingAnalyzer.

ContextBudgetManager (and the PermissionManager/SymbolRangeCompressor it
needs) is built fresh per call, scoped to result.repository_root —
different contracts can point at different workspaces, so a
PermissionManager fixed at construction time would silently read from
the wrong repository the moment two contracts with different workspaces
were packaged through the same singleton ContextPackager. RelevanceRanker
and ContextUnderstandingAnalyzer have no workspace dependency, so those
are safe to inject once.

understanding_analyzer is optional; when it's None, or when it fails,
ContextPackager still returns a complete, valid ContextPackage with
empty understanding_notes — selection is never SLM-decided, so SLM-2
being unavailable doesn't break packaging, only removes its commentary.

Repository debugging routing fix, Change 6 (diagnostic logging): emits
one DEBUG-level JSON log line per package() call via the
"arcf.retrieval" logger (files_sent_to_llm, budget_used_tokens,
excluded_file_count), keyed by context_resolution_id — the other half
of the routing-decision log code_intelligence/service.py emits at
resolution time (see that module's own docstring for why these are two
correlated lines rather than one). Internal/DEBUG only.
"""

import asyncio
import json
import logging
from pathlib import Path

from context.budget_manager import ContextBudgetManager
from context.compressor import SymbolRangeCompressor
from context.relevance_ranker import RelevanceRanker
from context.understanding import ContextUnderstandingAnalyzer
from domain.context_package import ContextPackage
from domain.context_resolution import ContextResolutionResult
from infrastructure.cost import CostEstimator
from infrastructure.llm_client import LLMResponse
from shared.errors import ContextUnderstandingError, LLMInvocationError
from workspace.permissions import PermissionManager

_logger = logging.getLogger("arcf.retrieval")


class ContextPackager:
    def __init__(
        self,
        ranker: RelevanceRanker,
        token_estimator: CostEstimator,
        understanding_analyzer: ContextUnderstandingAnalyzer | None = None,
    ) -> None:
        self._ranker = ranker
        self._token_estimator = token_estimator
        self._understanding_analyzer = understanding_analyzer

    async def package(
        self,
        result: ContextResolutionResult,
        raw_request: str,
        max_tokens: int,
        ranking_profile: dict[str, float] | None = None,
    ) -> tuple[ContextPackage, LLMResponse | None]:
        permissions = PermissionManager(Path(result.repository_root))
        budget_manager = ContextBudgetManager(
            permissions, self._token_estimator, SymbolRangeCompressor(permissions)
        )

        ranked = await asyncio.to_thread(self._ranker.rank, result, ranking_profile)
        packaged_files, used_tokens, excluded_count = await asyncio.to_thread(
            budget_manager.select, ranked, result, max_tokens
        )

        understanding_notes: list[str] = []
        llm_response: LLMResponse | None = None
        if self._understanding_analyzer is not None and packaged_files:
            try:
                note, llm_response = await self._understanding_analyzer.analyze(
                    raw_request, ranked, result.entry_points
                )
            except (ContextUnderstandingError, LLMInvocationError):
                pass
            else:
                if note.summary:
                    understanding_notes.append(note.summary)
                understanding_notes.extend(note.key_relationships)

        raw_tokens = result.token_estimate.raw_context_tokens
        prompt_compression_ratio = round(raw_tokens / used_tokens, 4) if used_tokens else 0.0

        package = ContextPackage(
            contract_id=result.contract_id,
            workspace_id=result.workspace_id,
            context_resolution_id=result.id,
            relevant_files=packaged_files,
            dependency_chain=result.dependency_chain,
            budget_max_tokens=max_tokens,
            budget_used_tokens=used_tokens,
            prompt_compression_ratio=prompt_compression_ratio,
            excluded_file_count=excluded_count,
            understanding_notes=understanding_notes,
            compressed_snippet_count=sum(1 for file in packaged_files if file.truncated),
        )
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug(
                json.dumps(
                    {
                        "context_resolution_id": str(result.id),
                        "files_sent_to_llm": len(packaged_files),
                        "budget_used_tokens": used_tokens,
                        "excluded_file_count": excluded_count,
                    }
                )
            )
        return package, llm_response
