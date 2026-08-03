import pytest

from infrastructure.rate_limit import RateLimiter, TokenBucket
from shared.errors import RateLimitExceededError


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_token_bucket_allows_up_to_capacity() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=3, refill_per_second=1.0, clock=clock)
    for _ in range(3):
        allowed, _ = bucket.try_consume()
        assert allowed
    allowed, retry_after = bucket.try_consume()
    assert not allowed
    assert retry_after > 0


def test_token_bucket_refills_over_time() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=1, refill_per_second=1.0, clock=clock)
    assert bucket.try_consume()[0] is True
    assert bucket.try_consume()[0] is False
    clock.advance(1.0)
    assert bucket.try_consume()[0] is True


def test_token_bucket_never_exceeds_capacity() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=2, refill_per_second=10.0, clock=clock)
    clock.advance(100.0)
    assert bucket.try_consume()[0] is True
    assert bucket.try_consume()[0] is True
    assert bucket.try_consume()[0] is False


def test_rate_limiter_tracks_buckets_per_principal() -> None:
    clock = FakeClock()
    limiter = RateLimiter(capacity=1, refill_per_second=1.0, clock=clock)
    limiter.enforce("alice")
    with pytest.raises(RateLimitExceededError):
        limiter.enforce("alice")
    limiter.enforce("bob")  # separate bucket, unaffected by alice's limit
