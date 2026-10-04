"""Shared helpers for the generator tests."""

from collections.abc import Mapping
from math import sqrt

Z_BONFERRONI = 3.29  # one-sided p = 0.0005 per test, about 0.005 over the ten statistical tests


def chi2_critical(df: int, z: float = Z_BONFERRONI) -> float:
    """The chi-square quantile for z standard deviations (Wilson-Hilferty), no scipy needed."""
    return df * (1 - 2 / (9 * df) + z * sqrt(2 / (9 * df))) ** 3


def chi2_statistic[K](observed: Mapping[K, int], expected: Mapping[K, float]) -> float:
    """Pearson's statistic over the cells whose expected count is at least 5."""
    return sum((observed.get(cell, 0) - e) ** 2 / e for cell, e in expected.items() if e >= 5)
