"""SuiteResultStore — persists every SuiteModeRunRecord (one task run
through one mode) as structured JSON. Same sqlite-blob pattern as
BenchmarkStore (benchmark/storage.py): a fresh connection per call,
JSON blob storage, no ORM.

Keyed by (suite_name, task_id, mode) with INSERT OR REPLACE: re-running
a task+mode overwrites its previous attempt, so the store always
reflects the suite's current state rather than accumulating stale
reruns — "repeatable" means the latest run is the one that counts.
"""

import contextlib
import sqlite3

from shared.clock import utc_now

from benchmark.domain.models import BenchmarkMode
from benchmark.suite.models import SuiteModeRunRecord

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS suite_mode_runs (
    suite_name TEXT NOT NULL,
    task_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (suite_name, task_id, mode)
)
"""


class SuiteResultStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with contextlib.closing(self._connect()) as conn, conn:
            conn.execute(_CREATE_TABLE_SQL)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def save(self, suite_name: str, record: SuiteModeRunRecord) -> None:
        with contextlib.closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO suite_mode_runs "
                "(suite_name, task_id, mode, generated_at, payload) VALUES (?, ?, ?, ?, ?)",
                (
                    suite_name,
                    record.task_id,
                    record.mode.value,
                    utc_now().isoformat(),
                    record.model_dump_json(),
                ),
            )

    def list_for_suite(self, suite_name: str) -> list[SuiteModeRunRecord]:
        with contextlib.closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT payload FROM suite_mode_runs WHERE suite_name = ?", (suite_name,)
            ).fetchall()
        return [SuiteModeRunRecord.model_validate_json(row[0]) for row in rows]

    def records_by_task(
        self, suite_name: str
    ) -> dict[str, dict[BenchmarkMode, SuiteModeRunRecord]]:
        grouped: dict[str, dict[BenchmarkMode, SuiteModeRunRecord]] = {}
        for record in self.list_for_suite(suite_name):
            grouped.setdefault(record.task_id, {})[record.mode] = record
        return grouped
