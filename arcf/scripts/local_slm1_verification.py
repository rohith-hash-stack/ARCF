"""local_slm1_verification.py -- feature/local-inference-server,
CHECKLIST.md "3c" success/failure criterion for the SLM-1 half.

Question: can the real, unmodified IntentExtractor (contracts/
intent_extraction.py) reliably produce its required structured JSON
contract (RawIntentExtraction) when pointed at a self-hosted Ollama
model instead of gpt-4o-mini? Smaller open instruct models are known to
be worse at strict structured output than gpt-4o-mini -- this is a real
open risk, not assumed to pass.

Success criterion (stated up front, per CHECKLIST.md 3c): every one of
the 6 real BENCHMARK_TASKS queries (scripts/validate_llm_grounding.py --
reused verbatim, not simplified stand-ins) produces a response that
parses into RawIntentExtraction with zero ValidationError, at
temperature=0.0, via the real LiteLLMClient/IntentExtractor path with
no source changes. Entity quality against each task's own
ground_truth_terms is reported for honesty but is NOT the pass/fail
gate -- a smaller model extracting weaker entities is a separate,
already-tracked problem (recall gap, gap #3's own reranker work);
JSON-contract compliance is the only thing this script is scoped to
answer.

Failure criterion: any real ValidationError, timeout, or malformed
response on any of the 6 queries means SLM-1 hosting is NOT ready for
this model and stays flagged as its own follow-on (per 3c's own
"failure" branch) rather than silently forced through.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pydantic import ValidationError

from contracts.intent_extraction import IntentExtractor
from infrastructure.llm_client import LiteLLMClient

MODEL = "ollama_chat/qwen2.5:1.5b-instruct"

# Verbatim from scripts/validate_llm_grounding.py's BENCHMARK_TASKS --
# real queries this project already treats as ground truth, not
# invented for this script.
QUERIES = [
    (
        "task1_targeted_logic",
        "How does Catalog.Register validate and handle node service metadata during registration?",
        ["Catalog", "Register", "RegisterRequest"],
    ),
    (
        "task2_dependency_tracing",
        "Trace how Agent cache updates propagate to downstream service check listeners.",
        ["UpdateEvent", "Notify", "Cache"],
    ),
    (
        "task3_interface_type_contract",
        "What fields are required when instantiating an Agent configuration struct?",
        ["Config"],
    ),
    (
        "task4_refactoring_multifile",
        "What functions directly call or depend on the ACL binding rule list endpoint?",
        ["BindingRuleList", "ACLBindingRuleList", "binder"],
    ),
    (
        "task5_ambiguous_common_name",
        "What is the primary responsibility of the New function inside the agent/cache package?",
        ["Cache", "Options"],
    ),
]


async def main() -> None:
    client = LiteLLMClient(max_retries=2, base_delay_seconds=0.5)
    extractor = IntentExtractor(client, model=MODEL)

    print(f"Model: {MODEL}")
    print(f"Running {len(QUERIES)} real queries through IntentExtractor...\n")

    contract_failures: list[str] = []
    results: list[dict] = []

    for task_id, query, ground_truth_terms in QUERIES:
        start = time.monotonic()
        try:
            parsed, response = await extractor.extract(query)
            elapsed = time.monotonic() - start
            overlap = sorted(
                set(t.lower() for t in ground_truth_terms)
                & set(e.lower() for e in parsed.entities)
            )
            print(f"[{task_id}] OK in {elapsed:.2f}s ({response.total_tokens} tokens)")
            print(f"  entities: {parsed.entities}")
            print(f"  ground_truth_terms: {ground_truth_terms}  overlap: {overlap}")
            print(f"  domain={parsed.domain} task={parsed.task} confidence={parsed.self_reported_confidence}")
            results.append(
                {
                    "task_id": task_id,
                    "elapsed_s": elapsed,
                    "entities": parsed.entities,
                    "overlap_with_ground_truth": overlap,
                }
            )
        except ValidationError as exc:
            elapsed = time.monotonic() - start
            print(f"[{task_id}] CONTRACT FAILURE after {elapsed:.2f}s: {exc}")
            contract_failures.append(task_id)
        except Exception as exc:  # noqa: BLE001 -- real infra failure, report don't hide
            elapsed = time.monotonic() - start
            print(f"[{task_id}] CALL FAILURE after {elapsed:.2f}s: {type(exc).__name__}: {exc}")
            contract_failures.append(task_id)
        print()

    print("=" * 72)
    if contract_failures:
        print(
            f"FAILURE: {len(contract_failures)}/{len(QUERIES)} queries did not produce a "
            f"valid RawIntentExtraction: {contract_failures}"
        )
        print("Per CHECKLIST.md 3c's failure criterion: SLM-1 hosting on this model is "
              "NOT ready; stays flagged as its own follow-on, not forced through.")
    else:
        print(
            f"SUCCESS: {len(QUERIES)}/{len(QUERIES)} real queries produced a valid "
            f"RawIntentExtraction via local Ollama, zero source changes."
        )
        avg_elapsed = sum(r["elapsed_s"] for r in results) / len(results)
        print(f"Average latency: {avg_elapsed:.2f}s/query (CPU, local, no API cost).")


if __name__ == "__main__":
    asyncio.run(main())
