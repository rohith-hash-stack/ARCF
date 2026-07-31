from datetime import UTC, datetime, timedelta

import pytest

from infrastructure.idempotency import IdempotencyGuard, InMemoryIdempotencyStore, hash_payload
from shared.errors import IdempotencyConflictError


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)


def test_hash_payload_is_order_independent() -> None:
    assert hash_payload({"a": 1, "b": 2}) == hash_payload({"b": 2, "a": 1})


def test_hash_payload_differs_for_different_content() -> None:
    assert hash_payload({"a": 1}) != hash_payload({"a": 2})


def test_fresh_key_returns_none() -> None:
    guard = IdempotencyGuard(InMemoryIdempotencyStore(ttl_seconds=60))
    assert guard.check("key-1", "hash-1") is None


def test_same_key_same_payload_replays() -> None:
    guard = IdempotencyGuard(InMemoryIdempotencyStore(ttl_seconds=60))
    guard.save("key-1", "hash-1", status_code=200, body={"content": "hello"})
    cached = guard.check("key-1", "hash-1")
    assert cached is not None
    assert cached.body == {"content": "hello"}


def test_same_key_different_payload_conflicts() -> None:
    guard = IdempotencyGuard(InMemoryIdempotencyStore(ttl_seconds=60))
    guard.save("key-1", "hash-1", status_code=200, body={"content": "hello"})
    with pytest.raises(IdempotencyConflictError):
        guard.check("key-1", "hash-2")


def test_record_expires_after_ttl() -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = InMemoryIdempotencyStore(ttl_seconds=60, clock=clock)
    guard = IdempotencyGuard(store, clock=clock)
    guard.save("key-1", "hash-1", status_code=200, body={"content": "hello"})
    clock.advance(seconds=61)
    assert guard.check("key-1", "hash-1") is None
