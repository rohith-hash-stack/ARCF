"""Retrieval ground-truth tasks for the semantic-layer experiment.

Per the experiment brief's Step 5 ("reuse existing tasks wherever
possible ... do not create a new artificial benchmark merely to make
the SLM look good"):

IMPORTANT, honest correction rather than an assumption: this codebase
has no benchmark suite literally named "Phase 3" and no task category
literally named "Category B ambiguous symbol" (confirmed by exhaustive
grep across `arcf/` and `benchmark/` — see the experiment report's
architecture-map section). The closest real, reusable ground truth with
a single unambiguous target file per task is `benchmark/suites/
pilot.json`'s five `repo_key: "arcf"` tasks — `arcf` is the one
benchmark repository actually present and usable in this sandbox (the
repos `arcf/scripts/validate_llm_grounding.py` uses, e.g. Consul, and
`.benchmark_repos/{consul,django,fastapi,flask,sqlalchemy,traefik,
vllm}/`, are empty directories here — see the report).

`ARCF_REPO_RETRIEVAL_TASKS[:5]` below are a direct, minimal projection
of those five pilot.json tasks down to a single `target_file` (derived
from each task's own existing `expected_path_prefixes` or
`expected_grounding` — no new queries, no new ground truth invented for
those five).

A known, honestly-flagged weakness of reusing them for THIS experiment:
three of the five (`bug-fixing-jwt-missing-sub`, `bug-fixing-idempotency
-replay`, `refactoring-retry-exception-resolution`) state their target
file's path VERBATIM inside the query text itself (they were authored
for end-to-end code-generation scoring, not for stressing semantic
ambiguity) — ARCF-DI's lexical-probe fallback can resolve these
regardless of what the semantic layer does, so they cannot discriminate
between semantic-interpretation quality levels. Kept anyway (removing
real, already-graded tasks to make a suite "harder" would be its own
form of cherry-picking) but their results should be read as a
regression check, not a semantic-sensitivity signal.

The 6th task, `ambiguous-symbol-save`, is NEW — constructed for this
experiment specifically because no ambiguous-symbol fixture exists
anywhere runnable in this sandbox, following the same discipline
`arcf/scripts/validate_llm_grounding.py`'s `task5_ambiguous_common_name`
used for Consul's `New`: grep-VERIFIED against the real, present `arcf`
source (not assumed), not hand-picked post hoc from a run's output.
`save` is defined 12 times across 5 different files in `arcf/src`
(`infrastructure/contract_store.py` x3 incl. the Protocol stub,
`context_resolution_store.py` x2, `idempotency.py` x1,
`comparison_store.py` x3, `execution_ledger_db.py` x3 — verified via
`grep -rn "^\\s*def save("` before this task was written, not after).
This is exactly the "short, common, ambiguous name across many files"
shape the experiment brief calls out. Its target is the ONE file that
answers the specific question asked, not "any file with a save method".
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RetrievalTask:
    task_id: str
    category: str
    query: str
    target_file: str
    """Single ground-truth file, relative to the repo root, whose rank
    within ARCF-DI's candidate pool Recall@k/MRR are computed against."""
    expected_grounding_terms: list[str] = field(default_factory=list)
    """Used only by suite/retrieval_scoring.py's C/D/F failure-
    classification heuristic — never part of the rank computation
    itself."""
    known_ambiguous: bool = False
    reused_from_pilot_json: bool = True


ARCF_REPO_RETRIEVAL_TASKS: list[RetrievalTask] = [
    RetrievalTask(
        task_id="repo-understanding-auth-discovery",
        category="repository_understanding",
        query=(
            "Explain how this repository authenticates incoming API requests: which module "
            "and class handle it, which credential schemes are supported, and what happens "
            "when authentication fails."
        ),
        target_file="src/infrastructure/auth.py",
        expected_grounding_terms=["auth.py", "Authenticator", "AuthenticationError"],
    ),
    RetrievalTask(
        task_id="repo-understanding-dependency-analysis",
        category="repository_understanding",
        query=(
            "What does ExecutionContractManager depend on, and which of those dependencies "
            "would need to change if the contract persistence backend were swapped out for a "
            "different database?"
        ),
        target_file="src/contracts/manager.py",
        expected_grounding_terms=["manager.py", "contract_store.py", "ContractStore"],
    ),
    RetrievalTask(
        task_id="bug-fixing-jwt-missing-sub",
        category="bug_fixing",
        query=(
            "Requests bearing a JWT with no 'sub' claim are being authenticated successfully "
            "when they should be rejected outright — this is a real authentication bypass. "
            "Investigate src/infrastructure/auth.py and fix it."
        ),
        target_file="src/infrastructure/auth.py",
        expected_grounding_terms=["auth.py", "AuthenticationError", "sub"],
    ),
    RetrievalTask(
        task_id="bug-fixing-idempotency-replay",
        category="bug_fixing",
        query=(
            "Reusing an Idempotency-Key with a different request body is supposed to be "
            "rejected as a conflict, but it is currently being silently accepted and replaying "
            "the original cached response instead. Investigate "
            "src/infrastructure/idempotency.py and fix it."
        ),
        target_file="src/infrastructure/idempotency.py",
        expected_grounding_terms=["idempotency.py", "IdempotencyConflictError"],
    ),
    RetrievalTask(
        task_id="refactoring-retry-exception-resolution",
        category="refactoring",
        query=(
            "In src/infrastructure/llm_client.py, the retryable-exception-name resolution "
            "(building RETRYABLE_EXCEPTIONS from _RETRYABLE_NAMES) is done inline at module "
            "scope. Extract it into a small, named, reusable helper function without changing "
            "behavior."
        ),
        target_file="src/infrastructure/llm_client.py",
        expected_grounding_terms=["llm_client.py", "RETRYABLE_EXCEPTIONS", "_RETRYABLE_NAMES"],
    ),
    RetrievalTask(
        task_id="ambiguous-symbol-save",
        category="ambiguous_symbol",
        query="After a new contract is created from a user's request, where does it get saved?",
        target_file="src/infrastructure/contract_store.py",
        expected_grounding_terms=["contract_store.py", "ContractStore", "save", "LivingContract"],
        known_ambiguous=True,
        reused_from_pilot_json=False,
    ),
]
