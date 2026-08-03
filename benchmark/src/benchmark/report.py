"""render_text_report — the plain-text, side-by-side Direct / ARCF
Remote / ARCF Local report format, plus a success-criteria checklist
computed directly off the ComparisonResult (no re-derivation of numbers
already computed by BenchmarkAnalyzer/ArcfRunner).

Each mode's own section reports "Context Sent" (files_sent_to_llm /
repository_files for THAT mode) — how much of the repo it used. This is
deliberately a different number from the Delta section's CER
(BenchmarkAnalyzer's arcf.files_sent_to_llm / direct.files_sent_to_llm
ratio, already established by the existing 2-mode benchmark): CER
compares two modes against each other, "Context Sent" describes one
mode on its own, and conflating the two under one label would make
Direct's context-sent figure ("almost the whole repo") look like a
comparison ratio it isn't.

Quality is reported structurally (answer length, modified files) rather
than auto-judged pass/fail — there's no LLM-judge or ground-truth oracle
in scope, so "quality equal or better than Direct" is left for the
operator to read generated_output and decide, rather than faking an
automated verdict.
"""

from benchmark.domain.models import BenchmarkMode, ComparisonResult, RunResult

_MODE_LABELS: dict[BenchmarkMode, str] = {
    BenchmarkMode.DIRECT: "Direct LLM",
    BenchmarkMode.ARCF: "ARCF Remote",
    BenchmarkMode.ARCF_LOCAL: "ARCF Local",
}

_LOCAL_SLM_LATENCY_BUDGET_MS = 1000.0
_CER_SUCCESS_RANGE = (0.01, 0.03)


def render_text_report(result: ComparisonResult) -> str:
    lines: list[str] = [
        f"Task: {result.task}",
        "",
        f"Repository: {result.repository}",
        "",
        f"Model: {result.model}",
    ]

    for mode, run in (
        (BenchmarkMode.DIRECT, result.direct),
        (BenchmarkMode.ARCF, result.arcf),
        (BenchmarkMode.ARCF_LOCAL, result.arcf_local),
    ):
        if run is None:
            continue
        lines += ["", "---", "", *_render_run(mode, run)]

    lines += ["", "---", "", *_render_delta(result)]
    lines += ["", "---", "", *_render_success_criteria(result)]

    return "\n".join(lines)


def _render_run(mode: BenchmarkMode, run: RunResult) -> list[str]:
    lines = [
        _MODE_LABELS[mode],
        "",
        f"Input Tokens: {run.token_metrics.input_tokens:,}",
        "",
        f"Latency: {run.latency_metrics.total_ms / 1000:.1f} s",
    ]

    stages = run.latency_metrics.stages
    if stages is not None:
        lines += [
            "",
            f"  Intent Extraction (SLM-1): {stages.intent_extraction_ms:.0f} ms",
            f"  Workspace Scan: {stages.workspace_scan_ms:.0f} ms",
            f"  Code Intelligence / Context Resolution: {stages.code_intelligence_ms:.0f} ms",
            f"  Context Packaging: {stages.context_packaging_ms:.0f} ms",
            f"  Final LLM Call: {stages.final_llm_ms:.0f} ms",
        ]

    lines.append("")
    if run.context_metrics.repository_files:
        context_sent_pct = (
            run.context_metrics.files_sent_to_llm / run.context_metrics.repository_files * 100
        )
        lines.append(f"Context Sent: {context_sent_pct:.1f}% of repository")
    else:
        lines.append("Context Sent: n/a")

    lines.append(f"Answer Length: {run.quality_metrics.answer_length:,} chars")
    lines.append(f"Modified Files: {len(run.quality_metrics.modified_files)}")
    return lines


def _render_delta(result: ComparisonResult) -> list[str]:
    lines = ["Delta", ""]

    if result.arcf is not None:
        lines.append(_pct_line("Token Reduction (ARCF Remote)", result.token_reduction_pct))
        lines.append(_pct_line("Latency Reduction (ARCF Remote)", result.latency_reduction_pct))
        lines.append(_ratio_pct_line("CER (ARCF Remote)", result.context_efficiency_ratio))
        lines.append(_ratio_line("PCR (ARCF Remote)", result.prompt_compression_ratio))

    if result.arcf_local is not None:
        lines.append("")
        lines.append(_pct_line("Token Reduction (ARCF Local)", result.local_token_reduction_pct))
        lines.append(
            _pct_line("Latency Reduction (ARCF Local)", result.local_latency_reduction_pct)
        )
        lines.append(_ratio_pct_line("CER (ARCF Local)", result.local_context_efficiency_ratio))
        lines.append(_ratio_line("PCR (ARCF Local)", result.local_prompt_compression_ratio))

    if result.arcf is not None and result.arcf_local is not None:
        lines.append("")
        lines.append(
            _pct_line(
                "Local vs Remote Latency Reduction",
                result.local_vs_remote_latency_reduction_pct,
            )
        )
        lines.append(
            "Quality Difference: see Answer Length / Modified Files above — "
            "no automated quality judge is in scope, inspect generated_output directly."
        )

    return lines


def _render_success_criteria(result: ComparisonResult) -> list[str]:
    lines = ["Success Criteria"]
    local = result.arcf_local
    direct = result.direct

    if local is None:
        lines.append("- Local SLM not run this comparison (arcf_local missing).")
        return lines

    stages = local.latency_metrics.stages
    intent_ms = stages.intent_extraction_ms if stages is not None else None
    lines.append(
        _check_line(
            "Local SLM latency < 1 s",
            intent_ms is not None and intent_ms < _LOCAL_SLM_LATENCY_BUDGET_MS,
            f"{intent_ms:.0f} ms" if intent_ms is not None else "n/a",
        )
    )

    if direct is not None:
        lines.append(
            _check_line(
                "Total ARCF Local latency < Direct latency",
                local.latency_metrics.total_ms < direct.latency_metrics.total_ms,
                f"{local.latency_metrics.total_ms:.0f} ms vs "
                f"{direct.latency_metrics.total_ms:.0f} ms",
            )
        )

    cer = result.local_context_efficiency_ratio
    lines.append(
        _check_line(
            "CER approximately 1-3%",
            cer is not None and _CER_SUCCESS_RANGE[0] <= cer <= _CER_SUCCESS_RANGE[1],
            f"{cer * 100:.1f}%" if cer is not None else "n/a",
        )
    )

    lines.append(
        "- [ ] Answer quality equal or better than Direct LLM — not automatically "
        "verified, no quality oracle in scope; compare generated_output manually."
    )
    return lines


def _pct_line(label: str, value: float | None) -> str:
    return f"{label}: {value:.1f}%" if value is not None else f"{label}: n/a"


def _ratio_pct_line(label: str, value: float | None) -> str:
    return f"{label}: {value * 100:.1f}%" if value is not None else f"{label}: n/a"


def _ratio_line(label: str, value: float | None) -> str:
    return f"{label}: {value:.1f}x" if value is not None else f"{label}: n/a"


def _check_line(label: str, passed: bool, actual: str) -> str:
    mark = "x" if passed else " "
    return f"- [{mark}] {label} (actual: {actual})"
