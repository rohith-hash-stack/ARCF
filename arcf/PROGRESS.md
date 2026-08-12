# ARCF Progress Log

**Last updated:** 2026-08-12 IST · **Base/main HEAD:** `3b53144` · **Tests:** 947/947 passing

Read this file top-to-bottom to pick up where things stand — it's the fast-start doc for a new
chat session. Detailed *why* for each entry lives in Claude's memory files (per-topic, e.g.
`arcf_payload_optimization_path_masking`); this file is the curated *what/when* summary, updated
after each merge to `Base`, not after every small step.

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
  Real cause of the specific Task 1 regression is unconfirmed even after a targeted tier fix.
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
