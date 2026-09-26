"""B3's Área do Investidor Negociação extract, read by column name only.

Confirmed from open-source importers of real files: "Data do Negócio" (day
first), "Tipo de Movimentação" (Compra/Venda), "Instituição", and a trailing
F on fractional-market tickers. "Mercado" and "Código de Negociação" are
inferred, so B3 is not a named platform. Synthetic rows only.
"""

from __future__ import annotations

import pytest
from test_audit_importers import xlsx

from quant_trade.audit import universal
from quant_trade.audit.importers import ReportFormatError, import_report

INFERRED = [
    "Data do Negócio", "Tipo de Movimentação", "Mercado", "Prazo/Vencimento", "Instituição",
    "Código de Negociação", "Quantidade", "Preço", "Valor",
]  # fmt: skip


def _row(
    day: str, side: str, market: str, ticker: str, quantity: int, price: float
) -> list[object]:
    broker = "XP INVESTIMENTOS CCTVM S/A"
    return [day, side, market, "-", broker, ticker, quantity, price, quantity * price]


def _pnl(data: bytes, name: str) -> list[float]:
    return [round(trade.pnl, 2) for trade in import_report(data, name).trades.trades]


def test_the_confirmed_names_are_read_with_dates_day_first() -> None:
    # Every day is 12 or less, so only the column name says day first.
    lines = [
        "Data do Negócio;Tipo de Movimentação;Instituição;Ativo;Quantidade;Preço",
        "03/09/2026;Venda;XP INVESTIMENTOS;PETR4;100;38,50",
        "02/08/2026;Compra;XP INVESTIMENTOS;PETR4;100;36,00",
    ]
    report = import_report(("\n".join(lines) + "\n").encode(), "negociacao.csv")
    (trade,) = report.trades.trades
    assert (trade.entry_time.month, trade.entry_time.day) == (8, 2)
    assert (trade.exit_time.month, trade.exit_time.day) == (9, 3)
    assert round(trade.pnl, 2) == 250.0


def test_the_inferred_layout_reads_the_ticker_not_the_market() -> None:
    rows = [
        INFERRED,
        _row("14/08/2026", "Venda", "Mercado à Vista", "PETR4", 100, 38.5),
        _row("12/08/2026", "Venda", "Mercado à Vista", "VALE3", 5, 62.0),
        _row("10/08/2026", "Compra", "Mercado à Vista", "PETR4", 100, 36.0),
        # Five shares bought on the fractional market, sold as VALE3: one position.
        _row("05/08/2026", "Compra", "Mercado Fracionário", "VALE3F", 5, 60.0),
    ]
    report = import_report(xlsx({"Negociação": rows}), "negociacao.xlsx")
    assert report.metadata["column_symbol"] == "Código de Negociação"
    assert report.metadata["symbol"] == "PETR4, VALE3"
    assert sorted(round(trade.pnl, 2) for trade in report.trades.trades) == [10.0, 250.0]
    assert not any("still open" in warning for warning in report.warnings)


def test_an_f_is_kept_outside_the_b3_layout() -> None:
    header = ["Symbol", "Mercado", "Side", "Quantity", "Price", "Time"]
    assert universal.whole_lot_tickers(header, [["VALE3F", "Fracionário"]], {"symbol": 0}) == [
        ["VALE3F", "Fracionário"]
    ]
    b3 = ["Código de Negociação", "Mercado"]
    columns = {"symbol": 0}
    assert universal.whole_lot_tickers(b3, [["VALE3F", "Mercado à Vista"]], columns) == [
        ["VALE3F", "Mercado à Vista"]
    ]
    assert universal.whole_lot_tickers(b3, [["VALE3F", "Mercado Fracionário"]], columns) == [
        ["VALE3", "Mercado Fracionário"]
    ]


def test_other_date_columns_still_ask_about_ambiguous_dates() -> None:
    lines = [
        "Data;Tipo;Ativo;Quantidade;Preço",
        "03/09/2026;Venda;PETR4;100;38,50",
        "02/08/2026;Compra;PETR4;100;36,00",
    ]
    with pytest.raises(ReportFormatError):
        import_report(("\n".join(lines) + "\n").encode(), "outro.csv")


@pytest.mark.parametrize(
    ("header", "role", "column"),
    [
        # A Spanish or Portuguese export whose only instrument column is "Mercado".
        (["Fecha", "Mercado", "Tipo", "Cantidad", "Precio"], "symbol", 1),
        # As before this change, "Mercado" outranks "Ativo".
        (["Data", "Ativo", "Mercado", "Tipo", "Quantidade", "Preço"], "symbol", 2),
        (["Date", "Symbol", "Side", "Quantity", "Price"], "side", 2),
        (["Data", "Ativo", "Tipo", "Quantidade", "Preço"], "time", 0),
    ],
)
def test_files_without_b3_names_keep_their_columns(
    header: list[str], role: str, column: int
) -> None:
    assert universal.guess_columns(header)[role] == column
