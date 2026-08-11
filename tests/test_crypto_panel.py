"""Tests for the universe-to-venue join, concentrated on identity binding.

The join is where survivorship bias gets a second chance to enter: the venues
know only tickers, thousands of tickers are carried by more than one coin, and
both the naive fix (join on ticker) and the obvious defence (drop ambiguous
tickers) are wrong in the same direction. These tests pin the behaviour that
avoids both.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from quant_trade.data.crypto_panel import (
    STABLECOIN_SYMBOLS,
    bind_bar_to_coin,
    build_panel,
    load_universe_facts,
    load_venue_series,
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


def _write_venue(root, series: dict[str, list[dict]], venue="bybit") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "series").mkdir(exist_ok=True)
    records = [{"type": "header", "venue": venue, "previous_sha256": ""}]
    for symbol, bars in series.items():
        with (root / "series" / f"{symbol}.jsonl").open("w", encoding="utf-8") as handle:
            for bar in bars:
                handle.write(json.dumps(bar, sort_keys=True) + "\n")
        records.append(
            {"type": "symbol", "symbol": symbol, "outcome": "listed", "row_count": len(bars)}
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


# --- identity binding ----------------------------------------------------


def _facts(tmp_path, rows_by_day):
    _write_universe(tmp_path, rows_by_day)
    days = sorted(rows_by_day)
    return load_universe_facts(
        tmp_path,
        start_date=date.fromisoformat(days[0]),
        end_date=date.fromisoformat(days[-1]),
    )


def test_unique_ticker_binds_directly(tmp_path) -> None:
    facts = _facts(tmp_path, {"2020-01-01": [_coin(1, "AAA", 10, 1_000.0, 100.0)]})
    # price agreement is irrelevant when only one coin can own the ticker
    assert bind_bar_to_coin(
        candidates={1}, day_iso="2020-01-01", close=999.0, facts=facts
    ) == 1


def test_ambiguous_ticker_binds_to_the_matching_price(tmp_path) -> None:
    """Two coins share GOLD; implied prices are 10.0 and 5000.0."""
    facts = _facts(
        tmp_path,
        {
            "2020-01-01": [
                _coin(1, "GOLD", 10, 1_000.0, 100.0),      # implied 10.0
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
    bound = bind_bar_to_coin(
        candidates={1, 2}, day_iso="2020-01-01", close=250.0, facts=facts
    )
    assert bound is None


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
                _coin(3, "USDT", 3, 1_000.0, 100.0),     # stablecoin
            ]
        },
    )
    assert set(facts.ids_by_symbol) == {"AAA"}
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
    assert list(frame["symbol"].unique()) == ["AAA:1"]
    assert frame["market_cap_usd"].iloc[0] == 1_000.0
    assert frame["venue"].iloc[0] == "bybit"


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
    assert set(frame["symbol"]) == {"AAA:1"}
    assert report.coins_in_rank_band == 2  # it was in the universe, just not tradable


def test_the_venue_with_more_bound_history_wins(tmp_path) -> None:
    """Venues disagree about death dates; a series must come from one of them."""
    rows, days = _three_day_universe()
    _write_universe(tmp_path / "universe", rows)
    _write_venue(tmp_path / "short", {"AAAUSDT": [_bar(days[0], 10.0)]}, venue="bybit")
    _write_venue(
        tmp_path / "long", {"AAAUSDT": [_bar(d, 10.0) for d in days]}, venue="binance"
    )
    frame, _ = build_panel(
        tmp_path / "universe",
        {"bybit": tmp_path / "short", "binance": tmp_path / "long"},
        start_date=date(2020, 1, 1),
        end_date=date(2020, 1, 3),
        min_bound_bars=1,
    )
    assert set(frame["venue"]) == {"binance"}
    assert len(frame) == 3


def test_a_coin_with_too_little_bound_history_is_excluded_and_counted(tmp_path) -> None:
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
    assert frame.empty
    assert report.coins_below_min_bound_bars == 1


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
            json.dumps({"type": "symbol", "symbol": "GHOSTUSDT", "outcome": "not_listed"})
            + "\n"
        )
    series = load_venue_series(root, start_date=date(2020, 1, 1), end_date=date(2020, 1, 2))
    assert set(series) == {"AAAUSDT"}


@pytest.mark.parametrize("close", [10.0, 14.9])
def test_tolerance_band_edges(tmp_path, close) -> None:
    facts = _facts(
        tmp_path,
        {
            "2020-01-01": [
                _coin(1, "GOLD", 10, 1_000.0, 100.0),        # implied 10.0
                _coin(2, "GOLD", 20, 10_000_000.0, 1000.0),  # implied 10000.0
            ]
        },
    )
    assert bind_bar_to_coin(
        candidates={1, 2}, day_iso="2020-01-01", close=close, facts=facts
    ) == 1
