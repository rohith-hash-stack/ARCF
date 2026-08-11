# ARCF 50-Repo / 200-Query Evaluation Sweep

Source fixture: `llm_repository_test_fixture_batch_3.docx` (50 public repos x
4 queries each = 200 queries, spanning explanation/tracing/debugging/
refactoring/implementation/performance/testing tasks).

Methodology: each repo is shallow-cloned, all 4 queries run through
[scripts/repo_query_answer.py](../../scripts/repo_query_answer.py) with
`--resolver both` (classic and DRP each produce a full LLM-generated
answer, not just retrieval diagnostics), the per-query JSON output is kept
in this directory, any issue found is fixed (with a regression test) before
moving to the next repo, and the clone is deleted afterward. Full test
suite (`uv run pytest tests/ -q`) is run after every fix.

Prerequisite work before this sweep started: added `CppLanguageAnalyzer`
([cpp_analyzer.py](../../src/code_intelligence/languages/cpp_analyzer.py))
and `RustLanguageAnalyzer`
([rust_analyzer.py](../../src/code_intelligence/languages/rust_analyzer.py))
to unblock the ~20 repos in this fixture with no prior C/C++/Rust analyzer
support, and built `scripts/repo_query_answer.py` since the existing
`drp_benchmark.py` requires a known `--target-file` these open-ended
queries don't have.

Baseline test count at sweep start: 852/852 passing.

## Fix #3: DRP confidence metric measured repo size, not decisiveness

**User's framing**: rather than trying to make DRP more accurate on particular
codebases (already explored and closed out — see
[[arcf_drp_issue3_experiment]]), optimize for *stability across repository
archetypes*: predictable, graceful degradation under ambiguity instead of
confidently asserting a wrong subsystem.

**Root cause**: `query_router.py`'s `winning_confidence` was
`winner.combined_score / sum(every subsystem's combined_score)` — the
winner's share of TOTAL score mass across the whole taxonomy. This scales
with how many subsystems a repo happens to have, not with how decisively
the winner beat the runner-up. A large repo (gvisor: many packages) divides
even a landslide win across dozens of denominators, so the reported
"confidence" stays near zero regardless of whether the pick is excellent or
wrong. Verified with real numbers: gvisor's best DRP answer in this sweep
(Q2, FUSE trace, 6/6 signatures byte-exact) and one of its worst (Q4, wrong
file entirely) both reported confidence 0.00 — numerically indistinguishable.

**Fix**: replaced it with a margin-based metric — the normalized gap between
the top-2 subsystems' own `combined_score`, i.e. how decisively #1 beat #2,
independent of taxonomy size. This is the SAME quantity `_NEAR_TIE_MARGIN`
already used internally for near-tie file inclusion, just finally surfaced
as the reported confidence instead of a disconnected number. Also updated
`resolution_reason`'s wording: a near-tie now says "ambiguous... treat this
as low-confidence" instead of the old "resolved subsystem X" phrasing that
implied certainty regardless of the actual internal signal.

**Falsification-tested against DRP's own 5 ground-truth benchmark repos**
(`docs/drp_benchmark_data/*.json`, from the closed Issue #3 experiment — 2
Python, 2 Go, 1 more Python, so already cross-language) via
[scripts/drp_confidence_calibration_experiment.py](../../scripts/drp_confidence_calibration_experiment.py),
a read-only recomputation from already-saved routing data (no repo re-cloned):

| Repo | Verdict | Old confidence | New margin confidence |
|---|---|---:|---:|
| django | PASS (decisive) | 0.0105 | **0.1246** |
| sqlalchemy | PASS (genuine near-tie, happened to land right) | 0.0376 | 0.0060 |
| traefik | FAIL | 0.0229 | 0.0095 |
| consul | FAIL | 0.0017 | 0.0017 |
| vllm | FAIL | 0.0044 | 0.0145 |

Old metric ranked Traefik (a confirmed-wrong resolution) ABOVE Django (the
one clean, correct, decisive case) — backwards. New metric puts Django 8x
above every other repo, correctly isolating the one case with a genuinely
one-sided win. SQLAlchemy scoring low despite being correct is intentional,
not a miss: its ORM code and paired test directory are genuinely close
competitors — the metric reports the resolver's own internal decisiveness,
not a prediction of ground truth, so honest low confidence on a lucky-but-
ambiguous pick is correct behavior.

**Live spot-check against a real repo** (googletest, resolver-only, no LLM
needed): the exact same winning file (`googletest-listener-test.cc`) won
two different queries — one where it was a weak/incidental match, one where
it was genuinely the right answer. Old metric: 0.05 vs 0.08 (indistinguishable).
New metric: **0.04 vs 0.33** — an 8x spread that actually tracks fit quality
for the identical file.

**Verified universal, not repo/language-specific**: the change lives entirely
in DRP's scoring/routing layer (`query_router.py`), several layers above any
language-specific parsing — it doesn't reference language, file type, or
any repo-specific concept anywhere. Ground truth spans Python and Go repos
from the closed experiment; the live spot-check adds C++. Tests: 6 new
(3 in `test_query_router.py`, 2 in `test_drp_resolver.py`, covering decisive/
near-tie/no-signal cases), 858/858 full suite passing, zero regressions.

**Explicit scope limits (not solved by this fix)**:
- Does not fix DRP's underlying TF-IDF disambiguation ceiling — Traefik/
  Consul/vLLM may still pick the wrong subsystem. The goal was narrower:
  when DRP is uncertain, it now says so predictably instead of masking
  uncertainty behind a meaningless number.
- Does not detect "nothing in the repo matches this query at all" as
  numerically distinct from "top pick barely beat #2" — `combined_score`
  is itself normalized to the observed maximum, so the winner's raw score
  stays in a narrow high band (~0.85-0.93) regardless of true relevance,
  only ever collapsing to exactly zero when literally everything scored
  zero. Detecting a genuine "weak signal everywhere" case would need the
  pre-normalization scores, not `combined_score` — flagged as a real gap,
  not silently assumed covered.
- Small ground-truth sample (5 repos + 1 live spot-check). Suggestive and
  internally consistent, not a large-scale statistical proof.

## Fix #2: test-harness prompt was over-restrictive (not an ARCF bug)

**Reported by the user**: when ARCF's retrieval found no relevant files, it
answered "I don't have enough context" while the direct-LLM baseline
(no context at all) confidently gave a full answer — defeating the whole
point of using ARCF, since a real user would rather get a good answer than
an honest refusal.

**Root cause — but NOT in ARCF's production code**: `scripts/
repo_query_answer.py`'s original hand-rolled prompt told the model
*"using ONLY the source files provided... say so explicitly rather than
filling in from general knowledge"* — copied from
`direct_vs_arcf_conceptual_query.py`, a prior script deliberately built to
**isolate retrieval quality** by preventing the model from "cheating"
with training knowledge. That instruction is appropriate for an isolation
experiment; it is **not** how ARCF's real production prompt works.
`execution/context_goal_composer.py`'s actual `ContextGoalComposer`
template (Phase 8, the real "final generation" prompt) never forbids
general knowledge — it just presents the deterministically-selected
context and asks for the best answer in whatever form fits. So the
"ARCF looks worse than direct" behavior the user observed was an artifact
of my own test harness's prompt choice, not a defect in ARCF itself.

**Fix**: rewrote `repo_query_answer.py` to call ARCF's REAL production
classes instead of a hand-rolled prompt — `context.packager.
ContextPackager` for packaging and `execution.context_goal_composer.
ContextGoalComposer` + `execution.final_generation.FinalGenerationRunner`
for prompting/generation, exactly what the app's own /contracts pipeline
would use. Full test suite: 853/853 (no test coverage changes needed —
this only affects the diagnostic script, not ARCF's own tested classes).

**Verified**: regenerated all 12 stored query results (repos 1-3) with the
fixed pipeline. Every previously-hedging case (googletest Q1 classic,
flatbuffers Q1 classic+DRP, flatbuffers Q4 classic+DRP) now produces a
full, substantive answer instead of a refusal — e.g. googletest Q1
classic went from *"The internal mechanism... is not detailed explicitly
in the files provided... I cannot provide a more detailed explanation"*
to a full explanation incorporating both general GoogleTest knowledge AND
real grounded specifics from the retrieved files (`ExplainMatchResult`,
`ParseGoogleMockFlag`, `MatchPrintAndExplain`). Zero errors across all 12
regenerated results. Viewer artifact and all JSON files in this directory
now reflect the corrected pipeline.

**Scope note**: this does NOT fix underlying retrieval-quality gaps (e.g.
googletest Q1's Tier-1 "Explain" collision, still causing gmock-matcher
files to outrank the actual test-registration engine) — those are
separate, already-documented, accepted heuristic tradeoffs. What this
fixes is specifically the failure mode of ARCF producing a bare non-answer
in cases where a plain LLM call would have said something useful — ARCF's
answer now never regresses below what direct-LLM-with-no-context would
say, even when retrieval is imperfect, because it can supplement weak
context with general knowledge exactly like a real engineer would while
still preferring grounded specifics when they're available.

## Answer-content validation pass (2026-08-10)

Beyond retrieval-quality assessment (which repo-by-repo log entries below
already cover), every concrete, falsifiable claim in all 12 stored
Classic/DRP answers (repos 1-3, pre-Fix-#1) was individually checked
against the real cloned source — function/struct/class names, line
numbers, verbatim error-message strings, method signatures — by
re-cloning each repo and grepping/reading the exact referenced location.
This is validating **answer content accuracy**, a different axis from
retrieval quality (a correctly-retrieved file can still be described
inaccurately, and vice versa).

**Result: 4 confirmed inaccuracies found out of dozens of individually
verified claims across 12 queries** (~30+ specific facts checked: function
names, line-number ranges, verbatim error strings, struct definitions).
The large majority of claims were exactly correct, several down to
line-number ranges off by 0-2 lines. None of the 4 found issues are ARCF
resolver/pipeline bugs — all four are LLM generation-layer inaccuracies
(the model describing/writing code slightly wrong even when given
correct, sufficient context), a different failure class from Fix #1
(which was a retrieval bug). Not something fixable in ARCF's Python code;
recorded as a distinct, real answer-quality risk category.

1. **googletest Q4, DRP** — fabricated a non-existent constructor
   `TestEventListener(listener)` (the real class has no such constructor,
   only an implicit default one) — despite the correct real pattern
   (`EventRecordingListener(const char* name)`) being directly present in
   DRP's own retrieved context. The clearest case: an outright invented
   API that would not compile.
2. **gvisor Q2, Classic** — invented the struct name `FilesystemImpl` for
   `pkg/sentry/fsimpl/gofer/filesystem.go`; the real (unexported) struct
   is just `filesystem`. Plausible-sounding but wrong name, not read
   directly off the packaged file content.
3. **gvisor Q3, Classic** — dropped `sentry/` when citing the path
   `pkg/sentry/seccheck/scsdk/client.go` in prose (wrote
   `pkg/seccheck/scsdk/client.go`) — the struct itself (`SandboxClient`)
   is real, just the cited path was garbled.
4. **gvisor Q3, Classic** — attributed `CreateSandbox`/`StartSandbox`
   methods to `SandboxClient`; those methods are real but actually belong
   to a different struct (`shimRedirector`) in a different packaged file
   (`pkg/shim/v1/service.go`) — a cross-file conflation.

Every other checked claim across all 12 queries was accurate, including
highly specific ones (e.g. classic's googletest Q2 line-range claims for
`TypeParameterizedTest::Register`, `TestSuite::TestSuite`, and
`HandleExceptionsInMethodIfSupported` were each within 0-2 lines of the
real definition; DRP's flatbuffers/gvisor answers reproduced exact method
names like `__offset`/`__indirect`/`__vector_len`, `hostConnection`'s
`writeRequest`/`readLoop`/`abortPending`, and `CgroupRegistry`'s
`Register`/`FindHierarchy` including a verbatim error string, all
character-for-character correct).

## Status

| # | Repo | Language(s) | Queries run | Issues found | Issues fixed | Status |
|---|------|-------------|:---:|:---:|:---:|---|
| 1 | [googletest](https://github.com/google/googletest) | C++ | 4/4 | 0 | 0 | Done |
| 2 | [flatbuffers](https://github.com/google/flatbuffers) | C++ | 4/4 | 1 | 1 (universal, [details](#fix-1-anchor-classifier-tier-3-scan-order-cap)) | Verified fixed |
| 3 | [gvisor](https://github.com/google/gvisor) | Go | 4/4 | 0 | 0 | Done, re-verified post-fix |

## Fix log

### Fix #1: anchor_classifier Tier-3 scan-order cap

**Found in**: flatbuffers Q1. **Root cause**: `context/anchor_classifier.py`'s
`classify_symbol_anchors` (Tier 3, the lexical/prefix-substring probe used
by the default `enable_anchor_classification=True` configuration every
script in this repo treats as "final validated") called
`context/lexical_symbol_probe.probe_symbol_names` — which fills its
`_MAX_MATCHED_NAMES = 20` cap in raw `SymbolIndex.all()` scan order, an
accident of file-scan order with no relevance judgment at all. A
already-built, already-validated alternative,
`probe_symbol_names_ranked` (ranks eligible names by how many *distinct*
query-word-prefixes they match, then by ambiguity ascending, before
capping), existed in the same file and was proven on a real SQLAlchemy
regression — but it was only reachable via a separate, narrower
experimental flag (`enable_ranked_seed_selection`) that has **no effect**
whenever `enable_anchor_classification=True`, i.e. never, in practice.

**Why this is universal, not FlatBuffers- or C++-specific**: the fix is a
one-line swap in a single, language-agnostic shared function
(`classify_symbol_anchors`) called identically for every analyzer/language
in this codebase — it does not touch, know about, or special-case any
language, repo, or naming convention. The failure mode itself (many
same-rooted candidate names crowding out a more relevant one purely by
scan order) is structural, not language-specific: it recurs for any
"one-class-per-X" naming pattern (per-language codegen backends, per-
protocol handlers, per-database drivers, per-cloud-provider clients, etc.),
which is common well beyond FlatBuffers.

**Fix**: `anchor_classifier.py` now imports and calls
`probe_symbol_names_ranked` instead of `probe_symbol_names` for Tier 3.
One line changed at the call site, plus the module docstring/import.

**Falsification test** (`tests/context/test_anchor_classifier.py::test_tier3_prefers_multi_prefix_match_over_scan_order`):
25 noise symbols matching one query-word prefix precede, in scan order, a
single symbol matching two — reproduces the exact FlatBuffers shape in an
isolated, deterministic unit test. **Confirmed failing before the fix**,
**confirmed passing after**.

**Full suite**: 853/853 passing after the fix (852 baseline + 1 new test),
zero regressions.

**Verified against the real repos, resolver-only (no LLM re-run needed —
this is deterministic Python, not LLM output)**:
- flatbuffers Q1: candidate files went from **zero** real compiler-source
  files (only Gradle/CI/README noise) to **9 real compiler-source files**
  including `src/idl_parser.cpp`, `src/idl_gen_json_schema.cpp`,
  `src/code_generators.cpp`, `src/flatc_main.cpp`. (Note: the top-ranked
  Tier 3 names turned out to be `GenerateFromSchema`/`JsonSchemaGenerator`/
  `NewJsonSchemaCodeGenerator` rather than `CppGenerator` specifically —
  these match TWO of the query's distinct words ("schema" + "generate"),
  which is a more principled match than `CppGenerator`'s one-word overlap
  with 49 other same-rooted `*Generator` siblings in this repo. The fix
  surfacing real compiler files at all, even if not the exact file
  originally guessed, confirms it's working as designed, not coincidence.)
- Re-ran all 4 googletest + all 4 gvisor queries (resolver-only, 8 cases,
  zero LLM calls) to check for regressions on the two already-"done"
  repos: zero exceptions, candidate sets stayed sensible, and gvisor Q4
  ("refactor a syscall implementation") newly surfaced genuinely relevant
  files (`pkg/hostsyscall/hostsyscall.go`, `pkg/abi/sentry/syscall.go`) it
  had NOT found before the fix — a second, independent confirmation the
  fix generalizes rather than overfitting to flatbuffers.

## Repo-by-repo log

### 1. googletest — C++

All 4 queries run through `--resolver both` (8 pipeline runs total), zero
exceptions, zero crashes. Full per-query JSON: `googletest__*.json` in this
directory.

- **Q1** ("Explain how GoogleTest discovers and executes individual test
  cases internally.") — classic retrieved mostly README/doc files and gave
  an honest "not detailed in what I have" answer rather than fabricating;
  DRP retrieved `googletest-listener-test.cc` (confidence 0.05, i.e. DRP
  itself flagged this as a weak match) and gave a plausible but
  under-grounded answer. **Investigated, not a defect**: classic's Tier-1
  anchor classifier promoted the query's own word "Explain" to an exact-
  match anchor (confidence 1.0) because GoogleMock genuinely defines a
  helper literally named `Explain(matcher, value)` (verified by grepping
  the clone) — a real, if here-irrelevant, symbol collision with the
  query's instructional verb. `anchor_classifier.py`'s own docstring
  explicitly rejects adding a task-verb stopword list for exactly this
  reason (would overfit to one query phrasing style) — this is an
  accepted, documented tradeoff of the existing heuristic, not a bug.
- **Q2** (parameterized-test overhead) — classic found real, on-point
  files (`TypeParameterizedTest::Register`, `TestSuite`'s setup/teardown,
  `HandleExceptionsInMethodIfSupported`) and gave a strong, well-cited
  answer. DRP again landed on `googletest-listener-test.cc`
  (low-confidence) with an honest "this file doesn't answer that" response.
- **Q3** (refactor a matcher to dedupe failure-message formatting) — both
  resolvers found strongly relevant matcher files; DRP's answer proposed a
  concrete, idiomatic refactor.
- **Q4** (add a duration/status test listener) — DRP correctly identified
  `googletest-listener-test.cc` as the on-point file this time (it's
  directly about listeners) and produced an excellent, concrete
  implementation sketch.
- Apparent "same file for two different queries" (Q1 vs Q2, both DRP) was
  checked and is coincidental low-confidence fallback, not a determinism
  bug — Q3/Q4 each returned different, query-appropriate files.
- One apparent data-corruption finding (a `'` in Q3's DRP answer rendering
  as `�` in my terminal) was investigated and is a false alarm: the stored
  JSON correctly contains U+2019, confirmed via direct codepoint
  inspection — a terminal/console display limitation, not a pipeline bug.

**Conclusion**: no code changes required for this repo. DRP's weak
confidence on queries with no strong lexical/entity signal (Q1, Q2) is a
known, previously-documented characteristic (see `arcf_drp_issue3_experiment`
memory), not a new regression.

**Direct-LLM baseline** (added retroactively after this repo, backfilled):
for Q1, the direct (no-context) answer is detailed, confident, and
plausible purely from the model's training data — GoogleTest is an
extremely well-documented, famous project, so this is expected, not a
finding specific to ARCF. Notably, direct's answer sounded MORE confident
than classic's (which correctly hedged "not detailed in the files
provided" rather than fabricating) even though classic's hedge is the
more honest response given what it actually retrieved. This is worth
watching across the sweep: for famous repos, a good-looking classic/DRP
answer isn't proof of correct retrieval unless it cites specifics the
direct answer couldn't have guessed, and a low-confidence DRP retrieval on
famous repos will tend to lose head-to-head against direct's confident
recall, precisely where a full-pipeline evaluation is least informative
about ARCF's own retrieval quality.

### 2. flatbuffers — C++

All 4 queries run through `--resolver both` + direct baseline (12 pipeline
runs total), zero exceptions, zero crashes.

- **Q1** (schema -> generated code architecture) — neither resolver
  surfaced the actual compiler source (`src/idl_gen_cpp.cpp`, containing
  `flatbuffers::cpp::CppGenerator`, confirmed present and parses cleanly:
  117 symbols, 0 parse errors via a direct analyzer smoke test). Classic
  fell back to Gradle/CI config files; DRP landed on unrelated TypeScript
  test fixtures (confidence 0.01).
  - **FIXED** — see [Fix #1](#fix-log) above. Root cause: `anchor_classifier.py`'s
    Tier 3 used the unranked `probe_symbol_names`, which hit its
    `_MAX_MATCHED_NAMES = 20` cap in raw scan order — FlatBuffers' one-
    class-per-target-language pattern (`CppGenerator`/`JavaGenerator`/
    `GoGenerator`/... 50 total "generator-ish" names) meant 20+ eligible
    names existed, and scan order excluded the most relevant ones before
    the cap was reached. Swapped to the already-built, already-validated
    `probe_symbol_names_ranked`. Verified against the real repo: went from
    zero real compiler-source candidates to 9 (`idl_parser.cpp`,
    `idl_gen_json_schema.cpp`, `code_generators.cpp`, `flatc_main.cpp`,
    etc.). Regression-checked against googletest and gvisor (see Fix #1)
    with no negative impact and one incidental improvement (gvisor Q4).
- **Q2** (zero-copy access) — both resolvers found real generated-code
  accessor patterns (`__offset`/`__vector`/`__indirect`) and gave a
  correct, well-grounded explanation, just from generated-output files
  (Kotlin/Java) rather than the runtime library source that implements
  those accessors generically — still a reasonable, honest answer.
- **Q3** (debug nested-table accessor bug) — classic packaged an unrelated
  generated file (`NestedStructT.java`) with no nested-table logic in it;
  the answer correctly and explicitly said the provided file didn't
  contain enough information rather than fabricating a diagnosis — good
  failure-mode behavior even though retrieval missed.
- **Q4** (add a CLI schema-validation diagnostic flag) — both resolvers
  honestly reported the packaged files didn't contain command-line-option
  handling, rather than fabricating an answer.

**Conclusion**: one real, pre-existing (not introduced by this session)
resolver-recall bug found, root-caused, and fixed universally (Fix #1) —
Q1's retrieval is now dramatically better against the real repo. Q2-Q4's
observations are the pipeline correctly declining to fabricate when
retrieval genuinely missed, which is the desired failure mode, not a bug.
Note: Q1-Q4's actual answer text/JSON files in this directory predate the
fix (not re-run yet, pending API token) — this log reflects fresh
resolver-only re-verification, not stale JSON.

### 3. gvisor — Go

All 4 queries run through `--resolver both` + direct baseline (12 pipeline
runs total), zero exceptions, zero crashes. Notably strong results on this
repo — the first Go-language repo in the sweep (no new analyzer needed,
Go support predates this session).

- **Q1** (syscall/host-kernel separation) — classic correctly identified
  the Sentry (user-space kernel) / Gofer (9P filesystem proxy)
  architecture, grounded in actual README content. DRP found a real but
  narrow file (`pkg/sentry/syscalls/linux/error.go`) and correctly hedged.
- **Q2** (filesystem operation trace) — excellent, deeply-grounded answer
  citing real structs/methods (`hostConnection`, `readLoop`,
  `writeRequest`, FUSE plumbing in `host_connection.go`/`fusefs.go`) — this
  is retrieval working as intended.
- **Q3** (startup-time regression with many mounts) — classic identified
  `CgroupRegistry`/`FindHierarchy`/lock contention as plausible overhead
  sources — reasonable, grounded hypothesis for a performance
  investigation query.
- **Q4** (refactor syscall validation logic) — classic produced a concrete
  `validateSyscallArgs` extraction proposal; DRP landed on a
  documentation/formatting file and correctly declined to fabricate.

**Conclusion**: no code changes needed. This repo shows the pipeline
performing well across all 4 query types when working in an already-mature
language (Go) on a well-organized codebase.
