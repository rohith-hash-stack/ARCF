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


def _fake_response() -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(_CONFIDENT_PAYLOAD)))],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )


@pytest.fixture
def patched_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)


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


def _create_contract(client: TestClient) -> str:
    response = client.post(
        "/api/v1/contracts",
        json={"raw_request": "fix the failing login test"},
        headers={"X-API-Key": "testkey"},
    )
    result: str = response.json()["contract_id"]
    return result


def test_attach_workspace_evolves_contract(tmp_path: Path, patched_llm: None) -> None:
    workspace_dir = tmp_path / "repo"
    workspace_dir.mkdir()
    (workspace_dir / "app.py").write_text("print(1)")

    client = _build_client(tmp_path)
    contract_id = _create_contract(client)

    response = client.post(
        f"/api/v1/contracts/{contract_id}/workspace",
        json={"workspace_root": str(workspace_dir)},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2
    assert body["contract"]["workspace_metadata"] is not None
    assert body["contract"]["workspace_metadata"]["file_count"] == 1


def test_attach_workspace_unknown_contract_returns_404(tmp_path: Path, patched_llm: None) -> None:
    client = _build_client(tmp_path)
    response = client.post(
        "/api/v1/contracts/00000000-0000-0000-0000-000000000000/workspace",
        json={"workspace_root": str(tmp_path)},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 404


def test_attach_workspace_missing_credentials_rejected(
    tmp_path: Path, patched_llm: None
) -> None:
    client = _build_client(tmp_path)
    response = client.post(
        "/api/v1/contracts/00000000-0000-0000-0000-000000000000/workspace",
        json={"workspace_root": str(tmp_path)},
    )
    assert response.status_code == 401


def test_attach_workspace_rejects_disallowed_root(tmp_path: Path, patched_llm: None) -> None:
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    other_dir = tmp_path / "other"
    other_dir.mkdir()

    client = _build_client(tmp_path, workspace_allowlist_raw=str(allowed_dir))
    contract_id = _create_contract(client)

    response = client.post(
        f"/api/v1/contracts/{contract_id}/workspace",
        json={"workspace_root": str(other_dir)},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 403


def test_attach_workspace_invalid_path_returns_400(tmp_path: Path, patched_llm: None) -> None:
    client = _build_client(tmp_path)
    contract_id = _create_contract(client)

    response = client.post(
        f"/api/v1/contracts/{contract_id}/workspace",
        json={"workspace_root": str(tmp_path / "does_not_exist")},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 400
