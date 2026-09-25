"""Did the strategy do better than simply holding the market it trades?

A robot on the Nasdaq 100 that made 40 % in a year the index rose 50 % did
not add skill: it rode the market, with extra steps and extra risk. This
module puts the strategy's own daily closes beside the public closes of the
market its file names (``market.dominant_asset``) on the same days, and
reports, for both, the return, the worst fall and the return per unit of
risk (Sharpe ratio, leverage-free: doubling the position doubles return and
risk alike), plus how closely the two moved (correlation) and how much the
strategy moved per unit of market move (beta).

One finding, as a question, never a class change: ``rides_the_market`` when
the two move together (correlation at or above ``CLOSE_MOVE``) and the
strategy's Sharpe ratio is not at least ``SHARPE_EDGE`` above holding's. Figures are MEASURED:
the strategy's side from the upload, the market's from FRED's public closes
on the same dates, both named in the note.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.market import Asset
from quant_trade.audit.schema import measured

#: Days the two series must share before anything is compared.
MIN_DAYS = 60
#: Calendar span needed, so a few busy weeks do not stand for a strategy.
MIN_SPAN_DAYS = 90
#: Correlation of daily returns at which the strategy "moves with" the market.
CLOSE_MOVE = 0.7
#: Extra Sharpe the strategy needs over holding before it "adds" something.
SHARPE_EDGE = 0.1
#: A market close older than this before a strategy day is too stale to pair.
MAX_GAP_DAYS = 5

UNAVAILABLE = "the market's public closes could not be read when the report was made"
NOTE = (
    "the strategy's daily closes against the market's public closes (FRED) on the same "
    "days; Sharpe ratios without subtracting a cash rate, annualised by the days observed"
)


def _drawdown(levels: np.ndarray) -> float:
    peaks = np.maximum.accumulate(levels)
    return float((levels / peaks - 1.0).min())


def _sharpe(returns: np.ndarray, per_year: float) -> float | None:
    sd = float(returns.std(ddof=1))
    if not math.isfinite(sd) or sd <= 0:
        return None
    return float(returns.mean() / sd * math.sqrt(per_year))


def _day_closes(frame: pd.DataFrame) -> pd.Series:
    stamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True))
    days = stamps.tz_convert("UTC").tz_localize(None).floor("D").astype("datetime64[ns]")
    equity = pd.Series(frame["equity"].to_numpy(dtype=float), index=days)
    closes = equity.groupby(level=0).last()
    return closes[closes > 0]


def versus_holding(frame: pd.DataFrame, closes: pd.Series, asset: Asset) -> dict[str, Any]:
    """The strategy and simply holding ``asset`` over the same days."""
    base = {"asset": asset.key, "label": asset.label, "source_url": asset.source_url}
    strategy = _day_closes(frame)
    market = closes.copy()
    market.index = (
        pd.DatetimeIndex(market.index).tz_localize(None).floor("D").astype("datetime64[ns]")
    )
    market = market[~market.index.duplicated(keep="last")].sort_index()
    if strategy.empty or market.empty:
        return {"status": "NOT_MEASURED", "reason": "no overlapping days", **base}
    # Pair each strategy day with the market's last close on or before it.
    paired = pd.merge_asof(
        pd.DataFrame({"day": strategy.index, "strategy": strategy.to_numpy()}),
        pd.DataFrame({"day": market.index, "market": market.to_numpy(), "seen": market.index}),
        on="day",
        direction="backward",
    ).dropna()
    paired = paired[(paired["day"] - paired["seen"]).dt.days <= MAX_GAP_DAYS]
    if len(paired) < MIN_DAYS + 1:
        return {
            "status": "NOT_MEASURED",
            "reason": f"fewer than {MIN_DAYS} days shared with the market's public closes",
            **base,
        }
    first, last = paired["day"].iloc[0], paired["day"].iloc[-1]
    span = (last - first).days
    if span < MIN_SPAN_DAYS:
        return {
            "status": "NOT_MEASURED",
            "reason": f"the shared days span less than {MIN_SPAN_DAYS} calendar days",
            **base,
        }
    s_levels = paired["strategy"].to_numpy(dtype=float)
    m_levels = paired["market"].to_numpy(dtype=float)
    s_ret = s_levels[1:] / s_levels[:-1] - 1.0
    m_ret = m_levels[1:] / m_levels[:-1] - 1.0
    per_year = len(s_ret) / (span / 365.25)
    s_sharpe = _sharpe(s_ret, per_year)
    m_sharpe = _sharpe(m_ret, per_year)
    if s_sharpe is None or m_sharpe is None or float(m_ret.std(ddof=1)) <= 0:
        return {"status": "NOT_MEASURED", "reason": "one of the two series never moves", **base}
    correlation = float(np.corrcoef(s_ret, m_ret)[0, 1])
    beta = float(np.cov(s_ret, m_ret, ddof=1)[0, 1] / m_ret.var(ddof=1))
    out: dict[str, Any] = {
        "status": "MEASURED",
        "note": NOTE,
        **base,
        "first": str(first.date()),
        "last": str(last.date()),
        "days": measured(len(s_ret), NOTE),
        "strategy_return": measured(float(s_levels[-1] / s_levels[0] - 1.0), NOTE),
        "market_return": measured(float(m_levels[-1] / m_levels[0] - 1.0), NOTE),
        "strategy_drawdown": measured(_drawdown(s_levels), NOTE),
        "market_drawdown": measured(_drawdown(m_levels), NOTE),
        "strategy_sharpe": measured(s_sharpe, NOTE),
        "market_sharpe": measured(m_sharpe, NOTE),
        "correlation": measured(correlation, NOTE),
        "beta": measured(beta, NOTE),
        "findings": [],
    }
    if correlation >= CLOSE_MOVE and s_sharpe < m_sharpe + SHARPE_EDGE:
        out["findings"].append("rides_the_market")
    return out


__all__ = ["CLOSE_MOVE", "MIN_DAYS", "UNAVAILABLE", "versus_holding"]
