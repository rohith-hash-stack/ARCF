"""BenchmarkProvider abstraction — Stage 6 of the v2.3 migration plan
(see arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md Sec. 2.5/5.3/7).

A thin declarative layer over what infrastructure.llm_client.LiteLLMClient
already does today — it doesn't replace LiteLLMClient, it replaces "the
caller must know litellm's model-string conventions" (bare "gpt-4o-mini"
vs. prefixed "gemini/gemini-flash-latest" vs. "ollama_chat/qwen2.5:1.5b-
instruct") with a named, discoverable provider registry. Direct
precedent: benchmark.local_slm.provider.LocalSLMProvider, generalized
here from "one local provider" to "any provider."
"""

from benchmark.providers.errors import UnknownProviderError
from benchmark.providers.ollama_provider import OllamaBenchmarkProvider
from benchmark.providers.provider import BenchmarkProvider
from benchmark.providers.registry import ProviderRegistry, default_provider_registry
from benchmark.providers.remote_provider import RemoteBenchmarkProvider

__all__ = [
    "BenchmarkProvider",
    "OllamaBenchmarkProvider",
    "ProviderRegistry",
    "RemoteBenchmarkProvider",
    "UnknownProviderError",
    "default_provider_registry",
]
