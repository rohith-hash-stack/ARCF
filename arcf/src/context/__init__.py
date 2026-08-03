"""Context Intelligence Layer (Phase 6) — SLM-assisted, but never
SLM-decided.

Consumes only domain.context_resolution.ContextResolutionResult —
nothing in this package imports from code_intelligence/ (Tree-sitter,
SymbolIndex, CallGraph, DependencyGraph, ImportGraph, LanguageAnalyzer,
CandidateSelector internals). See
tests/code_intelligence/test_phase6_boundary.py for the enforced proof
of that rule.

RelevanceRanker and ContextBudgetManager are fully deterministic —
selection is never made by the SLM. ContextUnderstandingAnalyzer
(SLM-2) only ever adds supplementary commentary; if it fails or is
omitted, ContextPackager still produces a complete, valid
ContextPackage.
"""
