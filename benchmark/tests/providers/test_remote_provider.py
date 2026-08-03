import pytest

from benchmark.providers.remote_provider import RemoteBenchmarkProvider, make_remote_providers


def test_openai_bare_alias_passes_through_unchanged() -> None:
    provider = RemoteBenchmarkProvider(
        name="openai", prefix="", api_key_env_var="OPENAI_API_KEY"
    )
    assert provider.resolve_model("gpt-4o-mini") == "gpt-4o-mini"


def test_gemini_prefixes_bare_alias() -> None:
    provider = RemoteBenchmarkProvider(
        name="gemini", prefix="gemini", api_key_env_var="GEMINI_API_KEY"
    )
    assert provider.resolve_model("gemini-flash-latest") == "gemini/gemini-flash-latest"


def test_prefix_not_doubled_when_alias_already_prefixed() -> None:
    provider = RemoteBenchmarkProvider(
        name="groq", prefix="groq", api_key_env_var="GROQ_API_KEY"
    )
    assert provider.resolve_model("groq/llama-3.1-8b-instant") == "groq/llama-3.1-8b-instant"


def test_is_available_true_when_env_var_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    provider = RemoteBenchmarkProvider(
        name="groq", prefix="groq", api_key_env_var="GROQ_API_KEY"
    )
    assert provider.is_available() is True


def test_is_available_false_when_env_var_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    provider = RemoteBenchmarkProvider(
        name="groq", prefix="groq", api_key_env_var="GROQ_API_KEY"
    )
    assert provider.is_available() is False


def test_make_remote_providers_returns_four_named_providers() -> None:
    providers = make_remote_providers()
    assert {p.name for p in providers} == {"openai", "anthropic", "gemini", "groq"}
