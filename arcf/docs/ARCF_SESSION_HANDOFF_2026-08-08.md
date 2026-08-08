# ARCF Session Handoff — 2026-08-08

**Purpose:** continuity document for starting a fresh context window. Read this first;
it captures everything needed to resume without re-deriving this session's context.
Supersedes `ARCF_SESSION_HANDOFF_2026-08-06.md` for anything it overlaps with (that
doc's Batch 1/recursion-bug tracking is still open and NOT touched this session — see
§6 for status).

---

## 1. What this session did — stable pipeline fixes (all implemented, tested, verified)

Four real bugs found and fixed in ARCF's Phase 5/6 retrieval-and-packaging pipeline,
each discovered via live testing against real public repos (flask, fastapi), not
synthetic cases:

| # | Bug | Fix | File(s) |
|---|---|---|---|
| 1 | A conceptual query with no named entity (e.g. "explain how context locals work") never tried lexical-probe recovery once `expand_with_evidence`'s generic evidence-contract categories had already produced *any* (irrelevant) candidate files — the ordering silently preferred a weak generic signal over a stronger, more specific one that never got a chance to run. | Re-gated lexical symbol probing on whether the *original* exact-symbol resolution was empty, not on whatever the generic evidence-fallback ended up finding. Merges additively — never drops what evidence-fallback already found. | `code_intelligence/service.py` |
| 2 | `MemoryError` crash: a symbol with a self-referential call edge (e.g. `super().same_name()` an imprecise resolver links to itself) seeded `CallGraph._layered_bfs`'s frontier with the start node itself, so `ContextResolver._chain_for`'s parent-pointer walk looped forever appending the same node. Reproduced for real: 555s hang then crash resolving one symbol (`ScriptInfo.make_context`) in a 236-file flask checkout. | Root-cause fix: exclude `start` from `_layered_bfs`'s own initial frontier (mirrors the `neighbor != start` guard already applied to every later hop). Defense-in-depth: added a cycle guard (`seen` set) to `_chain_for`'s walk regardless. | `code_intelligence/call_graph.py`, `code_intelligence/context_resolver.py` |
| 3 | Lexical-probe recovery (bug 1's fix) could match up to 20 loosely-related symbol names off one query and expand each at the same depth a *confident* exact-name match gets, compounding uncertainty into token/latency blowup — up to 262K tokens on a real fastapi query (worse than Direct LLM). | Fixed depth for lexical-probe-recovery expansion (`_LEXICAL_PROBE_RECOVERY_DEPTH = 1`), deliberately shallower than a confident match's task-derived depth. | `code_intelligence/service.py` |
| 4 | **Evidence-preserving context packaging** (the significant one): `ContextBudgetManager` only ever compressed a file when it didn't fit the remaining token budget — never based on *how confident the match was*. A lexically-probed symbol living inside a large, otherwise-unrelated file (e.g. `fastapi/routing.py`, 49K tokens, matched via `request_response`) got sent in full just because it fit, dominating 56% of one real query's context while the actual answer file (`background.py`, 384 tokens) sat at 0.4%. | New `EvidenceTier` (`PRIMARY`/`SUPPORTING`) on `FileReference`: confident direct matches / query-referenced files stay `PRIMARY` (today's full-file-if-it-fits behavior, unchanged); everything reached via call-graph/inheritance expansion, lexical-probe recovery, or generic evidence-contract matching is `SUPPORTING`, compressed to its relevant symbol range *up front*, regardless of whether it would fit whole. Reuses the existing `SymbolRangeCompressor` — no second compression mechanism. Also fixed a related gap found while verifying this: `_expand_calls`'s "module-level call sites" path added files with **no** attached `SymbolReference` at all, so they had nothing to compress *around* and silently stayed full-size regardless of tier — fixed via `_attach_call_site_symbols` (reuses the real same-named Symbol when the file merely defines something with the matched name; synthesizes one at the call site's own real location otherwise). Measured effect on the case that motivated this: 87,826 → 26,500 input tokens on one real fastapi query (69.8% further reduction on top of fixes 1-3); the middleware-blowup file specifically went from 34.5K uncompressed → 7.1K compressed. | `domain/context_resolution.py` (new `EvidenceTier`), `context/budget_manager.py`, `context/relevance_ranker.py`, `code_intelligence/context_resolver.py` (`_attach_call_site_symbols`), `context/evidence_fallback.py`, `context/evidence_validator.py` |

**Result:** 687 tests passing (up from ~648 at session start). Nothing committed to git
this session — all changes are working-tree only in both `arcf/` and `benchmark/` (see
§5 for the full file list).

## 2. Phase 7: Language Semantic Enrichment (LSE) — spiked, tested live, CLOSED

A separate research thread: whether a deterministic, non-embedding graph-enrichment
layer (decorator/annotation/composition/etc. relationships, sitting *before* retrieval)
would help multi-hop, cross-conceptual queries current ARCF wasn't designed for (e.g.
"How are dependencies injected?"). Full design discussion, critical review, and a
de-risking implementation spike happened this session — **then it was tested live and
explicitly closed by the user** after two negative results.

**What was built** (stays in the codebase, standalone, fully tested, never wired into
`service.py` or the benchmark UI — zero risk to the pipeline described in §1):
`domain/code_intelligence.py`'s `DecoratorReference`, `python_analyzer.py`'s decorator
AST extraction, `code_intelligence/decorator_graph.py`'s `DecoratorGraph`,
`domain/context_resolution.py`'s third `EvidenceTier.EXPERIMENTAL` value,
`context/evidence_validator.py`'s `prune_experimental_candidates` (a corroboration +
lexical-relevance + ambiguity-cap pruning gate — REMOVES weak LSE candidates, the
inverse of `validate_sufficiency` which ADDS missing evidence-category coverage),
`code_intelligence/multi_hop_orchestrator.py`'s `MultiHopOrchestrator` (chains a
decorator match into `ContextResolver`'s existing call-graph expansion as a second hop,
pruning *before* that second hop is allowed to run — this ordering is what keeps a
multi-hop chain from repeating the fan-out blowup in §1's bug 3/4 at compounded scale).

**Why it stopped:** two live 3-way comparisons (Direct / baseline ARCF / ARCF+LSE, real
LLM, real fastapi repo) both showed the *same* result — baseline ARCF (§1's fixes, no
LSE) already found the right files on its own via SLM-1's real entity extraction, and
**LSE's hop 2 — the actual multi-hop chaining mechanism this spike existed to validate
— found zero new files in both tests.** Hop 1 added a handful of marginal files at real
token cost (+24.7% on the second test) with no visible answer-quality gain. Root cause
identified as structural, not bad luck: both test queries' wording happened to exactly
match the underlying symbol/decorator name, which is exactly the case where cheap
exact-name matching already wins. Worse: the original motivating example ("How are
dependencies injected?") isn't even reachable by decorator relationships in the first
place — FastAPI's real DI is a parameter default value (`Depends(...)`), not a
decorator. **User's explicit decision: "ok lets stop here."** Do not resume Phase 7
(build the remaining 13 relationship types, extend to other languages, or re-run LSE
benchmarks) unless the user explicitly reopens it. Full writeup, including the exact
numbers from both live tests, is in the `arcf-phase7-lse-experiment` memory file
(outside this repo, in Claude's own memory store) — read that before touching Phase 7
again, it has more detail than is worth duplicating here.

## 3. This session's final validation: 10-query battery on stable ARCF (§1's fixes, no LSE)

Run live against real repos (`flask`, `fastapi`, this `arcf` repo itself), `gpt-4o-mini`,
`ARCF Remote` mode only (Direct-vs-ARCF comparisons were already extensively established
earlier this session across multiple repos — this battery's purpose was validating
ARCF's own robustness/correctness across a diverse, previously-untested query set, not
re-establishing the comparison). **All 10 succeeded — zero crashes, zero zero-context
failures**, across three different repos and query shapes (repository-understanding,
architecture explanation, cross-functional tracing, "what happens when X fails").

**Direct LLM comparison was also run for all 10** (initially skipped as "already
established," then run properly on request — see below for why that matters):

| # | Repo | Query | Direct tok | ARCF tok | Tok reduction | Direct lat | ARCF lat | Lat reduction | Direct files | ARCF files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | flask | CLI app-factory discovery | 101,098 | 27,086 | 73.2% | 14.3s | 9.7s | 32.3% | 81 | 29 |
| 2 | flask | Jinja2 template rendering/context | 101,102 | 33,542 | 66.8% | 30.0s | 7.7s | 74.3% | 81 | 43 |
| 3 | flask | Session cookie signing/validation | 101,097 | 41,686 | 58.8% | 49.3s | 20.4s | 58.6% | 81 | 40 |
| 4 | fastapi | Request body validation vs Pydantic | 104,080 | 53,881 | 48.2% | 24.5s | 15.9s | 35.2% | 256 | 30 |
| 5 | fastapi | OpenAPI schema generation | 104,081 | 73,942 | 29.0% | 20.2s | 28.4s | **-40.4%** | 256 | 66 |
| 6 | fastapi | Nested dependency injection resolution | 104,080 | 76,246 | 26.7% | 37.3s | 37.0s | 0.9% | 256 | 137 |
| 7 | arcf | Intent extraction → contract building | 101,037 | 36,958 | 63.4% | 15.8s | 44.0s | **-177.8%** | 69 | 49 |
| 8 | arcf | Evidence-preserving packaging's compress decision | 101,035 | 23,387 | 76.9% | 11.6s | 12.0s | -3.5% | 69 | 41 |
| 9 | arcf | Benchmark request flow, CLI → LLM → back | 101,038 | 13,318 | 86.8% | 47.7s | 10.0s | 79.2% | 69 | 18 |
| 10 | arcf | JWT auth failure handling | 101,033 | 10,634 | 89.5% | 18.4s | 11.7s | 36.6% | 69 | 17 |

**Totals: 1,019,681 → 390,680 tokens, 61.7% overall reduction.**

**Token reduction is a clean, consistent win — all 10 positive, 26.7% to 89.5%.
Latency is NOT a clean win — 3 of 10 were slower under ARCF**, one substantially
(query 7: 44.0s vs 15.8s, -177.8%). This correlates with the same two file-count
outliers below (queries 5, 6) plus query 7 — cases where ARCF's extra pipeline stages
(SLM-1 call + code intelligence + packaging, on top of the same final LLM call Direct
alone makes) outweighed whatever time was saved by sending less context. Some of this
is plausibly just final-LLM-call response-time variance rather than a systemic
pipeline cost (query 9's ARCF `arcf` run was 10.0s vs query 7's 44.0s on the same repo
with a comparable file count), but that's a hypothesis, not verified — don't state
"ARCF is faster" as a blanket claim without checking which query shape you're in first.

Grounding spot-checked via file lists and answer previews (full text — 400-char previews
only, not complete responses; see §3c for why that mattered — persisted at
`docs/session_2026-08-08_data/ten_query_results.json` /
`ten_query_direct_results.json`, copied into this repo, survives past any one session):
query 3 correctly named `SecureCookieSessionInterface`/`itsdangerous`;
query 10 correctly found `infrastructure/auth.py` + `test_auth.py` and referenced
`AuthenticationError`; query 9 correctly traced through
`interfaces/api/routes/comparison.py`, `telemetry/comparison_aggregator.py`. All 10 ARCF
runs had `entities=[]` (SLM-1 extracted no concrete symbol for any of these — expected,
they're all conceptual/architectural phrasings, exactly the query shape that exercises
the evidence-fallback/lexical-probe paths fixed in §1) yet all 10 still produced real,
repo-grounded file sets, and all 10 Direct runs got *some* answer too (none refused) —
this session's own earlier live tests already showed Direct explicitly admitting "the
provided context does not contain..." on some queries; that didn't recur in this
particular 10, though it's not guaranteed not to on a different query shape.

**One open finding, not yet investigated or fixed:** queries 5 and 6 (fastapi OpenAPI
schema, fastapi nested DI) pulled noticeably more files/tokens than the other eight (66
and 137 files respectively vs. a 17-49 range for the rest). Not a crash, not a
regression — still well under Direct LLM's typical ~100K-token dump and evidence-
preserving packaging is doing its job (compressing what it can) — but 137 files for one
query is a real outlier worth understanding before calling this fully tuned. Likely the
same "common decorator/symbol name matches broadly" shape as the `Depends`/`FastAPI`
finding from earlier this session (`Depends`/dependency-related wording is exactly what
caused the worst blowup pre-fix), just now bounded rather than catastrophic. **Next
session, if continuing this line of work:** pull the full candidate list for queries 5
and 6 from `ten_query_results.json` (or re-run) and check whether it's dominated by a
few genuinely-relevant files plus a long tail of marginal ones, the same pattern
evidence-preserving packaging was built to handle for single files — if the *file
count* itself (not just per-file size) needs a cap, that's a different, not-yet-built
mechanism.

## 3b. Second validation round: real Batch 1/Batch 2 queries, 10 NEW repos (correcting §3)

§3's 10-query battery used ad-hoc queries against flask/fastapi/arcf, not the actual
documented `QUERIES` dict in `scripts/batch1_diagnostic.py`/`batch2_diagnostic.py` — the
user caught this and asked for a redo using the real batch queries, against repos not
already tested this session. Re-run properly: 10 queries pulled **verbatim** from those
two scripts' `QUERIES` dicts, against 10 freshly shallow-cloned repos chosen for
moderate size (avoiding kubernetes/pytorch/chromium-scale monorepos that would dominate
clone/index time) while still spanning Python/Go/TypeScript: `sqlalchemy`, `django`
(batch 1), `celery`, `consul`, `pnpm`, `traefik`, `containerd`, `open-telemetry`
(opentelemetry-collector) (batch 2), plus `ollama` and `vllm-project` (batch 1). Full
Direct-vs-ARCF comparison this time (both LLM calls), not the diagnostic-only
no-final-LLM script those two scripts default to.

| # | Repo | Batch | Direct tok | ARCF tok | Tok reduction | Direct lat | ARCF lat | Lat reduction | Direct files | ARCF files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | sqlalchemy | 1 | 101,835 | 101,451 | 0.4% | 56.1s | 34.0s | 39.4% | 129 | 95 |
| 2 | django | 1 | 111,427 | 42,579 | 61.8% | 258.6s | 35.2s | 86.4% | 705 | 99 |
| 3 | celery | 2 | 100,976 | 51,432 | 49.1% | 39.0s | 76.4s | -95.9% | 69 | 84 |
| 4 | ollama | 1 | 100,635 | 57,791 | 42.6% | 103.0s | 26.1s | 74.6% | 49 | 40 |
| 5 | consul | 2 | 109,363 | 74,202 | 32.2% | 389.1s | 82.0s | 78.9% | 704 | 43 |
| 6 | pnpm | 2 | 100,956 | 103,045 | -2.1% | 209.7s | 42.3s | 79.8% | 48 | 171 |
| 7 | traefik | 2 | 101,147 | 65,046 | 35.7% | 99.3s | 36.0s | 63.7% | 83 | 155 |
| 8 | containerd | 2 | 100,913 | 22,010 | 78.2% | 88.8s | 36.2s | 59.3% | 70 | 26 |
| 9 | vllm-project | 1 | 106,785 | 91,932 | 13.9% | 253.7s | 58.8s | 76.8% | 360 | 115 |
| 10 | open-telemetry | 2 | 101,710 | 62,769 | 38.3% | 137.6s | 29.5s | 78.6% | 112 | 93 |

**All 10 succeeded (no crashes). Total tokens: 1,035,747 → 672,257, 35.1% overall
reduction.** Full per-query data (400-char answer previews, referenced-file lists,
error tracebacks if any) persisted at
`docs/session_2026-08-08_data/batch_10query_results.json` — copied into this repo, not
scratchpad-only. **This file has previews only, not full response text — see §3c for
the full text, which is what actually mattered for judging correctness.**

**Two real negatives, found and reported honestly, not smoothed over — the next
session's actual priority if continuing retrieval-quality work:**

- **sqlalchemy: 0.4% token reduction, functionally no compression at all.** ARCF sent
  95 files (vs Direct's 129), landing at nearly the same total token count. The
  retrieved file list (`dialects/mssql/*`, `dialects/oracle/*`, `engine/cursor.py`,
  `exc.py`) doesn't look tightly focused on lazy-vs-eager *loading strategy* code
  specifically (that lives in `lib/sqlalchemy/orm/strategies.py`/`orm/loading.py`,
  neither of which appears in the top 10 shown) — reads like a broad evidence-
  fallback/lexical-probe match that never really landed on the right subsystem, not
  merely "found the right thing but couldn't compress it."
- **pnpm: -2.1%, ARCF sent MORE tokens than Direct** (171 files vs Direct's 48). pnpm is
  a large multi-package TypeScript monorepo (note the `pnpm11/` versioned-workspace
  path prefix in the file list) — this has the same shape as the `Depends`/`FastAPI`
  fan-out finding from earlier this session (a common word/symbol matching broadly
  across many structurally-similar files), just triggered here by many workspace
  packages instead of many test files. **Suggests the fan-out risk isn't fully closed
  for large monorepos generally** — evidence-preserving packaging (§1, item 4) bounds
  *per-file* cost once a file is in the candidate set, but doesn't bound *how many*
  files a broad lexical/evidence match pulls in to begin with. That's the same
  file-count-cap gap already flagged in §3 for the fastapi OpenAPI/DI queries — now
  confirmed on a second, structurally different repo, which upgrades it from "one
  outlier" to "a real, repeatable pattern worth fixing."
- **celery: latency regression, -95.9%** (76.4s vs Direct's 39.0s) despite sending
  under half the tokens. Not explained — this run didn't capture ARCF's stage-by-stage
  latency breakdown (`StageLatencies`), so there's no data yet on whether this is
  SLM-1/code-intelligence/packaging overhead or just final-LLM-call response-time
  variance. **Next session: re-run this specific query with stage latencies captured
  before concluding anything about it.**

**The strong, real pattern underneath the two negatives:** on the largest repos (django:
705 files/258.6s, consul: 704 files/389.1s, vllm-project: 360 files/253.7s under
Direct), ARCF's targeted retrieval was 3-7x faster because Direct's naive scan-and-dump
has to read and tokenize hundreds of files just to fill its budget. That advantage is
structural (it comes from *not* reading everything), not a fluke of these specific
repos — but it coexists with the file-count fan-out gap above, which is the more
important thing to fix next, not a victory-lap footnote.

## 3c. Quality/grounding comparison (§3b's real gap — user caught this, correctly)

§3b reported only token/latency/file-count metrics. The user pushed back: **"we can't
decide on tokens and latency itself"** — correct, and worth treating as a standing
principle for any future benchmark round, not just this one. Re-ran all 10 queries a
second time capturing **full** response text (not 400-char previews — first pass had
truncated everything, which wasn't enough to judge correctness either), then actually
read all 20 answers side by side. This materially changes the conclusion §3b implied.

**Only 2 of 10 are clearly, verifiably well-grounded** (cite real, specific internals —
not generic knowledge dressed up as a file diff):
- **containerd** — cites real protobuf event types (`SnapshotPrepare`, `SnapshotCommit`,
  `SnapshotRemove` from `api/events/snapshot.pb.go`) that genuinely exist in the repo.
- **celery** — references `celery/beat.py`, `celery/bin/worker.py`, `celery/schedules.py`
  — the actual scheduling/worker/broker modules the question asked about.

**3 of 10 are clearly NOT grounded — retrieval missed, and ARCF fabricated a plausible
generic answer instead of surfacing the miss:**
- **sqlalchemy** — retrieved `dialects/oracle`, `dialects/mssql`, never touched the real
  loading-strategy code (`orm/strategies.py`/`orm/loading.py`). Produced the *same*
  generic lazy/eager-loading textbook explanation Direct gave, just repackaged as a new
  `docs/lazy_vs_eager_loading.md` file — a fabricated deliverable dressed as grounded.
- **pnpm** — retrieved napi bindings and test-copy-artifact scripts, never touched the
  real content-addressable-store implementation. Same generic hard-links/content-hash
  explanation as Direct, wrapped in a fake README diff.
- **vllm-project** — ARCF's own answer text admits "the task does not specify a
  particular file" and invents a new doc file. Retrieval found benchmark scripts, never
  the real PagedAttention CUDA kernel (`csrc/attention/`).

**5 of 10 are mixed/uncertain** — real file paths, but possibly the wrong subsystem,
not confidently verifiable without deeper per-repo knowledge than is practical to apply
here:
- **django** — ARCF grounded itself in `admin/filters.py`/`admindocs/middleware.py` (the
  *admin app's* request handling), not the core request→template pipeline
  (`django/shortcuts.py`, `django/template/response.py`). **Direct's answer was actually
  MORE on-target here** — it correctly named `django/shortcuts.py`'s `render()`.
- **ollama** — the answer text references modifying `server/routes_generate_renderer_test.go`,
  which doesn't appear in ARCF's own `referenced_files` list at all — worth checking
  whether that's a real file the model actually saw further down the list, or a
  mismatch/fabrication. Not resolved this session.
- **consul, traefik, open-telemetry** — cite some real paths, plausible-sounding, not
  independently verified against what's actually the "right" subsystem in each repo.

**The finding that actually matters, more than any number in §3b's tables: token/latency
wins do not predict grounding quality, at all.** containerd (78.2% token reduction, one
of §3b's best metric results) is also one of the two best-grounded answers. sqlalchemy
and vllm-project (weak/negative token reduction) are also weakly grounded — consistent
so far — but pnpm is *also* weakly grounded despite sending MORE tokens than Direct
(worse on the metric AND the quality axis simultaneously). There is no clean
"efficient ⇒ correct" or "inefficient ⇒ wrong" relationship visible in this sample size.

**The more concerning systemic pattern, true of both Direct and ARCF, not just ARCF:**
when retrieval/context doesn't actually contain the answer, neither model says so —
both confidently generate plausible, well-formatted, wrong-or-generic content. ARCF's
failure mode is arguably worse in appearance: it wraps the same generic content in a
fabricated file diff against a real path, which *looks* more grounded and trustworthy
than Direct's plain prose while being just as ungrounded underneath. **This — not the
file-count fan-out gap from §3b — is the priority finding for a future session
continuing retrieval-quality work**: some mechanism (even a simple one — does the
packaged context actually contain any file matching the query's key terms before the
final LLM call runs, distinct from whether SLM-1 extracted an entity) to catch and
surface a genuine "insufficient grounding" case rather than let the final LLM
paper over it, for both modes but especially for ARCF where the deliverable format
(unified diffs against real paths) actively disguises the gap.

Full answer text for all 10 pairs (both Direct and ARCF, complete responses, not
truncated): `docs/session_2026-08-08_data/full_answers/{01..10}_<repo>.json` — copied
into this repo, persists past any one session. Each file has `direct_referenced_files`,
`direct_answer` (full text), `arcf_referenced_files`, `arcf_answer` (full text) for one
repo/task pair.

## 4. Known, unfixed, non-blocking items (found this session, not acted on)

- **Cost display bug, cosmetic only:** `benchmark/src/benchmark/infrastructure/cost.py`'s
  `DEFAULT_PRICING` table values are actual OpenAI per-1M-token rates, but the code
  computes cost as if they were per-1K — inflates every displayed/logged cost figure
  ~1000x (a real ~$0.02 gpt-4o-mini call shows as ~$15-16 in the benchmark UI/DB). Actual
  billed API cost is unaffected; only the benchmark's own cost display/logging is wrong.
  Not fixed — flagged during earlier analysis, deprioritized, never revisited.
- **§3's file-count outlier** for DI/OpenAPI-schema-shaped queries against fastapi — see
  above.

## 5. Files touched this session (working tree, nothing committed)

`arcf/`: modified `src/code_intelligence/{call_graph,context_resolver,engine,index,
service}.py`, `src/code_intelligence/languages/python_analyzer.py`,
`src/context/{budget_manager,evidence_fallback,evidence_validator,
lexical_symbol_probe,relevance_ranker}.py`, `src/domain/{code_intelligence,
context_resolution}.py`, plus their test files. New (Phase 7 spike, §2):
`src/code_intelligence/decorator_graph.py`, `src/code_intelligence/
multi_hop_orchestrator.py`, `tests/code_intelligence/test_decorator_graph.py`,
`tests/code_intelligence/test_multi_hop_orchestrator.py`. `benchmark/`: no source
changes, only its SQLite DBs (`benchmark_runs.db`, `benchmark_execution_ledger.db`) from
live test runs. Workspace root: `.claude/launch.json` (benchmark server's `--env-file`
wiring, from an earlier localhost session, unrelated to this doc's content).

Run `git status --short` in both `arcf/` and `benchmark/` for the live diff before
doing anything destructive — nothing here has been committed or reviewed for commit yet.

## 6. Batch 1 (from the 2026-08-06 handoff) — status unchanged, not touched this session

The 08-06 handoff's §9-§13 (50-query batch across 30 public repos, blocked on a
systemic recursion bug in all six language analyzers' AST walkers) was **not resumed
this session** — this session's work was a different, self-directed thread (live
testing against flask/fastapi/arcf specifically, not the formal 30-repo batch). The
recursion bug is still unfixed and the two options presented in that doc's §12 are
still undecided. If picking that thread back up, start from that document's §9 onward,
not from this one.

## 7. Environment / how to resume

Same as the 2026-08-06 handoff's §2 — still accurate: two apps (`arcf/`, `benchmark/`),
editable-install linked, dev servers in `.claude/launch.json`
(`arcf-benchmark` port 8010, `arcf-api` port 8000), launch via the Browser preview tool
only. Real LLM calls cost real (small — a `gpt-4o-mini` comparison run is a few cents
despite the ~1000x-inflated display figure per §4) money; this session ran roughly 25-30
real LLM-backed comparisons total (Phase 1 fixes' verification + Phase 7's live tests +
this section's 10-query battery) without issue.

## 8. Subsystem-localization experiment (root-cause follow-up) — CLOSED, tested, mixed result

Follow-up to the root-cause analysis (§3's finding that call-graph fan-out off a
lexically-probed symbol, not language-analyzer coverage, is the dominant driver of
inconsistent retrieval): tested the specific hypothesis that ranking a query-relevant
repository subsystem (directory) BEFORE lexical-probe recovery runs, then scoping the
probe to it, would reduce that fan-out without a redesign, embeddings, or a new language
analyzer. **Explicitly user-directed as a validation experiment, not a production
change** — same framing/rigor as Phase 7 LSE (§2).

**Implementation** (isolated, feature-flagged, Python-only, off by default):
- `src/context/subsystem_localizer.py` (new) — `localize_subsystems()` ranks
  repository directories by how many of the query's lexical-probe prefixes
  (`lexical_symbol_probe.py`'s existing technique, reused not reimplemented) match
  the directory name, filenames within it, or already-indexed symbol names under it.
  Confidence = matched prefixes / total prefixes.
- `src/context/lexical_symbol_probe.py` — added `probe_prefixes()` (public wrapper)
  and a `restrict_to_prefixes` parameter on `probe_symbol_names()` that scopes which
  symbol *names* are eligible before the existing 20-name cap is applied, while
  keeping the ambiguity safety count (`_MAX_MATCHES_PER_NAME`) global — see that
  parameter's docstring for why the ambiguity bound must stay global even when the
  eligible-name pool is scoped.
- `src/code_intelligence/service.py` — new `enable_subsystem_localization: bool =
  False` parameter threaded through `attach_code_intelligence()` / `_resolve()`.
  When `True` and the query's original symbol resolution found nothing, the
  highest-confidence subsystem(s) (ties included) are computed first and the
  lexical probe is scoped to them directly, instead of probing unrestricted and
  filtering after.
- Tests: `tests/context/test_subsystem_localizer.py` (5 tests, synthetic fixture),
  plus an integration test in `tests/code_intelligence/test_service.py`
  (`test_subsystem_localization_flag_defaults_off_and_reproduces_sqlalchemy_fanout`)
  proving the flag changes end-to-end behavior. Full suite: 693 passed throughout.
- One-off experiment runner (not a permanent script, kept for reproducibility):
  `scripts/subsystem_localization_experiment.py` — runs
  `attach_code_intelligence()` twice (flag off/on) against a real cloned repo with
  the same real SLM-1-extracted entities for both arms, retrieval-only (no final
  generation call).

**Real-repo result** (SQLAlchemy, the batch1 query "Explain how lazy loading differs
from eager loading internally and what SQL each strategy generates.", full results:
`docs/session_2026-08-08_data/subsystem_localization_experiment_results.json`):

| | Baseline (flag off) | Experimental (flag on) |
|---|---|---|
| Candidate files | 140 | 129 |
| Input tokens | 1,863,292 | 1,664,903 (−11%) |
| Irrelevant fan-out files (dialects/testing/cache) | 23 | 8 (−65%) |
| `lib/sqlalchemy/orm/strategies.py` retrieved | yes | yes |
| `lib/sqlalchemy/orm/loading.py` retrieved | yes | **no** |

Localization correctly identified the repository's `orm` directory as the
query-relevant subsystem (tied 0.83 confidence between `lib/sqlalchemy/orm` and
`test/orm` — a real signal, not noise) and measurably cut both token volume and
irrelevant-subsystem fan-out. But it **dropped one of the two canonical files**,
failing the user's explicit stated success bar ("retrieves the canonical files
*while* reducing fan-out" — both required, not a trade-off). Root cause: the probe's
existing 20-matched-name cap is shared across all tied top subsystems; `test/orm`
(67 files) and `lib/sqlalchemy/orm` (38 files) tied, and the combined pool of
same-rooted matches filled the cap with generic hits before reaching
`orm/loading.py`'s own symbols (`load_on_ident`, etc.).

**First attempt had a separate, now-fixed bug**, worth remembering if this is ever
revisited: the initial wiring computed the unrestricted probe result first and
filtered it down to in-subsystem names afterward — since the unrestricted probe's own
20-name cap could already exclude the correct in-subsystem symbol before filtering
ever ran, the flag was silently a no-op on the very first real run (both arms
byte-identical). Fixed by scoping the probe itself via `restrict_to_prefixes` before
the cap applies, not after. If picking this back up, don't reintroduce the
filter-after-the-cap version.

**Status: closed by explicit user decision after two directed questions** (whether to
fix-and-rerun after the first no-op result: yes; whether to keep iterating after the
second, partial-but-failing result: no — "stop here, write up as closed"). The flag
stays in the codebase, default `False`, zero effect on any existing caller or test.
Two concrete next moves were identified but **not attempted, by user choice**, if
this is ever resumed: exclude `test/`-mirror directories from subsystem candidates
(removes the tie that diluted the cap), or raise the per-subsystem name cap when
localization is active (a scoped search has a smaller blast radius than the
unrestricted case, so a higher cap there is lower-risk than raising it globally). Do
not resume this without the user asking — same convention as Phase 7 LSE's closure.

### 8b. Ranked-probe follow-up experiment — also CLOSED, negative result

Direct follow-up: added `probe_symbol_names_ranked()` (`src/context/lexical_symbol_probe.py`)
and a second flag, `enable_ranked_seed_selection` (only has effect when
`enable_subsystem_localization` is also `True`), which changes the localized probe's
20-name-cap selection rule from raw scan order to ranked by (distinct query-prefixes
matched, then global ambiguity count). Same SQLAlchemy query, three arms compared
(`scripts/subsystem_localization_experiment.py`, results in the same JSON file):

| | Baseline | Localization only | Localization + ranked selection |
|---|---|---|---|
| Candidate files | 140 | 129 | 90 |
| Input tokens | 1,863,292 | 1,664,903 | 963,574 |
| Irrelevant fan-out | 23 | 8 | **11 (worse)** |
| `orm/loading.py` retrieved | yes | no | **no (unchanged)** |

Ranking made things worse, not better, and the mechanism is understood, not
mysterious: the ranking signal (count of distinct query prefixes matched) has a
**length/verbosity bias** — long CamelCase test-class names (`ChainedJoinedload
InheritedRelationshipTest`, `GenerativeTest`, ...) accumulate multiple incidental
prefix hits just by concatenating several descriptive words, systematically
outscoring short precise implementation symbols (`load_on_ident`) that only ever get
one shot at matching one prefix. A follow-up code review (not another experiment)
found the deployed signal was also missing two things the original design called
for: it never used `Symbol.kind` (so CLASS-kind test fixtures get treated identically
to FUNCTION/METHOD implementation symbols, despite triggering a completely different
downstream expansion path — inheritance-graph vs. call-graph, see §9 below) and never
used `CallGraph` centrality (already O(1)-queryable, `_caller_symbols_of`/
`_callee_symbols_of`, unused by the ranking function).

**Status: closed by explicit user decision.** Both flags (`enable_subsystem_localization`,
`enable_ranked_seed_selection`) remain in the codebase, both default `False`, 697/697
tests pass. A follow-up principal-architect-level review proposed a larger
"confidence-aware retrieval" redesign (continuous confidence propagated and decayed
across graph traversal, replacing binary include/exclude decisions and hard caps) as
the architecturally correct direction — **not built, not started**. Explicitly
assessed and **not recommended as a near-term milestone**: two iterations already
underperformed their own success bars, the redesign would touch `ContextResolver`'s
core expansion methods and `CallGraph`'s core traversal primitive (not an isolated,
flagged add-on like everything else in §8/§8b), and it carries a larger, not smaller,
calibration/tuning-risk surface than the ranked probe that just failed. Recorded here
as a well-reasoned but explicitly deferred hypothesis, not a plan. This whole line of
investigation (subsystem localization → ranked probe → confidence-architecture
proposal) is closed. Do not resume without the user asking.

### 9. Open issues identified this session, for offline investigation

Concrete, code-grounded findings — not proposals, not fixes — for whoever picks this
up next:

1. **Uncapped `callers_of()` expansion** — `src/code_intelligence/context_resolver.py`,
   `_expand_calls()`, the first loop (module-level call sites). No depth limit, no
   count limit; the only gate (`_TokenBudget`) is inactive on the lexical-probe-recovery
   path since `max_expansion_tokens` is never passed there. Every one of the (ranked or
   unranked) probe-matched names hits this unconditionally. Identified as the single
   largest untouched contributor to fan-out this session — never fixed, never even
   attempted, flagged as the lowest-risk next move ahead of any ranking work.
2. **No confidence propagation** — `EvidenceTier` (PRIMARY/SUPPORTING/EXPERIMENTAL) is
   assigned once, at first-add (`ContextResolver._add_file`), and never revised. A file
   reached via two uncertain hops off a weak lexical guess gets the identical tier as a
   file one confident hop from an exact match. Root architectural finding of this
   session; not implemented.
3. **Ranking/probing is blind to `Symbol.kind`** — `probe_symbol_names_ranked` and the
   underlying `probe_symbol_names` never look at `symbol.kind`, despite
   `ContextResolver.resolve()` itself branching expansion behavior on exactly that field
   (FUNCTION/METHOD → call-graph hops via `_expand_calls`; CLASS → inheritance-graph
   hops via `_expand_subclasses`). A CLASS-kind match and a FUNCTION-kind match are
   currently indistinguishable to the probe despite triggering structurally different,
   independently-risky expansion paths.
4. **Test-fixture vs. domain-class ambiguity has no resolution** — kind alone can't
   distinguish `LazyLoader`/`EagerLoader` (domain classes, the actual answer) from
   `GenerativeTest`/`ChainedJoinedloadInheritedRelationshipTest` (test fixtures, noise) —
   both are CLASS-kind. `contracts/evidence_contract.py` / `workspace/
   repository_segmentation.py` already have test-directory detection logic that was
   never connected to probing or ranking — a real, available, unused signal.
5. **`CallGraph` centrality is computed and unused** — `_caller_symbols_of` /
   `_callee_symbols_of` (`src/code_intelligence/call_graph.py`) are O(1)-queryable
   adjacency dicts built at index time; no ranking or probing logic reads them.
6. **Two independent ambiguity gates at the same threshold, uncoordinated** —
   `_MAX_MATCHES_PER_NAME = 5` (`lexical_symbol_probe.py`) and
   `_MAX_CANDIDATES_TO_EXPAND = 5` (`context_resolver.py`) are separate constants in
   separate modules that happen to share a value — not a bug, but a sign that
   ambiguity/confidence logic is fragmented rather than owned by one mechanism.
7. **Subsystem-localization tie dilution** — when two subsystems tie on confidence
   (`test/orm` vs. `lib/sqlalchemy/orm`, both 0.8333), the fixed name cap is shared
   across both, diluting coverage of the actually-correct one. `context/
   subsystem_localizer.py`'s `localize_subsystems()`.
8. **Cross-language / dynamic-dispatch boundary is a hard ceiling, not a tunable
   parameter** — no graph edges exist across e.g. a Python/CUDA boundary (relevant to
   vLLM specifically), so no amount of ranking or propagation sophistication can
   recover relevance there; already-flagged by `unsupported_conditions.py`'s
   `has_dynamic_dispatch_hint`, never connected to retrieval confidence.
9. **Decorator-mediated relationships are invisible to `CallGraph`** — Flask/FastAPI-
   style dependency injection isn't captured by plain call edges. Phase 7's LSE spike
   (`decorator_graph.py`, `multi_hop_orchestrator.py`) targeted exactly this and is
   still in the codebase, unused by default, tested but found not to add value on the
   two live queries it was tried against (see §2) — not re-litigated this session, but
   still the only attempt so far at this specific gap.
10. **Weak-signal repo shapes are untested** — small, loosely-coupled multi-package
    repos (pnpm, Traefik-shaped) were flagged as a risk (diffuse centrality, no strong
    directory-level signal) but never actually run through any of this session's
    experiments; SQLAlchemy is the only repo any of §8/§8b was tested against.
11. **Cost display bug, cosmetic, unrelated to retrieval** — `benchmark/src/benchmark/
    infrastructure/cost.py`'s `DEFAULT_PRICING` table is priced per-1M tokens but the
    code computes as if per-1K, inflating displayed/logged cost ~1000x. Real billed
    cost unaffected. Still unfixed (carried over from earlier in this session).
12. **Settled, not open**: analyzer/language coverage is confirmed *not* the dominant
    driver of retrieval failures (SQLAlchemy at 0.95 coverage still failed via 81%
    call-graph fan-out) — don't re-investigate this axis without new evidence.

## 10. Anchor Classification — the one mechanism that actually worked, plus its limits

Direct follow-up to §9's issue list, built and validated after it (same day). Two new
flags, both default `False`, `enable_anchor_classification` and
`enable_confidence_propagation`, both independent of and mutually exclusive with
everything in §8/§8b (subsystem localization, ranked seed selection) — see
`service.py`'s own branch ordering.

**What it is** (`src/context/anchor_classifier.py`):
- **Tier 1 (confidence 1.0)** — exact query-word matches, PLUS a deterministic
  morphological reconstruction path (`generate_morphological_candidates`,
  `classify_morphological_anchors`): strips common suffixes (-ing/-ed/-es/-s),
  recombines adjacent query words with agentive suffixes (-er/-or) and casing
  conventions (CamelCase, snake_case, **and a leading-underscore variant** — the real
  fix, see below), then verifies every candidate against `SymbolIndex.find_by_name()`.
  Only confirmed real symbols survive, so false positives are structurally
  impossible — this is what justifies Tier 1 confidence for a *reconstructed* name,
  not just a literally-typed one.
- **Tier 3 (confidence 0.5)** — the pre-existing unrestricted lexical probe,
  now token-budget-gated at 50,000 tokens (`_TIER3_EXPANSION_TOKEN_BUDGET`),
  finally activating `ContextResolver`'s `_TokenBudget` gate that was built in an
  earlier session but never actually invoked on this path.
- **Tier 4 (confidence 0.35, recalibrated twice against real data)** — filename/path-
  only matches (comments/docstrings explicitly out of scope, ARCF's IR doesn't
  capture them). Started at the brief's own 0.15, which made ranking *worse* than
  doing nothing on the real SQLAlchemy run; raised to 0.35, then a second real bug
  was found and fixed — its reason string (`"tier4: ..."`) didn't match any
  `RANKING_PROFILES` key, double-penalizing it — remapped to reuse the existing
  `"references:"` weight key instead of inventing a new one.
- **Class-method expansion** (`_expand_class_anchors_to_methods`) — a Tier 1 anchor
  that resolves to a CLASS also seeds its own METHOD-kind children, because
  `ContextResolver` only runs call-graph expansion for FUNCTION/METHOD symbols, never
  for the class itself (class-kind goes through inheritance expansion instead) — so a
  class-level anchor's own methods' real call edges were otherwise invisible.
  Ambiguity-gated at the same threshold (5) two other probes in this codebase already
  use, after an unguarded version caused a real, measured regression (candidate count
  140→**297**, worse than doing nothing) by matching `__init__` against every
  unrelated class in the repo that happens to define one.

**Real result, SQLAlchemy, the same batch1 query used throughout this investigation**
(`docs/session_2026-08-08_data/anchor_classification_experiment_results.json`, latest
run reproduced identically twice):

| | Baseline | Anchor classification + confidence propagation |
|---|---|---|
| Phase 5 candidates | 140 | 119 |
| Phase 5 tokens | 1,863,292 | 1,430,328 |
| `orm/strategies.py` | rank 90/140, not packaged | **rank #1/119, score 1.0, packaged** |
| `orm/loading.py` | rank 125/140, not packaged | rank 77/119, score 0.276, not packaged |

`orm/strategies.py` becoming the **first, and only, canonical file successfully
retrieved and packaged** in this entire investigation (subsystem localization, ranked
probing, and multi-axis decomposition all failed to achieve this on the same query) is
the one unambiguous positive result to carry forward. It happened because the real
SQLAlchemy symbol is `_LazyLoader` (leading underscore, Python's "internal use"
convention) — every earlier synthetic test fixture this session assumed `LazyLoader`
without the underscore, an unverified guess baked in from the start of the
investigation and never checked against the real source until this point.

`orm/loading.py` remains unretrieved. Root cause understood, not fixed: its
best-connected real symbol, `_load_on_ident`, is a three-word compound
(`load`/`on`/`ident`) whose vocabulary never overlaps with the query at all — no
lexical, morphological, or graph mechanism built this session can reach a symbol the
query shares zero words with. The class-method-expansion fix did find a *different*
real edge (`_load_for_state`, a genuine hop-1 caller), but the resulting larger
candidate pool (45→119) wasn't enough to lift it into the packaged set at the real
8,000-token budget.

**Multi-Axis Query Decomposition** (`enable_multi_axis_decomposition`,
`src/context/query_decomposition.py`) was built and tested as a separate, explicitly
isolated experiment the same day — splits a comparative query into independent
retrieval axes (general English markers: "differs from", "versus", "and what", etc.,
never repository vocabulary) with a strict per-axis quota. Real result: the best
fan-out reduction measured all session (140→19 candidates, 93%) but **worse**
canonical-file recall (neither file even remained a candidate) — confirmed
mechanically, not guessed: each axis reuses the same undifferentiated lexical probe
and role-weight ranking as the baseline, so a smaller pool just concentrates the same
wrong winner instead of diluting it. Directly mapped against every item in §9's issue
list: addresses none of them — it's a fan-out-volume lever, not a ranking-precision
fix, and the two are not substitutes for each other. Not enabled in the final
configuration below; kept in the codebase, default off, mutually exclusive with
anchor classification by design.

**Closing configuration** (this investigation's final state, "ARCF + all validated
solutions"): `enable_anchor_classification=True`, `enable_confidence_propagation=True`,
everything else default `False`. 728/728 tests pass. 1 of 2 canonical files reliably
retrieved and packaged, with a fully understood mechanism and a fully understood
reason for the remaining gap. Do not resume this investigation without the user
asking — same convention as every other closure in this document.
