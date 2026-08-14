import pytest
from pydantic import ValidationError

from domain.audit import AuditStamp, PersistedBehavioralRecord
from domain.behavioral_record import BehavioralRecord, DependencyDepth, RecordComplexity
from domain.code_intelligence import SourceLocation, SymbolKind


def test_audit_stamp_holds_its_three_fields() -> None:
    stamp = AuditStamp(commit_sha="abc123", resolver_version="v1", schema_version="v1")
    assert stamp.commit_sha == "abc123"
    assert stamp.resolver_version == "v1"
    assert stamp.schema_version == "v1"


def test_audit_stamp_is_frozen() -> None:
    stamp = AuditStamp(commit_sha="abc123", resolver_version="v1", schema_version="v1")
    with pytest.raises(ValidationError):
        stamp.commit_sha = "def456"  # type: ignore[misc]


def _record() -> BehavioralRecord:
    return BehavioralRecord(
        symbol_id="a.py::foo",
        qualified_name="foo",
        kind=SymbolKind.FUNCTION,
        language="python",
        location=SourceLocation(file_path="a.py", start_line=1, end_line=5),
        dependency_depth=DependencyDepth(hops=0, truncated=False),
        disambiguation_aware=True,
        complexity=RecordComplexity(line_count=5, direct_call_count=0),
    )


def test_persisted_behavioral_record_holds_stamp_and_record() -> None:
    stamp = AuditStamp(commit_sha="abc123", resolver_version="v1", schema_version="v1")
    persisted = PersistedBehavioralRecord(stamp=stamp, record=_record())
    assert persisted.stamp == stamp
    assert persisted.record.symbol_id == "a.py::foo"


def test_persisted_behavioral_record_is_frozen() -> None:
    stamp = AuditStamp(commit_sha="abc123", resolver_version="v1", schema_version="v1")
    persisted = PersistedBehavioralRecord(stamp=stamp, record=_record())
    with pytest.raises(ValidationError):
        persisted.record = _record()  # type: ignore[misc]
