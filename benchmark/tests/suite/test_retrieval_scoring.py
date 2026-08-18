from benchmark.suite.retrieval_scoring import (
    FailureClass,
    diagnose,
    mean_recall_at_k,
    mean_reciprocal_rank,
    recall_at_k,
    reciprocal_rank,
)


def test_recall_at_k_true_when_rank_within_k() -> None:
    assert recall_at_k(1, 1) is True
    assert recall_at_k(5, 5) is True
    assert recall_at_k(6, 5) is False
    assert recall_at_k(None, 5) is False


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(1) == 1.0
    assert reciprocal_rank(4) == 0.25
    assert reciprocal_rank(None) == 0.0


def test_mean_recall_at_k_empty_is_zero() -> None:
    assert mean_recall_at_k([], 1) == 0.0


def test_mean_recall_at_k() -> None:
    ranks = [1, 3, None, 8]
    assert mean_recall_at_k(ranks, 1) == 0.25
    assert mean_recall_at_k(ranks, 5) == 0.5


def test_mean_reciprocal_rank_empty_is_zero() -> None:
    assert mean_reciprocal_rank([]) == 0.0


def test_mean_reciprocal_rank() -> None:
    assert mean_reciprocal_rank([1, 2, None]) == (1.0 + 0.5 + 0.0) / 3


def test_diagnose_success_within_threshold() -> None:
    d = diagnose("t1", rank=1, retrieval_terms=["Foo"], candidate_count=5)
    assert d.failure_class == FailureClass.SUCCESS


def test_diagnose_ranked_too_low() -> None:
    d = diagnose("t1", rank=9, retrieval_terms=["Foo"], candidate_count=20, recall_threshold_k=5)
    assert d.failure_class == FailureClass.TARGET_IN_POOL_RANKED_TOO_LOW


def test_diagnose_known_ambiguous_takes_priority_when_not_in_pool() -> None:
    d = diagnose(
        "t1", rank=None, retrieval_terms=["Foo"], candidate_count=3, known_ambiguous=True
    )
    assert d.failure_class == FailureClass.QUERY_INHERENTLY_AMBIGUOUS


def test_diagnose_no_terms_at_all() -> None:
    d = diagnose("t1", rank=None, retrieval_terms=[], candidate_count=0)
    assert d.failure_class == FailureClass.TARGET_NOT_IN_POOL


def test_diagnose_terms_but_zero_candidates_is_unresolvable() -> None:
    d = diagnose("t1", rank=None, retrieval_terms=["not a real symbol"], candidate_count=0)
    assert d.failure_class == FailureClass.SLM_TERMS_UNRESOLVABLE_BY_ARCF_DI


def test_diagnose_terms_no_overlap_with_expected_is_likely_wrong() -> None:
    d = diagnose(
        "t1",
        rank=None,
        retrieval_terms=["totally_unrelated_symbol"],
        candidate_count=4,
        expected_grounding_terms=["auth.py", "Authenticator"],
    )
    assert d.failure_class == FailureClass.SLM_INTERPRETATION_LIKELY_WRONG


def test_diagnose_terms_overlap_but_target_missing_is_other_limitation() -> None:
    d = diagnose(
        "t1",
        rank=None,
        retrieval_terms=["Authenticator"],
        candidate_count=4,
        expected_grounding_terms=["auth.py", "Authenticator"],
    )
    assert d.failure_class == FailureClass.OTHER_DETERMINISTIC_LIMITATION
