from pathlib import Path
from uuid import uuid4

import pytest

from domain.comparison_result import ComparisonResult
from domain.execution_ledger import ExecutionLedgerEntry
from infrastructure.comparison_store import (
    ComparisonStore,
    InMemoryComparisonStore,
    SqliteComparisonStore,
)


def _entry(mode: str) -> ExecutionLedgerEntry:
    return ExecutionLedgerEntry(
        workspace_id="workspace-1",
        contract_id="contract-1",
        mode=mode,  # type: ignore[arg-type]
        model="gpt-4o-mini",
        prompt="fix the bug",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        latency_ms=250.0,
        estimated_cost_usd=0.01,
        artifact_content="some output",
    )


def _result() -> ComparisonResult:
    return ComparisonResult(
        task="fix the bug",
        repository="my/repo",
        direct=_entry("direct"),
        arcf=_entry("arcf"),
        token_reduction_pct=40.0,
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> ComparisonStore:
    if request.param == "memory":
        return InMemoryComparisonStore()
    return SqliteComparisonStore(str(tmp_path / "comparisons.db"))


def test_get_returns_none_for_unknown_id(store: ComparisonStore) -> None:
    assert store.get(uuid4()) is None


def test_save_and_get_roundtrips(store: ComparisonStore) -> None:
    result = _result()
    store.save(result)

    fetched = store.get(result.id)
    assert fetched is not None
    assert fetched.id == result.id
    assert fetched.task == result.task
    assert fetched.token_reduction_pct == 40.0
    assert fetched.direct.mode == "direct"
    assert fetched.arcf.mode == "arcf"


def test_sqlite_store_persists_across_instances(tmp_path: Path) -> None:
    db_path = str(tmp_path / "persist.db")
    result = _result()

    SqliteComparisonStore(db_path).save(result)
    reopened = SqliteComparisonStore(db_path)
    fetched = reopened.get(result.id)

    assert fetched is not None
    assert fetched.id == result.id
