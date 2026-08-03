"""ContextUnderstandingAnalyzer — SLM-2, Phase 6's only model call.

Supplementary only: produces a short natural-language summary and key
relationships for a ContextPackage. Never makes selection decisions —
RelevanceRanker and ContextBudgetManager already decided what's
included before this runs. If this fails (bad JSON, provider error),
ContextPackager catches it and returns a package with empty
understanding_notes rather than failing the whole request.
"""

import json

from pydantic import BaseModel, Field, ValidationError

from context.relevance_ranker import RankedFile
from domain.context_resolution import SymbolReference
from infrastructure.llm_client import LiteLLMClient, LLMResponse
from shared.errors import ContextUnderstandingError

_PROMPT_TEMPLATE = """You are a code context summarization assistant. Given a software \
engineering task and the files/symbols a deterministic analysis has already selected as \
relevant, produce a single JSON object with EXACTLY these keys:

- "summary": a short (1-3 sentence) explanation of how the selected files relate to the task
- "key_relationships": array of short strings describing important relationships between \
the selected files/symbols (empty array if none stand out)

Respond with ONLY the JSON object, no other text, no markdown fences.

Task:
\"\"\"
{raw_request}
\"\"\"

Selected files (already chosen deterministically; do not add or remove any):
{file_list}

Key symbols involved:
{symbol_list}
"""


class ContextUnderstandingNote(BaseModel):
    summary: str
    key_relationships: list[str] = Field(default_factory=list)


class ContextUnderstandingAnalyzer:
    def __init__(
        self,
        llm_client: LiteLLMClient,
        model: str,
        max_parse_retries: int = 2,
        max_tokens: int = 300,
    ) -> None:
        self._llm_client = llm_client
        self._model = model
        self._max_parse_retries = max(1, max_parse_retries)
        self._max_tokens = max_tokens

    async def analyze(
        self,
        raw_request: str,
        ranked_files: list[RankedFile],
        entry_points: list[SymbolReference],
    ) -> tuple[ContextUnderstandingNote, LLMResponse]:
        file_list = "\n".join(f"- {f.file_path} ({f.reason})" for f in ranked_files) or "(none)"
        symbol_list = (
            "\n".join(f"- {s.qualified_name} ({s.kind})" for s in entry_points) or "(none)"
        )
        prompt = _PROMPT_TEMPLATE.format(
            raw_request=raw_request, file_list=file_list, symbol_list=symbol_list
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
                note = ContextUnderstandingNote.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                continue
            return note, completion

        raise ContextUnderstandingError(
            f"SLM-2 failed to produce valid structured output after "
            f"{self._max_parse_retries} attempts: {last_error}"
        )
