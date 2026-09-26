"""How the strategy did in calm markets and in turbulent ones.

A strategy that earns in quiet markets and gives it back when fear rises is a
different product from one that earns when others panic, even with the same
headline figures. This module splits the returns by the VIX (CBOE's measure of
how much the S&P 500 is expected to move over the next month, FRED's
``VIXCLS``, read at run time): *calm* while the VIX closed below
``TURBULENT_AT``, *turbulent* at or above it. 20 is close to the index's
long-run average; since 1990 it has closed at 20 or more on about a third of
the days.

Each return is placed by the VIX close of the last market day *before* the
day its stretch starts (at most ``MAX_GAP_DAYS`` old), so the regime was known
before the return happened. For each regime the report gives the share of the
time, the number of returns, the return per month compounded over that
regime's days only, and the Sharpe ratio annualised like the headline one.
The two mean returns are compared in Welch standard errors; a gap under
``CLEAR_GAP`` reads as "no clear difference", never as a finding. The VIX is a
US equity measure: for other markets it is a general gauge of fear, and the
note says so. Nothing here changes the class.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.market import VIX
from quant_trade.audit.schema import measured

#: VIX close at and above which a market counts as turbulent.
TURBULENT_AT = 20.0
#: Returns each regime needs before its figures are printed.
MIN_RETURNS = 20
#: Calendar days the whole history must cover.
MIN_SPAN_DAYS = 90
#: A VIX close older than this before a return's start is too stale to use.
MAX_GAP_DAYS = 5
#: Standard errors the gap in mean returns must reach to read as a difference.
CLEAR_GAP = 2.0
#: Average days in a month, for the monthly return.
MONTH_DAYS = 365.25 / 12
#: A spread below this is rounding noise on a flat series, not risk.
FLAT_SPREAD = 1e-12

NOTE = (
    "each return placed by the VIX close of the last market day before it starts (calm "
    "below 20, turbulent at 20 or above); return per month compounded over each regime's "
    "days; Sharpe annualised like the headline Sharpe; gap in mean returns in Welch "
    "standard errors"
)
UNAVAILABLE = "the VIX closes could not be read when the report was made"
NOT_COVERED = "the VIX closes do not cover the whole history"
SHORT = "the history covers fewer than 90 days"
FEW_CALM = "fewer than 20 returns in calm markets (VIX below 20)"
FEW_TURBULENT = "fewer than 20 returns in turbulent markets (VIX at 20 or above)"
ZERO = "the curve reaches zero"


def _days(stamps: pd.Series) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(pd.to_datetime(stamps, utc=True))
    return index.tz_convert("UTC").tz_localize(None).astype("datetime64[ns]")


def _side(returns: np.ndarray, days: np.ndarray, total_days: float, ppy: float) -> dict[str, Any]:
    regime_days = float(days.sum())
    growth = float(np.log1p(returns).sum())
    monthly = math.expm1(growth * MONTH_DAYS / regime_days) if regime_days > 0 else 0.0
    out: dict[str, Any] = {
        "returns": measured(int(len(returns)), NOTE),
        "time_share": measured(regime_days / total_days if total_days > 0 else 0.0, NOTE),
        "monthly_return": measured(monthly, NOTE),
    }
    spread = float(returns.std(ddof=1))
    if math.isfinite(spread) and spread > FLAT_SPREAD:
        out["sharpe"] = measured(float(returns.mean() / spread * math.sqrt(ppy)), NOTE)
    return out


def by_vix(frame: pd.DataFrame, vix: pd.Series, ppy: float) -> dict[str, Any]:
    """The returns in ``frame`` (``timestamp``, ``equity``) split by the VIX
    close known before each one started."""
    base = {
        "series": VIX.series,
        "label": VIX.label,
        "source_url": VIX.source_url,
        "turbulent_at": TURBULENT_AT,
    }
    stamps = _days(frame["timestamp"])
    equity = frame["equity"].to_numpy(dtype=float)
    if len(equity) < 2 or (stamps[-1] - stamps[0]).days < MIN_SPAN_DAYS:
        return {"status": "NOT_MEASURED", "reason": SHORT, **base}
    if bool((equity <= 0).any()):
        return {"status": "NOT_MEASURED", "reason": ZERO, **base}
    returns = equity[1:] / equity[:-1] - 1.0
    span_days = np.clip(
        np.asarray((stamps[1:] - stamps[:-1]).total_seconds(), dtype=float) / 86400.0, 0.0, None
    )
    known = vix.copy()
    known.index = pd.DatetimeIndex(known.index).tz_localize(None).astype("datetime64[ns]")
    known = known[~known.index.duplicated(keep="last")].sort_index()
    if known.empty:
        return {"status": "NOT_MEASURED", "reason": UNAVAILABLE, **base}
    # A close is known only after its day ends: a stretch starting on day D is
    # placed by the last close before D.
    paired = pd.merge_asof(
        pd.DataFrame({"day": stamps[:-1].floor("D")}),
        pd.DataFrame({"day": known.index, "vix": known.to_numpy(), "seen": known.index}),
        on="day",
        direction="backward",
        allow_exact_matches=False,
    )
    stale = paired["seen"].isna() | ((paired["day"] - paired["seen"]).dt.days > MAX_GAP_DAYS)
    if bool(stale.any()):
        return {"status": "NOT_MEASURED", "reason": NOT_COVERED, **base}
    turbulent = paired["vix"].to_numpy(dtype=float) >= TURBULENT_AT
    calm = ~turbulent
    if int(calm.sum()) < MIN_RETURNS:
        return {"status": "NOT_MEASURED", "reason": FEW_CALM, **base}
    if int(turbulent.sum()) < MIN_RETURNS:
        return {"status": "NOT_MEASURED", "reason": FEW_TURBULENT, **base}
    total_days = float(span_days.sum())
    out: dict[str, Any] = {
        "status": "MEASURED",
        "note": NOTE,
        **base,
        "first": str(stamps[0].date()),
        "last": str(stamps[-1].date()),
        "calm": _side(returns[calm], span_days[calm], total_days, ppy),
        "turbulent": _side(returns[turbulent], span_days[turbulent], total_days, ppy),
    }
    a, b = returns[calm], returns[turbulent]
    se = math.sqrt(float(a.var(ddof=1)) / len(a) + float(b.var(ddof=1)) / len(b))
    if math.isfinite(se) and se > FLAT_SPREAD:
        out["gap_in_se"] = measured(float((a.mean() - b.mean()) / se), NOTE)
    return out


__all__ = [
    "CLEAR_GAP",
    "NOTE",
    "TURBULENT_AT",
    "UNAVAILABLE",
    "by_vix",
]
