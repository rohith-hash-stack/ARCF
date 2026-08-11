"""SLM-1 Intent Extraction — the first place a model's output enters the
pipeline.

RawIntentExtraction is deliberately NOT UserIntent: it's the raw,
unvalidated-against-deterministic-signals shape the SLM is asked to
produce. ExecutionContractManager (contracts/manager.py) is what turns
this into a real UserIntent, after DomainClassifier/TaskClassifier
corroboration and ConfidenceEngine scoring — this module never claims
its own output is trustworthy on its own.
"""

import json

from pydantic import BaseModel, Field, ValidationError

from infrastructure.llm_client import LiteLLMClient, LLMResponse
from shared.errors import IntentExtractionError

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


class RawIntentExtraction(BaseModel):
    intent_summary: str
    domain: str
    task: str
    entities: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    self_reported_confidence: float = Field(ge=0.0, le=1.0)
    suggested_clarifying_questions: list[str] = Field(default_factory=list)


class IntentExtractor:
    def __init__(
        self,
        llm_client: LiteLLMClient,
        model: str,
        max_parse_retries: int = 2,
        max_tokens: int = 512,
    ) -> None:
        self._llm_client = llm_client
        self._model = model
        self._max_parse_retries = max(1, max_parse_retries)
        self._max_tokens = max_tokens

    async def extract(self, raw_request: str) -> tuple[RawIntentExtraction, LLMResponse]:
        prompt = _PROMPT_TEMPLATE.format(raw_request=raw_request)
        last_error: Exception | None = None

        for _ in range(self._max_parse_retries):
            completion = await self._llm_client.complete(
                prompt,
                self._model,
                max_tokens=self._max_tokens,
                response_format={"type": "json_object"},
                # Structured extraction, not creative generation — a
                # deterministic decode removes run-to-run entity variance
                # confirmed by scripts/slm1_determinism_experiment.py
                # (same query, unset temperature, 1-3 different results
                # across 4 repeats; temperature=0, always 1). Doesn't fix
                # under-extraction on its own (see that script's own
                # findings) — only removes the coin-flip on top of it.
                temperature=0.0,
            )
            try:
                data = json.loads(completion.content)
                parsed = RawIntentExtraction.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                continue
            return parsed, completion

        raise IntentExtractionError(
            f"SLM-1 failed to produce valid structured output after "
            f"{self._max_parse_retries} attempts: {last_error}"
        )
