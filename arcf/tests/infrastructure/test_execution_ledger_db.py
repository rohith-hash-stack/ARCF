from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from domain.execution_ledger import ExecutionLedgerEntry
from infrastructure.execution_ledger_db import (
    RETENTION_PER_WORKSPACE,
    ExecutionLedgerStore,
    InMemoryExecutionLedgerStore,
    SqliteExecutionLedgerStore,
)


def _make_entry(
    workspace_id: str = "workspace-1",
    created_at: datetime | None = None,
    **overrides: object,
) -> ExecutionLedgerEntry:
    defaults: dict[str, object] = {
        "workspace_id": workspace_id,
        "contract_id": "contract-1",
        "mode": "arcf",
        "model": "gpt-4o-mini",
        "prompt": "fix the bug",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "latency_ms": 250.0,
        "estimated_cost_usd": 0.01,
        "artifact_content": "diff --git a/foo.py b/foo.py",
    }
    if created_at is not None:
        defaults["created_at"] = created_at
    defaults.update(overrides)
    return ExecutionLedgerEntry(**defaults)  # type: ignore[arg-type]


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> ExecutionLedgerStore:
    if request.param == "memory":
        return InMemoryExecutionLedgerStore()
    return SqliteExecutionLedgerStore(str(tmp_path / "ledger.db"))


def test_get_returns_none_for_unknown_request_id(store: ExecutionLedgerStore) -> None:
    assert store.get(uuid4()) is None


def test_save_and_get_roundtrips(store: ExecutionLedgerStore) -> None:
    entry = _make_entry()
    store.save(entry)
    fetched = store.get(entry.request_id)
    assert fetched is not None
    assert fetched.request_id == entry.request_id
    assert fetched.prompt == entry.prompt
    assert fetched.total_tokens == entry.total_tokens


def test_list_recent_orders_newest_first(store: ExecutionLedgerStore) -> None:
    now = datetime.now(UTC)
    older = _make_entry(created_at=now - timedelta(minutes=5))
    newer = _make_entry(created_at=now)
    store.save(older)
    store.save(newer)

    recent = store.list_recent()
    assert [e.request_id for e in recent] == [newer.request_id, older.request_id]


def test_list_recent_respects_limit(store: ExecutionLedgerStore) -> None:
    for _ in range(5):
        store.save(_make_entry())

    assert len(store.list_recent(limit=3)) == 3


def test_delete_removes_entry_and_returns_true(store: ExecutionLedgerStore) -> None:
    entry = _make_entry()
    store.save(entry)

    assert store.delete(entry.request_id) is True
    assert store.get(entry.request_id) is None


def test_delete_returns_false_for_unknown_request_id(store: ExecutionLedgerStore) -> None:
    assert store.delete(uuid4()) is False


def test_save_overwrites_existing_entry_by_request_id(store: ExecutionLedgerStore) -> None:
    entry = _make_entry()
    store.save(entry)

    updated = entry.with_manual_rating(5)
    store.save(updated)

    fetched = store.get(entry.request_id)
    assert fetched is not None
    assert fetched.manual_rating == 5


def test_retention_keeps_only_most_recent_per_workspace(store: ExecutionLedgerStore) -> None:
    now = datetime.now(UTC)
    entries = [
        _make_entry(workspace_id="workspace-1", created_at=now - timedelta(minutes=i))
        for i in range(RETENTION_PER_WORKSPACE + 5)
    ]
    for entry in entries:
        store.save(entry)

    remaining = store.list_recent(limit=1000)
    assert len(remaining) == RETENTION_PER_WORKSPACE
    # The 5 oldest (highest i, furthest in the past) should have been pruned.
    surviving_ids = {e.request_id for e in remaining}
    assert all(e.request_id in surviving_ids for e in entries[:RETENTION_PER_WORKSPACE])
    assert not any(e.request_id in surviving_ids for e in entries[RETENTION_PER_WORKSPACE:])


def test_retention_does_not_cross_workspaces(store: ExecutionLedgerStore) -> None:
    now = datetime.now(UTC)
    workspace_a_entries = [
        _make_entry(workspace_id="workspace-a", created_at=now - timedelta(minutes=i))
        for i in range(RETENTION_PER_WORKSPACE)
    ]
    workspace_b_entry = _make_entry(workspace_id="workspace-b", created_at=now)
    for entry in [*workspace_a_entries, workspace_b_entry]:
        store.save(entry)

    remaining_ids = {e.request_id for e in store.list_recent(limit=1000)}
    assert workspace_b_entry.request_id in remaining_ids
    assert len(remaining_ids) == RETENTION_PER_WORKSPACE + 1


def test_sqlite_store_persists_across_instances(tmp_path: Path) -> None:
    db_path = str(tmp_path / "persist.db")
    entry = _make_entry()

    SqliteExecutionLedgerStore(db_path).save(entry)
    reopened = SqliteExecutionLedgerStore(db_path)
    fetched = reopened.get(entry.request_id)

    assert fetched is not None
    assert fetched.request_id == entry.request_id
