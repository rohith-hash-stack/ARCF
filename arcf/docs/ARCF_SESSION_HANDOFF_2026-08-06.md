# ARCF Session Handoff — 2026-08-06

**Purpose:** continuity document for starting a fresh context window. Read this first;
it captures everything needed to resume the current work (classifier gap investigation)
without re-deriving the prior session's context.

**⚠️ UPDATE (same day, later context window) — read §9-§13 first, they supersede §7's
"exact next steps" with what's actually in progress right now.**

---

## 1. What this session did (already complete, already tested, already running)

A Principal Architect review requested a 15-point deterministic architecture hardening
of ARCF's Phase 5 (Code Intelligence) / Phase 6 (Context Resolution & Packaging)
pipeline. This was fully implemented, staged, and verified this session:

| Stage | What it added |
|---|---|
| Foundation | `context/task_profile.py` — `RetrievalTaskType` enum, deterministic task classification, per-task traversal depth + ranking weight tables |
| 1 | Adaptive multi-hop traversal (depth 1/2/3/unbounded by task type) replacing fixed one-hop, with per-file justification chains — `code_intelligence/context_resolver.py`, `call_graph.py`, `dependency_graph.py`, `inheritance_graph.py`, `candidate_selector.py` |
| 2 | Symbol disambiguation via locality scoring (same file > same dir > import-graph reachable) — `code_intelligence/reference_resolver.py` |
| 3 | Evidence-sufficiency validation (unconditional, not just on empty results) — new `context/evidence_validator.py`, new authentication/test_execution/ci_explanation evidence contracts in `contracts/evidence_contract.py` |
| 4 | Monorepo/repository-segment awareness — new `workspace/repository_segmentation.py` |
| 5 | Language capability registry + unsupported-file/parse-error/generated-code surfacing — new `code_intelligence/language_coverage.py`, `unsupported_conditions.py` |
| 6 | Task-aware ranking profiles + constructor-preserving compression (a selected method now pulls its class's constructor along so compression never severs it) |
| 7 | Parallel indexing (`ThreadPoolExecutor`, proven byte-for-byte deterministic regardless of worker count) — `code_intelligence/engine.py` |
| 8 | Pipeline reordering (lightweight checks before the expensive parse; short-circuit for fully-unsupported repos) — `code_intelligence/service.py` |
| 9 | TypeScript `tsconfig.json` path-alias resolution + Python `src/`-layout resolution — new `typescript_path_aliases.py`, `python_src_layout.py` |
| 10 | Retrieval-completeness metadata (15 new fields on `ContextResolutionResult`) |
| 11 | Deterministic validation suite — `scripts/hardening_validation_suite.py` (dual-purpose: runnable report + `tests/hardening_validation/`) |

**Result:** 629 passing tests in `arcf/` (up from 533 baseline), 199 unmodified in
`benchmark/`, `ruff`/`mypy --strict` clean across `src/`, `tests/`, `scripts/`.

**Governance:** this work conflicted with the repo's active v2.3 baseline freeze
(`docs/ARCF_V2.3_BASELINE_FREEZE.md`). The user explicitly authorized a **re-scope**
(not a lift) of the freeze for this specific body of work; the addendum is already
written into that file. **Any further new architectural surface (SLM-0, embeddings,
etc.) needs the same explicit re-scoping treatment — don't add it silently.**

One incidental bug fix, unrelated to the hardening work: `benchmark/src/benchmark/repository.py`'s
`RepositoryLoader.clone()` used a plain `shutil.rmtree()` that fails on Windows against
read-only git pack files (WinError 5). Fixed by reusing the `_force_rmtree` pattern
already established in `benchmark/src/benchmark/suite/repo_pool.py`. Already applied,
tested, and verified working (fastapi clone succeeded after the fix).

## 2. Environment / how to resume

- Two apps, two separate `.venv`s: `arcf/` (the API + pipeline) and `benchmark/` (the
  comparison harness + UI), the latter depends on the former via an **editable** path
  install (`arcf = { path = "../arcf", editable = true }` in `benchmark/pyproject.toml`)
  — confirmed via the `.pth` file, so any source edit under `arcf/src/` is live for
  `benchmark/` immediately, but **only after restarting its server process** (no
  `--reload`, Python caches imports for the process lifetime).
- Dev server configs already exist in `.claude/launch.json` (workspace root, i.e.
  `C:\Users\VasiganiRohitBabu\Desktop\Claude\.claude\launch.json`):
  - `arcf-api` — port 8000, Swagger docs at `/docs`. Wired with `--env-file` pointing at
    `arcf/.env` (already contains working `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` — do not
    print or duplicate these values in any doc/chat; the file is already `.gitignore`d).
  - `arcf-benchmark` — port 8010, the comparison UI (repository load, task prompt,
    Direct/ARCF/Both/All-three modes, provider/model picker, execution history with
    real SQLite-backed persistence that survives server restarts).
  - Launch via the Browser preview tool: `preview_start` with `{"name": "arcf-benchmark"}`
    (or `arcf-api`). **Never launch these via raw Bash/uvicorn — always use the preview
    tool**, per this environment's own instructions.
- **Real LLM calls cost real money.** A "Direct + ARCF" run against the 224-file `arcf`
  repo cost ~$17-18 in one earlier test (Direct LLM alone sent 101k+ input tokens). A
  double-submit accident in this session cost ~$34 in one go. Confirm scope/cost with
  the user before triggering benchmark runs, and watch for double-submission (check
  `/api/executions` execution count before and after a click, not just page state).

## 3. The core problem being tracked (not yet fixed — awaiting user's test batches)

**Symptom, evidenced with real data, not assumed:** for certain query *shapes*, ARCF
returns zero candidate files even when the repository clearly contains relevant code.
Confirmed via real benchmark execution history (`/api/executions` on the running
`arcf-benchmark` app) — e.g. two real runs of `"How are dependencies injected?"`
against a freshly-cloned `fastapi` repo both returned `selected_files: []`, and the
final LLM correctly reported "no file context was provided."

**Root cause, traced through actual code, not guessed:**
1. `target_names` for `ContextResolver.resolve()` come from `UserIntent.entities`
   (SLM-1's own extraction). A conceptual question like "How are dependencies
   injected?" names no concrete symbol, so SLM-1 extracts nothing, and symbol-based
   resolution legitimately finds nothing.
2. The fallback (`context/evidence_fallback.py`'s `expand_with_evidence`) only fires
   when `RepositoryScopeClassifier.classify(raw_request)` returns `repository_scope=True`.
   That classifier (`contracts/repository_scope_classifier.py`) requires a documentation
   verb (`explain`/`document`/`describe`/`summarize`) to **co-occur** with a repository
   noun (`repository`/`repo`/`codebase`/`project`/`test suite`). "How are dependencies
   injected?" has neither, so `repository_scope=False`, and the fallback never runs.
3. This session's own new evidence-validator (`context/evidence_validator.py`, Stage 3)
   also checks `detect_task_type_for_evidence()` (CI/test-execution/authentication
   keyword lists) — none match this phrasing either, so that path is also a no-op.
4. End state: every deterministic path comes back empty. ARCF correctly refuses to
   fabricate context rather than guessing — this is working as designed, just too
   conservatively for this query shape.

**Verified this is not "every query on every new repo"** — pulled real execution
history and found `arcf` (18 files) and `qa-workplace-playwright-rcz` (11-13 files,
multiple prompts) both worked correctly. The zero-result cases all fit the same
diagnosed pattern above, not a general regression.

## 4. Proposed layered fix (discussed, NOT yet implemented — user has not given go-ahead)

In priority order, cheapest/safest first:

1. **Remove the AND-condition for explanation verbs.** `RepositoryScopeClassifier`
   already has precedent for this: debugging phrases (`"help me debug"`) don't require
   a co-occurring repository noun, because the classifier's own docstring argues this
   tool has no other plausible subject for a debugging request. The same argument
   applies to explanation verbs (`explain`/`describe`/`summarize`/`document`) — they
   almost never mean anything else in this context either. This is a **structural** fix
   (removes an unnecessary requirement) not a keyword-list expansion, so it closes an
   entire class of phrasing permanently, not just one example.
2. **Decouple query-referenced file matching from the scope gate.** `expand_with_evidence`'s
   tier 1 (regex-extracts filenames/paths/quoted tokens from the raw request and matches
   them against real scanned files) is currently gated behind the same
   `classification.repository_scope` boolean as the broader evidence-category tier. There's
   no reason for this — if the user's literal words match a real filename, that's a safe,
   cheap, precise signal that should run unconditionally, independent of whether the
   classifier recognizes the query shape.
3. **Deterministic lexical/stemmed symbol probing** (not yet designed in code, discussed
   only) — tokenize the raw query, strip stopwords, substring-probe each token against
   `SymbolIndex.find_by_name`/filenames regardless of classifier verdict. Concretely
   would have caught the fastapi case: `"depend"` is a literal substring of `Dependant`/
   `Depends`.
4. **Bounded SLM-0 term-expansion** (fully designed in a separate architecture review
   this session, NOT started) — a small local model that only proposes candidate terms
   (e.g. `{"related_terms": ["Depends", "Dependant", "solve_dependencies"]}`), filtered
   deterministically against the real symbol index before ever being used, feeding the
   *existing* `target_names` channel — never choosing files, never ranking, never picking
   retrieval strategy. Schema should be minimal: **only** `related_terms: list[str]`,
   hard-capped in code (not just prompted), regex-validated to look identifier-shaped.
   Explicitly do NOT add `concepts`, `architectural_domains`, or `search_strategy` fields
   — the last one in particular is the model making a retrieval-strategy decision, which
   crosses the line this whole design is trying to stay inside of. Needs the same
   structural enforcement PRHL has (import-graph test proving it can never reach
   `RelevanceRanker`/`SymbolRangeCompressor` directly) — last-resort tier only, tried
   after symbol resolution AND evidence contracts both come back empty.
5. **The embeddings question — explicitly unresolved, deliberately deferred.** Four
   options discussed: (A) hard no, (B) a structurally separate opt-in "fuzzy mode" never
   imported by the core pipeline (same isolation pattern as PRHL, applied at package
   level), (C) embeddings for re-ranking an already-deterministically-selected candidate
   set only, never for discovering new files, (D) defer the decision entirely until
   layers 1-4 are measured and a real residual gap is sized. Recommendation given: **D
   now**, and **B, not C**, if a fallback position is ever needed — C sounds narrower but
   normalizes embeddings living inside the core pipeline, which is a harder line to hold
   over time than a package-level boundary. Do not add an embedding index without an
   explicit, conscious decision — it directly contradicts the freeze doc's "no embeddings,
   no vector database" prohibition and is the one change in this whole line of discussion
   that would actively erase ARCF's differentiation rather than build on it (see §5).

**Important clarification already established:** none of the above is "training" the
classifier. `RepositoryScopeClassifier` stays hand-written, deterministic, PR-reviewable
keyword logic throughout layers 1-3. Batches of test queries are a **measurement/
regression suite** (same role as `benchmark/suites/*.json` and
`hardening_validation_suite.py`), not training data for a learned model. Layer 4 (SLM-0)
and the embeddings question are the only points where a model enters the retrieval
*decision* path at all, and both are still unresolved/undecided.

## 5. Why this matters beyond just fixing one query — the differentiation argument

Separately reviewed this session: a large "evolve ARCF into a repository-agnostic
context intelligence system" proposal. Conclusion: most of what was proposed already
exists in ARCF today (repository intelligence graphs, evidence expansion, budget
packaging). The two genuinely novel/at-risk pieces were an embedding index (directly
contradicts stated philosophy — see §4.5) and a local transformer choosing "retrieval
strategy" (a retrieval decision, not vocabulary expansion — same concern as the
`search_strategy` field above).

What's actually differentiated about ARCF versus prior art (Aider's repo-map is the
closest existing analog — deterministic graph ranking, no embeddings; Sourcegraph SCIP
is the heavier-weight version of the symbol/xref graph; Cursor/Copilot are the
embedding-based baseline to benchmark against): full causal justification chains per
file (not just a similarity score), task-type-aware deterministic ranking chosen by a
classifier not a model, evidence-sufficiency contracts with an explicit
satisfied/missing report, and a structurally-provable (not just documented) trust
boundary between SLM output and file selection. **Adding embeddings as a load-bearing
retrieval mechanism erases most of this differentiation**, not because embeddings are
bad, but because it moves ARCF into an extremely crowded category it can't win on
retrieval-quality-alone against much better-funded competitors.

## 6. Cross-repo generalization — read this before interpreting Batch 2

The classifier fix (layers 1-2 above) is **text-only** — it never inspects the target
repository, so its trigger behavior is identical regardless of which repo a query is run
against. But **retrieval result quality is inherently repo-dependent**: it depends on
what symbols/files/evidence actually exist in that specific repository — its dominant
language (only Python/TypeScript/JavaScript/Java/Go/C#/Kotlin have registered analyzers;
Rust and others are unsupported today), whether it has CI config at all, how consistently
it names things, whether it's a monorepo (segment-boundary filtering from Stage 4 can
legitimately narrow results). **A query that triggers correctly and finds good files on
Repo A but returns fewer/no files on Repo B for the same phrasing is not automatically a
regression** — check whether Repo B actually has the evidence categories / symbols /
language support the query needs before concluding the classifier fix didn't generalize.

## 7. Exact next steps (agreed plan, not yet executed)

1. **User provides Batch 1**: realistic queries across multiple different git repos.
2. Run each through the current (unmodified) pipeline via the `arcf-benchmark` UI or a
   scripted equivalent; for each, record: repo, exact prompt, `selected_files` count,
   and — for zero-result cases — which specific mechanism should have caught it (symbol
   resolution? evidence contract? classifier trigger?) per the diagnostic method in §3.
3. For each genuine gap found, propose the specific deterministic fix (§4, layers 1-3
   first) **and get explicit go-ahead before touching code** — this session's established
   working pattern has been: investigate and report findings, implement only when asked.
4. Implement the agreed fixes, re-run Batch 1, confirm the fixes closed those cases
   without regressing `arcf`'s own 629+199 passing tests.
5. Run **Batch 2** (held out, similar-shaped queries across the same/different repos) as
   validation — per §6, expect the *trigger* to generalize; investigate any *result*
   differences against what actually exists in that repo before calling it a bug.
6. Revisit the SLM-0 and embeddings questions (§4.4-4.5) only if a real, measured
   residual gap remains after layers 1-3 — not before.

---

## 9. Batch 1 — the user's actual test queries (received, in progress)

The user provided **Batch 1**: 50 realistic queries across **30 real public repositories**
(Kubernetes, React, Next.js, VS Code, PyTorch, TensorFlow, FastAPI, Django, Flask,
SQLAlchemy, Redis, PostgreSQL, LLVM, Linux Kernel, Rust compiler, Go, CPython, Node.js,
Nginx, DuckDB, ClickHouse, Apache Spark, Ray, LangChain, vLLM, Ollama, Hugging Face
Transformers, Apache Airflow, Home Assistant, OpenTelemetry Collector, Grafana,
Prometheus, Elasticsearch, Apache Kafka, Apache Superset), spanning summarization,
execution tracing, internals explanation, debugging, refactoring, feature implementation,
performance, and architecture query shapes.

**The full query text for every repo is already transcribed into
`scripts/batch1_diagnostic.py`'s `QUERIES` dict — do not ask the user to re-paste the
batch, it's already captured in code.** GitHub URLs (needed for cloning, not stored in
the script) map to the script's `repo-key` values as follows:

| repo-key | GitHub URL |
|---|---|
| kubernetes | https://github.com/kubernetes/kubernetes |
| react | https://github.com/facebook/react |
| nextjs | https://github.com/vercel/next.js |
| vscode | https://github.com/microsoft/vscode |
| pytorch | https://github.com/pytorch/pytorch |
| tensorflow | https://github.com/tensorflow/tensorflow |
| fastapi | https://github.com/fastapi/fastapi |
| django | https://github.com/django/django |
| flask | https://github.com/pallets/flask |
| sqlalchemy | https://github.com/sqlalchemy/sqlalchemy |
| redis | https://github.com/redis/redis |
| postgres | https://github.com/postgres/postgres |
| llvm | https://github.com/llvm/llvm-project |
| linux | https://github.com/torvalds/linux |
| rust | https://github.com/rust-lang/rust |
| go | https://github.com/golang/go |
| cpython | https://github.com/python/cpython |
| node | https://github.com/nodejs/node |
| nginx | https://github.com/nginx/nginx |
| duckdb | https://github.com/duckdb/duckdb |
| clickhouse | https://github.com/ClickHouse/ClickHouse |
| spark | https://github.com/apache/spark |
| ray | https://github.com/ray-project/ray |
| langchain | https://github.com/langchain-ai/langchain |
| vllm | https://github.com/vllm-project/vllm |
| ollama | https://github.com/ollama/ollama |
| transformers | https://github.com/huggingface/transformers |
| airflow | https://github.com/apache/airflow |
| home-assistant | https://github.com/home-assistant/core |
| opentelemetry-collector | https://github.com/open-telemetry/opentelemetry-collector |
| grafana | https://github.com/grafana/grafana |
| prometheus | https://github.com/prometheus/prometheus |
| elasticsearch | https://github.com/elastic/elasticsearch |
| kafka | https://github.com/apache/kafka |
| superset | https://github.com/apache/superset |

**User's explicit execution protocol (confirmed, do not deviate without asking):**
process repos **one at a time** — clone, run its queries, record results, **delete the
clone**, move to the next. Keep a running results log across the whole batch. Propose
fixes for genuine gaps found, get a quick go/no-go, then continue — this is not a "hold
all fixes to the end" workflow, it's "test → diagnose → fix if agreed → continue."

## 10. Tooling already built for this (working, verified)

- **`scripts/batch1_diagnostic.py`** — cheap, no-final-LLM-call diagnostic runner. Real
  SLM-1 intent extraction (`IntentExtractor`, small/cheap real cost, ~$0.001-0.005/query)
  + the real deterministic `CodeIntelligenceContractService.attach_code_intelligence()`
  pipeline, exactly as production runs it. **Never** calls a final-generation LLM, so it
  never sends a whole repo as context — this is what makes it safe to run ~50 queries
  across 30 repos without the financial risk the benchmark UI's "Run Benchmark" flow has
  (see §2's cost warning — that flow cost ~$34 in one earlier double-submit accident).
  Usage:
  ```
  uv run python scripts/batch1_diagnostic.py --repo-key <key> --repo-path <path>
  ```
  Appends one Markdown table row per query to `docs/BATCH1_RESULTS.md` (auto-created).
  Verified correct against a known-good case before trusting its output: a query naming
  a concrete function (`"Fix the bug in the authenticate() function"`) correctly extracts
  `entities=['authenticate()']`; a conceptual question extracts `entities=[]` — matches
  the already-diagnosed root cause exactly, so this is real SLM-1 behavior, not a script
  bug.
- **`docs/BATCH1_RESULTS.md`** — the running results log (git-ignored? **check** — it's
  new, may need `git add` explicitly later; not committed either way, no commits made
  this session). Currently has 2 rows (fastapi smoke test, see §11).
- **Windows git note learned this session**: shallow-cloning very large repos (tried on
  Kubernetes) can fail with `Filename too long` on Windows's default 260-char path limit
  even when the clone itself succeeds — checkout fails partway. Fix: pass
  `-c core.longpaths=true` to the clone command (scoped per-command, not global config):
  ```
  git -c core.longpaths=true clone --depth 1 <url> <dest>
  ```

## 11. Batch 1 status as of context handoff

| Repo | Status | Notes |
|---|---|---|
| fastapi | **Smoke-tested** (2 rows in `BATCH1_RESULTS.md`) | Used the already-existing clone at `C:\Users\VasiganiRohitBabu\Desktop\Claude\.benchmark_repos\fastapi` (from earlier benchmark-UI testing) rather than a fresh clone-per-protocol — results are still valid (same repo state), but if strict protocol adherence matters, re-run properly. Both queries got `entities=[]`, `candidates=0` — matches the already-known classifier gap, not new information. |
| kubernetes | **Blocked — crashed indexing, not the classifier issue** | See §12. Clone was left in the **session-specific scratchpad**, which will **not** survive into a new session — treat it as gone, re-clone if needed (command in §12). |
| all other 28 repos | **Not started** | |

## 12. New finding this session: systemic recursion bug in ALL SIX language analyzers

Indexing Kubernetes crashed with `RecursionError: maximum recursion depth exceeded`
inside `GoLanguageAnalyzer._visit`/`_visit_children`
(`src/code_intelligence/languages/go_analyzer.py:209,213`). Root cause: the AST walker
recurses directly (`self._visit_children(node, ...)` calling `self._visit(child, ...)`
calling `self._visit_children(...)` again) with **no depth guard and no iterative
fallback**. Our existing Go test fixtures are all small/shallow synthetic snippets, so
this never surfaced before — real Kubernetes Go files (generated deepcopy code, deeply
nested switch/struct definitions) are exactly the shape that trips it.

**Confirmed via a quick read-only grep (already done, don't redo) that this is systemic,
not Go-specific**: all six language analyzers use the same plain-recursive pattern with
no depth protection —
`typescript_analyzer.py:124,188`, `java_analyzer.py:98,143`, `csharp_analyzer.py:101,146`,
`kotlin_analyzer.py:99,149`, `go_analyzer.py:209,213` all have `_visit`/`_visit_children`;
`python_analyzer.py:98` has a self-recursive `_walk` instead, same pattern under a
different name. **This means any of the six languages can crash indexing given a
sufficiently deep/complex real-world file** — expect this to recur on other Go-heavy
repos in the batch (Prometheus, OpenTelemetry Collector, Ollama, Grafana's backend),
possibly TypeScript-heavy ones (React, Next.js, VS Code), Elasticsearch (Java), and
conceivably deeply-nested generated Python.

**Two fix options were presented to the user, no decision made, nothing implemented:**
1. Quick: `sys.setrecursionlimit(N)` — cheap but risky, just delays the crash further and
   risks an uncatchable native stack overflow instead of a clean `RecursionError`.
2. Correct: convert the recursive walk to an iterative, explicit-stack-based traversal —
   removes the depth limit entirely (bounded by heap, not call stack). Right fix, but
   touches core parsing logic in all six analyzers, each with substantial existing test
   coverage (24-119 tests per language) that needs to keep passing.

**This is the first decision point for the new session**: which fix approach, and
whether to fix all six analyzers preemptively or just Go (since Go is the one that's
actually blocked right now) and handle others reactively as they're hit.

To resume Kubernetes testing once a fix is in place:
```
git -c core.longpaths=true clone --depth 1 https://github.com/kubernetes/kubernetes.git <scratchpad>/kubernetes
uv run python scripts/batch1_diagnostic.py --repo-key kubernetes --repo-path <scratchpad>/kubernetes
```
(then delete the clone per protocol, per §9).

## 13. Expected pattern for the language-unsupported repos in this batch

Independent of both the classifier gap (§3) and the recursion bug (§12): these repos'
**dominant** language has no registered `LanguageAnalyzer` at all (only Python,
TypeScript/JavaScript, Java, Go, C#, Kotlin are supported today) — expect the Stage 8
short-circuit path (`languages_unsupported` populated, `candidate_files` likely 0 or
near-0 regardless of query phrasing) for: **redis, postgres, llvm, linux, nginx, duckdb,
clickhouse** (all C/C++), **rust** (the compiler itself, Rust), **kafka, spark** (Scala),
and **cpython**'s core interpreter specifically (C — though CPython's repo also has a
large pure-Python stdlib, so this one may be a genuine mixed-language partial-success
case, worth checking rather than assuming). **node** (Node.js) is similar — V8 itself is
C++, but `lib/*.js` is real JavaScript, so expect a mixed/partial result there too, not a
clean unsupported short-circuit. Don't mistake these for new classifier-gap findings —
tag them as "language coverage gap" in the results log, separate from "classifier gap"
and "recursion crash," so the three failure categories don't get conflated when
reporting back to the user.

## 8. Files touched/added this session (for quick re-orientation)

Run `git status --short` in both `arcf/` and `benchmark/` for the current diff. Key new
files in `arcf/`: `src/context/task_profile.py`, `src/context/evidence_validator.py`,
`src/workspace/repository_segmentation.py`, `src/code_intelligence/language_coverage.py`,
`src/code_intelligence/unsupported_conditions.py`,
`src/code_intelligence/typescript_path_aliases.py`,
`src/code_intelligence/python_src_layout.py`, `scripts/hardening_validation_suite.py`,
`tests/hardening_validation/`. Modified: `src/code_intelligence/{context_resolver,
call_graph,dependency_graph,inheritance_graph,candidate_selector,engine,service,
symbol_index,reference_resolver,index}.py`, `src/context/{packager,relevance_ranker}.py`,
`src/contracts/evidence_contract.py`, `src/domain/{context_resolution,context_package}.py`,
`src/interfaces/api/routes/context_package.py`, `docs/ARCF_V2.3_BASELINE_FREEZE.md`
(re-scope addendum), `pyproject.toml` (pytest/mypy path additions for `scripts/`). In
`benchmark/`: `src/benchmark/repository.py` (the WinError 5 fix). Nothing has been
committed to git this session — all changes are working-tree only.
