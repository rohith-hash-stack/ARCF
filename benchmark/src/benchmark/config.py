"""Benchmark app configuration — mirrors ARCF's own shared/config.py
pattern (pydantic-settings, env-overridable).

ARCF's own guardrail machinery (auth, rate limiting, ExecutionContext,
cost guardrail HTTP responses) is deliberately NOT reused here: this is
a local tool one operator runs against repositories they already
trust, not a multi-tenant HTTP service — only the deterministic
pipeline classes and LiteLLMClient are reused, called directly.
"""

from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_LOCAL_SLM_CANDIDATES = "qwen2.5:1.5b-instruct,qwen2.5:3b-instruct,phi3:mini"


class BenchmarkSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BENCHMARK_", env_file=".env", extra="ignore")

    default_model: str = "gpt-4o-mini"
    slm_model: str = "gpt-4o-mini"
    slm_max_tokens: int = 512
    """SLM-1's output budget (ARCF's IntentExtractor default). Some
    models (e.g. Gemini's reasoning variants) spend a chunk of this on
    internal reasoning before any visible JSON — override higher for
    those, via BENCHMARK_SLM_MAX_TOKENS, without touching ARCF itself."""

    local_slm_base_url: str = "http://localhost:11434"
    """Ollama's default local HTTP address."""
    local_slm_candidates_raw: str = _DEFAULT_LOCAL_SLM_CANDIDATES
    """Priority-ordered local model tags to try, first installed wins.
    Comma-separated so it's overridable via BENCHMARK_LOCAL_SLM_CANDIDATES_RAW
    without a code change, mirroring api_keys_raw/workspace_allowlist_raw
    in arcf/src/shared/config.py."""

    max_context_tokens: int = 100_000
    max_output_tokens: int = 2048

    max_retries: int = 3
    retry_base_delay_seconds: float = 0.5

    workspace_max_files_scanned: int = 20_000

    clone_root: str = ".benchmark_repos"
    store_path: str = "benchmark_runs.db"

    arcf_source_root: str = "../arcf"
    """Path (relative to benchmark/) to the real arcf checkout used as
    the base repo for suite tasks — never modified in place, only
    copied from (see suite/repo_pool.py)."""
    suite_repos_root: str = ".suite_repos"
    """Where suite base checkouts (arcf_base/, todomvc_base/) live."""
    suite_store_path: str = "suite_runs.db"

    @cached_property
    def local_slm_candidates(self) -> list[str]:
        return [c.strip() for c in self.local_slm_candidates_raw.split(",") if c.strip()]


def get_settings() -> BenchmarkSettings:
    return BenchmarkSettings()
