"""OllamaProvider — detects which of a priority-ordered list of local
model candidates is actually installed in a local Ollama daemon, and
resolves the first match to a model string litellm understands.

Deliberately does not auto-pull a missing model: pulling means
downloading gigabytes over the network, which is an action the operator
should explicitly authorize each time, not something that happens
silently as a side effect of running a benchmark.
"""

import httpx

from benchmark.local_slm.errors import LocalSLMUnavailableError

_DEFAULT_TIMEOUT_SECONDS = 3.0


class OllamaProvider:
    def __init__(
        self,
        base_url: str,
        candidates: list[str],
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._candidates = candidates
        self._timeout_seconds = timeout_seconds

    def resolve_model(self) -> str:
        installed = self._installed_models()
        for candidate in self._candidates:
            if candidate in installed:
                return f"ollama_chat/{candidate}"

        pull_hints = " or ".join(f"`ollama pull {candidate}`" for candidate in self._candidates)
        raise LocalSLMUnavailableError(
            f"None of the configured local SLM candidates {self._candidates} are installed "
            f"in Ollama at {self._base_url} (installed: {sorted(installed) or 'none'}). "
            f"Run {pull_hints} to make one available."
        )

    def _installed_models(self) -> set[str]:
        try:
            response = httpx.get(f"{self._base_url}/api/tags", timeout=self._timeout_seconds)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LocalSLMUnavailableError(
                f"Ollama is not reachable at {self._base_url}: {exc}. Make sure the Ollama "
                "daemon is running (`ollama serve`) and reachable at that address."
            ) from exc

        data = response.json()
        return {model["name"] for model in data.get("models", []) if "name" in model}
