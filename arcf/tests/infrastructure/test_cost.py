import pytest

from infrastructure.cost import CostEstimator, CostGuardrail
from shared.errors import CostGuardrailExceededError


def test_estimate_counts_real_tokens_for_known_model() -> None:
    estimator = CostEstimator()
    estimate = estimator.estimate("hello world", "gpt-4o-mini", assumed_completion_tokens=100)
    assert estimate.prompt_tokens > 0
    assert estimate.estimated_cost_usd > 0


def test_unknown_model_falls_back_to_conservative_pricing() -> None:
    estimator = CostEstimator()
    known = estimator.estimate("hello world", "gpt-4o-mini", assumed_completion_tokens=100)
    unknown = estimator.estimate(
        "hello world", "some-unlisted-model", assumed_completion_tokens=100
    )
    assert unknown.estimated_cost_usd > known.estimated_cost_usd


def test_guardrail_allows_cheap_request() -> None:
    guardrail = CostGuardrail(CostEstimator(), max_cost_usd=1.0)
    estimate = guardrail.check("short prompt", "gpt-4o-mini", assumed_completion_tokens=10)
    assert estimate.estimated_cost_usd <= 1.0


def test_guardrail_rejects_expensive_request() -> None:
    guardrail = CostGuardrail(CostEstimator(), max_cost_usd=0.0001)
    with pytest.raises(CostGuardrailExceededError):
        guardrail.check("a reasonably long prompt " * 50, "gpt-4o", assumed_completion_tokens=4096)


def test_actual_cost_uses_real_usage_numbers() -> None:
    estimator = CostEstimator()
    cost = estimator.actual_cost(prompt_tokens=1000, completion_tokens=1000, model="gpt-4o-mini")
    assert cost == pytest.approx(0.15 + 0.60)
