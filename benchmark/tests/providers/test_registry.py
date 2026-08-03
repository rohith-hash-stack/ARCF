import pytest

from benchmark.providers.errors import UnknownProviderError
from benchmark.providers.registry import ProviderRegistry, default_provider_registry


class _FakeProvider:
    def __init__(self, name: str, available: bool) -> None:
        self.name = name
        self._available = available

    def resolve_model(self, alias: str) -> str:
        return f"{self.name}/{alias}"

    def is_available(self) -> bool:
        return self._available


def test_get_returns_registered_provider() -> None:
    registry = ProviderRegistry([_FakeProvider("openai", True)])
    assert registry.get("openai").resolve_model("gpt-4o-mini") == "openai/gpt-4o-mini"


def test_get_raises_for_unknown_name() -> None:
    registry = ProviderRegistry([_FakeProvider("openai", True)])
    with pytest.raises(UnknownProviderError, match="openai"):
        registry.get("nonexistent")


def test_names_returns_all_registered_providers_sorted() -> None:
    registry = ProviderRegistry([_FakeProvider("groq", True), _FakeProvider("anthropic", True)])
    assert registry.names() == ["anthropic", "groq"]


def test_available_names_filters_to_available_only() -> None:
    registry = ProviderRegistry([_FakeProvider("openai", True), _FakeProvider("groq", False)])
    assert registry.available_names() == ["openai"]


def test_default_provider_registry_includes_all_five_providers() -> None:
    registry = default_provider_registry()
    assert registry.names() == ["anthropic", "gemini", "groq", "ollama", "openai"]
