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
Nothing here changes the class.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.market import CASH
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


def annual_yield(discount: np.ndarray) -> np.ndarray:
    """The compounded annual yield of a 91-day bill bought at bank discount ``discount``."""
    return (1.0 - discount * BILL_DAYS / 360.0) ** (-365.0 / BILL_DAYS) - 1.0


def _days(stamps: pd.Series) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(pd.to_datetime(stamps, utc=True))
    return index.tz_convert("UTC").tz_localize(None).astype("datetime64[ns]")


def excess_sharpe(frame: pd.DataFrame, rates: pd.Series, ppy: float) -> dict[str, Any]:
    """The Sharpe ratio of the returns in ``frame`` (``timestamp``, ``equity``)
    after the bill's rate over each return's days."""
    base = {"series": CASH.series, "label": CASH.label, "source_url": CASH.source_url}
    stamps = _days(frame["timestamp"])
    equity = frame["equity"].to_numpy(dtype=float)
    if len(equity) < MIN_RETURNS + 1:
        return {"status": "NOT_MEASURED", "reason": TOO_FEW, **base}
    returns = equity[1:] / equity[:-1] - 1.0
    starts = stamps[:-1]
    span_days = np.asarray((stamps[1:] - stamps[:-1]).total_seconds(), dtype=float) / 86400.0
    known = rates.copy()
    known.index = pd.DatetimeIndex(known.index).tz_localize(None).astype("datetime64[ns]")
    known = known[~known.index.duplicated(keep="last")].sort_index()
    if known.empty:
        return {"status": "NOT_MEASURED", "reason": UNAVAILABLE, **base}
    paired = pd.merge_asof(
        pd.DataFrame({"day": starts.floor("D")}),
        pd.DataFrame({"day": known.index, "rate": known.to_numpy(), "seen": known.index}),
        on="day",
        direction="backward",
    )
    stale = paired["seen"].isna() | ((paired["day"] - paired["seen"]).dt.days > MAX_GAP_DAYS)
    if bool(stale.any()):
        return {"status": "NOT_MEASURED", "reason": NOT_COVERED, **base}
    yearly = annual_yield(paired["rate"].to_numpy(dtype=float) / 100.0)
    cash = (1.0 + yearly) ** (np.clip(span_days, 0.0, None) / 365.0) - 1.0
    excess = returns - cash
    spread = float(excess.std(ddof=1))
    if not math.isfinite(spread) or spread <= 0:
        return {"status": "NOT_MEASURED", "reason": FLAT, **base}
    weights = np.clip(span_days, 0.0, None)
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
        "note": NOTE,
        **base,
        "sharpe_excess": measured(sharpe, NOTE),
        "mean_rate": measured(mean_rate, NOTE),
        "strategy_yearly": measured(strategy_yearly, "the strategy's compound return a year"),
        "below_cash": below,
    }


__all__ = ["NOTE", "UNAVAILABLE", "annual_yield", "excess_sharpe"]
