# ARCF v2.3 — Architecture Freeze

**Status:** ACTIVE — effective 2026-08-04
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
| Execution Ledger | `domain/execution_ledger.py`, `infrastructure/execution_ledger_db.py`, `interfaces/api/routes/execution_ledger.py` — extended for validation readiness (see the validation readiness report) with `files_changed`, `lines_changed`, `build_result`, `test_result`, `execution_status` |
| Comparison API | `domain/comparison_result.py`, `telemetry/comparison_aggregator.py`, `infrastructure/comparison_store.py`, `interfaces/api/routes/comparison.py` |
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
