"""Unified retrieval task profile (ARCF architecture hardening, foundation
module) — the single deterministic vocabulary that drives how far
ContextResolver traverses (code_intelligence/context_resolver.py) and how
RelevanceRanker weighs what it finds (context/relevance_ranker.py).

Deliberately additive and independent of Phase 3's Contract-facing
classifiers (contracts/task_classifier.py, contracts/
repository_scope_classifier.py): classify_retrieval_task() *reuses* their
outputs as hints rather than replacing or modifying them, so this module
carries zero risk to Phase 3's existing behavior or test suite. Same
keyword-substring idiom as those classifiers — no model reasoning, no
ranking, fully reproducible.

RetrievalTaskType.UNKNOWN is deliberately mapped to today's exact
traversal depth (1, i.e. the previous fixed one-hop behavior) and today's
exact ranking weights (see relevance_ranker._REASON_WEIGHTS) — a caller
that doesn't thread a task type through gets byte-identical behavior to
before this module existed.
"""

from dataclasses import dataclass
from enum import StrEnum


class RetrievalTaskType(StrEnum):
    BUG_FIX = "bug_fix"
    REPOSITORY_EXPLANATION = "repository_explanation"
    ARCHITECTURE_UNDERSTANDING = "architecture_understanding"
    REFACTOR_IMPACT_ANALYSIS = "refactor_impact_analysis"
    LARGE_STRUCTURAL_CHANGE = "large_structural_change"
    CI_CD = "ci_cd"
    PERFORMANCE = "performance"
    UNKNOWN = "unknown"


_CI_CD_WORDS: tuple[str, ...] = (
    "ci/cd",
    "ci ",
    " cd ",
    "pipeline",
    "workflow",
    "github actions",
    "gitlab ci",
    "jenkins",
    "deploy",
    "deployment",
    "build pipeline",
    "continuous integration",
    "continuous deployment",
)

_PERFORMANCE_WORDS: tuple[str, ...] = (
    "performance",
    "latency",
    "slow",
    "optimize",
    "optimization",
    "throughput",
    "bottleneck",
    "hot path",
    "n+1",
    "memory leak",
    "profil",
)

_ARCHITECTURE_WORDS: tuple[str, ...] = (
    "architecture",
    "module boundaries",
    "how is this structured",
    "high-level design",
    "system design",
    "component overview",
)

_LARGE_STRUCTURAL_WORDS: tuple[str, ...] = (
    "large",
    "structural",
    "system-wide",
    "sweeping",
    "repository-wide",
    "codebase-wide",
    "across the codebase",
    "across the repository",
)

_IMPACT_WORDS: tuple[str, ...] = (
    "impact",
    "blast radius",
    "what would break",
    "what breaks",
    "downstream",
)


def classify_retrieval_task(
    raw_request: str,
    task_classifier_task: str = "unknown",
    repository_scope_task_type: str = "unscoped",
) -> RetrievalTaskType:
    """Deterministic keyword classification into RetrievalTaskType.

    `task_classifier_task` is contracts.task_classifier.TaskClassifier's
    output (bug_fix/feature/refactor/documentation/test/unknown).
    `repository_scope_task_type` is contracts.repository_scope_classifier.
    RepositoryScopeClassifier's output (repository_debugging/
    repository_documentation/unscoped). Both are reused as hints; this
    function never mutates or re-derives them.
    """
    text_lower = raw_request.lower()

    if any(word in text_lower for word in _CI_CD_WORDS):
        return RetrievalTaskType.CI_CD

    if any(word in text_lower for word in _PERFORMANCE_WORDS):
        return RetrievalTaskType.PERFORMANCE

    if repository_scope_task_type == "repository_debugging" or task_classifier_task == "bug_fix":
        return RetrievalTaskType.BUG_FIX

    if repository_scope_task_type == "repository_documentation":
        if any(word in text_lower for word in _ARCHITECTURE_WORDS):
            return RetrievalTaskType.ARCHITECTURE_UNDERSTANDING
        return RetrievalTaskType.REPOSITORY_EXPLANATION

    if any(word in text_lower for word in _ARCHITECTURE_WORDS):
        return RetrievalTaskType.ARCHITECTURE_UNDERSTANDING

    if task_classifier_task == "refactor":
        if any(word in text_lower for word in _LARGE_STRUCTURAL_WORDS):
            return RetrievalTaskType.LARGE_STRUCTURAL_CHANGE
        return RetrievalTaskType.REFACTOR_IMPACT_ANALYSIS

    if any(word in text_lower for word in _IMPACT_WORDS):
        return RetrievalTaskType.REFACTOR_IMPACT_ANALYSIS

    return RetrievalTaskType.UNKNOWN


# None means "expand hop by hop until max_expansion_tokens is reached"
# (brief: "Large structural changes: continue until token budget is
# reached") rather than a fixed hop count.
TRAVERSAL_DEPTH: dict[RetrievalTaskType, int | None] = {
    RetrievalTaskType.BUG_FIX: 1,
    RetrievalTaskType.REPOSITORY_EXPLANATION: 2,
    RetrievalTaskType.ARCHITECTURE_UNDERSTANDING: 2,
    RetrievalTaskType.REFACTOR_IMPACT_ANALYSIS: 3,
    RetrievalTaskType.LARGE_STRUCTURAL_CHANGE: None,
    RetrievalTaskType.CI_CD: 1,
    RetrievalTaskType.PERFORMANCE: 2,
    RetrievalTaskType.UNKNOWN: 1,
}

# "*" is the fallback weight for any reason-verb not explicitly listed
# (mirrors relevance_ranker's previous module-level _DEFAULT_REASON_WEIGHT).
# UNKNOWN is byte-identical to relevance_ranker's pre-hardening
# _REASON_WEIGHTS/_DEFAULT_REASON_WEIGHT so untagged callers see no change.
# Every profile's "called" key mirrors its "calls" value (ARCF Issue #9
# fix, 2026-08-08): ContextResolver emits "called by X (hop N)" for
# transitive callees — first word "called", not "calls" — and this table
# had no matching entry, so every hop-N caller-chain file was silently
# scored at the generic "*" default instead of the call-graph weight
# each profile actually intended. Found via real SQLAlchemy data, where
# this suppressed both canonical files' scores in the
# repository_explanation profile specifically.
RANKING_PROFILES: dict[RetrievalTaskType, dict[str, float]] = {
    RetrievalTaskType.UNKNOWN: {
        "defines": 1.0,
        "calls": 0.7,
        "called": 0.7,
        "extends": 0.6,
        "references:": 0.8,
        "*": 0.3,
    },
    # Bug fix priority (brief §7): direct callers, direct definitions,
    # request path (imports), error-related modules (evidence).
    RetrievalTaskType.BUG_FIX: {
        "defines": 1.0,
        "calls": 0.95,
        "called": 0.95,
        "imports": 0.7,
        "extends": 0.5,
        "references:": 0.85,
        "evidence:": 0.3,
        "*": 0.2,
    },
    # Refactor / impact analysis priority: transitive callers,
    # inheritance, interface definitions, impacted modules.
    RetrievalTaskType.REFACTOR_IMPACT_ANALYSIS: {
        "extends": 1.0,
        "defines": 0.85,
        "calls": 0.9,
        "called": 0.9,
        "imports": 0.8,
        "references:": 0.7,
        "evidence:": 0.3,
        "*": 0.25,
    },
    # Repository explanation priority: broad evidence (README, project
    # structure, dependency manifests) alongside module definitions —
    # less dependency-root-specific than architecture understanding.
    RetrievalTaskType.REPOSITORY_EXPLANATION: {
        "defines": 0.9,
        "evidence:": 0.85,
        "references:": 0.7,
        "imports": 0.5,
        "calls": 0.4,
        "called": 0.4,
        "extends": 0.4,
        "*": 0.4,
    },
    # Architecture understanding priority: entry points (handled by
    # RelevanceRanker's separate entry-point bonus, not a reason-verb
    # weight), module boundaries (defines), configuration (evidence),
    # dependency roots (imports).
    RetrievalTaskType.ARCHITECTURE_UNDERSTANDING: {
        "defines": 1.0,
        "evidence:": 0.75,
        "imports": 0.7,
        "references:": 0.6,
        "calls": 0.4,
        "called": 0.4,
        "extends": 0.4,
        "*": 0.35,
    },
    # CI/CD priority: workflows, build scripts, deployment configuration —
    # almost entirely evidence-contract-driven, not call-graph-driven.
    RetrievalTaskType.CI_CD: {
        "evidence:": 1.0,
        "references:": 0.8,
        "defines": 0.5,
        "imports": 0.3,
        "calls": 0.2,
        "called": 0.2,
        "extends": 0.2,
        "*": 0.4,
    },
    # Performance priority: execution path, request handlers, service
    # layers, data access layers — essentially the call chain end to end.
    RetrievalTaskType.PERFORMANCE: {
        "defines": 0.9,
        "calls": 1.0,
        "called": 1.0,
        "imports": 0.6,
        "extends": 0.5,
        "references:": 0.7,
        "evidence:": 0.3,
        "*": 0.25,
    },
}
# Large structural change shares refactor/impact-analysis's weight shape —
# its distinguishing feature is unbounded traversal depth (see
# TRAVERSAL_DEPTH above), not a different ranking shape.
RANKING_PROFILES[RetrievalTaskType.LARGE_STRUCTURAL_CHANGE] = RANKING_PROFILES[
    RetrievalTaskType.REFACTOR_IMPACT_ANALYSIS
]


@dataclass(frozen=True)
class TraversalProfile:
    task_type: RetrievalTaskType
    max_depth: int | None
    ranking_weights: dict[str, float]


def traversal_profile_for(task_type: RetrievalTaskType) -> TraversalProfile:
    return TraversalProfile(
        task_type=task_type,
        max_depth=TRAVERSAL_DEPTH[task_type],
        ranking_weights=RANKING_PROFILES[task_type],
    )
