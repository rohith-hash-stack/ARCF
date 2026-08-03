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
        "comparison_store_path": str(tmp_path / "comparisons.db"),
    }
    defaults.update(settings_overrides)
    settings = Settings(**defaults)  # type: ignore[arg-type]
    return TestClient(create_app(settings))


def _seed_entry(client: TestClient, mode: str, **overrides: object) -> ExecutionLedgerEntry:
    defaults: dict[str, object] = {
        "workspace_id": "workspace-1",
        "contract_id": "contract-1",
        "mode": mode,
        "model": "gpt-4o-mini",
        "prompt": "fix the bug",
        "prompt_tokens": 1000 if mode == "direct" else 300,
        "completion_tokens": 50,
        "total_tokens": 1000 if mode == "direct" else 300,
        "latency_ms": 2000.0 if mode == "direct" else 800.0,
        "estimated_cost_usd": 0.10 if mode == "direct" else 0.03,
        "artifact_content": "some output",
        "selected_files": [] if mode == "direct" else ["auth/service.py"],
    }
    defaults.update(overrides)
    entry = ExecutionLedgerEntry(**defaults)  # type: ignore[arg-type]
    app = cast(FastAPI, client.app)
    store = cast(ExecutionLedgerStore, app.state.execution_ledger_store)
    store.save(entry)
    return entry


def test_create_comparison_missing_credentials_rejected(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    response = client.post(
        "/api/v1/compare",
        json={
            "task": "task",
            "repository": "repo",
            "direct_request_id": str(uuid4()),
            "arcf_request_id": str(uuid4()),
        },
    )
    assert response.status_code == 401


def test_create_comparison_unknown_direct_entry_returns_404(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    arcf_entry = _seed_entry(client, "arcf")

    response = client.post(
        "/api/v1/compare",
        json={
            "task": "task",
            "repository": "repo",
            "direct_request_id": str(uuid4()),
            "arcf_request_id": str(arcf_entry.request_id),
        },
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 404


def test_create_comparison_mode_mismatch_returns_400(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    entry_a = _seed_entry(client, "arcf")
    entry_b = _seed_entry(client, "arcf")

    response = client.post(
        "/api/v1/compare",
        json={
            "task": "task",
            "repository": "repo",
            "direct_request_id": str(entry_a.request_id),
            "arcf_request_id": str(entry_b.request_id),
        },
        headers={"X-API-Key": "testkey"},
    )
    assert response.status_code == 400


def test_create_and_get_comparison_full_flow(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    direct_entry = _seed_entry(client, "direct")
    arcf_entry = _seed_entry(client, "arcf")

    create_response = client.post(
        "/api/v1/compare",
        json={
            "task": "fix the bug",
            "repository": "my/repo",
            "direct_request_id": str(direct_entry.request_id),
            "arcf_request_id": str(arcf_entry.request_id),
        },
        headers={"X-API-Key": "testkey"},
    )
    assert create_response.status_code == 200
    body = create_response.json()
    assert body["task"] == "fix the bug"
    assert body["token_reduction_pct"] == 70.0
    assert body["context_efficiency_ratio"] is None  # direct has no selected_files
    comparison_id = body["id"]

    get_response = client.get(
        f"/api/v1/compare/{comparison_id}", headers={"X-API-Key": "testkey"}
    )
    assert get_response.status_code == 200
    assert get_response.json()["id"] == comparison_id


def test_get_comparison_unknown_id_returns_404(tmp_path: Path) -> None:
    client = _build_client(tmp_path)
    response = client.get(f"/api/v1/compare/{uuid4()}", headers={"X-API-Key": "testkey"})
    assert response.status_code == 404
