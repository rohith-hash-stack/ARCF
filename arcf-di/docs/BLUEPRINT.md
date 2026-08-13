# ARCF-DI: Deterministic Repository Index — Implementation Blueprint

**Core rule:** *"The SLM may compress evidence, but it may never create evidence."* Scoped to indexing and retrieval only — not to downstream code generation.

**In scope:** `code_intelligence/`, `context/` (deterministic modules), the `domain` IR, `workspace/`.
**Out of scope:** `execution/`, `contracts/`, `telemetry/comparison_aggregator.py`.

Every recommendation below cites the actual ARCF module, class, or line it extends, replaces, or isolates.

---

## Phase 0 — Scope freeze

**In scope**

| Module | Role in ARCF-DI |
|---|---|
| `code_intelligence/*` | Language analyzers, graphs, resolver, engine — the deterministic evidence core. |
| `domain/code_intelligence.py` | Canonical IR — `Symbol`, `CallReference`, `ImportReference`, `DecoratorReference`, `SourceLocation`. Extended, not replaced. |
| `context/*` (deterministic modules) | `relevance_ranker`, `budget_manager`, `compressor`, `anchor_classifier`, `subsystem_localizer`, `lexical_symbol_probe`, `evidence_validator`, `evidence_fallback`, `query_decomposition`, `task_profile` — none import the LLM client today; stays that way. |
| `context/understanding.py` | SLM-2. Rebuilt in Phase 5 — the one `context/` module that does touch the LLM client. |
| `workspace/*` | Repo scanning, language/framework detection, git discovery — reused as-is for manifest discovery (Phase 2). |
| `infrastructure/llm_client.py` | Reused unmodified as transport for Phase 5's constrained calls only. |

**Out of scope — isolated by hard interface boundary**

| Module | Why |
|---|---|
| `execution/final_generation.py` | Unconstrained code-generation call. Its job is to *create*, which the core rule forbids for evidence. |
| `execution/prhl.py`, `context_goal_composer.py` | Advisory hints for the generation step, not indexing. |
| `contracts/*` | Request-intake (SLM-1 intent extraction) for the code-gen pipeline, not repository indexing. |
| `telemetry/comparison_aggregator.py` | CER/PCR comparison between "direct" vs "ARCF" pipelines — a different evaluation axis. |
| `runtime/, planning/, governance/, validation/, application/` | Empty stubs today. ARCF-DI's Phase 7 audit model is the real implementation of what "governance" was scaffolded for, but should live in a namespace ARCF-DI owns, not inherit the stub's name. |

**Boundary contract**: freeze the interface at the existing `ContextPackage` / `ContextResolutionResult` types. ARCF-DI owns everything that produces these; `contracts/` and `execution/` only read them. Enforced by a CI import-lint at Phase 10, step 10.

---

## Phase 1 — Deterministic evidence layer

**SourceLocation** — `{file_path, start_line, end_line, start_col?, end_col?}`. Determinism: full, pure function of the tree-sitter parse at a fixed commit. Regeneration: re-parse the file at that commit. Audit: `git show <commit>:<file_path> | sed -n '<start>,<end>p'` reproduces the exact evidence text.

**RepositorySymbol** (extends `Symbol`) — `{id, kind, qualified_name, simple_name, language, location, docstring, signature}`. `id = f"{file_path}::{qualified_name}#{start_line}"`, already the pattern `python_analyzer.py:420-421` uses. Self-describing — decomposes back to file+line with no lookup table.

**Import** — `{id, location, module_path, resolved_kind: REPOSITORY|EXTERNAL|STDLIB|UNRESOLVED, resolved_target}`. Regeneration requires re-running Phase 2's classifier against the manifest snapshot at that commit.

**ExternalLibraryReference** (new) — `{id, library_name, library_version, manifest_source, used_by: [SymbolId], api_surface_used: [str], confidence: CONFIRMED_LOCKED|CONFIRMED_RANGE|INFERRED_UNVERSIONED|AMBIGUOUS}`. `api_surface_used` is a literal member-access capture (e.g. `"axios.post"`) — never a description of library behavior.

**CallEdge** (extends `CallReference`) — `{id, caller_symbol_id, callee_ref: ResolvedRepo|ResolvedExternal|Unresolved(reason), call_site, resolution_confidence: EXACT_QUALIFIED|LOCALITY_DISAMBIGUATED|SIMPLE_NAME_FALLBACK|AMBIGUOUS_MULTI, candidates: [SymbolId]}`. `candidates` populated whenever `AMBIGUOUS_MULTI`, so the audit trail always answers "why this edge, not that one."

**Remaining types (compact):**

| Type | Key fields | Determinism note |
|---|---|---|
| `InheritanceEdge` | base_symbol_id, derived_symbol_id, resolution_confidence | Existing `_unresolved_bases` (`inheritance_graph.py:26-29`) promoted from internal to audit-visible. |
| `DecoratorAnnotation` | decorator_name, target_symbol_id, arguments, framework_hint | `framework_hint` only set against an explicit allowlist — never guessed. |
| `Route` | method, path_template, handler_symbol_id, extraction_method | Literal/simple-concat paths only; dynamic → `UNRESOLVED_DYNAMIC`. |
| `ConfigReference` | key, access_pattern, referencing_symbol_id | Literal keys only; computed keys → `UNRESOLVED_DYNAMIC_KEY`. |
| `SQLReference` | raw_query_text, reconstructed: bool, tables_referenced | `tables_referenced` parsed from literal text, never inferred from naming. |
| `Comment`/`Docstring` | text (verbatim), attached_symbol_id | Verbatim capture — the single safest evidence type; can't be wrong, it's a direct copy. |

String literals are not a universal standalone index (scale/noise); folded into the categories above.

---

## Phase 2 — External library boundary

Doesn't exist today: `SymbolIndex` only indexes repo-emitted symbols (`symbol_index.py:17-24`); external references simply fail to resolve.

**Algorithm**
1. Parse manifests per package root (reuse `workspace/repository_segmentation.py` for monorepo boundaries) into a `DeclaredDependency` set. Prefer a lockfile when present (`CONFIRMED_LOCKED`); fall back to the manifest range (`CONFIRMED_RANGE`).
2. Match each `Import.module_path` against declared dependencies with per-ecosystem rules: npm (direct/scoped/longest-prefix subpath match), Go (structurally easier — an import path prefixed by the module's own `go.mod` module directive is repository-internal, everything else external, no heuristics needed), Python (needs a small import-name↔distribution-name alias table, e.g. `pyyaml`→`yaml` — bounded, real maintenance).
3. Pre-seed a static per-language stdlib list so builtins don't fall into `UNRESOLVED` noise.
4. Classify: `CONFIRMED_EXTERNAL` / `REPOSITORY_INTERNAL` / `STDLIB` / `UNRESOLVED(reason)`.

**Edge cases:** workspace-internal packages imported by published name → must classify `REPOSITORY_INTERNAL`, not external. Vendored library source physically in-repo → treat as repository-internal for evidence purposes (confirm explicitly before enabling — a real judgment call). Barrel/re-export files → transitive resolution, depth-bounded. Unpinned ranges with no lockfile → `CONFIRMED_RANGE`, never resolved to a guessed version.

**Failure behavior:** unresolvable/ambiguous imports recorded as `UNRESOLVED(reason)`, never dropped, never guessed.

**Integration point:** sits between each language analyzer's import extraction and `ReferenceResolver`/`CallGraph` construction; `CallGraph` consults the classification to decide whether to attempt repo-symbol resolution or shortcut to an `ExternalLibraryReference`.

---

## Phase 3 — Symbol resolution, redesigned

Closes the gap `reference_resolver.py` documents about itself: "resolution is by exact qualified-name match first, falling back to simple-name match" (lines 4-9) — the exact mechanism behind the repo's own recorded `New()` collision (one call attributed to 460 files).

| Requirement | Concrete change |
|---|---|
| Mandatory disambiguation | `resolve_with_disambiguation` (`reference_resolver.py:166-241`) becomes the only path; `CallGraph.__init__`'s current bare `resolve()` call (`call_graph.py:28-37`) is removed as a silent default. |
| Deterministic tie-breaking | Extend the existing locality score (same-file=3, same-dir=2, import-hop=1, `reference_resolver.py:243-264`) with a lexicographic-by-id tie-break — the same pattern `CallGraph._layered_bfs` already uses (`call_graph.py:77-81`), applied consistently. |
| Ambiguity preservation | Retrieval-time pruning to one preferred candidate is fine as a *view*. The stored `CallEdge` must retain the full candidate list and score — pruning is retrieval-time convenience, not storage-time deletion. |
| No silent fallback | The simple-name fallback (`reference_resolver.py:157-164`) becomes an explicit, audit-visible tier — `SIMPLE_NAME_FALLBACK` — flagged lower-confidence than an exact match. |

**Can stay heuristic:** same-file/same-directory/import-graph locality scoring — explainable and deterministic without type inference, as long as it's always surfaced as heuristic.
**Needs true type resolution:** interface/abstract-method dispatch, overload resolution, generics — represent as `INTERFACE_DISPATCH_UNRESOLVED` with the full statically-known implementer set (reusing `InheritanceGraph`), never guessed to one.

**Incremental rollout:** 3a — mandatory disambiguation + tie-break (contained, flag-gated, same-process-ablated before defaulting on). 3b — thread ambiguity/candidates end-to-end through `ContextResolutionResult` and consumers. 3c (optional, highest cost) — real type resolution, one language at a time; Go is cheapest (module-path internal/external is already structural), TypeScript can integrate `tsc`'s own checker; dynamic languages (Python, Ruby, untyped JS) should probably stay heuristic indefinitely — a scoping decision, not deferred work.

---

## Phase 4 — Structured behavioral records

Every field below is fully derivable from Phases 1–3 with zero SLM involvement — the record is auditable by construction.

```
{
  identity: { symbol_id, qualified_name, kind, language }
  location: SourceLocation
  imports: [ImportId]                 // filtered to ones actually referenced in this symbol's body
  direct_calls: [CallEdgeId]
  indirect_calls: [{edge, hop, path}] // bounded per Phase 6; path never flattened away
  callers: [CallEdgeId]
  observable_effects: [{kind: NETWORK_CALL|FILE_IO|DB_QUERY|ENV_READ|PROCESS_SPAWN,
                         evidence: CallEdgeId|ConfigRefId|SQLRefId}]  // never inferred from naming
  config_references: [ConfigReferenceId]
  routes: [RouteId]
  sql: [SQLReferenceId]
  literals: [StringLiteralId]
  comments: [CommentId]
  complexity: { cyclomatic, line_count, direct_call_count }
  dependency_depth: { hops, truncated: bool }
  external_api_usage: [{ref: ExtRefId, hop}]
}
```

This record *is* the original Stage-2 goal — `server.Start()`'s "calls registerRoutes, imports net/http" is a literal rendering of `direct_calls` + `imports`, nothing more.

---

## Phase 5 — Evidence-constrained summarization

The highest-risk phase: this is where "never create evidence" is either enforced by construction or quietly becomes a prompt suggestion.

| Concern | Decision |
|---|---|
| Prompt design | Template-constrained: bullet-list serialization of the record's fields; model may use *only* listed items, must emit `INSUFFICIENT_EVIDENCE` for unsupported claims, forbidden from describing what an external call *does* beyond the literal invocation. |
| Deterministic generation | `temperature=0.0`, model version pinned per index version. Closes a real gap: `context/understanding.py:77-82` sets no temperature today (only SLM-1 does, `intent_extraction.py:98-105`). |
| Extractive vs. constrained | Hybrid — factual clauses are template-rendered (zero model involvement) for small records; SLM reserved for compressing large records only. |
| Citation format | Inline evidence-id per sentence, e.g. `[ev:call:a83f21]`, stripped for display but retained in `citations: [{span, evidence_id}]`. |
| Verification | Rule-based entailment check — given the constrained vocabulary, verifying every clause maps to a record field is cheaper and more auditable than a second model call. |
| Rejection rules | Reject on: missing citation; citation pointing to a field absent from the record; a denylisted interpretive verb (*validates, ensures, coordinates, secures, handles*) not literally derivable from any evidence item. |
| Confidence scoring | Computed mechanically from the record (resolution confidence of underlying edges, `depth_truncated`, `INFERRED_UNVERSIONED` usage) — never self-reported by the model. |

**Accepted:** "Calls `authenticate()` [ev:call:x1] and `logEvent()` [ev:call:x2]."
**Rejected:** "Coordinates authentication and logging to secure the request." — no evidence item states a coordination relationship or purpose.
**Accepted (library boundary):** "Invokes `axios.post(url, payload)` [ev:call:x5, external: axios]."
**Rejected (library boundary):** "Sends the request and retries on transient failure." — retry behavior is axios's internal behavior, not present in repo evidence.

---

## Phase 6 — Query-time retrieval

Mostly extension, not replacement — the deterministic core of `context/` already does most of this.

| Capability | Approach |
|---|---|
| Search index | Extend `lexical_symbol_probe.py`, `anchor_classifier.py`, `subsystem_localizer.py` to cover routes/config/SQL/external-refs, not indexed today. |
| Graph expansion | Reuse `multi_hop_orchestrator.py` + `CallGraph._layered_bfs`, gated to expand only through non-`AMBIGUOUS_MULTI` edges without surfacing the ambiguity implicitly. |
| Ranking | Reuse `relevance_ranker.py`. Do not add a second SLM-based ranking signal without re-running the same same-process ablation that falsified the earlier semantic-reranker experiment. |
| Token-budget packaging | Reuse `budget_manager.py` + `compressor.py`'s `SymbolRangeCompressor`, extended to carry citation ids into truncated excerpts. |
| Evidence attribution | Replace `ContextPackage.relevant_files[].reason: str` (`domain/context_package.py:26`) with `citations: [EvidenceId]`; prose becomes a rendered view generated *from* citations. |
| Ambiguity handling | Results touching `AMBIGUOUS_MULTI` surface every candidate with its tie-break score in the audit trail; pruning to top-1 is fine for the user-facing answer, not for the record. |
| Deterministic ordering | Same `sorted()`/lexicographic-tie-break discipline already used elsewhere, extended to the new evidence types. |

---

## Phase 7 — Auditability

| Element | Source |
|---|---|
| Evidence IDs | Extend the existing content-derived id pattern to every Phase 1 evidence type. |
| Graph traversal log | New: `{step, node_visited, edge_used, score_at_step}` per expansion — cheap, the BFS already visits in a defined order. |
| Ranking explanation | Change `relevance_ranker` to return a breakdown (lexical, locality, graph distance) per result, not just a scalar. |
| Summary provenance | Phase 5's citation list, directly. |
| Version identifiers | Stamp every record with resolver/analyzer/classifier version at build time. |
| Commit hash linkage | Stamp every evidence record with the commit SHA it was extracted from. |
| Reproducibility requirement | Given `(commit hash, index-build version)`, re-running the pipeline must produce byte-identical evidence and summaries. |

---

## Phase 8 — Persistent index

`CodeIntelligenceIndex` is explicitly non-serializable today (`index.py` docstring). This phase changes that:

- **Versioned schema** — every Phase 1 type gets an explicit `schema_version`.
- **Commit-aware indexing** — one snapshot per commit; reuse `engine.py:11-16`'s content-hash file-level caching as the incremental-rebuild basis.
- **Regeneration framing** — the store is a cache of a pure function, not a source of truth; the repo at commit C remains the source of truth.
- **Migration** — a `schema_version` bump triggers a full reindex, not a migration script, given the regeneration guarantee.
- **Integrity validation** — spot-check re-derivation of a sample of records against a live re-run on load; flag drift.
- **Incremental rebuild** — extend per-file caching to be resolution-aware: invalidate callers of a changed file's exports, not just the file's own symbols.
- **Deterministic serialization** — canonical field ordering, explicit UTF-8, fixed-point/rational score storage.

---

## Phase 9 — Validation framework

| Test class | What it proves |
|---|---|
| Reproducibility across runs | Full pipeline run twice against the same commit → byte-identical serialized index. |
| Graph stability | Regression fixtures for the documented recursive-symbol case (`call_graph.py:83-94`) plus high-fan-in-name stress cases (the real `New()` collision). |
| Summary stability | Same record in → same summary out at temperature 0; zero record diff → zero summary diff across two reindex cycles. |
| Retrieval stability | Same query, same commit → same ranked order, every run. |
| Ambiguity handling | Fixture repos with deliberate name collisions assert `AMBIGUOUS_MULTI` survives end-to-end, never silently collapsed. |
| Library-boundary correctness | Per-ecosystem fixtures (npm, go, pip, maven/gradle, cargo) including the monorepo-workspace-internal edge case. |
| Citation integrity | Every persisted summary's citations resolve to real evidence records; Phase 5's accept/reject pairs become golden regression fixtures. |

---

## Phase 10 — Migration from current ARCF

| Disposition | Modules |
|---|---|
| Keep unchanged | `code_intelligence/languages/*`, `domain/code_intelligence.py` (extended), `shared/*`, `infrastructure/llm_client.py`, `workspace/*` |
| Modify | `reference_resolver.py`, `call_graph.py`, `context/understanding.py` (biggest single-file change), `domain/context_package.py`, `context/packager.py`, `compressor.py`, `budget_manager.py`, `code_intelligence/index.py` |
| Replace | `reference_resolver.resolve()`'s silent name-fallback; `ContextPackage.relevant_files[].reason` as sole evidence record |
| Remove | None — every identified change is additive/extending. |
| Isolate | `execution/*`, `contracts/*`, `telemetry/comparison_aggregator.py` |

**Build order (repo stays buildable after every step):**

1. Phase 1 schema extensions — additive, existing consumers unaffected. *Low risk.*
2. Phase 2 library-boundary classifier — new, standalone, ships/tests independently. *Low risk.*
3. Phase 3a mandatory disambiguation — flag-gated, ablated against current behavior before defaulting on. *Medium risk.*
4. Phase 4 behavioral record assembly — pure aggregation of 1–3. *Low risk.*
5. Phase 8 minimal persistence — needed before Phase 5 citations are meaningful across runs and before Phase 9 can test stored output. *Medium risk.*
6. Phase 5 evidence-constrained summarization — flag-gated alongside the current free-text path; gate on the Phase 9 rejection-rule suite passing before defaulting on. *High risk.*
7. Phase 6 retrieval integration — thread citations through packager/compressor/budget_manager. *Medium risk.*
8. Phase 7 full audit-log surfacing — additive instrumentation only. *Low risk.*
9. Phase 9 validation suite — continuous from step 3 onward, not deferred.
10. Phase 10 boundary enforcement — CI import-lint blocking ARCF-DI modules from importing `execution/*` or `contracts/*`.

---

*Grounded against `code_intelligence/`, `context/`, `domain/`, `execution/`, `contracts/` as of the ARCF codebase reviewed 2026-08-13.*
