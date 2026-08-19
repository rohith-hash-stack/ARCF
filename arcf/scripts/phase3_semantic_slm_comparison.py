"""phase3_semantic_slm_comparison.py -- decisive, single-execution test of:

    "Does a real generic local SLM materially improve ARCF retrieval
    compared with the existing ARCF semantic path?"

Two arms, sharing everything downstream of the semantic-interpretation
stage (same repo index, same ContextResolver, same RelevanceRanker, same
task set, same k):

    current_arcf        ExistingSlm1Interpreter(gpt-4o-mini)        -- arcf's
                         real production SLM-1 (IntentExtractor, unmodified),
                         remote model, real OPENAI_API_KEY.
    generic_local_slm    LLMSemanticInterpreter(ollama_chat/qwen2.5:1.5b-
                         instruct) -- the new ARCF-specialized prompt/contract
                         (benchmark/semantic_layer/contract.py), on a real
                         local Ollama daemon already running in this
                         environment. No fake client, no remote substitute.

Both classes and the `to_target_names` adapter are REUSED unmodified from
the semantic-SLM experiment infrastructure built in the prior session
(benchmark/src/benchmark/semantic_layer/*). Nothing under arcf/src/ is
imported beyond existing, already-public retrieval primitives
(ContextResolver, RelevanceRanker, CodeIntelligenceEngine,
RepositoryScanner) -- no ARCF-DI ranking/retrieval algorithm is modified.

Tasks: all 20 real, ground-truth-verified Phase 3 tasks for Django and
SQLAlchemy (arcf/scripts/phase3_benchmark_tasks_django.py,
phase3_benchmark_tasks_sqlalchemy.py) -- reused verbatim, not
re-authored. These two repos were chosen (over Traefik/Consul/reuse-tier)
because they are both Python, meaning the SAME already-built
PythonLanguageAnalyzer/ContextResolver wiring the Phase 3 deterministic
pass already validated on them applies without new per-language
engineering -- keeping this a one-execution, non-open-ended task per the
brief. Category coverage across the 20 tasks: A(2) B(2) D(2) E(2) F(2)
H(2) I(4) J(2) L-negative(2). No C (vocabulary mismatch), G, or K tasks
exist in this pair -- an honest gap, not silently filled.

None of the 20 queries state their target file path verbatim (checked
against each task's own `query` string before this script was written).

Resolution path: ContextResolver(index).resolve(..., target_names,
traversal_depth=2) + RelevanceRanker().rank(...) -- the SAME lighter
(non-service-layer) call the Phase 3 deterministic pass already used on
these exact two repos (not CodeIntelligenceContractService's fuller
attach_code_intelligence, which the ORIGINAL arcf-only semantic_layer_
experiment.py used). This keeps this run's methodology consistent with
the deterministic baseline it is compared against, at the cost of not
exercising anchor-classification/confidence-propagation (out of scope
for a single-question, single-execution task).

Usage:
    uv run python scripts/phase3_semantic_slm_comparison.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "benchmark" / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from code_intelligence.context_resolver import ContextResolver  # noqa: E402
from code_intelligence.engine import CodeIntelligenceEngine  # noqa: E402
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer  # noqa: E402
from code_intelligence.registry import LanguageRegistry  # noqa: E402
from context.relevance_ranker import RelevanceRanker  # noqa: E402
from infrastructure.cost import CostEstimator  # noqa: E402
from infrastructure.llm_client import LiteLLMClient  # noqa: E402
from workspace.scanner import RepositoryScanner  # noqa: E402

from benchmark.local_slm.errors import LocalSLMUnavailableError  # noqa: E402
from benchmark.local_slm.ollama_provider import OllamaProvider  # noqa: E402
from benchmark.semantic_layer.adapter import to_target_names  # noqa: E402
from benchmark.semantic_layer.errors import SemanticInterpretationError  # noqa: E402
from benchmark.semantic_layer.interpreter import (  # noqa: E402
    ExistingSlm1Interpreter,
    InterpretationResult,
    LLMSemanticInterpreter,
    SemanticInterpreter,
)

from phase3_benchmark_tasks_django import BENCHMARK_TASKS_DJANGO  # noqa: E402
from phase3_benchmark_tasks_sqlalchemy import BENCHMARK_TASKS_SQLALCHEMY  # noqa: E402

BENCHMARK_ROOT = Path(__file__).resolve().parent.parent / ".benchmark_repos"
RESULTS_DIR = Path(__file__).resolve().parent / "phase3_results"
TRAVERSAL_DEPTH = 2
LOCAL_MODEL_CANDIDATES = ["qwen2.5:1.5b-instruct"]

REPOS = [
    ("django", BENCHMARK_ROOT / "django", BENCHMARK_TASKS_DJANGO),
    ("sqlalchemy", BENCHMARK_ROOT / "sqlalchemy", BENCHMARK_TASKS_SQLALCHEMY),
]


def _recall_at_k(ranked: list[str], gt: list[str], k: int) -> float | None:
    if not gt:
        return None
    top_k = set(ranked[:k])
    return sum(1 for g in gt if g in top_k) / len(gt)


def _mrr(ranked: list[str], gt: list[str]) -> float | None:
    if not gt:
        return None
    gt_set = set(gt)
    for i, path in enumerate(ranked, start=1):
        if path in gt_set:
            return 1.0 / i
    return 0.0


def _first_hit_rank(ranked: list[str], gt: list[str]) -> int | None:
    gt_set = set(gt)
    for i, path in enumerate(ranked, start=1):
        if path in gt_set:
            return i
    return None


def _classify_failure(task: dict, target_names: list[str], rank: int | None, k: int, candidate_count: int) -> str | None:
    """Heuristic classification per the brief's taxonomy:
    A=SLM semantic-interpretation failure, B=target absent from pool,
    C=target present but ranking failure, D=ambiguous query,
    E=ARCF-DI limitation, F=other. Explicitly heuristic, same disposition
    as the prior report's own C/D/F classes -- not a certainty label.
    Priority order below is deliberate: a known-ambiguous ground-truth
    task (D) is diagnosed as such even if the SLM also produced no
    terms, because the ambiguity is the pre-existing, independently
    confirmed mechanism (the closed recall-gap boundary), not a fresh
    SLM failure being rediscovered here."""
    if rank is not None and rank <= k:
        return None
    if task.get("ambiguity_expected"):
        return "D"
    if not target_names:
        return "A"
    if rank is None and candidate_count == 0 and task["category"] == "H":
        return "E"
    if rank is None:
        return "B"
    return "C"


async def _run_task(index, root: Path, task: dict, interpreter: SemanticInterpreter, k: int) -> dict:
    try:
        interp_result: InterpretationResult = await interpreter.interpret(task["query"])
    except (SemanticInterpretationError, LocalSLMUnavailableError) as exc:
        return {"task_id": task["id"], "category": task["category"], "arm_error": str(exc)}

    target_names = to_target_names(interp_result.interpretation)

    resolver = ContextResolver(index)
    start = time.perf_counter()
    result = resolver.resolve(
        "phase3-slm-cmp", "phase3-slm-cmp", str(root), target_names, traversal_depth=TRAVERSAL_DEPTH
    )
    resolve_ms = (time.perf_counter() - start) * 1000

    ranked = RelevanceRanker().rank(result)
    ranked_paths = [r.file_path for r in ranked]
    gt_files = task["ground_truth_files"]

    base = {
        "task_id": task["id"],
        "category": task["category"],
        "negative": task["negative"],
        "retrieval_terms": target_names,
        "slm_intent": interp_result.interpretation.intent,
        "slm_concepts": list(interp_result.interpretation.concepts),
        "slm_confidence": interp_result.interpretation.confidence,
        "slm_is_ambiguous": interp_result.interpretation.is_ambiguous,
        "candidate_count": len(result.candidate_files),
        "slm_prompt_tokens": interp_result.prompt_tokens,
        "slm_completion_tokens": interp_result.completion_tokens,
        "slm_latency_ms": interp_result.latency_ms,
        "slm_malformed_attempts": interp_result.malformed_attempts,
        "resolve_latency_ms": resolve_ms,
    }

    if task["negative"]:
        base.update(
            {
                "false_positive": len(result.candidate_files) > 0,
                "recall_at_1": None,
                "recall_at_5": None,
                "mrr": None,
                "rank": None,
                "failure_class": None,
            }
        )
        return base

    r1 = _recall_at_k(ranked_paths, gt_files, 1)
    r5 = _recall_at_k(ranked_paths, gt_files, k)
    mrr = _mrr(ranked_paths, gt_files)
    rank = _first_hit_rank(ranked_paths, gt_files)
    failure_class = _classify_failure(task, target_names, rank, k, len(result.candidate_files))

    base.update(
        {
            "ground_truth_files": gt_files,
            "top10_candidates": ranked_paths[:10],
            "rank": rank,
            "recall_at_1": r1,
            "recall_at_5": r5,
            "mrr": mrr,
            "failure_class": failure_class,
            "false_positive": None,
        }
    )
    return base


def _index_repo(root: Path):
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    scan = RepositoryScanner().scan(root)
    t0 = time.perf_counter()
    index = engine.build_index(root, scan.files)
    return index, time.perf_counter() - t0, len(scan.files)


def _aggregate(task_results: list[dict]) -> dict:
    ok = [r for r in task_results if "arm_error" not in r]
    pos = [r for r in ok if not r["negative"]]
    neg = [r for r in ok if r["negative"]]
    errored = [r for r in task_results if "arm_error" in r]
    r1s = [r["recall_at_1"] for r in pos]
    r5s = [r["recall_at_5"] for r in pos]
    mrrs = [r["mrr"] for r in pos]
    failure_counts: dict[str, int] = {}
    for r in pos:
        fc = r["failure_class"]
        if fc:
            failure_counts[fc] = failure_counts.get(fc, 0) + 1
    all_ok = pos + neg
    return {
        "tasks_run": len(ok),
        "tasks_errored": len(errored),
        "positive_tasks": len(pos),
        "negative_tasks": len(neg),
        "mean_recall_at_1": statistics.mean(r1s) if r1s else None,
        "mean_recall_at_5": statistics.mean(r5s) if r5s else None,
        "mean_mrr": statistics.mean(mrrs) if mrrs else None,
        "mean_candidate_count": statistics.mean([r["candidate_count"] for r in pos]) if pos else None,
        "false_positive_rate": (
            sum(1 for r in neg if r["false_positive"]) / len(neg) if neg else None
        ),
        "mean_slm_latency_ms": statistics.mean([r["slm_latency_ms"] for r in all_ok]) if all_ok else None,
        "mean_slm_prompt_tokens": statistics.mean([r["slm_prompt_tokens"] for r in all_ok]) if all_ok else None,
        "mean_slm_completion_tokens": statistics.mean([r["slm_completion_tokens"] for r in all_ok]) if all_ok else None,
        "malformed_output_rate": (
            sum(1 for r in all_ok if r["slm_malformed_attempts"] > 0) / len(all_ok) if all_ok else None
        ),
        "failure_class_counts": failure_counts,
    }


async def main_async(args: argparse.Namespace) -> dict:
    llm_client = LiteLLMClient(max_retries=2, base_delay_seconds=0.5)
    local_model = OllamaProvider(
        base_url="http://localhost:11434", candidates=LOCAL_MODEL_CANDIDATES
    ).resolve_model()

    arms: dict[str, SemanticInterpreter] = {
        "current_arcf": ExistingSlm1Interpreter(llm_client, model="gpt-4o-mini"),
        "generic_local_slm": LLMSemanticInterpreter(llm_client, model=local_model),
    }

    report: dict = {"local_model": local_model, "k": args.k, "repos": {}}
    for repo_name, root, tasks in REPOS:
        index, index_seconds, files_scanned = _index_repo(root)
        report["repos"][repo_name] = {
            "files_scanned": files_scanned,
            "index_seconds": index_seconds,
            "arms": {},
        }
        for arm_name, interpreter in arms.items():
            task_results = []
            for task in tasks:
                res = await _run_task(index, root, task, interpreter, k=args.k)
                task_results.append(res)
                print(
                    f"[{repo_name}/{arm_name}] {task['id']}: "
                    f"rank={res.get('rank')} r@1={res.get('recall_at_1')} "
                    f"fp={res.get('false_positive')}"
                )
            report["repos"][repo_name]["arms"][arm_name] = {
                "summary": _aggregate(task_results),
                "tasks": task_results,
            }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--out", default=str(RESULTS_DIR / "phase3_semantic_slm_comparison.json"))
    args = parser.parse_args()

    report = asyncio.run(main_async(args))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {args.out}")
    for repo_name, repo_data in report["repos"].items():
        print(f"\n{repo_name}:")
        for arm_name, arm_data in repo_data["arms"].items():
            s = arm_data["summary"]
            print(
                f"  {arm_name}: R@1={s['mean_recall_at_1']} R@5={s['mean_recall_at_5']} "
                f"MRR={s['mean_mrr']} FPR={s['false_positive_rate']} "
                f"errors={s['tasks_errored']}"
            )


if __name__ == "__main__":
    main()
