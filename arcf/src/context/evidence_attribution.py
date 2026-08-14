"""attribute_citations (ARCF-DI Phase 6) — enriches already-selected
PackagedFiles with structured evidence citations, without touching how
they were selected, ranked, or budgeted.

Deliberately a post-processing step over ContextPackager's existing
output, not a change to RelevanceRanker/ContextBudgetManager/
SymbolRangeCompressor: those are the well-tested selection pipeline
(BLUEPRINT.md Phase 6 explicitly says don't add a second ranking signal
without re-running the same ablation discipline that falsified the
semantic-reranker experiment). This module answers a narrower, purely
structural question — "what evidence backs the file that was already
selected" — by reusing Phase 4/5's own BehavioralRecordBuilder and
citable_evidence_ids, nothing new.

Citations are attributed per FILE, not per query: every FUNCTION/METHOD
symbol defined in a packaged file contributes its own citable evidence
ids to that file's `citations`. This deliberately does not attempt to
narrow citations to only the symbols relevant to the current query —
RelevanceRanker/SymbolRangeCompressor already decided the file (or
excerpt) is relevant; this module's job is only to make what backs that
file auditable, at file granularity, which is what PackagedFile itself
already operates at.
"""

from code_intelligence.behavioral_record import BehavioralRecordBuilder
from code_intelligence.call_graph import CallGraph
from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import CallResolutionConfidence, FileAnalysis, SymbolKind
from domain.context_package import PackagedFile


def attribute_citations(
    packaged_files: list[PackagedFile],
    symbol_index: SymbolIndex,
    call_graph: CallGraph,
    file_analyses: dict[str, FileAnalysis],
) -> list[PackagedFile]:
    """Returns new PackagedFile instances (frozen models) with `citations`/
    `ambiguous_evidence_ids` populated — never mutates its input, and
    preserves input order (the ranking ContextPackager already produced
    is not this module's concern)."""
    builder = BehavioralRecordBuilder(symbol_index, call_graph, file_analyses)

    enriched: list[PackagedFile] = []
    for packaged in packaged_files:
        citations: set[str] = set()
        ambiguous: set[str] = set()

        for symbol in symbol_index.by_file(packaged.file_path):
            if symbol.kind not in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                continue
            record = builder.build(symbol.id)
            if record is None:
                continue
            citations.update(record.file_import_ids)
            citations.update(record.direct_callees)
            citations.update(record.external_libraries_used)
            for call in record.ambiguous_calls:
                citations.add(call.call_id)
                ambiguous.add(call.call_id)

        enriched.append(
            packaged.model_copy(
                update={
                    "citations": sorted(citations),
                    "ambiguous_evidence_ids": sorted(ambiguous),
                }
            )
        )
    return enriched


def resolves_cleanly(packaged: PackagedFile, call_graph: CallGraph) -> bool:
    """True when none of `packaged.citations` trace back to an
    AMBIGUOUS_MULTI-resolved call — a convenience for callers that only
    want a yes/no signal rather than reading `ambiguous_evidence_ids`
    directly. Recomputes from the CallGraph's own resolved_calls rather
    than trusting `ambiguous_evidence_ids` blindly, so it stays correct
    even if a caller constructed a PackagedFile by hand without going
    through attribute_citations."""
    ambiguous_ids = {
        call.id
        for call in call_graph.resolved_calls
        if call.resolution_confidence is CallResolutionConfidence.AMBIGUOUS_MULTI
    }
    return not (set(packaged.citations) & ambiguous_ids)
