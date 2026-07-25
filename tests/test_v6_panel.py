"""HistoricalCarryPanel: parsers, point-in-time join, gaps, E2E, CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_trade.carry.panel import (
    build_carry_panel,
    panel_to_research_inputs,
    parse_bybit_kline_page,
)
from quant_trade.carry.panel_backfill import run_panel_backfill

SPOT = Path("tests/fixtures/bybit_kline_spot.json")
SINCE, UNTIL = 1784505600000, 1784649600000

FIXTURES = {
    "spot": "tests/fixtures/bybit_kline_spot.json",
    "perp": "tests/fixtures/bybit_kline_perp.json",
    "mark": "tests/fixtures/bybit_kline_mark.json",
    "index": "tests/fixtures/bybit_kline_index.json",
    "funding": "tests/fixtures/bybit_funding_history.json",
}


def _series(kind: str):
    return parse_bybit_kline_page(
        Path(FIXTURES[kind]).read_bytes(), symbol="BTC", kind=kind
    )


def _settlements():
    payload = json.loads(Path(FIXTURES["funding"]).read_text())
    return [
        {"settled_at_ms": int(r["fundingRateTimestamp"]), "rate": float(r["fundingRate"])}
        for r in payload["result"]["list"]
    ]


def test_kline_parser_sorts_validates_and_checks_identity():
    rows = _series("spot")
    assert len(rows) == 41
    starts = [r["start_ms"] for r in rows]
    assert starts == sorted(starts)
    assert all(r["close"] > 0 for r in rows)
    with pytest.raises(ValueError, match="identity mismatch"):
        parse_bybit_kline_page(SPOT.read_bytes(), symbol="ETH", kind="spot")
    with pytest.raises(ValueError, match="retCode"):
        parse_bybit_kline_page(
            json.dumps({"retCode": 10001, "retMsg": "bad"}).encode(),
            symbol="BTC",
            kind="spot",
        )


def test_panel_joins_all_series_and_attaches_settlements_causally():
    rows, audit = build_carry_panel(
        venue="bybit",
        symbol="BTC",
        spot=_series("spot"),
        perp=_series("perp"),
        mark=_series("mark"),
        index=_series("index"),
        settlements=_settlements(),
    )
    assert audit.is_clean
    assert audit.rows == 41
    assert audit.coverage_ratio == 1.0
    assert audit.settlements == 6
    # settlements land in exactly the bar containing their instant, once each
    attached = [s for r in rows for s in r["funding_settlements"]]
    assert len(attached) == 6
    # mark is the perp price source; the spread is a labelled proxy
    assert all(r["spread_source"] == "proxy_ohlcv_close" for r in rows)
    assert all(r["mark_close"] != r["spot_close"] for r in rows)


def test_panel_never_forward_fills_gaps():
    perp = [r for r in _series("perp") if r["start_ms"] not in (SINCE + 3600_000 * 5,)]
    rows, audit = build_carry_panel(
        venue="bybit",
        symbol="BTC",
        spot=_series("spot"),
        perp=perp,
        mark=_series("mark"),
        index=_series("index"),
        settlements=_settlements(),
    )
    assert audit.missing_bars == 1
    assert not audit.is_clean
    assert len(rows) == 40  # the gap bar simply does not exist


def test_signal_series_is_settlement_driven():
    rows, _ = build_carry_panel(
        venue="bybit",
        symbol="BTC",
        spot=_series("spot"),
        perp=_series("perp"),
        mark=_series("mark"),
        index=_series("index"),
        settlements=_settlements(),
    )
    snapshots, settlements, signal = panel_to_research_inputs(rows, provenance="test_only")
    assert len(snapshots) == len(signal) == 41
    assert len(settlements) == 6
    # before the first settlement the signal is 0; after each settlement it
    # steps to that settled rate and HOLDS until the next one (never a poll)
    assert signal[0] == pytest.approx(0.00012)  # first settlement at bar 0
    assert signal[1] == pytest.approx(0.00012)  # held between settlements
    assert signal[-1] == pytest.approx(0.00013)  # last settled rate


def test_e2e_recorded_pages_to_promotion(tmp_path):
    """recorded raw → receipts → panel → ledger → research → artifacts → promotion."""
    import yaml

    from quant_trade.carry.promote import reproduce_campaign
    from quant_trade.carry.research import run_carry_research, write_carry_artifacts

    result = run_panel_backfill(
        "bybit", "BTC", tmp_path / "panel", since_ms=SINCE, until_ms=UNTIL,
        fixture_pages=FIXTURES,
    )
    assert result.status == "OK"
    assert result.audit["is_clean"]
    with open("configs/carry/cash_and_carry_synthetic.yaml") as fh:
        cfg = yaml.safe_load(fh)
    cfg["data"] = {"source": "panel", "path": str(tmp_path / "panel")}
    cfg["signal"] = {"entry_threshold": 0.0, "trailing_window": 3}
    research = run_carry_research(cfg)
    assert research.ledger_summary["reconciled"] is True
    claimed = tmp_path / "claimed"
    write_carry_artifacts(claimed, cfg, research)
    report = reproduce_campaign(cfg, claimed, rebuild_dir=tmp_path / "rebuild")
    # byte-for-byte reproducible AND honestly non-promotable (fixtures)
    assert report.reproduced is True
    assert report.status == "REJECTED"


def test_backfill_is_idempotent_and_receipted(tmp_path):
    from quant_trade.evidence.receipts import load_receipts, resolve_dir_provenance

    out = tmp_path / "panel"
    first = run_panel_backfill(
        "bybit", "BTC", out, since_ms=SINCE, until_ms=UNTIL, fixture_pages=FIXTURES
    )
    receipts = load_receipts(out / "receipts.jsonl")
    assert len(receipts) == first.pages_fetched + 1  # four series + funding
    assert {r["source_kind"] for r in receipts} == {"fixture"}
    prov = resolve_dir_provenance(out / "receipts.jsonl")
    assert prov.provenance == "test_only"
    # re-run: content-addressed raw pages do not duplicate on disk
    raw_count = len(list((out / "raw").iterdir()))
    run_panel_backfill(
        "bybit", "BTC", out, since_ms=SINCE, until_ms=UNTIL, fixture_pages=FIXTURES
    )
    assert len(list((out / "raw").iterdir())) == raw_count


def test_blocked_network_records_not_run(tmp_path):
    def blocked(url: str) -> bytes:
        raise OSError("Tunnel connection failed: 403 Forbidden")

    result = run_panel_backfill(
        "bybit", "BTC", tmp_path / "panel", since_ms=SINCE, until_ms=UNTIL,
        fetcher=blocked,
    )
    assert result.status == "NOT_RUN_NETWORK_BLOCKED"
    assert "403" in result.error
    log = (tmp_path / "panel" / "backfill_attempts.jsonl").read_text()
    assert "NOT_RUN_NETWORK_BLOCKED" in log


def test_cli_backfill_panel_and_audit(tmp_path):
    from typer.testing import CliRunner

    from quant_trade.cli import app

    runner = CliRunner()
    out = tmp_path / "panel"
    built = runner.invoke(
        app,
        [
            "carry",
            "backfill-panel",
            "--venue",
            "bybit",
            "--symbol",
            "BTC",
            "--output",
            str(out),
            "--since-ms",
            str(SINCE),
            "--until-ms",
            str(UNTIL),
            "--fixture-dir",
            "tests/fixtures",
        ],
    )
    assert built.exit_code == 0, built.output
    assert "panel_rows=41" in built.output.replace(" ", "").replace("\n", "")
    audited = runner.invoke(app, ["carry", "panel-audit", "--panel-dir", str(out)])
    assert audited.exit_code == 0, audited.output
    assert "CLEAN" in audited.output
    assert "test_only" in audited.output
