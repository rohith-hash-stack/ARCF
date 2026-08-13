# ARCF-DI Progress Log

**Last updated:** 2026-08-13 · **Branch:** `arcf-di/base` (off `main`) · **Status:** Phase 0 (scope freeze) complete, blueprint drafted, no code written yet.

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

**Next**: Phase 1 (deterministic evidence layer — additive IR fields) per the migration order in `docs/BLUEPRINT.md`, step 1.
