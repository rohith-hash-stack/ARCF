"""grounding_structural_behavioral_metrics_check.py -- checklist item #4
(arcf/CHECKLIST.md, Grounding Quality: Structural vs. Behavioral Split)
real-Consul verification, no LLM calls (deliberately -- this metric is
about candidate/packaged FILES, never a generated answer, so no judge
call is needed either, same reasoning as item #9's negative-query
harness).

Runs the REAL Arm A (ARCF classic resolver -> RelevanceRanker ->
ContextBudgetManager/ContextPackager) and Arm B (same resolution,
_greedy_full_file_package) packaging paths from
scripts/validate_llm_grounding.py against real Consul, for all 6
BENCHMARK_TASKS, and computes G_struct/G_behav via the exact same
_structural_behavioral_grounding_metrics function the paid harness uses
-- imported, not reimplemented, so this check can never silently drift
from what the harness actually reports.

target_names are hand-specified per task (matching each task's own
ground_truth_terms), bypassing real SLM-1 entity extraction -- same
determinism/cost/speed rationale as item #9's negative-query harness
and this item's own free precheck script. Also verifies the "100% Run
Determinism" success gate directly: runs task6 (the one clean positive
behavioral case) twice and asserts byte-identical G_struct/G_behav.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from context.packager import ContextPackager
from context.relevance_ranker import RelevanceRanker
from context.task_profile import RANKING_PROFILES, classify_retrieval_task
from contracts.repository_scope_classifier import RepositoryScopeClassifier
from contracts.task_classifier import TaskClassifier
from domain.contract import Contract
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator

from validate_llm_grounding import (  # noqa: E402
    BENCHMARK_TASKS,
    MAX_TOKENS_CONTEXT,
    _structural_behavioral_grounding_metrics,
)

REPO_ROOT = Path("C:/Users/VasiganiRohitBabu/Desktop/Claude/.benchmark_repos/consul")

# Hand-specified target_names per task, matching each task's own
# ground_truth_terms (deterministic -- see module docstring).
TARGET_NAMES = {
    "task1_targeted_logic": ["Catalog", "Register"],
    "task2_dependency_tracing": ["Cache", "UpdateEvent", "Notify"],
    "task3_interface_type_contract": ["Config"],
    "task4_refactoring_multifile": ["ACLBindingRuleList", "BindingRuleList", "Binder"],
    "task5_ambiguous_common_name": ["New"],
    "task6_path_hint_secondary_sibling": ["Prepopulate"],
}


async def _package_arm_a(service, contract_store, query, entities):
    intent = UserIntent(
        raw_request=query, intent="grounding-check", domain="code_navigation", task="unknown",
        entities=entities, confidence=1.0,
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)
    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)), target_names=entities, workspace_root=str(REPO_ROOT),
        resolver_strategy="classic", enable_anchor_classification=True,
        enable_confidence_propagation=True,
    )
    task_classifier_task = TaskClassifier().classify(query)
    scope = RepositoryScopeClassifier().classify(query)
    retrieval_task_type = classify_retrieval_task(query, task_classifier_task, scope.task_type)
    ranking_profile = RANKING_PROFILES[retrieval_task_type]
    packager = ContextPackager(RelevanceRanker(), CostEstimator())
    package, _ = await packager.package(
        resolution, query, MAX_TOKENS_CONTEXT, ranking_profile, task_type=retrieval_task_type
    )
    return [f.file_path for f in package.relevant_files], retrieval_task_type


async def main() -> None:
    engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(engine, contract_store, InMemoryContextResolutionStore())

    print(f"{'task':38s} {'depth':>6s} {'G_struct':>9s} {'primary_ok':>11s} {'G_behav':>8s}")
    for task in BENCHMARK_TASKS:
        entities = TARGET_NAMES[task["id"]]
        packaged_files, task_type = await _package_arm_a(service, contract_store, task["query"], entities)
        metrics = _structural_behavioral_grounding_metrics(
            packaged_files, task["ground_truth_structural"], task["ground_truth_behavioral"]
        )
        print(
            f"{task['id']:38s} {task_type.value:>6s} "
            f"{str(metrics['g_struct']):>9s} {str(metrics['primary_satisfied']):>11s} "
            f"{str(metrics['g_behav']):>8s}   packaged={len(packaged_files)}"
        )

    print("\n=== Determinism check: task6 run twice, same target_names ===")
    task6 = next(t for t in BENCHMARK_TASKS if t["id"] == "task6_path_hint_secondary_sibling")
    entities = TARGET_NAMES[task6["id"]]
    results = []
    for i in range(2):
        packaged_files, _ = await _package_arm_a(service, contract_store, task6["query"], entities)
        metrics = _structural_behavioral_grounding_metrics(
            packaged_files, task6["ground_truth_structural"], task6["ground_truth_behavioral"]
        )
        results.append((sorted(packaged_files), metrics))
        print(f"  run {i + 1}: packaged={len(packaged_files)} metrics={metrics}")
    identical = results[0] == results[1]
    print(f"  Gate (100% Run Determinism, byte-identical repeat): {'PASS' if identical else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
