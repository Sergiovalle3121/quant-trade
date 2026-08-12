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
dated that day placed it in the declared band, its identity warm-up had
completed, and the venue served a tradable bar. The panel deliberately retains
marks outside that opening universe, so signals consume the explicit
``eligible_to_open`` flag rather than inferring membership from row presence.
Nothing here needs to know today's coin list, which is the whole point.

**Capacity before cost.** Eligibility requires that the coin's own venue
turnover could plausibly absorb the order size. Aggregator volume is not used
for this: it sums wash-traded venues, and `docs/CRYPTO_LOWCAP_ANTIBIAS_PLAN.md`
classes it as evidence about the source rather than about liquidity.

Every weight at time t is a function of bars at or before t, enforced by the
truncation-invariance tests that cover the whole registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from quant_trade.data.panel import pivot_close
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text
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
REQUIRED_PANEL_COLUMNS = (
    "market_cap_usd",
    "cmc_rank",
    "venue_turnover_usd",
    "eligible_to_open",
    "tradable",
)

H4_REQUIRED_PANEL_COLUMNS = ("first_venue_bar_at", "left_censored")

TARGET_PORTFOLIO = "TARGET_PORTFOLIO"
FORCED_EXIT = "FORCED_EXIT"


def _require_columns(data: pd.DataFrame, extra: tuple[str, ...] = ()) -> None:
    """Fail with the reason rather than a KeyError from three frames down."""
    missing = [c for c in (*REQUIRED_PANEL_COLUMNS, *extra) if c not in data.columns]
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
    trailing = turnover.rolling(
        window,
        min_periods=min(window, max(2, window // 3)),
    ).median()
    liquid = trailing >= order_notional * turnover_multiple
    try:
        eligible_to_open = _pivot(data, "eligible_to_open").astype("boolean")
        tradable = _pivot(data, "tradable").astype("boolean")
    except (TypeError, ValueError) as exc:
        raise ValueError("eligible_to_open and tradable must contain booleans") from exc
    return liquid.fillna(False) & eligible_to_open.fillna(False) & tradable.fillna(False)


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
    trailing = turnover.rolling(
        window,
        min_periods=min(window, max(2, window // 3)),
    ).median()
    # Least liquid scores highest, unless the control band is requested.
    scores = trailing if liquid_band else -trailing
    selected = _top_n_mask(scores, eligible, top_n)
    close = pivot_close(data)
    return weights_to_long(_equal_weight(selected), rebalance=rebalance_mask(close.index, freq))


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

    base_eligible = _eligible(
        data, order_notional=order_notional, turnover_multiple=multiple, window=window
    )
    eligible = base_eligible.copy()
    death_trigger = pd.DataFrame(False, index=eligible.index, columns=eligible.columns, dtype=bool)
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
        death_trigger = ((~alive_by_rank) | collapsed).fillna(False)
        eligible = eligible & ~death_trigger

    # Among survivors, hold the largest by market cap so the basket is a
    # stable, low-turnover core rather than a rotating tail.
    selected = _top_n_mask(_pivot(data, "market_cap_usd"), eligible, top_n)
    close = pivot_close(data)
    annual = rebalance_mask(close.index, freq)
    targets = weights_to_long(_equal_weight(selected), rebalance=annual)
    targets["order_intent"] = TARGET_PORTFOLIO

    # H2 promises an exit when its death screen fires, not merely exclusion at
    # the following annual rebalance.  Simulate only the membership state needed
    # to emit sparse exits: annual targets replace the desired basket; between
    # them, a newly triggered held name receives a symbol-only zero target.
    # The evaluator interprets FORCED_EXIT as preserving every other position.
    if screen_off:
        return targets
    held: set[str] = set()
    forced_rows: list[dict[str, Any]] = []
    for timestamp in close.index:
        exiting = sorted(
            symbol
            for symbol in held
            if symbol in death_trigger.columns and bool(death_trigger.at[timestamp, symbol])
        )
        for symbol in exiting:
            forced_rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "target_weight": 0.0,
                    "order_intent": FORCED_EXIT,
                }
            )
            held.remove(symbol)
        if bool(annual.loc[timestamp]):
            held = set(selected.columns[selected.loc[timestamp].fillna(False)])
    if not forced_rows:
        return targets
    forced = pd.DataFrame(forced_rows)
    return (
        pd.concat([targets, forced], ignore_index=True)
        .sort_values(["timestamp", "symbol", "order_intent"])
        .reset_index(drop=True)
    )


@dataclass(frozen=True)
class FrozenCohort:
    """The exact H3 cohort chosen once, before either arm diverges."""

    decision_timestamp: str
    instrument_ids: tuple[str, ...]
    digest: str


def frozen_rebalance_cohort(
    data: pd.DataFrame, params: dict[str, Any] | None = None
) -> FrozenCohort:
    """Select H3's cohort once and return its canonical audit digest."""
    params = params or {}
    _require_columns(data)
    order_notional = float(params.get("order_notional_usd", DEFAULT_ORDER_NOTIONAL_USD))
    multiple = float(params.get("turnover_multiple", DEFAULT_TURNOVER_MULTIPLE))
    window = int(params.get("liquidity_window", DEFAULT_LIQUIDITY_WINDOW))
    top_n = int(params.get("top_n", 20))
    freq = str(params.get("rebalance_frequency", "annual"))
    if top_n < 1:
        raise ValueError("top_n must be >= 1")

    eligible = _eligible(
        data, order_notional=order_notional, turnover_multiple=multiple, window=window
    )
    selected = _top_n_mask(_pivot(data, "market_cap_usd"), eligible, top_n)
    close = pivot_close(data)
    mask = rebalance_mask(close.index, freq)
    decisions = [timestamp for timestamp in mask[mask].index if bool(selected.loc[timestamp].any())]
    if len(decisions) == 0:
        timestamp = ""
        instruments: tuple[str, ...] = ()
    else:
        first = decisions[0]
        timestamp = pd.Timestamp(first).isoformat()
        instruments = tuple(sorted(selected.columns[selected.loc[first].fillna(False)]))
    payload = {
        "decision_timestamp": timestamp,
        "instrument_ids": list(instruments),
        "selection_rule": "largest_market_cap_among_eligible_top_n",
        "top_n": top_n,
    }
    return FrozenCohort(
        decision_timestamp=timestamp,
        instrument_ids=instruments,
        digest=sha256_of_text(canonical_dumps(payload)),
    )


def annual_equal_weight_rebalance(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """H3: rebalance a fixed eligible basket to equal weight once a year.

    The whole hypothesis is that the *rebalancing itself* pays in a
    high-dispersion cross-section, so the comparison is against buy-and-hold of
    the identical names (``rebalance_once=True``), which emits one target at
    the first rebalance date and never trades again. Any difference between the
    two is then attributable to rebalancing and not to selection, which is what
    makes the test interpretable.

    ``freeze_cohort=False`` is reserved for the external equal-weight eligible
    benchmark.  It reselects the point-in-time eligible basket at every
    rebalance; H3 itself defaults to, and its control requires, the frozen path.
    """
    _require_columns(data)
    rebalance_once = bool(params.get("rebalance_once", False))
    freeze_cohort = bool(params.get("freeze_cohort", True))
    freq = str(params.get("rebalance_frequency", "annual"))
    close = pivot_close(data)
    mask = rebalance_mask(close.index, freq)

    if freeze_cohort:
        cohort = frozen_rebalance_cohort(data, params)
        selected = pd.DataFrame(False, index=close.index, columns=close.columns)
        if cohort.instrument_ids:
            selected.loc[:, list(cohort.instrument_ids)] = True
        weights = _equal_weight(selected)
        if cohort.decision_timestamp:
            cohort_timestamp = pd.Timestamp(cohort.decision_timestamp)
            mask = mask & (mask.index >= cohort_timestamp)
        else:
            mask = pd.Series(False, index=mask.index)
    else:
        order_notional = float(params.get("order_notional_usd", DEFAULT_ORDER_NOTIONAL_USD))
        multiple = float(params.get("turnover_multiple", DEFAULT_TURNOVER_MULTIPLE))
        window = int(params.get("liquidity_window", DEFAULT_LIQUIDITY_WINDOW))
        top_n = int(params.get("top_n", 20))
        if top_n < 1:
            raise ValueError("top_n must be >= 1")
        eligible = _eligible(
            data,
            order_notional=order_notional,
            turnover_multiple=multiple,
            window=window,
        )
        selected = _top_n_mask(_pivot(data, "market_cap_usd"), eligible, top_n)
        weights = _equal_weight(selected).reindex(
            index=close.index, columns=close.columns, fill_value=0.0
        )
    if rebalance_once:
        first = mask[mask].index[:1]
        mask = pd.Series(mask.index.isin(first), index=mask.index)
    result = weights_to_long(weights, rebalance=mask)
    result["order_intent"] = TARGET_PORTFOLIO
    if freeze_cohort:
        result.attrs["cohort_digest"] = cohort.digest
        result.attrs["cohort_instrument_ids"] = cohort.instrument_ids
        result.attrs["cohort_decision_timestamp"] = cohort.decision_timestamp
        result.attrs["cohort_mode"] = "frozen"
    else:
        result.attrs["cohort_mode"] = "dynamic_eligible"
    return result


def survival_duration(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """H4: hold the coins that have survived longest inside the band.

    Age is elapsed calendar time since the first venue bar known at that date.
    It therefore continues through a data gap and does not use entry into the
    top-1000 as a proxy for listing.  Histories that begin before collection are
    explicitly left-censored and excluded rather than assigned a flattering age.
    """
    _require_columns(data, H4_REQUIRED_PANEL_COLUMNS)
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
    age_rows = data[["timestamp", "symbol", "first_venue_bar_at", "left_censored"]].copy()
    age_rows["timestamp"] = pd.to_datetime(age_rows["timestamp"], utc=True, errors="coerce")
    age_rows["first_venue_bar_at"] = pd.to_datetime(
        age_rows["first_venue_bar_at"], utc=True, errors="coerce"
    )
    if age_rows[["timestamp", "first_venue_bar_at"]].isna().any().any():
        raise ValueError("H4 requires valid timestamp and first_venue_bar_at values")
    age_rows["age_days"] = (age_rows["timestamp"] - age_rows["first_venue_bar_at"]).dt.days
    if (age_rows["age_days"] < 0).any():
        raise ValueError("first_venue_bar_at cannot be later than the panel row")
    try:
        age_rows["left_censored"] = age_rows["left_censored"].astype("boolean")
    except (TypeError, ValueError) as exc:
        raise ValueError("left_censored must contain booleans") from exc
    age = age_rows.pivot(index="timestamp", columns="symbol", values="age_days").sort_index()
    censored = age_rows.pivot(
        index="timestamp", columns="symbol", values="left_censored"
    ).sort_index()
    if exclude_censored:
        eligible = eligible & ~censored.reindex_like(eligible).fillna(True)
    eligible = eligible & (age >= min_age_days).fillna(False)
    selected = _top_n_mask(age, eligible, top_n)
    close = pivot_close(data)
    weights = _equal_weight(selected).reindex(columns=pivot_close(data).columns, fill_value=0.0)
    return weights_to_long(weights, rebalance=rebalance_mask(close.index, freq))


__all__ = [
    "DEFAULT_LIQUIDITY_WINDOW",
    "DEFAULT_ORDER_NOTIONAL_USD",
    "DEFAULT_TURNOVER_MULTIPLE",
    "FORCED_EXIT",
    "FrozenCohort",
    "TARGET_PORTFOLIO",
    "annual_equal_weight_rebalance",
    "capacity_illiquidity",
    "death_avoidance",
    "frozen_rebalance_cohort",
    "survival_duration",
]
