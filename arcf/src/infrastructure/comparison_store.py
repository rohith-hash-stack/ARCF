"""Comparison persistence (Phase 11 deliverable). Stage 5 of the v2.3
migration plan (see arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md
Sec. 2.4/5.1/7) — what makes GET /api/v1/compare/{comparison_id}
possible, since a ComparisonResult must be readable again after
POST /api/v1/compare produced it.

Same "fresh connection per call, JSON blob payload, no ORM" convention
as infrastructure/contract_store.py and infrastructure/
execution_ledger_db.py.
"""

import contextlib
import sqlite3
from typing import Protocol
from uuid import UUID

from domain.comparison_result import ComparisonResult

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS comparison_results (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
)
"""


class ComparisonStore(Protocol):
    def save(self, result: ComparisonResult) -> None: ...
    def get(self, comparison_id: UUID) -> ComparisonResult | None: ...


class InMemoryComparisonStore:
    def __init__(self) -> None:
        self._results: dict[UUID, ComparisonResult] = {}

    def save(self, result: ComparisonResult) -> None:
        self._results[result.id] = result

    def get(self, comparison_id: UUID) -> ComparisonResult | None:
        return self._results.get(comparison_id)


class SqliteComparisonStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with contextlib.closing(self._connect()) as conn, conn:
            conn.execute(_CREATE_TABLE_SQL)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def save(self, result: ComparisonResult) -> None:
        with contextlib.closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO comparison_results (id, payload) VALUES (?, ?)",
                (str(result.id), result.model_dump_json()),
            )

    def get(self, comparison_id: UUID) -> ComparisonResult | None:
        with contextlib.closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload FROM comparison_results WHERE id = ?",
                (str(comparison_id),),
            ).fetchone()
        return ComparisonResult.model_validate_json(row[0]) if row else None
