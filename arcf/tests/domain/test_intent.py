import pytest
from pydantic import ValidationError

from domain.intent import UserIntent


def _make_intent(**overrides: object) -> UserIntent:
    defaults: dict[str, object] = {
        "raw_request": "Fix the failing Playwright login test",
        "intent": "fix_failing_test",
        "domain": "testing",
        "task": "bug_fix",
        "confidence": 0.87,
    }
    defaults.update(overrides)
    return UserIntent(**defaults)  # type: ignore[arg-type]


def test_defaults_are_empty_collections() -> None:
    intent = _make_intent()
    assert intent.entities == []
    assert intent.constraints == []
    assert intent.assumptions == []
    assert intent.clarifications == []
    assert intent.strategy_hints == []
    assert intent.complexity is None


def test_needs_clarification_false_when_no_clarifications() -> None:
    assert _make_intent().needs_clarification is False


def test_needs_clarification_true_when_clarifications_present() -> None:
    intent = _make_intent(clarifications=["Which environment: staging or prod?"])
    assert intent.needs_clarification is True


def test_confidence_out_of_bounds_rejected() -> None:
    with pytest.raises(ValidationError):
        _make_intent(confidence=1.5)
