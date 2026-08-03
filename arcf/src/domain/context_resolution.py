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


class SymbolReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol_id: str
    name: str
    qualified_name: str
    kind: SymbolKind
    file_path: str
    start_line: int
    end_line: int


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
