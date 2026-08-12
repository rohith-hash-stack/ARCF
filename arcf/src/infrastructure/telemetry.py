"""TelemetryCollector — checklist item #13 (arcf/CHECKLIST.md). In-memory,
zero-external-networking structured telemetry for retrieval pipeline
passes, opt-in (a caller must construct a collector and call `.record()`
after a real `ContextResolver.resolve()`/`ContextPackager.package()` pair
— no existing caller does this automatically, so every current caller/test
is byte-identical unaffected).

Real pipeline boundaries, not invented ones (see this item's own
CHECKLIST.md entry for the full reasoning): `ContextResolver.resolve()`
and `ContextPackager.package()` are the two genuinely separate public
calls in the real pipeline — `ContextBudgetManager.select()` internally
does the relative-score falloff gate ("pruning") and budget-fit/
compression ("final_selection") together, and `resolve()` does entry-point
matching and graph expansion together via private helpers already
threaded twice this session (items #3, #10) — so this collector times
those two real boundaries as wholes, and gets stage-level *counts* for
free from data those calls already return (`FileReference.origin_stage`,
item #10's own capability) rather than adding new internal timing probes.
"""

from __future__ import annotations

import statistics
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from context.task_profile import RetrievalTaskType
from domain.context_package import ContextPackage
from domain.context_resolution import ContextResolutionResult, OriginStage
from shared.clock import utc_now


class OriginStageBreakdown(BaseModel):
    """Aggregated FileReference.origin_stage counts for one resolve() call
    — the "Origin Breakdown" the spec asks for, computed by counting
    already-present data, not a new instrumentation point."""

    model_config = ConfigDict(frozen=True)

    ast_direct: int = Field(default=0, ge=0)
    scoped_graph_expansion: int = Field(default=0, ge=0)
    raw_string_fallback: int = Field(default=0, ge=0)
    evidence_fallback_match: int = Field(default=0, ge=0)
    untagged: int = Field(default=0, ge=0)
    """Should always be 0 on a real resolve() result — item #10 tags every
    real construction site in the default classic path. A nonzero value
    here is itself a real signal (a new FileReference construction site
    this item's own coverage audit missed), not a legitimate "no stage"
    case — see OriginStage's own docstring."""

    @property
    def total(self) -> int:
        return (
            self.ast_direct + self.scoped_graph_expansion + self.raw_string_fallback
            + self.evidence_fallback_match + self.untagged
        )

    @property
    def fallback_count(self) -> int:
        """RAW_STRING_FALLBACK + EVIDENCE_FALLBACK_MATCH — the two stages
        that mean "not identity-propagated," the signal assert_no_fallbacks
        checks."""
        return self.raw_string_fallback + self.evidence_fallback_match

    @property
    def fallback_ratio(self) -> float:
        return round(self.fallback_count / self.total, 4) if self.total else 0.0


def _origin_breakdown(result: ContextResolutionResult) -> OriginStageBreakdown:
    counts: dict[OriginStage, int] = dict.fromkeys(OriginStage, 0)
    untagged = 0
    for ref in result.candidate_files:
        if ref.origin_stage is None:
            untagged += 1
        else:
            counts[ref.origin_stage] += 1
    return OriginStageBreakdown(
        ast_direct=counts[OriginStage.AST_DIRECT],
        scoped_graph_expansion=counts[OriginStage.SCOPED_GRAPH_EXPANSION],
        raw_string_fallback=counts[OriginStage.RAW_STRING_FALLBACK],
        evidence_fallback_match=counts[OriginStage.EVIDENCE_FALLBACK_MATCH],
        untagged=untagged,
    )


class TelemetryEvent(BaseModel):
    """Structured telemetry payload for one retrieval pass. Every field
    below is required (not Optional) unless the underlying data genuinely
    doesn't exist yet at record time (e.g. `package_latency_ms` is None
    when only resolve() has been recorded, no package() call yet) — "Zero
    Missing Fields" is enforced by pydantic construction, not a separate
    check bolted on after."""

    model_config = ConfigDict(frozen=True)

    query_id: UUID
    """ContextResolutionResult.id — already a real, unique identifier per
    resolution, no new id scheme needed."""
    classified_task: RetrievalTaskType | None = None
    """None when the caller didn't classify the query before recording
    (e.g. a raw resolve()-only call) — a real "not yet known" case, unlike
    origin_breakdown.untagged which should never happen."""
    traversal_depth: int
    """ContextResolutionResult.retrieval_depth_used — the real max hop
    reached, not the requested traversal_depth parameter (which may exceed
    what the actual call graph had to offer)."""

    resolve_latency_ms: float = Field(ge=0.0)
    package_latency_ms: float | None = Field(default=None, ge=0.0)

    origin_breakdown: OriginStageBreakdown

    token_budget_capacity: int | None = None
    tokens_utilized: int | None = None
    utilization_ratio: float | None = Field(default=None, ge=0.0)

    precision: float | None = Field(default=None, ge=0.0, le=1.0)
    """Checklist item #11: caller-supplied, from real ground truth (e.g. a
    grounding harness's set-overlap precision) -- TelemetryCollector has
    no way to compute this itself, it only instruments the pipeline. None
    means "no ground truth available for this event," a real and common
    case (most production queries have none), not a missing-data bug."""
    recall: float | None = Field(default=None, ge=0.0, le=1.0)
    """Same caller-supplied contract as `precision`."""

    recorded_at: datetime = Field(default_factory=utc_now)


class TelemetryCollector:
    """In-memory aggregator, zero external networking. Construct one per
    benchmark/test run (or per long-lived service instance, if a caller
    wants standing telemetry), call `.record()` after each real
    resolve()/package() pair, read `.get_run_summary()`/
    `.assert_no_fallbacks()` whenever a summary or a release-gate check is
    needed."""

    def __init__(self) -> None:
        self._events: list[TelemetryEvent] = []

    def record(
        self,
        result: ContextResolutionResult,
        resolve_latency_ms: float,
        package: ContextPackage | None = None,
        package_latency_ms: float | None = None,
        classified_task: RetrievalTaskType | None = None,
        precision: float | None = None,
        recall: float | None = None,
    ) -> TelemetryEvent:
        utilization_ratio = None
        if package is not None and package.budget_max_tokens > 0:
            utilization_ratio = round(package.budget_used_tokens / package.budget_max_tokens, 4)
        event = TelemetryEvent(
            query_id=result.id,
            classified_task=classified_task,
            traversal_depth=result.retrieval_depth_used,
            resolve_latency_ms=resolve_latency_ms,
            package_latency_ms=package_latency_ms,
            origin_breakdown=_origin_breakdown(result),
            token_budget_capacity=package.budget_max_tokens if package is not None else None,
            tokens_utilized=package.budget_used_tokens if package is not None else None,
            utilization_ratio=utilization_ratio,
            precision=precision,
            recall=recall,
        )
        self._events.append(event)
        return event

    @property
    def events(self) -> list[TelemetryEvent]:
        return list(self._events)

    def get_run_summary(self) -> dict:
        """Programmatic summary interface — the shape #11's release gates
        would actually read. Returns plain dict (not a pydantic model):
        this is a read-only aggregation for a CI script to branch on, not
        a payload that itself needs schema validation the way TelemetryEvent
        does."""
        if not self._events:
            return {
                "event_count": 0, "resolve_latency_ms": None, "package_latency_ms": None,
                "origin_breakdown_totals": OriginStageBreakdown().model_dump(),
                "overall_fallback_ratio": 0.0, "mean_utilization_ratio": None,
                "quality_data_available": False, "mean_precision": None, "mean_recall": None,
                "min_recall": None,
            }

        resolve_latencies = [e.resolve_latency_ms for e in self._events]
        package_latencies = [e.package_latency_ms for e in self._events if e.package_latency_ms is not None]
        utilizations = [e.utilization_ratio for e in self._events if e.utilization_ratio is not None]
        precisions = [e.precision for e in self._events if e.precision is not None]
        recalls = [e.recall for e in self._events if e.recall is not None]

        totals = OriginStageBreakdown(
            ast_direct=sum(e.origin_breakdown.ast_direct for e in self._events),
            scoped_graph_expansion=sum(e.origin_breakdown.scoped_graph_expansion for e in self._events),
            raw_string_fallback=sum(e.origin_breakdown.raw_string_fallback for e in self._events),
            evidence_fallback_match=sum(e.origin_breakdown.evidence_fallback_match for e in self._events),
            untagged=sum(e.origin_breakdown.untagged for e in self._events),
        )

        return {
            "event_count": len(self._events),
            "resolve_latency_ms": _latency_stats(resolve_latencies),
            "package_latency_ms": _latency_stats(package_latencies) if package_latencies else None,
            "origin_breakdown_totals": totals.model_dump(),
            "overall_fallback_ratio": totals.fallback_ratio,
            "mean_utilization_ratio": (
                round(statistics.mean(utilizations), 4) if utilizations else None
            ),
            # Checklist item #11: True only when at least one recorded event
            # carried real ground-truth-derived precision/recall -- lets a
            # release gate distinguish "quality checked and fine" from "quality
            # was never checked," which a bare None on the aggregate can't do
            # (an empty list and "everyone scored exactly 0" look identical
            # without this flag).
            "quality_data_available": bool(precisions or recalls),
            "mean_precision": round(statistics.mean(precisions), 4) if precisions else None,
            "mean_recall": round(statistics.mean(recalls), 4) if recalls else None,
            "min_recall": round(min(recalls), 4) if recalls else None,
        }

    def assert_no_fallbacks(self, max_fallback_ratio: float = 0.0) -> None:
        """Release-gate helper for #11: raises AssertionError if the
        aggregate fallback ratio (RAW_STRING_FALLBACK + EVIDENCE_FALLBACK_
        MATCH, across every recorded event) exceeds `max_fallback_ratio`.
        Default 0.0 — a CI gate that wants to allow a small, known-safe
        fallback rate can pass a higher threshold explicitly; the strict
        default matches the checklist item's own "Zero Unflagged
        Re-introductions" framing from item #10."""
        summary = self.get_run_summary()
        ratio = summary["overall_fallback_ratio"]
        if ratio > max_fallback_ratio:
            raise AssertionError(
                f"TelemetryCollector.assert_no_fallbacks: fallback ratio {ratio} exceeds "
                f"max_fallback_ratio {max_fallback_ratio} across {summary['event_count']} "
                f"recorded event(s): {summary['origin_breakdown_totals']}"
            )


def _latency_stats(values: list[float]) -> dict:
    sorted_values = sorted(values)
    n = len(sorted_values)
    return {
        "mean": round(statistics.mean(sorted_values), 3),
        "p50": round(sorted_values[n // 2], 3),
        "p95": round(sorted_values[min(n - 1, int(n * 0.95))], 3),
        "max": round(sorted_values[-1], 3),
    }
