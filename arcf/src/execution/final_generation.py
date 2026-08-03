"""FinalGenerationRunner — Phase 8's actual "final LLM call," the one
step ARCF's own pipeline never had before v2.3 (per
arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md Sec. 1.3: previously only
benchmark/src/benchmark/runners/base.py's compile_prompt stood in for
it, by its own docstring's admission).

Takes ContextGoalComposer's assembled prompt and calls the LLM with NO
response_format constraint — unlike SLM-1/SLM-2/PRHL, which all
request structured JSON for their own extraction/advisory purposes,
this is the one call whose output the whole system exists to produce,
and per the v2.3 brief it must not be schema-constrained. Wraps the
raw completion in an Artifact (domain/artifact.py) — the output shape
Contract.artifacts was already reserved for, per domain/contract.py.
"""

from domain.artifact import Artifact
from domain.context_package import ContextPackage
from domain.context_resolution import ContextResolutionResult
from domain.contract import Contract
from domain.enums import ArtifactKind
from execution.context_goal_composer import ContextGoalComposer
from infrastructure.llm_client import LiteLLMClient, LLMResponse


class FinalGenerationRunner:
    def __init__(
        self,
        composer: ContextGoalComposer,
        llm_client: LiteLLMClient,
        model: str,
        max_tokens: int = 4096,
    ) -> None:
        self._composer = composer
        self._llm_client = llm_client
        self._model = model
        self._max_tokens = max_tokens

    async def generate(
        self,
        contract: Contract,
        package: ContextPackage,
        resolution: ContextResolutionResult,
        kind: ArtifactKind = ArtifactKind.CODE_CHANGE,
    ) -> tuple[Artifact, LLMResponse]:
        prompt = self._composer.compose(contract, package, resolution)
        # No response_format: this is the one call in the whole pipeline
        # whose output must not be schema-constrained.
        completion = await self._llm_client.complete(
            prompt, self._model, max_tokens=self._max_tokens
        )
        artifact = Artifact(
            kind=kind,
            content=completion.content,
            metadata={
                "contract_id": str(contract.id),
                "context_package_id": str(package.id),
            },
        )
        return artifact, completion
