"""phase3_deterministic_pass_django_sqlalchemy.py -- Phase 3 retrieval
benchmark (docs/ARCF_RETRIEVAL_BENCHMARK_PLAN_2026-08-17.md Sec 7, step 1:
the deterministic-only pass). Django + SQLAlchemy only -- this session's
assigned lane of a 3-stage parallel effort (Traefik/Consul and
vLLM/Flask/spring-petclinic are separate sibling runs).

ZERO LLM calls. Every metric here comes from real ContextResolutionResult /
ContextPackage / EvidenceSufficiencyReport objects produced by pure
retrieval code -- classify_retrieval_task, ContextResolver.resolve()
("classic" -- code_intelligence/context_resolver.py, NOT DRP), and
RelevanceRanker/ContextPackager, exactly the pipeline
validation_breadth_matrix_check.py already exercises for Flask/Consul/
spring-petclinic/vllm. This script is that script's template, extended to
compute Recall@K/MRR/Precision@K/evidence-completeness/latency
percentiles/determinism per docs/ARCF_RETRIEVAL_BENCHMARK_PLAN_2026-08-17.md
Sec 4, instead of just a pass/fail gate check.

Ground truth: scripts/phase3_benchmark_tasks_django.py,
scripts/phase3_benchmark_tasks_sqlalchemy.py -- every ground_truth_files
entry in both was confirmed by directly reading the real cloned source
BEFORE this script ever ran (plan Sec 3's non-negotiable rule): ARCF's own
retrieval output was never consulted to build ground truth.

target_names passed to ContextResolver.resolve() are hand-picked per task
below (TARGET_NAMES_BY_TASK_ID), the same discipline
validation_breadth_matrix_check.py's CASES.target_names already uses --
real symbol/identifier strings confirmed present in the source (see each
task's own ground_truth_symbols), not run through SLM-1 (which would be
an LLM call, out of scope for this pass) and not reverse-engineered from
ARCF's own output.

Usage:
    uv run python scripts/phase3_deterministic_pass_django_sqlalchemy.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from code_intelligence.context_resolver import ContextResolver  # noqa: E402
from code_intelligence.engine import CodeIntelligenceEngine  # noqa: E402
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer  # noqa: E402
from code_intelligence.registry import LanguageRegistry  # noqa: E402
from context.evidence_validator import validate_sufficiency  # noqa: E402
from context.packager import ContextPackager  # noqa: E402
from context.relevance_ranker import RelevanceRanker  # noqa: E402
from context.task_profile import RetrievalTaskType, classify_retrieval_task  # noqa: E402
from contracts.evidence_contract import build_evidence_contract, detect_task_type_for_evidence  # noqa: E402
from infrastructure.cost import CostEstimator  # noqa: E402
from workspace.scanner import DEFAULT_MAX_FILES, RepositoryScanner  # noqa: E402

from failure_taxonomy import classify_grounding_failure  # noqa: E402
from phase3_benchmark_tasks_django import BENCHMARK_TASKS_DJANGO  # noqa: E402
from phase3_benchmark_tasks_sqlalchemy import BENCHMARK_TASKS_SQLALCHEMY  # noqa: E402

BENCHMARK_ROOT = Path(__file__).resolve().parent.parent / ".benchmark_repos"
MAX_TOKENS = 8000
RESULTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "phase3_retrieval_benchmark"

# Hand-picked, source-confirmed target_names per task -- see each task's
# ground_truth_symbols in the two task-list files for the grep/read that
# confirmed each name. Kept separate from the ground-truth schema itself
# (plan Sec 3) since target_names is a harness input, not a ground-truth
# fact -- same separation validation_breadth_matrix_check.py's RepoCase
# already makes (target_names is on RepoCase, not on any "ground truth"
# structure).
TARGET_NAMES_BY_TASK_ID: dict[str, list[str]] = {
    # -- SQLAlchemy --
    "sqla_task1_engine_connect": ["engine/connect"],
    "sqla_task2_declarative_metaclass": ["DeclarativeMeta"],
    "sqla_task3_instrumented_attribute_descriptor": ["InstrumentedAttribute"],
    "sqla_task4_table_new_dynamic_dispatch": ["Table"],
    "sqla_task5_dialect_plugin_loading": ["PluginLoader", "get_dialect"],
    "sqla_task6_unit_of_work_subsystem": ["UOWTransaction"],
    "sqla_task7_session_commit_call_chain": ["commit", "UOWTransaction"],
    "sqla_task8_ambiguous_process": ["process"],
    "sqla_task9_mapped_column_wraps_column": ["MappedColumn", "Column"],
    "sqla_task10_negative_graphql": ["GraphQLResolver"],
    # -- Django --
    "django_task1_modelbase_metaclass_inheritance": ["ModelBase", "AbstractUser"],
    "django_task2_modelform_metaclass_hierarchy": ["ModelFormMetaclass", "MediaDefiningClass"],
    "django_task3_manager_from_queryset_dynamic_class": ["from_queryset"],
    "django_task4_model_save_exact": ["db/models/base/save"],
    "django_task5_ambiguous_save": ["save"],
    "django_task6_signal_dispatch_subsystem": ["Signal"],
    "django_task7_request_response_call_chain": ["get_response", "resolve"],
    "django_task8_middleware_config_driven": ["load_middleware"],
    "django_task9_admin_uses_forms_metaclass": ["BaseModelAdmin", "MediaDefiningClass"],
    "django_task10_negative_graphql_websocket": ["GraphQLSchema"],
}


@dataclass
class RepoConfig:
    name: str
    root: Path
    tasks: list[dict]


REPOS = [
    RepoConfig("django", BENCHMARK_ROOT / "django", BENCHMARK_TASKS_DJANGO),
    RepoConfig("sqlalchemy", BENCHMARK_ROOT / "sqlalchemy", BENCHMARK_TASKS_SQLALCHEMY),
]


def _index_repo(root: Path) -> tuple[object, list, int, bool]:
    """Returns (index, scanned_files, files_scanned_count, truncated)."""
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(root)
    index = engine.build_index(root, scan.files)
    return index, scan.files, len(scan.files), scan.truncated


def _recall_at_k(ranked_paths: list[str], ground_truth: list[str], k: int) -> float:
    if not ground_truth:
        return float("nan")
    top_k = set(ranked_paths[:k])
    hit = sum(1 for gt in ground_truth if gt in top_k)
    return hit / len(ground_truth)


def _mrr(ranked_paths: list[str], ground_truth: list[str]) -> float:
    if not ground_truth:
        return float("nan")
    gt_set = set(ground_truth)
    for i, path in enumerate(ranked_paths, start=1):
        if path in gt_set:
            return 1.0 / i
    return 0.0


def _precision_at_k(candidate_paths: list[str], ground_truth: list[str]) -> float:
    if not candidate_paths:
        return float("nan")
    gt_set = set(ground_truth)
    hits = sum(1 for p in candidate_paths if p in gt_set)
    return hits / len(candidate_paths)


def _percentiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50": None, "p95": None, "p99": None}
    s = sorted(values)

    def pct(p: float) -> float:
        idx = min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))
        return round(s[idx], 2)

    return {"p50": pct(0.50), "p95": pct(0.95), "p99": pct(0.99)}


async def _run_task(index, root: Path, task: dict) -> dict:
    task_id = task["id"]
    target_names = TARGET_NAMES_BY_TASK_ID.get(task_id)
    if target_names is None:
        raise KeyError(f"No TARGET_NAMES_BY_TASK_ID entry for {task_id!r}")

    resolver = ContextResolver(index)
    start = time.perf_counter()
    result = resolver.resolve("phase3-ws", "phase3-contract", str(root), target_names, traversal_depth=2)
    resolve_ms = (time.perf_counter() - start) * 1000

    # Evidence sufficiency -- same production wiring as
    # application/execute_use_case.py's attach_code_intelligence path:
    # detect_task_type_for_evidence(raw_request) selects which (if any)
    # of the three registered evidence contracts applies, then
    # validate_sufficiency runs the real deterministic glob-match
    # expansion. Most of these repository-navigation queries have no
    # registered contract (auth/test_execution/ci_explanation are the
    # only three) -- reported honestly as "no contract" below rather than
    # forcing evidence-completeness to look artificially complete.
    evidence_task_type = detect_task_type_for_evidence(task["query"])
    contract = build_evidence_contract(evidence_task_type) if evidence_task_type else ()
    scan = RepositoryScanner().scan(root)
    if contract:
        result, evidence_report = validate_sufficiency(result, contract, scan.files, root)
    else:
        evidence_report = None

    ranked = RelevanceRanker().rank(result)
    ranked_paths = [r.file_path for r in ranked]

    retrieval_task_type = classify_retrieval_task(task["query"])
    packager = ContextPackager(RelevanceRanker(), CostEstimator())
    pkg_start = time.perf_counter()
    package, _ = await packager.package(
        result, task["query"], MAX_TOKENS, task_type=retrieval_task_type,
    )
    package_ms = (time.perf_counter() - pkg_start) * 1000
    packaged_paths = [f.file_path for f in package.relevant_files]

    gt_files = task["ground_truth_files"]

    # Failure classification for any ground-truth file that resolution
    # found (ranked_paths) but packaging dropped.
    failures = []
    for gt in gt_files:
        if gt in ranked_paths and gt not in packaged_paths:
            diag = classify_grounding_failure(
                gt, result, ranked, packaged_paths, MAX_TOKENS, retrieval_task_type,
            )
            if diag is not None:
                failures.append({"file": gt, "category": diag.primary.value})

    unresolved_gt = [gt for gt in gt_files if gt not in ranked_paths]

    metrics = {
        "task_id": task_id,
        "category": task["category"],
        "negative": task["negative"],
        "query": task["query"],
        "target_names": target_names,
        "resolve_latency_ms": round(resolve_ms, 3),
        "package_latency_ms": round(package_ms, 3),
        "candidate_file_count": len(result.candidate_files),
        "ranked_files": ranked_paths,
        "packaged_files": packaged_paths,
        "confidence": result.confidence,
        "confidence_source": "classic",  # G9: never comparable to a DRP confidence value
        "ambiguous_targets": list(result.ambiguous_targets),
        "unresolved_symbols": list(result.unresolved_symbols),
        "evidence_task_type": evidence_task_type,
        "evidence_categories_satisfied": list(result.evidence_categories_satisfied),
        "evidence_categories_missing": list(result.evidence_categories_missing),
        "evidence_completeness": (
            None
            if not (result.evidence_categories_satisfied or result.evidence_categories_missing)
            else len(result.evidence_categories_satisfied)
            / (len(result.evidence_categories_satisfied) + len(result.evidence_categories_missing))
        ),
        "case_b_triggered": bool(result.evidence_categories_missing),
        "unresolved_query": len(result.candidate_files) == 0,
        "unresolved_ground_truth_files": unresolved_gt,
        "packaging_failures": failures,
    }

    if task["negative"]:
        # False positive = resolver returned ANY real candidate for a
        # query about something that doesn't exist in the repo.
        metrics["false_positive"] = len(result.candidate_files) > 0
        metrics["recall_at_1"] = metrics["recall_at_5"] = metrics["recall_at_10"] = None
        metrics["mrr"] = None
        metrics["precision_at_k"] = None
    else:
        metrics["false_positive"] = None
        metrics["recall_at_1"] = _recall_at_k(ranked_paths, gt_files, 1)
        metrics["recall_at_5"] = _recall_at_k(ranked_paths, gt_files, 5)
        metrics["recall_at_10"] = _recall_at_k(ranked_paths, gt_files, 10)
        metrics["mrr"] = _mrr(ranked_paths, gt_files)
        metrics["precision_at_k"] = _precision_at_k(packaged_paths, gt_files)

    return metrics


async def _determinism_check(index, root: Path, task: dict) -> dict:
    """Plan Sec 7.4: re-run one task twice through the full pipeline,
    confirm byte-identical candidate_files."""
    target_names = TARGET_NAMES_BY_TASK_ID[task["id"]]
    resolver = ContextResolver(index)
    r1 = resolver.resolve("phase3-ws", "phase3-contract", str(root), target_names, traversal_depth=2)
    r2 = resolver.resolve("phase3-ws", "phase3-contract", str(root), target_names, traversal_depth=2)
    paths1 = [f.file_path for f in r1.candidate_files]
    paths2 = [f.file_path for f in r2.candidate_files]
    identical = paths1 == paths2
    return {
        "task_id": task["id"],
        "run1_candidate_files": paths1,
        "run2_candidate_files": paths2,
        "byte_identical": identical,
    }


async def _run_repo(cfg: RepoConfig) -> dict:
    report: dict = {"repo": cfg.name}
    print(f"\n=== {cfg.name} ===")

    start = time.perf_counter()
    try:
        index, scanned_files, files_scanned, truncated = _index_repo(cfg.root)
    except Exception as exc:  # noqa: BLE001 -- reported, not swallowed
        report["status"] = "INDEX_FAILED"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        print(f"  INDEX_FAILED: {report['error']}")
        return report
    index_seconds = round(time.perf_counter() - start, 2)

    report["index_seconds"] = index_seconds
    report["files_scanned"] = files_scanned
    report["files_analyzed"] = len(index.file_analyses)
    report["symbols_indexed"] = len(index.symbol_index.all())
    report["scanner_truncated"] = truncated
    report["default_max_files_cap"] = DEFAULT_MAX_FILES
    report["approaching_max_files_cap"] = files_scanned >= 0.5 * DEFAULT_MAX_FILES
    print(
        f"  files_scanned={files_scanned} files_analyzed={report['files_analyzed']} "
        f"symbols_indexed={report['symbols_indexed']} index_seconds={index_seconds} "
        f"truncated={truncated}"
    )

    task_results = []
    for task in cfg.tasks:
        try:
            metrics = await _run_task(index, cfg.root, task)
        except Exception as exc:  # noqa: BLE001 -- one bad task shouldn't kill the run
            metrics = {
                "task_id": task["id"],
                "category": task["category"],
                "status": "TASK_FAILED",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
            print(f"  [{task['id']}] TASK_FAILED: {metrics['error']}")
        else:
            print(
                f"  [{task['id']}] cat={task['category']} candidates={metrics['candidate_file_count']} "
                f"R@1={metrics['recall_at_1']} R@5={metrics['recall_at_5']} MRR={metrics['mrr']} "
                f"conf={metrics['confidence']:.3f} case_b={metrics['case_b_triggered']} "
                f"unresolved={metrics['unresolved_query']}"
            )
        task_results.append(metrics)
    report["task_results"] = task_results

    # Determinism check (plan Sec 7.4) -- first non-negative task in the list.
    det_task = next((t for t in cfg.tasks if not t["negative"]), cfg.tasks[0])
    report["determinism_check"] = await _determinism_check(index, cfg.root, det_task)
    print(
        f"  determinism_check[{det_task['id']}]: "
        f"byte_identical={report['determinism_check']['byte_identical']}"
    )

    # Aggregates
    ok_results = [r for r in task_results if "status" not in r]
    non_negative = [r for r in ok_results if not r["negative"]]
    negative = [r for r in ok_results if r["negative"]]

    def _mean(key: str, rows: list[dict]) -> float | None:
        vals = [r[key] for r in rows if r.get(key) is not None and r[key] == r[key]]  # filter NaN
        return round(statistics.mean(vals), 4) if vals else None

    resolve_latencies = [r["resolve_latency_ms"] for r in ok_results]
    package_latencies = [r["package_latency_ms"] for r in ok_results]

    report["aggregate"] = {
        "n_tasks": len(cfg.tasks),
        "n_ok": len(ok_results),
        "n_failed": len(task_results) - len(ok_results),
        "mean_recall_at_1": _mean("recall_at_1", non_negative),
        "mean_recall_at_5": _mean("recall_at_5", non_negative),
        "mean_recall_at_10": _mean("recall_at_10", non_negative),
        "mean_mrr": _mean("mrr", non_negative),
        "mean_precision_at_k": _mean("precision_at_k", non_negative),
        "mean_evidence_completeness": _mean("evidence_completeness", ok_results),
        "unresolved_query_rate": round(
            sum(1 for r in ok_results if r["unresolved_query"]) / len(ok_results), 4
        ) if ok_results else None,
        "case_b_trigger_rate": round(
            sum(1 for r in ok_results if r["case_b_triggered"]) / len(ok_results), 4
        ) if ok_results else None,
        "false_positive_rate_negative_tasks": (
            round(sum(1 for r in negative if r["false_positive"]) / len(negative), 4)
            if negative else None
        ),
        "n_negative_tasks": len(negative),
        "resolve_latency_ms_percentiles": _percentiles(resolve_latencies),
        "package_latency_ms_percentiles": _percentiles(package_latencies),
        "mean_confidence_classic": _mean("confidence", ok_results),
    }
    report["status"] = "OK"
    return report


def _write_markdown(all_reports: list[dict]) -> str:
    lines = ["# Phase 3 Deterministic Retrieval Benchmark -- Django + SQLAlchemy", ""]
    lines.append(
        "Zero LLM calls. ContextResolver (classic) only -- see plan Sec 7 step 1. "
        "n=1 per task (single-run, per plan Sec 11 labeling requirement)."
    )
    lines.append("")

    for report in all_reports:
        lines.append(f"## {report['repo']}")
        lines.append("")
        if report["status"] != "OK":
            lines.append(f"STATUS: {report['status']} -- {report.get('error')}")
            lines.append("")
            continue
        lines.append(
            f"- files_scanned={report['files_scanned']} files_analyzed={report['files_analyzed']} "
            f"symbols_indexed={report['symbols_indexed']} index_seconds={report['index_seconds']} "
            f"scanner_truncated={report['scanner_truncated']} "
            f"(DEFAULT_MAX_FILES={report['default_max_files_cap']}, "
            f"approaching_cap={report['approaching_max_files_cap']})"
        )
        lines.append(
            f"- determinism_check ({report['determinism_check']['task_id']}): "
            f"byte_identical={report['determinism_check']['byte_identical']}"
        )
        lines.append("")
        lines.append(
            "| task_id | category | R@1 | R@5 | R@10 | MRR | Precision@K | Evidence Compl. | "
            "Case-B | Unresolved | Confidence (classic) |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in report["task_results"]:
            if "status" in r:
                lines.append(f"| {r['task_id']} | -- | TASK_FAILED: {r['error']} |||||||| |")
                continue
            if r["negative"]:
                lines.append(
                    f"| {r['task_id']} | {r['category']} (negative) | -- | -- | -- | -- | -- | "
                    f"{_fmt(r['evidence_completeness'])} | {r['case_b_triggered']} | "
                    f"{r['unresolved_query']} | {r['confidence']:.3f} "
                    f"(false_positive={r['false_positive']}) |"
                )
                continue
            lines.append(
                f"| {r['task_id']} | {r['category']} | {_fmt(r['recall_at_1'])} | "
                f"{_fmt(r['recall_at_5'])} | {_fmt(r['recall_at_10'])} | {_fmt(r['mrr'])} | "
                f"{_fmt(r['precision_at_k'])} | {_fmt(r['evidence_completeness'])} | "
                f"{r['case_b_triggered']} | {r['unresolved_query']} | {r['confidence']:.3f} |"
            )
        lines.append("")
        agg = report["aggregate"]
        lines.append(
            f"**Aggregate ({agg['n_ok']}/{agg['n_tasks']} tasks completed, "
            f"{agg['n_negative_tasks']} negative):** "
            f"mean R@1={_fmt(agg['mean_recall_at_1'])} R@5={_fmt(agg['mean_recall_at_5'])} "
            f"R@10={_fmt(agg['mean_recall_at_10'])} MRR={_fmt(agg['mean_mrr'])} "
            f"Precision@K={_fmt(agg['mean_precision_at_k'])} "
            f"evidence_completeness={_fmt(agg['mean_evidence_completeness'])} "
            f"unresolved_query_rate={_fmt(agg['unresolved_query_rate'])} "
            f"case_b_trigger_rate={_fmt(agg['case_b_trigger_rate'])} "
            f"FPR(negative)={_fmt(agg['false_positive_rate_negative_tasks'])} "
            f"mean_confidence(classic)={_fmt(agg['mean_confidence_classic'])}"
        )
        lines.append("")
        lines.append(
            f"resolve_latency_ms p50/p95/p99 = {agg['resolve_latency_ms_percentiles']}  \n"
            f"package_latency_ms p50/p95/p99 = {agg['package_latency_ms_percentiles']}"
        )
        lines.append("")

    lines.append("## Cross-repository aggregate")
    lines.append("")
    ok_reports = [r for r in all_reports if r["status"] == "OK"]
    all_task_results = [r for rep in ok_reports for r in rep["task_results"] if "status" not in r]
    all_non_negative = [r for r in all_task_results if not r["negative"]]

    def _cross_mean(key: str) -> float | None:
        vals = [r[key] for r in all_non_negative if r.get(key) is not None and r[key] == r[key]]
        return round(statistics.mean(vals), 4) if vals else None

    lines.append(
        f"n_tasks={len(all_task_results)} across {len(ok_reports)} repos: "
        f"mean R@1={_fmt(_cross_mean('recall_at_1'))} R@5={_fmt(_cross_mean('recall_at_5'))} "
        f"R@10={_fmt(_cross_mean('recall_at_10'))} MRR={_fmt(_cross_mean('mrr'))}"
    )
    lines.append("")

    lines.append("## Per-category aggregate (across both repos)")
    lines.append("")
    by_cat: dict[str, list[dict]] = {}
    for r in all_task_results:
        by_cat.setdefault(r["category"], []).append(r)
    lines.append("| category | n | mean R@1 | mean R@5 | mean MRR |")
    lines.append("|---|---|---|---|---|")
    for cat in sorted(by_cat):
        rows = by_cat[cat]
        non_neg_rows = [r for r in rows if not r["negative"]]
        r1 = [r["recall_at_1"] for r in non_neg_rows if r.get("recall_at_1") == r.get("recall_at_1")]
        r5 = [r["recall_at_5"] for r in non_neg_rows if r.get("recall_at_5") == r.get("recall_at_5")]
        mrr = [r["mrr"] for r in non_neg_rows if r.get("mrr") == r.get("mrr")]
        lines.append(
            f"| {cat} | {len(rows)} | "
            f"{round(statistics.mean(r1), 4) if r1 else '--'} | "
            f"{round(statistics.mean(r5), 4) if r5 else '--'} | "
            f"{round(statistics.mean(mrr), 4) if mrr else '--'} |"
        )
    lines.append("")

    return "\n".join(lines)


def _fmt(v) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float) and v != v:  # NaN
        return "N/A"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


async def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    all_reports = []
    for cfg in REPOS:
        report = await _run_repo(cfg)
        all_reports.append(report)
        json_path = RESULTS_DIR / f"phase3_deterministic_{cfg.name}.json"
        json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"  wrote {json_path}")

    md = _write_markdown(all_reports)
    md_path = RESULTS_DIR / "phase3_deterministic_django_sqlalchemy_summary.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"\nwrote {md_path}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
