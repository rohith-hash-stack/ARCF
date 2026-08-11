"""slm1_determinism_experiment.py — falsification experiment, standalone,
touches no ARCF source. Hypothesis (from repeated sweep re-runs showing
the SAME query's entities_extracted changing between runs — e.g.
"Investigate a regression where sandbox startup..." got ['sandbox'] once
and [] another time): `LiteLLMClient.complete()` never sets `temperature`,
so `IntentExtractor` (contracts/intent_extraction.py) runs SLM-1 at the
provider's default (OpenAI: 1.0) for a structured-extraction task that
should be deterministic — the entities found (and therefore whether a
query gets precise symbol-based resolution or falls back to broad
evidence-fallback) is currently a coin flip on repeated identical input,
not a property of the query's content.

Success criterion (stated up front): if calling `litellm.acompletion`
directly with `temperature=0` on the SAME prompt N times produces
IDENTICAL entities every time (or near-identical — allow superficial
wording drift but require the SAME concepts), while the current
temperature-unset behavior varies across repeats on the same queries,
that confirms temperature is the lever, not just a general "LLMs are
noisy" shrug — worth fixing. If temperature=0 still varies as much as
default, the hypothesis is wrong and this shouldn't be pursued.
"""

import asyncio
import json

import litellm
from dotenv import load_dotenv

load_dotenv()

_PROMPT_TEMPLATE = """You are an intent-extraction system for a software engineering assistant. \
Given a user's request, extract structured information as a single JSON object with EXACTLY \
these keys:

- "intent_summary": a short (3-6 word) label for what the user wants done
- "domain": one of ["frontend", "backend", "testing", "infrastructure", "data", \
"documentation", "unknown"]
- "task": one of ["bug_fix", "feature", "refactor", "documentation", "test", "unknown"]
- "entities": array of specific files/functions/components/features mentioned (empty array if none)
- "constraints": array of explicit limitations the user stated (empty array if none)
- "assumptions": array of things you are inferring that were not explicitly stated \
(empty array if none)
- "self_reported_confidence": a number between 0 and 1 for how confident you are in this extraction
- "suggested_clarifying_questions": array of questions to ask the user if the request is ambiguous \
(empty array if not ambiguous)

Respond with ONLY the JSON object, no other text, no markdown fences.

User request:
\"\"\"
{raw_request}
\"\"\"
"""

QUERIES = [
    "Investigate a regression where sandbox startup time increases with the number of mounts.",
    "A parameterized test suite is taking significantly longer than expected to run; investigate what could be causing the slowdown.",
    "Add support for a test listener that records the duration and final status of every test.",
    "Debug a generated accessor that produces incorrect results for nested tables.",
]

REPEATS = 4
MODEL = "gpt-4o-mini"


async def _call(query: str, temperature: float | None) -> list[str]:
    kwargs = {"temperature": temperature} if temperature is not None else {}
    response = await litellm.acompletion(
        model=MODEL,
        messages=[{"role": "user", "content": _PROMPT_TEMPLATE.format(raw_request=query)}],
        max_tokens=512,
        response_format={"type": "json_object"},
        **kwargs,
    )
    content = response.choices[0].message.content
    data = json.loads(content)
    return data.get("entities", [])


async def main() -> None:
    for query in QUERIES:
        print(f"\n=== {query[:70]} ===")
        for label, temp in (("default (unset)", None), ("temperature=0", 0.0)):
            results = []
            for _ in range(REPEATS):
                entities = await _call(query, temp)
                results.append(entities)
            unique = {tuple(r) for r in results}
            print(f"  {label:20s} runs={results}")
            print(f"  {label:20s} -> {len(unique)} unique result(s) out of {REPEATS} runs")


if __name__ == "__main__":
    asyncio.run(main())
