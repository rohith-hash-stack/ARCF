from types import SimpleNamespace
from uuid import UUID

import litellm
import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from shared.config import Settings


def _fake_response(content: str = "generated output") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=5, total_tokens=10),
    )


@pytest.fixture
def patched_llm(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"count": 0}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        calls["count"] += 1
        return _fake_response()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    return calls


def _build_client(**settings_overrides: object) -> TestClient:
    defaults: dict[str, object] = {
        "api_keys_raw": "testkey:alice",
        "rate_limit_capacity": 100,
        "rate_limit_refill_per_second": 100.0,
        "cost_guardrail_max_usd": 10.0,
        "max_request_bytes": 1_000_000,
    }
    defaults.update(settings_overrides)
    settings = Settings(**defaults)  # type: ignore[arg-type]
    return TestClient(create_app(settings))


def test_missing_credentials_rejected(patched_llm: dict[str, int]) -> None:
    client = _build_client()
    response = client.post("/api/v1/execute", json={"prompt": "hello"})
    assert response.status_code == 401


def test_successful_execute_returns_response_and_trace_id(patched_llm: dict[str, int]) -> None:
    client = _build_client()
    response = client.post(
        "/api/v1/execute",
        json={"prompt": "hello", "model": "gpt-4o-mini"},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "generated output"
    assert body["usage"]["total_tokens"] == 10
    assert body["idempotent_replay"] is False
    assert "X-Trace-Id" in response.headers
    assert len(response.headers["X-Trace-Id"]) == 32
    assert UUID(body["request_id"])  # raises if not a valid UUID
    assert body["remaining_budget_usd"] == pytest.approx(10.0 - body["actual_cost_usd"])


def test_request_id_differs_across_separate_requests(patched_llm: dict[str, int]) -> None:
    client = _build_client()
    headers = {"X-API-Key": "testkey"}
    first = client.post("/api/v1/execute", json={"prompt": "hello"}, headers=headers)
    second = client.post("/api/v1/execute", json={"prompt": "goodbye"}, headers=headers)
    assert first.json()["request_id"] != second.json()["request_id"]


def test_idempotent_replay_does_not_call_llm_twice(patched_llm: dict[str, int]) -> None:
    client = _build_client()
    headers = {"X-API-Key": "testkey", "Idempotency-Key": "req-1"}
    payload = {"prompt": "hello", "model": "gpt-4o-mini"}

    first = client.post("/api/v1/execute", json=payload, headers=headers)
    second = client.post("/api/v1/execute", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["idempotent_replay"] is False
    assert second.json()["idempotent_replay"] is True
    assert patched_llm["count"] == 1


def test_idempotency_key_reuse_with_different_payload_conflicts(
    patched_llm: dict[str, int],
) -> None:
    client = _build_client()
    headers = {"X-API-Key": "testkey", "Idempotency-Key": "req-1"}

    first = client.post(
        "/api/v1/execute", json={"prompt": "hello", "model": "gpt-4o-mini"}, headers=headers
    )
    second = client.post(
        "/api/v1/execute", json={"prompt": "goodbye", "model": "gpt-4o-mini"}, headers=headers
    )

    assert first.status_code == 200
    assert second.status_code == 409


def test_rate_limit_exceeded_returns_429(patched_llm: dict[str, int]) -> None:
    client = _build_client(rate_limit_capacity=1, rate_limit_refill_per_second=0.0)
    headers = {"X-API-Key": "testkey"}
    payload = {"prompt": "hello", "model": "gpt-4o-mini"}

    first = client.post("/api/v1/execute", json=payload, headers=headers)
    second = client.post("/api/v1/execute", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 429
    assert "Retry-After" in second.headers


def test_cost_guardrail_rejects_expensive_request(patched_llm: dict[str, int]) -> None:
    client = _build_client(cost_guardrail_max_usd=0.0000001)
    response = client.post(
        "/api/v1/execute",
        json={"prompt": "hello", "model": "gpt-4o-mini"},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 402
    assert patched_llm["count"] == 0


def test_request_body_over_size_limit_returns_413(patched_llm: dict[str, int]) -> None:
    client = _build_client(max_request_bytes=10)
    response = client.post(
        "/api/v1/execute",
        json={"prompt": "this prompt is much longer than ten bytes"},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 413
