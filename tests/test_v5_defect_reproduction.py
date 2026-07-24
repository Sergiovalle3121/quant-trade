"""V5 P0 reproduction: fictitious-profit mechanisms that must be closed.

Each test encodes behaviour the platform MUST have. They are xfail(strict=True)
while the defect stands; the marker is removed as each block fixes its defect.
"""

from __future__ import annotations

import pytest
import yaml

from quant_trade.carry.research import run_carry_research
from quant_trade.carry.store import FundingObservation, append_observations


def _obs(minute: int, *, venue="binance", symbol="BTC", spot=64000.0, perp=64010.0,
         rate=0.001, hour: int = 0) -> FundingObservation:
    ts = f"2026-07-20T{hour:02d}:{minute:02d}:00Z"
    return FundingObservation(
        venue=venue,
        symbol=symbol,
        captured_at_utc=ts,
        exchange_timestamp_utc=ts,
        spot_bid=spot - 0.5,
        spot_ask=spot + 0.5,
        perp_bid=perp - 0.5,
        perp_ask=perp + 0.5,
        perp_mark=perp,
        perp_index=spot,
        realized_funding_rate=rate,
        source_name="test",
    )


def _campaign_config(path) -> dict:
    cfg = yaml.safe_load(open("configs/carry/cash_and_carry_synthetic.yaml"))
    cfg["data"] = {"source": "jsonl_observations", "path": str(path)}
    cfg["signal"] = {"entry_threshold": -1.0, "trailing_window": 1}
    return cfg


# --- P0-A: strict economic identity ---------------------------------------


@pytest.mark.xfail(reason="P0-A: mixed instruments share one return series", strict=True)
def test_p0a_mixed_symbols_fail_closed(tmp_path):
    # Alternating BTC (64k) and ETH (3k) observations in one store: global
    # timestamp ordering would compute 64k->3k "price moves" as basis P&L.
    store = tmp_path / "mixed_symbols.jsonl"
    rows = []
    for i in range(0, 40):
        sym = "BTC" if i % 2 == 0 else "ETH"
        px = 64000.0 if sym == "BTC" else 3000.0
        rows.append(_obs(minute=i % 60, hour=i // 60, symbol=sym, spot=px, perp=px * 1.0002))
    append_observations(store, rows)
    with pytest.raises(ValueError, match="identit"):
        run_carry_research(_campaign_config(store))


@pytest.mark.xfail(reason="P0-A: mixed venues share one return series", strict=True)
def test_p0a_mixed_venues_fail_closed(tmp_path):
    store = tmp_path / "mixed_venues.jsonl"
    rows = []
    for i in range(0, 40):
        venue = "binance" if i % 2 == 0 else "okx"
        px = 64000.0 if venue == "binance" else 63950.0
        rows.append(_obs(minute=i % 60, hour=i // 60, venue=venue, spot=px, perp=px * 1.0002))
    append_observations(store, rows)
    with pytest.raises(ValueError, match="identit"):
        run_carry_research(_campaign_config(store))


# --- P0-B: polls are not settlements ---------------------------------------


@pytest.mark.xfail(reason="P0-B: every poll accrues funding as if settled", strict=True)
def test_p0b_ninety_polls_are_not_ninety_settlements(tmp_path):
    # 90 polls of the SAME 8h funding rate, five minutes apart. The position
    # can only ever collect that funding ONCE (at the settlement); today each
    # observation accrues it again (~89x overcount).
    store = tmp_path / "polls.jsonl"
    rows = [
        _obs(minute=(i * 5) % 60, hour=(i * 5) // 60, rate=0.001) for i in range(90)
    ]
    append_observations(store, rows)
    result = run_carry_research(_campaign_config(store))
    total_funding = float(result.net_return_series["funding_pnl"].sum())
    assert total_funding <= 0.001 + 1e-12, (
        f"90 polls accrued {total_funding:.4f} of funding; at most one settlement "
        "(0.001) fits in the window"
    )
