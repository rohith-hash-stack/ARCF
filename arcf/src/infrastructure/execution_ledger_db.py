"""Execution Ledger persistence (Phase 9 deliverable). Stage 4 of the
v2.3 migration plan (see arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md
Sec. 2.6/7/10).

Same "fresh connection per call, JSON blob payload, no ORM" convention
as infrastructure/contract_store.py — SqliteExecutionLedgerStore opens
a new sqlite3.Connection per call rather than holding one open, so
it's safe to run through asyncio.to_thread from concurrent requests.

Retention: the v2.3 brief says "last 50" without specifying scope; per
Sec. 10 Open Question #2, this keeps the most recent 50 entries PER
workspace_id rather than 50 globally — a single active repository
would otherwise evict every other workspace's history within minutes.
"""

import contextlib
import sqlite3
from typing import Protocol
from uuid import UUID

from domain.execution_ledger import ExecutionLedgerEntry

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS execution_ledger (
    request_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
)
"""
RETENTION_PER_WORKSPACE = 50


class ExecutionLedgerStore(Protocol):
    def save(self, entry: ExecutionLedgerEntry) -> None: ...
    def get(self, request_id: UUID) -> ExecutionLedgerEntry | None: ...
    def list_recent(self, limit: int = 50) -> list[ExecutionLedgerEntry]: ...
    def delete(self, request_id: UUID) -> bool: ...


class InMemoryExecutionLedgerStore:
    def __init__(self) -> None:
        self._entries: dict[UUID, ExecutionLedgerEntry] = {}

    def save(self, entry: ExecutionLedgerEntry) -> None:
        self._entries[entry.request_id] = entry
        self._prune(entry.workspace_id)

    def get(self, request_id: UUID) -> ExecutionLedgerEntry | None:
        return self._entries.get(request_id)

    def list_recent(self, limit: int = 50) -> list[ExecutionLedgerEntry]:
        ordered = sorted(self._entries.values(), key=lambda e: e.created_at, reverse=True)
        return ordered[:limit]

    def delete(self, request_id: UUID) -> bool:
        return self._entries.pop(request_id, None) is not None

    def _prune(self, workspace_id: str) -> None:
        same_workspace = sorted(
            (e for e in self._entries.values() if e.workspace_id == workspace_id),
            key=lambda e: e.created_at,
            reverse=True,
        )
        for stale in same_workspace[RETENTION_PER_WORKSPACE:]:
            del self._entries[stale.request_id]


class SqliteExecutionLedgerStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with contextlib.closing(self._connect()) as conn, conn:
            conn.execute(_CREATE_TABLE_SQL)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def save(self, entry: ExecutionLedgerEntry) -> None:
        with contextlib.closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO execution_ledger "
                "(request_id, workspace_id, created_at, payload) VALUES (?, ?, ?, ?)",
                (
                    str(entry.request_id),
                    entry.workspace_id,
                    entry.created_at.isoformat(),
                    entry.model_dump_json(),
                ),
            )
            self._prune(conn, entry.workspace_id)

    def get(self, request_id: UUID) -> ExecutionLedgerEntry | None:
        with contextlib.closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload FROM execution_ledger WHERE request_id = ?",
                (str(request_id),),
            ).fetchone()
        return ExecutionLedgerEntry.model_validate_json(row[0]) if row else None

    def list_recent(self, limit: int = 50) -> list[ExecutionLedgerEntry]:
        with contextlib.closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT payload FROM execution_ledger ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [ExecutionLedgerEntry.model_validate_json(row[0]) for row in rows]

    def delete(self, request_id: UUID) -> bool:
        with contextlib.closing(self._connect()) as conn, conn:
            cursor = conn.execute(
                "DELETE FROM execution_ledger WHERE request_id = ?", (str(request_id),)
            )
        return cursor.rowcount > 0

    def _prune(self, conn: sqlite3.Connection, workspace_id: str) -> None:
        conn.execute(
            """
            DELETE FROM execution_ledger
            WHERE workspace_id = ? AND request_id NOT IN (
                SELECT request_id FROM execution_ledger
                WHERE workspace_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            )
            """,
            (workspace_id, workspace_id, RETENTION_PER_WORKSPACE),
        )
