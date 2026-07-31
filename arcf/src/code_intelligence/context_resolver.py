"""ContextResolver — the only file besides CodeIntelligenceEngine itself
allowed to touch SymbolIndex/CallGraph/InheritanceGraph/DependencyGraph
internals. Everything it produces crosses into domain.context_resolution
types before leaving this module.

A thin translation layer, deliberately: it reuses CandidateFileSelector's
existing queries (callers_of, subclasses_of) rather than re-deriving
graph traversal, and ReferenceResolver/SymbolIndex for lookups. Its own
job is bookkeeping — turning "which files/symbols matter and why" into
the flat ContextResolutionResult shape, plus the deterministic
confidence score, resolution_reason, and token estimate that make the
result auditable and token-aware before any SLM is ever called.

Scope, deliberately bounded: candidate_files/dependency_chain/call_chain
are ONE hop out from the resolved entry points (definitions, direct
callers, direct subclasses, and import edges *among* the files already
selected) — not a full transitive expansion of the whole codebase.
Narrowing an ever-larger candidate set further is Phase 6's job
(ambiguity reduction, ranking, compression), not this one's.
"""

from collections import Counter
from uuid import uuid4

from code_intelligence.index import CodeIntelligenceIndex
from domain.code_intelligence import Symbol, SymbolKind
from domain.context_resolution import (
    CallEdge,
    ContextResolutionResult,
    DependencyEdge,
    FileReference,
    SymbolReference,
    TokenEstimate,
)


class ContextResolver:
    def __init__(self, index: CodeIntelligenceIndex) -> None:
        self._index = index

    def resolve(
        self,
        workspace_id: str,
        contract_id: str,
        repository_root: str,
        target_names: list[str],
    ) -> ContextResolutionResult:
        entry_point_symbols: list[Symbol] = []
        impacted_symbols: dict[str, Symbol] = {}
        candidate_files: set[str] = set()
        file_reasons: dict[str, str] = {}
        call_edges: list[CallEdge] = []

        resolved_count = 0
        for name in target_names:
            matches = self._index.symbol_index.find_by_name(name)
            if matches:
                resolved_count += 1
            for symbol in matches:
                entry_point_symbols.append(symbol)
                self._add_file(candidate_files, file_reasons, symbol.file_path, f"defines {name}")

                if symbol.kind in (SymbolKind.FUNCTION, SymbolKind.METHOD):
                    for caller_file in self._index.candidate_selector.callers_of(symbol.name):
                        self._add_file(candidate_files, file_reasons, caller_file, f"calls {name}")
                    for caller_id in self._index.call_graph.caller_symbols_of(symbol.id):
                        caller_symbol = self._index.symbol_index.get(caller_id)
                        if caller_symbol is not None:
                            impacted_symbols[caller_id] = caller_symbol
                        caller_file = caller_symbol.file_path if caller_symbol else symbol.file_path
                        call_edges.append(
                            CallEdge(
                                caller_symbol_id=caller_id,
                                callee_symbol_id=symbol.id,
                                file_path=caller_file,
                            )
                        )
                    for callee_id in self._index.call_graph.callee_symbols_of(symbol.id):
                        callee_symbol = self._index.symbol_index.get(callee_id)
                        if callee_symbol is not None:
                            impacted_symbols[callee_id] = callee_symbol
                        call_edges.append(
                            CallEdge(
                                caller_symbol_id=symbol.id,
                                callee_symbol_id=callee_id,
                                file_path=symbol.file_path,
                            )
                        )
                elif symbol.kind is SymbolKind.CLASS:
                    for subclass_file in self._index.candidate_selector.subclasses_of(symbol.name):
                        self._add_file(
                            candidate_files, file_reasons, subclass_file, f"extends {name}"
                        )
                    for subclass_id in self._index.inheritance_graph.all_subclasses_of(symbol.id):
                        subclass_symbol = self._index.symbol_index.get(subclass_id)
                        if subclass_symbol is not None:
                            impacted_symbols[subclass_id] = subclass_symbol

        dependency_edges = [
            DependencyEdge(from_file=file_path, to_file=imported)
            for file_path in candidate_files
            for imported in self._index.import_graph.imports_of(file_path)
            if imported in candidate_files
        ]

        raw_context_tokens = sum(self._index.token_counts.values())
        selected_context_tokens = sum(
            self._index.token_counts.get(file_path, 0) for file_path in candidate_files
        )
        compression_ratio = (
            round(selected_context_tokens / raw_context_tokens, 4) if raw_context_tokens else 0.0
        )

        total_targets = len(target_names)
        confidence = round(resolved_count / total_targets, 4) if total_targets else 0.0

        return ContextResolutionResult(
            id=uuid4(),
            workspace_id=workspace_id,
            contract_id=contract_id,
            repository_root=repository_root,
            language=self._dominant_language(candidate_files),
            candidate_files=[
                FileReference(
                    file_path=file_path,
                    reason=file_reasons.get(file_path, "related"),
                    language=self._language_of(file_path),
                    token_count=self._index.token_counts.get(file_path, 0),
                )
                for file_path in sorted(candidate_files)
            ],
            impacted_symbols=[
                self._to_symbol_reference(symbol)
                for symbol in sorted(impacted_symbols.values(), key=lambda s: s.id)
            ],
            dependency_chain=dependency_edges,
            call_chain=call_edges,
            entry_points=[self._to_symbol_reference(symbol) for symbol in entry_point_symbols],
            confidence=confidence,
            token_estimate=TokenEstimate(
                raw_context_tokens=raw_context_tokens,
                selected_context_tokens=selected_context_tokens,
                compression_ratio=compression_ratio,
            ),
            resolution_reason=self._build_reason(total_targets, resolved_count, candidate_files),
        )

    @staticmethod
    def _add_file(
        candidate_files: set[str], file_reasons: dict[str, str], file_path: str, reason: str
    ) -> None:
        candidate_files.add(file_path)
        file_reasons.setdefault(file_path, reason)

    def _to_symbol_reference(self, symbol: Symbol) -> SymbolReference:
        return SymbolReference(
            symbol_id=symbol.id,
            name=symbol.name,
            qualified_name=symbol.qualified_name,
            kind=symbol.kind,
            file_path=symbol.file_path,
            start_line=symbol.location.start_line,
            end_line=symbol.location.end_line,
        )

    def _language_of(self, file_path: str) -> str:
        analysis = self._index.file_analyses.get(file_path)
        return analysis.language if analysis is not None else "unknown"

    def _dominant_language(self, candidate_files: set[str]) -> str:
        languages = [self._language_of(file_path) for file_path in candidate_files]
        if not languages:
            return "unknown"
        return Counter(languages).most_common(1)[0][0]

    @staticmethod
    def _build_reason(total_targets: int, resolved_count: int, candidate_files: set[str]) -> str:
        if total_targets == 0:
            return "No target names provided; nothing to resolve."
        parts = [f"Resolved {resolved_count}/{total_targets} target name(s) to known symbols."]
        if candidate_files:
            parts.append(
                f"Selected {len(candidate_files)} candidate file(s) via direct definition, "
                "call, and inheritance relationships."
            )
        else:
            parts.append("No candidate files found.")
        return " ".join(parts)
