"""ArcfExecutionOrchestrator tests (architecture closure, 2026-08-16).

Builds the real production sub-components (same classes
interfaces/api/app.py's create_app() wires) directly, rather than going
through FastAPI/TestClient, per DI-07/DI-08 (Recovery/Verification must
be independently testable). Only litellm.acompletion is faked, matching
this codebase's established test convention (see
tests/interfaces/test_context_package_route.py) -- everything else is
real: real SQLite-free in-memory stores, real ContextResolver/
RelevanceRanker/ContextBudgetManager, real prompt assembly.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import litellm
import pytest

from application.execute_use_case import ArcfExecutionOrchestrator
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from context.packager import ContextPackager
from context.relevance_ranker import RelevanceRanker
from context.understanding import ContextUnderstandingAnalyzer
from contracts.clarification import ClarificationPlanner
from contracts.confidence import ConfidenceEngine
from contracts.domain_classifier import DomainClassifier
from contracts.intent_extraction import IntentExtractor
from contracts.manager import ExecutionContractManager
from contracts.task_classifier import TaskClassifier
from domain.verification_result import GroundingVerificationStatus
from execution.context_goal_composer import ContextGoalComposer
from execution.final_generation import FinalGenerationRunner
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator
from infrastructure.execution_ledger_db import InMemoryExecutionLedgerStore
from infrastructure.llm_client import LiteLLMClient
from shared.errors import ContractNotFoundError

_MODEL = "gpt-4o-mini"

_INTENT_PAYLOAD: dict[str, object] = {
    "intent_summary": "add input validation",
    "domain": "backend",
    "task": "feature",
    "entities": ["authenticate"],
    "constraints": [],
    "assumptions": [],
    "self_reported_confidence": 0.9,
    "suggested_clarifying_questions": [],
}
_UNDERSTANDING_PAYLOAD: dict[str, object] = {
    "summary": "auth.py defines authenticate, called from login.py.",
    "key_relationships": ["login.py -> auth.py"],
}


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )


@pytest.fixture
def llm_state() -> dict[str, str]:
    return {"generation_content": "Modified `auth.py` to add a null check."}


@pytest.fixture
def patched_llm(monkeypatch: pytest.MonkeyPatch, llm_state: dict[str, str]) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        messages = kwargs.get("messages", [])
        prompt = messages[0]["content"] if messages else ""  # type: ignore[index]
        if "Dependency relationships among the selected files:" in prompt:
            return _fake_response(llm_state["generation_content"])
        if "key_relationships" in prompt:
            return _fake_response(json.dumps(_UNDERSTANDING_PAYLOAD))
        return _fake_response(json.dumps(_INTENT_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "auth.py").write_text("def authenticate(user):\n    return True\n")
    (repo / "login.py").write_text(
        "from .auth import authenticate\n\ndef login(user):\n    return authenticate(user)\n"
    )
    return repo


def _build_pipeline(
    ledger_store: InMemoryExecutionLedgerStore | None = None,
) -> tuple[ExecutionContractManager, ArcfExecutionOrchestrator, InMemoryExecutionLedgerStore]:
    llm_client = LiteLLMClient(max_retries=1, base_delay_seconds=0.0)
    contract_store = InMemoryContractStore()
    contract_manager = ExecutionContractManager(
        intent_extractor=IntentExtractor(llm_client=llm_client, model=_MODEL),
        domain_classifier=DomainClassifier(),
        task_classifier=TaskClassifier(),
        confidence_engine=ConfidenceEngine(),
        clarification_planner=ClarificationPlanner(),
        contract_store=contract_store,
    )
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    code_intelligence_service = CodeIntelligenceContractService(
        engine=engine,
        contract_store=contract_store,
        resolution_store=InMemoryContextResolutionStore(),
    )
    context_packager = ContextPackager(
        ranker=RelevanceRanker(),
        token_estimator=CostEstimator(),
        understanding_analyzer=ContextUnderstandingAnalyzer(llm_client=llm_client, model=_MODEL),
    )
    generation_runner = FinalGenerationRunner(ContextGoalComposer(), llm_client, _MODEL)
    ledger_store = ledger_store or InMemoryExecutionLedgerStore()
    orchestrator = ArcfExecutionOrchestrator(
        code_intelligence_service=code_intelligence_service,
        context_packager=context_packager,
        generation_runner=generation_runner,
        execution_ledger_store=ledger_store,
        cost_estimator=CostEstimator(),
        generation_model=_MODEL,
    )
    return contract_manager, orchestrator, ledger_store


# ---------------------------------------------------------------------------
# DI-01/DI-02/DI-10: the production composition root actually constructs this
# ---------------------------------------------------------------------------


def test_production_composition_root_constructs_orchestrator_via_di() -> None:
    from interfaces.api.app import create_app
    from shared.config import Settings

    settings = Settings(api_keys_raw="testkey:alice")  # type: ignore[call-arg]
    app = create_app(settings)

    assert isinstance(app.state.arcf_orchestrator, ArcfExecutionOrchestrator)
    # Constructed with the SAME singleton service instances DI already
    # wires for the lower-level routes, not a second, parallel set.
    assert app.state.arcf_orchestrator._code_intelligence_service is app.state.code_intelligence_service
    assert app.state.arcf_orchestrator._context_packager is app.state.context_packager


def test_classifiers_are_injected_by_composition_root_not_constructed_per_iteration() -> None:
    """DI consistency (2026-08-17, independent verification report):
    RepositoryScopeClassifier/TaskClassifier were previously constructed
    fresh inside run()'s own loop body on every iteration, inconsistent
    with every other collaborator this class depends on (all injected at
    construction time). Confirms the production composition root now
    passes its own instances rather than the orchestrator defaulting to
    ad hoc ones."""
    from contracts.repository_scope_classifier import RepositoryScopeClassifier
    from contracts.task_classifier import TaskClassifier
    from interfaces.api.app import create_app
    from shared.config import Settings

    settings = Settings(api_keys_raw="testkey:alice")  # type: ignore[call-arg]
    app = create_app(settings)

    assert isinstance(app.state.arcf_orchestrator._repository_scope_classifier, RepositoryScopeClassifier)
    assert isinstance(app.state.arcf_orchestrator._task_classifier, TaskClassifier)


def test_max_recovery_attempts_flows_from_settings_through_composition_root() -> None:
    """Config ownership (closure item #43): the retry bound is not a
    hardcoded constant hidden inside the orchestrator -- it flows
    Settings -> create_app() (composition root) -> ArcfExecutionOrchestrator,
    the same pattern every other configured value (default_model, etc.)
    already uses in this codebase."""
    from interfaces.api.app import create_app
    from shared.config import Settings

    settings = Settings(  # type: ignore[call-arg]
        api_keys_raw="testkey:alice", arcf_max_recovery_attempts=3
    )
    app = create_app(settings)

    assert app.state.arcf_orchestrator._max_recovery_attempts == 3


async def test_ledger_store_failure_does_not_crash_an_otherwise_successful_run(
    tmp_path: Path, patched_llm: None
) -> None:
    """PS-4 (persistence failures must not silently corrupt the main
    execution result), scoped narrowly to this closure's own new ledger
    write (see _save_ledger_entry's own docstring for why this isn't a
    codebase-wide fix)."""
    repo = _make_repo(tmp_path)
    contract_manager, orchestrator, _ledger_store = _build_pipeline()
    living, _ = await contract_manager.create_contract(
        "Please add input validation to the greeting handler", workspace_root=str(repo)
    )

    def broken_save(entry: object) -> None:
        raise RuntimeError("simulated database outage")

    orchestrator._execution_ledger_store.save = broken_save  # type: ignore[method-assign]

    result = await orchestrator.run(living.contract_id, target_names=["authenticate"])

    assert result.final_status == "success"
    assert result.artifact is not None


async def test_ledger_entry_construction_failure_does_not_crash_a_successful_run(
    tmp_path: Path, patched_llm: None
) -> None:
    """G-new-5 (2026-08-17 independent verification): the store-write
    guard above only covers `_save_ledger_entry`'s own call -- entry
    CONSTRUCTION (the token/cost aggregation, ExecutionLedgerEntry(...)
    itself) previously sat outside any protection at all, asymmetric with
    the failure path's own hardening. A construction-time exception here
    must not turn an otherwise fully successful, already-verified
    execution into an unhandled error for the caller."""
    repo = _make_repo(tmp_path)
    contract_manager, orchestrator, ledger_store = _build_pipeline()
    living, _ = await contract_manager.create_contract(
        "Please add input validation to the greeting handler", workspace_root=str(repo)
    )

    def broken_actual_cost(*args: object, **kwargs: object) -> float:
        raise RuntimeError("simulated cost-accounting bug during ledger construction")

    orchestrator._cost_estimator.actual_cost = broken_actual_cost  # type: ignore[method-assign]

    result = await orchestrator.run(living.contract_id, target_names=["authenticate"])

    assert result.final_status == "success"
    assert result.artifact is not None
    assert ledger_store.list_recent() == []  # construction failed -- nothing persisted, no crash


async def test_ledger_entry_construction_failure_on_failure_path_preserves_original_exception(
    tmp_path: Path, patched_llm: None, llm_state: dict[str, str]
) -> None:
    """G-new-5 follow-up, execution-to-ledger contract re-audit (item 20):
    the failure path's own ledger-entry construction (inside
    _persist_failure_ledger_entry, called from run()'s `except Exception`
    handler immediately before `raise`) was equally unguarded -- a second
    exception during THAT construction would have replaced the real,
    original failure reason instead of the original `raise` ever
    executing, exactly the "inconsistent audit state" this re-audit
    exists to rule out. The original RuntimeError from the retry must
    still be what actually propagates, not a cost-accounting bug."""
    llm_state["generation_content"] = "References `nonexistent/file_one.py` only."
    repo = _make_repo(tmp_path)
    contract_manager, orchestrator, ledger_store = _build_pipeline()
    living, _ = await contract_manager.create_contract(
        "Please add input validation to the greeting handler", workspace_root=str(repo)
    )

    real_attach = orchestrator._code_intelligence_service.attach_code_intelligence
    call_count = {"n": 0}

    async def flaky_attach(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated transient failure on the retry")
        return await real_attach(*args, **kwargs)

    orchestrator._code_intelligence_service.attach_code_intelligence = flaky_attach  # type: ignore[method-assign]

    def broken_actual_cost(*args: object, **kwargs: object) -> float:
        raise ValueError("simulated cost-accounting bug during failure-ledger construction")

    orchestrator._cost_estimator.actual_cost = broken_actual_cost  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="simulated transient failure"):
        await orchestrator.run(living.contract_id, target_names=["authenticate"])

    assert call_count["n"] == 2
    assert ledger_store.list_recent() == []  # construction failed -- nothing persisted, no crash


# ---------------------------------------------------------------------------
# Normal path
# ---------------------------------------------------------------------------


async def test_normal_path_reaches_generation_and_verification(
    tmp_path: Path, patched_llm: None
) -> None:
    repo = _make_repo(tmp_path)
    contract_manager, orchestrator, ledger_store = _build_pipeline()
    living, _ = await contract_manager.create_contract(
        "Please add input validation to the greeting handler", workspace_root=str(repo)
    )

    result = await orchestrator.run(living.contract_id, target_names=["authenticate"])

    assert result.final_status == "success"
    assert result.verification is not None
    assert result.verification.status == GroundingVerificationStatus.SUFFICIENT
    assert result.recovery_attempts == 0
    assert result.strategy_used == "classic"
    assert result.artifact is not None
    assert result.artifact.content == "Modified `auth.py` to add a null check."
    assert result.resolution_confidence == 1.0
    assert result.resolution_confidence_source == "classic"

    entry = ledger_store.get(result.request_id)
    assert entry is not None
    assert entry.contract_id == str(living.contract_id)
    assert entry.artifact_content == result.artifact.content
    assert set(entry.selected_files) == {"auth.py", "login.py"}
    assert entry.metadata["recovery_attempts"] == 0
    assert entry.metadata["final_status"] == "success"


async def test_entities_default_from_contract_intent_when_target_names_omitted(
    tmp_path: Path, patched_llm: None
) -> None:
    """QU-2/C-B2 closure: SLM-1's entities (["authenticate"] in
    _INTENT_PAYLOAD) reach retrieval without the caller supplying
    target_names at all."""
    repo = _make_repo(tmp_path)
    contract_manager, orchestrator, _ = _build_pipeline()
    living, _ = await contract_manager.create_contract(
        "Please add input validation to the greeting handler", workspace_root=str(repo)
    )

    result = await orchestrator.run(living.contract_id)  # no target_names

    assert result.final_status == "success"
    assert result.context_resolution_id is not None
    assert result.artifact is not None
    assert result.verification is not None
    assert result.verification.status == GroundingVerificationStatus.SUFFICIENT


# ---------------------------------------------------------------------------
# Case B: candidates exist, evidence insufficient -> recovery
# ---------------------------------------------------------------------------


async def test_insufficient_evidence_triggers_one_recovery_attempt_then_honestly_exhausts(
    tmp_path: Path, patched_llm: None
) -> None:
    """"authentication" in raw_request triggers AUTHENTICATION_EVIDENCE_CONTRACT
    (contracts/evidence_contract.py); the tiny fixture repo (auth.py +
    login.py only) genuinely lacks "credential source"/"session
    persistence"/"configuration" files ANYWHERE in the repository -- Case B
    on the classic attempt, checked BEFORE generation is ever attempted.

    Final closure pass (2026-08-17), Final Issue 1: before that pass's own
    fix, this test asserted `final_status == "success"` after the DRP
    retry -- but that was only true because DrpResolver's result never
    had evidence_categories_missing populated AT ALL, not because DRP
    genuinely found the missing evidence. Now that DRP runs the same
    validate_sufficiency() check classic does (real production code, no
    mock), the honest outcome is exhaustion: validate_sufficiency's own
    expansion mechanism is a deterministic repo-wide glob match, resolver-
    independent -- if the evidence files genuinely don't exist anywhere in
    the repository, no resolution STRATEGY can conjure them, and no
    resolver should ever report otherwise. This is the natural,
    non-mocked demonstration of Case-B recovery through DRP the
    architecture requires -- a real production execution, not a
    controlled double (see
    test_case_b_evidence_still_missing_after_recovery_exhausts_to_low_confidence
    below for the complementary isolated-mechanism proof, which uses a
    double specifically so it's not tied to what this particular fixture
    repo happens to contain)."""
    repo = _make_repo(tmp_path)
    contract_manager, orchestrator, ledger_store = _build_pipeline()
    living, _ = await contract_manager.create_contract(
        "Please review the authentication flow", workspace_root=str(repo)
    )

    result = await orchestrator.run(living.contract_id, target_names=["authenticate"])

    assert result.recovery_attempts == 1
    assert result.strategy_used == "drp"
    assert result.resolution_confidence_source == "drp"
    assert result.final_status == "low_confidence"
    assert result.verification is not None
    assert result.verification.status == GroundingVerificationStatus.INSUFFICIENT_EVIDENCE
    assert result.verification.missing_evidence_categories != ()
    # The retry still reaches generation despite evidence remaining
    # insufficient -- attempts are exhausted, not silently short-circuited.
    assert result.artifact is not None

    entry = ledger_store.get(result.request_id)
    assert entry is not None
    assert entry.metadata["recovery_attempts"] == 1
    assert entry.metadata["strategy_used"] == "drp"
    assert entry.metadata["final_status"] == "low_confidence"


async def test_task_type_classification_is_computed_once_per_run_not_per_retry(
    tmp_path: Path, patched_llm: None
) -> None:
    """G12 (2026-08-17 independent verification report): retrieval_task_type/
    ranking_profile are pure functions of raw_request, which never changes
    across this run() call's own recovery retry -- previously recomputed
    on every loop iteration for no reason. Proves the real fix (a cached
    value, computed once) rather than just asserting the final outcome is
    unchanged, using the same Case-B recovery scenario that genuinely
    retries."""
    repo = _make_repo(tmp_path)
    contract_manager, orchestrator, _ledger_store = _build_pipeline()
    living, _ = await contract_manager.create_contract(
        "Please review the authentication flow", workspace_root=str(repo)
    )

    real_classify = orchestrator._task_classifier.classify
    call_count = {"n": 0}

    def counting_classify(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        return real_classify(*args, **kwargs)

    orchestrator._task_classifier.classify = counting_classify  # type: ignore[method-assign]

    result = await orchestrator.run(living.contract_id, target_names=["authenticate"])

    assert result.recovery_attempts == 1  # confirms a real retry happened
    assert call_count["n"] == 1  # but classification only ran once


async def test_case_b_evidence_still_missing_after_recovery_exhausts_to_low_confidence(
    tmp_path: Path, patched_llm: None
) -> None:
    """G-new-7 (2026-08-17 independent verification report), updated by
    the final closure pass's Final Issue 1 fix: Case-B exhaustion
    (evidence STILL missing after the recovery retry) is now ALSO
    naturally reachable end-to-end (see
    test_insufficient_evidence_triggers_one_recovery_attempt_then_honestly_exhausts
    above, a real, non-mocked production execution proving exactly this).
    This test remains valuable as a complementary, ISOLATED-mechanism
    proof: it forces the scenario via a controlled double on
    attach_code_intelligence with an arbitrary missing category
    ("credential source") rather than depending on what a specific
    fixture repository happens to lack, so it keeps testing the
    orchestrator's own exhaustion-handling logic in isolation even if a
    future fixture change made the natural test above stop naturally
    triggering Case B. Distinct from Case-C exhaustion (verify_grounding's
    own unsupported-reference outcome), covered separately by
    test_unsupported_reference_triggers_recovery_and_exhausts_to_low_confidence."""
    repo = _make_repo(tmp_path)
    contract_manager, orchestrator, ledger_store = _build_pipeline()
    living, _ = await contract_manager.create_contract(
        "Please review the authentication flow", workspace_root=str(repo)
    )

    real_attach = orchestrator._code_intelligence_service.attach_code_intelligence

    async def always_missing_evidence(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        living_result, resolution = await real_attach(*args, **kwargs)
        forced = resolution.model_copy(
            update={"evidence_categories_missing": ("credential source",)}
        )
        return living_result, forced

    orchestrator._code_intelligence_service.attach_code_intelligence = always_missing_evidence  # type: ignore[method-assign]

    result = await orchestrator.run(living.contract_id, target_names=["authenticate"])

    assert result.recovery_attempts == 1  # bounded -- never a second retry
    assert result.strategy_used == "drp"  # the one allowed retry really was attempted
    assert result.final_status == "low_confidence"
    assert result.verification is not None
    assert result.verification.status == GroundingVerificationStatus.INSUFFICIENT_EVIDENCE
    assert result.verification.missing_evidence_categories == ("credential source",)
    # The final pass still reaches generation despite evidence remaining
    # insufficient -- attempts are exhausted, not silently short-circuited
    # before a real result is produced.
    assert result.artifact is not None

    entry = ledger_store.get(result.request_id)
    assert entry is not None
    assert entry.metadata["final_status"] == "low_confidence"
    assert entry.metadata["verification_status"] == "insufficient_evidence"


# ---------------------------------------------------------------------------
# Case C: evidence exists, generation references an unretrieved file ->
# recovery -> still low_confidence if the retry doesn't fix it -> never
# silently reports success
# ---------------------------------------------------------------------------


async def test_unsupported_reference_triggers_recovery_and_exhausts_to_low_confidence(
    tmp_path: Path, patched_llm: None, llm_state: dict[str, str]
) -> None:
    llm_state["generation_content"] = (
        "Modified `auth.py` and also `payments/gateway.py` (which does not exist in this repo)."
    )
    repo = _make_repo(tmp_path)
    contract_manager, orchestrator, ledger_store = _build_pipeline()
    living, _ = await contract_manager.create_contract(
        "Please add input validation to the greeting handler", workspace_root=str(repo)
    )

    result = await orchestrator.run(living.contract_id, target_names=["authenticate"])

    # The fake LLM keeps returning the same ungrounded content on the
    # retry too (a real LLM might not, but this proves exhaustion behaves
    # correctly when it doesn't self-correct) -- MAX_RECOVERY_ATTEMPTS=1
    # is respected exactly once, never more, and the result is explicit,
    # never silently "success".
    assert result.recovery_attempts == 1
    assert result.strategy_used == "drp"
    assert result.final_status == "low_confidence"
    assert result.verification is not None
    assert result.verification.status == GroundingVerificationStatus.UNSUPPORTED_REFERENCES
    assert "payments/gateway.py" in result.verification.unsupported_file_references

    entry = ledger_store.get(result.request_id)
    assert entry is not None
    assert entry.metadata["final_status"] == "low_confidence"
    # Run itself completed (this is NOT a transport/infra failure) --
    # execution_status describes "did the run complete", not grounding
    # quality (domain/execution_ledger.py's own documented distinction).
    assert entry.execution_status == "success"


async def test_recovery_never_exceeds_max_recovery_attempts(
    tmp_path: Path, patched_llm: None, llm_state: dict[str, str]
) -> None:
    llm_state["generation_content"] = "References `nonexistent/file_one.py` only."
    repo = _make_repo(tmp_path)
    contract_manager, orchestrator, _ = _build_pipeline()
    living, _ = await contract_manager.create_contract(
        "Please add input validation to the greeting handler", workspace_root=str(repo)
    )

    result = await orchestrator.run(living.contract_id, target_names=["authenticate"])

    assert result.recovery_attempts == 1  # exactly the fixed bound, not more


# ---------------------------------------------------------------------------
# Infrastructure failures propagate as real exceptions, not low_confidence
# ---------------------------------------------------------------------------


async def test_unknown_contract_raises_not_masked_as_low_confidence(patched_llm: None) -> None:
    _contract_manager, orchestrator, _ = _build_pipeline()
    from uuid import uuid4

    with pytest.raises(ContractNotFoundError):
        await orchestrator.run(uuid4(), target_names=["authenticate"])


async def test_exception_during_recovery_retry_still_persists_real_spend_from_attempt_zero(
    tmp_path: Path, patched_llm: None, llm_state: dict[str, str]
) -> None:
    """2026-08-17 hardening (adversarial re-verification found this):
    attempt 0 can fully complete a real, costed generate() call, fail
    verification, and trigger a recovery retry -- if the RETRY's own
    attach_code_intelligence call then raises (any transient failure),
    the exception must still propagate (this is a real infrastructure
    failure, not a grounding outcome), but attempt 0's real spend must
    not simply vanish from the ledger. Previously it did."""
    llm_state["generation_content"] = "References `nonexistent/file_one.py` only."
    repo = _make_repo(tmp_path)
    contract_manager, orchestrator, ledger_store = _build_pipeline()
    living, _ = await contract_manager.create_contract(
        "Please add input validation to the greeting handler", workspace_root=str(repo)
    )

    real_attach = orchestrator._code_intelligence_service.attach_code_intelligence
    call_count = {"n": 0}

    async def flaky_attach(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        if call_count["n"] == 2:  # the recovery retry's own call
            raise RuntimeError("simulated transient failure on the retry")
        return await real_attach(*args, **kwargs)

    orchestrator._code_intelligence_service.attach_code_intelligence = flaky_attach  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="simulated transient failure"):
        await orchestrator.run(living.contract_id, target_names=["authenticate"])

    assert call_count["n"] == 2  # confirms the retry really was reached
    entries = ledger_store.list_recent()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.total_tokens > 0  # attempt 0's real generation cost, not lost
    assert entry.execution_status == "execution_error"  # RuntimeError isn't in the known mapping
    assert entry.metadata["failure_reason"].startswith("RuntimeError")
    assert entry.metadata["final_status"] is None
