"""Execution Contract — the object that flows through every ARCF phase.

Field set matches the "Execution Contract (Example)" list on the
architecture diagram: intent/domain/task/entities/constraints/assumptions
(carried via UserIntent), workspace, target files, execution strategy,
success criteria, permissions, policies, confidence (via UserIntent),
risks, metadata. Versioning, timestamps and lineage are handled by the
LivingContract wrapper, not here — Contract is one immutable snapshot of
content; progressing a contract means producing a new Contract and
wrapping it in a new LivingContract version.

workspace_metadata is populated by Phase 4's Workspace Intelligence
layer, attached via WorkspaceContractService.evolve() — a Contract can
exist (and be approved) before workspace analysis runs, so this stays
optional rather than required.

context_resolution_id references a Phase 5 ContextResolutionResult by
id only, not embedded — that result can hold dozens of file/symbol
references, and embedding it the way the much smaller WorkspaceMetadata
is embedded would bloat every subsequent LivingContract version stored
as a full JSON snapshot (Phase 3). Contract deliberately does not
import domain.context_resolution at all; it only needs to know the id
exists.
"""

from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from domain.artifact import Artifact
from domain.intent import UserIntent
from domain.workspace import WorkspaceMetadata


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    intent: UserIntent
    workspace_root: str | None = None
    workspace_metadata: WorkspaceMetadata | None = None
    context_resolution_id: UUID | None = None
    target_files: list[str] = Field(default_factory=list)
    execution_strategy: str | None = None
    success_criteria: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
