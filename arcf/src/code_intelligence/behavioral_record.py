"""BehavioralRecordBuilder (ARCF-DI Phase 4) — pure aggregation of
Phases 1-3's evidence into one BehavioralRecord per repository-defined
FUNCTION/METHOD symbol. No new evidence extraction happens here: every
field is read from SymbolIndex/CallGraph/FileAnalysis, objects Phases
1-3 already produce deterministically. This module never imports
infrastructure.llm_client — Phase 5 (summarization) is a separate,
downstream consumer of BehavioralRecord, not a dependency of it.

Deliberately takes explicit components (SymbolIndex, CallGraph,
per-file FileAnalysis) rather than the whole CodeIntelligenceIndex —
index.py's own docstring restricts CodeIntelligenceIndex references to
itself and context_resolver.py; this keeps that boundary intact and
keeps the builder trivially testable with hand-built fixtures, the same
pattern CallGraph/InheritanceGraph already use (take a resolver, not an
engine).
"""

from code_intelligence.call_graph import CallGraph
from code_intelligence.symbol_index import SymbolIndex
from domain.behavioral_record import (
    AmbiguousCall,
    BehavioralRecord,
    DependencyDepth,
    RecordComplexity,
    TransitiveCallee,
)
from domain.code_intelligence import CallResolutionConfidence, FileAnalysis, SymbolKind

_DEFAULT_MAX_INDIRECT_HOPS = 5


class BehavioralRecordBuilder:
    def __init__(
        self,
        symbol_index: SymbolIndex,
        call_graph: CallGraph,
        file_analyses: dict[str, FileAnalysis],
        max_indirect_hops: int = _DEFAULT_MAX_INDIRECT_HOPS,
    ) -> None:
        self._symbol_index = symbol_index
        self._call_graph = call_graph
        self._file_analyses = file_analyses
        self._max_indirect_hops = max_indirect_hops
        # A CallGraph built with mandatory_disambiguation=True is the only
        # one that ever populates resolution_confidence/candidates; a
        # single resolved call carrying either is sufficient (and cheap)
        # evidence that the flag was on for this graph, without requiring
        # the caller to also pass it here and risk the two disagreeing.
        self._disambiguation_aware = any(
            call.resolution_confidence is not None for call in call_graph.resolved_calls
        )

    def build(self, symbol_id: str) -> BehavioralRecord | None:
        symbol = self._symbol_index.get(symbol_id)
        if symbol is None or symbol.kind not in (SymbolKind.FUNCTION, SymbolKind.METHOD):
            return None

        file_analysis = self._file_analyses.get(symbol.file_path)
        file_import_ids = (
            [imp.id for imp in file_analysis.imports] if file_analysis is not None else []
        )
        external_libraries_used = sorted(
            {
                imp.resolved_library
                for imp in (file_analysis.imports if file_analysis is not None else [])
                if imp.resolved_library is not None
            }
        )

        direct_callees = sorted(self._call_graph.callee_symbols_of(symbol_id))
        direct_callers = sorted(self._call_graph.caller_symbols_of(symbol_id))

        transitive = self._call_graph.transitive_callee_symbols_of(
            symbol_id, max_depth=self._max_indirect_hops
        )
        indirect_callees = sorted(
            (
                TransitiveCallee(symbol_id=sid, hop=hop)
                for sid, (hop, _parent) in transitive.items()
            ),
            key=lambda t: (t.hop, t.symbol_id),
        )
        deepest_hop = max((t.hop for t in indirect_callees), default=0)
        dependency_depth = DependencyDepth(
            hops=deepest_hop, truncated=deepest_hop == self._max_indirect_hops
        )

        ambiguous_calls = sorted(
            (
                AmbiguousCall(
                    call_id=call.id, callee_name=call.callee_name, candidates=call.candidates
                )
                for call in self._call_graph.resolved_calls
                if call.caller_id == symbol_id
                and call.resolution_confidence is CallResolutionConfidence.AMBIGUOUS_MULTI
            ),
            key=lambda a: a.call_id,
        )

        line_count = symbol.location.end_line - symbol.location.start_line + 1
        complexity = RecordComplexity(line_count=line_count, direct_call_count=len(direct_callees))

        return BehavioralRecord(
            symbol_id=symbol.id,
            qualified_name=symbol.qualified_name,
            kind=symbol.kind,
            language=file_analysis.language if file_analysis is not None else "unknown",
            location=symbol.location,
            file_import_ids=file_import_ids,
            direct_callees=direct_callees,
            direct_callers=direct_callers,
            indirect_callees=indirect_callees,
            dependency_depth=dependency_depth,
            ambiguous_calls=ambiguous_calls,
            disambiguation_aware=self._disambiguation_aware,
            external_libraries_used=external_libraries_used,
            complexity=complexity,
        )

    def build_all(self) -> list[BehavioralRecord]:
        """Every FUNCTION/METHOD symbol, deterministically ordered by id —
        never dict/set iteration order."""
        records = []
        for symbol in sorted(self._symbol_index.all(), key=lambda s: s.id):
            if symbol.kind not in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                continue
            record = self.build(symbol.id)
            if record is not None:
                records.append(record)
        return records
