import pytest
from pydantic import ValidationError

from domain.complexity import ComplexityScore
from domain.enums import ComplexityLevel


def test_valid_score_constructs() -> None:
    score = ComplexityScore(score=0.42, level=ComplexityLevel.MEDIUM, signals={"file_count": 0.3})
    assert score.score == 0.42
    assert score.level is ComplexityLevel.MEDIUM
    assert score.signals == {"file_count": 0.3}


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_score_out_of_bounds_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        ComplexityScore(score=value, level=ComplexityLevel.LOW)


def test_is_frozen() -> None:
    score = ComplexityScore(score=0.1, level=ComplexityLevel.LOW)
    with pytest.raises(ValidationError):
        score.score = 0.9
