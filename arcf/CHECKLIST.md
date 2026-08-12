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
- **Active branch:** none — no item started yet
- **Active item:** none
- **In-flight state:** none
- **Next step:** start **item 3** (Locality UPS suppression) — first in the decided priority order
  below.

## Priority order (decided 2026-08-12)

Reasoning: aim first at the one item pointed at a real, already-diagnosed open lever; do the cheap
verification spikes early since other items depend on their answers; treat "make it live" as
requiring telemetry before a deployment/rollback flow means anything; leave same-shape-as-falsified
items parked until new evidence shows up.

**Tier 1 — next up**
1. **#3** Locality UPS suppression — aimed at the one concrete open lever (`has_locality`
   import-reachability permissiveness), direct continuation of the disambiguation-pruning thread.
2. **#5** Canonical IR gap check — cheap spike, scopes #2/#6/#10 correctly instead of guessing.
3. **#10** Symbol-Identity mode / audit trail — small, pays for itself immediately in the next
   falsification experiment's ablation trace (would have sped up Arm 1 / Arm 4's own tracing).

**Tier 2 — required before "live" means anything**
4. **#13** Observability & Telemetry — nothing to gate a promotion on without this first.
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

- **Status:** Not Started — highest-signal candidate
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
- **Success criteria:** _not defined yet — must include a same-process ablation (real resolution,
  UPS-adjusted vs. δ=0) per the standard established by [[arcf_arm2_semantic_reranker_falsified]]
  and [[arcf_arm4_path_locality_falsified]]: an aggregate score movement alone is not sufficient
  evidence._

## 4. Grounding Quality — Structural vs. Behavioral

- **Status:** Not Started
- **Source:** original doc §4
- **Note:** genuinely addresses an open item (`Grounding-score target ≥3.4/5.0 composite` never
  hit in three measured runs — `PROGRESS.md` Open/unresolved). Adding a new tunable `λ` weight
  should be treated with the same caution as item 1 — define the success criterion for what
  "behavioral grounding matters more for debugging queries" means on real data before tuning `λ`.
- **Success criteria:** _not defined yet._

## 5. Determinism — Canonical Intermediate Representation

- **Status:** Verify gap exists before building
- **Source:** original doc §5
- **Correction:** largely already built. `Symbol` already carries `param_types`/`return_type`,
  there's a `FieldReference` type, and symbol IDs are already the unit `CallGraph.
  caller_files_of()` operates on ([[arcf_arm1_type_graph_falsified]],
  [[arcf_disambiguation_pruning_shipped]]). Check current `code_intelligence/` types for what's
  actually missing (likely: `Language`, `Span` completeness, or a documented consumer contract)
  before treating this as greenfield work.
- **Success criteria:** _not defined yet._

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

- **Status:** Not Started
- **Source:** original doc §10
- **Note:** real gap, directly useful for debugging future falsification work — an explicit
  `ExpansionMode=FALLBACK` / `Reason=MissingGraphEdge` audit trail would have made several past
  ablation traces (Arm 1, Arm 4, the disambiguation-pruning `_expand_calls` trace) faster to
  attribute without manual code reading.
- **Success criteria:** _not defined yet._

## 11. Operational Confidence — Deployment Strategy

- **Status:** Not Started
- **Source:** original doc §11
- **Note:** real, currently-zero production-deployment infrastructure — every finding on this
  project today lives in a memory file and a hand-run script, not a versioned index or a canary.
  No overlap with falsified work. High priority if the goal is actually going live.
- **Success criteria:** _not defined yet._

## 12. Confidence Propagation Across the Pipeline

- **Status:** Parked (needs new evidence)
- **Source:** original doc §13
- **Why parked:** same family as item 1 — multiplying per-stage confidences still rests on the
  assumption that a confidence signal reliably predicts correctness for the hard cases, which is
  exactly what's falsified for the dominant failure mode (high-frequency name ambiguity).
- **Reopen condition:** same as item 1.
- **Success criteria:** _not defined yet._

## 13. Observability & Telemetry

- **Status:** Not Started
- **Source:** original doc §14
- **Note:** real gap, no overlap with falsified work. High priority — pairs directly with item 11;
  neither is useful alone (telemetry needs something live to measure; deployment needs telemetry
  to know if a promotion is safe).
- **Success criteria:** _not defined yet._

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
