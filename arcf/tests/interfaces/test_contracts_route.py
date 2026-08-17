import json
from pathlib import Path
from types import SimpleNamespace

import litellm
import pytest
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from shared.config import Settings

_CONFIDENT_PAYLOAD = {
    "intent_summary": "fix login bug",
    "domain": "backend",
    "task": "bug_fix",
    "entities": ["login.py"],
    "constraints": [],
    "assumptions": [],
    "self_reported_confidence": 0.9,
    "suggested_clarifying_questions": [],
}

_AMBIGUOUS_PAYLOAD = {
    "intent_summary": "do something",
    "domain": "unknown",
    "task": "unknown",
    "entities": [],
    "constraints": [],
    "assumptions": [],
    "self_reported_confidence": 0.3,
    "suggested_clarifying_questions": [],
}


def _fake_response(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )


@pytest.fixture
def patched_llm(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, object]]]:
    state: dict[str, list[dict[str, object]]] = {"queue": [dict(_CONFIDENT_PAYLOAD)]}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        payload = state["queue"].pop(0) if len(state["queue"]) > 1 else state["queue"][0]
        return _fake_response(payload)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    return state


def _build_client(tmp_path: Path, **settings_overrides: object) -> TestClient:
    defaults: dict[str, object] = {
        "api_keys_raw": "testkey:alice",
        "rate_limit_capacity": 100,
        "rate_limit_refill_per_second": 100.0,
        "cost_guardrail_max_usd": 10.0,
        "contract_store_path": str(tmp_path / "contracts.db"),
        "context_resolution_store_path": str(tmp_path / "context_resolutions.db"),
    }
    defaults.update(settings_overrides)
    settings = Settings(**defaults)  # type: ignore[arg-type]
    return TestClient(create_app(settings))


def test_create_contract_missing_credentials_rejected(
    tmp_path: Path, patched_llm: dict[str, list[dict[str, object]]]
) -> None:
    client = _build_client(tmp_path)
    response = client.post("/api/v1/contracts", json={"raw_request": "fix the login bug"})
    assert response.status_code == 401


def test_create_contract_approved_when_confident(
    tmp_path: Path, patched_llm: dict[str, list[dict[str, object]]]
) -> None:
    client = _build_client(tmp_path)
    response = client.post(
        "/api/v1/contracts",
        json={"raw_request": "fix the failing login test in login.py"},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["needs_clarification"] is False
    assert body["version"] == 1
    assert body["contract"]["intent"]["domain"] == "backend"
    assert body["remaining_budget_usd"] < 10.0


def test_create_contract_needs_clarification_when_ambiguous(
    tmp_path: Path, patched_llm: dict[str, list[dict[str, object]]]
) -> None:
    patched_llm["queue"] = [dict(_AMBIGUOUS_PAYLOAD)]
    client = _build_client(tmp_path)
    response = client.post(
        "/api/v1/contracts",
        json={"raw_request": "do the thing"},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_clarification"
    assert body["needs_clarification"] is True
    assert len(body["clarifying_questions"]) > 0


def test_clarify_evolves_to_version_two(
    tmp_path: Path, patched_llm: dict[str, list[dict[str, object]]]
) -> None:
    patched_llm["queue"] = [dict(_AMBIGUOUS_PAYLOAD), dict(_CONFIDENT_PAYLOAD)]
    client = _build_client(tmp_path)

    created = client.post(
        "/api/v1/contracts",
        json={"raw_request": "do the thing"},
        headers={"X-API-Key": "testkey"},
    )
    contract_id = created.json()["contract_id"]

    clarified = client.post(
        f"/api/v1/contracts/{contract_id}/clarify",
        json={"answer": "I mean fix login.py"},
        headers={"X-API-Key": "testkey"},
    )
    assert clarified.status_code == 200
    body = clarified.json()
    assert body["contract_id"] == contract_id
    assert body["version"] == 2
    assert body["status"] == "approved"


def test_clarify_unknown_contract_returns_404(
    tmp_path: Path, patched_llm: dict[str, list[dict[str, object]]]
) -> None:
    client = _build_client(tmp_path)
    response = client.post(
        "/api/v1/contracts/00000000-0000-0000-0000-000000000000/clarify",
        json={"answer": "answer"},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 404


def test_get_contract_returns_persisted_contract(
    tmp_path: Path, patched_llm: dict[str, list[dict[str, object]]]
) -> None:
    client = _build_client(tmp_path)
    created = client.post(
        "/api/v1/contracts",
        json={"raw_request": "fix the failing login test in login.py"},
        headers={"X-API-Key": "testkey"},
    )
    contract_id = created.json()["contract_id"]

    fetched = client.get(f"/api/v1/contracts/{contract_id}", headers={"X-API-Key": "testkey"})
    assert fetched.status_code == 200
    assert fetched.json()["contract_id"] == contract_id


def test_get_contract_unknown_id_returns_404(
    tmp_path: Path, patched_llm: dict[str, list[dict[str, object]]]
) -> None:
    client = _build_client(tmp_path)
    response = client.get(
        "/api/v1/contracts/00000000-0000-0000-0000-000000000000",
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 404


def test_cost_guardrail_rejects_expensive_request(
    tmp_path: Path, patched_llm: dict[str, list[dict[str, object]]]
) -> None:
    client = _build_client(tmp_path, cost_guardrail_max_usd=0.0000001)
    response = client.post(
        "/api/v1/contracts",
        json={"raw_request": "fix the failing login test"},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 402
