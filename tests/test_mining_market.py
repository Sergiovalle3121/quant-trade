"""Tests for read-only mining market snapshots and hashprice methods."""

from __future__ import annotations

import pytest

from quant_trade.mining.market import (
    FakeMiningMarketAdapter,
    MiningMarketData,
    bottom_up_hashprice,
    compare_hashprice,
    load_market_from_record,
    require_fresh,
    validate_market_record,
)


def _market(**overrides) -> MiningMarketData:
    base = dict(
        coin="BTC",
        algorithm="sha256",
        coin_price_usd=60000.0,
        network_hashrate_hs=6.0e20,  # 600 EH/s
        difficulty=8.0e13,
        block_subsidy_coin=3.125,
        tx_fee_revenue_coin_per_block=0.15,
        blocks_per_day=144.0,
        captured_at_utc="2024-05-01T00:00:00Z",
        source_name="unit_test",
        source_url="https://example.test/snapshot",
        pool_fee_rate=0.01,
    )
    base.update(overrides)
    return MiningMarketData(**base)


def test_bottom_up_hashprice_matches_hand_calc():
    m = _market()
    coin_per_block = 3.125 + 0.15
    coin_per_th_day = coin_per_block * 144.0 / (6.0e20 / 1e12)
    expected = coin_per_th_day * 60000.0
    assert bottom_up_hashprice(m) == pytest.approx(expected)


def test_compare_hashprice_flags_divergence():
    bottom = bottom_up_hashprice(_market())
    # a direct quote within tolerance -> no alert
    close = compare_hashprice(_market(direct_hashprice_usd_per_th_day=bottom * 1.05))
    assert not close.diverges and close.alert is None
    # a direct quote far from bottom-up -> alert
    far = compare_hashprice(_market(direct_hashprice_usd_per_th_day=bottom * 1.5))
    assert far.diverges
    assert far.alert and "diverge" in far.alert


def test_no_direct_quote_returns_bottom_up_only():
    cmp = compare_hashprice(_market())
    assert cmp.direct_usd_per_th_day is None
    assert cmp.relative_divergence is None
    assert not cmp.diverges


def test_stale_snapshot_fails_closed():
    fresh = _market(staleness_seconds=10.0, max_age_seconds=3600.0)
    assert require_fresh(fresh) is fresh
    stale = _market(staleness_seconds=99999.0, max_age_seconds=3600.0)
    assert stale.is_stale
    with pytest.raises(ValueError, match="stale"):
        require_fresh(stale)


def test_validation_and_attribution():
    errors = validate_market_record({"coin": "BTC"})
    assert any("network_hashrate_hs" in e for e in errors)
    assert any("source_name" in e for e in errors)
    with pytest.raises(ValueError, match="invalid market record"):
        load_market_from_record({"coin": "BTC"})


def test_fake_adapter_returns_snapshot():
    adapter = FakeMiningMarketAdapter(_market())
    got = adapter.fetch("btc")
    assert got.coin == "BTC"
    with pytest.raises(ValueError, match="no snapshot"):
        adapter.fetch("ETH")
