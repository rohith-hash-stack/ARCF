"""Paired t-test, stdlib-only (no scipy/numpy dependency for something
this self-contained).

The two-tailed p-value for a t-statistic with `df` degrees of freedom
is the regularized incomplete beta function I_x(df/2, 1/2) evaluated at
x = df/(df+t^2) — the standard identity relating the Student's t and
Beta distributions (see Abramowitz & Stegun 26.7.1, or Numerical
Recipes §6.4/§6.14, whose betacf/betai continued-fraction algorithm is
what _incomplete_beta below implements). This is the same formula
scipy.stats.ttest_rel ultimately evaluates; reimplementing it here
avoids a heavy new dependency for one function.
"""

import math
import statistics

_MAX_ITERATIONS = 200
_EPSILON = 3e-9
_FLOOR = 1e-300


def _continued_fraction(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = _FLOOR if abs(d) < _FLOOR else d
    d = 1.0 / d
    h = d

    for m in range(1, _MAX_ITERATIONS + 1):
        m2 = 2 * m

        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = _FLOOR if abs(d) < _FLOOR else d
        c = 1.0 + aa / c
        c = _FLOOR if abs(c) < _FLOOR else c
        d = 1.0 / d
        h *= d * c

        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = _FLOOR if abs(d) < _FLOOR else d
        c = 1.0 + aa / c
        c = _FLOOR if abs(c) < _FLOOR else c
        d = 1.0 / d
        delta = d * c
        h *= delta

        if abs(delta - 1.0) < _EPSILON:
            break

    return h


def _incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0

    log_prefactor = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    )
    prefactor = math.exp(log_prefactor)

    if x < (a + 1.0) / (a + b + 2.0):
        return prefactor * _continued_fraction(a, b, x) / a
    return 1.0 - prefactor * _continued_fraction(b, a, 1 - x) / b


def t_distribution_two_tailed_p(t_statistic: float, degrees_of_freedom: int) -> float:
    if degrees_of_freedom < 1:
        raise ValueError("degrees_of_freedom must be >= 1")
    x = degrees_of_freedom / (degrees_of_freedom + t_statistic * t_statistic)
    return _incomplete_beta(degrees_of_freedom / 2.0, 0.5, x)


def paired_ttest(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    """Two-tailed paired t-test on xs vs ys. Returns (t_statistic,
    p_value), or None if there are fewer than 2 pairs (not enough data
    for the test to mean anything)."""
    if len(xs) != len(ys):
        raise ValueError("xs and ys must be the same length (paired samples)")
    n = len(xs)
    if n < 2:
        return None

    diffs = [x - y for x, y in zip(xs, ys, strict=True)]
    mean_diff = statistics.mean(diffs)

    if all(d == diffs[0] for d in diffs):
        # Zero variance: every pair had the identical difference.
        return (0.0, 1.0) if mean_diff == 0 else (math.inf, 0.0)

    stdev_diff = statistics.stdev(diffs)
    t_statistic = mean_diff / (stdev_diff / math.sqrt(n))
    p_value = t_distribution_two_tailed_p(abs(t_statistic), n - 1)
    return t_statistic, p_value
