from pathlib import Path
from uuid import uuid4

import pytest

from domain.contract import Contract
from domain.enums import ContractStatus
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.contract_store import ContractStore, InMemoryContractStore, SqliteContractStore


def _make_living(status: ContractStatus = ContractStatus.DRAFT) -> LivingContract:
    intent = UserIntent(
        raw_request="Fix the failing login test",
        intent="fix_login_test",
        domain="testing",
        task="bug_fix",
        confidence=0.8,
    )
    return LivingContract(contract=Contract(intent=intent), status=status)


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> ContractStore:
    if request.param == "memory":
        return InMemoryContractStore()
    return SqliteContractStore(str(tmp_path / "contracts.db"))


def test_get_latest_returns_none_for_unknown_contract(store: ContractStore) -> None:
    assert store.get_latest(uuid4()) is None


def test_save_and_get_latest_roundtrips(store: ContractStore) -> None:
    living = _make_living()
    store.save(living)
    fetched = store.get_latest(living.contract_id)
    assert fetched is not None
    assert fetched.contract_id == living.contract_id
    assert fetched.contract.intent.raw_request == living.contract.intent.raw_request


def test_get_latest_returns_highest_version(store: ContractStore) -> None:
    v1 = _make_living()
    store.save(v1)
    v2 = v1.evolve(v1.contract, status=ContractStatus.APPROVED)
    store.save(v2)

    latest = store.get_latest(v1.contract_id)
    assert latest is not None
    assert latest.version == 2
    assert latest.status is ContractStatus.APPROVED


def test_get_history_returns_all_versions_in_order(store: ContractStore) -> None:
    v1 = _make_living()
    store.save(v1)
    v2 = v1.evolve(v1.contract)
    store.save(v2)
    v3 = v2.evolve(v2.contract)
    store.save(v3)

    history = store.get_history(v1.contract_id)
    assert [living.version for living in history] == [1, 2, 3]


def test_sqlite_store_persists_across_instances(tmp_path: Path) -> None:
    db_path = str(tmp_path / "persist.db")
    living = _make_living()

    SqliteContractStore(db_path).save(living)
    reopened = SqliteContractStore(db_path)
    fetched = reopened.get_latest(living.contract_id)

    assert fetched is not None
    assert fetched.contract_id == living.contract_id
