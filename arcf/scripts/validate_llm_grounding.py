"""validate_llm_grounding.py — ARCF vs. Direct LLM grounding & accuracy
validation harness (2026-08-11), real Consul, real LLM calls, no mocks.

Three arms per task, same query, same repository:

  Arm A (ARCF Payload): ContextResolver ("classic") -> RelevanceRanker ->
      ContextBudgetManager -> ContextPackager -- ARCF's real, current
      production pipeline, which now includes Features A/B/C (Tier-1
      ambiguity decay, relative score falloff gate, AST enclosing scope
      slicing -- see arcf_realtime_pipeline_optimization memory / this
      repo's own recent history) unconditionally, since they're merged
      into Base/main as the default behavior, not an opt-in flag.

  Arm B (Baseline Raw Payload): the SAME ContextResolver resolution and
      the SAME RelevanceRanker ranking as Arm A (so retrieval QUALITY is
      held constant -- Feature A's ambiguity decay is a scoring change,
      not a packaging one, so it's still reflected here), but packaged
      by `_greedy_full_file_package` instead of ContextBudgetManager:
      full-file reads, greedy top-K fill, no compression, no relative
      score falloff gate. This is deliberately an ABLATION of Features
      B/C specifically (ARCF's pre-2026-08-11 packaging policy), not a
      different retrieval mechanism -- isolates what B/C's packaging
      policy contributes at identical retrieval quality, rather than
      re-litigating retrieval quality itself (that comparison already
      exists: repo_query_answer.py's "light" naive-keyword-grep arm).

  Arm C (Zero Context / Direct): the query alone, no repository context
      at all -- tests base parametric knowledge vs. genuine grounding
      need, same as repo_query_answer.py's "direct" arm.

Model availability (checked directly against the configured keys before
writing this, not assumed): ANTHROPIC_API_KEY in .env is invalid
(authentication_error on a live call); the configured OpenAI project
does not have `gpt-4o` access, only `gpt-4o-mini`. GENERATION_MODEL is
therefore gpt-4o-mini for every arm AND the judge -- the task's own
"Claude 3.5 Sonnet / GPT-4o" framing is not achievable with the keys
actually available in this environment, so this substitutes rather than
silently failing or fabricating results from an unavailable model.

TTFT (Time-to-First-Token): LiteLLMClient.complete() is a single
blocking call (see its own docstring) and doesn't stream, so genuine
TTFT isn't measurable through it. `_stream_complete` below is a
script-local streaming helper built directly on litellm for this
specific need -- not a change to the shared production client.

Ground truth (`BENCHMARK_TASKS`) was established by directly grepping
the real, cloned Consul source (not assumed from the task names) --
see each task's `ground_truth_files`/`ground_truth_terms`. Task 5 is
deliberately the SAME extreme-ambiguity "New" case already documented
as an open, unsolved gap (arcf_callgraph_locality_fix /
arcf_realtime_pipeline_optimization memories): agent/cache's real
`func New(options Options) *Cache` (cache.go:209) competes against 150+
other same-named declarations repo-wide, and Tier-1 entry-point fan-out
means ARCF's own resolution may not even surface the right file among
its packaged candidates. This harness doesn't presuppose a good outcome
there -- it's included specifically to test whether that known
structural gap shows up as measurably worse grounding, not hidden from
the benchmark suite to make ARCF look better.

Target names for resolution are NOT hardcoded per task -- IntentExtractor
(the same real SLM-1 entity extraction repo_query_answer.py uses) pulls
them from the query text, so this doesn't cherry-pick target_names to
bias the outcome in either direction.

Usage:
    uv run python scripts/validate_llm_grounding.py --repo-path <path> --repo-name consul \
        [--n-runs 3]

--n-runs (default 3) repeats every task that many times and reports
mean +/- stddev per arm/metric, since SLM-1 entity extraction is
non-deterministic in content (not just order) even at temperature=0.0
-- a single-run score delta cannot be attributed to a real cause without
this (see PROGRESS.md's "Benchmark noise floor" entry).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import traceback
from pathlib import Path
from uuid import UUID, uuid4

import litellm

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from context.packager import ContextPackager
from context.relevance_ranker import RankedFile, RelevanceRanker
from context.task_profile import RANKING_PROFILES, classify_retrieval_task
from contracts.intent_extraction import IntentExtractor
from contracts.repository_scope_classifier import RepositoryScopeClassifier
from contracts.task_classifier import TaskClassifier
from domain.contract import Contract
from domain.context_package import ContextPackage, PackagedFile
from domain.context_resolution import ContextResolutionResult
from domain.intent import UserIntent
from domain.versioning import LivingContract
from execution.context_goal_composer import ContextGoalComposer
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator
from infrastructure.llm_client import LiteLLMClient
from shared.errors import WorkspacePathError
from workspace.permissions import PermissionManager

GENERATION_MODEL = "gpt-4o-mini"
JUDGE_MODEL = GENERATION_MODEL
MAX_TOKENS_CONTEXT = 8000
MAX_TOKENS_ANSWER = 1200
MAX_TOKENS_JUDGE = 400
RESULTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "llm_grounding_validation"
_READ_ERRORS: tuple[type[Exception], ...] = (OSError, WorkspacePathError)

BENCHMARK_TASKS = [
    {
        "id": "task1_targeted_logic",
        "query": "How does Catalog.Register validate and handle node service metadata during registration?",
        "ground_truth_files": ["agent/consul/catalog_endpoint.go"],
        "ground_truth_terms": ["Catalog", "Register", "RegisterRequest"],
    },
    {
        "id": "task2_dependency_tracing",
        "query": "Trace how Agent cache updates propagate to downstream service check listeners.",
        "ground_truth_files": ["agent/cache/cache.go", "agent/cache/watch.go"],
        "ground_truth_terms": ["UpdateEvent", "Notify", "Cache"],
    },
    {
        "id": "task3_interface_type_contract",
        "query": "What fields are required when instantiating an Agent configuration struct?",
        "ground_truth_files": ["agent/config/config.go"],
        "ground_truth_terms": ["Config"],
    },
    {
        "id": "task4_refactoring_multifile",
        "query": "What functions directly call or depend on the ACL binding rule list endpoint?",
        "ground_truth_files": ["agent/consul/acl_endpoint.go", "agent/consul/auth/binder.go"],
        "ground_truth_terms": ["BindingRuleList", "ACLBindingRuleList", "binder"],
    },
    {
        "id": "task5_ambiguous_common_name",
        "query": "What is the primary responsibility of the New function inside the agent/cache package?",
        "ground_truth_files": ["agent/cache/cache.go"],
        "ground_truth_terms": ["Cache", "Options"],
    },
    {
        # Arm 4 (Enhanced Path-Hint & Locality Propagation, 2026-08-12):
        # deliberately targets this arm's exact blind spot in tasks
        # 1-5 -- every prior task's ground truth is the direct entry
        # point (PRIMARY tier, already score-saturated, which Arm 4's
        # boost structurally can never move). This task's ground truth
        # includes a SECONDARY file reached only via real call-graph
        # expansion from a SIBLING package, the one case Arm 4 can
        # actually affect. Not assumed -- directly grepped from the
        # real cloned Consul source: agent/cache/cache.go:970 defines
        # `Prepopulate`; agent/auto-config/tls.go:103 is the only real,
        # unambiguous (no name-collision, unlike "New") non-test caller
        # of Cache.Prepopulate specifically, in a sibling directory
        # under agent/ (agent/auto-config/ vs. agent/cache/, shared
        # parent "agent/").
        "id": "task6_path_hint_secondary_sibling",
        "query": (
            "How does the `agent/cache` package's Prepopulate method get used by sibling "
            "packages like agent/auto-config to seed cache entries before RPC results are "
            "available?"
        ),
        "ground_truth_files": ["agent/cache/cache.go", "agent/auto-config/tls.go"],
        "ground_truth_terms": ["Prepopulate", "Cache"],
    },
]

JUDGE_PROMPT_TEMPLATE = """You are grading an AI assistant's answer to a code-navigation question about the open-source project "{repo_name}".

Question: {query}

Ground-truth references (files/symbols a well-grounded answer should engage with, established directly from the real source, not from the assistant's answer):
{ground_truth}

Assistant's answer:
{answer}

Grade the answer on three criteria, each an integer 1-5:
- factual_grounding: Are the code references, type/function names, and logic paths factual and consistent with the ground truth? 1 = fabricated/hallucinated details, 5 = fully grounded, nothing invented.
- completeness: Does the answer fully address the question, given what a well-grounded answer covering the ground truth should include? 1 = missing the core of the question, 5 = fully answers it.
- conciseness: Is the answer focused, or does it wander into irrelevant detail / padding? 1 = bloated/unfocused, 5 = tight and on-topic.

Respond with ONLY a JSON object, no other text:
{{"factual_grounding": <int>, "completeness": <int>, "conciseness": <int>, "rationale": "<one sentence>"}}
"""


async def _stream_complete(
    prompt: str, model: str, max_tokens: int, temperature: float = 0.0
) -> dict:
    """Script-local streaming helper for TTFT -- see module docstring.
    Returns content/usage/timing in the same shape LiteLLMClient.complete
    uses, plus ttft_seconds (None if the stream produced zero content
    chunks, e.g. an immediate error)."""
    start = time.perf_counter()
    first_token_time: float | None = None
    chunks: list[str] = []
    prompt_tokens = completion_tokens = total_tokens = 0

    stream = await litellm.acompletion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
        stream_options={"include_usage": True},
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            if first_token_time is None:
                first_token_time = time.perf_counter()
            chunks.append(delta)
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
            total_tokens = usage.total_tokens

    end = time.perf_counter()
    return {
        "content": "".join(chunks),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "ttft_seconds": round(first_token_time - start, 3) if first_token_time else None,
        "total_latency_seconds": round(end - start, 3),
    }


def _greedy_full_file_package(
    result: ContextResolutionResult,
    ranked: list[RankedFile],
    permissions: PermissionManager,
    token_estimator: CostEstimator,
) -> ContextPackage:
    """Arm B's packaging policy -- see module docstring."""
    packaged: list[PackagedFile] = []
    used = 0
    excluded = 0
    for r in ranked:
        remaining = MAX_TOKENS_CONTEXT - used
        if remaining <= 0:
            excluded += 1
            continue
        try:
            content = permissions.safe_read_text(r.file_path)
        except _READ_ERRORS:
            excluded += 1
            continue
        tokens = token_estimator.count_tokens(content, GENERATION_MODEL)
        if tokens > remaining:
            excluded += 1
            continue
        packaged.append(
            PackagedFile(
                file_path=r.file_path,
                content=content,
                relevance_score=r.relevance_score,
                reason=r.reason,
                token_count=tokens,
                truncated=False,
            )
        )
        used += tokens

    raw_tokens = result.token_estimate.raw_context_tokens
    compression_ratio = round(raw_tokens / used, 4) if used else 0.0
    return ContextPackage(
        contract_id=result.contract_id,
        workspace_id=result.workspace_id,
        context_resolution_id=result.id,
        relevant_files=packaged,
        dependency_chain=result.dependency_chain,
        budget_max_tokens=MAX_TOKENS_CONTEXT,
        budget_used_tokens=used,
        prompt_compression_ratio=compression_ratio,
        excluded_file_count=excluded,
    )


def _file_overlap_metrics(packaged_files: list[str], ground_truth_files: list[str]) -> dict:
    """Deterministic retrieval-accuracy check -- set-overlap precision/
    recall/F1 of the actually PACKAGED files against ground truth, as
    opposed to _key_term_check's check of the generated answer text."""
    packaged_set = set(packaged_files)
    truth_set = set(ground_truth_files)
    hits = packaged_set & truth_set
    precision = round(len(hits) / len(packaged_set), 3) if packaged_set else 0.0
    recall = round(len(hits) / len(truth_set), 3) if truth_set else 0.0
    f1 = round(2 * precision * recall / (precision + recall), 3) if (precision + recall) else 0.0
    return {
        "hits": sorted(hits),
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _key_term_check(answer: str, ground_truth_files: list[str], ground_truth_terms: list[str]) -> dict:
    """Deterministic reference-assertion check -- independent of and a
    sanity check against the LLM judge's factual_grounding score."""
    answer_lower = answer.lower()
    file_hits = [
        f for f in ground_truth_files
        if Path(f).name.lower() in answer_lower or f.lower() in answer_lower
    ]
    term_hits = [t for t in ground_truth_terms if t.lower() in answer_lower]
    total = len(ground_truth_files) + len(ground_truth_terms)
    hit_count = len(file_hits) + len(term_hits)
    return {
        "file_hits": file_hits,
        "term_hits": term_hits,
        "hit_rate": round(hit_count / total, 3) if total else 0.0,
    }


async def _judge(
    client: LiteLLMClient, repo_name: str, query: str, ground_truth_files: list[str],
    ground_truth_terms: list[str], answer: str,
) -> dict:
    ground_truth = "Files: " + ", ".join(ground_truth_files) + "\nTerms: " + ", ".join(ground_truth_terms)
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        repo_name=repo_name, query=query, ground_truth=ground_truth, answer=answer[:6000]
    )
    response = await client.complete(
        prompt, JUDGE_MODEL, max_tokens=MAX_TOKENS_JUDGE,
        response_format={"type": "json_object"}, temperature=0.0,
    )
    try:
        scores = json.loads(response.content)
    except json.JSONDecodeError:
        return {"error": "judge_response_not_valid_json", "raw": response.content}
    return scores


async def _arm_a_arcf(
    root: Path, query: str, entities: list[str], contract: Contract,
    service: CodeIntelligenceContractService, living: LivingContract,
) -> dict:
    start = time.perf_counter()
    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)), target_names=entities, workspace_root=str(root),
        resolver_strategy="classic", enable_anchor_classification=True,
        enable_confidence_propagation=True,
    )
    resolve_elapsed = time.perf_counter() - start

    scope = RepositoryScopeClassifier().classify(query)
    task_classifier_task = TaskClassifier().classify(query)
    retrieval_task_type = classify_retrieval_task(query, task_classifier_task, scope.task_type)
    ranking_profile = RANKING_PROFILES[retrieval_task_type]

    packager = ContextPackager(RelevanceRanker(), CostEstimator())
    package, _ = await packager.package(
        resolution, query, MAX_TOKENS_CONTEXT, ranking_profile, task_type=retrieval_task_type
    )

    prompt = ContextGoalComposer().compose(contract, package, resolution)
    completion = await _stream_complete(prompt, GENERATION_MODEL, MAX_TOKENS_ANSWER)

    return {
        "arm": "arcf",
        "answer": completion["content"],
        "prompt_tokens": completion["prompt_tokens"],
        "completion_tokens": completion["completion_tokens"],
        "total_tokens": completion["total_tokens"],
        "ttft_seconds": completion["ttft_seconds"],
        "generation_latency_seconds": completion["total_latency_seconds"],
        "resolve_latency_seconds": round(resolve_elapsed, 3),
        "candidate_count": len(resolution.candidate_files),
        "packaged_file_count": len(package.relevant_files),
        "packaged_tokens": package.budget_used_tokens,
        "excluded_count": package.excluded_file_count,
        "packaged_files": [f.file_path for f in package.relevant_files],
    }


async def _arm_b_baseline(
    root: Path, query: str, entities: list[str], contract: Contract,
    service: CodeIntelligenceContractService, living: LivingContract,
) -> dict:
    start = time.perf_counter()
    _, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)), target_names=entities, workspace_root=str(root),
        resolver_strategy="classic",
    )
    resolve_elapsed = time.perf_counter() - start

    ranked = RelevanceRanker().rank(resolution)
    permissions = PermissionManager(root)
    token_estimator = CostEstimator()
    package = _greedy_full_file_package(resolution, ranked, permissions, token_estimator)

    prompt = ContextGoalComposer().compose(contract, package, resolution)
    completion = await _stream_complete(prompt, GENERATION_MODEL, MAX_TOKENS_ANSWER)

    return {
        "arm": "baseline_raw",
        "answer": completion["content"],
        "prompt_tokens": completion["prompt_tokens"],
        "completion_tokens": completion["completion_tokens"],
        "total_tokens": completion["total_tokens"],
        "ttft_seconds": completion["ttft_seconds"],
        "generation_latency_seconds": completion["total_latency_seconds"],
        "resolve_latency_seconds": round(resolve_elapsed, 3),
        "candidate_count": len(resolution.candidate_files),
        "packaged_file_count": len(package.relevant_files),
        "packaged_tokens": package.budget_used_tokens,
        "excluded_count": package.excluded_file_count,
        "packaged_files": [f.file_path for f in package.relevant_files],
    }


async def _arm_c_direct(repo_name: str, query: str) -> dict:
    prompt = (
        f"Question about the open-source project {repo_name}: {query}\n\n"
        "Answer from your own knowledge of this project."
    )
    completion = await _stream_complete(prompt, GENERATION_MODEL, MAX_TOKENS_ANSWER)
    return {
        "arm": "zero_context",
        "answer": completion["content"],
        "prompt_tokens": completion["prompt_tokens"],
        "completion_tokens": completion["completion_tokens"],
        "total_tokens": completion["total_tokens"],
        "ttft_seconds": completion["ttft_seconds"],
        "generation_latency_seconds": completion["total_latency_seconds"],
    }


async def _run_one_task(
    root: Path, repo_name: str, task: dict, client: LiteLLMClient,
    service: CodeIntelligenceContractService, contract_store: InMemoryContractStore,
) -> dict:
    query = task["query"]
    print(f"\n[{task['id']}] extracting entities...")
    extractor = IntentExtractor(client, model=GENERATION_MODEL)
    raw, _ = await extractor.extract(query)
    entities = list(raw.entities)
    intent = UserIntent(
        raw_request=query, intent=raw.intent_summary, domain=raw.domain, task=raw.task,
        entities=entities, confidence=raw.self_reported_confidence,
    )
    print(f"[{task['id']}] entities: {entities or '(none)'}")

    results: dict[str, dict] = {}

    for arm_name in ("arcf", "baseline_raw", "zero_context"):
        try:
            if arm_name == "arcf":
                living = LivingContract(contract=Contract(intent=intent))
                contract_store.save(living)
                contract = Contract(id=uuid4(), intent=intent)
                results[arm_name] = await _arm_a_arcf(
                    root, query, entities, contract, service, living
                )
            elif arm_name == "baseline_raw":
                living = LivingContract(contract=Contract(intent=intent))
                contract_store.save(living)
                contract = Contract(id=uuid4(), intent=intent)
                results[arm_name] = await _arm_b_baseline(
                    root, query, entities, contract, service, living
                )
            else:
                results[arm_name] = await _arm_c_direct(repo_name, query)
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed silently
            results[arm_name] = {
                "arm": arm_name, "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
            print(f"[{task['id']}] {arm_name} FAILED: {exc}")
            continue
        print(f"[{task['id']}] {arm_name} generated ({results[arm_name].get('total_tokens', '?')} tokens)")

    for arm_name, result in results.items():
        if "error" in result:
            result["key_term_check"] = None
            result["file_overlap"] = None
            result["judge"] = None
            continue
        result["key_term_check"] = _key_term_check(
            result["answer"], task["ground_truth_files"], task["ground_truth_terms"]
        )
        result["file_overlap"] = _file_overlap_metrics(
            result.get("packaged_files", []), task["ground_truth_files"]
        )
        try:
            result["judge"] = await _judge(
                client, repo_name, query, task["ground_truth_files"],
                task["ground_truth_terms"], result["answer"],
            )
        except Exception as exc:  # noqa: BLE001
            result["judge"] = {"error": f"{type(exc).__name__}: {exc}"}
        print(f"[{task['id']}] {arm_name} judged: {result['judge']}")

    return {"task_id": task["id"], "query": query, "entities": entities, "results": results}


def _fmt(value) -> str:
    return "-" if value is None else str(value)


def _mean_std(values: list[float]) -> tuple[float | None, float | None]:
    """Population stddev (not sample) so a single-run n_runs=1 invocation
    degrades to stddev=0.0 instead of raising StatisticsError."""
    if not values:
        return None, None
    mean = round(statistics.mean(values), 3)
    std = round(statistics.pstdev(values), 3) if len(values) > 1 else 0.0
    return mean, std


def _fmt_mean_std(values: list[float]) -> str:
    mean, std = _mean_std(values)
    return "-" if mean is None else f"{mean} ± {std}"


def _extract_run_metrics(result: dict) -> dict[str, float | None]:
    """Pulls the Task-1 grounding metrics + budget utilization out of a
    single arm's single-run result dict, for cross-run aggregation."""
    overlap = result.get("file_overlap") or {}
    key_term = result.get("key_term_check") or {}
    packaged_tokens = result.get("packaged_tokens")
    budget_utilization = (
        round(packaged_tokens / MAX_TOKENS_CONTEXT, 3) if packaged_tokens is not None else None
    )
    return {
        "precision": overlap.get("precision"),
        "recall": overlap.get("recall"),
        "f1": overlap.get("f1"),
        "budget_utilization": budget_utilization,
        "key_term_score": key_term.get("hit_rate"),
    }


_METRIC_LABELS = {
    "precision": "File Precision",
    "recall": "File Recall",
    "f1": "File F1",
    "budget_utilization": "Context Budget Utilization",
    "key_term_score": "Key-Term Hit Rate",
}


def _build_markdown_table(all_task_results: list[dict]) -> str:
    """all_task_results: list of {"task_id", "query", "runs": [task_result, ...]}
    where each task_result is one _run_one_task() call's return value (one
    pass). Every metric is reported as mean ± stddev across the n_runs
    passes for that task/arm, to surface LLM/SLM-1 non-determinism rather
    than hide it behind a single-sample number."""
    lines = [
        "| Task | Metric | Arm A (ARCF) | Arm B (Raw Baseline) | Arm C (Zero Context) |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    arm_keys = ["arcf", "baseline_raw", "zero_context"]
    metric_names = ["precision", "recall", "f1", "budget_utilization", "key_term_score"]
    overall_metric_values: dict[str, dict[str, list[float]]] = {
        arm: {m: [] for m in metric_names} for arm in arm_keys
    }
    overall_grounding: dict[str, list[float]] = {k: [] for k in arm_keys}
    overall_composite: dict[str, list[float]] = {k: [] for k in arm_keys}

    for task_result in all_task_results:
        task_id = task_result["task_id"]
        runs = task_result["runs"]
        n_runs = len(runs)

        status_row = [task_id, f"Runs OK (of {n_runs})"]
        tokens_row = ["", "Prompt Tokens / TTFT(s) / Latency(s), mean ± stddev"]
        score_row = ["", "Grounding / Completeness / Conciseness, mean ± stddev"]
        metric_rows = {m: ["", f"{_METRIC_LABELS[m]}, mean ± stddev"] for m in metric_names}

        for arm in arm_keys:
            arm_results = [run["results"].get(arm, {}) for run in runs]
            ok_results = [r for r in arm_results if "error" not in r]
            status_row.append(f"{len(ok_results)}/{n_runs}")

            prompt_tokens = [r["prompt_tokens"] for r in ok_results if r.get("prompt_tokens") is not None]
            ttft = [r["ttft_seconds"] for r in ok_results if r.get("ttft_seconds") is not None]
            latency = [
                r["generation_latency_seconds"] for r in ok_results
                if r.get("generation_latency_seconds") is not None
            ]
            tokens_row.append(
                f"{_fmt_mean_std(prompt_tokens)} / {_fmt_mean_std(ttft)} / {_fmt_mean_std(latency)}"
            )

            fg_vals, cm_vals, cc_vals = [], [], []
            for r in ok_results:
                judge = r.get("judge") or {}
                fg, cm, cc = judge.get("factual_grounding"), judge.get("completeness"), judge.get("conciseness")
                if isinstance(fg, (int, float)):
                    fg_vals.append(fg)
                    overall_grounding[arm].append(fg)
                if isinstance(cm, (int, float)):
                    cm_vals.append(cm)
                if isinstance(cc, (int, float)):
                    cc_vals.append(cc)
                if isinstance(fg, (int, float)) and isinstance(cm, (int, float)) and isinstance(cc, (int, float)):
                    overall_composite[arm].append((fg + cm + cc) / 3)
            score_row.append(f"{_fmt_mean_std(fg_vals)} / {_fmt_mean_std(cm_vals)} / {_fmt_mean_std(cc_vals)}")

            run_metrics_list = [_extract_run_metrics(r) for r in ok_results]
            for m in metric_names:
                values = [rm[m] for rm in run_metrics_list if rm.get(m) is not None]
                overall_metric_values[arm][m].extend(values)
                metric_rows[m].append(_fmt_mean_std(values))

        lines.append("| " + " | ".join(status_row) + " |")
        lines.append("| " + " | ".join(tokens_row) + " |")
        lines.append("| " + " | ".join(score_row) + " |")
        for m in metric_names:
            lines.append("| " + " | ".join(metric_rows[m]) + " |")

    overall_row = ["**Overall**", "**Avg. Grounding / Avg. Composite (mean ± stddev)**"]
    for arm in arm_keys:
        overall_row.append(
            f"**{_fmt_mean_std(overall_grounding[arm])} / {_fmt_mean_std(overall_composite[arm])}**"
        )
    lines.append("| " + " | ".join(overall_row) + " |")

    for m in metric_names:
        metric_overall_row = ["**Overall**", f"**{_METRIC_LABELS[m]} (mean ± stddev)**"]
        for arm in arm_keys:
            metric_overall_row.append(f"**{_fmt_mean_std(overall_metric_values[arm][m])}**")
        lines.append("| " + " | ".join(metric_overall_row) + " |")

    return "\n".join(lines)


def _full_registry() -> LanguageRegistry:
    return LanguageRegistry([GoLanguageAnalyzer()])


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--repo-name", required=True)
    parser.add_argument(
        "--n-runs", type=int, default=3,
        help=(
            "Number of times to repeat each benchmark task (default: 3). "
            "SLM-1 entity extraction is non-deterministic in content even at "
            "temperature=0.0 (see PROGRESS.md); repeating runs and reporting "
            "mean +/- stddev surfaces that noise instead of hiding it behind "
            "a single-sample score."
        ),
    )
    args = parser.parse_args()
    if args.n_runs < 1:
        parser.error("--n-runs must be >= 1")
    root = Path(args.repo_path)

    client = LiteLLMClient(max_retries=3, base_delay_seconds=0.5)
    engine = CodeIntelligenceEngine(_full_registry(), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )

    all_task_results = []
    for task in BENCHMARK_TASKS:
        runs = []
        for run_idx in range(args.n_runs):
            print(f"\n=== {task['id']} — run {run_idx + 1}/{args.n_runs} ===")
            runs.append(
                await _run_one_task(root, args.repo_name, task, client, service, contract_store)
            )
        all_task_results.append({"task_id": task["id"], "query": task["query"], "runs": runs})

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RESULTS_DIR / f"{args.repo_name}_grounding_validation.json"
    raw_path.write_text(json.dumps(all_task_results, indent=2), encoding="utf-8")

    table = _build_markdown_table(all_task_results)
    table_path = RESULTS_DIR / f"{args.repo_name}_grounding_validation_summary.md"
    table_path.write_text(table + "\n", encoding="utf-8")

    print("\n\n" + "=" * 80)
    print(table)
    print("=" * 80)
    print(f"\nRaw results: {raw_path}")
    print(f"Summary table: {table_path}")


if __name__ == "__main__":
    asyncio.run(main())
