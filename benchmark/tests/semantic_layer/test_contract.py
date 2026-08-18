import pytest
from pydantic import ValidationError

from benchmark.semantic_layer.contract import SemanticQueryInterpretation, UncertaintyLevel


def test_minimal_valid_interpretation() -> None:
    interp = SemanticQueryInterpretation(intent="locate_symbol")
    assert interp.retrieval_terms == []
    assert interp.confidence == UncertaintyLevel.UNCERTAIN
    assert interp.is_ambiguous is False
    assert interp.is_negative_query is False


def test_uncertain_confidence_with_empty_terms_is_valid() -> None:
    interp = SemanticQueryInterpretation(
        intent="locate_symbol", retrieval_terms=[], confidence=UncertaintyLevel.UNCERTAIN
    )
    assert interp.retrieval_terms == []


def test_blank_intent_rejected() -> None:
    with pytest.raises(ValidationError):
        SemanticQueryInterpretation(intent="   ")


def test_unknown_confidence_level_rejected() -> None:
    with pytest.raises(ValidationError):
        SemanticQueryInterpretation(intent="x", confidence="very_sure")


def test_too_many_retrieval_terms_rejected() -> None:
    with pytest.raises(ValidationError):
        SemanticQueryInterpretation(intent="x", retrieval_terms=[f"t{i}" for i in range(20)])


def test_fabricated_line_number_rejected() -> None:
    with pytest.raises(ValidationError):
        SemanticQueryInterpretation(intent="x", retrieval_terms=["42"])


def test_fabricated_path_line_location_rejected() -> None:
    with pytest.raises(ValidationError):
        SemanticQueryInterpretation(intent="x", retrieval_terms=["src/auth.py:88"])


def test_ordinary_identifier_terms_accepted() -> None:
    interp = SemanticQueryInterpretation(
        intent="x", retrieval_terms=["Authenticator", "auth.py", "AuthenticationError"]
    )
    assert interp.retrieval_terms == ["Authenticator", "auth.py", "AuthenticationError"]


def test_negative_query_fields() -> None:
    interp = SemanticQueryInterpretation(
        intent="explain_absence",
        is_negative_query=True,
        negation_targets=["sub claim validation"],
    )
    assert interp.is_negative_query is True
    assert interp.negation_targets == ["sub claim validation"]


def test_ambiguous_query_fields() -> None:
    interp = SemanticQueryInterpretation(
        intent="locate_symbol",
        is_ambiguous=True,
        ambiguous_alternatives=["the agent-local handler", "the RPC handler"],
    )
    assert interp.is_ambiguous is True
    assert len(interp.ambiguous_alternatives) == 2


def test_frozen_model_is_immutable() -> None:
    interp = SemanticQueryInterpretation(intent="x")
    with pytest.raises(ValidationError):
        interp.intent = "y"  # type: ignore[misc]
