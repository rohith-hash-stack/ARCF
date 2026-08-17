"""FastAPI app factory for the Secure Fast Path, Intent & Contract Layer,
Workspace Intelligence, Code Intelligence, and Context Intelligence.

A factory (not a module-level `app = FastAPI()`) so tests can build an
app wired to fake settings/clock/sleep without needing environment
variables or monkeypatching module globals.
"""

from pathlib import Path

from fastapi import FastAPI

from application.execute_use_case import ArcfExecutionOrchestrator
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.cpp_analyzer import CppLanguageAnalyzer
from code_intelligence.languages.csharp_analyzer import CSharpLanguageAnalyzer
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.languages.java_analyzer import JavaLanguageAnalyzer
from code_intelligence.languages.kotlin_analyzer import KotlinLanguageAnalyzer
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.languages.rust_analyzer import RustLanguageAnalyzer
from code_intelligence.languages.typescript_analyzer import TypeScriptLanguageAnalyzer
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
from contracts.repository_scope_classifier import RepositoryScopeClassifier
from contracts.task_classifier import TaskClassifier
from execution.context_goal_composer import ContextGoalComposer
from execution.final_generation import FinalGenerationRunner
from infrastructure.auth import Authenticator
from infrastructure.comparison_store import SqliteComparisonStore
from infrastructure.context_resolution_store import SqliteContextResolutionStore
from infrastructure.contract_store import SqliteContractStore
from infrastructure.cost import CostEstimator, CostGuardrail
from infrastructure.execution_ledger_db import SqliteExecutionLedgerStore
from infrastructure.idempotency import IdempotencyGuard, InMemoryIdempotencyStore
from infrastructure.llm_client import LiteLLMClient
from infrastructure.rate_limit import RateLimiter
from infrastructure.tracing import configure_tracing
from interfaces.api.middleware import RequestSizeLimitMiddleware, TracingMiddleware
from interfaces.api.routes.code_intelligence import router as code_intelligence_router
from interfaces.api.routes.comparison import router as comparison_router
from interfaces.api.routes.context_package import router as context_package_router
from interfaces.api.routes.contracts import router as contracts_router
from interfaces.api.routes.execute import router as execute_router
from interfaces.api.routes.execution_ledger import router as execution_ledger_router
from interfaces.api.routes.grounded_execution import router as grounded_execution_router
from interfaces.api.routes.workspace import router as workspace_router
from shared.config import Settings, get_settings
from telemetry.comparison_aggregator import ComparisonAggregator
from workspace.analyzer import WorkspaceAnalyzer
from workspace.git_discovery import GitRepositoryDiscovery
from workspace.language_detection import LanguageDetector
from workspace.scanner import RepositoryScanner
from workspace.service import WorkspaceContractService
from workspace.structure_analyzer import ProjectStructureAnalyzer


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(title="ARCF Secure Fast Path", version="0.1.0")

    app.state.settings = settings
    app.state.authenticator = Authenticator(settings)
    app.state.rate_limiter = RateLimiter(
        capacity=settings.rate_limit_capacity,
        refill_per_second=settings.rate_limit_refill_per_second,
    )
    app.state.idempotency_guard = IdempotencyGuard(
        InMemoryIdempotencyStore(ttl_seconds=settings.idempotency_ttl_seconds)
    )
    app.state.cost_guardrail = CostGuardrail(
        estimator=CostEstimator(), max_cost_usd=settings.cost_guardrail_max_usd
    )
    app.state.llm_client = LiteLLMClient(
        max_retries=settings.max_retries,
        base_delay_seconds=settings.retry_base_delay_seconds,
    )

    contract_store = SqliteContractStore(settings.contract_store_path)
    app.state.contract_manager = ExecutionContractManager(
        intent_extractor=IntentExtractor(
            llm_client=app.state.llm_client, model=settings.slm_model
        ),
        domain_classifier=DomainClassifier(),
        task_classifier=TaskClassifier(),
        confidence_engine=ConfidenceEngine(),
        clarification_planner=ClarificationPlanner(
            confidence_threshold=settings.confidence_clarification_threshold
        ),
        contract_store=contract_store,
    )
    app.state.workspace_service = WorkspaceContractService(
        analyzer=WorkspaceAnalyzer(
            git_discovery=GitRepositoryDiscovery(),
            scanner=RepositoryScanner(max_files=settings.workspace_max_files_scanned),
            language_detector=LanguageDetector(),
            structure_analyzer=ProjectStructureAnalyzer(),
        ),
        contract_store=contract_store,
        allowed_roots=[Path(root) for root in settings.workspace_allowlist],
    )

    code_intelligence_engine = CodeIntelligenceEngine(
        registry=LanguageRegistry(
            [
                PythonLanguageAnalyzer(),
                TypeScriptLanguageAnalyzer(),
                GoLanguageAnalyzer(),
                JavaLanguageAnalyzer(),
                CSharpLanguageAnalyzer(),
                KotlinLanguageAnalyzer(),
                CppLanguageAnalyzer(),
                RustLanguageAnalyzer(),
            ]
        ),
        token_estimator=CostEstimator(),
    )
    context_resolution_store = SqliteContextResolutionStore(settings.context_resolution_store_path)
    app.state.code_intelligence_service = CodeIntelligenceContractService(
        engine=code_intelligence_engine,
        contract_store=contract_store,
        resolution_store=context_resolution_store,
    )
    app.state.context_resolution_store = context_resolution_store
    app.state.execution_ledger_store = SqliteExecutionLedgerStore(
        settings.execution_ledger_db_path
    )
    app.state.comparison_store = SqliteComparisonStore(settings.comparison_store_path)
    app.state.comparison_aggregator = ComparisonAggregator()
    app.state.context_packager = ContextPackager(
        ranker=RelevanceRanker(),
        token_estimator=CostEstimator(),
        understanding_analyzer=ContextUnderstandingAnalyzer(
            llm_client=app.state.llm_client, model=settings.slm_model
        ),
    )

    # Architecture closure (2026-08-16): Phase 8's generation step, built
    # but never previously constructed by any production code path.
    app.state.generation_runner = FinalGenerationRunner(
        composer=ContextGoalComposer(),
        llm_client=app.state.llm_client,
        model=settings.default_model,
    )
    app.state.arcf_orchestrator = ArcfExecutionOrchestrator(
        code_intelligence_service=app.state.code_intelligence_service,
        context_packager=app.state.context_packager,
        generation_runner=app.state.generation_runner,
        execution_ledger_store=app.state.execution_ledger_store,
        cost_estimator=CostEstimator(),
        generation_model=settings.default_model,
        max_recovery_attempts=settings.arcf_max_recovery_attempts,
        repository_scope_classifier=RepositoryScopeClassifier(),
        task_classifier=TaskClassifier(),
    )

    tracer = configure_tracing(settings)
    app.add_middleware(TracingMiddleware, tracer=tracer)
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.max_request_bytes)

    app.include_router(execute_router)
    app.include_router(contracts_router)
    app.include_router(workspace_router)
    app.include_router(code_intelligence_router)
    app.include_router(context_package_router)
    app.include_router(execution_ledger_router)
    app.include_router(comparison_router)
    app.include_router(grounded_execution_router)

    return app


app = create_app()
