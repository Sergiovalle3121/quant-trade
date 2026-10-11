"""Entry-page aggregates use only the site's finite public content taxonomy."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import (  # noqa: E402
    challenge_calc,
    funnel,
    institutional,
    reading,
    ruin_calc,
)
from quant_trade.audit.articles import ARTICLES, article_url  # noqa: E402
from quant_trade.audit.audiences import AUDIENCE_PAGES, audience_url  # noqa: E402
from quant_trade.audit.calculator import CALCULATOR_PATH  # noqa: E402
from quant_trade.audit.examples import EXAMPLES_PATH  # noqa: E402
from quant_trade.audit.guides import GUIDES, guide_url  # noqa: E402
from quant_trade.audit.pages import LANDING_PATHS  # noqa: E402
from quant_trade.audit.rules_table import RULES_TABLE_PATH  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.tools_hub import TOOLS_PATH  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402
from quant_trade.audit.winrate import WINRATE_PATH  # noqa: E402

BROWSER = {"User-Agent": "Mozilla/5.0 PagePrivacySentinel", "X-Forwarded-For": "192.0.2.91"}
KEY = "k" * 40
QUERY_SECRET = "private-query-sentinel"


def _pages() -> list[tuple[str, str, str]]:
    pages = [
        (path, locale, group)
        for group, paths in (
            ("landing", LANDING_PATHS),
            ("calculadora-suerte", CALCULATOR_PATH),
            ("calculadora-aciertos", WINRATE_PATH),
            ("calculadora-ruina", ruin_calc.RUIN_PATH),
            ("reglas-prop-firm", RULES_TABLE_PATH),
            ("lectura", reading.READING_PATH),
            ("herramientas", TOOLS_PATH),
            ("ejemplos", EXAMPLES_PATH),
            ("revision-institucional", institutional.REVIEW_PATHS),
        )
        for locale, path in paths.items()
    ]
    pages.extend(
        (path, locale, f"calculadora-reto/{firm}" if firm else "calculadora-reto")
        for path, (locale, firm) in challenge_calc.PAGES.items()
    )
    for locale in ("es", "en", "pt"):
        pages.extend((guide_url(g.slug, locale), locale, f"guias/{g.slug}") for g in GUIDES)
        pages.extend(
            (article_url(a.key, locale), locale, f"articulos/{a.slug_for('es')}") for a in ARTICLES
        )
        pages.extend(
            (audience_url(a.slug, locale), locale, f"audiencia/{a.slug}") for a in AUDIENCE_PAGES
        )
    return pages


@pytest.fixture(scope="module")
def app(tmp_path_factory: pytest.TempPathFactory) -> Any:
    directory = tmp_path_factory.mktemp("page-visits")
    return create_app(
        AuditSettings(
            database_url=f"sqlite:///{directory}/audit.db", admin_key=KEY, bootstrap_samples=100
        )
    )


@pytest.mark.parametrize(("path", "locale", "group"), _pages())
def test_public_routes_use_canonical_groups_without_query_or_person_data(
    app: Any, path: str, locale: str, group: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    counted: list[dict[str, str]] = []
    monkeypatch.setattr(app.state.visits, "add", lambda **kw: counted.append(kw))
    response = TestClient(app, headers=BROWSER).get(
        path, params={"ref": "f6", "token": QUERY_SECRET, "email": "private@example.test"}
    )
    assert response.status_code == 200
    assert counted == [
        {
            "day": funnel.day_of(datetime.now(UTC)),
            "locale": locale,
            "ref": "f6",
            "page_group": group,
        }
    ]
    assert funnel.clean_page_group(group) == group
    assert all(value not in repr(counted) for value in (*BROWSER.values(), QUERY_SECRET))


@pytest.mark.parametrize("public_id", ["ejemplo", "ejemplo-senal"])
def test_reserved_public_samples_share_the_sample_group(
    app: Any, public_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    counted: list[dict[str, str]] = []
    monkeypatch.setattr(app.state.visits, "add", lambda **kw: counted.append(kw))
    response = TestClient(app, headers=BROWSER).get(f"/v/{public_id}?lang=en&ref=share")
    assert response.status_code == 200
    assert [(v["locale"], v["page_group"]) for v in counted] == [("en", "v/ejemplo")]


def test_daily_cookie_preserves_first_entry_and_first_ref(app: Any) -> None:
    client = TestClient(app, headers=BROWSER)
    first = client.get("/calculadora-reto/ftmo?ref=f6")
    assert first.cookies.get(funnel.SEEN_COOKIE) == funnel.day_of(datetime.now(UTC))
    assert client.get("/calculadora-ruina?ref=f4").status_code == 200
    assert client.get("/lectura").status_code == 200
    app.state.visits.flush()
    rows = app.state.store.page_visit_rows(funnel.day_of(datetime.now(UTC)))
    assert [(locale, ref, group, count) for _, locale, ref, group, count in rows] == [
        ("es", "f6", "calculadora-reto/ftmo", 1)
    ]


def test_page_group_allowlist_rejects_arbitrary_paths_and_identifiers() -> None:
    for value in (
        "lectura?trades=123",
        "lectura#secret",
        "/lectura",
        "v/AbCd1234_-90",
        "calculadora-reto/unknown",
        "guias/private-id",
        "articulos/private-id",
        "audiencia/private-id",
        "https://example.test/lectura",
        "lectura/" + "x" * 100,
    ):
        assert funnel.clean_page_group(value) == ""
    assert all(len(group) <= 96 for group in funnel.page_groups())


def test_memory_counter_batches_by_group_and_retries_only_failed_groups() -> None:
    class Sink:
        fail = True
        rows: list[dict[str, Any]] = []

        def count_visit(self, **kw: Any) -> None:
            if self.fail and kw["page_group"] == "lectura":
                raise RuntimeError("unavailable")
            self.rows.append(kw)

    sink = Sink()
    counter = funnel.VisitCounter(sink)
    for group in ("lectura", "lectura", "landing"):
        counter.add(day="2026-10-11", locale="es", ref="f6", page_group=group)
    assert sink.rows == []
    counter.flush()
    assert [(r["page_group"], r["amount"]) for r in sink.rows] == [("landing", 1)]
    sink.fail = False
    counter.flush()
    counter.flush()
    assert [(r["page_group"], r["amount"]) for r in sink.rows] == [("landing", 1), ("lectura", 2)]
    with pytest.raises(ValueError, match="invalid visit page group"):
        counter.add(day="2026-10-11", locale="es", ref="f6", page_group="lectura?private=1")


def test_panel_displays_only_aggregate_visit_dimensions(tmp_path: Path) -> None:
    app = create_app(AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", admin_key=KEY))
    client = TestClient(app, headers=BROWSER)
    client.get("/lectura", params={"ref": "f4", "private": QUERY_SECRET})
    assert "<h3>Páginas</h3>" not in client.get("/panel").text
    panel = client.post("/panel", data={"key": KEY})
    assert panel.status_code == 200
    assert "Páginas" in panel.text and "lectura" in panel.text
    assert all(value not in panel.text for value in (*BROWSER.values(), QUERY_SECRET))
    assert "rigor_seen" not in panel.text
    assert set(app.state.store.funnel_page_visits.c.keys()) == {
        "day",
        "locale",
        "ref",
        "page_group",
        "visits",
    }
