"""ARCF Pre-Expansion Anchor Classification experiment — SQLAlchemy
validation (2026-08-08), before committing to the full 5-repo x 3-mode
protocol. Runs Phase 5 (attach_code_intelligence) AND Phase 6
(RelevanceRanker + ContextBudgetManager) for both arms — see
phase6_activation_check.py's own finding: Phase 5 candidate counts alone
don't tell you what actually reaches the LLM, and the real production
route always runs both.

Two arms:
  baseline    — both new flags off, today's shipped behavior.
  anchor      — enable_anchor_classification=True,
                enable_confidence_propagation=True.

Retrieval-only: no final generation LLM call (matches this session's
established cost discipline). Real SLM-1 intent-extraction call, small
and shared identically by both arms.

Usage:
    uv run python scripts/anchor_classification_experiment.py --repo-path <sqlalchemy>
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
from context.relevance_ranker import RelevanceRanker
from context.task_profile import RANKING_PROFILES, classify_retrieval_task
from contracts.intent_extraction import IntentExtractor
from contracts.repository_scope_classifier import RepositoryScopeClassifier
from contracts.task_classifier import TaskClassifier
from domain.context_resolution import ContextResolutionResult
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
    / "anchor_classification_experiment_results.json"
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
    enable_anchor_classification: bool,
    enable_confidence_propagation: bool,
    max_tokens: int,
) -> ArmResult:
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)

    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)),
        target_names=entities,
        workspace_root=str(root),
        enable_anchor_classification=enable_anchor_classification,
        enable_confidence_propagation=enable_confidence_propagation,
    )

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
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    args = parser.parse_args()
    root = Path(args.repo_path)

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

    baseline = await _run_arm(root, entities, intent, "baseline (flags off)", False, False, args.max_tokens)
    anchor = await _run_arm(
        root, entities, intent, "anchor classification + confidence propagation", True, True, args.max_tokens
    )

    output = {
        "query": QUERY,
        "entities_extracted": entities,
        "max_tokens": args.max_tokens,
        "canonical_files": list(CANONICAL_FILES),
        "baseline": asdict(baseline),
        "anchor_classification": asdict(anchor),
    }
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_FILE.write_text(json.dumps(output, indent=2), encoding="utf-8")

    for arm in (baseline, anchor):
        print(f"\n=== {arm.label} ===")
        print(json.dumps(asdict(arm), indent=2))
    print(f"\nWritten to {RESULTS_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
