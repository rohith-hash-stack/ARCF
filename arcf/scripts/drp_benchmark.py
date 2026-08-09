"""ARCF Issue #3 — Classic vs DRP (Dynamic Repository Profiling), retrieval-only.

Success criteria for this experiment (whether a repository can teach
ARCF its own semantic structure well enough to retrieve the right
runtime subsystem where lexical retrieval fails) are about retrieval
rank/hit, packaging token budget, and latency — not answer quality — so
this script never calls an LLM. That keeps the primary benchmark fast,
free, and reproducible, and matches the Evaluation Framework's
instrumentation list exactly: top subsystem, top community, top-20
files, whether the target file was retrieved, retrieval rank, packaging
token count, resolver latency, graph expansion count, confidence scores.

Classic is benchmarked through its real production entrypoint
(`CodeIntelligenceContractService.attach_code_intelligence`, with
`enable_anchor_classification`/`enable_confidence_propagation` — "the
final validated configuration" per `direct_vs_arcf_conceptual_query.py`)
so it gets its strongest fair baseline, including the lexical-probe/
anchor-classification recovery layers a bare `ContextResolver.resolve()`
call wouldn't exercise. DRP is invoked directly
(`DrpIndexBuilder`/`DrpResolver`) to preserve its own diagnostics
(subsystem/community/expansion-count breakdown) that
`attach_code_intelligence`'s `resolver_strategy="drp"` branch
deliberately discards (see `_resolve_drp`'s own docstring in
service.py) — that branch exists for production reachability, not for
this benchmark's instrumentation needs.

Both resolutions are packaged through the SAME unmodified
RelevanceRanker -> ContextBudgetManager pipeline afterward, so the
packaged-token comparison is apples-to-apples regardless of which
resolver produced the ContextResolutionResult.

`--pmi-expansion` toggles the ARCF Issue #3 PMI query-expansion extension
(code_intelligence/drp/pmi_expansion.py) on the DRP run only — a repo-
local, deterministic word-association graph (no embeddings, no LLM) that
expands ONLY query terms with zero document frequency anywhere in DRP's
own corpus, letting a controlled A/B against the same benchmark answer
whether it actually closes a gap plain DRP can't.

Usage:
    uv run python scripts/drp_benchmark.py \\
        --repo-path <path> --repo-name <name> --language python|go \\
        --query "<query text>" --target-file <path/relative/to/repo.py> \\
        [--target-names name1 name2 ...] [--resolver classic|drp|both] \\
        [--pmi-expansion]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from uuid import UUID

from code_intelligence.drp.diagnostics import compute_retrieval_rank
from code_intelligence.drp.drp_index import DrpIndexBuilder
from code_intelligence.drp.drp_resolver import DrpResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from context.budget_manager import ContextBudgetManager
from context.compressor import SymbolRangeCompressor
from context.relevance_ranker import RelevanceRanker
from context.task_profile import RANKING_PROFILES, classify_retrieval_task
from contracts.repository_scope_classifier import RepositoryScopeClassifier
from contracts.task_classifier import TaskClassifier
from domain.context_package import ContextPackage
from domain.context_resolution import ContextResolutionResult
from domain.contract import Contract
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator
from workspace.permissions import PermissionManager
from workspace.scanner import RepositoryScanner

MAX_TOKENS_CONTEXT = 8000
RESULTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "drp_benchmark_data"

_ANALYZERS = {
    "python": PythonLanguageAnalyzer,
    "go": GoLanguageAnalyzer,
}


def _package(root: Path, query: str, resolution: ContextResolutionResult) -> tuple[int, int]:
    scope = RepositoryScopeClassifier().classify(query)
    task_classifier_task = TaskClassifier().classify(query)
    retrieval_task_type = classify_retrieval_task(query, task_classifier_task, scope.task_type)
    ranking_profile = RANKING_PROFILES[retrieval_task_type]
    ranked = RelevanceRanker().rank(resolution, ranking_profile)

    permissions = PermissionManager(root)
    budget_manager = ContextBudgetManager(
        permissions, CostEstimator(), SymbolRangeCompressor(permissions)
    )
    packaged: list[ContextPackage]
    packaged, used_tokens, _excluded = budget_manager.select(ranked, resolution, MAX_TOKENS_CONTEXT)
    return used_tokens, len(packaged)


async def _run_classic(
    root: Path, repo_name: str, query: str, target_names: list[str], language: str
) -> dict:
    analyzer_cls = _ANALYZERS[language]
    engine = CodeIntelligenceEngine(LanguageRegistry([analyzer_cls()]), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )
    intent = UserIntent(
        raw_request=query,
        intent="drp benchmark",
        domain=repo_name,
        task="repository_understanding",
        entities=target_names,
        confidence=1.0,
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)

    start = time.perf_counter()
    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)),
        target_names=target_names,
        workspace_root=str(root),
        enable_anchor_classification=True,
        enable_confidence_propagation=True,
    )
    elapsed = time.perf_counter() - start

    used_tokens, packaged_count = _package(root, query, resolution)
    files = [f.file_path for f in resolution.candidate_files]
    return {
        "resolver": "classic",
        "top_files": files[:20],
        "candidate_count": len(files),
        "confidence": resolution.confidence,
        "resolver_latency_seconds": round(elapsed, 4),
        "packaged_tokens": used_tokens,
        "packaged_file_count": packaged_count,
        "graph_expansion_count": None,
        "top_subsystem": None,
        "top_community": None,
        "subsystem_scores": None,
    }


def _run_drp(
    root: Path,
    query: str,
    target_names: list[str],
    language: str,
    enable_pmi_expansion: bool = False,
) -> dict:
    analyzer_cls = _ANALYZERS[language]
    engine = CodeIntelligenceEngine(LanguageRegistry([analyzer_cls()]), CostEstimator())
    scan = RepositoryScanner().scan(root)
    index = engine.build_index(root, scan.files)
    drp_index = DrpIndexBuilder.build(index, root, enable_pmi_expansion=enable_pmi_expansion)

    resolution, diagnostics = DrpResolver(index, drp_index).resolve(
        str(root),
        "drp-benchmark",
        str(root),
        query,
        target_names=target_names,
        enable_pmi_expansion=enable_pmi_expansion,
    )

    used_tokens, packaged_count = _package(root, query, resolution)
    files = [f.file_path for f in resolution.candidate_files]
    return {
        "resolver": "drp+pmi" if enable_pmi_expansion else "drp",
        "top_files": files[:20],
        "candidate_count": len(files),
        "confidence": resolution.confidence,
        "resolver_latency_seconds": round(diagnostics.resolver_latency_seconds, 4),
        "packaged_tokens": used_tokens,
        "packaged_file_count": packaged_count,
        "graph_expansion_count": diagnostics.graph_expansion_count,
        "top_subsystem": diagnostics.top_subsystem,
        "top_community": diagnostics.top_community,
        "subsystem_scores": diagnostics.subsystem_scores,
        "query_expansion": diagnostics.query_expansion,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--repo-name", required=True)
    parser.add_argument("--language", required=True, choices=sorted(_ANALYZERS.keys()))
    parser.add_argument("--query", required=True)
    parser.add_argument("--target-file", required=True)
    parser.add_argument("--target-names", nargs="*", default=[])
    parser.add_argument("--resolver", choices=["classic", "drp", "both"], default="both")
    parser.add_argument("--pmi-expansion", action="store_true")
    args = parser.parse_args()
    root = Path(args.repo_path)

    results: dict[str, dict] = {}
    if args.resolver in ("classic", "both"):
        results["classic"] = await _run_classic(
            root, args.repo_name, args.query, args.target_names, args.language
        )
    if args.resolver in ("drp", "both"):
        results["drp"] = _run_drp(
            root, args.query, args.target_names, args.language, args.pmi_expansion
        )

    for result in results.values():
        result["target_file"] = args.target_file
        result["retrieval_rank"] = compute_retrieval_rank(result["top_files"], args.target_file)
        result["target_retrieved"] = result["retrieval_rank"] is not None

    output = {
        "query": args.query,
        "repo": args.repo_name,
        "language": args.language,
        "target_file": args.target_file,
        "results": results,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"drp_vs_classic_{args.repo_name}.json"
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"\n=== DRP vs Classic — {args.repo_name} ===")
    print(f"Query: {args.query}")
    print(f"Target file: {args.target_file}\n")
    for name, result in results.items():
        print(
            f"[{name}] retrieved={result['target_retrieved']} rank={result['retrieval_rank']} "
            f"candidates={result['candidate_count']} confidence={result['confidence']:.2f} "
            f"packaged_tokens={result['packaged_tokens']} "
            f"latency={result['resolver_latency_seconds']}s"
        )
        if name == "drp":
            print(
                f"       top_subsystem={result['top_subsystem']} "
                f"top_community={result['top_community']} "
                f"expansion_count={result['graph_expansion_count']}"
            )
            if result.get("query_expansion"):
                print(f"       query_expansion={result['query_expansion']}")
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
