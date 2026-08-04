from pathlib import Path
from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain.execution_ledger import ExecutionLedgerEntry
from infrastructure.execution_ledger_db import ExecutionLedgerStore
from interfaces.api.app import create_app
from shared.config import Settings


def _build_client(tmp_path: Path, **settings_overrides: object) -> TestClient:
    defaults: dict[str, object] = {
        "api_keys_raw": "testkey:alice",
        "rate_limit_capacity": 100,
        "rate_limit_refill_per_second": 100.0,
        "contract_store_path": str(tmp_path / "contracts.db"),
        "execution_ledger_db_path": str(tmp_path / "ledger.db"),
    }
    defaults.update(settings_overrides)
    settings = Settings(**defaults)  # type: ignore[arg-type]
    return TestClient(create_app(settings))


def _seed(client: TestClient, **overrides: object) -> ExecutionLedgerEntry:
    defaults: dict[str, object] = {
        "workspace_id": "workspace-1",
        "contract_id": "contract-1",
        "mode": "arcf",
        "model": "gpt-4o-mini",
        "prompt": "fix the bug",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "latency_ms": 250.0,
        "estimated_cost_usd": 0.01,
        "artifact_content": "line one\nline two\n",
    }
    defaults.update(overrides)
    entry = ExecutionLedgerEntry(**defaults)  # type: ignore[arg-type]
    app = cast(FastAPI, client.app)
    store = cast(ExecutionLedgerStore, app.state.execution_ledger_store)
    store.save(entry)
    return entry


def test_list_executions_missing_credentials_rejected(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    response = client.get("/api/v1/executions")
    assert response.status_code == 401


def test_list_executions_returns_seeded_entries(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    entry = _seed(client)

    response = client.get("/api/v1/executions", headers={"X-API-Key": "testkey"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["request_id"] == str(entry.request_id)


def test_list_executions_respects_limit(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    for _ in range(3):
        _seed(client)

    response = client.get(
        "/api/v1/executions", params={"limit": 2}, headers={"X-API-Key": "testkey"}
    )
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_execution_returns_seeded_entry(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    entry = _seed(client)

    response = client.get(
        f"/api/v1/executions/{entry.request_id}", headers={"X-API-Key": "testkey"}
    )
    assert response.status_code == 200
    assert response.json()["prompt"] == "fix the bug"


def test_get_execution_unknown_id_returns_404(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    response = client.get(f"/api/v1/executions/{uuid4()}", headers={"X-API-Key": "testkey"})
    assert response.status_code == 404


def test_delete_execution_removes_entry(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    entry = _seed(client)

    response = client.delete(
        f"/api/v1/executions/{entry.request_id}", headers={"X-API-Key": "testkey"}
    )
    assert response.status_code == 204

    follow_up = client.get(
        f"/api/v1/executions/{entry.request_id}", headers={"X-API-Key": "testkey"}
    )
    assert follow_up.status_code == 404


def test_delete_execution_unknown_id_returns_404(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    response = client.delete(f"/api/v1/executions/{uuid4()}", headers={"X-API-Key": "testkey"})
    assert response.status_code == 404


def test_patch_execution_sets_manual_rating(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    entry = _seed(client)

    response = client.patch(
        f"/api/v1/executions/{entry.request_id}",
        json={"manual_rating": 4},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 200
    assert response.json()["manual_rating"] == 4


def test_patch_execution_sets_build_and_test_result(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    entry = _seed(client)

    response = client.patch(
        f"/api/v1/executions/{entry.request_id}",
        json={"build_result": "passed", "test_result": "failed"},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["build_result"] == "passed"
    assert body["test_result"] == "failed"


def test_seeded_entry_defaults_for_new_fields(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    entry = _seed(client)

    response = client.get(
        f"/api/v1/executions/{entry.request_id}", headers={"X-API-Key": "testkey"}
    )
    body = response.json()
    assert body["execution_status"] == "success"
    assert body["files_changed"] == []
    assert body["lines_changed"] == 0
    assert body["build_result"] is None
    assert body["test_result"] is None


def test_patch_execution_requires_at_least_one_field(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    entry = _seed(client)

    response = client.patch(
        f"/api/v1/executions/{entry.request_id}",
        json={},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 400


def test_patch_execution_unknown_id_returns_404(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    response = client.patch(
        f"/api/v1/executions/{uuid4()}",
        json={"manual_rating": 3},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 404


def test_compare_executions_returns_deltas_and_diff(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    entry_a = _seed(
        client,
        total_tokens=100,
        estimated_cost_usd=0.01,
        latency_ms=100.0,
        artifact_content="line one\nline two\n",
    )
    entry_b = _seed(
        client,
        total_tokens=150,
        estimated_cost_usd=0.02,
        latency_ms=150.0,
        artifact_content="line one\nline three\n",
    )

    response = client.get(
        "/api/v1/executions/compare",
        params={"a": str(entry_a.request_id), "b": str(entry_b.request_id)},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_tokens_delta"] == 50
    assert round(body["estimated_cost_delta_usd"], 4) == 0.01
    assert body["latency_delta_ms"] == 50.0
    assert "-line two" in body["artifact_diff"]
    assert "+line three" in body["artifact_diff"]


def test_compare_executions_unknown_id_returns_404(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    entry = _seed(client)

    response = client.get(
        "/api/v1/executions/compare",
        params={"a": str(entry.request_id), "b": str(uuid4())},
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 404
