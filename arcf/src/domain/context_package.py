"""Context Package (Phase 6 deliverable) — the prompt-ready output of
Context Intelligence: budget-aware, compressed, and (optionally)
SLM-annotated, built entirely from a ContextResolutionResult.

Still domain/: pure data, no behavior. Produced by
context/packager.py's ContextPackager, which is the only Phase 6
component allowed to run the ranking/budgeting/compression pipeline —
everything downstream (Phase 7 planning, Phase 8 prompt compilation)
consumes this shape, the same way Phase 6 itself only ever consumes
ContextResolutionResult.
"""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from domain.context_resolution import DependencyEdge
from shared.clock import utc_now


class PackagedFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    file_path: str
    content: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    reason: str
    token_count: int = Field(ge=0)
    truncated: bool
    """True when `content` is a compressed excerpt (relevant symbol line
    ranges only) rather than the file's full text — see
    context/compressor.py."""


class ContextPackage(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    contract_id: str
    workspace_id: str
    context_resolution_id: UUID

    relevant_files: list[PackagedFile] = Field(default_factory=list)
    dependency_chain: list[DependencyEdge] = Field(default_factory=list)

    budget_max_tokens: int = Field(ge=0)
    budget_used_tokens: int = Field(ge=0)
    prompt_compression_ratio: float = Field(ge=0.0)
    """raw_context_tokens / budget_used_tokens (Phase 11's Prompt
    Compression Ratio) — note this is the INVERSE orientation of
    ContextResolutionResult.token_estimate.compression_ratio, which is
    CER-style (selected/raw, a fraction <= 1). PCR is typically >= 1:
    higher means more compression achieved."""
    excluded_file_count: int = Field(ge=0)
    """Candidate files that fit neither in full nor compressed within
    budget_max_tokens — visible here so a caller can tell "everything
    relevant fit" apart from "the budget was too tight"."""

    understanding_notes: list[str] = Field(default_factory=list)
    """SLM-2 generated commentary — supplementary only. An empty list
    means either SLM-2 wasn't used or it failed; the package is still
    complete and valid either way, since selection is never SLM-decided."""

    compressed_snippet_count: int = Field(ge=0, default=0)
    """ARCF hardening §11: how many of relevant_files are compressed
    excerpts (truncated=True) rather than full file content — part of the
    deterministic retrieval-completeness metadata, computed by counting,
    never estimated."""

    generated_at: datetime = Field(default_factory=utc_now)
