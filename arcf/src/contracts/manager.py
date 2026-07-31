"""Execution Contract Manager — Phase 3's orchestration layer.

Ties together SLM-1 extraction, deterministic classifier corroboration,
confidence scoring, clarification planning, contract construction, and
persistence. Deliberately has no FastAPI/HTTP dependency and no
knowledge of ExecutionContext, Settings, or the cost guardrail — those
are the API layer's concern (interfaces/api/routes/contracts.py), which
uses the LLMResponse this returns to do its own budget accounting. That
keeps this class testable with a fake IntentExtractor and an
InMemoryContractStore, no FastAPI or network involved.
"""

import asyncio
from uuid import UUID, uuid4

from contracts.clarification import ClarificationPlanner
from contracts.confidence import ConfidenceEngine, ConfidenceSignals
from contracts.domain_classifier import DomainClassifier
from contracts.intent_extraction import IntentExtractor
from contracts.task_classifier import TaskClassifier
from domain.contract import Contract
from domain.enums import ContractStatus
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.contract_store import ContractStore
from infrastructure.llm_client import LLMResponse
from shared.errors import ContractNotFoundError


class ExecutionContractManager:
    def __init__(
        self,
        intent_extractor: IntentExtractor,
        domain_classifier: DomainClassifier,
        task_classifier: TaskClassifier,
        confidence_engine: ConfidenceEngine,
        clarification_planner: ClarificationPlanner,
        contract_store: ContractStore,
    ) -> None:
        self._intent_extractor = intent_extractor
        self._domain_classifier = domain_classifier
        self._task_classifier = task_classifier
        self._confidence_engine = confidence_engine
        self._clarification_planner = clarification_planner
        self._contract_store = contract_store

    async def _build_intent(self, raw_request: str) -> tuple[UserIntent, LLMResponse]:
        raw, llm_response = await self._intent_extractor.extract(raw_request)

        domain_agrees = self._domain_classifier.agrees_with(raw_request, raw.domain)
        task_agrees = self._task_classifier.agrees_with(raw_request, raw.task)

        signals = ConfidenceSignals(
            domain_known=raw.domain != "unknown",
            task_known=raw.task != "unknown",
            domain_classifier_agrees=domain_agrees,
            task_classifier_agrees=task_agrees,
            entity_count=len(raw.entities),
            constraint_count=len(raw.constraints),
            assumption_count=len(raw.assumptions),
            self_reported_confidence=raw.self_reported_confidence,
            raw_request_char_count=len(raw_request),
        )
        confidence = self._confidence_engine.score(signals)

        clarifications = self._clarification_planner.plan(
            raw.domain, raw.task, raw.entities, confidence
        )
        for question in raw.suggested_clarifying_questions:
            if question not in clarifications:
                clarifications.append(question)

        intent = UserIntent(
            raw_request=raw_request,
            intent=raw.intent_summary,
            domain=raw.domain,
            task=raw.task,
            entities=raw.entities,
            constraints=raw.constraints,
            assumptions=raw.assumptions,
            confidence=confidence,
            clarifications=clarifications,
        )
        return intent, llm_response

    async def create_contract(
        self, raw_request: str, workspace_root: str | None = None
    ) -> tuple[LivingContract, LLMResponse]:
        intent, llm_response = await self._build_intent(raw_request)
        contract = Contract(intent=intent, workspace_root=workspace_root)
        status = (
            ContractStatus.NEEDS_CLARIFICATION
            if intent.needs_clarification
            else ContractStatus.APPROVED
        )
        living = LivingContract(contract=contract, status=status)
        await asyncio.to_thread(self._contract_store.save, living)
        return living, llm_response

    async def clarify(
        self, contract_id: UUID, answer: str
    ) -> tuple[LivingContract, LLMResponse]:
        latest = await asyncio.to_thread(self._contract_store.get_latest, contract_id)
        if latest is None:
            raise ContractNotFoundError(f"No contract found with id {contract_id}")

        augmented_request = (
            f"{latest.contract.intent.raw_request}\n\nAdditional context from user: {answer}"
        )
        intent, llm_response = await self._build_intent(augmented_request)
        new_contract = latest.contract.model_copy(update={"intent": intent, "id": uuid4()})
        status = (
            ContractStatus.NEEDS_CLARIFICATION
            if intent.needs_clarification
            else ContractStatus.APPROVED
        )
        evolved = latest.evolve(new_contract, status=status)
        await asyncio.to_thread(self._contract_store.save, evolved)
        return evolved, llm_response

    async def get_contract(self, contract_id: UUID) -> LivingContract | None:
        return await asyncio.to_thread(self._contract_store.get_latest, contract_id)
