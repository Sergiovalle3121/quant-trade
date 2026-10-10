"""How a monthly track record did through widely recorded market falls.

An investor's first question after the calendar table is "what happened in
2008, in March 2020, in 2022?". This module takes a fixed list of calendar
windows, each the months from peak to trough of a fall that is on the public
record (US equities for the equity windows, bitcoin for the crypto one), and
for every window the record covers in full reports the fund's compounded
return and, when the file carries a benchmark, the benchmark's over the same
months. The windows are fixed in advance, never fitted to the file, and no
market data is bundled: only the dates.

It also reports the worst and best 12-month return and the share of rolling
12-month windows that ended positive.

One finding, as a question: with a benchmark and at least two covered
windows, ``fell_more_in_crises`` when the fund did worse than its benchmark
in two thirds or more of them. No red flag and no class change. Every
figure is MEASURED from the uploaded series.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.market import asset_of
from quant_trade.audit.schema import measured


@dataclass(frozen=True)
class Window:
    key: str
    first: str  # first month, "YYYY-MM"
    last: str  # last month, inclusive


#: Peak-to-trough months of widely recorded falls, oldest first.
WINDOWS: tuple[Window, ...] = (
    Window("dotcom", "2000-09", "2002-09"),
    Window("gfc", "2007-11", "2009-02"),
    Window("euro", "2011-05", "2011-09"),
    Window("china_oil", "2015-06", "2016-02"),
    Window("late_2018", "2018-10", "2018-12"),
    Window("covid", "2020-02", "2020-03"),
    Window("rates_2022", "2022-01", "2022-09"),
    Window("crypto_2022", "2021-11", "2022-12"),
)


@dataclass(frozen=True)
class MarketMove:
    index: str
    change: float  # month-end close before the window to the last month's close
    source_url: str


#: What public indices did over each window, for context beside the file's own
#: figures: a dozen fixed historical facts (how far each index fell over the
#: window), worked out once from the month-end levels FRED shows and cited with
#: those pages, never a data feed. No index series is read at run time or shown
#: beyond these figures (S&P Dow Jones Indices, Nasdaq and Coinbase do not allow
#: their data to be reproduced without permission; see ``market.ASSETS``). They
#: never come from the upload and never enter a finding or the class. The S&P 500
#: series on FRED starts in 2016, so older windows show the Nasdaq Composite only.
MARKET_AS_OF = "2026-09-25"
_SP500 = "https://fred.stlouisfed.org/series/SP500"
_NASDAQ = "https://fred.stlouisfed.org/series/NASDAQCOM"
_BITCOIN = "https://fred.stlouisfed.org/series/CBBTCUSD"
MARKET: dict[str, tuple[MarketMove, ...]] = {
    "dotcom": (MarketMove("Nasdaq Composite", -0.7214, _NASDAQ),),
    "gfc": (MarketMove("Nasdaq Composite", -0.5181, _NASDAQ),),
    "euro": (MarketMove("Nasdaq Composite", -0.1594, _NASDAQ),),
    "china_oil": (MarketMove("Nasdaq Composite", -0.1010, _NASDAQ),),
    "late_2018": (
        MarketMove("S&P 500", -0.1397, _SP500),
        MarketMove("Nasdaq Composite", -0.1754, _NASDAQ),
    ),
    "covid": (
        MarketMove("S&P 500", -0.1987, _SP500),
        MarketMove("Nasdaq Composite", -0.1585, _NASDAQ),
    ),
    "rates_2022": (
        MarketMove("S&P 500", -0.2477, _SP500),
        MarketMove("Nasdaq Composite", -0.3240, _NASDAQ),
    ),
    "crypto_2022": (MarketMove("Bitcoin (Coinbase)", -0.7305, _BITCOIN),),
}
#: The market each window's fall belongs to: the class of the public index
#: beside it in ``MARKET`` (US equities for the S&P 500 and the Nasdaq,
#: crypto for bitcoin).
WINDOW_MARKET: dict[str, str] = {
    "dotcom": "us_equity",
    "gfc": "us_equity",
    "euro": "us_equity",
    "china_oil": "us_equity",
    "late_2018": "us_equity",
    "covid": "us_equity",
    "rates_2022": "us_equity",
    "crypto_2022": "crypto",
}
#: The class of each market ``market.asset_of`` recognises in a symbol name.
_ASSET_MARKET: dict[str, str] = {
    "sp500": "us_equity",
    "nasdaq100": "us_equity",
    "bitcoin": "crypto",
}


#: Metal codes quoted against a currency (``XAUUSD``), a market of their own.
_METALS = frozenset({"XAU", "XAG", "XPT", "XPD"})


def symbol_market(name: str) -> str | None:
    """The market one symbol name trades, with the readings the audit already
    uses: ``market.asset_of`` for US equity indices and bitcoin, and the
    currency pairs ``engine.fx_pair`` recognises (``EURUSD.m`` is ``fx``);
    a metal against a currency is ``metal``. ``None`` when the name says
    nothing certain (a stock, another index, another coin)."""
    # Imported here: the engine imports this module.
    from quant_trade.audit.engine import FX_CURRENCIES

    text = str(name).rsplit(":", 1)[-1]
    asset = asset_of(text)
    if asset is not None and asset.key in _ASSET_MARKET:
        return _ASSET_MARKET[asset.key]
    pair = "".join(ch for ch in text.upper() if ch.isalnum())[:6]
    if len(pair) == 6 and pair[3:] in FX_CURRENCIES:
        if pair[:3] in FX_CURRENCIES:
            return "fx"
        if pair[:3] in _METALS:
            return "metal"
    return None


def traded_markets(symbols: Iterable[str]) -> set[str] | None:
    """The markets the named symbols trade, or ``None`` when one of them is not
    certain: the crises of other markets are left out only when every symbol
    is known (``AUDUSD`` and ``EURUSD`` trade no US equities and no bitcoin)."""
    found: set[str] = set()
    for name in symbols:
        market = symbol_market(name)
        if market is None:
            return None
        found.add(market)
    return found


#: Months of rolling windows for the worst and best stretch.
ROLLING = 12
#: Share of covered windows in which trailing the benchmark is a finding.
WORSE_SHARE = 2 / 3
MIN_WINDOWS = 2
#: A curve starting this close to a month's start, or ending this close to
#: its end, counts that month in full.
EDGE_WEEK_DAYS = 7
#: A curve that never moves this far from its start has nothing to show.
FLAT_CURVE = 0.001

NOTE = (
    "fixed calendar windows of widely recorded market falls; the fund's months "
    "compounded over each window it covers in full"
)
CURVE_NOTE = (
    "fixed calendar windows of widely recorded market falls; the curve's month-end "
    "returns compounded over each window it covers in full"
)


def _by_month(series: pd.Series) -> pd.Series:
    stamps = pd.DatetimeIndex(series.index)
    if stamps.tz is not None:
        stamps = stamps.tz_convert("UTC").tz_localize(None)
    return pd.Series(series.to_numpy(dtype=float), index=stamps.to_period("M"))


def _compound(values: np.ndarray) -> float:
    return float(np.prod(1.0 + values) - 1.0)


def crisis_review(fund: pd.Series, benchmark: pd.Series | None = None) -> dict[str, Any]:
    """The fund's return through each covered window, and its 12-month extremes."""
    months = _by_month(fund)
    index = _by_month(benchmark) if benchmark is not None else None
    rows: list[dict[str, Any]] = []
    for window in WINDOWS:
        span = pd.period_range(window.first, window.last, freq="M")
        if not span.isin(months.index).all():
            continue
        row: dict[str, Any] = {
            "key": window.key,
            "first": window.first,
            "last": window.last,
            "fund": measured(_compound(months.loc[span].to_numpy())),
        }
        if index is not None and span.isin(index.index).all():
            row["benchmark"] = measured(_compound(index.loc[span].to_numpy()))
        rows.append(row)
    review: dict[str, Any] = {"status": "MEASURED", "note": NOTE, "windows": rows, "findings": []}
    values = months.to_numpy(dtype=float)
    if len(values) >= 2 * ROLLING:
        wealth = np.cumprod(1.0 + values)
        start = np.concatenate([[1.0], wealth[:-ROLLING]])
        rolling = wealth[ROLLING - 1 :] / start[: len(wealth) - ROLLING + 1] - 1.0
        review["worst_12m"] = measured(float(rolling.min()))
        review["best_12m"] = measured(float(rolling.max()))
        review["positive_12m"] = measured(float((rolling > 0).mean()))
    compared = [row for row in rows if "benchmark" in row]
    if len(compared) >= MIN_WINDOWS:
        worse = sum(1 for row in compared if row["fund"]["value"] < row["benchmark"]["value"])
        review["worse_than_benchmark"] = measured(worse)
        review["compared"] = measured(len(compared))
        if worse >= WORSE_SHARE * len(compared):
            review["findings"].append("fell_more_in_crises")
    return review


def curve_months(frame: pd.DataFrame, *, from_trades: bool = False) -> pd.Series:
    """Month-end returns of a dated equity curve of any frequency.

    On a curve rebuilt from trades a month with no point carries the previous
    level (nothing closed that month). On an uploaded curve it stays missing,
    so a hole in the data never covers a window. The first month counts when
    the curve starts in its first week, the last when it reaches its final
    week: a window is never covered by a month the curve saw only in part."""
    equity = frame.set_index("timestamp")["equity"].astype(float)
    stamps = pd.DatetimeIndex(equity.index)
    if stamps.tz is not None:
        stamps = stamps.tz_convert("UTC").tz_localize(None)
    equity = pd.Series(equity.to_numpy(), index=stamps).sort_index()
    if len(equity) < 2:
        return pd.Series(dtype=float)
    first = equity.index[0]
    if first.day <= EDGE_WEEK_DAYS:
        # The first point stands in for the previous month's close.
        opening = first.normalize().replace(day=1) - pd.Timedelta(days=1)
        equity = pd.concat([pd.Series([equity.iloc[0]], index=[opening]), equity])
    month_end = equity.resample("ME").last()
    if from_trades:
        month_end = month_end.ffill()
    if equity.index[-1] < month_end.index[-1] - pd.Timedelta(days=EDGE_WEEK_DAYS):
        month_end = month_end.iloc[:-1]
    returns = month_end / month_end.shift(1) - 1.0
    return returns.iloc[1:].dropna()


def curve_crises(
    frame: pd.DataFrame, benchmark: pd.Series | None = None, *, from_trades: bool = False
) -> dict[str, Any]:
    """The crisis windows for a backtest or trade history's equity curve;
    NOT_MEASURED when the curve covers none of them in full."""
    months = curve_months(frame, from_trades=from_trades)
    if months.empty:
        return {"status": "NOT_MEASURED", "reason": "the curve is shorter than two months"}
    if (months <= -1.0).any():
        return {"status": "NOT_MEASURED", "reason": "the curve has no usable month-end levels"}
    equity = frame["equity"].astype(float).to_numpy()
    if equity[0] > 0 and float(np.abs(equity / equity[0] - 1.0).max()) < FLAT_CURVE:
        return {"status": "NOT_MEASURED", "reason": "the curve never moves 0.1 % from its start"}
    review = crisis_review(months, benchmark)
    review["note"] = CURVE_NOTE
    if not review["windows"]:
        return {
            "status": "NOT_MEASURED",
            "reason": "the curve covers none of the dated market falls in full",
        }
    if from_trades:
        stamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True))
        traded = set(stamps.tz_convert("UTC").tz_localize(None).to_period("M")[1:])
        for row in review["windows"]:
            span = pd.period_range(row["first"], row["last"], freq="M")
            if not traded.intersection(span):
                row["no_trades"] = True
    return review


__all__ = [
    "MARKET",
    "MARKET_AS_OF",
    "WINDOWS",
    "WINDOW_MARKET",
    "MarketMove",
    "Window",
    "crisis_review",
    "curve_crises",
    "curve_months",
    "symbol_market",
    "traded_markets",
]
