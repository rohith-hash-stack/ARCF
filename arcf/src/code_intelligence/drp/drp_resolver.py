"""DrpResolver — DRP's public entry point, mirroring
`code_intelligence.context_resolver.ContextResolver`'s own role: a thin
translation layer from DRP's internal routing result into the exact
same `domain.context_resolution.ContextResolutionResult` shape the
classic resolver produces, so everything downstream of resolution
(`RelevanceRanker`, `ContextBudgetManager`, `ContextPackager`) works
completely unmodified regardless of which resolver produced the result.

`ContextResolver` itself is never imported or subclassed here — DRP is a
parallel, independent path, not a variant of the classic one.
"""

from __future__ import annotations

import time

from code_intelligence.drp.diagnostics import DrpDiagnostics
from code_intelligence.drp.drp_index import DrpIndex
from code_intelligence.drp.pmi_expansion import expand_query_terms
from code_intelligence.drp.query_router import route_query
from code_intelligence.drp.tfidf import tokenize
from code_intelligence.index import CodeIntelligenceIndex
from domain.code_intelligence import Symbol
from domain.context_resolution import (
    ContextResolutionResult,
    EvidenceTier,
    FileReference,
    SymbolReference,
    TokenEstimate,
)

# How many of the resolver's own candidate files diagnostics report —
# matches the Evaluation Framework's "top 20 files" instrumentation
# requirement.
_DIAGNOSTICS_TOP_FILES = 20


def _to_symbol_reference(symbol: Symbol) -> SymbolReference:
    return SymbolReference(
        symbol_id=symbol.id,
        name=symbol.name,
        qualified_name=symbol.qualified_name,
        kind=symbol.kind,
        file_path=symbol.file_path,
        start_line=symbol.location.start_line,
        end_line=symbol.location.end_line,
        parent_symbol_id=symbol.parent_id,
    )


class DrpResolver:
    def __init__(self, index: CodeIntelligenceIndex, drp_index: DrpIndex) -> None:
        self._index = index
        self._drp_index = drp_index

    def resolve(
        self,
        workspace_id: str,
        contract_id: str,
        repository_root: str,
        query: str,
        target_names: list[str] | None = None,
        traversal_depth: int = 2,
        enable_pmi_expansion: bool = False,
    ) -> tuple[ContextResolutionResult, DrpDiagnostics]:
        # target_names (e.g. SLM-1-extracted entities, the same input the
        # classic resolver takes) are folded into the query text rather
        # than driving a separate lookup path: DRP's whole premise is
        # that structural/TF-IDF signal should work even when no exact
        # symbol name is present, so entity names are just extra query
        # tokens here, not a privileged exact-match channel.
        full_query = query if not target_names else f"{query} {' '.join(target_names)}"

        # ARCF Issue #3 PMI query-expansion extension, off by default:
        # `enable_pmi_expansion=False` (or `pmi_graph=None`, i.e. DrpIndex
        # was built without it) leaves `full_query` completely untouched
        # — byte-identical to every existing DRP behavior. When on, only
        # query terms with ZERO document frequency anywhere in the file
        # corpus (file_tfidf.idf has no entry — they could never
        # discriminate any file regardless of wording) get expanded via
        # the repo-local PMI word graph; terms that already have real
        # corpus presence are left alone (see pmi_expansion.py's own
        # docstring for why this coverage gate, not a whole-query one).
        query_expansion = None
        if enable_pmi_expansion and self._drp_index.pmi_graph is not None:
            query_expansion = expand_query_terms(
                tokenize(full_query), self._drp_index.file_tfidf, self._drp_index.pmi_graph
            )
            if query_expansion.expanded_terms:
                inferred_terms = [
                    neighbor
                    for neighbors in query_expansion.expanded_terms.values()
                    for neighbor, _ in neighbors
                ]
                full_query = f"{full_query} {' '.join(inferred_terms)}"

        start = time.perf_counter()
        routing = route_query(
            full_query,
            self._drp_index.taxonomy,
            self._drp_index.file_tfidf,
            self._drp_index.file_to_units,
            self._drp_index.subsystem_graph,
            self._index,
            traversal_depth,
        )
        elapsed = time.perf_counter() - start

        subsystem_label = routing.winning_subsystem or "(root)"
        candidate_files: list[FileReference] = []
        impacted_symbols: list[SymbolReference] = []
        entry_points: list[SymbolReference] = []
        seen: set[str] = set()

        for file_path in routing.entry_files:
            analysis = self._index.file_analyses.get(file_path)
            if analysis is None or file_path in seen:
                continue
            seen.add(file_path)
            candidate_files.append(
                FileReference(
                    file_path=file_path,
                    reason=(
                        f"drp: subsystem {subsystem_label} "
                        f"(confidence {routing.winning_confidence:.2f})"
                    ),
                    language=analysis.language,
                    token_count=self._index.token_counts.get(file_path, 0),
                    evidence_tier=EvidenceTier.PRIMARY,
                )
            )
            for symbol in analysis.symbols:
                ref = _to_symbol_reference(symbol)
                impacted_symbols.append(ref)
                entry_points.append(ref)

        for file_path, (hop, parent) in sorted(routing.expansion.items()):
            analysis = self._index.file_analyses.get(file_path)
            if analysis is None or file_path in seen:
                continue
            seen.add(file_path)
            candidate_files.append(
                FileReference(
                    file_path=file_path,
                    reason=f"drp: imported by {parent} in subsystem {subsystem_label}",
                    language=analysis.language,
                    token_count=self._index.token_counts.get(file_path, 0),
                    evidence_tier=EvidenceTier.SUPPORTING,
                    justification_chain=(f"drp entry (hop {hop})",),
                )
            )
            for symbol in analysis.symbols:
                impacted_symbols.append(_to_symbol_reference(symbol))

        # A subsystem that came within a hair of winning (see
        # query_router.py's _NEAR_TIE_MARGIN) still gets its own best
        # files considered — winner-take-all with no margin was found,
        # against real Consul and Django runs, to exclude the correct
        # subsystem's files entirely over a 2-3% scoring gap. SUPPORTING,
        # not PRIMARY: these are corroborating candidates from a close
        # runner-up, not the resolver's actual top pick.
        for near_tied_subsystem in routing.near_tied_subsystems:
            for file_path in routing.near_tied_entry_files.get(near_tied_subsystem, []):
                analysis = self._index.file_analyses.get(file_path)
                if analysis is None or file_path in seen:
                    continue
                seen.add(file_path)
                candidate_files.append(
                    FileReference(
                        file_path=file_path,
                        reason=(
                            f"drp: near-tied subsystem {near_tied_subsystem} "
                            f"(close second to {subsystem_label})"
                        ),
                        language=analysis.language,
                        token_count=self._index.token_counts.get(file_path, 0),
                        evidence_tier=EvidenceTier.SUPPORTING,
                    )
                )
                for symbol in analysis.symbols:
                    impacted_symbols.append(_to_symbol_reference(symbol))

        raw_tokens = sum(self._index.token_counts.values())
        selected_tokens = sum(f.token_count for f in candidate_files)
        compression_ratio = selected_tokens / raw_tokens if raw_tokens else 0.0
        languages_detected = tuple(
            sorted({analysis.language for analysis in self._index.file_analyses.values()})
        )
        result_language = (
            candidate_files[0].language
            if candidate_files
            else (languages_detected[0] if languages_detected else "unknown")
        )
        retrieval_depth_used = max((hop for hop, _ in routing.expansion.values()), default=0)
        resolution_reason = (
            f"DRP resolved subsystem '{subsystem_label}' with confidence "
            f"{routing.winning_confidence:.2f}"
            if candidate_files
            else "DRP found no matching subsystem for this query"
        )

        result = ContextResolutionResult(
            workspace_id=workspace_id,
            contract_id=contract_id,
            repository_root=repository_root,
            language=result_language,
            candidate_files=candidate_files,
            impacted_symbols=impacted_symbols,
            entry_points=entry_points,
            confidence=routing.winning_confidence,
            token_estimate=TokenEstimate(
                raw_context_tokens=raw_tokens,
                selected_context_tokens=selected_tokens,
                compression_ratio=compression_ratio,
            ),
            resolution_reason=resolution_reason,
            retrieval_depth_used=retrieval_depth_used,
            languages_detected=languages_detected,
            files_scanned=len(self._index.file_analyses) + len(self._index.skipped_files),
            files_analyzed=len(self._index.file_analyses),
            analyzer_coverage=(
                len(self._index.file_analyses)
                / (len(self._index.file_analyses) + len(self._index.skipped_files))
                if (self._index.file_analyses or self._index.skipped_files)
                else 1.0
            ),
        )

        diagnostics = DrpDiagnostics(
            top_subsystem=routing.winning_subsystem,
            top_subsystem_confidence=routing.winning_confidence,
            top_community=routing.top_community_id,
            top_files=[f.file_path for f in candidate_files[:_DIAGNOSTICS_TOP_FILES]],
            resolver_latency_seconds=elapsed,
            graph_expansion_count=len(routing.expansion),
            subsystem_scores=[
                (s.subsystem_path, s.combined_score) for s in routing.subsystem_scores[:10]
            ],
            query_expansion=(
                {
                    term: [(neighbor, round(score, 4)) for neighbor, score in neighbors]
                    for term, neighbors in query_expansion.expanded_terms.items()
                }
                if query_expansion is not None
                else None
            ),
        )
        return result, diagnostics
