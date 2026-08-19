"""phase3_deterministic_pass_reuse_tier.py -- ARCF Retrieval Benchmark
Plan (docs/ARCF_RETRIEVAL_BENCHMARK_PLAN_2026-08-17.md), Phase 3,
deterministic-only pass (plan §7 step 1), "reuse tier" repos: Flask,
spring-petclinic, vLLM.

HARD CONSTRAINTS (per the phase-3 execution brief): zero LLM API calls,
zero changes under arcf/src/, ground truth never derived from ARCF's own
retrieval output. This script only ever imports the already-shipped
ContextResolver / RelevanceRanker / ContextPackager / EvidenceValidator
pipeline objects directly -- the same composition
scripts/validation_breadth_matrix_check.py already uses -- never
LiteLLMClient, never IntentExtractor (SLM-1), never ArcfExecutionOrchestrator
(whose recovery path can invoke generation).

Two things this script does, matching the phase-3 brief's steps 2/4/5:

1. REGRESSION CHECK (step 2): re-runs validation_breadth_matrix_check.py's
   own methodology -- same target_names, same MAX_TOKENS=8000, same
   TelemetryCollector -> production_gate.evaluate_release wiring -- against
   FRESH shallow clones in arcf/.benchmark_repos/{flask,spring-petclinic,
   vllm} (created by this phase-3 task, separate from the older clones this
   project's memory says already exist one directory up, at
   .benchmark_repos/ next to arcf/ -- those are NOT touched by this
   script). Compares the freshly measured overall_fallback_ratio against
   the previously recorded values (2026-08-12 checkpoint, in-memory
   record: Flask 85.7%, spring-petclinic 50%, vllm-mixed 66.7%) and
   reports drift honestly instead of forcing a match.

2. NEW-TASK PASS (step 4): runs the 6 new ground-truth tasks from
   phase3_benchmark_tasks_reuse_tier.py through the same direct-resolver
   composition, computing Recall@1/5/10, MRR, Precision@K, evidence
   completeness (EvidenceValidator.validate_sufficiency, contract
   selected via the deterministic classify_retrieval_task keyword
   classifier -- NOT an LLM call), unresolved-query rate, Case-B trigger
   rate (evidence_categories_missing non-empty, same check
   application/execute_use_case.py's real orchestrator makes BEFORE
   spending an LLM call on generation), confidence-by-source (classic
   resolver only -- this script never exercises the DRP strategy switch,
   so every value here is explicitly the "classic" arm, never blended
   with a DRP number that was never produced), and latency percentiles.

Determinism check (plan §7.4, step 5): one task per repo is resolved
TWICE and the two candidate_files sets are compared for byte-identical
equality.

Usage:
    uv run python scripts/phase3_deterministic_pass_reuse_tier.py
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from code_intelligence.context_resolver import ContextResolver
from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.java_analyzer import JavaLanguageAnalyzer
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.languages.rust_analyzer import RustLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from context.evidence_validator import validate_sufficiency
from context.packager import ContextPackager
from context.relevance_ranker import RelevanceRanker
from context.task_profile import RetrievalTaskType, classify_retrieval_task
from contracts.evidence_contract import build_evidence_contract
from infrastructure.cost import CostEstimator
from infrastructure.production_gate import ReleaseGateConfig, evaluate_release
from infrastructure.telemetry import TelemetryCollector
from workspace.scanner import RepositoryScanner

from failure_taxonomy import classify_grounding_failure  # noqa: E402
from phase3_benchmark_tasks_reuse_tier import PHASE3_REUSE_TIER_TASKS  # noqa: E402

# Fresh clones created for this phase-3 task (see module docstring --
# deliberately NOT the older .benchmark_repos/ one directory up).
BENCHMARK_ROOT = Path(__file__).resolve().parent.parent / ".benchmark_repos"
MAX_TOKENS = 8000
RESULTS_DIR = Path(__file__).resolve().parent / "phase3_results"

# Recorded 2026-08-12 checkpoint (arcf_repo_sweep / validation-breadth-
# matrix memory, and validation_breadth_matrix_check.py's own module
# docstring) -- the baseline this regression check compares against.
PRIOR_FALLBACK_RATIOS = {
    "flask": 0.857,
    "spring-petclinic": 0.50,
    "vllm": 0.667,
}


@dataclass
class RegressionCase:
    tier: str
    name: str
    root: Path
    analyzers: list
    target_names: list[str]


REGRESSION_CASES = [
    RegressionCase(
        "Python", "flask", BENCHMARK_ROOT / "flask", [PythonLanguageAnalyzer()],
        ["Flask"],
    ),
    RegressionCase(
        "Java", "spring-petclinic", BENCHMARK_ROOT / "spring-petclinic", [JavaLanguageAnalyzer()],
        ["Owner", "Person"],
    ),
    RegressionCase(
        "Mixed (Python+Rust)", "vllm", BENCHMARK_ROOT / "vllm",
        [PythonLanguageAnalyzer(), RustLanguageAnalyzer()],
        ["LLM", "CompletionChunk"],
    ),
]

_REPO_ROOT_BY_NAME = {c.name: c.root for c in REGRESSION_CASES}


def _index_repo(root: Path, analyzers: list) -> tuple[object, list, Exception | None]:
    try:
        engine = CodeIntelligenceEngine(LanguageRegistry(analyzers), CostEstimator())
        scan = RepositoryScanner().scan(root)
        index = engine.build_index(root, scan.files)
        return index, scan.files, None
    except Exception as exc:  # noqa: BLE001
        return None, [], exc


async def _run_regression_case(case: RegressionCase, index, scanned_files: list, index_exc: Exception | None) -> dict:
    report: dict = {"tier": case.tier, "repo": case.name}
    report["files_scanned"] = len(scanned_files)

    if index_exc is not None:
        report["status"] = "INDEX_FAILED"
        report["error"] = f"{type(index_exc).__name__}: {index_exc}"
        report["traceback"] = traceback.format_exc()
        return report

    report["files_analyzed"] = len(index.file_analyses)
    report["symbols_indexed"] = len(index.symbol_index.all())

    resolver = ContextResolver(index)
    collector = TelemetryCollector()
    all_diagnoses = []

    for target in case.target_names:
        resolve_start = time.perf_counter()
        result = resolver.resolve("ws1", "c1", str(case.root), [target], traversal_depth=1)
        resolve_ms = (time.perf_counter() - resolve_start) * 1000

        ranked_files = RelevanceRanker().rank(result)
        pkg_start = time.perf_counter()
        packager = ContextPackager(RelevanceRanker(), CostEstimator())
        package, _ = await packager.package(
            result, f"query about {target}", MAX_TOKENS, task_type=RetrievalTaskType.UNKNOWN,
        )
        package_ms = (time.perf_counter() - pkg_start) * 1000

        collector.record(
            result, resolve_ms, package=package, package_latency_ms=package_ms,
            classified_task=RetrievalTaskType.UNKNOWN,
        )

        packaged_files = [f.file_path for f in package.relevant_files]
        for ranked in ranked_files:
            if ranked.file_path not in packaged_files:
                diag = classify_grounding_failure(
                    ranked.file_path, result, ranked_files, packaged_files, MAX_TOKENS,
                    RetrievalTaskType.UNKNOWN,
                )
                if diag is not None:
                    all_diagnoses.append(diag)

        report.setdefault("per_target", []).append({
            "target": target, "candidates": len(result.candidate_files),
            "packaged": len(packaged_files), "excluded": package.excluded_file_count,
        })

    run_summary = collector.get_run_summary()
    report["run_summary"] = run_summary
    decision = evaluate_release(run_summary, config=ReleaseGateConfig())
    report["gate_decision"] = decision.status
    report["gate_results"] = [
        {"gate": g.gate_name.value, "passed": g.passed, "skipped": g.skipped, "detail": g.detail}
        for g in decision.gate_results
    ]
    failure_counts: dict[str, int] = {}
    for d in all_diagnoses:
        failure_counts[d.primary.value] = failure_counts.get(d.primary.value, 0) + 1
    report["failure_taxonomy"] = {"total": len(all_diagnoses), "by_category": failure_counts}
    report["status"] = "OK"

    fresh_ratio = run_summary["overall_fallback_ratio"]
    prior_ratio = PRIOR_FALLBACK_RATIOS[case.name]
    drift = None if fresh_ratio is None else round(fresh_ratio - prior_ratio, 4)
    report["regression_check"] = {
        "prior_fallback_ratio": prior_ratio,
        "fresh_fallback_ratio": fresh_ratio,
        "drift": drift,
        "reproduced": drift is not None and abs(drift) < 0.02,  # <2pp treated as "reproduced"
    }
    return report


# ---------------------------------------------------------------------------
# New-task pass
# ---------------------------------------------------------------------------

def _recall_at_k(ranked_paths: list[str], ground_truth: set[str], k: int) -> float | None:
    if not ground_truth:
        return None
    top_k = set(ranked_paths[:k])
    return round(len(top_k & ground_truth) / len(ground_truth), 4)


def _mrr(ranked_paths: list[str], ground_truth: set[str]) -> float:
    for idx, path in enumerate(ranked_paths, start=1):
        if path in ground_truth:
            return round(1.0 / idx, 4)
    return 0.0


def _precision_at_k(top_k_paths: list[str], ground_truth: set[str]) -> float | None:
    if not top_k_paths:
        return None
    hits = sum(1 for p in top_k_paths if p in ground_truth)
    return round(hits / len(top_k_paths), 4)


async def _run_new_task(task: dict, index, scanned_files, root: Path) -> dict:
    result_entry: dict = {"id": task["id"], "repo": task["repo"], "category": task["category"], "query": task["query"]}
    ground_truth = set(task["ground_truth_files"])

    resolver = ContextResolver(index)
    resolve_start = time.perf_counter()
    result = resolver.resolve("ws1", "c1", str(root), task["target_names"], traversal_depth=1)
    resolve_ms = (time.perf_counter() - resolve_start) * 1000

    ranked_files = RelevanceRanker().rank(result)
    ranked_paths = [r.file_path for r in ranked_files]

    task_type = classify_retrieval_task(task["query"])
    pkg_start = time.perf_counter()
    packager = ContextPackager(RelevanceRanker(), CostEstimator())
    package, _ = await packager.package(result, task["query"], MAX_TOKENS, task_type=task_type)
    package_ms = (time.perf_counter() - pkg_start) * 1000
    packaged_paths = [f.file_path for f in package.relevant_files]

    contract = build_evidence_contract(task_type.value)
    expanded_result, evidence_report = validate_sufficiency(result, contract, scanned_files, root)

    candidate_count = len(result.candidate_files)
    result_entry["candidate_count"] = candidate_count
    result_entry["unresolved"] = candidate_count == 0
    result_entry["negative"] = task["negative"]
    if task["negative"]:
        # False-positive check: a negative query should resolve to zero
        # real candidates. Any non-empty candidate set on a genuinely
        # nonexistent target is a false positive.
        result_entry["false_positive"] = candidate_count > 0
    else:
        result_entry["recall_at_1"] = _recall_at_k(ranked_paths, ground_truth, 1)
        result_entry["recall_at_5"] = _recall_at_k(ranked_paths, ground_truth, 5)
        result_entry["recall_at_10"] = _recall_at_k(ranked_paths, ground_truth, 10)
        result_entry["mrr"] = _mrr(ranked_paths, ground_truth) if ground_truth else None
        result_entry["precision_at_packaged_k"] = _precision_at_k(packaged_paths, ground_truth)
        result_entry["packaged_k"] = len(packaged_paths)

    result_entry["task_type_classified"] = task_type.value
    result_entry["evidence_contract_categories"] = [c.name for c in contract]
    total_evidence = len(evidence_report.satisfied) + len(evidence_report.missing)
    result_entry["evidence_completeness"] = (
        round(len(evidence_report.satisfied) / total_evidence, 4) if total_evidence else None
    )
    result_entry["case_b_triggered"] = bool(evidence_report.missing) and candidate_count > 0

    conf_by_source = {
        "ambiguity_confidence": [r.ambiguity_confidence for r in ranked_files if r.ambiguity_confidence is not None],
        "path_mask_confidence": [r.path_mask_confidence for r in ranked_files if r.path_mask_confidence is not None],
    }
    result_entry["confidence_by_source_classic"] = {
        k: (round(statistics.mean(v), 4) if v else None) for k, v in conf_by_source.items()
    }
    result_entry["ambiguous_targets"] = list(result.ambiguous_targets)

    result_entry["resolve_latency_ms"] = round(resolve_ms, 3)
    result_entry["package_latency_ms"] = round(package_ms, 3)
    result_entry["total_latency_ms"] = round(resolve_ms + package_ms, 3)

    return result_entry


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {"p50": None, "p95": None, "p99": None, "n": 0}
    s = sorted(values)

    def pct(p: float) -> float:
        idx = min(len(s) - 1, int(round(p * (len(s) - 1))))
        return round(s[idx], 3)

    return {"p50": pct(0.50), "p95": pct(0.95), "p99": pct(0.99), "n": len(s)}


async def _determinism_check(index, root: Path, target_names: list[str]) -> dict:
    resolver = ContextResolver(index)
    r1 = resolver.resolve("ws1", "c1", str(root), target_names, traversal_depth=1)
    r2 = resolver.resolve("ws1", "c1", str(root), target_names, traversal_depth=1)
    files1 = sorted((f.file_path, f.reason) for f in r1.candidate_files)
    files2 = sorted((f.file_path, f.reason) for f in r2.candidate_files)
    return {
        "target_names": target_names,
        "run1_candidate_count": len(files1),
        "run2_candidate_count": len(files2),
        "byte_identical": files1 == files2,
    }


async def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    raw: dict = {"regression_check": [], "new_tasks": [], "determinism_check": []}

    # -- Step 2: regression check on fresh clones ---------------------------
    # index_by_repo captures the (index, scanned_files, root) built for the
    # regression check so the new-task pass and determinism check below
    # reuse it directly -- vllm's index in particular is expensive enough
    # (thousands of files) that rebuilding it a second/third time would be
    # real wasted work, not just inelegant.
    index_by_repo: dict[str, tuple[object, list, Path]] = {}
    print("=== Regression check: fresh clones vs. 2026-08-12 checkpoint ===")
    for case in REGRESSION_CASES:
        print(f"\n--- {case.tier}: {case.name} ---")
        index_start = time.perf_counter()
        idx, scanned_files, index_exc = _index_repo(case.root, case.analyzers)
        index_seconds = round(time.perf_counter() - index_start, 2)
        report = await _run_regression_case(case, idx, scanned_files, index_exc)
        report["index_seconds"] = index_seconds
        raw["regression_check"].append(report)
        if report["status"] != "OK":
            print(f"  STATUS: {report['status']} -- {report.get('error')}")
            continue
        index_by_repo[case.name] = (idx, scanned_files, case.root)
        rc = report["regression_check"]
        print(f"  files_scanned={report['files_scanned']} symbols_indexed={report['symbols_indexed']}")
        print(f"  fresh_fallback_ratio={rc['fresh_fallback_ratio']} prior={rc['prior_fallback_ratio']} "
              f"drift={rc['drift']} reproduced={rc['reproduced']}")

    # -- Step 4: new-task pass -----------------------------------------------
    print("\n\n=== New-task pass (6 tasks, categories B/E/F/H/L) ===")
    for task in PHASE3_REUSE_TIER_TASKS:
        idx, scanned, root = index_by_repo[task["repo"]]
        entry = await _run_new_task(task, idx, scanned, root)
        raw["new_tasks"].append(entry)
        print(f"\n--- {entry['id']} ({entry['category']}) ---")
        if entry["negative"]:
            print(f"  candidate_count={entry['candidate_count']} false_positive={entry['false_positive']}")
        else:
            print(f"  recall@1={entry['recall_at_1']} recall@5={entry['recall_at_5']} "
                  f"recall@10={entry['recall_at_10']} mrr={entry['mrr']} "
                  f"precision@{entry['packaged_k']}={entry['precision_at_packaged_k']}")
        print(f"  evidence_completeness={entry['evidence_completeness']} case_b={entry['case_b_triggered']} "
              f"unresolved={entry['unresolved']}")
        print(f"  latency: resolve={entry['resolve_latency_ms']}ms package={entry['package_latency_ms']}ms")

    # -- Step 5: determinism check (one task per repo, twice) --------------
    print("\n\n=== Determinism check ===")
    determinism_targets = {
        "flask": ["route", "add_url_rule"],
        "spring-petclinic": ["VisitController", "processNewVisitForm", "addVisit"],
        "vllm": ["generate"],
    }
    for repo_name, targets in determinism_targets.items():
        idx, _scanned, root = index_by_repo[repo_name]
        det = await _determinism_check(idx, root, targets)
        det["repo"] = repo_name
        raw["determinism_check"].append(det)
        print(f"  {repo_name}: byte_identical={det['byte_identical']} "
              f"(run1={det['run1_candidate_count']} run2={det['run2_candidate_count']} candidates)")

    # -- Aggregate metrics ----------------------------------------------------
    non_negative = [t for t in raw["new_tasks"] if not t["negative"]]
    negative = [t for t in raw["new_tasks"] if t["negative"]]
    all_latencies = [t["total_latency_ms"] for t in raw["new_tasks"]]

    aggregate = {
        "n_new_tasks": len(raw["new_tasks"]),
        "n_positive_tasks": len(non_negative),
        "n_negative_tasks": len(negative),
        "mean_recall_at_1": round(statistics.mean(v["recall_at_1"] for v in non_negative if v["recall_at_1"] is not None), 4) if non_negative else None,
        "mean_recall_at_5": round(statistics.mean(v["recall_at_5"] for v in non_negative if v["recall_at_5"] is not None), 4) if non_negative else None,
        "mean_recall_at_10": round(statistics.mean(v["recall_at_10"] for v in non_negative if v["recall_at_10"] is not None), 4) if non_negative else None,
        "mean_mrr": round(statistics.mean(v["mrr"] for v in non_negative if v["mrr"] is not None), 4) if non_negative else None,
        "unresolved_query_rate": round(sum(1 for t in raw["new_tasks"] if t["unresolved"]) / len(raw["new_tasks"]), 4) if raw["new_tasks"] else None,
        "false_positive_rate_negative_tasks": round(sum(1 for t in negative if t["false_positive"]) / len(negative), 4) if negative else None,
        "case_b_trigger_rate": round(sum(1 for t in raw["new_tasks"] if t["case_b_triggered"]) / len(raw["new_tasks"]), 4) if raw["new_tasks"] else None,
        "latency_ms": _percentiles(all_latencies),
        "n_run_label": "n=1 per task (single-run) -- NOT a multi-run statistical result; see plan §11.",
    }
    raw["aggregate"] = aggregate

    print("\n\n=== Aggregate (new tasks, n=1 per task) ===")
    for k, v in aggregate.items():
        print(f"  {k}: {v}")

    # -- Save outputs -----------------------------------------------------
    json_path = RESULTS_DIR / "phase3_reuse_tier_results.json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(raw, fh, indent=2, default=str)
    print(f"\nRaw results written to {json_path}")

    _write_markdown_summary(raw)


def _write_markdown_summary(raw: dict) -> None:
    lines = ["# Phase 3 Deterministic Pass -- Reuse Tier (Flask / spring-petclinic / vLLM)", ""]
    lines.append("## Regression check (fresh clones vs. 2026-08-12 checkpoint)")
    lines.append("")
    lines.append("| Repo | Prior fallback ratio | Fresh fallback ratio | Drift | Reproduced (<2pp)? |")
    lines.append("|---|---|---|---|---|")
    for r in raw["regression_check"]:
        if r["status"] != "OK":
            lines.append(f"| {r['repo']} | -- | -- | INDEX_FAILED: {r.get('error')} | N |")
            continue
        rc = r["regression_check"]
        lines.append(f"| {r['repo']} | {rc['prior_fallback_ratio']} | {rc['fresh_fallback_ratio']} | {rc['drift']} | {rc['reproduced']} |")
    lines.append("")

    lines.append("## New tasks (per-task results, n=1 each)")
    lines.append("")
    lines.append("| id | repo | category | recall@1 | recall@5 | recall@10 | MRR | precision@K | evidence_completeness | case_b | unresolved |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for t in raw["new_tasks"]:
        if t["negative"]:
            lines.append(f"| {t['id']} | {t['repo']} | {t['category']} (negative) | -- | -- | -- | -- | -- | {t['evidence_completeness']} | {t['case_b_triggered']} | {t['unresolved']} (false_positive={t['false_positive']}) |")
        else:
            lines.append(
                f"| {t['id']} | {t['repo']} | {t['category']} | {t['recall_at_1']} | {t['recall_at_5']} | "
                f"{t['recall_at_10']} | {t['mrr']} | {t['precision_at_packaged_k']} (K={t['packaged_k']}) | "
                f"{t['evidence_completeness']} | {t['case_b_triggered']} | {t['unresolved']} |"
            )
    lines.append("")

    lines.append("## Aggregate (n=1 per task -- single-run, not statistically tested)")
    lines.append("")
    for k, v in raw["aggregate"].items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")

    lines.append("## Determinism check (plan §7.4)")
    lines.append("")
    lines.append("| Repo | run1 candidates | run2 candidates | byte-identical |")
    lines.append("|---|---|---|---|")
    for d in raw["determinism_check"]:
        lines.append(f"| {d['repo']} | {d['run1_candidate_count']} | {d['run2_candidate_count']} | {d['byte_identical']} |")
    lines.append("")

    md_path = RESULTS_DIR / "phase3_reuse_tier_summary.md"
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"Markdown summary written to {md_path}")


if __name__ == "__main__":
    asyncio.run(main())
