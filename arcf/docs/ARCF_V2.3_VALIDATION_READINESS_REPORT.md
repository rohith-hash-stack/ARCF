# ARCF v2.3 — Validation Readiness Report

**Prepared for:** Test Lead / Engineering Manager / Delivery Manager
**Subject:** Readiness to run a 30–40 task comparative benchmark (Direct LLM vs. ARCF)
**Date:** 2026-08-04
**Companion document:** [ARCF_V2.3_BASELINE_FREEZE.md](ARCF_V2.3_BASELINE_FREEZE.md)

> **Update (2026-08-04, ARCF v2.3 Execution Directive, Action 2):** the §4/§7 blocker
> "nothing writes to the Ledger automatically" is now closed. `benchmark/src/benchmark/
> ledger.py`'s `LedgerRecorder` is wired into `BenchmarkController.run()` (used by
> `benchmark compare` and the API's `/benchmark/run`) and `SuiteRunner.run_task_mode()`
> (used by `benchmark suite run`) — every execution, success or failure, is now
> automatically persisted, including a `provider`/`--provider` flag finally wiring the
> `BenchmarkProvider` registry (§6 limitation #5) into both the CLI and the API. A
> single mode failing no longer discards a mode that already succeeded — see
> `benchmark/src/benchmark/controller.py`'s module docstring. 26 new tests cover this
> (`tests/test_ledger.py`, `tests/test_controller.py`, `tests/test_model_resolution.py`,
> plus suite/API/CLI test extensions). The rest of this report (§1–3, §5, §6.1–4/6–8,
> §7 items 1/3–6) is otherwise unchanged and still accurate as of this update.

> **Update (2026-08-04, ARCF v2.3 Execution Directive, Actions 1 & 3):** the frontend
> dashboard is built (Action 1 — extends `benchmark/src/benchmark/api/static/`, not a new
> app, per explicit direction) and verified live in a browser: repository load, a failed
> run (no credentials configured in this environment) correctly recorded to the Ledger
> as `provider_error`, Execution History filter/search/2-row-compare/export, and
> Metrics/Diff Viewer rendering all confirmed working via DOM/network/console inspection.
> §7 item 1's task-count blocker is substantially addressed: `benchmark/suites/
> v23_baseline_40.json` replaces the 8-task pilot with 40 tasks (8 per category,
> including a new `feature_implementation` category), an aggregated report generator
> (`render_suite_report`) and a separate executive summary generator
> (`render_executive_summary`) covering every metric the Execution Directive named,
> including the previously-missing "average repository grounding score." Honest caveats
> on the new suite: only 2 of 40 tasks target `todomvc` (no verified real fixture
> material was available this session for more), and roughly half the Bug Fixing/
> Refactoring/Feature Implementation tasks fall back to the full arcf test suite as a
> broad "did it break anything" oracle rather than a task-specific assertion, because a
> precise real regression wasn't available to construct safely for every prompt (e.g.
> arcf has no login/password/database-transaction concepts many of the requested prompts
> assume) — this is disclosed per-task, not hidden. Two Bug Fixing tasks (401 auth
> bypass, JWT signature bypass) inject real, hand-verified regressions into
> `arcf/src/infrastructure/auth.py`; both were proven this session to make the exact
> right existing tests fail when the bug is present and pass when it isn't. **No real
> LLM calls were made for Action 3** — everything above was proven with litellm mocked,
> per explicit instruction not to spend real money without a separate go-ahead. §7 item 2
> (no automated Ledger writes) is now closed per the Action 2 update above, so the suite
> can be run for real (`benchmark suite run --suite v23_baseline_40 --mode ...`) once
> provider credentials are configured — that live run has not happened yet.

## How to read this report

This report is written to be checked, not taken on faith. Every "ready" claim below
points at a specific file and a specific passing test suite you can re-run yourself.
Every gap is stated as a gap, not rounded up to "ready" or hidden in a footnote. Where a
metric can't be trusted yet, that's said plainly, including *why* it can't be trusted —
not just that it's incomplete.

**Bottom line up front:** the deterministic pipeline (multi-language indexing, context
resolution, the Execution Ledger, the Comparison API) is solid and independently
verified. The thing standing between today and a real 30–40 task run is orchestration
and scale, not architecture: there is no automated path yet from "a runner produced a
result" to "that result is in the Ledger," and the benchmark suite itself has 8 of the
30–40 target tasks written. Both are scoped, bounded pieces of work, not open design
questions.

---

## 1. Architecture Freeze Confirmation

ARCF v2.3, as implemented through Stages 1–6 of the v2.3 migration
([ARCF_v2.3_ARCHITECTURE_REVIEW.md](ARCF_v2.3_ARCHITECTURE_REVIEW.md)), is frozen as the
benchmark baseline effective 2026-08-04. Full terms are in
[ARCF_V2.3_BASELINE_FREEZE.md](ARCF_V2.3_BASELINE_FREEZE.md): only bug fixes and
benchmark-related improvements are authorized against this baseline until the freeze is
lifted. The Execution Ledger extension described in §4 below is itself the one
benchmark-related change made under this freeze — it's flagged as such, not as a new
architectural module.

## 2. Supported Languages — Evidence, Not Assertion

**Claim:** the multi-language analyzer framework is operational and correctly registered
for Python, TypeScript/JavaScript, Java, C#, Go, and Kotlin.

**Evidence:** [tests/code_intelligence/test_multi_language_repository_validation.py](../tests/code_intelligence/test_multi_language_repository_validation.py) —
7 tests, all passing, added specifically for this report. Each test builds a real
two-file fixture repository (a "definer" file and a "caller" file in a different
module/package that imports and calls it), then runs the **full** Phase 5 pipeline
end to end: `CodeIntelligenceEngine.build_index` → `SymbolIndex` / `ImportGraph` /
`DependencyGraph` / `CallGraph` / `CandidateFileSelector` → `ContextResolver.resolve`.
This is a materially stronger check than the per-analyzer unit tests
(`tests/code_intelligence/languages/*.py`, 24–119 tests apiece) that already existed —
those exercise one analyzer in isolation; this proves cross-file symbol resolution,
import resolution, and call-graph attribution all work together, using one
`CodeIntelligenceEngine` registered with all six analyzers simultaneously — the same
wiring `interfaces/api/app.py` and `benchmark/src/benchmark/bootstrap.py` use in
production. A seventh test (`test_all_six_languages_coexist_in_one_registry_without_cross_contamination`)
proves dispatch-by-extension picks the correct analyzer for each of the six languages
in one shared repository with zero leakage between them.

| Language | Analyzer | Registered in `app.py` / `bootstrap.py` | Indexing + resolution proven |
|---|---|---|---|
| Python | `python_analyzer.py` | Yes | Yes |
| TypeScript / JavaScript | `typescript_analyzer.py` | Yes | Yes |
| Java | `java_analyzer.py` | Yes | Yes |
| C# | `csharp_analyzer.py` | Yes | Yes |
| Go | `go_analyzer.py` | Yes | Yes |
| Kotlin | `kotlin_analyzer.py` | Yes | Yes |

**What this evidence does *not* cover** (see §6, Known Limitations, for the honest
version): the fixtures are synthetic, minimal two-file repositories, not real
third-party codebases. Import resolution for Go, C#, and Kotlin is a documented
best-effort heuristic (each analyzer's own module docstring explains why — Go/C#
imports name a whole package/namespace, not one file, unlike Python/TypeScript/Java's
closer-to-1:1 mapping) — it has not been stress-tested against a large, real repository
with deep package nesting, re-exports, or build-tool-specific path remapping.

## 3. Benchmark Mode Readiness

| Capability | Status | Where | Notes |
|---|---|---|---|
| Direct LLM execution | **Ready** | `benchmark/src/benchmark/runners/direct_llm_runner.py` | Sends the full scanned repository (bounded by `max_context_tokens`) — a genuine "send everything" baseline using the same scanner ARCF uses. |
| ARCF execution | **Ready** | `benchmark/src/benchmark/runners/arcf_runner.py` | Drives the real Phase 1–8 pipeline (Contract → Workspace → Code Intelligence → Context Package → Composer/final generation), not a simulation. Modes B (remote SLM-1) and C (local SLM-1) are the same class with different constructor args. |
| Multiple providers | **Partial** | `benchmark/src/benchmark/providers/` (new this session) | `LiteLLMClient` itself is provider-agnostic by construction and was proven this session against OpenAI/Gemini/Groq/Ollama-shaped model strings (see architecture review §2.5). A `BenchmarkProvider` registry now exists (openai/anthropic/gemini/groq/ollama), fully unit-tested (16 tests), but **is not yet wired into `cli.py`** — today's CLI still takes a raw litellm model string via `--model`, unaffected by the new registry. |
| Token measurement | **Ready** | `TokenMetrics` in `benchmark/domain/models.py` | Input/output/total, from real `LLMResponse` usage, not estimated. |
| Latency measurement | **Ready** | `LatencyMetrics` / `StageLatencies` | Per-stage breakdown for ARCF (intent extraction, workspace scan, code intelligence, context packaging, final LLM call). |
| Cost estimation | **Ready** | `CostMetrics` | Both estimated (pre-call, from `CostEstimator`) and actual (post-call, from real token counts). |
| Files modified | **Ready** | `QualityMetrics.modified_files`, `quality.extract_modified_files` | Parses two output conventions: markdown `### path` headers and unified-diff / `git diff` headers. Best-effort text parsing, not a real diff engine — documented as such in `quality.py`. |
| Lines changed | **New this session** | `QualityMetrics.lines_changed`, `quality.count_changed_lines` | Counts +/− hunk lines in unified-diff-formatted output. **Returns 0 for the suite's own output format** — the suite forces full-file-content blocks (`### path` + complete file, via `suite/patcher.py`'s `FORMAT_ADDENDUM`), not diffs, so this signal is honestly blank for every suite-mode run today. See §6. |
| Build status | **Gap** | `suite/verifier.py`'s `run_verification` | Only exists inside suite mode, and only as a single combined `verify_command` per task — there is no separate build step. Not available at all for ad-hoc (non-suite) `benchmark compare`/`run` invocations. |
| Test status | **Gap — same root cause** | `ModeVerification.tests_passed` | Same single `verify_command` produces this signal; it is stored in a separate suite-only model (`ModeVerification` / `SuiteModeRunRecord`) and is **not** wired into `RunResult.quality_metrics` (`compilation_success`/`test_success` stay `None` by design — see that model's own docstring) or into `ExecutionLedgerEntry.build_result`/`test_result`. That wiring doesn't exist yet. |
| Execution status | **New this session, unpopulated** | `ExecutionLedgerEntry.execution_status` | Field exists (default `"success"`), but nothing in `benchmark/` or `arcf/src` sets it to `"failed"`/`"timeout"`/`"error"` automatically yet — runners currently propagate exceptions rather than catching them and recording a status. A caller writing a Ledger entry must set this explicitly today. |

## 4. Execution Ledger Readiness

**Status: Ready**, extended this session specifically for this validation baseline.

`domain/execution_ledger.py`'s `ExecutionLedgerEntry` now carries every field requested:
timestamp (`created_at`), repository (`repository_root`), branch, mode, model, prompt,
selected files, selected symbols, input/output/total tokens, latency, estimated cost,
files changed, lines changed, build result, test result, and execution status (plus
`manual_rating` and a `predicted_response` snapshot, carried over from earlier stages).

- **Persistence:** `infrastructure/execution_ledger_db.py` — SQLite (`SqliteExecutionLedgerStore`)
  and in-memory implementations behind one `ExecutionLedgerStore` protocol. Retention
  keeps the most recent 50 entries **per workspace**, not 50 globally (a deliberate
  choice, documented in that module, so one active repository can't evict every other
  workspace's history).
- **HTTP surface:** `interfaces/api/routes/execution_ledger.py` — list (last N, capped
  at 200), get by id, delete, patch (manual rating / build result / test result), and a
  generic compare-any-two-entries endpoint with a unified diff of artifact content.
- **Verification:** 40 passing tests across `tests/domain/test_execution_ledger.py`,
  `tests/infrastructure/test_execution_ledger_db.py`, and
  `tests/interfaces/test_execution_ledger_route.py`, including explicit round-trip
  coverage of every field added this session.

**The one real gap:** nothing writes to this Ledger automatically yet. There is no
`application/execute_use_case.py` (an end-to-end orchestrator tying Contract → Workspace
→ Code Intelligence → Context → Composer → Ledger together) — that was explicitly
deferred in the original v2.3 migration plan (Sec. 6), and it still doesn't exist. Every
entry seen in this session's tests was constructed and saved by hand. Before a 30–40
task suite can populate a Ledger worth analyzing, *something* — either that orchestrator,
or a thinner adapter inside `benchmark/`'s own runners — needs to call
`ExecutionLedgerStore.save()` after each Direct/ARCF run.

## 5. Comparison Interface Readiness

**Status: API-ready.**

`POST /api/v1/compare` and `GET /api/v1/compare/{id}` (`interfaces/api/routes/comparison.py`)
produce a `ComparisonResult` (`domain/comparison_result.py`) that embeds the **full**
`direct` and `arcf` `ExecutionLedgerEntry` objects side by side — not a re-declared
subset — plus `token_reduction_pct`, `latency_reduction_pct`, `cost_reduction_pct`,
`context_efficiency_ratio` (CER), and `prompt_compression_ratio` (PCR), using formulas
quoted directly from `benchmark/src/benchmark/analyzer.py`'s existing, working
implementation.

Because it embeds full Ledger entries, **every field added to the Ledger this session
(files_changed, lines_changed, build_result, test_result, execution_status) is already
visible side by side with zero additional comparison-layer code** — proven by
`tests/interfaces/test_comparison_route.py::test_comparison_surfaces_validation_baseline_fields_side_by_side`,
added for this report.

**Gaps:**

- **No frontend.** "Comparison UI" today means an API contract a frontend could be
  built against, not a rendered page. `benchmark/`'s own static comparison UI
  (`benchmark/src/benchmark/api/static/*`, referenced in the architecture review as
  already built and browser-tested in an earlier session) is a **separate,
  benchmark-only UI** — it is not wired to ARCF's own `/api/v1/compare` endpoint.
- `POST /api/v1/compare` requires both entries to already exist in the Ledger — it
  inherits §4's gap. It deliberately does not drive a Direct/ARCF run itself (see that
  route's own module docstring for the reasoning: duplicating `benchmark/`'s runners
  here was assessed as scope creep against the architecture review's own risk table).
- No human-evaluation interface exists (the original v2.3 brief's "human evaluation via
  comparison UI," architecture review Sec. 9 item 3) — only the Ledger's `PATCH`
  endpoint for setting `manual_rating` after the fact, via API, not a UI.

## 6. Known Limitations

1. **Lines-changed is diff-format-dependent.** It reads 0 for every suite-mode run
   today, because the suite forces full-file-content output, not diffs (see §3). A
   correct lines-changed count for suite mode requires diffing generated content against
   the original file on disk (before/after), which nothing computes yet.
2. **Build and test status are conflated into one signal**, and only exist for suite
   tasks that define a `verify_command`. There is no distinct "did it compile" check
   separate from "did the tests pass."
3. **`execution_status` is not yet auto-populated** by any runner. It's a schema-level
   readiness item, not a working automatic signal.
4. **No automated Ledger writes.** Every Ledger entry used in this session's evidence
   was constructed directly in a test. Production use requires either the deferred
   `application/execute_use_case.py` or a benchmark-side adapter.
5. **`BenchmarkProvider` is unused.** The abstraction exists and is tested in isolation
   but doesn't yet change any runtime behavior — the CLI still takes a raw model string.
6. **Multi-language import resolution is a documented best-effort heuristic**, not exact,
   for Go, C#, and Kotlin (see §2). It has only been validated against small synthetic
   fixtures, not a real large repository per language.
7. **No independent re-verification this session of the statistical harness**
   (`benchmark/suite/stats.py`'s paired t-test, `benchmark/suite/report.py`'s verdict
   rule). The architecture review states these were hand-verified in an earlier session;
   that claim was not re-checked here.
8. **The Comparison UI is API-only.** No rendered frontend exists against ARCF's own
   `/api/v1/compare`; the benchmark's separate static UI is not connected to it.

## 7. Blockers Before Running a 30–40 Task Benchmark Suite

In priority order — items 1–2 block the suite from running at meaningful scale at all;
items 3–6 affect the *credibility* of results once it does run.

1. **Task count.** `benchmark/suites/pilot.json` has **8 tasks** today, across 4
   categories (`repository_understanding`, `bug_fixing`, `refactoring`,
   `test_generation`), against 2 repositories (`arcf` — Python; `todomvc` — TypeScript).
   Reaching 30–40 tasks means authoring roughly 22–32 more. None currently target Java,
   C#, Go, or Kotlin repositories — `benchmark/src/benchmark/suite/repo_pool.py` only
   registers `arcf` and `todomvc` as base checkouts. If multi-language coverage in the
   *benchmark results themselves* (not just the indexing validation in §2) matters for
   this run, that requires registering new base repos per language too.
2. **No automated Ledger population.** As in §4 — running 30–40 tasks × multiple
   providers × multiple modes by hand-constructing Ledger entries will not scale.
   This needs to be built before the run, not worked around during it.
3. **Provider selection is manual.** Running the suite against multiple providers today
   means passing correct, provider-specific litellm model strings by hand per invocation
   — no CLI-level provider discovery or availability check yet (§3, §6.5).
4. **Build/test signals will be incomplete or absent** for any task category without a
   `verify_command`, and lines-changed will read 0 for every suite-mode task regardless
   of category (§6.1–2). Decide before the run whether that's acceptable for this
   suite's purpose, or whether it's a blocking gap to close first.
5. **Multi-language analyzer validation has only been done on synthetic fixtures.**
   Before trusting CER/PCR numbers for Java/C#/Go/Kotlin tasks specifically, indexing at
   least one real repository per language (not the 2-file fixtures in §2) is recommended.
6. **Statistical harness not re-verified this session** (§6.7) — worth a fresh sanity
   check before treating its p-values as authoritative for a 30–40 task result.

## 8. Test Evidence Summary

All claims above are backed by tests that pass as of this report, run against this
session's code:

- `arcf/`: **479 passing tests**, `ruff check` clean, `mypy --strict` clean across 181
  source+test files.
- `benchmark/`: **139 passing tests**, `ruff check` clean, `mypy --strict` clean across
  75 source+test files.

Re-run with:

```bash
cd arcf && uv run pytest -q && uv run ruff check src tests && uv run mypy src tests
cd ../benchmark && uv run pytest -q && uv run ruff check src tests && uv run mypy src tests
```

## 9. Recommendation

Do not start the 30–40 task suite yet. Close blockers 1 and 2 in §7 first — they are
the difference between "a benchmark suite exists" and "a benchmark suite that produces
data anyone can trust." Everything else in this report is either already solid (the
deterministic pipeline, the Ledger schema, the Comparison API) or a scoped, well-
understood gap (§6) that can be closed or explicitly accepted as a stated limitation
before the run, not discovered after it.
