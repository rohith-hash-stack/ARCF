# ARCF — Independent Final Architecture Closure Verification Report

**Date:** 2026-08-17
**Branch verified:** `feature/architecture-closure` (off `Base` @ `5b7fa5c`) — HEAD still equals Base; all closure work exists only as uncommitted working-tree changes (18 modified, 12 new files). Nothing committed or merged.
**Method:** 10 independent background agents, each re-tracing actual code/tests/runtime behavior rather than trusting the prior session's own status claims (`ARCF_ARCHITECTURE_CLOSURE_CHECKLIST_2026-08-16.md`, `ARCF_ARCHITECTURE_AUDIT_DISCOVERY_2026-08-16.md`, the prior adversarial-round summary). Those documents were treated as a **claim set to verify**, not as evidence.
**Status vocabulary used throughout:** `RESOLVED` / `PARTIALLY RESOLVED` / `NOT RESOLVED` / `NOT VERIFIABLE` / `OUT OF SCOPE`. No hedged language ("probably," "should be") is used as a final verdict.

---

## 1. Executive Verification Status

> **PARTIALLY VERIFIED**

This is not a rejection of the closure work — the central architectural claim (Generation was previously bypassable/ungrounded and is now genuinely wired through Verification and bounded Recovery) holds up under real, adversarial, object-level tracing, and DI, Recovery-bound, and provenance-tagging work is genuinely solid. It is not `VERIFIED COMPLETE` because this verification round itself — independent of anything previously flagged — surfaced **7 new, real, currently-unfixed gaps** (§9) that no prior pass caught, on top of confirming several previously-known deferred items are still open. Per the user's standing instruction: passing 1022/1022 tests is not evidence of completeness on its own, and it is not being treated as such here.

The pattern across this whole effort (declare done → independent re-check → find real gaps → fix → declare done → independent re-check → find more real gaps) held true a third time in this very round. That recurrence is itself part of the executive finding: it means the honest posture going forward is "verify again before the next completeness claim," not "closed."

---

## 2. Original 19-Gap Reconciliation Table

Reconstructed independently from `ARCF_ARCHITECTURE_AUDIT_DISCOVERY_2026-08-16.md`'s own original gap text (read directly, not paraphrased from the checklist).

| ID | Original gap | Claimed fix | Actual code location | Verification method | Status | Evidence |
|---|---|---|---|---|---|---|
| G1 | No canonical execution path ties Retrieval→Evidence→Context→Generation→Verification together | New `ArcfExecutionOrchestrator.run()` + `POST /contracts/{id}/grounded-execution` | `src/application/execute_use_case.py`, `src/interfaces/api/routes/grounded_execution.py` | Object/data tracing through the full call chain; route reachability confirmed | **RESOLVED** | Route registered in `app.py`; orchestrator invoked with real constructed dependencies, not stubs |
| G2 | Generation callable without any grounding check (bypass) | `verify_grounding()` invoked unconditionally post-generation | `src/execution/verification.py` | Independent instrumented script traced a unique marker from `ContextPackage.relevant_files` through to the verification result | **RESOLVED** | Marker-tracing proof (see §6); no code path reaches `FinalGenerationRunner` output without also reaching `verify_grounding()` |
| G3 | No bounded recovery on evidence-insufficiency / ungrounded output | Single `attempt` counter + `MAX_RECOVERY_ATTEMPTS` (default 1) | `execute_use_case.py` loop, `Settings.arcf_max_recovery_attempts` | Forced-exhaustion test + static bound analysis | **RESOLVED**, with a caveat — see G-new-1 in §9 (cost-guardrail undercounts true worst-case calls) | `test_recovery_never_exceeds_max_recovery_attempts` passes; bound itself is real, but the *cost estimate* for that bound is wrong |
| G4 | Recovery strategy selection not deterministic (risk of LLM-in-the-loop retry logic) | Hardcoded literal `strategy = "drp"`, never LLM-derived | `execute_use_case.py` | Grep for any LLM call between evidence-insufficiency detection and strategy assignment | **RESOLVED** | No LLM call exists in that path; strategy is a Python literal |
| G5 | Recovery re-entry point unclear / risk of becoming a second orchestrator | Recovery re-enters only via existing `attach_code_intelligence`/`package`/`generate` calls | `execute_use_case.py` | Confirmed no direct access to `ContextResolver`/`CallGraph`/`SymbolIndex`/locality internals from the recovery branch | **RESOLVED** | Recovery is two `if` blocks inside the same loop, not a separate component (independently reconfirmed by the layer-rediscovery agent) |
| G6 | No DI composition root / dependencies constructed ad hoc | `create_app()` composition root constructs every singleton onto `app.state`; `Depends()` accessors | `src/interfaces/api/app.py`, `src/interfaces/api/dependencies.py` | Construction-order trace, per-dependency lifetime check | **RESOLVED** | All 7 orchestrator ctor args, including `max_recovery_attempts`, traced to `Settings` |
| G7 | No automated circular-dependency guard | New test scanning import graph | `tests/code_intelligence/test_phase6_boundary.py` | Read test body directly | **PARTIALLY RESOLVED** | Test only generically scans the reverse direction (code_intelligence→application); forward direction checks a hardcoded file list, not a generic scan — see §5/§9 |
| G8 | `max_recovery_attempts` not threaded from config | `Settings.arcf_max_recovery_attempts` → composition root → orchestrator ctor | `shared/config.py`, `app.py` | Traced end-to-end | **RESOLVED** | `test_max_recovery_attempts_flows_from_settings_through_composition_root` passes and asserts the real value, not a mock |
| G9 | Confidence semantics blended/conflated across stages | `resolution_confidence` + `resolution_confidence_source` kept as separate provenance fields, never blended | `src/domain/execution_result.py` | Field-level read | **PARTIALLY RESOLVED** (as originally and honestly documented) | Provenance is tagged; the underlying dual-formula conflation this was tagging is explicitly *not* eliminated — this was never claimed as fully resolved, and that framing still holds |
| G10 | `origin_stage` unset on some `FileReference` construction sites | Fixed at the evidence-validator fallback site | `src/context/evidence_validator.py:~331` | grep + read | **PARTIALLY RESOLVED** | 1 of 4 known sites fixed; DRP's 3 sites (`drp_resolver.py:~121,143,169`) still omit it, explicitly deferred (needs new enum value) |
| G11 | Persistence failures could crash an otherwise-successful request | `_save_ledger_entry` wraps only the store `.save()` call in try/except | `execute_use_case.py` | Simulated store-outage test | **PARTIALLY RESOLVED** | Fixed narrowly for this closure's own new ledger-write code only; the same unguarded pattern remains elsewhere in the codebase, explicitly out of scope by design, not silently dropped |
| G12 | Task-type computed redundantly across stages | N/A — pre-existing, newly counted during this closure | Multiple sites | Count re-verified | **NOT RESOLVED** (documented, not silently dropped) | Count is now 4 sites (this closure's new route code added a 4th without consolidating); tracked as known, unconsolidated duplication |
| G13 | Task-type budget ceiling not connected to context packaging | `task_type=retrieval_task_type` threaded into `packager.package()` | `src/interfaces/api/routes/context_package.py` | Read call site | **RESOLVED** | Parameter present and non-default at the call site |
| G14 | `callers_of`/`transitive_callers_of` dead/unused methods | Removed | `src/code_intelligence/candidate_selector.py` | grep confirms zero remaining references | **RESOLVED** | Also removed from all dependent tests |
| G15 | Response body leaks internal/discarded LLM output | `response_model_exclude={"result": {"llm_responses"}}` | `grounded_execution.py` route decorator | Response-body assertion test | **RESOLVED** | `llm_responses` absent from HTTP response; still present internally for cost accounting and the ledger |
| G16 | Unbounded metadata growth in subclass expansion (2 loops) | `_TokenBudget` gate (loop 1) + `_MAX_IMPACTED_SUBCLASS_SYMBOLS = 200` cap (loop 2) | `src/code_intelligence/context_resolver.py:~104-109,704-714` | Fixture with 300 direct subclasses | **RESOLVED for `_expand_subclasses`**; **NOT RESOLVED for its sibling `_expand_calls`** | `_expand_calls`'s own `impacted_symbols`/`call_edges` accumulation has the identical unbounded-growth shape and no cap at all — new finding, see §9 |
| G17 | Verification path-matching false negatives/positives (case sensitivity, backslash paths, extensionless files, suffix false-match) | Rewrote extraction (3 new regex patterns) + boundary-aware, case-insensitive matching | `src/execution/verification.py` | 6 targeted regression tests + the original `utils.py`/`database_utils.py` false-match repro | **PARTIALLY RESOLVED** | Original bug classes genuinely fixed; a *new* gap in the same mechanism found this round — absolute paths (`/unix/...`, `C:\windows\...`) are structurally invisible to the extraction regexes' negative lookbehind, so a fabricated absolute-path reference passes as `SUFFICIENT` — see §9 |
| G18 | Cost guardrail underestimates real worst-case spend | Pre-flight estimate scaled by real worst-case call count + context-sized proxy prompt | `grounded_execution.py` | Tight-budget rejection test | **PARTIALLY RESOLVED** | Genuinely improved over the pre-fix version (which used a single short prompt estimate), but the "worst-case call count" constant itself (`2 * (max_recovery_attempts+1)` = 4) does not account for `LiteLLMClient`'s own internal retry (max_retries=3) or SLM-2's internal retry (max_parse_retries=2) nested inside each pass — true worst case is materially higher than the formula assumes, see §9 |
| G19 | Comparison-API claim in `ARCF_V2.3_BASELINE_FREEZE.md` ("frozen," now stale) | Checklist marked this "corrected" | `docs/ARCF_V2.3_BASELINE_FREEZE.md` | git diff against Base | **NOT RESOLVED**, and the "corrected" claim itself is unsubstantiated | `git diff` shows **zero changes** to that file from Base — 2 of its 3 "frozen" claims (Execution Ledger, Composer/Generation) are now incidentally true as a side effect of unrelated work, but the Comparison API claim is still false and was never actually corrected in the document itself |

**Tally:** 6 RESOLVED · 8 PARTIALLY RESOLVED · 2 NOT RESOLVED (honestly tracked) · 0 NOT VERIFIABLE · 0 OUT OF SCOPE, plus the standalone tracking-integrity finding on G19 (see §8).

---

## 3. Layer Acceptance Matrix

| Layer | Purpose/I-O/deps clear | Failure behavior defined | State ownership clear | Test-covered | Status | Notes |
|---|---|---|---|---|---|---|
| Query Understanding (SLM-1/contracts) | Yes | Yes (parse-retry bounded, `max_parse_retries=2`) | Yes | Yes | **RESOLVED** | Unchanged by this closure, independently re-confirmed |
| Workspace/Repository Scope | Yes | Yes | Yes | Yes | **RESOLVED** | `RepositoryScopeClassifier` constructed inline per-iteration inside the orchestrator rather than via DI — functionally harmless (stateless), but inconsistent with the DI story elsewhere, see §9 |
| Code Intelligence (indexing, classic+DRP) | Yes | Partially — DRP branch fully bypasses classic-pipeline internal fallback mechanisms (confirmed at `service.py:~373-382`), by design | Yes | Yes | **PARTIALLY RESOLVED** | Confirmed intentional, not a bug, but worth a code comment (none exists) |
| Evidence validation | Yes | Yes | Yes | Yes | **RESOLVED** | — |
| Ranking | Yes | Yes | Yes | Yes | **RESOLVED** | — |
| Context Construction | Yes | Yes | **In-memory only** — `ContextResolutionStore` loses all retrieval results on process restart | Yes (for happy path; not for restart/dangling-reference case) | **PARTIALLY RESOLVED** | New finding: a durable ledger entry can outlive its own `context_resolution_id` reference after a restart — `GET /executions/{id}` would return a dangling reference. See §9 |
| Goal Composition | Yes | Yes | Yes | Yes | **RESOLVED** | — |
| Generation | Yes | Yes | Yes | Yes | **RESOLVED** | Confirmed genuinely reachable only through the verified/grounded path — see §6 |
| Verification | Yes, and scope is honestly bounded (`contradictions_checked` hardcoded `False`, no semantic/logical/completeness claim made anywhere) | Yes | Yes | Yes (11 tests) | **PARTIALLY RESOLVED** | Mechanism is correctly scoped and honestly documented; the absolute-path detection gap (§9) is a real hole in that mechanism's coverage, not a scope-overclaim problem |
| Recovery | Yes — genuinely just 2 `if` blocks in the same loop, not a second orchestrator | Yes (exhaustion forces `low_confidence`, tested) | Yes | Yes | **RESOLVED** | Independently reconfirmed by 2 separate agents (recovery-deep-dive and layer-rediscovery) using different methods |
| Execution Ledger | Yes | Yes for failure path (try/except added), **asymmetric for success path** — construction of the success-path ledger entry itself sits outside any try/except | Yes | Partial | **PARTIALLY RESOLVED** | New finding, see §9 |

---

## 4. Connection Acceptance Matrix

Applying the user's 11-point checklist per connection (producer executes / produces required value / value reaches consumer / consumer uses it / no silent discard / no manual reconstruction / provenance preserved / confidence semantics preserved / failure state preserved / no internals access / test-covered).

| Connection | Status | Failing point(s), if any |
|---|---|---|
| Query Understanding → Workspace Scope | **RESOLVED** | — |
| Workspace Scope → Code Intelligence | **RESOLVED** | — |
| Code Intelligence → Evidence Validation | **RESOLVED** | — |
| Evidence Validation → Ranking | **RESOLVED** | — |
| Ranking → Context Construction | **RESOLVED** | — |
| Context Construction → Goal Composition | **RESOLVED** | task_type now threaded (G13) |
| Goal Composition → Generation | **RESOLVED** | Object-traced with a unique marker (§6) |
| Generation → Verification | **RESOLVED** | Verified unconditional, no bypass path found in a repo-wide search |
| Verification → Recovery | **PARTIALLY RESOLVED** | Control-flow connection is real and test-covered; the *evidence* Verification hands Recovery has the absolute-path blind spot (§9), so a genuinely ungrounded-but-absolute-path-referencing answer would not trigger recovery |
| Recovery → (re-entry to Code Intelligence/Context/Generation) | **RESOLVED** | Confirmed no internals access, single counter, deterministic strategy |
| Execution → Ledger | **PARTIALLY RESOLVED** | Success-path construction unprotected (§9); failure-path protected |
| Query-entity propagation (SLM-1 → Code Intelligence target_names) | **RESOLVED** | `effective_target_names = target_names or list(latest.contract.intent.entities)` confirmed at `service.py:~332` |

---

## 5. DI Acceptance Matrix

| Criterion | Status | Evidence |
|---|---|---|
| Composition root exists and is the single construction point | **RESOLVED** | `create_app()` in `app.py`; all singletons on `app.state` |
| Orchestrator constructed with all real dependencies (not stubs) at the composition root | **RESOLVED** | `test_production_composition_root_constructs_orchestrator_via_di` passes against the real `create_app()` |
| Per-dependency construction method traced (factories/lifetimes) | **RESOLVED** | Each of the 7 ctor args traced to its own construction site |
| Config threaded through to orchestrator (not hardcoded) | **RESOLVED** | `max_recovery_attempts` flows from `Settings` end-to-end, test-covered |
| Architectural-boundary respect (no reverse dependency from code_intelligence/context onto application) | **RESOLVED** | `test_no_reverse_dependency_from_code_intelligence_or_context_onto_application` — generic scan, real finding of zero violations |
| Architectural-boundary respect (forward direction: application/context not reaching into code_intelligence internals) | **PARTIALLY RESOLVED** | The test covering this direction only checks a hardcoded file list, not a generic import-graph scan — a new file added later on either side would not be automatically covered |
| Circular-dependency guard | **PARTIALLY RESOLVED** | Same test/file as above — only genuinely comprehensive in one direction |
| DI consistency (are *all* stateful collaborators actually injected, or are some constructed inline?) | **PARTIALLY RESOLVED** | `RepositoryScopeClassifier()` and `TaskClassifier()` are constructed inline inside the orchestrator's loop body rather than injected via the composition root — inconsistent with the rest of the DI story, though both are stateless so no correctness impact was found |
| Testability (can the orchestrator be constructed with substitute collaborators in tests?) | **RESOLVED** | Confirmed via the existing test suite's use of in-memory store substitutes |

---

## 6. Control-Flow Verification

- **Generation-bypass fix**: verified with real object/data tracing, not class-name presence. An independent instrumented script planted a unique marker string inside a `ContextPackage.relevant_files` entry and traced it through `ContextGoalComposer.compose()` → `FinalGenerationRunner` → `verify_grounding()`, confirming the same object identity (not a reconstructed copy) flows through the whole chain and that `verify_grounding()` is unconditionally invoked before any result is returned from `ArcfExecutionOrchestrator.run()`. **RESOLVED.**
- **Canonical endpoint / bypass search**: repo-wide search for any other route or code path that constructs `FinalGenerationRunner` or calls the underlying LLM client directly for a grounded answer, bypassing the orchestrator. **None found.** **RESOLVED.**
- **Evidence states A/B/C do not collapse**: confirmed via `test_normal_path_reaches_generation_and_verification` (Case A), `test_insufficient_evidence_triggers_one_recovery_attempt_with_drp_strategy` (Case B, strengthened this round to assert actual outcome not just attempt count), `test_unsupported_reference_triggers_recovery_and_exhausts_to_low_confidence` (Case C). All 3 states are distinct, test-covered, and drive different control flow — not just computed and discarded. **RESOLVED.**
- **Recovery bound, exhaustively**: single shared counter covers both checkpoints (pre-generation evidence-gap check, post-generation verification-failure check); no nested/recursive recovery path exists; `LiteLLMClient`'s internal retry and SLM-2's internal parse-retry are separate, independently-bounded mechanisms that do not interact with the recovery counter (confirmed: they retry *within* one orchestrator pass, not by incrementing `attempt`). The recovery bound itself is real and cannot be exceeded. **RESOLVED** — but note this is a different question from whether the *cost guardrail's* estimate of worst-case calls is accurate (it isn't — see §9, G-new-1).
- **Recovery exhaustion, forced**: `test_recovery_never_exceeds_max_recovery_attempts` and the Case C test both force exhaustion and assert `final_status == "low_confidence"`, not just a counter value. **RESOLVED.**
- **Recovery test quality**: `test_unsupported_reference_triggers_recovery_and_exhausts_to_low_confidence` and the strengthened Case B test both assert real alternate execution (different `resolution` object, different `strategy_used` field, different final content), not just object construction or counter increments. **RESOLVED.**

---

## 7. Adversarial Finding Reconciliation (prior round, §41.1 of the checklist)

All 11 items from the prior adversarial re-verification round were independently re-checked against current code/tests in this round, not re-read from the checklist's own account.

| # | Finding | Reconciliation status |
|---|---|---|
| 1 | Ledger loss on mid-recovery exception | **CONFIRMED genuinely fixed** — try/except present, new test passes, reproduces the exact original scenario |
| 2 | Verification lenient-suffix false match (`utils.py`/`database_utils.py`) | **CONFIRMED genuinely fixed** — boundary-aware matching in place, regression test passes |
| 3 | Verification extraction coverage gaps (backslash/extensionless/bare filenames) | **CONFIRMED genuinely fixed** for the cases originally named — but this round found a *new*, different coverage gap (absolute paths) in the same mechanism, see §9 |
| 4 | Verification case-sensitivity false positive | **CONFIRMED genuinely fixed** |
| 5 | G16 second-loop unbounded expansion | **CONFIRMED genuinely fixed** for `_expand_subclasses` — but this round found the *sibling* method `_expand_calls` has the identical unfixed defect, see §9 |
| 6 | Cost guardrail underestimate | **CONFIRMED genuinely improved**, not fully — see §9, G-new-1 |
| 7 | LLM-response leakage in HTTP response | **CONFIRMED genuinely fixed** |
| 8 | Weak Case-B recovery test | **CONFIRMED genuinely strengthened** — now asserts real outcome |
| 9 | G15 dropped from tracking | **CONFIRMED fixed at 1 of 4 sites, remaining 3 honestly documented as deferred** |
| 10 | G18 dropped from tracking | **CONFIRMED fixed narrowly for this closure's own code, remaining scope honestly documented as out of scope** |
| 11 (test strength) | Headline recovery test meaningfulness | **CONFIRMED** — re-audited this round as part of the independent test-quality pass, no false-confidence pattern found |

No discrepancies between the prior round's self-reported outcomes and this round's independent re-check. This is the one part of the process that held up completely clean on reconciliation — none of the 11 were overclaimed.

---

## 8. Tracking Reconciliation

- G15 and G18 were confirmed as real prior instances of "silently dropped from tracking" (caught and corrected in the prior adversarial round).
- **This round found a third instance of the same failure pattern**: G19's "corrected" status in the checklist is itself unsubstantiated — `git diff` against Base shows zero changes to `ARCF_V2.3_BASELINE_FREEZE.md`, meaning the claim of correction was recorded without the underlying edit actually happening. This is a process-integrity finding, not a large architectural one, but it is the same category of failure (a status marked resolved without the evidence to back it) that this whole verification exercise exists to catch, recurring for a third time.
- No other original requirement was found to have been renamed, merged, deleted, or reclassified without a documented reason. The G9/G10/G11 "PARTIALLY RESOLVED" framings in the original checklist were independently found to be honest (not softened) characterizations, not overclaims.

---

## 9. Remaining Issues (new findings from this verification round — none fixed, per instruction)

| # | Issue | Severity | Location | Evidence |
|---|---|---|---|---|
| G-new-1 | Cost guardrail's worst-case LLM call count (4, from `2*(max_recovery_attempts+1)`) does not account for `LiteLLMClient`'s own internal retry (`max_retries=3`) or SLM-2's internal parse-retry (`max_parse_retries=2`), both nested inside each of up to 2 orchestrator passes. True worst case is materially higher (up to 18 by one agent's count). | Medium — under-protected budget, same class of bug as the one just fixed, not caught by the fix | `grounded_execution.py` guardrail; `infrastructure/llm_client.py`; `context/understanding.py` | Static trace of nested retry loops |
| G-new-2 | `verify_grounding()`'s extraction regexes have a negative lookbehind (`(?<![\w/\\])`) on the directory-path pattern that makes absolute paths (`/unix/style`, `C:\windows\style`) structurally invisible to extraction. A fabricated absolute-path reference to a non-retrieved file passes verification as `SUFFICIENT`. | High — defeats the core purpose of grounding verification for one whole class of reference | `src/execution/verification.py` | Agent-run empirical repro: fabricated absolute-path reference to non-retrieved file → status `SUFFICIENT` |
| G-new-3 | `_expand_calls` (sibling method to the fixed `_expand_subclasses` in `context_resolver.py`) has an unbounded `impacted_symbols`/`call_edges` accumulation with no cap, only bounded by locality-filtered BFS frontier exhaustion — itself unbounded under `LARGE_STRUCTURAL_CHANGE`'s `traversal_depth=None`. | High — same defect class as G16, unfixed in its sibling | `src/code_intelligence/context_resolver.py` | Read of `_expand_calls`, contrasted with the capped `_expand_subclasses` |
| G-new-4 | `ContextResolutionStore` is in-memory only. Retrieval results vanish on process restart while the durable execution ledger's `context_resolution_id` reference survives, producing a dangling reference reachable via `GET /executions/{id}` after a restart. | Medium — data-loss/dangling-reference risk, not correctness-under-normal-operation | Store wiring in `app.py` | Independent layer-rediscovery agent trace |
| G-new-5 | Success-path ledger entry construction (`_persist_ledger_entry`'s call site) sits outside any try/except, unlike the deliberately-hardened failure path added in the prior round. An exception during successful-path entry construction is unprotected and untested. | Medium — asymmetric hardening, real gap in a mechanism just built this closure | `execute_use_case.py` | Code read; no test exercises this path |
| G-new-6 | 2 diagram-vs-code discrepancies in the checklist's §37 ASCII architecture diagram: it draws the orchestrator as directly calling into `POST /contracts` / Query Understanding as one live chain (they are actually two decoupled HTTP requests), and never names the actual `grounded-execution` entry-point route at all. | Low — documentation accuracy, not a code defect | `docs/ARCF_ARCHITECTURE_CLOSURE_CHECKLIST_2026-08-16.md` §37 | Diagram vs. route registration read side-by-side |
| G-new-7 | 3 genuinely untested negative paths: (a) `LLMInvocationError` propagation through the full stack, (b) Case-B evidence-still-missing-after-retry exhaustion (distinct from Case-C unsupported-reference exhaustion, which *is* tested), (c) malformed/nonexistent `workspace_root` at the actual call path the orchestrator uses. | Medium — coverage gap, not a known-broken behavior | `tests/application/`, `tests/interfaces/` | Confirmed absent via targeted grep across the relevant test files |
| (carried) | `app.py`'s eager module-level `app = create_app()` + `tracing.py`'s module-level `_configured` global — pre-existing, not introduced by this closure, but means `otel_service_name` is only honored on the first `create_app()` call per process. | Low, pre-existing | `app.py:~179`, `infrastructure/tracing.py` | git diff confirms pre-existing |
| (carried) | DRP's 3 `FileReference` sites still omit `origin_stage` (G10/G15 remainder) | Medium, already tracked as deferred | `drp_resolver.py:~121,143,169` | grep |
| (carried) | Codebase-wide unguarded-persistence pattern outside this closure's own new code (G11/G18 remainder) | Low, already tracked as out-of-scope by design | multiple sites | grep |

---

## 10. Architecture-vs-Code Discrepancy

Covered in G-new-6 above. Beyond the diagram, no discrepancy was found between the checklist's prose descriptions of layer responsibilities and the actual code — the diagram is the only artifact found to be inaccurate, and only in the 2 ways listed.

---

## 11. Test-Quality Findings

- Independent audit of 47 tests relevant to this closure found **zero remaining false-confidence patterns** (no test mocks the exact thing it claims to verify, no test only proves construction rather than behavior, no test asserts invocation without validating output). The previously-flagged weak Case-B recovery test is confirmed now genuinely strengthened.
- 3 real negative-path gaps found and listed in §9 (G-new-7) — these are coverage gaps, not evidence of a broken mechanism; each was independently checked by having an agent attempt to construct the scenario in a scratch script, not just by grepping for an absent test name.
- `test_grounded_execution_full_pipeline_reaches_generated_verified_answer` was independently re-confirmed to prove control-flow/status but *not* content-derivation from context on its own (the mock LLM response doesn't depend on file content) — this was already known from the prior round and remains an accurate characterization, not a new gap; the marker-tracing script in §6 is what actually proves content-derivation, and it is a script, not a committed test.

---

## 12. Exact Blockers

If the goal is to honestly claim `VERIFIED COMPLETE` rather than `PARTIALLY VERIFIED`, these are the specific items that must be resolved first, in priority order:

1. **G-new-2** (absolute-path grounding-verification blind spot) — this is the highest-severity item because it defeats the stated purpose of the mechanism for one whole reference class, on the same subsystem this whole closure effort centers on.
2. **G-new-3** (`_expand_calls` unbounded growth) — same defect class as the flagship G16 fix, in its untouched sibling.
3. **G-new-5** (success-path ledger construction unprotected) — asymmetric with the failure-path hardening built earlier this closure; the asymmetry itself is the tell that this was missed, not designed.
4. **G-new-1** (cost guardrail true-worst-case undercount) — same defect class as the item already fixed this closure (#6 in §7), recurring in the same mechanism.
5. **G19's unsubstantiated "corrected" tracking claim** — a documentation-only fix (correct the claim or actually make the edit), but flagged as a blocker to a *process*-completeness claim specifically, since it's the third recurrence of the same tracking-integrity failure.
6. G-new-4, G-new-6, G-new-7, and the carried items are real but lower-severity; they do not block a completeness claim on their own but should be listed alongside whichever of 1–5 triggers the next implementation pass.

No code has been modified in the production of this report. All findings above are diagnostic only, per the standing instruction for this verification round. The decision of whether to run another implementation pass against this list is deferred to the user.
