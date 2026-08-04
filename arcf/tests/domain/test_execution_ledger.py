import pytest
from pydantic import ValidationError

from domain.execution_ledger import ExecutionLedgerEntry


def _entry(**overrides: object) -> ExecutionLedgerEntry:
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
        "artifact_content": "some output",
    }
    defaults.update(overrides)
    return ExecutionLedgerEntry(**defaults)  # type: ignore[arg-type]


def test_defaults_for_validation_fields() -> None:
    entry = _entry()
    assert entry.execution_status == "success"
    assert entry.files_changed == []
    assert entry.lines_changed == 0
    assert entry.build_result is None
    assert entry.test_result is None
    assert entry.manual_rating is None
    assert entry.provider is None
    assert entry.metadata == {}


def test_accepts_provider_and_metadata() -> None:
    entry = _entry(provider="openai", metadata={"error": "boom", "error_type": "ValueError"})
    assert entry.provider == "openai"
    assert entry.metadata == {"error": "boom", "error_type": "ValueError"}


def test_rejects_invalid_execution_status_values_no_longer_supported() -> None:
    for stale_value in ("failed", "error"):
        with pytest.raises(ValidationError):
            _entry(execution_status=stale_value)


def test_accepts_all_new_execution_status_values() -> None:
    for value in ("success", "timeout", "provider_error", "validation_error", "execution_error"):
        assert _entry(execution_status=value).execution_status == value


def test_with_manual_rating_returns_new_instance() -> None:
    original = _entry()
    updated = original.with_manual_rating(4)
    assert original.manual_rating is None
    assert updated.manual_rating == 4
    assert updated.request_id == original.request_id


def test_with_build_result_returns_new_instance() -> None:
    original = _entry()
    updated = original.with_build_result("passed")
    assert original.build_result is None
    assert updated.build_result == "passed"


def test_with_test_result_returns_new_instance() -> None:
    original = _entry()
    updated = original.with_test_result("failed")
    assert original.test_result is None
    assert updated.test_result == "failed"


def test_rejects_invalid_execution_status() -> None:
    with pytest.raises(ValidationError):
        _entry(execution_status="not-a-status")


def test_rejects_invalid_build_result() -> None:
    with pytest.raises(ValidationError):
        _entry(build_result="maybe")


def test_entry_is_frozen() -> None:
    entry = _entry()
    with pytest.raises(ValidationError):
        entry.execution_status = "timeout"
