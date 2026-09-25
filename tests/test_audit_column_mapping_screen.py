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
