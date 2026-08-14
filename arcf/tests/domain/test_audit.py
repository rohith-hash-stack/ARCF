import pytest
from pydantic import ValidationError

from domain.audit import AuditStamp


def test_audit_stamp_holds_its_three_fields() -> None:
    stamp = AuditStamp(commit_sha="abc123", resolver_version="v1", schema_version="v1")
    assert stamp.commit_sha == "abc123"
    assert stamp.resolver_version == "v1"
    assert stamp.schema_version == "v1"


def test_audit_stamp_is_frozen() -> None:
    stamp = AuditStamp(commit_sha="abc123", resolver_version="v1", schema_version="v1")
    with pytest.raises(ValidationError):
        stamp.commit_sha = "def456"  # type: ignore[misc]
