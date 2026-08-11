"""repo_query_answer.py — full pipeline, repo/query/language-agnostic: real
SLM-1 intent extraction -> code intelligence / context resolution (BOTH
"classic" and "drp" resolver_strategy) -> context packaging -> a real LLM
answer, for one repo + one free-text query with NO known ground-truth
target file.

Unlike scripts/drp_benchmark.py (resolver-only diagnostics against a KNOWN
--target-file, never calls a final-generation LLM) and
scripts/direct_vs_arcf_conceptual_query.py (classic-only, single hardcoded
--language), this script is for the 50-repo/200-query evaluation batch,
where queries are open-ended ("Explain how X discovers test cases") with
no known correct file — so answer quality has to be judged by reading the
generated text, not a retrieval-rank number. It therefore:

- Uses the FULL LanguageRegistry (every analyzer this codebase has,
  including cpp_analyzer/rust_analyzer) rather than a single --language
  flag, so a repo doesn't need a single "dominant" language declared up
  front and mixed-language repos are handled the same way production
  (interfaces/api/app.py's own registry) already does — files with no
  matching analyzer are simply skipped, not an error.
- Runs the SAME query through resolver_strategy="classic" AND "drp" and
  packages+generates an answer for each, so the two are directly
  comparable (packaging/prompting logic is identical for both — only the
  ContextResolutionResult differs), following the same "one pipeline,
  two resolvers" discipline drp_benchmark.py's docstring establishes.
- Catches and records a resolver failure independently per strategy
  (rather than letting one strategy's exception abort the other), since
  the point of this script is finding issues, not stopping at the first
  one.
- Also runs a "direct" arm — the query alone, no repo context at all,
  same GENERATION_MODEL — so every result can be judged against what the
  model already knows from training, not just against ARCF's other
  resolver strategy. Without this control, a good-looking ARCF answer on
  a famous open-source project (which GENERATION_MODEL may have memorized
  outright) proves nothing about whether ARCF's retrieved context is
  actually doing any work. Mirrors direct_vs_arcf_conceptual_query.py's
  `_direct_llm`.
- Uses ARCF's REAL production packaging/prompting classes
  (`context.packager.ContextPackager`, `execution.context_goal_composer.
  ContextGoalComposer`, `execution.final_generation.FinalGenerationRunner`)
  rather than a hand-rolled prompt. An earlier version of this script
  hand-rolled a prompt copied from direct_vs_arcf_conceptual_query.py
  (itself a deliberate A/B-isolation experiment) that told the model to
  use ONLY the provided files and explicitly refuse to fill gaps from
  general knowledge — appropriate for isolating retrieval quality in that
  experiment, but NOT how ARCF's actual ContextGoalComposer prompts in
  production: its own template never forbids general knowledge, it just
  presents the deterministically-selected context and asks for the best
  answer. The hand-rolled version made weak retrieval look artificially
  worse than a plain direct-LLM call with no context at all, which
  doesn't reflect what ARCF would really say to a user.

Usage:
    uv run python scripts/repo_query_answer.py \\
        --repo-path <path> --repo-name <name> --query "<query text>" \\
        [--resolver classic|drp|both] [--skip-direct]

`--query` is repeatable (`--query "Q1" --query "Q2" ...`) to run several
queries against the same already-cloned repo in one process. This isn't
just convenience: `_resolve_and_answer` builds a `CodeIntelligenceEngine`/
`CodeIntelligenceIndex` per call, and both `resolver_strategy` values
independently re-parse the whole repo (service.py's `_resolve` and
`_resolve_drp` each call `build_index`) — against an immutable clone,
every one of those parses after the first is redundant work, not a
different answer. `main()` now builds one `service`/`index_cache` for
the whole process and passes the SAME `index_cache` dict into every
`attach_code_intelligence` call (both resolver strategies, every query),
so only the first resolution against a given root actually parses;
everything after reuses it via the opt-in `index_cache` parameter
(defaulted to `None` everywhere else — see its docstring on
`CodeIntelligenceContractService.attach_code_intelligence`). Per-query
output files and their JSON shape are unchanged — one file per query,
same keys — so this doesn't affect anything already reading
`docs/repo_query_answers/*.json`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import traceback
from pathlib import Path
from uuid import UUID

from code_intelligence.engine import CodeIntelligenceEngine
from code_intelligence.languages.cpp_analyzer import CppLanguageAnalyzer
from code_intelligence.languages.csharp_analyzer import CSharpLanguageAnalyzer
from code_intelligence.languages.go_analyzer import GoLanguageAnalyzer
from code_intelligence.languages.java_analyzer import JavaLanguageAnalyzer
from code_intelligence.languages.kotlin_analyzer import KotlinLanguageAnalyzer
from code_intelligence.languages.python_analyzer import PythonLanguageAnalyzer
from code_intelligence.languages.rust_analyzer import RustLanguageAnalyzer
from code_intelligence.languages.typescript_analyzer import TypeScriptLanguageAnalyzer
from code_intelligence.registry import LanguageRegistry
from code_intelligence.service import CodeIntelligenceContractService
from context.packager import ContextPackager
from context.relevance_ranker import RelevanceRanker
from context.task_profile import RANKING_PROFILES, classify_retrieval_task
from contracts.intent_extraction import IntentExtractor
from contracts.repository_scope_classifier import RepositoryScopeClassifier
from contracts.task_classifier import TaskClassifier
from domain.contract import Contract
from domain.enums import ArtifactKind
from domain.intent import UserIntent
from domain.versioning import LivingContract
from execution.context_goal_composer import ContextGoalComposer
from execution.final_generation import FinalGenerationRunner
from infrastructure.context_resolution_store import InMemoryContextResolutionStore
from infrastructure.contract_store import InMemoryContractStore
from infrastructure.cost import CostEstimator
from infrastructure.llm_client import LiteLLMClient

GENERATION_MODEL = "gpt-4o-mini"
MAX_TOKENS_CONTEXT = 8000
MAX_TOKENS_ANSWER = 1200
RESULTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "repo_query_answers"


async def _direct_llm(client: LiteLLMClient, repo_name: str, query: str) -> dict:
    prompt = (
        f"Question about the open-source project {repo_name}: {query}\n\n"
        "Answer from your own knowledge of this project."
    )
    response = await client.complete(prompt, GENERATION_MODEL, MAX_TOKENS_ANSWER)
    return {
        "answer": response.content,
        "prompt_tokens": response.prompt_tokens,
        "completion_tokens": response.completion_tokens,
        "total_tokens": response.total_tokens,
    }


def _full_registry() -> LanguageRegistry:
    # Every analyzer this codebase has — matches production wiring
    # (interfaces/api/app.py), not a single --language guess. A file with
    # no matching analyzer is silently skipped by the engine, same as
    # today's production behavior for any unsupported file.
    return LanguageRegistry(
        [
            PythonLanguageAnalyzer(),
            TypeScriptLanguageAnalyzer(),
            GoLanguageAnalyzer(),
            JavaLanguageAnalyzer(),
            CSharpLanguageAnalyzer(),
            KotlinLanguageAnalyzer(),
            CppLanguageAnalyzer(),
            RustLanguageAnalyzer(),
        ]
    )


async def _resolve_and_answer(
    root: Path,
    query: str,
    entities: list[str],
    intent: UserIntent,
    client: LiteLLMClient,
    resolver_strategy: str,
    service: CodeIntelligenceContractService,
    contract_store: InMemoryContractStore,
    index_cache: dict,
) -> dict:
    living = LivingContract(contract=Contract(intent=intent))
    contract_store.save(living)

    # resolver_strategy="drp" bypasses/ignores anchor-classification and
    # confidence-propagation entirely (see service.py's own docstring) —
    # only pass them for "classic", matching every existing script's
    # "final validated configuration" for that strategy.
    classic_flags = (
        {"enable_anchor_classification": True, "enable_confidence_propagation": True}
        if resolver_strategy == "classic"
        else {}
    )

    start = asyncio.get_event_loop().time()
    updated_living, resolution = await service.attach_code_intelligence(
        UUID(str(living.contract_id)),
        target_names=entities,
        workspace_root=str(root),
        resolver_strategy=resolver_strategy,
        index_cache=index_cache,
        **classic_flags,
    )
    resolve_elapsed = asyncio.get_event_loop().time() - start

    scope = RepositoryScopeClassifier().classify(query)
    task_classifier_task = TaskClassifier().classify(query)
    retrieval_task_type = classify_retrieval_task(query, task_classifier_task, scope.task_type)
    ranking_profile = RANKING_PROFILES[retrieval_task_type]

    # Real Phase 6 packaging (RelevanceRanker -> ContextBudgetManager),
    # not a hand-rolled reimplementation of it.
    packager = ContextPackager(RelevanceRanker(), CostEstimator())
    package, _ = await packager.package(resolution, query, MAX_TOKENS_CONTEXT, ranking_profile)

    # Real Phase 8 prompt assembly + generation — no "ONLY use the
    # provided files" instruction here; ContextGoalComposer's own
    # template just presents the context and asks for the best answer,
    # same as production would.
    runner = FinalGenerationRunner(
        ContextGoalComposer(), client, GENERATION_MODEL, max_tokens=MAX_TOKENS_ANSWER
    )
    gen_start = asyncio.get_event_loop().time()
    artifact, completion = await runner.generate(
        updated_living.contract, package, resolution, kind=ArtifactKind.EXPLANATION
    )
    gen_elapsed = asyncio.get_event_loop().time() - gen_start

    return {
        "resolver_strategy": resolver_strategy,
        "answer": artifact.content,
        "prompt_tokens": completion.prompt_tokens,
        "completion_tokens": completion.completion_tokens,
        "total_tokens": completion.total_tokens,
        "candidate_count": len(resolution.candidate_files),
        "phase5_tokens": resolution.token_estimate.selected_context_tokens,
        "packaged_file_count": len(package.relevant_files),
        "packaged_tokens": package.budget_used_tokens,
        "excluded_count": package.excluded_file_count,
        "packaged_files": [f.file_path for f in package.relevant_files],
        "resolve_latency_seconds": round(resolve_elapsed, 3),
        "generation_latency_seconds": round(gen_elapsed, 3),
        "resolution_reason": resolution.resolution_reason,
    }


async def _run_one_query(
    root: Path,
    repo_name: str,
    query: str,
    resolver: str,
    skip_direct: bool,
    client: LiteLLMClient,
    service: CodeIntelligenceContractService,
    contract_store: InMemoryContractStore,
    index_cache: dict,
) -> None:
    extractor = IntentExtractor(client, model=GENERATION_MODEL)
    raw, _ = await extractor.extract(query)
    entities = list(raw.entities)
    intent = UserIntent(
        raw_request=query,
        intent=raw.intent_summary,
        domain=raw.domain,
        task=raw.task,
        entities=entities,
        confidence=raw.self_reported_confidence,
    )
    print(f"[{repo_name}] entities_extracted: {entities or '(none)'}")

    strategies = ["classic", "drp"] if resolver == "both" else [resolver]
    results: dict[str, dict] = {}
    if not skip_direct:
        try:
            results["direct"] = await _direct_llm(client, repo_name, query)
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed silently
            results["direct"] = {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
    for strategy in strategies:
        try:
            results[strategy] = await _resolve_and_answer(
                root, query, entities, intent, client, strategy, service, contract_store, index_cache
            )
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed silently
            results[strategy] = {
                "resolver_strategy": strategy,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }

    output = {
        "query": query,
        "repo": repo_name,
        "entities_extracted": entities,
        "results": results,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_query = "".join(c if c.isalnum() else "_" for c in query[:60])
    results_file = RESULTS_DIR / f"{repo_name}__{safe_query}.json"
    results_file.write_text(json.dumps(output, indent=2), encoding="utf-8")

    for strategy, result in results.items():
        print(f"\n=== [{repo_name}] {strategy.upper()} ===")
        if "error" in result:
            print(f"ERROR: {result['error']}")
            continue
        if strategy == "direct":
            print(result["answer"])
            print(f"\n[tokens: prompt={result['prompt_tokens']} completion={result['completion_tokens']}]")
            continue
        print(f"Packaged files: {result['packaged_files']}")
        print(
            f"Candidates: {result['candidate_count']}, "
            f"packaged: {result['packaged_file_count']}, tokens: {result['packaged_tokens']}"
        )
        print(result["answer"])
        print(
            f"\n[tokens: prompt={result['prompt_tokens']} completion={result['completion_tokens']}] "
            f"[latency: resolve={result['resolve_latency_seconds']}s "
            f"generation={result['generation_latency_seconds']}s]"
        )

    print(f"\nWritten to {results_file}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--repo-name", required=True)
    parser.add_argument(
        "--query",
        required=True,
        action="append",
        help="Repeatable — pass multiple --query flags to run several queries "
        "against the same repo in one process, reusing one parsed index.",
    )
    parser.add_argument("--resolver", choices=["classic", "drp", "both"], default="both")
    parser.add_argument("--skip-direct", action="store_true")
    args = parser.parse_args()
    root = Path(args.repo_path)

    client = LiteLLMClient(max_retries=3, base_delay_seconds=0.5)

    # Built ONCE for the whole process (all queries, both resolver
    # strategies) — `index_cache` is the opt-in cache `_resolve`/
    # `_resolve_drp` (service.py) key by resolved workspace root, so the
    # first resolution against this (immutable, already-cloned) root
    # parses it and every later call this process makes reuses that
    # parse. See this module's docstring for why that redundant work
    # existed before this change.
    engine = CodeIntelligenceEngine(_full_registry(), CostEstimator())
    contract_store = InMemoryContractStore()
    service = CodeIntelligenceContractService(
        engine, contract_store, InMemoryContextResolutionStore()
    )
    index_cache: dict = {}

    for query in args.query:
        await _run_one_query(
            root,
            args.repo_name,
            query,
            args.resolver,
            args.skip_direct,
            client,
            service,
            contract_store,
            index_cache,
        )


if __name__ == "__main__":
    asyncio.run(main())
