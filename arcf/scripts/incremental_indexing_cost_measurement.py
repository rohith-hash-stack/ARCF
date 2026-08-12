"""incremental_indexing_cost_measurement.py -- diagnostic only, touches
no ARCF source. Checklist item #7: measures the REAL cost split between
per-file parsing (already incrementally cached, per engine.build_index's
own docstring) and graph construction (SymbolIndex/ImportGraph/CallGraph/
etc. -- claimed "always cheap in-memory work," never itself incrementally
cached) on real Consul, before designing anything against an assumed gap.

Three real measurements:
  1. Full build from scratch (cold parse + graph construction).
  2. Full build with previous_index where EVERY file is unchanged --
     isolates graph-construction-only cost (parsing is 100% cache hits,
     confirmed via CodeIntelligenceIndex.content_hashes equality).
  3. Full build with previous_index where exactly ONE file changed --
     the real "single-file diff" scenario the spec's ">=80% latency
     reduction on single-file diffs" success criterion is about.
"""

from __future__ import annotations

import time
from pathlib import Path

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner

REPO_ROOT = Path("C:/Users/VasiganiRohitBabu/Desktop/Claude/.benchmark_repos/consul")
N_REPEATS = 3


def main() -> None:
    engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(REPO_ROOT)
    print(f"Real Consul: {len(scan.files)} scanned files")

    # 1. Full cold build.
    cold_times = []
    index = None
    for _ in range(N_REPEATS):
        start = time.perf_counter()
        index = engine.build_index(REPO_ROOT, scan.files)
        cold_times.append(time.perf_counter() - start)
    print(f"\n1. Full cold build (no previous_index): {[round(t, 3) for t in cold_times]}")
    print(f"   {len(index.file_analyses)} files analyzed, {len(index.symbol_index.all())} symbols")

    # 2. Full build, previous_index = the exact same index (100% cache hits) --
    #    isolates graph-construction-only cost.
    warm_times = []
    for _ in range(N_REPEATS):
        start = time.perf_counter()
        engine.build_index(REPO_ROOT, scan.files, previous_index=index)
        warm_times.append(time.perf_counter() - start)
    print(f"\n2. Full build, ALL files cached (graph-construction-only cost): "
          f"{[round(t, 3) for t in warm_times]}")

    mean_cold = sum(cold_times) / len(cold_times)
    mean_warm = sum(warm_times) / len(warm_times)
    graph_fraction = mean_warm / mean_cold * 100
    print(f"\nmean cold={mean_cold:.3f}s  mean warm(cache-hit)={mean_warm:.3f}s")
    print(f"Graph-construction-only cost is {graph_fraction:.1f}% of a full cold build.")
    print(f"(This is the real number the 'always rebuilt fresh, it's cheap' docstring "
          f"claim rests on -- measured, not assumed.)")

    # 3. Single-file diff scenario: modify one file's content in memory by
    #    building a previous_index from a version with one file's hash
    #    forced to differ (simulates "exactly one file changed" without
    #    touching the real repo on disk).
    import dataclasses
    stale_hashes = dict(index.content_hashes)
    one_file = scan.files[0].relative_path
    stale_hashes[one_file] = "deliberately-stale-hash-to-force-reparse"
    stale_index = dataclasses.replace(index, content_hashes=stale_hashes)

    single_file_times = []
    for _ in range(N_REPEATS):
        start = time.perf_counter()
        engine.build_index(REPO_ROOT, scan.files, previous_index=stale_index)
        single_file_times.append(time.perf_counter() - start)
    mean_single = sum(single_file_times) / len(single_file_times)
    reduction_pct = (mean_cold - mean_single) / mean_cold * 100
    print(f"\n3. Single-file diff (1/{len(scan.files)} files force-reparsed): "
          f"{[round(t, 3) for t in single_file_times]}")
    print(f"mean single-file-diff={mean_single:.3f}s")
    print(f"Latency reduction vs full cold rebuild: {reduction_pct:.1f}%")
    print(f"Gate (>=80% reduction on single-file diff): "
          f"{'PASS' if reduction_pct >= 80.0 else 'FAIL'}")


if __name__ == "__main__":
    main()
