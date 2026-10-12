"""The signal-copier page reproduces calculator results, not editorial estimates."""

from __future__ import annotations

import math
from urllib.parse import parse_qs, urlsplit

import pytest

from quant_trade.audit import audience_numbers as numbers
from quant_trade.audit import calculator, reading, ruin_calc, winrate
from quant_trade.audit.public_card import _num, _pct, _readings, breakeven_rate


def test_example_uses_the_public_calculators_and_fixed_sizing() -> None:
    example = numbers.signal_copier_example()
    claim = reading.claim_from_query({"trades": "40", "win_rate": "80", "years": "0.5"}, "en")
    assert example.claim == claim
    assert example.winrate == winrate.read(claim)
    assert example.winrate.interval is not None

    # Parse a visitor's query independently: the published assumptions must
    # reproduce exactly the tool linked beside them, including Wilson's lower end.
    parsed = ruin_calc.parse(
        {
            "win_rate": "80",
            "trades": "40",
            "unit": "pct",
            "avg_win": "1",
            "avg_loss": "3",
            "ruin": "30",
            "horizon": "500",
        }
    )
    assert parsed.errors == ()
    assert parsed.value == example.ruin_input
    assert parsed.value is not None
    assert example.ruin == ruin_calc.compute(parsed.value)
    assert example.ruin.lower is not None
    assert example.ruin.interval == example.winrate.interval
    assert example.ruin.lower.win_rate == example.winrate.interval[0]
    assert example.ruin.lower.ruin > example.ruin.declared.ruin
    # The break-even win rate comes from the win-rate calculator with the same
    # +1 %/−3 % sizes; the declared rate sits above it and Wilson's lower end below,
    # which is the ruin comparison the page explains.
    sized = reading.claim_from_query(
        {"trades": "40", "win_rate": "80", "years": "0.5", "target_r": "1", "stop_r": "3"}, "en"
    )
    assert example.sizing == winrate.read(sized)
    assert example.sizing.breakeven == breakeven_rate(1.0, 3.0)
    assert example.sizing.interval == example.winrate.interval
    assert example.winrate.interval[0] < example.sizing.breakeven < numbers.DECLARED_RATE_PCT / 100
    assert example.ruin.declared.expectancy_share > 0 > example.ruin.lower.expectancy_share


def test_ruin_is_a_thirty_percent_loss_and_the_example_is_reproducible() -> None:
    example = numbers.signal_copier_example()
    value = example.ruin_input
    paths = ruin_calc.simulate(value.win_rate, value.win, value.loss, value.horizon)
    at_loss_limit = float((paths.lowest <= 0.70 + ruin_calc.TOUCH).mean())
    assert example.ruin.declared.ruin == at_loss_limit
    numbers.signal_copier_example.cache_clear()
    ruin_calc.compute.cache_clear()
    assert numbers.signal_copier_example() == example


def test_luck_uses_separate_declared_sharpe_and_trials() -> None:
    example = numbers.signal_copier_example()
    expected_input = calculator.CalculatorInput(sharpe=1.0, years=0.5, trials=100)
    expected = calculator.compute(expected_input)
    assert example.luck_input == expected_input
    assert example.luck_years_needed == expected["years_needed"]["value"]
    assert example.luck_sharpe == expected["luck_sharpe"]["value"]
    # Gain and drawdown do not imply the missing Sharpe or trial count.
    assert example.claim.sharpe is None
    assert example.claim.trials is None
    # The first check contrasts the declared months with the months luck needs.
    assert math.ceil(example.luck_years_needed * 12.0) > numbers.DECLARED_MONTHS


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_reader_keeps_unsupported_and_missing_figures_absent(locale: str) -> None:
    values = numbers.reader_values()
    assert set(values) <= set(reading.FIELDS)
    assert not {"gain", "drawdown", "months", "sharpe", "trials"} & set(values)
    rows = numbers.reader_rows(locale)
    claim = reading.claim_from_query(values, locale)
    assert rows == tuple(_readings(claim))
    by_key = {key: value for key, value, _ in rows}
    assert by_key["wilson"] is not None
    # With 40 trades the reader prints its fair-coin row; the luck row stays absent
    # because trials are missing (a Sharpe is not required: the null model applies).
    assert by_key["coin"] is not None
    assert by_key["luck"] is None
    assert by_key["breakeven"] is None
    assert numbers.signal_copier_values(locale)["coin"] == by_key["coin"]
    assert not {"profit_factor", "sharpe", "trials", "target_r", "stop_r"} & set(
        numbers.reader_values()
    )
    assert set(numbers.sizing_values()) == set(values) | {"target_r", "stop_r"}
    link = reading.reading_url(locale, values)
    assert parse_qs(urlsplit(link).query) == {
        **{key: [value] for key, value in values.items()},
        "ref": ["lectura"],
    }


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_display_preserves_precision_until_localized_render(locale: str) -> None:
    example = numbers.signal_copier_example()
    values = numbers.signal_copier_values(locale)
    assert example.winrate.interval is not None
    assert example.ruin.lower is not None
    low, high = example.winrate.interval
    assert values["wilson_low"] == _pct(low, locale)
    assert values["wilson_high"] == _pct(high, locale)
    assert values["ruin"] == _pct(example.ruin.declared.ruin, locale)
    assert values["ruin_low"] == _pct(example.ruin.lower.ruin, locale)
    assert values["luck_months"] == str(math.ceil(example.luck_years_needed * 12.0))
    assert values["remaining"] == "70 %"
    assert example.sizing.breakeven is not None
    assert values["breakeven"] == _pct(example.sizing.breakeven, locale)
    # Expectancy as the ruin page writes it: two decimals, sign from the rounded value.
    declared = example.ruin.declared.expectancy_share * 100
    lower = example.ruin.lower.expectancy_share * 100
    assert values["expectancy"] == f"+{_num(declared, locale, 2)} %"
    assert values["expectancy_low"] == f"−{_num(abs(lower), locale, 2)} %"
    assert numbers._signed_pct(0.0, locale) == f"{_num(0.0, locale, 2)} %"
    assert numbers._signed_pct(-0.000001, locale) == f"{_num(0.0, locale, 2)} %"
