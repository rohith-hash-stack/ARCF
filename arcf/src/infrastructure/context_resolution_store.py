"""ContextResolutionStore — persists ContextResolutionResult objects
so Contract.context_resolution_id can be resolved back to the full
object across separate API calls (resolve now, package later).

Durability (2026-08-17, independent verification report G-new-4):
Contract.context_resolution_id is itself durably stored (Contract lives
in SqliteContractStore), and interfaces/api/routes/context_package.py's
POST /contracts/{id}/context-package dereferences it as a matter of its
own documented contract ("Requires /code-intelligence to have run
first"), with no lifecycle caveat anywhere saying that dereference is
only valid within the same process lifetime. The lifecycle contract this
module previously left implicit -- and this docstring's own prior
wording ("if a real deployment needs it to survive a restart, this is
the one place that would change") had already identified as the thing
to fix, without fixing it -- is therefore: YES, a context_resolution_id
handed to a caller (including in ArcfExecutionResult, returned from
POST /contracts/{id}/grounded-execution) must remain dereferenceable for
as long as the Contract that references it does, restart included.
SqliteContextResolutionStore below is that fix, applying the exact same
pattern already used three other times in this codebase
(infrastructure/contract_store.py, execution_ledger_db.py,
comparison_store.py) rather than introducing a new persistence
mechanism. InMemoryContextResolutionStore is kept for tests that don't
need durability and want zero I/O.
"""

import contextlib
import sqlite3
from typing import Protocol
from uuid import UUID

from domain.context_resolution import ContextResolutionResult

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS context_resolutions (
    result_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
)
"""


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


class SqliteContextResolutionStore:
    """Same connect-per-call, cache-nothing shape as SqliteContractStore
    -- safe to run through asyncio.to_thread from concurrent requests,
    no shared connection to guard."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with contextlib.closing(self._connect()) as conn, conn:
            conn.execute(_CREATE_TABLE_SQL)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def save(self, result: ContextResolutionResult) -> None:
        with contextlib.closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO context_resolutions (result_id, payload) VALUES (?, ?)",
                (str(result.id), result.model_dump_json()),
            )

    def get(self, result_id: UUID) -> ContextResolutionResult | None:
        with contextlib.closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload FROM context_resolutions WHERE result_id = ?",
                (str(result_id),),
            ).fetchone()
        return ContextResolutionResult.model_validate_json(row[0]) if row else None
