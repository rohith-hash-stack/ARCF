"""Batch 1 diagnostic runner (classifier-gap investigation, 2026-08-06 handoff).

Cheap, no-final-LLM-call testing of the retrieval pipeline: real SLM-1 intent
extraction (small, real cost) + the deterministic Phase 5/6 pipeline via
CodeIntelligenceContractService, exactly as production code does. Never calls
a "final generation" LLM, so this never sends a whole repository as context —
unlike the benchmark UI's "Run Benchmark" flow, which is what makes it safe to
run many queries across many repos without real financial risk.

Usage (one repo at a time, per the user's explicit request — clone, test,
delete, move to next):

    uv run python scripts/batch1_diagnostic.py --repo-key kubernetes --repo-path <path>

Appends one row per query to docs/BATCH1_RESULTS.md (created if missing).
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.csharp_analyzer import CSharpLanguageAnalyzer
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.languages.java_analyzer import JavaLanguageAnalyzer
from code_intelligence.languages.kotlin_analyzer import KotlinLanguageAnalyzer
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.languages.typescript_analyzer import TypeScriptLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from contracts.intent_extraction import IntentExtractor
from domain.contract import Contract
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator
from infrastructure.llm_client import LiteLLMClient

RESULTS_FILE = Path(__file__).resolve().parent.parent / "docs" / "BATCH1_RESULTS.md"

# repo_key -> list of task prompts, transcribed verbatim from the user's Batch 1.
QUERIES: dict[str, list[str]] = {
    "kubernetes": [
        "Explain how the scheduler decides which node a Pod is placed on. Trace the execution path starting from a newly created Pod until it is bound to a node.",
        "A recently introduced scheduler plugin appears to increase scheduling latency. Identify likely bottlenecks and propose optimizations without changing scheduling semantics.",
    ],
    "react": [
        "Explain how the Fiber reconciler performs work scheduling differently from the legacy stack reconciler. Include the role of lanes.",
        "Refactor a reconciliation helper to improve readability while preserving behavior. Highlight why each change is safe.",
    ],
    "nextjs": [
        "Explain how App Router streaming with React Server Components works from the initial request until hydration.",
        "Add a new middleware option that logs response timing only in development mode while avoiding production overhead.",
    ],
    "vscode": [
        "Trace what happens internally when a user opens a file from the Explorer until syntax highlighting appears.",
        "A regression causes extensions to activate more slowly after startup. Suggest a debugging strategy and likely sources of overhead.",
    ],
    "pytorch": [
        "Explain how autograd constructs the backward graph for tensor operations. Use a simple matrix multiplication example.",
        "Implement a new tensor operation with CPU and CUDA kernels and integrate it into autograd. Outline all files that would need changes.",
    ],
    "tensorflow": [
        "Explain the execution flow difference between eager execution and graph execution.",
        "A custom operation leaks GPU memory during repeated execution. Describe how you would isolate the issue.",
    ],
    "fastapi": [
        "Explain how dependency injection works internally and how request-scoped dependencies are resolved.",
        "Add support for a custom dependency cache invalidation strategy without breaking existing behavior.",
    ],
    "django": [
        "Trace how an incoming HTTP request becomes a rendered template response. Include middleware execution order.",
        "Refactor a queryset optimization that currently causes duplicated SQL generation while keeping API compatibility.",
    ],
    "flask": [
        "Explain how request and application contexts are implemented using context locals.",
    ],
    "sqlalchemy": [
        "Explain how lazy loading differs from eager loading internally and what SQL each strategy generates.",
        "Debug an N+1 query issue introduced by a recent ORM refactor.",
    ],
    "redis": [
        "Explain the lifecycle of a SET command from client connection through persistence.",
        "Implement a new INFO metric for tracking expired key cleanup efficiency.",
    ],
    "postgres": [
        "Explain how MVCC prevents readers from blocking writers. Trace tuple visibility decisions.",
        "Investigate why VACUUM performance regressed after a recent patch.",
    ],
    "llvm": [
        "Explain how an LLVM optimization pass transforms intermediate representation before code generation.",
        "Add a simple optimization pass that removes redundant arithmetic expressions.",
    ],
    "linux": [
        "Explain the lifecycle of a system call from user space into kernel space and back.",
        "Debug a kernel panic occurring only when CONFIG_PREEMPT is enabled.",
    ],
    "rust": [
        "Explain how the borrow checker determines whether mutable and immutable borrows are valid.",
        "Add a new compiler diagnostic suggesting a fix for a common lifetime error.",
    ],
    "go": [
        "Explain how goroutine scheduling interacts with OS threads and the work-stealing scheduler.",
        "Investigate a scheduler regression causing excessive thread creation under high concurrency.",
    ],
    "cpython": [
        "Explain how Python's garbage collector complements reference counting.",
        "Implement a new built-in function and describe every subsystem that needs updating.",
    ],
    "node": [
        "Explain the interaction between libuv, the event loop, and JavaScript execution.",
        "Debug a performance regression affecting Promise-heavy workloads.",
    ],
    "nginx": [
        "Explain how an HTTP request moves through the Nginx request processing phases.",
        "Implement a custom response header module while minimizing request overhead.",
    ],
    "duckdb": [
        "Explain how vectorized query execution improves analytical query performance.",
        "Optimize a hash aggregation implementation that regressed in recent benchmarks.",
    ],
    "clickhouse": [
        "Explain how MergeTree organizes data on disk and why it improves analytical workloads.",
    ],
    "spark": [
        "Trace a DataFrame query from Catalyst optimization through physical execution.",
    ],
    "ray": [
        "Explain how distributed task scheduling works and how object references are managed across nodes.",
    ],
    "langchain": [
        "Refactor the tool invocation pipeline to reduce duplicated callback handling logic while preserving public APIs.",
    ],
    "vllm": [
        "Explain how PagedAttention reduces KV cache fragmentation compared to naive allocation.",
    ],
    "ollama": [
        "Add support for reporting per-request token generation latency in the API responses.",
    ],
    "transformers": [
        "Explain how AutoModel resolves configuration classes into concrete model implementations.",
    ],
    "airflow": [
        "Explain the scheduler's DAG parsing workflow and identify opportunities to reduce startup latency.",
    ],
    "home-assistant": [
        "Debug a race condition that occurs when multiple integrations update the same entity simultaneously.",
    ],
    "opentelemetry-collector": [
        "Add a processor that records per-pipeline processing latency without changing existing exporters.",
    ],
    "grafana": [
        "Explain how dashboard queries flow from the frontend through backend data sources and back to visualization.",
    ],
    "prometheus": [
        "Explain how PromQL expressions are parsed and evaluated during query execution.",
    ],
    "elasticsearch": [
        "Trace an indexing request from REST API reception through shard assignment and segment creation.",
    ],
    "kafka": [
        "Explain how consumer group rebalancing works and why incremental cooperative rebalancing reduces disruption.",
    ],
    "superset": [
        "Refactor dashboard filter synchronization logic to improve maintainability while keeping existing behavior unchanged.",
    ],
}


def _full_registry() -> LanguageRegistry:
    return LanguageRegistry(
        [
            PythonLanguageAnalyzer(),
            TypeScriptLanguageAnalyzer(),
            JavaLanguageAnalyzer(),
            GoLanguageAnalyzer(),
            CSharpLanguageAnalyzer(),
            KotlinLanguageAnalyzer(),
        ]
    )


@dataclass(frozen=True)
class QueryResult:
    repo: str
    prompt: str
    files_scanned: int
    files_analyzed: int
    candidate_files: int
    languages_detected: tuple[str, ...]
    languages_unsupported: tuple[str, ...]
    repository_scope: bool
    scope_task_type: str
    evidence_satisfied: tuple[str, ...]
    evidence_missing: tuple[str, ...]
    entities_extracted: tuple[str, ...]
    resolution_reason: str


async def _run_one(root: Path, repo_key: str, prompt: str) -> QueryResult:
    engine = CodeIntelligenceEngine(_full_registry(), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )

    # Real SLM-1 call — small, cheap, extracts entities the same way production
    # contract creation does. This is the only real LLM cost this script incurs.
    extractor = IntentExtractor(
        LiteLLMClient(max_retries=3, base_delay_seconds=0.5), model="gpt-4o-mini"
    )
    raw, _llm_response = await extractor.extract(prompt)
    entities = tuple(raw.entities)

    intent = UserIntent(
        raw_request=prompt,
        intent=raw.intent_summary,
        domain=raw.domain,
        task=raw.task,
        entities=list(entities),
        confidence=raw.self_reported_confidence,
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)

    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)), target_names=list(entities), workspace_root=str(root)
    )

    from contracts.evidence_contract import detect_task_type_for_evidence
    from contracts.repository_scope_classifier import RepositoryScopeClassifier

    scope = RepositoryScopeClassifier().classify(prompt)
    evidence_type = detect_task_type_for_evidence(prompt) or scope.task_type

    return QueryResult(
        repo=repo_key,
        prompt=prompt,
        files_scanned=resolution.files_scanned,
        files_analyzed=resolution.files_analyzed,
        candidate_files=len(resolution.candidate_files),
        languages_detected=resolution.languages_detected,
        languages_unsupported=resolution.languages_unsupported,
        repository_scope=scope.repository_scope,
        scope_task_type=scope.task_type,
        evidence_satisfied=resolution.evidence_categories_satisfied,
        evidence_missing=resolution.evidence_categories_missing,
        entities_extracted=entities,
        resolution_reason=resolution.resolution_reason,
    )


def _append_results(results: list[QueryResult]) -> None:
    is_new = not RESULTS_FILE.exists()
    with RESULTS_FILE.open("a", encoding="utf-8") as f:
        if is_new:
            f.write("# Batch 1 Results\n\n")
            f.write(
                "| Repo | Prompt (60ch) | Files scanned | Analyzed | Candidates | "
                "Languages detected | Unsupported | Entities | Reason |\n"
            )
            f.write("|---|---|---|---|---|---|---|---|---|\n")
        for r in results:
            f.write(
                f"| {r.repo} | {r.prompt[:60].replace(chr(10), ' ')}... | "
                f"{r.files_scanned} | {r.files_analyzed} | {r.candidate_files} | "
                f"{', '.join(r.languages_detected) or '-'} | "
                f"{', '.join(r.languages_unsupported) or '-'} | "
                f"{', '.join(r.entities_extracted) or '(none)'} | "
                f"{r.resolution_reason[:120].replace(chr(10), ' ')} |\n"
            )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-key", required=True, choices=sorted(QUERIES.keys()))
    parser.add_argument("--repo-path", required=True)
    args = parser.parse_args()

    root = Path(args.repo_path)
    prompts = QUERIES[args.repo_key]
    results = []
    for prompt in prompts:
        result = await _run_one(root, args.repo_key, prompt)
        results.append(result)
        print(f"[{args.repo_key}] candidates={result.candidate_files} "
              f"scanned={result.files_scanned} analyzed={result.files_analyzed} "
              f"unsupported={result.languages_unsupported} entities={result.entities_extracted}")
        print(f"  reason: {result.resolution_reason}")

    _append_results(results)
    print(f"Appended {len(results)} row(s) to {RESULTS_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
