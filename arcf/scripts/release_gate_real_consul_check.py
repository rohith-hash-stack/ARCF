"""release_gate_real_consul_check.py -- checklist item #11 end-to-end
verification, real Consul, no LLM calls. Runs real resolve()+package()
calls through a real TelemetryCollector, feeds the real RunSummary into
evaluate_release(), and demonstrates regression sensitivity by injecting
a synthetic regression on top of the real baseline (not a fabricated
"candidate ARCF version" -- see production_gate.py's own docstring for
why no such thing exists to compare against yet).
"""

from __future__ import annotations

from pathlib import Path

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from context.packager import ContextPackager
from context.relevance_ranker import RelevanceRanker
from infrastructure.cost import CostEstimator
from infrastructure.production_gate import ReleaseGateConfig, evaluate_release
from infrastructure.telemetry import TelemetryCollector
from workspace.scanner import RepositoryScanner

REPO_ROOT = Path("C:/Users/VasiganiRohitBabu/Desktop/Claude/.benchmark_repos/consul")
QUERIES = [["Register"], ["New"], ["Catalog"], ["Agent"]]


def main() -> None:
    import asyncio
    import time

    async def run() -> None:
        engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
        scan = RepositoryScanner().scan(REPO_ROOT)
        index = engine.build_index(REPO_ROOT, scan.files)
        resolver = ContextResolver(index)
        packager = ContextPackager(RelevanceRanker(), CostEstimator())

        collector = TelemetryCollector()
        for targets in QUERIES:
            start = time.perf_counter()
            result = resolver.resolve("ws1", "c1", str(REPO_ROOT), targets, traversal_depth=2)
            resolve_ms = (time.perf_counter() - start) * 1000
            start = time.perf_counter()
            package, _ = await packager.package(result, f"query about {targets}", max_tokens=8000)
            package_ms = (time.perf_counter() - start) * 1000
            collector.record(
                result, resolve_latency_ms=resolve_ms, package=package, package_latency_ms=package_ms
            )

        real_summary = collector.get_run_summary()
        print(f"=== Real Consul RunSummary ({len(QUERIES)} queries) ===")
        print(real_summary)

        print("\n=== Gate 1: evaluate real summary, no baseline ===")
        decision = evaluate_release(real_summary)
        print(decision.status)
        print(decision.failure_report())

        print("\n=== Gate 2: real summary as its OWN baseline (repeat-run smoke test) ===")
        # Real finding, not a bug: fallback/token_budget are ABSOLUTE ceilings
        # (matching the spec's own "zero unflagged fallbacks" / "utilization <=
        # threshold" wording) -- they evaluate independently of baseline, so
        # self-comparison does NOT bypass them if the real data itself exceeds
        # the ceiling. Only the RELATIVE gates (latency, quality precision-drop)
        # are expected to trivially pass here (0% delta against yourself).
        decision_self = evaluate_release(real_summary, baseline_summary=real_summary)
        print(decision_self.status)
        print(decision_self.failure_report())
        by_name_self = {g.gate_name: g for g in decision_self.gate_results}
        assert by_name_self["latency"].passed, "latency vs self must be 0% overhead"
        print(f"latency gate vs self: {by_name_self['latency'].detail} (correctly passes)")
        if not decision_self.approved:
            print("Overall REJECTED -- expected, since real Consul's own fallback ratio "
                  f"({real_summary['overall_fallback_ratio']}) exceeds the strict default "
                  "ceiling (0.0), independent of baseline. Demonstrating with a realistic "
                  "config threshold instead:")
            realistic_config = ReleaseGateConfig(max_fallback_ratio=0.05)
            decision_realistic = evaluate_release(
                real_summary, baseline_summary=real_summary, config=realistic_config
            )
            print(decision_realistic.status)
            assert decision_realistic.approved, (
                "a run compared against itself, with a realistic (non-zero-tolerance) "
                "fallback ceiling, must approve"
            )

        print("\n=== Gate 3: synthetic regression injection on top of the REAL baseline ===")
        regressed = dict(real_summary)
        regressed["overall_fallback_ratio"] = 0.8
        regressed["resolve_latency_ms"] = {
            **real_summary["resolve_latency_ms"],
            "mean": real_summary["resolve_latency_ms"]["mean"] * 3,
        }
        decision_regressed = evaluate_release(
            regressed, baseline_summary=real_summary, config=ReleaseGateConfig()
        )
        print(decision_regressed.status)
        print(decision_regressed.failure_report())
        assert not decision_regressed.approved, "injected regression must be caught"
        print("\nPASS: regression injected on real baseline data was correctly rejected.")

    asyncio.run(run())


if __name__ == "__main__":
    main()
