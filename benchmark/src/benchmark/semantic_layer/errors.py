class SemanticInterpretationError(Exception):
    """Raised when a SemanticInterpreter cannot produce a valid
    SemanticQueryInterpretation after exhausting its retries — mirrors
    arcf's own `IntentExtractionError` shape (see
    src/shared/errors.py) without adding a dependency from `arcf/src`
    onto this experiment-only package."""
