"""Cost guardrail — reject a request before it ever reaches the LLM if its
estimated cost exceeds budget.

Token counting uses tiktoken against the actual prompt text, not a rough
character estimate, so the guardrail is trustworthy rather than
advisory. Pricing is a static table (USD per 1M tokens, matching how
OpenAI and most providers publish rates); unlisted models fall back to a
conservative rate so an unrecognized model name fails safe (rejected)
rather than silently bypassing the guardrail.
"""

import tiktoken
from pydantic import BaseModel, ConfigDict

from shared.errors import CostGuardrailExceededError

# USD per 1M tokens: (prompt_price, completion_price) — real OpenAI
# rates (e.g. gpt-4o-mini: $0.15/$0.60 per 1M tokens). ARCF Issue #13
# fix (2026-08-08): these values were always per-1M, but estimate() and
# actual_cost() divided by 1,000 as if they were per-1K, inflating every
# computed cost ~1000x — a real functional bug, not just a display one:
# CostGuardrail.check() below rejects requests that exceed a max_cost_usd
# budget, so a 1000x-inflated estimate could wrongly reject legitimate,
# well-within-budget requests. Real billed API cost was never affected
# (LiteLLMClient calls the provider directly), only this estimate.
DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-3.5-turbo": (0.50, 1.50),
}
FALLBACK_PRICING: tuple[float, float] = (1.0, 2.0)

# Self-hosted models (feature/local-inference-server) run on hardware ARCF
# already owns, not a metered API -- billing them at FALLBACK_PRICING's
# conservative paid-provider rate would be actively wrong (fabricated
# nonzero cost for a free call, able to trip CostGuardrailExceededError
# for no real reason), not merely imprecise the way it is for a genuinely
# unrecognized paid model. Matched by LiteLLM provider prefix, not one
# hardcoded tag, so any locally-served model (Ollama today, others later)
# is covered without editing this table per model swap.
_LOCAL_MODEL_PREFIXES: tuple[str, ...] = ("ollama_chat/", "ollama/")
LOCAL_MODEL_PRICING: tuple[float, float] = (0.0, 0.0)


class CostEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    prompt_tokens: int
    assumed_completion_tokens: int
    estimated_cost_usd: float


class CostEstimator:
    def __init__(self, pricing: dict[str, tuple[float, float]] | None = None) -> None:
        self._pricing = pricing or DEFAULT_PRICING

    def count_tokens(self, text: str, model: str) -> int:
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        # disallowed_special=() — every caller here is counting tokens of
        # real file/prompt content for budget/cost estimation, never
        # constructing a payload that gets sent to a model verbatim (that
        # happens elsewhere, via LiteLLMClient). tiktoken's default raises
        # if the text merely CONTAINS a special-token-shaped substring
        # (e.g. a real repository file with "<|endoftext|>" in a string
        # literal, docstring, or test fixture — plausible in any LLM-
        # adjacent codebase); that default exists to stop accidental
        # special tokens from reaching a model, which isn't a risk here.
        return len(encoding.encode(text, disallowed_special=()))

    def _prices_for(self, model: str) -> tuple[float, float]:
        if model.startswith(_LOCAL_MODEL_PREFIXES):
            return LOCAL_MODEL_PRICING
        return self._pricing.get(model, FALLBACK_PRICING)

    def estimate(
        self, prompt: str, model: str, assumed_completion_tokens: int = 1024
    ) -> CostEstimate:
        prompt_tokens = self.count_tokens(prompt, model)
        prompt_price, completion_price = self._prices_for(model)
        cost = (prompt_tokens / 1_000_000) * prompt_price + (
            assumed_completion_tokens / 1_000_000
        ) * completion_price
        return CostEstimate(
            model=model,
            prompt_tokens=prompt_tokens,
            assumed_completion_tokens=assumed_completion_tokens,
            estimated_cost_usd=cost,
        )

    def actual_cost(self, prompt_tokens: int, completion_tokens: int, model: str) -> float:
        prompt_price, completion_price = self._prices_for(model)
        return (prompt_tokens / 1_000_000) * prompt_price + (
            completion_tokens / 1_000_000
        ) * completion_price


class CostGuardrail:
    def __init__(self, estimator: CostEstimator, max_cost_usd: float) -> None:
        self.estimator = estimator
        self._max_cost_usd = max_cost_usd

    def check(
        self, prompt: str, model: str, assumed_completion_tokens: int = 1024
    ) -> CostEstimate:
        estimate = self.estimator.estimate(prompt, model, assumed_completion_tokens)
        if estimate.estimated_cost_usd > self._max_cost_usd:
            raise CostGuardrailExceededError(estimate.estimated_cost_usd, self._max_cost_usd)
        return estimate
