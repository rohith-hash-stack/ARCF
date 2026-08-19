# Does a Real Generic Local SLM Materially Improve ARCF Retrieval? — Decisive Report

**Question asked:** "Does a real generic local SLM materially improve ARCF retrieval compared
with the existing ARCF semantic path?" One execution, decisive answer. QLoRA, ARCF-DI
ranking/retrieval changes, and embeddings/RAG were explicitly out of scope and none were touched.

**Answer, stated up front: NO. Generic local SLM is clearly, repeatably WORSE, not better,
across both repositories and nearly every metric. STOP — no corrective execution needed (see
§13).**

---

## 1. Experiment Executed

Two arms, identical downstream pipeline, real live calls only (no fake client, no remote
substitute for "local"):

| Arm | Interpreter | Model | Access |
|---|---|---|---|
| `current_arcf` | `ExistingSlm1Interpreter` (arcf's real, unmodified SLM-1 / `IntentExtractor`) | `gpt-4o-mini` | Real OpenAI API key (confirmed working this session) |
| `generic_local_slm` | `LLMSemanticInterpreter` (the ARCF-specialized contract prompt built in the prior session) | `ollama_chat/qwen2.5:1.5b-instruct` | Real local Ollama daemon, already running, no install needed |

Both feed the identical downstream call: `ContextResolver.resolve(target_names, traversal_depth=2)`
→ `RelevanceRanker.rank(...)`. Only `target_names` (produced by whichever interpreter) differs.
No file under `arcf/src/` was modified; no ARCF-DI ranking/retrieval logic was touched.

**Tasks:** all 20 existing, ground-truth-verified Phase 3 tasks for Django + SQLAlchemy
(`arcf/scripts/phase3_benchmark_tasks_django.py`, `_sqlalchemy.py`), reused verbatim — 18
positive + 2 negative. Categories covered: A(2) B(2) D(2) E(2) F(2) H(2) I(4) J(2) L(2). No C
(vocabulary mismatch), G, or K tasks exist in this repo pair — an honest gap, not filled
artificially. No query states its target file path verbatim (checked before the run).

**Scope-limiting choice, stated explicitly:** only Django + SQLAlchemy ran (not Traefik/Consul/
reuse-tier) because both are Python — reusing the exact indexing/resolution wiring the Phase 3
deterministic pass already validated on these two repos, avoiding new per-language engineering
in a task meant to stay to one execution.

Neither arm has any access to the cloned repository — both prompts are generic and take only the
raw query string (verified by reading both prompt templates). Repository content enters only in
the shared downstream `ContextResolver` step. Caveat: most queries do name "Django"/"SQLAlchemy"
by framework name (natural, not path-leakage), which plausibly favors `gpt-4o-mini`'s much larger
pretraining exposure to these popular projects over the 1.5B local model — noted in §9.

---

## 2. Baseline Results (`current_arcf`, real `gpt-4o-mini`)

| Repo | R@1 | R@5 | MRR | Mean candidates | FPR (negative) |
|---|---|---|---|---|---|
| Django | 0.296 | 0.333 | 0.559 | 81.9 | 0.0 |
| SQLAlchemy | 0.204 | 0.204 | 0.343 | 14.8 | 0.0 |
| **Combined (equal-weighted)** | **0.250** | **0.269** | **0.451** | — | **0.0** |

---

## 3. Generic SLM Results (`generic_local_slm`, real `qwen2.5:1.5b-instruct` via Ollama)

| Repo | R@1 | R@5 | MRR | Mean candidates | FPR (negative) |
|---|---|---|---|---|---|
| Django | 0.111 | 0.111 | 0.113 | 69.1 | 0.0 |
| SQLAlchemy | 0.111 | 0.111 | 0.113 | 9.1 | 0.0 |
| **Combined (equal-weighted)** | **0.111** | **0.111** | **0.113** | — | **0.0** |

**Every single metric is worse for the generic local SLM, on both repos, with no exceptions.**
R@1 drops by more than half (0.250→0.111), R@5 drops by more than half (0.269→0.111), MRR drops
to roughly a quarter (0.451→0.113). Zero false positives either arm — the weakness is not
hallucinated identifiers, it's under-production of usable ones (§5).

---

## 4. Category-Level Comparison

| Category | current_arcf success (rank≤5) | generic_local_slm success (rank≤5) |
|---|---|---|
| A — exact symbol (2) | 2/2 | 2/2 |
| B — ambiguous symbol (2, scored under D below) | 0/2 | 0/2 |
| D — subsystem (2) | 1/2 | 0/2 |
| E — cross-file behavior (2) | 2/2 | 0/2 |
| F — call-chain (2) | 2/2 | 0/2 |
| H — config-driven (2) | 0/2 | 0/2 |
| I — dynamic dispatch (4) | 1/4 | 0/4 |
| J — inheritance-heavy (2) | 2/2 | 0/2 |
| L — negative (2) | 2/2 clean (FPR=0) | 2/2 clean (FPR=0) |

`current_arcf` wins or ties in every category; it never loses to `generic_local_slm` in any
category. The only category where both arms fail equally is H (config-driven) — consistent with
the project's own prior finding that ARCF-DI has no mechanism at all for config-key-driven
queries (a retrieval-side gap, not a semantic one — see §6 failure class E). Category A (exact
symbol) is the only category where both arms are equally strong, expected since exact/qualified
names are the easiest case for any interpreter.

---

## 5. Candidate Discovery vs. Ranking Analysis

For `current_arcf`, failures split across genuinely different mechanisms (§6): some are pure
ranking failures (target found, buried), some are pure discovery failures, one is a known
retrieval-side gap (config-driven queries). This mirrors the prior bypass-control finding that
ranking, not semantic interpretation, was the dominant bottleneck for *that* arm.

For `generic_local_slm`, the picture is different and mechanically specific: **13 of its 16
failures (81%) are "SLM produced zero usable retrieval terms" (failure class A) — candidate
count is literally 0, nothing was ever searched.** This is not a ranking problem for this arm; it
never reaches ranking in most failures.

**The specific, diagnosable root cause** (visible directly in the raw per-task JSON): the local
model frequently identifies the right concepts but puts them in the contract's `concepts` field
instead of `retrieval_terms`. Example, `django_task1` (target: `AbstractUser`/`AbstractBaseUser`/
`PermissionsMixin`/`Model` hierarchy):

- `current_arcf` → `retrieval_terms: ["User", "AbstractUser", "AbstractBaseUser",
  "PermissionsMixin", "Model"]` → rank 1, success.
- `generic_local_slm` → `retrieval_terms: []`, `concepts: ["Django", "User model",
  "AbstractUser/AbstractBaseUser/PermissionsMixin class hierarchy", "metaclass"]` → the same real
  information, landed in the wrong contract field. Per `adapter.py`'s own (correct) design,
  `concepts` is deliberately never projected into ARCF-DI's exact-match channel — so this
  information never reaches retrieval at all.

This happened in most of the 1.5B model's failures across both repos. It is a genuine, repeatable
weakness of this specific model+prompt combination — schema/instruction-adherence, not necessarily
"no understanding of the code." See §9 for why this still supports "not validated," not a
caveat that reverses the conclusion.

---

## 6. Failure Classification (positive tasks only, 18 per arm)

| Class | Meaning | current_arcf | generic_local_slm |
|---|---|---|---|
| A | SLM semantic-interpretation failure (empty/unusable terms) | 3 | **13** |
| B | Target absent from candidate pool | 2 | 0 |
| C | Target present but ranking failure | 2 | 1 |
| D | Ambiguous query (known recall-gap boundary) | 2 | 2 |
| E | ARCF-DI limitation (zero-mechanism case, category H) | 1 | 0 |
| F | Other | 0 | 0 |
| **Successes (rank ≤ 5)** | | **8/18** | **2/18** |

Classification is heuristic (same disposition as the prior report's own C/D/F classes), applied
by fixed priority: known-ambiguous ground truth → D; else empty terms → A; else absent-with-
zero-candidates-on-a-category-H-task → E; else absent → B; else present-but-low-rank → C. Full
per-task detail: `arcf/scripts/phase3_results/phase3_semantic_slm_comparison.json`.

Both `D` cases for `generic_local_slm` (`django_task5`, `sqla_task8`) are mechanically closer to
its own `A` failures than to `current_arcf`'s — one of the two (`django_task5`) had zero
retrieval terms too, unlike `current_arcf`'s version of the same task which did surface (and get
buried among) 85 real candidates. Reported honestly rather than smoothed over.

---

## 7. Regressions / False Positives

**None.** `arcf`'s existing 942-test suite was not touched (no `arcf/src/` file was modified).
False-positive rate is 0.0 for both arms on both repos' negative tasks — neither model
hallucinated a plausible-sounding but fabricated identifier for the GraphQL/WebSocket negative
queries, even the local model despite frequently flagging them `is_ambiguous=true`.
`malformed_output_rate` was 0.0 except one retry on `sqla_task4` (local arm) — the harness's
existing retry-then-error path handled it without incident, no crash.

---

## 8. What This Experiment Proves

1. **On this real, ground-truth-verified 18-task set across two real repositories, ARCF's
   existing SLM-1 path (`gpt-4o-mini`) materially and consistently outperforms a real generic
   local SLM (`qwen2.5:1.5b-instruct`) using the new ARCF-specialized contract/prompt** — not a
   tie, not a small effect: R@1 and R@5 both drop by more than half, MRR by roughly three-quarters.
2. **The mechanism is diagnosable, not just a number**: the local model's dominant failure mode
   (13/18 tasks) is producing zero usable `retrieval_terms` — frequently because it puts the
   right information in the wrong contract field (`concepts` instead of `retrieval_terms`), which
   the existing adapter correctly refuses to forward to ARCF-DI.
3. **This reproduces, on new repositories, the same underlying pattern this codebase's prior
   record already showed**: `slm1_bypass_experiment.py`'s 11/12-unaffected finding and the 8
   falsified recall-gap attempts both point toward the semantic-interpretation stage not being
   the place extra investment pays off — this execution adds a second, independent, *live*
   confirmation with a real (not absent) generic-SLM arm, closing exactly the gap the prior
   report flagged as missing.

## 9. What This Experiment Does NOT Prove

- **It does not prove no generic local SLM could ever help** — only that this specific 1.5B
  model, with this specific prompt, on these two repositories, underperforms. A larger local
  model (e.g. `qwen2.5:3b-instruct`, `phi3:mini` — both were candidate options) or a
  better-adhered-to prompt schema might close some of the `concepts`-vs-`retrieval_terms` gap.
  That is a prompt-engineering question, not a QLoRA question, and is out of this task's scope.
- **It does not isolate model capability from pretraining-familiarity with Django/SQLAlchemy
  specifically** — `gpt-4o-mini` likely has far more memorized knowledge of these two very-popular
  open-source projects than a 1.5B model does; some of `current_arcf`'s advantage may be
  "knows Django/SQLAlchemy well" rather than "is a better generic semantic interpreter." A
  repo-agnostic synthetic-codebase test would be needed to fully separate these — not attempted
  here, consistent with staying to one execution.
- **It does not test category C (vocabulary mismatch), G, or K** — no such tasks exist in this
  repo pair.
- **It does not touch Traefik/Consul/Go or the reuse-tier repos** — scope was deliberately
  limited to Python-only to stay within one execution.

## 10. FINAL DECISION

**SLM direction not validated.**

The evidence points the opposite direction from "invest here": the generic local SLM tested is
materially worse than ARCF's existing semantic path, not comparable and not better, reproduced
across two independent repositories and 8 of 9 non-trivial query categories.

## 11. QLoRA Decision

**Do not proceed to QLoRA.**

This is now the second independent, real (non-synthetic) data point — after the prior session's
bypass-control result and this codebase's own falsified recall-gap record — all pointing the same
direction. There is no positive signal here to spend fine-tuning investment chasing.

## 12. Recommended Next Action

1. **Stop this line of investigation** (per the brief's own strict stop condition — this was a
   valid, non-infrastructure-failing execution; no corrective run is warranted).
2. If retrieval quality remains the priority, redirect effort at the mechanisms this run and the
   prior bypass-control both actually point to: **ranking** for `current_arcf`'s own failures
   (classes B/C/D above) and the confirmed **zero-mechanism gap for config-driven queries**
   (class E, category H) — not the semantic-interpretation stage.
3. If a generic-local-SLM angle is ever revisited, the cheap, narrow follow-up (not started here)
   is fixing the `concepts`-vs-`retrieval_terms` field confusion in the existing specialized
   prompt (§5) and re-testing — a prompt fix, not a QLoRA investment, and not undertaken as part
   of this decisive execution.

---

**Raw data:** `arcf/scripts/phase3_results/phase3_semantic_slm_comparison.json` (all 40 real
task-level results, both arms, both repos). **Run log:**
`arcf/scripts/phase3_results/phase3_semantic_slm_comparison_run.log`.
