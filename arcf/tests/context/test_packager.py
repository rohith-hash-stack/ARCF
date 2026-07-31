import json
from pathlib import Path
from types import SimpleNamespace

import litellm
import pytest

from context.packager import ContextPackager
from context.relevance_ranker import RelevanceRanker
from context.understanding import ContextUnderstandingAnalyzer
from domain.code_intelligence import SymbolKind
from domain.context_resolution import (
    ContextResolutionResult,
    FileReference,
    SymbolReference,
    TokenEstimate,
)
from infrastructure.cost import CostEstimator
from infrastructure.llm_client import LiteLLMClient

_UNDERSTANDING_PAYLOAD = {
    "summary": "auth.py defines authenticate, called from login.py.",
    "key_relationships": ["login.py -> auth.py"],
}


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10, total_tokens=30),
    )


async def _no_sleep(seconds: float) -> None:
    return None


def _result(repository_root: str) -> ContextResolutionResult:
    entry = SymbolReference(
        symbol_id="auth.py::authenticate",
        name="authenticate",
        qualified_name="authenticate",
        kind=SymbolKind.FUNCTION,
        file_path="auth.py",
        start_line=1,
        end_line=2,
    )
    return ContextResolutionResult(
        workspace_id=repository_root,
        contract_id="contract-1",
        repository_root=repository_root,
        language="python",
        candidate_files=[
            FileReference(
                file_path="auth.py",
                reason="defines authenticate",
                language="python",
                token_count=10,
            ),
        ],
        entry_points=[entry],
        confidence=1.0,
        token_estimate=TokenEstimate(
            raw_context_tokens=1000, selected_context_tokens=10, compression_ratio=0.01
        ),
        resolution_reason="test",
    )


def _packager(with_understanding: bool = True) -> ContextPackager:
    ranker = RelevanceRanker()
    estimator = CostEstimator()
    if not with_understanding:
        return ContextPackager(ranker, estimator, understanding_analyzer=None)
    client = LiteLLMClient(max_retries=1, base_delay_seconds=0.0, sleep=_no_sleep)
    analyzer = ContextUnderstandingAnalyzer(client, "gpt-4o-mini")
    return ContextPackager(ranker, estimator, understanding_analyzer=analyzer)


async def test_package_includes_ranked_files_and_understanding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response(json.dumps(_UNDERSTANDING_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    result = _result(str(tmp_path))
    package, llm_response = await _packager().package(result, "fix auth bug", max_tokens=10_000)

    assert len(package.relevant_files) == 1
    assert package.relevant_files[0].file_path == "auth.py"
    assert package.understanding_notes == [
        _UNDERSTANDING_PAYLOAD["summary"],
        *_UNDERSTANDING_PAYLOAD["key_relationships"],
    ]
    assert llm_response is not None
    assert package.contract_id == "contract-1"
    assert package.context_resolution_id == result.id


async def test_package_without_understanding_analyzer_still_completes(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    result = _result(str(tmp_path))

    package, llm_response = await _packager(with_understanding=False).package(
        result, "fix auth bug", max_tokens=10_000
    )

    assert len(package.relevant_files) == 1
    assert package.understanding_notes == []
    assert llm_response is None


async def test_package_degrades_gracefully_when_slm2_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("not valid json, and stays that way")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    result = _result(str(tmp_path))
    package, llm_response = await _packager().package(result, "fix auth bug", max_tokens=10_000)

    # package is still complete and valid even though SLM-2 never produced usable output
    assert len(package.relevant_files) == 1
    assert package.understanding_notes == []


async def test_prompt_compression_ratio_computed_from_raw_and_used_tokens(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    result = _result(str(tmp_path))

    package, _ = await _packager(with_understanding=False).package(
        result, "fix auth bug", max_tokens=10_000
    )

    expected = round(result.token_estimate.raw_context_tokens / package.budget_used_tokens, 4)
    assert package.prompt_compression_ratio == expected


async def test_empty_candidates_produces_empty_package_without_calling_slm2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"count": 0}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        calls["count"] += 1
        return _fake_response(json.dumps(_UNDERSTANDING_PAYLOAD))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    empty_result = ContextResolutionResult(
        workspace_id=str(tmp_path),
        contract_id="contract-1",
        repository_root=str(tmp_path),
        language="python",
        confidence=0.0,
        token_estimate=TokenEstimate(
            raw_context_tokens=0, selected_context_tokens=0, compression_ratio=0.0
        ),
        resolution_reason="no target names",
    )
    package, llm_response = await _packager().package(empty_result, "task", max_tokens=1000)

    assert package.relevant_files == []
    assert llm_response is None
    assert calls["count"] == 0
