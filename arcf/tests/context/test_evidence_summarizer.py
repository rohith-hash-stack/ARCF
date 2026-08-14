from types import SimpleNamespace

import litellm
import pytest

from context.evidence_summarizer import (
    EvidenceConstrainedSummarizer,
    citable_evidence_ids,
    render_template,
    verify_and_extract,
)
from domain.behavioral_record import (
    AmbiguousCall,
    BehavioralRecord,
    DependencyDepth,
    RecordComplexity,
)
from domain.code_intelligence import SourceLocation, SymbolKind
from domain.summarization import SummaryConfidence, SummarySource
from infrastructure.llm_client import LiteLLMClient


def _record(**overrides: object) -> BehavioralRecord:
    defaults: dict[str, object] = dict(
        symbol_id="service.py::login",
        qualified_name="login",
        kind=SymbolKind.FUNCTION,
        language="python",
        location=SourceLocation(file_path="service.py", start_line=1, end_line=5),
        dependency_depth=DependencyDepth(hops=0, truncated=False),
        disambiguation_aware=True,
        complexity=RecordComplexity(line_count=5, direct_call_count=0),
    )
    defaults.update(overrides)
    return BehavioralRecord(**defaults)  # type: ignore[arg-type]


# --- citable_evidence_ids ---------------------------------------------


def test_citable_evidence_ids_unions_all_evidence_fields() -> None:
    record = _record(
        file_import_ids=["import:service.py::os#1"],
        direct_callees=["auth.py::authenticate"],
        external_libraries_used=["requests"],
        ambiguous_calls=[
            AmbiguousCall(call_id="call:x#1-1", callee_name="helper", candidates=["a", "b"])
        ],
    )
    assert citable_evidence_ids(record) == {
        "import:service.py::os#1",
        "auth.py::authenticate",
        "requests",
        "call:x#1-1",
    }


# --- render_template ----------------------------------------------------


def test_render_template_empty_record_is_insufficient_evidence() -> None:
    summary = render_template(_record())
    assert summary.insufficient_evidence is True
    assert summary.text == ""
    assert summary.source is SummarySource.TEMPLATE


def test_render_template_cites_every_direct_callee() -> None:
    record = _record(direct_callees=["auth.py::authenticate", "log.py::logEvent"])
    summary = render_template(record)
    assert "authenticate" in summary.text
    assert "logEvent" in summary.text
    assert set(summary.citations) == {"auth.py::authenticate", "log.py::logEvent"}
    assert summary.insufficient_evidence is False


def test_render_template_mentions_external_libraries() -> None:
    record = _record(external_libraries_used=["axios", "requests"])
    summary = render_template(record)
    assert "axios" in summary.text
    assert "requests" in summary.text
    assert set(summary.citations) == {"axios", "requests"}


def test_render_template_flags_ambiguous_calls() -> None:
    record = _record(
        ambiguous_calls=[
            AmbiguousCall(call_id="call:x#1-1", callee_name="New", candidates=["a", "b"])
        ]
    )
    summary = render_template(record)
    assert "ambiguous" in summary.text.lower()
    assert "New" in summary.text
    assert summary.citations == ["call:x#1-1"]


def test_render_template_confidence_low_when_not_disambiguation_aware() -> None:
    record = _record(direct_callees=["a.py::a"], disambiguation_aware=False)
    assert render_template(record).confidence is SummaryConfidence.LOW


def test_render_template_confidence_low_when_truncated() -> None:
    record = _record(
        direct_callees=["a.py::a"],
        dependency_depth=DependencyDepth(hops=5, truncated=True),
    )
    assert render_template(record).confidence is SummaryConfidence.LOW


def test_render_template_confidence_medium_with_ambiguity() -> None:
    record = _record(
        ambiguous_calls=[
            AmbiguousCall(call_id="call:x#1-1", callee_name="New", candidates=["a", "b"])
        ]
    )
    assert render_template(record).confidence is SummaryConfidence.MEDIUM


def test_render_template_confidence_high_when_clean() -> None:
    record = _record(direct_callees=["a.py::a"])
    assert render_template(record).confidence is SummaryConfidence.HIGH


# --- verify_and_extract: BLUEPRINT.md Phase 5's own accept/reject pairs -


def test_accepts_literal_cited_calls() -> None:
    text = "Calls authenticate() [ev:auth.py::authenticate] and logEvent() [ev:log.py::logEvent]."
    accepted, citations, rejected = verify_and_extract(
        text, {"auth.py::authenticate", "log.py::logEvent"}
    )
    assert "authenticate()" in accepted
    assert "logEvent()" in accepted
    assert citations == ["auth.py::authenticate", "log.py::logEvent"]
    assert rejected == []


def test_rejects_interpretive_relationship_claim() -> None:
    text = (
        "Coordinates authentication and logging to secure the request "
        "[ev:auth.py::authenticate]."
    )
    accepted, citations, rejected = verify_and_extract(text, {"auth.py::authenticate"})
    assert accepted == ""
    assert citations == []
    [claim] = rejected
    assert "coordinates" in claim.reason.lower() or "secures" in claim.reason.lower()


def test_accepts_literal_external_call() -> None:
    text = "Invokes axios.post(url, payload) [ev:axios]."
    accepted, citations, rejected = verify_and_extract(text, {"axios"})
    assert "axios.post" in accepted
    assert citations == ["axios"]
    assert rejected == []


def test_rejects_imported_library_knowledge_when_it_uses_denylisted_language() -> None:
    """The denylist catches this specific phrasing (contains "handles").
    It does NOT reliably catch every way of describing a library's
    internal behavior in words outside the denylist (e.g. "retries",
    "caches") -- a known, documented limitation of a keyword-based
    checker, not a claim this test makes stronger than it is."""
    text = "Handles retries on transient failure automatically [ev:axios]."
    accepted, citations, rejected = verify_and_extract(text, {"axios"})
    assert accepted == ""
    [claim] = rejected
    assert claim.reason.startswith("interpretive language")


def test_rejects_sentence_with_no_citation_at_all() -> None:
    text = "This function does something important."
    accepted, citations, rejected = verify_and_extract(text, set())
    assert accepted == ""
    [claim] = rejected
    assert claim.reason == "missing citation"


def test_rejects_citation_to_id_not_on_the_record() -> None:
    text = "Calls authenticate() [ev:some.other.symbol]"
    accepted, citations, rejected = verify_and_extract(text, {"auth.py::authenticate"})
    assert accepted == ""
    [claim] = rejected
    assert "not in record evidence" in claim.reason


def test_partial_acceptance_keeps_good_sentences_and_drops_bad_ones() -> None:
    text = (
        "Calls authenticate() [ev:auth.py::authenticate]. "
        "Coordinates the whole login flow [ev:auth.py::authenticate]."
    )
    accepted, citations, rejected = verify_and_extract(text, {"auth.py::authenticate"})
    assert accepted == "Calls authenticate() ."
    assert citations == ["auth.py::authenticate"]
    assert len(rejected) == 1


# --- EvidenceConstrainedSummarizer: template/SLM routing ----------------


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10, total_tokens=30),
    )


async def _no_sleep(seconds: float) -> None:
    return None


def _summarizer(template_threshold: int = 3) -> EvidenceConstrainedSummarizer:
    client = LiteLLMClient(max_retries=1, base_delay_seconds=0.0, sleep=_no_sleep)
    return EvidenceConstrainedSummarizer(
        client, "gpt-4o-mini", template_threshold=template_threshold
    )


async def test_small_record_never_calls_the_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_if_called(**kwargs: object) -> SimpleNamespace:
        raise AssertionError("LLM should not be called for a small record")

    monkeypatch.setattr(litellm, "acompletion", fail_if_called)
    record = _record(direct_callees=["a.py::a"])
    summary = await _summarizer().summarize(record)
    assert summary.source is SummarySource.TEMPLATE


async def test_large_record_calls_llm_with_temperature_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return _fake_response("Calls a() [ev:a.py::a].")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    record = _record(direct_callees=["a.py::a", "b.py::b", "c.py::c", "d.py::d"])
    summary = await _summarizer().summarize(record)

    assert summary.source is SummarySource.SLM
    assert captured["temperature"] == 0.0
    assert summary.citations == ["a.py::a"]


async def test_insufficient_evidence_marker_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("INSUFFICIENT_EVIDENCE")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    record = _record(direct_callees=["a.py::a", "b.py::b", "c.py::c", "d.py::d"])
    summary = await _summarizer().summarize(record)

    assert summary.insufficient_evidence is True
    assert summary.text == ""


async def test_fully_rejected_output_becomes_insufficient_evidence_with_audit_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("Manages the entire request lifecycle [ev:a.py::a].")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    record = _record(direct_callees=["a.py::a", "b.py::b", "c.py::c", "d.py::d"])
    summary = await _summarizer().summarize(record)

    assert summary.insufficient_evidence is True
    assert summary.text == ""
    assert len(summary.rejected_claims) == 1


async def test_llm_failure_falls_back_to_template(monkeypatch: pytest.MonkeyPatch) -> None:
    async def always_fails(**kwargs: object) -> SimpleNamespace:
        raise litellm.APIConnectionError("boom", llm_provider="test", model="gpt-4o-mini")

    monkeypatch.setattr(litellm, "acompletion", always_fails)
    record = _record(direct_callees=["a.py::a", "b.py::b", "c.py::c", "d.py::d"])
    summary = await _summarizer().summarize(record)

    assert summary.source is SummarySource.TEMPLATE
    assert summary.insufficient_evidence is False


async def test_deterministic_across_independent_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same acceptance test as every prior phase: identical evidence in,
    identical summary out."""

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        return _fake_response("Calls a() [ev:a.py::a].")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    record = _record(direct_callees=["a.py::a", "b.py::b", "c.py::c", "d.py::d"])

    first = await _summarizer().summarize(record)
    second = await _summarizer().summarize(record)
    assert first.model_dump() == second.model_dump()
