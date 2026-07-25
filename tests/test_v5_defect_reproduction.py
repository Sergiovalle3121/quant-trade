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
    with open("configs/carry/cash_and_carry_synthetic.yaml") as fh:
        cfg = yaml.safe_load(fh)
    cfg["data"] = {"source": "jsonl_observations", "path": str(path)}
    cfg["signal"] = {"entry_threshold": -1.0, "trailing_window": 1}
    return cfg


# --- P0-A: strict economic identity ---------------------------------------


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


# --- adversarial semantics (V5-1) ------------------------------------------


def test_settlement_accrues_exactly_once_and_dedups(tmp_path):
    import dataclasses

    store = tmp_path / "with_settlement.jsonl"
    rows = [_obs(minute=(i * 5) % 60, hour=(i * 5) // 60, rate=0.001) for i in range(24)]
    settlement = dataclasses.replace(
        _obs(minute=0, hour=1, rate=0.001), source_event="funding_settlement"
    )
    append_observations(store, rows)
    # append the settlement twice: dedup by funding time keeps one
    r1 = append_observations(store, [settlement])
    r2 = append_observations(store, [settlement])
    assert r1.appended == 1 and r2.appended == 0
    result = run_carry_research(_campaign_config(store))
    total_funding = float(result.net_return_series["funding_pnl"].sum())
    # the ledger accrues funding on the PERP NOTIONAL (≈ half the capital at
    # 1x leverage), and the duplicated settlement must count exactly ONCE:
    # one 0.001 settlement on ~0.5 capital ≈ 0.0005, never ~0.001 (twice)
    assert total_funding > 0.0
    assert total_funding < 0.001 * 0.75, "duplicated settlement was double-counted"
    assert total_funding == pytest.approx(0.001 * 0.5, rel=0.05)


def test_prediction_never_enters_realized_pnl(tmp_path):
    import dataclasses

    store = tmp_path / "with_prediction.jsonl"
    rows = [_obs(minute=(i * 5) % 60, hour=(i * 5) // 60, rate=0.0) for i in range(24)]
    prediction = dataclasses.replace(
        _obs(minute=30, hour=0, rate=0.05), source_event="funding_prediction"
    )
    append_observations(store, rows + [prediction])
    result = run_carry_research(_campaign_config(store))
    assert float(result.net_return_series["funding_pnl"].sum()) == 0.0


def test_raw_tamper_invalidates_observation():
    import hashlib

    from quant_trade.carry.store import verify_raw_payload

    raw = b'{"fundingRate":"0.0001"}'
    record = {"raw_sha256": hashlib.sha256(raw).hexdigest()}
    assert verify_raw_payload(record, raw)
    assert not verify_raw_payload(record, raw + b" ")
    assert not verify_raw_payload({"raw_sha256": ""}, raw)


def test_concurrent_collectors_do_not_duplicate(tmp_path):
    import threading

    store = tmp_path / "concurrent.jsonl"
    rows = [_obs(minute=(i * 5) % 60, hour=(i * 5) // 60) for i in range(30)]
    threads = [
        threading.Thread(target=append_observations, args=(store, rows)) for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    from quant_trade.carry.store import read_store

    stored = read_store(store)
    assert len(stored.records) == 30  # no duplicates, no torn lines
    assert stored.quarantined == []


def test_excessive_clock_skew_fails_closed(tmp_path):
    import dataclasses

    store = tmp_path / "skewed.jsonl"
    good = [_obs(minute=(i * 5) % 60, hour=(i * 5) // 60) for i in range(10)]
    skewed = dataclasses.replace(
        _obs(minute=55, hour=1), captured_at_utc="2026-07-20T03:00:00Z"
    )
    append_observations(store, good + [skewed])
    with pytest.raises(ValueError, match="clock skew"):
        run_carry_research(_campaign_config(store))


def test_mixed_provenance_is_never_real(tmp_path):
    # A dataset mixing synthetic-labelled and real-labelled records must never
    # evaluate as real: the manifest labels it "mixed" and sufficiency fails.
    import dataclasses

    from quant_trade.carry.data import synthetic_funding_snapshots, write_snapshots_json

    snaps = synthetic_funding_snapshots(periods=120, seed=1)
    half_real = [
        dataclasses.replace(s, data_source="real") if i % 2 == 0 else s
        for i, s in enumerate(snaps)
    ]
    path = write_snapshots_json(tmp_path / "mixed_prov.json", half_real)
    with open("configs/carry/cash_and_carry_synthetic.yaml") as fh:
        cfg = yaml.safe_load(fh)
    cfg["data"] = {"source": "json", "path": str(path)}
    result = run_carry_research(cfg)
    assert result.decision == "NOT_RUN_INSUFFICIENT_REAL_DATA"
    assert result.dataset_manifest["data_source"] == "mixed"
