"""Semantic-layer experiment infrastructure — NOT wired into production.

Everything under this package exists to answer one question experimentally:
does routing a query through a generic small LLM ("SLM"), with either
ARCF's existing SLM-1 prompt/contract or a new, richer, ARCF-specialized
one, change ARCF-DI's retrieval outcomes relative to ARCF's current
production semantic stage (SLM-1 on a remote model)?

Nothing here is imported by `arcf/src` or by `benchmark`'s own
production runners (`runners/arcf_runner.py`, `bootstrap.py`). It is
additive, isolated, and reversible: deleting this package and
`scripts/semantic_layer_experiment.py` returns the repository to its
prior state exactly.

See `contract.py` for the structured output contract (Step 2 of the
experiment brief), `interpreter.py` for the swappable model interface
(Step 3), `adapter.py` for the minimal, explicitly-scoped projection
into ARCF-DI's existing `target_names: list[str]` channel, and
`retrieval_scoring.py` for Recall@k/MRR/failure-classification metrics
that don't exist elsewhere in this codebase.
"""
