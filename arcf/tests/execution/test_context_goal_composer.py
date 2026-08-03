"""Tests for ContextGoalComposer, including the structural non-
interference proof required by
arcf/docs/ARCF_v2.3_ARCHITECTURE_REVIEW.md Sec. 8/9: PRHL must never
influence the assembled prompt. Verified two ways, mirroring
tests/code_intelligence/test_phase6_boundary.py's approach:

1. Statically — parsing context_goal_composer.py's own imports (via
   ast, not a string search) and asserting execution.prhl is not among
   them.
2. Behaviorally — composing a prompt, then running PRHLAnalyzer over
   the same ContextPackage, then composing again: the two prompts must
   be byte-identical.
"""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import litellm
import pytest

import execution.context_goal_composer as context_goal_composer_module
from domain.code_intelligence import SymbolKind
from domain.context_package import ContextPackage, PackagedFile
from domain.context_resolution import (
    ContextResolutionResult,
    DependencyEdge,
    SymbolReference,
    TokenEstimate,
)
from domain.contract import Contract
from domain.intent import UserIntent
from execution.context_goal_composer import ContextGoalComposer
from execution.prhl import PRHLAnalyzer
from infrastructure.llm_client import LiteLLMClient


def _intent(intent: str = "Fix the login bug") -> UserIntent:
    return UserIntent(
        raw_request="the login bug",
        intent=intent,
        domain="auth",
        task="bugfix",
        confidence=0.9,
    )


def _contract(success_criteria: list[str] | None = None) -> Contract:
    return Contract(
        intent=_intent(),
        success_criteria=success_criteria or ["Login succeeds with valid credentials"],
    )


def _resolution() -> ContextResolutionResult:
    return ContextResolutionResult(
        workspace_id="workspace-1",
        contract_id="contract-1",
        repository_root="/repo",
        language="python",
        entry_points=[
            SymbolReference(
                symbol_id="auth/service.py::AuthService.authenticate#1",
                name="authenticate",
                qualified_name="AuthService.authenticate",
                kind=SymbolKind.METHOD,
                file_path="auth/service.py",
                start_line=1,
                end_line=5,
            )
        ],
        confidence=0.9,
        token_estimate=TokenEstimate(
            raw_context_tokens=100, selected_context_tokens=50, compression_ratio=0.5
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
                content="class AuthService:\n    def authenticate(self): ...\n",
                relevance_score=1.0,
                reason="defines authenticate",
                token_count=50,
                truncated=False,
            )
        ],
        dependency_chain=[DependencyEdge(from_file="routes/login.py", to_file="auth/service.py")],
        budget_max_tokens=1000,
        budget_used_tokens=50,
        prompt_compression_ratio=1.0,
        excluded_file_count=0,
    )


def test_compose_includes_goal_and_success_criteria() -> None:
    prompt = ContextGoalComposer().compose(_contract(), _package(), _resolution())
    assert "Fix the login bug" in prompt
    assert "Login succeeds with valid credentials" in prompt


def test_compose_includes_selected_file_content() -> None:
    prompt = ContextGoalComposer().compose(_contract(), _package(), _resolution())
    assert "auth/service.py" in prompt
    assert "defines authenticate" in prompt
    assert "class AuthService" in prompt


def test_compose_includes_symbol_and_dependency_info() -> None:
    prompt = ContextGoalComposer().compose(_contract(), _package(), _resolution())
    assert "AuthService.authenticate" in prompt
    assert "routes/login.py -> auth/service.py" in prompt


def test_compose_handles_empty_context_package() -> None:
    empty_package = ContextPackage(
        contract_id="contract-1",
        workspace_id="workspace-1",
        context_resolution_id=uuid4(),
        budget_max_tokens=1000,
        budget_used_tokens=0,
        prompt_compression_ratio=0.0,
        excluded_file_count=0,
    )
    empty_resolution = ContextResolutionResult(
        workspace_id="workspace-1",
        contract_id="contract-1",
        repository_root="/repo",
        language="python",
        confidence=0.9,
        token_estimate=TokenEstimate(
            raw_context_tokens=0, selected_context_tokens=0, compression_ratio=0.0
        ),
        resolution_reason="no candidates",
    )
    prompt = ContextGoalComposer().compose(_contract(), empty_package, empty_resolution)
    assert "(none)" in prompt


def test_module_does_not_import_prhl() -> None:
    source_path = Path(context_goal_composer_module.__file__)
    tree = ast.parse(source_path.read_text())

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert imported_modules, "expected the composer to import something"
    assert all(not module.startswith("execution.prhl") for module in imported_modules)


async def test_compose_output_unaffected_by_prhl(monkeypatch: pytest.MonkeyPatch) -> None:
    contract, package, resolution = _contract(), _package(), _resolution()
    composer = ContextGoalComposer()

    before = composer.compose(contract, package, resolution)

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        payload = {
            "likely_direction": "Add a retry to authenticate.",
            "probable_touchpoints": ["auth/service.py"],
            "expected_diff_scope": "small",
            "anticipated_dependencies": [],
            "risk_flags": ["no test coverage"],
        }
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    client = LiteLLMClient(max_retries=1, base_delay_seconds=0.0)
    await PRHLAnalyzer(client, "gpt-4o-mini").analyze(contract.intent.raw_request, package)

    after = composer.compose(contract, package, resolution)

    assert before == after
