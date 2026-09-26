"""A table past the limits is refused before it is read in full."""

from __future__ import annotations

import pytest

from quant_trade.audit import importers, universal
from quant_trade.audit.guard import find_claims
from quant_trade.audit.importers import ReportFormatError, import_report

HEADER = "Entry time,Exit time,Symbol,Side,Entry price,Exit price,Quantity,Profit"


def _row(day: int, quantity: str = "1") -> str:
    stamp = f"2026-08-{day:02d} 10:00"
    return f"{stamp},{stamp},ES,Buy,1,2,{quantity},1"


def test_a_page_with_more_rows_than_the_limit_is_refused_before_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importers, "MAX_HTML_ROWS", 5)

    def parsed(*_: object) -> None:
        raise AssertionError("the page was parsed")

    monkeypatch.setattr(importers._TableReader, "feed", parsed)
    page = "<html><table>" + "<tr><td>1</td></tr>" * 6 + "</table></html>"
    with pytest.raises(ReportFormatError) as refused:
        import_report(page.encode(), "trades.html", initial_balance=10_000)
    assert refused.value.code == "too_many_rows"
    assert "more than 5 table rows" in str(refused.value)
    assert "más de 5 filas" in refused.value.message_es
    portuguese = refused.value.localized("pt")
    assert "mais de 5 linhas" in portuguese
    for text in (str(refused.value), refused.value.message_es, portuguese):
        assert not find_claims(text)


def test_a_page_at_the_row_limit_is_still_read(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [HEADER, *(_row(day) for day in range(1, 5))]
    monkeypatch.setattr(importers, "MAX_HTML_ROWS", len(rows))
    cells = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in line.split(",")) + "</tr>" for line in rows
    )
    report = import_report(
        f"<html><table>{cells}</table></html>".encode(), "trades.html", initial_balance=10_000
    )
    assert len(report.trades.trades) == 4


def test_a_trade_list_past_the_limit_is_refused_before_its_dates_are_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importers, "MAX_TRADES", 5)

    def read_dates(*_: object, **__: object) -> None:
        raise AssertionError("the dates were read")

    monkeypatch.setattr(universal, "_times", read_dates)
    data = "\n".join([HEADER, *(_row(day) for day in range(1, 8))]).encode()
    with pytest.raises(ReportFormatError) as refused:
        import_report(data, "trades.csv", initial_balance=10_000)
    assert refused.value.code == "too_many_trades"
    assert "has 7 closed trades; the limit is 5" in str(refused.value)


def test_rows_without_a_quantity_do_not_count_toward_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importers, "MAX_TRADES", 5)
    rows = [_row(day) for day in range(1, 6)] + [_row(6, "0"), _row(7, "")]
    data = "\n".join([HEADER, *rows]).encode()
    report = import_report(data, "trades.csv", initial_balance=10_000)
    assert len(report.trades.trades) == 5


def test_a_page_with_more_cells_than_the_limit_is_refused_before_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importers, "MAX_HTML_CELLS", 5)
    page = "<html><table><tr>" + "<td>1</td>" * 6 + "</tr></table></html>"
    with pytest.raises(ReportFormatError) as refused:
        import_report(page.encode(), "trades.html", initial_balance=10_000)
    assert refused.value.code == "too_many_rows"
    assert "more than 5 table cells" in str(refused.value)
    assert "más de 5 celdas" in refused.value.message_es
    assert "mais de 5 células" in refused.value.localized("pt")


def test_rows_the_reader_drops_do_not_count_toward_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importers, "MAX_TRADES", 5)
    unknown_side = "2026-08-10 10:00,2026-08-10 10:00,ES,Hold,1,2,1,1"
    no_result = "2026-08-11 10:00,2026-08-11 10:00,ES,Buy,1,2,1,n/a"
    rows = [_row(day) for day in range(1, 6)] + [unknown_side, no_result]
    data = "\n".join([HEADER, *rows]).encode()
    report = import_report(data, "trades.csv", initial_balance=10_000)
    assert len(report.trades.trades) == 5
