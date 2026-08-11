import json
from types import SimpleNamespace

import litellm
import pytest

from contracts.intent_extraction import IntentExtractor
from infrastructure.llm_client import LiteLLMClient
from shared.errors import IntentExtractionError

_VALID_PAYLOAD = {
    "intent_summary": "fix login bug",
    "domain": "backend",
    "task": "bug_fix",
    "entities": ["login.py"],
    "constraints": [],
    "assumptions": [],
    "self_reported_confidence": 0.8,
    "suggested_clarifying_questions": [],
}


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )


async def _no_sleep(seconds: float) -> None:
    return None


def _extractor() -> IntentExtractor:
    client = LiteLLMClient(max_retries=1, base_delay_seconds=0.0, sleep=_no_sleep)
    return IntentExtractor(llm_client=client, model="gpt-4o-mini", max_parse_retries=2)


async def test_extract_returns_parsed_result_and_llm_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response(json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    extractor = _extractor()
    raw, llm_response = await extractor.extract("fix the login bug in login.py")

    assert raw.domain == "backend"
    assert raw.task == "bug_fix"
    assert raw.entities == ["login.py"]
    assert llm_response.total_tokens == 70


async def test_retries_on_invalid_json_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        calls["count"] += 1
        if calls["count"] == 1:
            return _fake_response("not valid json")
        return _fake_response(json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    extractor = _extractor()
    raw, _ = await extractor.extract("fix the login bug")

    assert calls["count"] == 2
    assert raw.domain == "backend"


async def test_raises_after_exhausting_parse_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("this is not json at all")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    extractor = _extractor()
    with pytest.raises(IntentExtractionError):
        await extractor.extract("fix the login bug")


async def test_raises_on_schema_validation_failure_after_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_payload = dict(_VALID_PAYLOAD)
    del invalid_payload["domain"]  # required field missing

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response(json.dumps(invalid_payload))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    extractor = _extractor()
    with pytest.raises(IntentExtractionError):
        await extractor.extract("fix the login bug")


async def test_requests_json_object_response_format(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _fake_response(json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    extractor = _extractor()
    await extractor.extract("fix the login bug")

    assert captured["response_format"] == {"type": "json_object"}


async def test_requests_deterministic_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    """arcf-slm1-entity-extraction (2026-08-11,
    scripts/slm1_determinism_experiment.py): SLM-1's entities were
    confirmed non-deterministic at the provider's default temperature —
    the SAME query's entities varied run to run. Structured extraction,
    not creative generation, so temperature=0.0 must reach every call,
    not just the first attempt."""
    captured: dict[str, object] = {}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _fake_response(json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    extractor = _extractor()
    await extractor.extract("fix the login bug")

    assert captured["temperature"] == 0.0


async def test_prompt_forbids_prose_entities_and_requires_identifier_grammar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """arcf-grounding-validation-entity-extraction-gap (2026-08-11): a
    real Consul benchmark found SLM-1 frequently returning natural-
    language noun phrases ("Agent cache", "New function", "downstream
    service check listeners") as entities, which ReferenceResolver.
    resolve()'s exact-match requirement can never resolve -- silently
    falling through to weak evidence-contract matching. This can only be
    verified at the prompt-content level (an LLM's actual compliance
    with a prompt isn't something a unit test can assert -- that's what
    scripts/validate_llm_grounding.py's real-Consul re-run is for), but
    the instruction the prompt gives the model must at minimum say the
    right thing."""
    captured: dict[str, object] = {}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _fake_response(json.dumps(_VALID_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    extractor = _extractor()
    await extractor.extract("Trace how Agent cache updates propagate to downstream service check listeners.")

    prompt = captured["messages"][0]["content"]
    assert "PascalCase" in prompt
    assert "snake_case" in prompt
    assert "path-qualified hint" in prompt
    assert "service check listeners" in prompt  # the real failing example, cited directly
