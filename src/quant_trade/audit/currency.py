"""The result in other currencies and after US inflation.

A trader in Mexico whose account is in dollars lives in pesos: when the peso
falls, a flat dollar curve made money in pesos, and when it rises, a winning
curve can lose. This module takes the dollar levels of the curve and converts
each one at the Federal Reserve's noon buying rate of that day (FRED's H.10
series: ``DEXMXUS`` for the peso, ``DEXUSEU`` for the euro and so on, read at
run time), then reports, per currency, the total return, the return a year
(only over a year or more of history) and the worst fall. A rate older than
``MAX_GAP_DAYS`` before a point leaves that currency out.

It also deflates the dollar result by US consumer prices (``CPIAUCNS``, not
seasonally adjusted, monthly): each point takes its own month's price level, or the latest month
published (at most ``MAX_CPI_GAP_DAYS`` old; the index comes out about two
weeks after its month ends). The deflator is US inflation only: FRED carries
no up-to-date consumer price index for most of the other currencies, so the
currency figures are before their own inflation, and the note says so.

It runs only when the account is in US dollars: when an imported report names
the currency (``USD``, or ``USC`` for a cent account, whose ratios are the same),
or when nothing names it, and then the note says the curve is read as dollars.
Nothing here changes the class.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.market import CPI, FX
from quant_trade.audit.schema import measured

#: Calendar days the history must cover.
MIN_SPAN_DAYS = 90
#: Calendar days before a return a year is shown.
MIN_YEAR_DAYS = 365
#: An exchange rate older than this before a point is too stale to use.
MAX_GAP_DAYS = 7
#: A consumer price index month older than this before a point is too stale.
MAX_CPI_GAP_DAYS = 75
#: Series quoted as US dollars per unit of the currency (the rest are units per dollar).
DOLLARS_PER_UNIT = frozenset({"DEXUSEU", "DEXUSUK"})
#: Account currencies read as dollars.
DOLLAR_CODES = frozenset({"USD", "USC", "USDT", "USDC"})
#: Characters kept of a named account currency.
MAX_CODE_CHARS = 8

NOTE = (
    "the dollar levels converted at the Federal Reserve's noon buying rate of each day "
    "(FRED H.10); return a year compounded over the calendar days, shown from one year "
    "of history; worst fall from a peak in that currency; before that currency's own "
    "inflation; a USDT or USDC account is read at one dollar per coin"
)
REAL_NOTE = (
    "the dollar levels divided by US consumer prices (FRED CPIAUCNS) of each point's "
    "month, or the latest month published; US inflation only"
)
ASSUMED_USD = "no currency is named in the file, so the curve is read as US dollars"
OTHER_CURRENCY = "the account is not in US dollars"
SHORT = "the history covers fewer than 90 days"
NOT_POSITIVE = "the curve reaches zero"
UNAVAILABLE = "the exchange rates could not be read when the report was made"
CPI_UNAVAILABLE = "US consumer prices could not be read when the report was made"
CPI_NOT_COVERED = "US consumer prices do not cover the whole history"


def _days(stamps: pd.Series) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(pd.to_datetime(stamps, utc=True))
    return index.tz_convert("UTC").tz_localize(None).astype("datetime64[ns]")


def _asof(stamps: pd.DatetimeIndex, series: pd.Series, max_gap: int) -> np.ndarray | None:
    """The series' last value on or before each stamp's day, or None when any
    is missing or older than ``max_gap`` days."""
    known = series.copy()
    known.index = pd.DatetimeIndex(known.index).tz_localize(None).astype("datetime64[ns]")
    known = known[~known.index.duplicated(keep="last")].sort_index()
    known = known[np.isfinite(known.to_numpy(dtype=float)) & (known.to_numpy(dtype=float) > 0)]
    if known.empty:
        return None
    paired = pd.merge_asof(
        pd.DataFrame({"day": stamps.floor("D")}),
        pd.DataFrame({"day": known.index, "value": known.to_numpy(), "seen": known.index}),
        on="day",
        direction="backward",
    )
    stale = paired["seen"].isna() | ((paired["day"] - paired["seen"]).dt.days > max_gap)
    if bool(stale.any()):
        return None
    return paired["value"].to_numpy(dtype=float)


def _figures(levels: np.ndarray, days: float, note: str) -> dict[str, Any]:
    total = float(levels[-1] / levels[0] - 1.0)
    out: dict[str, Any] = {
        "total_return": measured(total, note),
        "worst_fall": measured(float((levels / np.maximum.accumulate(levels) - 1.0).min()), note),
    }
    if days >= MIN_YEAR_DAYS:
        out["yearly_return"] = measured(float((1.0 + total) ** (365.0 / days) - 1.0), note)
    return out


def in_currencies(
    frame: pd.DataFrame,
    series: dict[str, pd.Series | None],
    account_currency: str | None = None,
) -> dict[str, Any]:
    """The curve in ``frame`` (``timestamp``, ``equity`` in dollars) in each
    currency of ``market.FX`` and after US inflation; ``series`` maps each
    FRED key (``fx_mxn``, ``cpi``) to its values, or None when unread."""
    code = (account_currency or "").strip().upper()[:MAX_CODE_CHARS] or None
    if code is not None and code not in DOLLAR_CODES:
        return {"status": "NOT_MEASURED", "reason": OTHER_CURRENCY, "account_currency": code}
    stamps = _days(frame["timestamp"])
    levels = frame["equity"].to_numpy(dtype=float)
    if len(levels) < 2 or (stamps[-1] - stamps[0]).days < MIN_SPAN_DAYS:
        return {"status": "NOT_MEASURED", "reason": SHORT}
    if not bool(np.all(np.isfinite(levels))) or bool((levels <= 0).any()):
        return {"status": "NOT_MEASURED", "reason": NOT_POSITIVE}
    days = float((stamps[-1] - stamps[0]).total_seconds()) / 86400.0
    currencies: list[dict[str, Any]] = []
    for asset in FX:
        rates = _rates(series.get(asset.key), stamps, MAX_GAP_DAYS)
        if rates is None:
            continue
        per_dollar = 1.0 / rates if asset.series in DOLLARS_PER_UNIT else rates
        currencies.append(
            {
                "code": asset.label,
                "series": asset.series,
                "source_url": asset.source_url,
                **_figures(levels * per_dollar, days, NOTE),
            }
        )
    out: dict[str, Any] = {
        "status": "MEASURED" if currencies else "NOT_MEASURED",
        "first": str(stamps[0].date()),
        "last": str(stamps[-1].date()),
        "dollars": _figures(levels, days, NOTE),
        "currencies": currencies,
        "note": NOTE,
    }
    if not currencies:
        out["reason"] = UNAVAILABLE
    if code is None:
        out["assumption"] = ASSUMED_USD
    out["real"] = _real(levels, stamps, days, series.get(CPI.key))
    if out["status"] != "MEASURED" and out["real"].get("status") == "MEASURED":
        out["status"] = "MEASURED"
        out.pop("reason", None)
    return out


def _rates(values: pd.Series | None, stamps: pd.DatetimeIndex, gap: int) -> np.ndarray | None:
    if values is None or values.empty:
        return None
    return _asof(stamps, values, gap)


def _real(
    levels: np.ndarray, stamps: pd.DatetimeIndex, days: float, cpi: pd.Series | None
) -> dict[str, Any]:
    if cpi is None or cpi.empty:
        return {"status": "NOT_MEASURED", "reason": CPI_UNAVAILABLE}
    # FRED dates each month on its first day, so a point takes its own month's
    # price level, or the latest published one (about two weeks after a month ends).
    prices = _asof(stamps, cpi, MAX_CPI_GAP_DAYS)
    if prices is None:
        return {"status": "NOT_MEASURED", "reason": CPI_NOT_COVERED}
    out: dict[str, Any] = {
        "status": "MEASURED",
        "series": CPI.series,
        "source_url": CPI.source_url,
    }
    out.update(_figures(levels / prices, days, REAL_NOTE))
    inflation = float(prices[-1] / prices[0] - 1.0)
    out["inflation"] = measured(inflation, REAL_NOTE)
    if days >= MIN_YEAR_DAYS and math.isfinite(inflation):
        out["yearly_inflation"] = measured(
            float((1.0 + inflation) ** (365.0 / days) - 1.0), REAL_NOTE
        )
    return out


def series_keys() -> list[str]:
    """The ``market.SERIES`` keys this module reads."""
    return [CPI.key, *(asset.key for asset in FX)]


__all__ = ["NOTE", "REAL_NOTE", "in_currencies", "series_keys"]
