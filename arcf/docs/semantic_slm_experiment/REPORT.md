# Does a Semantic SLM Layer Improve ARCF Retrieval? — Experiment Report

**Scope of this task:** determine, experimentally, whether a generic SLM semantic-interpretation
layer is worth investing in — specifically whether it justifies going on to QLoRA training. No
QLoRA training or production adapter infrastructure was built. No ARCF-DI retrieval algorithm was
modified. No benchmark ground truth was modified.

**Bottom line, stated up front:** the live A/B/C comparison this brief asks for (current ARCF vs.
generic local SLM vs. ARCF-specialized-prompt SLM) **could not be executed in this sandbox** — no
LLM API key and no local model runtime (Ollama) were available (see §4/§9). What *could* be
obtained is (a) new, tested, reusable infrastructure to run that comparison the moment credentials
exist, (b) one real, live data point (the SLM-1-bypass control, which needs no LLM), and (c) this
codebase's own substantial prior empirical record on exactly this question, which already leans
toward **"the semantic layer is not the dominant bottleneck"** — see §11/§13.

---

## 1. Existing ARCF Semantic Architecture

ARCF already has a semantic-interpretation stage in production — it is not a deterministic-only
pipeline waiting for its first SLM. This matters: the brief's "A. Current ARCF baseline" is not
"no semantic layer," it's "semantic layer = SLM-1 on a remote model."

**Pipeline, confirmed by reading `contracts/manager.py`, `contracts/intent_extraction.py`, and
`code_intelligence/service.py`:**

```
User query (raw_request)
  -> IntentExtractor.extract()  [SLM-1: an LLM call, json_object mode, temperature=0.0,
                                  model = shared/config.py's slm_model, default "gpt-4o-mini"]
     -> RawIntentExtraction{intent_summary, domain, task, entities, constraints,
                             assumptions, self_reported_confidence, suggested_clarifying_questions}
  -> DomainClassifier / TaskClassifier   (deterministic keyword corroboration, NOT LLM)
  -> ConfidenceEngine.score()            (deterministic weighted formula)
  -> ClarificationPlanner.plan()         (deterministic + SLM-1's own suggested questions)
  -> UserIntent{..., entities}           persisted on the Contract

  [only `entities` — a flat list[str] — ever reaches retrieval, via a SEPARATE, caller-driven
   call: target_names = UserIntent.entities]

  -> CodeIntelligenceContractService.attach_code_intelligence(target_names, workspace_root, ...)
     -> classic: ContextResolver Tier-1 EXACT match (SymbolIndex.find_by_name/
                 find_by_qualified_name) + lexical-probe/anchor-classification fallbacks
     -> drp:     DrpResolver folds target_names into the query TEXT (not a privileged channel)
  -> ContextResolutionResult{candidate_files, ...}
  -> RelevanceRanker -> ContextBudgetManager -> ContextPackage
  -> ContextUnderstandingAnalyzer ("SLM-2" — a SECOND LLM call, advisory-only commentary,
                                    never influences file selection — packager.py's own docstring:
                                    "selection is never SLM-decided")
```

Key facts that shape everything below:

- **No swappable interface exists today.** `IntentExtractor.__init__` and
  `ContextUnderstandingAnalyzer.__init__` both hard-type a concrete `LiteLLMClient`, not a
  Protocol. The only swap axis in production is the `model: str` argument — any litellm-supported
  model string, changeable via `ARCF_SLM_MODEL`. This experiment adds a real Protocol (§3) without
  touching that production code.
- **ARCF-DI's actual accepted interface is narrow**: plain query text plus an optional **flat
  `list[str]`** (`target_names`). Classic resolution exact-matches each string against real symbol
  names; DRP folds them into the query text as extra tokens. Neither accepts a structured object —
  this bounds how much a richer semantic contract (§2) can influence retrieval without changing
  ARCF-DI itself.
- **`benchmark/` already has a "Direct vs. current-ARCF vs. generic-local-SLM" harness**, built in
  a prior session and *not* something this task needed to invent: `benchmark/src/benchmark/
  bootstrap.py` wires three runners — `direct_runner` (no ARCF-DI), `arcf_runner` constructed with
  `slm_model=settings.slm_model` (remote, e.g. `gpt-4o-mini` — "Mode B"), and `arcf_local_runner`
  constructed identically except its `IntentExtractor`'s model comes from
  `benchmark.local_slm.ollama_provider.OllamaProvider.resolve_model()` (local Ollama, default
  candidates `qwen2.5:1.5b-instruct` / `qwen2.5:3b-instruct` / `phi3:mini` — "Mode C"). Per
  `bootstrap.py`'s own docstring: *"only the ExecutionContractManager (and therefore
  IntentExtractor/slm_model) differs between the two ArcfRunner instances, which is the whole
  point: 'only intent extraction differs' is enforced by construction, not by convention."* This
  is exactly the brief's Step 4 control requirement, already built. `benchmark/suite/runner.py`
  wraps this with a full statistical suite (paired t-tests, per-category summaries, a mechanically
  computed `'continue'|'pivot'|'stop'` verdict) driving `benchmark/suites/pilot.json` (8 tasks) and
  `v23_baseline_40.json` (40 tasks).
- **What that existing harness does NOT have**: Recall@1/Recall@5/MRR (rank-based). Its only
  retrieval-accuracy metric is set-overlap Precision/Recall/F1 against free-text `expected_grounding`
  terms (`benchmark/suite/scoring.py`), for final-*answer* grounding, not raw retrieval rank. A
  rank primitive already exists, but in a different, standalone script:
  `code_intelligence/drp/diagnostics.py::compute_retrieval_rank(files, target_file)` — the exact
  function `arcf/scripts/drp_benchmark.py` already uses against `resolution.candidate_files`. This
  experiment's new code (§3) reuses that primitive rather than inventing a second rank definition,
  and adds the Recall@k/MRR aggregation that didn't exist anywhere.
- **"Phase 3" and "Category B ambiguous symbol" are not literal artifacts in this codebase** — an
  honest correction, not an assumption. Exhaustive grep across `arcf/` and `benchmark/` found: (a)
  "Phase 3" always refers to ARCF's own pipeline stage numbering (SLM-1 intent extraction is
  "Phase 3"), never a benchmark-suite version; (b) no task category or fixture is named "Category
  B" anywhere. The closest real analog is `arcf/scripts/validate_llm_grounding.py`'s
  `task5_ambiguous_common_name` (the flagship Consul `agent/cache.New` ambiguity, 156 same-named
  candidates repo-wide) and PROGRESS.md's repeatedly-documented "flagship 'New'-style
  extreme-ambiguity retrieval — still not solved" thread. That thread's own root-cause diagnosis
  (`docs/ARCF_SESSION_HANDOFF_2026-08-09.md` and PROGRESS.md's "Open/unresolved" list) attributes
  it to **Tier-1 entry-point fan-out** — a deterministic-side mechanism, not a semantic-extraction
  one. See §5 for how this task's own retrieval-task set was built given that correction.
- **This exact question has already been investigated, twice, at the code level**, before this
  task started:
  - `arcf/scripts/slm1_bypass_experiment.py` — real stored SLM-1 entities vs. `target_names=[]`,
    same query, classic and DRP resolvers. Documented finding: **11/12 queries produced identical
    (9 byte-identical, 2 identical except log text) candidate sets and confidence** whether SLM-1's
    entities were used or not; the 1 differing case, SLM-1's entities arguably made resolution
    *worse*, not better.
  - `arcf/scripts/contract_creation_slm1_experiment.py` — real SLM-1 calls compared against the
    deterministic `DomainClassifier`/`TaskClassifier`'s independent guesses, testing whether
    SLM-1's contribution to `ConfidenceEngine`'s "agreement" signal (0.30 of its total weight) is
    redundant. Its ≥80%-agreement success threshold is stated in the script; **the actual measured
    result was never persisted** (stdout-only, not re-run this session either — no API key, see
    §4) — a genuine, named gap, not a finding either way.
  - `docs/ARCF_SESSION_HANDOFF_2026-08-09.md` separately records: *"**SLM-based query expansion** —
    analyzed in depth, user said 'forgot about SLM Q/A proposal, I will find an alternative way.'
    Do not resume."* — a prior, explicit decision against a semantic-expansion approach on DRP's
    subsystem-routing thread specifically (a different mechanism from SLM-1, noted for completeness).

## 2. Changes Made

All changes are additive, under `benchmark/` only. **Zero files under `arcf/src/` were modified.**
No ARCF-DI retrieval algorithm, ranking formula, or benchmark ground truth was touched.

| File | What |
|---|---|
| `benchmark/src/benchmark/semantic_layer/contract.py` | NEW. `SemanticQueryInterpretation` — the structured semantic contract (full design in §2 below and in the module's own docstrings: required/optional fields, validation rules, malformed-output/uncertainty/ambiguous/negative-query handling). |
| `benchmark/src/benchmark/semantic_layer/interpreter.py` | NEW. `SemanticInterpreter` Protocol (the swappable seam) + three implementations: `ExistingSlm1Interpreter` (wraps arcf's real `IntentExtractor` unmodified), `LLMSemanticInterpreter` (new ARCF-specialized prompt using the new contract), `BypassInterpreter` (no LLM call, the SLM-1-bypass control). |
| `benchmark/src/benchmark/semantic_layer/adapter.py` | NEW. `to_target_names()` — the one, minimal, explicitly-scoped projection from the new contract down to the `target_names: list[str]` ARCF-DI already accepts. This is the "minimal adapter" the brief allows without touching ARCF-DI; see the module's own docstring for exactly what is and is not projected. |
| `benchmark/src/benchmark/semantic_layer/tasks.py` | NEW. 6 retrieval ground-truth tasks: 5 are a direct, minimal single-file projection of `benchmark/suites/pilot.json`'s existing `repo_key="arcf"` tasks (no new queries, no new ground truth invented); 1 (`ambiguous-symbol-save`) is genuinely new, constructed because no ambiguous-symbol fixture exists anywhere runnable in this sandbox, using the same grep-verified-against-real-source discipline `validate_llm_grounding.py`'s Consul task already used (see the module docstring for the exact `grep` that found `save` defined 12 times across 5 files in `arcf/src`). |
| `benchmark/src/benchmark/suite/retrieval_scoring.py` | NEW. `recall_at_k`, `mean_recall_at_k`, `reciprocal_rank`, `mean_reciprocal_rank`, and `diagnose()` (the A–F failure classification from Step 6 of the brief). Reuses `code_intelligence.drp.diagnostics.compute_retrieval_rank`, does not reimplement it. |
| `benchmark/scripts/semantic_layer_experiment.py` | NEW. The runner: 4 arms (`current_arcf`, `generic_slm_plain`, `generic_slm_specialized`, `slm_bypass_control`) against one shared `CodeIntelligenceContractService` instance, `--fake-client` dry-run mode, JSON output. |
| `benchmark/tests/semantic_layer/*`, `benchmark/tests/suite/test_retrieval_scoring.py` | NEW. 33 unit tests, all passing (see §9). |
| `arcf/docs/semantic_slm_experiment/*.json` | NEW. The two result files this report cites verbatim (§5/§6). |

## 3. Generic SLM Architecture

### The contract (Step 2)

`SemanticQueryInterpretation` (full field-by-field rationale in `contract.py`'s docstrings):

- **Required**: `intent` (free-text label, non-blank), `confidence` (closed set:
  `high|medium|low|uncertain` — a qualitative level, not a numeric score, so the model can't
  fabricate false precision), `is_ambiguous` (bool, default False), `is_negative_query` (bool,
  default False).
- **Optional, default empty/None**: `retrieval_terms`, `concepts`, `behavior`, `framework`,
  `ambiguous_alternatives`, `negation_targets`.
- **Validation rules**: every string list capped at 12 items and 80 chars/item; any retrieval term
  matching a bare-number or `path:line` shape is REJECTED at the pydantic layer — the model is not
  allowed to assert a line number or file location, only ARCF-DI may do that.
- **Malformed output**: `LLMSemanticInterpreter` retries (default 2 attempts) on JSON-decode or
  pydantic `ValidationError`, then raises `SemanticInterpretationError` — same shape as
  `IntentExtractor`'s existing retry-then-`IntentExtractionError` pattern, not a new convention.
- **Uncertainty**: `confidence="uncertain"` with empty `retrieval_terms` is explicitly, structurally
  VALID — not a failure state to "fix" (`contract.py`'s model-validator docstring exists
  specifically to keep a future edit from silently reintroducing a non-empty-terms requirement).
  The adapter (below) treats `uncertain` specially regardless of what `retrieval_terms` contains.
- **Ambiguous queries**: `is_ambiguous` + optional `ambiguous_alternatives` — the interpreter's own
  signal, computed pre-retrieval, distinct from ARCF-DI's own post-retrieval ambiguity signals
  (e.g. `FileReference.ambiguity_confidence`).
- **Negative queries**: `is_negative_query` + optional `negation_targets`, so a query like "why
  isn't the JWT's sub claim validated" is flagged rather than silently treated as a positive
  "find X" query. See adapter.py for exactly how far this flag's handling goes today (it is
  surfaced, not yet specially routed — see §12).

### The adapter (Step 3, the "minimal ARCF-DI interface")

`to_target_names(interpretation) -> list[str]` is the **only** connection between this contract and
ARCF-DI. Only `retrieval_terms` is projected — `concepts`/`behavior` never reach ARCF-DI, because
doing so would let "the SLM's vague topical impression" get exact-matched as if it were an asserted
identifier, exactly the repository-truth fabrication the brief prohibits. `confidence="uncertain"`
forces an empty list even if `retrieval_terms` is non-empty, so an interpreter that says "I don't
know" cannot still smuggle a guess into retrieval.

### The swappable interface (Step 3)

```python
class SemanticInterpreter(Protocol):
    async def interpret(self, query: str) -> InterpretationResult: ...
```

Three implementations feed the *same* downstream `CodeIntelligenceContractService
.attach_code_intelligence` call unmodified:

- `ExistingSlm1Interpreter(llm_client, model)` — wraps arcf's real `IntentExtractor`. Used for
  BOTH "current ARCF" (`model=gpt-4o-mini`, arcf's actual default) and "generic SLM, no special
  prompting" (`model=<local Ollama model>`) — same prompt and contract either way, only the model
  string differs, isolating "does a smaller model alone change anything" (brief's Step 7, arm 2).
- `LLMSemanticInterpreter(llm_client, model)` — the new, ARCF-specialized prompt/contract above, on
  the same local model — isolates prompt/contract effect from model effect (Step 7, arm 3).
- `BypassInterpreter()` — no LLM call, `target_names=[]` always — the SLM-1-bypass control,
  matching `slm1_bypass_experiment.py`'s own hypothesis test.

A future QLoRA-tuned SLM would be a fourth implementation of the same three-line Protocol — no
change to `adapter.py`, `retrieval_scoring.py`, or `arcf/src` required. This is deliberate: it's
the seam Step 3 asked for, built without pre-committing to QLoRA being the right next step.

## 4. Benchmark Methodology

**Reused, not reinvented**: the runner (`scripts/semantic_layer_experiment.py`) calls
`CodeIntelligenceContractService.attach_code_intelligence` — the exact real production entry point
`arcf_runner.py` and `slm1_bypass_experiment.py` already call — and reuses
`compute_retrieval_rank` from `code_intelligence/drp/diagnostics.py` unmodified. All four arms
share ONE `CodeIntelligenceEngine`/`CodeIntelligenceContractService`/`InMemoryContractStore`
instance and run against the same repository at the same commit within a single process invocation
— only `target_names` (produced by whichever `SemanticInterpreter` the arm uses) differs between
arms, matching the brief's Step 4 control requirement exactly.

**Repository and pinning**: the ONE repository actually usable in this sandbox is `arcf` itself —
`.benchmark_repos/{consul,django,fastapi,flask,sqlalchemy,traefik,vllm}/` are present as directory
names but **empty** (confirmed by listing each one), and `arcf/scripts/validate_llm_grounding.py`'s
Consul-based ambiguous-symbol task could not be re-run for that reason. This environment has no
notion of a pinned commit SHA for those seven repos anywhere in the codebase (confirmed by grep) —
an existing, pre-dates-this-task reproducibility gap, not something this task introduced. The `arcf`
repository used here is this session's own checkout, at the commit this branch was built from
(`git -C arcf rev-parse HEAD` at commit time — see the branch's own git history for the exact SHA);
both the real bypass-control run and the fake-client smoke run used the identical checkout.

**Tasks**: 6 retrieval tasks (§2's `tasks.py`), each with a single ground-truth `target_file` — see
§1's honest correction on why these are a projection of `pilot.json`'s arcf-repo tasks plus one new,
independently-grep-verified ambiguous-symbol task, not a "Category B" suite that doesn't exist.
A named, honestly-flagged weakness: 3 of the 6 tasks state their target file's path verbatim in the
query text (they were authored for end-to-end code-gen scoring, not semantic-ambiguity stress —
see `tasks.py`'s docstring) — ARCF-DI's lexical-probe fallback can resolve these regardless of
semantic-layer quality, so they cannot discriminate between interpreters. Kept anyway rather than
dropped, to avoid cherry-picking a suite that looks harder than what already existed.

**Metrics**: Recall@1, Recall@5, MRR (rank-based, new — §1), candidate-pool size, top-k candidates,
the A–F failure classification (§1/`retrieval_scoring.py`; C/D/F are explicitly labeled heuristic,
not certain — see `FailureClass`'s own docstring), SLM prompt/completion tokens, latency, and
`malformed_attempts` (retry count due to invalid JSON/schema — a real malformed-output-rate proxy,
reusing `LLMResponse.attempts`, not a new counter bolted on separately).

## 5. Baseline Results

**Could not be obtained.** "Current ARCF baseline" here means SLM-1 on `gpt-4o-mini` (§1) — a live
LLM call. This sandboxed environment has **no `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` set** (checked
directly; only `ANTHROPIC_BASE_URL` is present, which is this Claude Code session's own internal
routing, not a general-purpose credential litellm can use). A real attempt was made — not skipped —
and failed exactly as expected:

```
litellm.InternalServerError: OpenAIException - Missing credentials. Please pass an `api_key`, ...
or set the `OPENAI_API_KEY` or `OPENAI_ADMIN_KEY` environment variable.
```

All 6 tasks in the `current_arcf` arm recorded this as `arm_error`, not a silently-produced number
— see `arcf/docs/semantic_slm_experiment/bypass_control_real_result.json`'s `arms.current_arcf`.

**What WAS obtained for real** (no LLM required): the `slm_bypass_control` arm — `target_names=[]`
always, ARCF-DI's own deterministic fallbacks (lexical probe, anchor classification) doing all the
work. This is genuine, live, non-synthetic output from the real `arcf` repository:

| task_id | rank | candidates | failure_class |
|---|---|---|---|
| repo-understanding-auth-discovery | 20 | 36 | B (in pool, ranked too low) |
| repo-understanding-dependency-analysis | 12 | 34 | B |
| bug-fixing-jwt-missing-sub | 14 | 45 | B |
| bug-fixing-idempotency-replay | 12 | 35 | B |
| refactoring-retry-exception-resolution | 12 | 25 | B |
| ambiguous-symbol-save | 8 | 23 | B |

**Aggregate: Recall@1 = 0.0, Recall@5 = 0.0, MRR = 0.083.** Notably: the target file entered the
candidate pool in **6/6 tasks (never class A)** — ARCF-DI's deterministic fallback discovery
mechanism found the right file every time even with zero semantic guidance. It never ranked it in
the top 5. On this small task set, with the semantic layer fully absent, the bottleneck is
consistently **ranking, not discovery**.

## 6. Generic SLM Results

**Could not be obtained** — both `generic_slm_plain` and `generic_slm_specialized` require a local
Ollama daemon. None is installed or running in this sandbox (`which ollama` finds nothing; no GPU
present). The runner's own `OllamaProvider` correctly detected this and skipped both arms with a
clear, actionable message rather than crashing or fabricating a result:

```
Ollama is not reachable at http://localhost:11434: [Errno 111] Connection refused.
Make sure the Ollama daemon is running (`ollama serve`) and reachable at that address.
```

Per the brief's own instruction ("if model configuration/hardware is uncertain, do not make
assumptions"), no attempt was made to install Ollama and pull multi-gigabyte model weights into
this ephemeral sandbox to force a number — that would be standing up new infrastructure to answer
one question, not evaluating whether the question is worth answering.

**What was verified instead**: a `--fake-client` smoke run (`litellm.acompletion` monkeypatched to
a deterministic canned responder, matching this repo's own existing test convention in
`tests/contracts/test_intent_extraction.py`) — proves the full harness (both interpreters, the
adapter, retrieval, ranking, aggregation, JSON output) executes end-to-end without error. This is
explicitly `"synthetic": true` in `arcf/docs/semantic_slm_experiment/
fake_client_smoke_test_result.json` and must not be read as evidence about real model quality.

## 7. Category-Level Results

Not obtainable with only one working (control) arm — category-level *comparison* requires at least
two arms to differ. The bypass-control arm's own 6/6 results (§5) span 4 of the task categories
(`repository_understanding`, `bug_fixing`, `refactoring`, `ambiguous_symbol`) with the same
qualitative outcome (found, ranked 8–20) in all of them — too small and too uniform a sample to
support a category-level claim beyond "not obviously category-dependent in this control arm."

## 8. Failure Classification

All 6 bypass-control tasks classified as **B — target in pool, ranked below threshold k=5** (see
§5's table; `diagnose()`'s exact logic in `retrieval_scoring.py`). Zero A (never entered pool),
consistent with this codebase's own prior finding that ARCF's lexical-probe/anchor-classification
fallback layers are relatively strong discovery mechanisms even without entity guidance — and
consistent with `slm1_bypass_experiment.py`'s own historical 11/12-unaffected finding (§1): removing
SLM-1's entities didn't collapse discovery there either.

C/D (SLM-interpretation-quality classes) could not be exercised — no arm with actual SLM output ran.

## 9. Token/Latency Analysis

Not obtainable for the same credential/hardware reasons (§5/§6). The harness records
`slm_prompt_tokens`/`slm_completion_tokens`/`slm_latency_ms`/`slm_attempts`/`slm_malformed_attempts`
per task per arm and is ready to populate them the moment a working arm runs — see
`_aggregate()` in `scripts/semantic_layer_experiment.py`.

**Test suite**, run in full after every change:

- `arcf/` (the production package): **942/942 passed**, unchanged from before this task — confirms
  zero regressions from a change set that touches nothing under `arcf/src/`.
- `benchmark/` (this task's own package): **232/232 passed** — 199 pre-existing + 33 new tests for
  `contract.py`/`interpreter.py`/`adapter.py`/`retrieval_scoring.py`.
- `ruff check` on all new files: clean (`All checks passed!`).

## 10. Regressions

None observed or possible by construction: no file under `arcf/src/` was modified, and the full
942-test `arcf` suite is byte-for-byte the same pass count as this branch's starting point. Nothing
in `benchmark/`'s existing runners/bootstrap/suite code was modified either — only new files were
added.

## 11. What the Experiment Actually Proves

1. **The infrastructure gap is closed, not the empirical question.** A real, tested, swappable
   `SemanticInterpreter` seam now exists, with a framework-independent structured contract, a
   minimal ARCF-DI adapter, reusable Recall@k/MRR/failure-classification metrics, and a 4-arm
   runner — all additive, all reversible, all passing their own tests. This is genuinely new
   capability this codebase didn't have (the closest prior art, `benchmark/`'s Mode B/C runners,
   measures final-answer quality via LLM-judge/grounding-term-overlap, not retrieval rank).
2. **One real number was obtained**: with the semantic layer fully absent, ARCF's deterministic
   fallback discovery found the correct file in 6/6 real tasks against the real `arcf` repository,
   but never ranked it in the top 5 (MRR 0.083). That's a genuine, if narrow, data point about
   *this specific 6-task set's* ranking behavior under zero semantic guidance — not about whether
   a semantic layer would fix it, since no semantic-layer arm could run for comparison.
3. **This codebase's own substantial pre-existing empirical record**, cited in full in §1, already
   bears on the underlying question and predates this task: `slm1_bypass_experiment.py`'s
   11/12-unaffected finding, PROGRESS.md's 8 separately-falsified attempts to close the
   "recall-gap" thread (personalized PageRank, package-specificity pruning, a semantic re-ranker,
   a standing lexical probe, type-graph indexing, qualified-identifier vocabulary extraction — none
   of them semantic-SLM-based, but all targeting the SAME symptom this task is about, and all
   falsified by rigorous same-process ablation), and the explicit prior decision to not pursue
   "SLM-based query expansion." None of this is new evidence produced by this task — it is
   evidence this task located, read in full, and is reporting honestly rather than re-deriving.

## 12. What It Does NOT Prove

- **It does not show a generic SLM would or would not help.** No `current_arcf` or
  `generic_slm_*` arm produced a single real number — every claim in §11 about "the semantic layer"
  is either about zero semantic layer (bypass control) or about this codebase's *own prior*
  experiments, not this task's new harness running live.
- **It does not show the new ARCF-specialized contract/prompt (`LLMSemanticInterpreter`) is better
  or worse than the existing SLM-1 prompt** — `generic_slm_plain` vs `generic_slm_specialized`
  (Step 7's ablation) never ran against each other.
- **It does not validate `is_negative_query` handling** — the field is defined, surfaced, and
  tested at the schema level, but the adapter does not yet special-case it (documented explicitly
  in `adapter.py`), and no negative-query task was included in `tasks.py` to exercise it end-to-end.
- **It does not extend to the repositories most associated with the "Category B ambiguous symbol"
  complaint** (Consul's `agent/cache.New`, 156-way ambiguity) — those repos are unavailable in this
  sandbox; the one new ambiguous-symbol task built here (`save`, 12 definitions/5 files) is real and
  independently verified, but is a much smaller ambiguity than the Consul flagship case and only
  one data point.
- **The 6-task set is far too small for statistical confidence either way** — even with live arms,
  6 tasks (3 of which leak their target path in the query text, per §4) would not have been
  sufficient to support a strong recommendation; this was always going to be a "does the harness
  work and what does the existing record say" delivery, not a statistically powered A/B result,
  given the sandbox's constraints.

## 13. QLoRA Decision

Per the decision tree in the brief: **QLoRA training should NOT be started from this task's own
new evidence**, because no generic-SLM arm produced a result to evaluate against "does the generic
SLM show improvement." That is a **hardware/credential gap in this delivery environment, not a
finding that generic SLMs don't help** — the two must not be conflated, and this report does not
claim the latter.

Separately, and more strongly: **this codebase's own pre-existing empirical record (§1, §11) is not
neutral on the question — it leans toward "semantic interpretation is not the dominant bottleneck"
for the specific failure mode this task is about.** `slm1_bypass_experiment.py` found removing
SLM-1's entities changed almost nothing (11/12 unaffected); the flagship ambiguous-symbol case is
root-caused to Tier-1 entry-point fan-out (a deterministic mechanism); 8 separate attempts to close
the same symptom via non-SLM mechanisms were falsified by rigorous ablation; a semantic re-ranker
specifically was tried and falsified (`arcf_arm2_semantic_reranker_falsified`, byte-identical
packaged output on/off). None of these were QLoRA-specific, but they all targeted "does better
semantic/relevance signal change retrieval outcomes here," and the answer was consistently no.

**Combined recommendation: D — inconclusive from this task's own new run, but NOT an
"investigate QLoRA" signal either.** The responsible next step (§14) is to close the credential/
hardware gap and get ONE real generic-SLM data point using the infrastructure this task built,
before spending anything on QLoRA. If that run reproduces the existing record's pattern (little to
no change vs. bypass/current-ARCF), that would be a second, independent confirmation against QLoRA
investment — consistent with, not contradicting, everything already on record in this codebase.

## 14. Recommended Next Step

1. **Do not start QLoRA work.** Neither this task's own (incomplete) run nor this codebase's
   existing record supports it, and the existing record actively leans against "the semantic layer
   is the bottleneck" for the symptom motivating this task.
2. **Get the one missing data point cheaply, before anything else**: run
   `benchmark/scripts/semantic_layer_experiment.py` (no `--fake-client`) in an environment with
   either (a) an `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` litellm can use for the `current_arcf` arm,
   or (b) a local Ollama daemon with one of `qwen2.5:1.5b-instruct`/`qwen2.5:3b-instruct`/
   `phi3:mini` pulled for the two generic-SLM arms — ideally both, in the same run, since all four
   arms already share one process and one repository state. This is now a single command, not a
   new engineering effort.
3. **If pursuing that further, extend `tasks.py` past today's 6 tasks** — specifically more tasks
   whose query text does NOT leak the target path (only 3/6 today qualify), and, if a
   larger/ambiguity-rich repo becomes available in the run environment (e.g. Consul, matching
   `validate_llm_grounding.py`'s existing flagship case), re-run against that rather than only
   `arcf`'s own smaller, less symbol-ambiguous codebase.
4. **Only if that real run shows a material Recall@5/MRR improvement for `generic_slm_plain` or
   `generic_slm_specialized` over `current_arcf`/`slm_bypass_control`**, revisit the QLoRA decision
   tree — and even then, first separate model-effect from prompt-effect (Step 7's ablation, which
   the harness already supports) before concluding fine-tuning, rather than better prompting, is
   the right lever.
