# ARCF End-to-End Architecture Audit — Discovery Report

**Status:** Discovery/gap-detection only (Steps 1–6 of the requested 10-step process). No code has
been changed. This is the deliverable to review before any restructuring begins.
**Scope:** `arcf/src/` (all layers) + `arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md` and
`ARCF_V2.3_BASELINE_FREEZE.md` (the project's own existing architecture source of truth).
**Method:** 5 parallel deep-read agents, one traced end-to-end orchestration trace done directly,
every claim below is cited to file:line. No historical benchmark results, prior conversations, or
old experiments were used as evidence — only current repository code and current repository docs,
per the audit brief's own "source of truth" instructions.
**Date:** 2026-08-16.

---

## 0. Executive summary

**ARCF today is two structurally disconnected systems, not one pipeline**, plus several
layers from the requested conceptual model that don't exist yet — some by deliberate,
documented staging, one (Verification) that was never planned at all.

1. **Retrieval (Contract → Code-Intelligence → Context-Package) is real, mostly well-built, and
   internally consistent.** Symbol/import/call/inheritance graphs, disambiguation, locality
   filtering, evidence-category coverage checking, task-aware ranking, budget-bounded compression —
   all genuinely wired, genuinely tested, matches the project's own "deterministic hardening"
   freeze addendum almost field-for-field.
2. **Generation (`/api/v1/execute`) is a complete bypass of that entire pipeline.** It takes a raw
   prompt string and calls the LLM directly. Its request schema has no field that could carry a
   `ContextPackage`, `contract_id`, or resolution id — this is not a missing wire, it's a missing
   plug. Real code exists that *would* correctly consume a `ContextPackage` and ground a prompt in
   it (`execution/context_goal_composer.py` + `execution/final_generation.py`) — but nothing in the
   deployed API imports either module. The project's own freeze doc lists this code as "frozen"
   (i.e. delivered, working, baseline-locked) — that claim is false as measured against the actual
   route registration in `interfaces/api/app.py`.
3. **Verification (Layer 9) does not exist in any form**, and — this is the one finding that isn't
   "staged for later" — **it isn't on the project's own 11-phase roadmap either.** `ARCF_v2.3_
   ARCHITECTURE_REVIEW.md` names Phases 7–11 explicitly (Planning, Composer/PRHL, Execution Ledger,
   Runtime/Orchestration, Token Intelligence) and none of them is "compare the generated answer
   against the evidence used to generate it." This is a gap between the audit brief's acceptance
   criteria and ARCF's own plan, not just an implementation lag.
4. **Recovery/Retry (Layer 10) also does not exist as a semantic capability**, but this one *is*
   staged: it lives structurally where Phase 10 ("Orchestration/runtime") would go, and the
   project's own freeze doc explicitly defers Phase 10 until a 30–40 task benchmark suite completes
   — and explicitly prohibits "autonomous agentic loops" in the meantime. A failure-driven retry
   loop is arguably adjacent to that prohibition; this is a real tension for whoever scopes Layer 10
   later, not a simple omission.
5. **Query Understanding (Layer 2) computes real, well-corroborated intent data that almost none of
   which reaches retrieval.** `UserIntent.entities` — the actual SLM-extracted symbol names — is
   never read by `code_intelligence/service.py`. Retrieval instead requires the API caller to
   separately, manually supply `target_names`. `domain`, `task`, `constraints`, `assumptions`, and
   `confidence` are computed, persisted, and never read again; task type is independently
   re-derived from raw text three separate times in three different files instead of reusing the
   one already scored at contract-creation time.
6. **The persistence/telemetry layer that would make any of this observable in production is built
   but almost entirely unwired.** `ExecutionLedgerEntry`/`TelemetryCollector`/`production_gate.
   evaluate_release()` all exist, are tested, and have zero real production callers outside
   `contract_store`/`context_resolution_store` (which *are* genuinely live). The freeze doc lists
   the Execution Ledger as "frozen/delivered" — same discrepancy pattern as Gap 2.

None of this is presented as "the codebase is bad." Most of the deepest, most careful engineering
in this repo (locality-filtered graph expansion, disambiguation, evidence-tier provenance,
task-aware ranking, incremental indexing) lives entirely within the retrieval/ranking/packaging
layers that turn out to be disconnected from generation. The gap is structural and specific, not
diffuse.

---

## 1. Real architecture as built vs. the conceptual 11-layer model

### 1.1 What the code actually does end-to-end, traced directly

```
POST /api/v1/contracts                    → ExecutionContractManager.create_contract
                                              (SLM-1 intent extraction + classifier
                                              corroboration + confidence + clarification)
                                              → Contract{intent: UserIntent} persisted

POST /contracts/{id}/code-intelligence     → CodeIntelligenceContractService
                                              .attach_code_intelligence(contract_id,
                                              target_names, workspace_root)
                                              — target_names is CLIENT-SUPPLIED, NOT
                                              read from contract.intent.entities
                                              → ContextResolutionResult persisted

POST /contracts/{id}/context-package       → ContextPackager.package(result, raw_request,
                                              max_tokens, ranking_profile)
                                              → ContextPackage returned directly as the
                                              HTTP response body. Nothing downstream of
                                              this call happens server-side.

POST /api/v1/execute                       → llm_client.complete(payload.prompt, ...)
                                              — payload.prompt is a raw string with NO
                                              field for contract_id/context_package.
                                              Completely independent of the three routes
                                              above; shares no code path with them.
```

There is no fifth call, and no server-side chaining between the third and fourth. A client that
faithfully walks contract → code-intelligence → context-package gets a JSON blob of selected files
back and **must reimplement prompt assembly and generation themselves** — the code that would do
this correctly for them (`execution/context_goal_composer.py` + `execution/final_generation.py`)
exists but is only reachable from `tests/` and two standalone CLI research scripts
(`scripts/repo_query_answer.py`, `scripts/validate_llm_grounding.py`), never from the API.

### 1.2 Mapping onto the requested 11-layer model

| Conceptual layer | Real ARCF equivalent | Status |
|---|---|---|
| 1. Repository/Index-Time Intelligence | `code_intelligence/engine.py` + graphs + DRP subsystem | **Built, mostly wired** — DRP unreachable from API (§3) |
| 2. Query Understanding | `contracts/*.py` (SLM-1 + classifiers + confidence) | **Built, output mostly discarded** (§3) |
| 3. Candidate Generation | `code_intelligence/reference_resolver.py` + `context_resolver.py` | **Built, wired, real** |
| 4. Retrieval/Structural Expansion | `code_intelligence/locality.py` + `context_resolver.py`'s `_expand_calls`/`_expand_subclasses` | **Built, wired** — one unbounded-expansion gap (§3) |
| 5. Evidence Extraction/Validation | `context/evidence_validator.py`, `context/evidence_fallback.py` | **Half built** — coverage-checking only, half the module is dead code |
| 6. Ranking | `context/relevance_ranker.py` | **Built, wired, real** — confidence-conflation gaps (§3) |
| 7. Context Construction | `context/packager.py`, `context/budget_manager.py`, `context/compressor.py` | **Built, wired, real — the most solid layer in the system** |
| 8. Generation | `execution/final_generation.py`, `execution/context_goal_composer.py` | **Built correctly, wired to nothing** |
| 9. Verification | — | **Does not exist. Not on the roadmap.** |
| 10. Recovery/Retry | — | **Does not exist. Staged as Phase 10, explicitly deferred.** |
| 11. Persistence/Ledger/Telemetry | `infrastructure/execution_ledger_db.py`, `telemetry.py`, `production_gate.py` | **Built, mostly unwired** — contract_store/context_resolution_store are the live exceptions |

---

## 2. Layer-by-layer contract inventory

*(Abbreviated here — full field-by-field tables with file:line citations are in the five agent
transcripts this report was synthesized from; this section gives the load-bearing facts.)*

**Shared IR** (`domain/code_intelligence.py`): `Symbol`, `CallReference`, `ImportReference`,
`DecoratorReference`, `FileAnalysis` — implemented identically by 8 language analyzers via a
`LanguageAnalyzer` Protocol (`code_intelligence/language_analyzer.py`). Extension point genuinely
open: adding a language requires zero changes outside `code_intelligence/languages/`.

**`ContextResolutionResult`** (`domain/context_resolution.py`) — the central retrieval contract.
Carries `candidate_files: list[FileReference]`, each with `evidence_tier` (PRIMARY/SUPPORTING/
EXPERIMENTAL), `origin_stage` (AST_DIRECT/SCOPED_GRAPH_EXPANSION/RAW_STRING_FALLBACK/
EVIDENCE_FALLBACK_MATCH), `justification_chain`, `ambiguity_confidence`, `path_mask_confidence`,
`anchor_confidence`. Well-designed provenance contract — **but not universally populated**: two
reachable production code paths (`evidence_validator._to_file_reference`, and the entire DRP
resolver) construct `FileReference`s without `origin_stage`, contradicting the type's own docstring
claim that a `None` here "would indicate a call site this audit missed."

**`ContextPackage`** (`domain/context_package.py`) — the Layer 7 output contract.
`relevant_files: list[PackagedFile]`, `excluded_file_count`, `prompt_compression_ratio`,
`understanding_notes`. Clean, complete, honestly reports what didn't fit rather than silently
dropping it.

**`ExecuteRequest`/`ExecuteResponse`** (`interfaces/api/schemas.py:26-52`) — `prompt, model,
max_tokens` in; `content, usage, attempts` out. **No field anywhere in this contract can reference a
`ContextPackage`, `contract_id`, or resolution id.** This is the concrete, code-level proof behind
Gap 1 below.

**`UserIntent`** (`domain/intent.py`) — 11 fields (`raw_request, intent, domain, task, entities,
constraints, assumptions, confidence, clarifications, strategy_hints, complexity`). Of these, only
`raw_request` and `clarifications`/`needs_clarification` are read anywhere downstream of
contract creation (confirmed by exhaustive grep). `strategy_hints` and `complexity` are declared,
never populated by any construction site, and never read — `complexity`'s own module docstring
says it belongs to an "Execution Strategy Selector (Phase 3/7)" that doesn't exist yet.

---

## 3. Confirmed gaps, categorized per the audit brief's own gap taxonomy

### Missing communication

- **G1 — Query Understanding → Candidate Generation is not connected.** `UserIntent.entities`
  (SLM-1's extracted symbol names) is never read by `code_intelligence/service.py`. The retrieval
  API instead requires `target_names` as a separate, required, client-supplied field
  (`CreateCodeIntelligenceRequest.target_names`, `min_length=1`). `interfaces/api/routes/
  code_intelligence.py:58-60` passes `payload.target_names` straight through — `contract.intent.
  entities` never enters the call. *(Connection B, criterion C-B2 — direct violation.)*
- **G2 — Context Construction → Generation is not connected in the deployed API.**
  `execution/context_goal_composer.py` + `execution/final_generation.py` correctly consume a
  `ContextPackage` and ground a prompt — confirmed by direct read, this is real working code — but
  zero files under `src/interfaces/`, `src/application/`, `src/contracts/`, or `src/domain/` import
  either module (`grep -rn "import execution\|from execution" src/interfaces src/application
  src/contracts src/domain` → zero matches). `src/interfaces/api/app.py` registers exactly 7
  routers; none of them constructs `FinalGenerationRunner`. *(Connection G, criteria C-G1/C-G2/
  C-G3 — direct violation; also FA-1, FA-8.)*
- **G3 — Generation → Verification and Verification → Recovery cannot be connected because neither
  endpoint exists.** *(Connections H and I — non-existent by construction.)*

### Invalid communication / duplicated responsibility

- **G4 — Task type is independently re-derived three separate times** instead of reusing the one
  already computed and confidence-corroborated at contract creation: `contracts/manager.py:51`
  (via `TaskClassifier.agrees_with`, feeding `ConfidenceSignals` only), `code_intelligence/
  service.py:390` (fresh `TaskClassifier().classify()` call, feeding `retrieval_task_type`), and
  `interfaces/api/routes/context_package.py:109` (a *third*, independently-instantiated
  `TaskClassifier().classify()` call, feeding the ranking profile). None of the three reads
  `contract.intent.task`.
- **G5 — `ContextResolutionResult.confidence` is written by two structurally different formulas**
  depending on resolver path — `context_resolver.py`'s target-resolution ratio vs. `drp/
  query_router.py`'s margin-based subsystem-routing score — with no field on the object indicating
  which formula produced a given value. *(QU-4, RK-5 violation.)*
- **G6 — `RelevanceRanker._score` multiplies three semantically unrelated confidence signals**
  (`anchor_confidence`, `ambiguity_confidence`, `path_mask_confidence`) into one `relevance_score`
  float, with no per-factor breakdown retained on the output for `anchor_confidence` specifically.
  *(RK-5, RK-7 violation.)*
- **G7 — Ranking is invoked from inside candidate-generation code**, not just downstream packaging:
  `service.py:1068`, inside the experimental `_resolve_via_multi_axis_decomposition` (itself called
  from `_resolve` before the function returns), uses `RelevanceRanker.rank()`'s output to decide
  *which files become candidates at all* (top-1-per-axis selection), not just their order. Gated
  behind `enable_multi_axis_decomposition=True`, off by default and never set by the real API route
  — real, reachable code, not hypothetical. *(CG-6, RK-3 violation, scoped to an experimental path.)*

### Disconnected implemented functionality (dead/orphaned code)

- **G8 — `context/evidence_validator.py`'s `prune_experimental_candidates` is dead in production.**
  Its only caller, `MultiHopOrchestrator`, is never instantiated anywhere in `src/` outside its own
  unit tests — confirmed by the module's own docstring, which admits this directly. The other half
  of the same file, `validate_sufficiency`, *is* live (called unconditionally whenever a task type
  has a registered evidence contract).
- **G9 — `DecoratorGraph` is built on every index construction** but its one real consumer class,
  `MultiHopOrchestrator`, is never wired into `service.py` — an orphan two levels deep, exactly as
  the module's own "Phase 7 spike" docstring predicts.
- **G10 — `DependencyGraph` is built on every index construction**; its only consumption path,
  `CandidateFileSelector.impacted_files()`, has zero callers anywhere in `src/` (test-only).
- **G11 — `CandidateFileSelector.callers_of`/`.transitive_callers_of`** have zero production
  callers — `context_resolver.py` bypasses them and re-implements graph traversal directly against
  `CallGraph`/`SymbolIndex`.
- **G12 — The DRP subsystem (TF-IDF, PMI expansion, subsystem taxonomy/communities) is fully wired
  into `service.py._resolve_drp` behind `resolver_strategy="drp"`, but the sole production HTTP
  route never sets that parameter** (`interfaces/api/routes/code_intelligence.py:58-60` passes only
  3 positional args) — `grep`-confirmed zero production call sites ever set `resolver_strategy=
  "drp"`. Reachable only from tests and standalone benchmark scripts that call `DrpIndexBuilder`/
  `DrpResolver` directly, bypassing `service.py` entirely. *(RI-5, CG-1, FA-3 violation — this is
  precisely the "isolated utility with no architectural consumer" the brief warns against.)*
- **G13 — `TelemetryCollector`/`ConfidenceLabel` have zero production callers.** Opt-in by design,
  confirmed via exhaustive search that no route/service constructs one. `production_gate.
  evaluate_release()` is callable only from `scripts/` and one test file — an offline analysis
  tool, not a live release gate, despite `ARCF_V2.3_BASELINE_FREEZE.md` listing it under "frozen"
  (delivered) state.
- **G14 — `ExecutionLedgerEntry` has a fully built store and full CRUD/compare API but zero
  production writer.** The one production `store.save()` call (`PATCH /api/v1/executions/{id}`)
  only *updates* a pre-existing entry; nothing creates the initial one. The route file's own
  docstring names the missing piece: `application/execute_use_case.py`, which does not exist —
  `application/` is a 5-line empty stub. `POST /api/v1/execute` never touches the ledger at all.
  Downstream, `comparison_store`/`POST /api/v1/compare` is mechanically real on both sides but
  structurally starved of real input for the same reason.

### Incompatible contracts / information loss

- **G15 — `FileReference.origin_stage` is `None` on two reachable production paths** despite the
  type's own docstring implying this shouldn't happen: `evidence_validator._to_file_reference`
  (live, unconditional whenever a task has an evidence contract) and the entire DRP resolver path
  (live when reachable, see G12).
- **G16 — `_expand_subclasses` has no token-budget gate at all**, unlike `_expand_calls`
  (`context_resolver.py:642-684` — no `max_expansion_tokens` parameter, no `_TokenBudget.allow()`
  call). Under `RetrievalTaskType.LARGE_STRUCTURAL_CHANGE` (unbounded `traversal_depth`) with a
  CLASS-kind entry point, this is a genuine unbounded-output code path. *(CG-5, RE-3 violation.)*
- **G17 — Evidence quality (`evidence_tier`) is deliberately excluded from `RelevanceRanker`'s
  score computation** — it's read only later, by `ContextBudgetManager`, for compression-tier
  policy. So "evidence quality affecting ranking" (RK-4, C-E3) doesn't happen at the score level,
  only at the packaging level.
- **G18 — No persistence call anywhere is wrapped in try/except targeting store failures.**
  `contract_store.save`, `context_resolution_store.save`, `execution_ledger` `store.save`,
  `comparison_store.save` — all four production call sites are unguarded; a store exception
  propagates to an unhandled 500, aborting the request even after expensive upstream LLM work
  already succeeded and was already billed. Not silent corruption (PS-2 technically holds), but not
  isolated either (PS-4's spirit is violated).

### Documentation-vs-reality mismatch (new category, not in the brief's own list, but real)

- **G19 — `ARCF_V2.3_BASELINE_FREEZE.md` declares Execution Ledger, Context+Goal Composer/final
  generation, and Comparison API "frozen" (i.e., delivered, working, locked baseline).** Direct
  code inspection shows all three are either unreachable from the live API (G2) or have no real
  production data source (G14). The freeze document is describing code that exists and passes its
  own unit tests, but overstates its *integration* status.

---

## 4. Connection-by-connection status (A–J)

| Connection | Status | Basis |
|---|---|---|
| A — Repo Intelligence → Retrieval | **Partial** | Classic graphs (symbol/call/import/inheritance) flow correctly with compatible identifiers (`Symbol.id`). DRP/semantic vocabulary generated (when built) but discarded from the live API (G12). |
| B — Query Understanding → Retrieval | **Fail** | Entities never reach candidate generation (G1). Task/domain re-derived independently rather than reused (G4). Query confidence and retrieval confidence stay distinguishable only because they're never connected at all — a degenerate pass on C-B4. |
| C — Candidate Generation → Graph Expansion | **Mostly pass** | Valid candidates flow in; seed provenance survives via `parent_symbol_id`; call-expansion limits enforced; subclass-expansion limits are not (G16). |
| D — Retrieval → Evidence | **Partial** | Every evidence item originates from a retrieved candidate; non-empty-but-insufficient is representable (`evidence_categories_missing`) — but validation only rejects on path-glob absence, never on content quality. |
| E — Evidence → Ranking | **Fail** | Evidence quality is explicitly excluded from the ranking score (G17); ranking cannot distinguish structurally-similar candidates by evidentiary strength at the score level. |
| F — Ranking → Context | **Pass** | Confirmed: `ContextBudgetManager` consumes exactly the ranked list, order respected via an explicit documented policy (falloff gate + PRIMARY floor), provenance and budget both preserved. This is the one connection in the whole system with no confirmed gap. |
| G — Context → Generation | **Fail** | No live connection exists at all (G2). Not "bypassed" so much as "never built" in the deployed API. |
| H — Generation → Verification | **Fail (non-existent)** | Verification doesn't exist. |
| I — Verification → Recovery | **Fail (non-existent)** | Neither side exists. |
| J — Recovery → Retrieval | **Fail (non-existent)** | Recovery doesn't exist. Closest analog, `evidence_fallback.py`, is an inline same-call fallback cascade, not a post-hoc recovery re-entry. |

---

## 5. Cross-layer criteria — early read

| Criterion | Status | Note |
|---|---|---|
| XL-1 No orphaned info | **Fail** | G8–G14 are all confirmed orphans. |
| XL-2 No silent info loss | **Partial** | Most orphaning is at least docstring-documented (arguably "explicit," if you count code comments) — but the entities→target_names disconnect (G1) is not documented as intentional anywhere found. |
| XL-3 Contract compatibility | **Mostly pass** | Where connections exist, pydantic contracts are well-typed and compatible. |
| XL-4 Stable identity index→...→verification | **Partial** | Holds through Context; chain has nothing to extend into past that point. |
| XL-5 Provenance continuity Query→...→Verification | **Fail** | Breaks exactly at Context→Generation and Generation→Verification. |
| XL-6 Clear ownership | **Mostly pass** | One blur: multi-axis decomposition (G7) mixes ranking and retrieval ownership. |
| XL-7 No hidden bypasses | **Fail** | `/execute` is precisely this. |
| XL-8 No uncontrolled retry loops | **Pass (degenerate)** | True only because no retry/recovery loop exists yet. |
| XL-9 Consistent configuration reaching its consumer | **Partial** | Most `enable_*` flags correctly gated; `resolver_strategy="drp"` is a config value that can never be set from the live API (G12). |
| XL-10 Observable execution | **Partial** | Well-designed telemetry infrastructure exists; zero production caller instantiates it (G13). |

---

## 6. Draft Final Architecture Acceptance Matrix (FA-1 … FA-20)

| ID | Criterion | Status | Basis |
|---|---|---|---|
| FA-1 | One coherent execution path | **Fail** | Two disconnected systems (§1.1); no single trace exists from Query to Final Response without a client manually bridging 3 HTTP calls and then hitting a dead end. |
| FA-2 | Repository intelligence participates | **Partial** | Classic graphs do; DRP (the "semantic"/vocabulary half) doesn't reach the live API (G12). |
| FA-3 | Multiple retrieval signals converge | **Fail** | DRP is exactly the "competing retrieval universe operating independently" the brief warns against — except it can't even run in production today. |
| FA-4 | Retrieval separated from ranking | **Mostly pass** | True on the default path; violated on the experimental multi-axis path (G7). |
| FA-5 | Evidence is first-class | **Partial** | Real typed distinction exists (`EvidenceTier`, `evidence_categories_*`) but doesn't propagate into the ranking score itself (G17). |
| FA-6 | Confidence has architectural meaning | **Fail** | Multiple unrelated confidence signals conflated (G5, G6); `UserIntent.confidence` computed and never read again. |
| FA-7 | Context is traceable | **Mostly pass** | True through Context Construction; nothing to trace into beyond it. |
| FA-8 | Generation connected to retrieval | **Fail** | The definitive finding — G2. |
| FA-9 | Verification is connected | **Fail (non-existent)** | |
| FA-10 | Verification can influence control flow | **Fail (non-existent)** | |
| FA-11 | Recovery is bounded | **N/A** | Nothing to bound; the one real retry mechanism (LLM transport retry) is bounded but isn't semantic recovery. |
| FA-12 | End-to-end provenance | **Fail** | Chain breaks at Context→Generation. |
| FA-13 | Architecture is testable | **Partial** | Individual layers are well-tested (992 tests per PROGRESS.md); no test exercises the full Query→Response path because that path doesn't exist server-side. |
| FA-14 | Architecture is explainable | **Partial** | `reason`/`justification_chain` explain *why a candidate matched*; no field explains *why a numeric score is what it is* (G6). |
| FA-15 | No architectural dead ends | **Fail** | G8–G14 are all dead ends by the criterion's own definition. |
| FA-16 | No invalid dependency direction | **Pass** | No violation found — infrastructure doesn't own domain logic anywhere inspected. |
| FA-17 | No duplicated system-of-record | **Partial** | Task classification is computed 3 times independently rather than once and reused (G4) — not a competing store, but a competing computation of the same fact. |
| FA-18 | Existing functionality preserved | **N/A for discovery** | No changes made yet. |
| FA-19 | Deterministic boundaries stay deterministic | **Pass** | Confirmed: indexing, retrieval, ranking, budgeting are all deterministic by construction and by test (PROGRESS.md's determinism re-verification, incremental-equivalence tests). No LLM controls repository structure. |
| FA-20 | End-to-end acceptance demo | **Fail** | Cannot be demonstrated — the path doesn't connect end to end. |

---

## 7. Relationship to the project's own existing plan (important context)

This audit's brief describes an 11-layer model including a dedicated Verification layer and a
Recovery/Retry layer. Cross-referencing against `ARCF_v2.3_ARCHITECTURE_REVIEW.md`'s own 11-phase
plan:

- **Phases 7 (Planning), 9 (Execution Ledger), 10 (Orchestration/Runtime), 11 (Token
  Intelligence)** map reasonably onto this audit's Context Construction/Generation, Persistence,
  Recovery, and observability layers respectively — **and are explicitly, deliberately unbuilt or
  partially built**, per the project's own staging decisions. This is not something this audit
  discovered; the project already knew and documented it.
- **There is no Phase anywhere in the existing plan corresponding to Verification** (comparing a
  generated answer against retrieved evidence for unsupported claims/contradictions). This is a
  genuine gap between what this audit's acceptance criteria require and what ARCF's own roadmap
  ever scoped — worth a direct decision from whoever owns the roadmap, not just an implementation
  task.
- **`ARCF_V2.3_BASELINE_FREEZE.md` currently prohibits**, unless the freeze is re-scoped again:
  new architectural modules beyond Stages 1–6, autonomous agentic loops, and (relevant to Layer 10)
  anything resembling workflow automation. **A Recovery/Retry layer that re-enters retrieval based
  on a failure judgment sits close to "agentic loop" territory** by this document's own prohibited
  list — building it may require an explicit re-scope decision from the repository owner, the same
  kind of decision the "Re-scope Addendum (2026-08-06)" already shows this project makes
  deliberately, not silently.
- **The freeze also explicitly prohibits embeddings/semantic/probabilistic retrieval and learned
  retrieval weights.** This audit's RI-5 ("semantic information preserved... accessible through a
  retrieval-facing contract") should be read against that constraint: DRP's TF-IDF/PMI/taxonomy
  subsystem *is* ARCF's deterministic (non-learned, non-embedding) answer to "semantic" retrieval,
  and it exists — the actual gap is that it's unreachable from the live API (G12), not that
  semantic retrieval is architecturally missing by design.

---

## 8. What this report is and isn't

This is Steps 1–6 (Discovery → Gap Detection) of the requested process, covering all 11 layers and
all 10 named connections plus cross-layer and final-architecture criteria, entirely from direct
code reads (no historical results used). It does **not** include Steps 7–10 (Restructure, Test,
Acceptance Verification, Final Report) — no code has been changed.

**Recommended next decision points**, not yet actioned:

1. **Highest-leverage single fix**: give `/execute` (or a new endpoint) a way to consume a
   `ContextPackage` and route it through the already-correct, already-tested `context_goal_
   composer.py`/`final_generation.py` code (G2). This alone would close FA-1, FA-8, GN-1/2/3, and
   Connection G, without inventing anything new — the code to wire already exists.
2. **Cheapest real win**: thread `contract.intent.entities` into `attach_code_intelligence` as a
   default source for `target_names` when the client doesn't override it (G1) — closes QU-2,
   Connection C-B2, without changing any downstream contract.
3. **Decision needed, not just code**: whether Verification is in scope for this restructuring at
   all, given it was never on ARCF's own roadmap — this is a genuinely new capability, not a wiring
   fix, and should be scoped deliberately (§7) rather than bolted on to satisfy a checklist.
4. **Decision needed, not just code**: whether Recovery/Retry can be built under the current freeze
   scope, or needs its own re-scope addendum first, given its adjacency to the freeze's "no
   autonomous agentic loops" prohibition (§7).

None of the above has been started. Awaiting direction on which to pursue first.
