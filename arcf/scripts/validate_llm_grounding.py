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
    uv run python scripts/validate_llm_grounding.py --repo-path <path> --repo-name consul
"""

from __future__ import annotations

import argparse
import asyncio
import json
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
    package, _ = await packager.package(resolution, query, MAX_TOKENS_CONTEXT, ranking_profile)

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
            result["judge"] = None
            continue
        result["key_term_check"] = _key_term_check(
            result["answer"], task["ground_truth_files"], task["ground_truth_terms"]
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


def _build_markdown_table(all_task_results: list[dict]) -> str:
    lines = [
        "| Task | Metric | Arm A (ARCF) | Arm B (Raw Baseline) | Arm C (Zero Context) |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    arm_keys = ["arcf", "baseline_raw", "zero_context"]
    totals: dict[str, list[float]] = {k: [] for k in arm_keys}
    grounding_totals: dict[str, list[float]] = {k: [] for k in arm_keys}

    for task_result in all_task_results:
        task_id = task_result["task_id"]
        results = task_result["results"]

        tokens_row = [task_id, "Prompt Tokens / TTFT(s) / Total Latency(s)"]
        score_row = ["", "Grounding / Completeness / Conciseness"]
        for arm in arm_keys:
            r = results.get(arm, {})
            if "error" in r:
                tokens_row.append("ERROR")
                score_row.append("ERROR")
                continue
            tokens_row.append(
                f"{_fmt(r.get('prompt_tokens'))} / {_fmt(r.get('ttft_seconds'))} / "
                f"{_fmt(r.get('generation_latency_seconds'))}"
            )
            judge = r.get("judge") or {}
            if "error" in judge:
                score_row.append("judge error")
            else:
                fg, cm, cc = judge.get("factual_grounding"), judge.get("completeness"), judge.get("conciseness")
                score_row.append(f"{_fmt(fg)} / {_fmt(cm)} / {_fmt(cc)}")
                if isinstance(fg, (int, float)):
                    grounding_totals[arm].append(fg)
                    totals[arm].append((fg + (cm or 0) + (cc or 0)) / 3)

        lines.append("| " + " | ".join(tokens_row) + " |")
        lines.append("| " + " | ".join(score_row) + " |")

    overall_row = ["**Overall**", "**Avg. Grounding / Avg. Composite Score**"]
    for arm in arm_keys:
        g = grounding_totals[arm]
        t = totals[arm]
        avg_g = round(sum(g) / len(g), 2) if g else None
        avg_t = round(sum(t) / len(t), 2) if t else None
        overall_row.append(f"**{_fmt(avg_g)} / {_fmt(avg_t)}**")
    lines.append("| " + " | ".join(overall_row) + " |")

    return "\n".join(lines)


def _full_registry() -> LanguageRegistry:
    return LanguageRegistry([GoLanguageAnalyzer()])


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--repo-name", required=True)
    args = parser.parse_args()
    root = Path(args.repo_path)

    client = LiteLLMClient(max_retries=3, base_delay_seconds=0.5)
    engine = CodeIntelligenceEngine(_full_registry(), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )

    all_task_results = []
    for task in BENCHMARK_TASKS:
        task_result = await _run_one_task(root, args.repo_name, task, client, service, contract_store)
        all_task_results.append(task_result)

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
