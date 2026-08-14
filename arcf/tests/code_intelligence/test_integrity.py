from code_intelligence.behavioral_record import BehavioralRecordBuilder
from code_intelligence.call_graph import CallGraph
from code_intelligence.integrity import verify_integrity
from code_intelligence.reference_resolver import ReferenceResolver
from code_intelligence.symbol_index import SymbolIndex
from domain.audit import AuditStamp, PersistedBehavioralRecord
from domain.code_intelligence import CallReference, SourceLocation, Symbol, SymbolKind
from infrastructure.behavioral_record_store import InMemoryBehavioralRecordStore


def _function(name: str, file_path: str) -> Symbol:
    return Symbol(
        id=f"{file_path}::{name}",
        name=name,
        qualified_name=name,
        kind=SymbolKind.FUNCTION,
        file_path=file_path,
        location=SourceLocation(file_path=file_path, start_line=1, end_line=5),
    )


def _setup() -> tuple[BehavioralRecordBuilder, InMemoryBehavioralRecordStore, Symbol]:
    login = _function("login", "service.py")
    authenticate = _function("authenticate", "auth.py")
    symbol_index = SymbolIndex([login, authenticate])
    resolver = ReferenceResolver(symbol_index)
    calls = [
        CallReference(
            caller_id=login.id,
            callee_name="authenticate",
            file_path="service.py",
            location=SourceLocation(file_path="service.py", start_line=3, end_line=3),
        )
    ]
    graph = CallGraph(calls, resolver)
    builder = BehavioralRecordBuilder(symbol_index, graph, {})
    store = InMemoryBehavioralRecordStore()
    return builder, store, login


def test_clean_report_when_stored_matches_live() -> None:
    builder, store, login = _setup()
    record = builder.build(login.id)
    assert record is not None
    store.save(
        PersistedBehavioralRecord(
            stamp=AuditStamp(commit_sha="c1", resolver_version="v1", schema_version="v1"),
            record=record,
        )
    )

    report = verify_integrity(store, builder, "c1", [login.id])
    assert report.clean is True
    assert report.checked == 1
    assert report.mismatches == []


def test_reports_missing_record() -> None:
    builder, store, login = _setup()
    report = verify_integrity(store, builder, "c1", [login.id])
    assert report.clean is False
    [mismatch] = report.mismatches
    assert mismatch.reason == "not found in store"


def test_reports_content_drift() -> None:
    builder, store, login = _setup()
    record = builder.build(login.id)
    assert record is not None
    stale = record.model_copy(update={"direct_callees": ["nonexistent.py::ghost"]})
    store.save(
        PersistedBehavioralRecord(
            stamp=AuditStamp(commit_sha="c1", resolver_version="v1", schema_version="v1"),
            record=stale,
        )
    )

    report = verify_integrity(store, builder, "c1", [login.id])
    assert report.clean is False
    [mismatch] = report.mismatches
    assert mismatch.reason == "content drift"


def test_reports_no_longer_resolvable() -> None:
    builder, store, login = _setup()
    record = builder.build(login.id)
    assert record is not None
    store.save(
        PersistedBehavioralRecord(
            stamp=AuditStamp(commit_sha="c1", resolver_version="v1", schema_version="v1"),
            record=record,
        )
    )

    report = verify_integrity(store, builder, "c1", [login.id, "made.up::symbol"])
    assert report.checked == 2
    [mismatch] = report.mismatches
    assert mismatch.symbol_id == "made.up::symbol"
    assert mismatch.reason == "not found in store"


def test_checks_in_given_order_not_a_derived_order() -> None:
    builder, store, login = _setup()
    report = verify_integrity(store, builder, "c1", ["z", "a", "m"])
    assert [m.symbol_id for m in report.mismatches] == ["z", "a", "m"]
