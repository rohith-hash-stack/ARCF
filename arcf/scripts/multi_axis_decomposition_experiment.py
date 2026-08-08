"""ARCF Multi-Axis Query Decomposition experiment — SQLAlchemy validation
(2026-08-08). Isolated from the subsystem-localization / ranked-probe /
anchor-classification experiments by construction — only
`enable_multi_axis_decomposition` is set, everything else stays at its
default (False).

Two arms, both run through Phase 5 (attach_code_intelligence) AND Phase 6
(RelevanceRanker + ContextBudgetManager) — see phase6_activation_check.py's
own finding that Phase 5 candidate counts alone don't reflect what
actually reaches the LLM:
  baseline    — every flag off, today's shipped behavior.
  multi_axis  — enable_multi_axis_decomposition=True only.

Retrieval-only: no final generation LLM call in this pass (real SLM-1
intent-extraction call only, small and shared identically by both arms).

Usage:
    uv run python scripts/multi_axis_decomposition_experiment.py --repo-path <sqlalchemy>
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import UUID

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from context.budget_manager import ContextBudgetManager
from context.compressor import SymbolRangeCompressor
from context.query_decomposition import decompose_query
from context.relevance_ranker import RelevanceRanker
from context.task_profile import RANKING_PROFILES, classify_retrieval_task
from contracts.intent_extraction import IntentExtractor
from contracts.repository_scope_classifier import RepositoryScopeClassifier
from contracts.task_classifier import TaskClassifier
from domain.contract import Contract
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator
from infrastructure.llm_client import LiteLLMClient
from workspace.permissions import PermissionManager

QUERY = (
    "Explain how lazy loading differs from eager loading internally and "
    "what SQL each strategy generates."
)
CANONICAL_FILES = ("lib/sqlalchemy/orm/loading.py", "lib/sqlalchemy/orm/strategies.py")
DEFAULT_MAX_TOKENS = 8000  # real API default, schemas.CreateContextPackageRequest
RESULTS_FILE = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "session_2026-08-08_data"
    / "multi_axis_decomposition_experiment_results.json"
)


@dataclass(frozen=True)
class ArmResult:
    label: str
    phase5_candidate_count: int
    phase5_tokens: int
    packaged_file_count: int
    packaged_tokens: int
    excluded_count: int
    canonical_rank: dict[str, int | None]
    canonical_score: dict[str, float | None]
    canonical_origin: dict[str, str | None]
    canonical_packaged: dict[str, bool]
    resolution_reason: str
    total_latency_seconds: float = 0.0


def _rank_lookup(ranked: list, canonical_files: tuple[str, ...]) -> tuple[dict, dict]:
    rank_by_file: dict[str, int | None] = dict.fromkeys(canonical_files)
    score_by_file: dict[str, float | None] = dict.fromkeys(canonical_files)
    for i, r in enumerate(ranked):
        if r.file_path in canonical_files:
            rank_by_file[r.file_path] = i + 1
            score_by_file[r.file_path] = r.relevance_score
    return rank_by_file, score_by_file


async def _run_arm(
    root: Path,
    entities: list[str],
    intent: UserIntent,
    label: str,
    enable_multi_axis_decomposition: bool,
    max_tokens: int,
) -> ArmResult:
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)

    start = asyncio.get_event_loop().time()
    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)),
        target_names=entities,
        workspace_root=str(root),
        enable_multi_axis_decomposition=enable_multi_axis_decomposition,
    )
    elapsed = asyncio.get_event_loop().time() - start

    scope = RepositoryScopeClassifier().classify(QUERY)
    task_classifier_task = TaskClassifier().classify(QUERY)
    retrieval_task_type = classify_retrieval_task(QUERY, task_classifier_task, scope.task_type)
    ranking_profile = RANKING_PROFILES[retrieval_task_type]

    ranked = RelevanceRanker().rank(resolution, ranking_profile)
    canonical_rank, canonical_score = _rank_lookup(ranked, CANONICAL_FILES)
    canonical_origin = {
        f: next((r.reason for r in ranked if r.file_path == f), None) for f in CANONICAL_FILES
    }

    permissions = PermissionManager(root)
    budget_manager = ContextBudgetManager(
        permissions, CostEstimator(), SymbolRangeCompressor(permissions)
    )
    packaged, used_tokens, excluded = budget_manager.select(ranked, resolution, max_tokens)
    packaged_paths = {f.file_path for f in packaged}
    canonical_packaged = {f: f in packaged_paths for f in CANONICAL_FILES}

    print(f"[{label}] resolved in {elapsed:.2f}s")
    return ArmResult(
        label=label,
        phase5_candidate_count=len(resolution.candidate_files),
        phase5_tokens=resolution.token_estimate.selected_context_tokens,
        packaged_file_count=len(packaged),
        packaged_tokens=used_tokens,
        excluded_count=excluded,
        canonical_rank=canonical_rank,
        canonical_score=canonical_score,
        canonical_origin=canonical_origin,
        canonical_packaged=canonical_packaged,
        resolution_reason=resolution.resolution_reason,
        total_latency_seconds=round(elapsed, 3),
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    args = parser.parse_args()
    root = Path(args.repo_path)

    axes = decompose_query(QUERY)
    print(f"Decomposition: {[a.text for a in axes]}")

    extractor = IntentExtractor(
        LiteLLMClient(max_retries=3, base_delay_seconds=0.5), model="gpt-4o-mini"
    )
    raw, _ = await extractor.extract(QUERY)
    entities = list(raw.entities)
    intent = UserIntent(
        raw_request=QUERY,
        intent=raw.intent_summary,
        domain=raw.domain,
        task=raw.task,
        entities=entities,
        confidence=raw.self_reported_confidence,
    )
    print(f"entities_extracted: {entities or '(none)'}")

    baseline = await _run_arm(root, entities, intent, "baseline (flags off)", False, args.max_tokens)
    multi_axis = await _run_arm(
        root, entities, intent, "multi-axis decomposition", True, args.max_tokens
    )

    output = {
        "query": QUERY,
        "axes": [a.text for a in axes],
        "entities_extracted": entities,
        "max_tokens": args.max_tokens,
        "canonical_files": list(CANONICAL_FILES),
        "baseline": asdict(baseline),
        "multi_axis": asdict(multi_axis),
    }
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(output, indent=2), encoding="utf-8")

    for arm in (baseline, multi_axis):
        print(f"\n=== {arm.label} ===")
        print(json.dumps(asdict(arm), indent=2))
    print(f"\nWritten to {RESULTS_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
