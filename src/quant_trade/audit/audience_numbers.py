"""Declared teaching figures for the signal-copier audience page.

The Wilson interval, simulated ruin and history-versus-luck figures come
from the existing public calculators. They are assumptions, not measured
properties of a provider. The fixed-size ruin scenario is separate from
the advertised gain and drawdown: those two percentages cannot determine
average win/loss sizes, a Sharpe or a future loss probability.

The current figure reader accepts years, trades and win rate, but has no
gain, drawdown or cash-flow fields. Its unsupported figures remain absent;
this module must not infer them from an advertised percentage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from quant_trade.audit import account, calculator, reading, redflags, ruin_calc, winrate
from quant_trade.audit.public_card import PublicClaim, _num, _pct, _readings

DECLARED_RATE_PCT = 80.0
DECLARED_TRADES = 40
DECLARED_GAIN_PCT = 120.0
DECLARED_MONTHS = 6
DECLARED_DRAWDOWN_PCT = 12.0

#: Separate sizing assumptions, percentages of the initial balance per trade.
DECLARED_AVERAGE_WIN_PCT = 1.0
DECLARED_AVERAGE_LOSS_PCT = 3.0
#: The existing engine interprets this as a loss, leaving 70 % of initial balance.
DECLARED_RUIN_PCT = 30.0
DECLARED_HORIZON = ruin_calc.DEFAULT_HORIZON

#: A separate history-versus-luck illustration, never inferred from gain or drawdown.
DECLARED_SHARPE = 1.0
DECLARED_TRIALS = 100


def reader_values() -> dict[str, str]:
    """Only fields the existing public reader can actually interpret."""
    return {
        "trades": str(DECLARED_TRADES),
        "win_rate": f"{DECLARED_RATE_PCT:g}",
        "years": str(DECLARED_MONTHS / 12.0),
    }


def reader_rows(locale: str) -> tuple[tuple[str, str | None, str], ...]:
    """The figure reader's own localized output, with absent inputs kept absent."""
    return tuple(_readings(reading.claim_from_query(reader_values(), locale)))


def sizing_values() -> dict[str, str]:
    """The reader's fields plus the copy sizes as target and stop: only their
    ratio matters for the break-even win rate, the same one the ruin page uses."""
    return {
        **reader_values(),
        "target_r": f"{DECLARED_AVERAGE_WIN_PCT:g}",
        "stop_r": f"{DECLARED_AVERAGE_LOSS_PCT:g}",
    }


def _signed_pct(value: float, locale: str) -> str:
    """A share of the balance as a signed percentage with two decimals, as the
    ruin page writes expectancy: the sign follows the rounded value, so one that
    rounds to zero shows none; the minus is typographic, like the page's losses."""
    text = f"{_num(value * 100, locale, 2)} %"
    rounded = round(value * 100, 2)
    if rounded == 0:
        return text.lstrip("-")
    return "+" + text if rounded > 0 else "−" + text.lstrip("-")


@dataclass(frozen=True)
class SignalCopierExample:
    """Calculator outputs retained at full precision; every input is DECLARED."""

    claim: PublicClaim
    #: The same claim with the copy sizes, for the break-even win rate before costs.
    #: Declared before ``winrate``, whose field name shadows the module in this scope.
    sizing: winrate.WinRateReading
    winrate: winrate.WinRateReading
    ruin_input: ruin_calc.RuinInput
    ruin: ruin_calc.RuinReading
    luck_input: calculator.CalculatorInput
    luck_years_needed: float
    luck_sharpe: float


@lru_cache(maxsize=1)
def signal_copier_example() -> SignalCopierExample:
    """One deterministic example, computed once per process by the real tools."""
    claim = reading.claim_from_query(reader_values(), "en")
    ruin_input = ruin_calc.RuinInput(
        win_rate_pct=DECLARED_RATE_PCT,
        unit="pct",
        avg_win=DECLARED_AVERAGE_WIN_PCT,
        avg_loss=DECLARED_AVERAGE_LOSS_PCT,
        risk=None,
        ruin_pct=DECLARED_RUIN_PCT,
        horizon=DECLARED_HORIZON,
        trades=DECLARED_TRADES,
    )
    luck_input = calculator.CalculatorInput(
        sharpe=DECLARED_SHARPE,
        years=DECLARED_MONTHS / 12.0,
        trials=DECLARED_TRIALS,
    )
    luck = calculator.compute(luck_input)
    return SignalCopierExample(
        claim=claim,
        winrate=winrate.read(claim),
        sizing=winrate.read(reading.claim_from_query(sizing_values(), "en")),
        ruin_input=ruin_input,
        ruin=ruin_calc.compute(ruin_input),
        luck_input=luck_input,
        luck_years_needed=float(luck["years_needed"]["value"]),
        luck_sharpe=float(luck["luck_sharpe"]["value"]),
    )


def signal_copier_values(locale: str) -> dict[str, str]:
    """Localized substitutions; output rounding never changes calculator inputs."""
    example = signal_copier_example()
    interval = example.winrate.interval
    lower = example.ruin.lower
    breakeven = example.sizing.breakeven
    # The reader's own fair-coin row, exactly as the linked page prints it.
    coin = {key: value for key, value, _ in reader_rows(locale)}.get("coin")
    if interval is None or lower is None or breakeven is None or coin is None:
        raise ValueError("the declared example requires Wilson, break-even and coin rows")

    def input_percent(value: float) -> str:
        return f"{_num(value, locale, 0)} %"

    return {
        "rate": input_percent(DECLARED_RATE_PCT),
        "trades": _num(DECLARED_TRADES, locale, 0),
        "gain": f"+{input_percent(DECLARED_GAIN_PCT)}",
        "months": _num(DECLARED_MONTHS, locale, 0),
        "years": _num(DECLARED_MONTHS / 12.0, locale, 1),
        "drawdown": input_percent(DECLARED_DRAWDOWN_PCT),
        "wilson_low": _pct(interval[0], locale),
        "wilson_high": _pct(interval[1], locale),
        "coin": coin,
        "win": input_percent(DECLARED_AVERAGE_WIN_PCT),
        "loss": input_percent(DECLARED_AVERAGE_LOSS_PCT),
        "breakeven": _pct(breakeven, locale),
        "expectancy": _signed_pct(example.ruin.declared.expectancy_share, locale),
        "expectancy_low": _signed_pct(lower.expectancy_share, locale),
        "ruin_limit": input_percent(DECLARED_RUIN_PCT),
        "remaining": input_percent(100.0 - DECLARED_RUIN_PCT),
        "horizon": _num(DECLARED_HORIZON, locale, 0),
        "samples": _num(ruin_calc.SAMPLES, locale, 0),
        "ruin": _pct(example.ruin.declared.ruin, locale),
        "ruin_low": _pct(lower.ruin, locale),
        "sharpe": _num(DECLARED_SHARPE, locale, 1),
        "trials": _num(DECLARED_TRIALS, locale, 0),
        "luck_months": _num(math.ceil(example.luck_years_needed * 12.0), locale, 0),
        "luck_sharpe": _num(example.luck_sharpe, locale, 2),
        "luck_frequency": _num(example.luck_input.periods_per_year, locale, 0),
        "floating_warn": input_percent(account.FLOATING_WARN * 100.0),
        "inflated_min_gain": input_percent(account.INFLATED_MIN_GAIN * 100.0),
        "inflated_share": _pct(account.INFLATED_SHARE, locale),
        "top_up_drawdown": input_percent(account.TOP_UP_DRAWDOWN * 100.0),
        "martingale_ratio": _num(redflags.MARTINGALE_WARN_RATIO, locale, 2),
        "martingale_min": _num(redflags.MARTINGALE_MIN_EACH, locale, 0),
        "grid_share": input_percent(redflags.GRID_WARN_SHARE * 100.0),
        "grid_min": _num(redflags.GRID_WARN_MIN, locale, 0),
    }
