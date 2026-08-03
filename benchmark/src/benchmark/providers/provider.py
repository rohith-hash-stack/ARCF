"""BenchmarkProvider — the Protocol every provider (openai, anthropic,
gemini, groq, ollama, ...) implements. Quoted verbatim from
arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md Sec. 5.3.
"""

from typing import Protocol


class BenchmarkProvider(Protocol):
    name: str
    """"openai" | "anthropic" | "gemini" | "groq" | "ollama" | ..."""

    def resolve_model(self, alias: str) -> str:
        """Turn a short, provider-scoped alias (e.g. "gpt-4o-mini",
        "qwen2.5:1.5b-instruct") into a model string usable directly by
        infrastructure.llm_client.LiteLLMClient.complete(model=...)."""
        ...

    def is_available(self) -> bool:
        """Whether this provider is currently usable — an API key is
        configured (remote providers) or the local daemon is reachable
        (Ollama). Never raises; used for capability discovery, not for
        resolving a specific model."""
        ...
