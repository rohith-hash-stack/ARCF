"""Idempotency-Key support for /api/v1/execute.

A client retrying a request after a dropped connection must get back the
exact same result, not a second LLM call. Reusing the same key with a
different payload is a client bug, not a cache hit — it is rejected
rather than silently replaying the wrong response.
"""

import hashlib
import json
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from shared.clock import utc_now
from shared.errors import IdempotencyConflictError


def hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IdempotencyRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_hash: str
    status_code: int
    body: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now)


class IdempotencyStore(Protocol):
    def get(self, key: str) -> IdempotencyRecord | None: ...
    def put(self, key: str, record: IdempotencyRecord) -> None: ...


class InMemoryIdempotencyStore:
    def __init__(self, ttl_seconds: int, clock: Callable[[], datetime] = utc_now) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock
        self._records: dict[str, IdempotencyRecord] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> IdempotencyRecord | None:
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return None
            if self._clock() - record.created_at > self._ttl:
                del self._records[key]
                return None
            return record

    def put(self, key: str, record: IdempotencyRecord) -> None:
        with self._lock:
            self._records[key] = record


class IdempotencyGuard:
    def __init__(self, store: IdempotencyStore, clock: Callable[[], datetime] = utc_now) -> None:
        self._store = store
        self._clock = clock

    def check(self, key: str, request_hash: str) -> IdempotencyRecord | None:
        """None means proceed as a fresh request; otherwise replay the record."""
        existing = self._store.get(key)
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError(
                f"Idempotency-Key {key!r} was already used with a different request body"
            )
        return existing

    def save(self, key: str, request_hash: str, status_code: int, body: dict[str, Any]) -> None:
        self._store.put(
            key,
            IdempotencyRecord(
                request_hash=request_hash,
                status_code=status_code,
                body=body,
                created_at=self._clock(),
            ),
        )
