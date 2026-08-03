import math

import pytest

from benchmark.suite.stats import paired_ttest, t_distribution_two_tailed_p


@pytest.mark.parametrize(
    "t_statistic,df,expected_p",
    [
        (2.262, 9, 0.05),
        (12.706, 1, 0.05),
        (2.042, 30, 0.05),
    ],
)
def test_matches_known_critical_values(t_statistic: float, df: int, expected_p: float) -> None:
    assert t_distribution_two_tailed_p(t_statistic, df) == pytest.approx(expected_p, abs=1e-3)


def test_t_zero_is_p_one() -> None:
    assert t_distribution_two_tailed_p(0.0, 10) == pytest.approx(1.0)


def test_paired_ttest_significant_difference() -> None:
    xs = [10.0, 12.0, 9.0, 11.0, 10.0, 13.0, 9.0, 10.0]
    ys = [8.0, 9.0, 7.0, 8.0, 7.0, 9.0, 8.0, 7.0]
    result = paired_ttest(xs, ys)
    assert result is not None
    t_stat, p_value = result
    assert t_stat > 0
    assert p_value < 0.05


def test_paired_ttest_identical_pairs_is_p_one() -> None:
    result = paired_ttest([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert result == (0.0, 1.0)


def test_paired_ttest_identical_nonzero_diff() -> None:
    t_stat, p_value = paired_ttest([2.0, 3.0, 4.0], [1.0, 2.0, 3.0])  # type: ignore[misc]
    assert t_stat == math.inf
    assert p_value == 0.0


def test_paired_ttest_requires_equal_length() -> None:
    with pytest.raises(ValueError, match="same length"):
        paired_ttest([1.0, 2.0], [1.0])


def test_paired_ttest_too_few_pairs_returns_none() -> None:
    assert paired_ttest([1.0], [2.0]) is None
    assert paired_ttest([], []) is None
