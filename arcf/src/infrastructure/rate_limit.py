"""Per-principal token-bucket rate limiting.

One bucket per principal id, refilled continuously rather than on a
fixed window, so a burst right at a window boundary can't double a
principal's effective quota.
"""

import threading
import time
from collections.abc import Callable

from shared.errors import RateLimitExceededError


class TokenBucket:
    def __init__(
        self,
        capacity: float,
        refill_per_second: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._tokens = capacity
        self._clock = clock
        self._last_refill = clock()

    def try_consume(self, tokens: float = 1.0) -> tuple[bool, float]:
        now = self._clock()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_second)

        if self._tokens >= tokens:
            self._tokens -= tokens
            return True, 0.0

        deficit = tokens - self._tokens
        if self.refill_per_second > 0:
            retry_after = deficit / self.refill_per_second
        else:
            retry_after = float("inf")
        return False, retry_after


class RateLimiter:
    def __init__(
        self,
        capacity: int,
        refill_per_second: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._capacity = capacity
        self._refill_per_second = refill_per_second
        self._clock = clock
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def enforce(self, principal_id: str, tokens: float = 1.0) -> None:
        with self._lock:
            bucket = self._buckets.setdefault(
                principal_id,
                TokenBucket(self._capacity, self._refill_per_second, clock=self._clock),
            )
            allowed, retry_after = bucket.try_consume(tokens)

        if not allowed:
            raise RateLimitExceededError(retry_after)
