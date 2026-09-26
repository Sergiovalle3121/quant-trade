"""The Sharpe ratio after what cash in dollars paid over the same dates.

The headline Sharpe divides the average return by its spread and subtracts
nothing. A strategy that made 5 % a year in 2023, when a US Treasury bill paid
about 5 %, did no better than cash; the same 5 % in 2015, when bills paid
nothing, did. This module subtracts, from each return, what the 3-month US
Treasury bill paid over the same stretch of days (FRED's ``DTB3``, read at run
time) and reports the Sharpe ratio of what is left, beside the plain one.

Each return spans the days from the previous point to its own; the bill's
rate on or before the start of that stretch (at most ``MAX_GAP_DAYS`` old) is
compounded over those days. FRED publishes a bank-discount rate ``d``: a
91-day bill costs ``1 - d * 91 / 360``, so the annual yield compounded is
``(1 - d * 91 / 360) ** (-365 / 91) - 1`` (5.234 % for a 5 % discount rate),
and that yield is what is used. It is a dollar rate: for an account in another
currency, that currency's own cash rate is the fair one, and the note says so.

When an imported report names the account's currency and FRED carries a
current cash rate for it (``LOCAL``: the overnight or immediate rate of the
peso, real, euro, pound, yen and Canadian dollar, the 3-month interbank rate of
the Swiss franc), that rate is subtracted instead (:func:`local_excess_sharpe`),
converted to an annual yield by its own quote: a simple rate over ``tenor_days``
on a ``basis``-day year, rolled over for a year, or, for Brazil's, a rate that
is already an annual compounded yield. Monthly series are averages of the
month, so a point takes its own month's value or the latest one published.
Nothing here changes the class.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.market import CASH, LOCAL_CASH, Asset
from quant_trade.audit.schema import measured

#: A bill rate older than this before a return's start is too stale to use.
MAX_GAP_DAYS = 10
#: Days to maturity of the 3-month bill the discount rate is quoted for.
BILL_DAYS = 91.0
#: Below this excess Sharpe the report says in words that cash did better.
BELOW_CASH_SHARPE = -3.0
#: Returns needed before the figure is worth printing.
MIN_RETURNS = 10

NOTE = (
    "Sharpe ratio of the returns after subtracting what the 3-month US Treasury bill paid "
    "over the same days (FRED DTB3, converted from the discount rate to an annual yield), "
    "annualised like the headline Sharpe; a dollar rate"
)
UNAVAILABLE = "the Treasury bill rates could not be read when the report was made"
NOT_COVERED = "the Treasury bill rates do not cover the whole history"
TOO_FEW = "fewer than ten returns"
FLAT = "the returns never move"
NOTE_LOCAL = (
    "Sharpe ratio of the returns after subtracting what cash in the account's own currency "
    "paid over the same days (the short rate FRED publishes for that currency, converted "
    "to an annual yield by its own quote), annualised like the headline Sharpe"
)
#: A monthly average older than this before a return's start is too stale to use.
MAX_MONTHLY_GAP_DAYS = 75


@dataclass(frozen=True)
class LocalCash:
    """A currency's own cash rate and how its quote becomes an annual yield."""

    asset: Asset
    #: Days in the year the quote divides by; None when it is already an
    #: annual compounded yield.
    basis: float | None
    #: Days the quoted rate is for: 1 overnight, 91 for three months.
    tenor_days: float
    #: How old the last value before a return's start may be.
    max_gap: int

    def yearly(self, percent: np.ndarray) -> np.ndarray:
        rate = np.asarray(percent, dtype=float) / 100.0
        if self.basis is None:
            return rate
        return (1.0 + rate * self.tenor_days / self.basis) ** (365.0 / self.tenor_days) - 1.0


_BY_CODE = {asset.label: asset for asset in LOCAL_CASH}
#: Cash rates by account currency: (days in the quote's year, tenor, staleness).
LOCAL: dict[str, LocalCash] = {
    "MXN": LocalCash(_BY_CODE["MXN"], 360.0, 1.0, MAX_MONTHLY_GAP_DAYS),
    "BRL": LocalCash(_BY_CODE["BRL"], None, 1.0, MAX_MONTHLY_GAP_DAYS),
    "EUR": LocalCash(_BY_CODE["EUR"], 360.0, 1.0, 10),
    "GBP": LocalCash(_BY_CODE["GBP"], 365.0, 1.0, 10),
    "JPY": LocalCash(_BY_CODE["JPY"], 365.0, 1.0, MAX_MONTHLY_GAP_DAYS),
    "CAD": LocalCash(_BY_CODE["CAD"], 365.0, 1.0, MAX_MONTHLY_GAP_DAYS),
    "CHF": LocalCash(_BY_CODE["CHF"], 360.0, 91.0, MAX_MONTHLY_GAP_DAYS),
}


def annual_yield(discount: np.ndarray) -> np.ndarray:
    """The compounded annual yield of a 91-day bill bought at bank discount ``discount``."""
    return (1.0 - discount * BILL_DAYS / 360.0) ** (-365.0 / BILL_DAYS) - 1.0


def _days(stamps: pd.Series) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(pd.to_datetime(stamps, utc=True))
    return index.tz_convert("UTC").tz_localize(None).astype("datetime64[ns]")


def _span_rates(
    stamps: pd.DatetimeIndex,
    rates: pd.Series,
    max_gap: int = MAX_GAP_DAYS,
    to_yearly: Callable[[np.ndarray], np.ndarray] | None = None,
) -> tuple[np.ndarray, np.ndarray] | str:
    """The rate's annual yield at the start of each span between consecutive
    ``stamps`` and the span's length in days, or why they are missing (the
    bill's discount rate unless ``to_yearly`` says how to read the quote)."""
    starts = stamps[:-1]
    span_days = np.clip(
        np.asarray((stamps[1:] - stamps[:-1]).total_seconds(), dtype=float) / 86400.0, 0.0, None
    )
    known = rates.copy()
    known.index = pd.DatetimeIndex(known.index).tz_localize(None).astype("datetime64[ns]")
    known = known[~known.index.duplicated(keep="last")].sort_index()
    if known.empty:
        return UNAVAILABLE
    paired = pd.merge_asof(
        pd.DataFrame({"day": starts.floor("D")}),
        pd.DataFrame({"day": known.index, "rate": known.to_numpy(), "seen": known.index}),
        on="day",
        direction="backward",
    )
    stale = paired["seen"].isna() | ((paired["day"] - paired["seen"]).dt.days > max_gap)
    if bool(stale.any()):
        return NOT_COVERED
    quoted = paired["rate"].to_numpy(dtype=float)
    if to_yearly is None:
        return annual_yield(quoted / 100.0), span_days
    return to_yearly(quoted), span_days


def span_cash(stamps: pd.Series, rates: pd.Series | None) -> np.ndarray | None:
    """What the bill paid over each span between consecutive ``stamps``;
    ``None`` when the rates are missing or do not cover every span's start."""
    if rates is None or rates.empty or len(stamps) < 2:
        return None
    paired = _span_rates(_days(stamps), rates)
    if isinstance(paired, str):
        return None
    yearly, span_days = paired
    return np.asarray((1.0 + yearly) ** (span_days / 365.0) - 1.0, dtype=float)


def excess_sharpe(frame: pd.DataFrame, rates: pd.Series, ppy: float) -> dict[str, Any]:
    """The Sharpe ratio of the returns in ``frame`` (``timestamp``, ``equity``)
    after the bill's rate over each return's days."""
    base = {"series": CASH.series, "label": CASH.label, "source_url": CASH.source_url}
    return _excess(frame, rates, ppy, base, NOTE, MAX_GAP_DAYS, None)


def local_excess_sharpe(
    frame: pd.DataFrame, rates: pd.Series, ppy: float, currency: str
) -> dict[str, Any]:
    """The Sharpe ratio of the returns in ``frame`` after the cash rate of the
    account's own ``currency`` (a key of ``LOCAL``); the values are cleaned
    first (numbers only, within the series' bounds)."""
    local = LOCAL[currency]
    asset = local.asset
    base = {
        "series": asset.series,
        "label": asset.label,
        "source_url": asset.source_url,
        "currency": currency,
    }
    index = pd.DatetimeIndex(pd.to_datetime(rates.index))
    values = pd.to_numeric(pd.Series(rates.to_numpy(), index=index), errors="coerce")
    numbers = values.to_numpy(dtype=float)
    low = asset.floor if asset.floor is not None else -math.inf
    high = asset.ceiling if asset.ceiling is not None else math.inf
    values = values[np.isfinite(numbers) & (numbers >= low) & (numbers <= high)].astype(float)
    if values.empty:
        return {"status": "NOT_MEASURED", "reason": UNAVAILABLE, **base}
    return _excess(frame, values, ppy, base, NOTE_LOCAL, local.max_gap, local.yearly)


def _excess(
    frame: pd.DataFrame,
    rates: pd.Series,
    ppy: float,
    base: dict[str, Any],
    note: str,
    max_gap: int,
    to_yearly: Callable[[np.ndarray], np.ndarray] | None,
) -> dict[str, Any]:
    stamps = _days(frame["timestamp"])
    equity = frame["equity"].to_numpy(dtype=float)
    if len(equity) < MIN_RETURNS + 1:
        return {"status": "NOT_MEASURED", "reason": TOO_FEW, **base}
    returns = equity[1:] / equity[:-1] - 1.0
    paired = _span_rates(stamps, rates, max_gap, to_yearly)
    if isinstance(paired, str):
        return {"status": "NOT_MEASURED", "reason": paired, **base}
    yearly, span_days = paired
    cash = (1.0 + yearly) ** (span_days / 365.0) - 1.0
    excess = returns - cash
    spread = float(excess.std(ddof=1))
    if not math.isfinite(spread) or spread <= 0:
        return {"status": "NOT_MEASURED", "reason": FLAT, **base}
    weights = span_days
    mean_rate = float(np.average(yearly, weights=weights)) if weights.sum() > 0 else 0.0
    sharpe = float(excess.mean() / spread * math.sqrt(ppy))
    years = float(weights.sum()) / 365.0
    strategy_yearly = (
        float((equity[-1] / equity[0]) ** (1.0 / years) - 1.0) if years > 0 else float("nan")
    )
    # A curve that barely moves makes the excess Sharpe a large negative number
    # that reads like a bug; the plain comparison says the same thing.
    below = (math.isfinite(strategy_yearly) and strategy_yearly < mean_rate) or (
        sharpe < BELOW_CASH_SHARPE
    )
    return {
        "status": "MEASURED",
        "note": note,
        **base,
        "sharpe_excess": measured(sharpe, note),
        "mean_rate": measured(mean_rate, note),
        "strategy_yearly": measured(strategy_yearly, "the strategy's compound return a year"),
        "below_cash": below,
    }


__all__ = [
    "LOCAL",
    "NOTE",
    "NOTE_LOCAL",
    "UNAVAILABLE",
    "annual_yield",
    "excess_sharpe",
    "local_excess_sharpe",
    "span_cash",
]
