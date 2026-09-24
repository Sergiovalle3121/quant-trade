"""The ``/ejemplo`` report: a full audit of synthetic data, built in memory.

A visitor sees what a paid report contains before uploading anything. The
input is an MT5 Strategy Tester report and an optimisation export generated
from a fixed seed: nobody's account, strategy or market data. The engine,
the importers and the renderer are the production ones, so the sample shows
exactly what a client gets, including an unflattering class when the
synthetic data earns one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from quant_trade.audit.engine import run_audit
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs

SAMPLE_SEED = 20260924
SAMPLE_DAYS = 500
SAMPLE_PASSES = 120
#: A fixed clock so the sample (and its hashes) never change between restarts.
SAMPLE_NOW = datetime(2026, 9, 24, tzinfo=UTC)
SAMPLE_BOOTSTRAP = 500


def _money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def synthetic_mt5_report(
    days: int = SAMPLE_DAYS, *, edge_pips: float = 4.0, seed: int = SAMPLE_SEED, lots: float = 0.5
) -> bytes:
    """An MT5 tester HTML report (UTF-16 LE with BOM, as the terminal writes
    it) with one EURUSD round trip per business day. Synthetic by design."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=days)
    balance = 10_000.0
    price = 1.1
    rows = [
        "<tr><td>2023.01.02 00:00:00</td><td>1</td><td></td><td>balance</td><td></td><td></td>"
        "<td></td><td></td><td>0.00</td><td>0.00</td><td>10 000.00</td><td>10 000.00</td>"
        "<td></td></tr>"
    ]
    deal = 2
    for day in dates:
        side = "buy" if rng.random() < 0.5 else "sell"
        sign = 1.0 if side == "buy" else -1.0
        entry = round(price, 5)
        pips = edge_pips + rng.normal(0.0, 25.0)
        exit_price = round(entry + sign * pips * 0.0001, 5)
        price = exit_price
        profit = round(pips * 10.0 * lots, 2)
        stamp = day.strftime("%Y.%m.%d")
        balance -= 3.5
        rows.append(
            f"<tr><td>{stamp} 09:00:00</td><td>{deal}</td><td>EURUSD</td><td>{side}</td>"
            f"<td>in</td><td>{lots}</td><td>{entry:.5f}</td><td>{deal}</td><td>-3.50</td>"
            f"<td>0.00</td><td>0.00</td><td>{_money(balance)}</td><td></td></tr>"
        )
        balance += profit - 3.5
        close = "sell" if side == "buy" else "buy"
        rows.append(
            f"<tr><td>{stamp} 17:00:00</td><td>{deal + 1}</td><td>EURUSD</td><td>{close}</td>"
            f"<td>out</td><td>{lots}</td><td>{exit_price:.5f}</td><td>{deal + 1}</td>"
            f"<td>-3.50</td><td>0.00</td><td>{profit:.2f}</td><td>{_money(balance)}</td>"
            "<td></td></tr>"
        )
        deal += 2
    header = (
        "<tr><td><b>Time</b></td><td><b>Deal</b></td><td><b>Symbol</b></td><td><b>Type</b></td>"
        "<td><b>Direction</b></td><td><b>Volume</b></td><td><b>Price</b></td>"
        "<td><b>Order</b></td><td><b>Commission</b></td><td><b>Swap</b></td>"
        "<td><b>Profit</b></td><td><b>Balance</b></td><td><b>Comment</b></td></tr>"
    )
    end = dates[-1].strftime("%Y.%m.%d")
    html_text = (
        "<html><head><title>Strategy Tester Report</title></head><body><table>"
        "<tr><td colspan='13'><b>Strategy Tester Report</b></td></tr>"
        "<tr><td colspan='3'>Expert:</td><td colspan='10'><b>SyntheticSampleEA</b></td></tr>"
        "<tr><td colspan='3'>Symbol:</td><td colspan='10'><b>EURUSD</b></td></tr>"
        f"<tr><td colspan='3'>Period:</td><td colspan='10'><b>H1 (2023.01.02 - {end})</b>"
        "</td></tr>"
        "<tr><td colspan='3'>Currency:</td><td colspan='10'><b>USD</b></td></tr>"
        "<tr><td colspan='3'>Initial Deposit:</td><td colspan='10'><b>10 000.00</b></td></tr>"
        "</table><table>"
        "<tr><th colspan='13'><b>Deals</b></th></tr>" + header + "".join(rows) + "</table>"
        "</body></html>"
    )
    return b"\xff\xfe" + html_text.encode("utf-16-le")


def synthetic_mt5_optimization(passes: int = SAMPLE_PASSES) -> bytes:
    """An MT5 optimisation export (SpreadsheetML) listing ``passes`` passes."""
    names = ["Pass", "Result", "Profit", "Trades", "FastMA", "SlowMA"]
    head = "".join(f'<Cell><Data ss:Type="String">{name}</Data></Cell>' for name in names)
    rows = []
    for index in range(passes):
        values = [index, 10_000 + index, index, 100, 5 + index % 20, 50 + index // 20]
        rows.append(
            "<Row>"
            + "".join(f'<Cell><Data ss:Type="Number">{value}</Data></Cell>' for value in values)
            + "</Row>"
        )
    return (
        '<?xml version="1.0"?>\n<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        '<Worksheet ss:Name="Tester Optimizator Results"><Table>'
        f"<Row>{head}</Row>" + "".join(rows) + "</Table></Worksheet></Workbook>"
    ).encode("utf-8")


def sample_result(locale: str = "es", *, bootstrap_samples: int = SAMPLE_BOOTSTRAP) -> AuditResult:
    """The sample audit in ``locale``; deterministic for a given sample size."""
    declared = DeclaredMetadata(
        trials=SAMPLE_PASSES,
        cost_bps_per_side=1.0,
        oos_start="2024-06-03",
        description="",
        benchmark_applicable=False,
        locale=locale if locale in ("es", "en") else "es",
        challenge=None,
    )
    inputs = build_inputs(
        None,
        declared,
        report_bytes=synthetic_mt5_report(),
        report_filename="SyntheticSampleEA.html",
        optimization_bytes=synthetic_mt5_optimization(),
    )
    return run_audit(inputs, bootstrap_samples=bootstrap_samples, now=SAMPLE_NOW)


__all__ = [
    "SAMPLE_NOW",
    "sample_result",
    "synthetic_mt5_optimization",
    "synthetic_mt5_report",
]
