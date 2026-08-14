import json
import logging
from pathlib import Path
from types import SimpleNamespace

import litellm
import pytest

from code_intelligence.call_graph import CallGraph
from code_intelligence.reference_resolver import ReferenceResolver
from code_intelligence.symbol_index import SymbolIndex
from context.evidence_summarizer import EvidenceConstrainedSummarizer
from context.packager import ContextPackager
from context.relevance_ranker import RelevanceRanker
from context.task_profile import RANKING_PROFILES, RetrievalTaskType
from context.understanding import ContextUnderstandingAnalyzer
from domain.code_intelligence import CallReference, FileAnalysis, SourceLocation, Symbol, SymbolKind
from domain.context_resolution import (
    ContextResolutionResult,
    EvidenceTier,
    FileReference,
    SymbolReference,
    TokenEstimate,
)
from domain.summarization import SummarySource
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


def _authenticate_symbol() -> Symbol:
    # Matches _result()'s entry point exactly: same symbol_id/file_path,
    # so BehavioralRecordBuilder.build can actually find it.
    return Symbol(
        id="auth.py::authenticate",
        name="authenticate",
        qualified_name="authenticate",
        kind=SymbolKind.FUNCTION,
        file_path="auth.py",
        location=SourceLocation(file_path="auth.py", start_line=1, end_line=2),
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


async def test_ranking_profile_is_threaded_through_to_the_ranker(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    result = _result(str(tmp_path))

    package, _ = await _packager(with_understanding=False).package(
        result,
        "fix auth bug",
        max_tokens=10_000,
        ranking_profile=RANKING_PROFILES[RetrievalTaskType.BUG_FIX],
    )

    assert len(package.relevant_files) == 1


async def test_compressed_snippet_count_reflects_truncated_files(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text(
        "\n".join(f"line {i}" for i in range(1, 300))
        + "\n\ndef authenticate(user):\n    return True\n"
    )
    result = _result(str(tmp_path))

    package, _ = await _packager(with_understanding=False).package(
        result, "fix auth bug", max_tokens=20
    )

    assert package.compressed_snippet_count == sum(1 for f in package.relevant_files if f.truncated)
    assert package.compressed_snippet_count >= 0


async def test_fastapi_style_large_supporting_file_is_compressed_not_dropped_or_kept_whole(
    tmp_path: Path,
) -> None:
    """End-to-end regression for the real finding that motivated evidence-
    preserving context packaging: testing the ARCF fix against FastAPI,
    a lexically-probed symbol (request_response) happened to be defined
    in routing.py, a huge central file — 49,172 of 87,170 total packaged
    tokens (56%) — while the file that actually answered the question
    (background.py, defining BackgroundTasks) was only 384 tokens.
    Success criteria: the real answer file is retained in full, the large
    supporting file is retained too (never silently dropped) but shrunk
    to its relevant region, and total tokens used are far below the naive
    sum of both files' full sizes."""
    padding = "\n".join(f"    # padding line {i}" for i in range(1, 3000))
    (tmp_path / "routing.py").write_text(
        f"class APIRoute:\n{padding}\n    def request_response(self):\n        pass\n"
    )
    (tmp_path / "background.py").write_text(
        "class BackgroundTasks:\n    def add_task(self, func):\n        ...\n"
    )
    routing_tokens = CostEstimator().count_tokens(
        (tmp_path / "routing.py").read_text(), "gpt-4o-mini"
    )
    background_tokens = CostEstimator().count_tokens(
        (tmp_path / "background.py").read_text(), "gpt-4o-mini"
    )
    assert routing_tokens > 10_000, "fixture must reproduce a genuinely large supporting file"

    routing_symbol = SymbolReference(
        symbol_id="routing.py::request_response",
        name="request_response",
        qualified_name="APIRoute.request_response",
        kind=SymbolKind.METHOD,
        file_path="routing.py",
        start_line=3001,
        end_line=3002,
        parent_symbol_id="routing.py::APIRoute",
    )
    background_symbol = SymbolReference(
        symbol_id="background.py::BackgroundTasks",
        name="BackgroundTasks",
        qualified_name="BackgroundTasks",
        kind=SymbolKind.CLASS,
        file_path="background.py",
        start_line=1,
        end_line=3,
    )
    result = ContextResolutionResult(
        workspace_id=str(tmp_path),
        contract_id="contract-1",
        repository_root=str(tmp_path),
        language="python",
        candidate_files=[
            FileReference(
                file_path="routing.py",
                reason="defines request_response",
                language="python",
                token_count=routing_tokens,
                evidence_tier=EvidenceTier.SUPPORTING,
            ),
            FileReference(
                file_path="background.py",
                reason="defines BackgroundTasks",
                language="python",
                token_count=background_tokens,
                evidence_tier=EvidenceTier.PRIMARY,
            ),
        ],
        entry_points=[routing_symbol, background_symbol],
        confidence=1.0,
        token_estimate=TokenEstimate(
            raw_context_tokens=routing_tokens + background_tokens,
            selected_context_tokens=routing_tokens + background_tokens,
            compression_ratio=1.0,
        ),
        resolution_reason="test",
    )

    package, _ = await _packager(with_understanding=False).package(
        result, "Explain how background tasks get scheduled.", max_tokens=100_000
    )

    by_path = {f.file_path: f for f in package.relevant_files}
    assert set(by_path) == {"routing.py", "background.py"}

    assert by_path["background.py"].truncated is False
    assert "class BackgroundTasks" in by_path["background.py"].content

    assert by_path["routing.py"].truncated is True
    assert "def request_response" in by_path["routing.py"].content
    assert by_path["routing.py"].token_count < routing_tokens / 10, (
        "the large supporting file must be cut down to its relevant region, "
        "not kept whole just because it fit the budget"
    )

    assert package.budget_used_tokens < (routing_tokens + background_tokens) / 5


async def test_diagnostic_log_line_correlated_by_context_resolution_id(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    result = _result(str(tmp_path))

    with caplog.at_level(logging.DEBUG, logger="arcf.retrieval"):
        await _packager(with_understanding=False).package(result, "fix auth bug", max_tokens=10_000)

    records = [r for r in caplog.records if r.name == "arcf.retrieval"]
    assert len(records) == 1
    payload = json.loads(records[0].getMessage())
    assert payload["context_resolution_id"] == str(result.id)


# --- ARCF-DI Phase 5/6 wiring: EvidenceConstrainedSummarizer/
# attribute_citations threaded through ContextPackager.package ----------


async def test_package_without_evidence_params_leaves_citations_and_summaries_empty(
    tmp_path: Path,
) -> None:
    # Every caller that predates this wiring (and any caller that still
    # omits the new params) must see byte-identical behavior: no
    # citations populated, no behavioral_summaries computed.
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    result = _result(str(tmp_path))

    package, _ = await _packager(with_understanding=False).package(
        result, "fix auth bug", max_tokens=10_000
    )

    assert package.relevant_files[0].citations == []
    assert package.behavioral_summaries == []


async def test_package_with_evidence_params_populates_citations_and_template_summary(
    tmp_path: Path,
) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    result = _result(str(tmp_path))

    authenticate = _authenticate_symbol()
    check_password = Symbol(
        id="auth.py::check_password",
        name="check_password",
        qualified_name="check_password",
        kind=SymbolKind.FUNCTION,
        file_path="auth.py",
        location=SourceLocation(file_path="auth.py", start_line=4, end_line=5),
    )
    symbol_index = SymbolIndex([authenticate, check_password])
    resolver = ReferenceResolver(symbol_index)
    calls = [
        CallReference(
            caller_id=authenticate.id,
            callee_name="check_password",
            file_path="auth.py",
            location=SourceLocation(file_path="auth.py", start_line=2, end_line=2),
        )
    ]
    call_graph = CallGraph(calls, resolver)
    file_analyses = {"auth.py": FileAnalysis(file_path="auth.py", language="python")}

    package, _ = await _packager(with_understanding=False).package(
        result,
        "fix auth bug",
        max_tokens=10_000,
        symbol_index=symbol_index,
        call_graph=call_graph,
        file_analyses=file_analyses,
    )

    assert package.relevant_files[0].citations != []
    [summary] = package.behavioral_summaries
    assert summary.symbol_id == authenticate.id
    assert summary.source == SummarySource.TEMPLATE
    assert "check_password" in summary.text


async def test_package_with_summarizer_escalates_to_slm_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    result = _result(str(tmp_path))

    authenticate = _authenticate_symbol()
    check_password = Symbol(
        id="auth.py::check_password",
        name="check_password",
        qualified_name="check_password",
        kind=SymbolKind.FUNCTION,
        file_path="auth.py",
        location=SourceLocation(file_path="auth.py", start_line=4, end_line=5),
    )
    symbol_index = SymbolIndex([authenticate, check_password])
    resolver = ReferenceResolver(symbol_index)
    calls = [
        CallReference(
            caller_id=authenticate.id,
            callee_name="check_password",
            file_path="auth.py",
            location=SourceLocation(file_path="auth.py", start_line=2, end_line=2),
        )
    ]
    call_graph = CallGraph(calls, resolver)
    file_analyses = {"auth.py": FileAnalysis(file_path="auth.py", language="python")}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("Calls check_password. [ev:auth.py::check_password]")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    client = LiteLLMClient(max_retries=1, base_delay_seconds=0.0, sleep=_no_sleep)
    summarizer = EvidenceConstrainedSummarizer(client, "gpt-4o-mini", template_threshold=0)

    package, _ = await _packager(with_understanding=False).package(
        result,
        "fix auth bug",
        max_tokens=10_000,
        symbol_index=symbol_index,
        call_graph=call_graph,
        file_analyses=file_analyses,
        behavioral_summarizer=summarizer,
    )

    [summary] = package.behavioral_summaries
    assert summary.source == SummarySource.SLM


async def test_package_dedupes_repeated_entry_point_symbols(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    authenticate = _authenticate_symbol()
    result = ContextResolutionResult(
        workspace_id=str(tmp_path),
        contract_id="contract-1",
        repository_root=str(tmp_path),
        language="python",
        candidate_files=[
            FileReference(
                file_path="auth.py",
                reason="defines authenticate",
                language="python",
                token_count=10,
            ),
        ],
        entry_points=[
            SymbolReference(
                symbol_id=authenticate.id,
                name="authenticate",
                qualified_name="authenticate",
                kind=SymbolKind.FUNCTION,
                file_path="auth.py",
                start_line=1,
                end_line=2,
            ),
            SymbolReference(
                symbol_id=authenticate.id,
                name="authenticate",
                qualified_name="authenticate",
                kind=SymbolKind.FUNCTION,
                file_path="auth.py",
                start_line=1,
                end_line=2,
            ),
        ],
        confidence=1.0,
        token_estimate=TokenEstimate(
            raw_context_tokens=1000, selected_context_tokens=10, compression_ratio=0.01
        ),
        resolution_reason="test",
    )

    symbol_index = SymbolIndex([authenticate])
    call_graph = CallGraph([], ReferenceResolver(symbol_index))
    file_analyses = {"auth.py": FileAnalysis(file_path="auth.py", language="python")}

    package, _ = await _packager(with_understanding=False).package(
        result,
        "fix auth bug",
        max_tokens=10_000,
        symbol_index=symbol_index,
        call_graph=call_graph,
        file_analyses=file_analyses,
    )

    assert len(package.behavioral_summaries) == 1


async def test_package_skips_entry_point_with_no_buildable_record(tmp_path: Path) -> None:
    (tmp_path / "auth.py").write_text("def authenticate(user):\n    return True\n")
    result = _result(str(tmp_path))

    # Deliberately empty: the entry point symbol_id from _result() isn't
    # in this index, so BehavioralRecordBuilder.build returns None.
    symbol_index = SymbolIndex([])
    call_graph = CallGraph([], ReferenceResolver(symbol_index))
    file_analyses: dict[str, FileAnalysis] = {}

    package, _ = await _packager(with_understanding=False).package(
        result,
        "fix auth bug",
        max_tokens=10_000,
        symbol_index=symbol_index,
        call_graph=call_graph,
        file_analyses=file_analyses,
    )

    assert package.behavioral_summaries == []
