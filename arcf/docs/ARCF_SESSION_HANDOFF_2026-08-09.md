# ARCF Session Handoff — 2026-08-09 (DRP / Issue #3)

**Purpose:** continuity document for a fresh context window. Read this first — it
captures everything needed to resume without re-deriving this session's work.
**Next step the user explicitly asked for: continue investigating from Traefik** (see
§7). This doc covers the DRP (Dynamic Repository Profiling) experiment only — for the
stable Phase 5/6 pipeline's own history, see `ARCF_SESSION_HANDOFF_2026-08-08.md` and
`ARCF_SESSION_HANDOFF_2026-08-06.md` (unrelated, not touched this session).

---

## 1. What DRP is and why it exists

**ARCF Issue #3**: the stable pipeline (`code_intelligence/context_resolver.py`)
resolves via exact/lexical symbol-name matching + call/inheritance graph expansion. It
fails on "diffuse-structure" repos — where the right subsystem is organized by
directory/package convention rather than by any name a query literally mentions.

**DRP** is a second, fully isolated resolver strategy that teaches itself a
repository's structure deterministically — directory taxonomy + per-file/per-symbol
TF-IDF + graph-community detection — with **zero embeddings, zero LLM calls, zero
hardcoded concept dictionaries**. This is a hard constraint carried over from the
`arcf-phase7-lse-experiment` memory file and `context/evidence_validator.py`'s own
"no-embeddings/no-scoring-model" docstring — do not relax it without the user
explicitly asking (an SLM-based query-expansion idea was proposed and explicitly
rejected by the user this session — see §8).

**Isolation discipline** (unbroken all session): nothing in `context_resolver.py`,
the five existing graph classes, or `context/` packaging is touched. DRP is reached
only through `resolver_strategy="drp"` on `CodeIntelligenceContractService.
attach_code_intelligence` (`code_intelligence/service.py`), default `"classic"` —
every existing caller/test is byte-identical. 805/805 tests pass as of this doc
(updated 2026-08-09/10 follow-up session — see fixes #9-#13 in §3; fix #13 touches
`go_analyzer.py`, a shared LanguageAnalyzer, not DRP-only, but stays within the same
"never touch context_resolver.py / the five classic graph classes" isolation
discipline since LanguageAnalyzer is a different, lower layer).

## 2. Architecture — `arcf/src/code_intelligence/drp/`

```
taxonomy.py        Stage 1: adaptive directory taxonomy (see §3, fixes #1 and #6)
text_corpus.py      Stage 2a: per-file/per-symbol vocabulary + usage-count gathering
tfidf.py              Stage 2b: TF-IDF with length- and usage-confidence dampening
subsystem_graph.py     Stage 3: file-level graph + deterministic Label Propagation
query_router.py           Stage 4: routing, incl. near-tie subsystem expansion (fix #5)
pmi_expansion.py            Optional: repo-local PMI word-association query expansion
drp_index.py                  Bundles all of the above into one DrpIndex
drp_resolver.py                  Public entry point, translates to ContextResolutionResult
diagnostics.py                     Benchmark-only instrumentation (DrpDiagnostics)
```

Wiring: `code_intelligence/service.py`'s `_resolve_drp` (isolated branch).
Benchmark harness: `arcf/scripts/drp_benchmark.py` — retrieval-only, no LLM calls,
`--resolver classic|drp|both --pmi-expansion`.
Tests: `arcf/tests/code_intelligence/drp/` (62 tests) — run with
`uv run pytest tests/code_intelligence/drp -q` from `arcf/`.
Benchmark repos: shallow-cloned siblings at
`C:\Users\VasiganiRohitBabu\Desktop\Claude\.benchmark_repos\{traefik,consul,django,sqlalchemy,vllm}`
— already cloned, reuse them, don't re-clone.

## 3. Every real bug found and fixed this session (all verified against real repos, not assumed)

| # | Bug (found via) | Fix | File |
|---|---|---|---|
| 1 | LP oscillation: a 3-node import chain never converged under synchronous (Jacobi-style) label updates | Switched to asynchronous (Gauss-Seidel) updates | `subsystem_graph.py` |
| 2 | Raw term-frequency let a tiny document win by magnitude alone (Traefik: `cmd/configuration.go` beat `pkg/server`) | Sublinear tf + L2-normalized cosine similarity | `tfidf.py` |
| 3 | Pooling a whole subsystem/file into one TF-IDF document diluted the one relevant file/symbol among unrelated neighbors (Traefik at file level, then SQLAlchemy's `orm/strategies.py`'s 17 loader classes at symbol level) | File-level scoring (not subsystem-pooled), then symbol-level scoring for large files (**user's own idea**) — aggregate UP via top-K mean, never pool DOWN | `text_corpus.py` (`gather_scoring_units`), `query_router.py` |
| 4 | Taxonomy fixed at top+second directory level only — real package boundaries in Django/SQLAlchemy/vLLM sit 3-4 levels deep, pooling huge unrelated subtrees together | Recursive adaptive splitting by file-count threshold (`_MAX_FILES_PER_SUBSYSTEM=50`), subsumes the old fixed-depth rule as a special case | `taxonomy.py` |
| 5 | Tiny/sparse documents (a 4-token function, just its own name) beat substantial relevant ones via cosine's bias toward concentrated short vectors | Length-confidence dampening, ramped `min(1.0, tokens/30)` (BM25-length-norm spirit, not a full rewrite) | `tfidf.py` |
| 6 | Test functions (discovered/invoked by test runners, never called from an explicit call site — true for ANY testing framework, including one testing itself) and empty re-export modules (zero symbols, zero calls) outscored real, heavily-used implementation | Usage-confidence dampening from the already-built `CallGraph` — **deliberately NOT a `test/`/`tests/` folder-name check**, since the user correctly flagged that would misfire on a repo whose own purpose is testing; incoming-call count is purely structural | `text_corpus.py` (`gather_scoring_units`'s `unit_usage`), `tfidf.py` |
| 7 | Winner-take-all: a subsystem within 2-3% of the winner got ZERO candidate files (Consul, Django) | Near-tie subsystem expansion — runner-up subsystems within `_NEAR_TIE_MARGIN=0.03` also get their own entry files (SUPPORTING tier, capped at `_MAX_NEAR_TIE_SUBSYSTEMS=2`) | `query_router.py`, `drp_resolver.py` |
| 8 | A large FLAT directory (idiomatic Go: one package, many files, zero subdirectories — Consul's `agent/consul`, 175 files) can never be split by directory depth, no matter how large | Filename-prefix clustering (Go's own convention: `catalog_endpoint.go`/`catalog_endpoint_ce.go`/`catalog_endpoint_test.go` share the `catalog` prefix) when a directory is oversized AND has no subdirectories — including its own direct files even when it DOES split by subdirectory too (a second sub-bug found mid-fix: `agent/consul` has one small real subdirectory `autopilotevents/` mixed in with 175 flat files, which was falling through to the old "just register the flat blob" path) | `taxonomy.py` (`_filename_prefix`, `register_direct_files`) |
| 9 | `CallGraph`/`ReferenceResolver.resolve()` deliberately fan out an ambiguous name to EVERY same-named symbol in the whole repo (documented, intentional design for `CallGraph`'s real purpose — conservative reachability/impact analysis; see `reference_resolver.py`'s own module docstring). DRP's `_combined_call_count` (fix #6) trusted that fanned-out edge set as if it were a real COUNT — a real SQLAlchemy run found three unrelated `__init__` methods each credited with an identical, inflated 367 "callers" (the total count of every `__init__()` call anywhere in the repo), which defeated fix #6's own usage-confidence dampening for an example/demo file (`examples/dogpile_caching/caching_query.py`, `usage_count=1323`, full confidence, zero dampening) | Locality filter (same file / same directory via `SymbolIndex.same_package` / import-reachable via `ImportGraph` — the same signal `resolve_with_disambiguation` already uses elsewhere) applied as a **read-side filter on DRP's own usage count**, not any change to `CallGraph`/`ReferenceResolver` themselves — stays inside DRP's isolation boundary. Fixed the anomaly (1323→11) and improved Django (rank 10→**5**) with no regressions on SQLAlchemy (still rank 1) or the 798-test suite (was 797, +1 new test) | `text_corpus.py` (`_combined_call_count`, new `_has_locality`) |
| 10 | Languages that declare methods OUTSIDE their receiver type's own source range (Go: `func (c *Catalog) Register(...)`, separate from `type Catalog struct{...}`) left every such method's own doc comment and body completely unreachable by fix #3's per-symbol split — the parent's own line-range extraction never touches it, and methods (`parent_id != None`) never got their own scoring unit either. Real Consul case: `Catalog.Register`'s doc comment ("Register a service and/or check(s) in a node...") — nearly a paraphrase of the benchmark query — was entirely absent from the corpus. **First attempted fix (pooling all method comments into the parent's one unit) made things WORSE** (target score 0.25→0.11) by reintroducing fix #3's own dilution problem one level deeper (11 methods' unrelated concerns — ACL checks, metrics, hashing — burying Register's specific vocabulary) | Give each externally-declared child its own scoring unit (a genuine second splitting tier, gated by `_is_within` so Python's already-correct nested-range case is untouched) instead of pooling, plus a leading-comment lookback (`_expand_start_for_leading_comment`) since a symbol's own doc comment sits on the lines ABOVE its declared `start_line`, not inside it — a separate, subtler part of the same bug. `_file_level_scores`'s existing max-across-a-file's-units reduction picks the new units up automatically, no query_router.py change needed. 799/799 tests (new Go-fixture test added), no regressions on the 5-repo sweep, though this alone didn't flip Consul (see fix #11 and §6 for why) | `text_corpus.py` (`gather_scoring_units`, new `_is_within`/`_expand_start_for_leading_comment`) |
| 11 | No stemming anywhere in `tokenize()` — exact-string matching only. Found while checking why fix #10's newly-reachable `Register` doc comment still scored 0: the query says "agent **registers** it," the comment says "**Register** a service..." — two different tokens, zero overlap, despite being the same word | Lightweight, deterministic suffix-stripping (`_stem` — plural -s/-es/-ies, verb -ing/-ed; explicitly NOT a full Porter/Snowball implementation or an external NLP dependency, matching this module's own "pure Python/math, no libraries" restraint) applied inside `tokenize()`, so it's automatic for corpus, query, AND PMI-expansion text alike. Verified against a stress-test word list for false positives (class/process/status/success/bus stay unchanged) before landing. Real effect: **Django improved to rank 1** (from rank 5), SQLAlchemy stays rank 1, no regressions on the 801-test suite (2 new stemming tests added) or the other 3 repos — Traefik's wrong winner even moved into the correct neighborhood (`pkg/server/service` instead of `integration`) | `tfidf.py` (`tokenize`, new `_stem`) |
| 12 | Even with fixes #10/#11, `Register`'s own unit still scored a raw 0.6086 but got zeroed to 0.0 by usage-confidence dampening (fix #6): `usage_count=0`. Root cause: a framework-dispatched method (RPC handler invoked by name/reflection through a registration table) structurally has zero recorded callers no matter how central it is — `CallGraph` only sees explicit call expressions, and this session confirmed the receiver TYPE's own construction (`&Catalog{...}`, a struct literal) isn't tracked as a "call" either, so the type itself can't be used as a confidence fallback. What DOES survive: checked all 11 of `Catalog`'s methods directly — 9 showed 0 own callers, but `ServiceNodes` (4) and `VirtualIPForService` (6) didn't, real evidence the type as a whole is live, active code. This is the **user's own graph-proximity idea**, applied to its narrowest, best-evidenced form (not the fuller "type → method → call" graph originally proposed — see below) | A zero-usage split method borrows the MAX usage count among its siblings on the same receiver type as a confidence floor (never lowers an already-nonzero count) — pure structural composition of the existing parent-child relationship, no new analysis. Verified in isolation with a dedicated test (`Dispatched`/`Called`/`Widget` fixture) and against real Consul data (`Register`'s own score: 0.0→0.1826). **Did NOT change Consul's end-to-end ranking** — `Register` still isn't `catalog_endpoint.go`'s highest-scoring unit (something else in the file already scores 0.4633), so `_file_level_scores`'s max-across-units reduction was never bottlenecked on it for this specific query. A real, tested, isolated correctness fix that just wasn't decisive here. 802/802 tests (1 new test), no regressions on the 5-repo sweep | `text_corpus.py` (`gather_scoring_units`, sibling-usage-floor pass) |

| 13 | `go_analyzer.py`'s `_resolve_import_path` matched a raw import path directly against workspace-relative paths — but a real Go import is module-qualified (`github.com/org/repo/pkg/auth`), and the module's own declared prefix (from `go.mod`, never read) never appears in workspace-relative paths (`pkg/auth`) at all. Confirmed against a real Traefik scan: **0 of 5,931 imports ever resolved**, local or not — meaning `ImportGraph` was completely empty for every Go repo this whole session, and fix #9's locality filter had silently been degraded to same-file/same-package checks only (its import-reachability tier never fired for Go). This is a shared, core `LanguageAnalyzer` bug, not DRP-specific — found while building the qualified-identifier falsification experiment (§9), which needed real import resolution to detect "project-local" symbols | `_resolve_import_path` now tries progressively shorter suffixes of the import path (dropping leading segments one at a time) against `workspace_files`, returning the first (longest, most specific) match — recovers the workspace-relative portion of a module-qualified path without ever reading `go.mod`, purely from data already available. Traefik: 0→1,361/5,931 resolved; Consul: 0→6,462/16,602. Stdlib/third-party imports correctly still never resolve (verified with a dedicated test). 3 new tests, 805/805 full suite, zero regressions on the 5-repo DRP sweep (all 5 repos' rank/candidates unchanged after this fix alone) | `go_analyzer.py` (`_resolve_import_path`) |

**On the fuller graph-proximity idea (user's original proposal, "ConfigurationWatcher → Watch → loadConfiguration" with score diffusion across call edges):** fix #12 implements the narrowest slice of it (usage-confidence only, sibling-max floor) because that's exactly what the concrete Consul evidence supported. The broader version — propagating TF-IDF *relevance* itself (not just usage-confidence) across a type→method→call graph — is still unbuilt. **Checked whether it would even help before building it (per this doc's own discipline) — it would not; see the final re-diagnosis immediately below.**

**Consul, re-diagnosed one more time after fix #12 (2026-08-10) — final conclusion for this experiment.** Fresh `subsystem_scores` breakdown: `agent/consul::catalog` (the correct subsystem) actually **wins** on taxonomy (0.625 vs the winner's 0.375) and **ties** on community (0.755 vs 0.755) — the entire remaining gap is TF-IDF (0.230 vs the winner `agent::agent`'s 0.562). Traced that gap to its source: `agent/agent.go`'s `AddServiceRequest`/`Agent.AddService`/`Agent.registerEndpoint` score very high (raw weights: "add" 0.57, "service" 0.38, "agent" 0.35, "register" 0.22) — and **this is a completely legitimate match, not noise**. Consul's real service-registration flow genuinely spans two architectural layers: `agent/agent.go` is the agent-local HTTP API where a registration request first lands (`Agent.AddService`), and `agent/consul/catalog_endpoint.go`'s `Catalog.Register` is the RPC handler that actually writes it into the catalog (reached later, via anti-entropy sync). The benchmark query — "...when an **agent registers** it" — is honestly ambiguous between these two; the literal phrase arguably points at `agent.go` even more directly than at the RPC layer. No amount of relevance-propagation across `Catalog`'s own internal call graph would resolve this, because the competing signal isn't a mis-scored neighbor of the target file — it's an entirely different, legitimately relevant file answering a different (but related) question. **Conclusion: every specific, fixable bug this session found (#1-#12) is fixed and verified. Consul's remaining failure is the same structural ceiling already documented for Traefik (§5/§7) and vLLM (§8) — genuine cross-cutting topical overlap between architecturally distinct files, not a defect. User confirmed accepting this as the final diagnosis; do not resume chasing Consul without new evidence that changes this conclusion.**

**Rejected/deferred ideas** (do not re-propose without new evidence):
- **SLM-based query expansion** — analyzed in depth, user said "forgot about SLM Q/A proposal, I will find an alternative way." Do not resume.
- **Dual-layer prose-code binding** (comment-to-symbol proximity pointers) — architecturally reviewed, found to not actually fix the Traefik case (the file's own comments don't contain the missing word either) — see §7.
- **`test/`/`tests/` folder-name deprioritization** — user explicitly rejected this ("what if repository itself a testing framework... suggest another approach") in favor of fix #6 above (call-graph based, not name-based).
- **Qualified-identifier-reference vocabulary extraction, unfiltered or path-gated** — two earlier variants tried and reverted (see §7's original account): unfiltered caused the SQLAlchemy regression fix #9 later explained; a "production-file" path-based guardrail (excluding `test`/`examples`/`benchmark` paths from the new signal) also reverted — it correctly stopped test files from directly absorbing the signal, but SQLAlchemy's `lib/sqlalchemy/orm` vs `test/orm::test` margin was ALREADY razor-thin (0.6%) before this change, and enriching vocabulary across many production files still shifted the corpus-wide IDF landscape enough to flip it — a mechanism no per-file gate can reach, since IDF is computed once, globally, before any per-file weighting applies. **A third, far more rigorous variant (project-local-only via `resolved_file_path`, deduplicated/low-weight, measured with a dedicated falsification methodology) was run in a follow-up session — see §9. Verdict: falsified.** Two of five repos improved (SQLAlchemy, Django), but Traefik — the repo whose own diagnosed lexical gap motivated the whole idea — barely moved and never reached retrieval, while Consul regressed and vLLM's routed candidate list was flooded with 14 test/benchmark files despite graph-locality weighting. Do not re-attempt any qualified-identifier-extraction variant without new evidence addressing §9's core finding: the repo that most needed this fix didn't respond to it, which undercuts the "lexical incompleteness is the root cause" premise more than any single regression does.

## 4. Current benchmark status (as of this doc)

| repo | query target | status | current blocker |
|---|---|---|---|
| **SQLAlchemy** | `lib/sqlalchemy/orm/strategies.py` | ✅ **succeeds, rank 1** | — |
| **Django** | `django/db/models/query.py` | ✅ **succeeds, rank 1** (rank 10 → 5 via fix #9, → **1** via fix #11 stemming, 2026-08-09) | — |
| Traefik | `pkg/server/configurationwatcher.go` | ❌ fails | vocabulary-extraction gap (§5/§7) — the qualified-reference fix that helps this is no longer regression-gated (fix #9 fixed the anomaly that caused its SQLAlchemy regression) but was not re-attempted this session. Stemming (fix #11) moved the wrong winner into the right neighborhood (`pkg/server/service`) without flipping it |
| Consul | `agent/consul/catalog_endpoint.go` | ❌ fails, **closed out as a genuine architectural ambiguity, not a bug** | see §6's final re-diagnosis — every specific bug found this session (#1-#12) is fixed and verified; what remains is the same structural ceiling as Traefik/vLLM |
| vLLM | `vllm/v1/core/sched/scheduler.py` | ❌ fails | fully re-diagnosed 2026-08-09 — see §8, same structural ceiling as Consul, not a quick fix. Unaffected by fixes #10/#11 (`scheduler.py` isn't split) |

Grounded queries/targets (all independently verified against real source before use —
do not re-verify unless the repo has changed):

```
Consul:     "How does Consul add a new service instance to the catalog when an agent
             registers it?" -> agent/consul/catalog_endpoint.go
Django:     "How does Django avoid hitting the database again when the same queryset
             is evaluated more than once?" -> django/db/models/query.py
SQLAlchemy: "How does SQLAlchemy decide whether to load a relationship immediately or
             wait until it's accessed?" -> lib/sqlalchemy/orm/strategies.py
vLLM:       "How does vLLM decide which request to pause when it runs out of memory
             for the KV cache during batching?" -> vllm/v1/core/sched/scheduler.py
Traefik:    "Explain how dynamic configuration updates propagate without restarting
             the server." -> pkg/server/configurationwatcher.go
```

Re-run any of these with:
```bash
cd arcf
uv run python scripts/drp_benchmark.py \
  --repo-path "../.benchmark_repos/<repo>" --repo-name <repo> --language <python|go> \
  --query "<query>" --target-file <target> --resolver drp --pmi-expansion
```

## 5. §7 in detail — Traefik, re-diagnosed 2026-08-09 (follow-up session)

**Original finding (word "restarting" has zero document frequency anywhere in the
corpus) still holds**, confirmed again this session. But the fuller re-diagnosis below
supersedes the old "that's the whole story" framing — the gap is broader than one
missing word.

**Fixes #7/#8 re-verified against current Traefik, confirmed NOT the fix:**
- Fix #8 (flat-directory splitting): doesn't apply — `pkg/server` is 27 files, well
  under the split threshold.
- Fix #7 (near-tie expansion): re-ran the benchmark and checked `subsystem_scores`
  fresh. `pkg/server` scores 0.7960 combined; the near-tie threshold is winner×0.97 =
  0.8390. Four other subsystems (`integration` 0.8649, `pkg/tls` 0.8293, `pkg/
  middlewares/snicheck` 0.8064, `pkg/server/service` 0.7968) all sit strictly ahead of
  it, and `pkg/server` itself misses the near-tie cutoff by ~5% — not a close call.

**Refined root cause (more precise than the old write-up):** it isn't only that
"restarting" is absent. The word "server" — genuinely present in the corpus — gets
*diluted away from the target file specifically*, because of how cosine/L2-normalized
TF-IDF treats document breadth. `configurationwatcher.go` is a 183-token file with a
naturally broad vocabulary (configuration, watcher, provider, listeners,
transformers…); the literal word "server" appears in it exactly once (the `package
server` line), so after L2-normalization its weight on "server" is tiny. Meanwhile
`pkg/server/server.go` is a small, 53-token file that's almost entirely *about* the
word "server" (type `Server`, `NewServer`, etc.), so cosine gives it a near-maximal
weight (0.337) on that one term and it wins outright on that signal alone — the same
"small + concentrated beats large + diverse" pathology fix #5 targeted, but fix #5's
`_MIN_SUBSTANTIAL_TOKENS=30` dampening ramp saturates at 30 tokens and never touches
this case (`server.go` at 53 tokens is already at full confidence, not sparse by that
threshold's definition).

**Deeper cause underneath that:** `text_corpus.py`'s vocabulary extraction only reads
comments/docstrings + DEFINED symbol names, never the file's own body — so
`configurationwatcher.go` orchestrating `dynamic.Message`/`dynamic.Configuration`/
`dynamic.Configurations` **17 times** in its body contributes *zero* vocabulary,
because those are usages of an imported type, not a definition or a comment. Confirmed
by grep (`grep -c "dynamic\." configurationwatcher.go` → 17) and by inspecting the
file's own `TfIdfProfile.weights`: only "configuration" appears among the query's
terms; "dynamic" isn't in the vocabulary at all despite being the single most-repeated
substantive word in the file's actual code.

**A targeted fix for that deeper cause was prototyped and reverted this session** —
see the "Qualified-identifier-reference vocabulary extraction" entry in the
rejected/deferred list above for the full result (real gains on Traefik's own score
and on Django, but a verified SQLAlchemy regression and an unresolved CallGraph
usage-count anomaly on example/demo files). Any future attempt at this specific
Traefik gap should start from that entry, not from scratch.

**Sanity-checked again this session, still holds:** a real, verified alternative
phrasing that DOES succeed (proves DRP's mechanism is sound when query vocabulary
aligns with the repo's own vocabulary): *"How does the ConfigurationWatcher apply new
configuration changes from providers?"* → rank 1, confirmed unchanged after fixes
#7/#8. Useful evidence for any final writeup, not itself something to fix.

## 6. §6 in detail — Consul, re-diagnosed 2026-08-09 (follow-up session): two distinct issues, neither resolved

Fix #8 correctly isolated `agent/consul::catalog` as its own 3-file cluster
(`catalog_endpoint.go`, `catalog_endpoint_ce.go`, `catalog_endpoint_test.go`) — but its
`combined_score` **dropped** (rank ~48-49, worse than before fix #8). Root cause:
`_top_k_mean(scores, k=3)` in `query_router.py` averages the top-3 files' scores. A
large subsystem with 100 files only ever shows its best 3 (hides 97 weak ones); a
cluster with EXACTLY 3 files must average all 3, weak ones included — even though
`catalog_endpoint.go` alone still scores 0.4998, the highest of any individual file in
the whole repository (re-confirmed exactly, byte-for-byte, this session — determinism
check passed).

**Prototyped this session (in a standalone script, `query_router.py` never touched):**
replaced the flat top-3 mean with a rank-weighted mean (`decay**i` weights, i.e. the
best file counts fully, the 2nd/3rd count less) and swept the decay parameter:

| decay | winner | target (`agent/consul::catalog`) rank | target score |
|---|---|---|---|
| 0.0 (pure max, no averaging at all) | `agent/structs::catalog` (0.888) | 5 | 0.758 |
| 0.3 | `agent/structs::catalog` (0.888) | 16 | 0.733 |
| 0.5 | `test/integration/.../libs` (0.879) | 28 | 0.686 |
| 0.7 | `test/integration/.../libs` (0.879) | 37 | 0.635 |
| (current, flat top-3 mean) | — | 49 | 0.577 |

The penalty is real and rank-weighting demonstrably helps (49→5 at the extreme), but
**even fully removing the averaging penalty (pure max) still doesn't make the target
win** — `agent/structs::catalog` beats it outright regardless of decay. So this
aggregation fix, however it's finally tuned, is necessary but not sufficient by
itself. Not yet landed (needs a decay choice + the full 62-test/5-repo sweep before
any commitment, per convention) — **still Consul's first open item**.

**New finding this session: why `agent/structs::catalog` competes so well, and it's
not simply "wrong."** `agent/structs/catalog.go` (64 tokens, stays whole — under the
`_MAX_SYMBOLS_PER_FILE_DOCUMENT=8` split threshold) genuinely defines the catalog
registration data structures, with real doc comments mentioning "consul"/"catalog"/
"service" — a topically adjacent, defensible file, not a false match. Meanwhile the
real target file's best-matching scoring unit isn't the whole `catalog_endpoint.go`
file — it's `Catalog#78` (the RPC-handler struct itself), because fix #3 splits any
file with >8 top-level symbols into one unit per symbol, and `catalog_endpoint.go` has
13. That unit is only 24 tokens once isolated by splitting, so fix #5's length-
confidence dampening (`min(1, tokens/30)`) knocks its score down to 80%. `agent/
structs/catalog.go`, staying whole at 64 tokens, gets zero dampening. **Two
independently-correct fixes (#3's per-symbol splitting, #5's small-document distrust)
interact badly here**: a receiver struct's own scoring unit is inherently going to be
small once isolated by splitting, regardless of how substantial or central that type
is to the file's real purpose — length-confidence dampening can't currently tell "this
is small because splitting isolated one legitimate piece" apart from "this is small
because it's genuinely sparse/trivial" (the case fix #5 was built for). **This is
Consul's second open item, unstarted** — needs its own careful investigation (likely:
should length-confidence apply differently, or with a different threshold, to a
symbol-split unit vs. a whole-file unit) before touching any code; do not conflate it
with the top-K-mean item above, they're independent causes.

**Both items were still open when fix #9 landed. Re-diagnosed again after fix #9,
and it made the target's own score WORSE, not better — a third, distinct cause
surfaced:** `Catalog#78` (the target's own best-matching unit)'s `usage_count` dropped
from 33 to **10** once fix #9's locality filter removed the name-collision inflation —
a more accurate count, but now below fix #6's `_MIN_CALLS_FOR_FULL_CONFIDENCE=20`
threshold, so it gets dampened to 50% confidence, roughly halving the target's own
score (0.4998→0.2499). Re-ran the rank-weighted top-K sweep with fix #9's corrected
numbers: even pure max (decay=0.0) now only reaches rank 42 (was rank 5 before fix #9
— the fix made this specific query harder, even though it was a net-positive,
verified-correct change overall). **Root cause: `Catalog#78` is a Go RPC endpoint,
dispatched by Consul's RPC framework via a name/reflection registration table, not
via direct static calls** — so its real invocation is structurally invisible to
static call-graph analysis, and any real caller count for it will legitimately look
low no matter how accurate the counting gets. This is a different problem from
"noisy/inflated count" (which fix #9 correctly solved) — it's "genuinely low count for
a reason usage-confidence dampening can't distinguish from real disuse." No safe fix
identified: recognizing an RPC handler would mean pattern-matching a naming/receiver
convention, in tension with DRP's own "zero hardcoded concept dictionaries" constraint.
Also confirmed (re-ran with current, fixed code) that the subsystem now beating
`agent/consul::catalog` outright is `agent/cache-types::catalog` (0.9041) — a real,
topically-legitimate cluster of catalog read/cache-query implementation files
(`catalog_service_list.go` etc., the single highest-scoring FILE in the whole repo at
0.4721), not noise. **Not the same simple picture as before — Consul's failure is now
three layered, independently-caused issues (top-K-mean; fix #3/#5 split-unit
dampening; RPC-dispatch invisibility to CallGraph), and the codebase itself has
multiple genuinely plausible, semantically-adjacent files/subsystems (registration
endpoint, struct definitions, cache-query implementations) all legitimately sharing
"catalog"/"service"/"agent" vocabulary — this last part matches the same structural
ceiling described for vLLM in §8.** Nothing implemented; both prior items remain
diagnosed-only, and this third cause is diagnosed-only too. Recommend treating Consul
as a deeper, dedicated future investigation rather than an incremental patch target.

## 8. vLLM, diagnosed 2026-08-09 (follow-up session, first real diagnosis since fixes #7/#8/#9)

The previously-documented blocker (`examples/disaggregated`) was stale — re-ran fresh
and the picture is different now.

**The winning subsystem is a real, topically-legitimate competitor, not noise.**
`vllm/distributed/kv_transfer/kv_connector/v1/mooncake` (combined=0.9000) is the
distributed KV-cache-transfer subsystem — genuinely dense with "memory"/"cache"/
"batch" vocabulary, since it moves KV cache blocks between machines. Its own top
file, `mooncake/store/worker.py` (0.7025), is the single highest-scoring file in the
ENTIRE repo on this query. There's even a literal name collision: `mooncake/store/
scheduler.py` exists alongside the real target `vllm/v1/core/sched/scheduler.py`.

**The real target's subsystem (`vllm/v1/core`) sits at rank 7 (combined=0.7508)** —
a genuine ~17% gap behind the winner, nowhere near the 3% near-tie margin. `vllm/v1/
core` wasn't split further by taxonomy (only 15 files, under the `_MAX_FILES_PER_
SUBSYSTEM=50` threshold), so `sched/scheduler.py` competes directly against sibling
KV-cache-manager files in the same flat node — and doesn't even win THERE:
`sched/interface.py` (the abstract Scheduler interface, 0.4837) outscores the
concrete implementation (`sched/scheduler.py`, 0.2923), plausibly because an
interface's own docstring states the concept ("decide which request to run/pause")
more directly than the implementation's code does.

**Same structural ceiling as Consul, not an isolated bug:** three repos in a row
(Traefik's vocabulary-extraction gap in a lexically-dense area, Consul's genuinely-
competitive catalog/service files, vLLM's genuinely-competitive KV-cache/memory/batch
files) now land on the same underlying limit — bag-of-words TF-IDF cannot cleanly
separate architecturally-distinct concerns (local scheduling/eviction vs. distributed
transfer vs. attention computation, in vLLM's case) when they legitimately share
vocabulary, without embeddings-level semantic understanding DRP is constitutionally
built not to use. Not something to chase with another incremental patch — flagging as
a fundamental, known limitation of the approach rather than a bug queue item.

## 9. Falsification experiment: project-local qualified-identifier indexing (2026-08-10)

**Purpose (user's own framing, verbatim intent):** test, without trying to make it
succeed, whether "some target files are lexically underrepresented in the index" is
the actual root cause of Issue #3's retrieval failures — not build a feature. One
variable only: a low-weight, PROJECT-LOCAL (never stdlib/third-party) qualified-
identifier field, added in parallel to the real corpus, never modifying DRP logic,
subsystem aggregation, or confidence propagation.

**Blocker found before the experiment could even run:** "project-local" detection
needs `ImportReference.resolved_file_path`, which turned out to be effectively
non-functional — **fixed as fix #13 above** (Go: 0→1,361/5,931 resolved). Without that
fix, this experiment would have silently measured almost nothing for Traefik/Consul.

**Isolation:** implemented entirely in a new, standalone script,
`arcf/scripts/qualified_id_falsification.py` — reads `gather_scoring_units`,
`build_tfidf_index`, `route_query`, and `DrpIndexBuilder` but never modifies any of
them. Baseline = the real, unmodified `DrpIndexBuilder.build()` output. Experimental =
the same `unit_usage`/`file_to_units`/taxonomy/subsystem_graph, with one additional
per-file text field (deduplicated `qualifier.member` pairs whose qualifier resolves
locally via imports) appended before calling the same `build_tfidf_index`. Both
conditions are then run through the real, unmodified `route_query` (Stage 4) so the
comparison reflects actual subsystem/community/taxonomy aggregation, not just raw
per-file cosine similarity — nothing in `text_corpus.py`/`tfidf.py`/`query_router.py`
was touched by this experiment.

**Results (full detail in `docs/drp_benchmark_data/qualified_id_falsification.json`):**

| repo | lexical rank (base→exp) | in final candidates | noisy files newly in routed candidates |
|---|---|---|---|
| Traefik | 52 → 48 | False → False | 1 (`kubernetes_test.go`) |
| Consul | 27 → **48** (regressed) | False → False | 0 (moot — never retrieved either way) |
| SQLAlchemy | 2 → **1** | True → True | 1 (`test/orm/test_events.py`) |
| Django | 3 → **1** | True → True | 0 |
| vLLM | 106 → 110 | False → False | **14** — entire winning subsystem flipped to `tests/v1/core` |

**Verdict against the user's own explicit success criteria: does not survive.**
Consul regressed (violates "Consul does not become worse"). vLLM's candidate list was
flooded with test/benchmark files despite graph-locality/community/taxonomy weighting
(violates both "ambiguous candidates do not increase significantly" and "precision
remains stable"). Graph-locality dampening held perfectly for Django, held partially
for SQLAlchemy/Traefik (1 noisy candidate each), and failed completely for vLLM — no
predictor found yet for which repos it protects.

**The decisive finding, more important than any single regression:** Traefik — the
repo whose own documented lexical gap ("dynamic" missing from `configurationwatcher.
go`'s vocabulary, see §5) directly motivated this entire idea — barely moved (52→48)
and never once reached retrieval in either condition. The two repos that DID improve
(SQLAlchemy, Django) had no comparable documented lexical gap going in. **This
inverts the expected result if "lexical incompleteness" were really the dominant root
cause of Issue #3** — closing the gap should have helped the repo with the gap the
most, not the least. This is stronger evidence against the lexical-incompleteness
hypothesis than the regressions are evidence against the mechanism itself.

**Recommendation (matches the user's own read after reviewing this report):** do not
carry this forward as the foundation for a Behavioral Semantic Index or any other
larger architectural extension as currently scoped. The pattern looks repo-structure-
dependent (how tightly test files are graph-connected to production code; how
concentrated a project's own vocabulary already is) rather than a general lexical
fix — and the falsification's own strongest signal is that it didn't even solve the
case it was built for. Any future revival of this idea should start by explaining
Traefik's non-response, not by re-tuning the noise-suppression side.

**Script is a reusable falsification harness**, not a one-off: `--repo NAME` to run
just one, or no argument for the full 5-repo sweep. Re-run it fresh rather than
trusting these numbers if the underlying corpus/text_corpus.py/tfidf.py changes.

## 7. Conventions to preserve

- **Determinism is non-negotiable** — every new module follows the existing
  "sorted iteration, lexicographic tie-break" discipline from `call_graph.py`'s
  `_layered_bfs`. Verify with a `test_..._is_deterministic` test for anything new.
- **Constants get an empirical-justification comment citing the real repo/number**
  that motivated them (e.g. `_MAX_FILES_PER_SUBSYSTEM = 50` cites Traefik's working
  27-file `pkg/server` vs. SQLAlchemy's broken 255-file `lib/sqlalchemy`). Don't add a
  tuning constant without real numbers behind it — check with a quick diagnostic
  script against the actual repo first (see the many `uv run python -c "..."`
  one-liners used throughout this session for the pattern).
- **Root-cause before fixing** — every fix this session started with a diagnostic
  script inspecting real `subsystem_scores`/file scores/token counts before writing
  any code. Don't guess at why something is winning; verify it.
- **Isolation** — never edit `context_resolver.py` or the five classic graph classes.
  New DRP mechanisms get their own module or an additive field, never a modification
  to already-stable DRP code's core contract without re-running the full 62-test DRP
  suite plus the 5-repo benchmark sweep.
- **Run the full suite, not just DRP's**, before/after any change:
  `uv run pytest -q` from `arcf/` (805 passing as of this doc, updated 2026-08-09/10
  follow-up session — fixes #9-#13 added 8 new tests total).
