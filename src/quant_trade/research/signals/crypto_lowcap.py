"""The four pre-registered low/mid-cap crypto hypotheses.

Each implements exactly one sealed declaration under
``data/experiments/crypto_lowcap_2026_08/``; the hypothesis text, the
refutation condition and the trial budget live in the seal, not here.

Three constraints shape all four, and none of them is a style choice:

**Annual rebalancing.** The selection gate caps total turnover at 3.0 over the
test window. Against a 2.69-year holdout that is 1.11x/year, so anything above
roughly one full rebalance per year fails on turnover before its returns are
examined. Every signal here rebalances in January and not otherwise.

**Point-in-time membership.** A coin is eligible on a date only if the snapshot
dated that day contained it and a venue served a bar for it. The panel already
enforces this by construction — rows exist only where both held — so a pivot
leaves NaN outside membership and NaN becomes zero weight. Nothing here needs
to know today's coin list, which is the whole point.

**Capacity before cost.** Eligibility requires that the coin's own venue
turnover could plausibly absorb the order size. Aggregator volume is not used
for this: it sums wash-traded venues, and `docs/CRYPTO_LOWCAP_ANTIBIAS_PLAN.md`
classes it as evidence about the source rather than about liquidity.

Every weight at time t is a function of bars at or before t, enforced by the
truncation-invariance tests that cover the whole registry.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_trade.data.panel import pivot_close
from quant_trade.research.signals.base import rebalance_mask, weights_to_long

#: Order size the capacity screen is applied at, matching the cost model's
#: calibration and the capital this research is for. ASSUMPTION, declared.
DEFAULT_ORDER_NOTIONAL_USD = 1_000.0

#: A coin's own venue turnover must exceed this multiple of the order size for
#: the order to be plausible without moving the market. The measured cost model
#: prices the book directly; this is the coarser daily-bar screen that runs
#: before it. ASSUMPTION, declared.
DEFAULT_TURNOVER_MULTIPLE = 50.0

#: Trailing window for turnover, long enough that one quiet week cannot eject a
#: coin and short enough to notice a venue winding a listing down.
DEFAULT_LIQUIDITY_WINDOW = 90


#: Columns these signals need beyond canonical OHLCV. They come from the
#: point-in-time universe join in `quant_trade.data.crypto_panel`, and a plain
#: price panel simply does not carry them.
REQUIRED_PANEL_COLUMNS = ("market_cap_usd", "cmc_rank", "venue_turnover_usd")


def _require_columns(data: pd.DataFrame) -> None:
    """Fail with the reason rather than a KeyError from three frames down."""
    missing = [c for c in REQUIRED_PANEL_COLUMNS if c not in data.columns]
    if missing:
        raise ValueError(
            f"crypto low-cap signals require the point-in-time columns {missing} "
            "which a plain OHLCV panel does not carry; build the panel with "
            "quant_trade.data.crypto_panel.build_panel"
        )


def _pivot(data: pd.DataFrame, column: str) -> pd.DataFrame:
    return data.pivot(index="timestamp", columns="symbol", values=column).sort_index()


def _eligible(
    data: pd.DataFrame,
    *,
    order_notional: float,
    turnover_multiple: float,
    window: int,
) -> pd.DataFrame:
    """Boolean mask of coins tradable on each date, using only past bars.

    Two conditions: the coin is in the point-in-time panel that day, and its
    trailing median venue turnover clears the order size by the declared
    multiple. The median is deliberate — a mean lets one spike from a listing
    event or a wash-trading burst carry a coin for months.
    """
    turnover = _pivot(data, "venue_turnover_usd")
    trailing = turnover.rolling(window, min_periods=max(2, window // 3)).median()
    liquid = trailing >= order_notional * turnover_multiple
    present = _pivot(data, "close").notna()
    return liquid.fillna(False) & present


def _equal_weight(selected: pd.DataFrame) -> pd.DataFrame:
    counts = selected.sum(axis=1)
    weights = selected.astype(float).div(counts.where(counts > 0), axis=0)
    return weights.fillna(0.0)


def _top_n_mask(scores: pd.DataFrame, eligible: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """Per-date mask of the ``top_n`` highest scores among eligible names."""
    masked = scores.where(eligible)
    ranks = masked.rank(axis=1, ascending=False, method="first")
    return (ranks <= top_n) & eligible


def capacity_illiquidity(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """H1: hold the least-liquid coins that are still tradable at our size.

    The premium, if it exists, is compensation for sitting where professional
    capital structurally cannot: 25% of micro books could not fill $10,000 at
    any price. So the score is *inverse* capacity — smallest venue turnover
    first — floored by the eligibility screen so the portfolio never holds a
    coin it could not have bought.

    ``liquid_band=True`` inverts the selection to the most liquid eligible
    coins. That is not a second strategy; it is the control the sealed
    refutation is written against, and it must be run with identical
    parameters or the comparison proves nothing.
    """
    _require_columns(data)
    top_n = int(params.get("top_n", 20))
    order_notional = float(params.get("order_notional_usd", DEFAULT_ORDER_NOTIONAL_USD))
    multiple = float(params.get("turnover_multiple", DEFAULT_TURNOVER_MULTIPLE))
    window = int(params.get("liquidity_window", DEFAULT_LIQUIDITY_WINDOW))
    liquid_band = bool(params.get("liquid_band", False))
    freq = str(params.get("rebalance_frequency", "annual"))
    if top_n < 1:
        raise ValueError("top_n must be >= 1")

    eligible = _eligible(
        data, order_notional=order_notional, turnover_multiple=multiple, window=window
    )
    turnover = _pivot(data, "venue_turnover_usd")
    trailing = turnover.rolling(window, min_periods=max(2, window // 3)).median()
    # Least liquid scores highest, unless the control band is requested.
    scores = trailing if liquid_band else -trailing
    selected = _top_n_mask(scores, eligible, top_n)
    close = pivot_close(data)
    return weights_to_long(
        _equal_weight(selected), rebalance=rebalance_mask(close.index, freq)
    )


def death_avoidance(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """H2: hold the universe minus the names that look like they are dying.

    Not a winner-picking signal. It starts from an equal-weight basket of
    everything eligible and removes names showing the two pre-death signals the
    panel can actually observe:

    - **rank decay**: the coin's rank has worsened by more than a declared
      number of places against its own level a year ago;
    - **turnover collapse**: trailing venue turnover has fallen below a
      declared fraction of its own longer-run median.

    Both are relative to the coin's own history, so neither smuggles in a
    cross-sectional judgement about which coins are good.

    ``screen_off=True`` disables both screens, producing the unscreened basket
    the sealed refutation compares against.
    """
    _require_columns(data)
    order_notional = float(params.get("order_notional_usd", DEFAULT_ORDER_NOTIONAL_USD))
    multiple = float(params.get("turnover_multiple", DEFAULT_TURNOVER_MULTIPLE))
    window = int(params.get("liquidity_window", DEFAULT_LIQUIDITY_WINDOW))
    rank_lookback = int(params.get("rank_lookback_days", 365))
    max_rank_decay = float(params.get("max_rank_decay", 300.0))
    turnover_collapse = float(params.get("turnover_collapse_ratio", 0.25))
    long_window = int(params.get("long_liquidity_window", 365))
    top_n = int(params.get("top_n", 20))
    screen_off = bool(params.get("screen_off", False))
    freq = str(params.get("rebalance_frequency", "annual"))

    eligible = _eligible(
        data, order_notional=order_notional, turnover_multiple=multiple, window=window
    )
    if not screen_off:
        rank = _pivot(data, "cmc_rank")
        decay = rank - rank.shift(rank_lookback)
        # A coin with no rank a year ago has not demonstrated decay; absence of
        # evidence is not evidence of death, so it stays until it says otherwise.
        alive_by_rank = ~(decay > max_rank_decay).fillna(False)

        turnover = _pivot(data, "venue_turnover_usd")
        short = turnover.rolling(window, min_periods=max(2, window // 3)).median()
        long = turnover.rolling(long_window, min_periods=window).median()
        collapsed = (short < long * turnover_collapse).fillna(False)
        eligible = eligible & alive_by_rank & ~collapsed

    # Among survivors, hold the largest by market cap so the basket is a
    # stable, low-turnover core rather than a rotating tail.
    selected = _top_n_mask(_pivot(data, "market_cap_usd"), eligible, top_n)
    close = pivot_close(data)
    return weights_to_long(
        _equal_weight(selected), rebalance=rebalance_mask(close.index, freq)
    )


def annual_equal_weight_rebalance(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """H3: rebalance a fixed eligible basket to equal weight once a year.

    The whole hypothesis is that the *rebalancing itself* pays in a
    high-dispersion cross-section, so the comparison is against buy-and-hold of
    the identical names (``rebalance_once=True``), which emits one target at
    the first rebalance date and never trades again. Any difference between the
    two is then attributable to rebalancing and not to selection, which is what
    makes the test interpretable.
    """
    _require_columns(data)
    order_notional = float(params.get("order_notional_usd", DEFAULT_ORDER_NOTIONAL_USD))
    multiple = float(params.get("turnover_multiple", DEFAULT_TURNOVER_MULTIPLE))
    window = int(params.get("liquidity_window", DEFAULT_LIQUIDITY_WINDOW))
    top_n = int(params.get("top_n", 20))
    rebalance_once = bool(params.get("rebalance_once", False))
    freq = str(params.get("rebalance_frequency", "annual"))

    eligible = _eligible(
        data, order_notional=order_notional, turnover_multiple=multiple, window=window
    )
    selected = _top_n_mask(_pivot(data, "market_cap_usd"), eligible, top_n)
    weights = _equal_weight(selected)
    close = pivot_close(data)
    mask = rebalance_mask(close.index, freq)
    if rebalance_once:
        first = mask[mask].index[:1]
        mask = pd.Series(mask.index.isin(first), index=mask.index)
    return weights_to_long(weights, rebalance=mask)


def survival_duration(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """H4: hold the coins that have survived longest inside the band.

    Age is counted in observed bars since the coin first appeared in the panel,
    so it is a within-panel measure and is **left-censored**: a coin already
    alive on the first date has an unknown true age. Censored coins are
    excluded rather than credited with the age they happen to show, because
    crediting them would rank the panel's opening cohort above everything that
    joined later purely as an artifact of when the window starts.
    """
    _require_columns(data)
    order_notional = float(params.get("order_notional_usd", DEFAULT_ORDER_NOTIONAL_USD))
    multiple = float(params.get("turnover_multiple", DEFAULT_TURNOVER_MULTIPLE))
    window = int(params.get("liquidity_window", DEFAULT_LIQUIDITY_WINDOW))
    min_age_days = int(params.get("min_age_days", 730))
    top_n = int(params.get("top_n", 20))
    exclude_censored = bool(params.get("exclude_left_censored", True))
    freq = str(params.get("rebalance_frequency", "annual"))

    eligible = _eligible(
        data, order_notional=order_notional, turnover_multiple=multiple, window=window
    )
    present = _pivot(data, "close").notna()
    age = present.cumsum().where(present)
    if exclude_censored:
        censored = present.iloc[0]
        age = age.loc[:, ~censored.fillna(False)] if censored.any() else age
        eligible = eligible.reindex(columns=age.columns, fill_value=False)
        present = present.reindex(columns=age.columns, fill_value=False)
    eligible = eligible & (age >= min_age_days).fillna(False)
    selected = _top_n_mask(age, eligible, top_n)
    close = pivot_close(data)
    weights = _equal_weight(selected).reindex(
        columns=pivot_close(data).columns, fill_value=0.0
    )
    return weights_to_long(weights, rebalance=rebalance_mask(close.index, freq))


__all__ = [
    "DEFAULT_LIQUIDITY_WINDOW",
    "DEFAULT_ORDER_NOTIONAL_USD",
    "DEFAULT_TURNOVER_MULTIPLE",
    "annual_equal_weight_rebalance",
    "capacity_illiquidity",
    "death_avoidance",
    "survival_duration",
]
