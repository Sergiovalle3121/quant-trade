"""Tests for the four sealed low/mid-cap crypto hypotheses.

The invariant that matters most is truncation invariance: weights on date t
must be identical whether or not the panel contains anything after t. On a
panel built from a point-in-time universe it is easy to violate accidentally,
because membership itself changes over time and a careless pivot leaks it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.research.signals.base import rebalance_mask
from quant_trade.research.signals.crypto_lowcap import (
    FORCED_EXIT,
    annual_equal_weight_rebalance,
    capacity_illiquidity,
    death_avoidance,
    frozen_rebalance_cohort,
    survival_duration,
)
from quant_trade.research.strategy_registry import get_research_signal_model

SIGNALS = (
    capacity_illiquidity,
    death_avoidance,
    annual_equal_weight_rebalance,
    survival_duration,
)


def _panel(
    n_days: int = 900,
    n_symbols: int = 12,
    seed: int = 7,
    start: str = "2019-01-01",
    turnover_scale: float = 1e6,
) -> pd.DataFrame:
    """A crypto-shaped panel: staggered listings, deaths, dispersed turnover."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, periods=n_days, freq="D", tz="UTC")
    rows = []
    for i in range(n_symbols):
        # staggered entry and, for some, an early death
        first = 0 if i < 4 else int(rng.integers(1, n_days // 3))
        last = n_days if i % 5 else int(rng.integers(n_days // 2, n_days))
        close = 10 * np.cumprod(1 + rng.normal(0.0003, 0.05, n_days))
        turnover = turnover_scale * (i + 1) * np.exp(rng.normal(0, 0.3, n_days))
        for j in range(first, last):
            price = float(close[j])
            rows.append(
                {
                    "timestamp": dates[j],
                    "symbol": f"C{i}:{100 + i}",
                    "cmc_id": 100 + i,
                    "venue": "bybit",
                    "open": price,
                    "high": price * 1.05,
                    "low": price * 0.95,
                    "close": price,
                    "volume": 1000.0,
                    "venue_turnover_usd": float(turnover[j]),
                    "cmc_rank": float(50 + i * 20),
                    "market_cap_usd": price * 1e6 * (i + 1),
                    "reported_volume_usd": float(turnover[j]) * 3,
                    "eligible_to_open": True,
                    "tradable": True,
                    "first_venue_bar_at": dates[first],
                    "left_censored": first == 0,
                }
            )
    return pd.DataFrame(rows).sort_values(["timestamp", "symbol"]).reset_index(drop=True)


@pytest.mark.parametrize("signal", SIGNALS, ids=lambda f: f.__name__)
def test_truncation_invariance(signal) -> None:
    """Weights before t cannot change when data after t is removed."""
    panel = _panel()
    cutoff = panel["timestamp"].quantile(0.7)
    truncated = panel[panel["timestamp"] <= cutoff]

    full = signal(panel, {})
    partial = signal(truncated, {})
    full_before = full[full["timestamp"] <= cutoff].reset_index(drop=True)
    partial_before = partial[partial["timestamp"] <= cutoff].reset_index(drop=True)

    common = sorted(set(full_before["symbol"]) & set(partial_before["symbol"]))
    left = (
        full_before[full_before["symbol"].isin(common)]
        .set_index(["timestamp", "symbol"])["target_weight"]
        .sort_index()
    )
    right = (
        partial_before[partial_before["symbol"].isin(common)]
        .set_index(["timestamp", "symbol"])["target_weight"]
        .sort_index()
    )
    assert set(left.index) == set(right.index)
    pd.testing.assert_series_equal(left, right, check_exact=False, rtol=1e-9)


@pytest.mark.parametrize("signal", SIGNALS, ids=lambda f: f.__name__)
def test_weights_are_long_only_and_never_exceed_one(signal) -> None:
    weights = signal(_panel(), {})
    assert (weights["target_weight"] >= 0).all()
    totals = weights.groupby("timestamp")["target_weight"].sum()
    assert (totals <= 1.0 + 1e-9).all()


@pytest.mark.parametrize("signal", SIGNALS, ids=lambda f: f.__name__)
def test_rebalances_only_in_january(signal) -> None:
    """The turnover gate permits roughly one rebalance a year, and no more."""
    weights = signal(_panel(), {})
    months = pd.to_datetime(weights["timestamp"].unique()).month
    assert set(months) <= {1}


@pytest.mark.parametrize("signal", SIGNALS, ids=lambda f: f.__name__)
def test_registered_under_a_stable_name(signal) -> None:
    name = {
        "capacity_illiquidity": "crypto_capacity_illiquidity",
        "death_avoidance": "crypto_death_avoidance",
        "annual_equal_weight_rebalance": "crypto_annual_equal_weight_rebalance",
        "survival_duration": "crypto_survival_duration",
    }[signal.__name__]
    model = get_research_signal_model(name)
    assert model.generate(_panel(), {}).equals(signal(_panel(), {}))


def test_annual_mask_is_strict_january_with_no_first_bar_fallback() -> None:
    index = pd.date_range("2019-06-01", periods=800, freq="D", tz="UTC")
    mask = rebalance_mask(index, "annual")
    marked = index[mask.to_numpy()]
    assert list(marked) == [
        pd.Timestamp("2020-01-01", tz="UTC"),
        pd.Timestamp("2021-01-01", tz="UTC"),
    ]
    assert not mask.iloc[0]  # a mid-year start does not invent a rebalance


def test_illiquid_and_liquid_bands_select_opposite_names() -> None:
    """H1's control must be the same construction pointed the other way."""
    panel = _panel()
    params = {"top_n": 3}
    illiquid = capacity_illiquidity(panel, params)
    liquid = capacity_illiquidity(panel, {**params, "liquid_band": True})
    # The last rebalance, not the first: the trailing liquidity window needs
    # history, so the earliest rebalance can legitimately hold nothing.
    when = illiquid["timestamp"].max()
    held_illiquid = set(
        illiquid[(illiquid["timestamp"] == when) & (illiquid["target_weight"] > 0)]["symbol"]
    )
    held_liquid = set(
        liquid[(liquid["timestamp"] == when) & (liquid["target_weight"] > 0)]["symbol"]
    )
    assert held_illiquid and held_liquid
    assert not (held_illiquid & held_liquid)


def test_capacity_screen_rejects_coins_too_thin_for_the_order() -> None:
    """A coin whose venue turnover cannot support the order is not tradable."""
    thin = _panel(turnover_scale=1.0)  # turnover far below 50 x $1,000
    weights = capacity_illiquidity(thin, {})
    assert weights["target_weight"].sum() == 0.0


def test_explicit_open_eligibility_and_tradability_are_both_required() -> None:
    panel = _panel()
    target = panel["symbol"].iloc[-1]
    panel.loc[panel["symbol"] == target, "eligible_to_open"] = False
    ineligible = capacity_illiquidity(panel, {"top_n": 20})
    assert not ((ineligible["symbol"] == target) & (ineligible["target_weight"] > 0)).any()

    panel.loc[panel["symbol"] == target, "eligible_to_open"] = True
    panel.loc[panel["symbol"] == target, "tradable"] = False
    untradable = capacity_illiquidity(panel, {"top_n": 20})
    assert not ((untradable["symbol"] == target) & (untradable["target_weight"] > 0)).any()


def test_plain_price_presence_is_not_an_eligibility_contract() -> None:
    panel = _panel().drop(columns=["eligible_to_open"])
    with pytest.raises(ValueError, match="eligible_to_open"):
        capacity_illiquidity(panel, {})


def test_death_screen_ejects_a_collapsing_name() -> None:
    panel = _panel(n_symbols=6, seed=3)
    # A name that survives to the end: the fixture kills every fifth symbol, and
    # a coin that is already dead tells us nothing about whether a screen works.
    end = panel["timestamp"].max()
    survivors = sorted(panel.groupby("symbol")["timestamp"].max().pipe(lambda s: s[s == end]).index)
    target = survivors[-1]
    # Collapse the last year of turnover, leaving prices alone. The factor is
    # chosen to trip the death screen (below 25% of its own long-run median)
    # while staying above the capacity floor: the two exclusions are different
    # mechanisms, and a collapse deep enough to breach capacity would prove
    # nothing about the death screen.
    collapsing = (panel["symbol"] == target) & (panel["timestamp"] > end - pd.Timedelta(days=300))
    panel.loc[collapsing, "venue_turnover_usd"] *= 0.05

    screened = death_avoidance(panel, {"top_n": 6})
    unscreened = death_avoidance(panel, {"top_n": 6, "screen_off": True})
    last_rebalance = screened["timestamp"].max()

    def held(frame):
        at = frame[(frame["timestamp"] == last_rebalance) & (frame["target_weight"] > 0)]
        return set(at["symbol"])

    assert target in held(unscreened)
    assert target not in held(screened)


def test_death_screen_emits_sparse_forced_exit_between_annual_rebalances() -> None:
    panel = _panel(n_days=1_200, n_symbols=6, seed=3, start="2018-06-01")
    january = pd.Timestamp("2020-01-01", tz="UTC")
    at_january = death_avoidance(
        panel[panel["timestamp"] <= january],
        {"top_n": 6, "rank_lookback_days": 30, "max_rank_decay": 50},
    )
    held = set(
        at_january[(at_january["timestamp"] == january) & (at_january["target_weight"] > 0)][
            "symbol"
        ]
    )
    assert held
    target = sorted(held)[0]
    february = pd.Timestamp("2020-02-10", tz="UTC")
    panel.loc[
        (panel["symbol"] == target) & (panel["timestamp"] >= february),
        "cmc_rank",
    ] += 500

    weights = death_avoidance(
        panel,
        {"top_n": 6, "rank_lookback_days": 30, "max_rank_decay": 50},
    )
    exits = weights[(weights["symbol"] == target) & (weights["order_intent"] == FORCED_EXIT)]
    assert len(exits) == 1
    assert exits.iloc[0]["timestamp"] == february
    assert exits.iloc[0]["target_weight"] == 0.0
    assert exits.iloc[0]["timestamp"].month == 2
    assert not weights.duplicated(["timestamp", "symbol"]).any()


def test_buy_and_hold_control_trades_exactly_once() -> None:
    panel = _panel()
    once = annual_equal_weight_rebalance(panel, {"rebalance_once": True})
    annual = annual_equal_weight_rebalance(panel, {})
    assert once["timestamp"].nunique() == 1
    assert annual["timestamp"].nunique() > 1
    assert once["timestamp"].min() == annual["timestamp"].min()


def test_h3_arms_share_one_frozen_cohort_and_never_add_replacements() -> None:
    panel = _panel(n_days=1_500)
    cohort = frozen_rebalance_cohort(panel, {"top_n": 4})
    annual = annual_equal_weight_rebalance(panel, {"top_n": 4})
    once = annual_equal_weight_rebalance(panel, {"top_n": 4, "rebalance_once": True})

    assert cohort.instrument_ids
    assert annual.attrs["cohort_digest"] == cohort.digest == once.attrs["cohort_digest"]
    annual_positive = set(annual[annual["target_weight"] > 0]["symbol"])
    once_positive = set(once[once["target_weight"] > 0]["symbol"])
    assert annual_positive == once_positive == set(cohort.instrument_ids)

    # A future outsider can become the largest name, but it cannot enter either
    # arm: the cohort was fixed before treatment and control diverged.
    outsider = next(
        symbol for symbol in panel["symbol"].unique() if symbol not in cohort.instrument_ids
    )
    future = panel["timestamp"] > pd.Timestamp(cohort.decision_timestamp)
    panel.loc[future & (panel["symbol"] == outsider), "market_cap_usd"] = 999e9
    changed = annual_equal_weight_rebalance(panel, {"top_n": 4})
    assert outsider not in set(changed[changed["target_weight"] > 0]["symbol"])
    assert changed.attrs["cohort_digest"] == cohort.digest


def test_dynamic_equal_weight_benchmark_reselects_current_eligible_names() -> None:
    panel = _panel(n_days=1_500)
    cohort = frozen_rebalance_cohort(panel, {"top_n": 4})
    last_rebalance = pd.Timestamp("2023-01-01", tz="UTC")
    present = set(panel.loc[panel["timestamp"] == last_rebalance, "symbol"])
    outsider = next(symbol for symbol in sorted(present) if symbol not in cohort.instrument_ids)
    after_cohort = panel["timestamp"] > pd.Timestamp(cohort.decision_timestamp)
    panel.loc[after_cohort & panel["symbol"].eq(outsider), "market_cap_usd"] = 999e9

    dynamic = annual_equal_weight_rebalance(panel, {"top_n": 4, "freeze_cohort": False})
    frozen = annual_equal_weight_rebalance(panel, {"top_n": 4})
    dynamic_held = set(
        dynamic[dynamic["timestamp"].eq(last_rebalance) & dynamic["target_weight"].gt(0)]["symbol"]
    )

    assert dynamic.attrs["cohort_mode"] == "dynamic_eligible"
    assert outsider in dynamic_held
    assert outsider not in set(frozen[frozen["target_weight"] > 0]["symbol"])


def test_left_censored_coins_are_excluded_from_survival_ranking() -> None:
    """Coins alive on the first bar have unknown age and must not be credited."""
    panel = _panel()
    first_day = panel["timestamp"].min()
    censored = set(panel[panel["timestamp"] == first_day]["symbol"])
    weights = survival_duration(panel, {"min_age_days": 30, "top_n": 5})
    held = set(weights[weights["target_weight"] > 0]["symbol"])
    assert held
    assert not (held & censored)


def test_survival_duration_prefers_the_older_cohort() -> None:
    panel = _panel()
    weights = survival_duration(panel, {"min_age_days": 30, "top_n": 2})
    first = weights["timestamp"].min()
    held = weights[(weights["timestamp"] == first) & (weights["target_weight"] > 0)]
    ages = {}
    for symbol in panel["symbol"].unique():
        bars = panel[(panel["symbol"] == symbol) & (panel["timestamp"] <= first)]
        ages[symbol] = len(bars)
    chosen = set(held["symbol"])
    not_chosen = {s: a for s, a in ages.items() if s not in chosen and a > 0}
    if chosen and not_chosen:
        assert min(ages[s] for s in chosen) >= max(not_chosen.values()) - 1


def test_h4_age_is_elapsed_from_first_venue_bar_and_survives_a_gap() -> None:
    panel = _panel(n_days=900)
    non_censored = panel.loc[~panel["left_censored"], "symbol"].unique()[0]
    rows = panel[panel["symbol"] == non_censored]
    first = pd.Timestamp(rows["first_venue_bar_at"].iloc[0])
    gap_start = first + pd.Timedelta(days=100)
    gap_end = first + pd.Timedelta(days=160)
    panel = panel[
        ~((panel["symbol"] == non_censored) & panel["timestamp"].between(gap_start, gap_end))
    ]
    weights = survival_duration(
        panel,
        {"min_age_days": 300, "top_n": 20, "liquidity_window": 30},
    )
    eligible_after_300 = weights[
        (weights["symbol"] == non_censored)
        & (weights["timestamp"] >= first + pd.Timedelta(days=300))
        & (weights["target_weight"] > 0)
    ]
    assert not eligible_after_300.empty


def test_h4_refuses_age_inferred_from_panel_presence() -> None:
    panel = _panel().drop(columns=["first_venue_bar_at"])
    with pytest.raises(ValueError, match="first_venue_bar_at"):
        survival_duration(panel, {})


@pytest.mark.parametrize("signal", SIGNALS, ids=lambda f: f.__name__)
def test_an_empty_panel_produces_no_weights(signal) -> None:
    empty = _panel().iloc[0:0]
    with pytest.raises((ValueError, KeyError, IndexError)):
        signal(empty, {})
