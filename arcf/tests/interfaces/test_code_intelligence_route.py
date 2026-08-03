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
    "entities": ["authenticate"],
    "constraints": [],
    "assumptions": [],
    "self_reported_confidence": 0.9,
    "suggested_clarifying_questions": [],
}


def _fake_response(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )


@pytest.fixture
def patched_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response(_CONFIDENT_PAYLOAD)

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)


def _build_client(tmp_path: Path, **settings_overrides: object) -> TestClient:
    defaults: dict[str, object] = {
        "api_keys_raw": "testkey:alice",
        "rate_limit_capacity": 100,
        "rate_limit_refill_per_second": 100.0,
        "cost_guardrail_max_usd": 10.0,
        "contract_store_path": str(tmp_path / "contracts.db"),
    }
    defaults.update(settings_overrides)
    settings = Settings(**defaults)  # type: ignore[arg-type]
    return TestClient(create_app(settings))


def _create_contract(client: TestClient) -> str:
    response = client.post(
        "/api/v1/contracts",
        json={"raw_request": "fix the failing authenticate function"},
        headers={"X-API-Key": "testkey"},
    )
    contract_id: str = response.json()["contract_id"]
    return contract_id


def test_build_code_intelligence_missing_credentials_rejected(
    tmp_path: Path, patched_llm: None
) -> None:
    client = _build_client(tmp_path)
    response = client.post(
        "/api/v1/contracts/00000000-0000-0000-0000-000000000000/code-intelligence",
        json={"target_names": ["authenticate"]},
    )
    assert response.status_code == 401


def test_build_code_intelligence_unknown_contract_returns_404(
    tmp_path: Path, patched_llm: None
) -> None:
    client = _build_client(tmp_path)
    response = client.post(
        "/api/v1/contracts/00000000-0000-0000-0000-000000000000/code-intelligence",
        json={"target_names": ["authenticate"], "workspace_root": str(tmp_path)},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 404


def test_build_code_intelligence_no_workspace_returns_400(
    tmp_path: Path, patched_llm: None
) -> None:
    client = _build_client(tmp_path)
    contract_id = _create_contract(client)

    response = client.post(
        f"/api/v1/contracts/{contract_id}/code-intelligence",
        json={"target_names": ["authenticate"]},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 400


def test_build_code_intelligence_bad_workspace_path_returns_400(
    tmp_path: Path, patched_llm: None
) -> None:
    client = _build_client(tmp_path)
    contract_id = _create_contract(client)

    response = client.post(
        f"/api/v1/contracts/{contract_id}/code-intelligence",
        json={
            "target_names": ["authenticate"],
            "workspace_root": str(tmp_path / "does_not_exist"),
        },
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 400


def test_build_code_intelligence_resolves_and_evolves_contract(
    tmp_path: Path, patched_llm: None
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (repo / "login.py").write_text(
        "from .auth import authenticate\n\ndef login(user):\n    return authenticate(user)\n"
    )

    client = _build_client(tmp_path)
    contract_id = _create_contract(client)

    response = client.post(
        f"/api/v1/contracts/{contract_id}/code-intelligence",
        json={"target_names": ["authenticate"], "workspace_root": str(repo)},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["contract_id"] == contract_id
    assert body["contract_version"] == 2
    assert body["resolution"]["confidence"] == 1.0
    candidate_paths = {f["file_path"] for f in body["resolution"]["candidate_files"]}
    assert candidate_paths == {"auth.py", "login.py"}


def test_build_code_intelligence_reuses_attached_workspace_root(
    tmp_path: Path, patched_llm: None
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "auth.py").write_text("def authenticate(user):\n    return True\n")

    client = _build_client(tmp_path)
    contract_id = _create_contract(client)

    attach_response = client.post(
        f"/api/v1/contracts/{contract_id}/workspace",
        json={"workspace_root": str(repo)},
        headers={"X-API-Key": "testkey"},
    )
    assert attach_response.status_code == 200

    response = client.post(
        f"/api/v1/contracts/{contract_id}/code-intelligence",
        json={"target_names": ["authenticate"]},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 200
    assert response.json()["contract_version"] == 3
