"""slm1_determinism_reverification.py -- gap #2 (SLM-1 non-determinism),
falsification experiment, standalone, touches no ARCF source yet.

Re-checks a specific, already-documented real finding
(arcf_payload_optimization_path_masking memory, PROGRESS.md's "Benchmark
noise floor" open item): a real Consul benchmark run at temperature=0.0
dropped "New" from task5's extracted entities entirely on one run,
collapsing a stable 5/5/4 judge score to 1/1/2 -- unrelated to any code
change. The EARLIER slm1_determinism_experiment.py (2026-08-11) tested 4
different, simpler queries and found temperature=0 "perfectly stable" on
all 4 -- this experiment checks whether that stability claim actually
holds on the REAL flip-prone query, using the REAL CURRENT production
prompt (contracts/intent_extraction.py's IntentExtractor), not a
simplified stand-in prompt.

Success criterion (stated up front): if repeated real calls on task5's
exact query, at temperature=0.0, via the real IntentExtractor, show
"New" present in fewer than 100% of runs, that CONFIRMS temperature=0
alone does not guarantee determinism for this real case (a known,
documented LLM-serving-infrastructure limitation, not an ARCF prompt
bug) -- and motivates testing a deterministic verbatim-identifier
backstop as an additive mitigation, tested in the same run.

Failure criterion: if "New" is present in 100% of real repeats, the
originally-reported flip was noise from a DIFFERENT cause (a stale
prompt version, a provider-side incident) and this specific mitigation
isn't needed -- reported honestly either way, not assumed.
"""

from __future__ import annotations

import asyncio
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from contracts.intent_extraction import IntentExtractor
from infrastructure.llm_client import LiteLLMClient

QUERY = "What is the primary responsibility of the New function inside the agent/cache package?"
REPEATS = 10
MODEL = "gpt-4o-mini"

# Deterministic verbatim-identifier backstop, tested as a hypothesis
# here BEFORE being wired into any source file: any token in the raw
# query text that is itself identifier-shaped (PascalCase, camelCase,
# snake_case, UPPER_CASE, or a dotted Type.Member form) -- the exact
# entity SHAPES IntentExtractor's own prompt already asks the model to
# extract, now pulled out with a regex instead of trusting the model to
# reliably notice it every time. Deliberately excludes common English
# sentence-leading capitalized words (a hand-picked short stopword list,
# same "small, targeted, not a general stemmer" discipline as
# task_classifier.py's own "-ation" exclusion) to avoid extracting "What"
# from "What is...".
_STOPWORDS = {
    "What", "How", "Why", "When", "Where", "Who", "Which", "Does", "Is",
    "Are", "The", "This", "That", "Add", "Fix", "Investigate", "Debug",
    "Trace", "Explain",
}
_IDENTIFIER_PATTERN = re.compile(
    r"\b([A-Z][a-zA-Z0-9]*(?:\.[A-Za-z][a-zA-Z0-9]*)?|[a-z][a-z0-9]*(?:_[a-z0-9]+)+|[A-Z][A-Z0-9_]{2,})\b"
)


def deterministic_verbatim_entities(raw_request: str) -> list[str]:
    candidates = _IDENTIFIER_PATTERN.findall(raw_request)
    return [c for c in candidates if c not in _STOPWORDS]


async def main() -> None:
    client = LiteLLMClient(max_retries=3, base_delay_seconds=0.5)
    extractor = IntentExtractor(client, model=MODEL)

    print(f"Query: {QUERY}")
    print(f"Deterministic verbatim-identifier backstop finds: {deterministic_verbatim_entities(QUERY)}")
    print(f"\nRunning {REPEATS} real temperature=0.0 SLM-1 calls...")

    raw_results: list[tuple[str, ...]] = []
    for i in range(REPEATS):
        parsed, _ = await extractor.extract(QUERY)
        raw_results.append(tuple(parsed.entities))
        print(f"  run {i + 1}: {parsed.entities}")

    unique = Counter(raw_results)
    new_present_count = sum(1 for r in raw_results if "New" in r)

    print(f"\n{len(unique)} unique result(s) out of {REPEATS} runs:")
    for result, count in unique.items():
        print(f"  {count}x -> {list(result)}")
    print(f"\n'New' present in {new_present_count}/{REPEATS} real runs at temperature=0.0")

    backstop = deterministic_verbatim_entities(QUERY)
    unioned_results = [tuple(sorted(set(r) | set(backstop))) for r in raw_results]
    unioned_unique = Counter(unioned_results)
    new_present_with_backstop = sum(1 for r in unioned_results if "New" in r)
    print(f"\nWith deterministic backstop UNIONED in: {len(unioned_unique)} unique result(s)")
    for result, count in unioned_unique.items():
        print(f"  {count}x -> {list(result)}")
    print(f"'New' present in {new_present_with_backstop}/{REPEATS} runs WITH backstop")


if __name__ == "__main__":
    asyncio.run(main())
