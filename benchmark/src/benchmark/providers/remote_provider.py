"""RemoteBenchmarkProvider — one BenchmarkProvider implementation
covering every litellm-supported remote provider that follows the
"{provider}/{alias}" model-string convention (gemini, groq, and any
future addition), plus openai's bare-alias convention (no prefix) as
already used throughout this codebase (infrastructure/cost.py's
DEFAULT_PRICING keys, shared/config.py's default_model). One class
instead of near-duplicate per-provider classes — the only thing that
varies between providers is the prefix and which env var proves
availability.

Anthropic also gets the "{provider}/{alias}" treatment here rather than
relying on litellm's bare "claude-..." auto-detection — an explicit
prefix is unambiguous and litellm accepts it for every provider, so
there's no behavioral downside to being explicit everywhere except
openai's own established bare convention.
"""

import os

from benchmark.providers.provider import BenchmarkProvider


class RemoteBenchmarkProvider:
    def __init__(self, name: str, prefix: str, api_key_env_var: str) -> None:
        self.name = name
        self._prefix = prefix
        self._api_key_env_var = api_key_env_var

    def resolve_model(self, alias: str) -> str:
        if not self._prefix or alias.startswith(f"{self._prefix}/"):
            return alias
        return f"{self._prefix}/{alias}"

    def is_available(self) -> bool:
        return bool(os.environ.get(self._api_key_env_var))


def make_remote_providers() -> list[BenchmarkProvider]:
    return [
        RemoteBenchmarkProvider(name="openai", prefix="", api_key_env_var="OPENAI_API_KEY"),
        RemoteBenchmarkProvider(
            name="anthropic", prefix="anthropic", api_key_env_var="ANTHROPIC_API_KEY"
        ),
        RemoteBenchmarkProvider(name="gemini", prefix="gemini", api_key_env_var="GEMINI_API_KEY"),
        RemoteBenchmarkProvider(name="groq", prefix="groq", api_key_env_var="GROQ_API_KEY"),
    ]
