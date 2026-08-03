from types import SimpleNamespace

import httpx
import pytest

from benchmark.local_slm.errors import LocalSLMUnavailableError
from benchmark.providers.ollama_provider import OllamaBenchmarkProvider


def _fake_tags_response(model_names: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"models": [{"name": name} for name in model_names]},
    )


def test_resolve_model_delegates_to_local_slm_ollama_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "benchmark.local_slm.ollama_provider.httpx.get",
        lambda *a, **k: _fake_tags_response(["qwen2.5:1.5b-instruct"]),
    )
    provider = OllamaBenchmarkProvider(base_url="http://localhost:11434")
    assert provider.resolve_model("qwen2.5:1.5b-instruct") == "ollama_chat/qwen2.5:1.5b-instruct"


def test_resolve_model_raises_when_alias_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "benchmark.local_slm.ollama_provider.httpx.get",
        lambda *a, **k: _fake_tags_response(["llama3.2:latest"]),
    )
    provider = OllamaBenchmarkProvider(base_url="http://localhost:11434")
    with pytest.raises(LocalSLMUnavailableError):
        provider.resolve_model("qwen2.5:1.5b-instruct")


def test_is_available_true_when_daemon_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "benchmark.providers.ollama_provider.httpx.get",
        lambda *a, **k: _fake_tags_response([]),
    )
    provider = OllamaBenchmarkProvider(base_url="http://localhost:11434")
    assert provider.is_available() is True


def test_is_available_false_when_daemon_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("benchmark.providers.ollama_provider.httpx.get", _raise)
    provider = OllamaBenchmarkProvider(base_url="http://localhost:11434")
    assert provider.is_available() is False


def test_provider_name_is_ollama() -> None:
    assert OllamaBenchmarkProvider(base_url="http://localhost:11434").name == "ollama"
