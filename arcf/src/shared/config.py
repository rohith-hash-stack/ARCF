"""Runtime configuration for the Secure Fast Path (Phase 2), the Intent
& Contract Layer (Phase 3), and Workspace Intelligence (Phase 4).

Single source of truth for every guardrail's threshold, so a limit is
never hardcoded twice. All values are overridable via ARCF_-prefixed
environment variables or a local .env file.
"""

from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARCF_", env_file=".env", extra="ignore")

    # Auth — api_keys_raw format: "key1:principal_a,key2:principal_b"
    api_keys_raw: str = ""
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"

    # Rate limiting (token bucket, per principal)
    rate_limit_capacity: int = 60
    rate_limit_refill_per_second: float = 1.0

    # Idempotency
    idempotency_ttl_seconds: int = 86_400

    # Request size guardrail
    max_request_bytes: int = 1_000_000

    # Cost guardrail
    cost_guardrail_max_usd: float = 1.0
    default_model: str = "gpt-4o-mini"

    # LLM retry policy
    max_retries: int = 3
    retry_base_delay_seconds: float = 0.5

    # Tracing
    otel_service_name: str = "arcf"
    otel_exporter_otlp_endpoint: str | None = None

    # Intent & Contract Layer (Phase 3)
    slm_model: str = "gpt-4o-mini"
    confidence_clarification_threshold: float = 0.6
    contract_store_path: str = "arcf_contracts.db"

    # Execution Ledger (Phase 9)
    execution_ledger_db_path: str = "arcf_execution_ledger.db"

    # Comparison API (Phase 11)
    comparison_store_path: str = "arcf_comparisons.db"

    # Workspace Intelligence (Phase 4)
    # Comma-separated absolute paths; empty = unrestricted (local-dev-tool default).
    workspace_allowlist_raw: str = ""
    workspace_max_files_scanned: int = 20_000

    @cached_property
    def api_keys(self) -> dict[str, str]:
        """Map raw API key -> principal id."""
        keys: dict[str, str] = {}
        for pair in self.api_keys_raw.split(","):
            pair = pair.strip()
            if not pair:
                continue
            key, _, principal = pair.partition(":")
            if key and principal:
                keys[key] = principal
        return keys

    @cached_property
    def workspace_allowlist(self) -> list[str]:
        return [root.strip() for root in self.workspace_allowlist_raw.split(",") if root.strip()]


def get_settings() -> Settings:
    return Settings()
