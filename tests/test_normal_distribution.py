"""The shared normal CDF, including Acklam's two tail branches.

``metrics.statistics`` used to carry a private copy of these.  There is now one
implementation, and these tests pin it directly rather than only through the
PSR/DSR estimators that happen to call it near the centre of the distribution.
"""

from __future__ import annotations

import math

import pytest

from quant_trade.metrics.normal import normal_cdf, normal_inverse_cdf
from quant_trade.metrics.statistics import _phi, _phi_inv


def test_statistics_uses_the_shared_implementation() -> None:
    assert _phi is normal_cdf
    assert _phi_inv is normal_inverse_cdf


@pytest.mark.parametrize(
    ("x", "expected"),
    [(0.0, 0.5), (1.0, 0.8413447461), (-1.0, 0.1586552539), (1.959963985, 0.975)],
)
def test_normal_cdf_matches_known_values(x: float, expected: float) -> None:
    assert normal_cdf(x) == pytest.approx(expected, abs=1e-9)


@pytest.mark.parametrize("p", [1e-8, 1e-4, 0.02, 0.024, 0.1, 0.5, 0.9, 0.976, 0.9999, 1 - 1e-8])
def test_inverse_round_trips_through_both_tails_and_the_centre(p: float) -> None:
    """0.02425 and its complement are the branch boundaries in Acklam's form."""
    assert normal_cdf(normal_inverse_cdf(p)) == pytest.approx(p, abs=2e-6)


def test_inverse_is_antisymmetric() -> None:
    for p in (0.001, 0.05, 0.25):
        assert normal_inverse_cdf(p) == pytest.approx(-normal_inverse_cdf(1.0 - p), abs=1e-6)


@pytest.mark.parametrize("p", [0.0, 1.0, -0.5, 1.5, 2.0])
def test_inverse_rejects_probabilities_outside_the_open_unit_interval(p: float) -> None:
    with pytest.raises(ValueError):
        normal_inverse_cdf(p)


def test_cdf_saturates_without_raising() -> None:
    assert normal_cdf(-40.0) == pytest.approx(0.0, abs=1e-12)
    assert normal_cdf(40.0) == pytest.approx(1.0, abs=1e-12)
    assert math.isfinite(normal_cdf(0.0))
