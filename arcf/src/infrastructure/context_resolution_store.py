"""ContextResolutionStore — persists ContextResolutionResult objects
so Contract.context_resolution_id can be resolved back to the full
object across separate API calls (resolve now, package later).

In-memory only, mirroring IdempotencyStore's minimalism (Phase 2) —
unlike LivingContract, a ContextResolutionResult is a snapshot tied to
one point-in-time analysis, not something that needs durable
versioned history. If a real deployment needs it to survive a
restart, this is the one place that would change.
"""

from typing import Protocol
from uuid import UUID

from domain.context_resolution import ContextResolutionResult


class ContextResolutionStore(Protocol):
    def save(self, result: ContextResolutionResult) -> None: ...
    def get(self, result_id: UUID) -> ContextResolutionResult | None: ...


class InMemoryContextResolutionStore:
    def __init__(self) -> None:
        self._results: dict[UUID, ContextResolutionResult] = {}

    def save(self, result: ContextResolutionResult) -> None:
        self._results[result.id] = result

    def get(self, result_id: UUID) -> ContextResolutionResult | None:
        return self._results.get(result_id)
