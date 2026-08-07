"""Context Resolution Contract — the boundary between Phase 5 (Code
Intelligence Engine, deterministic) and Phase 6 (Context Intelligence,
SLM-assisted).

Deliberately placed in domain/, not code_intelligence/: Phase 6 must be
able to import everything it needs (ContextResolutionResult and its
nested types) without ever importing from code_intelligence/ itself.
That is what makes "Phase 6 depends only on this contract" a structural
fact rather than a convention someone can accidentally violate — the
SLM-assisted layer never sees Tree-sitter, SymbolIndex, CallGraph,
DependencyGraph, ImportGraph, LanguageAnalyzer, or CandidateSelector
internals, because nothing in domain/ imports any of those either.

FileReference/SymbolReference/DependencyEdge/CallEdge are deliberately
NOT aliases of Symbol/CallReference/ImportReference from
domain/code_intelligence.py — they are thinner, purpose-built
projections that drop graph-construction internals (base_names,
parent_id) Phase 6 has no use for. That's what makes this a real
boundary instead of a relabeling exercise.

ContextResolutionResult is produced by code_intelligence/context_resolver.py
(the only file besides the engine itself allowed to touch SymbolIndex/
CallGraph/etc.) and is completely language-agnostic: a future
TypeScript/Java/Go analyzer produces the exact same shape, proven by
tests/code_intelligence/test_context_resolver_language_agnostic.py.

Referenced from Contract by id (context_resolution_id), not embedded —
LivingContract versions are persisted as full JSON snapshots (Phase 3),
and this result can contain dozens of file/symbol references; embedding
it the way the much smaller WorkspaceMetadata is embedded would bloat
every subsequent contract version.
"""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from domain.code_intelligence import SymbolKind
from shared.clock import utc_now


class FileReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    file_path: str
    reason: str
    """Deterministic, human-readable justification (e.g. "defines
    authenticate", "calls authenticate", "extends BasePage") — this is
    what makes the resolution auditable rather than a black box."""
    language: str
    token_count: int = Field(ge=0)
    """This file's token count, carried over from Phase 5's per-file
    counts (CodeIntelligenceIndex.token_counts) — Phase 6's Context
    Budget Manager needs this for budget-aware selection but must not
    reach into code_intelligence internals to get it, so it travels
    with the contract instead."""
    justification_chain: tuple[str, ...] = ()
    """ARCF hardening (adaptive deterministic traversal): the full hop-by-
    hop path from a resolved entry point to this file, e.g. ("defines
    authenticate", "called by Service.login", "called by
    Controller.handle_login") — empty for files added via a single-step
    relationship (`reason` alone already explains those)."""


class SymbolReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol_id: str
    name: str
    qualified_name: str
    kind: SymbolKind
    file_path: str
    start_line: int
    end_line: int
    parent_symbol_id: str | None = None
    """ARCF hardening §8: the enclosing class's symbol id, when this is a
    METHOD — carried across the Phase 5/6 boundary so a constructor added
    by ContextResolver._enrich_with_constructors is auditable rather than
    appearing to be an unexplained extra symbol."""


class DependencyEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    from_file: str
    to_file: str


class CallEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    caller_symbol_id: str | None
    callee_symbol_id: str
    file_path: str


class TokenEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_context_tokens: int = Field(ge=0)
    """Token count of every analyzed file in the workspace — "Context
    Available" in Phase 11's Context Efficiency Ratio."""
    selected_context_tokens: int = Field(ge=0)
    """Token count of just candidate_files — "Context Used". Computed
    here, deterministically, before Phase 6 does any ranking/compression
    and before any LLM is ever called."""
    compression_ratio: float = Field(ge=0.0)
    """selected_context_tokens / raw_context_tokens."""


class ContextResolutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    workspace_id: str
    contract_id: str
    repository_root: str
    language: str

    candidate_files: list[FileReference] = Field(default_factory=list)
    impacted_symbols: list[SymbolReference] = Field(default_factory=list)
    dependency_chain: list[DependencyEdge] = Field(default_factory=list)
    call_chain: list[CallEdge] = Field(default_factory=list)
    entry_points: list[SymbolReference] = Field(default_factory=list)

    confidence: float = Field(ge=0.0, le=1.0)
    token_estimate: TokenEstimate
    resolution_reason: str
    generated_at: datetime = Field(default_factory=utc_now)

    retrieval_depth_used: int = 0
    """ARCF hardening: the deepest call/import/inheritance hop actually
    reached during traversal (0 = only entry-point definitions, no
    expansion). Part of the deterministic retrieval-completeness metadata
    — never an LLM-generated confidence score."""

    ambiguous_targets: tuple[str, ...] = ()
    """ARCF hardening §3 (symbol disambiguation): target names that
    resolved to more than one candidate symbol and could not be narrowed
    to a single one via deterministic locality signals (same file, same
    directory, import-graph reachability from the already-resolved
    context). Surfaced explicitly rather than silently expanding to every
    candidate or silently picking one."""

    evidence_categories_satisfied: tuple[str, ...] = ()
    """ARCF hardening §2 (evidence sufficiency validation): required
    evidence categories (contracts/evidence_contract.py, per task type)
    already covered by candidate_files, whether from graph-driven
    selection or deterministic expansion."""
    evidence_categories_missing: tuple[str, ...] = ()
    """Required evidence categories that remained unsatisfied even after
    deterministic expansion (e.g. the repository genuinely has no CI
    workflow file) — surfaced honestly rather than fabricated."""

    repository_segment: str = ""
    """ARCF hardening §4 (repository boundary awareness): the monorepo
    segment (nearest enclosing manifest/workspace-config directory) that
    dominates candidate_files — "" means the whole-repository segment
    (single-project repo, or no dominant segment yet)."""

    files_scanned: int = 0
    """ARCF hardening §5/§11: total files RepositoryScanner found in the
    workspace, regardless of language support."""
    files_analyzed: int = 0
    """Files an analyzer actually parsed (files_scanned minus
    skipped_files, see code_intelligence.index.CodeIntelligenceIndex)."""
    languages_detected: tuple[str, ...] = ()
    """Every language workspace/language_detection.py found at least one
    file for, ranked by file count."""
    languages_unsupported: tuple[str, ...] = ()
    """Subset of languages_detected with no registered LanguageAnalyzer —
    files in these languages were scanned but never indexed."""
    analyzer_coverage: float = 1.0
    """files_analyzed / files_scanned (1.0 when there's nothing to scan or
    everything scanned was analyzed)."""
    unresolved_symbols: tuple[str, ...] = ()
    """Target names that resolved to zero symbols, plus (via
    ambiguous_targets) names that resolved to more than one candidate the
    disambiguation locality signals couldn't narrow — the parts of this
    resolution that are honestly incomplete rather than silently assumed
    complete."""
    unresolved_imports: tuple[str, ...] = ()
    """Import statements a LanguageAnalyzer recorded but could not resolve
    to a workspace file (ImportReference.resolved_file_path is None) —
    stdlib/third-party imports, or a genuinely unresolvable one, surfaced
    rather than silently dropped from the import graph."""
    parse_error_files: tuple[str, ...] = ()
    """Files an analyzer attempted but reported parse errors for
    (FileAnalysis.parse_errors) — malformed source or an unsupported
    syntax construct, distinct from files never attempted at all."""
    generated_files: tuple[str, ...] = ()
    """ARCF hardening §13: files matching common generated-code
    conventions (protobuf/gRPC stubs, *.g.cs, /generated/ directories,
    `@Generated`-style markers) — a deterministic, best-effort heuristic,
    not exhaustive. Included in candidate_files like any other file, just
    flagged so low-value generated content can be deprioritized."""
    dynamic_dispatch_hints: tuple[str, ...] = ()
    """Files containing a deterministic keyword hint of reflection-heavy
    or runtime-dependency-injected code (e.g. `getattr(`, `@Inject`,
    `importlib.import_module(`) — static analysis cannot see through
    these, so they're surfaced as a known limitation rather than silently
    assumed fully resolved."""
