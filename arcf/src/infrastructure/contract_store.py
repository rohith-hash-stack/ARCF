"""Living Contract persistence (Phase 3 deliverable).

Each version of a contract's lineage is stored as a full JSON snapshot
keyed by (contract_id, version) — contract_id is LivingContract's
stable lineage id (see domain/versioning.py), not the per-snapshot
Contract.id. SqliteContractStore opens a fresh connection per call and
never caches one across calls, so it's safe to run through
asyncio.to_thread from multiple concurrent requests.
"""

import contextlib
import sqlite3
from typing import Protocol
from uuid import UUID

from domain.versioning import LivingContract

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS living_contracts (
    contract_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (contract_id, version)
)
"""


class ContractStore(Protocol):
    def save(self, living: LivingContract) -> None: ...
    def get_latest(self, contract_id: UUID) -> LivingContract | None: ...
    def get_history(self, contract_id: UUID) -> list[LivingContract]: ...


class InMemoryContractStore:
    def __init__(self) -> None:
        self._versions: dict[UUID, list[LivingContract]] = {}

    def save(self, living: LivingContract) -> None:
        self._versions.setdefault(living.contract_id, []).append(living)

    def get_latest(self, contract_id: UUID) -> LivingContract | None:
        history = self._versions.get(contract_id)
        if not history:
            return None
        return max(history, key=lambda living: living.version)

    def get_history(self, contract_id: UUID) -> list[LivingContract]:
        return sorted(self._versions.get(contract_id, []), key=lambda living: living.version)


class SqliteContractStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with contextlib.closing(self._connect()) as conn, conn:
            conn.execute(_CREATE_TABLE_SQL)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def save(self, living: LivingContract) -> None:
        with contextlib.closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO living_contracts (contract_id, version, payload) "
                "VALUES (?, ?, ?)",
                (str(living.contract_id), living.version, living.model_dump_json()),
            )

    def get_latest(self, contract_id: UUID) -> LivingContract | None:
        with contextlib.closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload FROM living_contracts WHERE contract_id = ? "
                "ORDER BY version DESC LIMIT 1",
                (str(contract_id),),
            ).fetchone()
        return LivingContract.model_validate_json(row[0]) if row else None

    def get_history(self, contract_id: UUID) -> list[LivingContract]:
        with contextlib.closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT payload FROM living_contracts WHERE contract_id = ? ORDER BY version ASC",
                (str(contract_id),),
            ).fetchall()
        return [LivingContract.model_validate_json(row[0]) for row in rows]
