"""Code Intelligence Engine (Phase 5) — deterministic repository
understanding, language-agnostic by construction.

Every component here (SymbolIndex, ImportGraph, DependencyGraph,
InheritanceGraph, CallGraph, CandidateFileSelector, CodeIntelligenceEngine)
operates purely on the IR in domain/code_intelligence.py. None of them
import tree-sitter or contain per-language logic — that lives entirely
in languages/, behind the LanguageAnalyzer interface. Adding TypeScript,
Java, or Go support means adding one file under languages/ and
registering it with LanguageRegistry; nothing in this package's other
modules changes.
"""
