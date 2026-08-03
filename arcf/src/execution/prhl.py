"""PRHLAnalyzer — Predictive Response Hinting Layer. Stage 2 of the
v2.3 migration plan (see arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md
Sec. 2.2/6/7).

Same pattern as SLM-2 (context/understanding.py's
ContextUnderstandingAnalyzer): one small LLM call, structured JSON
output, parsed with retries. Runs *after* Phase 6 has already produced
a ContextPackage — deterministic selection is finalized before this is
ever called, and this module has no way to feed back into it: it only
needs a ContextPackage to run against, not a finished final-generation
step, which is why it can ship ahead of Phase 8's Context + Goal
Composer.

Advisory-only, structurally: PRHLAnalyzer returns a PredictedResponseHint
for a caller to store (e.g. as a future Execution Ledger entry) — it
must never be imported by whatever assembles the final generation
prompt. A failure here (bad JSON, provider error) is the caller's to
catch and degrade from, exactly like ContextUnderstandingError; it is
never fatal to the run PRHL is annotating.
"""

import json

from pydantic import ValidationError

from domain.context_package import ContextPackage
from domain.predicted_response import PredictedResponseHint
from infrastructure.llm_client import LiteLLMClient, LLMResponse
from shared.errors import PRHLError

_PROMPT_TEMPLATE = """You are a senior engineer predicting how a coding task will likely be \
solved, given the task and the files/dependencies a deterministic analysis has already \
selected as relevant. Produce a single JSON object with EXACTLY these keys:

- "likely_direction": a short (1-2 sentence) prediction of the likely implementation approach
- "probable_touchpoints": array of file paths you expect will need to change
- "expected_diff_scope": one of "small", "medium", "large"
- "anticipated_dependencies": array of new imports/packages/modules you expect the change \
to introduce that aren't already part of the selected context (empty array if none)
- "risk_flags": array of short warnings, e.g. "may require a schema migration" (empty array \
if none stand out)

This is a prediction only — it will never be shown to, or enforced on, whatever generates \
the actual change. Respond with ONLY the JSON object, no other text, no markdown fences.

Task:
\"\"\"
{raw_request}
\"\"\"

Selected files (already chosen deterministically; do not add or remove any):
{file_list}

Known dependency relationships among the selected files:
{dependency_list}
"""


class PRHLAnalyzer:
    def __init__(
        self,
        llm_client: LiteLLMClient,
        model: str,
        max_parse_retries: int = 2,
        max_tokens: int = 400,
    ) -> None:
        self._llm_client = llm_client
        self._model = model
        self._max_parse_retries = max(1, max_parse_retries)
        self._max_tokens = max_tokens

    async def analyze(
        self, raw_request: str, package: ContextPackage
    ) -> tuple[PredictedResponseHint, LLMResponse]:
        file_list = (
            "\n".join(f"- {f.file_path} ({f.reason})" for f in package.relevant_files) or "(none)"
        )
        dependency_list = (
            "\n".join(f"- {e.from_file} -> {e.to_file}" for e in package.dependency_chain)
            or "(none)"
        )
        prompt = _PROMPT_TEMPLATE.format(
            raw_request=raw_request, file_list=file_list, dependency_list=dependency_list
        )

        last_error: Exception | None = None
        for _ in range(self._max_parse_retries):
            completion = await self._llm_client.complete(
                prompt,
                self._model,
                max_tokens=self._max_tokens,
                response_format={"type": "json_object"},
            )
            try:
                data = json.loads(completion.content)
                hint = PredictedResponseHint.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                continue
            return hint, completion

        raise PRHLError(
            f"PRHL failed to produce valid structured output after "
            f"{self._max_parse_retries} attempts: {last_error}"
        )
