"""Entry-page aggregates use only the site's finite public content taxonomy."""

from __future__ import annotations

import logging
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
from quant_trade.audit.legal import LegalContext, privacy_text  # noqa: E402
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


#: What the privacy text calls each counted family of pages, per language (es, en, pt).
LEGAL_NAMES: dict[str, tuple[str, str, str]] = {
    "landing": ("página principal", "home page", "página inicial"),
    "audiencia": ("cada caso", "case pages", "páginas de casos"),
    "calculadora-suerte": ("calculadoras", "calculators", "calculadoras"),
    "calculadora-aciertos": ("calculadoras", "calculators", "calculadoras"),
    "calculadora-reto": ("calculadoras", "calculators", "calculadoras"),
    "calculadora-ruina": ("calculadoras", "calculators", "calculadoras"),
    "lectura": ("tarjeta de cifras", "figures card", "cartão de números"),
    "ejemplos": ("ejemplos", "examples", "exemplos"),
    "herramientas": ("página de herramientas", "tools page", "página de ferramentas"),
    "reglas-prop-firm": ("tabla de reglas", "rules table", "tabela de regras"),
    "v": ("verificación", "verification", "verificação"),
    "guias": ("guías", "guides", "guias"),
    "articulos": ("artículos", "articles", "artigos"),
    "revision-institucional": (
        "revisión institucional",
        "institutional review",
        "revisão institucional",
    ),
}
#: The dimensions the counter persists besides day, language and tag, as the
#: privacy text names them (es, en, pt).
LEGAL_DIMENSIONS: dict[str, tuple[str, str, str]] = {
    "page-group": ("grupo de página", "page group", "grupo de página"),
}


def _counting_paragraph(locale: str) -> str:
    """The privacy paragraph that describes the visit counter (it names the daily cookie)."""
    text = privacy_text(LegalContext(), locale)
    found = [p for _title, items in text.sections for p in items if funnel.SEEN_COOKIE in p]
    assert len(found) == 1, locale
    return found[0].lower()


def test_privacy_text_names_every_counted_page_family() -> None:
    families = {group.split("/", 1)[0] for group in funnel.page_groups()}
    assert families == set(LEGAL_NAMES), "a new family needs its legal name"
    for index, locale in enumerate(("es", "en", "pt")):
        paragraph = _counting_paragraph(locale)
        for family, names in LEGAL_NAMES.items():
            assert names[index] in paragraph, f"{locale}: privacy text no longer names {family}"
        for dimension, names in LEGAL_DIMENSIONS.items():
            assert names[index] in paragraph, f"{locale}: privacy text no longer names {dimension}"


def test_unlisted_campaign_tags_are_capped_per_flush_batch(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Sink:
        fail = False
        rows: list[dict[str, Any]] = []

        def count_visit(self, **kw: Any) -> None:
            if self.fail:
                raise RuntimeError("unavailable")
            self.rows.append(kw)

    sink = Sink()
    counter = funnel.VisitCounter(sink)
    limit = funnel.MAX_PENDING_CAMPAIGN_REFS
    tags = [f"dc-{chr(97 + i // 26)}{chr(97 + i % 26)}-100" for i in range(limit + 5)]
    assert all(funnel.clean_ref(tag) == tag and tag not in funnel.REF_TAGS for tag in tags)
    with caplog.at_level(logging.WARNING, logger="quant_trade.audit.funnel"):
        for tag in tags:
            counter.add(day="2026-10-11", locale="es", ref=tag, page_group="lectura")
        # A listed tag and an already pending campaign tag are never demoted.
        counter.add(day="2026-10-11", locale="es", ref="f6", page_group="lectura")
        counter.add(day="2026-10-11", locale="en", ref=tags[0], page_group="landing")
    assert sum("count as direct" in record.message for record in caplog.records) == 1
    # A failed write keeps the batch, and its tags still count toward the cap.
    sink.fail = True
    counter.flush()
    counter.add(day="2026-10-11", locale="es", ref=tags[-1], page_group="lectura")
    sink.fail = False
    counter.flush()
    by_ref = {(row["locale"], row["ref"], row["page_group"]): row["amount"] for row in sink.rows}
    assert all(by_ref[("es", tag, "lectura")] == 1 for tag in tags[:limit])
    assert all(("es", tag, "lectura") not in by_ref for tag in tags[limit:])
    assert by_ref[("es", "", "lectura")] == 6
    assert by_ref[("es", "f6", "lectura")] == 1
    assert by_ref[("en", tags[0], "landing")] == 1
    # The next batch starts afresh: a new campaign tag counts again.
    counter.add(day="2026-10-11", locale="es", ref=tags[-1], page_group="lectura")
    counter.flush()
    assert sink.rows[-1]["ref"] == tags[-1]


def test_a_counter_error_never_breaks_a_public_page(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", admin_key=KEY))

    def broken(**_kw: Any) -> None:
        raise ValueError("invalid visit page group")

    app.state.visits.add = broken
    client = TestClient(app, headers=BROWSER)
    with caplog.at_level(logging.WARNING, logger="quant_trade.audit.web"):
        response = client.get("/lectura", params={"private": QUERY_SECRET})
    assert response.status_code == 200
    messages = [record.getMessage() for record in caplog.records if "not counted" in record.message]
    assert messages == ["visit to lectura not counted: invalid visit page group"]
    assert QUERY_SECRET not in " ".join(messages)
