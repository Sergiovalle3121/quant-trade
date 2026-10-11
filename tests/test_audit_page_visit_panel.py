"""The private page summary contains bounded aggregate entry counters only."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.funnel import DIRECT, Funnel  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.ops_panel import (  # noqa: E402
    PageVisitRow,
    page_visits_section,
    top_entry_pages,
)
from quant_trade.audit.owner import funnel_section  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
KEY = "synthetic-page-counter-owner-key-" + "k" * 30


def _rows(page: str) -> list[list[str]]:
    return [
        [html.unescape(value) for value in re.findall(r"<td>(.*?)</td>", row)]
        for row in re.findall(r"<tbody>(.*?)</tbody>", page, re.S)[0].split("</tr>")
        if "<td>" in row
    ]


def test_page_windows_include_today_and_boundaries_in_utc() -> None:
    rows: list[PageVisitRow] = [
        ("2026-10-11", "es", "f4", "lectura", 1),
        ("2026-10-05", "en", "f5", "lectura", 2),
        ("2026-10-04", "es", "f4", "lectura", 4),
        ("2026-09-14", "es", "f4", "lectura", 8),
        ("2026-09-13", "es", "f4", "lectura", 16),
        ("2026-10-12", "es", "f4", "lectura", 32),
    ]
    # This is still October 11 UTC, despite the local date being October 12.
    at = datetime(2026, 10, 12, 1, tzinfo=timezone(timedelta(hours=14)))
    page = page_visits_section(rows, at=at)
    assert _rows(page) == [["lectura", "3", "15"]]
    assert "Últimos 7 días · MEASURED" in page
    assert "Últimos 28 días · MEASURED" in page
    assert find_claims(page) == []


def test_pages_sort_by_28_then_7_days_and_name_with_firms_inside_parent() -> None:
    rows: list[PageVisitRow] = [
        ("2026-10-11", "es", "f4", "calculadora-reto", 2),
        ("2026-10-11", "es", "f4", "calculadora-reto/ftmo", 4),
        ("2026-10-11", "en", "f5", "calculadora-reto/ftmo", 1),
        ("2026-09-14", "es", "f4", "calculadora-reto/the5ers", 5),
        ("2026-10-11", "es", "f4", "landing", 8),
        ("2026-10-11", "es", "f4", "herramientas", 8),
        ("2026-09-14", "es", "f4", "lectura", 8),
    ]
    page = page_visits_section(rows, at=NOW)
    assert _rows(page) == [
        ["calculadora-reto", "7", "12"],
        ["↳ calculadora-reto/ftmo", "5", "5"],
        ["↳ calculadora-reto/the5ers", "0", "5"],
        ["↳ calculadora-reto (sin firma)", "2", "2"],
        ["herramientas", "8", "8"],
        ["landing", "8", "8"],
        ["lectura", "0", "8"],
    ]
    assert "no se suma otra vez" in page
    assert "primera página registrada del día" in page
    assert "no todas las páginas vistas" in page


def test_ref_entry_uses_full_funnel_window_and_deterministic_ties() -> None:
    rows: list[PageVisitRow] = [
        ("2026-09-12", "es", "f4", "landing", 4),
        ("2026-10-11", "en", "f4", "lectura", 4),
        ("2026-09-11", "es", "f4", "calculadora-suerte", 10),
        ("2026-10-12", "es", "f4", "calculadora-suerte", 10),
        ("2026-10-11", "es", "f5", "calculadora-reto/ftmo", 3),
        ("2026-10-11", "en", "f5", "calculadora-reto/ftmo", 2),
        ("2026-10-11", "es", "f5", "calculadora-reto", 4),
    ]
    assert top_entry_pages(rows, at=NOW, days=30) == {
        "f4": "landing",
        "f5": "calculadora-reto/ftmo",
    }
    funnel = Funnel()
    for ref in ("f4", "f5", "f6"):
        funnel.add("visits", day="2026-10-11", locale="es", ref=ref, amount=9)
    page = funnel_section(funnel, days=30, example="/?ref=f4", page_rows=rows, at=NOW)
    ref_rows = _rows(page)
    assert {row[0]: row[-1] for row in ref_rows} == {
        "f4": "landing",
        "f5": "calculadora-reto/ftmo",
        "f6": "NOT_MEASURED",
        "Total": "—",
    }
    assert all(row[2] == "9" for row in ref_rows[:-1])
    assert "Página de entrada más frecuente · MEASURED" in page
    assert "últimos 30 días UTC con grupo registrado" in page
    assert find_claims(page) == []


def test_missing_historical_groups_are_not_reconstructed() -> None:
    funnel = Funnel()
    funnel.add("visits", day="2026-10-11", locale="es", ref="f4", amount=37)
    page = funnel_section(funnel, days=30, example="/?ref=f4", at=NOW)
    assert _rows(page)[0][-1] == "NOT_MEASURED"
    section = page.split("<section id='page-visits'>", 1)[1].split("</section>", 1)[0]
    assert _rows(section) == []
    assert "37" not in section
    assert "NOT_MEASURED · sin visitas por página registradas" in section
    assert "no se reconstruye" in section


def test_unbounded_page_inputs_never_reach_panel_or_ref_winners() -> None:
    private = "private-report-3847-customer@example.invalid-192.0.2.49"
    groups = [
        f"lectura?token={private}",
        f"v/{private}",
        f"/v/{private}",
        f"guias/{private}",
        f"articulos/{private}",
        f"calculadora-reto/{private}",
    ]
    rows: list[PageVisitRow] = [("2026-10-11", "es", "f4", group, 100) for group in groups]
    rows.append(("2026-10-11", "es", "f4", "v/publicacion", 1))
    funnel = Funnel()
    funnel.add("visits", day="2026-10-11", locale="es", ref="f4")
    page = funnel_section(funnel, days=30, example="/?ref=f4", page_rows=rows, at=NOW)
    assert private not in page
    assert "token=" not in page
    assert _rows(page)[0][-1] == "v/publicacion"
    assert "sin datos por persona, IP ni user agent" in page
    assert find_claims(page) == []


def test_private_panel_shows_entry_groups_without_request_or_person_details(tmp_path: Path) -> None:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", admin_key=KEY)
    store = make_store(settings.database_url)
    agent = "Mozilla/5.0 SyntheticUniqueBrowser3847"
    private = "synthetic-private-report-customer@example.invalid"
    client = TestClient(create_app(settings, store), headers={"user-agent": agent})
    assert client.get(f"/lectura?ref=f4&private={private}").status_code == 200
    # The existing daily cookie still prevents counting subsequent pages that day.
    assert client.get("/calculadora-reto/ftmo?ref=f4").status_code == 200
    assert "id='page-visits'" not in client.get("/panel").text
    response = client.post("/panel", data={"key": KEY})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    section = response.text.split("<section id='page-visits'>", 1)[1].split("</section>", 1)[0]
    assert _rows(section) == [["lectura", "1", "1"]]
    for value in (private, agent, "SyntheticUniqueBrowser3847", "testclient"):
        assert value not in response.text
    assert find_claims(response.text) == []


def test_retired_groups_keep_their_history_in_the_panel() -> None:
    """A renamed slug or a firm that left the calculator still counts in the totals."""
    rows: list[PageVisitRow] = [
        ("2026-10-11", "es", "f4", "articulos/slug-antiguo", 40),
        ("2026-10-10", "en", "f4", "calculadora-reto/firma-retirada", 3),
        ("2026-10-11", "es", "", "landing", 1),
        ("2026-10-11", "es", "f4", "Lectura", 100),  # never written: not a stored shape
        ("2026-10-11", "es", "f4", "lectura/x/y", 100),
    ]
    page = page_visits_section(rows, at=NOW)
    assert _rows(page) == [
        ["articulos/slug-antiguo", "40", "40"],
        ["calculadora-reto", "3", "3"],
        ["↳ calculadora-reto/firma-retirada", "3", "3"],
        ["landing", "1", "1"],
    ]
    assert "100" not in page
    assert top_entry_pages(rows, at=NOW, days=30) == {
        "f4": "articulos/slug-antiguo",
        DIRECT: "landing",
    }
