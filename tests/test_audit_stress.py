"""Stress tests remove the best outcomes and report what is left, exactly."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
from audit_fixtures import csv_bytes, positive_drift, trades_frame

from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.report import render_html
from quant_trade.audit.schema import DeclaredMetadata, build_inputs
from quant_trade.audit.stress import returns_stress, trades_stress
from quant_trade.core.models import Trade

NOW = datetime(2026, 1, 1, tzinfo=UTC)
START = datetime(2024, 1, 1, tzinfo=UTC)


def _trade(pnl: float, day: int) -> Trade:
    entry = START + timedelta(days=day)
    return Trade(
        entry_time=entry,
        exit_time=entry + timedelta(hours=5),
        quantity=1.0,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        pnl=pnl,
        return_pct=pnl / 100.0,
    )


def _rows(block):
    return {row["scenario"]: row for row in block["rows"]}


def test_trades_without_the_best_are_summed_exactly_with_fees_kept() -> None:
    pnls = [100.0, 50.0, 10.0, -5.0, -5.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, -20.0]
    trades = [_trade(p, 3 * i) for i, p in enumerate(pnls)]
    out = trades_stress(trades, fees_total=4.0)
    assert out["status"] == "MEASURED"
    assert out["original"]["value"] == sum(pnls) - 4.0
    rows = _rows(out)
    assert rows["best_1_trades"]["result"]["value"] == sum(pnls) - 100.0 - 4.0
    top5 = 100.0 + 50.0 + 10.0 + 1.0 + 1.0
    assert rows["best_5_trades"]["result"]["value"] == sum(pnls) - top5 - 4.0
    assert rows["best_5_trades"]["stays_positive"] is False
    # 10 % of 12 trades rounds up to 2.
    assert rows["best_10pct_trades"]["removed"] == 2
    assert rows["best_10pct_trades"]["result"]["value"] == sum(pnls) - 150.0 - 4.0
    assert out["top5_share"]["value"] == top5 / (sum(pnls) - 4.0)


def test_best_exit_month_is_removed_whole() -> None:
    trades = [_trade(10.0, 0), _trade(10.0, 1), _trade(50.0, 40), _trade(-3.0, 70)]
    rows = _rows(trades_stress(trades))
    month = rows["best_month"]
    assert month["month"] == "2024-02"
    assert month["removed"] == 1
    assert month["result"]["value"] == 17.0


def test_too_few_trades_is_not_measured() -> None:
    assert trades_stress([_trade(1.0, 0)])["status"] == "NOT_MEASURED"


def test_curve_without_best_periods_compounds_the_rest() -> None:
    returns = np.array([0.10, -0.02, 0.01, 0.03, -0.01, 0.02, 0.0, 0.05, -0.03, 0.01, 0.02, 0.01])
    equity = 100.0 * np.cumprod(np.concatenate([[1.0], 1.0 + returns]))
    stamps = pd.date_range("2024-01-01", periods=len(equity), freq="7D", tz="UTC")
    frame = pd.DataFrame({"timestamp": stamps, "equity": equity})
    out = returns_stress(frame)
    assert out["status"] == "MEASURED"
    assert np.isclose(out["original"]["value"], np.prod(1 + returns) - 1)
    rows = _rows(out)
    best5 = np.sort(returns)[::-1][:5]
    kept = np.prod(1 + returns) / np.prod(1 + best5) - 1
    assert np.isclose(rows["best_5_periods"]["result"]["value"], kept)
    assert "best_10_periods" in rows
    assert "best_1pct_periods" in rows and rows["best_1pct_periods"]["removed"] == 1
    assert rows["best_month"]["month"] == "2024-01"


def test_short_curve_skips_rows_it_cannot_compute() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=7, freq="D", tz="UTC"),
            "equity": [100, 101, 102, 101, 103, 104, 105],
        }
    )
    rows = _rows(returns_stress(frame))
    assert "best_10_periods" not in rows
    assert "best_5_periods" in rows


def test_engine_and_report_carry_the_stress_tests() -> None:
    inputs = build_inputs(
        csv_bytes(positive_drift(600)),
        DeclaredMetadata(trials=1),
        trades_bytes=csv_bytes(trades_frame(30)),
    )
    result = run_audit(inputs, now=NOW, audit_id="stress1", bootstrap_samples=200)
    assert result.stress is not None
    assert result.stress["returns"]["status"] == "MEASURED"
    assert result.stress["trades"]["status"] == "MEASURED"
    for locale, title in (("es", "Pruebas de estrés"), ("en", "Stress tests")):
        page = render_html(result, watermark=False, free_mode=False, locale=locale)
        assert title in page
        assert find_claims(page) == []
    locked = render_html(result, watermark=True, free_mode=False, checkout_url="/c")
    assert "Qué queda sin sus mejores operaciones y meses" in locked  # what payment unlocks
    assert "Sin el mejor mes" not in locked  # the table itself is locked


def test_older_results_without_stress_still_render() -> None:
    inputs = build_inputs(csv_bytes(positive_drift(300)), DeclaredMetadata())
    result = run_audit(inputs, now=NOW, audit_id="stress2", bootstrap_samples=200)
    old = result.model_copy(update={"stress": None})
    assert "Pruebas de estrés" in render_html(old, watermark=False, free_mode=False)
