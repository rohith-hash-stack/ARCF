from types import SimpleNamespace

import litellm
import pytest

import infrastructure.llm_client as llm_client_module
from infrastructure.llm_client import LiteLLMClient
from shared.errors import LLMInvocationError


def _fake_response(content: str, prompt_tokens: int, completion_tokens: int) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


async def _no_sleep(seconds: float) -> None:
    return None


async def test_successful_call_returns_response(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("hello", 10, 5)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    client = LiteLLMClient(max_retries=3, base_delay_seconds=0.01, sleep=_no_sleep)
    result = await client.complete("hi", "gpt-4o-mini")
    assert result.content == "hello"
    assert result.attempts == 1
    assert result.total_tokens == 15


async def test_retries_on_retryable_error_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client_module, "RETRYABLE_EXCEPTIONS", (ConnectionError,))
    calls = {"count": 0}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        calls["count"] += 1
        if calls["count"] < 2:
            raise ConnectionError("transient")
        return _fake_response("ok", 1, 1)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    sleeps: list[float] = []

    async def recording_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = LiteLLMClient(max_retries=3, base_delay_seconds=0.01, sleep=recording_sleep)
    result = await client.complete("hi", "gpt-4o-mini")
    assert result.attempts == 2
    assert len(sleeps) == 1


async def test_exhausts_retries_and_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client_module, "RETRYABLE_EXCEPTIONS", (ConnectionError,))

    async def always_fails(**kwargs: object) -> SimpleNamespace:
        raise ConnectionError("still down")

    monkeypatch.setattr(litellm, "acompletion", always_fails)
    client = LiteLLMClient(max_retries=2, base_delay_seconds=0.01, sleep=_no_sleep)
    with pytest.raises(LLMInvocationError):
        await client.complete("hi", "gpt-4o-mini")


async def test_non_retryable_error_fails_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_client_module, "RETRYABLE_EXCEPTIONS", (ConnectionError,))
    calls = {"count": 0}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        calls["count"] += 1
        raise ValueError("bad request")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    client = LiteLLMClient(max_retries=3, base_delay_seconds=0.01, sleep=_no_sleep)
    with pytest.raises(LLMInvocationError):
        await client.complete("hi", "gpt-4o-mini")
    assert calls["count"] == 1
