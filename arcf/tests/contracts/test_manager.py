from uuid import uuid4

import pytest

from contracts.clarification import ClarificationPlanner
from contracts.confidence import ConfidenceEngine
from contracts.domain_classifier import DomainClassifier
from contracts.intent_extraction import RawIntentExtraction
from contracts.manager import ExecutionContractManager
from contracts.task_classifier import TaskClassifier
from domain.enums import ContractStatus
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.llm_client import LLMResponse
from shared.errors import ContractNotFoundError

_FAKE_LLM_RESPONSE = LLMResponse(
    content="",
    model="fake-slm",
    prompt_tokens=10,
    completion_tokens=10,
    total_tokens=20,
    attempts=1,
)


class FakeIntentExtractor:
    def __init__(self, responses: list[RawIntentExtraction]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    async def extract(self, raw_request: str) -> tuple[RawIntentExtraction, LLMResponse]:
        self.calls.append(raw_request)
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[index], _FAKE_LLM_RESPONSE


def _confident_response() -> RawIntentExtraction:
    return RawIntentExtraction(
        intent_summary="fix login bug",
        domain="backend",
        task="bug_fix",
        entities=["login.py"],
        constraints=[],
        assumptions=[],
        self_reported_confidence=0.9,
        suggested_clarifying_questions=[],
    )


def _ambiguous_response() -> RawIntentExtraction:
    return RawIntentExtraction(
        intent_summary="do something",
        domain="unknown",
        task="unknown",
        entities=[],
        constraints=[],
        assumptions=[],
        self_reported_confidence=0.3,
        suggested_clarifying_questions=[],
    )


def _build_manager(
    responses: list[RawIntentExtraction],
) -> tuple[ExecutionContractManager, InMemoryContractStore]:
    store = InMemoryContractStore()
    manager = ExecutionContractManager(
        intent_extractor=FakeIntentExtractor(responses),  # type: ignore[arg-type]
        domain_classifier=DomainClassifier(),
        task_classifier=TaskClassifier(),
        confidence_engine=ConfidenceEngine(),
        clarification_planner=ClarificationPlanner(),
        contract_store=store,
    )
    return manager, store


async def test_create_contract_approved_when_confident() -> None:
    manager, _ = _build_manager([_confident_response()])
    living, _ = await manager.create_contract("fix the broken login test in login.py")

    assert living.status is ContractStatus.APPROVED
    assert living.version == 1
    assert living.contract.intent.needs_clarification is False


async def test_create_contract_needs_clarification_when_ambiguous() -> None:
    manager, _ = _build_manager([_ambiguous_response()])
    living, _ = await manager.create_contract("do the thing")

    assert living.status is ContractStatus.NEEDS_CLARIFICATION
    assert living.contract.intent.needs_clarification is True
    assert len(living.contract.intent.clarifications) >= 1


async def test_create_contract_persists_to_store() -> None:
    manager, store = _build_manager([_confident_response()])
    living, _ = await manager.create_contract("fix the broken login test")

    fetched = store.get_latest(living.contract_id)
    assert fetched == living


async def test_clarify_evolves_contract_and_preserves_lineage_id() -> None:
    manager, _ = _build_manager([_ambiguous_response(), _confident_response()])

    v1, _ = await manager.create_contract("do the thing")
    assert v1.status is ContractStatus.NEEDS_CLARIFICATION

    v2, _ = await manager.clarify(v1.contract_id, "I mean fix login.py")

    assert v2.contract_id == v1.contract_id
    assert v2.version == 2
    assert v2.status is ContractStatus.APPROVED
    assert v2.contract.id != v1.contract.id
    assert v1.contract.id in v2.lineage


async def test_clarify_augments_original_request_with_answer() -> None:
    manager, _ = _build_manager([_ambiguous_response(), _confident_response()])
    v1, _ = await manager.create_contract("do the thing")
    await manager.clarify(v1.contract_id, "I mean fix login.py")

    extractor: FakeIntentExtractor = manager._intent_extractor  # type: ignore[assignment]
    assert "do the thing" in extractor.calls[1]
    assert "I mean fix login.py" in extractor.calls[1]


async def test_clarify_raises_for_unknown_contract_id() -> None:
    manager, _ = _build_manager([_confident_response()])
    with pytest.raises(ContractNotFoundError):
        await manager.clarify(uuid4(), "some answer")


async def test_get_contract_returns_none_for_unknown_id() -> None:
    manager, _ = _build_manager([_confident_response()])
    assert await manager.get_contract(uuid4()) is None


async def test_get_contract_returns_latest_version() -> None:
    manager, _ = _build_manager([_ambiguous_response(), _confident_response()])
    v1, _ = await manager.create_contract("do the thing")
    v2, _ = await manager.clarify(v1.contract_id, "I mean fix login.py")

    fetched = await manager.get_contract(v1.contract_id)
    assert fetched == v2
