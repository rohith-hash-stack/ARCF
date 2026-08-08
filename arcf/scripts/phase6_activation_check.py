"""Does activating the already-built, already-deployed Phase 6 (RelevanceRanker
+ ContextBudgetManager) materially reduce the SQLAlchemy candidate set and
preserve canonical-file recall? Answers a direct, factual question about
EXISTING code (no new heuristics, no new signals) rather than proposing
anything new — see docs/ARCF_SESSION_HANDOFF_2026-08-08.md for why this
question came up (Phase 5's attach_code_intelligence() never calls Phase 6;
every prior measurement this session was pre-ranking, pre-budget).

Mirrors the real API route's own recipe exactly
(interfaces/api/routes/context_package.py's create_context_package): classify
the query the same way the route does, pick the matching RANKING_PROFILES
entry, then RelevanceRanker.rank() -> ContextBudgetManager.select() with the
route's own real default max_tokens (schemas.CreateContextPackageRequest,
default=8000).

Usage:
    uv run python scripts/phase6_activation_check.py --repo-path <sqlalchemy>
"""

from __future__ import annotations

import argparse
import asyncio
import json
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


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument(
        "--budgets", nargs="+", type=int, default=[DEFAULT_MAX_TOKENS, 32000, 100000]
    )
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

    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)

    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)), target_names=entities, workspace_root=str(root)
    )
    print(f"Phase 5 (unranked, unbudgeted): {len(resolution.candidate_files)} candidate files, "
          f"{resolution.token_estimate.selected_context_tokens} tokens")

    # Real route's own recipe (context_package.py:103-113): same classification,
    # same RANKING_PROFILES lookup.
    scope = RepositoryScopeClassifier().classify(QUERY)
    task_classifier_task = TaskClassifier().classify(QUERY)
    retrieval_task_type = classify_retrieval_task(QUERY, task_classifier_task, scope.task_type)
    ranking_profile = RANKING_PROFILES[retrieval_task_type]
    print(f"Classified RetrievalTaskType: {retrieval_task_type}")

    ranked = RelevanceRanker().rank(resolution, ranking_profile)

    score_counts: dict[float, int] = {}
    for r in ranked:
        score_counts[r.relevance_score] = score_counts.get(r.relevance_score, 0) + 1
    print(f"Score distribution across all {len(ranked)} ranked files: {sorted(score_counts.items(), reverse=True)}")
    for i, r in enumerate(ranked):
        if r.file_path in CANONICAL_FILES:
            print(f"  rank #{i+1}/{len(ranked)}: {r.file_path} score={r.relevance_score} reason={r.reason!r}")
    print(f"entities_extracted from real SLM-1: {entities}")

    permissions = PermissionManager(root)
    budget_manager = ContextBudgetManager(
        permissions, CostEstimator(), SymbolRangeCompressor(permissions)
    )

    results = {}
    for max_tokens in args.budgets:
        packaged, used_tokens, excluded = budget_manager.select(ranked, resolution, max_tokens)
        packaged_paths = [f.file_path for f in packaged]
        canonical_status = {f: f in packaged_paths for f in CANONICAL_FILES}
        noise_markers = ("dialects/", "testing/", "cache", "test/")
        noise_in_packaged = [
            p for p in packaged_paths if any(m in p for m in noise_markers) and p not in CANONICAL_FILES
        ]
        results[max_tokens] = {
            "packaged_file_count": len(packaged),
            "tokens_used": used_tokens,
            "excluded_count": excluded,
            "canonical_files_retrieved": canonical_status,
            "noise_files_in_packaged": noise_in_packaged,
            "packaged_files_ranked_order": [
                {
                    "file": f.file_path,
                    "reason": f.reason,
                    "score": f.relevance_score,
                    "truncated": f.truncated,
                }
                for f in packaged[:15]
            ],
        }
        print(f"\n=== max_tokens={max_tokens} ===")
        print(json.dumps(results[max_tokens], indent=2))

    out_path = (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "session_2026-08-08_data"
        / "phase6_activation_check_results.json"
    )
    out_path.write_text(
        json.dumps(
            {
                "query": QUERY,
                "phase5_unranked_candidate_count": len(resolution.candidate_files),
                "phase5_unranked_tokens": resolution.token_estimate.selected_context_tokens,
                "retrieval_task_type": str(retrieval_task_type),
                "by_budget": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
