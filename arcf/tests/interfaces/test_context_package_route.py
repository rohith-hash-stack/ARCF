import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import litellm
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from interfaces.api.app import create_app
from shared.config import Settings

_CONFIDENT_PAYLOAD: dict[str, object] = {
    "intent_summary": "fix login bug",
    "domain": "backend",
    "task": "bug_fix",
    "entities": ["authenticate"],
    "constraints": [],
    "assumptions": [],
    "self_reported_confidence": 0.9,
    "suggested_clarifying_questions": [],
}

_UNDERSTANDING_PAYLOAD: dict[str, object] = {
    "summary": "auth.py defines authenticate, called from login.py.",
    "key_relationships": ["login.py -> auth.py"],
}


def _fake_response(payload: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )


@pytest.fixture
def patched_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    # SLM-1 (intent extraction) and SLM-2 (context understanding) prompts are
    # distinguishable by content, so one fake covers both regardless of call
    # order across the create-contract / code-intelligence / package sequence.
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        messages = kwargs.get("messages", [])
        prompt = messages[0]["content"] if messages else ""  # type: ignore[index]
        if "key_relationships" in prompt:
            return _fake_response(_UNDERSTANDING_PAYLOAD)
        return _fake_response(_CONFIDENT_PAYLOAD)

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


def _create_contract_with_code_intelligence(
    client: TestClient, repo: Path
) -> tuple[str, str]:
    """Returns (contract_id, context_resolution_id)."""
    created = client.post(
        "/api/v1/contracts",
        json={"raw_request": "fix the failing authenticate function"},
        headers={"X-API-Key": "testkey"},
    )
    contract_id: str = created.json()["contract_id"]

    ci_response = client.post(
        f"/api/v1/contracts/{contract_id}/code-intelligence",
        json={"target_names": ["authenticate"], "workspace_root": str(repo)},
        headers={"X-API-Key": "testkey"},
    )
    assert ci_response.status_code == 200
    resolution_id: str = ci_response.json()["resolution"]["id"]
    return contract_id, resolution_id


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (repo / "login.py").write_text(
        "from .auth import authenticate\n\ndef login(user):\n    return authenticate(user)\n"
    )
    return repo


def test_context_package_missing_credentials_rejected(tmp_path: Path, patched_llm: None) -> None:
    client = _build_client(tmp_path)
    response = client.post(
        "/api/v1/contracts/00000000-0000-0000-0000-000000000000/context-package",
        json={"max_tokens": 8000},
    )
    assert response.status_code == 401


def test_context_package_unknown_contract_returns_404(tmp_path: Path, patched_llm: None) -> None:
    client = _build_client(tmp_path)
    response = client.post(
        "/api/v1/contracts/00000000-0000-0000-0000-000000000000/context-package",
        json={"max_tokens": 8000},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 404


def test_context_package_without_code_intelligence_returns_400(
    tmp_path: Path, patched_llm: None
) -> None:
    client = _build_client(tmp_path)
    created = client.post(
        "/api/v1/contracts",
        json={"raw_request": "fix the failing authenticate function"},
        headers={"X-API-Key": "testkey"},
    )
    contract_id = created.json()["contract_id"]

    response = client.post(
        f"/api/v1/contracts/{contract_id}/context-package",
        json={"max_tokens": 8000},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 400


def test_context_package_survives_a_process_restart(tmp_path: Path, patched_llm: None) -> None:
    """G-new-4 (2026-08-17 independent verification report): before this
    fix, ContextResolutionStore was in-memory only. Contract.context_resolution_id
    IS durably stored (SqliteContractStore), so a caller resolving code
    intelligence, then hitting this exact /context-package endpoint after
    a real process restart (a brand new create_app() instance, sharing
    nothing but the same on-disk db paths -- the same simulation
    test_contract_store.py's own persistence test uses), would previously
    get a dangling reference: the contract's own context_resolution_id
    field would resolve fine, but the ContextResolutionResult it points
    to would already be gone. Proves it no longer is."""
    repo = _make_repo(tmp_path)
    db_path = str(tmp_path / "contracts.db")
    resolution_db_path = str(tmp_path / "context_resolutions.db")

    first_process_client = _build_client(
        tmp_path, contract_store_path=db_path, context_resolution_store_path=resolution_db_path
    )
    contract_id, resolution_id = _create_contract_with_code_intelligence(
        first_process_client, repo
    )

    # A brand new create_app() call, sharing nothing with the first
    # client but the on-disk db paths -- this is the "restart."
    second_process_client = _build_client(
        tmp_path, contract_store_path=db_path, context_resolution_store_path=resolution_db_path
    )
    response = second_process_client.post(
        f"/api/v1/contracts/{contract_id}/context-package",
        json={"max_tokens": 8000},
        headers={"X-API-Key": "testkey"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["package"]["context_resolution_id"] == resolution_id


def test_context_package_full_flow(tmp_path: Path, patched_llm: None) -> None:
    repo = _make_repo(tmp_path)
    client = _build_client(tmp_path)
    contract_id, _ = _create_contract_with_code_intelligence(client, repo)

    response = client.post(
        f"/api/v1/contracts/{contract_id}/context-package",
        json={"max_tokens": 8000},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 200
    body = response.json()
    package = body["package"]
    assert {f["file_path"] for f in package["relevant_files"]} == {"auth.py", "login.py"}
    assert package["understanding_notes"] == [
        "auth.py defines authenticate, called from login.py.",
        "login.py -> auth.py",
    ]
    assert package["budget_max_tokens"] == 8000
    assert body["remaining_budget_usd"] < 10.0


def test_context_package_cost_guardrail_rejects_expensive_request(
    tmp_path: Path, patched_llm: None
) -> None:
    # Contract creation (SLM-1) and code-intelligence attachment need a normal
    # budget to succeed; only the context-package call (SLM-2) should be
    # guardrail-rejected. A second client with a tight budget shares the
    # contract via the same SQLite-backed contract store, but
    # ContextResolutionStore is deliberately in-memory-per-app (see its
    # module docstring), so the resolution result has to be copied across
    # for this two-client test setup — a real deployment is one process
    # with one store, so this isn't a production concern, only a test one.
    repo = _make_repo(tmp_path)
    db_path = str(tmp_path / "contracts.db")

    setup_client = _build_client(tmp_path, contract_store_path=db_path)
    contract_id, resolution_id = _create_contract_with_code_intelligence(setup_client, repo)

    tight_client = _build_client(
        tmp_path, contract_store_path=db_path, cost_guardrail_max_usd=0.0000001
    )
    setup_app = cast(FastAPI, setup_client.app)
    tight_app = cast(FastAPI, tight_client.app)
    resolution = setup_app.state.context_resolution_store.get(UUID(resolution_id))
    assert resolution is not None
    tight_app.state.context_resolution_store.save(resolution)

    response = tight_client.post(
        f"/api/v1/contracts/{contract_id}/context-package",
        json={"max_tokens": 8000},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 402
