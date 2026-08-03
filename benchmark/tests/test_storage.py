from pathlib import Path
from uuid import uuid4

from benchmark.domain.models import ComparisonResult
from benchmark.storage import BenchmarkStore


def _result(task: str = "fix bug") -> ComparisonResult:
    return ComparisonResult(task=task, repository="/repo", model="gpt-4o-mini")


def test_save_and_get_roundtrips(tmp_path: Path) -> None:
    store = BenchmarkStore(str(tmp_path / "runs.db"))
    result = _result()
    store.save(result)

    fetched = store.get(result.id)
    assert fetched is not None
    assert fetched.id == result.id
    assert fetched.task == result.task


def test_get_returns_none_for_unknown_id(tmp_path: Path) -> None:
    store = BenchmarkStore(str(tmp_path / "runs.db"))
    assert store.get(uuid4()) is None


def test_list_all_returns_saved_runs_newest_first(tmp_path: Path) -> None:
    store = BenchmarkStore(str(tmp_path / "runs.db"))
    first = _result("first task")
    store.save(first)
    second = _result("second task")
    store.save(second)

    results = store.list_all()
    assert {r.id for r in results} == {first.id, second.id}


def test_persists_across_store_instances(tmp_path: Path) -> None:
    db_path = str(tmp_path / "runs.db")
    result = _result()
    BenchmarkStore(db_path).save(result)

    reopened = BenchmarkStore(db_path)
    fetched = reopened.get(result.id)
    assert fetched is not None
    assert fetched.id == result.id
