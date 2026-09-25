"""MetaTrader reports from terminals set to other languages, and the MT4 rows
those real reports showed (docs/research/audit_iteration4/mt_languages_check.md).

Every case rewrites a synthetic fixture; no downloaded report is used.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quant_trade.audit.importers import MT4_TESTER_HTML, decode_text, import_report
from quant_trade.audit.report import _reading_rows

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_bytes().decode("utf-8")


def gross(report) -> list[float]:
    return [round(trade.pnl, 2) for trade in report.trades.trades]


def _replace(text: str, pairs: tuple[tuple[str, str], ...]) -> str:
    for old, new in pairs:
        assert old in text, old
        text = text.replace(old, new)
    return text


RUSSIAN_MT4 = (
    ("<td colspan=2>Symbol</td>", "<td colspan=2>Символ</td>"),
    ("<td colspan=2>Period</td>", "<td colspan=2>Период</td>"),
    ("<td colspan=2>Parameters</td>", "<td colspan=2>Параметры</td>"),
    (
        "<td>Initial deposit</td><td align=right>10000.00</td>",
        "<td>Начальный депозит</td><td align=right>200.00</td>",
    ),
    ("<td>Total net profit</td>", "<td>Чистая прибыль</td>"),
    ("<td>Total trades</td>", "<td>Всего сделок</td>"),
    ("<td>Modelling quality</td>", "<td>Качество моделирования</td>"),
)
PORTUGUESE_MT4 = (
    ("<td colspan=2>Symbol</td>", "<td colspan=2>Ativo</td>"),
    ("<td colspan=2>Period</td>", "<td colspan=2>Período</td>"),
    ("<td colspan=2>Parameters</td>", "<td colspan=2>Parâmetros</td>"),
    (
        "<td>Initial deposit</td><td align=right>10000.00</td>",
        "<td>Depósito Inicial</td><td align=right>200.00</td>",
    ),
    ("<td>Total net profit</td>", "<td>Lucro líquido total</td>"),
    ("<td>Total trades</td>", "<td>Total de negociações</td>"),
    ("<td>Modelling quality</td>", "<td>Qualidade do modelamento</td>"),
)


@pytest.mark.parametrize(
    ("labels", "encoding"),
    [(RUSSIAN_MT4, "cp1251"), (PORTUGUESE_MT4, "cp1252")],
    ids=["ru-cp1251", "pt-cp1252"],
)
def test_mt4_summary_in_other_languages_without_a_charset(
    labels: tuple[tuple[str, str], ...], encoding: str
) -> None:
    data = _replace(fixture("mt4_tester.htm"), labels).encode(encoding)
    report = import_report(data, "StrategyTester.htm")
    assert report.source_format == MT4_TESTER_HTML
    assert gross(report) == [-0.4, 100.0, -30.0, 25.5]
    # The deposit is the report's own, not the 10,000 assumed without one.
    assert report.initial_balance == 200.0
    assert not any("assumed" in w for w in report.warnings)
    assert report.metadata["declared_total_trades"] == "4"
    assert report.metadata["declared_total_net_profit"] == "95.10"
    assert report.metadata["modelling_quality"] == "90.00%"
    assert report.metadata["inputs"] == "3"


def test_cp1251_is_chosen_only_for_russian_report_words() -> None:
    russian = "<td>Начальный депозит</td>".encode("cp1251")
    assert "Начальный депозит" in decode_text(russian)
    # Western text stays cp1252 even though its bytes also decode as cp1251.
    portuguese = "<td>Depósito Inicial</td>".encode("cp1252")
    assert "Depósito Inicial" in decode_text(portuguese)


def _mt4_row(
    n: int, time: str, kind: str, order: int, size: str, price: str, money: str = ""
) -> str:
    tail = (
        f"<td class=mspt>{money.split('|')[0]}</td><td class=mspt>{money.split('|')[1]}</td>"
        if money
        else "<td colspan=2></td>"
    )
    return (
        f"<tr align=right><td>{n}</td><td class=msdate>{time}</td><td>{kind}</td>"
        f"<td>{order}</td><td class=mspt>{size}</td><td>{price}</td>"
        f"<td align=right>0.00000</td><td align=right>0.00000</td>{tail}</tr>"
    )


def _with_rows(rows: list[str], trades: int, net: str) -> bytes:
    text = fixture("mt4_tester.htm")
    head, _, rest = text.partition("<tr align=right><td>1</td>")
    _, _, tail = rest.partition("</table>\n</div>")
    head = head.replace(
        "<td>Total trades</td><td align=right>4</td>",
        f"<td>Total trades</td><td align=right>{trades}</td>",
    ).replace(
        "<td>Total net profit</td><td align=right>95.10</td>",
        f"<td>Total net profit</td><td align=right>{net}</td>",
    )
    return (head + "".join(rows) + "</table>\n</div>" + tail).encode("utf-8")


def test_mt4_rollover_swap_close_and_open_continue_the_position() -> None:
    # Some brokers close every open position at rollover ("swap close") and
    # reopen it under a new ticket ("swap open"); MetaTrader counts the close.
    rows = [
        _mt4_row(1, "2024.01.02 09:00", "buy", 1, "0.10", "1.10000"),
        _mt4_row(2, "2024.01.03 00:00", "swap close", 1, "0.10", "1.10100", "12.00|10012.00"),
        _mt4_row(3, "2024.01.03 00:00", "swap open", 2, "0.10", "1.10100"),
        _mt4_row(4, "2024.01.03 09:00", "s/l", 2, "0.10", "1.09900", "-20.00|9992.00"),
    ]
    report = import_report(_with_rows(rows, 2, "-8.00"), "StrategyTester.htm")
    assert gross(report) == [12.0, -20.0]
    assert report.trades.sides == ["long", "long"]
    assert not any("paired" in w or "never closed" in w for w in report.warnings)
    assert not any("the report states" in w for w in report.warnings)


def test_mt4_partial_close_moves_the_rest_to_a_new_ticket() -> None:
    # Closing half of ticket 1 prints the rest as a new "sell" ticket 2 at the
    # close's time and the original entry price.
    rows = [
        _mt4_row(1, "2024.01.02 09:00", "sell", 1, "0.20", "1.10000"),
        _mt4_row(2, "2024.01.02 12:00", "close", 1, "0.10", "1.09900", "10.00|10010.00"),
        _mt4_row(3, "2024.01.02 12:00", "sell", 2, "0.10", "1.10000"),
        _mt4_row(4, "2024.01.02 15:00", "close", 2, "0.10", "1.09800", "20.00|10030.00"),
    ]
    report = import_report(_with_rows(rows, 2, "30.00"), "StrategyTester.htm")
    assert gross(report) == [10.0, 20.0]
    entries = {trade.entry_time.hour for trade in report.trades.trades}
    assert entries == {9}
    assert not any("never closed" in w for w in report.warnings)


CHINESE_MT5 = (
    ("Initial Deposit:", "初始入金:"),
    ("Currency:", "货币:"),
    ("Total Net Profit:", "总净盈利:"),
    ("Total Trades:", "交易总计:"),
    ("Total Deals:", "总成交:"),
)
PORTUGUESE_MT5 = (
    ("Initial Deposit:", "Depósito Inicial:"),
    ("Currency:", "Moeda:"),
    ("Total Net Profit:", "Lucro Líquido Total:"),
    ("Total Trades:", "Total de Negociações:"),
    ("Total Deals:", "Ofertas Total:"),
)


@pytest.mark.parametrize("labels", [CHINESE_MT5, PORTUGUESE_MT5], ids=["zh", "pt"])
def test_mt5_tester_summary_in_chinese_and_portuguese(labels: tuple[tuple[str, str], ...]) -> None:
    text = _replace(fixture("mt5_tester.html"), labels)
    report = import_report(("﻿" + text).encode("utf-8"), "ReportTester.html")
    assert report.initial_balance == 10_000.0
    assert report.currency == "USD"
    assert report.metadata["declared_total_net_profit"] == "63.05"
    assert report.metadata["declared_total_trades"] == "5"
    assert report.metadata["declared_total_deals"] == "9"


def test_mt5_history_account_line_with_leverage() -> None:
    text = fixture("mt5_history.html").replace(
        "(USD,&nbsp;SyntheticBroker-Demo", "(USD,&nbsp;1:500,&nbsp;SyntheticBroker-Demo"
    )
    report = import_report(text.encode("utf-8"), "ReportHistory.html")
    assert report.currency == "USD"
    assert report.metadata["leverage"] == "1:500"
    assert report.metadata["server"] == "SyntheticBroker-Demo"


def _reading(meta: dict[str, str], trades: int, net: float) -> list[tuple[str, float, float, bool]]:
    data = {
        "inputs": {"report_metadata": meta},
        "trade_stats": {
            "trade_count": {"value": trades, "evidence": "MEASURED"},
            "net_pnl": {"value": net, "evidence": "MEASURED"},
        },
    }
    return _reading_rows(data)


def test_reading_counts_partial_closes_as_metatrader_does() -> None:
    # 60 positions, one closed in two parts: MetaTrader's "Total Trades" is 61.
    meta = {
        "declared_total_trades": "61",
        "declared_total_net_profit": "15.27",
        "closing_deals": "61",
    }
    rows = _reading(meta, 60, 15.27)
    assert rows[0] == ("trade_count", 61.0, 61.0, True)
    # Without the closing-deal count, a real difference still shows.
    rows = _reading({"declared_total_trades": "61"}, 60, 15.27)
    assert rows[0][3] is False


def test_reading_allows_a_cent_of_rounding_per_two_trades() -> None:
    meta = {"declared_total_trades": "3659", "declared_total_net_profit": "10555.76"}
    assert all(ok for *_, ok in _reading(meta, 3659, 10556.08))
    # A few trades cannot hide a difference of dollars.
    meta = {"declared_total_trades": "35", "declared_total_net_profit": "636.20"}
    assert not all(ok for *_, ok in _reading(meta, 35, 634.50))


def test_a_swap_credit_counts_in_the_net_result() -> None:
    from dataclasses import replace

    from quant_trade.audit.engine import _trade_stats
    from quant_trade.audit.schema import DeclaredMetadata, build_inputs

    data = fixture("mt5_tester.html").encode("utf-8")
    inputs = build_inputs(None, DeclaredMetadata(), report_bytes=data, report_filename="r.html")
    gross_sum = sum(trade.pnl for trade in inputs.trades.trades)
    # Swap paid to the account (positive) raises the net result, as MetaTrader shows it.
    credited = replace(inputs, reported_fees={"commission": 0.0, "swap": 1.7})
    assert _trade_stats(credited)["net_pnl"]["value"] == pytest.approx(gross_sum + 1.7)
