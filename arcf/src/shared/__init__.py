"""Cross-cutting utilities with no dependency on any ARCF layer."""

from shared.clock import utc_now
from shared.config import Settings, get_settings
from shared.errors import (
    ArcfError,
    AuthenticationError,
    ContextResolutionNotFoundError,
    ContextUnderstandingError,
    ContractNotFoundError,
    CostGuardrailExceededError,
    IdempotencyConflictError,
    IntentExtractionError,
    LLMInvocationError,
    NoWorkspaceAttachedError,
    RateLimitExceededError,
    RequestTooLargeError,
    WorkspaceNotAllowedError,
    WorkspacePathError,
)

__all__ = [
    "ArcfError",
    "AuthenticationError",
    "ContextResolutionNotFoundError",
    "ContextUnderstandingError",
    "ContractNotFoundError",
    "CostGuardrailExceededError",
    "IdempotencyConflictError",
    "IntentExtractionError",
    "LLMInvocationError",
    "NoWorkspaceAttachedError",
    "RateLimitExceededError",
    "RequestTooLargeError",
    "Settings",
    "WorkspaceNotAllowedError",
    "WorkspacePathError",
    "get_settings",
    "utc_now",
]
