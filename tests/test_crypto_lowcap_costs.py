"""Tests for the low/mid-cap cost model: book arithmetic, evidence rules,
measurement runner (fixtures only — no network, per repository policy)."""

from __future__ import annotations

import json

import pytest

from quant_trade.costs.crypto_lowcap import (
    BYBIT_SPOT_TAKER_FEE,
    CostInput,
    CostModelError,
    TierCostProfile,
    equivalent_total_window_turnover,
    max_viable_annual_turnover,
    round_trip_taker_cost_bps,
    tier_for_market_cap,
)
from quant_trade.costs.measure import run_cost_measurement
from quant_trade.costs.orderbook import (
    half_spread_bps,
    parse_bybit_orderbook,
    round_trip_exec_cost_bps,
    walk_cost_bps,
)


def _book_bytes(
    symbol: str = "ABCUSDT",
    bids: list[list[str]] | None = None,
    asks: list[list[str]] | None = None,
) -> bytes:
    payload = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "s": symbol,
            "b": bids if bids is not None else [["99.0", "10"], ["98.0", "10"]],
            "a": asks if asks is not None else [["101.0", "10"], ["102.0", "10"]],
            "ts": 1700000000000,
            "u": 1,
        },
    }
    return json.dumps(payload).encode()


# --- order-book arithmetic ---------------------------------------------------


def test_half_spread_is_measured_from_best_quotes():
    book = parse_bybit_orderbook(_book_bytes())
    # mid = 100, spread = 2 -> half-spread = 1/100 = 100 bps
    assert half_spread_bps(book) == pytest.approx(100.0)


def test_walk_cost_within_first_level_is_half_spread():
    book = parse_bybit_orderbook(_book_bytes())
    # $500 fits inside the 10 @ 101 ask level -> vwap 101 vs mid 100 = 100 bps
    assert walk_cost_bps(book, "buy", 500.0) == pytest.approx(100.0)
    assert walk_cost_bps(book, "sell", 500.0) == pytest.approx(100.0)


def test_walk_cost_crossing_levels_uses_vwap():
    book = parse_bybit_orderbook(_book_bytes())
    # Buy $1515: 1010 at 101, remaining 505 at 102.
    # vwap = (1010*101 + 505*102) / 1515 = 101.3333 -> 133.33 bps vs mid 100.
    cost = walk_cost_bps(book, "buy", 1515.0)
    assert cost == pytest.approx(133.333, abs=0.01)


def test_walk_cost_beyond_visible_book_is_none_not_extrapolated():
    book = parse_bybit_orderbook(_book_bytes())
    # Total ask notional = 10*101 + 10*102 = 2030 < 5000.
    assert walk_cost_bps(book, "buy", 5000.0) is None
    assert round_trip_exec_cost_bps(book, 5000.0) is None


def test_round_trip_is_buy_plus_sell():
    book = parse_bybit_orderbook(_book_bytes())
    assert round_trip_exec_cost_bps(book, 500.0) == pytest.approx(200.0)


def test_crossed_book_is_rejected():
    with pytest.raises(ValueError, match="crossed"):
        parse_bybit_orderbook(_book_bytes(bids=[["102.0", "1"]], asks=[["101.0", "1"]]))


def test_empty_side_is_rejected():
    with pytest.raises(ValueError, match="empty side"):
        parse_bybit_orderbook(_book_bytes(bids=[]))


def test_bad_ret_code_is_rejected():
    payload = {"retCode": 10001, "retMsg": "params error"}
    with pytest.raises(ValueError, match="retCode"):
        parse_bybit_orderbook(json.dumps(payload).encode())


# --- evidence rules ----------------------------------------------------------


def test_unknown_evidence_class_is_rejected():
    with pytest.raises(CostModelError, match="evidence_class"):
        CostInput(name="x", value_bps=1.0, evidence_class="VIBES", source="s")


def test_measured_class_without_bytes_hash_is_rejected():
    with pytest.raises(CostModelError, match="sha256"):
        CostInput(
            name="x", value_bps=1.0, evidence_class="REAL_PUBLIC_RETAIL", source="s"
        )


def test_fee_assumption_is_labelled():
    assert BYBIT_SPOT_TAKER_FEE.evidence_class == "ASSUMPTION"
    assert BYBIT_SPOT_TAKER_FEE.value_bps == 10.0


# --- tiers and turnover ------------------------------------------------------


def test_tier_boundaries():
    assert tier_for_market_cap(50e9) == "mega"
    assert tier_for_market_cap(5e9) == "large"
    assert tier_for_market_cap(500e6) == "mid"
    assert tier_for_market_cap(50e6) == "low"
    assert tier_for_market_cap(5e6) == "micro"
    assert tier_for_market_cap(5e5) is None


def _profile(exec_costs: dict[float, float | None]) -> TierCostProfile:
    return TierCostProfile(
        tier="mid",
        market_cap_min_usd=100e6,
        market_cap_max_usd=1e9,
        sample_count=10,
        half_spread_bps_p50=5.0,
        half_spread_bps_p75=9.0,
        exec_cost_bps_by_notional=exec_costs,
        exec_cost_p75_bps_by_notional=exec_costs,
        evidence_class="ASSUMPTION",
        source="test fixture",
        captured_at_utc="2026-08-05T00:00:00Z",
        manifest_sha256="",
    )


def test_round_trip_cost_adds_two_taker_fees_to_execution():
    profile = _profile({1000.0: 30.0, 10000.0: 80.0})
    # 2 x 10 bps fee + 30 bps execution = 50 bps at $1k (conservative lookup).
    assert round_trip_taker_cost_bps(profile, 800.0) == pytest.approx(50.0)
    assert round_trip_taker_cost_bps(profile, 10000.0) == pytest.approx(100.0)


def test_not_executable_size_propagates_none():
    profile = _profile({1000.0: 30.0, 10000.0: None})
    assert round_trip_taker_cost_bps(profile, 5000.0) is None
    assert round_trip_taker_cost_bps(profile, 20000.0) is None  # beyond calibration


def test_measured_profile_requires_manifest_hash():
    with pytest.raises(CostModelError, match="manifest"):
        TierCostProfile(
            tier="mid",
            market_cap_min_usd=100e6,
            market_cap_max_usd=1e9,
            sample_count=1,
            half_spread_bps_p50=5.0,
            half_spread_bps_p75=9.0,
            exec_cost_bps_by_notional={},
            exec_cost_p75_bps_by_notional={},
            evidence_class="REAL_PUBLIC_RETAIL",
            source="s",
            captured_at_utc="t",
            manifest_sha256="",
        )


def test_max_viable_turnover_is_budget_over_cost():
    assert max_viable_annual_turnover(100.0, 500.0) == pytest.approx(5.0)
    assert equivalent_total_window_turnover(0.52, 5.75) == pytest.approx(2.99)
    with pytest.raises(CostModelError):
        max_viable_annual_turnover(0.0, 500.0)


def test_default_profiles_are_measured_and_usable():
    from quant_trade.costs.crypto_lowcap import DEFAULT_TIER_PROFILES

    assert {p.tier for p in DEFAULT_TIER_PROFILES} == {"mega", "large", "mid", "low", "micro"}
    for profile in DEFAULT_TIER_PROFILES:
        assert profile.evidence_class == "REAL_PUBLIC_RETAIL"
        assert profile.manifest_sha256  # measured claims carry their bytes hash
        assert profile.sample_count > 0
    low = next(p for p in DEFAULT_TIER_PROFILES if p.tier == "low")
    # 2 x 10 bps assumed taker fee + 23.3 bps measured execution at $1k.
    assert round_trip_taker_cost_bps(low, 1000.0) == pytest.approx(43.3)


# --- measurement runner (fixtures) ------------------------------------------


def _snapshot_bytes(rows: list[tuple[int, str, float]]) -> bytes:
    data = [
        {
            "id": cmc_id,
            "symbol": symbol,
            "name": symbol.title(),
            "cmcRank": i + 1,
            "quotes": [{"marketCap": mcap, "volume24h": mcap * 0.05}],
        }
        for i, (cmc_id, symbol, mcap) in enumerate(rows)
    ]
    return json.dumps({"data": data}).encode()


def _instruments_bytes(bases: list[str]) -> bytes:
    payload = {
        "retCode": 0,
        "result": {
            "list": [
                {"baseCoin": base, "quoteCoin": "USDT", "status": "Trading"}
                for base in bases
            ]
        },
    }
    return json.dumps(payload).encode()


def _fixture_fetcher(tmp_responses: dict[str, bytes]):
    def fetch(url: str) -> bytes:
        for key, value in tmp_responses.items():
            if key in url:
                return value
        raise AssertionError(f"unexpected url in test: {url}")

    return fetch


def test_measurement_aggregates_tiers_and_writes_receipts(tmp_path):
    responses = {
        "start=1": _snapshot_bytes(
            [(1, "AAA", 500e6), (2, "BBB", 50e6), (3, "USDT", 100e9), (4, "CCC", 60e6)]
        ),
        "start=5001": b"{}",  # short tail: parse fails, loop breaks — not an error
        "instruments-info": _instruments_bytes(["AAA", "BBB", "USDT"]),
        "symbol=AAAUSDT": _book_bytes("AAAUSDT"),
        "symbol=BBBUSDT": _book_bytes(
            "BBBUSDT",
            bids=[["9.9", "100"], ["9.8", "100"]],
            asks=[["10.1", "100"], ["10.2", "100"]],
        ),
    }
    result = run_cost_measurement(
        tmp_path, snapshot_date="2026-08-03", fetcher=_fixture_fetcher(responses)
    )
    assert result.status == "OK"
    assert result.symbols_measured == 2  # USDT excluded as stable, CCC not on Bybit
    assert result.tiers["mid"].sample_count == 1
    assert result.tiers["low"].sample_count == 1
    # BBB: mid 10.0, spread 0.2 -> half-spread = 100 bps
    assert result.tiers["low"].half_spread_bps_p50 == pytest.approx(100.0)
    # $100 fits level one on both sides for both books.
    assert result.tiers["mid"].exec_cost_bps_by_notional_p50[100.0] == pytest.approx(200.0)
    assert (tmp_path / "receipts.jsonl").exists()
    assert (tmp_path / "measurement.json").exists()
    assert result.manifest_sha256
    # Unfillable calibration sizes are a refusal, not a number.
    assert result.tiers["mid"].exec_cost_bps_by_notional_p50[10000.0] is None
    assert result.tiers["mid"].executable_fraction_by_notional[10000.0] == 0.0


def test_measurement_records_blocked_network_verbatim(tmp_path):
    def blocked(url: str) -> bytes:
        raise OSError("egress denied by policy")

    result = run_cost_measurement(tmp_path, snapshot_date="2026-08-03", fetcher=blocked)
    assert result.status == "NOT_RUN_NETWORK_BLOCKED"
    assert "egress denied by policy" in result.error
    assert (tmp_path / "measurement_attempts.jsonl").exists()


def test_measurement_rejects_garbage_snapshot(tmp_path):
    responses = {"start=1": b'{"data": "nope"}'}
    result = run_cost_measurement(
        tmp_path, snapshot_date="2026-08-03", fetcher=_fixture_fetcher(responses)
    )
    assert result.status == "NOT_RUN_PARSE_REJECTED"
    assert "snapshot" in result.error
