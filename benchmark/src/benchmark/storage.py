"""BenchmarkStore — persists every ComparisonResult (historical
comparison, per the spec). Mirrors ARCF's own SqliteContractStore
pattern exactly: a fresh connection per call, JSON blob storage, no
ORM — consistent with how the rest of this codebase (both projects)
does SQLite persistence.
"""

import contextlib
import sqlite3
from uuid import UUID

from benchmark.domain.models import ComparisonResult

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS benchmark_runs (
    id TEXT PRIMARY KEY,
    task TEXT NOT NULL,
    repository TEXT NOT NULL,
    model TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    payload TEXT NOT NULL
)
"""


class BenchmarkStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with contextlib.closing(self._connect()) as conn, conn:
            conn.execute(_CREATE_TABLE_SQL)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def save(self, result: ComparisonResult) -> None:
        with contextlib.closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO benchmark_runs "
                "(id, task, repository, model, generated_at, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(result.id),
                    result.task,
                    result.repository,
                    result.model,
                    result.generated_at.isoformat(),
                    result.model_dump_json(),
                ),
            )

    def get(self, result_id: UUID) -> ComparisonResult | None:
        with contextlib.closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload FROM benchmark_runs WHERE id = ?", (str(result_id),)
            ).fetchone()
        return ComparisonResult.model_validate_json(row[0]) if row else None

    def list_all(self) -> list[ComparisonResult]:
        with contextlib.closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT payload FROM benchmark_runs ORDER BY generated_at DESC"
            ).fetchall()
        return [ComparisonResult.model_validate_json(row[0]) for row in rows]
