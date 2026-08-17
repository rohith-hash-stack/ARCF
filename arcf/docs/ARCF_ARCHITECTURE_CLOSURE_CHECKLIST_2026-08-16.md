# ARCF Architecture Closure — Master Checklist & Progress Record

**Status (2026-08-17, updated): implementation pass complete against the independent verification
report's full findings list.** See §42 for the full record — 3 rounds of independent re-verification
have now happened (§41.1, the 2026-08-17 10-agent independent report, and this implementation pass
closing its findings), each finding real issues the previous round missed. **1052/1052 tests
passing** (was 1022 before this pass; +30 net new). Not yet committed to git — see §40/§42 for the
full file list; awaiting the user's go-ahead to commit (this session does not commit without being
asked).

The line below ("CLOSURE COMPLETE, adversarially re-verified") is preserved as the historical record
of what §41.1's round concluded — §42 documents why that conclusion, while honest about what it
covered, was not the final word, and should not be read as the current status on its own.

**Two verification rounds happened, both triggered by direct user requests to re-check rather than
accept the prior claim, and both found real issues:**
1. "Did you cover ARCF DI?" → found 2 real DI gaps (config not threaded through Settings, no
   automated circular-dependency test) — fixed, see §22's correction note. 1008→1011 tests.
2. "Check everything one more time... make sure every gap resolved" → 4 independent adversarial
   agents (one per: orchestrator/recovery bug-hunting, DI re-verification, gap-by-gap G1-G19
   cross-check, inter-layer data-flow tracing) → found **6 real code bugs** and **2 of the original
   19 numbered gaps silently missing from tracking entirely** (not fixed, not deferred, just absent
   — exactly the failure mode this whole exercise exists to catch). All fixed; see §41.1 for the
   full account. 1011→1022 tests.

Read §41.1 before trusting any earlier section's "VERIFIED"/"PASS" language at face value — several
were corrected after being marked prematurely. This file is now accurate as of the second round; if
you find a THIRD gap between a claim here and the code, that's a repeat of the same pattern — verify
against the code directly, don't extend trust to this document by default.

**This is the single source of truth for the architecture-closure effort.** If you are picking this
up in a new session: read this file top to bottom before doing anything else. It supersedes nothing
in `PROGRESS.md`/`CHECKLIST.md` (those track the project's general backlog); this file tracks only
the closure authorized 2026-08-16.

**Branch:** `feature/architecture-closure`, off `Base` (`5b7fa5c`). Baseline test count on branch
creation: **992/992 passing** (`.venv/Scripts/python.exe -m pytest -q`, run from `arcf/`). **Use the
venv's Python** (`arcf/.venv/Scripts/python.exe`), not system Python — system Python is missing
`litellm` and will show false collection errors.

**Prior analysis documents this closure is built on** (read these for full detail; this file
summarizes and tracks, doesn't repeat):
- `ARCF_ARCHITECTURE_AUDIT_DISCOVERY_2026-08-16.md` — 19 numbered gaps (G1–G19), connection-by-
  connection status (A–J), draft acceptance matrices.
- `ARCF_ARCHITECTURE_CLOSURE_PLAN_2026-08-16.md` — stage-by-stage status table, confidence
  inventory, Retrieval→Evidence→Context path characterization, Case A/B/C failure-state analysis,
  Verification/Recovery placement determination.

**Authorization on record:** Verification and bounded deterministic Recovery are in scope, narrowly
— evidence-based, deterministic, bounded, no LLM-directed control flow, no semantic/contradiction
detection, no new retrieval algorithms, no embeddings. DI is explicitly in scope as part of this
closure, not a separate task. This is one closure, not phased sign-offs — implemented in dependency
order internally, reported once.

**Status legend:** `NOT_STARTED` · `IN_PROGRESS` · `BLOCKED` (reason required) · `IMPLEMENTED` (code
exists) · `VERIFIED` (acceptance criterion actually demonstrated, not just "looks correct") ·
`DEFERRED` (explicit justification required).

---

## How to resume this in a new session

1. Read this file fully.
2. Run `cd arcf && .venv/Scripts/python.exe -m pytest -q` — confirm you're still at ≥992 passing
   before touching anything.
3. Check `git log --oneline -15` on `feature/architecture-closure` against the "Implementation log"
   (§40) below to see what's actually landed vs. what this file claims.
4. Find the first `NOT_STARTED`/`IN_PROGRESS`/`BLOCKED` item in dependency order (§3 P0 first, then
   §13 onward) and continue there.
5. Update this file's relevant section (status, implementation location, evidence, tests) as part
   of the same commit that does the work — not as an afterthought.

---

## 1. Architecture Spine / Application Orchestrator

| Item | Status | Location | What changed | Acceptance criterion | Evidence |
|---|---|---|---|---|---|
| `ArcfExecutionOrchestrator` class | **VERIFIED** | `src/application/execute_use_case.py` (new) | Full pipeline: `attach_code_intelligence` → evidence check → `package` → `generate` → `verify_grounding` → bounded recovery → `ArcfExecutionResult` → ledger write | FA-01, FA-02 | `tests/application/test_execute_use_case.py` (7 tests) + `tests/interfaces/test_grounded_execution_route.py` (4 tests), all passing |
| Orchestrator constructed via existing composition root | **VERIFIED** | `src/interfaces/api/app.py` (`create_app`) | Constructed with the same singleton `code_intelligence_service`/`context_packager` instances already used by the lower-level routes — not a parallel set | DI-FA-02 | `test_production_composition_root_constructs_orchestrator_via_di` asserts identity (`is`), not just type |
| New canonical HTTP entry point | **VERIFIED** | `src/interfaces/api/routes/grounded_execution.py` (new), `POST /contracts/{id}/grounded-execution` | One HTTP call, starting from only a `contract_id`, reaches a real generated + verified answer | FA-01, FA-02 | `test_grounded_execution_full_pipeline_reaches_generated_verified_answer` — real end-to-end, no mocking beyond `litellm.acompletion` |

## 2. Layer Responsibilities

Full responsibility table (Purpose/Inputs/Outputs/Dependencies/Consumers/Failure behavior per
layer) — see §32 (Layer Acceptance Criteria) for the per-layer table; not duplicated here to avoid
two competing tables drifting apart.

## 3. Layer Contracts

Tracked per-layer in §32. Cross-layer contract type inventory:

| Contract type | File | Status as of closure start |
|---|---|---|
| `UserIntent` | `domain/intent.py` | Existing, unchanged by this closure except how `entities` is consumed downstream |
| `ContextResolutionResult` | `domain/context_resolution.py` | Existing, unchanged |
| `ContextPackage` | `domain/context_package.py` | Existing, unchanged |
| `Artifact` | `domain/artifact.py` | Existing, unchanged |
| `GroundingVerificationResult` | `domain/verification_result.py` (new) | NOT_STARTED |
| `ExecutionLedgerEntry` | `domain/execution_ledger.py` | Existing, unchanged — gets a real writer |
| Canonical execution result | TBD, see §23 | NOT_STARTED |

## 4. Layer-to-Layer Communication

See discovery report §4 (Connection A–J) for baseline status. Tracked for changes in §33.

## 5. Information Propagation

See closure plan §E (information-loss map). Two items this closure actually fixes:
`UserIntent.entities` → retrieval (§6), `evidence_categories_missing` → a real decision (§11/§17).
Everything else in that map is either already fine or explicitly out of scope (see §39).

## 6. Query Understanding

| Item | Status | Location | What changed | Acceptance | Evidence |
|---|---|---|---|---|---|
| `attach_code_intelligence` defaults `target_names` from `contract.intent.entities` when caller supplies none | **IMPLEMENTED** | `src/code_intelligence/service.py` (`_resolve` call site) | `effective_target_names = target_names or list(latest.contract.intent.entities)` | QU-2, C-B2: "entities reach retrieval without requiring the client to duplicate extraction" | Code change + `CreateCodeIntelligenceRequest.target_names` relaxed from `min_length=1` to `default_factory=list` in `schemas.py` |
| Existing callers unaffected (explicit `target_names` still respected) | **VERIFIED** | same | `or` short-circuits on any non-empty list — identical behavior for every caller that supplies names | Backward compatibility | Full suite: 995/995 (992 baseline, zero regressions) after this + 2 other changes below |

## 7. Workspace / Repository Scope

**Investigated (2026-08-16):** `WorkspaceContractService`/`WorkspaceAnalyzer` (git discovery,
language detection, structure analysis, permissions) own repository-level metadata
(`WorkspaceMetadata`). `code_intelligence/engine.py` does its own independent file scan
(`RepositoryScanner().scan(root_path)` inside `service.py._resolve`) rather than reusing
`WorkspaceMetadata`'s already-scanned file list. **Determination:** this is DUPLICATION, not
clearly intentional — `service.py` calls `RepositoryScanner().scan()` fresh rather than accepting
the already-scanned `ScannedFile` list from a prior `WorkspaceContractService` call. **Decision:
DEFERRED**, not fixed in this closure — it's a real inefficiency (double directory walk) but not a
correctness gap (both scans use the same `RepositoryScanner` with the same `max_files` config, so
results are consistent, not divergent), and touching it risks the workspace/code-intelligence
boundary for no closure-relevant benefit. Documented here so it isn't silently lost. See §39.

## 8. Code Intelligence

No changes planned. Full status already covered (discovery report §2, closure plan §B rows 4–7).
This closure does not modify `ContextResolver`, `locality.py`, `candidate_selector.py`, any graph
class, or any language analyzer.

## 9. Retrieval / Resolution

No changes to `ContextResolver`/`ReferenceResolver` internals. The only touch point is
`attach_code_intelligence`'s `target_names` default (§6) — an additive parameter-handling change at
the service boundary, not a resolution-algorithm change.

## 10. DRP Integration

| Item | Status | Location | What changed | Acceptance | Evidence |
|---|---|---|---|---|---|
| DRP reachable as the orchestrator's Recovery strategy | NOT_STARTED | `application/execute_use_case.py` | — | FA-12, P0.8 | — |
| No second DRP implementation created | NOT_STARTED (constraint, not a task) | — | — | "Do not create another DRP implementation" | Will verify at closure: grep confirms only `code_intelligence/drp/` implements DRP |

## 11. Evidence

| Item | Status | Location | What changed | Acceptance | Evidence |
|---|---|---|---|---|---|
| `evidence_categories_missing` gates a real decision (proceed vs. recovery attempt) | NOT_STARTED | `application/execute_use_case.py` | — | FA-07, C-D3 | — |
| Existing `validate_sufficiency` behavior unchanged | NOT_STARTED (constraint) | `context/evidence_validator.py` | — | No regression | — |

## 12. Ranking

**No changes.** Per your instruction §16 ("do not redesign ranking unnecessarily") and the closure
plan's own finding (§G: evidence integrates as a gate, not a new ranking dimension) — confirmed the
existing ranking contract is not incorrect, just not evidence-aware at the score level, which is an
intentional, documented, unchanged design choice this closure does not touch.

## 13. Context Construction

**No changes.** Already the one connection (Ranking→Context) with zero confirmed gaps (discovery
report §4). This closure only adds a *caller* of `ContextPackager.package()` (the orchestrator) —
the packager itself is untouched.

## 14. Goal Composition

**No changes.** `execution/context_goal_composer.py` already correctly consumes `ContextPackage` —
confirmed by direct read during discovery. This closure gives it a caller, not new logic.

## 15. Generation

| Item | Status | Location | What changed | Acceptance | Evidence |
|---|---|---|---|---|---|
| `FinalGenerationRunner` constructed in the composition root | **VERIFIED** | `src/interfaces/api/app.py` | `app.state.generation_runner = FinalGenerationRunner(ContextGoalComposer(), llm_client, settings.default_model)` | GN-1, FA-08 | Constructed on every `create_app()` call; DI test confirms |
| Orchestrator calls `FinalGenerationRunner.generate()` | **VERIFIED** | `application/execute_use_case.py` | `artifact, generation_llm_response = await self._generation_runner.generate(living.contract, package, resolution)` | Connection G (Context→Generation) closes | End-to-end test proves `Artifact.content` reaches the HTTP response, grounded in the real `ContextPackage` |

## 16. Deterministic Grounding Verification

| Item | Status | Location | What changed | Acceptance | Evidence |
|---|---|---|---|---|---|
| `GroundingVerificationResult` contract | **VERIFIED** | `domain/verification_result.py` (new) | `status`/`evidence_sufficient`/`missing_evidence_categories`/`unsupported_file_references`/`contradictions_checked`/`recovery_eligible` | Structured result, no capability overclaim | `contradictions_checked` is hardcoded `False` on every path — never fabricated true |
| `verify_grounding()` pure function | **VERIFIED** | `execution/verification.py` (new) | Deterministic evidence-category check + deterministic file-path-reference check | VF-1 (evidence-based), explicitly NOT VF-3 (contradiction — unsupported, documented as such) | 5/5 unit tests (`tests/execution/test_verification.py`): sufficient, insufficient-evidence, unsupported-reference, git-diff-path-prefix-tolerance, prose-with-no-paths |
| Orchestrator calls verification after generation | **VERIFIED** | `application/execute_use_case.py` | `verification = verify_grounding(artifact, package, resolution)` | FA-08, P0.5 | Same tests above |

## 17. Recovery / Retry

| Item | Status | Location | What changed | Acceptance | Evidence |
|---|---|---|---|---|---|
| `MAX_RECOVERY_ATTEMPTS = 1` fixed bound, shared across both trigger points | **VERIFIED** | `application/execute_use_case.py` | Single `attempt` counter, checked at both the pre-generation evidence gate and the post-generation verification gate | FA-09, P0/§18 | `test_recovery_never_exceeds_max_recovery_attempts`, `test_unsupported_reference_triggers_recovery_and_exhausts_to_low_confidence` — both confirm `recovery_attempts == 1`, never more, even when the retry doesn't fix the problem |
| Strategy selection: evidence-insufficient OR verification-failed → retry once with `resolver_strategy="drp"` | **VERIFIED** | same | Hardcoded literal `strategy = "drp"` — no LLM, no dynamic construction | FA-10, FA-11, §19 | `test_insufficient_evidence_triggers_one_recovery_attempt_with_drp_strategy` (Case B) and the unsupported-reference test (Case C) both confirm `strategy_used == "drp"`. As a direct side effect, DRP now has a real production consumer (closes the separately-flagged G12/RI-5/FA-3 gap) |
| Exhaustion → explicit low-confidence/failure result, never silent success | **VERIFIED** | same | `final_status = "success" if verification.status == SUFFICIENT else "low_confidence"` | FA-13, §20 | `test_unsupported_reference_triggers_recovery_and_exhausts_to_low_confidence` — retry doesn't self-correct (fake LLM repeats the same content), result is honestly `"low_confidence"`, not `"success"` |
| Internal fallback (`evidence_fallback.py`, lexical probe) left untouched, separate budget | **VERIFIED** (constraint honored) | — | Zero changes to `evidence_fallback.py`/`lexical_symbol_probe.py`/`anchor_classifier.py` | §15, §21 — internal fallback is NOT the application Recovery budget | Full suite green; Case A (empty retrieval) continues to be handled entirely inline within one `attach_code_intelligence` call, never touching `MAX_RECOVERY_ATTEMPTS` |
| Recovery re-enters only through the existing orchestration boundary, never touches internals | **VERIFIED** | same | Recovery calls only `attach_code_intelligence`/`package`/`generate` — the same 3 public methods any HTTP caller could call individually | P0.7, §14 | `application/execute_use_case.py` imports zero symbols from `code_intelligence.context_resolver`/`call_graph`/`symbol_index`/`locality` — grep-confirmed |

## 18. Failure-State Handling

Case A (empty retrieval) / Case B (insufficient evidence) / Case C (ungrounded generation) — see
closure plan §H for the full analysis. Case A already handled internally, untouched. B and C both
route through the one Recovery mechanism above, each tagged with its own reason in the canonical
result (§23) — not collapsed into one boolean.

## 19. Confidence Contracts

| Item | Status | Location | What changed | Acceptance | Evidence |
|---|---|---|---|---|---|
| No combined confidence score introduced | **VERIFIED** (constraint honored) | — | `ArcfExecutionResult` carries `resolution_confidence`/`resolution_confidence_source` as two separate fields, never blended | §25/§26/§27, FA-14 | Domain type + orchestrator tests |
| `ContextResolutionResult.confidence` dual-formula conflation (classic vs. DRP) | DEFERRED (justification corrected 2026-08-17) | `domain/context_resolution.py`, `drp/query_router.py` | — | **Correction**: the original justification here ("zero current consumers") became false the moment this closure's own `ArcfExecutionResult.resolution_confidence` started reading `resolution.confidence` directly (`execute_use_case.py`). The field now DOES have a real consumer. The deferral decision itself still stands — fixing the two-formula conflation is a separate, riskier change to a widely-read field, and the new result type already adds the provenance tag (`resolution_confidence_source`) the old field itself lacks, which is what actually mattered for this closure's own output. But the stated reason for deferring needed correcting, not the decision. Found by the 2026-08-17 adversarial re-verification (§41.1), not the original work. | See §39 |

## 20. Dependency Direction

**Investigated (2026-08-16).** Real import graph between `context/` and `code_intelligence/`
(`grep`-verified both directions):

- `code_intelligence/service.py` imports 8 names from `context/` (`anchor_classifier`,
  `evidence_fallback`, `evidence_validator`, `lexical_symbol_probe`, `query_decomposition`,
  `relevance_ranker`, `subsystem_localizer`, `task_profile`) — expected and correct: `service.py` is
  the retrieval orchestrator, it's supposed to call ranking/evidence/fallback helpers.
- `context/anchor_classifier.py`, `context/lexical_symbol_probe.py`, `context/subsystem_localizer.py`
  import `SymbolIndex` from `code_intelligence.symbol_index` — the only `context/` → `code_intelligence`
  direction found.

**Determination:** this is **not** the boundary violation it first appears to be. `SymbolIndex` is
`code_intelligence`'s own intentional public read-interface (`.find_by_name`, `.get`, `.by_kind`,
etc.) — the same interface `candidate_selector.py`/`reference_resolver.py`/`locality.py` (all
squarely inside `code_intelligence`) already consume. Reading it via its defined query methods is
legitimate layering, not "reaching into internals." **Critically, the TRUE Ranking/Context
Construction layer — `context/relevance_ranker.py`, `context/packager.py`,
`context/budget_manager.py`, `context/compressor.py`, the files whose contracts actually matter for
FA-06 — have ZERO `code_intelligence` imports**, confirmed by direct grep. The 3 files that do import
`SymbolIndex` are experimental, flag-gated-off (§26/§28) retrieval-time fallback mechanisms that are
functionally part of Candidate Generation/Retrieval (layer 3/4), just historically placed under
`src/context/` by package naming rather than function. No behavior is wrong; the package boundary is
cosmetically misleading, not architecturally broken.

**Real gap found and being fixed:** the existing architecture-boundary test
(`tests/code_intelligence/test_phase6_boundary.py`) only verifies a **synthetic stub file**
(`phase6_stub_consumer.py`) never imports `code_intelligence` — it does not inspect any real
production file. Per your own instruction ("if existing tests don't detect real dependency paths,
fix the tests"), this closure adds a new test asserting the actual production Ranking/Context
files have zero `code_intelligence` imports — a real, previously-unverified boundary.

| Item | Status | Location | What changed | Acceptance | Evidence |
|---|---|---|---|---|---|
| Investigation | VERIFIED | — | — | Documented above | This entry |
| No code move/refactor of the 3 `SymbolIndex`-reading modules | DEFERRED (decision, not oversight) | — | — | Package-organization nit, not a live defect; all 3 are feature-flagged off by default; moving files risks unrelated test breakage for zero closure-relevant benefit | See §39 |
| New architecture boundary test: real Ranking/Context files have zero `code_intelligence` imports | **VERIFIED** | `tests/code_intelligence/test_phase6_boundary.py` (extended) | New `test_real_ranking_and_context_construction_modules_do_not_import_code_intelligence`, AST-parses the 4 real files directly | FA-06, DI-FA-10, P30 | Passes — confirms zero `code_intelligence` imports in `relevance_ranker.py`/`packager.py`/`budget_manager.py`/`compressor.py` |

## 21. Expansion Bounds

| Item | Status | Location | What changed | Acceptance | Evidence |
|---|---|---|---|---|---|
| `_expand_subclasses` first loop (candidate files) has no token-budget gate (G16 from discovery report) | **VERIFIED** | `code_intelligence/context_resolver.py` | Threaded `max_expansion_tokens`/`_TokenBudget` into `_expand_subclasses` the same way `_expand_calls` already uses it; call site updated | FA-15, CG-5, RE-3 | `test_unbounded_subclass_expansion_respects_max_expansion_tokens` |
| `_expand_subclasses` **second** loop (feeding `impacted_symbols`) has no bound at all | **VERIFIED** (corrected 2026-08-17 — see §41.1) | `code_intelligence/context_resolver.py` | **Correction**: the original fix above only covered the first loop. The 2026-08-17 adversarial re-verification found this second loop — over `inheritance_graph.all_subclasses_of`, feeding `impacted_symbols`, which `RelevanceRanker` genuinely reads for its `impacted_counts` scoring signal — remained fully unbounded, contrary to the original "Fixed + regression-tested" claim. Added `_MAX_IMPACTED_SUBCLASS_SYMBOLS = 200` as a deterministic count cap. | FA-15 | New `test_wide_subclass_hierarchy_caps_impacted_symbols_count` — a 300-direct-subclass fixture confirms the cap holds |

**Scope note:** this is a real, confirmed inconsistency (call-expansion bounded, subclass-expansion
not) and FA-15 requires it. Fixing it is a small, additive, low-risk change (thread the existing
`_TokenBudget` into `_expand_subclasses` the same way `_expand_calls` already uses it) — in scope
for this closure, tracked here, not deferred, since FA-15 explicitly names "all production retrieval
expansion paths" and Recovery's own bound doesn't substitute for it (§31/your instruction explicitly
says so).

## 22. ARCF Dependency Injection

**Investigated (2026-08-16).** Findings:

- **Composition root:** `src/interfaces/api/app.py`'s `create_app()` function. No formal DI
  container/framework (no `dependency-injector`, `punq`, service-locator library) — a disciplined
  manual pattern: every service is constructor-injected with its real collaborators inside
  `create_app()`, then stashed on `app.state`.
- **"Injection" mechanism:** FastAPI's `Depends()` + small `get_*` accessor functions in
  `interfaces/api/dependencies.py`, each fetching one singleton off `request.app.state`.
- **Lifetimes:** everything is an app-lifetime singleton, constructed once, alive for the process.
  The one exception is `ExecutionContext`, built fresh per request in `get_execution_context`
  (auth/budget/trace state — correctly request-scoped).
- **Testability:** confirmed via `tests/interfaces/test_execute_route.py` — tests call
  `create_app(settings=test_settings)` (a real construction, with test-scoped config: temp SQLite
  paths, permissive rate limits) and monkeypatch the outermost I/O edge (`litellm.acompletion`) with
  `pytest.monkeypatch`, rather than using FastAPI's `dependency_overrides`. This is the established,
  consistent convention across this codebase's route tests — not a gap, a working pattern to match.
- **Strategy selection (Classic/DRP):** currently a call-time string parameter
  (`resolver_strategy: Literal["classic","drp"]`) on `attach_code_intelligence`, not a
  construction-time injected strategy object. **Decision: keep it this way.** Converting it to a
  DI-constructed strategy abstraction would be exactly the "mechanically convert everything to DI"
  anti-pattern your own instruction (§42) says to avoid — the existing contract is already tested,
  already correct, and call-time selection is the right shape for something the orchestrator decides
  per-attempt (attempt 0 vs. the one recovery attempt), not something fixed at construction time.

**DI design decisions for this closure:**

**Correction (2026-08-17, caught by direct re-check after an initial premature PASS claim — not by
new investigation):** two real gaps existed against this section's own items even after the first
implementation pass:
1. **Item #43 (config ownership):** `max_recovery_attempts` was a hardcoded module constant used
   only as a constructor default — never sourced from `Settings`, unlike `generation_model` (which
   correctly flows `Settings.default_model` → `create_app()` → orchestrator). **Fixed**: added
   `Settings.arcf_max_recovery_attempts: int = 1` (`shared/config.py`), threaded through
   `create_app()`. Test: `test_max_recovery_attempts_flows_from_settings_through_composition_root`.
2. **DI-04/DI-FA-10 (no circular dependency):** verified only via a one-off manual grep during
   investigation, never locked in as an automated test — exactly the "test passing isn't sufficient
   if it doesn't inspect the real dependency path" trap this closure's own §20 work had already
   flagged once, recurring here. **Fixed**: two new permanent tests in
   `tests/code_intelligence/test_phase6_boundary.py` — `test_application_orchestrator_does_not_
   import_code_intelligence_internals` (the orchestrator imports only `code_intelligence.service`,
   never `context_resolver`/`call_graph`/`symbol_index`/`locality`/`reference_resolver`/
   `candidate_selector`) and `test_no_reverse_dependency_from_code_intelligence_or_context_onto_
   application` (scans every file under both packages for a reverse import).

Both were caught by the user asking "did you cover ARCF DI?" and re-verifying directly rather than
re-asserting the prior claim — worth recording as a lesson for this closure specifically: **PASS was
marked before code-level regression protection existed, not just before the property was true.**

| Decision | Status | Location | Rationale |
|---|---|---|---|
| `ArcfExecutionOrchestrator` gets constructor-injected dependencies (`code_intelligence_service`, `context_packager`, `generation_runner`, `execution_ledger_store`), matching every other service in this codebase | **VERIFIED** | `application/execute_use_case.py` | Consistency with existing pattern (DI-FA-02) |
| Orchestrator constructed in `create_app()`, exposed via a new `get_arcf_orchestrator` in `dependencies.py` | NOT_STARTED | `interfaces/api/app.py`, `interfaces/api/dependencies.py` | DI-FA-01 (one composition root, not a second one) |
| `verify_grounding()` is a pure function, NOT a DI-injected class | DECIDED | `execution/verification.py` | It has no collaborators to inject (no I/O, no config beyond a fixed threshold constant) — forcing it into an injectable class to satisfy DI-08 mechanically would violate §42's own explicit prohibition. Testability (DI-08) is satisfied by direct function call in unit tests — no injection machinery needed for something with zero runtime dependencies. |
| Recovery strategy selection is inline orchestrator logic, not a separate injected class | DECIDED | `application/execute_use_case.py` | It's 2 branches on already-computed structured data (`evidence_categories_missing`, `GroundingVerificationResult.status`) — no external collaborator to inject. Testable directly by calling the orchestrator with fake sub-dependencies (matching this codebase's existing test convention, not a new one). |
| `resolver_strategy` stays a call-time parameter, not DI-constructed | DECIDED | `code_intelligence/service.py` (unchanged) | See investigation notes above |

### DI tests (DI-01 … DI-10)

| ID | Criterion | Status |
|---|---|---|
| DI-01 | Composition root can construct production graph | NOT_STARTED |
| DI-02 | Orchestrator can be constructed through DI | NOT_STARTED |
| DI-03 | Required dependencies are provided | NOT_STARTED |
| DI-04 | No prohibited circular dependencies | NOT_STARTED |
| DI-05 | Critical dependencies replaceable in tests | NOT_STARTED (will reuse existing monkeypatch-the-edge convention) |
| DI-06 | Classic/DRP strategy injection works | N/A by design — see decision table above (call-time, not DI-time); will test the call-time branching instead |
| DI-07 | Recovery independently testable | NOT_STARTED |
| DI-08 | Verification independently testable | NOT_STARTED |
| DI-09 | DI does not violate architecture boundaries | NOT_STARTED |
| DI-10 | Complete grounded execution graph constructible | NOT_STARTED |

## 23. Execution Result Contract

| Item | Status | Location | What changed | Acceptance | Evidence |
|---|---|---|---|---|---|
| Canonical execution result type (artifact, retrieval outcome, context outcome, verification result, recovery attempts, final status, confidence, provenance) | **VERIFIED** | `domain/execution_result.py` (new): `ArcfExecutionResult` | `request_id, contract_id, context_resolution_id, context_package_id, artifact, verification, recovery_attempts, strategy_used, final_status, resolution_confidence, resolution_confidence_source, llm_responses` | FA-16, P0.9 | Exercised by every orchestrator/route test; `resolution_confidence_source` is the new provenance tag deferred-but-not-forgotten fix (§19/26) — it doesn't fix the old field's dual-formula conflation but stops the new contract from inheriting the ambiguity |

## 24. Execution Ledger

| Item | Status | Location | What changed | Acceptance | Evidence |
|---|---|---|---|---|---|
| Orchestrator writes a real `ExecutionLedgerEntry` per run | **VERIFIED** | `application/execute_use_case.py` (`_persist_ledger_entry`, `_persist_failure_ledger_entry` for the partial-failure case) | Real prompt/tokens/cost/latency/selected files/symbols, plus `recovery_attempts`/`strategy_used`/`final_status`/`verification_status` in `metadata`; store-write failures now caught and logged rather than propagated (PS-4) | FA-17, P0.10 | `test_normal_path_reaches_generation_and_verification`, the HTTP end-to-end test, `test_exception_during_recovery_retry_still_persists_real_spend_from_attempt_zero`, `test_ledger_store_failure_does_not_crash_an_otherwise_successful_run` |
| No second execution-history mechanism created | **VERIFIED** (constraint honored) | — | Reuses `ExecutionLedgerStore`/`ExecutionLedgerEntry` exactly as they already existed — zero schema changes | Reuse `ExecutionLedgerStore` as-is, no schema change | `git diff` on `domain/execution_ledger.py`/`infrastructure/execution_ledger_db.py` is empty |
| **Scope correction (2026-08-17, §41.1)**: G14's closure was overstated | — | `infrastructure/comparison_store.py`, `interfaces/api/routes/comparison.py` | The original G14 finding covered TWO things: the execution ledger having no production writer (this closure genuinely fixes that), AND `comparison_store`/`POST /api/v1/compare` being "structurally starved of real input for the same reason." **Only the first half was fixed.** The orchestrator never touches `comparison_store`/`ComparisonAggregator`; that half of G14 remains exactly as broken as the discovery report originally found it, and this document didn't say so until the adversarial re-verification caught it. | — | Confirmed by direct re-check: `execute_use_case.py` has zero references to `comparison_store`/`ComparisonAggregator` |

## 25. Secure Fast Path Separation

| Item | Status | Location | What changed | Acceptance | Evidence |
|---|---|---|---|---|---|
| `/api/v1/execute` left functionally unchanged | **VERIFIED** (constraint honored) | `interfaces/api/routes/execute.py` | Zero changes | P0/§37, FA-20 | `git diff` on this file is empty; its own existing tests (`tests/interfaces/test_execute_route.py`) unmodified and still passing |
| New canonical route clearly distinct in naming/docs from the raw path | **VERIFIED** | `interfaces/api/routes/grounded_execution.py` (new) | `POST /contracts/{id}/grounded-execution` — name and module docstring both explicit that this is the grounded pipeline, `/execute` is the separate raw path | P12 | Route module docstring states the distinction explicitly |

## 26. Orphaned / Disconnected Components

**Investigated (2026-08-16), full agent report with file:line citations on file in the session
transcript; findings and decisions below are final for this closure.**

| Component | Decision | Justification |
|---|---|---|
| `FrameworkDetector` | **ADVISORY** | `.frameworks` reaches only a DEBUG-only log line (`service.py:1223`, gated behind `isEnabledFor(DEBUG)`) and a pass-through API response field. Never gates a decision. Correctly informational. |
| `RepositorySegmenter` | **INTERNAL_SUPPORT** | Materially gates evidence-fallback scope in `evidence_validator.py` (live) and sets `ContextResolutionResult.repository_segment` (`service.py:702-724`, live) — real, wired, but correctly used as internal plumbing with no independent entry point needed. |
| `PRHLAnalyzer` | **DEFERRED** (reasoning updated post-closure) | Confirmed zero production callers; `domain.execution_ledger.predicted_response` field exists but nothing assigns it anywhere in `src/`. Originally deferred because generation itself was unreachable — **this closure fixes that**, so a home now exists. Still explicitly NOT wired in this closure: PRHL is a new capability addition, not an architectural-gap fix, and is outside this closure's narrow Verification/Recovery/DI authorization. Flagged as the natural next candidate once this closure ships. |
| `MultiHopOrchestrator` | **DEFERRED** | Self-documented Phase 7 spike, explicitly not meant to replace the stable pipeline until independently evaluated. Zero production callers, correctly so. |
| `DecoratorGraph` | **DEFERRED** | Sole real consumer is `MultiHopOrchestrator`; classification tracks its consumer's — not independently dead, just transitively unreachable pending that spike's promotion. |
| `CandidateFileSelector.callers_of` / `.transitive_callers_of` | **REMOVE** | Confidently dead: zero production callers, explicitly textually superseded by `locality_filtered_callers_of_name` (`locality.py:185-199`), built specifically because this method's underlying `SymbolIndex.find_by_name`-based lookup caused a measured, real production defect (a bare "New" query matched 159 symbols → 156 candidate files across 156 unrelated subsystems, real Consul, 2026-08-11). Leaving it risks a future caller reintroducing an already-fixed bug. **Implemented this closure** — see §41. |
| `CandidateFileSelector.impacted_files` | **DEFERRED**, not REMOVE | Wraps `DependencyGraph.impacted_by` (import-graph BFS), which has no equivalent name-disambiguation defect. Unused but not broken or superseded — a legitimate future "blast radius" capability. Left as-is. |
| Task-type budget ceiling (`_BUDGET_TIER_BY_TASK_TYPE`, `budget_manager.py`) | **CONNECT** | Real, calibrated-against-real-Consul-data gap: `context_package.py`'s route already computes `retrieval_task_type` (line 110, for `ranking_profile`) but never passes it as `task_type=` into `packager.package()` (confirmed: `budget_manager.py:103` itself documents `task_type=None` as the current universal default). A one-line fix connects an already-computed value to its already-built, already-tested consumer. **Implemented this closure** — see §41. |
| Feature-flagged experimental paths (`enable_subsystem_localization`, `enable_ranked_seed_selection`, `enable_anchor_classification`, `enable_confidence_propagation`, `enable_multi_axis_decomposition`) | **DEFERRED** (all 5, as a group) | Each is explicitly documented in `service.py`'s own docstring as "an explicit, isolated A/B toggle for one specific experiment... do not default it to True without the experiment's own success criteria being met." Correctly unreachable from any HTTP route (confirmed: `CreateCodeIntelligenceRequest` has no field for any of them). Textbook correct deferral, not a gap. |
| `ContextUnderstandingAnalyzer` (SLM-2) | **ADVISORY** (confirmed, not just assumed) | Runs strictly after selection is finalized (`packager.py:73-90`); output only ever populates `ContextPackage.understanding_notes`, read nowhere else in `src/`; failures are caught and swallowed, never fatal. Functioning exactly as designed. |
| `TelemetryCollector`/telemetry | **DEFERRED** | Real, tested, deliberately opt-in observability infra, currently correctly serving offline CI/benchmark scripts (`scripts/*_check.py`) and `production_gate.py`. Zero production (`src/interfaces/`) callers. Wiring it into the live singleton service needs its own design decision (event storage/retention for a long-lived process) — out of scope for this closure, which already adds its own, narrower observability via the Execution Ledger (§24). |
| DRP subsystem (TF-IDF/PMI/taxonomy) | **CONNECT** (decided, part of P0.8) | Becomes the Recovery alternate strategy — real production consumer, not advisory. |

## 27. Classification Responsibilities

**Investigated (2026-08-16).** Verdict: **genuinely 4 distinct questions, no consolidation
warranted.**

| Classifier | Question answered | Real callers | Purpose |
|---|---|---|---|
| `DomainClassifier` | "Which codebase area does this concern?" | `contracts/manager.py:50` only | Corroborates SLM-1's own `domain` claim for confidence scoring |
| `TaskClassifier` | "What kind of change is requested?" | `contracts/manager.py:51` (corroboration) + `service.py`/`context_package.py` (hint into `classify_retrieval_task`) | Dual role, both legitimate and distinct |
| `RepositoryScopeClassifier` | "Does this need whole-repo evidence, and is it debugging or documentation?" | `service.py:201,389,439-451,697` — real, behavior-changing (gates evidence-contract fallback) | Resolution-time decision, not confidence scoring |
| `classify_retrieval_task` | "Which of 8 retrieval-tuning task types should drive depth/ranking/(now budget)?" | `service.py:391` (depth), `context_package.py:110-113` (ranking profile), now also budget tier (§26 CONNECT fix) | Composes the other 3 classifiers' outputs as documented, explicit hints — not a re-implementation |

`task_profile.py`'s own docstring confirms this is deliberate composition ("reuses their outputs as
hints rather than replacing or modifying them"), not accidental duplication. No action needed —
**VERIFIED, no consolidation.**

## 28. Advisory / Experimental Components

Resolved as part of §26: `FrameworkDetector` and `ContextUnderstandingAnalyzer` (SLM-2) both
confirmed correctly ADVISORY, functioning exactly as designed — investigated, not assumed. PRHL,
`MultiHopOrchestrator`/`DecoratorGraph`, and the 5 experimental flags all confirmed correctly
DEFERRED with concrete reasoning per component, not left ambiguous.

## 29. Architecture Tests

| Test category | Status | Location | Count |
|---|---|---|---|
| Layer tests | **VERIFIED** | `tests/execution/test_verification.py`, existing per-layer suites (unchanged) | 5 new + all existing |
| Contract tests | **VERIFIED** | `domain/verification_result.py`/`domain/execution_result.py` exercised by every orchestrator test | via §21 tests |
| Connection tests | **VERIFIED** | `tests/application/test_execute_use_case.py`, `tests/interfaces/test_grounded_execution_route.py` | 11 |
| Dependency-direction tests | **VERIFIED** | `tests/code_intelligence/test_phase6_boundary.py` (extended) | 1 new |
| DI tests | **VERIFIED** | `test_production_composition_root_constructs_orchestrator_via_di` | 1 (covers DI-01/02/10) |
| Control-flow tests | **VERIFIED** | `tests/application/test_execute_use_case.py` | 7 (normal, entities-default, Case B recovery, Case C recovery, bound respected, DI, error propagation) |
| Verification tests | **VERIFIED** | `tests/execution/test_verification.py` | 5 |
| Recovery tests | **VERIFIED** | within `tests/application/test_execute_use_case.py` | 3 (Case B, Case C+exhaustion, bound) |
| End-to-end tests | **VERIFIED** | `tests/interfaces/test_grounded_execution_route.py` | 4 |
| **Full suite regression** | **VERIFIED** | whole repo | **1008/1008 passing.** 992 baseline + 5 (verification) − 2 (removed dead-method tests) + 1 (subclass-budget) + 1 (boundary) + 7 (orchestrator) + 4 (route) = 1008. |

## 30. Contract Tests

Tracked within §29; not duplicated.

## 31. Integration / End-to-End Tests

Tracked within §29; not duplicated.

## 32. Layer Acceptance Criteria (per-layer, not generic)

| Layer | Purpose | Inputs | Outputs | Dependencies | Consumers | Failure behavior | Acceptance criteria | Status |
|---|---|---|---|---|---|---|---|---|
| Query Understanding | Produce structured, corroborated intent | `raw_request` | `UserIntent` | SLM-1, classifiers, `ConfidenceEngine` | Orchestrator (new), `contracts.py` route | `IntentExtractionError` on schema failure | Entities preserved to retrieval (this closure); task/domain/constraints/confidence preservation explicitly OUT of scope (documented, not silently dropped — see §39) | NOT_STARTED |
| Workspace | Establish repo scope, produce metadata | `workspace_root` | `WorkspaceMetadata` | git/language/structure analyzers | `contracts/manager.py`, `code_intelligence/service.py` (own independent scan — see §7) | `WorkspacePathError`/`WorkspaceNotAllowedError` | Unchanged this closure | N/A (no change) |
| Code Intelligence | Repository graphs/indices | `ScannedFile` list | `CodeIntelligenceIndex` | language analyzers | `ContextResolver`, DRP | Explicit `unsupported_languages`/`parse_error_files` surfacing (already built) | Unchanged this closure | N/A (no change) |
| Retrieval | Candidate generation + expansion | `target_names`, index | `ContextResolutionResult` | `ReferenceResolver`, `locality.py` | `ContextPackager`, orchestrator | Empty-candidate internal fallback (existing) | `target_names` defaults from `contract.intent.entities` (this closure); expansion bounds fixed for subclasses (§21) | IN_PROGRESS (design), NOT_STARTED (code) |
| Evidence | Coverage-of-category checking | `ContextResolutionResult`, task type | `evidence_categories_missing` | `evidence_validator.py` | Orchestrator (new — was nobody) | Reported, not gated (until this closure) | `evidence_categories_missing` gates a real Recovery decision | NOT_STARTED |
| Ranking | Score/order candidates | `ContextResolutionResult` | `list[RankedFile]` | none (pure) | `ContextBudgetManager` | N/A | Unchanged this closure | N/A (no change) |
| Context | Budget-bounded packaging | `list[RankedFile]` | `ContextPackage` | `ContextBudgetManager`, `SymbolRangeCompressor` | Orchestrator (new — was nobody) | `excluded_file_count` honestly reported (existing) | Unchanged this closure — gets a real caller | N/A (no change) |
| Goal Composition | Assemble final prompt | `Contract`, `ContextPackage`, `ContextResolutionResult` | prompt string | none | `FinalGenerationRunner` | N/A | Unchanged — gets a real caller | N/A (no change) |
| Generation | Call the LLM, no forced schema | prompt | `Artifact` | `LiteLLMClient` | Orchestrator (new — was nobody) | `LLMInvocationError` after retries | Reachable from the canonical entry point | NOT_STARTED |
| Verification | Deterministic grounding check | `Artifact`, `ContextPackage`, `ContextResolutionResult` | `GroundingVerificationResult` | none (pure) | Orchestrator | N/A (never throws — always returns a structured result) | Evidence-based, bounded, no semantic claims; explicit `contradictions_checked=False` | NOT_STARTED |
| Recovery | Bounded alternate-strategy retry | `GroundingVerificationResult` or `evidence_categories_missing` | retry decision + strategy | Orchestrator's own existing sub-calls only | Orchestrator (self) | Exhaustion → explicit low-confidence result | `MAX_RECOVERY_ATTEMPTS=1`, deterministic strategy (`"drp"`), no internals touched | NOT_STARTED |
| DI | Construct production graph | Settings | wired service graph | none | `create_app()` | N/A | See §22 | IN_PROGRESS (design) |

## 33. Connection Acceptance Criteria (C1–C10 per major connection)

| Connection | C1 reaches consumer | C2 no discard | C3 explicit transform | C4 provenance | C5 failure preserved | C6 confidence preserved | C7 no internals reach-in | C8 no side-channel | C9 tested | C10 DI-supplied |
|---|---|---|---|---|---|---|---|---|---|---|
| QueryUnderstanding → Retrieval (entities) | **PASS** | PASS | PASS (`target_names or list(entities)`) | N/A | N/A | N/A | PASS (unchanged) | PASS | **PASS** | PASS |
| Context → Generation | **PASS** | PASS | PASS (`ContextGoalComposer` unchanged, now reachable) | PASS | N/A | N/A | PASS | PASS | **PASS** | PASS |
| Generation → Verification | **PASS** | N/A (new) | PASS | PASS (`Artifact.metadata` carries `contract_id`/`context_package_id`) | PASS (`GroundingVerificationResult`) | N/A | PASS (pure function, no internals) | PASS | **PASS** | N/A (pure function, no DI needed) |
| Verification → Recovery | **PASS** | N/A (new) | PASS | PASS | PASS (structured `status`, not a boolean) | N/A | PASS (re-enters via orchestrator's own existing calls only) | PASS | **PASS** | PASS |
| Recovery → Retrieval (re-entry) | **PASS** | N/A | PASS (`resolver_strategy="drp"`, hardcoded literal) | N/A | N/A | N/A | PASS — grep-confirmed zero imports of `ContextResolver`/`CallGraph`/`SymbolIndex`/`locality` | PASS | **PASS** | PASS |
| Orchestrator → Execution Ledger | **PASS** | N/A | PASS | PASS (contract_id, resolution/package ids in entry + metadata) | PASS (`execution_status`, distinct from grounding `final_status`) | N/A | PASS | PASS | **PASS** | PASS |

All 6 connections targeted by this closure: **PASS on every column.** (Connections unrelated to this closure — A through F, H/I/J's non-existence resolved by this closure itself — retain the discovery report's own baseline status, not re-litigated here.)

## 34. Control-Flow Acceptance Criteria

| Path | Status | Test |
|---|---|---|
| Normal (Query→Understanding→Retrieval→Evidence→Ranking→Context→Generation→Verification→Success) | **VERIFIED** | `test_normal_path_reaches_generation_and_verification`, `test_grounded_execution_full_pipeline_reaches_generated_verified_answer` |
| Empty retrieval (existing internal fallback) | **VERIFIED unchanged** | Pre-existing `evidence_fallback.py`/lexical-probe tests, all still green — this closure adds nothing here and confirms it wasn't broken |
| Insufficient evidence → Recovery → (in this test) success | **VERIFIED** | `test_insufficient_evidence_triggers_one_recovery_attempt_with_drp_strategy` |
| Verification failure → Recovery → (in this test) still low_confidence, exhaustion honored | **VERIFIED** | `test_unsupported_reference_triggers_recovery_and_exhausts_to_low_confidence` |
| Recovery exhaustion → explicit low-confidence state, never silent success | **VERIFIED** | Same test — asserts `final_status == "low_confidence"` and `entry.metadata["final_status"] == "low_confidence"` in the persisted ledger entry too |

## 35. DI Acceptance Criteria (DI-FA-01 … DI-FA-12)

| ID | Criterion | Status | Evidence |
|---|---|---|---|
| DI-FA-01 | One identifiable composition root | **PASS** | `create_app()` remains the only composition root; `ArcfExecutionOrchestrator` constructed there, not in a second location |
| DI-FA-02 | Canonical orchestrator constructed through DI | **PASS** | `test_production_composition_root_constructs_orchestrator_via_di` |
| DI-FA-03 | No unnecessary manual construction | **PASS** | Orchestrator's own dependencies (`code_intelligence_service`, `context_packager`, `generation_runner`, `execution_ledger_store`, `cost_estimator`) are all constructor-injected, none `new`'d internally |
| DI-FA-04 | DI respects layer dependency direction | **PASS** | `test_application_orchestrator_does_not_import_code_intelligence_internals` + `test_no_reverse_dependency_from_code_intelligence_or_context_onto_application` (both real, permanent tests — not just a manual grep, see the correction note in §22) |
| DI-FA-05 | DI is not an uncontrolled service locator | **PASS** | New `get_arcf_orchestrator` accessor follows the exact existing `dependencies.py` pattern, no scattered `request.app.state.X` reads introduced |
| DI-FA-06 | Classic/DRP suppliable through intended abstraction | **N/A by design** | Call-time parameter, not construction-time injection — see §22 decision, explicitly not "mechanically converted" per your own instruction §42 |
| DI-FA-07 | Verification/Recovery testable via injection | **PASS** | `tests/application/test_execute_use_case.py` constructs the orchestrator directly with real (non-FastAPI) sub-components, faking only `litellm.acompletion` |
| DI-FA-08 | Complete grounded pipeline constructible via DI | **PASS** | Same test file's `_build_pipeline()` helper, plus the real `create_app()` DI test |
| DI-FA-09 | Required dependencies replaceable in tests | **PASS** | Same convention as every other route test in this codebase (monkeypatch the LLM edge) — no new mocking infrastructure invented, per your instruction §45 |
| DI-FA-10 | No prohibited circular dependency | **PASS** | Same evidence as DI-FA-04 |
| DI-FA-11 | Lifecycle/ownership documented | **PASS** | §22 of this document; orchestrator is an app-lifetime singleton, matching every other service; `max_recovery_attempts` now flows `Settings.arcf_max_recovery_attempts` → `create_app()` → orchestrator, same ownership pattern as `default_model` |
| DI-FA-12 | DI test-enforced where practical | **PASS** | `test_production_composition_root_constructs_orchestrator_via_di` runs the real composition root end-to-end |

## 36. Final Architecture Acceptance Criteria (FA-01 … FA-24)

All 24 tracked; see the discovery report's draft matrix for the 20 pre-closure statuses and the new
FA-21–24 (DI-specific) below. Final values filled in §38 sweep, not before real implementation.

| ID | Criterion | Pre-closure | **Final** | Evidence |
|---|---|---|---|---|
| FA-01 | Single canonical execution path | FAIL | **PASS** | `POST /contracts/{id}/grounded-execution` — one call, contract_id in, verified answer out |
| FA-02 | No client-driven internal orchestration | FAIL | **PASS** | Client no longer drives code-intelligence→context-package→(nothing) by hand |
| FA-03 | Complete information propagation | FAIL | **PASS for what this closure targeted** | Entities→retrieval, evidence-missing→recovery decision. `UserIntent.task/domain/constraints/confidence` remain undelivered — explicitly DEFERRED (§39), not silently dropped |
| FA-04 | No accidental disconnected production capability | FAIL | **PASS** | Every §26 component explicitly classified, none left ambiguous |
| FA-05 | Clear ownership | Mostly pass | **PASS** | Unchanged, re-confirmed |
| FA-06 | Valid dependency direction | Pass, test too narrow | **PASS, now properly tested** | §20 investigation + new real boundary test |
| FA-07 | Evidence affects control flow | FAIL | **PASS** | `evidence_categories_missing` now gates the pre-generation recovery decision |
| FA-08 | Verification executes | FAIL (didn't exist) | **PASS** | `verify_grounding()` runs on every orchestrator call |
| FA-09 | Recovery is bounded | N/A | **PASS** | `MAX_RECOVERY_ATTEMPTS = 1`, single shared counter, test-proven never exceeded |
| FA-10 | Recovery is deterministic | N/A | **PASS** | Hardcoded `strategy = "drp"`, no LLM decision anywhere in the loop |
| FA-11 | Recovery uses orchestration boundary | N/A | **PASS** | Grep-confirmed zero internal-module imports in the orchestrator |
| FA-12 | DRP is reachable | FAIL | **PASS** | DRP now has a real, tested, reachable production consumer (Recovery) |
| FA-13 | Final failure is explicit | N/A | **PASS** | `final_status="low_confidence"` on exhaustion, never silently `"success"` |
| FA-14 | Confidence semantics unambiguous | FAIL (pre-existing) | **DEFERRED** | New contract adds `resolution_confidence_source` (provenance the old field lacked); the old field's own dual-formula conflation is unfixed by design (§19/§39 — zero current consumers, outside this closure's dependency chain) |
| FA-15 | Expansion is bounded | FAIL (`_expand_subclasses`) | **PASS** | Fixed + regression-tested |
| FA-16 | Canonical execution result exists | FAIL | **PASS** | `ArcfExecutionResult` |
| FA-17 | Execution is observable | Partial | **PASS** | Real ledger entry per run, fetchable via existing `GET /executions/{id}` |
| FA-18 | Architecture is test-enforced | Partial | **PASS** | §29 — every category covered |
| FA-19 | End-to-end execution works | FAIL | **PASS** | `test_grounded_execution_full_pipeline_reaches_generated_verified_answer` |
| FA-20 | Existing supported behavior does not regress | N/A | **PASS** | 1008/1008; only 2 dead-method tests removed, matching the REMOVE decision |
| FA-21 | DI is architecturally integrated | N/A | **PASS** | §35 |
| FA-22 | DI does not bypass architecture | N/A | **PASS** | §35 DI-FA-04/06 |
| FA-23 | DI supports testability | N/A | **PASS** | §35 DI-FA-07/09 |
| FA-24 | Final architecture internally consistent (code/contracts/DI/tests/diagram/docs agree) | N/A | **PASS** | This document + §37 diagram describe the same, now-real system |

**23 of 24 criteria: PASS. One (FA-14) explicitly DEFERRED with reasoning, not silently dropped.**

## 37. Final Architecture Diagram

Produced from the actual implemented code (verified against real imports/call chains above), not an
aspirational design.

**Diagram correction (2026-08-17, independent verification report G-new-6):** the prior version of
this diagram drew `Application Orchestrator --> POST /contracts --> Query Understanding` as one live
call chain. That is not what the code does: `POST /contracts` (Query Understanding / SLM-1 / the
classifiers) is a **separate, prior HTTP request** the client makes to create a contract, decoupled
in time from grounded execution -- the orchestrator never calls it, imports its route, or depends on
it running in the same request. The orchestrator only ever receives an already-existing
`contract_id` and looks it up via `contract_manager.get_contract()`. The diagram also never named the
actual entry-point route at all. Both are fixed below; nothing about the *code* changed to produce
this correction, only the diagram.

```
Client
  |
  |  (1) POST /contracts  -- separate, PRIOR request; not called by the orchestrator
  v
Query Understanding (SLM-1 + classifiers) --> LivingContract persisted (SqliteContractStore)
  |
  |  (2) POST /contracts/{contract_id}/grounded-execution  -- the actual canonical entry point
  |      (interfaces/api/routes/grounded_execution.py)
  v
ARCF Composition Root (interfaces/api/app.py: create_app)
            |
            v
Application Orchestrator (application/execute_use_case.py: ArcfExecutionOrchestrator)
            |
            v
   contract_manager.get_contract(contract_id)  -->  the LivingContract created in step (1)
            |
            v
   attach_code_intelligence(target_names or contract.intent.entities, resolver_strategy)
            |
        +---+---+
        |       |
        v       v
    Classic    DRP            <-- both reachable now: Classic by default,
    resolver  resolver            DRP as Recovery's own alternate strategy
        |       |
        +---+---+
            |
            v
    Evidence check (evidence_categories_missing)
            |
     +------+-------+
     | sufficient    | insufficient (Case B)
     v               v
     |          Recovery: attempt+=1, strategy="drp", loop back to attach_code_intelligence
     v
  ContextPackager.package()  (Ranking -> Budget/Compression, unchanged)
            |
            v
  ContextGoalComposer.compose() -> FinalGenerationRunner.generate()
            |
            v
        Artifact
            |
            v
     verify_grounding()  (deterministic: evidence check + file-reference check)
            |
     +------+-------+
     | sufficient    | insufficient/unsupported-refs (Case C)
     v               v
     |          Recovery: attempt+=1 (if not already used), strategy="drp", loop back
     v
  ArcfExecutionResult (artifact, verification, recovery_attempts, strategy_used,
                        final_status, resolution_confidence(+source), llm_responses)
            |
            v
  ExecutionLedgerEntry  -->  ExecutionLedgerStore (existing, now has a real writer)
            |
            v
  GroundedExecutionResponse  -->  client


Separate, unchanged: Secure Fast Path
POST /api/v1/execute  -->  raw prompt  -->  LiteLLMClient.complete()  -->  ExecuteResponse
(no contract, no retrieval, no verification -- unrelated to the pipeline above,
 explicitly not implied to carry the same grounding guarantees, per P12)
```

## 38. Final Closure Verification (6 sweeps)

**Sweep 1 — Every layer:** every active layer touched by this closure (Generation, Verification,
Recovery, the new Orchestrator, DI) has a documented responsibility/contract/consumer and passing
acceptance criteria (§32). Layers not touched (Ranking, Context Construction, Code Intelligence)
were re-confirmed unchanged via `git diff` and their own still-passing existing test suites.

**Sweep 2 — Every connection:** the 6 connections this closure targeted (§33) all PASS on every one
of C1–C10. No required information is silently discarded (`evidence_categories_missing` and
`entities` both now have real consumers). Provenance (`resolution_confidence_source`,
`Artifact.metadata`, ledger `metadata`) is preserved end to end.

**Sweep 3 — DI:** `create_app()` (the one composition root) constructs the orchestrator with real
injected dependencies; verified via direct test (`test_production_composition_root_constructs_
orchestrator_via_di`), not just code reading.

**Sweep 4 — Control flow:** all 5 named paths (normal, empty-retrieval, insufficient-evidence,
verification-failure, exhaustion) are real, passing, code-verified tests (§34) — not asserted from
reading the code alone.

**Sweep 5 — Dependency direction:** real imports grep-confirmed in both directions (§20); the
orchestrator itself confirmed to import zero code-intelligence internals; new boundary test locks
this in for regression.

**Sweep 6 — Final architecture:** code (this branch), contracts (`domain/verification_result.py`,
`domain/execution_result.py`), DI (`app.py`/`dependencies.py`), tests (16 net new, 1008/1008 total),
diagram (§37), and this checklist all describe the same system — cross-checked by re-running the
full suite after every implementation step (§40), not just at the end.

**All 6 sweeps: PASS.**

## 39. Remaining Genuine Gaps (explicitly out of scope for this closure, with reasons)

**Revised 2026-08-17 after the adversarial re-verification (§41.1) found this exact table had
silently dropped two of the discovery report's own 19 numbered gaps (G15, G18) — neither fixed nor
listed here, just absent. Both are now explicitly entered below, corrected rather than repeated.**

| Gap | Why deferred |
|---|---|
| `UserIntent.task`/`.domain`/`.constraints`/`.assumptions`/`.confidence` never read downstream (task/domain now independently re-derived **4×**, not 3× — this closure's own orchestrator added a 4th site, `execute_use_case.py`, without consolidating the existing 3) | Real duplication (G4 in discovery report), but fixing it means consolidating 4 independent classifier call sites across 4 files with no shared abstraction today — a genuinely separate, larger refactor than this closure's dependency chain requires. Not blocking Verification/Recovery/DI. Correction (2026-08-17): the count itself was stale here; now accurate. |
| `ContextResolutionResult.confidence` written by 2 different formulas with no provenance marker | Real bug (G5). **Correction (2026-08-17)**: the field now DOES have a real consumer (`ArcfExecutionResult.resolution_confidence`, this closure's own code) — the original "zero current consumers" justification here was wrong as of this closure's own later work, not just stale. The deferral decision itself is still sound (fixing the two-formula conflation is separate and riskier than reading the value); see §19's own corrected entry for the full account. |
| Workspace/Code Intelligence double-scan (§7) | Real inefficiency, not a correctness gap; touching it risks an unrelated boundary for no closure benefit. |
| DRP's `ContextResolutionResult.confidence` (margin-based) still not consumed by anything even after DRP becomes reachable via Recovery | Recovery's own decision logic uses `GroundingVerificationResult`, not this field — DRP becoming reachable doesn't require this field to be read. Flagged for a future confidence-contract cleanup. |
| `RelevanceRanker`'s per-component score breakdown not recoverable from output (RK-7) | Explainability gap, not a control-flow/connection gap — explicitly not required for FA-08/09/10/11 (Verification/Recovery). |
| `evidence_tier` excluded from `RelevanceRanker`'s score, only affects `ContextBudgetManager`'s compression policy (this is G17 from the discovery report — not previously entered here by number, added 2026-08-17) | Intentional, documented, unchanged design choice (§12) — a real property of the ranking architecture, not a defect this closure introduced or is required to fix. |
| **G15 (partial)** — `code_intelligence/drp/drp_resolver.py`'s 3 `FileReference` construction sites still leave `origin_stage=None` | The `evidence_validator.py` half of G15 WAS fixed 2026-08-17 (§41.1). DRP's 3 sites were not: they'd need a new `OriginStage` enum value (DRP's TF-IDF/subsystem-taxonomy resolution isn't symbol-scoped like `AST_DIRECT`/`SCOPED_GRAPH_EXPANSION`, nor a glob-fallback like `EVIDENCE_FALLBACK_MATCH`/`RAW_STRING_FALLBACK` — it's genuinely a fourth mechanism), which is a real design decision affecting a widely-shared enum, not a quick patch. Previously silently absent from this table entirely (found 2026-08-17, not the original work) — now explicitly tracked, not fixed. |
| **G18** — persistence calls unguarded by try/except across the codebase (`contracts/manager.py`, `code_intelligence/service.py`, `workspace/service.py`, `interfaces/api/routes/comparison.py`) | Pre-existing, codebase-wide pattern, far outside this closure's scope to fix wholesale. **This closure's own new ledger-write call site was fixed** (`_save_ledger_entry` now catches/logs rather than propagates, §24) since leaving new code repeat a known anti-pattern once flagged would be indefensible — but the systemic pattern elsewhere remains untouched. Previously silently absent from this table (found 2026-08-17) — now explicitly tracked. |
| **G14 (partial)** — `comparison_store`/`POST /api/v1/compare` remains starved of real input | Only the execution-ledger half of the original G14 finding was in this closure's scope; the comparison-API half was never touched. Previously stated as fully "closed" in §24 — corrected 2026-08-17, see §24's own entry. |
| Orphaned components not resolved to CONNECT (only DRP is) | §26 investigation complete — every component explicitly classified CONNECT/ADVISORY/INTERNAL_SUPPORT/DEFERRED/REMOVE with real evidence, not left ambiguous. Nothing further to fill in here. |

## 40. Implementation Log

Chronological record of actual work on this branch, for cross-session continuity. Not yet
committed to git — will commit in logical groups once a coherent chunk is verified, per project
convention (see arcf/CHECKLIST.md's own "Bugs fixed on the same branch, same flow" discipline).

| Date | What | Files | Tests after |
|---|---|---|---|
| 2026-08-16 | Branch created | `feature/architecture-closure` off `Base` `5b7fa5c` | 992/992 (baseline) |
| 2026-08-16 | `GroundingVerificationResult` contract + `verify_grounding()` pure function | `domain/verification_result.py` (new), `execution/verification.py` (new), `tests/execution/test_verification.py` (new, 5 tests) | 997/997 |
| 2026-08-16 | Entities-default fix (§6) | `code_intelligence/service.py`, `interfaces/api/schemas.py` | no regressions |
| 2026-08-16 | Task-type budget ceiling CONNECT fix (§26) | `interfaces/api/routes/context_package.py` (thread `task_type=retrieval_task_type` into `packager.package()`) | no regressions |
| 2026-08-16 | `CandidateFileSelector.callers_of`/`.transitive_callers_of` REMOVE (§26) | `code_intelligence/candidate_selector.py` (methods removed, docstring updated); 3 test files updated to use a local `_caller_files_of` helper instead (`test_engine.py`, `test_language_agnostic.py`, `test_multi_language_repository_validation.py`) | 995/995 (992 baseline − 2 removed dead-method tests + 5 new verification tests) |
| 2026-08-16 | `_expand_subclasses` token-budget fix (G16, §21) | `code_intelligence/context_resolver.py`; new test in `tests/code_intelligence/test_context_resolver.py` | 996/996 |
| 2026-08-16 | Real architecture boundary test (§20) | `tests/code_intelligence/test_phase6_boundary.py` extended | 997/997 |
| 2026-08-16 | `ArcfExecutionOrchestrator` + canonical result + generation/verification wiring + DI + new route (§1/§15/§16/§17/§22/§23/§24/§25) | New: `application/execute_use_case.py`, `domain/execution_result.py`, `domain/verification_result.py`, `execution/verification.py`, `interfaces/api/routes/grounded_execution.py`. Changed: `interfaces/api/app.py`, `interfaces/api/dependencies.py`, `interfaces/api/schemas.py`, `application/__init__.py` (docstring) | 1004/1004 after DI wiring (before new tests) |
| 2026-08-16 | Orchestrator + route + DI test suites (§29) | New: `tests/application/__init__.py`, `tests/application/test_execute_use_case.py` (7 tests), `tests/interfaces/test_grounded_execution_route.py` (4 tests) | 1008/1008 |
| 2026-08-17 | DI correction pass (§22): config ownership + circular-dependency regression tests, prompted by a direct "did you cover ARCF DI?" re-check rather than new investigation | `shared/config.py` (+`arcf_max_recovery_attempts`), `interfaces/api/app.py` (thread it through), `tests/code_intelligence/test_phase6_boundary.py` (+2 tests), `tests/application/test_execute_use_case.py` (+1 test) | **1011/1011 — final** |

### Full file list (this branch, uncommitted)

**New files:**
```
docs/ARCF_ARCHITECTURE_AUDIT_DISCOVERY_2026-08-16.md
docs/ARCF_ARCHITECTURE_CLOSURE_CHECKLIST_2026-08-16.md
docs/ARCF_ARCHITECTURE_CLOSURE_PLAN_2026-08-16.md
src/application/execute_use_case.py
src/domain/execution_result.py
src/domain/verification_result.py
src/execution/verification.py
src/interfaces/api/routes/grounded_execution.py
tests/application/__init__.py
tests/application/test_execute_use_case.py
tests/execution/test_verification.py
tests/interfaces/test_grounded_execution_route.py
```

**Modified files:**
```
CHECKLIST.md                                              (session tracker pointer only)
src/application/__init__.py                               (docstring only)
src/code_intelligence/candidate_selector.py                (REMOVE callers_of/transitive_callers_of)
src/code_intelligence/context_resolver.py                  (G16 budget fix)
src/code_intelligence/service.py                            (entities-default fix)
src/interfaces/api/app.py                                   (DI wiring)
src/interfaces/api/dependencies.py                           (new accessor)
src/interfaces/api/routes/context_package.py                 (budget-tier CONNECT fix)
src/interfaces/api/schemas.py                                 (new request/response models, relaxed target_names)
src/shared/config.py                                           (arcf_max_recovery_attempts setting)
src/context/evidence_validator.py                                (G15 origin_stage fix, 2026-08-17)
tests/code_intelligence/test_candidate_selector.py            (removed dead-method tests)
tests/code_intelligence/test_context_resolver.py               (new subclass-budget test + impacted_symbols cap test)
tests/code_intelligence/test_engine.py                          (helper replacing removed method)
tests/code_intelligence/test_language_agnostic.py                (helper replacing removed method)
tests/code_intelligence/test_multi_language_repository_validation.py (helper replacing removed method)
tests/code_intelligence/test_phase6_boundary.py                    (real boundary test + 2 DI/circular-dependency tests, 2026-08-17)
tests/context/test_evidence_validator.py                            (origin_stage regression test, 2026-08-17)
```

**Also modified 2026-08-17** (adversarial re-verification fixes, all already covered by §41.1's own
table, listed here for the file-inventory record): `src/execution/verification.py` (regex rewrite),
`src/application/execute_use_case.py` (exception handling + failure ledger), `src/interfaces/api/
routes/grounded_execution.py` (cost guardrail scaling + response exclusion), `tests/execution/
test_verification.py`, `tests/application/test_execute_use_case.py`, `tests/interfaces/
test_grounded_execution_route.py` — all already listed above as new files from the first pass, now
carrying their second round of changes too.

**Explicitly NOT touched** (verified via `git diff` — empty): `context/relevance_ranker.py`,
`context/packager.py`, `context/budget_manager.py`, `context/compressor.py`, `interfaces/api/routes/
execute.py`, `code_intelligence/reference_resolver.py`, `code_intelligence/locality.py`,
`code_intelligence/drp/*`, every language analyzer, `contracts/*` (other than being read from, not
modified), `execution/final_generation.py`, `execution/context_goal_composer.py`,
`execution/prhl.py`, `infrastructure/telemetry.py`, `infrastructure/production_gate.py`,
`infrastructure/execution_ledger_db.py`, `domain/execution_ledger.py`.

## 41. Active investigation/implementation task list (internal, mirrors the harness TaskList)

All items from the original build (contracts, entities default, subclass budget, generation wiring,
orchestrator, route, tests, sweeps, diagram, report) — **done**, see §40. Superseded by §41.1 below,
which is the actually-current work log.

## 41.1 — 2026-08-17 Adversarial Re-Verification Pass

Triggered by the user asking to check everything again "just to make sure every gap, issue
resolved" — not a request to re-summarize, a request to re-verify. Four independent agents were
launched with no access to this document's prior claims, each told to find bugs/discrepancies
adversarially, not confirm the work. This is the account of what they found and what was done about
each finding — kept as its own section rather than folded silently into the sections above, so the
fact that real issues existed after the first "CLOSURE COMPLETE" declaration stays visible.

### What was found

**Agent 1 (orchestrator/recovery bug hunt), 3 real bugs + 2 real gaps:**
1. `verify_grounding()`'s path-matching had multiple false negatives (backslash paths never
   extracted at all, extensionless files like `Dockerfile`/`Makefile` never extracted, bare
   filenames with no directory never extracted) and one false-positive-causing bug (`_paths_match`'s
   boundary-unaware `str.endswith` let a fabricated `utils.py` incorrectly match an unrelated real
   `database_utils.py`) and one false-positive source (case sensitivity).
2. **The serious one**: if an exception interrupts a recovery RETRY iteration — after attempt 0
   already made real, costed LLM calls — the entire ledger write was skipped (only happens after the
   loop exits normally) and that real spend simply vanished from the audit record. Reproduced
   directly by the agent with an instrumented run.
3. The cost-guardrail pre-flight check estimated against a short `raw_request` for one call, but the
   real pipeline can make up to 4 calls with a much larger real prompt — a materially worse
   imprecision than the `/context-package` precedent it claimed parity with, and completely
   untested (no test exercised a tight-budget rejection for this route at all).
4. `llm_responses` (raw content from every real LLM call, including discarded/hallucinating attempts
   and SLM-2's internal notes) was exposed verbatim in the client-facing HTTP response with no
   exclusion — an unintended byproduct of embedding the whole domain object, not a deliberate
   decision.
5. The headline Case-B recovery test (`test_insufficient_evidence_triggers_one_recovery_attempt_
   with_drp_strategy`) asserted `recovery_attempts`/`strategy_used`/`artifact is not None` but never
   `final_status`/`verification.status` — since the loop falls through to generation regardless of
   whether a retry actually fixed anything once attempts are exhausted, this test would have
   survived a real regression where DRP stopped resolving the evidence gap.

**Agent 2 (DI re-verification)**: everything CONFIRMED CORRECT, including a live `create_app()` run
as an independent sanity check. No new findings — this was the one agent that found nothing wrong,
which is itself useful signal that the DI correction from the first re-check (§22) actually landed.

**Agent 3 (inter-layer data-flow tracing)**: all 8 traced data items (raw_request, resolution.
confidence/source, evidence_categories_missing, the package→generation→verification chain,
final_status propagation, llm_responses accounting, the HTTP boundary, entities→target_names)
CONFIRMED CORRECT DATA FLOW. No bugs found.

**Agent 4 (gap-by-gap G1-G19 cross-check against current code)**, the most consequential findings:
- **G15** (`FileReference.origin_stage` left `None` on 2 production paths) — never fixed, never
  deferred, **never mentioned anywhere in this checklist**, despite this document's own §39 claiming
  to track "Remaining Genuine Gaps... explicitly out of scope, with reasons." It simply fell out of
  the process.
- **G18** (persistence calls unguarded by try/except) — same pattern: silently absent from tracking,
  and this closure's own new ledger-write call site (`execute_use_case.py`) reproduced the exact
  unguarded pattern without acknowledgment.
- **G16/FA-15**: the "VERIFIED"/"PASS" claim was only half true. The original fix bounded
  `_expand_subclasses`'s candidate-FILE loop; a SECOND loop in the same method (feeding
  `impacted_symbols`, which genuinely feeds `RelevanceRanker`'s scoring) remained fully unbounded and
  had zero test coverage.
- **G5**: this document's own stated reason for deferring the confidence dual-formula fix ("zero
  current consumers") was factually contradicted by this closure's own later code
  (`resolution_confidence=resolution.confidence` in `execute_use_case.py`, which does read that
  field). The deferral decision itself was still reasonable — the written justification for it
  wasn't accurate anymore.
- **G14**: closure claimed but overstated — only the execution-ledger-writer half of the original
  gap was addressed; the original gap description's second half (`comparison_store`/`Comparison
  API` starved of input) was never touched and never mentioned.
- **G4**: this closure's own new code added a 4th independent task-type re-derivation site while the
  tracking document still said "three times."
- File-inventory bookkeeping (§40's file lists, untouched-file claims, test counts) — **all verified
  accurate**, no discrepancies. The gap-tracking failures above were specifically about the 19
  numbered gaps, not the mechanical change-tracking, which held up.

### What was fixed in response

| Finding | Fix | Evidence |
|---|---|---|
| Verify-grounding false negatives/positives | Rewrote `execution/verification.py`'s extraction (backslash paths, extensionless allowlist, bare-filename allowlist) and matching (removed the boundary-unaware suffix match, added case-insensitivity) | `tests/execution/test_verification.py` grew from 5 to 11 tests, all passing, each targeting one specific found bug |
| Ledger loss on mid-recovery exception | `run()` now wraps the loop in `try/except Exception`, persisting a best-effort failure ledger entry (real accumulated spend, `execution_status` mapped from the exception type) before re-raising the original exception unchanged | `test_exception_during_recovery_retry_still_persists_real_spend_from_attempt_zero` — reproduces the exact scenario, confirms the entry now exists with `total_tokens > 0` |
| Cost guardrail imprecision | Pre-flight estimate now scales `assumed_completion_tokens` by the real worst-case call count (`2 * (arcf_max_recovery_attempts + 1)`) and uses a context-budget-sized proxy prompt instead of the short `raw_request` | `test_grounded_execution_cost_guardrail_rejects_tight_budget` — previously this route had zero test of this behavior at all |
| `llm_responses` HTTP exposure | `response_model_exclude={"result": {"llm_responses"}}` on the route — still real internally (cost accounting) and in the ledger, excluded only from the client-facing body | `test_grounded_execution_full_pipeline_reaches_generated_verified_answer` now also asserts `"llm_responses" not in result` |
| Weak Case-B test | Strengthened to assert `final_status == "success"` and `verification.status == SUFFICIENT` explicitly | Same test, now actually fails if a future regression breaks DRP recovery |
| G16 second unbounded loop | Added `_MAX_IMPACTED_SUBCLASS_SYMBOLS = 200` cap in `context_resolver.py` | New `test_wide_subclass_hierarchy_caps_impacted_symbols_count` (300-subclass fixture, confirms the cap holds) |
| G15 (partial) | `evidence_validator.py`'s `_to_file_reference` now sets `origin_stage=OriginStage.EVIDENCE_FALLBACK_MATCH`, matching `evidence_fallback.py`'s own convention for the same category of addition | New `test_expanded_candidates_carry_origin_stage` |
| G15 (DRP's 3 sites) | **Deliberately NOT fixed** — would need a new `OriginStage` enum value (DRP resolution isn't symbol-scoped or fallback-glob-matched, it's genuinely a third mechanism), a real design decision affecting a widely-shared enum, out of scope for a bug-fix pass. Documented here instead of silently dropped again. | — |
| G18 (systemic pattern) | **Deliberately NOT fixed globally** — unguarded persistence exists in `contracts/manager.py`, `code_intelligence/service.py`, `workspace/service.py`, `interfaces/api/routes/comparison.py`, all pre-existing and outside this closure's scope. **This closure's OWN new ledger-write call site was fixed** (`_save_ledger_entry` now catches and logs rather than propagates a store failure) since leaving the new code repeating a known anti-pattern, once flagged, would be indefensible. | `test_ledger_store_failure_does_not_crash_an_otherwise_successful_run` |
| G4/G5/G14/G17/G19 wording | Corrected in place in §19/§26/§39 below rather than left stale | This section + inline corrections |

**Test count**: 1011 → 1022 (11 net new: 6 verification, 1 ledger-loss regression, 1 PS-4
regression, 1 subclass-cap regression, 1 origin_stage regression, 1 cost-guardrail regression,
minus overlap — see §40 for the precise per-commit breakdown).

**The honest meta-finding**: both rounds of re-verification were triggered by the user asking again,
not by this session proactively re-checking its own prior "done" claims. Left alone, this document
would have shipped with "CLOSURE COMPLETE" over a real financial-audit bug, a still-half-unbounded
expansion path claimed fully fixed, and two of nineteen tracked gaps quietly missing from their own
tracking table. Worth stating plainly rather than smoothing over in the final report.


---

## 42. 2026-08-17 Implementation Pass — Closing the Independent Verification Report's Findings

**Trigger:** an independent, 10-agent verification pass (produced as
`ARCF_INDEPENDENT_VERIFICATION_REPORT_2026-08-17.md`, treating this checklist's own prior claims as a
*claim set to verify*, not evidence) found 7 new real gaps (`G-new-1` through `G-new-7`) plus real,
previously-undecided scope questions on 8 carried items (`G7`, `G9`, `G10`, `G11`, `G12`, plus two DI
inconsistencies and a diagram discrepancy). That report's own verdict was **PARTIALLY VERIFIED**, not
`VERIFIED COMPLETE`. This section records the implementation pass that closed those findings.

**Method, per-item:** locate the actual implementation → understand the existing contract → implement
the smallest architecturally correct fix → add/modify regression tests → run targeted tests → re-check
for adjacent bypasses. No code was "fixed" merely to make a specific reported example pass — every fix
below traces to a general mechanism, with regression tests covering multiple variants, not just the
one case the report happened to cite.

### G-new-1 — Cost guardrail worst-case accounting

**Fix:** traced the real call tree instead of guessing a corrected number. SLM-2 (`ContextUnderstandingAnalyzer`)
retries up to `DEFAULT_MAX_PARSE_RETRIES` (now a named constant in `context/understanding.py`, was a
bare default) times, each internally retried by `LiteLLMClient` up to `settings.max_retries` times
(`context/packager.py` swallows both `ContextUnderstandingError` and `LLMInvocationError`, so these
retries genuinely all can happen without aborting the pipeline). Generation's one unwrapped call adds
`settings.max_retries` more. `execute_use_case.py`'s own loop can reach packaging+generation up to
`(arcf_max_recovery_attempts + 1)` times. True worst case at this project's defaults:
`(2*3 + 3) * (1+1) = 18`, not the flat `4` the old formula assumed. `grounded_execution.py`'s guardrail
now derives `worst_case_calls` from these real settings/constants, and scales BOTH the proxy prompt
size AND assumed completion tokens by it (the old version only scaled completion tokens, pricing only
one call's worth of prompt against eighteen calls' worth of completion — an inconsistency in the
guardrail's own favor, not a documented choice).
**Tests:** `test_cost_guardrail_rejects_budget_the_undercounted_formula_would_have_passed`
(`tests/interfaces/test_grounded_execution_route.py`) — proves the fix changed real behavior, not just
a comment, by computing the OLD and NEW estimates directly and picking a budget between them.
**Status: RESOLVED.**

### G-new-2 — Absolute-path grounding blind spot

**Fix:** `execution/verification.py`'s extraction regexes had a negative lookbehind
(`(?<![\w/\\])`) whose purpose was to stop mid-token matches, but which also excluded every absolute
path (Unix `/...` and Windows `C:\...` both start with an excluded character). Added
`_ABSOLUTE_PATH_PATTERN`/`_ABSOLUTE_EXTENSIONLESS_PATTERN` — dedicated patterns with a corrected
lookbehind (`\w`/`/`/`\\`/`:`) that explicitly allow the root anchor to open a match.
`_paths_match`/`_normalize` needed no changes — matching already handled a real absolute reference to
a real packaged relative file correctly (via the existing `/`-boundary suffix rule); only extraction
was blind.
**Tests:** 9 new tests in `tests/execution/test_verification.py` covering supported/unsupported ×
Unix/Windows-drive × with/without intermediate directory segments × extensionless, plus a malformed-text
non-regression test and an explicit G17-regression guard. All 20 tests in the file pass (11 pre-existing
+ 9 new).
**Status: RESOLVED.**

### G-new-3 — `_expand_calls` unbounded growth

**Fix:** `context_resolver.py`'s `_expand_calls` wrote into the shared `impacted_symbols`
dict and `call_edges` list unconditionally, before the per-file token-budget gate, in both its
`caller_hops` and `callee_hops` loops — the same defect class G16 already fixed for
`_expand_subclasses`. Renamed `_MAX_IMPACTED_SUBCLASS_SYMBOLS` → `_MAX_IMPACTED_SYMBOLS` (it was never
really subclass-specific — it bounds one shared dict both mechanisms write into) and added
`_MAX_CALL_EDGES = 400`; both loops now check the shared budget before appending. **A third,
previously-unknown growth site was found by this fix's own regression test**: `_attach_call_site_symbols`'s
loop over module-level call sites (reached even when `caller_hops`/`callee_hops` are empty) was also
fully unbounded — fixed with the same shared cap.
**Tests:** `test_dense_caller_graph_caps_impacted_symbols_and_call_edges`,
`test_dense_callee_graph_caps_impacted_symbols_and_call_edges` (`tests/code_intelligence/test_context_resolver.py`)
— 500-caller / 500-callee fixtures stay bounded under 200/400 respectively.
**Status: RESOLVED**, including the self-discovered third site.

### G-new-4 — `ContextResolutionStore` durability

**Determination:** `Contract.context_resolution_id` is itself durably stored (`SqliteContractStore`),
and `POST /contracts/{id}/context-package` dereferences it as a matter of its own documented contract,
with no lifecycle caveat anywhere. `ContextResolutionStore`'s own prior docstring had already
identified this as the one place to fix "if a real deployment needs it to survive a restart" — without
fixing it. Determination: **YES**, this reference must survive a restart.
**Fix:** added `SqliteContextResolutionStore`, applying the exact same connect-per-call pattern already
used three other times in this codebase (`contract_store.py`, `execution_ledger_db.py`,
`comparison_store.py`) — not a new persistence mechanism. Wired into `create_app()` in place of the
in-memory store; new `Settings.context_resolution_store_path` config field. `InMemoryContextResolutionStore`
kept for zero-I/O tests.
**Tests:** `tests/infrastructure/test_context_resolution_store.py` (parametrized memory/sqlite +
restart-persistence test), plus `test_context_package_survives_a_process_restart`
(`tests/interfaces/test_context_package_route.py`) — a real end-to-end HTTP test using two independent
`create_app()` instances sharing only on-disk db paths, proving the exact dangling-reference scenario
the report found no longer occurs.
**Status: RESOLVED.**

### G-new-5 — Success-path ledger write asymmetry

**Fix:** `_persist_ledger_entry`'s entry CONSTRUCTION (the token/cost aggregation and
`ExecutionLedgerEntry(...)` call, not just the store `.save()`) previously sat outside any try/except —
asymmetric with the failure path's own hardening from the prior round. Now wrapped the same way: on any
exception, logs and returns without persisting, but the actual `result` already computed and about to
be returned to the caller is completely unaffected. Applied the SAME fix to `_persist_failure_ledger_entry`
too (item 20 of the report explicitly required a full execution-to-ledger re-audit): its construction was
equally unguarded, and since it runs inside `run()`'s own `except Exception as exc:` handler immediately
before `raise` re-raises `exc`, a second exception there would have replaced the real, original failure
reason instead of the original exception ever propagating — a genuine "inconsistent audit state" risk.
**Tests:** `test_ledger_entry_construction_failure_does_not_crash_a_successful_run`,
`test_ledger_entry_construction_failure_on_failure_path_preserves_original_exception`
(`tests/application/test_execute_use_case.py`) — both simulate a construction-time exception (not a
store-write failure, which was already tested) and confirm the real result/original exception survives.
**Status: RESOLVED.**

### G-new-6 — Architecture diagram discrepancies

**Fix:** corrected §37's diagram directly (no code changed to satisfy it) — replaced the misleading
`Application Orchestrator --> POST /contracts --> Query Understanding` single chain with an accurate
two-step picture: `POST /contracts` as a separate, prior client request, and the actual entry route
(`POST /contracts/{contract_id}/grounded-execution`) named explicitly, showing the orchestrator only
ever looks up an already-existing contract.
**Status: RESOLVED.**

### G-new-7 — Negative-path coverage

**Fix:** added the 3 specifically-named tests, each proving real behavior at the actual boundary, not
an internal exception in isolation:
- `test_grounded_execution_llm_invocation_error_propagates_as_502` — real HTTP 502 with real error detail.
- `test_case_b_evidence_still_missing_after_recovery_exhausts_to_low_confidence` — forces this via a
  controlled double on `attach_code_intelligence`, because **the natural real-world case is not reachable
  with the current DRP implementation**: `DrpResolver.resolve()` never sets `evidence_categories_missing`
  at all, so a real DRP retry always reports evidence as satisfied regardless of whether it genuinely
  resolved anything. This is itself a new, real, separate finding — the orchestrator's OWN exhaustion
  handling is correct (this test proves it), but end-to-end Case-B exhaustion is effectively unreachable
  today because of a gap in a different component. Tracked as **NEW-1** below, not silently fixed
  (fixing DRP's own evidence-category computation is a real design decision about what DRP can honestly
  claim about evidence sufficiency, out of scope for this pass).
- `test_grounded_execution_with_nonexistent_workspace_root_returns_400` — a provided-but-invalid path,
  distinct from the already-tested "no workspace at all" case.
**Status: RESOLVED** (all 3 tests added and passing); **NEW-1 tracked, not fixed** (see below).

### G7 — Circular-dependency guard scope

**Determination:** the acceptance criterion does require a genuinely architecture-wide check — a
hardcoded file list / blocklist fails exactly the kind of silent-bypass risk this whole closure exists
to prevent. **Fixed**, not just documented: `test_application_orchestrator_does_not_import_code_intelligence_internals`
now scans every `.py` file under `application/` (not one hardcoded file) against an ALLOWLIST of the
one legitimate import (`code_intelligence.service`), matching the reverse-direction test's own already-generic
approach.
**Status: RESOLVED.**

### DI — Inline classifier construction

**Determination:** `RepositoryScopeClassifier`/`TaskClassifier` are real architectural dependencies
(`TaskClassifier` is already DI-injected for `ExecutionContractManager` at the same composition root),
not local pure helpers exempt from the DI discipline — constructing fresh instances per loop iteration
inside the orchestrator was a genuine, if functionally harmless, inconsistency with "the composition
root remains the architectural construction boundary."
**Fix:** both are now constructor parameters on `ArcfExecutionOrchestrator` (defaulting to a fresh
instance only so direct-construction callers/tests keep working; the production composition root
always passes its own instances), constructed once in `create_app()`, no longer reconstructed inside
`run()`'s loop.
**Tests:** `test_classifiers_are_injected_by_composition_root_not_constructed_per_iteration`.
**Status: RESOLVED.**

### G10 — DRP `origin_stage` sites

**Determination:** none of the 4 existing `OriginStage` values honestly describe DRP's TF-IDF/subsystem-routing
mechanism (not a symbol lookup, graph traversal, or filename/glob match) — assigning one of them would
have been exactly the "arbitrary value to make the test pass" the instructions warned against.
**Fix:** added `OriginStage.DRP_SUBSYSTEM_ROUTING`, a genuinely new, honestly-described value, applied
uniformly across DRP's 3 `FileReference` construction sites (direct subsystem entry, within-subsystem
expansion, near-tied-subsystem corroboration) — same granularity `RAW_STRING_FALLBACK` already uses to
cover two distinct classic call sites under one value.
**Tests:** `test_candidate_files_are_tagged_with_drp_origin_stage`.
**Status: RESOLVED.**

### G9 — Confidence semantics

**Determination:** the underlying dual-formula conflation (classic's resolved/total hit rate vs. DRP's
subsystem-routing margin) is a real, deliberate, previously-documented deferral — collapsing it into
one formula, or splitting the field, would be a breaking contract change to every existing consumer,
correctly out of scope for a bug-fix pass. The one production consumer of the raw field
(`execute_use_case.py`, carrying it into `ArcfExecutionResult`) already tags provenance via
`resolution_confidence_source`, so no consumer today actually treats the two as interchangeable.
**Fix (the "define the two concepts, prevent interchangeable treatment" branch):** added a detailed,
unmissable docstring directly on `ContextResolutionResult.confidence`'s own field definition (not just
on the downstream result type that happens to consume it correctly), naming both formulas explicitly.
**Tests:** new `tests/domain/test_context_resolution_confidence_semantics.py` — 3 tests proving the
divergence concretely (classic confidence is exactly a resolved/total ratio; DRP confidence tracks
`routing.winning_confidence` and has no such ratio at all; a worked example showing equal numeric
values can come from unrelated formulas).
**Status: PARTIALLY RESOLVED** (honestly, matching the original framing) — provenance is now defined at
the field's own definition site and contract-tested, but the underlying two-formulas-one-field
conflation remains, by deliberate, documented choice.

### G11 — Persistence hardening scope

**Determination:** the closure's own acceptance criteria never required hardening ALL ARCF persistence
— only this closure's own new code paths. `_save_ledger_entry`'s own comment already stated this scope
boundary narrowly and explicitly; G-new-5 extended the identical scope boundary to the construction-time
guard, not a wider one.
**Status: RESOLVED** (scope boundary confirmed correct and explicitly documented, not silently
redefined in either direction).

### G12 — Task-type duplication

**Determination:** `classify_retrieval_task()` is already the single authoritative function — all 3
call sites (`execute_use_case.py`, `code_intelligence/service.py`, `interfaces/api/routes/context_package.py`)
call the SAME function, so there was never an algorithmic-drift risk, only a call-count one. Full
cross-component consolidation would require threading the computed value through
`ContextResolutionResult`/`Contract`'s durable, cross-request contract (the `/context-package` route is
a genuinely separate HTTP request, possibly after a restart) — a bigger decision this pass documents
rather than makes silently.
**Fix (the safely-consolidatable part):** within `execute_use_case.py`'s own `run()` loop, the value is
a pure function of `raw_request`, which never changes across that call's own recovery retry — was
recomputed every iteration for no reason; now cached after the first computation.
**Tests:** `test_task_type_classification_is_computed_once_per_run_not_per_retry` — proves the real fix
(a call-counted classifier) using the genuine Case-B retry scenario, not just an unchanged-outcome
assertion.
**Status: PARTIALLY RESOLVED** — the safely-fixable redundancy is fixed and proven; the cross-component
duplication remains, correctly identified as requiring a bigger, undocumented-here decision (see
options below).

**G12 — options for the cross-component duplication, if a future pass wants to close it fully:**
1. Add a `retrieval_task_type` field to `ContextResolutionResult` (computed once inside
   `attach_code_intelligence`/DRP's `resolve()`, both of which already compute it internally),
   surfaced to every consumer for free. Requires touching a widely-shared domain type and both resolvers.
2. Leave `/context-package` as a fully independent debug/inspection path (its own module docstring
   already frames it that way) and only consolidate the orchestrator ↔ `attach_code_intelligence` pair
   via option 1's field. Smaller blast radius.
**Recommended:** option 2, if pursued — it closes the one pair that's genuinely part of the same
logical request, without touching the deliberately-independent lower-level route's contract.

### G16 — Broader expansion-safety audit (item 18)

An independent read-only audit of every other traversal/expansion mechanism in `code_intelligence/`
and `context/` (excluding `context_resolver.py`, already fixed) found:
- **`code_intelligence/drp/query_router.py`'s `_expand_within_subsystem`** — AT RISK, same unbounded
  shape, no count cap at all (the module's own docstring already acknowledges subsystems can be
  "giant"/"monster"-sized). **Fixed**: added `_MAX_EXPANSION_FILES = 200`.
- **`code_intelligence/drp/drp_resolver.py`'s `resolve()`** — AT RISK, appended every symbol from every
  expanded file into `impacted_symbols`/`entry_points` with no cap, the exact G16 shape unfixed in DRP.
  **Fixed**: added `_MAX_IMPACTED_SYMBOLS = 200`, checked at all 3 symbol-appending loops.
- `candidate_selector.py`/`locality.py` — the underlying BFS/graph functions still materialize their
  full result before `context_resolver.py`'s consumption-side cap applies (a real, but lower-severity,
  compute-cost gap — output is already bounded, only the intermediate computation isn't). Not fixed in
  this pass; tracked as **NEW-2** below.
- `evidence_fallback.py`/`subsystem_localizer.py` — confirmed cleanly gated everywhere growth occurs, no
  action needed.
- `reference_resolver.py` — confirmed low-risk by design (mirrors `CallGraph`'s own intentional
  over-inclusion, empirically small in practice).
**Tests:** `test_expansion_within_a_giant_subsystem_is_capped` (`tests/code_intelligence/drp/test_query_router.py`)
— 300-file linear import chain, `traversal_depth=250` (well beyond the count cap), confirms the count
cap — not the depth limit — is what stops growth.
**Status: RESOLVED for the two AT-RISK sites found; NEW-2 tracked for the lower-severity compute-cost
gap.**

### G18 — Cost guardrail second audit (item 19)

Independently re-traced after G-new-1's fix (not assuming the first calculation correct): request →
outer attempt (up to `arcf_max_recovery_attempts + 1`) → SLM-2 (up to `DEFAULT_MAX_PARSE_RETRIES` ×
`max_retries` internal calls) → generation (up to `max_retries` internal calls) → recovery loop-back →
ledger. This is the exact trace G-new-1's fix already implements (`llm_calls_per_pass = DEFAULT_MAX_PARSE_RETRIES
* max_retries + max_retries`, `worst_case_calls = llm_calls_per_pass * (arcf_max_recovery_attempts + 1)`)
— re-derived independently here and confirmed to match, not just re-read.
**Status: RESOLVED** (confirmed correct on independent re-derivation, no discrepancy found).

### Execution-to-ledger contract re-audit (item 20)

Every path re-checked after G-new-5's fix: success (protected, `_persist_ledger_entry`), failure with
real spend (protected, `_persist_failure_ledger_entry`), verification failure / recovery / recovery
exhaustion (all reach one of the two paths above depending on whether the loop completes or raises),
budget exhaustion (rejected pre-flight by the cost guardrail, before the orchestrator ever runs — no
ledger entry expected or written, correct), LLM exception (caught by `run()`'s own `except Exception`,
routed to the failure path), ledger exception itself (both construction and store-write now guarded at
both success and failure paths). No path found capable of producing inconsistent audit state.
**Status: RESOLVED.**

### Verification → Recovery contract re-check (item 21)

Re-checked after G-new-2's fix: unsupported relative path → `UNSUPPORTED_REFERENCES`, `recovery_eligible=True`
(unchanged, regression-tested). Unsupported absolute path → now also correctly `UNSUPPORTED_REFERENCES`,
`recovery_eligible=True` (the fix). Insufficient evidence → `INSUFFICIENT_EVIDENCE`, `recovery_eligible=True`
(unchanged). Supported output (relative or absolute) → `SUFFICIENT`, `recovery_eligible=False`
(unchanged, and now regression-tested for absolute references too). All 4 downstream control-flow
outcomes confirmed correct via the verification test suite (20/20 passing) plus the orchestrator's own
Case A/B/C tests.
**Status: RESOLVED.**

### New findings surfaced during this pass (tracked, not silently fixed)

| ID | Finding | Why not fixed in this pass |
|---|---|---|
| NEW-1 | `DrpResolver.resolve()` never sets `evidence_categories_missing` on the `ContextResolutionResult` it produces, meaning a real DRP recovery retry always reports evidence as satisfied regardless of whether it genuinely resolved anything — Case-B exhaustion is architecturally handled correctly by the orchestrator (proven by a controlled-double test) but effectively unreachable end-to-end today. | Fixing this requires DRP to make an honest claim about which evidence categories its own subsystem-routing result actually satisfies — a real design decision about DRP's own evidence-sufficiency semantics, not a bug fix. |
| NEW-2 | `candidate_selector.subclasses_of`/`InheritanceGraph.all_subclasses_of` and `locality.py`'s BFS helpers still materialize their full unbounded result before `context_resolver.py`'s consumption-side caps apply — output is already correctly bounded (G16/G-new-3 fixed), but the intermediate compute cost for a very deep/wide graph is not. | Lower severity than G-new-3 (a real gap in *output*, this is only a gap in *compute cost* for pathological graphs); capping the underlying BFS itself would touch shared graph-traversal primitives used by multiple callers beyond this closure's scope. |

### Test count

| Stage | Passing |
|---|---|
| Before this implementation pass (§41.1's end state) | 1022 |
| After this implementation pass | **1052** |

30 net new tests: 9 (G-new-2 absolute-path variants) + 2 (G-new-3 dense caller/callee) + 2 (G-new-5
construction-failure) + 1 (G-new-1 cost formula) + 5 (G-new-4 durability store + restart) + 3 (G-new-7
negative paths) + 1 (G7 generic scan, same test strengthened not counted as new) + 1 (DI classifier
injection) + 1 (G10 origin_stage) + 3 (G9 confidence semantics) + 1 (G12 caching) + 1 (G16 giant-subsystem
cap) = 30.

### Files changed in this pass

**Modified:** `src/execution/verification.py`, `src/code_intelligence/context_resolver.py`,
`src/application/execute_use_case.py`, `src/context/understanding.py`,
`src/interfaces/api/routes/grounded_execution.py`, `src/interfaces/api/app.py`, `src/shared/config.py`,
`src/infrastructure/context_resolution_store.py`, `src/domain/context_resolution.py`,
`src/code_intelligence/drp/drp_resolver.py`, `src/code_intelligence/drp/query_router.py`,
`docs/ARCF_V2.3_BASELINE_FREEZE.md`, `docs/ARCF_ARCHITECTURE_CLOSURE_CHECKLIST_2026-08-16.md`.

**New:** `tests/infrastructure/test_context_resolution_store.py`,
`tests/domain/test_context_resolution_confidence_semantics.py`,
`docs/ARCF_INDEPENDENT_VERIFICATION_REPORT_2026-08-17.md` (the input to this pass).

**Test files modified:** `tests/execution/test_verification.py`,
`tests/code_intelligence/test_context_resolver.py`, `tests/application/test_execute_use_case.py`,
`tests/interfaces/test_grounded_execution_route.py`, `tests/interfaces/test_context_package_route.py`,
`tests/code_intelligence/test_phase6_boundary.py`, `tests/code_intelligence/drp/test_drp_resolver.py`,
`tests/code_intelligence/drp/test_query_router.py`, plus the 7 `_build_client` test files updated to
set `context_resolution_store_path` to a tmp path (`test_code_intelligence_route.py`,
`test_comparison_route.py`, `test_context_package_route.py`, `test_contracts_route.py`,
`test_execution_ledger_route.py`, `test_grounded_execution_route.py`, `test_workspace_route.py`).

### Second self-review (before declaring this pass done)

- Did the fix create a new bypass? No.
- Did the fix introduce a new dependency cycle? No — DI injection and the new Sqlite store both follow
  existing, already-verified patterns.
- Did the fix change the canonical execution path? No — control-flow topology (evidence check →
  generation → verification → recovery) is unchanged; only bounds, caching, and injected dependencies
  changed.
- Did the fix weaken grounding? No — G-new-2 strictly strengthens it; regression tests confirm no
  change to relative-path behavior.
- Did the fix change recovery semantics? No — still one bounded attempt, deterministic `"drp"`
  strategy, same shared counter.
- Did the fix alter cost accounting? The guardrail's pre-flight *estimate* is deliberately stricter
  (the fix); actual post-hoc spend accounting from real `llm_responses` is unchanged.
- Did the fix create another unbounded expansion? No — actively searched for and fixed 2 more sibling
  instances (a 3rd `context_resolver.py` site, 2 DRP sites) rather than introducing any.
- Did the fix create another persistence inconsistency? No — G-new-5 fixed an asymmetry; the new
  `SqliteContextResolutionStore` follows the exact existing pattern, restart-persistence tested.
- Did the fix change public API semantics? The guardrail's rejection threshold is meaningfully
  stricter for the same endpoint (the fix's intended effect); request/response schemas unchanged; one
  new backward-compatible `Settings` field with a default.
- Did the fix make the diagram inaccurate? No — corrected it; no topology changes since.
- Did any acceptance criterion disappear? No — nothing deleted or weakened; 2 real bugs were found and
  fixed via this pass's OWN new tests (the 3rd `context_resolver.py` site, the DI-classifier proof),
  not just the originally-reported ones.

No issues found in this self-review.
