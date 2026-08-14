# ARCF-DI Progress Log

**Last updated:** 2026-08-14 · **Branch:** `arcf-di/feature/phase3-mandatory-disambiguation` (off `arcf-di/base`) · **Tests:** 987/987 passing (977 prior + 10 new) · **Status:** Phase 3a (mandatory disambiguation, opt-in) shipped.

Read this file top-to-bottom to pick up where things stand — the fast-start doc for a new session, same convention as the parent project's `arcf/PROGRESS.md`. Detailed design lives in `arcf-di/docs/BLUEPRINT.md`; this file is the curated *what/when* summary, updated after each phase lands.

## How this project is organized

- **`arcf-di/base`** — ARCF-DI's own consolidated checkpoint branch, scoped under the parent `arcf` repo. Every finished phase merges here.
- **`main`** — the parent repo's main branch; `arcf-di/base` fast-forwards into it only once a phase is green (its Phase 9 validation suite passing for that phase's scope).
- **Child branches** (`arcf-di/experiment/...`, `arcf-di/fix/...`) — one per bug fix or experiment, branched off `arcf-di/base`, merged back only once resolved. Never left half-done on `arcf-di/base`/`main`.
- Scope is frozen to `code_intelligence/`, `context/`, and the `domain` IR only. `execution/`, `contracts/`, and `telemetry/` are explicitly out of scope — a CI import-lint enforcing that boundary is scheduled at Phase 10, step 10.
- Core rule, unconditionally: *the SLM may compress evidence, but it may never create evidence* — scoped to indexing and retrieval, not to `execution/final_generation.py`.

### 2026-08-13 — Scope frozen; 11-phase implementation blueprint drafted (Phase 0 complete)

Reviewed ARCF's actual codebase (not just the target architecture) against the proposed ARCF-DI design across three passes: a theoretical critique of a deterministic-indexing-with-SLM-summarization proposal, a verification pass against the real `code_intelligence`/`context`/`execution` modules with file:line citations, and an 11-phase build blueprint mapping every phase to specific existing modules.

**Key confirmed findings from the real codebase** (not assumptions):
- `code_intelligence`'s IR (`domain/code_intelligence.py`) already carries `SourceLocation` provenance on `Symbol`/`CallReference`/`ImportReference`/`DecoratorReference` — the strongest existing asset for Phase 1's evidence schema.
- `reference_resolver.py` resolves by exact-qualified-name then simple-name fallback, **not** type inference (stated in its own docstring, lines 4-9) — the real, previously-reproduced `New()` bare-name collision (460 files attributed to one call site) is direct evidence of the precision gap Phase 3 has to close.
- No repository-vs-external symbol boundary exists today — unresolved calls land in one undifferentiated bucket (`call_graph.py:9-11`). Phase 2's library classifier is genuinely new, not an extension of anything.
- `context/understanding.py` (SLM-2) is the closest existing analog to a summarizer, but is query-scoped (not per-function), best-effort (errors swallowed), and does not pin `temperature` — all four have to change for Phase 5.
- `execution/final_generation.py` is confirmed out of scope: its job is to *create* code, which the core rule structurally forbids for evidence. `contracts/*` and `telemetry/comparison_aggregator.py` isolated for the same reason (request-intake and pipeline comparison, not indexing).
- `CodeIntelligenceIndex` is explicitly documented as non-serializable today (`index.py` docstring) — Phase 8 (persistent index) is real new infrastructure, not a config change.

**Acceptance test adopted for the whole effort**: a byte-identical serialized index across repeated runs against the same commit, with every retrieved fact traceable back to exact source lines. Scoped deliberately: byte-identical is mandatory for the deterministic evidence layer; for SLM-generated prose (Phase 5), content-addressed caching (`record_content_hash + model_version + prompt_version`) substitutes for literal byte-identical text, since `temperature=0` does not guarantee bit-identical LLM output across separate calls.

**Outcome**: no code written yet. `arcf-di/` scaffolded on `arcf-di/base` (branched off `main`) with this file and the full blueprint doc.

### 2026-08-13 — Shipped: Phase 1 (deterministic evidence layer)

On `arcf-di/feature/phase1-evidence-layer` (off `arcf-di/base`): extended `arcf/src/domain/code_intelligence.py` additively per `BLUEPRINT.md`'s Phase 1 schema — nothing here is wired to a producer yet, this phase is the canonical shape later phases populate.

**What landed:**
- Content-derived `id` (`@computed_field`, not an independently-settable field) on `CallReference`, `ImportReference`, `DecoratorReference` — same `file::name#line` scheme `Symbol.id` already used (duplicated per-language-analyzer as `_symbol_id`), namespaced with a type prefix (`call:`/`import:`/`decorator:`) so ids can never collide across evidence types. Verified as a pure function of content, not construction order — see `test_call_reference_id_is_content_derived_and_reproducible`.
- Two new enums (`ImportResolutionKind`, `CallResolutionConfidence`) naming the resolution tiers Phase 2 and Phase 3 will populate — defined now so those phases ship as "populate this existing field" rather than "add a field and change behavior in the same PR."
- `CallReference.resolution_confidence`/`candidates` and `ImportReference.resolved_kind`/`resolved_library` — all default `None`/empty, zero behavior change today. Notably: traced `call_graph.py:28-37` while doing this and confirmed the mechanism behind the `New()` collision precisely — `CallGraph.__init__` adds a real graph edge to **every** candidate `resolver.resolve()` returns, with no record an ambiguous name was ever ambiguous. `candidates` exists so Phase 3 has somewhere to preserve that fact instead of discarding it, as it does today.
- Four new evidence types — `ExternalLibraryReference`, `Route`, `ConfigReference`, `SQLReference` — wired into `FileAnalysis` as empty-default lists, the exact rollout shape `decorators` already established (Phase 7 spike precedent). No analyzer populates any of them yet.

**Verification**: 954/954 tests passing (942 pre-existing untouched + 12 new), `ruff check` and `mypy` clean on the changed files. The 12 new tests include a direct reproducibility check (`test_call_reference_id_is_content_derived_and_reproducible`) — two independently-constructed `CallReference`s with identical evidence produce identical ids regardless of `caller_id`, which is the unit-level form of the "byte-identical index across repeated runs" acceptance test agreed for the whole project.

**Outcome**: PR opened from `arcf-di/feature/phase1-evidence-layer` into `arcf-di/base`, pending merge. No existing consumer of `domain.code_intelligence` types changed behavior — confirmed by the full untouched pre-existing suite staying green.

**Next**: Phase 2 (external-library boundary classifier) per `docs/BLUEPRINT.md`.

### 2026-08-13 — Shipped: Phase 2 (external-library boundary)

On `arcf-di/feature/phase2-library-boundary`, stacked on top of the (still-unmerged) Phase 1 branch since this phase populates the `ImportResolutionKind`/`resolved_kind`/`resolved_library` schema Phase 1 only defined. PR opened against `arcf-di/feature/phase1-evidence-layer`; retarget to `arcf-di/base` once Phase 1 merges.

**What landed:**
- `workspace/dependency_manifest.py` — `DependencyManifestParser`, deterministic per-ecosystem parsing of declared dependencies. Scoped to three ecosystems this phase: npm (`package.json`), pip (`pyproject.toml` — both PEP 621 `[project.dependencies]` and Poetry's table, plus `requirements.txt`), go (`go.mod`, single-line and block `require`). Reuses `PermissionManager.safe_read_text` (never raw `open()`) and `ProjectStructureAnalyzer`'s existing `MANIFEST_FILENAMES` convention for which files to look at; deliberately duplicates (rather than imports) `FrameworkDetector`'s private parsing methods to keep this phase additive-only against a file with existing tests and callers — flagged in the module docstring as a reasonable future consolidation, not done here.
- `code_intelligence/library_boundary.py` — `LibraryBoundaryClassifier`. Classifies each `ImportReference` as `REPOSITORY`/`EXTERNAL`/`STDLIB`/`UNRESOLVED`. Deliberately does **not** re-derive repository-internal resolution: every language analyzer already fills `ImportReference.resolved_file_path` when an import resolves inside the repo, so this classifier only decides the remaining three tiers — same "read, never re-derive" discipline the codebase already applies to that field. Python stdlib detection uses `sys.stdlib_module_names` (the interpreter's own enumeration, not hand-maintained); Go stdlib detection uses the standard "no dot in the first import-path segment" convention, explicitly documented as a heuristic, not a language guarantee; Node built-ins are a static, extend-as-needed set. Go external matching is longest-declared-module-root-prefix (a go.mod `require` typically declares a root, e.g. `github.com/hashicorp/consul`, that real imports are subpackages of, e.g. `.../agent/cache`) with deterministic tie-break.
- Three languages get real EXTERNAL/STDLIB classification this phase (python→pip, typescript→npm, go→go); every other language ARCF supports (java, csharp, kotlin, cpp, rust) has no manifest parser yet and classifies `REPOSITORY` (via `resolved_file_path`) or `UNRESOLVED` — never a guessed `EXTERNAL`, confirmed by a dedicated test (`test_language_without_manifest_support_never_guesses_external`).
- `DeclaredDependency` added to `domain/code_intelligence.py` alongside `ExternalLibraryReference` (Phase 1's placeholder), completing the input/output pair for this phase's classifier.

**Verification**: 977/977 tests (954 prior + 23 new), `ruff`/`mypy` clean on every changed file. One test (`test_library_boundary_integration.py`) is the integration-level form of the project's core reproducibility requirement: parses a manifest and classifies imports twice, independently, against the same synthetic repo, and asserts byte-identical JSON output — same acceptance criterion agreed for the whole project, now with a passing test exercising it end to end rather than only at the unit level (Phase 1's `id`-reproducibility test).

**Known gaps, deliberately left open rather than guessed at**: lockfiles aren't read yet (`CONFIRMED_LOCKED` tier from `BLUEPRINT.md` isn't implemented — every match is `CONFIRMED_RANGE`-equivalent, using the manifest's own declared range); monorepo workspace-internal packages published under their own name aren't special-cased yet (a real gap flagged in `BLUEPRINT.md` Phase 2's edge cases — could misclassify as `UNRESOLVED` rather than `REPOSITORY` today, never as a false `EXTERNAL`, but still a known miss); vendored in-repo library source isn't special-cased.

**Outcome**: PR opened from `arcf-di/feature/phase2-library-boundary` into `arcf-di/feature/phase1-evidence-layer`, pending both merges.

**Next**: Phase 3 (symbol resolution redesign — mandatory disambiguation) per `docs/BLUEPRINT.md`. Note Phase 3's `candidates`/`resolution_confidence` schema fields already exist from Phase 1; this phase is "populate them," not "add them."

### 2026-08-14 — Shipped: Phase 3a (mandatory disambiguation, opt-in via flag)

On `arcf-di/feature/phase3-mandatory-disambiguation` (off `arcf-di/base`, both Phase 1 and Phase 2 now merged). Scoped to 3a only, per `BLUEPRINT.md`'s own incremental rollout — 3b (threading ambiguity end-to-end through `ContextResolutionResult`) and 3c (real type resolution) not attempted.

**What landed:**
- `ReferenceResolver.resolve_tiered` (new, additive) — `resolve()` is now defined in terms of it, identical behavior/signature, every existing caller (including `resolve_with_disambiguation`, untouched) unaffected. Reports whether the simple-name-fallback tier was used, closing the gap that made it impossible to tag `CallResolutionConfidence` honestly from outside the resolver.
- `CallGraph(..., mandatory_disambiguation: bool = False)` — **default False, so the existing default construction path (`engine.py`'s `_build_graphs`) is completely unaffected**; this is an opt-in mode, not a behavior change to production traffic. When `True`: uses the call site's own file as a locality context (same-file/same-directory/import-graph, `ReferenceResolver._locality_score`, unchanged) to narrow an ambiguous callee name to one edge whenever locality actually distinguishes the candidates; when it genuinely can't (no signal, or a real tie), preserves today's exact fan-out-to-every-candidate topology — recall is never sacrificed where there's no evidence to justify narrowing — but now records `resolution_confidence`/`candidates` on the resolved `CallReference` (new `CallGraph.resolved_calls` property) instead of leaving the ambiguity invisible, which is what happens today.
- `import_graph` threaded into `CallGraph.__init__` (optional, defaults `None`) and wired at its one production call site (`engine.py:271`) — needed for the import-graph locality tier; zero behavior change since `mandatory_disambiguation` stays `False` there.

**Verified via same-process ablation** (this project's own established discipline, applied here for the first time to a resolution change rather than a ranking one): built two `CallGraph`s from identical `calls`/`resolver`/`import_graph`, flag off vs on, one process, two scenarios in the same test (`test_ablation_mandatory_disambiguation_matches_default_topology_except_where_narrowed`). Confirmed exactly what the design predicts: **byte-identical topology** for a genuinely ambiguous name with no locality signal (two same-named symbols in unrelated directories, no import edge) — recall provably unaffected; **narrower topology** (fan-out-to-2 collapses to a single edge) only for a call with a real same-file locality signal, which is the intended, deliberate change.

**Verification**: 987/987 tests (977 prior + 10 new), `ruff`/`mypy` clean. New tests cover: `resolve_tiered` tier reporting, single-candidate confidence tagging (both `EXACT_QUALIFIED` and `SIMPLE_NAME_FALLBACK`), same-file locality narrowing, import-graph locality narrowing, genuine-ambiguity fan-out preservation with `candidates` recorded (deterministically sorted, closing the "deterministic tie-breaking" requirement), and the ablation test above.

**Deliberately not done in this phase**: `mandatory_disambiguation` is not defaulted to `True` anywhere — that's a separate decision (whether ARCF's production call graph should actually narrow ambiguous edges), out of scope for "does the mechanism work correctly," which is what this phase proves. `resolve_with_disambiguation` itself was not modified (no risk to `ContextResolver`, its only existing caller). Real type resolution (Phase 3c) remains explicitly out of scope, per `BLUEPRINT.md`'s own scoping: dynamic-dispatch/interface resolution still isn't attempted, and locality scoring is still a heuristic, not proof — now just an *auditable* one when the flag is on.

**Outcome**: PR to be opened from `arcf-di/feature/phase3-mandatory-disambiguation` into `arcf-di/base`.

**Next**: either Phase 3b (thread ambiguity through `ContextResolutionResult` and consumers) or Phase 4 (structured behavioral records, which only aggregates Phases 1–3's output — no new evidence extraction) per `docs/BLUEPRINT.md`'s build order.
