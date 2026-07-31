"""CodeIntelligenceEngine — orchestrates Phase 5's deterministic
repository-understanding pipeline into one CodeIntelligenceIndex.

This is the one place that ties LanguageRegistry (dispatch) to the
graphs (SymbolIndex, ImportGraph, DependencyGraph, InheritanceGraph,
CallGraph, CandidateFileSelector) — and it is itself entirely
language-agnostic: it only ever calls `registry.for_file(...)` and
`analyzer.analyze_file(...)`, never inspects a file extension or
imports a per-language module directly. Adding a new language changes
only which analyzers are registered, not this file.

Incremental indexing (Phase 5 deliverable): pass the previous
CodeIntelligenceIndex back in and files whose content hash is
unchanged reuse their cached FileAnalysis (and token count) rather than
being re-parsed/re-counted. Rebuilding the graphs themselves is always
cheap in-memory work with no I/O, so they're always rebuilt fresh from
whichever FileAnalysis objects (cached or freshly parsed) end up in play.

token_estimator counts tokens per file via tiktoken (reusing Phase 2's
CostEstimator rather than a second tokenizer) so ContextResolver can
compute TokenEstimate without re-reading file contents later. The
model name passed is an encoding choice only — this is a planning
signal, not a billing calculation tied to any specific LLM call.
"""

import hashlib
from pathlib import Path

from code_intelligence.call_graph import CallGraph
from code_intelligence.candidate_selector import CandidateFileSelector
from code_intelligence.dependency_graph import DependencyGraph
from code_intelligence.import_graph import ImportGraph
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.inheritance_graph import InheritanceGraph
from code_intelligence.reference_resolver import ReferenceResolver
from code_intelligence.registry import LanguageRegistry
from code_intelligence.symbol_index import SymbolIndex
from domain.code_intelligence import CallReference, FileAnalysis, ImportReference, Symbol
from infrastructure.cost import CostEstimator
from shared.errors import WorkspacePathError
from workspace.permissions import PermissionManager
from workspace.scanner import ScannedFile

_TOKEN_ESTIMATE_MODEL = "gpt-4o-mini"


class CodeIntelligenceEngine:
    def __init__(self, registry: LanguageRegistry, token_estimator: CostEstimator) -> None:
        self._registry = registry
        self._token_estimator = token_estimator

    def build_index(
        self,
        workspace_root: Path,
        files: list[ScannedFile],
        previous_index: CodeIntelligenceIndex | None = None,
    ) -> CodeIntelligenceIndex:
        permissions = PermissionManager(workspace_root)
        workspace_file_set = frozenset(file.relative_path for file in files)

        file_analyses: dict[str, FileAnalysis] = {}
        content_hashes: dict[str, str] = {}
        token_counts: dict[str, int] = {}

        for file in files:
            analyzer = self._registry.for_file(file.relative_path)
            if analyzer is None:
                continue

            try:
                content = permissions.safe_read_text(file.relative_path)
            except (OSError, WorkspacePathError):
                continue

            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            content_hashes[file.relative_path] = content_hash

            reusable = (
                previous_index is not None
                and previous_index.content_hashes.get(file.relative_path) == content_hash
            )
            if reusable and previous_index is not None:
                file_analyses[file.relative_path] = previous_index.file_analyses[
                    file.relative_path
                ]
                token_counts[file.relative_path] = previous_index.token_counts[
                    file.relative_path
                ]
                continue

            file_analyses[file.relative_path] = analyzer.analyze_file(
                file.relative_path, content, workspace_file_set
            )
            token_counts[file.relative_path] = self._token_estimator.count_tokens(
                content, _TOKEN_ESTIMATE_MODEL
            )

        return self._build_graphs(file_analyses, content_hashes, token_counts)

    @staticmethod
    def _build_graphs(
        file_analyses: dict[str, FileAnalysis],
        content_hashes: dict[str, str],
        token_counts: dict[str, int],
    ) -> CodeIntelligenceIndex:
        all_symbols: list[Symbol] = []
        all_calls: list[CallReference] = []
        all_imports: list[ImportReference] = []
        for analysis in file_analyses.values():
            all_symbols.extend(analysis.symbols)
            all_calls.extend(analysis.calls)
            all_imports.extend(analysis.imports)

        symbol_index = SymbolIndex(all_symbols)
        resolver = ReferenceResolver(symbol_index)
        import_graph = ImportGraph(all_imports)
        dependency_graph = DependencyGraph(import_graph)
        inheritance_graph = InheritanceGraph(all_symbols, resolver)
        call_graph = CallGraph(all_calls, resolver)
        candidate_selector = CandidateFileSelector(
            symbol_index, call_graph, inheritance_graph, dependency_graph
        )

        return CodeIntelligenceIndex(
            file_analyses=file_analyses,
            content_hashes=content_hashes,
            token_counts=token_counts,
            symbol_index=symbol_index,
            import_graph=import_graph,
            dependency_graph=dependency_graph,
            inheritance_graph=inheritance_graph,
            call_graph=call_graph,
            candidate_selector=candidate_selector,
        )
