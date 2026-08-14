"""verify_integrity (ARCF-DI Phase 8) — spot-checks that stored
PersistedBehavioralRecords still match what a live rebuild produces,
per BLUEPRINT.md Phase 8's "integrity validation" requirement.

Depends only on domain.audit.BehavioralRecordStore (the Protocol), not
any concrete implementation — InMemoryBehavioralRecordStore and
SqliteBehavioralRecordStore (infrastructure/behavioral_record_store.py)
both satisfy it, and this module never imports infrastructure/, keeping
code_intelligence/'s existing dependency direction intact.

A mismatch here means one of: the repository changed since the record
was stored (expected, not a bug — see `commit_sha` before treating a
mismatch as an error), the resolver/analyzer version drifted between
build time and query time (BLUEPRINT.md Phase 8's actual target), or a
genuine non-determinism bug. This function only detects and reports the
disagreement — deciding which of those three explains it is the
caller's job, informed by comparing `commit_sha`/`resolver_version` on
the stored stamp against the live builder's own.
"""

from dataclasses import dataclass

from code_intelligence.behavioral_record import BehavioralRecordBuilder
from domain.audit import BehavioralRecordStore


@dataclass(frozen=True)
class IntegrityMismatch:
    symbol_id: str
    reason: str


@dataclass(frozen=True)
class IntegrityReport:
    checked: int
    mismatches: list[IntegrityMismatch]

    @property
    def clean(self) -> bool:
        return not self.mismatches


def verify_integrity(
    store: BehavioralRecordStore,
    builder: BehavioralRecordBuilder,
    commit_sha: str,
    symbol_ids: list[str],
) -> IntegrityReport:
    """Re-derives each of `symbol_ids` live via `builder` and compares to
    what `store` has for it under `commit_sha`. Deterministic given a
    deterministic `builder` and an unchanged `store` — checks
    `symbol_ids` in the order given, never a set/dict-derived order."""
    mismatches: list[IntegrityMismatch] = []
    for symbol_id in symbol_ids:
        stored = store.get(commit_sha, symbol_id)
        if stored is None:
            mismatches.append(IntegrityMismatch(symbol_id=symbol_id, reason="not found in store"))
            continue

        live = builder.build(symbol_id)
        if live is None:
            mismatches.append(
                IntegrityMismatch(symbol_id=symbol_id, reason="no longer resolvable")
            )
            continue

        if live.model_dump() != stored.record.model_dump():
            mismatches.append(IntegrityMismatch(symbol_id=symbol_id, reason="content drift"))

    return IntegrityReport(checked=len(symbol_ids), mismatches=mismatches)
