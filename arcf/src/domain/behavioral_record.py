"""BehavioralRecord (ARCF-DI Phase 4) — the structured, fully evidence-
derived per-symbol record BLUEPRINT.md Phase 4 specifies. Every field is
a pure aggregation of Phases 1-3's already-deterministic evidence
(SymbolIndex, CallGraph, ImportReference.resolved_kind) — nothing here
is inferred, summarized, or produced by an SLM. Phase 5 renders a
human-readable summary FROM this record; this module has zero
dependency on Phase 5 or the LLM client, and code_intelligence/
behavioral_record.py (the builder) has zero dependency on either.
"""

from pydantic import BaseModel, ConfigDict, Field

from domain.code_intelligence import SourceLocation, SymbolKind


class TransitiveCallee(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol_id: str
    hop: int
    """1 = direct callee. Mirrors CallGraph.transitive_callee_symbols_of's
    own (hop, parent_symbol_id) shape; parent is deliberately not carried
    here — BehavioralRecord is a per-symbol record, not a path record,
    and BLUEPRINT.md Phase 6 is where a full path becomes relevant
    (query-time expansion), not indexing time."""


class AmbiguousCall(BaseModel):
    """ARCF-DI Phase 3's audit trail (CallGraph.resolved_calls, built with
    mandatory_disambiguation=True), surfaced directly on the record it
    concerns rather than left to be looked up separately."""

    model_config = ConfigDict(frozen=True)

    call_id: str
    callee_name: str
    candidates: list[str]


class RecordComplexity(BaseModel):
    """Purely structural, computed from the symbol's own SourceLocation
    span and its recorded direct-call count — deliberately NOT a
    cyclomatic-complexity score: no branch/loop-counting analyzer exists
    in this codebase yet, and claiming one would be exactly the kind of
    unevidenced number this project's core rule forbids."""

    model_config = ConfigDict(frozen=True)

    line_count: int
    direct_call_count: int


class DependencyDepth(BaseModel):
    model_config = ConfigDict(frozen=True)

    hops: int
    """Deepest hop actually reached, bounded by the builder's own
    max_indirect_hops — see `truncated`."""
    truncated: bool
    """True when `hops` equals the builder's traversal bound, meaning
    real depth beyond this point is unknown, not zero. False when
    traversal terminated on its own (a real leaf or cycle) before
    reaching the bound."""


class BehavioralRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol_id: str
    qualified_name: str
    kind: SymbolKind
    language: str
    location: SourceLocation

    file_import_ids: list[str] = Field(default_factory=list)
    """ImportReference ids for the symbol's own file — file-scoped, not
    body-scoped: no analyzer currently tracks which imports a specific
    function body actually references, so this is every import visible
    in the file. A documented, honest simplification, not a claim of
    per-symbol precision."""

    direct_callees: list[str] = Field(default_factory=list)
    direct_callers: list[str] = Field(default_factory=list)
    indirect_callees: list[TransitiveCallee] = Field(default_factory=list)
    dependency_depth: DependencyDepth

    ambiguous_calls: list[AmbiguousCall] = Field(default_factory=list)
    """Non-empty only when the CallGraph the record was built from used
    `mandatory_disambiguation=True`; empty when built from the default
    CallGraph — never silently misrepresented as "no ambiguity exists"
    when disambiguation was simply never run. See `disambiguation_aware`."""

    disambiguation_aware: bool
    """Whether `ambiguous_calls` reflects a real check (CallGraph built
    with `mandatory_disambiguation=True`) or is structurally empty
    because that check never ran. Read this before treating an empty
    `ambiguous_calls` as "no ambiguity" — with disambiguation_aware=False
    it means "not checked," not "checked and clean.\""""

    external_libraries_used: list[str] = Field(default_factory=list)
    """Declared-dependency names (DeclaredDependency.name, via
    ImportReference.resolved_library) the symbol's file imports as
    EXTERNAL — file-scoped, same caveat as file_import_ids. Empty
    whenever LibraryBoundaryClassifier was never run against these
    imports (resolved_kind still None), not necessarily "uses nothing
    external.\""""

    complexity: RecordComplexity
