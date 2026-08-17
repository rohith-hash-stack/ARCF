# ARCF v2.3 — Architecture Freeze

**Status:** RE-SCOPED — effective 2026-08-06 (see [Re-scope Addendum](#re-scope-addendum-2026-08-06) below); ACTIVE for everything not explicitly carved out
**Scope:** `arcf/` and `benchmark/` (this repository)
**Supersedes:** nothing — this is the first freeze declaration; it formalizes the state
reached at the end of [ARCF_v2.3_ARCHITECTURE_REVIEW.md](ARCF_v2.3_ARCHITECTURE_REVIEW.md)'s
Stage 6.

## Declaration

ARCF v2.3, as implemented through migration Stages 1–6 of the architecture review, is
**frozen as the benchmark baseline**. This is the version that will be compared against
direct LLM coding agents in the upcoming validation run.

No further architectural changes are authorized against this baseline except:

1. **Bug fixes** — corrections to existing behavior that do not change any module's
   contract or add new capability.
2. **Benchmark-related improvements** — changes strictly in service of running,
   measuring, or reporting the comparative evaluation (e.g. new suite tasks, additional
   metrics on the Execution Ledger/Comparison result shapes, provider wiring, report
   tooling).

Explicitly **out of scope** until the freeze is lifted:

- New architectural modules or phases beyond what Stages 1–6 already built.
- Autonomous agents or agentic loops.
- Memory systems (cross-run or cross-session state beyond the Execution Ledger's audit
  record).
- Workflow automation (e.g. auto-triggered pipelines, scheduled runs, CI wiring) unless
  it is itself the mechanism used to execute the benchmark suite.
- Prompt-constraining features — nothing may impose a response schema on Phase 8's final
  generation call; this was an explicit design constraint of v2.3 (see the architecture
  review, Sec. 2.1) and remains one under the freeze.

## What is frozen

Everything delivered in [ARCF_v2.3_ARCHITECTURE_REVIEW.md](ARCF_v2.3_ARCHITECTURE_REVIEW.md)
Stages 1–6:

| Area | Frozen state |
|---|---|
| Phases 1–6 (ingestion → context packaging) | Unchanged since v2.2; see the review's §1.1 |
| Multi-language repository intelligence | Python, TypeScript/JavaScript, Java, C#, Go, Kotlin analyzers, all registered in `interfaces/api/app.py` and `benchmark/src/benchmark/bootstrap.py` |
| PRHL (Predictive Response Hinting Layer) | `execution/prhl.py` — advisory-only, structurally forbidden from influencing the Composer's prompt |
| Context + Goal Composer / final generation | `execution/context_goal_composer.py`, `execution/final_generation.py` — no forced output schema |
| Execution Ledger | `domain/execution_ledger.py`, `infrastructure/execution_ledger_db.py`, `interfaces/api/routes/execution_ledger.py` — extended for validation readiness (see the validation readiness report) with `files_changed`, `lines_changed`, `build_result`, `test_result`, `execution_status`. As of the 2026-08-16/17 architecture closure, this now also has a real production writer (`application/execute_use_case.py`'s `ArcfExecutionOrchestrator`) — previously the shape existed but nothing server-side ever wrote to it. |
| Comparison API | `domain/comparison_result.py`, `telemetry/comparison_aggregator.py`, `infrastructure/comparison_store.py`, `interfaces/api/routes/comparison.py` — **correction (2026-08-17, G19/G14):** "frozen" here means only "not authorized for further change without re-scoping," not "fed by real production execution traffic." `comparison_store`/`ComparisonAggregator` remain structurally unreachable from `ArcfExecutionOrchestrator` — the same gap the original 19-gap discovery report's G14 finding identified, and the 2026-08-16/17 architecture closure did not address this half of it (only the Execution Ledger half above). A prior checklist pass (§41.1) once stated this correction had been made to this file; it had not — `git diff` against `Base` showed zero changes here until this edit. This line is that correction. |
| Benchmark harness | `benchmark/` — Direct/ARCF-Remote/ARCF-Local runners, `BenchmarkProvider` abstraction, quality/verification signals |

Any change to the *contract* of these modules (public method signatures, HTTP route
shapes, domain model fields with meaning beyond a benchmark instrumentation need) requires
lifting or explicitly re-scoping this freeze — it is not a decision to make silently in
the course of "just a bug fix."

## How this freeze is enforced

There is no automated gate for this freeze (no CI check blocks a PR that violates it).
It is a process control: reviewers evaluating changes against this branch should reject
anything that doesn't fit the two allowed categories above, and ask the change's author
to justify which category it falls under.

## Lifting the freeze

The freeze is lifted by a new decision, not a timeout. The natural trigger is: the
30–40 task benchmark suite (see the validation readiness report's blockers) has run to
completion and produced a statistically defensible result, at which point v2.3's
architecture is validated (or specific weaknesses are identified) and Phase 10
(orchestration/runtime) or other deferred work can be scoped deliberately, informed by
that result — not before.

## Re-scope Addendum (2026-08-06)

**Decision:** the freeze is **re-scoped, not lifted**, to explicitly authorize one
named body of work: the deterministic hardening effort described in a Principal
Architect review covering adaptive-depth graph traversal, evidence-sufficiency
validation, symbol disambiguation, repository boundary segmentation, the multi-language
analyzer capability registry, import/dependency resolution improvements, task-aware
deterministic ranking profiles, semantics-preserving compression, parallel indexing,
context packaging priorities, retrieval-completeness metadata, pipeline reordering, and
explicit surfacing of unsupported conditions — plus the deterministic validation
benchmark suite required to prove it. Authorized directly by the repository owner in
session, in full awareness of this freeze and its stated preference (§"Lifting the
freeze") to wait for the 30–40 task suite first.

**Why re-scope instead of lifting outright:** the original freeze's concern was scope
creep into agentic loops, memory systems, workflow automation, or a rigid Phase-8 output
schema — none of which this work touches. This effort changes the *contracts* of
`code_intelligence/` and `context/` (candidate selection, ranking, compression), which
the freeze's own text says requires an explicit re-scoping decision rather than being
silently treated as a "bug fix." That explicit decision is this addendum.

**What remains prohibited, unchanged from the base freeze:** embeddings, vector
databases, semantic/probabilistic retrieval, LLM-based file ranking, learned retrieval
weights, runtime/execution tracing, autonomous agentic loops, cross-session memory
systems beyond the Execution Ledger, and any forced response schema on Phase 8's final
generation call. See §14 of the hardening brief this addendum authorizes — it restates
the same boundary independently and is binding here too.

**What is explicitly now in scope**, superseding the base freeze's "new architectural
modules... out of scope" line for this work only:

- Deterministic, configurable-depth graph traversal in `code_intelligence/` (replacing
  fixed one-hop candidate selection), with a preserved justification chain per file.
- A deterministic evidence-sufficiency validation stage between candidate selection and
  packaging, with task-specific required-evidence contracts.
- Deterministic symbol disambiguation using module/package/namespace/import-graph
  locality, with ambiguity surfaced explicitly rather than silently resolved to the
  first match.
- Deterministic repository/workspace boundary segmentation for monorepos.
- A language capability registry that reports coverage and warns on skipped files,
  plus scaffolding for any currently-missing analyzers.
- Improved deterministic import/dependency resolution (relative, package, workspace,
  alias, build-tool path mappings) — no runtime execution, no probabilistic inference.
- Deterministic, configurable, task-aware ranking profiles (bug fix / refactor /
  architecture explanation / CI-CD / performance).
- Semantics-preserving symbol-range compression (constructors, required fields,
  referenced helpers, nearby constants stay attached to what they support).
- Parallelized indexing with a deterministic, reproducible, thread-scheduling-independent
  merge order.
- Deterministic context-packaging priority ordering, stopping at token budget.
- Deterministic retrieval-completeness metadata on `ContextResolutionResult` (files
  scanned/analyzed, languages detected, analyzer coverage, depth used, evidence
  categories satisfied, unresolved symbols, unsupported languages, compression count,
  token reduction ratio).
- Pipeline reordering so lightweight deterministic checks (repo/language detection,
  analyzer coverage, cost estimate) run before expensive SLM work.
- Explicit surfacing (never silent fallback) of unsupported languages, unresolved
  dynamic imports, reflection-heavy code, generated code, parser failures, truncated
  scans, and unresolved symbol ambiguity.
- A new deterministic benchmark suite validating the above against the categories listed
  in the hardening brief's §15, reporting files selected, depth, evidence satisfaction,
  token reduction, latency, justification chains, and a full-repository-context
  comparison.

Everything else in the base freeze — the two-category rule (bug fixes / benchmark
improvements) for anything *not* listed above, and the prohibition on agentic loops,
memory systems, workflow automation, and prompt-constraining schemas — remains in force
without change.
