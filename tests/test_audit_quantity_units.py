"""Sizing retains source quantities rather than monetary contract multipliers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from quant_trade.audit.importers import import_report
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"


@pytest.mark.parametrize("name", ["mt4_tester.htm", "mt5_tester.html"])
def test_metatrader_keeps_the_original_lots_separate_from_economic_quantity(name: str) -> None:
    report = import_report((FIXTURES / name).read_bytes(), name)
    assert report.quantity_unit == "lot"
    assert report.trade_quantities == report.lots
    assert report.trade_quantities is not None
    assert len(report.trade_quantities) == len(report.trades.trades)
    assert all(
        quantity < trade.quantity
        for quantity, trade in zip(report.trade_quantities, report.trades.trades, strict=True)
    )


@pytest.mark.parametrize(
    "name",
    [
        "ninjatrader.csv",
        "tradovate_performance.csv",
        "tradovate_orders.csv",
        "topstepx_trades.csv",
        "sierra_chart_trades.txt",
        "sierra_chart_trade_activity.txt",
    ],
)
def test_futures_export_preserves_contract_counts(name: str) -> None:
    report = import_report((FIXTURES / name).read_bytes(), name)
    assert report.quantity_unit == "contract"
    assert report.lots is None
    assert report.trade_quantities is not None
    assert set(report.trade_quantities) <= {1.0, 2.0}
    assert len(report.trade_quantities) == len(report.trades.trades)
    assert all(
        quantity < trade.quantity
        for quantity, trade in zip(report.trade_quantities, report.trades.trades, strict=True)
    )


def test_ctrader_closed_quantities_remain_lots_without_changing_cost_lots() -> None:
    data = (FIXTURES / "ctrader_history_columns.csv").read_bytes()
    data = data.replace(b"Gross (currency)", b"profit", 1)
    report = import_report(data, "history.csv")
    assert report.quantity_unit == "lot"
    assert report.trade_quantities == [0.25, 0.25, 0.1]
    assert report.lots is None
    assert report.trades.trades[0].quantity == pytest.approx(25_000)


def _generic_trades(symbols: tuple[str, ...], quantity_column: str = "Quantity") -> bytes:
    lines = [f"Symbol,Open Time,Close Time,Side,{quantity_column},Open Price,Close Price,Profit"]
    for day, symbol in enumerate(symbols, start=1):
        lines.append(f"{symbol},2026-01-{day:02d} 09:00,2026-01-{day:02d} 10:00,Buy,2,100,101,100")
    return ("\n".join(lines) + "\n").encode()


@pytest.mark.parametrize("symbols", [("CL",), ("AAPL",), ("ESZ6", "AAPL"), ("EURUSD",)])
def test_unknown_or_mixed_instruments_keep_file_units(symbols: tuple[str, ...]) -> None:
    report = import_report(_generic_trades(symbols), "ninjatrader.csv")
    assert report.quantity_unit == "file"
    assert report.trade_quantities == [2.0] * len(symbols)
    assert all(trade.quantity == 100.0 for trade in report.trades.trades)


def test_explicit_lot_column_identifies_the_source_unit() -> None:
    report = import_report(_generic_trades(("EURUSD",), "Lots"), "trades.csv")
    assert report.quantity_unit == "lot"
    assert report.trade_quantities == [2.0]
    assert report.lots is None


def test_build_inputs_preserves_original_quantities_and_unit() -> None:
    name = "topstepx_trades.csv"
    inputs = build_inputs(
        None,
        DeclaredMetadata(initial_balance=50_000),
        report_bytes=(FIXTURES / name).read_bytes(),
        report_filename=name,
        now=datetime(2026, 10, 11, tzinfo=UTC),
    )
    assert inputs.quantity_unit == "contract"
    assert inputs.trade_quantities == [2.0, 1.0, 1.0]
    assert inputs.trade_lots is None
    assert inputs.trades is not None
    assert [trade.quantity for trade in inputs.trades.trades] == [4.0, 2.0, 50.0]
