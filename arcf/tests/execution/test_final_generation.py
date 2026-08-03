from types import SimpleNamespace
from uuid import uuid4

import litellm
import pytest

from domain.context_package import ContextPackage, PackagedFile
from domain.context_resolution import ContextResolutionResult, TokenEstimate
from domain.contract import Contract
from domain.enums import ArtifactKind
from domain.intent import UserIntent
from execution.context_goal_composer import ContextGoalComposer
from execution.final_generation import FinalGenerationRunner
from infrastructure.llm_client import LiteLLMClient


def _contract() -> Contract:
    return Contract(
        intent=UserIntent(
            raw_request="fix the login bug",
            intent="Fix the login bug",
            domain="auth",
            task="bugfix",
            confidence=0.9,
        ),
        success_criteria=["Login succeeds with valid credentials"],
    )


def _resolution() -> ContextResolutionResult:
    return ContextResolutionResult(
        workspace_id="workspace-1",
        contract_id="contract-1",
        repository_root="/repo",
        language="python",
        confidence=0.9,
        token_estimate=TokenEstimate(
            raw_context_tokens=50, selected_context_tokens=50, compression_ratio=1.0
        ),
        resolution_reason="defines authenticate",
    )


def _package() -> ContextPackage:
    return ContextPackage(
        contract_id="contract-1",
        workspace_id="workspace-1",
        context_resolution_id=uuid4(),
        relevant_files=[
            PackagedFile(
                file_path="auth/service.py",
                content="class AuthService: ...",
                relevance_score=1.0,
                reason="defines authenticate",
                token_count=50,
                truncated=False,
            )
        ],
        budget_max_tokens=1000,
        budget_used_tokens=50,
        prompt_compression_ratio=1.0,
        excluded_file_count=0,
    )


def _runner() -> FinalGenerationRunner:
    client = LiteLLMClient(max_retries=1, base_delay_seconds=0.0)
    return FinalGenerationRunner(ContextGoalComposer(), client, "gpt-4o-mini")


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=40, completion_tokens=20, total_tokens=60),
    )


async def test_generate_returns_artifact_with_raw_completion_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("--- a/auth/service.py\n+++ b/auth/service.py\n")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    contract, package, resolution = _contract(), _package(), _resolution()
    artifact, response = await _runner().generate(contract, package, resolution)

    assert artifact.content == "--- a/auth/service.py\n+++ b/auth/service.py\n"
    assert artifact.kind is ArtifactKind.CODE_CHANGE
    assert artifact.metadata["contract_id"] == str(contract.id)
    assert artifact.metadata["context_package_id"] == str(package.id)
    assert response.total_tokens == 60


async def test_generate_does_not_constrain_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _fake_response("some prose explanation")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    await _runner().generate(_contract(), _package(), _resolution())

    assert captured["response_format"] is None


async def test_generate_accepts_a_non_default_artifact_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("This change adds a retry to authenticate.")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    artifact, _ = await _runner().generate(
        _contract(), _package(), _resolution(), kind=ArtifactKind.EXPLANATION
    )

    assert artifact.kind is ArtifactKind.EXPLANATION
