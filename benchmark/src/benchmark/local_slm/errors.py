"""Local SLM error types — kept out of arcf/src/shared/errors.py because
"local vs remote SLM" is a benchmark-tool concept ARCF's own pipeline
has no notion of (it only ever sees a model string).
"""


class LocalSLMUnavailableError(Exception):
    """Raised when no usable local model can be resolved. The message
    always carries the exact remediation step (an `ollama pull ...`
    command, or how to start the Ollama daemon) so the operator isn't
    left guessing.
    """
