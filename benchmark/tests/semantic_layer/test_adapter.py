from benchmark.semantic_layer.adapter import to_target_names
from benchmark.semantic_layer.contract import SemanticQueryInterpretation, UncertaintyLevel


def test_confident_terms_are_projected() -> None:
    interp = SemanticQueryInterpretation(
        intent="locate_symbol",
        retrieval_terms=["Authenticator", "auth.py"],
        confidence=UncertaintyLevel.HIGH,
    )
    assert to_target_names(interp) == ["Authenticator", "auth.py"]


def test_uncertain_confidence_yields_empty_list_even_with_terms() -> None:
    interp = SemanticQueryInterpretation.model_construct(
        intent="locate_symbol",
        retrieval_terms=["Authenticator"],
        concepts=[],
        behavior=[],
        framework=None,
        confidence=UncertaintyLevel.UNCERTAIN,
        is_ambiguous=False,
        ambiguous_alternatives=[],
        is_negative_query=False,
        negation_targets=[],
    )
    assert to_target_names(interp) == []


def test_concepts_and_behavior_are_never_projected() -> None:
    interp = SemanticQueryInterpretation(
        intent="locate_symbol",
        retrieval_terms=["Authenticator"],
        concepts=["middleware chain", "getByRole"],
        behavior=["locate button"],
        confidence=UncertaintyLevel.HIGH,
    )
    assert to_target_names(interp) == ["Authenticator"]


def test_empty_retrieval_terms_projects_to_empty_list() -> None:
    interp = SemanticQueryInterpretation(intent="locate_symbol", confidence=UncertaintyLevel.LOW)
    assert to_target_names(interp) == []
