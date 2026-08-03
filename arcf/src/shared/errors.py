"""Guardrail and pipeline exceptions raised by ARCF infrastructure.

Each maps 1:1 to an HTTP response in the API layer — kept as plain
exceptions here (not HTTPException) so infrastructure/ and contracts/
have no dependency on FastAPI and can be unit-tested in isolation.
"""


class ArcfError(Exception):
    """Base class for all ARCF domain/infrastructure errors."""


class AuthenticationError(ArcfError):
    pass


class RateLimitExceededError(ArcfError):
    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Rate limit exceeded, retry after {retry_after_seconds:.2f}s")


class RequestTooLargeError(ArcfError):
    pass


class IdempotencyConflictError(ArcfError):
    """Same Idempotency-Key reused with a different request payload."""


class CostGuardrailExceededError(ArcfError):
    def __init__(self, estimated_cost_usd: float, max_cost_usd: float) -> None:
        self.estimated_cost_usd = estimated_cost_usd
        self.max_cost_usd = max_cost_usd
        super().__init__(
            f"Estimated cost ${estimated_cost_usd:.4f} exceeds guardrail ${max_cost_usd:.4f}"
        )


class LLMInvocationError(ArcfError):
    """Raised after retries are exhausted calling the LLM provider."""


class IntentExtractionError(ArcfError):
    """SLM-1 failed to produce schema-valid structured output after retries."""


class ContractNotFoundError(ArcfError):
    """No LivingContract exists for the given contract_id."""


class WorkspacePathError(ArcfError):
    """A resolved path escapes its declared workspace root."""


class WorkspaceNotAllowedError(ArcfError):
    """workspace_root is not within the configured allowlist."""


class ContextUnderstandingError(ArcfError):
    """SLM-2 failed to produce schema-valid structured output after
    retries. Never fatal to a ContextPackage — callers should catch this
    and degrade to no understanding_notes, not fail the whole package."""


class ContextResolutionNotFoundError(ArcfError):
    """No ContextResolutionResult exists for the given id."""


class NoWorkspaceAttachedError(ArcfError):
    """Code intelligence was requested but no workspace_root is available —
    neither attached to the contract (Phase 4) nor provided explicitly."""


class PRHLError(ArcfError):
    """PRHL failed to produce schema-valid structured output after
    retries. Never fatal — like ContextUnderstandingError for SLM-2,
    callers should catch this and degrade to no predicted hint, not fail
    whatever's orchestrating the run."""
