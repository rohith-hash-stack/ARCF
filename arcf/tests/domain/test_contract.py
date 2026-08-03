from domain.artifact import Artifact
from domain.contract import Contract
from domain.enums import ArtifactKind
from domain.intent import UserIntent


def _make_intent() -> UserIntent:
    return UserIntent(
        raw_request="Fix the failing Playwright login test",
        intent="fix_failing_test",
        domain="testing",
        task="bug_fix",
        confidence=0.87,
    )


def test_contract_defaults() -> None:
    contract = Contract(intent=_make_intent())
    assert contract.target_files == []
    assert contract.permissions == []
    assert contract.policies == []
    assert contract.risks == []
    assert contract.artifacts == []
    assert contract.metadata == {}
    assert contract.execution_strategy is None


def test_contract_ids_are_unique() -> None:
    intent = _make_intent()
    assert Contract(intent=intent).id != Contract(intent=intent).id


def test_contract_carries_artifacts() -> None:
    artifact = Artifact(kind=ArtifactKind.TEST_CASE, content="def test_login(): ...")
    contract = Contract(intent=_make_intent(), artifacts=[artifact])
    assert contract.artifacts == [artifact]
