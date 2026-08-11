"""drp_confidence_calibration_experiment.py — falsification experiment for
a proposed replacement of DRP's exposed confidence metric.

Context: query_router.py's current `winning_confidence` is
`winner.combined_score / sum(every subsystem's combined_score)` — the
winner's SHARE OF TOTAL SCORE MASS across the whole taxonomy. This is
mechanically dominated by how many subsystems the repo has (more
subsystems -> smaller share -> lower "confidence", independent of
whether the pick was actually decisive), not by how much the winner beat
its closest competitor. Manual inspection during the 2026-08-10 repo
sweep found this metric numerically indistinguishable between DRP's best
and worst answers on the same (large) repo.

This script tests a candidate replacement — a MARGIN-based metric,
comparing the winner's combined_score against the runner-up's, which is
already computed and used internally for near-tie detection
(query_router.py's `_NEAR_TIE_MARGIN`) but never surfaced as the
reported confidence:

    new_confidence = (top1.combined_score - top2.combined_score) / top1.combined_score

against DRP's own 5-repo ground-truth benchmark suite (the same repos
used throughout the 2026-08 DRP experiment: SQLAlchemy, Django pass;
Traefik, Consul, vLLM fail) using data ALREADY on disk in
docs/drp_benchmark_data/*.json (each file's `subsystem_scores` list is
the top-10 (subsystem_path, combined_score) pairs from a real DRP run,
plus ground truth via `target_retrieved`). No repo re-cloned, no DRP
re-run — this is a pure, deterministic recomputation from already-saved
routing output, read-only.

Success criterion (defined before looking at the results table below):
the new metric must separate the one genuinely decisive, correct case
(Django, whose target file sits in an unambiguous winning subsystem)
from the ambiguous/incorrect cases by a wide, unambiguous margin — not
just "look more reasonable". Failure criterion: if the new metric's
values for known-wrong cases are comparable to or higher than for the
known-decisive-right case, or if it's no more separable than the old
metric, the proposal is falsified as-is.

This script does not modify any production DRP code.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "docs" / "drp_benchmark_data"

# The 5 ground-truth repos from the closed DRP Issue #3 experiment, with
# known pass/fail status per its own final verdict.
BENCHMARK_FILES = {
    "sqlalchemy": ("drp_vs_classic_sqlalchemy.json", "PASS"),
    "django": ("drp_vs_classic_django.json", "PASS"),
    "traefik": ("drp_vs_classic_traefik.json", "FAIL"),
    "consul": ("drp_vs_classic_consul.json", "FAIL"),
    "vllm": ("drp_vs_classic_vllm.json", "FAIL"),
}


def margin_confidence(subsystem_scores: list[tuple[str, float]]) -> float:
    """The proposed replacement metric — how decisively subsystem #1 beat
    subsystem #2, independent of how many other subsystems exist. Three
    explicit cases, matching the "decisive / ambiguous / no signal"
    contract this metric is meant to support downstream:
      - no subsystems at all -> 0.0 (nothing to be confident about)
      - top1 score is zero or negative -> 0.0 (no real signal; a margin
        computed against zero would be meaningless)
      - only one subsystem scored -> 1.0 (no competition = maximally
        decisive by definition, not evidence of a strong match)
      - otherwise -> the normalized gap between #1 and #2
    """
    if not subsystem_scores:
        return 0.0
    top1 = subsystem_scores[0][1]
    if top1 <= 0:
        return 0.0
    if len(subsystem_scores) == 1:
        return 1.0
    top2 = subsystem_scores[1][1]
    return max(0.0, (top1 - top2) / top1)


def main() -> None:
    rows = []
    for repo, (filename, verdict) in BENCHMARK_FILES.items():
        data = json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))
        drp = data["results"]["drp"]
        old_confidence = drp["confidence"]
        scores = [(path, score) for path, score in drp["subsystem_scores"]]
        new_confidence = margin_confidence(scores)
        rows.append(
            {
                "repo": repo,
                "verdict": verdict,
                "target_retrieved": drp["target_retrieved"],
                "old_confidence": old_confidence,
                "new_margin_confidence": new_confidence,
                "top1": scores[0] if scores else None,
                "top2": scores[1] if len(scores) > 1 else None,
            }
        )

    # Sort by verdict then old confidence to show the old metric's lack
    # of structure, then print both metrics side by side.
    print(f"{'repo':<12} {'verdict':<6} {'old_conf':>10} {'new_margin':>12}   top1 vs top2")
    print("-" * 100)
    for r in rows:
        top1_label = f"{r['top1'][0]} ({r['top1'][1]:.4f})" if r["top1"] else "-"
        top2_label = f"{r['top2'][0]} ({r['top2'][1]:.4f})" if r["top2"] else "-"
        print(
            f"{r['repo']:<12} {r['verdict']:<6} {r['old_confidence']:>10.5f} "
            f"{r['new_margin_confidence']:>12.5f}   {top1_label}  vs  {top2_label}"
        )

    print()
    pass_rows = [r for r in rows if r["verdict"] == "PASS"]
    fail_rows = [r for r in rows if r["verdict"] == "FAIL"]
    old_pass_avg = sum(r["old_confidence"] for r in pass_rows) / len(pass_rows)
    old_fail_avg = sum(r["old_confidence"] for r in fail_rows) / len(fail_rows)
    new_pass_avg = sum(r["new_margin_confidence"] for r in pass_rows) / len(pass_rows)
    new_fail_avg = sum(r["new_margin_confidence"] for r in fail_rows) / len(fail_rows)
    print(f"OLD metric: PASS avg={old_pass_avg:.5f}  FAIL avg={old_fail_avg:.5f}  "
          f"(PASS higher than FAIL: {old_pass_avg > old_fail_avg})")
    print(f"NEW metric: PASS avg={new_pass_avg:.5f}  FAIL avg={new_fail_avg:.5f}  "
          f"(PASS higher than FAIL: {new_pass_avg > new_fail_avg})")

    print()
    print("Per-repo old-metric rank order (descending):",
          [r["repo"] for r in sorted(rows, key=lambda r: -r["old_confidence"])])
    print("Per-repo new-metric rank order (descending):",
          [r["repo"] for r in sorted(rows, key=lambda r: -r["new_margin_confidence"])])


if __name__ == "__main__":
    main()
