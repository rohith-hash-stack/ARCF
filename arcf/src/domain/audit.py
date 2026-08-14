"""AuditStamp (ARCF-DI Phase 7, schema only) — the version/commit
provenance BLUEPRINT.md Phase 7 calls for ("version identifiers",
"commit hash linkage", "reproducibility requirement"). Nothing
constructs or attaches one yet: this is only meaningful once something
is actually persisted with a versioned schema (BLUEPRINT.md Phase 8),
so wiring it onto real evidence records is that phase's job, not this
one — the same schema-first-then-populate pattern Phase 1's enums
(ImportResolutionKind, CallResolutionConfidence) already established
for Phase 2/3.
"""

from pydantic import BaseModel, ConfigDict


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
