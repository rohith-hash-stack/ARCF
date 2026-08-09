"""Dynamic Repository Profiling (DRP) — ARCF experimental resolver strategy.

Isolated from the stable Phase 5/6 pipeline: nothing here is imported by
`context_resolver.py`, any of the five established graph classes, or any
`context/` packaging module. DRP is reached only through
`code_intelligence.service.CodeIntelligenceContractService.
attach_code_intelligence`'s `resolver_strategy="drp"` branch, which is
itself off by default (`resolver_strategy="classic"`).

DRP answers one question deterministically, without embeddings, LLM
calls, or hardcoded concept dictionaries: can a repository's own
directory taxonomy + per-subsystem vocabulary + import/call graph
structure locate the right subsystem for a query that names no symbol
lexical/exact matching would ever find? See docs for the originating
experiment (ARCF Issue #3, diffuse-structure repositories).

Stages, one module each:
  taxonomy.py        — Stage 1: directory/package Subsystem Nodes
  text_corpus.py      — Stage 2a: per-subsystem vocabulary extraction
  tfidf.py             — Stage 2b: per-subsystem TF-IDF profiles
  subsystem_graph.py    — Stage 3: file-level graph + Label Propagation
  query_router.py         — Stage 4: query scoring, routing, expansion
  drp_index.py              — bundles the above into one DrpIndex
  drp_resolver.py             — DrpResolver, the public entry point
  diagnostics.py                — benchmark-only instrumentation
"""
