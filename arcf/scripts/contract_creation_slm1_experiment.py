"""contract_creation_slm1_experiment.py — falsification experiment. Makes
real, fresh SLM-1 calls (small cost — this is the thing being measured)
against real queries, then compares against the deterministic classifiers
(DomainClassifier/TaskClassifier) that already run independently in
ExecutionContractManager._build_intent. Touches no ARCF source.

Context: the earlier slm1_bypass_experiment.py proved entities/target_names
don't help RESOLUTION — but manager.py shows the real production SLM-1
round-trip cost is paid at CONTRACT CREATION (Phase 3), a mandatory step
before resolution can even run, and its output feeds confidence.py's
ConfidenceEngine (domain_known/task_known/domain_agrees/task_agrees/
entity_count/constraint_count/assumption_count/self_reported_confidence)
and clarification.py's ClarificationPlanner — not just entities.

confidence.py's own weights: domain_known + task_known = 0.40 of the total
score, and BOTH are already independently computable by DomainClassifier.
classify()/TaskClassifier.classify() with no LLM at all. domain_agrees +
task_agrees = another 0.30, but "agreement" requires TWO independent
guesses — if SLM-1 is removed, there's nothing left to agree WITH, so that
signal becomes structurally meaningless, not just harder to compute.

Hypothesis under test: if the deterministic classifiers' own domain/task
guess already matches what real SLM-1 independently guesses on most real
queries, then the "agreement" signal is ALREADY close to redundant in
practice (SLM-1 mostly just confirms what the deterministic classifier
would have said alone) — meaning removing SLM-1 and using ONLY the
deterministic classifier's own domain/task (redesigning confidence.py to
drop the agreement terms, redistributing their weight) might lose little.
If they frequently DISAGREE, SLM-1 is catching real cases the deterministic
classifier alone would get wrong, and removing it would be a real quality
loss to confidence scoring.

Success criterion (stated up front): >=80% domain AND task agreement
between real SLM-1 and the deterministic classifiers, across a real,
varied query sample, would support the hypothesis that corroboration is
mostly redundant. Below that, report honestly that SLM-1's classification
is catching real disagreement the deterministic classifier can't replicate
alone — don't round up to "good enough" if the number is unconvincing.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from contracts.domain_classifier import DomainClassifier
from contracts.intent_extraction import IntentExtractor
from contracts.task_classifier import TaskClassifier
from infrastructure.llm_client import LiteLLMClient

SWEEP_DIR = Path(__file__).resolve().parent.parent / "docs" / "repo_query_answers"
GENERATION_MODEL = "gpt-4o-mini"

# A handful of additional, deliberately varied queries beyond the 12 sweep
# ones — different domains/tasks/phrasing styles, so the sample isn't only
# "explain X" style questions from one fixture batch.
EXTRA_QUERIES = [
    "Fix the null pointer exception in the login handler.",
    "Write unit tests for the new payment processing module.",
    "Document the REST API endpoints for the user service.",
    "Optimize the database query that's causing slow page loads.",
    "Set up CI/CD pipeline configuration for automated deployment.",
]


async def main() -> None:
    client = LiteLLMClient(max_retries=3, base_delay_seconds=0.5)
    extractor = IntentExtractor(client, model=GENERATION_MODEL)
    domain_classifier = DomainClassifier()
    task_classifier = TaskClassifier()

    queries = [json.loads(f.read_text(encoding="utf-8"))["query"] for f in sorted(SWEEP_DIR.glob("*.json"))]
    queries += EXTRA_QUERIES

    domain_agree = 0
    task_agree = 0
    total = 0
    for query in queries:
        raw, _ = await extractor.extract(query)
        det_domain = domain_classifier.classify(query)
        det_task = task_classifier.classify(query)
        domain_matches = domain_classifier.agrees_with(query, raw.domain)
        task_matches = task_classifier.agrees_with(query, raw.task)

        total += 1
        domain_agree += domain_matches
        task_agree += task_matches

        tag_d = "AGREE" if domain_matches else "DISAGREE"
        tag_t = "AGREE" if task_matches else "DISAGREE"
        print(f"\n=== {query[:65]!r} ===")
        print(f"  domain: slm1={raw.domain!r:15s} deterministic={det_domain!r:15s} [{tag_d}]")
        print(f"  task:   slm1={raw.task!r:15s} deterministic={det_task!r:15s} [{tag_t}]")
        print(f"  slm1 entities={raw.entities!r} constraints={raw.constraints!r} "
              f"assumptions={raw.assumptions!r} self_conf={raw.self_reported_confidence:.2f}")

    print(f"\n=== Summary: domain agreement {domain_agree}/{total} ({domain_agree/total:.0%}), "
          f"task agreement {task_agree}/{total} ({task_agree/total:.0%}) ===")


if __name__ == "__main__":
    asyncio.run(main())
