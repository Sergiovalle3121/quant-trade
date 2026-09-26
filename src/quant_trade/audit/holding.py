"""Did the strategy do better than simply holding the market it trades?

A robot on the Nasdaq 100 that made 40 % in a year the index rose 50 % did
not add skill: it rode the market, with extra steps and extra risk. This
module puts the strategy's own closes beside the public closes of the market
its file names (``market.dominant_asset``) and reports, for both, the return,
the worst fall and the return per unit of risk (Sharpe ratio, leverage-free:
doubling the position doubles return and risk alike), plus how closely the
two moved (correlation) and how much the strategy moved per unit of market
move (beta).

Pairing. The two series are paired on the sparser of the two calendars: a
strategy that also moves on weekends is read on the market's trading days
(its weekend moves roll into Monday), a weekday strategy beside bitcoin on its
own days. The other side's last level on or before each day is taken.

Sharpe ratios are on those shared days only, so the strategy's figure here
(``strategy_sharpe_shared_days``) is not the report's headline Sharpe, which
is read per row of the upload.

Correlation and beta use Friday-to-Friday weekly returns of the paired
levels: a strategy's day ends at its last stamp (often broker time read as
UTC) while FRED closes at the market's own close, and that offset of up to a
day pulls daily correlation and beta toward zero.

One finding, as a question, never a class change: ``rides_the_market`` when
the two move together (weekly correlation at or above ``CLOSE_MOVE``) and the
strategy's Sharpe ratio is not clearly above holding's: the gap is less than
``EDGE_SE`` standard errors of the difference of two correlated Sharpe
ratios (Jobson and Korkie with Memmel's correction, on the weekly returns).
A gap inside the noise reads as "no clear edge", never as "worse". Figures
are MEASURED: the strategy's side from the upload, the market's from FRED's
public closes on the same dates, both named in the note.
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
#: Weekly returns needed for the correlation, beta and the Sharpe gap test.
MIN_WEEKS = 12
#: Weekly correlation at which the strategy "moves with" the market.
CLOSE_MOVE = 0.7
#: Standard errors the Sharpe gap must reach before the strategy "adds" something.
EDGE_SE = 2.0
#: A market close older than this before a strategy day is too stale to pair.
MAX_GAP_DAYS = 5

UNAVAILABLE = "the market's public closes could not be read when the report was made"
NOTE = (
    "the strategy's closes against the market's public closes (FRED) on the days both are "
    "seen (the sparser of the two calendars); Sharpe ratios on those days without "
    "subtracting a cash rate, annualised by the days observed; correlation and beta on "
    "Friday-to-Friday weekly returns"
)


def _drawdown(levels: np.ndarray) -> float:
    peaks = np.maximum.accumulate(levels)
    return float((levels / peaks - 1.0).min())


def _ratio(returns: np.ndarray) -> float | None:
    """Mean over standard deviation (ddof=1), per period; None for a flat series."""
    sd = float(returns.std(ddof=1))
    if not math.isfinite(sd) or sd <= 0:
        return None
    return float(returns.mean() / sd)


def _day_closes(frame: pd.DataFrame) -> pd.Series:
    stamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True))
    days = stamps.tz_convert("UTC").tz_localize(None).floor("D").astype("datetime64[ns]")
    equity = pd.Series(frame["equity"].to_numpy(dtype=float), index=days)
    closes = equity.groupby(level=0).last()
    return closes[closes > 0]


def _pair(strategy: pd.Series, market: pd.Series) -> pd.DataFrame:
    """Both levels on the sparser calendar, with the other side's last level on
    or before each day (a market close at most ``MAX_GAP_DAYS`` old)."""
    on_strategy = pd.merge_asof(
        pd.DataFrame({"day": strategy.index, "strategy": strategy.to_numpy()}),
        pd.DataFrame({"day": market.index, "market": market.to_numpy(), "seen": market.index}),
        on="day",
        direction="backward",
    ).dropna()
    on_strategy = on_strategy[(on_strategy["day"] - on_strategy["seen"]).dt.days <= MAX_GAP_DAYS]
    inside = market[(market.index >= strategy.index[0]) & (market.index <= strategy.index[-1])]
    on_market = pd.merge_asof(
        pd.DataFrame({"day": inside.index, "market": inside.to_numpy()}),
        pd.DataFrame({"day": strategy.index, "strategy": strategy.to_numpy()}),
        on="day",
        direction="backward",
    ).dropna()
    # The strategy's equity holds between its own points, so no gap limit on its side.
    chosen = on_market if len(on_market) <= len(on_strategy) else on_strategy
    return chosen[["day", "strategy", "market"]].reset_index(drop=True)


def _weekly(paired: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    levels = paired.set_index("day")[["strategy", "market"]].resample("W-FRI").last().dropna()
    returns = levels.pct_change().dropna()
    return returns["strategy"].to_numpy(dtype=float), returns["market"].to_numpy(dtype=float)


def sharpe_gap_se(s_ratio: float, m_ratio: float, correlation: float, periods: int) -> float:
    """Standard error of the difference of two per-period Sharpe ratios measured
    on the same ``periods`` (Jobson and Korkie, Memmel's correction)."""
    var = (
        2.0
        - 2.0 * correlation
        + 0.5 * (s_ratio**2 + m_ratio**2 - 2.0 * s_ratio * m_ratio * correlation**2)
    ) / periods
    return math.sqrt(max(var, 0.0))


def versus_holding(frame: pd.DataFrame, closes: pd.Series, asset: Asset) -> dict[str, Any]:
    """The strategy and simply holding ``asset`` over the same days."""
    base = {"asset": asset.key, "label": asset.label, "source_url": asset.source_url}
    strategy = _day_closes(frame)
    market = closes.copy()
    market.index = (
        pd.DatetimeIndex(market.index).tz_localize(None).floor("D").astype("datetime64[ns]")
    )
    market = market[~market.index.duplicated(keep="last")].sort_index()
    market = market[market > 0]
    if strategy.empty or market.empty:
        return {"status": "NOT_MEASURED", "reason": "no overlapping days", **base}
    paired = _pair(strategy, market)
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
    s_week, m_week = _weekly(paired)
    if len(s_week) < MIN_WEEKS:
        return {
            "status": "NOT_MEASURED",
            "reason": f"fewer than {MIN_WEEKS} weeks shared with the market's public closes",
            **base,
        }
    s_daily, m_daily = _ratio(s_ret), _ratio(m_ret)
    s_weekly, m_weekly = _ratio(s_week), _ratio(m_week)
    if s_daily is None or m_daily is None or s_weekly is None or m_weekly is None:
        return {"status": "NOT_MEASURED", "reason": "one of the two series never moves", **base}
    years = span / 365.25
    per_year, weeks_per_year = len(s_ret) / years, len(s_week) / years
    correlation = float(np.corrcoef(s_week, m_week)[0, 1])
    beta = float(np.cov(s_week, m_week, ddof=1)[0, 1] / m_week.var(ddof=1))
    se = sharpe_gap_se(s_weekly, m_weekly, correlation, len(s_week))
    gap_in_se = (s_weekly - m_weekly) / se if se > 0 else 0.0
    out: dict[str, Any] = {
        "status": "MEASURED",
        "note": NOTE,
        **base,
        "first": str(first.date()),
        "last": str(last.date()),
        "days": measured(len(s_ret), NOTE),
        "weeks": measured(len(s_week), NOTE),
        "strategy_return": measured(float(s_levels[-1] / s_levels[0] - 1.0), NOTE),
        "market_return": measured(float(m_levels[-1] / m_levels[0] - 1.0), NOTE),
        "strategy_drawdown": measured(_drawdown(s_levels), NOTE),
        "market_drawdown": measured(_drawdown(m_levels), NOTE),
        "strategy_sharpe_shared_days": measured(s_daily * math.sqrt(per_year), NOTE),
        "market_sharpe": measured(m_daily * math.sqrt(per_year), NOTE),
        "correlation": measured(correlation, NOTE),
        "beta": measured(beta, NOTE),
        "sharpe_gap_se": measured(se * math.sqrt(weeks_per_year), NOTE),
        "sharpe_gap_in_se": measured(float(gap_in_se), NOTE),
        "findings": [],
    }
    if correlation >= CLOSE_MOVE and gap_in_se < EDGE_SE:
        out["findings"].append("rides_the_market")
    return out


__all__ = ["CLOSE_MOVE", "EDGE_SE", "MIN_DAYS", "UNAVAILABLE", "sharpe_gap_se", "versus_holding"]
