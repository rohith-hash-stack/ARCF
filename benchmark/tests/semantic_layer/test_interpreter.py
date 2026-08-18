import json
from types import SimpleNamespace

import litellm
import pytest
from infrastructure.llm_client import LiteLLMClient

from benchmark.semantic_layer.contract import UncertaintyLevel
from benchmark.semantic_layer.errors import SemanticInterpretationError
from benchmark.semantic_layer.interpreter import (
    BypassInterpreter,
    ExistingSlm1Interpreter,
    LLMSemanticInterpreter,
)

_VALID_SLM1_PAYLOAD = {
    "intent_summary": "find auth handler",
    "domain": "backend",
    "task": "bug_fix",
    "entities": ["auth.py", "Authenticator"],
    "constraints": [],
    "assumptions": [],
    "self_reported_confidence": 0.8,
    "suggested_clarifying_questions": [],
}

_VALID_SPECIALIZED_PAYLOAD = {
    "intent": "locate_symbol",
    "retrieval_terms": ["Authenticator", "auth.py"],
    "concepts": ["JWT validation"],
    "behavior": ["reject invalid tokens"],
    "framework": None,
    "confidence": "high",
    "is_ambiguous": False,
    "ambiguous_alternatives": [],
    "is_negative_query": False,
    "negation_targets": [],
}


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )


async def _no_sleep(seconds: float) -> None:
    return None


def _client() -> LiteLLMClient:
    return LiteLLMClient(max_retries=1, base_delay_seconds=0.0, sleep=_no_sleep)


async def test_existing_slm1_interpreter_wraps_real_intent_extractor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response(json.dumps(_VALID_SLM1_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    interpreter = ExistingSlm1Interpreter(_client(), model="gpt-4o-mini")
    result = await interpreter.interpret("find the auth handler")

    assert result.interpretation.retrieval_terms == ["auth.py", "Authenticator"]
    assert result.interpretation.confidence == UncertaintyLevel.HIGH
    assert result.prompt_tokens == 50
    assert result.malformed_attempts == 0


async def test_existing_slm1_interpreter_raises_semantic_interpretation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("not json")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    interpreter = ExistingSlm1Interpreter(_client(), model="gpt-4o-mini")
    with pytest.raises(SemanticInterpretationError):
        await interpreter.interpret("find the auth handler")


async def test_llm_semantic_interpreter_parses_specialized_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response(json.dumps(_VALID_SPECIALIZED_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    interpreter = LLMSemanticInterpreter(_client(), model="ollama_chat/qwen2.5:1.5b-instruct")
    result = await interpreter.interpret("how are JWTs validated?")

    assert result.interpretation.retrieval_terms == ["Authenticator", "auth.py"]
    assert result.interpretation.concepts == ["JWT validation"]
    assert result.malformed_attempts == 0


async def test_llm_semantic_interpreter_retries_then_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("{not valid json")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    interpreter = LLMSemanticInterpreter(_client(), model="ollama_chat/qwen2.5:1.5b-instruct",
                                          max_parse_retries=2)
    with pytest.raises(SemanticInterpretationError):
        await interpreter.interpret("how are JWTs validated?")


async def test_bypass_interpreter_makes_no_llm_call() -> None:
    interpreter = BypassInterpreter()
    result = await interpreter.interpret("anything at all")

    assert result.interpretation.retrieval_terms == []
    assert result.interpretation.confidence == UncertaintyLevel.UNCERTAIN
    assert result.prompt_tokens == 0
    assert result.attempts == 0
