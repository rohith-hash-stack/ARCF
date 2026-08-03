"""LocalSLMProvider — the pluggable seam requested for "if Ollama isn't
available, create an abstraction so we can plug it in later": any
future local backend (llama.cpp server, vLLM, LM Studio, ...) is just
another implementation of this Protocol. Callers (bootstrap.py) never
import a concrete provider class beyond the one they choose to wire up.
"""

from typing import Protocol


class LocalSLMProvider(Protocol):
    def resolve_model(self) -> str:
        """Return a model string usable directly by ARCF's own
        LiteLLMClient.complete(model=...) (e.g. "ollama_chat/qwen2.5:1.5b-instruct").

        Raises LocalSLMUnavailableError if no usable local model exists,
        with a message telling the operator exactly how to fix that.
        """
        ...
