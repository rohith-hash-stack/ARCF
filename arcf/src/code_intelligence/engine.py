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

ARCF architecture hardening §9 (parallel indexing): per-file work (read,
hash, parse, count tokens) runs on a bounded thread pool via
ThreadPoolExecutor.map, which — unlike as_completed — returns results in
the SAME order the input iterable was submitted in, regardless of which
worker finished first. Every downstream merge (file_analyses,
content_hashes, token_counts, and _build_graphs's symbol/call/import
concatenation) inserts in that same, scanner-determined order, so the
resulting CodeIntelligenceIndex is byte-for-byte identical no matter how
many workers ran or how their completion interleaved. Each
LanguageAnalyzer.analyze_file call already constructs its own
tree-sitter Parser locally (verified across all six analyzers — none
share a module-level mutable Parser instance), so parsing is safe to
parallelize without analyzer changes.
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from code_intelligence.call_graph import CallGraph
from code_intelligence.candidate_selector import CandidateFileSelector
from code_intelligence.decorator_graph import DecoratorGraph
from code_intelligence.dependency_graph import DependencyGraph
from code_intelligence.import_graph import ImportGraph
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.inheritance_graph import InheritanceGraph
from code_intelligence.python_src_layout import resolve_with_src_layout
from code_intelligence.reference_resolver import ReferenceResolver
from code_intelligence.registry import LanguageRegistry
from code_intelligence.symbol_index import SymbolIndex
from code_intelligence.typescript_path_aliases import load_path_aliases, resolve_with_aliases
from domain.code_intelligence import (
    CallReference,
    DecoratorReference,
    FileAnalysis,
    ImportReference,
    Symbol,
)
from infrastructure.cost import CostEstimator
from shared.errors import WorkspacePathError
from workspace.permissions import PermissionManager
from workspace.scanner import ScannedFile

_TOKEN_ESTIMATE_MODEL = "gpt-4o-mini"
_DEFAULT_MAX_WORKERS = 8


@dataclass(frozen=True)
class _FileResult:
    relative_path: str
    skipped: bool
    analysis: FileAnalysis | None = None
    content_hash: str | None = None
    token_count: int | None = None


class CodeIntelligenceEngine:
    def __init__(
        self,
        registry: LanguageRegistry,
        token_estimator: CostEstimator,
        max_workers: int = _DEFAULT_MAX_WORKERS,
    ) -> None:
        self._registry = registry
        self._token_estimator = token_estimator
        self._max_workers = max_workers

    @property
    def registry(self) -> LanguageRegistry:
        """ARCF hardening §5: exposed so callers (e.g.
        code_intelligence/language_coverage.py, via service.py) can report
        analyzer coverage without duplicating the registry construction."""
        return self._registry

    def build_index(
        self,
        workspace_root: Path,
        files: list[ScannedFile],
        previous_index: CodeIntelligenceIndex | None = None,
    ) -> CodeIntelligenceIndex:
        permissions = PermissionManager(workspace_root)
        workspace_file_set = frozenset(file.relative_path for file in files)

        def process_file(file: ScannedFile) -> _FileResult:
            analyzer = self._registry.for_file(file.relative_path)
            if analyzer is None:
                return _FileResult(file.relative_path, skipped=True)

            try:
                content = permissions.safe_read_text(file.relative_path)
            except (OSError, WorkspacePathError):
                return _FileResult(file.relative_path, skipped=True)

            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            reusable = (
                previous_index is not None
                and previous_index.content_hashes.get(file.relative_path) == content_hash
            )
            if reusable and previous_index is not None:
                return _FileResult(
                    file.relative_path,
                    skipped=False,
                    analysis=previous_index.file_analyses[file.relative_path],
                    content_hash=content_hash,
                    token_count=previous_index.token_counts[file.relative_path],
                )

            analysis = analyzer.analyze_file(file.relative_path, content, workspace_file_set)
            token_count = self._token_estimator.count_tokens(content, _TOKEN_ESTIMATE_MODEL)
            return _FileResult(
                file.relative_path,
                skipped=False,
                analysis=analysis,
                content_hash=content_hash,
                token_count=token_count,
            )

        if files:
            with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                # .map preserves input order in its results regardless of
                # completion order — the property that makes this
                # deterministic (see module docstring).
                results = list(executor.map(process_file, files))
        else:
            results = []

        file_analyses: dict[str, FileAnalysis] = {}
        content_hashes: dict[str, str] = {}
        token_counts: dict[str, int] = {}
        skipped_files: list[str] = []

        for result in results:
            if result.skipped:
                skipped_files.append(result.relative_path)
                continue
            assert result.analysis is not None
            assert result.content_hash is not None
            assert result.token_count is not None
            file_analyses[result.relative_path] = result.analysis
            content_hashes[result.relative_path] = result.content_hash
            token_counts[result.relative_path] = result.token_count

        self._resolve_typescript_path_aliases(workspace_root, workspace_file_set, file_analyses)
        self._resolve_python_src_layout_imports(workspace_file_set, file_analyses)

        return self._build_graphs(file_analyses, content_hashes, token_counts, skipped_files)

    @staticmethod
    def _resolve_typescript_path_aliases(
        workspace_root: Path,
        workspace_files: frozenset[str],
        file_analyses: dict[str, FileAnalysis],
    ) -> None:
        """ARCF hardening §6: a deterministic post-processing pass —
        applied here rather than inside TypeScriptLanguageAnalyzer itself,
        see typescript_path_aliases.py's module docstring for why. No-op
        (and no tsconfig.json read at all) when no analyzed file has an
        unresolved import, so repositories without TypeScript pay nothing
        for this."""
        has_unresolved_import = any(
            imp.resolved_file_path is None
            for analysis in file_analyses.values()
            for imp in analysis.imports
        )
        if not has_unresolved_import:
            return

        aliases = load_path_aliases(workspace_root)
        if not aliases:
            return

        for relative_path, analysis in file_analyses.items():
            updated_imports: list[ImportReference] = []
            changed = False
            for imp in analysis.imports:
                if imp.resolved_file_path is not None:
                    updated_imports.append(imp)
                    continue
                resolved = resolve_with_aliases(imp.raw_module, aliases, workspace_files)
                if resolved is None:
                    updated_imports.append(imp)
                    continue
                updated_imports.append(imp.model_copy(update={"resolved_file_path": resolved}))
                changed = True
            if changed:
                file_analyses[relative_path] = analysis.model_copy(
                    update={"imports": updated_imports}
                )

    @staticmethod
    def _resolve_python_src_layout_imports(
        workspace_files: frozenset[str],
        file_analyses: dict[str, FileAnalysis],
    ) -> None:
        """ARCF hardening §6: same deterministic post-processing pattern
        as TypeScript's alias resolution above, for Python's `src/`
        layout — see python_src_layout.py's module docstring. No-op when
        no scanned file actually sits under `src/`."""
        if not any(path.startswith("src/") for path in workspace_files):
            return

        for relative_path, analysis in file_analyses.items():
            if analysis.language != "python":
                continue
            updated_imports: list[ImportReference] = []
            changed = False
            for imp in analysis.imports:
                if imp.resolved_file_path is not None:
                    updated_imports.append(imp)
                    continue
                resolved = resolve_with_src_layout(
                    imp.raw_module, imp.imported_names, workspace_files
                )
                if resolved is None:
                    updated_imports.append(imp)
                    continue
                updated_imports.append(imp.model_copy(update={"resolved_file_path": resolved}))
                changed = True
            if changed:
                file_analyses[relative_path] = analysis.model_copy(
                    update={"imports": updated_imports}
                )

    @staticmethod
    def _build_graphs(
        file_analyses: dict[str, FileAnalysis],
        content_hashes: dict[str, str],
        token_counts: dict[str, int],
        skipped_files: list[str],
    ) -> CodeIntelligenceIndex:
        all_symbols: list[Symbol] = []
        all_calls: list[CallReference] = []
        all_imports: list[ImportReference] = []
        all_decorators: list[DecoratorReference] = []
        for analysis in file_analyses.values():
            all_symbols.extend(analysis.symbols)
            all_calls.extend(analysis.calls)
            all_imports.extend(analysis.imports)
            all_decorators.extend(analysis.decorators)

        symbol_index = SymbolIndex(all_symbols)
        resolver = ReferenceResolver(symbol_index)
        import_graph = ImportGraph(all_imports)
        dependency_graph = DependencyGraph(import_graph)
        inheritance_graph = InheritanceGraph(all_symbols, resolver)
        call_graph = CallGraph(all_calls, resolver)
        candidate_selector = CandidateFileSelector(
            symbol_index, call_graph, inheritance_graph, dependency_graph
        )
        decorator_graph = DecoratorGraph(all_decorators)

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
            decorator_graph=decorator_graph,
            skipped_files=skipped_files,
        )
