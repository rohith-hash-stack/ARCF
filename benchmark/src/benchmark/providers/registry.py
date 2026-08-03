"""ProviderRegistry — named lookup over a fixed set of BenchmarkProviders.

default_provider_registry() wires up the five providers proven this
session (per arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md Sec. 2.5:
Direct/ARCF-Remote/ARCF-Local pilot ran for real against Groq + local
Ollama; openai/anthropic/gemini use the same LiteLLMClient path with no
provider-specific branching) — callers needing a different set (e.g.
tests) construct ProviderRegistry directly instead.
"""

from benchmark.providers.errors import UnknownProviderError
from benchmark.providers.ollama_provider import OllamaBenchmarkProvider
from benchmark.providers.provider import BenchmarkProvider
from benchmark.providers.remote_provider import make_remote_providers


class ProviderRegistry:
    def __init__(self, providers: list[BenchmarkProvider]) -> None:
        self._by_name = {provider.name: provider for provider in providers}

    def get(self, name: str) -> BenchmarkProvider:
        try:
            return self._by_name[name]
        except KeyError:
            raise UnknownProviderError(
                f"Unknown provider '{name}'; available: {sorted(self._by_name)}"
            ) from None

    def names(self) -> list[str]:
        return sorted(self._by_name)

    def available_names(self) -> list[str]:
        return sorted(name for name, provider in self._by_name.items() if provider.is_available())


def default_provider_registry(ollama_base_url: str = "http://localhost:11434") -> ProviderRegistry:
    return ProviderRegistry([*make_remote_providers(), OllamaBenchmarkProvider(ollama_base_url)])
