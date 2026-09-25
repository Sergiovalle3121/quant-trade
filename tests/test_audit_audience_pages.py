"""One public page per kind of visitor, in Spanish and English, in the
sitemap, linked from the landing, and clean under the profit-claim guard."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.audiences import AUDIENCE_PAGES, audience_url  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guides import GUIDES_BY_SLUG  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402


def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        base_url="https://audit.example",
        **overrides,
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def test_every_audience_page_exists_in_both_languages(tmp_path: Path) -> None:
    client = _client(tmp_path, free_mode=False, access_codes=True, price_usd_cents=2900)
    for page in AUDIENCE_PAGES:
        for locale in ("es", "en"):
            path = audience_url(page.slug, locale)
            response = client.get(path)
            assert response.status_code == 200, path
            text = response.text
            assert f"<html lang='{locale}'>" in text
            assert page.text[locale].title.split(",")[0] in text
            assert "index, follow" in text
            assert f"https://audit.example{audience_url(page.slug, 'es')}" in text
            assert f"https://audit.example{audience_url(page.slug, 'en')}" in text
            assert "USD 29" in text
            assert find_claims(text) == [], path


def test_other_language_slug_redirects_and_unknown_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    page = AUDIENCE_PAGES[0]
    response = client.get(f"/para/{page.slug_en}", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == audience_url(page.slug, "es")
    assert client.get("/para/no-existe").status_code == 404


def test_audience_pages_are_in_the_sitemap_and_linked_from_the_landing(tmp_path: Path) -> None:
    client = _client(tmp_path)
    sitemap = client.get("/sitemap.xml").text
    landing = {"es": client.get("/").text, "en": client.get("/en").text}
    for page in AUDIENCE_PAGES:
        for locale in ("es", "en"):
            assert f"https://audit.example{audience_url(page.slug, locale)}<" in sitemap
            assert f"href='{audience_url(page.slug, locale)}'" in landing[locale]


def test_texts_name_only_existing_guides_and_both_languages_match() -> None:
    for page in AUDIENCE_PAGES:
        es, en = page.text["es"], page.text["en"]
        assert len(es.pains) == len(en.pains)
        assert len(es.uploads) == len(en.uploads)
        assert len(es.checks) == len(en.checks)
        assert len(es.faq) == len(en.faq)
        for text in (es, en):
            for _item, guide in text.uploads:
                assert guide == "" or guide in GUIDES_BY_SLUG


def test_fund_page_and_upload_help_mention_the_factsheet_table(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path, words in (
        ("/para/inversores-gestores-fondos", ("tabla de rentabilidades mensuales", "24 meses")),
        ("/for/investors-managers-funds", ("monthly returns table", "24 months")),
    ):
        page = client.get(path).text
        for word in words:
            assert word in page
    assert "tabla de rentabilidades mensuales de un fondo" in client.get("/").text
    assert "monthly returns table (a year per row" in client.get("/en").text


def test_trader_pages_link_the_universal_csv_guide(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert "/guias/csv-universal" in client.get("/para/traders-acciones-futuros-cripto").text
    assert "/guides/universal-csv" in client.get("/for/stock-futures-crypto-traders").text
    assert "cualquier bróker, exchange o diario" in client.get("/").text
    assert "any broker, exchange or journal" in client.get("/en").text


def test_named_platforms_match_the_universal_guide_and_show_on_the_pages(tmp_path: Path) -> None:
    from quant_trade.audit.audiences import RECOGNISED_PLATFORMS

    assert len(RECOGNISED_PLATFORMS) == 16
    guide = GUIDES_BY_SLUG["csv-universal"]
    for locale in ("es", "en"):
        tips = " ".join(guide.text[locale].tips)
        for name in RECOGNISED_PLATFORMS:
            assert name in tips, (locale, name)
    client = _client(tmp_path)
    for path in ("/para/traders-acciones-futuros-cripto", "/for/stock-futures-crypto-traders"):
        page = client.get(path).text
        for name in RECOGNISED_PLATFORMS:
            assert name.replace("&", "&amp;") in page, (path, name)
        assert find_claims(page) == []
    for path in ("/", "/en"):
        page = client.get(path).text
        assert "Interactive Brokers" in page and "Coinbase" in page
        assert find_claims(page) == []
    # Recognised, never "tried" or "tested" on customer files.
    for path in ("/para/retos-prop-firm", "/for/prop-firm-challenges"):
        page = client.get(path).text.lower()
        assert "tradovate" in page
        assert "probado" not in page and "tested on" not in page


def test_robot_buyers_land_on_the_form_with_the_extra_files_open(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path, lang in (("/para/compradores-de-robots", "es"), ("/for/robot-buyers", "en")):
        assert f"href='/?lang={lang}&amp;extras=1#subir'" in client.get(path).text
    for path in ("/para/retos-prop-firm", "/for/investors-managers-funds"):
        assert "extras=1" not in client.get(path).text
    assert "<details class='adv extras' open>" in client.get("/?lang=es&extras=1").text
    assert "<details class='adv extras'>" in client.get("/").text
