"""ContextBudgetManager (Phase 6 deliverable: Budget-aware context) —
greedy selection over RelevanceRanker's output against a token budget.

Deterministic, like the ranker: files are taken in ranked order until
the budget runs out. A file that doesn't fit in full falls back to
SymbolRangeCompressor's line-range extraction before being excluded
outright — compression is tried before exclusion, exclusion is the
last resort, and the returned excluded count makes that visible rather
than silent.

Evidence-preserving context packaging: that "doesn't fit -> compress"
trigger is *also*, independently, driven by evidence_tier now — not
just remaining budget. A SUPPORTING file (call-graph/inheritance/
lexical-probe/repository-scope expansion — see domain.
context_resolution.EvidenceTier's own docstring) with a known symbol
location is compressed to that symbol's range up front, regardless of
whether the full file would fit: a fan-out match shouldn't spend the
same budget as the thing actually being asked about just because it
happens to live in a large file (the motivating case: a lexically-
probed symbol defined inside a framework's 49K-token core routing
module, when the file that actually answers the question is 400
tokens). PRIMARY evidence (a confident direct match, or a file the
query itself named) keeps the plain full-if-it-fits behavior described
above unchanged — this is strictly an additional, earlier trigger for
compression, not a replacement of the existing one, and reuses the same
SymbolRangeCompressor either way.

Boilerplate evidence-category head-truncation (2026-08-11, ARCF
sweep cost investigation — see docs/repo_query_answers/SWEEP_REPORT.md
and scripts/context_budget_filler_diagnosis.py, the falsification
experiment this is based on): a SUPPORTING evidence file with NO known
symbol location (so the trigger above can't compress it — there's no
range to extract) still gets the plain full-if-it-fits treatment today,
even when its evidence category is machine-generated boilerplate that
was never going to explain the codebase's actual behavior regardless of
size — a 6,393-token `.github/workflows/build.yml` spends the SAME
budget as real source whether or not it fits. Measured against the real
12-query sweep: 3 of 12 packaged results were 96-100% boilerplate filler
by token count (all real content excluded for lack of remaining budget)
purely because a CI config or dependency-manifest file happened to be
large. Fix is deliberately narrow: only categories whose patterns are
config/build/CI filenames (never long-form prose — see
`_BOILERPLATE_EVIDENCE_CATEGORIES`'s own comment for the exact list and
why) are head-truncated to `_BOILERPLATE_FILLER_MAX_TOKENS`; "project
structure" (README*) and "test directories" are deliberately excluded
from this list — the same diagnosis found a real case (gvisor: "Explain
how gVisor separates application syscalls from the host kernel") where
README content was the actual basis for a correct, well-grounded
answer, so blanket-truncating every no-symbol SUPPORTING file would
have risked cutting genuinely load-bearing content to chase a token
number. This is a targeted trim of never-prose boilerplate, not a
general "shrink all filler" policy.

Resolution and packaging can happen as two separate API calls, so a
file present at resolution time may be gone (or unreadable) by the time
packaging runs — that's a real race, not a hypothetical, and is treated
the same as "didn't fit": excluded, not a hard failure of the whole
package.

Relative score falloff gate, Feature B (2026-08-11, Real-Time Token &
Latency Optimization): everything above stops a file from being
INCLUDED once it doesn't fit; nothing previously stopped a low-relevance
file from being included just because token budget happened to remain
— the "greedy token-filler" this feature is named for. `ranked_files`
arrives sorted descending by RelevanceRanker's relevance_score, so once
any candidate's score drops below `_RELATIVE_FALLOFF_GAMMA` times the
top candidate's score, every remaining candidate (sorted lower still)
is guaranteed to also qualify for the cutoff — packaging halts right
there, budget remaining or not, rather than continuing to spend it on
long-tail noise. This is independent of, and runs before, every
budget/compression decision above: a candidate can lose to relevance
falloff without ever reaching the "does it fit" question at all.

Two-Tier AST Snippet Rendering, Feature 2 (2026-08-11, Safe High-
Efficiency Payload Optimization): Feature C's `extract_with_ast_scope`
gives every SUPPORTING/EXPERIMENTAL candidate a full implementation
body. Measured cost: for a query with several secondary matches, most
of those bodies are never what the query is actually about — the
FIRST (highest-ranked) SUPPORTING candidate encountered, in
`ranked_files`' already-sorted order, is the FOCAL one and keeps the
full body; every one after it gets `extract_skeleton_only` instead
(signature/type contract only, body stripped) UNLESS its own
`justification_chain` shows it's directly (hop-1) call-graph-linked to
whatever entry point it was reached from — a secondary file that's one
hop from the real answer plausibly needs its own body to make sense of
that link, so it's exempted from skeletonization rather than risking a
genuinely load-bearing body being cut to chase a token number (same
"don't guess wrong" posture as the boilerplate-truncation carve-out
above).

Intent-based dynamic budget ceilings, Feature 3 (2026-08-11, Safe
High-Efficiency Payload Optimization): `max_tokens` has always been a
single fixed ceiling the CALLER chooses (typically ~8000, the same for
every query regardless of what it's actually asking). `select()` now
takes an optional `task_type` (context/task_profile.py's
RetrievalTaskType, the SAME deterministic classification RANKING_
PROFILES already keys off of, reused rather than inventing a second
classifier) and, when given, caps `max_tokens` FURTHER down to a
tier-specific ceiling via `_BUDGET_TIER_BY_TASK_TYPE` -- never raises
it above what the caller already asked for, only tightens it. A lookup
task genuinely doesn't need 8000 tokens of context to answer "what is
X"; a cross-module trace legitimately might need more room than a
single-file bug fix. `task_type=None` (every existing caller, until
threaded through) is fully backward compatible -- `max_tokens` passes
through completely unchanged, byte-identical to before this feature.
"""

from collections import defaultdict
from typing import Callable

from context.compressor import SymbolRangeCompressor
from context.relevance_ranker import RankedFile
from context.task_profile import RetrievalTaskType
from domain.context_package import PackagedFile
from domain.context_resolution import ContextResolutionResult, EvidenceTier, SymbolReference
from infrastructure.cost import CostEstimator
from shared.errors import WorkspacePathError
from workspace.permissions import PermissionManager

_TOKEN_ESTIMATE_MODEL = "gpt-4o-mini"
_READ_ERRORS: tuple[type[Exception], ...] = (OSError, WorkspacePathError)

# Evidence categories (contracts/evidence_contract.py) whose patterns are
# ALL specific config/build/CI filenames (package.json, pyproject.toml,
# Makefile, Dockerfile, .github/workflows/*, pytest.ini, ...) — never
# long-form prose a full-file read could plausibly need. Deliberately
# excludes "project structure" (README*, src/**) and "test directories"
# (tests/**, ...), which can and do carry genuine explanatory content or
# real source — see this module's docstring for the real case that
# motivated keeping those two out.
_BOILERPLATE_EVIDENCE_CATEGORIES = frozenset(
    {
        "dependency manifest",
        "project metadata",
        "build/workspace configuration",
        "CI/workflow files",
        "test framework/configuration",
    }
)
_BOILERPLATE_FILLER_MAX_TOKENS = 150

# Feature B (relative score falloff gate): a candidate scoring below this
# fraction of the top candidate's relevance_score is long-tail noise, not
# a real secondary match — halts packaging rather than filling remaining
# budget with it. See this module's own docstring for the full rationale.
_RELATIVE_FALLOFF_GAMMA = 0.45

# Feature 3 (intent-based dynamic budget ceilings): maps RetrievalTaskType
# onto the task spec's three tiers (lookup/definition, logic/
# implementation, cross-module trace). REPOSITORY_EXPLANATION and CI_CD
# are typically single-file/config lookups -> lookup tier. BUG_FIX and
# PERFORMANCE usually need to read one function's real logic, not just
# its signature -> logic tier. ARCHITECTURE_UNDERSTANDING, REFACTOR_
# IMPACT_ANALYSIS, and LARGE_STRUCTURAL_CHANGE inherently span multiple
# files/subsystems -> cross-module tier. UNKNOWN is the task spec's own
# explicit safety fallback (2500, the middle tier) -- an unclassified
# query gets neither the tightest nor the loosest cap.
_BUDGET_TIER_BY_TASK_TYPE: dict[RetrievalTaskType, int] = {
    RetrievalTaskType.REPOSITORY_EXPLANATION: 1200,
    RetrievalTaskType.CI_CD: 1200,
    RetrievalTaskType.BUG_FIX: 2500,
    RetrievalTaskType.PERFORMANCE: 2500,
    RetrievalTaskType.UNKNOWN: 2500,
    RetrievalTaskType.ARCHITECTURE_UNDERSTANDING: 4500,
    RetrievalTaskType.REFACTOR_IMPACT_ANALYSIS: 4500,
    RetrievalTaskType.LARGE_STRUCTURAL_CHANGE: 4500,
}
_DEFAULT_BUDGET_TIER = 2500

# Feature 2 (Two-Tier AST Snippet Rendering): a compress-first candidate
# reached at hop 1 has a 2-element justification_chain -- ("defines X",
# "calls X") for a module-level caller, or ("defines X", "called by
# Y")/("defines X", "calls Y") for a symbol-owning one at hop 1. Anything
# longer is hop 2+.
_HOP_ONE_CHAIN_LENGTH = 2


class ContextBudgetManager:
    def __init__(
        self,
        permissions: PermissionManager,
        token_estimator: CostEstimator,
        compressor: SymbolRangeCompressor,
    ) -> None:
        self._permissions = permissions
        self._token_estimator = token_estimator
        self._compressor = compressor

    def select(
        self,
        ranked_files: list[RankedFile],
        result: ContextResolutionResult,
        max_tokens: int,
        task_type: RetrievalTaskType | None = None,
    ) -> tuple[list[PackagedFile], int, int]:
        """Returns (packaged_files, tokens_used, excluded_file_count).
        `task_type`, when given (Feature 3), further tightens
        `max_tokens` to that task's own ceiling -- see this module's own
        docstring. Never loosens it: `min(max_tokens, tier)`."""
        symbols_by_file = self._symbols_by_file(result)

        if task_type is not None:
            max_tokens = min(
                max_tokens, _BUDGET_TIER_BY_TASK_TYPE.get(task_type, _DEFAULT_BUDGET_TIER)
            )

        packaged: list[PackagedFile] = []
        used = 0
        excluded = 0

        # Feature B: ranked_files is sorted descending by relevance_score
        # (RelevanceRanker's contract), so the first score IS the top —
        # no need to scan for a max. gamma * 0.0 is still 0.0, so an
        # all-zero-score candidate set (e.g. every file at the shared
        # default weight) never falls below its own threshold and this
        # gate is a no-op, exactly as it should be with nothing to fall
        # off from.
        top_score = ranked_files[0].relevance_score if ranked_files else 0.0
        falloff_threshold = _RELATIVE_FALLOFF_GAMMA * top_score

        # Feature 2: counts only compress-eligible (SUPPORTING/
        # EXPERIMENTAL-with-symbols) candidates actually reached below --
        # PRIMARY files don't compete for "focal" rank, since they
        # already get full-body treatment regardless.
        compress_first_seen = 0

        for index, ranked in enumerate(ranked_files):
            if ranked.relevance_score < falloff_threshold:
                # Every remaining candidate is sorted lower still, so all
                # of them also fail this same threshold — halt entirely
                # (not just skip this one) rather than keep spending
                # budget on long-tail noise just because it remains.
                excluded += len(ranked_files) - index
                break

            remaining = max_tokens - used
            if remaining <= 0:
                excluded += 1
                continue

            symbols_in_file = symbols_by_file.get(ranked.file_path, [])

            # Evidence-preserving context packaging (see this class's own
            # docstring): SUPPORTING evidence with a known symbol location
            # is compressed up front, before ever checking whether the
            # full file would fit — deliberately NOT gated on remaining
            # budget the way the fallback compression below is. A file
            # with no symbol location (e.g. a glob-matched "evidence:
            # <category>" file — README, pyproject.toml — nothing here to
            # extract a range *around*) falls through to the same
            # full-if-fits behavior PRIMARY evidence gets, since there is
            # no narrower "relevant part" to prefer over the whole file.
            compress_first_tiers = (EvidenceTier.SUPPORTING, EvidenceTier.EXPERIMENTAL)
            if ranked.evidence_tier in compress_first_tiers and symbols_in_file:
                # Feature C (AST Enclosing Scope Slicing): SUPPORTING/
                # EXPERIMENTAL are exactly the "secondary candidates" the
                # task spec means -- PRIMARY's doesn't-fit-in-full path
                # below keeps the plain extract() unchanged, since that's
                # a confident direct match, not fan-out noise.
                #
                # Feature 2 (Two-Tier AST Snippet Rendering): only the
                # FIRST (focal, highest-ranked) compress-eligible
                # candidate, or one directly (hop-1) call-graph-linked to
                # its own entry point, gets the full body -- see this
                # module's own docstring.
                is_focal = compress_first_seen == 0
                # An EMPTY chain means "no provenance info available",
                # not "hop 1" -- must be non-empty as well as short, or
                # every candidate with unset justification_chain would
                # wrongly count as hop-1-linked and skeletonization would
                # never trigger at all.
                is_hop_one_linked = 0 < len(ranked.justification_chain) <= _HOP_ONE_CHAIN_LENGTH
                compress_first_seen += 1
                extract_fn = (
                    self._compressor.extract_with_ast_scope
                    if is_focal or is_hop_one_linked
                    else self._compressor.extract_skeleton_only
                )
                compressed = self._compress(ranked, symbols_in_file, remaining, extract=extract_fn)
                if compressed is not None:
                    packaged.append(compressed)
                    used += compressed.token_count
                else:
                    excluded += 1
                continue

            # No symbol location to compress around (the trigger above
            # doesn't apply), but a boilerplate evidence category never
            # needed the full file in the first place — see this
            # module's docstring. Truncated regardless of remaining
            # budget, same "compress before checking full-fit"
            # discipline as the symbol-anchored trigger above.
            if (
                ranked.evidence_tier in compress_first_tiers
                and not symbols_in_file
                and ranked.reason.removeprefix("evidence: ") in _BOILERPLATE_EVIDENCE_CATEGORIES
                and ranked.token_count > _BOILERPLATE_FILLER_MAX_TOKENS
            ):
                truncated = self._truncate_boilerplate(ranked, remaining)
                if truncated is not None:
                    packaged.append(truncated)
                    used += truncated.token_count
                else:
                    excluded += 1
                continue

            if ranked.token_count <= remaining:
                try:
                    content = self._permissions.safe_read_text(ranked.file_path)
                except _READ_ERRORS:
                    excluded += 1
                    continue
                packaged.append(
                    PackagedFile(
                        file_path=ranked.file_path,
                        content=content,
                        relevance_score=ranked.relevance_score,
                        reason=ranked.reason,
                        token_count=ranked.token_count,
                        truncated=False,
                    )
                )
                used += ranked.token_count
                continue

            compressed = self._compress(ranked, symbols_in_file, remaining)
            if compressed is not None:
                packaged.append(compressed)
                used += compressed.token_count
            else:
                excluded += 1

        return packaged, used, excluded

    def _compress(
        self,
        ranked: RankedFile,
        symbols_in_file: list[SymbolReference],
        remaining: int,
        extract: Callable[[str, list[SymbolReference]], str] | None = None,
    ) -> PackagedFile | None:
        """Shared by both compression triggers above (evidence-tier-driven
        and doesn't-fit-in-full): `None` means "couldn't produce a
        compressed excerpt that fits" — the caller counts that as
        excluded, same as it always has for the doesn't-fit path.
        `extract` defaults to the plain SymbolRangeCompressor.extract;
        the evidence-tier-driven trigger passes extract_with_ast_scope
        instead (Feature C) — same shared token-check/PackagedFile
        construction either way, only the excerpt-building function
        differs."""
        extract_fn = extract if extract is not None else self._compressor.extract
        try:
            excerpt = extract_fn(ranked.file_path, symbols_in_file)
        except _READ_ERRORS:
            return None
        if not excerpt:
            return None

        excerpt_tokens = self._token_estimator.count_tokens(excerpt, _TOKEN_ESTIMATE_MODEL)
        if excerpt_tokens > remaining:
            return None

        return PackagedFile(
            file_path=ranked.file_path,
            content=excerpt,
            relevance_score=ranked.relevance_score,
            reason=ranked.reason,
            token_count=excerpt_tokens,
            truncated=True,
        )

    def _truncate_boilerplate(self, ranked: RankedFile, remaining: int) -> PackagedFile | None:
        """A no-symbol boilerplate evidence file (see
        `_BOILERPLATE_EVIDENCE_CATEGORIES`) head-truncated to
        `_BOILERPLATE_FILLER_MAX_TOKENS` — there's no symbol range to
        extract, so unlike `_compress` this just keeps the file's start
        (its filename plus the first fragment already signals "this is a
        CI/build/dependency file", which is all this category ever
        contributed). `None` (excluded) only if even the truncated cap
        doesn't fit what's left of the budget or the file can't be read."""
        cap = min(_BOILERPLATE_FILLER_MAX_TOKENS, remaining)
        if cap <= 0:
            return None
        try:
            content = self._permissions.safe_read_text(ranked.file_path)
        except _READ_ERRORS:
            return None

        chars_per_token = len(content) / ranked.token_count if ranked.token_count else 4.0
        excerpt = content[: int(cap * chars_per_token)]
        excerpt_tokens = self._token_estimator.count_tokens(excerpt, _TOKEN_ESTIMATE_MODEL)
        while excerpt_tokens > cap and excerpt:
            excerpt = excerpt[: max(1, int(len(excerpt) * 0.9))]
            excerpt_tokens = self._token_estimator.count_tokens(excerpt, _TOKEN_ESTIMATE_MODEL)
        if not excerpt:
            return None

        return PackagedFile(
            file_path=ranked.file_path,
            content=excerpt,
            relevance_score=ranked.relevance_score,
            reason=ranked.reason,
            token_count=excerpt_tokens,
            truncated=True,
        )

    @staticmethod
    def _symbols_by_file(result: ContextResolutionResult) -> dict[str, list[SymbolReference]]:
        by_file: dict[str, list[SymbolReference]] = defaultdict(list)
        for symbol in (*result.entry_points, *result.impacted_symbols):
            by_file[symbol.file_path].append(symbol)
        return by_file
