"""OllamaBenchmarkProvider — the BenchmarkProvider-shaped adapter over
benchmark.local_slm.OllamaProvider, which already does the real work
(detecting installed models against a local Ollama daemon). Delegation,
not reimplementation: local_slm.OllamaProvider's Protocol takes a fixed
candidate list at construction (built for SLM-1's "first installed
candidate wins" use case); BenchmarkProvider's takes one alias per
call, so this adapter constructs a single-candidate OllamaProvider per
resolve_model() call and reuses its detection/error-message logic
unchanged.
"""

import httpx

from benchmark.local_slm.ollama_provider import OllamaProvider

_AVAILABILITY_TIMEOUT_SECONDS = 3.0


class OllamaBenchmarkProvider:
    def __init__(self, base_url: str) -> None:
        self.name = "ollama"
        self._base_url = base_url

    def resolve_model(self, alias: str) -> str:
        return OllamaProvider(base_url=self._base_url, candidates=[alias]).resolve_model()

    def is_available(self) -> bool:
        try:
            response = httpx.get(
                f"{self._base_url.rstrip('/')}/api/tags", timeout=_AVAILABILITY_TIMEOUT_SECONDS
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True
