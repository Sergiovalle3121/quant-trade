"""H3 for real: perp-perp cross-venue dispersion with two ledgers (V6-I)."""

from __future__ import annotations

import pytest

from quant_trade.carry.cross_venue import (
    panel_to_dispersion_bars,
    run_perp_perp_dispersion,
)

START = 1784505600000
HOUR = 3600_000


def _bars(marks, settled):
    return [
        {"start_ms": START + i * HOUR, "mark": m, "settled_in_bar": s}
        for i, (m, s) in enumerate(zip(marks, settled, strict=True))
    ]


def test_dispersion_collects_the_settled_spread_and_reconciles():
    n = 30
    # venue B settles +0.002 every bar, venue A settles 0: spread = +0.002
    a = _bars([100.0] * n, [0.0] * n)
    b = _bars([100.0] * n, [0.002] * n)
    result = run_perp_perp_dispersion(
        a, b, venue_a="bybit", venue_b="okx", entry_threshold=0.0005,
        initial_capital=100_000.0,
    )
    assert result.entries == 1
    assert result.totals.funding_spread > 0
    assert result.reconciled, result.reconciliation_error
    # flat marks: zero divergence P&L, profit is pure funding spread net costs
    assert result.totals.mark_divergence_pnl == pytest.approx(0.0)
    assert result.final_equity > 100_000.0


def test_mark_divergence_is_real_pnl_never_concatenated():
    n = 20
    # A rallies 1% while B stays flat; long-A/short-B direction gains it,
    # measured per venue return — prices never cross venues
    a = _bars([100.0 * (1 + 0.0005 * i) for i in range(n)], [0.0] * n)
    b = _bars([100.0] * n, [0.002] * n)
    result = run_perp_perp_dispersion(
        a, b, venue_a="bybit", venue_b="okx", entry_threshold=0.0005,
        initial_capital=100_000.0,
    )
    assert result.totals.mark_divergence_pnl > 0
    assert result.reconciled


def test_costs_are_charged_on_entries_switches_and_terminal_close():
    n = 30
    # spread flips sign midway: entry + one switch + terminal close
    settled_b = [0.002] * 15 + [-0.002] * 15
    a = _bars([100.0] * n, [0.0] * n)
    b = _bars([100.0] * n, settled_b)
    result = run_perp_perp_dispersion(
        a, b, venue_a="bybit", venue_b="okx", entry_threshold=0.0005,
        initial_capital=100_000.0,
    )
    assert result.switches >= 1
    assert result.totals.trading_fees > 0
    assert result.totals.transfer_costs > 0
    assert result.reconciled


def test_insufficient_overlap_fails_closed():
    a = _bars([100.0] * 3, [0.0] * 3)
    b = _bars([100.0] * 3, [0.001] * 3)
    with pytest.raises(ValueError, match="overlapping"):
        run_perp_perp_dispersion(
            a, b, venue_a="bybit", venue_b="okx", entry_threshold=0.0
        )


def test_scanner_runs_h3_on_two_panels_and_stays_test_only(tmp_path):
    from quant_trade.carry.panel_backfill import run_panel_backfill
    from quant_trade.opportunities.trading_scan import scan_trading_opportunities

    fixtures = {
        "spot": "tests/fixtures/bybit_kline_spot.json",
        "perp": "tests/fixtures/bybit_kline_perp.json",
        "mark": "tests/fixtures/bybit_kline_mark.json",
        "index": "tests/fixtures/bybit_kline_index.json",
        "funding": "tests/fixtures/bybit_funding_history.json",
    }
    for name in ("panel_a", "panel_b"):
        run_panel_backfill(
            "bybit", "BTC", tmp_path / name,
            since_ms=1784505600000, until_ms=1784649600000, fixture_pages=fixtures,
        )
    cfg = {
        "hypotheses": [
            {
                "id": "H3",
                "name": "cross venue",
                "kind": "cross_venue_dispersion",
                "venues": [
                    {"venue": "bybit", "panel": str(tmp_path / "panel_a")},
                    {"venue": "okx", "panel": str(tmp_path / "panel_b")},
                ],
                "signal": {"entry_threshold": 0.00001, "trailing_window": 3},
            }
        ]
    }
    result = scan_trading_opportunities(cfg, evaluated_at_utc="2026-07-25T01:00:00Z")
    row = result.rows[0]
    # the engine RAN (metrics exist, ledger reconciled) but fixture panels
    # stay TEST_ONLY: never a candidate
    assert row.metrics["reconciled"] is True
    assert row.status == "NOT_RUN_INSUFFICIENT_REAL_DATA"
    assert row.data_source == "test_only"


def test_panel_rows_convert_to_dispersion_bars():
    rows = [
        {
            "start_ms": START,
            "mark_close": 100.5,
            "funding_settlements": [{"settled_at_ms": START, "rate": 0.001}],
        }
    ]
    bars = panel_to_dispersion_bars(rows)
    assert bars[0] == {"start_ms": START, "mark": 100.5, "settled_in_bar": 0.001}
