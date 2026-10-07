"""The calculator and luck section annualise at the declared return frequency."""

from __future__ import annotations

import math

import pytest

from quant_trade.audit.calculator import (
    COPY,
    CalculatorInput,
    calculator_copy,
    compute,
    parse_input,
)
from quant_trade.audit.guard import find_claims
from quant_trade.audit.luck import luck_review
from quant_trade.metrics.statistics import expected_max_sharpe


@pytest.mark.parametrize("periods", [252, 52, 12])
def test_calculator_uses_declared_frequency_in_observations_and_variance(periods: int) -> None:
    value = parse_input("1.8", "3", "100", str(periods))
    assert isinstance(value, CalculatorInput)
    assert value.periods_per_year == periods
    result = compute(value)
    # Normal-return sampling variance, based on the actual number of periods.
    variance = (1 + 0.5 * (1.8 / math.sqrt(periods)) ** 2) / (3 * periods - 1)
    expected = expected_max_sharpe(100, variance) * math.sqrt(periods)
    assert result["sharpe"]["value"] == pytest.approx(1.8)
    assert result["luck_sharpe"]["value"] == pytest.approx(expected)
    assert result["luck_sharpe"]["evidence"] == "MEASURED"


def test_daily_calculator_inputs_remain_backward_compatible() -> None:
    implicit = parse_input("1.8", "3", "100")
    explicit = parse_input("1.8", "3", "100", "252")
    assert implicit == explicit == CalculatorInput(1.8, 3, 100)
    assert isinstance(implicit, CalculatorInput)
    assert isinstance(explicit, CalculatorInput)
    assert compute(implicit) == compute(explicit)
    assert parse_input(None, None, None, "12") is None


@pytest.mark.parametrize("periods", ["", "nan", "inf", "0", "-12", "365", "monthly"])
def test_calculator_rejects_unsupported_frequency(periods: str) -> None:
    assert parse_input("1.8", "3", "100", periods) == "error_frequency"


def test_direct_calculator_input_cannot_use_an_unsupported_frequency() -> None:
    with pytest.raises(ValueError, match="unsupported return frequency"):
        compute(CalculatorInput(1.8, 3, 100, 0))


@pytest.mark.parametrize("periods", [252, 52, 12])
def test_luck_annualisation_uses_square_root_of_periods(periods: int) -> None:
    result = luck_review(
        {"sharpe_per_period": 0.3, "observations": 36},
        trials=100,
        trials_source="declared",
        sharpe_variance=0.01,
        periods_per_year=periods,
        span_years=3,
    )
    assert result["sharpe"]["value"] == pytest.approx(0.3 * math.sqrt(periods))
    assert result["luck_sharpe"]["value"] == pytest.approx(
        expected_max_sharpe(100, 0.01) * math.sqrt(periods)
    )


def test_luck_keeps_daily_default() -> None:
    result = luck_review(
        {"sharpe_per_period": 0.3, "observations": 36},
        trials=100,
        trials_source="declared",
        sharpe_variance=0.01,
        span_years=3,
    )
    assert result["sharpe"]["value"] == pytest.approx(0.3 * math.sqrt(252))


@pytest.mark.parametrize("periods", [float("nan"), float("inf"), 0, -12])
def test_luck_cannot_emit_nonfinite_frequency_metrics(periods: float) -> None:
    result = luck_review(
        {"sharpe_per_period": 0.3, "observations": 36},
        trials=100,
        trials_source="declared",
        sharpe_variance=0.01,
        periods_per_year=periods,
        span_years=3,
    )
    assert result["status"] == "NOT_MEASURED"


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("periods", [252, 52, 12])
def test_frequency_copy_matches_computation_and_passes_guard(locale: str, periods: int) -> None:
    copy = calculator_copy(locale, periods)
    assumption = copy["assumptions"][0]
    assert f"{periods} " in assumption and "DECLARED" in assumption
    assert copy["frequency_options"][periods] in assumption
    if periods != 252:
        assert "252" not in assumption
    for key in ("frequency", "frequency_help", "error_frequency", "declared_note", "cta"):
        assert find_claims(copy[key]) == []
    assert find_claims(assumption) == []
    assert all(find_claims(option) == [] for option in copy["frequency_options"].values())
    # Rendering another frequency does not change the default language copy.
    assert COPY[locale]["assumptions"][0] != assumption
