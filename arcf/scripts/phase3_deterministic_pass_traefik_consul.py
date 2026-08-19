"""phase3_deterministic_pass_traefik_consul.py -- Phase 3 retrieval
benchmark (docs/ARCF_RETRIEVAL_BENCHMARK_PLAN_2026-08-17.md Sec 7 step 1),
Traefik + Consul, deterministic-only pass.

ZERO LLM calls: every metric here comes from real ContextResolutionResult
objects produced by CodeIntelligenceContractService.attach_code_intelligence
(the same real production entrypoint drp_benchmark.py and
negative_query_fpr_real_consul_check.py already use), never from a
generated LLM artifact. No LiteLLMClient is constructed anywhere in this
file.

Ground truth: scripts/phase3_benchmark_tasks_traefik.py (9 new tasks) +
scripts/phase3_benchmark_tasks_consul_extension.py (3 new tasks) +
scripts/validate_llm_grounding.py's existing BENCHMARK_TASKS (6 Consul
tasks, imported and adapted to this plan's schema here -- NOT modified at
their source, per the plan's own "extend, don't replace" instruction).

target_names substitute for real SLM-1/IntentExtractor entity extraction
(which requires an LLM call and is out of scope for this pass): derived
deterministically from each task's own ground_truth_symbols (already
grep-confirmed real identifiers), or -- for negative/category-L tasks,
which have no ground_truth_symbols by construction -- from capitalized
identifier-shaped tokens in the query text itself, the same hand-picked
discipline negative_query_fpr_real_consul_check.py already uses for its
own NEGATIVE_QUERIES. This is a deliberate, disclosed substitute, not an
attempt to reproduce SLM-1's own behavior.

Both resolver strategies ("classic" and "drp") are run for every task
through the SAME CodeIntelligenceContractService instance per repository,
so the underlying CodeIntelligenceIndex (and, for drp, DrpIndex) is built
once and reused (see service.py's own _index_cache/_drp_index_cache) --
same-process, same-session discipline per plan Sec 7.3.

Usage:
    uv run python scripts/phase3_deterministic_pass_traefik_consul.py
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
import traceback
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asyncio

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from context.budget_manager import ContextBudgetManager
from context.compressor import SymbolRangeCompressor
from context.relevance_ranker import RelevanceRanker
from context.task_profile import RANKING_PROFILES, TRAVERSAL_DEPTH, classify_retrieval_task
from contracts.repository_scope_classifier import RepositoryScopeClassifier
from contracts.task_classifier import TaskClassifier
from domain.context_resolution import EvidenceTier, OriginStage
from domain.contract import Contract
from domain.intent import UserIntent
from domain.versioning import LivingContract
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator
from workspace.permissions import PermissionManager

from phase3_benchmark_tasks_consul_extension import BENCHMARK_TASKS_CONSUL_EXTENSION
from phase3_benchmark_tasks_traefik import BENCHMARK_TASKS_TRAEFIK
from validate_llm_grounding import BENCHMARK_TASKS as _CONSUL_EXISTING_RAW

BENCHMARK_ROOT = Path(__file__).resolve().parent.parent / ".benchmark_repos"
MAX_TOKENS = 8000
RESULTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "phase3_retrieval_benchmark"
_NON_FALLBACK_STAGES = (OriginStage.AST_DIRECT, OriginStage.SCOPED_GRAPH_EXPANSION)

# Category mapping for validate_llm_grounding.py's existing 6 Consul tasks
# -- documented reasoning in phase3_benchmark_tasks_consul_extension.py's
# own module docstring. Not stored in the source file itself (that file
# predates this plan's taxonomy); applied here only, for this pass's
# reporting.
_EXISTING_CONSUL_CATEGORY = {
    "task1_targeted_logic": "A",
    "task2_dependency_tracing": "E",
    "task3_interface_type_contract": "A",
    "task4_refactoring_multifile": "F",
    "task5_ambiguous_common_name": "B",
    "task6_path_hint_secondary_sibling": "E",
}
_EXISTING_CONSUL_AMBIGUITY = {
    "task2_dependency_tracing": (
        True,
        "Notify is a 78-way same-named-method ambiguity repo-wide "
        "(per this task's own original comment in validate_llm_grounding.py).",
    ),
    "task5_ambiguous_common_name": (
        True,
        "New has 150+ same-named declarations repo-wide "
        "(per this task's own original comment in validate_llm_grounding.py).",
    ),
}


def _adapt_existing_consul_tasks() -> list[dict]:
    """Wraps validate_llm_grounding.BENCHMARK_TASKS (unmodified at its
    source) into this plan's Sec 3 schema, purely for this pass's own
    reporting/metrics -- does not write back to that file."""
    adapted = []
    for raw in _CONSUL_EXISTING_RAW:
        ambiguity_expected, ambiguity_note = _EXISTING_CONSUL_AMBIGUITY.get(
            raw["id"], (False, None)
        )
        adapted.append(
            {
                "id": f"existing_{raw['id']}",
                "repo": "consul",
                "query": raw["query"],
                "category": _EXISTING_CONSUL_CATEGORY.get(raw["id"], "UNKNOWN"),
                "ground_truth_files": raw["ground_truth_files"],
                "ground_truth_structural": raw["ground_truth_structural"],
                "ground_truth_behavioral": raw["ground_truth_behavioral"],
                "ground_truth_symbols": raw.get("ground_truth_terms", []),
                "expected_subsystem": None,
                "expected_traversal_depth": None,  # computed below, per task
                "ambiguity_expected": ambiguity_expected,
                "ambiguity_note": ambiguity_note,
                "negative": False,
            }
        )
    return adapted


ALL_TASKS: dict[str, list[dict]] = {
    "traefik": list(BENCHMARK_TASKS_TRAEFIK),
    "consul": [*_adapt_existing_consul_tasks(), *BENCHMARK_TASKS_CONSUL_EXTENSION],
}

_IDENTIFIER_RE = re.compile(r"\b[A-Z][A-Za-z0-9]{3,}\b")


def _target_names_for_task(task: dict) -> list[str]:
    symbols = task.get("ground_truth_symbols") or []
    if symbols:
        names: set[str] = set()
        for sym in symbols:
            names.add(sym)
            if "." in sym:
                names.add(sym.rsplit(".", 1)[-1])
        return sorted(names)
    # Negative / no-ground-truth-symbol tasks: same hand-picked discipline
    # negative_query_fpr_real_consul_check.py uses -- capitalized
    # identifier-shaped tokens pulled directly from the query text.
    candidates = sorted(set(_IDENTIFIER_RE.findall(task["query"])))
    return candidates or [task["query"].split()[0]]


def _is_high_confidence_match(resolution) -> bool:
    return any(
        ref.origin_stage in _NON_FALLBACK_STAGES and ref.evidence_tier is EvidenceTier.PRIMARY
        for ref in resolution.candidate_files
    )


def _package(root: Path, query: str, resolution) -> tuple[list[str], int]:
    scope = RepositoryScopeClassifier().classify(query)
    task_classifier_task = TaskClassifier().classify(query)
    retrieval_task_type = classify_retrieval_task(query, task_classifier_task, scope.task_type)
    ranking_profile = RANKING_PROFILES[retrieval_task_type]
    ranked = RelevanceRanker().rank(resolution, ranking_profile)

    permissions = PermissionManager(root)
    budget_manager = ContextBudgetManager(
        permissions, CostEstimator(), SymbolRangeCompressor(permissions)
    )
    packaged, used_tokens, _excluded = budget_manager.select(ranked, resolution, MAX_TOKENS)
    packaged_paths = [p.file_path for p in packaged]
    return packaged_paths, used_tokens


def _recall_at_k(ranked_paths: list[str], gt_files: list[str], k: int) -> float | None:
    if not gt_files:
        return None
    top_k = set(ranked_paths[:k])
    return len(top_k & set(gt_files)) / len(gt_files)


def _mrr(ranked_paths: list[str], gt_files: list[str]) -> float | None:
    if not gt_files:
        return None
    gt_set = set(gt_files)
    for i, p in enumerate(ranked_paths, start=1):
        if p in gt_set:
            return round(1.0 / i, 4)
    return 0.0


def _precision_at_k(packaged_paths: list[str], gt_files: list[str]) -> float | None:
    if not gt_files or not packaged_paths:
        return None
    return round(len(set(packaged_paths) & set(gt_files)) / len(packaged_paths), 4)


async def _resolve(
    service: CodeIntelligenceContractService,
    contract_store: InMemoryContractStore,
    root: Path,
    query: str,
    target_names: list[str],
    resolver_strategy: str,
):
    intent = UserIntent(
        raw_request=query,
        intent="phase3 retrieval benchmark",
        domain="phase3",
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
        resolver_strategy=resolver_strategy,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    return resolution, elapsed_ms


async def _run_task(
    service: CodeIntelligenceContractService,
    contract_store: InMemoryContractStore,
    root: Path,
    task: dict,
) -> dict:
    query = task["query"]
    target_names = _target_names_for_task(task)
    gt_files = task["ground_truth_files"]

    # Real expected_traversal_depth, from the real classifier -- "recorded
    # not assumed" per the plan's own Sec 3 field comment.
    scope = RepositoryScopeClassifier().classify(query)
    task_classifier_task = TaskClassifier().classify(query)
    retrieval_task_type = classify_retrieval_task(query, task_classifier_task, scope.task_type)
    real_traversal_depth = TRAVERSAL_DEPTH[retrieval_task_type]

    result: dict = {
        "id": task["id"],
        "repo": task["repo"],
        "category": task["category"],
        "negative": task["negative"],
        "query": query,
        "target_names": target_names,
        "ground_truth_files": gt_files,
        "expected_traversal_depth_declared": task.get("expected_traversal_depth"),
        "real_retrieval_task_type": retrieval_task_type.value,
        "real_traversal_depth": real_traversal_depth,
        "resolvers": {},
    }

    for strategy in ("classic", "drp"):
        try:
            resolution, latency_ms = await _resolve(
                service, contract_store, root, query, target_names, strategy
            )
        except Exception as exc:  # noqa: BLE001 -- reported, never crashes the run
            result["resolvers"][strategy] = {
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
            continue

        candidate_paths = [f.file_path for f in resolution.candidate_files]
        packaged_paths, packaged_tokens = _package(root, query, resolution)

        satisfied = len(resolution.evidence_categories_satisfied)
        missing = len(resolution.evidence_categories_missing)
        evidence_completeness = (
            round(satisfied / (satisfied + missing), 4) if (satisfied + missing) else None
        )

        entry = {
            "status": "OK",
            "candidate_count": len(candidate_paths),
            "candidate_files": candidate_paths,
            "confidence": resolution.confidence,
            "resolve_latency_ms": round(latency_ms, 2),
            "packaged_file_count": len(packaged_paths),
            "packaged_tokens": packaged_tokens,
            "evidence_categories_satisfied": list(resolution.evidence_categories_satisfied),
            "evidence_categories_missing": list(resolution.evidence_categories_missing),
            "evidence_completeness": evidence_completeness,
            "unresolved": len(candidate_paths) == 0,
            "case_b_triggered": bool(resolution.evidence_categories_missing),
        }

        if task["negative"]:
            entry["false_positive_confident_match"] = _is_high_confidence_match(resolution)
        else:
            entry["recall_at_1"] = _recall_at_k(candidate_paths, gt_files, 1)
            entry["recall_at_5"] = _recall_at_k(candidate_paths, gt_files, 5)
            entry["recall_at_10"] = _recall_at_k(candidate_paths, gt_files, 10)
            entry["mrr"] = _mrr(candidate_paths, gt_files)
            entry["precision_at_k"] = _precision_at_k(packaged_paths, gt_files)

        result["resolvers"][strategy] = entry

    return result


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {"p50": None, "p95": None, "p99": None, "n": 0}
    ordered = sorted(values)

    def pct(p: float) -> float:
        idx = min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))
        return round(ordered[idx], 2)

    return {"p50": pct(0.50), "p95": pct(0.95), "p99": pct(0.99), "n": len(ordered)}


async def _determinism_check(
    service: CodeIntelligenceContractService,
    contract_store: InMemoryContractStore,
    root: Path,
    task: dict,
) -> dict:
    target_names = _target_names_for_task(task)
    r1, _ = await _resolve(service, contract_store, root, task["query"], target_names, "classic")
    r2, _ = await _resolve(service, contract_store, root, task["query"], target_names, "classic")
    files1 = [f.file_path for f in r1.candidate_files]
    files2 = [f.file_path for f in r2.candidate_files]
    return {"task_id": task["id"], "byte_identical": files1 == files2, "run1": files1, "run2": files2}


async def main() -> None:
    all_results: list[dict] = []
    determinism_results: list[dict] = []

    for repo_name, tasks in ALL_TASKS.items():
        root = BENCHMARK_ROOT / repo_name
        print(f"\n=== {repo_name} ({len(tasks)} tasks) ===")
        engine = CodeIntelligenceEngine(LanguageRegistry([GoLanguageAnalyzer()]), CostEstimator())
        contract_store = InMemoryContractStore()
        service = CodeIntelligenceContractService(
            engine, contract_store, InMemoryContextResolutionStore()
        )

        for task in tasks:
            print(f"  [{task['id']}] ({task['category']}) {task['query'][:70]}...")
            task_result = await _run_task(service, contract_store, root, task)
            all_results.append(task_result)
            for strategy, entry in task_result["resolvers"].items():
                if entry["status"] != "OK":
                    print(f"    {strategy}: ERROR {entry.get('error')}")
                    continue
                if task["negative"]:
                    print(
                        f"    {strategy}: candidates={entry['candidate_count']} "
                        f"false_positive={entry['false_positive_confident_match']} "
                        f"confidence={entry['confidence']:.2f} latency={entry['resolve_latency_ms']}ms"
                    )
                else:
                    print(
                        f"    {strategy}: recall@1={entry['recall_at_1']} recall@5={entry['recall_at_5']} "
                        f"mrr={entry['mrr']} evidence={entry['evidence_completeness']} "
                        f"confidence={entry['confidence']:.2f} latency={entry['resolve_latency_ms']}ms"
                    )

        # Determinism check (plan Sec 7.4): re-run the first task per repo
        # twice through the full real pipeline.
        determinism_results.append(
            await _determinism_check(service, contract_store, root, tasks[0])
        )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RESULTS_DIR / "traefik_consul_deterministic_results.json"
    raw_path.write_text(
        json.dumps(
            {"results": all_results, "determinism_checks": determinism_results}, indent=2
        ),
        encoding="utf-8",
    )
    print(f"\nRaw results written to {raw_path}")

    _write_summary(all_results, determinism_results)


def _write_summary(all_results: list[dict], determinism_results: list[dict]) -> None:
    lines: list[str] = []
    lines.append("# Phase 3 Deterministic Retrieval Benchmark -- Traefik + Consul")
    lines.append("")
    lines.append(
        "Deterministic-only pass (plan Sec 7 step 1), zero LLM calls. ARCF commit a9d104d "
        "(architecture-closure, frozen)."
    )
    lines.append("")

    for repo_name in ALL_TASKS:
        repo_results = [r for r in all_results if r["repo"] == repo_name]
        lines.append(f"## {repo_name}")
        lines.append("")
        lines.append(
            "| task | cat | resolver | recall@1 | recall@5 | recall@10 | mrr | "
            "precision@k | evidence | confidence | case_b | latency_ms |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in repo_results:
            for strategy, e in r["resolvers"].items():
                if e["status"] != "OK":
                    lines.append(f"| {r['id']} | {r['category']} | {strategy} | ERROR | | | | | | | | |")
                    continue
                if r["negative"]:
                    lines.append(
                        f"| {r['id']} | {r['category']} | {strategy} | -- | -- | -- | -- | -- | "
                        f"{e['evidence_completeness']} | {e['confidence']:.2f} | "
                        f"{e['case_b_triggered']} | {e['resolve_latency_ms']} |"
                    )
                else:
                    lines.append(
                        f"| {r['id']} | {r['category']} | {strategy} | {e['recall_at_1']} | "
                        f"{e['recall_at_5']} | {e['recall_at_10']} | {e['mrr']} | "
                        f"{e['precision_at_k']} | {e['evidence_completeness']} | "
                        f"{e['confidence']:.2f} | {e['case_b_triggered']} | {e['resolve_latency_ms']} |"
                    )
        lines.append("")

        for strategy in ("classic", "drp"):
            latencies = [
                r["resolvers"][strategy]["resolve_latency_ms"]
                for r in repo_results
                if r["resolvers"].get(strategy, {}).get("status") == "OK"
            ]
            confidences = [
                r["resolvers"][strategy]["confidence"]
                for r in repo_results
                if r["resolvers"].get(strategy, {}).get("status") == "OK"
            ]
            recalls1 = [
                r["resolvers"][strategy]["recall_at_1"]
                for r in repo_results
                if not r["negative"]
                and r["resolvers"].get(strategy, {}).get("status") == "OK"
                and r["resolvers"][strategy]["recall_at_1"] is not None
            ]
            unresolved = sum(
                1
                for r in repo_results
                if r["resolvers"].get(strategy, {}).get("status") == "OK"
                and r["resolvers"][strategy]["unresolved"]
            )
            case_b = sum(
                1
                for r in repo_results
                if r["resolvers"].get(strategy, {}).get("status") == "OK"
                and r["resolvers"][strategy]["case_b_triggered"]
            )
            n = len(repo_results)
            lat_pct = _percentiles(latencies)
            mean_recall1 = round(statistics.mean(recalls1), 4) if recalls1 else None
            mean_conf = round(statistics.mean(confidences), 4) if confidences else None
            lines.append(
                f"**{strategy} aggregate** ({repo_name}): mean recall@1={mean_recall1} "
                f"mean confidence={mean_conf} unresolved={unresolved}/{n} "
                f"case_b_rate={round(case_b / n, 4) if n else None} "
                f"latency_ms p50={lat_pct['p50']} p95={lat_pct['p95']} p99={lat_pct['p99']}"
            )
        lines.append("")

    lines.append("## Determinism checks (plan Sec 7.4)")
    lines.append("")
    for d in determinism_results:
        lines.append(f"- `{d['task_id']}`: byte-identical candidate_files across 2 runs = **{d['byte_identical']}**")
    lines.append("")

    lines.append("## Known-boundary confirmation (plan Sec 0 / arcf_recall_gap_closed)")
    lines.append("")
    for r in all_results:
        if r.get("category") == "B" or any(
            gt_task_id in r["id"] for gt_task_id in ("task5_ambiguous_common_name", "task2_dependency_tracing")
        ):
            lines.append(f"- `{r['id']}`: category {r['category']}, see raw results for ambiguity-related recall.")
    lines.append("")

    lines.append("Case-C rate: NOT MEASURABLE in this pass -- no generation step was run (no LLM call).")
    lines.append("")

    summary_path = RESULTS_DIR / "traefik_consul_deterministic_summary.md"
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Summary written to {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
