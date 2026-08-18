"""SemanticQueryInterpretation — the structured contract a semantic
interpretation layer (generic SLM, remote LLM, or ARCF's existing SLM-1)
produces from a natural-language query, BEFORE any retrieval happens.

Design principle (non-negotiable, enforced structurally by what this
model does and does not contain): the interpreter answers "what does the
user's query mean?" — never "what exists in this repository?". Nothing
in this schema is a repository fact. There is deliberately no field for
a file path that is asserted to exist, a line number, a symbol that is
asserted to be real, or a relationship between real files/symbols. Only
`ARCF-DI` (deterministic retrieval, unchanged by this experiment) is
permitted to assert any of those things. This model is downstream input
to retrieval, never a substitute for it — see `adapter.py`'s docstring
for exactly how (and how narrowly) it is allowed to influence ARCF-DI.

Framework-independence: nothing here is Playwright-, Django-, or
SQLAlchemy-specific. `framework` and `concepts` are free-text fields the
interpreter fills in for WHATEVER framework the query happens to be
about (or leaves empty/uncertain) — this schema itself encodes no
framework knowledge.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MAX_LIST_ITEMS = 12
_MAX_TERM_LENGTH = 80

# A retrieval term that is nothing but a line number, or a "path:line"
# shape, is exactly the kind of repository-fact fabrication this contract
# forbids (see module docstring) — the interpreter does not get to assert
# WHERE in a file something lives, only that some term is worth ARCF-DI
# checking. This is a best-effort syntactic guard, not a semantic one:
# it catches the obvious fabrication shapes, not every possible one.
_LOOKS_LIKE_FABRICATED_LOCATION = re.compile(r"^\d+$|:\d+$")


class UncertaintyLevel:
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNCERTAIN = "uncertain"
    """Not a low score — a distinct, first-class value. An interpreter
    that cannot confidently derive retrieval terms from the query MUST
    report `uncertain` rather than emit a fabricated high-confidence
    guess. See `SemanticQueryInterpretation.confidence`'s own docstring."""

    ALL = (HIGH, MEDIUM, LOW, UNCERTAIN)


def _validate_term_list(values: list[str], field_name: str) -> list[str]:
    if len(values) > _MAX_LIST_ITEMS:
        raise ValueError(f"{field_name} has {len(values)} items, max {_MAX_LIST_ITEMS}")
    cleaned: list[str] = []
    for raw in values:
        term = raw.strip()
        if not term:
            continue
        if len(term) > _MAX_TERM_LENGTH:
            raise ValueError(f"{field_name} item exceeds {_MAX_TERM_LENGTH} chars: {term!r}")
        if _LOOKS_LIKE_FABRICATED_LOCATION.search(term):
            raise ValueError(
                f"{field_name} item {term!r} looks like a fabricated file:line "
                "location — the interpreter must not assert WHERE something "
                "lives, only that a term is worth checking"
            )
        cleaned.append(term)
    return cleaned


class SemanticQueryInterpretation(BaseModel):
    """Structured semantic hints for one query. See module docstring for
    the "semantic hints, not repository facts" boundary this schema
    enforces.

    Required fields: `intent`, `retrieval_terms`, `confidence`,
    `is_ambiguous`, `is_negative_query`. Everything else is optional and
    defaults to "the interpreter had nothing to say here" (empty list /
    None) — a sparse-but-valid response is always preferred over a
    fabricated one.
    """

    model_config = ConfigDict(frozen=True)

    intent: str = Field(min_length=1, max_length=120)
    """Short label for what the user wants, e.g. "locate_symbol",
    "understand_behavior", "trace_call_chain", "explain_absence". Free
    text, not a closed enum — the space of query intents is open-ended
    and enumerating it up front would just move fabrication into intent
    values that don't fit. ARCF-DI never reads this field directly (see
    adapter.py); it exists for auditability and for future ranking-
    profile selection, exactly like `context/task_profile.py`'s existing
    deterministic `RetrievalTaskType` does today, but is NOT that enum
    and does NOT replace it in this experiment."""

    retrieval_terms: list[str] = Field(default_factory=list)
    """The only field the adapter projects into ARCF-DI's existing
    `target_names: list[str]` channel (see adapter.py). Identifier-like
    tokens or short qualified names the interpreter believes are worth
    ARCF-DI checking — NOT a claim that they exist. May be empty when
    `confidence` is `uncertain` (see UncertaintyLevel docstring) — an
    empty list here is a valid, honest answer, not a failure."""

    concepts: list[str] = Field(default_factory=list)
    """Framework/domain concepts the interpreter believes are relevant
    (e.g. "getByRole", "connection pool", "middleware chain") — semantic
    color for the human/report, not fed to ARCF-DI. Framework-agnostic:
    nothing in this schema hard-codes which frameworks exist."""

    behavior: list[str] = Field(default_factory=list)
    """Short, action-oriented phrases describing what the relevant code
    should DO, e.g. "locate the button", "reject the request". Not fed
    to ARCF-DI directly; documents the interpreter's read of the verb
    side of the query, separate from the noun side (`concepts`)."""

    framework: str | None = None
    """Best-guess framework/library name, or None when not applicable or
    not confidently inferrable. Never asserted as fact — ARCF-DI's own
    `workspace/framework_detection.py` remains the actual source of truth
    about which framework a repository uses; this is only the
    interpreter's guess about what the QUERY is talking about."""

    confidence: str = Field(default=UncertaintyLevel.UNCERTAIN)
    """One of UncertaintyLevel.ALL. Deliberately a small closed set of
    qualitative levels, not a numeric score: a numeric self-reported
    confidence (as ARCF-1's `RawIntentExtraction.self_reported_confidence`
    already has) invites false precision from a model that has no
    calibrated basis for producing one. `uncertain` is always a valid,
    non-penalized answer — see module docstring."""

    is_ambiguous: bool = False
    """The interpreter's own signal that the query supports more than
    one reasonable reading. Distinct from ARCF-DI's own downstream
    ambiguity signals (e.g. `domain/context_resolution.py`'s
    `ambiguity_confidence` on a resolved symbol) — this one is about the
    QUERY's language, computed before any retrieval happens."""

    ambiguous_alternatives: list[str] = Field(default_factory=list)
    """Short descriptions of the alternative readings, only meaningful
    when `is_ambiguous` is True. Not required even then — the
    interpreter may flag ambiguity without being able to enumerate
    specific alternatives."""

    is_negative_query: bool = False
    """True for queries about absence or failure-to-happen ("why does X
    NOT get called", "where is Y missing validation") — these need
    different retrieval handling than a positive "find X" query (see
    adapter.py's negative-query note), and naively feeding
    `retrieval_terms` from a negative query into ARCF-DI's positive
    exact-match/lexical channels can retrieve the wrong thing with high
    apparent confidence."""

    negation_targets: list[str] = Field(default_factory=list)
    """What is being negated, only meaningful when `is_negative_query`
    is True, e.g. ["validation", "sub claim check"] for "why isn't the
    JWT's sub claim validated". Optional even then."""

    @field_validator("intent")
    @classmethod
    def _intent_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("intent must not be blank")
        return stripped

    @field_validator("confidence")
    @classmethod
    def _confidence_is_known_level(cls, value: str) -> str:
        if value not in UncertaintyLevel.ALL:
            raise ValueError(
                f"confidence {value!r} is not one of {UncertaintyLevel.ALL} — "
                "malformed-output handling (see interpreter.py) treats this "
                "as a parse failure, not a silent coercion"
            )
        return value

    @field_validator("retrieval_terms", "concepts", "behavior", "ambiguous_alternatives",
                      "negation_targets")
    @classmethod
    def _bounded_term_lists(cls, value: list[str], info: object) -> list[str]:
        field_name = getattr(info, "field_name", "field")
        return _validate_term_list(value, field_name)

    @model_validator(mode="after")
    def _uncertain_confidence_permits_empty_terms(self) -> SemanticQueryInterpretation:
        """Not a rejection rule — a documentation point enforced as a
        no-op check: `confidence == "uncertain"` with empty
        `retrieval_terms` is explicitly VALID (see UncertaintyLevel and
        retrieval_terms docstrings) and must never be "fixed" by
        fabricating terms. Kept as an explicit validator (rather than
        just prose) so a future edit that adds a stricter rule here
        doesn't accidentally reintroduce a non-empty-terms requirement
        without noticing it conflicts with the uncertainty contract."""
        return self
