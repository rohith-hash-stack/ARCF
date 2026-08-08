from context.task_profile import (
    RANKING_PROFILES,
    TRAVERSAL_DEPTH,
    RetrievalTaskType,
    classify_retrieval_task,
    traversal_profile_for,
)


def test_defaults_to_unknown_with_no_hints() -> None:
    assert classify_retrieval_task("do something vague") == RetrievalTaskType.UNKNOWN


def test_bug_fix_from_task_classifier_hint() -> None:
    assert (
        classify_retrieval_task("please help", task_classifier_task="bug_fix")
        == RetrievalTaskType.BUG_FIX
    )


def test_bug_fix_from_repository_scope_hint() -> None:
    assert (
        classify_retrieval_task(
            "why is this failing", repository_scope_task_type="repository_debugging"
        )
        == RetrievalTaskType.BUG_FIX
    )


def test_repository_explanation_from_documentation_scope() -> None:
    assert (
        classify_retrieval_task(
            "please explain this repository", repository_scope_task_type="repository_documentation"
        )
        == RetrievalTaskType.REPOSITORY_EXPLANATION
    )


def test_architecture_understanding_from_documentation_scope_with_architecture_words() -> None:
    assert (
        classify_retrieval_task(
            "explain the architecture of this repository",
            repository_scope_task_type="repository_documentation",
        )
        == RetrievalTaskType.ARCHITECTURE_UNDERSTANDING
    )


def test_architecture_understanding_without_repository_scope() -> None:
    assert (
        classify_retrieval_task("what is the high-level design here?")
        == RetrievalTaskType.ARCHITECTURE_UNDERSTANDING
    )


def test_refactor_impact_analysis_from_task_classifier_hint() -> None:
    assert (
        classify_retrieval_task("clean up this module", task_classifier_task="refactor")
        == RetrievalTaskType.REFACTOR_IMPACT_ANALYSIS
    )


def test_large_structural_change_from_refactor_with_scope_words() -> None:
    assert (
        classify_retrieval_task(
            "restructure this in a sweeping, system-wide way", task_classifier_task="refactor"
        )
        == RetrievalTaskType.LARGE_STRUCTURAL_CHANGE
    )


def test_impact_words_alone_signal_refactor_impact_analysis() -> None:
    assert (
        classify_retrieval_task("what would break downstream if I change this?")
        == RetrievalTaskType.REFACTOR_IMPACT_ANALYSIS
    )


def test_ci_cd_detection() -> None:
    assert classify_retrieval_task("explain our CI/CD pipeline") == RetrievalTaskType.CI_CD


def test_performance_detection() -> None:
    assert (
        classify_retrieval_task("why is this endpoint so slow, optimize the latency")
        == RetrievalTaskType.PERFORMANCE
    )


def test_ci_cd_checked_before_bug_fix() -> None:
    # A failing pipeline is still fundamentally a CI/CD question, not a
    # generic bug fix — CI/CD vocabulary is checked first.
    assert (
        classify_retrieval_task(
            "the deployment pipeline is failing", repository_scope_task_type="repository_debugging"
        )
        == RetrievalTaskType.CI_CD
    )


def test_every_task_type_has_a_traversal_depth_and_ranking_profile() -> None:
    for task_type in RetrievalTaskType:
        assert task_type in TRAVERSAL_DEPTH
        assert task_type in RANKING_PROFILES
        assert "*" in RANKING_PROFILES[task_type]


def test_unknown_ranking_profile_matches_pre_hardening_weights() -> None:
    # "called" (ARCF Issue #9 fix, 2026-08-08) mirrors "calls" here too —
    # relevance_ranker._REASON_WEIGHTS gained the same key for the same
    # reason, so this profile is still byte-identical to that module's
    # pre-hardening weights, just with both now current.
    profile = RANKING_PROFILES[RetrievalTaskType.UNKNOWN]
    assert profile == {
        "defines": 1.0,
        "calls": 0.7,
        "called": 0.7,
        "extends": 0.6,
        "references:": 0.8,
        "*": 0.3,
    }


def test_large_structural_change_has_unbounded_depth() -> None:
    assert TRAVERSAL_DEPTH[RetrievalTaskType.LARGE_STRUCTURAL_CHANGE] is None


def test_traversal_profile_for_bundles_depth_and_weights() -> None:
    profile = traversal_profile_for(RetrievalTaskType.BUG_FIX)
    assert profile.max_depth == 1
    assert profile.ranking_weights == RANKING_PROFILES[RetrievalTaskType.BUG_FIX]
