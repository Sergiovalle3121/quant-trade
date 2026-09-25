"""A file no importer knows answers with its own columns to name, not a refusal."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import mapping  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.i18n import untranslated  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

PASSWORD = "una frase larga y segura"
CSRF_FIELD = re.compile(r"name='csrf' value='([^']+)'")
HEADER = "Abierto,Cerrado,Papel,Títulos,Compra,Venta,Neto"


def _journal(preamble: str = "") -> bytes:
    rows = []
    for day in range(1, 61):
        month, date = 1 + (day - 1) // 28, 1 + (day - 1) % 28
        move = 3 if day % 3 else -4
        rows.append(
            f"2025-{month:02d}-{date:02d} 10:00,2025-{month:02d}-{date:02d} 15:00,GC,1,2300,"
            f"{2300 + move},{move}"
        )
    lines = ([preamble] if preamble else []) + [HEADER, *rows]
    return ("\n".join(lines) + "\n").encode()


CHOSEN = {
    "col_entry_time": "Abierto",
    "col_exit_time": "Cerrado",
    "col_symbol": "Papel",
    "col_quantity": "Títulos",
    "col_entry_price": "Compra",
    "col_exit_price": "Venta",
    "col_profit": "Neto",
}


def _client(tmp_path: Path, **extra: object) -> TestClient:
    values: dict[str, object] = {
        "database_url": f"sqlite:///{tmp_path}/audit.db",
        "bootstrap_samples": 100,
    }
    values.update(extra)
    settings = AuditSettings(**values)  # type: ignore[arg-type]
    return TestClient(create_app(settings, make_store(settings.database_url)))


def test_an_unknown_table_shows_its_columns_and_rows_to_name(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"report": ("diario.csv", _journal(), "text/csv")}
    answer = client.post("/audits", files=files, data={"consent": "on", "initial_balance": "20000"})
    assert answer.status_code == 422
    page = answer.text
    assert "Dinos qué es cada columna" in page
    # The header and the first rows, as read.
    assert "<th>Títulos</th>" in page and "<td>2025-01-01 10:00</td>" in page
    # One menu per field, each offering the file's columns with an example.
    assert "name='col_entry_time'" in page and "name='col_price'" in page
    assert "<option value='Compra'>Compra · ej. 2300</option>" in page
    # The first upload's fields travel with the second one.
    assert "name='initial_balance' value='20000'" in page
    assert "name='consent' value='on'" in page
    assert "type='file' name='report' required" in page
    assert find_claims(page) == []
    # Nothing was audited or stored.
    assert (
        client.app.state.store.count_uploads_since("testclient", datetime(2000, 1, 1, tzinfo=UTC))
        == 0
    )


def test_the_named_columns_audit_the_same_file(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"report": ("diario.csv", _journal(), "text/csv")}
    posted = client.post(
        "/audits", files=files, data={"consent": "on", **CHOSEN}, follow_redirects=False
    )
    assert posted.status_code == 303, posted.text[:400]


def test_a_line_above_the_header_is_skipped(tmp_path: Path) -> None:
    table = mapping.read_table(_journal(preamble="UID: 123456"))
    assert table is not None
    assert table.header[:2] == ["Abierto", "Cerrado"]
    assert len(table.samples) == mapping.SAMPLE_ROWS


def test_the_page_is_in_english_too(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"report": ("journal.csv", _journal(), "text/csv")}
    answer = client.post("/audits", files=files, data={"consent": "on", "locale": "en"})
    assert answer.status_code == 422
    assert "Tell us what each column is" in answer.text
    assert "Compra · e.g. 2300" in answer.text
    assert find_claims(answer.text) == []


def test_a_json_client_gets_the_columns(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"report": ("diario.csv", _journal(), "text/csv")}
    answer = client.post(
        "/audits", files=files, data={"consent": "on"}, headers={"Accept": "application/json"}
    )
    assert answer.status_code == 422
    assert answer.json()["columns"] == HEADER.split(",")


def test_a_report_page_that_is_not_a_table_keeps_the_plain_error(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"report": ("x.html", b"<html><body><p>hola</p></body></html>", "text/html")}
    answer = client.post("/audits", files=files, data={"consent": "on"})
    assert answer.status_code == 400
    assert "Dinos qué es cada columna" not in answer.text


def _signed_in(tmp_path: Path) -> tuple[TestClient, str]:
    client = _client(tmp_path, free_mode=False, access_codes=True, contact_url="https://wa.me/000")
    csrf = CSRF_FIELD.search(client.get("/registro").text)
    assert csrf is not None
    client.post(
        "/registro",
        data={"email": "ana@example.com", "password": PASSWORD, "csrf": csrf.group(1)},
        follow_redirects=False,
    )
    account = client.app.state.store.find_account("ana@example.com")
    assert account is not None
    return client, account.id


def test_the_mapping_step_spends_no_free_report_and_is_remembered(tmp_path: Path) -> None:
    client, account_id = _signed_in(tmp_path)
    store = client.app.state.store
    files = {"report": ("diario.csv", _journal(), "text/csv")}
    asked = client.post("/audits", files=files, data={"consent": "on"})
    assert asked.status_code == 422
    # The free first report is still there after the mapping step.
    assert store.free_previews_since(datetime(2000, 1, 1, tzinfo=UTC), account_id=account_id) == 0
    assert (
        "acct=welcome"
        in client.post(
            "/audits", files=files, data={"consent": "on", **CHOSEN}, follow_redirects=False
        ).headers["location"]
    )
    saved = store.column_map(account_id, mapping.header_signature(HEADER.split(",")))
    assert mapping.loads(saved) == {key[4:]: value for key, value in CHOSEN.items()}
    # The same header again, with no columns named: read with the saved choice.
    again = client.post("/audits", files=files, data={"consent": "on"}, follow_redirects=False)
    assert again.status_code == 303, again.text[:400]
    # Deleting the account deletes its column maps.
    store.delete_account(account_id)
    assert store.column_map(account_id, mapping.header_signature(HEADER.split(","))) is None


def test_a_stored_choice_is_kept_to_known_fields_and_real_columns() -> None:
    table = mapping.read_table(_journal())
    assert table is not None
    kept = mapping.usable_mapping(
        {"profit": "Neto", "entry_time": "Nope", "evil": "Neto", "side": 3},
        table,  # type: ignore[dict-item]
    )
    assert kept == {"profit": "Neto"}
    assert mapping.loads("not json") == {} and mapping.loads("[1]") == {}


def _results(kind: str = "profit") -> bytes:
    """A list with a date and one figure per row, as a spreadsheet keeps it."""
    lines = ["Fecha cierre;Resultado neto;Nota" if kind == "profit" else "Día;Saldo;Nota"]
    level = 10_000.0
    for day in range(1, 61):
        month, date = 1 + (day - 1) // 28, 1 + (day - 1) % 28
        move = 30.5 if day % 3 else -41.25
        level += move
        figure = move if kind == "profit" else level
        lines.append(f"{date:02d}/{month:02d}/2025;{figure:.2f}".replace(".", ",") + ";x")
    return ("\n".join(lines) + "\n").encode()


def test_a_date_and_each_result_are_enough(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"report": ("pnl.csv", _results(), "text/csv")}
    asked = client.post("/audits", files=files, data={"consent": "on"})
    assert asked.status_code == 422
    assert "name='col_date'" in asked.text and "name='col_balance'" in asked.text
    chosen = {"col_date": "Fecha cierre", "col_profit": "Resultado neto"}
    posted = client.post(
        "/audits",
        files=files,
        data={"consent": "on", "initial_balance": "10000", **chosen},
        follow_redirects=False,
    )
    assert posted.status_code == 303, posted.text[:400]
    # A trade's closing date in the "exit" menu reads the same way.
    exit_named = client.post(
        "/audits",
        files=files,
        data={"consent": "on", "col_exit_time": "Fecha cierre", "col_profit": "Resultado neto"},
        follow_redirects=False,
    )
    assert exit_named.status_code == 303, exit_named.text[:400]


def test_the_curve_from_results_starts_at_the_balance_and_says_what_it_lacks() -> None:
    columns = {"date": "Fecha cierre", "profit": "Resultado neto"}
    curve, notes = mapping.curve_from_columns(_results(), columns, initial_balance=None)
    lines = curve.decode().splitlines()
    assert lines[0] == "timestamp,equity"
    assert lines[1] == "2024-12-31 00:00:00,10000.0"
    assert lines[2] == "2025-01-01 00:00:00,10030.5"
    assert len(lines) == 62
    assert notes[0] == mapping.MAPPED_PROFIT_WARNING
    assert "does not state a starting balance" in notes[1]
    for note in notes:
        assert find_claims(note) == []
    assert untranslated({"inputs": {"parse_warnings": notes}}) == []


def test_a_date_and_the_balance_are_enough(tmp_path: Path) -> None:
    columns = {"date": "Día", "balance": "Saldo"}
    curve, notes = mapping.curve_from_columns(_results("balance"), columns, initial_balance=None)
    assert curve.decode().splitlines()[1] == "2025-01-01 00:00:00,10030.5"
    assert notes == [mapping.MAPPED_BALANCE_WARNING]
    client = _client(tmp_path)
    files = {"report": ("saldo.csv", _results("balance"), "text/csv")}
    posted = client.post(
        "/audits",
        files=files,
        data={"consent": "on", "col_date": "Día", "col_balance": "Saldo"},
        follow_redirects=False,
    )
    assert posted.status_code == 303, posted.text[:400]


def test_an_incomplete_choice_names_what_is_missing_on_the_page(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"report": ("diario.csv", _journal(), "text/csv")}
    answer = client.post(
        "/audits",
        files=files,
        data={"consent": "on", "col_entry_time": "Abierto", "col_exit_time": "Cerrado"},
    )
    assert answer.status_code == 422
    text = answer.text
    assert "Para leerlo como una fila por operación aún falta:" in text
    assert "Cantidad, Precio de entrada, Precio de salida" in text
    assert "Indica sus columnas" not in text and "Name its columns" not in text
    assert find_claims(text) == []
    english = mapping.missing_fields({"date": "Fecha cierre"}, "en")
    assert english == "To read it as date and result, still missing: Trade result."


def test_too_few_readable_rows_are_offered_again(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"report": ("pnl.csv", _results(), "text/csv")}
    answer = client.post(
        "/audits",
        files=files,
        data={"consent": "on", "col_date": "Nota", "col_profit": "Resultado neto"},
    )
    assert answer.status_code == 422
    assert "menos de dos filas con fecha y cifra legibles" in answer.text


def test_a_very_wide_header_gets_the_plain_refusal_quickly(tmp_path: Path) -> None:
    import time

    wide = ",".join(f"c{i}" for i in range(200_000))
    data = (wide + "\n" + ",".join("1" for _ in range(200_000)) + "\n").encode()
    assert mapping.read_table(data) is None
    client = _client(tmp_path)
    started = time.monotonic()
    answer = client.post(
        "/audits", files={"report": ("wide.csv", data, "text/csv")}, data={"consent": "on"}
    )
    assert answer.status_code == 400
    assert time.monotonic() - started < 10


def test_the_preview_shows_at_most_the_menu_width() -> None:
    header = [f"col{i}" for i in range(mapping.MAX_COLUMNS + 20)]
    table = mapping.Table(header, [["x"] * len(header)])
    page = mapping.mapping_page(table, "problema")
    assert page.count("<th>") == mapping.MAX_COLUMNS
    assert "y 20 columnas más, que no se muestran" in page


def test_results_that_empty_the_account_ask_for_the_starting_balance(tmp_path: Path) -> None:
    client = _client(tmp_path)
    losing = b"Fecha cierre;Resultado neto\n13/01/2025;50\n14/01/2025;-400\n15/01/2025;20\n"
    files = {"report": ("pnl.csv", losing, "text/csv")}
    answer = client.post(
        "/audits",
        files=files,
        data={
            "consent": "on",
            "initial_balance": "300",
            "col_date": "Fecha cierre",
            "col_profit": "Resultado neto",
        },
    )
    assert answer.status_code == 400
    assert "declara el balance inicial de la cuenta" in answer.text
    assert "ganancia acumulada" not in answer.text
    assert find_claims(answer.text) == []


def _daily(header: str = "Fecha;Resultado") -> bytes:
    """A daily P&L sheet: semicolons with dot decimals, around +-60 a day."""
    lines = [header]
    for day in range(1, 29):
        move = 61.37 if day % 2 else -48.9
        lines.append(f"{day:02d}/02/2023;{move:.2f}")
    return ("\n".join(lines) + "\n").encode()


def test_a_daily_sheet_with_dot_decimals_reads_with_named_columns(tmp_path: Path) -> None:
    curve, _ = mapping.curve_from_columns(
        _daily(), {"date": "Fecha", "profit": "Resultado"}, initial_balance=5000
    )
    # 61.37 is sixty-one, not 6,137, even in a semicolon file.
    assert curve.decode().splitlines()[2] == "2023-02-01 00:00:00,5061.37"
    client = _client(tmp_path)
    for field in ("report", "equity"):
        posted = client.post(
            "/audits",
            files={field: ("pnl.csv", _daily(), "text/csv")},
            data={"consent": "on", "col_date": "Fecha", "col_profit": "Resultado"},
            follow_redirects=False,
        )
        assert posted.status_code == 303, (field, posted.text[:400])


def test_a_results_sheet_in_the_curve_field_is_offered_as_results(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for header in ("date;value", "Fecha;Resultado"):
        answer = client.post(
            "/audits",
            files={"equity": ("pnl.csv", _daily(header), "text/csv")},
            data={"consent": "on"},
        )
        assert answer.status_code == 422, (header, answer.text[:300])
        assert "type='file' name='report' required" in answer.text
        assert find_claims(answer.text) == []
    assert (
        "parece una lista de resultados"
        in client.post(
            "/audits",
            files={"equity": ("pnl.csv", _daily("date;value"), "text/csv")},
            data={"consent": "on"},
        ).text
    )
    table = mapping.read_table(_daily("date;value"))
    assert table is not None
    assert mapping.results_guess(table) == {"date": "date", "profit": "value"}


@pytest.mark.parametrize(
    ("cells", "default", "mark"),
    [
        (["12.34", "-5.10"], ",", "."),
        (["12,34", "-5,10"], ".", ","),
        (["1.234,50"], ".", ","),
        (["1,234.50"], ",", "."),
        (["1.234"], ",", ","),
    ],
)
def test_the_decimal_mark_comes_from_the_cells(cells: list[str], default: str, mark: str) -> None:
    assert mapping._decimal_mark(cells, default) == mark


def test_a_hand_typed_column_mixing_decimal_marks_reads_each_cell() -> None:
    cells = ["12.34", "-5,60", "101.10", "-7,25", "3.50", "8,01"]
    for default in (".", ","):
        assert mapping._figures(cells, default) == [12.34, -5.6, 101.1, -7.25, 3.5, 8.01]
    # A repeated mark is the thousands one; a lone three-digit tail follows the column.
    assert mapping._figures(["1.234.567", "2,5"], ",") == [1234567.0, 2.5]
    assert mapping._figures(["1.234,50", "1,234.50"], ".") == [1234.5, 1234.5]


def test_a_curve_file_without_a_known_value_column_preselects_the_balance(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    answer = client.post(
        "/audits",
        files={"equity": ("saldo.csv", _results("balance"), "text/csv")},
        data={"consent": "on"},
    )
    assert answer.status_code == 422
    assert re.search(r"name='col_balance'>.*?<option value='Saldo'[^>]* selected", answer.text)


def test_a_list_without_a_header_row_is_offered_with_numbered_columns(tmp_path: Path) -> None:
    rows = _daily().decode().splitlines()[1:]
    headerless = ("\n".join(rows) + "\n").encode()
    client = _client(tmp_path)
    for field in ("report", "equity"):
        answer = client.post(
            "/audits", files={field: ("pnl.csv", headerless, "text/csv")}, data={"consent": "on"}
        )
        assert answer.status_code == 422, (field, answer.text[:300])
        assert "<th>Col. 1</th>" in answer.text and "<th>Col. 2</th>" in answer.text
    posted = client.post(
        "/audits",
        files={"report": ("pnl.csv", headerless, "text/csv")},
        data={"consent": "on", "col_date": "Col. 1", "col_profit": "Col. 2"},
        follow_redirects=False,
    )
    assert posted.status_code == 303, posted.text[:400]


def test_the_report_field_preselects_a_date_and_a_balance(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for data, balance in ((_results("balance"), "Saldo"), (_daily("date;equity"), "equity")):
        answer = client.post(
            "/audits", files={"report": ("x.csv", data, "text/csv")}, data={"consent": "on"}
        )
        assert answer.status_code == 422
        assert re.search(
            rf"name='col_balance'>.*?<option value='{balance}'[^>]* selected", answer.text
        ), balance
        assert re.search(r"name='col_date'>.*?<option value='[^']+'[^>]* selected", answer.text)


@pytest.mark.parametrize("cell", ["1.2.3", "1,,2", "1.234.56", "12.3.4.5"])
def test_a_malformed_number_is_unreadable_not_guessed(cell: str) -> None:
    assert mapping._figures([cell, "5,5"], ",") == [None, 5.5]
