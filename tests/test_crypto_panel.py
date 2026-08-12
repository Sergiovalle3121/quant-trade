"""Tests for the universe-to-venue join, concentrated on identity binding.

The join is where survivorship bias gets a second chance to enter: the venues
know only tickers, thousands of tickers are carried by more than one coin, and
both the naive fix (join on ticker) and the obvious defence (drop ambiguous
tickers) are wrong in the same direction. These tests pin the behaviour that
avoids both.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from quant_trade.data.crypto_panel import (
    STABLECOIN_SYMBOLS,
    PanelRow,
    bind_bar_to_coin,
    build_panel,
    load_universe_facts,
    load_venue_series,
    overlay_market_events,
)


def _write_universe(root, rows_by_day: dict[str, list[dict]]) -> None:
    days = root / "days"
    days.mkdir(parents=True, exist_ok=True)
    for day, rows in rows_by_day.items():
        with (days / f"{day}.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")


def _coin(cmc_id, symbol, rank, mcap, supply, volume=1_000_000.0) -> dict:
    return {
        "cmc_id": cmc_id,
        "symbol": symbol,
        "name": symbol.title(),
        "cmc_rank": rank,
        "market_cap_usd": mcap,
        "volume24h_usd": volume,
        "circulating_supply": supply,
    }


def _write_venue(
    root,
    series: dict[str, list[dict]],
    venue="bybit",
    collection_start: str | None = None,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "series").mkdir(exist_ok=True)
    dates = sorted(bar["date"] for bars in series.values() for bar in bars)
    start = collection_start or dates[0]
    records = [
        {
            "type": "header",
            "venue": venue,
            "previous_sha256": "",
            "window": [start, dates[-1]],
        }
    ]
    for symbol, bars in series.items():
        with (root / "series" / f"{symbol}.jsonl").open("w", encoding="utf-8") as handle:
            for bar in bars:
                handle.write(json.dumps(bar, sort_keys=True) + "\n")
        records.append(
            {
                "type": "symbol",
                "symbol": symbol,
                "outcome": "listed",
                "row_count": len(bars),
                "first_date": min(bar["date"] for bar in bars),
                "last_date": max(bar["date"] for bar in bars),
            }
        )
    with (root / "journal.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def _bar(day, close, volume=100.0, turnover=1000.0) -> dict:
    return {
        "date": day,
        "start_ms": 0,
        "open": close,
        "high": close * 1.05,
        "low": close * 0.95,
        "close": close,
        "volume_base": volume,
        "turnover_quote": turnover,
    }


def _panel_row(**overrides) -> PanelRow:
    values = {
        "timestamp": datetime(2020, 1, 1, tzinfo=UTC),
        "symbol": "CMC:1",
        "instrument_id": "CMC:1",
        "cmc_id": 1,
        "ticker": "AAA",
        "venue": "bybit",
        "venue_symbol": "AAAUSDT",
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.0,
        "volume": 100.0,
        "mark_price": 10.0,
        "eligible_to_open": True,
        "tradable": True,
        "data_status": "VALID",
        "market_event": "NONE",
        "bound_bar_number": 20,
        "first_venue_bar_at": datetime(2019, 12, 13, tzinfo=UTC),
        "left_censored": False,
        "universe_age_days": 20,
        "venue_turnover_usd": 1_000.0,
        "cmc_rank": 10.0,
        "market_cap_usd": 100_000_000.0,
        "reported_volume_usd": 1_000_000.0,
        "circulating_supply": 10_000_000.0,
        "in_rank_band": True,
        "in_market_cap_band": True,
    }
    values.update(overrides)
    return PanelRow(**values)


def test_panel_row_is_frozen_and_validates_stable_identity() -> None:
    row = _panel_row()
    assert row.to_dict()["instrument_id"] == "CMC:1"
    with pytest.raises(FrozenInstanceError):
        row.ticker = "NEW"  # type: ignore[misc]
    with pytest.raises(ValueError, match="panel identity must be CMC:1"):
        _panel_row(instrument_id="AAA:1")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("eligible_to_open", 1, "actual bool"),
        ("tradable", "True", "actual bool"),
        ("left_censored", None, "actual bool"),
        ("data_status", "PHANTOM", "unsupported data_status"),
        ("market_event", "NONE|HALT", "NONE cannot be combined"),
    ],
)
def test_panel_row_rejects_implicit_state_values(field, value, message) -> None:
    with pytest.raises(ValueError, match=message):
        _panel_row(**{field: value})


# --- identity binding ----------------------------------------------------


def _facts(tmp_path, rows_by_day):
    _write_universe(tmp_path, rows_by_day)
    days = sorted(rows_by_day)
    return load_universe_facts(
        tmp_path,
        start_date=date.fromisoformat(days[0]),
        end_date=date.fromisoformat(days[-1]),
    )


def test_unique_ticker_still_requires_price_agreement(tmp_path) -> None:
    facts = _facts(tmp_path, {"2020-01-01": [_coin(1, "AAA", 10, 1_000.0, 100.0)]})
    assert bind_bar_to_coin(candidates={1}, day_iso="2020-01-01", close=10.1, facts=facts) == 1
    assert bind_bar_to_coin(candidates={1}, day_iso="2020-01-01", close=999.0, facts=facts) is None


def test_ambiguous_ticker_binds_to_the_matching_price(tmp_path) -> None:
    """Two coins share GOLD; implied prices are 10.0 and 5000.0."""
    facts = _facts(
        tmp_path,
        {
            "2020-01-01": [
                _coin(1, "GOLD", 10, 1_000.0, 100.0),  # implied 10.0
                _coin(2, "GOLD", 20, 5_000_000.0, 1000.0),  # implied 5000.0
            ]
        },
    )
    assert bind_bar_to_coin(candidates={1, 2}, day_iso="2020-01-01", close=10.4, facts=facts) == 1
    assert bind_bar_to_coin(candidates={1, 2}, day_iso="2020-01-01", close=4800.0, facts=facts) == 2


def test_ambiguous_bar_matching_neither_coin_is_left_unbound(tmp_path) -> None:
    facts = _facts(
        tmp_path,
        {
            "2020-01-01": [
                _coin(1, "GOLD", 10, 1_000.0, 100.0),
                _coin(2, "GOLD", 20, 5_000_000.0, 1000.0),
            ]
        },
    )
    bound = bind_bar_to_coin(candidates={1, 2}, day_iso="2020-01-01", close=250.0, facts=facts)
    assert bound is None


def test_two_plausible_owners_are_left_unbound(tmp_path) -> None:
    facts = _facts(
        tmp_path,
        {
            "2020-01-01": [
                _coin(1, "GOLD", 10, 1_000.0, 100.0),
                _coin(2, "GOLD", 20, 1_100.0, 100.0),
            ]
        },
    )
    assert (
        bind_bar_to_coin(candidates={1, 2}, day_iso="2020-01-01", close=10.5, facts=facts) is None
    )


def test_a_bar_on_a_day_the_coin_is_absent_does_not_bind(tmp_path) -> None:
    """A venue can keep trading a coin the universe screen has dropped."""
    facts = _facts(tmp_path, {"2020-01-01": [_coin(1, "AAA", 10, 1_000.0, 100.0)]})
    assert bind_bar_to_coin(candidates={1}, day_iso="2020-01-02", close=10.0, facts=facts) is None


def test_binding_follows_the_coin_across_a_ticker_change(tmp_path) -> None:
    """Identity is cmc_id, so a rename must not split one history in two."""
    facts = _facts(
        tmp_path,
        {
            "2020-01-01": [_coin(7, "OLD", 10, 1_000.0, 100.0)],
            "2020-01-02": [_coin(7, "NEW", 10, 1_100.0, 100.0)],
        },
    )
    assert facts.ids_by_symbol["OLD"] == {7}
    assert facts.ids_by_symbol["NEW"] == {7}
    assert bind_bar_to_coin(candidates={7}, day_iso="2020-01-02", close=11.0, facts=facts) == 7


# --- screens are applied and reported ------------------------------------


def test_rank_ceiling_and_stablecoins_are_screened(tmp_path) -> None:
    facts = _facts(
        tmp_path,
        {
            "2020-01-01": [
                _coin(1, "AAA", 10, 1_000.0, 100.0),
                _coin(2, "BBB", 5_000, 1_000.0, 100.0),  # outside rank ceiling
                _coin(3, "USDT", 3, 1_000.0, 100.0),  # stablecoin
            ]
        },
    )
    # Facts and potential marks remain auditable; membership is a separate flag.
    assert set(facts.ids_by_symbol) == {"AAA", "BBB", "USDT"}
    assert facts.by_date_coin[("2020-01-01", 1)]["in_rank_band"] is True
    assert facts.by_date_coin[("2020-01-01", 2)]["universe_eligible"] is False
    assert facts.by_date_coin[("2020-01-01", 3)]["stablecoin_excluded"] is True
    assert facts.stablecoins_seen == 1
    assert "USDT" in STABLECOIN_SYMBOLS


def test_negative_market_cap_rows_are_dropped(tmp_path) -> None:
    facts = _facts(
        tmp_path,
        {"2020-01-01": [_coin(1, "AAA", 10, -1_000.0, 100.0), _coin(2, "BBB", 11, 5.0, 1.0)]},
    )
    assert set(facts.ids_by_symbol) == {"BBB"}


def test_byte_identical_duplicate_rows_collapse(tmp_path) -> None:
    """The source padded four days with repeats; keeping the first chooses nothing."""
    row = _coin(1, "AAA", 10, 1_000.0, 100.0)
    facts = _facts(tmp_path, {"2020-01-01": [row, row, row]})
    assert facts.by_date_coin[("2020-01-01", 1)]["market_cap_usd"] == 1_000.0
    assert facts.coins == 1


# --- end to end ----------------------------------------------------------


def _three_day_universe():
    days = ["2020-01-01", "2020-01-02", "2020-01-03"]
    return {d: [_coin(1, "AAA", 10, 1_000.0, 100.0)] for d in days}, days


def test_panel_joins_prices_to_point_in_time_facts(tmp_path) -> None:
    rows, days = _three_day_universe()
    _write_universe(tmp_path / "universe", rows)
    _write_venue(tmp_path / "bybit", {"AAAUSDT": [_bar(d, 10.0) for d in days]})
    frame, report = build_panel(
        tmp_path / "universe",
        {"bybit": tmp_path / "bybit"},
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
        min_bound_bars=1,
    )
    assert report.coins_in_panel == 1
    assert report.rows_in_panel == 3
    assert list(frame["symbol"].unique()) == ["CMC:1"]
    assert list(frame["instrument_id"].unique()) == ["CMC:1"]
    assert set(frame["ticker"]) == {"AAA"}
    assert set(frame["venue_symbol"]) == {"AAAUSDT"}
    assert frame["mark_price"].equals(frame["close"])
    assert frame["tradable"].all()
    assert frame["market_cap_usd"].iloc[0] == 1_000.0
    assert frame["venue"].iloc[0] == "bybit"


def test_left_censor_comes_from_venue_history_not_universe_start(tmp_path) -> None:
    days = ["2020-01-10", "2020-01-11"]
    rows = {day: [_coin(1, "AAA", 10, 100_000_000.0, 10_000_000.0)] for day in days}
    _write_universe(tmp_path / "universe", rows)
    _write_venue(
        tmp_path / "bybit",
        {"AAAUSDT": [_bar(day, 10.0) for day in days]},
        collection_start="2020-01-01",
    )

    frame, _ = build_panel(
        tmp_path / "universe",
        {"bybit": tmp_path / "bybit"},
        start_date=date(2020, 1, 10),
        end_date=date(2020, 1, 11),
        min_bound_bars=1,
    )

    assert not frame["left_censored"].any()
    assert frame["first_venue_bar_at"].iloc[0] == datetime(2020, 1, 10, tzinfo=UTC)


def test_venue_history_at_collection_boundary_is_left_censored(tmp_path) -> None:
    days = ["2020-01-01", "2020-01-02"]
    rows = {day: [_coin(1, "AAA", 10, 100_000_000.0, 10_000_000.0)] for day in days}
    _write_universe(tmp_path / "universe", rows)
    _write_venue(tmp_path / "bybit", {"AAAUSDT": [_bar(day, 10.0) for day in days]})

    frame, _ = build_panel(
        tmp_path / "universe",
        {"bybit": tmp_path / "bybit"},
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 2),
        min_bound_bars=1,
    )

    assert frame["left_censored"].all()


def test_a_renamed_coin_stays_one_series(tmp_path) -> None:
    """Identity is cmc_id, so a rename must not split the panel row label.

    Labelling each row with the ticker the coin carried that day would produce
    two series for one coin — the same identity weld this module prevents on
    the join, arriving through the back door as a string.
    """
    days = ["2020-01-01", "2020-01-02", "2020-01-03"]
    rows = {
        days[0]: [_coin(7, "OLD", 10, 1_000.0, 100.0)],
        days[1]: [_coin(7, "NEW", 10, 1_000.0, 100.0)],
        days[2]: [_coin(7, "NEW", 10, 1_000.0, 100.0)],
    }
    _write_universe(tmp_path / "universe", rows)
    _write_venue(tmp_path / "bybit", {"OLDUSDT": [_bar(d, 10.0) for d in days]})
    frame, _ = build_panel(
        tmp_path / "universe",
        {"bybit": tmp_path / "bybit"},
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
        min_bound_bars=1,
    )
    assert frame["symbol"].nunique() == 1
    assert frame["cmc_id"].nunique() == 1
    assert set(frame["symbol"]) == {"CMC:7"}
    assert list(frame["ticker"]) == ["OLD", "NEW", "NEW"]
    assert set(frame["venue_symbol"]) == {"OLDUSDT"}
    assert "RENAME" in frame.loc[1, "market_event"]
    assert len(frame) == 3


def test_a_coin_the_venue_never_listed_is_simply_absent(tmp_path) -> None:
    rows, days = _three_day_universe()
    rows = {d: r + [_coin(2, "BBB", 11, 500.0, 50.0)] for d, r in rows.items()}
    _write_universe(tmp_path / "universe", rows)
    _write_venue(tmp_path / "bybit", {"AAAUSDT": [_bar(d, 10.0) for d in days]})
    frame, report = build_panel(
        tmp_path / "universe",
        {"bybit": tmp_path / "bybit"},
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
        min_bound_bars=1,
    )
    assert set(frame["symbol"]) == {"CMC:1"}
    assert report.coins_in_rank_band == 2  # it was in the universe, just not tradable


def test_declared_venue_wins_even_when_an_alternate_has_more_history(tmp_path) -> None:
    """Future coverage on another venue cannot choose the execution venue."""
    rows, days = _three_day_universe()
    _write_universe(tmp_path / "universe", rows)
    _write_venue(tmp_path / "short", {"AAAUSDT": [_bar(days[0], 10.0)]}, venue="bybit")
    _write_venue(tmp_path / "long", {"AAAUSDT": [_bar(d, 10.0) for d in days]}, venue="binance")
    frame, _ = build_panel(
        tmp_path / "universe",
        {"bybit": tmp_path / "short", "binance": tmp_path / "long"},
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
        min_bound_bars=1,
    )
    assert set(frame["venue"]) == {"bybit"}
    assert len(frame) == 1


def test_a_short_history_is_retained_but_causally_ineligible_and_counted(tmp_path) -> None:
    rows, days = _three_day_universe()
    _write_universe(tmp_path / "universe", rows)
    _write_venue(tmp_path / "bybit", {"AAAUSDT": [_bar(days[0], 10.0)]})
    frame, report = build_panel(
        tmp_path / "universe",
        {"bybit": tmp_path / "bybit"},
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
        min_bound_bars=20,
    )
    assert len(frame) == 1
    assert frame["bound_bar_number"].tolist() == [1]
    assert frame["eligible_to_open"].tolist() == [False]
    assert report.coins_below_min_bound_bars == 1


def test_twentieth_bound_bar_enables_opening_without_rewriting_the_prefix(tmp_path) -> None:
    days = [(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(21)]
    rows = {day: [_coin(1, "AAA", 10, 100_000_000.0, 10_000_000.0)] for day in days}
    _write_universe(tmp_path / "universe", rows)
    _write_venue(tmp_path / "bybit", {"AAAUSDT": [_bar(day, 10.0) for day in days]})
    frame, report = build_panel(
        tmp_path / "universe",
        {"bybit": tmp_path / "bybit"},
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 21),
    )
    assert len(frame) == 21
    assert not frame.loc[:18, "eligible_to_open"].any()
    assert frame.loc[19:, "eligible_to_open"].all()
    assert frame["bound_bar_number"].tolist() == list(range(1, 22))
    assert report.warmup_rows_ineligible == 19


def test_rank_exit_keeps_marks_and_blocks_only_new_opens(tmp_path) -> None:
    days = ["2020-01-01", "2020-01-02", "2020-01-03"]
    rows = {
        days[0]: [_coin(1, "AAA", 10, 100_000_000.0, 10_000_000.0)],
        days[1]: [_coin(1, "AAA", 1_500, 100_000_000.0, 10_000_000.0)],
        days[2]: [_coin(1, "AAA", 20, 100_000_000.0, 10_000_000.0)],
    }
    _write_universe(tmp_path / "universe", rows)
    _write_venue(tmp_path / "bybit", {"AAAUSDT": [_bar(day, 10.0) for day in days]})
    frame, report = build_panel(
        tmp_path / "universe",
        {"bybit": tmp_path / "bybit"},
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
        min_bound_bars=1,
    )
    assert len(frame) == 3
    assert frame["eligible_to_open"].tolist() == [True, False, True]
    assert frame["mark_price"].tolist() == [10.0, 10.0, 10.0]
    assert frame["market_event"].tolist() == ["NONE", "RANK_EXIT", "RANK_REENTRY"]
    assert report.rows_outside_open_universe == 1


def test_panel_prefix_is_invariant_to_future_identity_venue_and_warmup(tmp_path) -> None:
    days = [(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(25)]
    cutoff = date.fromisoformat(days[9])
    rows: dict[str, list[dict]] = {}
    for index, day in enumerate(days):
        ticker = "AAA" if index < 12 else "NEW"
        rank = 1_500 if index in (15, 16) else 10
        rows[day] = [_coin(1, ticker, rank, 100_000_000.0, 10_000_000.0)]
        # Future ticker reuse must not make the original owner's prefix ambiguous.
        if index >= 20:
            rows[day].append(_coin(2, "AAA", 30, 100_000_000.0, 10_000_000.0))

    _write_universe(tmp_path / "universe", rows)
    _write_venue(
        tmp_path / "bybit",
        {"AAAUSDT": [_bar(day, 10.0) for day in days[:22]]},
        venue="bybit",
    )
    _write_venue(
        tmp_path / "binance",
        {"AAAUSDT": [_bar(day, 10.0) for day in days]},
        venue="binance",
    )
    venue_dirs = {"bybit": tmp_path / "bybit", "binance": tmp_path / "binance"}
    short, short_report = build_panel(
        tmp_path / "universe",
        venue_dirs,
        start_date=date.fromisoformat(days[0]),
        end_date=cutoff,
    )
    full, full_report = build_panel(
        tmp_path / "universe",
        venue_dirs,
        start_date=date.fromisoformat(days[0]),
        end_date=date.fromisoformat(days[-1]),
    )
    full_prefix = full[full["timestamp"].dt.date <= cutoff].reset_index(drop=True)
    assert short.to_csv(index=False) == full_prefix.to_csv(index=False)
    assert not short["eligible_to_open"].any()  # fewer than 20 causal bars
    assert short_report.venues_used == full_report.venues_used == ["bybit"]
    assert set(full["symbol"]) == {"CMC:1"}
    assert "RENAME" in full.loc[full["ticker"] == "NEW", "market_event"].iloc[0]
    assert "RANK_EXIT" in set(full["market_event"])
    assert "RANK_REENTRY" in set(full["market_event"])
    assert not full["market_event"].str.contains("DELIST").any()


def test_future_venue_symbol_history_cannot_rewrite_left_censor_prefix(tmp_path) -> None:
    """A later venue rename cannot import its older raw history into prior rows."""
    days = ["2020-01-10", "2020-01-11", "2020-01-12"]
    rows = {
        days[0]: [_coin(7, "OLD", 10, 100_000_000.0, 10_000_000.0)],
        days[1]: [_coin(7, "OLD", 10, 100_000_000.0, 10_000_000.0)],
        days[2]: [_coin(7, "NEW", 10, 100_000_000.0, 10_000_000.0)],
    }
    _write_universe(tmp_path / "universe", rows)
    _write_venue(
        tmp_path / "bybit",
        {
            "OLDUSDT": [_bar(day, 10.0) for day in days[:2]],
            # The old raw NEWUSDT bar is outside the requested panel window and
            # has no causal CMC binding.  It must not censor OLDUSDT's prefix
            # merely because NEW becomes the venue metadata on a future date.
            "NEWUSDT": [_bar("2020-01-05", 10.0), _bar(days[2], 10.0)],
        },
        collection_start="2020-01-01",
    )

    short, _ = build_panel(
        tmp_path / "universe",
        {"bybit": tmp_path / "bybit"},
        start_date=date.fromisoformat(days[0]),
        end_date=date.fromisoformat(days[1]),
        min_bound_bars=1,
    )
    full, _ = build_panel(
        tmp_path / "universe",
        {"bybit": tmp_path / "bybit"},
        start_date=date.fromisoformat(days[0]),
        end_date=date.fromisoformat(days[2]),
        min_bound_bars=1,
    )
    full_prefix = full[full["timestamp"].dt.date <= date.fromisoformat(days[1])].reset_index(
        drop=True
    )

    assert short.to_csv(index=False) == full_prefix.to_csv(index=False)
    assert not short["left_censored"].any()
    assert set(full["venue_symbol"]) == {"OLDUSDT", "NEWUSDT"}


def test_event_overlay_never_manufactures_ohlc_for_a_sparse_event(tmp_path) -> None:
    rows, days = _three_day_universe()
    _write_universe(tmp_path / "universe", rows)
    _write_venue(tmp_path / "bybit", {"AAAUSDT": [_bar(days[0], 10.0), _bar(days[2], 9.0)]})
    panel, _ = build_panel(
        tmp_path / "universe",
        {"bybit": tmp_path / "bybit"},
        start_date=date.fromisoformat(days[0]),
        end_date=date.fromisoformat(days[2]),
        min_bound_bars=1,
    )
    events = pd.DataFrame(
        [
            {
                "timestamp": datetime(2020, 1, 2, tzinfo=UTC),
                "instrument_id": "CMC:1",
                "venue": "bybit",
                "market_event": "HALT",
            },
            {
                "timestamp": datetime(2020, 1, 3, tzinfo=UTC),
                "instrument_id": "CMC:1",
                "venue": "bybit",
                "market_event": "DELISTING_ANNOUNCED",
            },
        ]
    )

    overlaid, sparse = overlay_market_events(panel, events)

    assert len(overlaid) == len(panel) == 2
    assert "DELISTING_ANNOUNCED" in overlaid.iloc[-1]["market_event"]
    assert len(sparse) == 1
    assert sparse.iloc[0]["market_event"] == "HALT"


def test_a_dead_coin_keeps_its_history_up_to_death(tmp_path) -> None:
    """The panel must end the series, not forward-fill it into eternity."""
    days = ["2020-01-01", "2020-01-02", "2020-01-03"]
    rows = {d: [_coin(1, "AAA", 10, 1_000.0, 100.0)] for d in days[:2]}
    rows[days[2]] = [_coin(9, "ZZZ", 10, 900.0, 90.0)]  # AAA is gone
    _write_universe(tmp_path / "universe", rows)
    _write_venue(tmp_path / "bybit", {"AAAUSDT": [_bar(d, 10.0) for d in days[:2]]})
    frame, _ = build_panel(
        tmp_path / "universe",
        {"bybit": tmp_path / "bybit"},
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
        min_bound_bars=1,
    )
    assert len(frame) == 2
    assert frame["timestamp"].max().date() == date(2020, 1, 2)


def test_load_venue_series_ignores_non_listed_outcomes(tmp_path) -> None:
    root = tmp_path / "bybit"
    _write_venue(root, {"AAAUSDT": [_bar("2020-01-01", 1.0)]})
    with (root / "journal.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"type": "symbol", "symbol": "GHOSTUSDT", "outcome": "not_listed"}) + "\n"
        )
    series = load_venue_series(root, start_date=date(2020, 1, 1), end_date=date(2020, 1, 2))
    assert set(series) == {"AAAUSDT"}


@pytest.mark.parametrize("close", [10.0, 14.9])
def test_tolerance_band_edges(tmp_path, close) -> None:
    facts = _facts(
        tmp_path,
        {
            "2020-01-01": [
                _coin(1, "GOLD", 10, 1_000.0, 100.0),  # implied 10.0
                _coin(2, "GOLD", 20, 10_000_000.0, 1000.0),  # implied 10000.0
            ]
        },
    )
    assert bind_bar_to_coin(candidates={1, 2}, day_iso="2020-01-01", close=close, facts=facts) == 1
