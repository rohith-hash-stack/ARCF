"""SemanticInterpreter — the swappable seam (Step 3 of the experiment
brief) so "current ARCF", "generic SLM", and (later, NOT built here)
"QLoRA-tuned SLM" can all feed the identical downstream ARCF-DI call.

Three concrete implementations, corresponding to the experiment's arms:

- `ExistingSlm1Interpreter` — wraps arcf's OWN `contracts.intent_extraction
  .IntentExtractor` unmodified, just adapted to this Protocol. This is
  "current ARCF" when constructed with arcf's production `slm_model`
  (see arcf/src/shared/config.py's `slm_model` default) and is ALSO how
  the "generic SLM, no special prompting" arm is run — same prompt, only
  the model string changes. Zero new prompt-engineering in that arm,
  by design (isolates "does a smaller model alone change anything").
- `LLMSemanticInterpreter` — a NEW prompt using the richer
  `SemanticQueryInterpretation` contract (contract.py). This is the
  "generic SLM WITH an ARCF-specialized prompt" arm.
- `BypassInterpreter` — always returns an empty, `uncertain`
  interpretation with no LLM call. This is the SLM-1-bypass control arm
  (mirrors arcf/scripts/slm1_bypass_experiment.py's own hypothesis:
  check whether the semantic stage is doing anything at all before
  comparing which model does it best).

None of these three touch `arcf/src` — `ExistingSlm1Interpreter` only
constructs and calls the real `IntentExtractor` through its existing
public API.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Protocol

from contracts.intent_extraction import IntentExtractor
from infrastructure.llm_client import LiteLLMClient
from pydantic import ValidationError

from benchmark.semantic_layer.contract import SemanticQueryInterpretation, UncertaintyLevel
from benchmark.semantic_layer.errors import SemanticInterpretationError

_SPECIALIZED_PROMPT_TEMPLATE = """You are a semantic query interpreter for a code retrieval \
system. Your job is ONLY to interpret what the user's query MEANS — you have no access to any \
repository and must not claim any file, symbol, or line number exists. A separate, deterministic \
system (not you) will check your output against the real repository.

Given a user's query, respond with a single JSON object with EXACTLY these keys:

- "intent": short label for what the user wants (e.g. "locate_symbol", "understand_behavior", \
"trace_call_chain", "explain_absence")
- "retrieval_terms": array (0-12 items) of identifier-like tokens or short qualified names worth \
checking against the repository. NEVER invent file paths, line numbers, or "path:line" values. \
Empty array if you are not confident enough to name any.
- "concepts": array (0-12 items) of framework/domain concepts you believe are relevant (may be \
empty)
- "behavior": array (0-12 items) of short action phrases describing what the relevant code should \
DO (may be empty)
- "framework": your best guess at the relevant framework/library name, or null if you don't know
- "confidence": one of "high", "medium", "low", "uncertain" — use "uncertain" rather than \
guessing if you cannot confidently derive retrieval terms from this query
- "is_ambiguous": true if the query supports more than one reasonable reading, else false
- "ambiguous_alternatives": array of short descriptions of alternative readings (may be empty \
even if is_ambiguous is true)
- "is_negative_query": true if the query is about something NOT happening or missing (e.g. "why \
isn't X validated", "where is Y not handled"), else false
- "negation_targets": array describing what is being negated (only meaningful when \
is_negative_query is true; may be empty)

Respond with ONLY the JSON object, no other text, no markdown fences.

User query:
\"\"\"
{query}
\"\"\"
"""


@dataclass(frozen=True)
class InterpretationResult:
    interpretation: SemanticQueryInterpretation
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    attempts: int
    malformed_attempts: int
    """attempts - 1 when the final attempt succeeded, or `attempts` when
    every attempt was malformed and a fallback/error path was taken —
    the SLM-specific "malformed-output rate" metric Step 6 asks for."""


class SemanticInterpreter(Protocol):
    async def interpret(self, query: str) -> InterpretationResult: ...


class ExistingSlm1Interpreter:
    """Adapts arcf's real, production `IntentExtractor` to this
    Protocol, unmodified. See module docstring for which experiment arms
    this class is used for (both "current ARCF" and "generic SLM, no
    special prompting" — only the constructor's `model` argument
    differs between those two callers)."""

    def __init__(self, llm_client: LiteLLMClient, model: str, max_tokens: int = 512) -> None:
        self._extractor = IntentExtractor(llm_client, model=model, max_tokens=max_tokens)

    async def interpret(self, query: str) -> InterpretationResult:
        start = time.perf_counter()
        try:
            raw, response = await self._extractor.extract(query)
        except Exception as exc:  # IntentExtractionError or a raw LLMInvocationError
            raise SemanticInterpretationError(
                f"ExistingSlm1Interpreter failed: {exc}"
            ) from exc
        latency_ms = (time.perf_counter() - start) * 1000

        interpretation = SemanticQueryInterpretation(
            intent=raw.intent_summary or "unlabeled",
            retrieval_terms=raw.entities,
            concepts=[],
            behavior=[],
            framework=None,
            confidence=(
                UncertaintyLevel.UNCERTAIN
                if raw.self_reported_confidence < 0.34
                else UncertaintyLevel.MEDIUM
                if raw.self_reported_confidence < 0.67
                else UncertaintyLevel.HIGH
            ),
            is_ambiguous=bool(raw.suggested_clarifying_questions),
            ambiguous_alternatives=[],
            is_negative_query=False,
            negation_targets=[],
        )
        return InterpretationResult(
            interpretation=interpretation,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            latency_ms=latency_ms,
            attempts=response.attempts,
            malformed_attempts=response.attempts - 1,
        )


class LLMSemanticInterpreter:
    """The "ARCF-specialized prompt" arm: a NEW prompt asking directly
    for `SemanticQueryInterpretation`'s richer shape, on whatever model
    string is passed in (typically the same generic/local model
    `ExistingSlm1Interpreter` was also tested with, so the ONLY variable
    between those two arms is the prompt/contract, matching Step 7's
    ablation design)."""

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

    async def interpret(self, query: str) -> InterpretationResult:
        prompt = _SPECIALIZED_PROMPT_TEMPLATE.format(query=query)
        last_error: Exception | None = None
        malformed_attempts = 0
        start = time.perf_counter()

        for _ in range(self._max_parse_retries):
            completion = await self._llm_client.complete(
                prompt,
                self._model,
                max_tokens=self._max_tokens,
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            try:
                data = json.loads(completion.content)
                parsed = SemanticQueryInterpretation.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                malformed_attempts += 1
                continue
            latency_ms = (time.perf_counter() - start) * 1000
            return InterpretationResult(
                interpretation=parsed,
                prompt_tokens=completion.prompt_tokens,
                completion_tokens=completion.completion_tokens,
                latency_ms=latency_ms,
                attempts=completion.attempts,
                malformed_attempts=malformed_attempts,
            )

        raise SemanticInterpretationError(
            f"LLMSemanticInterpreter failed to produce valid structured output after "
            f"{self._max_parse_retries} attempts: {last_error}"
        )


class BypassInterpreter:
    """No LLM call. Always returns an empty, `uncertain` interpretation
    — the SLM-1-bypass control arm (see module docstring)."""

    async def interpret(self, query: str) -> InterpretationResult:
        return InterpretationResult(
            interpretation=SemanticQueryInterpretation(
                intent="bypassed",
                confidence=UncertaintyLevel.UNCERTAIN,
            ),
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0.0,
            attempts=0,
            malformed_attempts=0,
        )
