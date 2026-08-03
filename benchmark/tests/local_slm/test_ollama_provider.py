"""OllamaProvider tests — httpx.get is monkeypatched so these never hit
a real daemon (hermetic, matches how patched_llm mocks litellm in the
API integration tests). A separate live check (not part of this suite)
is done manually against the real local Ollama daemon before running
the benchmark for real.
"""

from types import SimpleNamespace

import httpx
import pytest

from benchmark.local_slm.errors import LocalSLMUnavailableError
from benchmark.local_slm.ollama_provider import OllamaProvider

_CANDIDATES = ["qwen2.5:1.5b-instruct", "qwen2.5:3b-instruct", "phi3:mini"]


def _fake_tags_response(model_names: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"models": [{"name": name} for name in model_names]},
    )


def test_resolves_first_installed_candidate_in_priority_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "benchmark.local_slm.ollama_provider.httpx.get",
        lambda *a, **k: _fake_tags_response(["llama3.2:latest", "qwen2.5:3b-instruct"]),
    )
    provider = OllamaProvider(base_url="http://localhost:11434", candidates=_CANDIDATES)
    assert provider.resolve_model() == "ollama_chat/qwen2.5:3b-instruct"


def test_skips_uninstalled_candidates_to_find_lower_priority_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "benchmark.local_slm.ollama_provider.httpx.get",
        lambda *a, **k: _fake_tags_response(["phi3:mini"]),
    )
    provider = OllamaProvider(base_url="http://localhost:11434", candidates=_CANDIDATES)
    assert provider.resolve_model() == "ollama_chat/phi3:mini"


def test_raises_with_pull_hint_when_no_candidate_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "benchmark.local_slm.ollama_provider.httpx.get",
        lambda *a, **k: _fake_tags_response(["llama3.2:latest"]),
    )
    provider = OllamaProvider(base_url="http://localhost:11434", candidates=_CANDIDATES)
    with pytest.raises(LocalSLMUnavailableError, match="ollama pull qwen2.5:1.5b-instruct"):
        provider.resolve_model()


def test_raises_when_ollama_daemon_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("benchmark.local_slm.ollama_provider.httpx.get", _raise)
    provider = OllamaProvider(base_url="http://localhost:11434", candidates=_CANDIDATES)
    with pytest.raises(LocalSLMUnavailableError, match="not reachable"):
        provider.resolve_model()
