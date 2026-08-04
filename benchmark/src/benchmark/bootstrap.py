"""build_runtime — the one place that wires ARCF's own Phase 1-6
classes (unmodified) plus the benchmark's own controller/analyzer/
storage/local-SLM detection, so api/app.py (long-running FastAPI
service) and cli.py (one-shot script) build the IDENTICAL runtime
instead of duplicating this wiring block twice.

Mode B and Mode C share one workspace_service/code_intelligence_service/
context_packager/llm_client instance — only the ExecutionContractManager
(and therefore IntentExtractor/slm_model) differs between the two
ArcfRunner instances, which is the whole point: "only intent extraction
differs" is enforced by construction, not by convention.

Local SLM cost note: CostEstimator (arcf/src/infrastructure/cost.py)
falls back to a conservative non-zero USD/1K-token rate for any model
name it doesn't recognize — including local Ollama model strings, which
are actually free to run. That's ARCF's own existing behavior for any
unlisted model (e.g. non-OpenAI remote models hit the same fallback)
and is left as-is rather than special-cased here; pipeline_overhead_cost
for arcf_local should be read as "what this would cost on a metered
provider," not a real local-inference cost.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.csharp_analyzer import CSharpLanguageAnalyzer
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.languages.java_analyzer import JavaLanguageAnalyzer
from code_intelligence.languages.kotlin_analyzer import KotlinLanguageAnalyzer
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.languages.typescript_analyzer import TypeScriptLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from context.packager import ContextPackager
from context.relevance_ranker import RelevanceRanker
from contracts.clarification import ClarificationPlanner
from contracts.confidence import ConfidenceEngine
from contracts.domain_classifier import DomainClassifier
from contracts.intent_extraction import IntentExtractor
from contracts.manager import ExecutionContractManager
from contracts.task_classifier import TaskClassifier
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator
from infrastructure.execution_ledger_db import SqliteExecutionLedgerStore
from infrastructure.llm_client import LiteLLMClient
from workspace.analyzer import WorkspaceAnalyzer
from workspace.git_discovery import GitRepositoryDiscovery
from workspace.language_detection import LanguageDetector
from workspace.scanner import RepositoryScanner
from workspace.service import WorkspaceContractService
from workspace.structure_analyzer import ProjectStructureAnalyzer

from benchmark.analyzer import BenchmarkAnalyzer
from benchmark.config import BenchmarkSettings
from benchmark.controller import BenchmarkController
from benchmark.domain.models import BenchmarkMode
from benchmark.ledger import LedgerRecorder
from benchmark.local_slm.errors import LocalSLMUnavailableError
from benchmark.local_slm.ollama_provider import OllamaProvider
from benchmark.repository import RepositoryLoader
from benchmark.runners.arcf_runner import ArcfRunner
from benchmark.runners.direct_llm_runner import DirectLLMRunner
from benchmark.storage import BenchmarkStore

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    settings: BenchmarkSettings
    repository_loader: RepositoryLoader
    controller: BenchmarkController
    store: BenchmarkStore
    ledger_recorder: LedgerRecorder
    """Shared with SuiteRunner (built by cli.py's _suite_run) so `suite
    run` and `compare`/the API write to the same Execution Ledger."""
    local_slm_unavailable_reason: str | None
    """None when Mode C (arcf_local) is available. Otherwise, why it
    isn't — surfaced by callers so operators aren't left guessing why
    a mode they expected is missing."""
    direct_runner: DirectLLMRunner
    arcf_runner: ArcfRunner
    arcf_local_runner: ArcfRunner | None
    """Same runner instances controller was built with — exposed here
    too so callers that need to drive individual runners directly (the
    suite runner, against scratch repos) reuse them instead of
    reaching into BenchmarkController's private attributes."""


def _workspace_analyzer(settings: BenchmarkSettings) -> WorkspaceAnalyzer:
    return WorkspaceAnalyzer(
        git_discovery=GitRepositoryDiscovery(),
        scanner=RepositoryScanner(max_files=settings.workspace_max_files_scanned),
        language_detector=LanguageDetector(),
        structure_analyzer=ProjectStructureAnalyzer(),
    )


def build_runtime(settings: BenchmarkSettings) -> Runtime:
    llm_client = LiteLLMClient(
        max_retries=settings.max_retries, base_delay_seconds=settings.retry_base_delay_seconds
    )
    cost_estimator = CostEstimator()

    repository_loader = RepositoryLoader(
        clone_root=Path(settings.clone_root),
        analyzer=_workspace_analyzer(settings),
        scanner=RepositoryScanner(max_files=settings.workspace_max_files_scanned),
    )

    # ARCF's actual Phase 1-6 pipeline, in-process and unmodified.
    contract_store = InMemoryContractStore()

    def build_contract_manager(slm_model: str) -> ExecutionContractManager:
        return ExecutionContractManager(
            intent_extractor=IntentExtractor(
                llm_client=llm_client, model=slm_model, max_tokens=settings.slm_max_tokens
            ),
            domain_classifier=DomainClassifier(),
            task_classifier=TaskClassifier(),
            confidence_engine=ConfidenceEngine(),
            clarification_planner=ClarificationPlanner(),
            contract_store=contract_store,
        )

    workspace_service = WorkspaceContractService(
        analyzer=_workspace_analyzer(settings),
        contract_store=contract_store,
        allowed_roots=[],  # unrestricted: operator already chose the repository being loaded
    )
    code_intelligence_service = CodeIntelligenceContractService(
        engine=CodeIntelligenceEngine(
            registry=LanguageRegistry(
                [
                    PythonLanguageAnalyzer(),
                    TypeScriptLanguageAnalyzer(),
                    GoLanguageAnalyzer(),
                    JavaLanguageAnalyzer(),
                    CSharpLanguageAnalyzer(),
                    KotlinLanguageAnalyzer(),
                ]
            ),
            token_estimator=cost_estimator,
        ),
        contract_store=contract_store,
        resolution_store=InMemoryContextResolutionStore(),
    )
    context_packager = ContextPackager(
        ranker=RelevanceRanker(), token_estimator=cost_estimator, understanding_analyzer=None
    )

    direct_runner = DirectLLMRunner(llm_client=llm_client, cost_estimator=cost_estimator)
    arcf_runner = ArcfRunner(
        contract_manager=build_contract_manager(settings.slm_model),
        workspace_service=workspace_service,
        code_intelligence_service=code_intelligence_service,
        context_packager=context_packager,
        llm_client=llm_client,
        cost_estimator=cost_estimator,
        slm_model=settings.slm_model,
        mode=BenchmarkMode.ARCF,
    )

    arcf_local_runner: ArcfRunner | None = None
    local_slm_unavailable_reason: str | None = None
    try:
        local_model = OllamaProvider(
            base_url=settings.local_slm_base_url,
            candidates=settings.local_slm_candidates,
        ).resolve_model()
    except LocalSLMUnavailableError as exc:
        local_slm_unavailable_reason = str(exc)
        logger.warning("Mode C (arcf_local) unavailable: %s", exc)
    else:
        arcf_local_runner = ArcfRunner(
            contract_manager=build_contract_manager(local_model),
            workspace_service=workspace_service,
            code_intelligence_service=code_intelligence_service,
            context_packager=context_packager,
            llm_client=llm_client,
            cost_estimator=cost_estimator,
            slm_model=local_model,
            mode=BenchmarkMode.ARCF_LOCAL,
        )

    ledger_recorder = LedgerRecorder(
        SqliteExecutionLedgerStore(settings.execution_ledger_db_path)
    )

    controller = BenchmarkController(
        direct_runner=direct_runner,
        arcf_runner=arcf_runner,
        arcf_local_runner=arcf_local_runner,
        analyzer=BenchmarkAnalyzer(),
        ledger_recorder=ledger_recorder,
    )

    return Runtime(
        settings=settings,
        repository_loader=repository_loader,
        controller=controller,
        store=BenchmarkStore(settings.store_path),
        ledger_recorder=ledger_recorder,
        local_slm_unavailable_reason=local_slm_unavailable_reason,
        direct_runner=direct_runner,
        arcf_runner=arcf_runner,
        arcf_local_runner=arcf_local_runner,
    )
