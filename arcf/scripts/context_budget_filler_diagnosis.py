"""context_budget_filler_diagnosis.py — falsification experiment,
resolver-only, no LLM calls, read-only against ARCF's real production
classes (CodeIntelligenceContractService, ContextPackager). Never writes
to docs/repo_query_answers/ or touches any src/ file.

Hypothesis (from arcf-repo-sweep-50's cost investigation): when a
repository-scoped query's symbol-based resolution finds nothing (empty
candidate_files), `context/evidence_fallback.py`'s evidence-contract
tier fills in generic per-task-type filler (README/CI-workflow/build-
manifest files, EvidenceTier.SUPPORTING with no symbol location to
compress around) — and `ContextBudgetManager.select()` only compresses
SUPPORTING files that HAVE a symbol location (`compress_first_tiers`
check is gated on `symbols_in_file` being non-empty), so this filler
gets packaged as FULL, uncompressed files. If true, a meaningful
fraction of `packaged_tokens` in queries with empty
`entities_extracted` (already known to be the low-grounding-value case
per SWEEP_REPORT.md) is generic filler, not query-specific content —
real slack, safely trimmable without touching PRIMARY (query-matched)
content or SUPPORTING-with-symbol content that already gets compressed.

Success criterion (stated up front, not adjusted after seeing results):
filler (`reason` starts with "evidence: " or is
"references: lexical-match"/"evidence: repository tree") must account
for >=30% of packaged_tokens in at least half of the queries whose
stored entities_extracted was empty, for the hypothesis to be worth
acting on. A lower/patchier number means the "12-15x direct" cost gap
is NOT meaningfully explained by trimmable filler and no fix should be
built on this basis.

Reuses the SAME (repo, query, entities_extracted) as the real sweep run
(docs/repo_query_answers/*.json) instead of re-calling SLM-1 intent
extraction, keeping this 100% free/deterministic.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.cpp_analyzer import CppLanguageAnalyzer
from code_intelligence.languages.csharp_analyzer import CSharpLanguageAnalyzer
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.languages.java_analyzer import JavaLanguageAnalyzer
from code_intelligence.languages.kotlin_analyzer import KotlinLanguageAnalyzer
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.languages.rust_analyzer import RustLanguageAnalyzer
from code_intelligence.languages.typescript_analyzer import TypeScriptLanguageAnalyzer
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

MAX_TOKENS_CONTEXT = 8000
SCRATCH_REPOS = Path(
    "C:/Users/VASIGA~1/AppData/Local/Temp/claude/"
    "C--Users-VasiganiRohitBabu-Desktop-Claude/"
    "9e0bfde9-a14d-4265-b142-a579ae3668d3/scratchpad/repos"
)
SWEEP_DIR = Path(__file__).resolve().parent.parent / "docs" / "repo_query_answers"

_FILLER_REASON_PREFIXES = ("evidence: ",)
_FILLER_EXACT_REASONS = {"references: lexical-match"}


def _is_filler(reason: str) -> bool:
    if reason in _FILLER_EXACT_REASONS:
        return True
    return any(reason.startswith(p) for p in _FILLER_REASON_PREFIXES)


def _full_registry() -> LanguageRegistry:
    return LanguageRegistry(
        [
            PythonLanguageAnalyzer(),
            TypeScriptLanguageAnalyzer(),
            GoLanguageAnalyzer(),
            JavaLanguageAnalyzer(),
            CSharpLanguageAnalyzer(),
            KotlinLanguageAnalyzer(),
            CppLanguageAnalyzer(),
            RustLanguageAnalyzer(),
        ]
    )


async def _diagnose_one(
    service: CodeIntelligenceContractService,
    contract_store: InMemoryContractStore,
    index_cache: dict,
    root: Path,
    query: str,
    entities: list[str],
) -> dict:
    intent = UserIntent(
        raw_request=query,
        intent="diagnose",
        domain="diagnostic",
        task="diagnostic",
        entities=entities,
        confidence=0.5,
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)

    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)),
        target_names=entities,
        workspace_root=str(root),
        resolver_strategy="classic",
        enable_anchor_classification=True,
        enable_confidence_propagation=True,
        index_cache=index_cache,
    )

    scope = RepositoryScopeClassifier().classify(query)
    task_classifier_task = TaskClassifier().classify(query)
    retrieval_task_type = classify_retrieval_task(query, task_classifier_task, scope.task_type)
    ranking_profile = RANKING_PROFILES[retrieval_task_type]

    packager = ContextPackager(RelevanceRanker(), CostEstimator())
    package, _ = await packager.package(resolution, query, MAX_TOKENS_CONTEXT, ranking_profile)

    filler_tokens = sum(f.token_count for f in package.relevant_files if _is_filler(f.reason))
    total_tokens = package.budget_used_tokens
    filler_files = [
        (f.file_path, f.reason, f.token_count) for f in package.relevant_files if _is_filler(f.reason)
    ]
    real_files = [
        (f.file_path, f.reason, f.token_count)
        for f in package.relevant_files
        if not _is_filler(f.reason)
    ]

    return {
        "query": query,
        "entities": entities,
        "total_tokens": total_tokens,
        "filler_tokens": filler_tokens,
        "filler_fraction": round(filler_tokens / total_tokens, 3) if total_tokens else 0.0,
        "filler_files": filler_files,
        "real_files": real_files,
    }


async def main() -> None:
    repos = {
        "googletest": SCRATCH_REPOS / "googletest",
        "flatbuffers": SCRATCH_REPOS / "flatbuffers",
        "gvisor": SCRATCH_REPOS / "gvisor",
    }

    stored_queries: list[tuple[str, str, list[str]]] = []
    for f in sorted(SWEEP_DIR.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        stored_queries.append((d["repo"], d["query"], d["entities_extracted"]))

    engine = CodeIntelligenceEngine(_full_registry(), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )
    index_cache: dict = {}

    results = []
    for repo_name, query, entities in stored_queries:
        root = repos[repo_name]
        if not root.is_dir():
            print(f"SKIP {repo_name}: not cloned at {root}")
            continue
        r = await _diagnose_one(service, contract_store, index_cache, root, query, entities)
        r["repo"] = repo_name
        results.append(r)
        print(
            f"{repo_name:12s} entities={entities!r:35s} "
            f"total={r['total_tokens']:5d} filler={r['filler_tokens']:5d} "
            f"({r['filler_fraction']:.0%})  query={query[:55]!r}"
        )

    empty_entity_results = [r for r in results if not r["entities"]]
    over_30pct = [r for r in empty_entity_results if r["filler_fraction"] >= 0.30]
    print()
    print(
        f"Empty-entity queries: {len(empty_entity_results)}, "
        f">=30% filler: {len(over_30pct)} "
        f"({len(over_30pct) / len(empty_entity_results):.0%} if any)"
        if empty_entity_results
        else "No empty-entity queries found."
    )
    print()
    print("Filler file breakdown (empty-entity queries only):")
    for r in empty_entity_results:
        print(f"\n--- {r['repo']} | {r['query'][:60]} (total={r['total_tokens']}, filler_frac={r['filler_fraction']:.0%}) ---")
        for path, reason, tokens in r["filler_files"]:
            print(f"    FILLER {tokens:5d}t  [{reason}]  {path}")
        for path, reason, tokens in r["real_files"]:
            print(f"    real   {tokens:5d}t  [{reason}]  {path}")

    out_path = SWEEP_DIR.parent / "drp_benchmark_data" / "context_budget_filler_diagnosis.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWritten to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
