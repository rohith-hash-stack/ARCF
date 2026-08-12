"""production_gate.py — checklist item #11 (arcf/CHECKLIST.md). Standalone,
programmatic release gate evaluator: consumes RunSummary dicts (the exact
return shape of infrastructure.telemetry.TelemetryCollector.get_run_summary()
— item #13) and emits an immutable, automated pass/fail decision, no manual
trace inspection required.

Never imports ContextResolver/ContextPackager or anything in the retrieval
pipeline itself — a pure downstream consumer of already-computed RunSummary
data, so a retrieval pass that never calls this module is untouched by
construction ("Zero Overhead on Baseline").

Scope correction (see this item's own CHECKLIST.md entry for the full
reasoning): the spec's Quality Gate wants "zero statistically significant
precision drops" — implemented here as a percentage-drop threshold against a
supplied baseline, not a true significance test (no scipy dependency added
to keep this module dependency-light, matching "Zero Overhead on Baseline"
in spirit too) — a deliberate simplification, not silently assumed rigorous.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from shared.clock import utc_now

RunSummary = dict


class GateName(StrEnum):
    FALLBACK = "fallback"
    LATENCY = "latency"
    TOKEN_BUDGET = "token_budget"
    QUALITY = "quality"


class ReleaseGateConfig(BaseModel):
    """All thresholds configurable, all defaulted to the spec's own stated
    values."""

    model_config = ConfigDict(frozen=True)

    max_fallback_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    """RAW_STRING_FALLBACK + EVIDENCE_FALLBACK_MATCH ratio ceiling. Default
    0.0 matches item #10's own "Zero Unflagged Re-introductions" framing."""
    max_latency_overhead_pct: float = Field(default=5.0)
    """Relative to a supplied baseline RunSummary's mean resolve latency —
    the spec's own "Δ Latency ≤ +5%"."""
    max_utilization_ratio: float = Field(default=0.95, ge=0.0)
    """Ceiling on mean_utilization_ratio (tokens_utilized /
    token_budget_capacity, averaged across the run)."""
    min_recall: float = Field(default=1.0, ge=0.0, le=1.0)
    """Floor on the run's MINIMUM per-query recall (not the mean) — "100%"
    means every query, not just the average."""
    max_precision_drop_pct: float = Field(default=0.0)
    """Relative to a supplied baseline RunSummary's mean precision, when
    both candidate and baseline have quality data."""


class GateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    gate_name: GateName
    passed: bool
    skipped: bool = False
    """True when the gate had no data to evaluate (e.g. no baseline
    supplied for the latency gate, no ground truth for the quality gate) —
    distinct from `passed=True`, which means "evaluated and fine." A
    skipped gate never blocks a release on its own, but IS visible in the
    decision so "never checked" is never confused with "checked and
    passed."""
    detail: str
    measured_value: float | None = None
    threshold: float | None = None


class ReleaseDecision(BaseModel):
    """Immutable binary result — RELEASE_APPROVED / RELEASE_REJECTED, per
    the spec's own naming, exposed as `.status`."""

    model_config = ConfigDict(frozen=True)

    approved: bool
    gate_results: tuple[GateResult, ...]
    evaluated_at: datetime = Field(default_factory=utc_now)

    @property
    def status(self) -> str:
        return "RELEASE_APPROVED" if self.approved else "RELEASE_REJECTED"

    def failure_report(self) -> str:
        """Detailed failure report specifying exact metric violations, per
        the spec's own "Structured Decision Output" requirement."""
        failing = [g for g in self.gate_results if not g.passed and not g.skipped]
        if not failing:
            return f"{self.status}: no gate failures."
        lines = [f"{self.status}: {len(failing)} gate(s) failed"]
        for g in failing:
            lines.append(
                f"  - {g.gate_name.value}: {g.detail} "
                f"(measured={g.measured_value}, threshold={g.threshold})"
            )
        return "\n".join(lines)


def _fallback_gate(summary: RunSummary, config: ReleaseGateConfig) -> GateResult:
    ratio = summary.get("overall_fallback_ratio")
    if summary.get("event_count", 0) == 0:
        return GateResult(
            gate_name=GateName.FALLBACK, passed=True, skipped=True,
            detail="no events recorded in this run",
        )
    passed = ratio <= config.max_fallback_ratio
    return GateResult(
        gate_name=GateName.FALLBACK, passed=passed,
        detail=(
            f"fallback ratio {ratio} "
            f"{'within' if passed else 'EXCEEDS'} max {config.max_fallback_ratio}"
        ),
        measured_value=ratio, threshold=config.max_fallback_ratio,
    )


def _latency_gate(
    summary: RunSummary, baseline_summary: RunSummary | None, config: ReleaseGateConfig
) -> GateResult:
    candidate_latency = summary.get("resolve_latency_ms")
    if candidate_latency is None:
        return GateResult(
            gate_name=GateName.LATENCY, passed=True, skipped=True,
            detail="candidate run has no latency data",
        )
    if baseline_summary is None or baseline_summary.get("resolve_latency_ms") is None:
        return GateResult(
            gate_name=GateName.LATENCY, passed=True, skipped=True,
            detail="no baseline supplied -- cannot compute relative overhead",
        )
    baseline_mean = baseline_summary["resolve_latency_ms"]["mean"]
    candidate_mean = candidate_latency["mean"]
    if baseline_mean <= 0:
        return GateResult(
            gate_name=GateName.LATENCY, passed=True, skipped=True,
            detail="baseline mean latency is zero -- cannot compute relative overhead",
        )
    overhead_pct = round((candidate_mean - baseline_mean) / baseline_mean * 100, 4)
    passed = overhead_pct <= config.max_latency_overhead_pct
    return GateResult(
        gate_name=GateName.LATENCY, passed=passed,
        detail=(
            f"latency overhead {overhead_pct}% "
            f"{'within' if passed else 'EXCEEDS'} max +{config.max_latency_overhead_pct}%"
        ),
        measured_value=overhead_pct, threshold=config.max_latency_overhead_pct,
    )


def _token_budget_gate(summary: RunSummary, config: ReleaseGateConfig) -> GateResult:
    ratio = summary.get("mean_utilization_ratio")
    if ratio is None:
        return GateResult(
            gate_name=GateName.TOKEN_BUDGET, passed=True, skipped=True,
            detail="no budget utilization data (no package() calls recorded)",
        )
    passed = ratio <= config.max_utilization_ratio
    return GateResult(
        gate_name=GateName.TOKEN_BUDGET, passed=passed,
        detail=(
            f"mean utilization {ratio} "
            f"{'within' if passed else 'EXCEEDS'} max {config.max_utilization_ratio}"
        ),
        measured_value=ratio, threshold=config.max_utilization_ratio,
    )


def _quality_gate(
    summary: RunSummary, baseline_summary: RunSummary | None, config: ReleaseGateConfig
) -> GateResult:
    if not summary.get("quality_data_available"):
        return GateResult(
            gate_name=GateName.QUALITY, passed=True, skipped=True,
            detail="no ground-truth precision/recall supplied for this run",
        )
    min_recall = summary.get("min_recall")
    recall_ok = min_recall is not None and min_recall >= config.min_recall
    reasons = [f"min recall {min_recall} {'meets' if recall_ok else 'BELOW'} required {config.min_recall}"]

    precision_ok = True
    if (
        baseline_summary is not None
        and baseline_summary.get("quality_data_available")
        and baseline_summary.get("mean_precision")
    ):
        baseline_precision = baseline_summary["mean_precision"]
        candidate_precision = summary.get("mean_precision")
        if baseline_precision > 0 and candidate_precision is not None:
            drop_pct = round((baseline_precision - candidate_precision) / baseline_precision * 100, 4)
            precision_ok = drop_pct <= config.max_precision_drop_pct
            reasons.append(
                f"precision drop {drop_pct}% "
                f"{'within' if precision_ok else 'EXCEEDS'} max {config.max_precision_drop_pct}%"
            )

    passed = recall_ok and precision_ok
    return GateResult(
        gate_name=GateName.QUALITY, passed=passed, detail="; ".join(reasons),
        measured_value=min_recall, threshold=config.min_recall,
    )


def evaluate_release(
    candidate_summary: RunSummary,
    baseline_summary: RunSummary | None = None,
    config: ReleaseGateConfig | None = None,
) -> ReleaseDecision:
    """The Programmatic Release Gate Runner. `candidate_summary` (required)
    and `baseline_summary` (optional — required only for the latency and
    precision-drop comparisons, both of which SKIP rather than fail when
    absent) must both be real `TelemetryCollector.get_run_summary()` return
    values — this function reads no other data source, satisfying "100% of
    metric inputs originate from the RunSummary interface" by construction,
    not by convention."""
    cfg = config or ReleaseGateConfig()
    gate_results = (
        _fallback_gate(candidate_summary, cfg),
        _latency_gate(candidate_summary, baseline_summary, cfg),
        _token_budget_gate(candidate_summary, cfg),
        _quality_gate(candidate_summary, baseline_summary, cfg),
    )
    approved = all(g.passed for g in gate_results)
    return ReleaseDecision(approved=approved, gate_results=gate_results)


def compare_collectors(baseline_summary: RunSummary, candidate_summary: RunSummary, config: ReleaseGateConfig | None = None) -> ReleaseDecision:
    """Shadow/canary evaluation driver: evaluates a candidate run
    side-by-side against a baseline run's RunSummary, without either
    touching the other or any live retrieval pipeline. Works with any two
    real `TelemetryCollector.get_run_summary()` outputs — two genuinely
    different ARCF configurations when one exists to compare, a repeat-run
    smoke test (baseline == candidate config, should always approve), or
    synthetic/injected summaries for regression-sensitivity testing. This
    is literally `evaluate_release` with the baseline wired in — the
    "driver" is the calling convention, not a different mechanism."""
    return evaluate_release(candidate_summary, baseline_summary=baseline_summary, config=config)
