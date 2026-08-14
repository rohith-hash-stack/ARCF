"""BehavioralRecordStore implementations (ARCF-DI Phase 8) — persists
PersistedBehavioralRecords keyed by (commit_sha, symbol_id). Mirrors
infrastructure/contract_store.py's own Protocol + InMemory + Sqlite
pattern exactly; the Protocol itself lives in domain/audit.py so
code_intelligence/integrity.py can depend on the interface without
importing this module's concrete Sqlite implementation.

Framing, per BLUEPRINT.md Phase 8: this store is a cache of a pure
function, not a source of truth — the repository at a given commit_sha
remains that. A `schema_version`/`resolver_version` mismatch on load
means "these bytes don't match what this code would produce today,"
which is what code_intelligence/integrity.py's verify_integrity checks
for, not silent staleness papered over.

Serialization is pydantic's own `model_dump_json()`/`model_validate_
json()` — deterministic for a given model instance, since field order
follows the model's declared schema, not any hash-randomized runtime
structure. See tests/infrastructure/test_behavioral_record_store.py's
`test_save_is_byte_identical_across_independent_saves` for this
project's core reproducibility acceptance test, applied here.
"""

import contextlib
import sqlite3

from domain.audit import PersistedBehavioralRecord

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS behavioral_records (
    commit_sha TEXT NOT NULL,
    symbol_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    resolver_version TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (commit_sha, symbol_id)
)
"""


class InMemoryBehavioralRecordStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], PersistedBehavioralRecord] = {}

    def save(self, persisted: PersistedBehavioralRecord) -> None:
        key = (persisted.stamp.commit_sha, persisted.record.symbol_id)
        self._records[key] = persisted

    def get(self, commit_sha: str, symbol_id: str) -> PersistedBehavioralRecord | None:
        return self._records.get((commit_sha, symbol_id))

    def get_all_for_commit(self, commit_sha: str) -> list[PersistedBehavioralRecord]:
        return sorted(
            (p for p in self._records.values() if p.stamp.commit_sha == commit_sha),
            key=lambda p: p.record.symbol_id,
        )


class SqliteBehavioralRecordStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with contextlib.closing(self._connect()) as conn, conn:
            conn.execute(_CREATE_TABLE_SQL)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def save(self, persisted: PersistedBehavioralRecord) -> None:
        with contextlib.closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO behavioral_records "
                "(commit_sha, symbol_id, schema_version, resolver_version, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    persisted.stamp.commit_sha,
                    persisted.record.symbol_id,
                    persisted.stamp.schema_version,
                    persisted.stamp.resolver_version,
                    persisted.model_dump_json(),
                ),
            )

    def get(self, commit_sha: str, symbol_id: str) -> PersistedBehavioralRecord | None:
        with contextlib.closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload FROM behavioral_records WHERE commit_sha = ? AND symbol_id = ?",
                (commit_sha, symbol_id),
            ).fetchone()
        return PersistedBehavioralRecord.model_validate_json(row[0]) if row else None

    def get_all_for_commit(self, commit_sha: str) -> list[PersistedBehavioralRecord]:
        with contextlib.closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT payload FROM behavioral_records "
                "WHERE commit_sha = ? ORDER BY symbol_id ASC",
                (commit_sha,),
            ).fetchall()
        return [PersistedBehavioralRecord.model_validate_json(row[0]) for row in rows]
