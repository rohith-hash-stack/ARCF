"""AuditStamp (ARCF-DI Phase 7, schema only) — the version/commit
provenance BLUEPRINT.md Phase 7 calls for ("version identifiers",
"commit hash linkage", "reproducibility requirement").

ARCF-DI Phase 8 makes the stamp real: PersistedBehavioralRecord wraps a
BehavioralRecord with the AuditStamp it was built under, and
BehavioralRecordStore (implemented in infrastructure/
behavioral_record_store.py, mirroring infrastructure/contract_store.py's
own Protocol + InMemory + Sqlite pattern) persists that pair keyed by
(commit_sha, symbol_id). The Protocol lives here, not in
infrastructure/, so code_intelligence/integrity.py's verify_integrity
can depend on the interface without importing a concrete store
implementation.
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from domain.behavioral_record import BehavioralRecord


class AuditStamp(BaseModel):
    model_config = ConfigDict(frozen=True)

    commit_sha: str
    """The repository commit an index build ran against — `git
    rev-parse HEAD` at build time, per BLUEPRINT.md Phase 7. Not
    populated by anything today; there is no build-time step that
    computes this yet."""
    resolver_version: str
    """Identifies the ReferenceResolver/CallGraph ruleset in effect —
    what actually changes ambiguity resolution (Phase 3), so this is
    what BLUEPRINT.md Phase 7's reproducibility requirement ("given
    (commit hash, index-build version), re-running the pipeline must
    produce byte-identical evidence") is checking is held constant."""
    schema_version: str
    """Version of the evidence schema itself (domain/code_intelligence.py,
    domain/behavioral_record.py, ...) — a bump here is BLUEPRINT.md
    Phase 8's trigger for a full reindex rather than a data migration,
    per its "the store is a cache of a pure function" framing."""


class PersistedBehavioralRecord(BaseModel):
    """ARCF-DI Phase 8: what actually gets stored — a BehavioralRecord
    plus the AuditStamp identifying exactly what produced it. The store
    is a cache of a pure function (BehavioralRecordBuilder.build,
    deterministic given the same commit and resolver ruleset), not a
    source of truth — the repository at `stamp.commit_sha` remains
    that, per BLUEPRINT.md Phase 8's own framing."""

    model_config = ConfigDict(frozen=True)

    stamp: AuditStamp
    record: BehavioralRecord


class BehavioralRecordStore(Protocol):
    def save(self, persisted: PersistedBehavioralRecord) -> None: ...
    def get(self, commit_sha: str, symbol_id: str) -> PersistedBehavioralRecord | None: ...
    def get_all_for_commit(self, commit_sha: str) -> list[PersistedBehavioralRecord]: ...
