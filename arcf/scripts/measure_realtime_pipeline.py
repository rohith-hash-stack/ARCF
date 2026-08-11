"""measure_realtime_pipeline.py — standalone before/after measurement for
the Real-Time Token & Latency Optimization work (2026-08-11): Feature A
(Tier-1 structural ambiguity decay), Feature B (relative score falloff
gate), Feature C (AST enclosing scope slicing).

Runs the real, unmodified resolution + packaging pipeline (ContextResolver
-> RelevanceRanker -> ContextBudgetManager, via ContextPackager — no LLM
call, no contract/SLM-1 layer) against a real Consul clone, for three
target names spanning the ambiguity spectrum: "New" (extreme, N=156),
"Register" (moderate, N~3-38 depending on kind-filtering — see
arcf_callgraph_locality_fix memory), "Agent" (control, low ambiguity).

Metrics printed per query, matching the task spec:
  1. Total Prompt Payload Tokens -- ContextPackage.budget_used_tokens
     (what's actually sent, capped at max_tokens).
  2. Total Candidate File Count -- both the raw resolution count
     (result.candidate_files, uncapped) and the packaged count actually
     sent (len(package.relevant_files), budget-capped) -- reported
     separately since they answer different questions ("how much noise
     did resolution find" vs. "how much of it survived packaging").
  3. Execution Latency (ms) -- wall-clock split into resolve() and
     package() phases plus a total, measured with time.perf_counter().
  4. Test suite status is NOT this script's job -- run pytest separately.

Not a pytest test: prints a human-readable report, meant to be re-run by
hand before/after each feature lands on
experiment/realtime-token-latency-optimization, exactly as the task's
own "Execution Steps" describe.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.index import CodeIntelligenceIndex
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from context.packager import ContextPackager
from context.relevance_ranker import RelevanceRanker
from context.task_profile import RetrievalTaskType
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner

SCRATCH_B = Path(
    "C:/Users/VASIGA~1/AppData/Local/Temp/claude/C--Users-VasiganiRohitBabu-Desktop-Claude/"
    "9e0bfde9-a14d-4265-b142-a579ae3668d3/scratchpad/pmi_repos"
)
MAX_TOKENS_CONTEXT = 8000
TARGET_NAMES = ["New", "Register", "Agent"]


def _build_index(root: Path) -> CodeIntelligenceIndex:
    engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(root)
    return engine.build_index(root, scan.files)


async def _measure_one(index: CodeIntelligenceIndex, root: Path, name: str) -> dict:
    resolver = ContextResolver(index)

    t0 = time.perf_counter()
    result = resolver.resolve("ws1", "contract1", str(root), [name])
    t1 = time.perf_counter()

    packager = ContextPackager(RelevanceRanker(), CostEstimator())
    # Feature 3 (intent-based dynamic budget ceilings): these are bare
    # single-word probes, not real natural-language queries -- genuinely
    # un-classifiable by task_profile's own keyword heuristics, so
    # UNKNOWN (the task spec's own explicit safety fallback, 2500
    # tokens) is the honest choice here, not a guess.
    package, _ = await packager.package(
        result,
        raw_request=f"(measurement probe for {name!r})",
        max_tokens=MAX_TOKENS_CONTEXT,
        task_type=RetrievalTaskType.UNKNOWN,
    )
    t2 = time.perf_counter()

    return {
        "name": name,
        "raw_candidate_files": len(result.candidate_files),
        "packaged_files": len(package.relevant_files),
        "excluded_files": package.excluded_file_count,
        "payload_tokens": package.budget_used_tokens,
        "confidence": result.confidence,
        "resolve_ms": round((t1 - t0) * 1000, 2),
        "package_ms": round((t2 - t1) * 1000, 2),
        "total_ms": round((t2 - t0) * 1000, 2),
    }


async def main() -> None:
    root = SCRATCH_B / "consul"
    index = _build_index(root)

    print(f"{'name':<10} {'raw_files':>10} {'packaged':>9} {'excluded':>9} "
          f"{'tokens':>8} {'conf':>6} {'resolve_ms':>11} {'package_ms':>11} {'total_ms':>9}")
    for name in TARGET_NAMES:
        row = await _measure_one(index, root, name)
        print(
            f"{row['name']:<10} {row['raw_candidate_files']:>10} {row['packaged_files']:>9} "
            f"{row['excluded_files']:>9} {row['payload_tokens']:>8} {row['confidence']:>6.3f} "
            f"{row['resolve_ms']:>11} {row['package_ms']:>11} {row['total_ms']:>9}"
        )


if __name__ == "__main__":
    asyncio.run(main())
