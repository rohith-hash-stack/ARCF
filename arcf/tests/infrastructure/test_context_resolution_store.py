from pathlib import Path
from uuid import uuid4

import pytest

from domain.context_resolution import ContextResolutionResult, TokenEstimate
from infrastructure.context_resolution_store import (
    ContextResolutionStore,
    InMemoryContextResolutionStore,
    SqliteContextResolutionStore,
)


def _make_result() -> ContextResolutionResult:
    return ContextResolutionResult(
        workspace_id="workspace-1",
        contract_id="contract-1",
        repository_root="/repo",
        language="python",
        confidence=0.9,
        token_estimate=TokenEstimate(
            raw_context_tokens=50, selected_context_tokens=50, compression_ratio=1.0
        ),
        resolution_reason="defines authenticate",
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> ContextResolutionStore:
    if request.param == "memory":
        return InMemoryContextResolutionStore()
    return SqliteContextResolutionStore(str(tmp_path / "context_resolutions.db"))


def test_get_returns_none_for_unknown_result(store: ContextResolutionStore) -> None:
    assert store.get(uuid4()) is None


def test_save_and_get_roundtrips(store: ContextResolutionStore) -> None:
    result = _make_result()
    store.save(result)
    fetched = store.get(result.id)

    assert fetched is not None
    assert fetched.id == result.id
    assert fetched.workspace_id == result.workspace_id
    assert fetched.resolution_reason == result.resolution_reason


def test_sqlite_store_persists_across_instances(tmp_path: Path) -> None:
    """G-new-4 (2026-08-17 independent verification report): the whole
    point of this store existing as a distinct SqliteContextResolutionStore
    -- Contract.context_resolution_id is durable (SqliteContractStore),
    so a resolution it references must remain dereferenceable after a
    real process restart, not just within one InMemoryContextResolutionStore's
    lifetime. Simulates a restart the same way test_contract_store.py's
    own equivalent test does: a second, independent store instance
    pointed at the same db file, never sharing the first instance's
    in-process state."""
    db_path = str(tmp_path / "persist.db")
    result = _make_result()

    SqliteContextResolutionStore(db_path).save(result)
    reopened = SqliteContextResolutionStore(db_path)
    fetched = reopened.get(result.id)

    assert fetched is not None
    assert fetched.id == result.id
    assert fetched.repository_root == result.repository_root
