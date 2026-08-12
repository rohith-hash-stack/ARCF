"""primary_priority_floor_ablation.py -- oversized entry-point budget
allocation experiment (recommended follow-on to checklist items #4/
#14, 2026-08-12), real Consul, no LLM calls, same-process ablation
(identical resolution, `enable_primary_priority_floor` on vs. off, one
process) -- the standard this project established after Arm 2's own
two-process-diff confound (arcf_arm2_semantic_reranker_falsified).

Real mechanism traced BEFORE writing `enable_primary_priority_floor`
(`ContextBudgetManager.select()`, `src/context/budget_manager.py`):
task1's real entry point (`agent/consul/catalog_endpoint.go`) clears
the relative score falloff gate (score 0.6309 > threshold 0.36) and its
own compressed excerpt is tiny (46-50 tokens, confirmed via
`SymbolRangeCompressor`, not assumed) -- but it's ranked 20th of 25
survivors, behind 20 SUPPORTING-tier call-graph fan-out files (score
0.72-0.80, each individually small but summing to 4481 of the
4500-token UNKNOWN-tier budget). By the time its turn comes in the
greedy fill loop, only 19 tokens remain -- not enough even for its own
46-50-token compressed excerpt. AST Structural Windowing (the
experiment spec's other proposed mechanism) was NOT built: compression
already produces a tiny excerpt here, so a fancier windowing strategy
would have zero marginal effect on this specific, real, traced case.

task6 was checked BEFORE assuming this fix is safe: it has the OPPOSITE
shape -- its real SUPPORTING answer (`agent/auto-config/tls.go`) is
ranked #1, while its PRIMARY candidates are ranked LAST (rank 7 of 7).
A naive "PRIMARY always first" reorder risks starving tls.go's own
budget -- this is exactly why a same-process ablation across ALL 6
tasks, not just task1, is required before reporting success.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

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

TARGET_NAMES = {
    "task1_targeted_logic": ["Catalog", "Register"],
    "task2_dependency_tracing": ["Cache", "UpdateEvent", "Notify"],
    "task3_interface_type_contract": ["Config"],
    "task4_refactoring_multifile": ["ACLBindingRuleList", "BindingRuleList", "Binder"],
    "task5_ambiguous_common_name": ["New"],
    "task6_path_hint_secondary_sibling": ["Prepopulate"],
}


async def _package(service, contract_store, query, entities, enable_flag: bool):
    intent = UserIntent(
        raw_request=query, intent="ablation", domain="code_navigation", task="unknown",
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
    task_type = classify_retrieval_task(query, task_classifier_task, scope.task_type)
    profile = RANKING_PROFILES[task_type]
    packager = ContextPackager(RelevanceRanker(), CostEstimator())
    package, _ = await packager.package(
        resolution, query, MAX_TOKENS_CONTEXT, profile, task_type=task_type,
        enable_primary_priority_floor=enable_flag,
    )
    return [f.file_path for f in package.relevant_files], package.budget_used_tokens


async def main() -> None:
    engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(engine, contract_store, InMemoryContextResolutionStore())

    print(f"{'task':38s} {'metric':10s} {'OFF':>8s} {'ON':>8s} {'changed':>8s}")
    all_ok = True
    for task in BENCHMARK_TASKS:
        entities = TARGET_NAMES[task["id"]]
        packaged_off, tokens_off = await _package(service, contract_store, task["query"], entities, False)
        packaged_on, tokens_on = await _package(service, contract_store, task["query"], entities, True)

        m_off = _structural_behavioral_grounding_metrics(
            packaged_off, task["ground_truth_structural"], task["ground_truth_behavioral"]
        )
        m_on = _structural_behavioral_grounding_metrics(
            packaged_on, task["ground_truth_structural"], task["ground_truth_behavioral"]
        )
        changed = sorted(packaged_off) != sorted(packaged_on)
        budget_ok = tokens_on <= 8000

        print(f"{task['id']:38s} {'g_struct':10s} {str(m_off['g_struct']):>8s} {str(m_on['g_struct']):>8s} {str(changed):>8s}")
        print(f"{'':38s} {'g_behav':10s} {str(m_off['g_behav']):>8s} {str(m_on['g_behav']):>8s}")
        print(f"{'':38s} tokens_used off={tokens_off} on={tokens_on} (<=8000: {budget_ok})")

        if not budget_ok:
            all_ok = False
            print("  BUDGET ENFORCEMENT GATE FAILED")

    print("\n=== Determinism check: task1 re-run twice with flag on ===")
    task1 = next(t for t in BENCHMARK_TASKS if t["id"] == "task1_targeted_logic")
    r1, t1 = await _package(service, contract_store, task1["query"], TARGET_NAMES[task1["id"]], True)
    r2, t2 = await _package(service, contract_store, task1["query"], TARGET_NAMES[task1["id"]], True)
    identical = sorted(r1) == sorted(r2) and t1 == t2
    print(f"  run1 packaged={len(r1)} tokens={t1}; run2 packaged={len(r2)} tokens={t2}; identical={identical}")


if __name__ == "__main__":
    asyncio.run(main())
