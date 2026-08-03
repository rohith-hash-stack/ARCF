from contracts.confidence import ConfidenceEngine, ConfidenceSignals


def _signals(**overrides: object) -> ConfidenceSignals:
    defaults: dict[str, object] = {
        "domain_known": True,
        "task_known": True,
        "domain_classifier_agrees": True,
        "task_classifier_agrees": True,
        "entity_count": 3,
        "constraint_count": 2,
        "assumption_count": 2,
        "self_reported_confidence": 0.9,
        "raw_request_char_count": 100,
    }
    defaults.update(overrides)
    return ConfidenceSignals(**defaults)  # type: ignore[arg-type]


def test_full_signal_agreement_scores_near_one() -> None:
    engine = ConfidenceEngine()
    score = engine.score(_signals())
    assert score > 0.9


def test_score_is_deterministic_for_same_signals() -> None:
    engine = ConfidenceEngine()
    signals = _signals()
    assert engine.score(signals) == engine.score(signals)


def test_missing_domain_and_task_lowers_score() -> None:
    engine = ConfidenceEngine()
    full = engine.score(_signals())
    missing = engine.score(_signals(domain_known=False, task_known=False))
    assert missing < full


def test_classifier_disagreement_lowers_score() -> None:
    engine = ConfidenceEngine()
    agrees = engine.score(_signals())
    disagrees = engine.score(
        _signals(domain_classifier_agrees=False, task_classifier_agrees=False)
    )
    assert disagrees < agrees


def test_self_reported_confidence_alone_cannot_force_high_score() -> None:
    engine = ConfidenceEngine()
    score = engine.score(
        _signals(
            domain_known=False,
            task_known=False,
            domain_classifier_agrees=False,
            task_classifier_agrees=False,
            entity_count=0,
            constraint_count=0,
            assumption_count=0,
            self_reported_confidence=1.0,
        )
    )
    assert score <= 0.15 + 1e-9  # only the self-report weight can contribute


def test_self_reported_confidence_is_clamped_above_one() -> None:
    engine = ConfidenceEngine()
    normal = engine.score(_signals(self_reported_confidence=1.0))
    over = engine.score(_signals(self_reported_confidence=5.0))
    assert normal == over


def test_short_request_penalized() -> None:
    engine = ConfidenceEngine()
    long_request = engine.score(_signals(raw_request_char_count=100))
    short_request = engine.score(_signals(raw_request_char_count=5))
    assert short_request < long_request


def test_score_bounded_between_zero_and_one() -> None:
    engine = ConfidenceEngine()
    score = engine.score(_signals())
    assert 0.0 <= score <= 1.0
