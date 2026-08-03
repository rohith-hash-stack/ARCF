"""API request/response shapes.

ComparisonResult itself (and the RunResult objects within it) is
returned directly from the run/report endpoints — it's already the
right shape; a parallel HTTP-specific copy would just be duplication.
"""

from typing import Literal

from pydantic import BaseModel, Field

BenchmarkModeName = Literal["direct", "arcf", "arcf_local"]
_DEFAULT_MODES: list[BenchmarkModeName] = ["direct", "arcf"]


class LoadRepositoryRequest(BaseModel):
    source: Literal["local", "clone"]
    path: str | None = None
    url: str | None = None
    ref: str | None = None


class LanguageStatResponse(BaseModel):
    language: str
    file_count: int
    percentage: float


class RepositoryInfoResponse(BaseModel):
    root: str
    is_git_repo: bool
    current_branch: str | None
    file_count: int
    languages: list[LanguageStatResponse]
    frameworks: list[str]


class RunBenchmarkRequest(BaseModel):
    repository_root: str
    task: str = Field(min_length=1, max_length=10_000)
    model: str | None = None
    modes: list[BenchmarkModeName] = Field(default_factory=lambda: list(_DEFAULT_MODES))
    max_context_tokens: int | None = None
    max_output_tokens: int | None = None


class LocalSlmStatusResponse(BaseModel):
    available: bool
    reason: str | None = None
    """Why arcf_local is unavailable, e.g. a missing-model pull hint or
    that the Ollama daemon isn't reachable. None when available."""
