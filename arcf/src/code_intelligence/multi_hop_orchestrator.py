"""MultiHopOrchestrator (ARCF Phase 7 spike: Language Semantic Enrichment)
— chains one LSE relationship graph (decorators, for this first spike)
into ARCF's EXISTING, stable retrieval machinery, rather than building a
second traversal engine. Standalone: nothing in code_intelligence/service.py
calls this today — it's an experimental branch, evaluated separately from
the stable pipeline, per Phase 7's own constraint ("must not replace ARCF
retrieval").

Two hops, each gated before the next is allowed to run:

Hop 1 (LSE): match the query's wording against every known decorator name
(DecoratorGraph.known_decorator_names(), reusing the exact prefix-
substring technique lexical_symbol_probe.py already uses elsewhere —
shares_lexical_root). Every decorated symbol's file is added, tagged
EvidenceTier.EXPERIMENTAL, then IMMEDIATELY pruned via
context.evidence_validator.prune_experimental_candidates — BEFORE any
further expansion. This ordering is the whole point: a low-confidence
hop-1 decorator match never gets the chance to fan out into hop 2, which
is what would repeat this session's FastAPI Depends/FastAPI blowup
(20 unpruned lexical matches each independently expanding through the
call graph) at compounded, multi-hop scale instead of single-hop.

Hop 2 (existing ARCF, not new code): survivors' symbol NAMES are fed into
ContextResolver.resolve() as target_names — exactly the same mechanism a
confident SLM-1-extracted entity would use, and the same pattern
code_intelligence/service.py's own lexical-probe recovery already
establishes (merge candidate_files/entry_points/impacted_symbols
additively, never touching what was already there). Capped at a shallower
depth than even that lexical-probe recovery gets, since this is hop 2 of
a chain already built on an uncertain hop 1.

Never mutates or replaces `baseline_result` — additive only. If nothing
about the query lexically matches any known decorator, this is a no-op
that returns the baseline result unchanged (byte-identical to today's
stable pipeline for any query with no decorator signal at all).
"""

from collections import defaultdict
from dataclasses import dataclass

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.index import CodeIntelligenceIndex
from context.evidence_validator import prune_experimental_candidates
from context.lexical_symbol_probe import shares_lexical_root
from domain.code_intelligence import Symbol
from domain.context_resolution import ContextResolutionResult, EvidenceTier, FileReference

_HOP2_TRAVERSAL_DEPTH = 1
"""Deliberately the most conservative depth anywhere in the pipeline —
shallower than confident matches get, and no deeper than
code_intelligence/service.py's own _LEXICAL_PROBE_RECOVERY_DEPTH (already
a deliberately conservative choice for single-hop lexical recovery). Hop
2 here is built on top of an already-uncertain hop 1, so it gets the
tightest budget, not the same one."""


@dataclass(frozen=True)
class MultiHopEnrichmentReport:
    """What the orchestrator actually did, for the Phase 7 benchmark to
    report directly rather than infer from candidate_files diffing."""

    matched_decorator_names: tuple[str, ...]
    hop1_proposed: int
    hop1_pruned: tuple[str, ...]
    hop2_new_files: tuple[str, ...]


class MultiHopOrchestrator:
    def __init__(self, index: CodeIntelligenceIndex) -> None:
        self._index = index

    def enrich(
        self, baseline_result: ContextResolutionResult, raw_request: str
    ) -> tuple[ContextResolutionResult, MultiHopEnrichmentReport]:
        matched_names = sorted(
            name
            for name in self._index.decorator_graph.known_decorator_names()
            if shares_lexical_root(name, raw_request)
        )
        empty_report = MultiHopEnrichmentReport(
            matched_decorator_names=tuple(matched_names),
            hop1_proposed=0,
            hop1_pruned=(),
            hop2_new_files=(),
        )
        if not matched_names:
            return baseline_result, empty_report

        symbols_by_file, hop1_result = self._add_hop1_candidates(baseline_result, matched_names)
        if hop1_result is baseline_result:
            return baseline_result, empty_report

        pruned_result, prune_report = prune_experimental_candidates(hop1_result, raw_request)
        survivor_names = sorted(
            {
                symbol.name
                for file_path in prune_report.kept
                for symbol in symbols_by_file.get(file_path, [])
            }
        )
        if not survivor_names:
            return pruned_result, MultiHopEnrichmentReport(
                matched_decorator_names=tuple(matched_names),
                hop1_proposed=prune_report.proposed,
                hop1_pruned=prune_report.pruned,
                hop2_new_files=(),
            )

        hop2_result = self._hop2_expand(pruned_result, survivor_names)
        new_hop2_files = tuple(
            sorted(
                {ref.file_path for ref in hop2_result.candidate_files}
                - {ref.file_path for ref in pruned_result.candidate_files}
            )
        )
        return hop2_result, MultiHopEnrichmentReport(
            matched_decorator_names=tuple(matched_names),
            hop1_proposed=prune_report.proposed,
            hop1_pruned=prune_report.pruned,
            hop2_new_files=new_hop2_files,
        )

    def _add_hop1_candidates(
        self, baseline_result: ContextResolutionResult, matched_names: list[str]
    ) -> tuple[dict[str, list[Symbol]], ContextResolutionResult]:
        decorator_graph = self._index.decorator_graph
        symbol_index = self._index.symbol_index

        matched_symbol_ids: set[str] = set()
        for name in matched_names:
            matched_symbol_ids |= decorator_graph.symbols_decorated_by(name)

        symbols_by_file: dict[str, list[Symbol]] = defaultdict(list)
        existing_paths = {ref.file_path for ref in baseline_result.candidate_files}
        new_refs_by_path: dict[str, FileReference] = {}

        for symbol_id in sorted(matched_symbol_ids):
            symbol = symbol_index.get(symbol_id)
            if symbol is None:
                continue
            # Recorded regardless of whether this file is new — hop 2
            # needs to know which symbols to expand from even for a file
            # the baseline pipeline already established for other
            # reasons. Deliberately NOT feeding already-established
            # files' decorated symbols into hop 2, though (see below):
            # only files that survive pruning as NEW, EXPERIMENTAL
            # candidates get to seed hop 2 — an already-established file
            # was already fully considered by the baseline pipeline on
            # its own terms.
            symbols_by_file[symbol.file_path].append(symbol)
            if symbol.file_path in existing_paths or symbol.file_path in new_refs_by_path:
                continue
            decorator_names = sorted(
                {d.decorator_name for d in decorator_graph.decorators_of(symbol_id)}
            )
            reason = f"decorated by {', '.join(decorator_names)}"
            analysis = self._index.file_analyses.get(symbol.file_path)
            new_refs_by_path[symbol.file_path] = FileReference(
                file_path=symbol.file_path,
                reason=reason,
                language=analysis.language if analysis is not None else "unknown",
                token_count=self._index.token_counts.get(symbol.file_path, 0),
                justification_chain=(reason,),
                evidence_tier=EvidenceTier.EXPERIMENTAL,
            )

        if not new_refs_by_path:
            return dict(symbols_by_file), baseline_result

        merged_files = sorted(
            [*baseline_result.candidate_files, *new_refs_by_path.values()],
            key=lambda ref: ref.file_path,
        )
        selected_tokens = sum(ref.token_count for ref in merged_files)
        raw_tokens = baseline_result.token_estimate.raw_context_tokens
        updated = baseline_result.model_copy(
            update={
                "candidate_files": merged_files,
                "token_estimate": baseline_result.token_estimate.model_copy(
                    update={
                        "selected_context_tokens": selected_tokens,
                        "compression_ratio": (
                            round(selected_tokens / raw_tokens, 4) if raw_tokens else 0.0
                        ),
                    }
                ),
                "resolution_reason": (
                    f"{baseline_result.resolution_reason} LSE hop 1: decorator match on "
                    f"{', '.join(matched_names)} added {len(new_refs_by_path)} file(s)."
                ),
            }
        )
        return dict(symbols_by_file), updated

    def _hop2_expand(
        self, pruned_result: ContextResolutionResult, survivor_names: list[str]
    ) -> ContextResolutionResult:
        hop2_result = ContextResolver(self._index).resolve(
            pruned_result.workspace_id,
            pruned_result.contract_id,
            pruned_result.repository_root,
            survivor_names,
            traversal_depth=_HOP2_TRAVERSAL_DEPTH,
            entry_point_tier=EvidenceTier.EXPERIMENTAL,
        )
        existing_paths = {ref.file_path for ref in pruned_result.candidate_files}
        new_refs = [
            ref for ref in hop2_result.candidate_files if ref.file_path not in existing_paths
        ]
        if not new_refs:
            return pruned_result

        merged_files = sorted(
            [*pruned_result.candidate_files, *new_refs], key=lambda ref: ref.file_path
        )
        existing_symbol_ids = {symbol.symbol_id for symbol in pruned_result.entry_points}
        merged_entry_points = [
            *pruned_result.entry_points,
            *(
                symbol
                for symbol in hop2_result.entry_points
                if symbol.symbol_id not in existing_symbol_ids
            ),
        ]
        existing_impacted_ids = {symbol.symbol_id for symbol in pruned_result.impacted_symbols}
        merged_impacted = [
            *pruned_result.impacted_symbols,
            *(
                symbol
                for symbol in hop2_result.impacted_symbols
                if symbol.symbol_id not in existing_impacted_ids
            ),
        ]
        selected_tokens = sum(ref.token_count for ref in merged_files)
        raw_tokens = pruned_result.token_estimate.raw_context_tokens
        return pruned_result.model_copy(
            update={
                "candidate_files": merged_files,
                "entry_points": merged_entry_points,
                "impacted_symbols": merged_impacted,
                "token_estimate": pruned_result.token_estimate.model_copy(
                    update={
                        "selected_context_tokens": selected_tokens,
                        "compression_ratio": (
                            round(selected_tokens / raw_tokens, 4) if raw_tokens else 0.0
                        ),
                    }
                ),
                "resolution_reason": (
                    f"{pruned_result.resolution_reason} LSE hop 2: expanded "
                    f"{len(survivor_names)} pruning-survivor symbol(s) via existing "
                    f"call-graph/inheritance machinery, adding {len(new_refs)} file(s)."
                ),
            }
        )
