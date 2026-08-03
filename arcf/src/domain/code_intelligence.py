"""Code Intelligence IR (Phase 5) — the language-independent intermediate
representation every LanguageAnalyzer produces and every orchestration
component (SymbolIndex, ImportGraph, DependencyGraph, InheritanceGraph,
CallGraph, CandidateFileSelector) consumes.

This is the contract that makes the engine language-agnostic: nothing
in code_intelligence/ imports tree-sitter or knows Python/TypeScript/
Java/Go syntax except the per-language analyzer that produces these
objects. Adding a new language means writing one new LanguageAnalyzer
that emits these same types — no other file changes.

Symbol.kind covers CLASS/FUNCTION/METHOD/INTERFACE as one shared
vocabulary; "class index", "method index", "function index", and
"interface index" (named separately in the playbook) are simply
SymbolIndex queries filtered by kind, not four parallel data
structures to keep in sync.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SymbolKind(StrEnum):
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    INTERFACE = "interface"


class SourceLocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    file_path: str
    start_line: int
    end_line: int


class Symbol(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    qualified_name: str
    kind: SymbolKind
    file_path: str
    location: SourceLocation
    base_names: list[str] = Field(default_factory=list)
    """Raw base-class/interface expressions as written (e.g. "BasePage").
    Resolved to actual Symbols by InheritanceGraph, not here — a Symbol
    only records what the source text said, never a cross-file guess.
    """
    parent_id: str | None = None
    """id of the enclosing CLASS (for a METHOD) or enclosing FUNCTION
    (for a nested function). None for module-level symbols."""


class CallReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    caller_id: str | None
    """id of the enclosing FUNCTION/METHOD Symbol, or None for a
    module-level (or class-body-level) call site."""
    callee_name: str
    """Raw simple name of the call target as written (e.g. "authenticate"
    from either `authenticate(x)` or `self.authenticate(x)`) — resolving
    this to actual Symbol(s) is CallGraph's job via ReferenceResolver,
    not this analyzer's."""
    file_path: str
    location: SourceLocation


class ImportReference(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_file: str
    raw_module: str
    """The module/path text exactly as written in source."""
    imported_names: list[str] = Field(default_factory=list)
    resolved_file_path: str | None = None
    """Which workspace file this import targets, if resolvable. Filled
    in by the LanguageAnalyzer itself at analysis time (it has the
    language-specific resolution rules AND the workspace file set) —
    ImportGraph/DependencyGraph only ever read this field, never
    resolve a raw module string themselves."""
    location: SourceLocation


class FileAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    file_path: str
    language: str
    symbols: list[Symbol] = Field(default_factory=list)
    calls: list[CallReference] = Field(default_factory=list)
    imports: list[ImportReference] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
