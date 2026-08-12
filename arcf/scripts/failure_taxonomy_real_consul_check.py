"""failure_taxonomy_real_consul_check.py -- checklist item #14 (arcf/
CHECKLIST.md, Failure Taxonomy) real-Consul verification, no LLM calls,
no source changes. Same discipline as items #4/#9/#10's own check
scripts: check the classifier against real, already-diagnosed failures
before reporting any success gate as passing.

Telemetry Alignment (one of the item's own success gates): reuses item
#4's own BENCHMARK_TASKS ground truth split and
`_structural_behavioral_grounding_metrics` to decide WHICH files are
"failures" to classify (rather than a parallel, disconnected notion of
failure), and records every resolve()/package() pair through a real
`TelemetryCollector` (item #13) so the classifier is shown operating on
the exact same objects telemetry already captures.
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
from infrastructure.telemetry import TelemetryCollector

from failure_taxonomy import FailureCategory, aggregate_failure_distribution, classify_grounding_failure  # noqa: E402
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


async def _run_task(service, contract_store, collector, task):
    query, entities = task["query"], TARGET_NAMES[task["id"]]
    intent = UserIntent(
        raw_request=query, intent="failure-taxonomy-check", domain="code_navigation", task="unknown",
        entities=entities, confidence=1.0,
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)

    import time
    start = time.perf_counter()
    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)), target_names=entities, workspace_root=str(REPO_ROOT),
        resolver_strategy="classic", enable_anchor_classification=True,
        enable_confidence_propagation=True,
    )
    resolve_ms = (time.perf_counter() - start) * 1000

    task_classifier_task = TaskClassifier().classify(query)
    scope = RepositoryScopeClassifier().classify(query)
    task_type = classify_retrieval_task(query, task_classifier_task, scope.task_type)
    profile = RANKING_PROFILES[task_type]

    ranked_files = RelevanceRanker().rank(resolution, profile)

    pkg_start = time.perf_counter()
    packager = ContextPackager(RelevanceRanker(), CostEstimator())
    package, _ = await packager.package(resolution, query, MAX_TOKENS_CONTEXT, profile, task_type=task_type)
    package_ms = (time.perf_counter() - pkg_start) * 1000

    collector.record(
        resolution, resolve_ms, package=package, package_latency_ms=package_ms, classified_task=task_type,
    )

    packaged_files = [f.file_path for f in package.relevant_files]
    return resolution, ranked_files, packaged_files, task_type


async def main() -> None:
    engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(engine, contract_store, InMemoryContextResolutionStore())
    collector = TelemetryCollector()

    all_diagnoses = []
    print(f"{'task':38s} {'file':45s} {'primary':28s} {'secondary':28s}")
    for task in BENCHMARK_TASKS:
        resolution, ranked_files, packaged_files, task_type = await _run_task(
            service, contract_store, collector, task
        )
        metrics = _structural_behavioral_grounding_metrics(
            packaged_files, task["ground_truth_structural"], task["ground_truth_behavioral"]
        )
        # Telemetry Alignment: which files failed comes from item #4's own
        # sub-scores, not a separately invented notion of "failed".
        missing = []
        if metrics["g_struct"] != 1.0:
            missing += [f for f in task["ground_truth_structural"] if f not in packaged_files]
        if metrics["g_behav"] is not None and metrics["g_behav"] != 1.0:
            missing += [f for f in task["ground_truth_behavioral"] if f not in packaged_files]

        for file_path in missing:
            diagnosis = classify_grounding_failure(
                file_path, resolution, ranked_files, packaged_files, MAX_TOKENS_CONTEXT, task_type,
            )
            assert diagnosis is not None, f"{file_path} was in packaged_files, shouldn't be in missing[]"
            all_diagnoses.append(diagnosis)
            sec = diagnosis.secondary.value if diagnosis.secondary else "-"
            print(f"{task['id']:38s} {file_path:45s} {diagnosis.primary.value:28s} {sec:28s}")
            print(f"    detail: {diagnosis.detail}")

    print("\n=== Taxonomy Coverage gate: every real failure classified? ===")
    print(f"  total real failures classified: {len(all_diagnoses)} (0 unclassified by construction)")

    print("\n=== Diagnostic Aggregation Report ===")
    report = aggregate_failure_distribution(all_diagnoses)
    print(report)

    print("\n=== Determinism check: re-run task5's classification twice ===")
    task5 = next(t for t in BENCHMARK_TASKS if t["id"] == "task5_ambiguous_common_name")
    results = []
    for i in range(2):
        collector2 = TelemetryCollector()
        resolution, ranked_files, packaged_files, task_type = await _run_task(
            service, contract_store, collector2, task5
        )
        diag = classify_grounding_failure(
            task5["ground_truth_structural"][0], resolution, ranked_files, packaged_files,
            MAX_TOKENS_CONTEXT, task_type,
        )
        results.append((diag.primary, diag.secondary, diag.detail))
        print(f"  run {i + 1}: primary={diag.primary.value} secondary={diag.secondary}")
    identical = results[0] == results[1]
    print(f"  Gate (Deterministic Categorization, byte-identical repeat): {'PASS' if identical else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
