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
    # ARCF Issue #13 fix (2026-08-08): DEFAULT_PRICING is USD per 1M
    # tokens (real OpenAI rates), not per 1K — this test's old expected
    # value (0.15 + 0.60 == 0.75) asserted the bug itself (a 1000x-
    # inflated cost for 1K prompt + 1K completion tokens). Correct
    # value: 1,000 tokens is 1/1000th of the 1M-token rate.
    estimator = CostEstimator()
    cost = estimator.actual_cost(prompt_tokens=1000, completion_tokens=1000, model="gpt-4o-mini")
    assert cost == pytest.approx((0.15 + 0.60) / 1000)


def test_count_tokens_handles_literal_special_token_text() -> None:
    """Real crash repro (2026-08-07): a real repository file (an LLM-
    adjacent codebase's example/fixture content) can literally contain a
    tiktoken special-token-shaped substring like "<|endoftext|>". tiktoken
    raises ValueError on that by default (a safety check meant for
    constructing actual model payloads) — count_tokens only ever counts
    tokens of file/prompt content for budget/cost estimation, never
    constructs a payload sent to a model verbatim, so this should count
    it as plain text instead of crashing."""
    estimator = CostEstimator()
    count = estimator.count_tokens("some text <|endoftext|> more text", "gpt-4o-mini")
    assert count > 0
