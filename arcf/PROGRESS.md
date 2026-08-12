# ARCF Progress Log

**Last updated:** 2026-08-12 09:26 IST · **Base/main HEAD:** `966163f` · **Tests:** 938/938 passing

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

## Timeline (most recent first)

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

## Maintenance note for Claude

Update this file after each merge to `Base` — a short dated entry (what changed, real
measured outcome, link to the fuller memory file) plus a refresh of the header (HEAD commit,
test count, timestamp). Keep entries honest: real wins and real unresolved trade-offs both belong
here, not just the wins.
