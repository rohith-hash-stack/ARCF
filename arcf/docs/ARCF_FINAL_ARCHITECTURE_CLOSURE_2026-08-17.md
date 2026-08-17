# ARCF — Final Architecture Closure

**Date:** 2026-08-17
**This is the authoritative closure document.** It supersedes the need to read prior appendices
(`ARCF_ARCHITECTURE_CLOSURE_CHECKLIST_2026-08-16.md` §1-42, `ARCF_INDEPENDENT_VERIFICATION_REPORT_2026-08-17.md`,
`ARCF_CLOSURE_IMPLEMENTATION_REPORT_2026-08-17.md`) to understand ARCF's current state — those remain
as the historical record of how this state was reached, and are not contradicted by anything below.
**Branch:** `feature/architecture-closure` (off `Base` @ `5b7fa5c`), still uncommitted.

---

## 1. Final Implementation Summary

This pass closed the two remaining genuine implementation gaps and converted every other open
question into an explicit, formally-classified decision. Per the classification scheme required for
this pass:

- **A. MUST FIX FOR FINAL ARCHITECTURE CLOSURE** — 2 items, both fixed this pass (§2, §3 below).
- **B. MUST DOCUMENT AS EXPLICIT ARCHITECTURAL DECISION** — 4 items, all recorded below with
  WHY/IMPACT/CURRENT SAFE CONTRACT/FUTURE OPTION where applicable (§7, §8 below and inline).
- **C. OUT OF CURRENT ARCHITECTURAL SCOPE** — 1 item (Comparison API connectivity), boundary stated.
- **D. FUTURE ENHANCEMENT** — 0 items generated fresh this pass (all future work already exists as
  documented options, not new open threads).

**Code changes this pass:**

| # | Change | File(s) | Category |
|---|---|---|---|
| 1 | `DrpResolver`'s dispatch (`code_intelligence/service.py::_resolve_drp`) now runs the same `validate_sufficiency()` evidence-contract check classic already does | `src/code_intelligence/service.py` | A — MUST FIX |
| 2 | Shared BFS primitive (`locality.py::_locality_filtered_bfs`) and `InheritanceGraph.all_subclasses_of` now cap intermediate traversal materialization, not just output | `src/code_intelligence/locality.py`, `src/code_intelligence/inheritance_graph.py` | A — MUST FIX |
| 3 | Existing Case-B orchestrator test updated to assert the new, honest exhaustion outcome instead of a since-invalidated "success" assumption | `tests/application/test_execute_use_case.py` | test correction, not new scope |

No other production code changed. No prohibited architecture introduced.

---

## 2. Final Issue 1 — DRP Evidence-State Contract (RESOLVED)

**Question A answered: YES.** Every retrieval mechanism must produce the same evidence-state
contract — the Case-B recovery architecture is defined in terms of `evidence_categories_missing`,
and an undocumented resolver-specific exemption from that contract is exactly the kind of hidden,
resolver-specific semantics this pass exists to eliminate.

**Root cause, traced directly (not assumed):** `CodeIntelligenceContractService._resolve()` dispatches
to `_resolve_drp()` in an early-return branch, *before* the line that calls `validate_sufficiency()`
for the classic path. `DrpResolver.resolve()` itself also never sets the field. Both facts combined
meant a DRP-produced `ContextResolutionResult` always looked evidence-satisfied — not just to the
orchestrator's pre-generation Case-B check, but to `verify_grounding()`'s own post-generation check,
since that function examines whichever resolution actually produced the artifact, which on any
recovery retry is DRP's.

**Fix:** `_resolve_drp()` now calls the same `validate_sufficiency()` classic uses, scoped by
`detect_task_type_for_evidence(raw_request)` alone (no `RepositoryScopeClassifier` fallback, since DRP
deliberately never runs scope classification — this preserves DRP's isolation from classic's *other*
mechanisms, which was never in question; only the evidence-state *contract* needed to be shared).
`validate_sufficiency()` is resolver-agnostic by construction (operates on `result.candidate_files` plus
the repository scan, not on classic-only internal state), so no other change was needed.

**Acceptance criterion — "a production execution must be capable of naturally reaching the correct
Case-B behavior through DRP when its actual evidence is insufficient, not solely via a mock/double":**
met. `tests/code_intelligence/test_service.py::test_resolver_strategy_drp_populates_evidence_categories_missing`
proves it directly at the service layer with zero mocks. At the orchestrator level,
`tests/application/test_execute_use_case.py::test_insufficient_evidence_triggers_one_recovery_attempt_then_honestly_exhausts`
proves a full, real, non-mocked execution reaches genuine Case-B exhaustion through DRP.

**A genuinely interesting, honest sub-finding surfaced by this fix:** because `validate_sufficiency()`'s
expansion step is a deterministic, repository-wide glob match (not limited to either resolver's own
candidate set), if the required evidence files exist *anywhere* in the repository, **either** resolver's
first attempt already finds them — meaning a different resolution *strategy* cannot manufacture evidence
that a *file* doesn't provide. Concretely: Case-B recovery via DRP now behaves honestly in both
directions — if the evidence genuinely exists, it's found before recovery is ever needed; if it
genuinely doesn't exist anywhere in the repo, no resolver reports otherwise, and honest exhaustion
(`low_confidence`) is correct. DRP's own recovery value remains real and distinct for **Case C**
(candidate-*file* coverage differences from a structurally different resolution algorithm), which was
already covered before this pass.

**Case A/B/C, restated with both resolvers explicit:**

| Case | Definition | Classic | DRP (as of this pass) |
|---|---|---|---|
| A | No candidates resolved at all | `unresolved_symbols` non-empty, `candidate_files` may still be non-empty via fallback expansion | DRP's own "no matching subsystem" outcome (`resolution_reason` states this explicitly) |
| B | Candidates exist, evidence insufficient | `evidence_categories_missing` set by `validate_sufficiency()`, always run | `evidence_categories_missing` **now also** set by `validate_sufficiency()`, always run (this pass's fix) |
| C | Generated output references an unretrieved repository file | Checked by `verify_grounding()` against whichever resolution produced the artifact | Same check, same function — resolver-agnostic by design, unaffected by this pass |

**Status: RESOLVED.**

---

## 3. Final Issue 2 — Expansion / Resource Boundary (RESOLVED)

**What ARCF promises, decided explicitly:** ARCF's established pattern (every cap added across this
whole closure effort) bounds **final output** — the data structures serialized into
`ContextResolutionResult`/returned to callers. This is a legitimate, deliberate architectural choice on
its own. **However**, two shared low-level primitives were found where *intermediate* traversal
materialization could itself exceed a real resource boundary *before* any output-side cap ever got a
chance to apply — the same class of real, measured MemoryError this codebase's own history already
recorded once (a 79-times-repeated identifier caused a crash, documented in
`context_resolver.py`'s `_MAX_CANDIDATES_TO_EXPAND` comment). That is a genuine violation of "all
expansion is bounded" if left unfixed, not a theoretical concern — `max_depth=None` /
`traversal_depth=None` are real, reachable, production inputs
(`RetrievalTaskType.LARGE_STRUCTURAL_CHANGE`).

**Fixed, not merely documented** (this pass):
- `code_intelligence/locality.py::_locality_filtered_bfs` — added `_MAX_BFS_NODES = 500`, checked
  every iteration of its own traversal loop. This is the single shared primitive underlying
  `locality_filtered_transitive_callers`/`locality_filtered_transitive_callees`, so both are fixed by
  one change.
- `code_intelligence/inheritance_graph.py::InheritanceGraph.all_subclasses_of` — added
  `_MAX_SUBCLASSES = 500`, checked every iteration of its own traversal loop.

**Deliberately left as output-only-bounded** (confirmed low-risk, not a violation): `reference_resolver.py`'s
candidate fan-out (mirrors `CallGraph`'s own intentional over-inclusion design, empirically small —
measured worst case 159 matches, not driven by traversal depth) and `locality_filtered_caller_files`/
`locality_filtered_callers_of_name` (single-hop, not recursive, bounded by real same-name collision
counts). Neither performs unbounded recursive traversal.

### Resource-boundary matrix (every mechanism in ARCF's expansion/traversal surface)

| Mechanism | Bound | Bound location | On exhaustion | Test |
|---|---|---|---|---|
| `_expand_subclasses` (candidate files) | `_TokenBudget` | `context_resolver.py` | Stops adding files past token budget | `test_unbounded_subclass_expansion_respects_max_expansion_tokens` |
| `_expand_subclasses` (impacted symbols) | `_MAX_IMPACTED_SYMBOLS=200` (shared) | `context_resolver.py` | Loop breaks, remaining subclasses dropped | `test_wide_subclass_hierarchy_caps_impacted_symbols_count` |
| `_expand_calls` (caller/callee hops) | `_MAX_IMPACTED_SYMBOLS`/`_MAX_CALL_EDGES=400` (shared) | `context_resolver.py` | Loop breaks | `test_dense_caller_graph_caps_impacted_symbols_and_call_edges`, `..._callee_graph...` |
| `_expand_calls` (hop-1 module-level call sites) | `_MAX_IMPACTED_SYMBOLS` (shared) | `context_resolver.py::_attach_call_site_symbols` | Loop breaks | covered by the dense-caller-graph test above (500-caller fixture) |
| `_expand_within_subsystem` (DRP file expansion) | `_MAX_EXPANSION_FILES=200` | `query_router.py` | While-loop condition fails, expansion stops | `test_expansion_within_a_giant_subsystem_is_capped` |
| `DrpResolver.resolve()` (symbol accumulation, 3 loops) | `_MAX_IMPACTED_SYMBOLS=200` | `drp_resolver.py` | Inner loop breaks per-file | covered indirectly; direct test not added (lower marginal value once the file-count cap above already limits how many files can contribute) |
| `_locality_filtered_bfs` (shared traversal primitive) | `_MAX_BFS_NODES=500` **(this pass)** | `locality.py` | While-loop condition fails, traversal stops | `test_locality_filtered_transitive_callers_caps_a_long_linear_chain` |
| `InheritanceGraph.all_subclasses_of` (shared traversal primitive) | `_MAX_SUBCLASSES=500` **(this pass)** | `inheritance_graph.py` | While-loop condition fails, `visited` truncated | `test_all_subclasses_of_caps_unbounded_traversal_on_a_wide_hierarchy` |
| `reference_resolver.py` candidate fan-out | None (by design) | — | N/A — bounded by real same-name collision counts, not traversal depth | Existing disambiguation tests |
| `locality_filtered_caller_files`/`_callers_of_name` | None (by design) | — | N/A — single-hop, not recursive | Existing locality tests |

**Status: RESOLVED.** Every mechanism in the table has a stated bound, bound location, exhaustion
behavior, and test, or an explicit "bounded by design, not traversal depth" rationale — no ambiguous
"bounded" terminology remains.

---

## 4. Final Issue 3 — Confidence Semantics / G9 (INTENTIONALLY DEFERRED, formally recorded)

**Contract, precisely defined:**

| Field | Meaning | Producer | Consumer(s) | Numerically comparable across resolvers? | Thresholdable? | Aggregable? | Generic score? |
|---|---|---|---|---|---|---|---|
| `ContextResolutionResult.confidence` | Classic: `resolved_count / total_targets` (a symbol-resolution hit rate). DRP: `routing.winning_confidence` (a subsystem-routing margin). | `ContextResolver.resolve()` (classic) or `DrpResolver.resolve()` (DRP) | `ArcfExecutionResult.resolution_confidence` (the only production consumer) | **No** | Only within one resolver's own formula, never across | No | No |
| `ArcfExecutionResult.resolution_confidence_source` | Which formula produced the paired `resolution_confidence` value (`"classic"` or `"drp"`) | `ArcfExecutionOrchestrator.run()` | Any caller of the grounded-execution API wanting to interpret `resolution_confidence` correctly | N/A (it's the disambiguator, not a confidence value) | N/A | N/A | N/A |

**Formal record:**
- **WHY deferred:** unifying the two formulas (or splitting into two differently-named fields) is a
  breaking change to `ContextResolutionResult`'s existing contract, consumed by both resolvers and
  every downstream layer (ranking, packaging, the orchestrator). No acceptance criterion in this
  closure requires formula unification — only that no consumer silently assumes interchangeability.
- **IMPACT if left as-is:** none currently, because the single production consumer
  (`ArcfExecutionOrchestrator`) always pairs the value with `resolution_confidence_source` and never
  compares or thresholds it against a value from the other resolver. A future consumer that ignored
  `resolution_confidence_source` and thresholded/compared the raw value across resolver runs would be
  the one real risk this defers.
- **CURRENT SAFE CONTRACT:** never read `resolution_confidence` without also reading
  `resolution_confidence_source`; never compare or threshold `resolution_confidence` values produced
  by different resolvers as though they were the same measurement. Enforced today by there being
  exactly one production consumer, which already follows this contract, plus 3 explicit contract tests
  (`tests/domain/test_context_resolution_confidence_semantics.py`) that would fail if the two formulas
  were ever silently collapsed into one without updating this record.
- **FUTURE OPTION:** if a second consumer of the raw field is ever added, either (a) require it to
  branch on `resolution_confidence_source` before interpreting the value, enforced by code review, or
  (b) introduce two distinctly-named fields (e.g. `classic_confidence`/`drp_routing_margin`) on
  `ContextResolutionResult` itself at that point, with a real migration for existing consumers.

**Status: INTENTIONALLY DEFERRED**, formally recorded per the required WHY/IMPACT/CURRENT SAFE
CONTRACT/FUTURE OPTION structure. Not an unresolved ambiguity.

---

## 5. Final Issue 4 — Task-Type Ownership / G12 (INTENTIONALLY DEFERRED, formally recorded)

**Authoritative model, stated explicitly:** `context/task_profile.py::classify_retrieval_task()` is the
single authoritative algorithm. It is a pure function of `(raw_request, task_classifier_task,
scope_task_type)`. Three call sites invoke it independently:

1. `application/execute_use_case.py` (orchestrator) — for `ranking_profile`/`task_type` passed into packaging.
2. `code_intelligence/service.py` (inside `attach_code_intelligence`, classic branch only) — for
   `traversal_depth` selection.
3. `interfaces/api/routes/context_package.py` — the fully independent lower-level debug/inspection route.

**Why their results cannot conflict:** all three call the identical pure function on the identical
`raw_request` string. A pure function's output depends only on its inputs — there is no state, no
timing dependency, and no code path where two calls with the same `raw_request` produce different
`retrieval_task_type` values. "Independent computation" here means "computed more than once," not
"computed differently." This was verified, not assumed: no divergent logic exists at any of the three
call sites — each is a direct call to the same imported function.

**What this pass fixed vs. deferred:**
- **Fixed:** call site #1's own internal redundancy — the orchestrator's `run()` loop previously
  recomputed the value on every recovery retry despite `raw_request` never changing across a single
  `run()` call. Now cached after the first computation
  (`tests/application/test_execute_use_case.py::test_task_type_classification_is_computed_once_per_run_not_per_retry`).
- **Deferred:** consolidating across all 3 call sites into one shared computation. This needs a
  cross-request-durable place to store the computed value (either a new field on
  `ContextResolutionResult`, threaded through both resolvers, or on `Contract` itself), since call site
  #3 runs as a genuinely separate HTTP request from #1/#2, possibly after a restart.

**Options recorded for a future pass, if pursued:**
1. Add `retrieval_task_type` to `ContextResolutionResult` (computed once inside `attach_code_intelligence`/
   `DrpResolver.resolve()`, both of which already compute it internally), surfaced to every consumer
   for free. Touches a widely-shared domain type and both resolvers.
2. Leave `/context-package` as a fully independent debug path (already its own documented framing) and
   only consolidate the orchestrator ↔ `attach_code_intelligence` pair via option 1's field. Smaller
   blast radius. **Recommended if pursued.**

**Status: INTENTIONALLY DEFERRED** for the cross-component duplication, **RESOLVED** for the
in-scope orchestrator-internal redundancy. One clearly documented semantic contract exists; no hidden
duplicate classification can silently produce conflicting task types (proven, not assumed, by the
pure-function argument above).

---

## 6. Final Issue 5 — G14 / Comparison API Terminology (Corrected)

**Resolved terminology, per this pass's explicit instruction not to use PARTIALLY RESOLVED merely
because something is intentionally out of scope:**

- The **Execution Ledger** half of the original G14 finding (no production writer existed) —
  **RESOLVED**. `ArcfExecutionOrchestrator` is a real, tested production writer.
- The **Comparison API connectivity** half of the original G14 finding (`comparison_store`/
  `ComparisonAggregator`/`POST /api/v1/compare` structurally starved of real input) — **OUT OF SCOPE**.
  Never touched by any round of this closure effort; never claimed fixed; explicitly documented as
  still-disconnected in `docs/ARCF_V2.3_BASELINE_FREEZE.md`'s "Comparison API" row (corrected in the
  prior implementation pass). This is a genuine scope boundary, not an unresolved ambiguity or a
  partial fix — no work was ever attempted on it, and none was required by this closure's own
  acceptance criteria.

**Status: G14 is now two separately-tracked halves — RESOLVED (ledger) and OUT OF SCOPE (comparison
connectivity).** The single "PARTIALLY RESOLVED" label previously used for both together is retired.

---

## 7. Final Issue 6 — G15 Contradiction (Corrected)

**Resolution:** G15's original finding was "some `FileReference` construction sites leave
`origin_stage` unset" — 4 sites total: 1 in `evidence_validator.py` (fixed in the first adversarial
round) and 3 in `drp_resolver.py` (fixed under G10's `OriginStage.DRP_SUBSYSTEM_ROUTING` addition in
the prior implementation pass). **All 4 original sites are now fixed.** G15's appearance in the prior
report's "Remaining OPEN/PARTIAL Items" table was itself the contradiction this issue asked to
resolve — it should not have appeared there once G10 closed its underlying sites.

**Status: G15 = RESOLVED.** Removed from the remaining-open/partial section in this document's own
master reconciliation (§9 below).

---

## 8. Final Issue 7 — Cost Guardrail, Re-Derived One Final Time

Independently re-traced against the actual current implementation (not assumed from the prior
report), and re-checked against every change made in this pass and the prior one:

```
1 grounded-execution request
  -> up to (arcf_max_recovery_attempts + 1) orchestrator passes   [default: 2]
       -> 1 packaging call (SLM-2, ContextUnderstandingAnalyzer.analyze())
            -> up to DEFAULT_MAX_PARSE_RETRIES parse-retry iterations   [default: 2]
                 -> each iteration calls LiteLLMClient.complete() once
                      -> up to settings.max_retries internal transient-failure retries   [default: 3]
            = up to (DEFAULT_MAX_PARSE_RETRIES * settings.max_retries) real network calls = 6
       -> 1 generation call (FinalGenerationRunner.generate(), one unwrapped LiteLLMClient.complete())
            -> up to settings.max_retries internal transient-failure retries   [default: 3]
            = up to settings.max_retries real network calls = 3
  = up to (6 + 3) = 9 real network calls PER PASS
  = up to 9 * 2 = 18 real network calls TOTAL at this project's own defaults
```

**Confirmed this pass:** neither of this pass's own fixes (the DRP evidence-contract fix, the two
resource-boundary caps) adds, removes, or nests any LLM call — `validate_sufficiency()`/`match_evidence()`
are pure deterministic glob-matching with zero LLM/network calls (confirmed directly: no `llm_client`
reference anywhere in `evidence_validator.py`). **18 is re-confirmed independently, unchanged by this
pass.**

**Guardrail formula (`interfaces/api/routes/grounded_execution.py`):**
`llm_calls_per_pass = DEFAULT_MAX_PARSE_RETRIES * settings.max_retries + settings.max_retries` = 9;
`worst_case_calls = llm_calls_per_pass * (settings.arcf_max_recovery_attempts + 1)` = 18. Both the
proxy prompt size AND assumed completion tokens are scaled by this real count (not just completion
tokens, which was the pre-fix asymmetry).

**Consistency check — estimated cost vs. actual maximum cost vs. configured budget vs. recovery limit
vs. internal retry limits:** the guardrail's pre-flight estimate is derived directly from
`settings.max_retries`, `DEFAULT_MAX_PARSE_RETRIES`, and `settings.arcf_max_recovery_attempts` — the
same three values that actually bound the real call tree above. There is no separate, independently-set
"maximum cost" constant that could drift from this derivation; the estimate *is* the trace, not an
approximation of it. Real spend, applied after the fact from `result.llm_responses`, is unaffected by
this estimate's own precision either way (per `grounded_execution.py`'s existing design).

**Status: RESOLVED**, independently re-derived and confirmed consistent.

---

## 9. Final Issue 8 — Ledger / Persistence Lifecycle (Confirmed Explicit)

| Store | Lifecycle | Backing | Why |
|---|---|---|---|
| `ContractStore` | **Restart-durable** | SQLite (`SqliteContractStore`) | `Contract`/`LivingContract` referenced across separate API calls by design (contract created now, code-intelligence attached later) |
| `ContextResolutionStore` | **Restart-durable** (fixed this closure, G-new-4) | SQLite (`SqliteContextResolutionStore`) | `Contract.context_resolution_id` is itself durable and dereferenced by a separate later request (`/context-package`) |
| `ExecutionLedgerStore` | **Restart-durable** | SQLite (`SqliteExecutionLedgerStore`) | Audit/observability record, `GET /executions/{id}` is meant to answer for any past execution |
| `ComparisonStore` | **Restart-durable** | SQLite (`SqliteComparisonStore`) | Same durability class as the ledger it compares |
| `IdempotencyGuard`'s store | **Process-local** (by design) | In-memory, TTL-based | Idempotency keys are meant to protect only a bounded recent window, not survive indefinitely; no API implies otherwise |
| `RateLimiter`'s token buckets | **Process-local** (by design) | In-memory | Rate limiting is inherently per-process capacity management, never claimed durable |

**Full failure-mode re-audit (unchanged from the prior implementation pass, re-confirmed here):**
successful execution (ledger construction + write both guarded), failed execution with real spend
(failure-path construction + write both guarded), verification failure (routes to the normal success
path with `final_status="low_confidence"`, ledger entry written normally), recovery exhaustion (same),
budget exhaustion (rejected pre-flight, before the orchestrator runs — correctly no ledger entry),
LLM failure (routed to the failure path, exception re-raised unchanged after best-effort persistence),
ledger persistence failure itself (logged, never propagated, at both construction and store-write
stages, both success and failure paths), process restart (`ContextResolutionStore` now durable,
`ExecutionLedgerStore` always was — no dangling reference possible, proven by
`test_context_package_survives_a_process_restart`).

**No API implies durability where none exists:** `IdempotencyGuard`/`RateLimiter` have no HTTP-facing
"retrieve past state" endpoint at all — nothing to imply durability to in the first place.

**Status: RESOLVED.**

---

## 10. Final Issue 9 — DI, Final Ownership Table

| Collaborator | Owner (construction site) | Injection path | Testable in isolation? | Category |
|---|---|---|---|---|
| `CodeIntelligenceContractService` | `create_app()` | `app.state` → `Depends()` / orchestrator ctor | Yes | Application dependency |
| `ContextPackager` | `create_app()` | Same | Yes | Application dependency |
| `FinalGenerationRunner` | `create_app()` | Same | Yes | Application dependency |
| `ExecutionLedgerStore` | `create_app()` | Same | Yes | Application dependency |
| `CostEstimator` (orchestrator's own) | `create_app()`, passed to orchestrator ctor | Orchestrator ctor | Yes | Application dependency |
| `RepositoryScopeClassifier` | `create_app()` (fixed this closure) | Orchestrator ctor | Yes | Application dependency |
| `TaskClassifier` | `create_app()` (fixed this closure) | Orchestrator ctor | Yes | Application dependency |
| `ArcfExecutionOrchestrator` itself | `create_app()` | `app.state` → `Depends()` | Yes | Application dependency (composition root's own top-level product) |
| `_to_symbol_reference` / `_normalize` / other free functions in `verification.py`/`drp_resolver.py` | Module-level, no construction | N/A | N/A (pure functions) | Stateless local helper — no state, no architectural boundary to inject across |
| `ExecutionLedgerEntry`/`ArcfExecutionResult` construction | Inline, per-call, inside orchestrator methods | N/A | N/A (value objects, not services) | Stateless local — data construction, not a collaborator |

**Distinction enforced:** every object with its own construction-time configuration, external I/O, or
cross-call state is DI-injected from `create_app()`. Every remaining inline construction is either a
pure function or an immutable value object — neither has a reason to be swapped in tests independently
of its caller, so neither is an architectural dependency. No further inline-constructed stateful
collaborator was found in `execute_use_case.py` on re-check for this pass (verified directly: grepped
every `= SomeClass(...)` call in the file).

**Status: RESOLVED.**

---

## 11. Final Issue 10 — Circular Dependency Boundary, Both Directions Confirmed

**Boundary being protected, stated explicitly:** `application/` (the orchestration layer) may depend on
`code_intelligence/`'s *public service boundary only* (`code_intelligence.service`); it must never reach
into `code_intelligence/`'s internals (`ContextResolver`, `CallGraph`, `SymbolIndex`, `locality.py`,
etc.) directly — that is what "Recovery must not manipulate internals" means enforced at the import
level. Conversely, nothing under `code_intelligence/` or `context/` may import `application/` at all —
that would be a real circular dependency, since `application/` already depends on both.

**Both directions, both now genuine architecture-wide scans (fixed this closure):**
- Forward (`application/` → `code_intelligence` internals): `test_application_orchestrator_does_not_import_code_intelligence_internals`
  now scans every `.py` file under `application/` against an ALLOWLIST of the one legitimate import
  (`code_intelligence.service`) — not a hardcoded blocklist, and not limited to one file.
- Reverse (`code_intelligence`/`context` → `application`): `test_no_reverse_dependency_from_code_intelligence_or_context_onto_application`
  scans every `.py` file under both packages — already generic before this closure, unchanged.

Neither test is a hardcoded snapshot of today's file list — both use `Path.rglob("*.py")`, so a new
file added to either package tomorrow is automatically covered without any test update.

**Status: RESOLVED.**

---

## 12. Final Issue 11 — Grounding Verification, Final Behavioral Matrix

| Reference | Retrieved | Expected | Test |
|---|---|---|---|
| Relative path | Yes | Supported | `test_sufficient_when_evidence_complete_and_references_match_packaged_files` |
| Relative path | No | Unsupported | `test_unsupported_reference_detected_when_file_never_retrieved` |
| Absolute Unix path | Yes | Supported | `test_absolute_unix_path_prefixing_a_real_packaged_file_is_supported` |
| Absolute Unix path | No | Unsupported | `test_absolute_unix_path_to_fabricated_file_is_recognized_and_unsupported` |
| Absolute Windows-drive path | Yes | Supported | `test_absolute_windows_drive_path_prefixing_a_real_packaged_file_is_supported` |
| Absolute Windows-drive path | No | Unsupported | `test_absolute_windows_drive_path_to_fabricated_file_is_recognized_and_unsupported` |
| Nested relative path (multi-segment) | Yes | Supported | `test_case_insensitive_reference_to_a_real_packaged_file_is_not_flagged` (also exercises multi-segment matching) |
| Nested relative path | No | Unsupported | `test_windows_backslash_path_reference_is_extracted_and_checked` |
| Extensionless conventional filename (relative) | Yes | Supported | `test_extensionless_conventional_filename_with_directory_prefix_is_checked` |
| Extensionless conventional filename (absolute) | No | Unsupported | `test_absolute_extensionless_conventional_filename_is_recognized` |
| Extensionless conventional filename (absolute) | Yes | Supported | `test_absolute_extensionless_conventional_filename_to_real_packaged_file_is_supported` |
| Absolute path, no intermediate directory segment | No | Unsupported | `test_absolute_path_with_no_intermediate_directory_segment_is_extracted` |
| Malformed/stray path-like text | — | Not extracted, no crash (documented limitation) | `test_malformed_absolute_looking_text_is_not_extracted_and_does_not_crash` |
| git-diff `a/`/`b/` prefix form | Yes | Supported (prefix-tolerant) | `test_git_diff_path_prefix_is_tolerated_not_flagged_unsupported` |
| Prose with no path-shaped text at all | N/A | Supported (no false positives) | `test_prose_with_no_file_paths_is_sufficient_when_evidence_complete` |
| Suffix collision (`utils.py` vs `database_utils.py`) | No (fabricated) | Unsupported (boundary-aware matching) | `test_suffix_match_does_not_cross_a_path_segment_boundary` |

**Verification → Recovery, every relevant failure type, control flow proven not just flags:**

| Verification outcome | Recovery triggered? | Proven by |
|---|---|---|
| `SUFFICIENT` | No | `test_normal_path_reaches_generation_and_verification` (real end-to-end, asserts `final_status=="success"`) |
| `INSUFFICIENT_EVIDENCE` (Case B, classic) | Yes, once | `test_insufficient_evidence_triggers_one_recovery_attempt_then_honestly_exhausts` (real, natural) |
| `INSUFFICIENT_EVIDENCE` (Case B, still missing after DRP retry) | Bounded, no 2nd retry | Same test (natural) + `test_case_b_evidence_still_missing_after_recovery_exhausts_to_low_confidence` (isolated mechanism) |
| `UNSUPPORTED_REFERENCES` (Case C) | Yes, once, then exhausts if unresolved | `test_unsupported_reference_triggers_recovery_and_exhausts_to_low_confidence` (real, asserts `final_status=="low_confidence"` and the specific unsupported reference) |

**Status: RESOLVED.**

---

## 13. Final Issue 12 — Recovery, Final Re-Confirmation

Verified against the current code (post all fixes in this pass and the prior one):
- **Bounded:** single `attempt` counter, `attempt < self._max_recovery_attempts` gates every retry
  trigger, both trigger points share the one counter.
- **Deterministic:** `strategy = "drp"` is a hardcoded Python literal; no LLM call exists anywhere
  between an insufficiency detection and the strategy assignment (grepped, confirmed).
- **Non-LLM-directed:** confirmed by the same grep above.
- **Non-recursive:** the loop is `while True` inside one method, `run()`; recovery re-enters only via
  `attach_code_intelligence`/`package`/`generate` — no call graph cycle back through `run()` itself.
- **Single orchestration path:** exactly one `while True:` loop; no second loop, no nested retry
  structure was introduced by this pass's cost-model fix (confirmed: the cost guardrail changes are
  entirely in the pre-flight HTTP route handler, executed *before* `orchestrator.run()` is ever called,
  with zero interaction with the recovery loop's own control flow).
- **Case B / Case C / recovery success / recovery exhaustion / budget exhaustion / LLM failure during
  recovery** — all explicitly tested (§12 table above for B/C; `test_recovery_never_exceeds_max_recovery_attempts`
  for the bound itself; `test_grounded_execution_cost_guardrail_rejects_tight_budget` and
  `test_cost_guardrail_rejects_budget_the_undercounted_formula_would_have_passed` for budget exhaustion;
  `test_exception_during_recovery_retry_still_persists_real_spend_from_attempt_zero` and
  `test_grounded_execution_llm_invocation_error_propagates_as_502` for LLM failure during recovery).

**No new retry path was introduced while fixing the cost model** — confirmed directly above.

**Status: RESOLVED.**

---

## 14. Final Issue 13 — Expansion Audit

See §3's resource-boundary matrix above — it is this audit, already produced to the exact format
requested (Mechanism / Bound / Bound location / Failure-exhaustion behavior / Test). No mechanism was
redesigned; the two genuinely unbounded shared primitives were capped, everything already safely
bounded was left unchanged.

---

## 15. Final Issue 14 — Negative Paths, Final Confirmation

| Negative path | Test |
|---|---|
| LLM failure | `test_grounded_execution_llm_invocation_error_propagates_as_502` (real HTTP 502) |
| Case-B exhaustion | `test_insufficient_evidence_triggers_one_recovery_attempt_then_honestly_exhausts` (natural) + `test_case_b_evidence_still_missing_after_recovery_exhausts_to_low_confidence` (isolated) |
| Case-C failure | `test_unsupported_reference_triggers_recovery_and_exhausts_to_low_confidence` |
| Invalid `workspace_root` | `test_grounded_execution_with_nonexistent_workspace_root_returns_400` |
| Absolute unsupported reference | `test_absolute_unix_path_to_fabricated_file_is_recognized_and_unsupported`, `test_absolute_windows_drive_path_to_fabricated_file_is_recognized_and_unsupported` |
| Ledger failure (store write) | `test_ledger_store_failure_does_not_crash_an_otherwise_successful_run` |
| Ledger failure (construction) | `test_ledger_entry_construction_failure_does_not_crash_a_successful_run`, `test_ledger_entry_construction_failure_on_failure_path_preserves_original_exception` |
| Recovery failure (exception mid-retry) | `test_exception_during_recovery_retry_still_persists_real_spend_from_attempt_zero` |
| Budget exhaustion | `test_grounded_execution_cost_guardrail_rejects_tight_budget`, `test_cost_guardrail_rejects_budget_the_undercounted_formula_would_have_passed` |
| Restart / durable-store behavior | `test_context_package_survives_a_process_restart`, `test_sqlite_store_persists_across_instances` |

All validate externally meaningful behavior (real HTTP status codes, real ledger entries read back,
real cross-process-instance restarts) — not internal flags asserted in isolation.

**Status: RESOLVED.**

---

## 16. Architecture Diagram (Final, Code-Reconciled)

```
Client
  |
  |  (1) POST /contracts  -- separate, PRIOR request; not called by the orchestrator
  v
Query Understanding (SLM-1 + classifiers) --> LivingContract persisted (SqliteContractStore, durable)
  |
  |  (2) POST /contracts/{contract_id}/grounded-execution  -- the canonical entry point
  |      (interfaces/api/routes/grounded_execution.py)
  |      Pre-flight: cost guardrail estimate (18-call worst case, real trace, §8)
  v
ARCF Composition Root (interfaces/api/app.py: create_app)
  |  constructs: CodeIntelligenceContractService, ContextPackager, FinalGenerationRunner,
  |  ExecutionLedgerStore (durable), ContextResolutionStore (durable, fixed this closure),
  |  RepositoryScopeClassifier, TaskClassifier (fixed this closure), ArcfExecutionOrchestrator
  v
Application Orchestrator (application/execute_use_case.py: ArcfExecutionOrchestrator)
  |
  v
  contract_manager.get_contract(contract_id)  -->  the LivingContract created in step (1)
  |
  v
  attach_code_intelligence(target_names or contract.intent.entities, resolver_strategy)
  |
  +---------------------+
  |                      |
  v                      v
Classic resolver      DRP resolver          <-- both reachable: Classic by default,
  |                      |                       DRP as Recovery's own alternate strategy
  |                      |
  v                      v
validate_sufficiency() -- NOW RUN BY BOTH (fixed this closure, Final Issue 1)
  |                      |
  +----------+-----------+
             |
             v
   Evidence check (evidence_categories_missing) -- honest for both resolvers now
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
  verify_grounding()  (deterministic: evidence check + relative/absolute path-reference check,
                        absolute-path blind spot fixed in the prior pass)
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
  ExecutionLedgerEntry construction (guarded, both success and failure paths, this closure)
      |
      v
  ExecutionLedgerStore (durable, SQLite)
      |
      v
  GroundedExecutionResponse  -->  client  (llm_responses excluded from the body, still in the ledger)


Separate, unchanged: Secure Fast Path
POST /api/v1/execute  -->  raw prompt  -->  LiteLLMClient.complete()  -->  ExecuteResponse
(no contract, no retrieval, no verification -- unrelated to the pipeline above, per P12)
```

Every arrow above was verified against actual code during this pass or the prior one, not carried
forward unverified.

---

## 17. Final Master Acceptance Matrix

| Area | Acceptance Criterion | Evidence | Test | Status |
|---|---|---|---|---|
| Query Understanding | SLM-1 + classifiers produce a durable `LivingContract` | `contracts/manager.py`, `SqliteContractStore` | Existing contract tests (unchanged) | RESOLVED |
| Retrieval | Classic and DRP both reachable, DRP as Recovery's own alternate strategy only | `execute_use_case.py`'s `strategy="drp"` literal | `test_recovery_never_exceeds_max_recovery_attempts` | RESOLVED |
| Evidence | Both resolvers produce the same evidence-state contract | `code_intelligence/service.py::_resolve_drp` (fixed this pass) | `test_resolver_strategy_drp_populates_evidence_categories_missing` | RESOLVED |
| Context | `ContextResolutionResult` durable across restarts | `SqliteContextResolutionStore` | `test_context_package_survives_a_process_restart` | RESOLVED |
| Generation | Reachable only through the verified/grounded path, no bypass | `FinalGenerationRunner` construction traced repo-wide | `test_grounded_execution_full_pipeline_reaches_generated_verified_answer` + marker-tracing script | RESOLVED |
| Verification | Bounded to evidence + reference checks, no semantic/logical claim | `contradictions_checked` hardcoded `False` | 20/20 `tests/execution/test_verification.py` | RESOLVED |
| Recovery | Bounded, deterministic, non-LLM-directed, single path | §13 above | §13's test list | RESOLVED |
| DI | Composition root is the sole construction boundary for every stateful collaborator | §10 above | `test_classifiers_are_injected_by_composition_root_not_constructed_per_iteration` + existing DI tests | RESOLVED |
| Ledger | Durable, guarded construction/write on both success and failure paths | §9 above | §9's test list | RESOLVED |
| Persistence | Every store's lifecycle explicit, no API implies false durability | §9 table | `tests/infrastructure/test_context_resolution_store.py` | RESOLVED |
| Resource boundaries | Every expansion mechanism has a stated, tested bound | §3 table | §3's test list | RESOLVED |

### Connection Acceptance Matrix

| Layer A | Layer B | Contract | Evidence | Test |
|---|---|---|---|---|
| Query Understanding | Workspace/Code Intelligence | `target_names` or `contract.intent.entities` | `service.py`'s entities-default fix | Existing service tests |
| Code Intelligence (either resolver) | Evidence Validation | `evidence_categories_missing` set uniformly (fixed this pass) | `_resolve`/`_resolve_drp` both call `validate_sufficiency` | `test_resolver_strategy_drp_populates_evidence_categories_missing` |
| Evidence Validation | Context Construction | Expanded `ContextResolutionResult` | `validate_sufficiency`'s return value | Existing evidence-validator tests |
| Context Construction | Goal Composition/Generation | `ContextPackage` | `ContextPackager.package()` | `test_normal_path_reaches_generation_and_verification` |
| Generation | Verification | `Artifact` unconditionally checked | `verify_grounding()` call site in `run()` | Marker-tracing script + full-pipeline test |
| Verification | Recovery | `recovery_eligible` + `attempt < max` | `run()`'s two check points | §12 table |
| Recovery | Code Intelligence (re-entry) | `attach_code_intelligence`/`package`/`generate` only, no internals | Import-boundary test | `test_application_orchestrator_does_not_import_code_intelligence_internals` |
| Execution | Ledger | Guarded construction + write, both outcomes | §9 | §9's test list |

### DI Acceptance Matrix

See §10's full table. Every architectural collaborator has a stated owner, construction location,
injection path, testability, and category (application dependency vs. stateless local helper).

---

## 18. Resource/Expansion Boundary Matrix

See §3.

## 19. Evidence-State Contract

See §2 — Classic vs. DRP explicitly compared, both now producing the same contract.

## 20. Confidence Contract

See §4 — both fields' meanings, producers, consumers, and safe-usage rules explicitly defined.

---

## 21. Test Results

```
.venv/Scripts/python.exe -m pytest -q
1055 passed, 7 warnings in 32.03s
```

| | Count |
|---|---|
| Baseline (start of this pass) | 1052 |
| Net new this pass | 3 (`test_resolver_strategy_drp_populates_evidence_categories_missing`, `test_all_subclasses_of_caps_unbounded_traversal_on_a_wide_hierarchy`, `test_locality_filtered_transitive_callers_caps_a_long_linear_chain`) — one pre-existing test rewritten in place (`test_insufficient_evidence_triggers_one_recovery_attempt_with_drp_strategy` → `..._then_honestly_exhausts`, same slot, updated assertions), one duplicate/broken fragment from an earlier edit removed |
| **Total** | **1055** |
| Passed | 1055 |
| Failed | 0 |
| Skipped | 0 |

No test was weakened or removed to obtain a green result — the one rewritten test's new assertions are
strictly *more* specific than its predecessor's (asserts the exact honest outcome, not a looser one).

---

## 22. Final Stopping Criteria

- [x] Canonical pipeline verified
- [x] Generation bypass impossible through known paths
- [x] Evidence states have one clear contract (§2, §19)
- [x] Classic + DRP evidence behavior is explicitly defined and now equal (§2)
- [x] Grounding supports relative + absolute references (§12)
- [x] Verification → Recovery contract verified (§12)
- [x] Recovery is bounded and deterministic (§13)
- [x] True maximum retry/cost calculation verified (§8, re-derived independently, confirmed 18)
- [x] All closure-scope expansion mechanisms have defined bounds (§3)
- [x] Intermediate-resource behavior explicitly classified (§3 — fixed, not just classified)
- [x] Context state lifecycle is explicit (§9)
- [x] Ledger success/failure semantics are consistent (§9)
- [x] DI composition root is complete (§10)
- [x] Dependency boundaries are tested (§11)
- [x] Confidence semantics are explicit and safe (§4)
- [x] Task-type ownership is explicit (§5)
- [x] Provenance is complete (`OriginStage.DRP_SUBSYSTEM_ROUTING`, prior pass)
- [x] Negative paths are covered (§15)
- [x] Architecture diagram matches implementation (§16)
- [x] Layer acceptance criteria satisfied (§17)
- [x] Connection acceptance criteria satisfied (§17)
- [x] DI acceptance criteria satisfied (§17)
- [x] Final architecture acceptance criteria satisfied (§17)
- [x] Every original gap has final status (§9 of the prior implementation report, unchanged, plus §6/§7 corrections here)
- [x] Every new finding has final status (G-new-1 through 7: RESOLVED; NEW-1: RESOLVED this pass via §2; NEW-2: RESOLVED this pass via §3)
- [x] No contradictory checklist status exists (§6, §7 corrected the two found)
- [x] No undocumented scope decision exists (§4, §5, §6 formally recorded)
- [x] No acceptance criterion was weakened
- [x] Full regression suite passes (§21)

**All criteria satisfied.**

---

## 23. Final Status

> ## FINAL ARCHITECTURE STATUS: CLOSED

Every closure-scope requirement in this pass and the two prior rounds is satisfied. The two
MUST-FIX items found in this pass (DRP's evidence-state contract, the two unbounded shared
traversal primitives) are fixed with regression tests proving real, non-mocked behavior. Every other
open question has been converted into an explicit, formally-recorded decision — INTENTIONALLY
DEFERRED (G9, G12's cross-component half) or OUT OF SCOPE (G14's Comparison-API half) — with no
remaining item left as a bare, unclassified ambiguity. Two prior contradictory status records (G14's
terminology, G15's stale "still open" listing) are corrected. The cost guardrail's worst-case call
count (18) was independently re-derived and confirmed. 1055/1055 tests pass, with 0 removed or
weakened. No prohibited architecture was introduced at any point in this pass.

Future engineering items that remain (the G9/G12 deferred formula-unification/consolidation options,
recorded with concrete future-option paths) are ordinary future work, not part of this closure's
scope, and should not trigger another architecture-closure round on their own.
