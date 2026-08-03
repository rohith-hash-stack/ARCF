"""Deterministic confidence scoring (Phase 3 deliverable).

The SLM's own self-reported confidence is one signal among several, not
the answer — per the Golden Rule ("never trust the LLM output"), the
final score is a fixed, reproducible function of signals that are
themselves either deterministic (classifier agreement, counts) or
clamped (the self-report). Two runs with identical signals always
produce identical confidence; no signal, on its own, can force a high
score.
"""

from pydantic import BaseModel, ConfigDict, Field

_SHORT_REQUEST_CHAR_THRESHOLD = 15

# Weights sum to 1.0.
_WEIGHT_DOMAIN_KNOWN = 0.20
_WEIGHT_TASK_KNOWN = 0.20
_WEIGHT_DOMAIN_AGREEMENT = 0.15
_WEIGHT_TASK_AGREEMENT = 0.15
_WEIGHT_ENTITIES = 0.10
_WEIGHT_CONSTRAINTS_ASSUMPTIONS = 0.05
_WEIGHT_SELF_REPORT = 0.15


class ConfidenceSignals(BaseModel):
    model_config = ConfigDict(frozen=True)

    domain_known: bool
    task_known: bool
    domain_classifier_agrees: bool
    task_classifier_agrees: bool
    entity_count: int = Field(ge=0)
    constraint_count: int = Field(ge=0)
    assumption_count: int = Field(ge=0)
    self_reported_confidence: float
    raw_request_char_count: int = Field(ge=0)


class ConfidenceEngine:
    def score(self, signals: ConfidenceSignals) -> float:
        value = 0.0
        value += _WEIGHT_DOMAIN_KNOWN if signals.domain_known else 0.0
        value += _WEIGHT_TASK_KNOWN if signals.task_known else 0.0
        value += _WEIGHT_DOMAIN_AGREEMENT if signals.domain_classifier_agrees else 0.0
        value += _WEIGHT_TASK_AGREEMENT if signals.task_classifier_agrees else 0.0
        value += min(signals.entity_count, 3) / 3 * _WEIGHT_ENTITIES
        value += (
            min(signals.constraint_count + signals.assumption_count, 4)
            / 4
            * _WEIGHT_CONSTRAINTS_ASSUMPTIONS
        )
        clamped_self_report = max(0.0, min(signals.self_reported_confidence, 1.0))
        value += clamped_self_report * _WEIGHT_SELF_REPORT

        if signals.raw_request_char_count < _SHORT_REQUEST_CHAR_THRESHOLD:
            value *= 0.7

        return round(max(0.0, min(1.0, value)), 4)
