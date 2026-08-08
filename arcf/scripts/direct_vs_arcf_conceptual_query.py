"""Direct LLM vs ARCF Remote LLM — parameterized, repo/query/language
agnostic (2026-08-08). Generalized from the pnpm and containerd one-off
runs into a reusable comparison: real SLM-1 intent extraction, real
Direct LLM generation (query only, no repo context), real ARCF Remote
LLM generation (query + ARCF's actual packaged context, using the final
validated configuration — enable_anchor_classification +
enable_confidence_propagation, the one mechanism shown to be a net win
this session), both on gpt-4o-mini.

Queries must be verbatim from scripts/batch1_diagnostic.py or
scripts/batch2_diagnostic.py's QUERIES dicts — this session's established
discipline, not ad-hoc phrasing.

Usage:
    uv run python scripts/direct_vs_arcf_conceptual_query.py \\
        --repo-path <path> --repo-name <name> --language python|go \\
        --query "<verbatim batch1/2 query text>"
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
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

GENERATION_MODEL = "gpt-4o-mini"
MAX_TOKENS_CONTEXT = 8000
MAX_TOKENS_ANSWER = 1000
RESULTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "session_2026-08-08_data"

_ANALYZERS = {
    "python": PythonLanguageAnalyzer,
    "go": GoLanguageAnalyzer,
}


async def _direct_llm(client: LiteLLMClient, repo_name: str, query: str) -> dict:
    prompt = (
        f"Question about the open-source project {repo_name}: {query}\n\n"
        "Answer from your own knowledge of this project."
    )
    response = await client.complete(prompt, GENERATION_MODEL, MAX_TOKENS_ANSWER)
    return {
        "answer": response.content,
        "prompt_tokens": response.prompt_tokens,
        "completion_tokens": response.completion_tokens,
        "total_tokens": response.total_tokens,
    }


async def _arcf_remote_llm(
    root: Path,
    repo_name: str,
    query: str,
    language: str,
    entities: list[str],
    intent: UserIntent,
    client: LiteLLMClient,
) -> dict:
    analyzer_cls = _ANALYZERS[language]
    engine = CodeIntelligenceEngine(LanguageRegistry([analyzer_cls()]), CostEstimator())
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
        enable_anchor_classification=True,
        enable_confidence_propagation=True,
    )
    resolve_elapsed = asyncio.get_event_loop().time() - start

    scope = RepositoryScopeClassifier().classify(query)
    task_classifier_task = TaskClassifier().classify(query)
    retrieval_task_type = classify_retrieval_task(query, task_classifier_task, scope.task_type)
    ranking_profile = RANKING_PROFILES[retrieval_task_type]
    ranked = RelevanceRanker().rank(resolution, ranking_profile)

    permissions = PermissionManager(root)
    budget_manager = ContextBudgetManager(
        permissions, CostEstimator(), SymbolRangeCompressor(permissions)
    )
    packaged, used_tokens, excluded = budget_manager.select(ranked, resolution, MAX_TOKENS_CONTEXT)

    # PackagedFile.content is already the budget-respecting text
    # ContextBudgetManager decided on (compressed excerpt for files that
    # didn't fit in full) — re-reading raw files from disk here would
    # silently blow past the intended token budget for any file that got
    # compressed, which is exactly the bug found on the first run of this
    # script (SQLAlchemy: reported an 8K budget, actually sent 126K).
    context_blocks = [f"### {f.file_path}\n```\n{f.content}\n```" for f in packaged]
    context_text = "\n\n".join(context_blocks)

    prompt = (
        f"You are answering a question about the {repo_name} codebase using ONLY "
        "the source files provided below as context. Cite specific files/functions "
        "where relevant. If the provided files don't fully answer the question, say "
        "so explicitly rather than filling in from general knowledge.\n\n"
        f"{context_text}\n\n"
        f"Question: {query}"
    )
    gen_start = asyncio.get_event_loop().time()
    response = await client.complete(prompt, GENERATION_MODEL, MAX_TOKENS_ANSWER)
    gen_elapsed = asyncio.get_event_loop().time() - gen_start

    return {
        "answer": response.content,
        "prompt_tokens": response.prompt_tokens,
        "completion_tokens": response.completion_tokens,
        "total_tokens": response.total_tokens,
        "phase5_candidate_count": len(resolution.candidate_files),
        "phase5_tokens": resolution.token_estimate.selected_context_tokens,
        "packaged_file_count": len(packaged),
        "packaged_tokens": used_tokens,
        "excluded_count": excluded,
        "packaged_files": [f.file_path for f in packaged],
        "resolve_latency_seconds": round(resolve_elapsed, 3),
        "generation_latency_seconds": round(gen_elapsed, 3),
        "resolution_reason": resolution.resolution_reason,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--repo-name", required=True)
    parser.add_argument("--language", required=True, choices=sorted(_ANALYZERS.keys()))
    parser.add_argument("--query", required=True)
    args = parser.parse_args()
    root = Path(args.repo_path)

    client = LiteLLMClient(max_retries=3, base_delay_seconds=0.5)

    extractor = IntentExtractor(client, model=GENERATION_MODEL)
    raw, _ = await extractor.extract(args.query)
    entities = list(raw.entities)
    intent = UserIntent(
        raw_request=args.query,
        intent=raw.intent_summary,
        domain=raw.domain,
        task=raw.task,
        entities=entities,
        confidence=raw.self_reported_confidence,
    )
    print(f"[{args.repo_name}] entities_extracted: {entities or '(none)'}")

    direct_result = await _direct_llm(client, args.repo_name, args.query)
    arcf_result = await _arcf_remote_llm(
        root, args.repo_name, args.query, args.language, entities, intent, client
    )

    output = {
        "query": args.query,
        "repo": args.repo_name,
        "language": args.language,
        "direct_llm": direct_result,
        "arcf_remote_llm": arcf_result,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_file = RESULTS_DIR / f"direct_vs_arcf_{args.repo_name}_results.json"
    results_file.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"\n=== [{args.repo_name}] DIRECT LLM ===")
    print(direct_result["answer"])
    print(
        f"\n[tokens: prompt={direct_result['prompt_tokens']} "
        f"completion={direct_result['completion_tokens']}]"
    )

    print(f"\n\n=== [{args.repo_name}] ARCF REMOTE LLM ===")
    print(f"Packaged files: {arcf_result['packaged_files']}")
    print(
        f"Phase5 candidates: {arcf_result['phase5_candidate_count']}, "
        f"packaged: {arcf_result['packaged_file_count']}, tokens: {arcf_result['packaged_tokens']}"
    )
    print(arcf_result["answer"])
    print(
        f"\n[tokens: prompt={arcf_result['prompt_tokens']} "
        f"completion={arcf_result['completion_tokens']}]"
    )
    print(
        f"[latency: resolve={arcf_result['resolve_latency_seconds']}s "
        f"generation={arcf_result['generation_latency_seconds']}s]"
    )
    print(f"\nWritten to {results_file}")


if __name__ == "__main__":
    asyncio.run(main())
