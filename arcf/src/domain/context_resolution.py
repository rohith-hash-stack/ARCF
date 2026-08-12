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
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from domain.code_intelligence import SymbolKind
from shared.clock import utc_now


class EvidenceTier(StrEnum):
    """Evidence-preserving context packaging — how confidently a file was
    matched, independent of `reason` (which explains *why* it matched).
    Drives ContextBudgetManager's compress-vs-keep-full decision: PRIMARY
    stays full whenever it fits the budget (today's behavior, unchanged);
    SUPPORTING is compressed to its relevant symbol range whenever one is
    known, regardless of whether it would've fit in full — a fan-out
    match shouldn't spend the same budget as the thing actually being
    asked about, however large the file it happens to live in is.

    PRIMARY: a direct definition match from a *confident* target name
    (an entity SLM-1 actually extracted, or a name the raw request
    itself referenced — contracts/evidence_contract.py's tier-1 "query-
    referenced" files), or the default for anything not explicitly
    downgraded below.

    SUPPORTING: reached via call-graph expansion, inheritance expansion,
    lexical-probe recovery (a prefix/substring symbol-name guess, not an
    exact match — see context/lexical_symbol_probe.py), or repository-
    scope evidence-contract matching (README/CI/test-config/dependency-
    manifest filler — context/evidence_fallback.py, context/
    evidence_validator.py). All of these are real, legitimate signal —
    they just don't warrant the same "assume it's all relevant" default
    a direct, confident match gets.

    EXPERIMENTAL: ARCF Phase 7 spike (Language Semantic Enrichment) —
    reached via a deterministic-but-not-yet-core relationship graph
    (decorator/annotation matching today; composition, DI-provider, etc.
    if the spike proves out) rather than any of ARCF's established
    graphs. Deliberately a THIRD value, not folded into SUPPORTING: the
    LSE pruning validator (context/evidence_validator.py's
    prune_experimental_candidates) must be able to target exactly and
    only these candidates, never touching SUPPORTING evidence from
    today's stable mechanisms. Compressed the same way SUPPORTING is by
    ContextBudgetManager — EXPERIMENTAL is a provenance distinction for
    pruning, not a different compression policy.
    """

    PRIMARY = "primary"
    SUPPORTING = "supporting"
    EXPERIMENTAL = "experimental"


class OriginStage(StrEnum):
    """Checklist item #10 (arcf/CHECKLIST.md) — which pipeline mechanism
    produced a given FileReference, so a candidate's provenance is a field
    read instead of manual `justification_chain`-string reading (the
    actual bottleneck in every prior ablation trace this session did by
    hand: item #3's `NewBaseDeps`-bridge trace, arcf_arm1_type_graph_
    falsified, arcf_arm4_path_locality_falsified).

    AST_DIRECT: the direct "defines {name}" entry-point match — the
    disambiguated Symbol itself IS the identity, no lookup involved.

    SCOPED_GRAPH_EXPANSION: reached via a symbol-ID-scoped traversal
    (`locality_filtered_transitive_callers`/`callees`, keyed by
    `symbol.id`) — genuinely identity-propagated.

    RAW_STRING_FALLBACK: reached via a raw-name lookup that re-searches
    `SymbolIndex.find_by_name` for every same-named symbol repo-wide,
    independent of which specific symbol was actually disambiguated
    (`locality_filtered_callers_of_name`, `candidate_selector.
    subclasses_of`) — confirmed by reading both directly, not assumed.
    This is NOT a behavior change from today (arcf_disambiguation_
    pruning_shipped already tested ID-scoping this specific lookup and
    found it barely changes candidate output, since CallGraph's own
    construction-time resolution over-attributes regardless of which
    lookup reads it later) — the fallback keeps working exactly as it
    does today, now honestly labeled instead of indistinguishable from
    an identity-propagated match.

    EVIDENCE_FALLBACK_MATCH: reached via `context/evidence_fallback.py`
    (README/CI/test-config/dependency-manifest filler, the lexical
    basename probe layer) or the anchor-classification Tier 4 filename
    match (`service.py`'s `attach_code_intelligence`) — genuinely
    symbol-less: a filename/path/glob match, not a symbol-name lookup at
    all, so it's a distinct category from RAW_STRING_FALLBACK rather than
    folded into it. Confirmed `expand_with_evidence` runs unconditionally
    on the default classic path (`service.py`'s own comment: "not just
    when classification.repository_scope"), so this is a real, reachable
    origin on an ordinary query, not a rare edge case."""

    AST_DIRECT = "ast_direct"
    SCOPED_GRAPH_EXPANSION = "scoped_graph_expansion"
    RAW_STRING_FALLBACK = "raw_string_fallback"
    EVIDENCE_FALLBACK_MATCH = "evidence_fallback_match"


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
    evidence_tier: EvidenceTier = EvidenceTier.PRIMARY
    """Evidence-preserving context packaging — see EvidenceTier's own
    docstring. Defaults to PRIMARY (today's full-file-if-it-fits
    behavior) so every construction site that doesn't explicitly reason
    about tiering keeps its current behavior rather than silently
    becoming over-compressed."""
    anchor_confidence: float | None = None
    """ARCF Pre-Expansion Anchor Classification experiment (2026-08-08,
    context/anchor_classifier.py), only ever set when
    `enable_confidence_propagation` is True: the originating anchor's
    tier confidence (1.0/0.5/0.15), decayed once per traversal hop
    (`anchor_classifier.decay_confidence`). `None` (the default) means
    "not computed for this file" — every construction site that doesn't
    opt into the experiment leaves this unset, and RelevanceRanker
    treats `None` as a neutral 1.0 multiplier, so existing behavior is
    byte-identical when the flag is off."""
    ambiguity_confidence: float | None = None
    """Real-Time Token & Latency Optimization, Feature A (2026-08-11,
    ContextResolver.resolve's target-name loop): 1 / log2(N + 1), where N
    is the raw ReferenceResolver.resolve_with_disambiguation match count
    for the target name this file's entry point was resolved from (N=1 ->
    1.0, no penalty). Only ever set on the direct "defines {name}" entry-
    point FileReference for that name — never on files reached via
    subsequent call/inheritance hop expansion, which already carry their
    own SUPPORTING-tier weight independent of this. Same opt-in-factor
    shape as `anchor_confidence` above (independent axis, multiplied in
    by RelevanceRanker, `None` is a neutral 1.0): a common name like Go's
    `New` resolving to 156 same-named candidates repo-wide currently
    gives every one of them the same undamped role_score as a single
    unambiguous match, which is what let confidence=1.000 candidate sets
    balloon to the whole repository (see arcf_callgraph_locality_fix
    memory) — this both distinguishes what remains genuinely likely-
    relevant from long-tail noise without invalidating what
    resolve_with_disambiguation itself already decided (both are correct
    Symbol matches; this only weights ranking, never drops a match)."""
    path_mask_confidence: float | None = None
    """Safe High-Efficiency Payload Optimization, Feature 1 (2026-08-11):
    0.15 when this file's entry point failed to match ANY of the
    query-wide path hints collected from every target name in the same
    request (ReferenceResolver.resolve_with_disambiguation's
    path_hint_matched=False), while at least one hint existed somewhere
    in the query. Same opt-in-multiplier shape as ambiguity_confidence
    above: `None` when no path hints exist in the query at all, or when
    this file's own candidate DID match one (already the intended,
    stronger signal there). This is the safety fallback for a
    legitimate cross-package query (e.g. "how does agent/cache talk to
    Catalog.Register?") where a hard path filter would otherwise have
    zero candidates to fall back on for the off-path entity — soft
    de-prioritizes instead of ever silently dropping a real match."""
    origin_stage: OriginStage | None = None
    """Checklist item #10, 2026-08-12: which mechanism produced this
    FileReference — see OriginStage's own docstring. `None` means "not
    yet tagged at this construction site" (same opt-in-field discipline
    as `anchor_confidence`/`ambiguity_confidence`/`path_mask_confidence`
    above) — every `_add_file` call site in `ContextResolver` sets this
    explicitly, so a real `None` on a genuine `resolve()` result would
    indicate a call site this item's own audit missed, not a legitimate
    "no stage" case."""
    parent_symbol_id: str | None = None
    """Checklist item #10: the SymbolID that triggered this file's
    inclusion — the disambiguated entry-point symbol for AST_DIRECT/
    RAW_STRING_FALLBACK, or the BFS's own real immediate-parent id for
    SCOPED_GRAPH_EXPANSION (not just the original entry symbol — the
    literal parent one hop back, already computed by
    `_locality_filtered_bfs`'s own `parents` dict)."""


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
