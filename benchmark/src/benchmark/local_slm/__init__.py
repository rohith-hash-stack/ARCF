"""Local SLM provider abstraction — resolves a model string for SLM-1
(intent extraction) to run against a locally-hosted model instead of a
remote one.

Scope is deliberately narrow: this package's only job is answering
"what model string should IntentExtractor use", the same way
BenchmarkSettings.slm_model already does for the remote case. It never
touches file selection, context resolution, planning, or verification
— those stay exactly as ARCF's Phase 1-6 pipeline already implements
them, untouched.
"""

from benchmark.local_slm.errors import LocalSLMUnavailableError
from benchmark.local_slm.ollama_provider import OllamaProvider
from benchmark.local_slm.provider import LocalSLMProvider

__all__ = ["LocalSLMProvider", "LocalSLMUnavailableError", "OllamaProvider"]
