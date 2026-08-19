# Phase 3 Deterministic-Only Pass — Aggregate Report

**Date:** 2026-08-17
**Scope:** Step 1 of `docs/ARCF_RETRIEVAL_BENCHMARK_PLAN_2026-08-17.md` §7 — deterministic-only
retrieval metrics (no LLM calls, no generated artifact, no composite grounding score). 7
repositories, 3 parallel passes. This report synthesizes the three passes' own per-repo
summaries; it does not re-run anything.

**Source data:** `docs/phase3_retrieval_benchmark/phase3_deterministic_django_sqlalchemy_summary.md`,
`docs/phase3_retrieval_benchmark/traefik_consul_deterministic_summary.md`,
`scripts/phase3_results/phase3_reuse_tier_summary.md`, plus their accompanying raw JSON files.

---

## 1. Methodology Notes & Inconsistencies (read this before trusting any number below)

Three independent passes ran in parallel with the same instructions but converged on
different implementation choices in two places. Both are named honestly rather than smoothed
over:

- **Resolver coverage differs by pass.** Traefik/Consul ran **both** classic and DRP resolvers
  for every task (18 tasks × 2 = 36 resolve calls). Django/SQLAlchemy and the reuse-tier pass
  ran **classic only**. Any classic-vs-DRP comparison in this report is therefore Traefik/Consul
  only — it is not a 7-repository comparison, and should not be read as one.
- **Negative-query (category L) false-positive measurement is confounded on the Traefik/Consul
  pass specifically.** All three passes needed a deterministic substitute for SLM-1's real
  (LLM-based, therefore banned in this deterministic pass) entity extraction. The Traefik/Consul
  substitute pulled the repository's own name (e.g. "Traefik") out of query text alongside the
  genuinely-fabricated term, and that repo-name token legitimately resolves to real files —
  producing `false_positive_confident_match=True` on both of that pass's negative tasks even
  though, per that agent's own isolation check, no candidate file in either task actually relates
  to the fabricated term. The other two passes' substitutes did not exhibit this artifact (6/6 of
  their negative tasks report clean `false_positive=False`). **Net: negative-query FPR is 0/6
  clean and 2/2 confounded-not-genuine on Traefik/Consul** — do not report a single blended FPR
  number across all 8 negative tasks; the two subsets aren't measuring the same thing.
- **Two `.benchmark_repos/` locations now exist.** `Claude/.benchmark_repos/` (repo root, one
  level above `arcf/`) is the older location, hardcoded as `validation_breadth_matrix_check.py`'s
  `BENCHMARK_ROOT`, holding the clones that produced the 2026-08-12 checkpoint numbers.
  `arcf/.benchmark_repos/` is new, created by this pass's three agents per their own
  instructions. Both now exist; nothing conflicts today, but they should be reconciled to one
  canonical path before Phase 4/5 build further on top of this.
- **All results in this report are n=1 (single-run).** Per plan §11, none of these numbers have
  been statistically tested — they describe one deterministic run each, not a distribution.

---

## 2. Per-Repository Headline (classic resolver, where isolatable)

| Repo | Lang | Tasks | Mean R@1 | Mean R@5 | Mean MRR | Notes |
|---|---|---|---|---|---|---|
| Traefik | Go | 9 | 0.479 | 0.625 | 0.653 | New ground truth |
| Consul | Go | 9 (6 existing + 3 new) | 0.062 | 0.562 | 0.346 | Zero ground-truth drift confirmed |
| Django | Python | 10 | 0.352 | 0.574 | 0.601 | 3 category-J (inheritance) tasks |
| SQLAlchemy | Python | 10 | 0.370 | 0.426 | 0.690 | 3 category-I (dynamic-dispatch) tasks |
| Flask | Python | 2 new + regression | — | — | — | Regression: 0.857→0.857, reproduced |
| spring-petclinic | Java | 2 new + regression | — | — | — | Regression: 0.5→0.5, reproduced exactly |
| vLLM | Python+Rust | 2 new + regression | — | — | — | Regression: 0.667→0.333, **did not reproduce** |

**A striking, repo-independent result: Consul — ARCF's most-tuned repository — has the*worst*
classic Recall@1 of the five repos with a full task set (0.062).** This is driven heavily by
`existing_task1_targeted_logic` (`Catalog.Register`) scoring 0.0 on both resolvers despite being
one of the project's own original, hand-verified ground-truth tasks — flagged for follow-up, not
explained by this pass.

---

## 3. Per-Query-Category Aggregate (classic resolver, all repos combined, task-level)

Computed directly from the raw per-task tables across all three passes (not from pre-averaged
repo-level means, to avoid double-weighting):

| Category | n tasks | Mean R@1 | Notable |
|---|---|---|---|
| A — exact symbol | 5 | **0.200** | Only Traefik's task scored non-zero (1.0); the other 4 (2× Consul, Django, SQLAlchemy) all scored 0.0 |
| B — ambiguous symbol | 5 | **0.000** | **Every single category-B task, across all 5 repos tested, scored zero under classic resolution.** See §5. |
| C — vocabulary mismatch | 1 | 1.000 | Only one C task exists across the whole benchmark — too small a sample to generalize |
| D — subsystem | 4 | 0.500 | |
| E — cross-file behavior | 6 | 0.333 | |
| F — call-chain | 5 | 0.133 | |
| G — exception/error propagation | 0 | — | **No repo produced a genuine G task this round — a real coverage gap** |
| H — config-driven behavior | 4 | 0.375 | Mean hides a qualitatively worse outlier — see §6 |
| I — dynamic dispatch | 6 | 0.472 | Second-best category after C's single-sample outlier |
| J — inheritance-heavy | 2 | 0.333 | Only Django tested this category this round |
| K — diffuse structure | 0 | — | **No repo produced a genuine K task this round — a real coverage gap** |
| L — negative | 8 | n/a (FPR, see §1) | 6/6 clean, 2/2 confounded (Traefik/Consul artifact) |

---

## 4. Classic vs. DRP Recovery (Traefik/Consul only — the only pass that tested both)

| Repo | Classic mean R@1 | DRP mean R@1 | Classic mean confidence | DRP mean confidence |
|---|---|---|---|---|
| Traefik | 0.479 | 0.417 | 0.907 | 0.149 |
| Consul | 0.062 | 0.188 | 0.889 | 0.089 |

- **DRP helped materially on Consul** (3× classic's recall) and **slightly hurt on Traefik**. Not
  a clean "DRP is better/worse" story — matches this project's own prior finding that DRP's value
  is query- and repo-dependent, not universal.
- **Confidence values are never comparable across resolvers, and the raw numbers make that
  concrete, not just theoretical**: DRP's confidence is consistently far lower than classic's
  across every single task in this pass (e.g. Traefik task2: classic 1.00 vs. DRP 0.02, both on
  the *same* underlying query) — a direct, real illustration of why the G9 freeze record
  (`docs/ARCF_ARCHITECTURE_FREEZE_2026-08-17.md` §6) insists these two formulas must never be
  thresholded or compared as the same measurement. A hypothetical consumer that did compare them
  raw would conclude DRP is dramatically less confident than classic on nearly every task, which
  is an artifact of the two different formulas, not a real confidence signal.
- **DRP rescue rate on the flagship ambiguous case**: both of Consul's and Traefik's category-B
  tasks (`existing_task5_ambiguous_common_name`, `traefik_task2_retry_new_ambiguous`) went from
  classic R@1=0.0 to DRP R@1=1.0 — a real, measured rescue, consistent with DRP's designed
  purpose as the recovery strategy.

---

## 5. Known-Boundary Confirmation — the single most consistent finding of this pass

Every category-B (ambiguous symbol) task in this benchmark, across five different repositories
and two languages, scored **classic Recall@1 = 0.0**:

- `django_task5_ambiguous_save` (Python)
- `sqla_task8_ambiguous_process` (Python)
- `traefik_task2_retry_new_ambiguous` (Go)
- `existing_task5_ambiguous_common_name` / Consul (Go)
- `vllm_generate_ambiguous` (Python)

This is the already-closed, 8-times-falsified ambiguous-name recall boundary
(`[[arcf_recall_gap_closed]]`), now independently reproduced on **4 repositories it had never
been tested against before** (Django, SQLAlchemy, Traefik, vLLM — only Consul had prior
exposure). Where DRP recovery was tested against this exact failure mode (Traefik, Consul), it
rescued the result to R@1=1.0 in both cases. Where DRP was not tested (Django, SQLAlchemy, vLLM),
whether recovery would have helped is unknown, not zero — a real, cheap follow-up for whoever
continues this benchmark.

**This is reported as confirmation of a known boundary, not a new discovery**, per the plan's own
§0 instruction — but the breadth of confirmation (5 repos, 2 languages, 100% failure rate under
classic resolution) is itself a new, useful data point: the boundary is not Consul-specific or
Go-specific, it is a general property of ARCF's current lexical/graph-based symbol resolution.

---

## 6. Real Findings Beyond the Known Boundary

1. **ARCF has no mechanism at all for config-key-driven queries.** `petclinic_database_config`
   (category H, "how is the database connection configured") resolved to **zero candidates** —
   not a ranking failure, not an ambiguity-decay failure, a complete absence of any matching
   mechanism. The other 3 category-H tasks scored 0.0/0.5/1.0 (partial success), so this is a
   qualitatively distinct, more severe failure mode than the category's 0.375 mean suggests.
2. **vLLM's fallback ratio did not reproduce** (0.667 → 0.333) across a ~9-day gap between
   clones, driven by real repository growth (files 6,429→6,599, symbols 59,353→61,302). This is
   evidence that any future benchmark comparison on a fast-moving repository needs a pinned
   commit, not a floating branch reference — flagged for Phase 4/5.
3. **Consul's own classic Recall@1 (0.062) is the worst of any fully-tested repo**, despite being
   ARCF's most-tuned benchmark target. Not explained by this pass — a real candidate for
   follow-up investigation before Phase 4/5 proceeds much further.
4. **Neither D1 nor D2 (freeze doc §5) was directly triggered** in this pass — no repo's file
   count approached the `RepositoryScanner` 20,000-file cap closely enough to test D2 (Django,
   the largest, used ~35%), and no task's traversal depth/fan-out was large enough to exercise
   D1's layer-materialization gap. Both remain genuinely untested by empirical data, not
   incidentally cleared — Phase 5 is still the right place to attack them deliberately.
5. **Case-B (evidence-insufficient recovery trigger) fired twice**, both on dynamic-dispatch
   (category I) tasks with partial evidence coverage (`sqla_task7`, evidence completeness 0.4;
   `consul_task7`, evidence completeness 0.8) — both real, not fabricated. Case-C could not be
   measured anywhere in this pass, correctly, since no generation step ran (Case-C is defined
   against a real generated artifact's grounding, which requires an LLM call).

---

## 7. What This Report Does Not Cover

Per the plan's own gating (§7, step 2): no composite grounding score, no `G_struct`/`G_behav`
split, no unsupported-reference rate, no generated-answer recall — all of these require a real
LLM call and are the next, separately-gated step (Phase 3's LLM-judged pass), not run here.
Category G (exception/error propagation) and K (diffuse structure) have zero task coverage this
round — a real gap for whoever extends this benchmark next, not silently filled in.
