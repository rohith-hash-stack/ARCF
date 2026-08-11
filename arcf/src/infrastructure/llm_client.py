"""LiteLLM wrapper — provider-independent completion with retry.

Only transient provider errors (rate limit, connection, timeout,
service/internal errors) are retried with exponential backoff.
Non-retryable errors (bad request, auth, content policy) fail on the
first attempt — retrying them would just waste the guardrail budget
already spent estimating cost.
"""

import asyncio
from collections.abc import Awaitable, Callable

import litellm
from pydantic import BaseModel, ConfigDict

from shared.errors import LLMInvocationError

_RETRYABLE_NAMES = (
    "RateLimitError",
    "APIConnectionError",
    "Timeout",
    "ServiceUnavailableError",
    "InternalServerError",
)
RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = tuple(
    exc_type
    for exc_type in (getattr(litellm, name, None) for name in _RETRYABLE_NAMES)
    if isinstance(exc_type, type) and issubclass(exc_type, Exception)
) or (Exception,)


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    attempts: int


class LiteLLMClient:
    def __init__(
        self,
        max_retries: int,
        base_delay_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._max_retries = max(1, max_retries)
        self._base_delay_seconds = base_delay_seconds
        self._sleep = sleep

    async def complete(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 1024,
        response_format: dict[str, str] | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """`temperature` is opt-in and defaulted to `None` (provider
        default, unchanged for every existing caller) — pass 0.0 for
        deterministic structured-extraction calls where reproducibility
        matters more than variation (see IntentExtractor, whose SLM-1
        entity extraction was confirmed non-deterministic at the provider
        default via scripts/slm1_determinism_experiment.py: the SAME
        query's `entities` varied run to run with temperature unset,
        converged to a single stable result at temperature=0)."""
        last_exc: Exception | None = None
        extra_kwargs: dict[str, float] = {} if temperature is None else {"temperature": temperature}

        for attempt in range(1, self._max_retries + 1):
            try:
                response = await litellm.acompletion(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    response_format=response_format,
                    **extra_kwargs,
                )
            except RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                if attempt == self._max_retries:
                    raise LLMInvocationError(
                        f"LLM call failed after {attempt} attempts: {exc}"
                    ) from exc
                await self._sleep(self._base_delay_seconds * (2 ** (attempt - 1)))
                continue
            except Exception as exc:
                raise LLMInvocationError(f"LLM call failed (non-retryable): {exc}") from exc

            usage = response.usage
            content = response.choices[0].message.content or ""
            return LLMResponse(
                content=content,
                model=model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                attempts=attempt,
            )

        raise LLMInvocationError(f"LLM call failed after {self._max_retries} attempts: {last_exc}")
