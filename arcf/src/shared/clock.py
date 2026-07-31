"""Single source of truth for timestamps across ARCF.

Every model that records a timestamp goes through utc_now() so that
tests can monkeypatch one function instead of stubbing datetime.now()
in every module.
"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)
