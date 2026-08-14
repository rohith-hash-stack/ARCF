from pathlib import Path

import pytest

from domain.audit import AuditStamp, BehavioralRecordStore, PersistedBehavioralRecord
from domain.behavioral_record import BehavioralRecord, DependencyDepth, RecordComplexity
from domain.code_intelligence import SourceLocation, SymbolKind
from infrastructure.behavioral_record_store import (
    InMemoryBehavioralRecordStore,
    SqliteBehavioralRecordStore,
)


def _record(symbol_id: str = "a.py::foo") -> BehavioralRecord:
    return BehavioralRecord(
        symbol_id=symbol_id,
        qualified_name="foo",
        kind=SymbolKind.FUNCTION,
        language="python",
        location=SourceLocation(file_path="a.py", start_line=1, end_line=5),
        direct_callees=["b.py::bar"],
        dependency_depth=DependencyDepth(hops=0, truncated=False),
        disambiguation_aware=True,
        complexity=RecordComplexity(line_count=5, direct_call_count=1),
    )


def _persisted(
    symbol_id: str = "a.py::foo", commit_sha: str = "deadbeef"
) -> PersistedBehavioralRecord:
    return PersistedBehavioralRecord(
        stamp=AuditStamp(commit_sha=commit_sha, resolver_version="v1", schema_version="v1"),
        record=_record(symbol_id),
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> BehavioralRecordStore:
    if request.param == "memory":
        return InMemoryBehavioralRecordStore()
    return SqliteBehavioralRecordStore(str(tmp_path / "behavioral_records.db"))


def test_get_returns_none_for_unknown_record(store: BehavioralRecordStore) -> None:
    assert store.get("deadbeef", "a.py::foo") is None


def test_save_and_get_roundtrips(store: BehavioralRecordStore) -> None:
    persisted = _persisted()
    store.save(persisted)
    loaded = store.get("deadbeef", "a.py::foo")
    assert loaded == persisted


def test_save_overwrites_same_key(store: BehavioralRecordStore) -> None:
    store.save(_persisted())
    updated = PersistedBehavioralRecord(
        stamp=AuditStamp(commit_sha="deadbeef", resolver_version="v2", schema_version="v1"),
        record=_record(),
    )
    store.save(updated)
    loaded = store.get("deadbeef", "a.py::foo")
    assert loaded is not None
    assert loaded.stamp.resolver_version == "v2"


def test_get_all_for_commit_filters_and_sorts_by_symbol_id(store: BehavioralRecordStore) -> None:
    store.save(_persisted(symbol_id="a.py::zeta", commit_sha="c1"))
    store.save(_persisted(symbol_id="a.py::alpha", commit_sha="c1"))
    store.save(_persisted(symbol_id="a.py::other", commit_sha="c2"))

    results = store.get_all_for_commit("c1")
    assert [p.record.symbol_id for p in results] == ["a.py::alpha", "a.py::zeta"]


def test_save_is_byte_identical_across_independent_saves(store: BehavioralRecordStore) -> None:
    """The project's core reproducibility acceptance test, applied to
    persistence: identical evidence in, byte-identical stored form out,
    regardless of which store implementation."""
    a = _persisted()
    b = _persisted()
    store.save(a)
    first = store.get("deadbeef", "a.py::foo")
    store.save(b)
    second = store.get("deadbeef", "a.py::foo")
    assert first is not None and second is not None
    assert first.model_dump_json() == second.model_dump_json()
