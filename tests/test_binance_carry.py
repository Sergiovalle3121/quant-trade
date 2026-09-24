"""Binance archive venue and the H1-BIN pre-registration (offline, no network)."""

from __future__ import annotations

import io
import zipfile

import pytest

from quant_trade.evidence.canonical_json import sha256_of_bytes
from quant_trade.v8.backfill import ChecksumMismatch, binance_archive_get
from quant_trade.v8.venues import (
    IdentityMismatch,
    VenueErrorResponse,
    instruments_url,
    parse_binance_funding,
    parse_binance_kline,
    series_spec,
    server_time_url,
)
from quant_trade.v9 import binance_carry_registration as reg

JAN_2024_MS = 1_704_067_200_000


def _zip(name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, text)
    return buffer.getvalue()


KLINE_ROW = "{ts},100.0,110.0,90.0,105.0,12.5,{end},1312.5,40,6.0,630.0,0\n"


def test_kline_parser_reads_headerless_millisecond_files() -> None:
    text = KLINE_ROW.format(ts=JAN_2024_MS, end=JAN_2024_MS + 3_599_999)
    rows = parse_binance_kline(_zip("BTCUSDT-1h-2024-01.csv", text), symbol="BTC", kind="perp")
    assert rows == [
        {
            "start_ms": JAN_2024_MS,
            "open": 100.0,
            "high": 110.0,
            "low": 90.0,
            "close": 105.0,
            "volume": 12.5,
            "quote_volume": 1312.5,
        }
    ]


def test_kline_parser_skips_header_and_converts_microseconds() -> None:
    header = "open_time,open,high,low,close,volume,close_time,quote_volume,count,a,b,ignore\n"
    text = header + KLINE_ROW.format(ts=JAN_2024_MS * 1000, end=(JAN_2024_MS + 3_599_999) * 1000)
    rows = parse_binance_kline(_zip("BTCUSDT-1h-2025-01.csv", text), symbol="BTC", kind="spot")
    assert rows[0]["start_ms"] == JAN_2024_MS


def test_mark_and_index_klines_carry_no_volume() -> None:
    text = KLINE_ROW.format(ts=JAN_2024_MS, end=JAN_2024_MS + 3_599_999)
    rows = parse_binance_kline(_zip("BTCUSDT-1h-2024-01.csv", text), symbol="BTC", kind="mark")
    assert "volume" not in rows[0]


def test_parser_refuses_another_symbols_file() -> None:
    text = KLINE_ROW.format(ts=JAN_2024_MS, end=JAN_2024_MS + 3_599_999)
    with pytest.raises(IdentityMismatch):
        parse_binance_kline(_zip("ETHUSDT-1h-2024-01.csv", text), symbol="BTC", kind="perp")


def test_parser_refuses_a_non_zip_payload() -> None:
    with pytest.raises(VenueErrorResponse):
        parse_binance_kline(b"<html>not found</html>", symbol="BTC", kind="perp")


def test_funding_parser_snaps_calc_latency_and_keeps_the_raw_stamp() -> None:
    text = (
        "calc_time,funding_interval_hours,last_funding_rate\n"
        f"{JAN_2024_MS + 1},8,0.0001\n"
        f"{JAN_2024_MS + 8 * 3_600_000},8,-0.00002\n"
    )
    rows = parse_binance_funding(_zip("BTCUSDT-fundingRate-2024-01.csv", text), symbol="BTC")
    assert [r["settled_at_ms"] for r in rows] == [JAN_2024_MS, JAN_2024_MS + 8 * 3_600_000]
    assert rows[0]["calc_time_ms"] == JAN_2024_MS + 1
    assert rows[1]["rate"] == -0.00002
    assert {r["rate_field"] for r in rows} == {"last_funding_rate"}


def test_funding_parser_refuses_a_kline_file() -> None:
    with pytest.raises(IdentityMismatch):
        parse_binance_funding(_zip("BTCUSDT-1h-2024-01.csv", "1,8,0.1\n"), symbol="BTC")


def test_archive_urls_walk_one_month_per_file() -> None:
    spec = series_spec("binance", "mark")
    url = spec.build_url(symbol="BTC", kind="mark", cursor_ms=JAN_2024_MS, interval_minutes=60)
    assert url == (
        "https://data.binance.vision/data/futures/um/monthly/markPriceKlines/"
        "BTCUSDT/1h/BTCUSDT-1h-2024-01.zip"
    )
    previous = spec.build_url(
        symbol="BTC", kind="mark", cursor_ms=JAN_2024_MS - 1, interval_minutes=60
    )
    assert previous.endswith("BTCUSDT-1h-2023-12.zip")
    funding = series_spec("binance", "funding").build_url(
        symbol="BTC", kind="funding", cursor_ms=JAN_2024_MS, interval_minutes=60
    )
    assert funding.endswith("/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2024-01.zip")


def test_archive_has_no_clock_or_instrument_endpoint() -> None:
    assert server_time_url("binance") is None
    assert instruments_url("binance", "BTC") is None


def test_archive_fetch_requires_the_venue_checksum(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"zip-bytes"
    published = {"value": sha256_of_bytes(payload)}

    def fake_http_get(url: str, *, timeout_seconds: float = 20.0):
        if url.endswith(".CHECKSUM"):
            return 200, f"{published['value']}  file.zip\n".encode(), {}
        return 200, payload, {}

    monkeypatch.setattr("quant_trade.v8.backfill.http_get", fake_http_get)
    assert binance_archive_get("https://data.binance.vision/x.zip")[1] == payload
    published["value"] = "0" * 64
    with pytest.raises(ChecksumMismatch):
        binance_archive_get("https://data.binance.vision/x.zip")


def test_registration_is_pinned() -> None:
    assert reg.freeze_hash() == reg.FROZEN_HASH


def test_registration_reuses_h1_variants_and_gates_unchanged() -> None:
    from quant_trade.v8.preregistration import H1, PROMOTION_GATES

    payload = reg.registration()
    assert [v["parameters"] for v in payload["variants"]] == [v.parameters for v in H1.variants]
    for name, value in PROMOTION_GATES.items():
        assert payload["gates"][name] == value
    assert payload["gates"]["require_positive_holdout"] is True


# --- end-to-end runner on a synthetic archive (offline, TEST_ONLY) -----------

HOUR_MS = 3_600_000
MARK_GAP_DAY = (JAN_2024_MS + 9 * 86_400_000) // 86_400_000
SPOT_OUTAGE_MS = JAN_2024_MS + 14 * 86_400_000 + 5 * HOUR_MS


def _fake_archive(url: str) -> tuple[int, bytes, dict[str, str]]:
    """Serve synthetic monthly archive ZIPs for Jan-Feb 2024."""
    import calendar
    import math

    name = url.rsplit("/", 1)[-1].removesuffix(".zip")
    daily = "/daily/" in url
    parts = name.split("-")
    year, month = int(parts[-3 if daily else -2]), int(parts[-2 if daily else -1])
    day = int(parts[-1]) if daily else 1
    start = calendar.timegm((year, month, day, 0, 0, 0)) * 1000
    days = 1 if daily else calendar.monthrange(year, month)[1]
    if "fundingRate" in url:
        lines = []
        for index in range(days * 3):
            stamp = start + index * 8 * HOUR_MS
            rate = 0.0003 if (stamp // (5 * 24 * HOUR_MS)) % 3 else -0.0001
            lines.append(f"{stamp + 1},8,{rate}")
        text = "\n".join(lines) + "\n"
    else:
        premium = 1.0005 if "/klines/" in url and "/futures/" in url else 1.0
        lines = []
        for index in range(days * 24):
            stamp = start + index * HOUR_MS
            if "markPrice" in url and not daily and stamp // 86_400_000 == MARK_GAP_DAY:
                continue  # the monthly file omits a day that the daily file has
            if "/spot/" in url and stamp == SPOT_OUTAGE_MS:
                continue  # the venue never published this bar
            price = 40_000.0 * (1.0 + 0.05 * math.sin(stamp / (7 * 24 * HOUR_MS))) * premium
            if daily and "/spot/" in url and stamp == SPOT_OUTAGE_MS - HOUR_MS:
                price *= 1.001  # the daily file disagrees with the monthly one
            lines.append(
                f"{stamp},{price},{price * 1.001},{price * 0.999},{price},10,"
                f"{stamp + HOUR_MS - 1},{price * 10},5,5,{price * 5},0"
            )
        text = "\n".join(lines) + "\n"
    return 200, _zip(f"{name}.csv", text), {}


def _synthetic_evidence(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from quant_trade.v8.backfill import BackfillRequest, run_backfill
    from quant_trade.v8.panel_builder import build_panel_from_evidence

    since, until = JAN_2024_MS, JAN_2024_MS + 60 * 24 * HOUR_MS - HOUR_MS
    request = BackfillRequest(venue="binance", symbol="BTC", since_ms=since, until_ms=until)
    result = run_backfill(
        request,
        tmp_path / "evidence",
        fetcher=_fake_archive,
        sleeper=lambda _s: None,
        clock=lambda: 0.0,
        source_kind="recorded_test_response",
        captured_at_utc="2026-09-24T00:00:00Z",
    )
    assert result.status == "OK", result.errors
    build_panel_from_evidence(
        result.evidence_dir,
        venue="binance",
        symbol="BTC",
        since_ms=since,
        until_ms=until,
        provenance="test_only",
    )
    monkeypatch.setattr(reg, "SINCE_UTC", "2024-01-01T00:00:00Z")
    monkeypatch.setattr(reg, "UNTIL_UTC", "2024-02-29T23:00:00Z")
    walk = dict(reg.SPLITS["walk_forward"], min_selection_rows=48, test_size=72, step_size=72)
    monkeypatch.setitem(reg.SPLITS, "walk_forward", walk)
    monkeypatch.setattr(reg, "FROZEN_HASH", reg.freeze_hash())
    return tmp_path / "evidence"


def test_runner_refuses_test_only_evidence(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from quant_trade.v9.binance_carry import STATE_NOT_MEASURED, run_h1_bin

    root = _synthetic_evidence(tmp_path, monkeypatch)
    payload = run_h1_bin(evidence_root=root, ledger_path=tmp_path / "trials.jsonl")
    assert payload["state"] == STATE_NOT_MEASURED
    assert payload["evidence"]["provenance"] == "test_only"
    assert not (tmp_path / "trials.jsonl").exists()


def test_runner_registers_trials_and_reveals_holdout_once(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant_trade.v8.validation as validation
    from quant_trade.v9.binance_carry import STATE_MEASURED_REJECTED, run_h1_bin
    from quant_trade.v9.trial_ledger import GlobalTrialLedger

    root = _synthetic_evidence(tmp_path, monkeypatch)
    real = validation.sufficiency_report

    def pretend_sufficient(*args, **kwargs):
        report = real(*args, **kwargs)
        return dict(report, sufficient=True, shortfalls=[])

    monkeypatch.setattr(validation, "sufficiency_report", pretend_sufficient)
    ledger_path = tmp_path / "trials.jsonl"
    payload = run_h1_bin(evidence_root=root, ledger_path=ledger_path)

    assert payload["state"] == STATE_MEASURED_REJECTED  # assumed costs never promote
    assert "cost_evidence_promotable" in payload["failed_gates"]
    seal = payload["holdout"]["seal"]
    assert seal["reveal_count"] == 1 and seal["frozen"]
    assert payload["holdout"]["frozen_variant"] in {v["variant_id"] for v in reg.VARIANTS}
    assert payload["walk_forward"]["window_count"] >= 1
    for window in payload["walk_forward"]["windows"]:
        assert window["selection_end_index"] < window["test_start_index"]
    stats = GlobalTrialLedger(ledger_path).stats()
    assert stats.distinct_trials == len(reg.VARIANTS)
    assert stats.chain_intact
    kinds = [r["kind"] for r in GlobalTrialLedger(ledger_path)._read()]
    assert kinds[: len(reg.VARIANTS)] == ["trial"] * len(reg.VARIANTS)
    assert payload["real_money_approved"] is False

    rerun = run_h1_bin(evidence_root=root, ledger_path=ledger_path)
    assert rerun["holdout"]["carry"] == payload["holdout"]["carry"]  # deterministic
    assert GlobalTrialLedger(ledger_path).stats().distinct_trials == len(reg.VARIANTS)


def test_daily_files_fill_monthly_gaps_and_outages_stay_unfilled(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from quant_trade.carry.panel import load_panel

    root = _synthetic_evidence(tmp_path, monkeypatch)
    directory = root / "binance_btc_usdt"
    outages = json.loads((directory / "venue_outages.json").read_text())["bars"]
    assert outages["spot"] == [SPOT_OUTAGE_MS]
    assert outages["mark"] == []
    conflicts = json.loads((directory / "venue_outages.json").read_text())[
        "monthly_daily_conflicts"
    ]
    assert [c["start_ms"] for c in conflicts] == [SPOT_OUTAGE_MS - HOUR_MS]
    rows = load_panel(directory)
    kept = next(r for r in rows if r["start_ms"] == SPOT_OUTAGE_MS - HOUR_MS)
    assert kept["spot_close"] == conflicts[0]["monthly"]["close"]
    stamps = {r["start_ms"] for r in rows}
    assert SPOT_OUTAGE_MS not in stamps  # no row is invented for an outage
    assert MARK_GAP_DAY * 86_400_000 + 3 * HOUR_MS in stamps  # daily file filled it
    manifest = json.loads((directory / "panel_manifest.json").read_text())
    assert manifest["audit"]["venue_outage_bars"] == 1
    assert manifest["audit"]["missing_bars"] == 0


def test_a_declared_outage_that_hides_a_bar_fails_verification(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from quant_trade.carry.panel import load_panel
    from quant_trade.evidence.canonical_json import atomic_write_json, sha256_of_file

    directory = _synthetic_evidence(tmp_path, monkeypatch) / "binance_btc_usdt"
    manifest_path = directory / "panel_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["build_context"]["venue_outage_ms"]["perp"] = [SPOT_OUTAGE_MS]
    atomic_write_json(manifest_path, manifest)
    (directory / "panel_manifest.sha256").write_text(sha256_of_file(manifest_path) + "\n")
    with pytest.raises(ValueError, match="declared outage"):
        load_panel(directory)


# --- ledger margin management ------------------------------------------------


def _rally_snaps(periods: int = 120, growth: float = 0.01):
    """A steady rally: the short perp pays variation margin every bar."""
    import dataclasses

    from quant_trade.carry.data import synthetic_funding_snapshots

    snaps = synthetic_funding_snapshots(periods=periods, seed=3)
    out = []
    for index, snap in enumerate(snaps):
        price = 100.0 * (1.0 + growth) ** index
        out.append(
            dataclasses.replace(
                snap,
                spot_price=price,
                perp_mark_price=price,
                perp_index_price=price,
                realized_funding_rate=0.0005,
            )
        )
    return out


def test_without_rehedge_a_rally_exhausts_the_short_perp_margin() -> None:
    from quant_trade.carry.ledger_engine import run_carry_ledger
    from quant_trade.carry.models import CarryCostModel

    with pytest.raises(ValueError, match="exhausted cash and posted margin"):
        run_carry_ledger(
            _rally_snaps(),
            CarryCostModel(half_spread_bps=1.0),
            entry_threshold=0.0,
            trailing_window=3,
            perp_leverage=3.0,
        )


def test_rehedge_survives_the_rally_and_pays_for_every_rehedge() -> None:
    from quant_trade.carry.ledger_engine import run_carry_ledger
    from quant_trade.carry.models import CarryCostModel

    costs = CarryCostModel(half_spread_bps=1.0)
    result = run_carry_ledger(
        _rally_snaps(),
        costs,
        entry_threshold=0.0,
        trailing_window=3,
        perp_leverage=3.0,
        rehedge_below_margin_fraction=0.5,
        size_on_equity=True,
    )
    assert result.rehedges >= 1
    assert result.entries == result.rehedges + 1
    assert result.reconciled, result.reconciliation_error
    assert result.totals.trading_fees > 0


def test_ledger_defaults_never_rehedge() -> None:
    from quant_trade.carry.ledger_engine import run_carry_ledger
    from quant_trade.carry.models import CarryCostModel

    flat_prices = _rally_snaps(periods=40, growth=0.0)
    result = run_carry_ledger(
        flat_prices, CarryCostModel(), entry_threshold=0.0, trailing_window=3, perp_leverage=3.0
    )
    assert result.rehedges == 0


def test_rehedge_amendment_is_pinned_and_changes_only_margin_mechanics() -> None:
    assert reg.freeze_hash_rehedge() == reg.FROZEN_HASH_REHEDGE
    base, amended = reg.registration(), reg.registration_rehedge()
    for key in ("data", "signal", "splits", "gates", "benchmarks", "falsifiers"):
        assert amended[key] == base[key]
    assert [v["parameters"] for v in amended["variants"]] == [
        v["parameters"] for v in base["variants"]
    ]
    changed = {
        k for k in amended["execution"] if amended["execution"][k] != base["execution"].get(k)
    }
    assert changed == {"rehedge_below_margin_fraction", "rehedge_rule", "size_on_equity"}
