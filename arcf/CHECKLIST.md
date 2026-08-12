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

- **Last updated:** 2026-08-12 (this session)
- **Active branch:** none. `experiment/locality-utility-suppression` left unmerged as a historical
  record (same treatment as `exp/enhanced-path-locality`, `exp/semantic-reranker`,
  `exp/type-graph-indexing`); `feature/symbol-identity-audit-trail` and
  `feature/observability-telemetry` both merged and deleted.
- **Active item:** none — **Tier 1 fully closed out** (#3 `Parked (falsified)`, #5 `Done`, #10
  `Shipped`), **Tier 2 item #13 (Observability & Telemetry) shipped** — `TelemetryCollector` +
  `TelemetryEvent`, all 4 user success gates verified with real measurements (-2.224% overhead,
  957/957 tests 0 schema violations, `get_run_summary()`/`assert_no_fallbacks()` ready for #11).
- **In-flight state:** none. `main`/`Base` clean and in sync, 957/957 tests green.
- **Next step:** Tier 2 continues — **#11 Operational Confidence** (deployment/versioning/canary/
  rollback), now directly actionable since it can gate on `TelemetryCollector.assert_no_fallbacks()`
  and `get_run_summary()`, then **#7 Incremental Indexing remaining gap**, per the decided priority
  order above.

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
6. **#7** Incremental Indexing remaining gap — verify the narrower partial-recompute gap, close it;
   production repos churn continuously, a benchmark-only pass doesn't prove this.

**Tier 3 — benchmark/coverage hardening**
7. **#9** Negative queries / false-positive rate — cheap, self-contained, no dependencies.
8. **#4** Grounding quality (structural/behavioral split) — real unmet target, but costs more than
   #9 (needs its own λ-tuning discipline).
9. **#14** Failure taxonomy — more valuable once #13 exists to feed it real data, not one-off traces.
10. **#8** Validation breadth (topology/scale) — biggest effort; couple with resuming the paused
    50-repo sweep rather than standing alone.

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

- **Status:** Not Started
- **Source:** original doc §4
- **Note:** genuinely addresses an open item (`Grounding-score target ≥3.4/5.0 composite` never
  hit in three measured runs — `PROGRESS.md` Open/unresolved). Adding a new tunable `λ` weight
  should be treated with the same caution as item 1 — define the success criterion for what
  "behavioral grounding matters more for debugging queries" means on real data before tuning `λ`.
- **Success criteria:** _not defined yet._

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

- **Status:** Partially shipped — verify remaining gap before building
- **Source:** original doc §7 and §12 (same underlying capability, tracked as one item)
- **Correction:** not missing. `CodeIntelligenceContractService` already does automatic,
  content-hash-keyed incremental reuse (`previous_index`) and caches both the base index and
  `DrpIndex` per workspace root — verified with a real test that an edited file is re-analyzed
  and an unchanged one reuses prior analysis ([[arcf_persistent_index_cache]]).
- **Real remaining gap:** dependency-aware *partial* recomputation of specific graph
  components/locality regions on a sub-file symbol change, not full-index rebuild avoidance
  (which is already solved). Scope to that narrower gap, not a rebuild from scratch.
- **Success criteria:** _not defined yet._

## 8. Validation Breadth — Repository Topology & Scale Diversity

- **Status:** Not Started
- **Source:** original doc §8
- **Note:** no overlap with falsified work — real, currently-single-repo-biased benchmark gap.
  Connects to the in-progress 50-repo sweep ([[arcf_repo_sweep_50]], 3/50 done, paused on token
  expiry) — could piggyback on that effort rather than building a separate matrix.
- **Success criteria:** _not defined yet._

## 9. Benchmark Coverage — Negative Queries / False-Positive Rate

- **Status:** Not Started
- **Source:** original doc §9
- **Note:** real, currently-uncovered gap — the existing harness (`validate_llm_grounding.py`)
  only measures recall/precision against a real positive ground truth, never a
  should-return-nothing case.
- **Success criteria:** _not defined yet._

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

- **Status:** In Progress
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

- **Status:** Not Started
- **Source:** original doc §15
- **Note:** real gap. Would have shortened several past investigations (e.g. distinguishing "graph
  failure" from "locality failure" was exactly the manual work done in the Arm 1 and
  disambiguation-pruning traces).
- **Success criteria:** _not defined yet._

---

## Housekeeping (flagged, not acted on)

Several branches are already merged into `Base` but not deleted, against the branching policy's
own cleanup rule (`feature/call-site-slicing-budget-rebalance`, `feature/task6-secondary-sibling-
benchmark`, `fix/context-resolver-disambiguation-pruning`, `fix/grounding-metrics-and-lexical-
probe`, `experiment/callgraph-fanout-impact`, `experiment/slm1-bypass-validation`). Not deleted as
part of this commit — ask before pruning branches that touch `origin`.
