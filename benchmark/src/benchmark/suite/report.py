"""Aggregates a suite run's SuiteTaskResults into a SuiteRunSummary and
renders the management-ready markdown report.

Every number here is either taken directly off an existing
ComparisonResult/ModeVerification field or is a simple mean/count over
those fields — no metric is invented at this layer, and the verdict is
computed mechanically from the stated Success Criteria, never written
as prose judgment.

Winner rule (stated once, applied identically to every task): a task
is won by whichever mode has the higher accuracy_score; a tie in
accuracy is broken by latency_reduction_pct (ARCF wins ties it's also
faster on); a tie in both is a genuine tie. Tasks missing either
mode's accuracy_score are excluded from the win tally (insufficient
data), not silently counted for either side.
"""

import statistics as pystats

from benchmark.domain.models import ComparisonResult
from benchmark.suite.models import (
    CategorySummary,
    ModeVerification,
    SuiteRunSummary,
    SuiteTaskResult,
    TaskCategory,
)
from benchmark.suite.stats import paired_ttest

TOKEN_REDUCTION_THRESHOLD_PCT = 50.0
CER_THRESHOLD = 0.05
LATENCY_REDUCTION_FLOOR_PCT = -20.0


def _mean(values: list[float]) -> float | None:
    return round(pystats.mean(values), 2) if values else None


def _task_winner(direct: ModeVerification | None, arcf: ModeVerification | None,
                  latency_reduction_pct: float | None) -> str | None:
    if direct is None or arcf is None:
        return None
    if direct.accuracy_score is None or arcf.accuracy_score is None:
        return None
    if arcf.accuracy_score > direct.accuracy_score:
        return "arcf"
    if direct.accuracy_score > arcf.accuracy_score:
        return "direct"
    if latency_reduction_pct is not None and latency_reduction_pct > 0:
        return "arcf"
    return "tie"


def summarize(suite_name: str, results: list[SuiteTaskResult]) -> SuiteRunSummary:
    comparisons: list[ComparisonResult] = [r.comparison for r in results]

    token_reductions = [
        c.token_reduction_pct for c in comparisons if c.token_reduction_pct is not None
    ]
    latency_reductions = [
        c.latency_reduction_pct for c in comparisons if c.latency_reduction_pct is not None
    ]
    cost_reductions = [
        c.cost_reduction_pct for c in comparisons if c.cost_reduction_pct is not None
    ]
    cers = [
        c.context_efficiency_ratio for c in comparisons if c.context_efficiency_ratio is not None
    ]
    pcrs = [
        c.prompt_compression_ratio for c in comparisons if c.prompt_compression_ratio is not None
    ]

    accuracy_deltas = [
        r.arcf_verification.accuracy_score - r.direct_verification.accuracy_score
        for r in results
        if r.arcf_verification is not None
        and r.direct_verification is not None
        and r.arcf_verification.accuracy_score is not None
        and r.direct_verification.accuracy_score is not None
    ]

    grounding_results = [r for r in results if r.category is TaskCategory.REPOSITORY_UNDERSTANDING]
    direct_grounding_scores = [
        r.direct_verification.accuracy_score
        for r in grounding_results
        if r.direct_verification is not None and r.direct_verification.accuracy_score is not None
    ]
    arcf_grounding_scores = [
        r.arcf_verification.accuracy_score
        for r in grounding_results
        if r.arcf_verification is not None and r.arcf_verification.accuracy_score is not None
    ]

    unrelated_deltas = [
        r.arcf_verification.unrelated_file_modifications
        - r.direct_verification.unrelated_file_modifications
        for r in results
        if r.arcf_verification is not None and r.direct_verification is not None
    ]

    winners = [
        _task_winner(r.direct_verification, r.arcf_verification, r.comparison.latency_reduction_pct)
        for r in results
    ]
    arcf_wins = winners.count("arcf")
    direct_wins = winners.count("direct")
    ties = winners.count("tie")

    category_summaries: list[CategorySummary] = []
    for category in TaskCategory:
        cat_results = [r for r in results if r.category is category]
        if not cat_results:
            continue
        cat_winners = [
            _task_winner(
                r.direct_verification, r.arcf_verification, r.comparison.latency_reduction_pct
            )
            for r in cat_results
        ]
        category_summaries.append(
            CategorySummary(
                category=category,
                task_count=len(cat_results),
                arcf_wins=cat_winners.count("arcf"),
                direct_wins=cat_winners.count("direct"),
            )
        )

    latency_pairs = [
        (c.direct.latency_metrics.total_ms, c.arcf.latency_metrics.total_ms)
        for c in comparisons
        if c.direct is not None and c.arcf is not None
    ]
    token_pairs = [
        (float(c.direct.token_metrics.total_tokens), float(c.arcf.token_metrics.total_tokens))
        for c in comparisons
        if c.direct is not None and c.arcf is not None
    ]
    latency_pairs_local = [
        (c.direct.latency_metrics.total_ms, c.arcf_local.latency_metrics.total_ms)
        for c in comparisons
        if c.direct is not None and c.arcf_local is not None
    ]
    token_pairs_local = [
        (float(c.direct.token_metrics.total_tokens), float(c.arcf_local.token_metrics.total_tokens))
        for c in comparisons
        if c.direct is not None and c.arcf_local is not None
    ]
    latency_ttest = paired_ttest([p[0] for p in latency_pairs], [p[1] for p in latency_pairs])
    token_ttest = paired_ttest([p[0] for p in token_pairs], [p[1] for p in token_pairs])
    latency_ttest_local = paired_ttest(
        [p[0] for p in latency_pairs_local], [p[1] for p in latency_pairs_local]
    )
    token_ttest_local = paired_ttest(
        [p[0] for p in token_pairs_local], [p[1] for p in token_pairs_local]
    )

    avg_token_reduction = _mean(token_reductions)
    avg_cer = _mean(cers)
    avg_accuracy_delta = _mean(accuracy_deltas)
    avg_unrelated_delta = _mean([float(d) for d in unrelated_deltas])
    avg_latency_reduction = _mean(latency_reductions)

    criteria_met = sum(
        [
            avg_token_reduction is not None
            and avg_token_reduction >= TOKEN_REDUCTION_THRESHOLD_PCT,
            avg_cer is not None and avg_cer <= CER_THRESHOLD,
            avg_accuracy_delta is not None and avg_accuracy_delta >= 0.0,
            avg_unrelated_delta is not None and avg_unrelated_delta <= 0.0,
            avg_latency_reduction is not None
            and avg_latency_reduction >= LATENCY_REDUCTION_FLOOR_PCT,
        ]
    )
    verdict = "continue" if criteria_met >= 4 else "pivot" if criteria_met >= 2 else "stop"

    return SuiteRunSummary(
        suite_name=suite_name,
        task_count=len(results),
        avg_token_reduction_pct=avg_token_reduction,
        avg_latency_reduction_pct=avg_latency_reduction,
        avg_cost_reduction_pct=_mean(cost_reductions),
        avg_cer=avg_cer,
        avg_pcr=_mean(pcrs),
        avg_accuracy_delta=avg_accuracy_delta,
        avg_direct_grounding_score=_mean(direct_grounding_scores),
        avg_arcf_grounding_score=_mean(arcf_grounding_scores),
        avg_unrelated_file_modifications_delta=avg_unrelated_delta,
        tasks_won_by_arcf=arcf_wins,
        tasks_won_by_direct=direct_wins,
        tasks_tied=ties,
        category_summaries=category_summaries,
        latency_ttest_p_value=latency_ttest[1] if latency_ttest else None,
        token_ttest_p_value=token_ttest[1] if token_ttest else None,
        latency_ttest_p_value_local=latency_ttest_local[1] if latency_ttest_local else None,
        token_ttest_p_value_local=token_ttest_local[1] if token_ttest_local else None,
        verdict=verdict,
    )


def render_executive_summary(summary: SuiteRunSummary) -> str:
    """A CTO/Delivery-Manager-facing artifact distinct from
    render_suite_report's full technical report (Action 3 of the ARCF
    v2.3 Execution Directive lists these as two separate deliverables:
    "Aggregated Report Generator" and "Executive Dashboard Summary").
    Every number here is the SAME summary.* value the full report uses
    — nothing is recomputed or reworded into a softer claim — this is
    just the subset a non-technical reader needs, without the per-task
    detail table.
    """
    lines: list[str] = [
        f"# ARCF Benchmark — Executive Summary ({summary.suite_name})",
        "",
        f"**{summary.task_count} tasks** run, Direct LLM vs. ARCF.",
        "",
        f"- Average token reduction: {_fmt_pct(summary.avg_token_reduction_pct)}",
        f"- Average cost reduction: {_fmt_pct(summary.avg_cost_reduction_pct)}",
        f"- Average latency difference: {_fmt_pct(summary.avg_latency_reduction_pct)}",
        f"- Average Context Efficiency Ratio (CER): {_fmt_ratio_pct(summary.avg_cer)}",
        f"- Average Prompt Compression Ratio (PCR): {_fmt_ratio(summary.avg_pcr)}",
        f"- Average repository grounding score — Direct: "
        f"{_fmt_ratio_pct(summary.avg_direct_grounding_score)}, ARCF: "
        f"{_fmt_ratio_pct(summary.avg_arcf_grounding_score)}",
        "",
        f"- Tasks won by ARCF: **{summary.tasks_won_by_arcf}**",
        f"- Tasks won by Direct LLM: **{summary.tasks_won_by_direct}**",
        f"- Tasks tied: **{summary.tasks_tied}**",
        "",
        "**Statistical significance** (paired t-test, Direct vs. ARCF Remote):",
        f"- Latency: p = {_fmt_p(summary.latency_ttest_p_value)}",
        f"- Tokens: p = {_fmt_p(summary.token_ttest_p_value)}",
        "",
        "## By category",
        "",
    ]
    for cat in summary.category_summaries:
        lines.append(
            f"- **{cat.category.value}** ({cat.task_count} tasks): "
            f"ARCF won {cat.arcf_wins}, Direct won {cat.direct_wins}"
        )
    lines += [
        "",
        "## Final Recommendation",
        "",
        f"**{summary.verdict.upper()}**",
        "",
        _verdict_rationale(summary),
    ]
    return "\n".join(lines)


def render_suite_report(suite_name: str, results: list[SuiteTaskResult]) -> str:
    summary = summarize(suite_name, results)
    lines: list[str] = [f"# ARCF Benchmark Validation Report — {suite_name}", ""]

    lines += ["## Executive Summary", ""]
    lines.append(f"- Tasks run: {summary.task_count}")
    lines.append(f"- Average token reduction: {_fmt_pct(summary.avg_token_reduction_pct)}")
    lines.append(f"- Average latency difference: {_fmt_pct(summary.avg_latency_reduction_pct)}")
    lines.append(f"- Average cost reduction: {_fmt_pct(summary.avg_cost_reduction_pct)}")
    lines.append(f"- Average CER: {_fmt_ratio_pct(summary.avg_cer)}")
    lines.append(f"- Average PCR: {_fmt_ratio(summary.avg_pcr)}")
    lines.append(
        f"- Average accuracy difference (ARCF - Direct): {_fmt_delta(summary.avg_accuracy_delta)}"
    )
    lines.append(
        f"- Average repository grounding score (Direct / ARCF, Repository Understanding "
        f"tasks only): {_fmt_ratio_pct(summary.avg_direct_grounding_score)} / "
        f"{_fmt_ratio_pct(summary.avg_arcf_grounding_score)}"
    )
    lines.append(
        f"- Average unrelated file modifications difference (ARCF - Direct): "
        f"{_fmt_delta(summary.avg_unrelated_file_modifications_delta)}"
    )
    lines.append(f"- Tasks won by ARCF: {summary.tasks_won_by_arcf}")
    lines.append(f"- Tasks won by Direct LLM: {summary.tasks_won_by_direct}")
    lines.append(f"- Tasks tied: {summary.tasks_tied}")
    lines.append(
        f"- Statistical significance (latency, paired t-test): p = "
        f"{_fmt_p(summary.latency_ttest_p_value)}"
    )
    lines.append(
        f"- Statistical significance (tokens, paired t-test): p = "
        f"{_fmt_p(summary.token_ttest_p_value)}"
    )
    lines.append(
        f"- Statistical significance (latency, Direct vs ARCF Local): p = "
        f"{_fmt_p(summary.latency_ttest_p_value_local)}"
    )
    lines.append(
        f"- Statistical significance (tokens, Direct vs ARCF Local): p = "
        f"{_fmt_p(summary.token_ttest_p_value_local)}"
    )
    lines.append("")

    lines += ["### By category", ""]
    for cat in summary.category_summaries:
        lines.append(
            f"- **{cat.category.value}** ({cat.task_count} tasks): "
            f"ARCF won {cat.arcf_wins}, Direct won {cat.direct_wins}"
        )
    lines.append("")

    lines += ["## Detailed Table", ""]
    lines.append(
        "| Task | Direct Tokens | ARCF Tokens | Reduction | Direct Latency | ARCF Latency | "
        "CER | PCR | Accuracy (D/A) | Winner |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for result in results:
        lines.append(_detail_row(result))
    lines.append("")

    lines += ["## Final Verdict", ""]
    lines.append(f"**{summary.verdict.upper()}**")
    lines.append("")
    lines.append(_verdict_rationale(summary))

    return "\n".join(lines)


def _detail_row(result: SuiteTaskResult) -> str:
    c = result.comparison
    direct_tokens = c.direct.token_metrics.total_tokens if c.direct else None
    arcf_tokens = c.arcf.token_metrics.total_tokens if c.arcf else None
    direct_latency = c.direct.latency_metrics.total_ms if c.direct else None
    arcf_latency = c.arcf.latency_metrics.total_ms if c.arcf else None
    direct_acc = result.direct_verification.accuracy_score if result.direct_verification else None
    arcf_acc = result.arcf_verification.accuracy_score if result.arcf_verification else None
    winner = _task_winner(
        result.direct_verification, result.arcf_verification, c.latency_reduction_pct
    )

    return (
        f"| {result.task_id} | {_fmt_int(direct_tokens)} | {_fmt_int(arcf_tokens)} | "
        f"{_fmt_pct(c.token_reduction_pct)} | {_fmt_ms(direct_latency)} | "
        f"{_fmt_ms(arcf_latency)} | "
        f"{_fmt_ratio_pct(c.context_efficiency_ratio)} | "
        f"{_fmt_ratio(c.prompt_compression_ratio)} | "
        f"{_fmt_score(direct_acc)}/{_fmt_score(arcf_acc)} | {winner or 'n/a'} |"
    )


def _verdict_rationale(summary: SuiteRunSummary) -> str:
    checks = [
        ("50%+ average token reduction",
         summary.avg_token_reduction_pct is not None
         and summary.avg_token_reduction_pct >= TOKEN_REDUCTION_THRESHOLD_PCT),
        ("CER below 5%", summary.avg_cer is not None and summary.avg_cer <= CER_THRESHOLD),
        ("Equal or better accuracy",
         summary.avg_accuracy_delta is not None and summary.avg_accuracy_delta >= 0.0),
        ("Equal or fewer unrelated file modifications",
         summary.avg_unrelated_file_modifications_delta is not None
         and summary.avg_unrelated_file_modifications_delta <= 0.0),
        ("Latency within 20% of Direct, or faster",
         summary.avg_latency_reduction_pct is not None
         and summary.avg_latency_reduction_pct >= LATENCY_REDUCTION_FLOOR_PCT),
    ]
    lines = [f"- [{'x' if passed else ' '}] {label}" for label, passed in checks]
    return "\n".join(lines)


def _fmt_pct(v: float | None) -> str:
    return f"{v:.1f}%" if v is not None else "n/a"


def _fmt_ratio_pct(v: float | None) -> str:
    return f"{v * 100:.1f}%" if v is not None else "n/a"


def _fmt_ratio(v: float | None) -> str:
    return f"{v:.1f}x" if v is not None else "n/a"


def _fmt_delta(v: float | None) -> str:
    return f"{v:+.2f}" if v is not None else "n/a"


def _fmt_p(v: float | None) -> str:
    return f"{v:.4f}" if v is not None else "n/a (insufficient data)"


def _fmt_int(v: int | None) -> str:
    return f"{v:,}" if v is not None else "n/a"


def _fmt_ms(v: float | None) -> str:
    return f"{v:.0f} ms" if v is not None else "n/a"


def _fmt_score(v: float | None) -> str:
    return f"{v:.2f}" if v is not None else "n/a"
