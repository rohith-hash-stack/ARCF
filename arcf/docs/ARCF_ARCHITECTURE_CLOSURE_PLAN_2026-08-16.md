# ARCF Architectural Closure — Reconstruction & Plan

**Status:** Analysis complete. No code changed yet. This is the single implementation plan for
approval — not a per-layer approval request.
**Relationship to prior doc:** builds on `ARCF_ARCHITECTURE_AUDIT_DISCOVERY_2026-08-16.md` (19
numbered gaps, full acceptance-matrix draft). This document goes one level deeper — precise
consumer-reach verification, confidence inventory, the Retrieval→Evidence→Context path, the three
failure-state cases, and concrete, code-grounded placement for Verification and Recovery — then
closes with one unified plan.
**Governing constraint carried through every decision below:** Verification and Recovery are
scoped narrowly per your authorization — deterministic where possible, evidence-based, bounded,
structured, no LLM-directed control flow, no unbounded loops, no new parallel pipeline.

---

## A. Actual current architecture (not the intended one)

```
POST /contracts                    ExecutionContractManager.create_contract
                                    SLM-1 → RawIntentExtraction → ConfidenceSignals → UserIntent
                                    persisted as Contract.intent
                                         │
                                         │  (client must read the response and manually
                                         │   construct the next request)
                                         ▼
POST /contracts/{id}/code-intelligence   CodeIntelligenceContractService.attach_code_intelligence
                                          target_names = CLIENT-SUPPLIED (NOT contract.intent.entities)
                                          → ContextResolutionResult persisted
                                         │
                                         │  (client must read the response, extract nothing —
                                         │   the next call only needs contract_id)
                                         ▼
POST /contracts/{id}/context-package     ContextPackager.package(...)
                                          → ContextPackage RETURNED DIRECTLY TO CLIENT.
                                            Nothing server-side consumes it further.
                                          ═══════════ PIPELINE ENDS HERE ═══════════

POST /api/v1/execute                     llm_client.complete(payload.prompt, ...)
                                          — payload.prompt: raw string, no contract_id field,
                                            no context_package field. Cannot reach the above.
                                          ═══════════ UNRELATED, PARALLEL PATH ═══════════
```

Real, tested code exists that would bridge the gap between the two blocks above
(`execution/context_goal_composer.py` + `execution/final_generation.py`) — it is simply never
called by anything in `src/interfaces/`. No route, no dependency wiring, nothing in
`src/application/` (a 5-line stub) ever constructs it.

---

## B. Stage-by-stage status (per your requested classification)

| # | Stage | Real implementation | Status |
|---|---|---|---|
| 1 | Entry Point | 4 separate HTTP routes, no unifying entry | **IMPLEMENTED BUT DISCONNECTED** — no single entry point exists; `/execute` and the contract/code-intelligence/context-package trio are structurally unrelated |
| 2 | Orchestration | `application/__init__.py` — 5-line stub | **NOT IMPLEMENTED** — `execute_use_case.py`, named by the codebase's own docstrings as the missing piece, does not exist |
| 3 | Query Understanding | `contracts/manager.py` + SLM-1 + 2 classifiers + `ConfidenceEngine` | **PARTIALLY IMPLEMENTED** — computes real, corroborated intent; only 2 of 11 `UserIntent` fields (`raw_request`, `clarifications`) are ever read again |
| 4 | Repository Intelligence | `code_intelligence/engine.py` + graphs; DRP subsystem (`code_intelligence/drp/`) | **IMPLEMENTED, PARTIALLY DISCONNECTED** — classic graphs fully live; DRP fully built and wired into `service.py` but the one production route never sets `resolver_strategy="drp"`, so it's unreachable |
| 5 | Candidate Generation | `reference_resolver.py` (`resolve_with_disambiguation`) | **IMPLEMENTED** — real, wired, always runs |
| 6 | Resolution/Retrieval | `context_resolver.py` (`ContextResolver.resolve`) | **IMPLEMENTED** — real, wired |
| 7 | Expansion | `locality.py` + `_expand_calls`/`_expand_subclasses` | **IMPLEMENTED, ONE GAP** — call-expansion is token-bounded; subclass-expansion (`_expand_subclasses`) has no budget gate at all |
| 8 | Evidence | `context/evidence_validator.py` (`validate_sufficiency`) | **PARTIALLY IMPLEMENTED** — coverage-of-glob-category checking only, live; content-relevance checking doesn't exist; the file's other half (`prune_experimental_candidates`) is dead code |
| 9 | Ranking | `context/relevance_ranker.py` | **IMPLEMENTED** — real, deterministic, explainable at the "why did this match" level, not at the "why this score" level |
| 10 | Context Construction | `context/packager.py` + `budget_manager.py` + `compressor.py` | **IMPLEMENTED** — the most solid, gap-free layer in the system |
| 11 | Generation | `execution/final_generation.py` + `context_goal_composer.py` | **IMPLEMENTED BUT DISCONNECTED** — correct code, zero callers outside tests/scripts |
| 12 | Verification | — | **NOT IMPLEMENTED, NOT PLANNED** — absent from ARCF's own 11-phase roadmap too |
| 13 | Recovery/Retry | `context/evidence_fallback.py` (inline, single-call only) | **PARTIALLY IMPLEMENTED** — real, bounded, strategy-varying recovery exists but only for the zero-candidate case, only inline within one `resolve()` call, never re-entered after a completed attempt |
| 14 | Final Result | `ExecuteResponse` (bypass path) or raw `ContextPackage` JSON (pipeline path) | **DUPLICATED** — two unrelated "final result" shapes exist, neither is the grounded answer the other three routes' work was for |

---

## C. Layer map — Responsibility / Input / Output / Actual consumer

Only layers with a real consumer-reach question are shown in full; the rest are unambiguous
(consumer confirmed by direct call-site grep in the discovery report).

| Layer | Responsibility | Input | Output | Does the output actually reach the component that needs it? |
|---|---|---|---|---|
| Query Understanding | Turn raw text into structured intent | `raw_request: str` | `UserIntent` (11 fields) | **No, mostly.** Only `raw_request`/`clarifications` reach anything. `entities` — the one field retrieval structurally needs — reaches nothing; retrieval takes `target_names` from the client instead. |
| Repository Intelligence (DRP half) | Deterministic subsystem/vocabulary modeling | `CodeIntelligenceIndex` | `DrpIndex` (TF-IDF, taxonomy, communities) | **No.** Real consumer (`DrpResolver`) exists and works; the API route that would select it never does. |
| Evidence | Evidence-category coverage | `ContextResolutionResult` + task type | `evidence_categories_satisfied/missing` | **Partially.** Reaches `ContextResolutionResult` (survives to the final object) but nothing downstream *acts* on `evidence_categories_missing` — it's reported, never used to gate or retry anything. |
| Ranking | Score and order candidates | `ContextResolutionResult` | `list[RankedFile]` | **Yes**, fully — this connection (Ranking → Context) is the one with zero confirmed gaps. |
| Context Construction | Budget-bounded packaging | `list[RankedFile]` | `ContextPackage` | **No**, past this point — the HTTP route returns it to the client and nothing server-side reads it again. |
| Generation | Ground a prompt, call the LLM | `ContextPackage` | `Artifact` | **N/A — never invoked in production at all.** |

**The central finding, stated once: it is not that layers 11–13 (Generation/Verification/Recovery)
have broken *contracts* — Generation's contract with Context Construction is fine (`Context
GoalComposer.compose` genuinely reads `ContextPackage.relevant_files`/`.dependency_chain`
correctly). The problem is that nothing calls Generation at all in the deployed system.** This
reframes "add Verification/Recovery" as fundamentally dependent on "build the orchestrator" —
you cannot attach Verification to a call chain that doesn't reach the point Verification needs to
observe.

---

## D. Communication map (the connections that matter for closure)

```
Contract.intent.entities ────────X (never read)───────▶ attach_code_intelligence(target_names=...)
                                                          [client supplies target_names manually today]

ContextResolutionResult.evidence_categories_missing ──X (computed, never consumed)──▶ nothing

ContextPackage ───────────────────X (route returns it, nothing calls further)───────▶ Generation
                                                          [execution/context_goal_composer.py
                                                           WOULD consume it correctly if called]

Artifact (generation output) ─────X (doesn't exist as a live object)────────────────▶ Verification
                                                          [nothing computes this today]

(no verification exists) ─────────X──────────────────────────────────────────────────▶ Recovery

ExecutionLedgerEntry contract ────✓ (fully defined)──X (no production writer)────────▶ Ledger store
```

Every `X` above is closed by the same root fix: **build the orchestrator, then thread the two
already-computed-but-discarded signals (`entities`, `evidence_categories_missing`) through it.**

---

## E. Information-loss map (the 17 items you named)

| Item | Created | Transformed | Consumed | Lost where | Intentional or gap? |
|---|---|---|---|---|---|
| Query entities | SLM-1 (`intent_extraction.py`) | — | Nowhere | Between `UserIntent` and `attach_code_intelligence` | **Gap** — no doc anywhere says this is deliberate |
| Query intent/task | SLM-1 + classifiers | Re-derived independently 3× instead of reused | `retrieval_task_type`, `ranking_profile` (both re-derived, not sourced from `contract.intent.task`) | Between `UserIntent.task` and every retrieval-time consumer | **Gap** — duplicated computation, not documented as intentional |
| Query constraints/assumptions | SLM-1 | Feed `ConfidenceSignals` only | Nowhere else | Immediately after contract creation | **Likely intentional** — no consumer was ever designed for these; not flagged anywhere as a bug, but also not documented as "deliberately terminal" |
| Repository vocabulary (DRP TF-IDF/PMI) | `drp/tfidf.py`, `pmi_expansion.py` | `DrpIndex` | `DrpResolver` (real, works) | Between `DrpResolver` and the live API (never selected) | **Gap** — real consumer exists, just unreachable |
| Repository subsystem info | `drp/subsystem_graph.py`, `taxonomy.py` | `DrpIndex.taxonomy` | `query_router.py` (real) | Same as above | **Gap**, same root cause |
| Candidate provenance | `context_resolver.py._add_file` | `FileReference.origin_stage` | `RankedFile`, `PackagedFile` | 2 real paths (`evidence_validator`, DRP) never set it | **Gap** — contradicts the field's own docstring guarantee |
| Retrieval scores | `RelevanceRanker._score` | `RankedFile.relevance_score` | `ContextBudgetManager` | Component breakdown (role/entry/impact/confidence factors) never survives past the local function scope | **Gap** for explainability (RK-7); not a functional loss |
| Structural relationships | `locality.py`, `call_graph.py` | `justification_chain` | `RankedFile`, `PackagedFile` | Not lost — this one survives cleanly | **No gap** |
| Evidence (category coverage) | `evidence_validator.validate_sufficiency` | `evidence_categories_missing` | Nobody | After being written onto `ContextResolutionResult` | **Gap** — computed, never acted on |
| Confidence (all 8 signals) | Multiple, independent | Multiplied/blended in `RelevanceRanker`; separately, 2 formulas write the same `.confidence` field | Ranking (blended), nobody (unblended per-factor) | Individual factor contributions after `_score` multiplies them | **Gap** — real conflation, see §F |
| Ranking information | `RelevanceRanker` | `RankedFile` | `PackagedFile` (`relevance_score`, `reason`) | Not lost — survives to `ContextPackage` | **No gap** |
| Context provenance | `ContextPackager` | `PackagedFile.reason`/`token_count` | Nobody past the HTTP response | After `POST /context-package` returns | **Gap** — same root cause as Generation disconnection |
| Generation result | — | — | — | Doesn't exist in the live system | **Gap** (the central one) |
| Verification result | — | — | — | Doesn't exist | **Gap**, newly authorized to close |
| Failure reason | `LLMInvocationError`, `ContractNotFoundError`, etc. (transport/validation only) | — | HTTP 4xx/5xx | No *semantic* failure reason (insufficient evidence, ungrounded generation) exists anywhere | **Gap** — the vocabulary exists for transport failures (`shared/errors.py`), not for evidence/grounding failures |
| Retry state | — | — | — | Doesn't exist beyond `LiteLLMClient`'s transient-error attempt counter | **Gap**, newly authorized to close (narrowly) |

---

## F. Confidence inventory (full, consolidated)

| # | Signal | Producer | Meaning | Range | Real consumer | Decision it influences |
|---|---|---|---|---|---|---|
| 1 | `ContextResolutionResult.confidence` (classic) | `context_resolver.py` — `resolved_count/total_targets` | Fraction of target names that resolved to ≥1 symbol | 0–1 | Carried on the result object; grep found no downstream reader | None currently |
| 2 | `ContextResolutionResult.confidence` (DRP) | `drp/query_router.py` — margin-based subsystem-routing score | Confidence the query routed to the right subsystem | 0–1 | Same field as #1, different formula, no provenance marker | None currently (and unreachable, per DRP gap) |
| 3 | `FileReference.anchor_confidence` | `anchor_classifier.py`, tier-based + hop decay | Confidence in an experimental anchor-tier match | 0–1 or `None` | `RelevanceRanker._score` (multiplied in) | Ranking score, only when the experimental flag is on (never, in production) |
| 4 | `FileReference.ambiguity_confidence` | `context_resolver.py` — `1/log2(matches+1)` | Penalty for a same-named symbol being ambiguous | 0–1 | `RelevanceRanker._score` (multiplied in); also carried onto `RankedFile` | Ranking score, always active |
| 5 | `FileReference.path_mask_confidence` | `context_resolver.py` | Penalty for a match that ignored a query path hint | 0.15 or `None` | Same as #4 | Ranking score, always active |
| 6 | `contracts/confidence.py` `ConfidenceEngine` output | Weighted sum over 7 intent-understanding signals | Confidence the SLM-1 intent extraction is trustworthy | 0–1 | `UserIntent.confidence` — never read again | Nothing downstream (`ClarificationPlanner` uses the *inputs* to this score, not the score itself) |
| 7 | `infrastructure/telemetry.py` `ConfidenceLabel` | Derived from `OriginStageBreakdown` | 3-way: empty / low-confidence-nonempty / confident | categorical | Nobody — `TelemetryCollector` has zero production callers | None |
| 8 | `evidence_categories_missing` (arguably confidence-adjacent — "how complete is the evidence") | `evidence_validator.validate_sufficiency` | Which required evidence categories weren't found | set of category names | Survives onto `ContextResolutionResult`; nobody acts on it | None currently — **this is the one signal the closure plan below finally wires to a decision** |

**Per your instruction not to blend these mathematically:** the closure plan does not introduce a
combined confidence score. #4/#5 stay inside ranking exactly as today (already-shipped, already
tested). #8 gets a new, narrow consumer (the recovery decision point). #1/#2's cross-formula
conflation is flagged as a pre-existing bug worth a one-line fix (tag which formula produced the
value) but is **not** required for this closure and is listed under "remaining gaps," not built now
— it doesn't block Verification/Recovery and touches a field read by nothing today.

---

## G. The Retrieval → Evidence → Context path — which shape is it really?

**Confirmed: it is the second shape you described.**

```
Candidates ──▶ Ranking ──▶ Context
                              ▲
Evidence ─────────────────────┘  (exists separately, merges only via evidence_tier,
                                   which affects COMPRESSION policy in ContextBudgetManager,
                                   never the ranking SCORE itself)
```

`RelevanceRanker._score` (`relevance_ranker.py`) never reads `FileReference.evidence_tier`. It's
read later, only by `ContextBudgetManager`, to decide compression aggressiveness (PRIMARY gets
priority packing, SUPPORTING/EXPERIMENTAL get compressed harder) — not to influence *which*
candidates rank higher. Similarly, `evidence_categories_missing` is computed and attached to the
result object but never feeds ranking or packaging decisions at all.

**How to integrate evidence without a duplicate retrieval system (your explicit constraint):** do
not add a new evidence-aware ranking pass. Instead, add exactly one new decision point that reads
`evidence_categories_missing` (already computed, already correct) **before** generation is
attempted — this is the natural, minimal integration point, not a new scoring dimension inside
`RelevanceRanker`. Ranking stays exactly as accurate/inaccurate as it is today; evidence sufficiency
becomes a gate on whether to proceed to generation or take the one allowed recovery attempt first.

---

## H. The three failure states — what the current code can and can't distinguish

| Case | Definition | Detectable today? | With what field? |
|---|---|---|---|
| **A** — Empty retrieval | Zero candidates for all target names | **Yes, and already recovered from automatically**, inline, within one `resolve()` call: `symbol_resolution_found_nothing` gates `expand_with_evidence` (3 widening tiers) then lexical-probe recovery. Real, bounded, strategy-varying — exactly what Recovery is supposed to look like, just scoped to this one case and never re-entered after the fact. | `not result.candidate_files` |
| **B** — Candidates exist, evidence insufficient | Non-empty `candidate_files`, non-empty `evidence_categories_missing` | **Yes, detectable** — but nothing today acts on it. This is a real, distinct, already-computed signal with zero consumers. | `result.evidence_categories_missing` |
| **C** — Evidence exists, generation ungrounded | Generation produced an artifact that references files/symbols never actually retrieved | **No — cannot be detected today**, because Generation never runs in production (nothing to check). Once Generation is wired in (this closure), a **deterministic** check is possible: does `Artifact.content` reference a file path not present in `ContextPackage.relevant_files`? This is text/path matching, not semantic understanding. | New — built as part of this closure, see §J |

**Per your explicit instruction not to collapse these into `retrieval_failed = true`:** the closure
plan keeps A/B/C as distinguishable triggers feeding the *same* bounded recovery mechanism (§K),
not merged into one boolean. A is already handled inline and needs no new code. B and C both route
through the new orchestrator's single recovery decision point, each tagged with its own reason.

---

## I. Verification — minimum architectural responsibility (answered from the code, not theory)

**What the current architecture can actually support, deterministically, today:**

1. **"Was evidence available?"** — Yes. `result.candidate_files` non-empty.
2. **"Was required evidence missing?"** — Yes. `result.evidence_categories_missing`, already
   computed by `evidence_validator.validate_sufficiency`, already correct, already tested. Zero new
   logic needed — just a new reader.
3. **"Does the generated result contain claims unsupported by available evidence?"** — Partially,
   and only in a narrow, honest sense: whether `Artifact.content` references a **file path** that
   isn't in `ContextPackage.relevant_files`. This is a deterministic string/path check (extract
   `` `path/to/file.py` ``-shaped tokens from the completion text, compare against the packaged file
   set), not a semantic claim-by-claim fact-check. It catches the clearest, cheapest form of
   ungrounded output (referencing a file that was never retrieved) and nothing subtler.
4. **"Does it contradict available evidence?"** — **No. The repository does not currently support
   this**, and per your instruction, this plan does not invent it. No NLI model, no embeddings
   (prohibited by the freeze), no LLM-judge (out of scope per your narrow authorization). The
   `VerificationResult` contract below carries an explicit `contradictions_checked: bool = False`
   field — not a fabricated always-true field, not silently omitted, a documented "this is not
   supported today."

**Where it naturally belongs, from the code:** `execution/` already houses the two other
post-retrieval, pre-orchestration modules (`context_goal_composer.py`, `prhl.py`) that follow the
exact "small, structured, degrades safely, never blocks" pattern this needs. A new
`execution/verification.py` sibling module, called immediately after `FinalGenerationRunner.
generate()` returns, is the placement the codebase's own package boundaries already imply — not a
new top-level concept.

### Proposed contract (naming follows the codebase's own conventions, not the brief's example names)

```python
# domain/verification_result.py — new, separate name from the existing
# domain.execution_ledger.VerificationResult (build/test pass-fail) to avoid
# exactly the same-field-name-different-meaning conflation this audit already
# flagged for ContextResolutionResult.confidence.

class GroundingVerificationResult(BaseModel):
    status: Literal["sufficient", "insufficient_evidence", "unsupported_references"]
    evidence_sufficient: bool                    # from evidence_categories_missing == ()
    missing_evidence_categories: tuple[str, ...]  # = result.evidence_categories_missing, verbatim
    unsupported_file_references: tuple[str, ...]  # file paths in Artifact.content not in ContextPackage.relevant_files
    contradictions_checked: bool = False          # explicit: not supported today
    recovery_eligible: bool                       # status != "sufficient" and attempts remain
```

---

## J. Recovery — minimum capability, from the code, reusing what exists

**The single most important design decision, grounded directly in the code:** ARCF already has a
second, structurally complete, independently-tested resolution mechanism —
`resolver_strategy="drp"` — that is genuinely different (TF-IDF/subsystem-taxonomy-based, not
symbol-name-based), not a parameter tweak of the same algorithm. It is currently unreachable from
the live API (Gap G12 in the discovery report). **Recovery's one allowed alternate strategy is:
re-invoke the same orchestration call with `resolver_strategy="drp"` instead of `"classic"`.**

This single choice satisfies every constraint you listed:
- **Reuses an existing mechanism** rather than inventing one (your instruction #2/#11).
- **Genuinely different, not a blind repeat** (RC-2) — a different resolution algorithm entirely,
  not the same one retried.
- **Deterministic** — no LLM decides anything; the orchestrator's own fixed control flow picks it.
- **Re-enters through the existing orchestration boundary** (`attach_code_intelligence`'s own public
  method signature) — Recovery never touches `ContextResolver`/`CallGraph`/index internals directly
  (your instruction #14).
- **Closes a second gap as a side effect, not a coincidence** — DRP finally gets a real production
  consumer, which was already independently flagged (RI-5, CG-1, FA-3) as needing one. This is what
  "one coherent closure" looks like in practice: the same fix serves two previously-separate
  findings.

### Trigger, bound, re-entry, exhaustion

```
MAX_RECOVERY_ATTEMPTS = 1   # fixed, configured, not adaptive — your instruction #13

attempt = 0
strategy = "classic"

loop:
    living, resolution = attach_code_intelligence(contract_id, target_names, workspace_root,
                                                    resolver_strategy=strategy)
    package = ContextPackager.package(resolution, raw_request, max_tokens, ranking_profile)

    # Case B check — BEFORE spending an LLM call
    if resolution.evidence_categories_missing and attempt < MAX_RECOVERY_ATTEMPTS:
        attempt += 1; strategy = "drp"; continue

    artifact, completion = FinalGenerationRunner.generate(living.contract, package, resolution)
    verification = verify_grounding(artifact, package, resolution)   # Case C check

    if verification.status != "sufficient" and attempt < MAX_RECOVERY_ATTEMPTS:
        attempt += 1; strategy = "drp"; continue

    break

final_status = "success" if verification.status == "sufficient" else "low_confidence"
# persist ExecutionLedgerEntry — real, already-shaped contract, finally gets a writer
# (execution_status="success", metadata={"recovery_attempts": attempt, "strategy_used": strategy, ...})
return artifact, verification, final_status   # NEVER silently reports success on exhaustion
```

**One shared attempt counter across both trigger points** (evidence-insufficiency and
verification-failure), not one budget per stage — this is deliberate, per your instruction that
total recovery must stay bounded regardless of which check fires. Worst case: 1 retry, 1 extra LLM
call, ever, per request.

**What Recovery explicitly does NOT do** (per your prohibited list, restated as concrete non-events
in this design): no LLM is asked whether to retry; no LLM chooses the strategy (`strategy = "drp"`
is a hardcoded literal in application code); no loop can exceed `MAX_RECOVERY_ATTEMPTS`; Recovery
never imports `ContextResolver`, `CallGraph`, or any index-internal module — it only calls the same
three already-public methods (`attach_code_intelligence`, `package`, `generate`) the three existing
HTTP routes already call individually.

**Where it belongs, from the code:** nowhere close to existing — this control flow requires an
orchestrator that doesn't exist. It belongs in `application/execute_use_case.py`, exactly where
`interfaces/api/routes/execution_ledger.py`'s own docstring and `ARCF_v2.3_ARCHITECTURE_REVIEW.md`
§6 already say the missing piece goes. Not a new architectural concept — the reserved, empty stub
this project already scaffolded for exactly this purpose.

---

## K. Why this must be one closure, not five phases (grounded in the dependency chain itself, not methodology preference)

1. Verification cannot be attached to anything until Generation is reachable — there's no live
   `Artifact` to check.
2. Generation cannot be reached without an orchestrator — no route calls it today.
3. Recovery cannot exist without Verification's structured failure reason (or the pre-generation
   evidence check) — there's nothing to recover *from* yet.
4. The orchestrator cannot correctly call retrieval without also fixing the entities gap (G1) — the
   whole point of building it is to finally connect `contract.intent.entities` to `target_names`,
   otherwise the new orchestrator would just re-implement the same disconnect the discovery report
   already found.

These four are one dependency chain, not four independent features. Building the orchestrator *is*
simultaneously: the Generation fix, Verification's prerequisite, Recovery's home, and the natural
place to finally read `contract.intent.entities`. There is no ordering that lets any of these ship
independently and still be correct — which is exactly why the original docx's "Phase 1 → Retrieval,
Phase 2 → Ranking..." framing produced the disconnects this audit found in the first place.

---

## L. Unified implementation plan (one closure — presented once, for one approval)

**New files:**
- `src/application/execute_use_case.py` — the orchestrator (§J's control flow), the one new
  top-level coordination point. Exposes `run(contract_id, target_names, workspace_root, model,
  max_tokens) -> tuple[Artifact, GroundingVerificationResult, ExecutionStatus]`.
- `src/execution/verification.py` — `verify_grounding(artifact, package, resolution) ->
  GroundingVerificationResult` (§I). Pure function, deterministic, no I/O beyond string parsing.
- `src/domain/verification_result.py` — `GroundingVerificationResult` (§I).
- `src/interfaces/api/routes/execute_pipeline.py` (or extend `contracts.py` with one new route,
  naming TBD at implementation time) — `POST /contracts/{id}/execute` — the one new HTTP entry
  point that actually calls the orchestrator end to end. `/api/v1/execute`'s existing raw-prompt
  behavior is left untouched (it's Phase 2's own documented, independent Secure Fast Path — not
  part of this closure, no reason to remove working functionality per your "don't unnecessarily
  break existing behavior" standing rule).

**Changed (additive only, no existing contract broken):**
- `src/code_intelligence/service.py` — `attach_code_intelligence`'s `target_names` handling: when
  the caller passes an empty list (or a new explicit sentinel), default to
  `contract.intent.entities`. Existing callers that pass their own `target_names` are byte-identical
  unaffected — this is strictly additive, closing G1 without changing the method's existing
  contract for any current caller.
- `src/infrastructure/execution_ledger_db.py` / `interfaces/api/routes/execution_ledger.py` — no
  contract change; the orchestrator becomes a real caller of the store's existing `save()`, closing
  G14 by finally using code that already exists.

**Explicitly NOT changed:** `RelevanceRanker`, `ContextBudgetManager`, `ContextResolver`,
`locality.py`, `evidence_fallback.py`, `evidence_validator.py`'s existing behavior, `DrpResolver`,
any language analyzer, any existing route's existing behavior. This closure is additive orchestration
plus two narrow, backward-compatible extension points — not a rewrite of any already-working layer.

**Build order** (your §24 ordering, applied):
1. `GroundingVerificationResult` contract (`domain/verification_result.py`) — no behavior yet.
2. `attach_code_intelligence`'s additive `target_names` default-from-entities change — testable in
   isolation against existing tests (must stay green unchanged).
3. `verify_grounding()` — pure function, unit-testable against hand-built `Artifact`/`ContextPackage`
   fixtures before anything calls it for real.
4. `execute_use_case.py`'s orchestration loop (§J) — wires steps 1–3 plus the existing
   `attach_code_intelligence`/`package`/`generate` calls together. This is where Generation first
   becomes reachable — the core fix.
5. `ExecutionLedgerEntry` writer call inside the orchestrator — no store/schema change, just the
   first real caller.
6. New HTTP route wiring the orchestrator to the API.
7. Tests (see §M) — unit (verification logic, recovery-loop branching with mocked sub-calls),
   contract (orchestrator's own input/output shapes), integration (real Consul-style workspace,
   real recovery trigger on a deliberately evidence-thin query), architecture-boundary
   (`execute_use_case.py` never imports `ContextResolver`/`CallGraph` directly — a static-import
   test, same pattern already used for PRHL's own non-interference guarantee in
   `test_context_goal_composer.py`), end-to-end (contract → orchestrator → grounded artifact,
   real workspace, no mocks).

---

## M. Acceptance criteria to verify at completion (template — filled in after implementation, not now)

**Control-flow acceptance** (your §20): each of the 4 named paths (normal / empty-candidate /
insufficient-evidence / verification-failure) plus exhaustion must be exercised by a real test with
a real workspace, not asserted from code reading alone.

**Recovery-specific acceptance:** attempt count never exceeds 1 in any test scenario, including one
deliberately constructed to fail both checks; exhaustion always yields `"low_confidence"`, never
`"success"`; `strategy` literal is never anything other than `"classic"`/`"drp"` — no dynamic
strategy construction.

**Boundary acceptance (BC-1…BC-8, your §21):** applied specifically to the two new connections this
closure creates (Context→Generation, Generation→Verification) and the one it repairs
(QueryUnderstanding→Retrieval via entities) — the other connections are unchanged and keep whatever
status the discovery report already established for them.

Full matrices (layer, connection, control-flow, final-architecture) will be produced as part of the
final report once implementation is complete and tested against real data — not fabricated ahead of
the work existing.

---

## N. What stays explicitly out of scope (unchanged from the freeze, restated for this closure)

Embeddings, vector databases, semantic/probabilistic retrieval, LLM-based file ranking, learned
retrieval weights, cross-session memory, unbounded or LLM-directed retry, autonomous agent loops,
forced response schema on the final generation call, contradiction/semantic-claim verification
(§I item 4 — explicitly not built, explicitly not faked). This closure does not touch
`RelevanceRanker`'s scoring formula, does not add a combined confidence score, and does not build a
second retrieval pipeline.

---

## O. Ready to implement

Everything above is analysis; nothing has been coded. Per your instruction, I'm not asking for
per-layer sign-off — this is the one plan. If this matches what you want closed, say so and I'll
build it in the order in §L, running the existing test suite after each step to confirm zero
regressions before moving to the next, and report back using the format in your §26 once done.
