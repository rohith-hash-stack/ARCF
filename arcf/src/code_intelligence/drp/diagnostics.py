"""DrpDiagnostics — benchmark-only instrumentation.

Deliberately kept OUT of `domain.context_resolution.ContextResolutionResult`:
that contract is the deliberately stable Phase 5/6 boundary (see its own
module docstring), and DRP is required to produce exactly that shape so
`RelevanceRanker`/`ContextBudgetManager`/`ContextPackager` work
unmodified. Everything the ARCF Issue #3 Evaluation Framework asks for
that ISN'T part of that contract (top community, per-subsystem score
breakdown, resolver latency, graph expansion count) lives here instead,
consumed only by `scripts/drp_benchmark.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DrpDiagnostics:
    top_subsystem: str
    top_subsystem_confidence: float
    top_community: str | None
    top_files: list[str] = field(default_factory=list)
    resolver_latency_seconds: float = 0.0
    graph_expansion_count: int = 0
    subsystem_scores: list[tuple[str, float]] = field(default_factory=list)
    """(subsystem_path, combined_score) for the top-ranked subsystems,
    most-relevant first."""
    query_expansion: dict[str, list[tuple[str, float]]] | None = None
    """ARCF Issue #3 PMI query-expansion extension — None when the
    extension was off or found nothing to expand. Otherwise:
    uncovered_query_term -> [(pmi_neighbor_term, ppmi_score), ...],
    exactly which words were inferred and why — auditability, not a
    black box (see pmi_expansion.py)."""


def compute_retrieval_rank(files: list[str], target_file: str) -> int | None:
    """1-based rank of `target_file` within `files` (already in the
    resolver's own candidate order), or None if it never appears —
    shared by the benchmark script for both classic and DRP results so
    the two are scored identically."""
    normalized_target = target_file.replace("\\", "/")
    for rank, file_path in enumerate(files, start=1):
        if file_path.replace("\\", "/") == normalized_target:
            return rank
    return None
