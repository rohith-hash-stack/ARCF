import pytest

from benchmark.model_resolution import resolve_model
from benchmark.providers.errors import UnknownProviderError


def test_no_provider_returns_model_unchanged() -> None:
    assert (
        resolve_model(None, "gpt-4o-mini", "default-model", "http://localhost:11434")
        == "gpt-4o-mini"
    )


def test_no_provider_and_no_model_falls_back_to_default() -> None:
    assert resolve_model(None, None, "default-model", "http://localhost:11434") == "default-model"


def test_provider_resolves_alias_through_registry() -> None:
    resolved = resolve_model("gemini", "gemini-flash-latest", "default-model", "http://x")
    assert resolved == "gemini/gemini-flash-latest"


def test_provider_with_no_model_resolves_default_through_registry() -> None:
    resolved = resolve_model("groq", None, "llama-3.1-8b-instant", "http://x")
    assert resolved == "groq/llama-3.1-8b-instant"


def test_unknown_provider_raises() -> None:
    with pytest.raises(UnknownProviderError):
        resolve_model("not-a-real-provider", "some-model", "default-model", "http://x")
