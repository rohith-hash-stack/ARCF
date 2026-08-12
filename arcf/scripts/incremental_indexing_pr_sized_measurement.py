"""incremental_indexing_pr_sized_measurement.py -- follow-up to
incremental_indexing_cost_measurement.py, checklist item #7. One cold
build (not 3x, to save time -- the mean is already established), then a
real PR-sized diff (15 files force-reparsed) to check the >=80% reduction
gate holds beyond the single-file case, not just extrapolated.
"""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from infrastructure.cost import CostEstimator
from workspace.scanner import RepositoryScanner

REPO_ROOT = Path("C:/Users/VasiganiRohitBabu/Desktop/Claude/.benchmark_repos/consul")
PR_SIZE = 15


def main() -> None:
    engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(REPO_ROOT)

    start = time.perf_counter()
    index = engine.build_index(REPO_ROOT, scan.files)
    cold_time = time.perf_counter() - start
    print(f"cold build: {cold_time:.3f}s ({len(index.file_analyses)} files analyzed)")

    stale_hashes = dict(index.content_hashes)
    changed_files = [p for p in list(index.file_analyses.keys())[:PR_SIZE]]
    for f in changed_files:
        stale_hashes[f] = f"deliberately-stale-{f}"
    stale_index = dataclasses.replace(index, content_hashes=stale_hashes)

    times = []
    for _ in range(3):
        start = time.perf_counter()
        engine.build_index(REPO_ROOT, scan.files, previous_index=stale_index)
        times.append(time.perf_counter() - start)

    mean_pr = sum(times) / len(times)
    reduction_pct = (cold_time - mean_pr) / cold_time * 100
    print(f"PR-sized diff ({PR_SIZE} files force-reparsed): {[round(t, 3) for t in times]}")
    print(f"mean={mean_pr:.3f}s  reduction vs cold={reduction_pct:.1f}%")
    print(f"Gate (>=80% reduction on PR-sized diff): {'PASS' if reduction_pct >= 80.0 else 'FAIL'}")


if __name__ == "__main__":
    main()
