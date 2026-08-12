"""negative_query_fpr_real_consul_check.py -- checklist item #9 real-Consul
verification, no LLM calls. Runs the same negative/adversarial query set
verified absent from real Consul (see this item's own CHECKLIST.md entry
for the grep verification) through the real
CodeIntelligenceContractService.attach_code_intelligence, and reports both
the spec's literal origin-stage-only FPR and the refined (origin_stage +
evidence_tier) FPR -- see tests/code_intelligence/
test_negative_query_false_positive_rate.py's module docstring for why the
refinement exists (a real, measured finding: lexical-probe-recovery can tag
an unrelated real symbol origin_stage=AST_DIRECT while correctly marking it
evidence_tier=SUPPORTING).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from domain.context_resolution import EvidenceTier, OriginStage
from domain.contract import Contract
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator
from infrastructure.telemetry import ConfidenceLabel, TelemetryCollector

REPO_ROOT = Path("C:/Users/VasiganiRohitBabu/Desktop/Claude/.benchmark_repos/consul")
_NON_FALLBACK_STAGES = (OriginStage.AST_DIRECT, OriginStage.SCOPED_GRAPH_EXPANSION)

# Grep-verified absent from real Consul (see this item's CHECKLIST.md entry).
NEGATIVE_QUERIES: list[tuple[str, list[str], str]] = [
    (
        "How does Consul's Agent.SyncExternalDatabase method synchronize with an "
        "external database?",
        ["SyncExternalDatabase"],
        "non_existent_symbol",
    ),
    (
        "Where is ValidateQuantumSignature implemented in Consul's ACL system?",
        ["ValidateQuantumSignature"],
        "non_existent_symbol",
    ),
    (
        "Where is the React frontend rendering pipeline?",
        [],
        "out_of_scope_concept",
    ),
    (
        "How does Consul handle Kubernetes Pod autoscaling directly?",
        ["HorizontalPodAutoscaler"],
        "out_of_scope_concept",
    ),
    (
        "Show implementation of Catalog.QuantumEntangle() used for service mesh synchronization",
        ["QuantumEntangle"],
        "hallucinated_identifier",
    ),
    (
        "Show implementation of RenderVirtualDOM() in the UI layer",
        ["RenderVirtualDOM"],
        "hallucinated_identifier",
    ),
    (
        "Explain how this repository implements the React frontend rendering pipeline.",
        [],
        "out_of_scope_concept_repo_scoped",
    ),
]


def _is_high_confidence_match(resolution) -> bool:
    return any(
        ref.origin_stage in _NON_FALLBACK_STAGES and ref.evidence_tier is EvidenceTier.PRIMARY
        for ref in resolution.candidate_files
    )


async def main() -> None:
    engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )
    collector = TelemetryCollector()

    raw_positives = []
    refined_positives = []
    for raw_request, target_names, category in NEGATIVE_QUERIES:
        intent = UserIntent(
            raw_request=raw_request, intent="diagnose", domain="diagnostic", task="diagnostic",
            entities=[], confidence=0.5,
        )
        living = LivingContract(contract=Contract(intent=intent))
        contract_store.save(living)

        _, resolution = await service.attach_code_intelligence(
            UUID(str(living.contract_id)), target_names=target_names,
            workspace_root=str(REPO_ROOT), resolver_strategy="classic",
        )
        event = collector.record(resolution, resolve_latency_ms=0.0)

        files = [(f.file_path, f.origin_stage, f.evidence_tier) for f in resolution.candidate_files]
        print(f"\n[{category}] {raw_request!r}")
        print(f"  candidate_count={len(resolution.candidate_files)}  label={event.confidence_label.value}")
        if files:
            print(f"  files: {files}")

        if event.confidence_label is ConfidenceLabel.CONFIDENT_MATCH:
            raw_positives.append((raw_request, category))
        if _is_high_confidence_match(resolution):
            refined_positives.append((raw_request, category, files))

    n = len(NEGATIVE_QUERIES)
    raw_fpr = len(raw_positives) / n
    refined_fpr = len(refined_positives) / n
    print(f"\n=== Real Consul negative-query FPR ({n} queries) ===")
    print(f"raw origin-stage-only FPR: {raw_fpr:.3f}  {raw_positives}")
    print(f"refined (origin_stage + evidence_tier PRIMARY) FPR: {refined_fpr:.3f}  {refined_positives}")
    print(f"Gate (<=5%, refined): {'PASS' if refined_fpr <= 0.05 else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
