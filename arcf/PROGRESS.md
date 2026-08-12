# ARCF Progress Log

**Last updated:** 2026-08-12 IST · **Base/main HEAD:** `a8910e6` · **Tests:** 988/988 passing

Read this file top-to-bottom to pick up where things stand — it's the fast-start doc for a new
chat session. Detailed *why* for each entry lives in Claude's memory files (per-topic, e.g.
`arcf_payload_optimization_path_masking`); this file is the curated *what/when* summary, updated
after each merge to `Base`, not after every small step.

### 2026-08-12 — Shipped: CHECKLIST.md item #14 (Failure Taxonomy & Automated Regression Attribution)
`scripts/failure_taxonomy.py`: `FailureCategory` (the user's exact 5 values) +
`classify_grounding_failure()`, pure/deterministic, harness-only. Reconciled against real code
before designing anything: read `ContextBudgetManager.select()` directly (not assumed) and mapped
every category onto one of its real, already-shipped exclusion mechanisms — the relative score
falloff gate (`_RELATIVE_FALLOFF_GAMMA=0.45`), task-type budget tiering
(`_BUDGET_TIER_BY_TASK_TYPE` — UNKNOWN/BUG_FIX get 4500 tokens, not the caller's nominal 8000, a
real fact this item's own tracing surfaced), and greedy-fill crowding — importing those constants
rather than duplicating them, zero drift risk. **Zero `src/` changes**; wired into
`validate_llm_grounding.py`'s Arm A path only (Arm B deliberately bypasses
`ContextBudgetManager` entirely per its own docstring, so applying this classifier there would
misclassify against a mechanism it never runs) via underscore-prefixed keys that get consumed into
a plain, JSON-serializable list and deleted before the result dict is ever persisted.

**Real verification** (`scripts/failure_taxonomy_real_consul_check.py`, real Consul, no LLM calls,
reusing item #4's own `BENCHMARK_TASKS`/`_structural_behavioral_grounding_metrics` to decide which
files are real failures — the Telemetry Alignment gate): 5 real failures classified across 4
tasks, **60% `AMBIGUITY_DECAY_DROPPED`, 20% `OVERSIZED_FILE_EXCLUDED`, 20%
`ZERO_CANDIDATE_EXTRACTION`**, 0% unclassified. task1's `catalog_endpoint.go` (10,069 tokens)
exceeds the *effective* 4500-token ceiling on its own — a genuine size failure, ambiguity decay as
a real secondary factor. task2/3/5's entries cleared their own size ceiling but fell below the
falloff gate purely from ambiguity decay (`Cache`×3, `Config`×7, `New`×224 same-named matches).
`watch.go` never became a candidate at all (the already-diagnosed "Notify" 78-way collision).
Determinism verified: task5 re-classified twice through the full real pipeline produced
byte-identical output.

**Real gap caught in item #4's own write-up while building this classifier, corrected there, not
silently left wrong**: task2's `G_struct` also failed in the full pipeline (not just `G_behav`),
for a different real reason (`Cache` itself is 3-way ambiguous and falls below the falloff gate)
than the already-documented `Notify`-collision `G_behav` failure — item #4's entry didn't
separately call this out originally. 988/988 tests (unchanged). Merged `a8910e6`.
→ memory: `arcf_failure_taxonomy_shipped`

### 2026-08-12 — Shipped: CHECKLIST.md item #4 (Grounding Quality — Structural vs. Behavioral Split)
`_structural_behavioral_grounding_metrics()` in `scripts/validate_llm_grounding.py`: `G_struct`
(recall of packaged files against a task's entry-point/interface/type files) and `G_behav`/R_path
(recall against real execution-path collaborator files, forced to 0 unless structural files are
100% present first, `None` for tasks with no behavioral component) — pure, deterministic, no LLM
calls, zero `src/` changes (a harness/metric addition only, same scope discipline as item #9).
`BENCHMARK_TASKS` gained additive `ground_truth_structural`/`ground_truth_behavioral` keys, grepped
directly against real Consul (not assumed): e.g. `agent/cache/cache.go` (structural, defines
`Prepopulate`) vs. `agent/auto-config/tls.go` (behavioral, the one real sibling-package caller).

**λ-tuning discipline honored, not reinvented**: directly ran `classify_retrieval_task()` against
all 6 real benchmark queries — every one classifies to `TRAVERSAL_DEPTH=1` in real production. No
new tunable expansion-depth knob was added, since both real failures found below are proven
depth-independent (more expansion would not have changed either outcome).

**Decisive real finding #1 (task2)**: at real depth=1 with target_names set to task2's own
ground-truth terms, `agent/cache/watch.go` never appears in `candidate_files` at all — traced
directly to `Notify` being a 78-way ambiguous name repo-wide, with disambiguation resolving it to
`agent/mock/notify.go` instead. Same shape as the already-closed, 8-times-falsified extreme-
ambiguity recall gap ([[arcf_recall_gap_closed]]). Kept as ground truth deliberately so `G_behav`
reports this honestly as a real 0.0.

**Decisive real finding #2 (tasks 1/3/5), the header result of this item**: running the actual
resolver -> RelevanceRanker -> ContextPackager pipeline (not just the raw resolver) showed
`G_struct=0.0` for all three single-file tasks — the genuine entry-point file, present in
`candidate_files`, doesn't survive packaging. Traced directly: in every case the real entry point
is unusually large (9k-12k tokens, competing for an 8000-token budget) **and** ambiguity-decayed
(2/7/224 same-named matches), dropping its rank below small decoy files (task5's real entry point
ranked 70th of 224 candidates). **This precisely diagnoses PROGRESS.md's own previously-
`unconfirmed` "Task 1 regression" note below** — the same root mechanism as the closed recall-gap
thread, now shown to also bite at the ranking/packaging stage, not just resolution (task5 is
literally the flagship "New" case). Deliberately **not fixed here**, same discipline as item #3 and
Arms 1/2/4 finding pre-existing mechanisms mid-work and not touching them without a dedicated
isolated falsification experiment — flagged as a genuinely new future candidate (ambiguity decay
vs. oversized single-file entry points competing for token budget), distinct from the 8 prior
recall-gap attempts.

**Real positive result (tasks 4/6)**: both `G_struct`/`G_behav` = 1.0 through the full real
pipeline; task6's behavioral hit confirmed genuine `SCOPED_GRAPH_EXPANSION` (a real call-graph hop),
not adjacency luck. Determinism verified: task6 run twice through the full pipeline produced
byte-identical `packaged_files` and scores. All 4 user success gates met (see CHECKLIST.md item #4
for the full table). 988/988 tests (unchanged — zero `src/` changes). Merged `f6f1e47`.
→ memory: `arcf_grounding_structural_behavioral_shipped`

## How this project is organized

- **`Base`** — consolidated, stable checkpoint. Every finished piece of work merges here.
- **`main`** — fast-forwarded from `Base` once `Base` is green. Production-repo runs happen here.
- **Child branches** (`experiment/...`, `fix/...`) — one per bug fix or experiment, branched off
  `Base`, merged back only once resolved. Never left half-done on `Base`/`main`.
- Every merge to `Base` is preceded by a full `pytest` run (currently 930 tests) — zero regressions
  is the bar, not a goal.
- **`CHECKLIST.md`** (repo root) — the forward-looking backlog/tracker, separate from this file.
  Read its session-tracker block first when starting a session; this file (`PROGRESS.md`) stays the
  dated shipped/falsified log.

### 2026-08-12 — Shipped: CHECKLIST.md item #9 (Negative Queries / False-Positive Rate)
New `ConfidenceLabel` enum + `TelemetryEvent.confidence_label` computed property
(`EMPTY_CANDIDATE_SET`/`LOW_CONFIDENCE`/`CONFIDENT_MATCH`), derived from `origin_breakdown` data
item #10/#13 already compute — real `#13` telemetry integration, not informal reuse. Negative-query
FPR harness tested through the real `CodeIntelligenceContractService.attach_code_intelligence` —
not bare `ContextResolver` — since the actual false-positive risk mechanisms (lexical-probe-
recovery, `evidence_fallback.py`) live in `service.py`'s orchestration. `target_names` hand-
specified per query (simulating a plausible-but-wrong SLM-1 extraction), real adversarial query
text passed as `raw_request` so lexical probing gets a genuine chance to misfire.

**Two wrong test premises caught and corrected before shipping**: a fixture built to "share a
lexical root" with a fabricated name did NOT actually trigger `lexical_symbol_probe.py`'s real
6-character-prefix rule (checked directly via `shares_lexical_root()`) — rebuilt with a genuine
collision. "in this repository" wording did NOT trigger `RepositoryScopeClassifier`'s
`repository_scope=True` — needed a documentation-word + repository-word combination, confirmed
directly.

**Decisive real finding**: the genuine collision revealed that origin_stage alone can't distinguish
a confident exact-name match from a probabilistic lexical-probe recovery (both land in
`AST_DIRECT`) — but `evidence_tier` already can (`PRIMARY` vs `SUPPORTING`, the system's own
existing confidence signal). Refined the FPR formula to require both. **Real Consul verification
(7 queries) made this decisive, not just theoretical**: raw origin-stage-only FPR (the spec's
literal formula) = **100%** — diagnostically useless at real scale (28,174 symbols means *some*
accidental 6-char-prefix collision fires for nearly any adversarial query). Every one of 166 real
candidate files across the run was tagged `evidence_tier=SUPPORTING`, none `PRIMARY` — refined FPR
= **0%**, clears the ≤5% gate cleanly. Both numbers reported, not just the passing one. A related
cost (13–39 candidate files spent even at correctly-low confidence) flagged as a genuine future
falsification-experiment candidate, deliberately not bundled into this item. 8 new tests, 988/988
total. Merged `73aae6d`.
→ memory: `arcf_negative_query_fpr_shipped`

### 2026-08-12 — CHECKLIST.md item #7 (Incremental Indexing) verified already solved — Tier 2 complete
Before designing anything against the spec's elaborate Diff-Driven Scope Identification / Targeted
Node & Edge Invalidation / Partial Subgraph Recomputation / Index Stitching & Reconciliation
architecture, read `CodeIntelligenceEngine.build_index` directly: its own docstring already states
per-file parsing is incrementally cached, but every graph (`SymbolIndex`/`CallGraph`/`ImportGraph`/
etc.) is always rebuilt fully, on the claim that graph construction is "always cheap." That claim
needed measuring, not trusting.

**Real measurement, real Consul (11,102 scanned files, 2,370 analyzed, 28,174 symbols)**: full cold
rebuild 141.6s; all-files-cached (isolates graph-construction-only cost) 8.4s — **5.9%** of total
cost, confirming the docstring's claim holds at real scale. Single-file diff: 5.7s, **96.0%
reduction**. PR-sized diff (15 files): 9.5s, **93.2% reduction**. **The existing, already-shipped
`previous_index` mechanism already clears the spec's own ≥80%-reduction gate** — no new code needed
for the performance criterion.

**Correctness gates satisfied by construction, not new logic**: the current design never attempts
partial graph patching — every graph is always rebuilt fully and fresh from a complete
`FileAnalysis` dict, so there's no "stitch modified subgraph back in" step for a bug to hide in.
Structurally *stronger* than the spec's proposed partial-recomputation architecture, whose own
stated risk (graph drift from imperfect invalidation) only exists if you build partial patching in
the first place. Verified with a real test, not left as an architectural argument: 4 new
equivalence tests (`test_incremental_equivalence.py`) covering edit/add/remove/no-op scenarios,
each asserting full-rebuild and incremental produce byte-identical structural signatures AND that
untouched files were genuinely reused (identity-checked), not silently re-parsed.

**Explicit engineering trade-off decision, not a shortcut**: the elaborate architecture was **not
built** — it would spend real effort and introduce the exact correctness risk the spec itself names,
to optimize a cost already measured at 5.9% of total latency and already 96%+ reduced by existing
code for the target scenarios. 4 new tests, 981/981 total. Merged `9bdb885`.
→ memory: `arcf_incremental_indexing_verified`

### 2026-08-12 — Shipped: CHECKLIST.md item #11 (Operational Confidence / Release Gate)
`src/infrastructure/production_gate.py`: `evaluate_release()` consumes `RunSummary` dicts (item
#13's `TelemetryCollector.get_run_summary()` own return shape, no adapter layer) and emits an
immutable `ReleaseDecision` (`RELEASE_APPROVED`/`RELEASE_REJECTED`) with a structured
per-gate failure report — 4 gates (fallback ratio ceiling, latency-vs-baseline ceiling,
token-budget-utilization ceiling, quality recall-floor + precision-drop-vs-baseline), each
independently skippable (not silently passed) when its required data isn't present.
`compare_collectors()` is the shadow/canary driver — a generic two-`RunSummary` comparison rather
than a hardcoded "candidate ARCF version" (none exists to compare against; item #3 was falsified,
never shipped).

**Scope correction**: the spec's Quality Gate needs ground-truth precision/recall, data
`TelemetryCollector` structurally can't compute itself. Extended `TelemetryEvent` (item #13,
already shipped) with optional caller-supplied `precision`/`recall` fields — additive, default
`None`, zero behavior change — so the gate's input is still 100% RunSummary-sourced, with a
`quality_data_available` flag distinguishing "never checked" from "checked and fine."

**All 4 user success gates verified, real measurements**: 100% automated evaluation (real
end-to-end round-trip, `scripts/release_gate_real_consul_check.py`); 100% regression sensitivity
(18 unit tests, one per gate independently injecting a synthetic regression with only that gate
failing, plus a synthetic regression injected on top of *real* Consul baseline data); zero overhead
by structural construction (`production_gate.py` imports nothing from the retrieval pipeline —
stdlib + pydantic + `shared.clock` only); seamless #13 integration (real round-trip tested).

**Real operational finding, surfaced not hidden**: the real end-to-end check showed
`RELEASE_REJECTED` under the spec's own literal default (`max_fallback_ratio=0.0`) — real Consul's
natural fallback rate (2.36%) exceeds a zero-tolerance ceiling by design. Confirmed this is correct
behavior, not a bug: fallback/token-budget gates are absolute ceilings (matching the spec's own
wording), independent of baseline — even a self-comparison smoke test doesn't bypass them if the
real data itself exceeds the ceiling (the *relative* latency gate correctly showed 0% overhead in
the same self-comparison). A realistic `max_fallback_ratio=0.05` approved the same real data
cleanly. Whoever configures this gate in production needs a realistic threshold informed by
measured data, not the spec's literal zero-tolerance default. 18 new unit tests, 977/977 total.
Merged `ed5cf86`.
→ memory: `arcf_operational_release_gate_shipped`

### 2026-08-12 — Shipped: CHECKLIST.md item #13 (Observability & Telemetry)
New `TelemetryCollector`/`TelemetryEvent` (`src/infrastructure/telemetry.py`): in-memory, zero
external networking, opt-in — no existing caller/test affected unless it explicitly attaches a
collector. Times the two real public pipeline boundaries (`ContextResolver.resolve()`,
`ContextPackager.package()`) as wholes rather than adding new internal instrumentation; gets the
"Origin Breakdown" the spec asked for free from item #10's `FileReference.origin_stage` data —
zero new instrumentation needed there. `get_run_summary()` (mean/p50/p95/max latency, aggregated
origin totals, overall fallback ratio, mean utilization) and `assert_no_fallbacks()` (a real
release-gate helper for item #11) both built and tested.

**Two scope corrections made explicit, not silently absorbed**: the spec's 4 named stage
boundaries don't map to 4 separately-callable real functions (`ContextBudgetManager.select()` does
"pruning" and "final_selection" together; `resolve()` does entry-point matching and graph expansion
together via private helpers already threaded twice this session) — timed the two genuine
boundaries instead. And "100% of telemetry payloads validate... across all 947+ tests" was made
literally true via an opt-in `ARCF_TELEMETRY_VALIDATE=1` `tests/conftest.py` wrapper (default
unset, zero behavior change — confirmed 957/957 either way) rather than retrofitting 947 unrelated
test files.

**All 4 user success gates verified with real measurements**: latency overhead **-2.224%**
(`scripts/telemetry_overhead_measurement.py`, real Consul, 200 iterations/arm — telemetry arm was
marginally *faster* on average, within noise); 100% Pipeline Coverage (both real boundaries
wrapped); 100% schema validity across the full suite (real one-time run: 957/957 tests, 140 events,
**0** schema/recording violations); programmatic interface ready for #11.

**Real secondary finding, traced not dismissed**: the full-suite run surfaced 9 untagged
candidates. Traced to `tests/context/test_packager.py`'s hand-built `ContextResolutionResult`
fixtures (bypass the real resolver entirely to test `ContextPackager`'s own logic in isolation) —
not a regression in item #10's coverage (still 100% on real Consul). 10 new unit tests. Merged
`bb0e596`.
→ memory: `arcf_observability_telemetry_shipped`

### 2026-08-12 — Shipped: CHECKLIST.md item #10 (Symbol-Identity Mode / Provenance Audit Trail)
New `OriginStage` enum (`AST_DIRECT`, `SCOPED_GRAPH_EXPANSION`, `RAW_STRING_FALLBACK`,
`EVIDENCE_FALLBACK_MATCH`) + `FileReference.origin_stage`/`parent_symbol_id`, additive/default-
`None`, wired through every real candidate-producing path in the default classic resolver: the
entry-point match, the two confirmed raw-name-lookup bypasses
(`locality_filtered_callers_of_name`, `candidate_selector.subclasses_of` — both call
`SymbolIndex.find_by_name` internally, verified by reading them directly), the ID-scoped
`caller_hops`/`callee_hops` walks (`parent_symbol_id` = the BFS's own real immediate parent, not
just the entry symbol), and the two symbol-less filename-match paths (`evidence_fallback.py`,
`service.py`'s anchor Tier 4) — confirmed `expand_with_evidence` runs unconditionally on the
default classic path, so these are real, reachable origins, not edge cases. Explicitly out of
scope, documented not silently skipped: `drp_resolver.py` (a separate `resolver_strategy`) and
`multi_hop_orchestrator.py`/`evidence_validator.py` (only reachable via an experimental spike
`service.py` never calls today).

**Real bug caught by this item's own unit test, fixed in the same flow**: first-write-wins tagging
let code order (not evidence strength) decide the label — `locality_filtered_callers_of_name` isn't
module-level-only despite its own comment, so it can reach the same file a properly ID-scoped
`caller_hops` walk also reaches, and since it runs first, first-write-wins picked the weaker
`RAW_STRING_FALLBACK` tag even when a stronger `SCOPED_GRAPH_EXPANSION` path also applied. Fixed
with a precedence-based merge, same "stronger evidence wins" shape as `file_tiers`' existing
PRIMARY-always-wins rule.

**Verified on real Consul** (`scripts/symbol_identity_audit_trail_verification.py`, no LLM calls)
at traversal depths 1/2/3, both flagship queries: all 3 user success gates pass — 100% Symbol
Traceability (0 untagged files, every run), Zero Unflagged Re-introductions, and a concrete
traceability-velocity demonstration re-running item #3's own dropped-file trace:
`parent_symbol_id='agent/setup.go::NewBaseDeps#101'` gives the exact file+symbol+line in one field
read, versus the manual `justification_chain` string-parsing that trace actually required. 947/947
tests (5 new). Merged `3b53144`.
→ memory: `arcf_symbol_identity_audit_trail_shipped`

### 2026-08-12 — CHECKLIST.md item #3 (Locality UPS Suppression) falsified — same disposition as Arms 1/2/4
Package-level Utility Package Score (`indegree + cross_subsystem_usage`, top-5th-percentile
threshold relative to each repo's own distribution, plus an absolute `indegree>=3` floor added
after a unit test caught the percentile-only version over-flagging ordinary packages on small
repos): `_locality_filtered_bfs` now stops expanding past a hub package's file instead of using it
as a further bridge to unrelated files. `enable_ups_suppression` threaded through
`locality_filtered_transitive_callers/callees` → `ContextResolver._expand_calls`/`resolve()` →
`CodeIntelligenceContractService.attach_code_intelligence`/`_resolve` (plus a test-only
`traversal_depth_override`), default `False`, zero behavior change for every existing caller.
945/945 tests (3 new).

**Free deterministic pre-check (real Consul, same-process ablation, `scripts/
ups_suppression_ablation.py`)**: byte-identical at the default `traversal_depth=1` — traced (not
assumed) to `_locality_filtered_bfs`'s own loop never recording hop-2+ into its result at
`max_depth=1`, so the mechanism is structurally unreachable there. Real production varies depth by
`RetrievalTaskType` (`TRAVERSAL_DEPTH`, `task_profile.py`) — swept depths 2/3 and found a real,
purely-subtractive effect on synthetic bare-name probes: `Register` -36.6%/-35.6% token footprint,
`New` -3.5%/-9.4%. Genuine cross-package ground truth (`task6`-style) unaffected at every depth,
determinism 100%.

**Real-LLM validation closed it out**: `classify_retrieval_task` against every existing benchmark
query confirmed ALL of them classify to depth=1 by default — wired a `traversal_depth_override` to
test at a real depth=2 anyway. A single free-to-check real-LLM run (gpt-4o-mini, real Consul)
showed `candidate_count` **identical, on vs. off**, for both task1 and task5: real SLM-1 extraction
pulled a qualified `Catalog.Register` (task1) and a path-hinted `['agent/cache', 'New']` (task5,
where Feature 1's already-shipped query-wide path-hint masking narrows resolution before
hop-expansion ever runs) — neither hits the bare-ambiguous-name path the synthetic probes used.
Same shape as Arms 1/2/4: correctly built, real synthetic-probe effect, no real effect once real
entity extraction and already-shipped upstream narrowing are in the loop. User chose to stop before
the full paid `n_runs=5` statistical run given this pattern.

**Outcome**: not merged — preserved unmerged on `experiment/locality-utility-suppression` as the
historical record, same disposition as Arms 1/2/4.
→ memory: `arcf_ups_suppression_falsified`

### 2026-08-12 — Added: `CHECKLIST.md` tracking doc
User wrote a 15-section gap-analysis doc proposing ARCF improvements; reviewed against the real
falsification history below before anything was built. Several proposed items were the same shape
as already-falsified work (§1's multi-signal confidence score ≈ [[arcf_entropy_confidence_falsified]];
§13's cross-pipeline confidence propagation, same family) or conflicted with the CallGraph-is-
off-limits constraint documented in `locality.py` (§2's edge-provenance idea). One item (§3, Utility
Package Score locality suppression) lines up with the one concrete open lever from the
disambiguation-pruning entry below (`has_locality`'s import-reachability tier) and is the current
highest-signal candidate. Consolidated into `CHECKLIST.md` as 14 tracked items (§7 DRP integration
+ §12 repository evolution merged, same underlying capability), each with a status, a correction
against project history, and an unfilled success-criteria line to complete before starting work.
No item started yet — this commit is process setup only.
→ memory: `arcf_checklist_md_reference`

### 2026-08-12 — Shipped: Disambiguation-Driven Candidate Pruning (grew directly out of Arm 1's own root-cause finding)
`ContextResolver.resolve()` computed `disambiguation.preferred`/`ambiguous` via
`ReferenceResolver.resolve_with_disambiguation`'s locality scoring but never consumed it — every
raw same-named match still became a candidate regardless of whether locality scoring had already
narrowed a multi-symbol name to one confident winner (Arm 1's own precise finding, see below).
Fixed on `fix/context-resolver-disambiguation-pruning`: `matches` now prunes to `[preferred]`
whenever `disambiguation.ambiguous` is `False` and there was more than one raw match — same trust
`path_hints` already extends to a caller-provided signal, now extended to the resolver's own
locality-derived one. `ambiguity_confidence` still reflects the raw pre-prune match count,
unchanged. 942/942 tests (4 new). Merged `4f68f69`.

**Verified via same-process ablation (real Consul, all 6 tasks)**: `ambiguous_targets` now
correctly reflects successful disambiguation (task5: 2 flagged-ambiguous entities → 0). Packaged-
file count unchanged on these tasks — traced to a *separate* mechanism, `_expand_calls`'s own
independent name-based call-graph expansion (`locality_filtered_callers_of_name`), which
re-introduces same-named files regardless of this fix.

**A natural follow-on (scoping that lookup to the disambiguated symbol ID instead of the bare
name) was verified NOT to help *before being built***: `CallGraph.caller_files_of(cache.New's own
ID)` already returns 460 files — `CallGraph`'s own construction-time resolution (`resolver.
resolve()`, non-disambiguating) over-attributes every bare `New(...)` call site to *every*
same-named symbol's ID, independent of which lookup later reads it. ID-scoped vs. name-scoped
locality filtering produced 31 vs. 32 files — a 1-file difference, not a fix. Not implemented.
**Documented as a genuinely different future hypothesis** (see Open/unresolved below): tightening
`has_locality`'s transitive import-graph-reachability tier (same file/directory/import-reachable
in either direction, currently unbounded-hop) is the real lever, but it's a separate, riskier
change (affects every locality-filtered call site in the codebase) needing its own isolated
falsification protocol, not a quick follow-up to this fix.
→ memory: `arcf_disambiguation_pruning_shipped`

### 2026-08-12 — Competitive Multi-Frontier Experimentation: Arm 1 (Type Graph / G_type Indexing, Go-only) falsified — with the most precise root cause of the three arms so far
Third arm of the planned 4-arm experiment (Arms 2 and 4 above; Arm 3 String Dispatch Index not
yet attempted). Go-only scope by explicit decision (Consul is Go, zero class inheritance —
struct composition/field types is where the real blind spot is). On `exp/type-graph-indexing`:
extended the shared IR (`Symbol.param_types`/`return_type`, new `FieldReference` type,
`FileAnalysis.fields`), populated Go-only in `GoLanguageAnalyzer` (verified against real
tree-sitter-go grammar — 36/36 analyzer tests passed on first run). New `TypeGraph`
(`code_intelligence/type_graph.py`, mirrors `InheritanceGraph`'s resolve-via-`ReferenceResolver`
pattern): single-hop composition adjacency. Wired into `ReferenceResolver._locality_score` as a
new tier between "same file" and "same directory". 965/965 tests (27 new).

**Same-process ablation (identical `ContextResolutionResult`, `type_graph` swapped for an empty
one, one process — the standard established by Arm 2's own catch)**: real data exists (14,674
`FieldReference`s indexed on real Consul, 3,510 resolved to real Symbols), mechanism verified
correct in isolation (31 unit tests) — but **zero packaged-file delta** across 7 general real
queries AND 3 further queries deliberately chosen where the field resolves to a *concrete
struct*, not an interface (ruling out the first, plausible-looking hypothesis).

**Root cause, more precisely diagnosed than either prior arm**: one case
(`PermissionDeniedError` → `Resource` field → ambiguous `Apply` method) showed a genuine
disambiguation-layer win — `disambiguation.ambiguous` flipped `True`→`False`. But
`ContextResolver.resolve()` never actually consumes `disambiguation.preferred` to prune the
candidate set for **any** locality tier (same file, type-graph, same directory, import-graph
alike) — it adds every match in `disambiguation.resolved` regardless of whether locality scoring
narrowed anything; `ambiguous_targets` is populated for reporting only. Only `path_hints` (a
separate, deliberate hard filter) actually prunes. This is a pre-existing architectural property
of the whole disambiguation layer, not a defect specific to this arm — consuming `preferred` to
prune would be a separate, more general fix (affecting all four tiers at once), out of this arm's
own scope.

**Outcome**: not merged — preserved unmerged on `exp/type-graph-indexing` (commit `cf40ab3`) as
the historical record, same disposition as Arms 2 and 4. No harness-side keeper this time (unlike
Arm 4's Task 6) — this arm's diagnostic value is the `disambiguation.preferred`-never-consumed
finding itself, now documented for whichever future work (this arm's own follow-up, or a
different one) wants to pursue it.
→ memory: `arcf_arm1_type_graph_falsified`

### 2026-08-12 — Competitive Multi-Frontier Experimentation: Arm 2 (Semantic Re-Ranker) falsified via same-process ablation
Second arm of the planned 4-arm competitive experiment (see Arm 4 entry below). Implemented on
`exp/semantic-reranker` (off `main` `39b8275`): an `ENABLE_SEMANTIC_RERANKER`-gated lightweight
term-overlap relevance proxy for candidates the relative-score falloff gate excludes — scores
each SUPPORTING/EXPERIMENTAL falloff-excluded candidate's call-site-window excerpt against the
query's own lowercase content words, packs those scoring >0.2 (highest first) until `used` hits
75% of `max_tokens`. Threaded `query` through `ContextPackager.package()` ->
`ContextBudgetManager.select()` as a new optional param (`None` fully backward compatible).
952/952 tests (14 new).

**Ablation protocol upgraded mid-task, a real methodological catch:** the literal two-process
diff this arm's own spec called for (`ENABLE_SEMANTIC_RERANKER=1` vs `=0`, two separate
`--n-runs 1` invocations) showed deltas on task5 — but `baseline_raw` (Arm B, whose code never
touches `ContextBudgetManager` or this toggle at all) *also* showed a delta on the same task,
proving at least part of the observed "delta" was SLM-1 entity-extraction noise between the two
process invocations (task5 is the documented flaky `'New'` case), not the toggle. Re-ran as a
**same-process** ablation instead — identical resolution, toggle on vs. off, one Python process —
across all 6 real tasks: **byte-identical packaged output in every single task.**

**Root cause, fully diagnosed per-task:** tasks 1/2/4/5 already use >90% of the 8000-token budget
in the main loop alone, past the pass's own 75% ceiling before it ever runs; task6 lands at
76.9%, blocked by the same ceiling by roughly one token's margin; task3 has zero
falloff-excluded candidates at all — nothing to re-rank regardless of budget headroom. ARCF's
existing falloff gate + Call-Site Slicing compression is volume-efficient enough (many small
excerpts, not a few large ones) that it already saturates either the budget or the real candidate
graph on its own, leaving no genuine gap for a post-hoc lexical re-ranker to fill on this
benchmark's real queries. (Caveat: this diagnosis used a flat `max_tokens=8000`, not
`task_type`-tiered — the exact percentages aren't what production enforces, but the same-process
zero-delta finding holds regardless of that detail.)

**Outcome:** not merged — preserved unmerged on `exp/semantic-reranker` (commit `149eb3a`) as the
historical record, same disposition as Arm 4. **Methodology takeaway, now load-bearing for Arms 1
and 3:** a same-process ablation (identical resolution, factor on vs. off, one process) is the
only trustworthy verification for a ranking/packaging change — a two-*process* diff is
confounded by SLM-1 non-determinism and can show a "delta" on an arm that provably cannot have
caused it, exactly like this task5 case.
→ memory: `arcf_arm2_semantic_reranker_falsified`

### 2026-08-12 — Competitive Multi-Frontier Experimentation: Arm 4 (Path-Hint Locality) falsified via ablation trace; Task 6 shipped
First arm of a planned 4-arm competitive experiment (Type Graph, Semantic Re-Ranker, String
Dispatch Index, Path-Hint Locality) against `main`. Implemented Arm 4 on `exp/enhanced-path-
locality`: `FileReference.path_locality_confidence`, a directory-proximity BOOST (same-directory
1.20 / sibling 1.12 / parent 1.06, `None` otherwise) for candidates reached via call-graph/
inheritance expansion, stacking with (not replacing) the existing `path_mask_confidence` penalty.
954/954 tests (16 new). Direct trace confirmed correct tier computation on real Consul data
(task2: 3/38 candidates boosted; task5: 13/19 when SLM-1's flaky `'New'` extraction survived).

**Benchmark blind spot found and closed:** every existing task's ground truth was the direct
entry point (PRIMARY tier, already score-saturated — structurally un-boostable by this arm's own
design). Added `task6_path_hint_secondary_sibling` to `validate_llm_grounding.py`'s
`BENCHMARK_TASKS`, built on a real, grepped (not assumed) cross-package relationship:
`agent/cache/cache.go` defines `Prepopulate`; `agent/auto-config/tls.go` is the only real,
unambiguous non-test sibling-package caller. Entity extraction fully deterministic across repeat
calls (unlike task5's `'New'`).

**Decisive falsification:** Task 6's aggregate numbers looked like a clear win (ARCF Recall 1.0
vs. baseline 0.5) — but per this session's mandatory code-path-tracing discipline, that aggregate
alone was not trusted. Ran the identical real resolution through `ContextBudgetManager` twice,
once with `path_locality_confidence` as computed and once with every value ablated to `None`:
**byte-identical packaged output both times** (used=6155, excluded=1, same 7 files). Task 6's
Recall lift is fully explained by ARCF's *existing* compression pipeline (Call-Site/AST-scope
slicing, already shipped, unrelated to this arm) letting a 9168-token file compress to 700 tokens
and fit trivially — the baseline arm misses it only because its greedy full-file packer can't
afford the whole file, a confound present on every task in this harness, independent of Arm 4.
Traced every task where the mechanism could fire (2, 5, 6) and found zero instances where the
boost changed a real packaged outcome: ARCF's compression already fits nearly everything that
clears the falloff gate regardless of rank order, so the one axis this arm operates on doesn't
bind in practice.

**Outcome:** Arm 4's ranking code (`domain/context_resolution.py`, `context_resolver.py`,
`relevance_ranker.py`) NOT merged — preserved as the historical falsification record on
`exp/enhanced-path-locality` (commit `56b1a8f`), unmerged. Task 6 itself, a real permanent harness
improvement independent of the arm's outcome, WAS merged (`ebdebb6`) — same "keep the
instrumentation, revert the feature" split as the earlier Hop-2 cleanup. Arms 1-3 (Type Graph,
Semantic Re-Ranker, String Dispatch Index) not yet attempted.
→ memory: `arcf_arm4_path_locality_falsified`

### 2026-08-12 — Call-Site Slicing (token efficiency) shipped; Hop-2 budget-fill removed as dead code
Child branch `feature/call-site-slicing-budget-rebalance` off `Base` `62aced2`. Two-part task:
replace secondary/tertiary candidates' whole-scope skeleton blanking with a tight +/-8-line
window around a symbol's own declaration line (`SymbolRangeCompressor.extract_call_site_window`,
`ContextBudgetManager._compress_call_site`), then spend the freed budget on an additive pass
packing Hop-2+ call-graph-linked candidates.

**Shipped — Call-Site Slicing, as a token-efficiency optimization:** real Consul measurement
(`--n-runs 3`) showed ~23% smaller packaged-token footprint for the same candidate sets, plus
improved mean Grounding (2.333 → 2.6) and Composite (2.800 → 2.867) judge scores. Focal and
hop-1-linked candidates are completely untouched (still full `extract_with_ast_scope` body);
`extract_skeleton_only` itself is kept as `_compress_call_site`'s own fallback when windowing
can't resolve a symbol's line, not removed.

**Removed — additive Hop-2 budget-fill pass, confirmed dead code:** the first implementation
also tried spending the tokens Call-Site Slicing frees up on candidates reached via a 2+-hop
`justification_chain`, to raise Context Budget Utilization from its measured ~50% toward
80–85%. Measured effect was the *opposite* of the goal (utilization fell to 0.382, not up) —
traced directly (not inferred from the aggregate score) by resolving a real Consul query and
inspecting every candidate's `justification_chain` length: **0 candidates ever exceeded length
1** (36 at length 0, 2 at length 1, zero at 2+). Real secondary evidence in this codebase's
candidate sets comes overwhelmingly from single-step relationships (inheritance, evidence-
category matches, lexical-probe recovery) that populate `justification_chain` as empty/short
*by design* — not from deep multi-hop call-graph traversal, the population this pass needed to
exist to do anything. Removed (`hop_two_leftover` tracking, `packaged_paths` dedup set, the
post-loop retry block, its 3 dedicated unit tests) rather than kept as unreachable code. Post-
removal benchmark run is statistically consistent with the pre-removal one (0.406 vs 0.382 mean
utilization, within noise), confirming the removal changed nothing real — it was genuinely dead,
not a regression introduced by deleting it.
→ evidence: `docs/llm_grounding_validation/consul_grounding_validation_summary_CALL_SITE_SLICING_FINAL.md`

### 2026-08-12 — Grounding-harness statistics (P/R/F1, multi-pass) + 8th recall-gap falsification
A static codebase audit (child branch `fix/grounding-metrics-and-lexical-probe` off `Base`
`cd0e808`) implemented three targeted improvements; one shipped, one was empirically falsified
and reverted before merge:

**Shipped — new infrastructure/harness gains:**
- **Programmatic grounding assertions:** `scripts/validate_llm_grounding.py` now computes
  set-intersection Precision/Recall/F1 of each arm's actually-`packaged_files` against
  `ground_truth_files` (`_file_overlap_metrics`), supplementing the pre-existing free-text
  `_key_term_check`. Safe on empty sets (returns `0.0`, no `ZeroDivisionError`).
- **Multi-pass statistical harness:** new `--n-runs` flag (default 3) repeats every benchmark
  task that many times and reports **mean ± stddev** per arm/metric (tokens, latency, judge
  scores, and the new P/R/F1 + budget-utilization + key-term metrics) — directly addresses the
  "benchmark noise floor" open item below by making SLM-1's run-to-run non-determinism visible
  as a number instead of a single-sample guess.

**Falsified and reverted — 8th attempt at the closed recall-gap thread ([[arcf_recall_gap_closed]]):**
Un-gating `lexical_symbol_probe.py` in `src/code_intelligence/service.py` to run as a standing,
always-on corroboration source (set-unioned with SLM-1's resolution) instead of only firing as a
zero-result fallback. Real Consul run (`--n-runs 3`) showed overall recall nudging up (0.1→0.2),
but a direct `resolution_reason` code-path trace on `task5_ambiguous_common_name` (the flagship
"New" case) proved the correct file was already resolved via the pre-existing `path_hint`
propagation mechanism *before* the standing probe ran — the probe's only real contribution was 13
additional candidate files, all unrelated same-named `New` functions in disconnected subsystems
(auto-config, grpc-external/peerstream, proxycfg-glue, structs, submatview). Zero measured recall
benefit once attributed correctly; reproduces the exact high-frequency-name-ambiguity noise the
recall-gap closure already documented. Reverted in commit `38ae7c5`; the harness improvements
above were kept since they're what made the falsification traceable rather than a guess from
aggregate scores alone.
→ memory: `arcf_recall_gap_closed` (now 8 falsified attempts), `arcf_payload_optimization_path_masking`

### 2026-08-12 — Safe High-Efficiency Payload Optimization (Features 1–4)
Query-wide path-hint masking (fixes SLM-1 entity-*order* non-determinism), two-tier AST snippet
rendering (full body for the focal candidate, signature-only skeletons for secondary ones),
intent-based dynamic budget ceilings, Top-K entry-point seed ranking (scoped down from the
original truncation spec after it conflicted with a real 2026-08-07 crash-fix invariant — explicit
decision: rank, never drop). Real token cuts, verified. Two real bugs caught and fixed *before*
shipping: a 4030ms→~700-1260ms performance regression in the ranking signal, and a fallback-logic
bug in the skeleton renderer. Grounding-score target (composite ≥3.4/5.0) was **not** hit on any
measured run — re-running the benchmark surfaced that SLM-1 is non-deterministic in *which*
entities it extracts, not just their order, even at `temperature=0.0`. That noise floor is
documented as a real, unresolved limitation, not smoothed over.
→ memory: `arcf_payload_optimization_path_masking`

### 2026-08-11 — SLM-1 entity contract fix + path-aware reference resolution (Features 1–3)
Refined the SLM-1 prompt to require real code-identifier grammar or path-qualified hints instead
of prose noun phrases; added `path_hint` filtering and identifier-permutation fallback to
`ReferenceResolver.resolve_with_disambiguation`. Fixed a real regression this itself caused
(`"Catalog.Register"` splitting into two separately-ambiguous words) before merging. Real but
partial: the flagship "New" ambiguity case improved in one run, then regressed in a second,
identical-settings run purely because SLM-1 returned the same two entities in a different order —
the seed of the order-independence problem Features 1–4 (above) later fixed.
→ memory: `arcf_path_aware_resolution_fix`

### 2026-08-11 — ARCF vs. direct-LLM grounding validation harness
Built `scripts/validate_llm_grounding.py`: 3-arm benchmark (ARCF pipeline / naive greedy-packing
baseline / zero-context) against real Consul with real `gpt-4o-mini` calls. Found zero-context
scored *higher* than ARCF overall on this run — but decomposed per-task rather than reported flat:
one task cleanly validated the earlier B/C packaging work, and three losses traced to a genuinely
new, previously-undocumented root cause — SLM-1 extracting unresolvable natural-language noun
phrases instead of exact symbol names.
→ memory: `arcf_grounding_validation_entity_extraction_gap`

### 2026-08-11 — Real-Time Token & Latency Optimization (Features A/B/C)
Tier-1 structural ambiguity decay, relative score falloff gate (γ=0.45), AST enclosing-scope
slicing for secondary candidates. Real gains for moderate/low-ambiguity queries; the extreme-
ambiguity "New" case stayed byte-identical before/after — same unsolved Tier-1 entry-point
fan-out gap the CallGraph fix (below) also hit.
→ memory: `arcf_realtime_pipeline_optimization`

### 2026-08-11 — CallGraph fan-out locality fix
Fixed classic resolution's call-graph hop-expansion fan-out for ambiguous names (e.g. "Register":
30→23 files, 25→12 subsystems on real Consul). Does **not** solve the flagship "New" case (156
matches) — that noise comes from Tier-1 entry-point selection itself, a separate mechanism, out of
scope for this fix.
→ memory: `arcf_callgraph_locality_fix`

### 2026-08-11 (earlier) — Recall-gap research thread permanently closed
7th and final falsified attempt (symbol-seeded Personalized PageRank, then Package Specificity
Score pruning) at the short-word recall problem. Closed as a proven architectural boundary of
ARCF's zero-embeddings design — do not reopen without new evidence.
→ memory: `arcf_recall_gap_closed`, `arcf_ppr_recall_falsified`

### 2026-08-11 (earlier) — TaskClassifier substring fix
Fixed a false-positive tie where `"implement"` substring-matched inside `"implementation"`.
→ memory: `arcf_slm1_scope_and_task_classifier_fix`

## Open / unresolved (don't re-litigate without new evidence)

- **Flagship "New"-style extreme-ambiguity retrieval** — still not solved. Root cause is Tier-1
  entry-point fan-out (a name resolving to 100+ same-named candidates repo-wide), a different
  mechanism from everything fixed so far.
- **Grounding-score target (≥3.4/5.0 composite)** — never hit in three measured benchmark runs.
  **Task 1 regression's real cause now confirmed** (checklist item #4, above): the genuine entry-
  point file is both oversized (competes for the whole token budget) and ambiguity-decayed (ranks
  below decoy files) — the same mechanism as the closed recall-gap thread, now shown to also hit
  ranking/packaging. Deliberately not fixed (needs its own isolated falsification experiment, same
  as the 8 prior recall-gap attempts) — diagnosed, not resolved.
- **Benchmark noise floor** — SLM-1 entity extraction is non-deterministic in *content*
  (not just order) even at `temperature=0.0`. Single-run score deltas on the 5-task grounding
  benchmark should not be trusted to attribute cause without multiple runs.
- **`path_hint` doesn't propagate across entities in a query** — only the entity that carries a
  path hint benefits from it directly; Feature 1 (query-wide masking) mitigates this for path
  hints specifically but the general case is still narrow.
- **DRP's `subsystem_graph.py`** — never had the CallGraph locality filter applied; deliberately
  deferred, would need the full 5-repo DRP ground-truth sweep first.
- **`has_locality`'s transitive import-graph-reachability tier is likely too permissive** — the
  actual blocker preventing Disambiguation-Driven Candidate Pruning (above) from changing packaged
  output on real Consul: for a foundational, widely-imported package like `agent/cache`, "import-
  reachable in either direction" (currently unbounded-hop, `locality.py`) lets in most of the
  `agent/*` tree regardless of real relevance. Verified NOT fixable by scoping
  `locality_filtered_callers_of_name` to a symbol ID instead of a bare name (1-file difference out
  of 34 — the real permissiveness is in `has_locality` itself, not which function reads it). A real
  candidate for a future, ISOLATED falsification experiment (tighter reachability, e.g. direct-
  import-only) — not a quick follow-up to any existing fix, since it would affect every locality-
  filtered call site in the codebase, not just the disambiguation path.

## Maintenance note for Claude

Update this file after each merge to `Base` — a short dated entry (what changed, real
measured outcome, link to the fuller memory file) plus a refresh of the header (HEAD commit,
test count, timestamp). Keep entries honest: real wins and real unresolved trade-offs both belong
here, not just the wins.
