from domain.contract import Contract
from domain.enums import ContractStatus
from domain.intent import UserIntent
from domain.versioning import LivingContract


def _make_intent() -> UserIntent:
    return UserIntent(
        raw_request="Fix the failing Playwright login test",
        intent="fix_failing_test",
        domain="testing",
        task="bug_fix",
        confidence=0.87,
    )


def test_initial_version_starts_at_one_with_empty_lineage() -> None:
    living = LivingContract(contract=Contract(intent=_make_intent()))
    assert living.version == 1
    assert living.lineage == []
    assert living.status is ContractStatus.DRAFT


def test_evolve_increments_version_and_records_lineage() -> None:
    original_contract = Contract(intent=_make_intent())
    living_v1 = LivingContract(contract=original_contract)

    updated_contract = original_contract.model_copy(update={"execution_strategy": "patch_and_test"})
    living_v2 = living_v1.evolve(updated_contract, status=ContractStatus.APPROVED)

    assert living_v2.version == 2
    assert living_v2.lineage == [original_contract.id]
    assert living_v2.status is ContractStatus.APPROVED
    assert living_v2.created_at == living_v1.created_at
    assert living_v2.updated_at >= living_v1.updated_at
    assert living_v2.contract_id == living_v1.contract_id


def test_evolve_preserves_status_when_not_specified() -> None:
    living_v1 = LivingContract(
        contract=Contract(intent=_make_intent()), status=ContractStatus.NEEDS_CLARIFICATION
    )
    living_v2 = living_v1.evolve(living_v1.contract)
    assert living_v2.status is ContractStatus.NEEDS_CLARIFICATION


def test_evolve_chain_accumulates_full_lineage() -> None:
    contract_a = Contract(intent=_make_intent())
    living = LivingContract(contract=contract_a)

    contract_b = contract_a.model_copy(update={"risks": ["flaky selector"]})
    living = living.evolve(contract_b)

    contract_c = contract_b.model_copy(update={"risks": ["flaky selector", "network timeout"]})
    living = living.evolve(contract_c)

    assert living.version == 3
    assert living.lineage == [contract_a.id, contract_b.id]


def test_contract_id_is_unique_per_lineage() -> None:
    a = LivingContract(contract=Contract(intent=_make_intent()))
    b = LivingContract(contract=Contract(intent=_make_intent()))
    assert a.contract_id != b.contract_id
