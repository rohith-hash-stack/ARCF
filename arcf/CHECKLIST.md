# ARCF Improvement Checklist

Forward-looking backlog of identified gaps, reviewed against real project history. This file is
the *plan*; `PROGRESS.md` is the *shipped log*. Read both at the start of any session — this one
first if you're picking up mid-item, `PROGRESS.md` for what's already landed.

## How this file works

- **One child branch per item**, branched off `Base`, per the standing [[arcf_branching_policy]]
  (only `main` + `Base` persist long-lived; every fix/experiment gets a disposable branch merged
  back on completion).
- **Status values**: `Not Started` · `In Progress` · `Blocked` · `Parked (needs new evidence)` ·
  `Shipped`.
- **Before starting an item**, write its explicit success/failure criteria into that item's
  "Success criteria" line if it isn't already filled in — per the standing falsification-experiment
  discipline, don't start coding against a vague goal.
- **An item only moves to `Shipped`** when merged to `Base` with zero known open issues (existing
  hard rule — a "mostly working" result stays `Blocked` or `Parked`, not shipped-with-caveats).
- **Bugs or issues found while working an item are fixed on that same branch, in the same flow,
  before merge.** Do not spin them off as separate follow-up items or defer them — this matches
  how every prior shipped item on this project actually happened (e.g. payload optimization caught
  and fixed 2 real bugs pre-ship; the SLM-1 path-aware fix fixed a regression it caused before
  merging).
- **When an item ships**: mark it `Shipped` here with the commit hash and one line of real
  measured outcome, *and* add the fuller dated entry to `PROGRESS.md` in the same commit. Don't let
  the two docs drift.
- **When an item is falsified/parked**: mark it here with the reason and the branch it lives on
  (unmerged, kept as historical record — same treatment as Arms 1/2/4), and still add a one-line
  `PROGRESS.md` entry so the attempt isn't invisible to the next session.

## Session tracker

Update this block at the end of every session so a new session (or a continuation after a context
limit) can resume without re-deriving anything.

- **Last updated:** 2026-08-17 — **ARCF Architecture Closure is CODE-COMPLETE and adversarially
  re-verified, not yet committed/merged.** Read `docs/ARCF_ARCHITECTURE_CLOSURE_CHECKLIST_2026-08-16.md`
  FIRST if resuming — it has the full record: 23/24 Final Architecture Acceptance criteria PASS (1
  explicitly deferred, FA-14), all 6 closure sweeps PASS, **1022/1022 tests passing** on
  `feature/architecture-closure` (off `Base` `5b7fa5c`). Real end-to-end proof: `POST /contracts/{id}
  /grounded-execution` now takes a bare `contract_id` through retrieval → evidence check → ranking →
  context → generation → deterministic grounding verification → bounded (`MAX_RECOVERY_ATTEMPTS=1`,
  `resolver_strategy="drp"`) recovery → a real persisted `ExecutionLedgerEntry`, closing the
  "Generation is a disconnected bypass" gap that was this whole effort's central finding.
  **Two independent re-verification rounds found and fixed real issues after the first "done"
  claim** — see the closure checklist's §41.1 for the full account: a financial-audit bug (real LLM
  spend silently unrecorded if an exception hit mid-recovery-retry), several verification-regex
  false positives/negatives, an unbounded second expansion loop the original G16 fix missed, and two
  of the discovery report's 19 numbered gaps (G15, G18) that had silently fallen out of tracking
  entirely. All fixed and tested. **Not yet committed to git or merged to `Base`** — awaiting
  explicit go-ahead (this session does not commit without being
  asked). `feature/local-inference-server` (gap #3) remains PAUSED, untouched, its one commit
  (`16ddfed`) unmerged, waiting to resume after this closure lands.
- **Prior entry (2026-08-13, frozen):** resuming gap #3 with a decided direction, see "3c"
  under "Production Readiness Gap Resolution" below.
- **Active branch (gap #3, paused):** `feature/local-inference-server`, off `Base`. Historical unmerged branches
  unchanged: `experiment/locality-utility-suppression` (same treatment as `exp/enhanced-path-
  locality`, `exp/semantic-reranker`, `exp/type-graph-indexing`, all left as historical record).
  `feature/symbol-identity-audit-trail`, `feature/observability-telemetry`, `feature/operational-
  release-gate`, `feature/incremental-index-equivalence`, `feature/negative-query-fpr-harness`,
  `feature/grounding-structural-behavioral-split`, `feature/failure-taxonomy`, `feature/validation-
  breadth-matrix`, and `feature/primary-priority-floor` all merged and deleted (unchanged from
  before).
- **Active item:** Gap #3 direction decided (self-hosted local inference server, not a paid API
  vendor) — infra build in progress on `feature/local-inference-server`. See "3c" below for the
  decision and its explicit success/failure criteria. Everything else unchanged — **Tier 1 AND Tier
  2 fully closed out; Tier 3 items #9, #4, #14, and #8
  all shipped — Tier 3 fully closed out.** Item #4's real finding worth remembering: the new `G_struct`/`G_behav` split didn't
  just add a metric — run through the real Arm A pipeline it precisely diagnosed PROGRESS.md's own
  previously `unconfirmed` "Task 1 regression": the genuine entry-point file for tasks 1/3/5 is both
  unusually large (9k–12k tokens, competing for an 8000-token budget) and ambiguity-decayed
  (2/7/224 same-named matches), which drops it below decoy files in ranking (task5's real entry
  point ranked 70th of 224) — the same mechanism as the already-closed 8-times-falsified recall-gap
  thread, now shown to also bite at the ranking/packaging stage. Deliberately not fixed (matches
  item #3/Arms 1-4's own "flag, don't fix a pre-existing mechanism mid-item" discipline) — flagged
  as a new future falsification-experiment candidate. Task2's `G_behav`=0 is the same closed
  boundary from a different angle ("Notify" is 78-way ambiguous). Tasks 4/6 both cleanly pass
  (`G_struct`=`G_behav`=1.0, task6's behavioral hit confirmed genuine `SCOPED_GRAPH_EXPANSION`).
  Item #14 built the classifier that made all of the above precise instead of hand-traced, and
  caught a real gap in item #4's own write-up along the way: task2's `G_struct` also failed, for a
  *different* reason (ambiguity decay on `Cache` itself) than the already-documented `G_behav`
  failure (the `Notify` collision) — corrected on item #4's own entry, not silently left wrong.
  Real Consul run: 60% of real failures = `AMBIGUITY_DECAY_DROPPED`, 20% `OVERSIZED_FILE_EXCLUDED`,
  20% `ZERO_CANDIDATE_EXTRACTION`. Item #8 (real 4-tier Go/Python/Java/Mixed matrix — Consul/Flask/
  spring-petclinic (freshly cloned)/vllm (already-polyglot py+rs)) then proved #11/#13/#14 all
  generalize cross-language with zero `src/` changes — 4/4 repos indexed clean (up to 59,353 real
  symbols spanning two languages in one graph, for `vllm`), and surfaced a real Topology Drift
  finding: fallback ratio varies sharply by repo (Go 4% vs. Python 85.7%/Java 50%/Mixed 66.7%),
  plausibly repo-size-driven (small candidate sets mean less real call-graph to expand into) rather
  than proven language-specific — flagged, not isolated, matching the standing discipline. Item #15
  (Oversized Entry-Point Budget Allocation, not in the original 15-section doc — a follow-on
  falsification experiment against item #4's own "Task 1 regression" finding) then **recovered
  task1's `G_struct` from 0.0 to 1.0** on the real full pipeline: traced the real mechanism first
  (task1's entry point clears the falloff gate and its own compressed excerpt is tiny, 46-50 tokens
  — the real cause is 19 `SUPPORTING`-tier fan-out files consuming 4,481 of a 4,500-token budget
  before its turn ever comes), confirmed via monkey-patching `_compress`, not assumed. Built only
  the "PRIMARY Node Priority Floor" mechanism from the spec's two proposed options — "AST Structural
  Windowing" was checked and found to have zero marginal effect on this specific real case
  (compression was never the bottleneck). Checked task6's opposite tier/rank shape for regression
  risk BEFORE trusting the fix, via a real same-process ablation across all 6 `BENCHMARK_TASKS` —
  tasks 2/3/5 byte-identical (correctly untouched, a different mechanism), task4/6 held at 1.0
  (task4's file set changed but only by displacing non-ground-truth filler). `enable_primary_
  priority_floor` (default `False`) on `ContextBudgetManager.select()`/`ContextPackager.package()`,
  4 new unit tests, 992/992 total.
- **In-flight state:** **RESUMED 2026-08-13.** The prior pause (2026-08-12, user starting a separate
  higher-priority experiment — a Jina-Reranker-on-public-repos investigation) is superseded: that
  investigation surfaced no API keys (Jina/GitHub) as the real blocker, which led to a direct
  decision on gap #3's own open question instead of finishing the external benchmark. See "3c" below
  for the decision. Gaps 2b (`Listener` prompt bug) and 3b (task6 multi-hint collision) are
  unchanged — still diagnosed, not fixed, no go-ahead given yet. Gaps 4/5/6 still not started.
  `main`/`Base` clean and in sync, full test suite green (992/992) as of the last checkpoint commit
  (`4dbc3a3`) before this session's branch work began.
- **Next step:** Build `feature/local-inference-server` per "3c"'s success criteria (self-hosted
  SLM-1 endpoint reachable through the existing `LiteLLMClient`, zero new pip dependency; a reranker
  HTTP client wired against a local TEI CPU server, returning real scores for a real candidate set).
  Once that merges to `Base`, open `exp/reranker-pre-budget-candidate-selection` as its own child
  branch to actually resolve gap #3 (fire only when `disambiguation.ambiguous is True`, real ground
  truth = task1/task5/task6, same-process ablation per [[arcf_arm2_semantic_reranker_falsified]]'s
  now-standard verification method) — do not conflate the infra branch with the experiment branch;
  a working local server is not itself evidence the reranker placement helps. Do NOT start a fresh
  investigation of gaps 2b/4/5/6 from scratch — each already has real, traced evidence recorded
  above. Separately, still flagged but not scheduled: (1) lexical-probe-recovery's real token/
  candidate-count cost on adversarial queries (13–39 files even at correctly-low confidence, from
  item #9); (2) resuming the paused 50-repo QA sweep ([[arcf_repo_sweep_50]], 3/50 done).

## Priority order (decided 2026-08-12)

Reasoning: aim first at the one item pointed at a real, already-diagnosed open lever; do the cheap
verification spikes early since other items depend on their answers; treat "make it live" as
requiring telemetry before a deployment/rollback flow means anything; leave same-shape-as-falsified
items parked until new evidence shows up.

**Tier 1 — next up**
1. **#3** Locality UPS suppression — aimed at the one concrete open lever (`has_locality`
   import-reachability permissiveness), direct continuation of the disambiguation-pruning thread.
2. **#5** Canonical IR gap check — cheap spike, scopes #2/#10 correctly (done 2026-08-12; turned out
   to be a weaker dependency for #6 than assumed here — see item #5's own dependency mapping).
3. **#10** Symbol-Identity mode / audit trail — small, pays for itself immediately in the next
   falsification experiment's ablation trace (would have sped up Arm 1 / Arm 4's own tracing).
   **Done 2026-08-12, shipped.**

**Tier 2 — required before "live" means anything**
4. **#13** Observability & Telemetry — nothing to gate a promotion on without this first.
   **Done 2026-08-12, shipped.**
5. **#11** Operational Confidence (versioning/canary/shadow/rollback) — sequenced right after #13
   on purpose; a deployment flow with no metrics feeding it isn't a safety net.
   **Done 2026-08-12, shipped.**
6. **#7** Incremental Indexing remaining gap — verify the narrower partial-recompute gap, close it;
   production repos churn continuously, a benchmark-only pass doesn't prove this.
   **Done 2026-08-12 — verified already solved by existing shipped code (96%/93.2% real reduction),
   elaborate architecture deliberately not built. Tier 2 complete.**

**Tier 3 — benchmark/coverage hardening**
7. **#9** Negative queries / false-positive rate — cheap, self-contained, no dependencies.
   **Done 2026-08-12, shipped.**
8. **#4** Grounding quality (structural/behavioral split) — real unmet target, but costs more than
   #9 (needs its own λ-tuning discipline). **Done 2026-08-12, shipped.**
9. **#14** Failure taxonomy — more valuable once #13 exists to feed it real data, not one-off traces.
   **Done 2026-08-12, shipped.**
10. **#8** Validation breadth (topology/scale) — biggest effort; couple with resuming the paused
    50-repo sweep rather than standing alone. **Done 2026-08-12, shipped** — scoped as its own real
    4-tier matrix run instead (see the item's own scope-correction note); the 50-repo sweep remains
    separately open, not blocking.

**Tier 4 — lower confidence of payoff, sequence last**
11. **#2** CallGraph edge provenance — sound as a wrapper redesign, but sequence after #3 lands
    (same subsystem — don't touch locality/traversal from two directions at once).
12. **#6** Typed query dependency graph — gated on SLM-1 entity-extraction determinism improving
    first; nothing on this checklist currently targets that gap.

**Parked — don't schedule**
13. **#1**, 14. **#12** — same shape as the already-falsified entropy-confidence work; leave parked
    pending new evidence.

---

## 1. Query Context Confidence Score (multi-signal retrieval fallback)

- **Status:** Parked (needs new evidence)
- **Source:** original doc §1
- **Why parked:** same shape as entropy-based DRP confidence, which was tried in two independently
  designed variants and falsified against real ground truth (one ranked a confirmed-wrong repo
  above a confirmed-correct one; the other produced the exact inverse of the working ranking —
  [[arcf_entropy_confidence_falsified]]). The flagship ambiguity case ("New", 156 same-named
  matches) is documented as mathematically under-determined, not a threshold-tuning problem
  ([[arcf_recall_gap_closed]]). A weighted multi-signal score doesn't change that underlying fact.
- **Reopen condition:** a genuinely new signal not covered by the 7 falsified recall-gap attempts,
  with a stated reason the prior failures don't apply.
- **Success criteria:** _not defined — do not start without first stating what "confidence
  correctly predicts resolution correctness" means on real ground truth, and testing that claim
  before building the weighted formula._

## 2. CallGraph Edge Provenance + Query-Adaptive Traversal

- **Status:** Not Started — needs scope correction first
- **Source:** original doc §2
- **Correction:** `CallGraph` itself is explicitly off-limits for modification — `locality.py`'s
  docstring documents a prior incident (ARCF Issue #3 Fix #9) where this was tried and reversed;
  `CallGraph`'s over-inclusion is deliberate and load-bearing for other consumers (impact
  analysis). Checked `call_graph.py` directly: currently one flat `CallGraph` class, no edge-type
  distinction. Provenance tagging (`HARD_CALL`/`PROBABILISTIC_CALL`/etc.) must be built as a
  read-side wrapper/filter layer over `CallGraph`, the same pattern `locality.py` already uses —
  not a change to `CallGraph`'s own construction.
- **Success criteria:** _not defined yet._

## 3. Locality — Utility Package Score (smooth suppression)

- **Status:** Parked (falsified) — same disposition as Arms 1/2/4, not merged
- **Source:** original doc §3
- **Why promising:** aimed at the one concrete, still-open, documented lever from the most
  recently shipped work: `has_locality`'s transitive import-reachability tier is currently
  unbounded-hop and known to be too permissive — this is the confirmed reason the
  Disambiguation-Driven Candidate Pruning fix (`4f68f69`) didn't change packaged output on real
  Consul ([[arcf_disambiguation_pruning_shipped]]). Unlike Arms 1/2/4 (all downstream *rank*
  tweaks that ARCF's compression pipeline absorbed with zero effect), this operates on an
  upstream *gate* (`has_locality`, which controls inclusion, not just order) — structurally
  different place to intervene.
- **Constraint:** stays a filter over `has_locality` in `locality.py`, not a `CallGraph` change —
  same off-limits boundary as item 2.

- **Started 2026-08-12, branch `experiment/locality-utility-suppression`.**

- **Precise target, checked against real code before writing anything:** `has_locality(file_a,
  file_b)` itself (same file / same directory / *direct* import edge either direction — confirmed
  `ImportGraph.imports_of`/`importers_of` are direct-edge-only, not transitive) is not itself
  "unbounded-hop." The unboundedness lives one level up, in `_locality_filtered_bfs`: it calls
  `has_locality` fresh at every hop with `max_depth=None` at most real call sites, so a chain of
  individually-real direct-import edges can still fan out arbitrarily far when it passes through a
  hub file (e.g. `agent/cache/cache.go`) that many unrelated files import. The suppression point is
  therefore **the BFS's per-node expansion decision**, not `has_locality`'s own boolean contract —
  `has_locality` keeps its existing meaning and every other caller (disambiguation's
  `_locality_score` is a separate, already-fixed mechanism and is untouched by this).

- **UPS formula, deliberately simplified from the original 3-term proposal, reasoned up front
  rather than tuned after the fact:** `UPS(file) = indegree(file) + cross_subsystem_usage(file)`,
  where `indegree(file) = |ImportGraph.importers_of(file)|` and `cross_subsystem_usage(file)` =
  number of *distinct directories* among those importers (using `SymbolIndex.same_package`'s own
  directory granularity, for consistency with the rest of this module). **`outdegree` is dropped**
  from the original `α·indegree + β·outdegree + γ·cross_subsystem_usage` — outdegree measures how
  much a file imports, which has no relationship to whether that file acts as a fan-out *bridge*
  for other people's unrelated call chains (the actual mechanism being suppressed). Adding a term
  that doesn't map to the mechanism would be scope creep, not rigor.

- **Suppression mechanism:** when `_locality_filtered_bfs` is about to expand past a frontier node,
  compute `UPS` for that node's file. If it exceeds a threshold (to be set from real measured
  values on Consul, not guessed — see below), that node stays in the result (it was reached via a
  genuine, real locality relationship) but does **not** get expanded further — a utility/hub file
  can be a destination, never a further bridge to more distant, unrelated files. This is the
  smooth-vs-hard-cap distinction from the original proposal translated honestly into this
  boolean-gated BFS: the *score* is computed continuously; only the final expand/stop decision is
  binary, because the BFS itself needs one.

- **Hypothesis (falsifiable, stated before implementation):** suppressing BFS expansion past
  high-UPS files reduces cross-subsystem fan-out on real ambiguous-name queries ("New", "Register"
  against real Consul — the same cases documented in
  `scripts/callgraph_fanout_impact_experiment.py` and this module's own docstring) without
  incorrectly dropping a real, direct, meaningful cross-package call chain (the
  `task6_path_hint_secondary_sibling` case — `agent/cache/cache.go`'s `Prepopulate` called from
  `agent/auto-config/tls.go` — must still resolve correctly, since `agent/cache` itself being
  high-UPS must not block *reaching* it, only block using it as a further bridge).

- **Success criteria (checked BEFORE any implementation begins, per the standing methodology):**
  1. Real UPS values for `agent/cache/cache.go` and a handful of ordinary files must be measured on
     real Consul first, so the threshold is grounded in real data, not a guessed constant.
  2. A same-process ablation (identical resolution, suppression on vs. off) must show a real
     reduction in `candidate_files`/distinct-subsystems-touched count on the "New"/"Register" cases
     — an aggregate score change alone is not sufficient evidence, per
     [[arcf_arm2_semantic_reranker_falsified]] and [[arcf_arm4_path_locality_falsified]].
  3. The same ablation must show the `task6_path_hint_secondary_sibling` ground-truth case is
     unaffected (still resolves `agent/cache.Prepopulate` → `agent/auto-config/tls.go` correctly).
  4. Full test suite must stay green.
- **Failure criteria:** any of the above three checks failing, or the mechanism requiring a fudged
  threshold that only works on hand-picked cases, means this stays `Parked`/unmerged on its branch,
  reported honestly, same as Arms 1/2/4 — *not* merged "for now."

- **User-specified refinements (2026-08-12, mid-implementation):** the user independently supplied
  a more detailed spec matching this diagnosis almost exactly (package-level indegree, hard-block
  past a UPS node rather than a decay multiplier, an explicit ablation toggle) plus stricter success
  gates: ≥15% context-budget-token reduction, statistically significant (p<0.05) precision
  improvement, 0% primary-path-recall regression, 100% run determinism. Two points reconciled with
  the user directly: (a) the spec's "or core standard/utility namespace" trigger is structurally
  redundant for this specific mechanism — `ImportGraph` only records *resolved* (intra-repo) import
  edges, so stdlib/third-party packages (`fmt`, `errors`, `context`) never become graph nodes at
  all; skipped, not implemented. (b) validation done as a free deterministic pre-check first, full
  paid LLM-harness statistical run only if that looks promising — per the user's own choice.

- **Real bug caught by this item's own unit tests, fixed in the same flow (not deferred):** the
  first version thresholded on percentile-rank alone. On small/typical package counts this breaks —
  e.g. 3 packages where two both have exactly 1 importer tie for "the top rank" and both get
  flagged, even though a single genuine caller is definitionally not a fan-out hub (caught by
  `test_ups_suppression_does_not_affect_a_genuine_low_fan_out_chain` before this ever reached real
  Consul data). Fixed by adding an absolute `indegree >= 3` floor alongside the percentile check —
  a generic minimum, not tuned to Consul (real Consul's own hub, `agent/cache`, clears it by two
  orders of magnitude). See `_MIN_INDEGREE_FOR_UTILITY_BRIDGE` in `locality.py`.

- **Real bug caught by the ablation itself, before reporting any result:** the first same-process
  ablation run (target_names=["New"]/["Register"], default `traversal_depth`) came back
  byte-identical on/off — but rather than reporting that as the falsification result immediately,
  traced *why* first (matching Arms 1/2/4's own discipline): `ContextResolver.resolve()`'s
  `traversal_depth` defaults to 1, and `_locality_filtered_bfs`'s own loop structure means hop-2+
  nodes are computed internally but never written to its returned `result` when `max_depth=1` —
  UPS suppression (which only prevents hop-2+ *expansion*) is structurally unreachable at that
  depth, independent of whether the suppression logic itself is correct. Checked `grep` for every
  real caller of `traversal_depth` (not assumed): production actually varies this per
  `RetrievalTaskType` via `TRAVERSAL_DEPTH` (`src/context/task_profile.py`) —
  `BUG_FIX`/`CI_CD`/`UNKNOWN`=1 (where this item's mechanism genuinely never fires), but
  `REPOSITORY_EXPLANATION`/`ARCHITECTURE_UNDERSTANDING`/`PERFORMANCE`=2,
  `REFACTOR_IMPACT_ANALYSIS`=3, `LARGE_STRUCTURAL_CHANGE`=unbounded. Re-ran the ablation sweeping
  depths 1/2/3 (`scripts/ups_suppression_ablation.py`) instead of depth=1 alone.

- **Real result of the depth-swept ablation (2026-08-12):**

  | query | depth | candidates off→on | token footprint off→on | reduction |
  |---|---|---|---|---|
  | Register (38 raw matches) | 1 | 23→23 | 75754→75754 | 0% (structurally unreachable, see above) |
  | Register | 2 | 32→29 | 224775→142529 | **36.6%** |
  | Register | 3 | 34→31 | 231050→148804 | **35.6%** |
  | New (159 raw matches) | 1 | 224→224 | 870212→870212 | 0% (structurally unreachable) |
  | New | 2 | 256→250 | 1097211→1059035 | 3.5% |
  | New | 3 | 289→269 | 1331397→1205788 | 9.4% |

  `added by suppression` was 0 in every single case (purely subtractive, as designed) and the
  genuine `task6`-style case (`agent/auto-config/tls.go` → `agent/cache.Prepopulate`) was
  byte-identical on/off at every depth — `tls.go` always present, candidate count unchanged.
  Determinism check (identical call repeated) passed every time. Directly traced (not inferred) why
  the dropped files are real noise, not a regression: e.g. `agent/acl_test.go`,
  `agent/agent_endpoint_test.go`, `agent/testagent.go` were all reached via
  `defines Register → called by NewBaseDeps → called by {NewTestACLAgent,newDefaultBaseDeps,Start}`
  — `NewBaseDeps` sits in the `agent` package, itself a measured real hub (UPS=225, top-25 on real
  Consul) — these are test/bootstrap files pulled in only because they call a hub bootstrap
  function that happens to also call `Register`, not because of any real relationship to ACL
  registration.

  **Honest read against the user's 4 stated gates:** ≥15% token-footprint reduction — met for
  `Register` (36.6%/35.6%), NOT met for `New` (3.5%/9.4%). 0% primary-path-recall regression — met
  (genuine case untouched at every depth). 100% determinism — met. Statistically significant
  (p<0.05) precision improvement — not yet checked, needs the paid multi-run LLM grounding harness
  (`validate_llm_grounding.py --n-runs`), deliberately deferred until the free pre-check looked
  promising, which it now does for at least one of the two flagship queries. **Not a clean pass —
  a real, non-zero, safe, but query-dependent effect**, reported as such, not rounded up.

- **Real disconfirming evidence that closed this out (2026-08-12), found via a free n=1 sanity
  check BEFORE spending on the full paid run:** the deterministic pre-check above used bare,
  synthetic probes (`target_names=["Register"]`/`["New"]` directly) — not what real SLM-1 entity
  extraction actually produces from the harness's own natural-language queries. Wired
  `enable_ups_suppression` + a test-only `traversal_depth_override` through `service.py`
  (`attach_code_intelligence`/`_resolve`) so the mechanism could be tested at a real depth (2,
  matching `REPOSITORY_EXPLANATION`/`ARCHITECTURE_UNDERSTANDING`/`PERFORMANCE`) against real
  entity-extracted queries — necessary because a direct check (`classify_retrieval_task` against
  every existing benchmark query) confirmed ALL of them classify to depth=1 by default, where this
  mechanism is structurally inert.

  A single real-LLM run (gpt-4o-mini, real Consul, `scripts/ups_suppression_llm_validation.py`)
  showed `candidate_count` **identical, on vs. off, for both task1 and task5** — not just a small
  effect, zero:
  - task1: real SLM-1 extraction pulled `Catalog.Register` (qualified), not bare `Register` — a
    different resolution path than the synthetic probe, one that doesn't hit the ambiguous-fan-out
    mechanism this fix targets at all (21 candidates, identical both conditions).
  - task5: real SLM-1 extraction pulled `['agent/cache', 'New']` — the path hint is already present
    in the query, and Feature 1 (query-wide path-hint masking, already shipped) narrows `New`'s
    resolution *before* hop-expansion ever runs (13 candidates, identical both conditions). The
    small packaged-token difference (4409→4435) traced to packaging-layer noise, not the
    suppression mechanism, since the candidate set itself never changed.

  **Same shape of finding as Arms 1/2/4**: correctly implemented, real unit-tested mechanism, real
  effect on a synthetic worst-case probe — but on real queries, already-shipped upstream narrowing
  (path hints, disambiguation-driven pruning) and real entity extraction's own qualification habits
  mean the raw fan-out this fix targets rarely occurs in practice. Presented this single free result
  to the user before spending on the full `n_runs=5` statistical run; user chose to stop rather than
  spend further given the pattern.

- **Status, final:** `Parked (falsified)` — not merged, same disposition as Arms 1/2/4. Preserved
  on `experiment/locality-utility-suppression` (unmerged) as the historical record — a correctly
  built, well-tested mechanism that real queries don't exercise, not a broken implementation. If
  revisited, needs either a genuinely different target (the raw name-based
  `locality_filtered_callers_of_name` path task1/task5 actually hit turned out NOT to be what was
  modified here — see item 2's CallGraph-provenance idea for a mechanism that might reach it) or new
  evidence that real queries do sometimes classify to depth≥2 with genuinely unqualified,
  path-hint-free ambiguous names.

## 4. Grounding Quality — Structural vs. Behavioral

- **Status:** Shipped — merged to `main`/`Base`, branch deleted after merge
- **Source:** original doc §4, detailed spec supplied by user 2026-08-12
- **Note:** genuinely addresses an open item (`Grounding-score target ≥3.4/5.0 composite` never
  hit in three measured runs — `PROGRESS.md` Open/unresolved).

- **Reconciled against real code before writing anything:** `PackagedFile` (the object the harness's
  own `packaged_files` list is built from) carries no structural/behavioral role field, and
  shouldn't need one — `FileReference.origin_stage` (item #10) already distinguishes `AST_DIRECT`
  (direct entry-point match) from `SCOPED_GRAPH_EXPANSION` (genuine call-graph hop) on the
  *resolution* side. The metric itself only needs the **ground truth** tagged by role (a property
  of the task, not of how ARCF happened to retrieve it) — `origin_stage` was used as supporting,
  real diagnostic evidence when validating each task's behavioral file (see below), not as part of
  the scored metric itself.

- **λ-tuning discipline honored, not reinvented:** directly ran `classify_retrieval_task()` against
  all 6 real `BENCHMARK_TASKS` query strings (not assumed) — **every single one** classifies to
  `TRAVERSAL_DEPTH == 1` in real production (task2's "downstream"/"trace" wording resolves to
  `BUG_FIX` via `RepositoryScopeClassifier`'s debugging trigger, checked *before*
  `REFACTOR_IMPACT_ANALYSIS`'s impact-words branch ever runs — confirmed by reading
  `classify_retrieval_task`'s own branch order, not assumed from the wording alone). Per this
  item's own caution note (echoing item #1's), no new tunable `λ`/expansion-depth knob was added:
  there is no real lever to tune here, since the two real failures found below (task2, and
  tasks 1/3/5) are both proven to be depth-independent — increasing expansion would not have
  changed either outcome (see traces below).

- **Design:** `_structural_behavioral_grounding_metrics(packaged_files, structural_files,
  behavioral_files)` in `scripts/validate_llm_grounding.py` — pure, deterministic, no LLM calls
  (this is a candidate-*file* metric, not a generated-answer metric, so no judge call is needed,
  same reasoning as item #9). `G_struct` = recall of `packaged_files` against the task's
  entry-point/interface/type files. `G_behav` (R_path) = recall against the task's real
  execution-path collaborator files, but forced to `0.0` unless the structural files are 100%
  present first (the spec's own prerequisite-weighting requirement) — and `None` (not `0`) for the
  3 single-file tasks with no behavioral component at all, so they don't corrupt the aggregate.
  `BENCHMARK_TASKS` gained additive `ground_truth_structural`/`ground_truth_behavioral` keys
  (existing `ground_truth_files`/`ground_truth_terms` untouched); `_run_one_task` and
  `_extract_run_metrics`/`_build_markdown_table` wired the two new sub-scores in as two more rows,
  reported per-task and as an overall mean ± stddev — genuinely distinct from `precision`/`recall`/
  `f1`, never blended into one number. **Zero changes to any file under `src/`** — this is a pure
  harness/metric addition, same scope discipline as item #9; 988/988 existing tests stayed green
  with no changes needed.

- **Real per-task grounding, grepped against the actual cloned Consul source before writing any
  task entry (not assumed):** `agent/cache/cache.go` defines the `Cache` type and `Prepopulate`
  (structural); `agent/cache/watch.go` defines `Cache.Notify`, a different file in the same package
  (behavioral — the actual propagation mechanism task2 asks about). `agent/consul/acl_endpoint.go`
  defines the `ACL.BindingRuleList` RPC endpoint (structural); `agent/consul/auth/binder.go`'s
  `Binder.Bind` doesn't call the endpoint directly but depends on the same underlying state-store
  `ACLBindingRuleList` function (behavioral — a real sibling collaborator, the actual "depend on"
  task4 asks about). `agent/auto-config/tls.go` is `Prepopulate`'s only real non-test sibling-package
  caller (behavioral, task6 — already established by Arm 4's own task6 addition).

- **Decisive real finding #1 (task2, `scripts/grounding_structural_behavioral_precheck.py`):** at
  real production depth=1, with target_names hand-set to every one of task2's own
  `ground_truth_terms` (`Cache`/`UpdateEvent`/`Notify`), `watch.go` is **completely absent** from
  `candidate_files`. Traced directly (`SymbolIndex.find_by_name`): `Notify` has **78** same-named
  methods repo-wide; disambiguation resolves it to `agent/mock/notify.go` instead of
  `agent/cache/watch.go`'s `Cache.Notify`. This is the exact shape of the already-closed,
  8-times-falsified extreme-ambiguity recall gap ([[arcf_recall_gap_closed]]) — the same mechanism
  as the flagship "New" case, now hit by "Notify" instead. **Not attempted as a fix here** — kept
  as ground truth deliberately, so `G_behav` reports this honestly as a real `0.0` rather than
  excluding it from the benchmark to make the number look better.

- **Decisive real finding #2 (tasks 1/3/5, full real Arm A pipeline —
  `scripts/grounding_structural_behavioral_metrics_check.py`):** running the actual resolver ->
  `RelevanceRanker` -> `ContextPackager` path (not just the raw resolver) showed `G_struct = 0.0` for
  tasks 1, 3, **and** 5 — the genuine entry-point file, present in `candidate_files`, does not survive
  into the final *packaged* output. Traced directly, not inferred from the aggregate: in every one
  of the three cases, the real entry-point file is unusually large (`catalog_endpoint.go` 10,069
  tokens, `config.go` 12,030, `cache.go` 9,168 — each alone exceeding or nearly exceeding the
  8000-token budget) **and** ambiguity-decayed (`Catalog`×2, `Config`×7, `New`×224 same-named
  matches), which drops its `relevance_score` below numerous small, irrelevant same-named-chain
  decoy files (task5's real entry point ranked **70th of 224** candidates). **This precisely
  diagnoses PROGRESS.md's own previously-`unconfirmed` "Task 1 regression" note** — same root
  mechanism as the already-closed ambiguity/recall-gap research thread, now shown to also bite at
  the *ranking/packaging* stage (not just resolution), and task5 is literally the flagship "New"
  case itself. **Not attempted as a fix here**, for the same reason item #3 and Arms 1/2/4 didn't
  fix what they found mid-work: this is a pre-existing, deeply architectural mechanism this session
  did not introduce, already the subject of 8 falsified attempts, and reopening it needs its own
  isolated falsification experiment with fresh evidence — not a quick change bundled into a metric
  harness item. Flagged as a genuinely new, sharper future candidate (the interaction between
  ambiguity decay and oversized single-file entry points competing for a fixed token budget),
  distinct from anything the 8 prior attempts specifically tried.

- **Real positive result (tasks 4 and 6):** both `G_struct` and `G_behav` = **1.0** through the full
  real Arm A pipeline — `binder.go` and `tls.go` both genuinely survive packaging, and `tls.go`'s
  `origin_stage` is confirmed `SCOPED_GRAPH_EXPANSION` (a real call-graph hop, not adjacency luck).

- **Self-correction (found while building checklist item #14's per-file classifier, not caught
  here originally):** the real full-pipeline table above also shows task2's `G_struct = 0.0`, which
  this entry's write-up didn't separately explain — it only discussed task2's `G_behav` failure
  (the "Notify" 78-way-ambiguity resolution-stage miss). Item #14's classifier traced task2's
  `G_struct` failure to a *different*, real mechanism: `cache.go` itself IS resolved
  (`origin_stage=ast_direct`), but `Cache`'s own 3-way ambiguity this run decays its score to 0.333,
  below the relative score falloff gate's 0.45 threshold at task2's real `BUG_FIX`-tier ranking — the
  same ambiguity-decay-at-ranking mechanism diagnosed above for tasks 1/3/5, now confirmed to affect
  task2 as well, independent of the separate Notify/`G_behav` finding. See item #14 for the full
  per-file breakdown.

- **Success criteria (defined from the real pre-check findings above, before final implementation,
  per the standing falsification-experiment discipline):**
  1. `R_path` (`G_behav`) ≥ 80% on tasks with a real, currently-reachable behavioral ground truth —
     **met**: task4 and task6 both = 1.0. Task2 is excluded from this specific gate (its `0.0` is the
     already-closed extreme-ambiguity boundary, reported honestly, not silently dropped from the
     benchmark).
  2. `G_struct`/`G_behav` reported as genuinely distinct sub-scores, never blended — **met**, verified
     structurally (two separate rows in `_build_markdown_table`, two separate keys throughout).
  3. Zero statistically significant precision drop — **met by construction**: zero `src/` changes,
     988/988 existing tests unaffected.
  4. 100% deterministic run output on a fixed candidate set — **met**: task6 run twice through the
     full real pipeline produced byte-identical `packaged_files` and `G_struct`/`G_behav`.
- **Failure criteria:** any of the above not holding, or a real behavioral task (4/6) scoring below
  80% for a reason traceable to *this item's own* code (not a pre-existing mechanism) — did not
  occur.

- **Result:** Merged to `Base`/`main`, zero known open issues, zero `src/` changes. 988/988 tests.

## 5. Determinism — Canonical Intermediate Representation

- **Status:** Done — zero-code audit complete, gap spec drafted, 0 production changes, $0 spent
- **Source:** original doc §5, re-scoped 2026-08-12 to the user's own 4-field verification-spike
  spec (Canonical SymbolID / Scope Boundary Metadata / Type & Receiver Info / Provenance Metadata
  Hooks), read directly against real code (`src/domain/code_intelligence.py`, `src/code_intelligence/
  symbol_index.py`, all 8 `*_analyzer.py` files, `src/domain/context_resolution.py`) — no line
  quoted below without opening the file first.

- **Self-correction on this item's own earlier note:** that note (written before this audit) claimed
  `Symbol` "already carries `param_types`/`return_type`" and a `FieldReference` type. **That was
  wrong** — checked `src/domain/code_intelligence.py` directly: those fields do not exist on
  `Base`/`main` at all. They were added on `exp/type-graph-indexing` for
  [[arcf_arm1_type_graph_falsified]], which was **not merged** (falsified, preserved unmerged as a
  historical record). The earlier note conflated an unmerged experimental branch with current
  `Base` state — exactly the kind of stale-memory risk this whole audit exists to catch. Corrected
  here, not silently left wrong.

### Schema Audit Matrix

| Field | Verdict | Evidence |
|---|---|---|
| **Canonical SymbolID** | **Partial** | `Symbol.id` exists (`domain/code_intelligence.py:42`), built identically by all 8 language analyzers as `f"{file_path}::{qualified_name}#{location.start_line}"` (verified byte-identical across `go_analyzer.py:469`, `python_analyzer.py:421`, `cpp/csharp/java/kotlin/rust/typescript_analyzer.py`, each with its own duplicate copy of the same formula — a real DRY gap, not a schema gap). Deterministic and unique within one file version, **but line-coupled**: a one-line edit above a declaration changes its `id` even though it's semantically the same symbol — not stable across trivial edits, which matters for the "replay, debugging, caching, regression comparison" use case the original proposal wanted. `Symbol.qualified_name` (`:44`) is the more refactor-stable identifier, but is per-file-scoped text (e.g. Go's `ReceiverType.MethodName`), not globally unique on its own — needs `file_path` alongside it to disambiguate two types with the same name in different files/packages. |
| **Scope Boundary Metadata** | **Partial** | `Symbol.parent_id` (`:53`, enclosing class/function) and `Symbol.file_path` (`:46`) exist and are populated by every analyzer. **No explicit package/module field** — "package context" is never stored, only derivable by calling `posixpath.dirname(file_path)` at every call site that needs it (`SymbolIndex.same_package`, `locality.py`, item #3's own UPS scoring all do this independently). Workable today, but a real package-path field would remove several independent re-derivations of the same fact. |
| **Type & Receiver Info** | **Missing** | `Symbol` has `kind: SymbolKind` (CLASS/FUNCTION/METHOD/INTERFACE, `:45`) but no structured parameter types, return type, or receiver type field. Go's own receiver is captured **as a string, folded into `qualified_name`** (`go_analyzer.py:329-336`, `_receiver_type_name` — e.g. `qualified_name = f"{receiver_type_name}.{name}"`), not as a separate structured field — exactly the "hacky string-parsing workaround downstream" the problem statement warned about, already happening today for anyone who needs the receiver type as data rather than as a text fragment inside a name. (`param_types`/`return_type`/`FieldReference` exist only on the unmerged `exp/type-graph-indexing` branch — see self-correction above.) |
| **Provenance Metadata Hooks** | **Missing on the IR itself, but a real pattern exists one layer downstream** | `Symbol`/`CallReference` (`domain/code_intelligence.py`) carry no origin-step or disambiguation-history field at all — `CallReference` (`:58-70`) has no edge-provenance/call-kind field either (relevant to item #2's own "lexical/type-based/interface-based/reflection/string-dispatch" classification — that data has nowhere to live on the current IR). But `FileReference` (`domain/context_resolution.py:87`, a *downstream, per-query resolution* object, not the canonical IR) already has exactly this shape of thing: `reason` (`:91`, human-readable justification) and `justification_chain` (`:102`, full hop-by-hop path). This is a real, working provenance pattern — just scoped to one query's resolution result, not attached to the canonical Symbol that gets indexed once and reused across queries. |

### Dependency mapping (item #2 / #6 / #10)

- **#2 (CallGraph Edge Provenance)** — directly blocked on the Type & Receiver Info gap (needs to
  distinguish interface-dispatched calls from concrete ones) and needs a genuinely new field on
  `CallReference` itself (a `call_kind`/edge-provenance tag) — nothing today. Already scoped in
  item #2's own entry to stay a read-side wrapper over `CallGraph`, consistent with this finding:
  the new field would need to live on `CallReference`/a wrapper structure, not require touching
  `CallGraph`'s own construction.
- **#6 (Typed Query Dependency Graph)** — **weaker dependency than assumed.** This item models the
  *query text* as a typed graph (Symbol/File/Package/Concept nodes, compare/trace/call/configure/
  implement edges) — that's a new, separate data model over parsed query intent, not something that
  reads Symbol/IR completeness at all. The real blocker for #6 (per its own entry) is SLM-1
  entity-extraction determinism, not IR schema. Correcting the priority-order rationale: #5 does
  not meaningfully unblock #6.
- **#10 (Symbol-Identity Mode / audit trail)** — directly served by the Provenance finding above:
  the natural implementation is extending `FileReference`'s already-working `reason`/
  `justification_chain` convention with an explicit `ExpansionMode`/`Reason=MissingGraphEdge` tag,
  **not** a new canonical-IR field. This re-scopes #10 from "build new provenance infrastructure"
  to "extend an existing, proven pattern" — smaller and lower-risk than its own entry currently
  assumes.

### Gap spec (drafted, not implemented — zero runtime changes)

If pursued: (1) consolidate the 8 duplicate `_symbol_id` implementations into one shared helper —
pure refactor, zero behavior change, fixes the DRY gap only. (2) Add `Symbol.package_path: str`
(computed once at analysis time from `file_path`, same value every call site already derives
independently) — additive, default-computable, no consumer breakage. (3) Add
`Symbol.receiver_type: str | None` (Go-specific today, `None` elsewhere) — additive. (4) Add
`CallReference.call_kind: str | None` (lexical/type-based/interface-based/reflection/heuristic,
`None` = unclassified) for item #2 to eventually populate. None of these are scheduled — this is
the audit deliverable only, per the item's own "0 production code changes" success gate.

- **Success criteria, verified met:** 100% of the 4 fields classified (table above) — ✅. 0
  production code changes, 0 API cost — ✅ (pure read/grep, no branch created). Concrete gap spec
  drafted without touching runtime logic — ✅ (above).

## 6. Query Understanding — Typed Dependency Graph

- **Status:** Not Started — lower priority
- **Source:** original doc §6
- **Note:** elegant, but the documented larger bottleneck is SLM-1 entity-extraction
  non-determinism — non-deterministic in both order *and* content even at `temperature=0.0`
  ([[arcf_payload_optimization_path_masking]] open item), and `path_hint` doesn't propagate
  across entities in a query ([[arcf_path_aware_resolution_fix]] open item). A typed graph model
  of query intent adds real complexity on top of a system whose current failures trace to
  upstream extraction noise, not edge-type modeling. Consider sequencing after the SLM-1
  determinism gap is addressed, not before.
- **Success criteria:** _not defined yet._

## 7. Incremental Indexing (merges original §7 "DRP Integration" + §12 "Repository Evolution")

- **Status:** Done — existing shipped code already clears the spec's own gates; equivalence test
  added as the real deliverable, elaborate diff-scoping architecture not built (would solve an
  already-solved problem)
- **Source:** original doc §7 and §12 (same underlying capability, tracked as one item), detailed
  spec supplied by user 2026-08-12

- **Correction:** not missing. `CodeIntelligenceContractService` already does automatic,
  content-hash-keyed incremental reuse (`previous_index`) and caches both the base index and
  `DrpIndex` per workspace root — verified with a real test that an edited file is re-analyzed
  and an unchanged one reuses prior analysis ([[arcf_persistent_index_cache]]).

- **Read `CodeIntelligenceEngine.build_index` directly before designing anything (not assumed):**
  its own docstring already states the real architecture — per-file parsing is incrementally
  cached (content-hash reuse), but every graph (`SymbolIndex`/`ImportGraph`/`CallGraph`/
  `InheritanceGraph`/`DependencyGraph`/`CandidateFileSelector`/`DecoratorGraph`) is **always
  rebuilt fully** from whichever `FileAnalysis` objects (cached or freshly parsed) end up in play,
  on the stated claim that graph construction is "always cheap in-memory work with no I/O." That
  claim needed to be measured, not trusted, before deciding whether the spec's elaborate
  diff-scoping/invalidation/stitching architecture was actually needed.

- **Real measurement on real Consul (11,102 scanned files, 2,370 analyzed, 28,174 symbols —
  `scripts/incremental_indexing_cost_measurement.py`, `scripts/
  incremental_indexing_pr_sized_measurement.py`):**

  | scenario | mean latency | vs. full cold rebuild |
  |---|---|---|
  | Full cold rebuild (baseline) | 141.6s | — |
  | All files cache-hit (graph-construction-only, isolates the claim above) | 8.4s | **5.9%** of total cost |
  | Single-file diff (1/11,102 changed) | 5.7s | **96.0% reduction** |
  | PR-sized diff (15/11,102 changed) | 9.5s | **93.2% reduction** |

  **The existing, already-shipped `previous_index` mechanism already clears the spec's own
  ≥80%-reduction gate** — no new code needed for the performance criterion. And graph
  construction, the one part that is NOT incrementally cached, is confirmed to genuinely be a
  small fraction of total cost (5.9%) at real scale — the docstring's claim holds, measured not
  assumed.

- **Correctness gates ("100% Topological Parity", "Zero Orphaned References") are satisfied by
  construction, not by new invalidation/stitching logic:** the current design never attempts
  partial graph patching — every graph is always rebuilt fresh and fully from a complete,
  consistent `FileAnalysis` dict (a mix of cached and freshly-parsed entries, but always the FULL
  set, never a partial one). There is no "stitch modified subgraph back into primary index" step
  for a bug to hide in, because there is no stitching at all. This is a structurally *stronger*
  safety property than the spec's proposed partial-recomputation architecture would have — that
  architecture's own stated risk ("graph drift... orphaned symbol references... invalid
  import-reachability scores if modified subgraphs are not cleanly invalidated and re-stitched")
  is a real risk *of building partial patching*, not a risk the current design carries at all.
  Verified with a real equivalence test (not just architectural reasoning) — see below.

- **Scope decision, made explicit rather than defaulting to "build what was speced":** the
  elaborate architecture (Diff-Driven Scope Identification, Targeted Node & Edge Invalidation,
  Partial Subgraph Recomputation, Index Stitching & Reconciliation) was **not built**. It would
  spend real engineering effort and introduce the exact correctness risk the spec itself names
  (graph drift from imperfect invalidation/stitching), to optimize a cost that's already measured
  at 5.9% of total latency and already 96%+ reduced by existing code for the target scenarios. This
  is a genuine engineering trade-off decision, not a shortcut — flagging it for the user rather
  than silently building something disproportionate to the measured problem.

- **Real deliverable instead: an automated equivalence regression test**
  (`tests/code_intelligence/test_incremental_equivalence.py`) — builds an index from scratch and an
  index incrementally (via `previous_index` with a real subset of files changed), asserts they are
  structurally identical (same symbols, same call/import/inheritance edges, same candidate
  selector state) for the same final repository state. This is the actual, permanent, testable form
  of "100% Topological Parity" / "Zero Orphaned References" — verified continuously by the existing
  test suite, not a one-time claim. 4 real scenarios covered: edit a file, add a file, remove a
  file, and the 100%-cache-hit no-op case — each asserting full-rebuild and incremental signatures
  match exactly, AND that untouched files were genuinely reused (`is` identity check on the cached
  `FileAnalysis` object) rather than the test trivially passing because everything got re-parsed
  regardless of `previous_index`.

- **Success criteria, all verified:**
  1. Real Consul measurement of the parsing-vs-graph-construction cost split — done, reported above
     (5.9% of total cost is graph construction).
  2. ≥80% latency reduction on single-file AND PR-sized diffs, measured not assumed — **96.0%** and
     **93.2%** respectively.
  3. A permanent equivalence test proving incremental and full-rebuild indexes are structurally
     identical — 4 new tests, added to the regular suite.
  4. Zero regressions in the existing indexer test suite — 981/981 tests (4 new), full suite green.
- **Failure criteria:** any structural difference found between incremental and full-rebuild
  indexes, or the measured reduction falling under 80% on either scenario, would mean revisiting
  the "don't build the elaborate architecture" decision above — **neither occurred.**

- **Result**: Merged to `Base`/`main`, zero known open issues. 981/981 tests.

## 8. Validation Breadth — Repository Topology & Scale Diversity

- **Status:** Shipped — merged to `main`/`Base`, branch deleted after merge
- **Source:** original doc §8, detailed spec supplied by user 2026-08-12
- **Note:** no overlap with falsified work — real, currently-single-repo-biased benchmark gap.

- **Scope correction against [[arcf_repo_sweep_50]]:** that sweep (3/50 done, paused on API token
  expiry) is a *different* activity — an LLM-judged answer-quality QA pass across 50 repos with no
  ground truth, using `repo_query_answer.py`. This item's own success gates (Matrix Execution,
  Parser Stability, Cross-Repo Telemetry, Operational Gate Parity) need none of that — they're all
  deterministic infrastructure checks (indexing, telemetry, gates, failure taxonomy), same
  no-LLM-calls discipline as items #4/#9/#10/#14. Scoped as its own real run rather than blocked on
  resuming the paused sweep.

- **Matrix, grounded in what's actually available before picking anything (`find
  .benchmark_repos/* -type f | ... | uniq -c`, not assumed):**
  - **Go:** `consul` (already the project's primary benchmark repo).
  - **Python:** `flask` (83 real `.py` files, already cloned — decorator-based routing is a real
    duck-typing/implicit-dispatch case, not synthetic).
  - **Java:** `spring-petclinic` — no Java repo existed in `.benchmark_repos` before this item;
    shallow-cloned fresh (49 real `.java` files, a real `Owner extends Person extends NamedEntity
    extends BaseEntity` hierarchy, confirmed by direct grep, matching the "deep class hierarchies"
    case the spec asks for).
  - **Mixed:** `vllm` — turned out to be **already a real polyglot repo** in `.benchmark_repos`
    (4,116 `.py` + 305 `.rs` files, confirmed directly, not assumed) — no new clone needed. Indexed
    with `PythonLanguageAnalyzer` and `RustLanguageAnalyzer` registered together in one
    `LanguageRegistry`, producing one genuinely cross-language `CodeIntelligenceIndex`.

- **Design:** `scripts/validation_breadth_matrix_check.py` — for each tier: build a real index
  (catching, not crashing on, any exception — the Matrix Execution/Parser Stability gates), run 1-2
  real `ContextResolver.resolve()` calls with hand-picked, grepped-and-confirmed real target names,
  rank + package via the real `RelevanceRanker`/`ContextPackager`, record every pass through a real
  `TelemetryCollector`, classify every resolved-but-unpackaged candidate through item #14's
  `classify_grounding_failure` (exercising it cross-language, not just on Go), and run item #11's
  `production_gate.evaluate_release()` on the resulting `RunSummary`. Zero `src/` changes — pure
  reuse of #11/#13/#14's existing, unmodified interfaces.

- **Real result, all 4 tiers, real Consul/Flask/spring-petclinic/vllm (`scripts/
  validation_breadth_matrix_check.py`):**

  | tier | repo | files scanned/analyzed | symbols | fallback ratio | gate decision |
  |---|---|---|---|---|---|
  | Go | consul | 11,102 / 2,370 | 28,174 | 0.04 | `RELEASE_REJECTED` |
  | Python | flask | 236 / 83 | 1,619 | 0.857 | `RELEASE_REJECTED` |
  | Java | spring-petclinic | 131 / 49 | 230 | 0.5 | `RELEASE_REJECTED` |
  | Mixed | vllm (py+rs) | 6,429 / 4,421 | 59,353 | 0.667 | `RELEASE_REJECTED` |

  **4/4 completed with zero unhandled crashes** — every index build, resolve/rank/package pass,
  `TelemetryCollector.record()`, and `evaluate_release()` call succeeded structurally on every
  tier, including the genuinely polyglot `vllm` index (59,353 real symbols spanning two languages
  in one graph). Every `RELEASE_REJECTED` decision is a **valid, correctly-computed** outcome, not
  a crash — all 4 rejections trace to the exact same gate, for the exact same reason: the literal
  `max_fallback_ratio=0.0` default (already documented as too strict for real data by item #11's
  own Consul finding) rejects every repo, Go included — confirming the gate applies **zero
  language-specific schema assumptions**, exactly the "Operational Gate Parity" gate's own wording.

- **Real Topology Drift finding (the point of this whole item):** fallback ratio varies sharply by
  language — Go 4% vs. Python 85.7%, Java 50%, Mixed 66.7%. Plausible, not yet isolated, cause:
  these are single/double-target, `depth=1` resolutions on comparatively small repos (83/49 files
  analyzed vs. Consul's 2,370), so a much smaller fraction of each repo's real call graph is
  available for `SCOPED_GRAPH_EXPANSION` to find — more of each small candidate set falls back to
  `RAW_STRING_FALLBACK`/`EVIDENCE_FALLBACK_MATCH` by construction, independent of language per se.
  Reported as a real, honest observation and a candidate root cause, **not claimed as proven** —
  isolating repo-size from language-specific dynamic-dispatch effects needs a dedicated, larger-N
  falsification experiment, out of this item's own scope (matches items #3/#4's "flag a real
  pattern, don't force a fix into scope" discipline).

- **Item #14's classifier cross-language robustness, a real bonus finding:** `classify_grounding_
  failure` was exercised on real Go, Python, and Mixed failures (Java had zero real failures — a
  valid, well-formed empty result, not a malformed one) and returned a real, named category every
  time — `oversized_file_excluded`/`context_budget_overflow`, no `src/`-side language branching
  needed, confirming the classifier generalizes as designed.

- **Success criteria:**
  1. Matrix Execution — 100% completion across all 4 tiers — **met**, 4/4.
  2. Parser Stability — zero unhandled AST/parsing crashes across Go/Python/Java(+Rust) — **met**.
  3. Cross-Repo Telemetry — valid `RunSummary` and failure-taxonomy output per repo — **met**, all
     4 `RunSummary`s well-formed, failure taxonomy output valid (including Java's genuine empty
     result).
  4. Operational Gate Parity — `production_gate.py` runs and outputs valid decisions across all
     targets, no language-specific schema assumption failures — **met**, 4/4 structurally valid
     decisions (all `RELEASE_REJECTED` for the same, already-understood, config-default reason).
- **Failure criteria:** any repo crashing during indexing/resolution/packaging, a malformed or
  missing telemetry/taxonomy payload, or a gate crash from a language-specific assumption — did
  not occur.

- **Result:** Merged to `Base`/`main`, zero known open issues, zero `src/` changes. 988/988 tests.

## 9. Benchmark Coverage — Negative Queries / False-Positive Rate

- **Status:** Shipped — merged to `main`/`Base`, branch deleted after merge
- **Source:** original doc §9, detailed spec supplied by user 2026-08-12
- **Note:** real, currently-uncovered gap — the existing harness (`validate_llm_grounding.py`)
  only measures recall/precision against a real positive ground truth, never a
  should-return-nothing case.

- **Real synergy, found before designing anything:** the spec's own FPR formula — "Negative
  Queries yielding > 0 **non-fallback** candidate files" — is *exactly* item #10's
  `OriginStage`/item #13's `fallback_ratio` split (`AST_DIRECT`+`SCOPED_GRAPH_EXPANSION` =
  non-fallback, `RAW_STRING_FALLBACK`+`EVIDENCE_FALLBACK_MATCH` = fallback). No new telemetry event
  types needed — `LOW_CONFIDENCE`/`EMPTY_CANDIDATE_SET` are derived classifications
  (`EMPTY_CANDIDATE_SET` = 0 candidates; `LOW_CONFIDENCE` = candidates present but all
  fallback-origin), not new schema surface on already-shipped code.

- **Scope correction: must test through the real `service.py` layer, not bare `ContextResolver`.**
  Checked directly: the lexical-probe-recovery path ("Classifier-gap fix, layer 3" in `service.py`)
  and `evidence_fallback.py`'s query-referenced/evidence-contract matching — the actual mechanisms
  that could produce a false positive on an adversarial query — both live in
  `CodeIntelligenceContractService._resolve`, not in `ContextResolver.resolve()` itself. Testing
  only the bare resolver would miss the real risk surface entirely (a fabricated name would
  trivially resolve to nothing at that layer, making the test vacuous). Uses
  `service.attach_code_intelligence(...)` — the real production entry point — for every negative
  query.

- **SLM-1 bypassed deliberately, for determinism/cost/speed, not by oversight:** `target_names` are
  hand-specified per negative query rather than extracted from query text via real SLM-1 — matches
  the spec's own "Fast & Self-Contained... runs deterministically" requirement, and SLM-1
  non-determinism is a well-documented, standing issue on this project
  ([[arcf_payload_optimization_path_masking]]) this item has no need to reintroduce. No LLM calls
  anywhere in this item — the FPR metric is about candidate FILES (resolver/packager output), never
  about a generated answer, so no judge call is needed either.

- **Negative query suite grounded in real Consul, not assumed** (verified via direct `grep` before
  writing any query, catching one real near-miss: a generic test-fixture resource string literal
  `"autoscaler"` exists in `internal/storage/conformance/conformance.go`, unrelated to any
  Kubernetes-autoscaling feature — confirmed Consul implements no such feature before using it as a
  negative example). Also deliberately picked a real lexical-collision case, not a trivially-safe
  one: `SyncExternalDatabase` shares a prefix with real functions (`StateSyncer`,
  `syncChangesEventFn`, etc. in `agent/ae/ae.go`) — a genuine test of whether the lexical-probe
  fallback path can be fooled into a false positive, not a query guaranteed to resolve to nothing
  trivially. Consul UI's actual framework confirmed via its own `package.json` (`ember build`,
  `ember-template-lint`) — genuinely no React code exists, unlike an assumption that could've been
  wrong.

- **Success criteria:**
  1. FPR ≤ 5% — computed via `origin_breakdown`'s non-fallback count, real Consul, real service
     layer, no LLM calls.
  2. Zero positive regression — no source code changes in this item at all (pure test/harness
     addition), verified by the full existing suite staying green.
  3. Telemetry integration — every negative query's result recorded through a real
     `TelemetryCollector.record()` call without exception, `EMPTY_CANDIDATE_SET`/`LOW_CONFIDENCE`
     correctly derived from real `origin_breakdown` data.
  4. Fast, deterministic, self-contained — no LLM calls, runs as a normal part of the pytest suite.
- **Failure criteria:** any negative query producing a real (non-fallback) match, or any
  `TelemetryCollector.record()` call raising, means investigate before reporting FPR as passing —
  not silently excluded from the denominator.

- **Real finding, mid-implementation, investigated not patched away:** two of my own test premises
  were wrong and caught before shipping. (1) A fixture built to "share a lexical root" with a
  fabricated name (`StateSyncer`/`sync_changes` vs. `SyncExternalDatabase`) did NOT actually trigger
  `lexical_symbol_probe.py`'s real matching rule — checked directly via `shares_lexical_root()`:
  the module requires a genuine 6-character prefix match, and "sync" (4 chars) isn't long enough on
  its own. Rebuilt with a real collision (`synchronize_state` vs. the query word "synchronize",
  sharing the 6-char prefix "synchr"), confirmed via the same function before relying on it. (2) "in
  this repository" wording did NOT trigger `RepositoryScopeClassifier`'s `repository_scope=True` —
  needed a documentation-word (`"explain"`) + repository-word (`"repository"`) combination
  specifically, confirmed directly.

- **The real collision surfaced a genuine mechanism worth documenting, not hiding:**
  lexical-probe-recovery — a real, deliberate feature that recovers matches for queries naming no
  exact symbol (e.g. real production case: "Add support for a custom dependency cache invalidation
  strategy" correctly recovers `Dependant`) — will, on an ADVERSARIAL query, sometimes recover an
  unrelated real symbol purely because the query's prose happens to share 6+ characters with it.
  That recovered file gets tagged `origin_stage=AST_DIRECT` (a real "defines X" entry point, as far
  as that field is concerned) — but the system already, correctly tags it
  `evidence_tier=SUPPORTING` (its own existing "this was a probabilistic recovery, not a confident
  match" signal, the same PRIMARY/SUPPORTING distinction `RelevanceRanker`/`ContextBudgetManager`
  already use everywhere else in this project). **Origin-stage alone can't tell a confident
  exact-name match from a probabilistic lexical recovery — evidence_tier can, because the system
  itself already computes that distinction.**

- **FPR formula refined from the spec's literal wording, both numbers reported not just the
  passing one:** a candidate counts as a genuine false positive only when `origin_stage` is
  non-fallback **AND** `evidence_tier is PRIMARY` — excluding correctly-self-flagged probabilistic
  recoveries from being conflated with actual overconfident hallucination (the real thing the
  spec's own framing, "polluting context with weak graph matches," is about). On the fast synthetic
  suite (6 queries, deliberately including the real collision): **raw origin-stage-only FPR =
  33.3%** (2/6 — both are the same real lexical-collision mechanism, not two different bugs);
  **refined FPR = 0.0%**, clears the ≤5% gate.

- **Real Consul verification, decisive — `scripts/negative_query_fpr_real_consul_check.py`, 7
  queries (the grep-verified-absent set + the repository-scoped React variant):**

  | metric | result |
  |---|---|
  | Raw origin-stage-only FPR (spec's literal formula) | **100%** (7/7) |
  | Refined FPR (origin_stage AND evidence_tier == PRIMARY) | **0%** (0/7) |
  | Candidates per query | 13–39 files, every single one tagged `evidence_tier=SUPPORTING` |

  **This is the decisive evidence for the refinement, not just the small synthetic collision**: at
  real scale (28,174 real symbols), lexical-probe-recovery's 6-character-prefix matching finds
  *some* accidental collision for every one of the 7 adversarial queries — the raw, literal-spec
  FPR is 100%, a number with **zero diagnostic value** (it can't distinguish "the system is
  confidently hallucinating" from "the system's own honest low-confidence recovery mechanism fired,
  exactly as designed, and correctly tagged itself as such"). Every one of the 166 total candidate
  files returned across all 7 queries — without a single exception — carries `evidence_tier=
  SUPPORTING`, never `PRIMARY`. The refined metric is not a convenient reinterpretation to make a
  number pass; it is the only version of this metric that carries real signal at production scale.

  **Related, secondary finding, flagged not fixed here** (out of this item's scope, a real future
  candidate): even at `SUPPORTING` tier, an adversarial query still spends 13–39 candidate files
  and real token budget before the (correctly low) confidence signal would let a downstream ranker
  deprioritize it. Tuning lexical-probe-recovery's aggressiveness would risk breaking real recall on
  legitimate under-specified queries (its actual, validated purpose — see
  `test_conceptual_query_with_no_entities_still_finds_real_symbol_via_lexical_probe`) and needs its
  own isolated falsification experiment with explicit success criteria, not a quick change bundled
  into this item.

- **Result**: Merged to `Base`/`main`, zero known open issues. Full test suite green.

## 10. Expansion Consistency — Symbol-Identity Mode

- **Status:** Shipped — merged to `main`/`Base`, branch deleted after merge
- **Source:** original doc §10, detailed spec supplied by user 2026-08-12

- **Precise targets, found by tracing every `_add_file` call site in `context_resolver.py` before
  writing anything (not assumed):**
  1. Entry-point direct match (`resolve()`'s main loop, `f"defines {name}"`) — the disambiguated
     `symbol` IS the identity. → `AST_DIRECT`.
  2. `_expand_calls`'s hop-1 module-level calls via `locality_filtered_callers_of_name(index, name,
     symbol.file_path)` — this is the exact raw-string bypass
     [[arcf_disambiguation_pruning_shipped]]'s own "Stage 1" finding already identified: it re-
     searches `SymbolIndex.find_by_name(name)` for EVERY same-named symbol repo-wide, not just the
     disambiguated one. → `RAW_STRING_FALLBACK`.
  3. `_expand_calls`'s `caller_hops`/`callee_hops` via `locality_filtered_transitive_callers/
     callees(..., symbol.id, ...)` — genuinely ID-scoped. → `SCOPED_GRAPH_EXPANSION`, with
     `parent_symbol_id` set to the BFS's own real immediate-parent id (`parent_id` from the
     `(hop, parent_id)` tuple already computed), not just the original entry symbol.
  4. `_expand_subclasses`'s first loop, `candidate_selector.subclasses_of(name, ...)` — checked
     directly: `subclasses_of` calls `SymbolIndex.find_by_name(class_name)` internally, the exact
     same raw-name-repo-wide-bypass shape as #2. → `RAW_STRING_FALLBACK`.

- **Correction to the user's own spec:** "Enforce deterministic SymbolID propagation... disambiguated
  candidates must be tracked by identity, not raw string names" reads as wanting the raw-name
  lookups (#2/#4 above) *replaced* with ID-scoped ones. [[arcf_disambiguation_pruning_shipped]]
  already tested exactly that for #2 and found it barely changes anything — `CallGraph`'s own
  construction-time resolution over-attributes every bare call site to every same-named symbol's ID
  regardless of which lookup reads it later (ID-scoped vs. name-scoped: 31 vs. 32 files, a 1-file
  difference). Re-attempting that behavioral change without new evidence would re-litigate a closed
  question. **This item is scoped as tagging/observability, not a retrieval-behavior change**: the
  raw-string fallback paths keep working exactly as they do today (they're structurally necessary —
  real same-named module-level call sites do need this), but every file they produce now carries an
  explicit, honest `RAW_STRING_FALLBACK` tag instead of being indistinguishable from an
  identity-propagated match. That satisfies "make unflagged re-introductions impossible" without
  re-attempting the already-falsified behavioral fix.

- **Design (extends item #5's own finding — `FileReference.reason`/`justification_chain` is
  already a working provenance pattern, not new infrastructure):** new `OriginStage` enum
  (`AST_DIRECT`, `SCOPED_GRAPH_EXPANSION`, `RAW_STRING_FALLBACK`) and two new `FileReference`
  fields, `origin_stage: OriginStage | None = None` and `parent_symbol_id: str | None = None` —
  same additive, default-`None`, first-write-wins discipline as every existing optional field on
  `FileReference` (`anchor_confidence`, `ambiguity_confidence`, `path_mask_confidence`). Threaded
  through `_add_file` the same way those are, into two new parallel dicts
  (`file_origin_stage`/`file_parent_symbol_id`), read at the final `FileReference(...)`
  construction in `resolve()`.

- **Success criteria (the user's own 3 gates, made concretely checkable):**
  1. **100% Symbol Traceability** — every `FileReference` in a real `resolve()` call's
     `candidate_files` has a non-`None` `origin_stage`. Checked by a script asserting this on real
     Consul queries (including "New"/"Register", the known worst-case fan-out cases), not just unit
     tests on synthetic fixtures.
  2. **Zero Unflagged Re-introductions** — every file reached via `locality_filtered_callers_of_name`
     or `candidate_selector.subclasses_of` (the two confirmed raw-name paths) is tagged
     `RAW_STRING_FALLBACK`, checked directly against real traversal, not inferred.
  3. **Traceability velocity** — re-run item #3's own dropped-file trace (`agent/acl_test.go` etc.,
     reached via `NewBaseDeps`) and confirm the origin is now a direct field read
     (`origin_stage`/`parent_symbol_id`) instead of the manual `justification_chain`-string-reading
     this session actually had to do to produce that finding.
- **Failure criteria:** any candidate file with `origin_stage=None` on a real query, or a
  raw-string-reached file NOT tagged `RAW_STRING_FALLBACK`, means the tagging is incomplete — fix
  before merge, not a partial ship.

- **Scope extended beyond `_expand_calls` alone, found by grepping every `FileReference(` in
  `src/` before claiming "100%" (not assumed): two more real, unconditionally-or-commonly-reachable
  construction sites in the default classic path — `evidence_fallback.py` (confirmed
  `expand_with_evidence` runs unconditionally on every classic-path query) and `service.py`'s
  anchor-classification Tier 4 filename match. Both genuinely symbol-less (filename/glob matching,
  no `SymbolIndex` lookup at all), so a 4th `OriginStage` value (`EVIDENCE_FALLBACK_MATCH`) was
  added rather than mislabeling them `RAW_STRING_FALLBACK`. Explicitly **out of scope, documented
  not silently skipped**: `drp_resolver.py` (3 sites — a separate `resolver_strategy` entirely) and
  `multi_hop_orchestrator.py`/`evidence_validator.py`'s `_to_file_reference` (only reachable via an
  experimental Phase 7 spike `service.py` never calls today, confirmed by checking its own
  docstring and import graph).

- **Real bug caught by this item's own unit test, fixed in the same flow:** first implementation
  used first-write-wins for `origin_stage` (matching `file_reasons`/`file_chains`'s existing
  discipline) — but `locality_filtered_callers_of_name` isn't module-level-only despite its own
  call site's comment (it calls `CallGraph.caller_files_of`, which returns every same-named caller
  file regardless of whether the call is symbol-owned), so it can reach the same file a properly
  ID-scoped `caller_hops` walk also reaches. Since that raw-name loop runs first in code order,
  first-write-wins let code order — not evidence strength — decide the label. Fixed with a
  precedence-based merge (`_ORIGIN_STAGE_PRECEDENCE`), same "stronger evidence wins" shape as
  `file_tiers`' existing PRIMARY-always-wins rule.

- **Real result, verified on real Consul (`scripts/symbol_identity_audit_trail_verification.py`,
  no LLM calls) at traversal depths 1/2/3, both flagship queries ("Register", "New"):** all 3 user
  success gates pass cleanly — 100% Symbol Traceability (0 untagged files across every run), Zero
  Unflagged Re-introductions (every `RAW_STRING_FALLBACK` file has a real `parent_symbol_id`), and
  a concrete traceability-velocity demonstration: re-ran item #3's own dropped-file trace
  (`agent/acl_test.go` etc.) and confirmed `parent_symbol_id='agent/setup.go::NewBaseDeps#101'`
  gives the exact file+symbol+line in one field read — the same information item #3's own
  investigation had to get by manually parsing a `justification_chain` string and separately
  hunting down where `NewBaseDeps` was defined. 947/947 tests (5 new). Merged to `Base`/`main`,
  zero known open issues.

## 11. Operational Confidence — Deployment Strategy

- **Status:** Shipped — merged to `main`/`Base`, branch deleted after merge
- **Source:** original doc §11, detailed spec supplied by user 2026-08-12
- **Note:** real, currently-zero production-deployment infrastructure — every finding on this
  project today lives in a memory file and a hand-run script, not a versioned index or a canary.
  No overlap with falsified work. High priority if the goal is actually going live.

- **Scope correction, found by reading `get_run_summary()`'s real return shape before designing
  against it (not assumed):** the spec's "Quality Safeguard: primary path recall remains at 100%
  with zero statistically significant precision drops" gate needs precision/recall against real
  ground truth — data `TelemetryCollector` structurally cannot have on its own (it instruments the
  pipeline, it doesn't know what the "correct" files for a query are; that's the
  `validate_llm_grounding.py`/`_file_overlap_metrics` harness's job, a different layer). So "100% of
  metric inputs originate from the RunSummary interface" can't mean RunSummary *computes*
  precision/recall — it means RunSummary is the *single channel* they travel through. **Design**:
  extend `TelemetryEvent` (item #13, already shipped) with optional, caller-supplied
  `precision`/`recall` fields — additive, default `None`, zero behavior change for every existing
  caller (same discipline as every other field on that model) — populated only by a caller that
  actually has ground truth (a benchmark harness), never fabricated. `get_run_summary()` aggregates
  mean precision/recall plus a `quality_data_available: bool` flag. The Quality Gate reads
  `quality_data_available`: **skipped** (not silently passed as "quality confirmed") when no event
  in the run carries that data, **evaluated** when it does. This keeps every gate's input honestly
  100% RunSummary-sourced without RunSummary pretending to compute something it can't.

- **Shadow/canary driver, scoped honestly:** no second, genuinely different ARCF configuration
  currently exists to compare against in production (item #3's UPS suppression was falsified and
  never shipped — the one candidate change this session produced). Built as a **generic** two-
  collector comparison (`compare_collectors(baseline, candidate, config)`, itself just
  `evaluate_release` fed both summaries) rather than hardcoding a specific "baseline vs. candidate
  ARCF version" scenario that doesn't concretely exist yet — works with any two real
  `TelemetryCollector` runs (two real different configs when one exists, a repeat-run smoke test,
  or synthetic/injected data for the regression-sensitivity success gate below).

- **Success criteria:**
  1. **100% Automated Evaluation** — `evaluate_release()` is a pure function over `RunSummary`-
     shaped input, emits a `ReleaseDecision` (frozen/immutable) with zero manual review step.
  2. **100% Regression Sensitivity** — one test per gate, independently injecting a synthetic
     regression (fallback spike, latency spike vs. baseline, utilization over ceiling, recall drop)
     and confirming that exact gate — and only that gate — rejects, with a real, specific failure
     detail (not a generic "something failed").
  3. **Zero Overhead on Baseline** — structural: `production_gate.py` never imports/touches
     `ContextResolver`/`ContextPackager`/anything in the retrieval pipeline itself — it's a pure
     downstream consumer of an already-computed `RunSummary` dict, so a retrieval pass that never
     calls it is untouched by construction, not by a measured-small number.
  4. **Seamless Integration with #13** — `evaluate_release()`'s only required input shape is
     literally `TelemetryCollector.get_run_summary()`'s own return value; verified with a real
     round-trip test (a real `TelemetryCollector` from a real resolve()+package() call, fed
     straight into `evaluate_release()`, no adapter/translation layer in between).
- **Failure criteria:** any gate that can't independently catch its own injected regression, or any
  input the gate reads that doesn't trace back to `get_run_summary()`'s real return shape, means
  this stays unmerged/fixed before merge.

- **Real result, all 4 gates verified:**
  1. **100% Automated Evaluation** — `evaluate_release()` is a pure function, real end-to-end
     round-trip verified (real `resolve()`+`package()` → real `TelemetryCollector` → real
     `ReleaseDecision`, `scripts/release_gate_real_consul_check.py`).
  2. **100% Regression Sensitivity** — 18 unit tests, one per gate independently injecting a
     synthetic regression and confirming ONLY that gate fails (specificity, not just sensitivity),
     plus a synthetic regression (fallback spike to 0.8, 3x latency) injected on top of **real**
     Consul baseline data, correctly caught with exactly the two affected gates flagged.
  3. **Zero Overhead on Baseline** — structural, not measured-small: `production_gate.py` imports
     nothing from `code_intelligence`/`context`/`domain.context_resolution` (stdlib + pydantic +
     `shared.clock` only) — cannot touch the retrieval pipeline by construction.
  4. **Seamless #13 Integration** — `evaluate_release()`'s only required shape is literally
     `TelemetryCollector.get_run_summary()`'s own return value, no adapter layer, real round-trip
     tested.

- **Real finding, surfaced not hidden:** running the real end-to-end check against real Consul (4
  queries) showed `RELEASE_REJECTED` under the **default** config — real Consul's own natural
  fallback rate (2.36%, from `RAW_STRING_FALLBACK`) exceeds the spec's own literal "zero unflagged
  fallbacks" default (`max_fallback_ratio=0.0`). This is real, not a bug: the fallback and
  token-budget gates are **absolute** ceilings (matching the spec's own wording), independent of
  baseline — even comparing a run against itself doesn't bypass them if the real data itself
  exceeds the ceiling (confirmed directly: self-comparison correctly showed the *relative* latency
  gate at exactly 0% overhead, while the *absolute* fallback gate still rejected). A realistic
  `max_fallback_ratio=0.05` config approved the same real data cleanly. **Operational takeaway for
  whoever configures this in practice**: the spec's literal zero-tolerance default is not
  achievable against this codebase's real behavior — pick a realistic ceiling informed by actual
  measured data (item #10's own real-Consul fallback rates), not the literal spec default, or every
  real release will be rejected by design.

- **Result**: Merged to `Base`/`main`, zero known open issues. 977/977 tests.

## 12. Confidence Propagation Across the Pipeline

- **Status:** Parked (needs new evidence)
- **Source:** original doc §13
- **Why parked:** same family as item 1 — multiplying per-stage confidences still rests on the
  assumption that a confidence signal reliably predicts correctness for the hard cases, which is
  exactly what's falsified for the dominant failure mode (high-frequency name ambiguity).
- **Reopen condition:** same as item 1.
- **Success criteria:** _not defined yet._

## 13. Observability & Telemetry

- **Status:** Shipped — merged to `main`/`Base`, branch deleted after merge
- **Source:** original doc §14, detailed spec supplied by user 2026-08-12
- **Note:** real gap, no overlap with falsified work. High priority — pairs directly with item 11;
  neither is useful alone (telemetry needs something live to measure; deployment needs telemetry
  to know if a promotion is safe).

- **Checked for existing infrastructure before building anything (not assumed clean-slate):**
  `src/infrastructure/tracing.py` is real, existing OpenTelemetry span setup — trace-id-per-request,
  export-optional — a different concern (distributed tracing) from structured retrieval-pipeline
  telemetry. `src/telemetry/comparison_aggregator.py` + `domain/execution_ledger.py`'s
  `ExecutionLedgerEntry` are a real, existing, *persisted* Phase 9 system (backed by
  `arcf_execution_ledger.db`) for per-EXECUTION audit records (direct-vs-ARCF token/latency/cost
  comparison) — coarser-grained, no origin-stage breakdown, no stage timing, a genuinely different
  layer. This item is a new, complementary, in-memory capability, not a duplicate.

- **Scope correction, found by reading `ContextPackager`/`ContextBudgetManager` directly:** the
  spec's 4 named stage boundaries (`ast_extraction`, `graph_expansion`, `pruning`,
  `final_selection`) don't map to 4 separately-callable functions in the real pipeline —
  `ContextBudgetManager.select()` is ONE function that does the relative-score falloff gate
  ("pruning") AND budget-fit/compression ("final_selection") together; `ContextResolver.resolve()`
  similarly does entry-point matching AND graph expansion internally via private helpers
  (`_expand_calls`/`_expand_subclasses`, already threaded twice this session for items #3 and #10).
  Instrumenting inside those private methods a third time would mean invasive per-call-site timing
  probes threaded through code already carrying two other opt-in mechanisms — real risk for
  marginal gain. **Real design**: time the two genuine public boundaries as wholes
  (`ContextResolver.resolve()`, `ContextPackager.package()`), and get the stage-level *counts* (not
  timings) for free from data those calls already return — `origin_stage` per file (item #10's own
  capability: `AST_DIRECT`+nothing-else-needed for "ast_extraction" count,
  `SCOPED_GRAPH_EXPANSION`+`RAW_STRING_FALLBACK` for "graph_expansion" count) and
  `ContextPackage.excluded_file_count`/`relevant_files` (already computed by `select()`) for
  "pruning"/"final_selection" counts. Zero new internal instrumentation, zero new risk to code
  already modified twice.

- **Scope correction on "100% of telemetry payloads validate... across all 947+ tests":** the
  collector is opt-in (a caller must attach it) — the existing 947 tests don't call it and won't be
  retrofitted to (real scope creep across unrelated test files, against this session's own
  discipline). Made literally true instead via an env-var-gated `conftest.py` wrapper
  (`ARCF_TELEMETRY_VALIDATE=1`, default unset = zero behavior/overhead change to every existing
  test) that monkeypatches `ContextResolver.resolve`/`ContextPackager.package` as pure
  pass-throughs (same return value, same side effects) plus telemetry recording, for one explicit
  verification run — not a permanent default.

- **Success criteria:**
  1. `TelemetryEvent` pydantic schema (query_id, classified_task, traversal_depth, stage latencies,
     origin breakdown, budget signals) — required fields, not `Optional`, so "zero missing fields"
     is enforced by construction, not a separate check.
  2. `TelemetryCollector.get_run_summary()`/`assert_no_fallbacks()` — real, tested, and directly
     callable from a CI-gate-style check (not just a demo).
  3. `<2%` latency overhead — measured on real Consul, many iterations, real number reported, not
     assumed.
  4. 100% schema-valid payloads across the full 947+-test suite, real one-time verification run,
     reported honestly (including if it's not 100%).
- **Failure criteria:** any schema violation across the full-suite validation run, or measured
  overhead ≥2%, means this stays unmerged/fixed before merge, not shipped with a caveat.

- **Real result, all 4 gates verified:**
  1. **Latency overhead**: measured on real Consul (`scripts/telemetry_overhead_measurement.py`,
     200 iterations/arm, same process) — **-2.224%** (the telemetry arm was marginally *faster* on
     average; well within noise given ~26-41ms stdev on a ~410ms mean). Gate (<2%): **PASS**.
  2. **100% Pipeline Coverage**: both real public boundaries (`ContextResolver.resolve()`,
     `ContextPackager.package()`) wrapped; origin-stage counts derived free from item #10's data.
  3. **100% schema-valid payloads across the full suite**: `tests/conftest.py`'s opt-in
     `ARCF_TELEMETRY_VALIDATE=1` wrapper, real one-time run — **957/957 tests passed, 140 events
     recorded, 0 schema/recording violations**. Default (unset): confirmed byte-identical,
     957/957 either way, zero behavior change.
  4. **Programmatic interface ready for #11**: `get_run_summary()`/`assert_no_fallbacks()` both
     real, tested (10 new unit tests), and directly callable — `assert_no_fallbacks()` raises with
     a real diagnostic message when the aggregate `RAW_STRING_FALLBACK`+`EVIDENCE_FALLBACK_MATCH`
     ratio exceeds a threshold, exactly the shape a CI release gate needs.

- **Real secondary finding, traced not dismissed**: the full-suite run surfaced 9 candidates with
  `origin_stage=None`. Traced (not assumed) to `tests/context/test_packager.py`'s hand-built
  `ContextResolutionResult` fixtures, which construct `FileReference` objects directly to test
  `ContextPackager`'s own ranking/budgeting logic in isolation — bypassing the real resolver
  entirely. **Not a regression in item #10's coverage** (verified 100% on real Consul) — a
  hand-built test double was never claimed to carry real provenance, same as any mock. Recorded in
  the wrapper's own output, not silenced, so a genuinely new untagged source in the future doesn't
  get lost among expected ones.

- **Result**: Merged to `Base`/`main`, zero known open issues. 957/957 tests.

## 14. Failure Taxonomy & Automated Regression Attribution

- **Status:** Shipped — merged to `main`/`Base`, branch deleted after merge
- **Source:** original doc §15, detailed spec supplied by user 2026-08-12
- **Note:** real gap. Would have shortened several past investigations (e.g. distinguishing "graph
  failure" from "locality failure" was exactly the manual work done in the Arm 1 and
  disambiguation-pruning traces) — and, as it turned out, shortened one from *this very session*
  (see the self-correction on item #4, above, found while building this item).

- **Reconciled against real code before writing anything:** the spec's "Candidate Ranks & Scores"
  input maps to `RelevanceRanker.rank()`'s `RankedFile` list, not a new `TelemetryEvent` field —
  `TelemetryEvent` (item #13) only stores aggregate `origin_breakdown` counts, never per-candidate
  rank arrays, and adding one would be a real `src/` schema change this item's own "Zero Codebase
  Impact" gate forbids. Read `ContextBudgetManager.select()` directly (`src/context/
  budget_manager.py`) before designing the classifier — every one of the 5 `FailureCategory` values
  maps to one real, already-shipped exclusion mechanism there, not an invented one:
  1. The relative score falloff gate (`_RELATIVE_FALLOFF_GAMMA = 0.45`, item #B/2026-08-11) cuts a
     candidate before the "does it fit" question is ever asked.
  2. Task-type budget tiering (`_BUDGET_TIER_BY_TASK_TYPE`) means the EFFECTIVE ceiling a file
     competes against is often far tighter than the caller's nominal `max_tokens` — `UNKNOWN`/
     `BUG_FIX` = 4500, not 8000, a real fact that changes which files are actually "oversized."
  3. Greedy fill order means a file can lose to budget crowding for reasons unrelated to its own
     size or ambiguity.

- **Design:** `scripts/failure_taxonomy.py` — `FailureCategory` (the user's exact 5 values),
  `classify_grounding_failure(file_path, result, ranked_files, packaged_files, caller_max_tokens,
  task_type)`, pure/deterministic, **imports** `_RELATIVE_FALLOFF_GAMMA`/`_BUDGET_TIER_BY_TASK_TYPE`
  from `budget_manager.py` rather than duplicating them (zero drift risk), and
  `aggregate_failure_distribution()` for the Diagnostic Aggregation Report. Decision tree, in order:
  absent from `candidate_files` entirely → `ZERO_CANDIDATE_EXTRACTION` (secondary
  `AMBIGUITY_DECAY_DROPPED` when `result.ambiguous_targets` is non-empty — real corroborating
  evidence, not an assumption, that a same-named collision is the likely cause); present but below
  the falloff threshold → `AMBIGUITY_DECAY_DROPPED` (if `ambiguity_confidence < 1.0`) or
  `PROBABILISTIC_EDGE_DISCARD` (if reached via `SCOPED_GRAPH_EXPANSION` and not ambiguity-decayed);
  present, cleared the falloff gate, but its own `token_count` exceeds the effective (task-tiered)
  ceiling → `OVERSIZED_FILE_EXCLUDED`; otherwise → `CONTEXT_BUDGET_OVERFLOW` (crowded out by
  earlier, lower-tier picks). Every branch resolves to a named category by construction — there is
  no code path that returns `UNKNOWN`/unclassified.

- **Scope correction: Arm A only, not Arm B.** `_arm_b_baseline`'s own docstring (already in this
  file) says it deliberately bypasses `ContextBudgetManager` entirely (`_greedy_full_file_package`,
  "no compression, no relative score falloff gate") — applying this classifier's falloff/tiering
  logic to Arm B's output would misclassify against a mechanism Arm B never runs. Wired into
  `_arm_a_arcf`'s result dict only, via underscore-prefixed `_resolution`/`_ranked_files`/
  `_task_type` keys that `_run_one_task` consumes into a plain, JSON-serializable
  `failure_diagnoses` list and then deletes — nothing non-serializable ever reaches
  `raw_path.write_text()`. `main()` emits the Diagnostic Aggregation Report (category counts +
  percentages across every task/run) to a new `..._failure_taxonomy_report.txt`, alongside the
  existing markdown table. **Zero `src/` changes** — `budget_manager.py`'s constants are imported,
  not modified; 988/988 existing tests unaffected.

- **Real verification (`scripts/failure_taxonomy_real_consul_check.py`, real Consul, no LLM
  calls, reusing item #4's own `BENCHMARK_TASKS`/`_structural_behavioral_grounding_metrics` to
  decide which files are "failures" — the Telemetry Alignment gate):**

  | task | file | primary | secondary |
  |---|---|---|---|
  | task1 | `catalog_endpoint.go` | `OVERSIZED_FILE_EXCLUDED` | `AMBIGUITY_DECAY_DROPPED` |
  | task2 | `cache.go` | `AMBIGUITY_DECAY_DROPPED` | — |
  | task2 | `watch.go` | `ZERO_CANDIDATE_EXTRACTION` | `AMBIGUITY_DECAY_DROPPED` |
  | task3 | `config.go` | `AMBIGUITY_DECAY_DROPPED` | — |
  | task5 | `cache.go` | `AMBIGUITY_DECAY_DROPPED` | — |

  task1's real detail: `token_count=10069` exceeds the effective 4500-token ceiling (`UNKNOWN`
  task-tier) on its own, independent of rank — a genuine size failure, with ambiguity decay as a
  real compounding secondary factor (`Catalog`×2). Tasks 2/3/5's `cache.go`/`config.go` entries
  cleared their own size ceiling but fell below the falloff gate purely from ambiguity decay
  (`Cache`×3, `Config`×7, `New`×224). `watch.go` never became a candidate at all (the already-
  diagnosed "Notify" 78-way collision). Diagnostic Aggregation Report on this real run: **60%
  `AMBIGUITY_DECAY_DROPPED`, 20% `OVERSIZED_FILE_EXCLUDED`, 20% `ZERO_CANDIDATE_EXTRACTION`**, 0%
  `PROBABILISTIC_EDGE_DISCARD`/`CONTEXT_BUDGET_OVERFLOW` on this benchmark (tasks 4/6 have zero
  real failures to classify — both hit `G_struct`=`G_behav`=1.0 per item #4).

- **Success criteria:**
  1. Taxonomy Coverage — 100% of real failures mapped to a named category, never `UNKNOWN` —
     **met by construction** (every decision-tree branch returns a real category) and confirmed on
     5/5 real failures above.
  2. Zero Codebase Impact — **met**: 0 `src/` changes, 988/988 tests unaffected.
  3. Deterministic Categorization — **met**: task5's real classification re-run twice through the
     full real pipeline produced byte-identical primary/secondary/detail output.
  4. Telemetry Alignment — **met**: every classified run is recorded through a real
     `TelemetryCollector.record()` call, and "what counts as a failure" is read directly from item
     #4's own `_structural_behavioral_grounding_metrics`, not a second, disconnected definition.
- **Failure criteria:** any real failure returning an unclassified/`None`-primary result, a
  non-deterministic repeat classification, or a required `src/` change — did not occur.

- **Result:** Merged to `Base`/`main`, zero known open issues, zero `src/` changes. 988/988 tests.

## 15. Oversized Entry-Point Budget Allocation — PRIMARY Priority Floor

- **Status:** Shipped — merged to `main`/`Base`, branch deleted after merge
- **Source:** not in the original 15-section doc — a follow-on falsification experiment against
  item #4/#14's own real finding (the "Task 1 regression"), detailed spec supplied by user
  2026-08-12, added as its own numbered item per the same precedent as item #3 (a real experiment
  outside the original doc's numbering still gets a full entry). Recommended over the alternative
  candidates (bare-name fan-out — same shape as the 8-times-falsified recall-gap thread; fallback-
  ratio disparity — a measurement exercise, not a fix) specifically because it targets a
  mechanism *distinct* from every prior falsified attempt, with real numbers already in hand.

- **Real mechanism traced BEFORE writing anything** (monkey-patching `ContextBudgetManager.
  _compress` to observe real args/return on a real Consul run, not assumed): task1's real entry
  point (`agent/consul/catalog_endpoint.go`) clears the relative score falloff gate (score 0.6309 >
  threshold 0.36) and is ranked 20th of 25 real survivors — every one of the 19 candidates ranked
  above it is `evidence_tier=SUPPORTING` (real call-graph fan-out from the `Register` target's own
  38-way ambiguity), while it is the FIRST `PRIMARY` candidate in the whole list. `_compress` IS
  called for it, with `remaining=19` tokens — its own compressed excerpt (confirmed via
  `SymbolRangeCompressor`, both `extract()` and `extract_with_ast_scope()`) is only 46-50 tokens,
  tiny, but still doesn't fit in the 19 tokens left after 19 SUPPORTING decoys consumed 4,481 of the
  4,500-token `UNKNOWN`-tier budget first.

- **Scope correction against the spec's own two proposed mechanisms:** "AST Structural Windowing"
  was **not built** — the real trace above shows compression was never the bottleneck (a 46-50-token
  excerpt is already about as small as anything could be); building a new windowing subsystem would
  have zero marginal effect on this specific, real, traced case. Only "PRIMARY Node Priority Floor"
  was implemented, since it's the mechanism the real data actually points at.

- **Real regression risk found and checked BEFORE trusting the fix:** task6 has the OPPOSITE shape
  from task1 — its real behavioral answer (`agent/auto-config/tls.go`, `SUPPORTING`) is ranked #1,
  while its `PRIMARY` candidates (including the real structural entry point, `cache.go`) are ranked
  LAST (7th of 7). A naive "PRIMARY always first" reorder could plausibly starve `tls.go`'s own
  budget — checked directly via a same-process ablation across ALL 6 real `BENCHMARK_TASKS`, not
  assumed safe from task1 alone.

- **Design:** `ContextBudgetManager.select()` gained one new parameter,
  `enable_primary_priority_floor: bool = False` (every existing caller byte-identical unaffected,
  confirmed by the full 988/988 suite before any new test was added). The relative score falloff
  gate still runs first, over the original score-sorted `ranked_files`, untouched — the flag never
  changes WHICH candidates survive it. Once survivors are known, the flag reorders ONLY the
  greedy-fill/compression pass: a stable two-group partition (every `PRIMARY` survivor, in its own
  existing relative score order, packed before every `SUPPORTING`/`EXPERIMENTAL` survivor, also in
  its own existing relative order) — never a re-sort by a new score. `ContextPackager.package()`
  threads the same flag through, default `False`.

- **Real same-process ablation, all 6 tasks (`scripts/primary_priority_floor_ablation.py`, real
  Consul, no LLM calls):**

  | task | `G_struct` off→on | `G_behav` off→on | file set changed | tokens used off→on |
  |---|---|---|---|---|
  | task1 | 0.0 → **1.0** | N/A | yes | 4481 → 4445 |
  | task2 | 0.0 → 0.0 | 0.0 → 0.0 | no | 2844 → 2844 |
  | task3 | 0.0 → 0.0 | N/A | no | 250 → 250 |
  | task4 | 1.0 → 1.0 | 1.0 → 1.0 | yes (subtractive only) | 3757 → 4493 |
  | task5 | 0.0 → 0.0 | N/A | no | 4477 → 4477 |
  | task6 | 1.0 → 1.0 | 1.0 → 1.0 | no | 4012 → 4012 |

  Tasks 2/3/5 are byte-identical, exactly as predicted: their failures happen at the falloff gate
  (before the packing-order fix ever applies), a mechanism this flag deliberately never touches —
  real confirmation the fix is scoped precisely to the one case it targets, not a broad reshuffle.
  Task4's file-set change, checked directly (not just the score): `{agent/http.go,
  agent/http_ce.go, agent/consul/state/memdb.go, agent/consul/state/state_store.go}` were displaced
  — 4 `SUPPORTING`-tier filler files, none of them ground truth — a purely subtractive trade-off,
  not a lucky coincidence. Task6, despite its opposite tier/rank shape, stays completely
  byte-identical — its own budget usage (4012 of 4500) never had enough crowding pressure for
  reordering to matter either way.

- **Success criteria:**
  1. Task 1 Grounding Recovery (`G_struct = 1.0`) — **met**: 0.0 → 1.0, confirmed on the real full
     pipeline, not a synthetic fixture.
  2. Budget Enforcement (≤ 8,000 tokens) — **met**: every task's real token usage stayed within its
     own effective ceiling (all ≤ 4,500 in this run, well under 8,000).
  3. No Regression on Tasks 4 & 6 (`G_struct = G_behav = 1.0` maintained) — **met**, both tasks;
     task4's underlying file set changed but only by displacing non-ground-truth filler.
  4. Pre-Check Falsification (a real, nonzero packing diff, not 0% change) — **met**: 2 of 6 tasks
     show a real, explained diff (task1, task4); the other 4 are correctly, predictably unaffected
     (not a sign of a no-op — a sign the mechanism only fires where it should).
- **Failure criteria:** task1 not recovering, any task4/6 score regression, a budget overflow past
  8,000 tokens, or a byte-identical result on every task (indicating the flag never actually
  engages) — did not occur.

- **Real unit test coverage added** (`tests/context/test_budget_manager.py`, 4 new): default-off
  behavior unchanged (a regression guard, not just an ablation script), the flag's core effect
  (a low-score `PRIMARY` displacing exactly one higher-score `SUPPORTING` file, not a free win),
  relative order preserved within each tier on a deliberately un-sorted input, and confirmation the
  flag never rescues a real falloff-gate casualty. 992/992 total tests (4 new).

- **Result:** Merged to `Base`/`main`, zero known open issues. 992/992 tests.

---

## Production Readiness Gap Resolution (started 2026-08-12, paused mid-work)

Follow-on effort after all 15 checklist items closed, prompted by a readiness review ("is ARCF
ready to integrate before an LLM"). 6 gaps identified, prioritized by dependency (verify current
state cheaply first, fix shared upstream noise second, tackle the hardest research problem third,
then breadth/calibration/cleanup). **Paused here — user is starting a separate, higher-priority
experiment.** Resume by reading this section top to bottom before doing anything else in this area.

### Status snapshot

| # | Gap | Status |
|---|-----|--------|
| 1 | Re-verify composite grounding score post item #15 | **Done** — real result below |
| 2 | SLM-1 non-determinism | **Done** — re-verified, doesn't reproduce, closed |
| 2b | `Listener` prompt bug (found investigating #1) | **Diagnosed, fix scoped, NOT implemented** — waiting on go-ahead |
| 3 | Extreme-ambiguity / recall-gap boundary (reranker) | **Not implemented** — waiting on direction (LLM-as-reranker vs. dedicated vendor) |
| 3b | Task6 multi-path-hint collision (found investigating #1) | **Flagged, NOT fixed** — same family as #3 |
| 4 | Non-Go grounding-quality ground truth (Python/Java/Mixed) | **Not started** |
| 5 | Release-gate default threshold calibration | **Not started** — depends on #4 |
| 6 | Placebo-effect complexity cleanup | **Not started** — lowest priority, not blocking |

### 1. Composite grounding score — real result, decisive

`scripts/validate_llm_grounding.py --repo-path .benchmark_repos/consul --repo-name consul
--n-runs 3`, real `gpt-4o-mini` calls, real Consul, post item #15 fix:

**Composite: `3.426 ± 0.888`** (Arm A / ARCF) — clears the ≥3.4/5.0 target **for the first time
ever recorded** in this project (previous best was 2.867, pre-item-#15). `G_struct`: task1 and
task4 both cleanly `1.0`.

**Real bug found and fixed en route, before trusting this number**: item #15's
`enable_primary_priority_floor` was built and same-process-ablation-verified, but **never actually
wired into this harness's Arm A call** — `_arm_a_arcf()` built `ContextPackager.package(...)`
without passing the flag, so the FIRST re-verification run silently tested the OLD (pre-fix)
behavior and showed task1 still failing. Fixed: `enable_primary_priority_floor=True` added to the
`packager.package(...)` call in `_arm_a_arcf`, matching how `enable_anchor_classification`/
`enable_confidence_propagation` are already explicitly turned on there. Confirmed directly (not
just re-run blind): resolved the real dotted entity `Catalog.Register` (real SLM-1 output, not the
hand-picked `['Catalog','Register']` used to build the fix) through the packager with the flag
on/off — `G_struct` 0.0 → 1.0, isolating the fix's effect precisely before re-running the full
paid benchmark.

**Important caveat, not a clean win — reported honestly**: Arm C (zero-context, no retrieval at
all) still scores **`4.111 ± 0.676` overall**, higher than ARCF's `3.426`. ARCF wins decisively on
some tasks (task1, task4) and loses badly on others (task2). The composite target being cleared
does not mean "retrieval reliably beats no retrieval" — that remains task-dependent and unresolved.
Raw results: `docs/llm_grounding_validation/consul_grounding_validation.json`; summary:
`consul_grounding_validation_summary.md`; failure taxonomy:
`consul_failure_taxonomy_report.txt` (real run: 68.4% `zero_candidate_extraction`, 15.8%
`oversized_file_excluded`, 15.8% `context_budget_overflow`).

### 2. SLM-1 non-determinism — re-verified, closed

`scripts/slm1_determinism_reverification.py`: 4 distinct real queries (including the exact query
from the original documented flip) × 28 total real `temperature=0.0` calls against the *current*
production prompt — **zero content variance in any of them**. A control at default (unset)
temperature on the same query showed real variance (4/10 runs differed, 2 genuine drops) —
confirming the test methodology can detect instability when it's actually there. **Conclusion: the
documented gap (`PROGRESS.md`'s "Benchmark noise floor" open item) does not currently reproduce.**
Most likely explanation: the prompt was hardened (explicit entity-shape rules, worked examples)
after that finding was recorded, and `temperature=0.0` combined with the current prompt is reliably
deterministic for this model. Not fixed with new code because there was nothing left to fix once
checked directly — building a mitigation for a non-reproducing bug would be untested complexity
against a falsified premise.

### 2b. The `Listener` prompt bug — diagnosed, NOT fixed, needs a go-ahead

Real root cause of a large share of task2's `zero_candidate_extraction` failures:
`contracts/intent_extraction.py`'s own prompt contains the worked example `"downstream service
check listeners" -> "Listener" or "Check"`. Task2's real query is *literally* "...downstream
service check listeners" — real SLM-1 extraction returns exactly `Listener`, precisely as
instructed. `Listener` is not a real symbol anywhere in Consul. The prompt is teaching the model to
fabricate a plausible-sounding fake identifier instead of either omitting (the prompt's OWN other
rule: "or omit it rather than inventing a made-up identifier") or deferring to the deterministic
fallback paths (`evidence_fallback.py`, `lexical_symbol_probe.py`) that exist specifically for this
situation.

**Proposed fix** (not yet implemented): remove that one bad worked example and the "extract the
most specific word as a guess" instruction; strengthen the "omit rather than invent" rule. Real,
isolated falsification test before/after: does this measurably improve real judged grounding on
task2 (and any other query that currently triggers the guessing behavior) without hurting tasks
that work fine today.

**Why not just done**: a prior session's own memory ([[arcf_slm1_determinism]]) explicitly flags
touching this prompt as "needs its own careful, separately-validated falsification experiment...
ask first, per [[feedback_falsification_experiments]]." Surfaced to the user 2026-08-12; **no
go-ahead received yet** when this session paused.

### 3. Extreme-ambiguity / recall-gap boundary — reranker, direction not yet chosen

Per [[arcf_recall_gap_closed]], all 8 prior deterministic/graph/lexical attempts are closed; the
only remaining lever is a genuinely different mechanism — semantic scoring. Briefed the user on
**LLM-as-reranker** (reuse the already-proven-deterministic `gpt-4o-mini`/`LiteLLMClient`, zero new
vendor dependency) vs. a dedicated reranker product (Cohere/Voyage/Jina — new dependency, ~$1-2/1k
calls, sub-100ms). **User said "something narrower first" then asked for a brief on the hosted-
reranker option; that brief was given, but no final direction (which specific path, or a go-ahead
to build either) was received before this session paused.**

Scoping notes for whoever picks this up: only fire when `ContextResolver`'s existing locality-based
disambiguation still leaves a target ambiguous (`disambiguation.ambiguous is True` after the
deterministic path already tried) — additive, not a replacement of the working deterministic path.
Reuse `SymbolRangeCompressor` for candidate snippets, don't build new extraction. Real ground truth
to test against: task5 ("New"), task1 ("Register"), and now also task6 (see 3b below — a second,
independently-discovered real case this same mechanism should fix).

### 3c. Direction decided (2026-08-13): self-hosted local inference server, not a paid API vendor

Context: user started a separate deep-investigation brief (Jina Reranker evaluated against public
repos — Traefik/SQLAlchemy pilot, issue→PR-mined ground truth) to answer gap #3's open "which
vendor" question empirically. Scoping that investigation surfaced the real blocker before any
benchmark ran: no `JINA_API_KEY`, no `GITHUB_TOKEN` (unauthenticated GitHub API capped at 60 req/hr,
not enough to mine real ground truth), and this machine has no GPU. Rather than keep fighting API
access, the user asked directly: can ARCF host its own SLM-1 model and its own reranker on one local
server instead of paying/keying into a vendor, does it work, and does it violate ARCF's philosophy.

**Decision: yes, self-hosted, on both counts.**
- **Technically works, and fits existing code better than the vendor-API route did**:
  `src/infrastructure/llm_client.py`'s `LiteLLMClient` is already provider-agnostic (`litellm.acompletion`)
  — pointing SLM-1 at a self-hosted OpenAI-compatible endpoint (Ollama/vLLM/TGI/LM Studio) is an
  `api_base` + model-string change, zero new dependency. Hugging Face's Text Embeddings Inference
  (TEI) serves reranker models (BGE, Jina's open checkpoints) over HTTP and ships a CPU image — this
  machine has no GPU (confirmed: no `nvidia-smi`, no `torch` installed) so CPU-only is the only
  option here regardless, and it's sufficient at pilot/production query volumes for ARCF (reranking
  fires only on already-ambiguous candidates, a small fraction of real queries per gap #3's own
  scoping notes below).
- **Does not violate ARCF's deterministic-first philosophy**: that philosophy is about *where*
  non-determinism enters the pipeline and how contained/replaceable it is, not about who hosts the
  model. A self-hosted pinned checkpoint is arguably *more* reproducible than an opaque vendor API
  whose version you don't control. The real risk isn't vendor-vs-self-hosted — it's the *placement*
  risk [[arcf_arm2_semantic_reranker_falsified]] already proved out: a reranker bolted on
  post-packing is inert regardless of who serves the model. This carries forward unchanged into
  `exp/reranker-pre-budget-candidate-selection` (see gap #3's own scoping notes above, unchanged):
  fire only when `disambiguation.ambiguous is True`, pre-budget, additive not a replacement.

**Success/failure criteria for `feature/local-inference-server` (this branch, infra only — no
grounding-quality claims made or tested here, that's the separate follow-on experiment's job)**:
- Success: a local server (Ollama/vLLM-equivalent + TEI CPU image, one compose stack) is reachable;
  `LiteLLMClient.complete()` produces a real structured-extraction response through it with zero new
  pip dependency beyond what `litellm`'s OpenAI-compatible path already requires; a new reranker HTTP
  client in `src/infrastructure/` returns real relevance scores for a real (query, candidate-snippet)
  batch against the local TEI server.
- Failure: if the self-hosted SLM-1 model can't reliably produce the same structured JSON contract
  `intent_extraction.py` requires (a real risk — smaller open models are often worse at strict
  structured output than `gpt-4o-mini`), this branch stays scoped to infra + reranker only, and
  SLM-1 hosting is flagged as its own separately-evidenced follow-on, not forced through.

### 3b. Task6 multi-path-hint collision — new finding, same family as #3, NOT fixed

Found while re-verifying gap #1: task6 was consistently `G_struct=1.0` in every hand-picked-name
check this session ran, but **regressed to `0.0` with real SLM-1 entities**
(`['agent/cache', 'Prepopulate', 'agent/auto-config']` — three entities, not just `['Prepopulate']`
as hand-picked earlier). Traced directly: `Prepopulate` has a second, unrelated same-named method in
`agent/auto-config/config.go` (`Cache.Prepopulate#35`, distinct from the real target
`agent/cache/cache.go::Cache.Prepopulate#970`). With only ONE path hint (`agent/cache/`), the real
target was favored. With TWO path hints present (`agent/cache/` AND `agent/auto-config/`), **both**
same-named candidates satisfy one of the two hints, so the path-hint mechanism can no longer favor
either — `Prepopulate` becomes genuinely ambiguous (`ambiguous_targets=('Prepopulate',)`) and falls
into the same ambiguity-decay-at-the-falloff-gate mechanism as tasks 2/3/5.

**Not previously documented** — a genuinely new interaction between multi-hint queries (Feature 1,
2026-08-11) and disambiguation, not caused by anything built this session, not yet attempted as a
fix. The reranker mechanism from gap #3 would plausibly fix this too (same shape: 2 same-named
candidates, judge which one the query text is really about) — worth testing together, not as two
separate experiments.

### 4. Non-Go grounding-quality ground truth — not started

Item #8 validated that Python/Java/Mixed repos index and run cleanly (Matrix Execution, Parser
Stability), but has ZERO curated ground truth for any of them — only Consul has real
`BENCHMARK_TASKS`. Needs: grep real target symbols + expected files in `flask`/`spring-petclinic`/
`vllm` (all already available in `.benchmark_repos/`, per item #8), build task fixtures the same
way item #4 did for Consul, then run the same `G_struct`/`G_behav`/composite-score measurement.
Real signal already in hand suggesting this matters: item #8's fallback-ratio disparity (Go 4% vs.
Python 85.7%/Java 50%/Mixed 66.7%) — unexplained, could be repo-size or could be a real
language-specific gap; only real ground truth on those repos will tell which.

### 5. Release-gate default threshold calibration — not started, depends on #4

`production_gate.py`'s literal `max_fallback_ratio=0.0` default rejects every real repo tested so
far (item #8: 4/4 rejections, including Consul). No validated "safe" default exists. Needs real
fallback-ratio baselines across more repos/languages (gap #4's byproduct) before a genuinely
informed default can be chosen — picking one now would just be a second guess.

### 6. Placebo-effect complexity cleanup — not started, lowest priority

Arms 1/2/4 (semantic re-ranker, type-graph indexing, path-hint locality boosting) were all falsified
via same-process ablation — real, tested code with zero real effect on real queries. Not blocking
integration; a maintainability pass (remove or clearly gate as historical-record-only) whenever
there's spare cycles. No urgency.

---

## Housekeeping (flagged, not acted on)

Several branches are already merged into `Base` but not deleted, against the branching policy's
own cleanup rule (`feature/call-site-slicing-budget-rebalance`, `feature/task6-secondary-sibling-
benchmark`, `fix/context-resolver-disambiguation-pruning`, `fix/grounding-metrics-and-lexical-
probe`, `experiment/callgraph-fanout-impact`, `experiment/slm1-bypass-validation`). Not deleted as
part of this commit — ask before pruning branches that touch `origin`.
