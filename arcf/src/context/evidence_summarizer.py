"""EvidenceConstrainedSummarizer (ARCF-DI Phase 5) — turns a
BehavioralRecord into an EvidenceSummary that satisfies the project's
core rule: "the SLM may compress evidence, but it may never create
evidence."

Not wired into context/packager.py's pipeline yet — that integration is
BLUEPRINT.md Phase 6's job ("thread citations through packager/
compressor/budget_manager"), same reason CallGraph's
`mandatory_disambiguation` shipped opt-in before any decision about
defaulting it on in production. This module is built and verified in
isolation first.

Two paths, chosen by evidence volume (BLUEPRINT.md Phase 5's "small
records skip the SLM entirely" design):

- Template (`render_template`): zero LLM involvement, pure string
  composition directly from BehavioralRecord fields. Fully cited by
  construction — every clause is a direct rendering of a field that is
  itself already-verified evidence, so there is nothing to verify.
- SLM-assisted (`EvidenceConstrainedSummarizer.summarize`): only for
  records whose evidence volume exceeds `template_threshold`. Builds a
  citation-constrained prompt, calls the LLM at temperature=0.0, then
  runs the raw output through `verify_and_extract` — the actual
  enforcement mechanism for "never create evidence." A sentence
  survives only if every citation tag it carries resolves to a real
  field on the record AND it contains no denylisted interpretive
  language. Sentences that fail either check are dropped, not kept,
  and recorded in `EvidenceSummary.rejected_claims` for audit.

`verify_and_extract` takes plain text and a citable-id set — it has no
dependency on the LLM client and is fully testable with hand-written
strings, which is where BLUEPRINT.md Phase 5's own accept/reject
examples become golden regression fixtures (see
tests/context/test_evidence_summarizer.py).
"""

import re

from domain.behavioral_record import BehavioralRecord
from domain.summarization import EvidenceSummary, RejectedClaim, SummaryConfidence, SummarySource
from infrastructure.llm_client import LiteLLMClient
from shared.errors import LLMInvocationError

_CITATION_PATTERN = re.compile(r"\[ev:([^\]]+)\]")

_DENYLIST = (
    "validates", "validate", "validating",
    "ensures", "ensure", "ensuring",
    "coordinates", "coordinate", "coordinating",
    "secures", "secure", "securing",
    "handles", "handle", "handling",
    "manages", "manage", "managing",
)
"""Interpretive/purpose language no evidence item can literally support —
BLUEPRINT.md Phase 5's own good/bad example pair ("Calls authenticate()
and then logEvent()" vs. "Coordinates authentication and logging")
operationalized as a denylist rather than left as a style guideline.
Deliberately conservative and small: false negatives (an interpretive
claim that slips through some other phrasing) are expected and are
what human review / BLUEPRINT.md Phase 9's citation-integrity suite is
for; false positives here just mean an occasional over-cautious reject,
never a fabricated claim kept."""

_INSUFFICIENT_EVIDENCE_MARKER = "INSUFFICIENT_EVIDENCE"

_PROMPT_TEMPLATE = """You are compressing already-verified static-analysis evidence about one \
function into 2-3 short sentences. You may state ONLY facts listed below — never describe what \
an external library call does beyond the literal invocation, never state a purpose or intent \
that isn't one of these listed facts, never use words like "validates", "ensures", \
"coordinates", "secures", "handles", or "manages" unless that exact fact is listed below.

Every sentence you write MUST end with at least one citation tag referencing the evidence id(s) \
it's based on, in the form [ev:ID]. Use ONLY the evidence ids listed below — never invent one.

If there is nothing you can say using only the facts below, respond with exactly the single \
word: {marker}

Evidence for {qualified_name}:
{evidence_lines}

Respond with ONLY the sentences (or the marker), no other text, no markdown.
"""


def citable_evidence_ids(record: BehavioralRecord) -> set[str]:
    """Every evidence id a generated sentence is allowed to cite for this
    record — the actual enforcement boundary for "never invent a
    citation." Deliberately a union of ids the record already carries,
    never a broader set (e.g. transitively-reachable evidence not on
    this record) — a summary about this symbol may only cite this
    symbol's own recorded evidence."""
    ids = set(record.file_import_ids)
    ids.update(record.direct_callees)
    ids.update(record.external_libraries_used)
    ids.update(call.call_id for call in record.ambiguous_calls)
    return ids


def _confidence(record: BehavioralRecord) -> SummaryConfidence:
    """Mechanical, not self-reported: LOW whenever disambiguation was
    never checked (an empty ambiguous_calls list means nothing here, see
    BehavioralRecord.disambiguation_aware) or the call graph was cut off
    before reaching a real boundary; MEDIUM when disambiguation ran and
    found real ambiguity; HIGH only when disambiguation ran, found none,
    and traversal wasn't truncated."""
    if not record.disambiguation_aware or record.dependency_depth.truncated:
        return SummaryConfidence.LOW
    if record.ambiguous_calls:
        return SummaryConfidence.MEDIUM
    return SummaryConfidence.HIGH


def _evidence_volume(record: BehavioralRecord) -> int:
    return (
        len(record.direct_callees)
        + len(record.external_libraries_used)
        + len(record.ambiguous_calls)
    )


def render_template(record: BehavioralRecord) -> EvidenceSummary:
    """Pure, deterministic, zero-LLM rendering — the only path for a
    record whose evidence volume is at or below the summarizer's
    threshold, and the fallback when the SLM path is unavailable or
    fails outright. Every clause is copied directly from record fields,
    so citation coverage is total by construction."""
    clauses: list[str] = []
    citations: set[str] = set()

    if record.direct_callees:
        names = ", ".join(_short_name(callee) for callee in record.direct_callees)
        clauses.append(f"Calls {names}.")
        citations.update(record.direct_callees)

    if record.external_libraries_used:
        libs = ", ".join(record.external_libraries_used)
        clauses.append(f"Uses external libraries: {libs}.")
        citations.update(record.external_libraries_used)

    if record.ambiguous_calls:
        names = ", ".join(sorted({call.callee_name for call in record.ambiguous_calls}))
        clauses.append(
            f"Calls to {names} could not be resolved to a single definition "
            f"(ambiguous — see candidates)."
        )
        citations.update(call.call_id for call in record.ambiguous_calls)

    text = " ".join(clauses)
    return EvidenceSummary(
        symbol_id=record.symbol_id,
        text=text,
        citations=sorted(citations),
        source=SummarySource.TEMPLATE,
        confidence=_confidence(record),
        insufficient_evidence=not clauses,
    )


def _short_name(symbol_id: str) -> str:
    """"auth.py::AuthService.authenticate" -> "authenticate" for
    readability in template prose. Purely cosmetic — the citation is the
    full symbol_id, unaffected by this."""
    return symbol_id.rsplit("::", 1)[-1].rsplit(".", 1)[-1]


def verify_and_extract(
    raw_text: str, citable_ids: set[str]
) -> tuple[str, list[str], list[RejectedClaim]]:
    """The actual "never create evidence" enforcement. Splits `raw_text`
    into sentences, keeps only those that (a) carry at least one
    citation tag, (b) every tag resolves into `citable_ids`, and (c)
    contain no denylisted interpretive word. Returns the accepted text
    (citation tags stripped), the sorted deduplicated citations actually
    used, and every rejected sentence with why."""
    accepted: list[str] = []
    citations: set[str] = set()
    rejected: list[RejectedClaim] = []

    for raw_sentence in _split_sentences(raw_text):
        sentence = raw_sentence.strip()
        if not sentence:
            continue

        tags = _CITATION_PATTERN.findall(sentence)
        if not tags:
            rejected.append(RejectedClaim(text=sentence, reason="missing citation"))
            continue

        unknown = [tag for tag in tags if tag not in citable_ids]
        if unknown:
            rejected.append(
                RejectedClaim(
                    text=sentence,
                    reason=f"citation not in record evidence: {', '.join(unknown)}",
                )
            )
            continue

        lowered = sentence.lower()
        denylisted = [word for word in _DENYLIST if word in lowered]
        if denylisted:
            rejected.append(
                RejectedClaim(
                    text=sentence,
                    reason=(
                        "interpretive language not derivable from evidence: "
                        f"{', '.join(denylisted)}"
                    ),
                )
            )
            continue

        citations.update(tags)
        accepted.append(_CITATION_PATTERN.sub("", sentence).strip())

    return " ".join(accepted), sorted(citations), rejected


def _split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


class EvidenceConstrainedSummarizer:
    def __init__(
        self,
        llm_client: LiteLLMClient,
        model: str,
        template_threshold: int = 3,
        max_tokens: int = 200,
    ) -> None:
        self._llm_client = llm_client
        self._model = model
        self._template_threshold = template_threshold
        self._max_tokens = max_tokens

    async def summarize(self, record: BehavioralRecord) -> EvidenceSummary:
        if _evidence_volume(record) <= self._template_threshold:
            return render_template(record)

        citable_ids = citable_evidence_ids(record)
        prompt = _PROMPT_TEMPLATE.format(
            marker=_INSUFFICIENT_EVIDENCE_MARKER,
            qualified_name=record.qualified_name,
            evidence_lines=_render_evidence_lines(record),
        )

        try:
            completion = await self._llm_client.complete(
                prompt, self._model, max_tokens=self._max_tokens, temperature=0.0
            )
        except LLMInvocationError:
            # Never fatal -- degrade to the always-available template path
            # rather than fail the whole record, same "never fatal to the
            # package" posture context/understanding.py's own docstring
            # already establishes for SLM-2.
            return render_template(record)

        raw = completion.content.strip()
        if raw == _INSUFFICIENT_EVIDENCE_MARKER:
            return EvidenceSummary(
                symbol_id=record.symbol_id,
                text="",
                citations=[],
                source=SummarySource.SLM,
                confidence=_confidence(record),
                insufficient_evidence=True,
            )

        text, citations, rejected = verify_and_extract(raw, citable_ids)
        if not text:
            # Every generated sentence failed verification -- an honest
            # "nothing survived," not a silently empty summary that looks
            # identical to "there was nothing to say" from the marker path.
            return EvidenceSummary(
                symbol_id=record.symbol_id,
                text="",
                citations=[],
                source=SummarySource.SLM,
                confidence=_confidence(record),
                insufficient_evidence=True,
                rejected_claims=rejected,
            )

        return EvidenceSummary(
            symbol_id=record.symbol_id,
            text=text,
            citations=citations,
            source=SummarySource.SLM,
            confidence=_confidence(record),
            rejected_claims=rejected,
        )


def _render_evidence_lines(record: BehavioralRecord) -> str:
    lines: list[str] = []
    for callee in record.direct_callees:
        lines.append(f"- calls {_short_name(callee)} [ev:{callee}]")
    for library in record.external_libraries_used:
        lines.append(f"- uses external library {library} [ev:{library}]")
    for call in record.ambiguous_calls:
        lines.append(
            f"- call to {call.callee_name} is ambiguous, {len(call.candidates)} "
            f"possible targets [ev:{call.call_id}]"
        )
    return "\n".join(lines) if lines else "(none)"
