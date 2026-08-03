"""Workspace Intelligence domain models (Phase 4).

Pure data, discovered entirely by deterministic algorithms (git metadata,
a bounded file-tree scan, extension/manifest lookups) — no SLM or LLM
involved anywhere in this module or the workspace/ package that produces
these models, per the Phase 4 goal: "repository discovery without AI."
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.clock import utc_now

FrameworkCategory = Literal[
    "web_frontend", "web_backend", "testing", "build_tool", "ai_orchestration"
]
ProjectLayout = Literal["src-layout", "flat-layout", "monorepo", "unknown"]


class RepositoryMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_git_repo: bool
    root_path: str | None = None
    current_branch: str | None = None
    head_commit: str | None = None
    remote_urls: list[str] = Field(default_factory=list)
    is_dirty: bool = False


class LanguageStat(BaseModel):
    model_config = ConfigDict(frozen=True)

    language: str
    file_count: int = Field(ge=0)
    percentage: float = Field(ge=0.0, le=100.0)


class FrameworkMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    category: FrameworkCategory
    evidence: list[str] = Field(default_factory=list)


class ProjectStructure(BaseModel):
    model_config = ConfigDict(frozen=True)

    layout: ProjectLayout
    manifest_files: list[str] = Field(default_factory=list)
    test_directories: list[str] = Field(default_factory=list)


class WorkspaceMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_root: str
    repository: RepositoryMetadata
    languages: list[LanguageStat] = Field(default_factory=list)
    frameworks: list[FrameworkMatch] = Field(default_factory=list)
    structure: ProjectStructure
    file_count: int = Field(ge=0)
    truncated: bool = False
    sensitive_paths: list[str] = Field(default_factory=list)
    scanned_at: datetime = Field(default_factory=utc_now)
