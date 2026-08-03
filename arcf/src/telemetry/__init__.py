"""Telemetry layer (Phase 11 of the original playbook; Stage 5 of the
v2.3 migration plan — see arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md).

comparison_aggregator.py: ComparisonAggregator, computing cross-mode
(direct vs. ARCF) reduction percentages and CER/PCR from two
ExecutionLedgerEntry records — the read-model aggregation Sec. 4's
module map reserved this package for, generalized from benchmark/src/
benchmark/analyzer.py's BenchmarkAnalyzer formulas.
"""
