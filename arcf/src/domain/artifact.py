"""Artifact — a unit of LLM output (Phase 8), per the "LLM Output" example
on the diagram: code changes/patches, explanations, test cases,
documentation, structured data.
"""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from domain.enums import ArtifactKind
from shared import utc_now


class Artifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    kind: ArtifactKind
    content: str
    path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
