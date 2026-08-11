"""entropy_confidence_experiment.py — falsification experiment, read-only,
recomputes from already-saved data, touches no ARCF source or DRP source.

Hypothesis (from the retrieval-improvement roadmap review, 2026-08-11):
margin confidence (query_router.py's `_margin_confidence`, landed as Fix #3)
only looks at the gap between the TOP TWO subsystems — it's blind to a
different failure shape: many subsystems clustered close together (not just
a close #2), where the winner isn't meaningfully distinguished from the
whole field, not just from one runner-up. Shannon entropy over the full
`combined_score` distribution should catch that shape and should be LOWER
(more confident) exactly when one subsystem dominates, HIGHER (less
confident) when scores are spread across many subsystems near-evenly —
independent of whether margin already flags the top-2 gap as decisive.

Success criterion (stated up front): entropy-confidence must (a) rank the
one unambiguous, correctly-resolved ground-truth repo (Django) above the
confirmed-wrong repositories (Traefik/Consul/vLLM), same direction as
margin already does — if it doesn't even preserve margin's known-correct
ordering, it's a broken metric, not just a redundant one; AND (b) show
measurable disagreement with margin on at least one repo (a case where
margin and entropy rank repos differently) — if the two metrics are always
in lockstep, entropy adds no NEW information and isn't worth shipping as a
second field.

Reuses query_router.py's REAL `_margin_confidence` (imported directly, not
reimplemented) against the same already-saved `subsystem_scores` raw data
Fix #3 itself validated against (docs/drp_benchmark_data/drp_vs_classic_
{sqlalchemy,django,traefik,consul,vllm}.json — the DRP Issue #3 experiment's
5 ground-truth repos, not the extra _alt/_pmi/_vocab_aligned Traefik
variants). No repo re-cloned, no resolver re-run.

v1 RESULT: FALSIFIED. Entropy computed directly over raw combined_score
ranked Traefik (confirmed wrong) above Django (the one clean, correct,
decisive case) — criterion (a) failed outright. Root cause: combined_score
sits in a narrow band across ALL 10 subsystems within a repo (not just the
winner — e.g. Django's own scores span only 0.679-0.925), so naive
sum-normalization into a probability distribution produces near-uniform
probabilities regardless of true decisiveness, drowning out the exact
relative gap margin already detects. See `_entropy_confidence`'s own
docstring, kept in place as the documented negative result.

v2 hypothesis, same session: min-max rescale each repo's own score
distribution to [0, 1] before computing entropy (see
`_rescaled_entropy_confidence`), so the winner is always 1.0 and the
repo's own weakest subsystem is 0.0 — entropy responds to relative
position within each repo's own observed spread instead of being
flattened by the shared absolute band. Tested against the same two
criteria in `main()`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from code_intelligence.drp.query_router import SubsystemScore, _margin_confidence

DATA_DIR = Path(__file__).resolve().parent.parent / "docs" / "drp_benchmark_data"
GROUND_TRUTH_REPOS = ("sqlalchemy", "django", "traefik", "consul", "vllm")


def _entropy_confidence(scores: list[float]) -> float:
    """v1, FALSIFIED 2026-08-11: entropy computed directly over raw
    combined_score. Failed because combined_score sits in a narrow band
    across ALL subsystems (not just the winner) within a repo — e.g.
    Django's own 10 scores span only 0.679-0.925 — so naive sum-
    normalization produces near-uniform probabilities regardless of
    whether the winner is genuinely decisive, drowning out the exact
    relative gap margin is built to detect. Kept here, unused by
    `main()`, as a documented negative result — see this module's own
    docstring for the full falsification writeup."""
    positive = [s for s in scores if s > 0]
    if len(positive) <= 1:
        return 1.0 if positive else 0.0
    total = sum(positive)
    probabilities = [s / total for s in positive]
    entropy = -sum(p * math.log2(p) for p in probabilities)
    max_entropy = math.log2(len(positive))
    normalized = entropy / max_entropy if max_entropy > 0 else 0.0
    return 1.0 - normalized


def _rescaled_entropy_confidence(scores: list[float]) -> float:
    """v2 hypothesis, 2026-08-11: min-max rescale each repo's OWN score
    distribution to [0, 1] before computing entropy — the winner always
    becomes 1.0, the repo's own weakest-scoring subsystem becomes 0.0,
    so entropy responds to each subsystem's position RELATIVE to that
    repo's own observed spread instead of being flattened by the
    absolute narrow band every repo's raw scores share. A subsystem
    exactly at the winner's score would be indistinguishable (entropy
    can't separate ties); a real 2nd-place well below the winner but
    still well above the pack should be visible here even when v1
    couldn't see it."""
    if not scores:
        return 0.0
    if len(scores) == 1:
        return 1.0
    lo, hi = min(scores), max(scores)
    if hi <= lo:
        return 0.0
    rescaled = [(s - lo) / (hi - lo) for s in scores]
    positive = [s for s in rescaled if s > 0]
    if len(positive) <= 1:
        return 1.0
    total = sum(positive)
    probabilities = [s / total for s in positive]
    entropy = -sum(p * math.log2(p) for p in probabilities)
    max_entropy = math.log2(len(positive))
    normalized = entropy / max_entropy if max_entropy > 0 else 0.0
    return 1.0 - normalized


def main() -> None:
    results = []
    for repo in GROUND_TRUTH_REPOS:
        path = DATA_DIR / f"drp_vs_classic_{repo}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_pairs = data["results"]["drp"]["subsystem_scores"]
        combined_scores = [score for _path, score in raw_pairs]

        subsystem_scores = [
            SubsystemScore(
                subsystem_path=p, tfidf_score=0.0, community_score=0.0,
                taxonomy_score=0.0, combined_score=score,
            )
            for p, score in raw_pairs
        ]
        margin = _margin_confidence(subsystem_scores)
        entropy_v1 = _entropy_confidence(combined_scores)
        entropy_v2 = _rescaled_entropy_confidence(combined_scores)

        results.append((repo, margin, entropy_v1, entropy_v2, len(combined_scores)))
        print(
            f"{repo:12s} n_subsystems={len(combined_scores):4d}  "
            f"margin={margin:.4f}  entropy_v1={entropy_v1:.4f}  entropy_v2_rescaled={entropy_v2:.4f}"
        )

    print()
    margin_rank = sorted(results, key=lambda r: -r[1])
    v2_rank = sorted(results, key=lambda r: -r[3])
    print("Margin ranking (most to least confident):        ", [r[0] for r in margin_rank])
    print("Entropy v2 (rescaled) ranking (most confident..): ", [r[0] for r in v2_rank])

    correct = {"django", "sqlalchemy"}  # the 2 ground-truth PASS repos per arcf_drp_issue3_experiment
    print()
    print("=== Testing v2 (rescaled) against the same success criteria ===")
    print("Criterion (a) — does entropy_v2 still put django above all 3 confirmed-wrong repos?")
    django_v2 = next(r[3] for r in results if r[0] == "django")
    wrong_v2 = [r[3] for r in results if r[0] not in correct]
    print(f"  django entropy_v2={django_v2:.4f} vs wrong repos={[round(w,4) for w in wrong_v2]}")
    print(f"  {'PASS' if django_v2 > max(wrong_v2) else 'FAIL'}")

    print()
    print("Criterion (b) — does entropy_v2 ever disagree with margin's ranking (real new info)?")
    disagreement = margin_rank != v2_rank
    print(f"  margin order == entropy_v2 order? {not disagreement}")
    print(f"  {'PASS (real disagreement found)' if disagreement else 'FAIL (metrics always agree, redundant)'}")


if __name__ == "__main__":
    main()
