import json
from types import SimpleNamespace
from uuid import uuid4

import litellm
import pytest

from domain.context_package import ContextPackage, PackagedFile
from domain.context_resolution import DependencyEdge
from execution.prhl import PRHLAnalyzer
from infrastructure.llm_client import LiteLLMClient
from shared.errors import PRHLError

_VALID_PAYLOAD = {
    "likely_direction": "Add a new method to AuthService and wire it into the login route.",
    "probable_touchpoints": ["auth/service.py", "routes/login.py"],
    "expected_diff_scope": "medium",
    "anticipated_dependencies": [],
    "risk_flags": ["touches code with no test coverage"],
}


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10, total_tokens=30),
    )


async def _no_sleep(seconds: float) -> None:
    return None


def _analyzer() -> PRHLAnalyzer:
    client = LiteLLMClient(max_retries=1, base_delay_seconds=0.0, sleep=_no_sleep)
    return PRHLAnalyzer(client, "gpt-4o-mini", max_parse_retries=2)


def _package() -> ContextPackage:
    return ContextPackage(
        contract_id="contract-1",
        workspace_id="workspace-1",
        context_resolution_id=uuid4(),
        relevant_files=[
            PackagedFile(
                file_path="auth/service.py",
                content="class AuthService: ...",
                relevance_score=1.0,
                reason="defines authenticate",
                token_count=50,
                truncated=False,
            )
        ],
        dependency_chain=[DependencyEdge(from_file="routes/login.py", to_file="auth/service.py")],
        budget_max_tokens=1000,
        budget_used_tokens=50,
        prompt_compression_ratio=1.0,
        excluded_file_count=0,
    )


async def test_analyze_returns_parsed_hint_and_llm_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response(json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    hint, response = await _analyzer().analyze("fix the auth bug", _package())

    assert hint.likely_direction == _VALID_PAYLOAD["likely_direction"]
    assert hint.probable_touchpoints == _VALID_PAYLOAD["probable_touchpoints"]
    assert hint.expected_diff_scope == "medium"
    assert hint.risk_flags == _VALID_PAYLOAD["risk_flags"]
    assert response.total_tokens == 30


async def test_requests_json_object_response_format(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _fake_response(json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    await _analyzer().analyze("task", _package())

    assert captured["response_format"] == {"type": "json_object"}


async def test_retries_on_invalid_json_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        calls["count"] += 1
        if calls["count"] == 1:
            return _fake_response("not json")
        return _fake_response(json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    hint, _ = await _analyzer().analyze("task", _package())

    assert calls["count"] == 2
    assert hint.expected_diff_scope == "medium"


async def test_raises_prhl_error_after_exhausting_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("still not json")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    with pytest.raises(PRHLError):
        await _analyzer().analyze("task", _package())


async def test_rejects_diff_scope_outside_enum(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        calls["count"] += 1
        bad_payload = {**_VALID_PAYLOAD, "expected_diff_scope": "huge"}
        return _fake_response(json.dumps(bad_payload))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    with pytest.raises(PRHLError):
        await _analyzer().analyze("task", _package())

    assert calls["count"] == 2


async def test_defaults_optional_lists_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    minimal_payload = {
        "likely_direction": "Add a helper function.",
        "expected_diff_scope": "small",
    }

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response(json.dumps(minimal_payload))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    hint, _ = await _analyzer().analyze("task", _package())

    assert hint.probable_touchpoints == []
    assert hint.anticipated_dependencies == []
    assert hint.risk_flags == []
