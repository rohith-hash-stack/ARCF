"""semantic_layer_experiment.py — controlled comparison of ARCF-DI
retrieval outcomes across semantic-interpretation arms, holding
everything downstream of the semantic stage fixed.

WHY (see /workspace/arcf/docs/semantic_slm_experiment/REPORT.md for the
full analysis): Phase-3-style benchmarking has repeatedly shown
ambiguous-symbol / short-name retrieval failures. This experiment does
NOT assume a semantic SLM (generic or QLoRA-tuned) is the fix — it
measures whether swapping ONLY the semantic-interpretation stage changes
retrieval rank at all, before any tuning investment is considered.

Four arms, sharing ONE CodeIntelligenceContractService instance (same
engine, same contract store, same repository, same resolver flags) so
retrieval logic, ranking, and repository state are held byte-identical
across arms — only `benchmark.semantic_layer.interpreter`'s
implementation differs:

  current_arcf              ExistingSlm1Interpreter(remote model)   — arcf's actual
                             production semantic stage (SLM-1) today.
  generic_slm_plain         ExistingSlm1Interpreter(local model)    — same SLM-1
                             prompt/contract, only the model swapped to a small
                             local one. Isolates "does a smaller model alone change
                             anything," per Step 7 of the experiment brief.
  generic_slm_specialized   LLMSemanticInterpreter(local model)     — new
                             ARCF-specialized prompt/contract (contract.py), same
                             local model. Isolates prompt/contract effect from model
                             effect.
  slm_bypass_control        BypassInterpreter()                     — no LLM call,
                             target_names=[]. Mirrors arcf/scripts/
                             slm1_bypass_experiment.py's own hypothesis: check
                             whether the semantic stage does anything at all before
                             asking which one does it best.

ARCF-DI itself (ContextResolver / DrpResolver / SymbolIndex / ...) is
never imported from `code_intelligence.drp.*` internals here beyond the
one existing rank primitive
(`code_intelligence.drp.diagnostics.compute_retrieval_rank`, already
used identically by `arcf/scripts/drp_benchmark.py`) — this script only
calls `CodeIntelligenceContractService.attach_code_intelligence`, the
same real production entry point `arcf_runner.py` and
`slm1_bypass_experiment.py` already call, with a different
`target_names` argument per arm.

Usage:
    uv run python scripts/semantic_layer_experiment.py \\
        --repo-root ../arcf --out results.json [--fake-client] \\
        [--remote-model gpt-4o-mini] [--k 5]

`--fake-client` runs with `litellm.acompletion` monkeypatched to a
deterministic canned responder — this produces a STRUCTURALLY valid,
clearly-labeled-synthetic result JSON to prove the harness works
end-to-end without any live API key or local model daemon. It is not
evidence about real semantic-interpretation quality; see the report for
why no live run could be performed in this environment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

_BENCHMARK_SRC = Path(__file__).resolve().parent.parent / "src"
_ARCF_SRC = Path(__file__).resolve().parent.parent.parent / "arcf" / "src"
for path in (_BENCHMARK_SRC, _ARCF_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from code_intelligence.engine import CodeIntelligenceEngine  # noqa: E402
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer  # noqa: E402
from code_intelligence.registry import LanguageRegistry  # noqa: E402
from code_intelligence.service import CodeIntelligenceContractService  # noqa: E402
from domain.contract import Contract  # noqa: E402
from domain.intent import UserIntent  # noqa: E402
from domain.versioning import LivingContract  # noqa: E402
from infrastructure.context_resolution_store import InMemoryContextResolutionStore  # noqa: E402
from infrastructure.contract_store import InMemoryContractStore  # noqa: E402
from infrastructure.cost import CostEstimator  # noqa: E402
from infrastructure.llm_client import LiteLLMClient  # noqa: E402

from benchmark.local_slm.errors import LocalSLMUnavailableError  # noqa: E402
from benchmark.local_slm.ollama_provider import OllamaProvider  # noqa: E402
from benchmark.semantic_layer.adapter import to_target_names  # noqa: E402
from benchmark.semantic_layer.errors import SemanticInterpretationError  # noqa: E402
from benchmark.semantic_layer.interpreter import (  # noqa: E402
    BypassInterpreter,
    ExistingSlm1Interpreter,
    InterpretationResult,
    LLMSemanticInterpreter,
    SemanticInterpreter,
)
from benchmark.semantic_layer.tasks import ARCF_REPO_RETRIEVAL_TASKS, RetrievalTask  # noqa: E402
from benchmark.suite.retrieval_scoring import (  # noqa: E402
    compute_retrieval_rank,
    diagnose,
    mean_recall_at_k,
    mean_reciprocal_rank,
)

_DEFAULT_LOCAL_CANDIDATES = ["qwen2.5:1.5b-instruct", "qwen2.5:3b-instruct", "phi3:mini"]


def _fake_completion_response(payload: dict) -> object:
    from types import SimpleNamespace

    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=40, total_tokens=160),
    )


async def _fake_acompletion(**kwargs: object) -> object:
    """Deterministic canned SLM-1 / semantic-interpreter response for
    --fake-client smoke-test mode. Always reports low confidence and
    empty retrieval terms — intentionally NOT tuned to make any arm
    look good; its only job is to exercise the harness end-to-end."""
    messages = kwargs.get("messages", [])
    prompt = messages[0]["content"] if messages else ""
    if "retrieval_terms" in prompt:
        return _fake_completion_response(
            {
                "intent": "locate_symbol",
                "retrieval_terms": [],
                "concepts": [],
                "behavior": [],
                "framework": None,
                "confidence": "uncertain",
                "is_ambiguous": False,
                "ambiguous_alternatives": [],
                "is_negative_query": False,
                "negation_targets": [],
            }
        )
    return _fake_completion_response(
        {
            "intent_summary": "smoke test",
            "domain": "backend",
            "task": "bug_fix",
            "entities": [],
            "constraints": [],
            "assumptions": [],
            "self_reported_confidence": 0.3,
            "suggested_clarifying_questions": [],
        }
    )


async def _run_one(
    interpreter: SemanticInterpreter,
    service: CodeIntelligenceContractService,
    contract_store: InMemoryContractStore,
    repo_root: str,
    task: RetrievalTask,
    k: int,
) -> dict:
    try:
        result: InterpretationResult = await interpreter.interpret(task.query)
    except (SemanticInterpretationError, LocalSLMUnavailableError) as exc:
        return {"task_id": task.task_id, "arm_error": str(exc)}

    target_names = to_target_names(result.interpretation)

    intent = UserIntent(
        raw_request=task.query,
        intent="semantic_layer_experiment",
        domain="diagnostic",
        task="diagnostic",
        entities=target_names,
        confidence=0.5,
    )
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)

    start = time.perf_counter()
    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)),
        target_names=target_names,
        workspace_root=repo_root,
        enable_anchor_classification=True,
        enable_confidence_propagation=True,
    )
    retrieval_ms = (time.perf_counter() - start) * 1000

    candidate_files = [f.file_path for f in resolution.candidate_files]
    rank = compute_retrieval_rank(candidate_files, task.target_file)
    diagnosis = diagnose(
        task_id=task.task_id,
        rank=rank,
        retrieval_terms=target_names,
        candidate_count=len(candidate_files),
        recall_threshold_k=k,
        known_ambiguous=task.known_ambiguous,
        expected_grounding_terms=task.expected_grounding_terms,
    )

    return {
        "task_id": task.task_id,
        "category": task.category,
        "target_file": task.target_file,
        "retrieval_terms": target_names,
        "confidence": result.interpretation.confidence,
        "is_ambiguous_per_slm": result.interpretation.is_ambiguous,
        "candidate_count": len(candidate_files),
        "top_k_candidates": candidate_files[:k],
        "rank": rank,
        "recall_at_1": rank == 1,
        "recall_at_5": rank is not None and rank <= 5,
        "reciprocal_rank": 0.0 if rank is None else 1.0 / rank,
        "failure_class": diagnosis.failure_class.value,
        "diagnosis_note": diagnosis.note,
        "slm_prompt_tokens": result.prompt_tokens,
        "slm_completion_tokens": result.completion_tokens,
        "slm_latency_ms": result.latency_ms,
        "slm_attempts": result.attempts,
        "slm_malformed_attempts": result.malformed_attempts,
        "retrieval_latency_ms": retrieval_ms,
    }


def _aggregate(arm_name: str, task_results: list[dict]) -> dict:
    ok = [r for r in task_results if "arm_error" not in r]
    ranks = [r["rank"] for r in ok]
    failure_counts: dict[str, int] = {}
    for r in ok:
        failure_counts[r["failure_class"]] = failure_counts.get(r["failure_class"], 0) + 1
    return {
        "arm": arm_name,
        "tasks_run": len(ok),
        "tasks_errored": len(task_results) - len(ok),
        "recall_at_1": mean_recall_at_k(ranks, 1),
        "recall_at_5": mean_recall_at_k(ranks, 5),
        "mrr": mean_reciprocal_rank(ranks),
        "mean_candidate_count": (
            sum(r["candidate_count"] for r in ok) / len(ok) if ok else 0.0
        ),
        "mean_slm_prompt_tokens": (
            sum(r["slm_prompt_tokens"] for r in ok) / len(ok) if ok else 0.0
        ),
        "mean_slm_completion_tokens": (
            sum(r["slm_completion_tokens"] for r in ok) / len(ok) if ok else 0.0
        ),
        "mean_slm_latency_ms": sum(r["slm_latency_ms"] for r in ok) / len(ok) if ok else 0.0,
        "malformed_output_rate": (
            sum(1 for r in ok if r["slm_malformed_attempts"] > 0) / len(ok) if ok else 0.0
        ),
        "failure_class_counts": failure_counts,
    }


async def _main_async(args: argparse.Namespace) -> dict:
    repo_root = str(Path(args.repo_root).resolve())
    engine = CodeIntelligenceEngine(LanguageRegistry([PythonLanguageAnalyzer()]), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )
    llm_client = LiteLLMClient(max_retries=2, base_delay_seconds=0.5)

    arms: dict[str, SemanticInterpreter | None] = {
        "current_arcf": ExistingSlm1Interpreter(llm_client, model=args.remote_model),
        "generic_slm_plain": None,
        "generic_slm_specialized": None,
        "slm_bypass_control": BypassInterpreter(),
    }
    local_unavailable_reason: str | None = None
    try:
        local_model = OllamaProvider(
            base_url=args.local_base_url, candidates=args.local_candidates
        ).resolve_model()
    except LocalSLMUnavailableError as exc:
        local_unavailable_reason = str(exc)
    else:
        arms["generic_slm_plain"] = ExistingSlm1Interpreter(llm_client, model=local_model)
        arms["generic_slm_specialized"] = LLMSemanticInterpreter(llm_client, model=local_model)

    report: dict = {
        "synthetic": args.fake_client,
        "repo_root": repo_root,
        "k": args.k,
        "local_slm_unavailable_reason": local_unavailable_reason,
        "arms": {},
    }

    for arm_name, interpreter in arms.items():
        if interpreter is None:
            report["arms"][arm_name] = {
                "arm": arm_name,
                "skipped_reason": local_unavailable_reason or "not constructed",
            }
            continue
        task_results = []
        for task in ARCF_REPO_RETRIEVAL_TASKS:
            task_results.append(
                await _run_one(interpreter, service, contract_store, repo_root, task, args.k)
            )
        report["arms"][arm_name] = {
            "summary": _aggregate(arm_name, task_results),
            "tasks": task_results,
        }

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default="../arcf")
    parser.add_argument("--remote-model", default="gpt-4o-mini")
    parser.add_argument("--local-base-url", default="http://localhost:11434")
    parser.add_argument("--local-candidates", nargs="+", default=_DEFAULT_LOCAL_CANDIDATES)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--out", default="semantic_layer_experiment_result.json")
    parser.add_argument(
        "--fake-client",
        action="store_true",
        help=(
            "Monkeypatch litellm.acompletion with a deterministic canned responder. "
            "Produces a structurally valid but SYNTHETIC result — proves the harness "
            "works end-to-end without live API/Ollama access. Not evidence."
        ),
    )
    args = parser.parse_args()

    if args.fake_client:
        import litellm

        with patch.object(litellm, "acompletion", _fake_acompletion):
            report = asyncio.run(_main_async(args))
    else:
        report = asyncio.run(_main_async(args))

    Path(args.out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {args.out} (synthetic={report['synthetic']})")
    for arm_name, arm_data in report["arms"].items():
        if "summary" in arm_data:
            s = arm_data["summary"]
            print(
                f"  {arm_name}: R@1={s['recall_at_1']:.2f} R@5={s['recall_at_5']:.2f} "
                f"MRR={s['mrr']:.3f} errors={s['tasks_errored']}"
            )
        else:
            print(f"  {arm_name}: SKIPPED ({arm_data.get('skipped_reason')})")


if __name__ == "__main__":
    main()
