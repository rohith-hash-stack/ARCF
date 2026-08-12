"""telemetry_overhead_measurement.py -- checklist item #13 success gate
"<2% Latency Overhead", measured not assumed. Real Consul, no LLM calls,
no source changes. Times resolve()+package() with and without a
TelemetryCollector attached, many iterations, same-process (so JIT/cache
warmup affects both arms equally), reports real overhead percentage.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from pathlib import Path

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from context.packager import ContextPackager
from context.relevance_ranker import RelevanceRanker
from infrastructure.cost import CostEstimator
from infrastructure.telemetry import TelemetryCollector
from workspace.scanner import RepositoryScanner

REPO_ROOT = Path("C:/Users/VasiganiRohitBabu/Desktop/Claude/.benchmark_repos/consul")
N_ITERATIONS = 200
QUERY_TARGETS = ["Register"]


async def run_without_telemetry(resolver: ContextResolver, packager: ContextPackager) -> float:
    start = time.perf_counter()
    result = resolver.resolve("ws1", "c1", str(REPO_ROOT), QUERY_TARGETS, traversal_depth=2)
    resolve_end = time.perf_counter()
    package, _ = await packager.package(result, "how does registration work", max_tokens=8000)
    package_end = time.perf_counter()
    return (package_end - start) * 1000


async def run_with_telemetry(
    resolver: ContextResolver, packager: ContextPackager, collector: TelemetryCollector
) -> float:
    start = time.perf_counter()
    result = resolver.resolve("ws1", "c1", str(REPO_ROOT), QUERY_TARGETS, traversal_depth=2)
    resolve_end = time.perf_counter()
    package, _ = await packager.package(result, "how does registration work", max_tokens=8000)
    package_end = time.perf_counter()
    collector.record(
        result,
        resolve_latency_ms=(resolve_end - start) * 1000,
        package=package,
        package_latency_ms=(package_end - resolve_end) * 1000,
    )
    return (package_end - start) * 1000


async def main() -> None:
    engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(REPO_ROOT)
    index = engine.build_index(REPO_ROOT, scan.files)
    resolver = ContextResolver(index)
    packager = ContextPackager(RelevanceRanker(), CostEstimator())

    # Warmup (JIT/cache effects, not measured).
    for _ in range(10):
        await run_without_telemetry(resolver, packager)

    without_ms: list[float] = []
    for _ in range(N_ITERATIONS):
        without_ms.append(await run_without_telemetry(resolver, packager))

    collector = TelemetryCollector()
    with_ms: list[float] = []
    for _ in range(N_ITERATIONS):
        with_ms.append(await run_with_telemetry(resolver, packager, collector))

    mean_without = statistics.mean(without_ms)
    mean_with = statistics.mean(with_ms)
    overhead_pct = (mean_with - mean_without) / mean_without * 100

    print(f"N_ITERATIONS={N_ITERATIONS}")
    print(f"without telemetry: mean={mean_without:.4f}ms  stdev={statistics.stdev(without_ms):.4f}ms")
    print(f"with telemetry:    mean={mean_with:.4f}ms  stdev={statistics.stdev(with_ms):.4f}ms")
    print(f"measured overhead: {overhead_pct:+.3f}%")
    print(f"gate (<2%): {'PASS' if overhead_pct < 2.0 else 'FAIL'}")
    print(f"\ncollector recorded {len(collector.events)} events, "
          f"summary: {collector.get_run_summary()}")


if __name__ == "__main__":
    asyncio.run(main())
