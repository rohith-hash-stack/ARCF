"""The minimal adapter between SemanticQueryInterpretation and ARCF-DI.

ARCF-DI's real accepted interface today (confirmed by reading
`code_intelligence/drp/query_router.py::route_query` and
`code_intelligence/drp/drp_resolver.py::DrpResolver.resolve`, and
`ContextResolver`'s Tier-1 exact-match path via `SymbolIndex.find_by_name`
/`find_by_qualified_name`) is: raw query text, plus an optional FLAT LIST
OF STRINGS (`target_names`). Classic resolution exact-matches each string
against real symbol names; DRP folds them into the query text as extra
tokens. Neither accepts a structured object.

This is the "minimal adapter" the experiment brief allows without
touching ARCF-DI itself: it projects `SemanticQueryInterpretation` down
to that same flat list, and nothing else. ARCF-DI's own code
(`ContextResolver`, `DrpResolver`, `SymbolIndex`, `ReferenceResolver`,
...) is never imported or modified here — this module only prepares one
of the arguments those classes already accept.
"""

from __future__ import annotations

from benchmark.semantic_layer.contract import SemanticQueryInterpretation, UncertaintyLevel


def to_target_names(interpretation: SemanticQueryInterpretation) -> list[str]:
    """Project `interpretation` to the `target_names: list[str]` ARCF-DI
    already accepts.

    Deliberately narrow:
    - Only `retrieval_terms` is projected. `concepts`/`behavior` are
      commentary for the human/report (see contract.py), not asserted
      identifiers — feeding them into ARCF-DI's exact-match channel
      would silently launder "the SLM's vague impression of the domain"
      into "a specific name ARCF-DI should trust", which is exactly the
      repository-truth-fabrication this experiment's architecture
      forbids.
    - `confidence == "uncertain"` returns an EMPTY list even if
      `retrieval_terms` is non-empty for some other reason (e.g. a
      malformed/inconsistent LLM response) — an interpreter that
      reports it doesn't know should not have its guesses passed to
      retrieval anyway. ARCF-DI's own fallback layers (lexical probe,
      anchor classification) already exist for exactly the
      "no usable entities" case and run automatically when
      `target_names` is empty.
    - Negative queries (`is_negative_query=True`) still project
      `retrieval_terms` normally: ARCF-DI's exact-match/lexical channels
      only ever ADD candidate files, they don't assert "and therefore
      this behavior exists" — the risk flagged in contract.py's
      docstring is about a caller (a human, or a future ranking-profile
      change) treating a negative query's hits as confirmatory, not
      about this adapter's own projection. This function does not
      special-case negative queries today; `is_negative_query` is
      surfaced in the result for the caller/report to account for
      separately, not silently handled here.
    """
    if interpretation.confidence == UncertaintyLevel.UNCERTAIN:
        return []
    return list(interpretation.retrieval_terms)
