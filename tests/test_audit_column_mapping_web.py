"""The upload form's "name its columns" step, end to end with no network."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import landing  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.universal import ROLES  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402


def _client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _own_journal() -> bytes:
    header = "Cuando entré,Cuando salí,Mercado,Cuánto,A cuánto entré,A cuánto salí,Gané"
    rows = []
    for day in range(1, 91):
        month, date = 1 + (day - 1) // 28, 1 + (day - 1) % 28
        move = 3 if day % 3 else -4
        rows.append(
            f"2025-{month:02d}-{date:02d} 10:00,2025-{month:02d}-{date:02d} 15:00,GC,1,2300,"
            f"{2300 + move},{move * 100}"
        )
    return ("\n".join([header, *rows]) + "\n").encode()


MAPPING = {
    "col_entry_time": "Cuando entré",
    "col_exit_time": "Cuando salí",
    "col_quantity": "Cuánto",
    "col_entry_price": "A cuánto entré",
    "col_exit_price": "A cuánto salí",
    "col_profit": "Gané",
}


def test_the_form_offers_a_field_per_column_role_in_both_languages() -> None:
    for locale in ("es", "en"):
        page = landing(locale=locale)
        assert "id='report-columns'" in page
        for role in ROLES:
            if role in {"swap", "account"}:
                continue
            assert f"name='col_{role}'" in page
        assert find_claims(page) == []


def test_a_journal_nobody_knows_is_audited_with_the_customers_mapping(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"report": ("mi_diario.csv", _own_journal(), "text/csv")}
    refused = client.post("/audits", files=files, data={"consent": "on"})
    assert refused.status_code == 422
    posted = client.post(
        "/audits",
        files=files,
        data={"consent": "on", "initial_balance": "20000", **MAPPING},
        follow_redirects=False,
    )
    assert posted.status_code == 303, posted.text[:500]
    report = client.get(posted.headers["location"])
    assert report.status_code == 200
    # The column map shows the customer's own column beside what it was read as.
    assert "<li><code>Gané</code><svg" in report.text and "<span>resultado</span>" in report.text


def test_a_mapped_column_missing_from_the_file_is_named(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"report": ("mi_diario.csv", _own_journal(), "text/csv")}
    answer = client.post(
        "/audits",
        files=files,
        data={"consent": "on", **MAPPING, "col_profit": "Perdí"},
    )
    assert answer.status_code == 422
    assert "Perdí" in answer.text


def test_one_column_chosen_for_two_fields_is_refused_naming_both(tmp_path: Path) -> None:
    # Entry and exit time from one column made every trade last zero seconds.
    client = _client(tmp_path)
    files = {"report": ("mi_diario.csv", _own_journal(), "text/csv")}
    twice = {**MAPPING, "col_exit_time": "Cuando entré"}
    for locale, words in (
        ("es", "se eligió para dos campos (hora de entrada y hora de salida)"),
        ("en", "was chosen for two fields (entry time and exit time)"),
    ):
        refused = client.post(
            "/audits", files=files, data={"consent": "on", "locale": locale, **twice}
        )
        assert refused.status_code == 422
        assert words in refused.text


def test_a_control_character_in_a_typed_column_name_is_dropped(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"report": ("mi_diario.csv", _own_journal(), "text/csv")}
    typed = {**MAPPING, "col_profit": "Ga\x00né\t"}
    posted = client.post(
        "/audits", files=files, data={"consent": "on", **typed}, follow_redirects=False
    )
    assert posted.status_code == 303, posted.text[:500]
    assert "\x00" not in client.get(posted.headers["location"]).text
