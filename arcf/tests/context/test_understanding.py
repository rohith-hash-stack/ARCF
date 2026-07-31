import json
from types import SimpleNamespace

import litellm
import pytest

from context.relevance_ranker import RankedFile
from context.understanding import ContextUnderstandingAnalyzer
from infrastructure.llm_client import LiteLLMClient
from shared.errors import ContextUnderstandingError

_VALID_PAYLOAD = {
    "summary": "These files implement authentication.",
    "key_relationships": ["login.py calls auth.py's authenticate"],
}


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10, total_tokens=30),
    )


async def _no_sleep(seconds: float) -> None:
    return None


def _analyzer() -> ContextUnderstandingAnalyzer:
    client = LiteLLMClient(max_retries=1, base_delay_seconds=0.0, sleep=_no_sleep)
    return ContextUnderstandingAnalyzer(client, "gpt-4o-mini", max_parse_retries=2)


def _ranked_files() -> list[RankedFile]:
    return [
        RankedFile(
            file_path="auth.py",
            relevance_score=1.0,
            reason="defines authenticate",
            language="python",
            token_count=50,
        )
    ]


async def test_analyze_returns_parsed_note_and_llm_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response(json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    note, response = await _analyzer().analyze("fix the auth bug", _ranked_files(), [])

    assert note.summary == _VALID_PAYLOAD["summary"]
    assert note.key_relationships == _VALID_PAYLOAD["key_relationships"]
    assert response.total_tokens == 30


async def test_requests_json_object_response_format(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _fake_response(json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    await _analyzer().analyze("task", _ranked_files(), [])

    assert captured["response_format"] == {"type": "json_object"}


async def test_retries_on_invalid_json_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        calls["count"] += 1
        if calls["count"] == 1:
            return _fake_response("not json")
        return _fake_response(json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    note, _ = await _analyzer().analyze("task", _ranked_files(), [])

    assert calls["count"] == 2
    assert note.summary == _VALID_PAYLOAD["summary"]


async def test_raises_context_understanding_error_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("still not json")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    with pytest.raises(ContextUnderstandingError):
        await _analyzer().analyze("task", _ranked_files(), [])


async def test_defaults_key_relationships_to_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response(json.dumps({"summary": "short summary"}))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    note, _ = await _analyzer().analyze("task", _ranked_files(), [])

    assert note.key_relationships == []
