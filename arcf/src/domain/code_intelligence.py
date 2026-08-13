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

ARCF-DI Phase 1 (arcf-di/docs/BLUEPRINT.md) extends this IR additively:
content-derived `id` on CallReference/ImportReference/DecoratorReference
(computed, never independently settable — an evidence id can't drift
from the evidence it describes); resolution-tier fields on CallReference
and ImportReference that later phases populate (Phase 3 resolver
redesign, Phase 2 library-boundary classifier respectively) but that
default to None/empty today, so this phase changes no runtime behavior;
and four new evidence types (ExternalLibraryReference, Route,
ConfigReference, SQLReference) wired into FileAnalysis as empty-default
lists, the same rollout shape `decorators` already established. No
analyzer populates any of the new fields yet — that's later phases.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field


class SymbolKind(StrEnum):
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    INTERFACE = "interface"


class ImportResolutionKind(StrEnum):
    """ARCF-DI Phase 1 (evidence layer, schema only): where an Import's
    `raw_module` was classified to. Nothing populates this yet — the
    classifier that turns a raw module string into one of these is
    ARCF-DI Phase 2 (external-library boundary), not this phase.
    `ImportReference.resolved_kind` defaults to None until then, so no
    existing producer or consumer is affected by adding this enum."""

    REPOSITORY = "repository"
    EXTERNAL = "external"
    STDLIB = "stdlib"
    UNRESOLVED = "unresolved"


class CallResolutionConfidence(StrEnum):
    """ARCF-DI Phase 1 (schema only): how a CallReference's `callee_name`
    was, or could be, resolved to Symbol id(s). Nothing sets this yet —
    ReferenceResolver's redesign (mandatory disambiguation, deterministic
    tie-breaking, no silent fallback) is ARCF-DI Phase 3. Recording the
    tier names now, ahead of the resolver change, is what lets Phase 3
    ship as "populate this existing field" instead of "invent a new one
    while also changing behavior" — deliberately smaller and easier to
    review in isolation."""

    EXACT_QUALIFIED = "exact_qualified"
    LOCALITY_DISAMBIGUATED = "locality_disambiguated"
    SIMPLE_NAME_FALLBACK = "simple_name_fallback"
    AMBIGUOUS_MULTI = "ambiguous_multi"


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
    resolution_confidence: CallResolutionConfidence | None = None
    """ARCF-DI Phase 1 (schema only): populated by Phase 3's redesigned
    ReferenceResolver, not by any analyzer or by today's CallGraph — a
    call site is a raw fact CallReference already never resolves itself
    (see callee_name's own docstring), so this stays None until the
    resolver that decides confidence exists. Defaulted, so every
    existing constructor call site is unaffected."""
    candidates: list[str] = Field(default_factory=list)
    """ARCF-DI Phase 1 (schema only): Symbol ids ReferenceResolver found
    for `callee_name` when resolution_confidence is AMBIGUOUS_MULTI.
    Empty until Phase 3 — the point of this field existing ahead of that
    work is that CallGraph today (call_graph.py) adds a real graph edge
    to *every* resolved candidate with no record that the name was ever
    ambiguous in the first place; the field exists here so Phase 3 has
    somewhere to preserve that fact instead of discarding it."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        """Content-derived, mirrors Symbol's own `f"{file}::{name}#{line}"`
        scheme (see e.g. python_analyzer.py's `_symbol_id`) but namespaced
        with a `call:` prefix so a call-site id can never collide with a
        Symbol id sharing the same file/name/line. A pure function of the
        other fields, not independently settable — an evidence id can't
        drift from the evidence it describes."""
        return (
            f"call:{self.file_path}::{self.callee_name}"
            f"#{self.location.start_line}-{self.location.end_line}"
        )


class DecoratorReference(BaseModel):
    """ARCF Phase 7 spike (Language Semantic Enrichment): a decorator or
    annotation applied to a Symbol — e.g. `@app.get("/users")` above a
    FUNCTION, `@dataclass` above a CLASS. Deliberately mirrors
    CallReference's own raw-text-now/resolve-later split: `decorator_name`
    is the decorator's callable expression exactly as written (an
    attribute path or bare identifier), never resolved to what it
    actually does — that's DecoratorGraph's job, working purely off this
    IR, same boundary CallGraph/InheritanceGraph already keep. Decorator
    *arguments* (e.g. the route path "/users") are deliberately NOT
    captured here — that would be framework-semantic interpretation
    ("this string is a route path"), out of scope for a language-level
    relationship; a decorator is a real syntactic fact regardless of what
    framework (if any) gives it meaning."""

    model_config = ConfigDict(frozen=True)

    symbol_id: str
    """id of the decorated Symbol (a FUNCTION, METHOD, or CLASS)."""
    decorator_name: str
    """Raw text of the decorator's callable expression as written (e.g.
    "app.get" from `@app.get("/users")`, "dataclass" from `@dataclass`,
    "app.route" from `@app.route(...)`) — never a resolved cross-file
    reference, mirroring CallReference.callee_name and Symbol.base_names."""
    file_path: str
    location: SourceLocation

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        """ARCF-DI Phase 1: content-derived, same scheme as CallReference.id."""
        return (
            f"decorator:{self.file_path}::{self.decorator_name}"
            f"@{self.symbol_id}#{self.location.start_line}"
        )


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
    resolved_kind: ImportResolutionKind | None = None
    """ARCF-DI Phase 1 (schema only): repository / external / stdlib /
    unresolved classification. None until Phase 2's manifest-backed
    classifier exists — `resolved_file_path` above already tells you
    *whether* this resolves inside the repo; this field is for the
    external/stdlib/unresolved split that field can't express, and
    intentionally doesn't guess at one from `raw_module` alone."""
    resolved_library: str | None = None
    """ARCF-DI Phase 1 (schema only): the declared dependency name this
    import matched, when resolved_kind is EXTERNAL (e.g. "axios",
    "requests") — set by Phase 2's classifier, from a project manifest,
    never inferred from the import string itself."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        """ARCF-DI Phase 1: content-derived, same scheme as CallReference.id."""
        return f"import:{self.source_file}::{self.raw_module}#{self.location.start_line}"


class DeclaredDependency(BaseModel):
    """ARCF-DI Phase 2: one dependency as declared in a manifest file —
    the input DependencyManifestParser produces and LibraryBoundaryClassifier
    consumes. `name` is lowercased and, for scoped npm packages, includes
    the scope (e.g. "@playwright/test") — never the ecosystem-specific
    quoting/casing a manifest happened to use, so lookups are exact-match
    without the classifier re-normalizing on every call.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    ecosystem: str
    """"npm" | "pip" | "go" for this phase — see BLUEPRINT.md Phase 2.
    An ecosystem ARCF-DI can't yet parse a manifest for is never
    represented here at all, never guessed."""
    version_spec: str | None = None
    """Verbatim as declared (a range, not a resolved version) — this
    phase reads manifests, not lockfiles, so there is no CONFIRMED_LOCKED
    tier yet, only the manifest's own declared range."""
    manifest_location: SourceLocation


class ExternalLibraryReference(BaseModel):
    """ARCF-DI Phase 1 (schema only): the library, the literal API surface
    used, and which repository symbols use it — deliberately nothing
    about what that API *does*. `api_surface_used` is a textual capture
    of the call expression as written (e.g. "axios.post"), never a
    description of library behavior; describing axios.post's own
    behavior is only permitted if axios's source exists in this
    repository, which this record has no way to know and doesn't try to.
    No analyzer or classifier populates this yet — that's ARCF-DI
    Phase 2."""

    model_config = ConfigDict(frozen=True)

    library_name: str
    library_version: str | None = None
    """From a lockfile when present, else the manifest's declared range.
    Never a guessed single version for an unpinned range."""
    manifest_location: SourceLocation
    """Points into the manifest file (package.json, go.mod, ...) that
    declared this dependency — not into any file that imports it."""
    used_by: list[str] = Field(default_factory=list)
    """Symbol ids of repository functions/methods that call this library."""
    api_surface_used: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        return f"extlib:{self.library_name}@{self.library_version or 'unpinned'}"


class Route(BaseModel):
    """ARCF-DI Phase 1 (schema only): an HTTP route, extracted only when
    the path is a literal or simple literal concatenation. A
    dynamically-built path (e.g. from a variable) is not represented
    here at all rather than guessed — callers should treat "no Route
    record" and "route exists but path is dynamic" as the same
    "not evidenced" case until a future phase decides that distinction
    is worth a field of its own. No analyzer populates this yet."""

    model_config = ConfigDict(frozen=True)

    method: str | None = None
    path_template: str
    handler_symbol_id: str
    location: SourceLocation

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        method = self.method or "*"
        return (
            f"route:{self.location.file_path}::{method} "
            f"{self.path_template}#{self.location.start_line}"
        )


class ConfigReference(BaseModel):
    """ARCF-DI Phase 1 (schema only): a literal configuration/environment
    key read at a specific call site. A computed/interpolated key is not
    represented here rather than guessed at. No analyzer populates this
    yet."""

    model_config = ConfigDict(frozen=True)

    key: str
    referencing_symbol_id: str
    location: SourceLocation

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        return f"config:{self.location.file_path}::{self.key}#{self.location.start_line}"


class SQLReference(BaseModel):
    """ARCF-DI Phase 1 (schema only): a SQL query's literal text captured
    at its call site, plus tables parsed out of that literal text — never
    inferred from the referencing function's name. `reconstructed=True`
    flags a query built from static string concatenation rather than one
    literal string, so a summarizer downstream can weight it accordingly.
    No analyzer populates this yet."""

    model_config = ConfigDict(frozen=True)

    raw_query_text: str
    reconstructed: bool = False
    tables_referenced: list[str] = Field(default_factory=list)
    referencing_symbol_id: str
    location: SourceLocation

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        return f"sql:{self.location.file_path}#{self.location.start_line}-{self.location.end_line}"


class FileAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True)

    file_path: str
    language: str
    symbols: list[Symbol] = Field(default_factory=list)
    calls: list[CallReference] = Field(default_factory=list)
    imports: list[ImportReference] = Field(default_factory=list)
    decorators: list[DecoratorReference] = Field(default_factory=list)
    """ARCF Phase 7 spike: empty for every analyzer except
    PythonLanguageAnalyzer for now — additive, so existing analyzers and
    every consumer of FileAnalysis that doesn't know about decorators yet
    are unaffected (default empty list, same pattern calls/imports
    already established)."""
    external_library_references: list[ExternalLibraryReference] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    config_references: list[ConfigReference] = Field(default_factory=list)
    sql_references: list[SQLReference] = Field(default_factory=list)
    """ARCF-DI Phase 1: same rollout shape as `decorators` above — empty
    for every analyzer today, additive, no existing consumer of
    FileAnalysis is affected. Populated starting Phase 2
    (external_library_references) and Phase 6 (routes/config/sql, via
    the language analyzers' existing literal/decorator/call extraction),
    not this phase."""
    parse_errors: list[str] = Field(default_factory=list)
