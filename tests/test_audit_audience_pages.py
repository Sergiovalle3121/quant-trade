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
            if page.contact_cta:
                assert "class='aud-price'" not in text
            else:
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
    assert "tabla de rentabilidades mensuales de un fondo" in client.get("/auditar").text
    assert "monthly returns table (a year per row" in client.get("/en/audit").text


def test_trader_pages_link_the_universal_csv_guide(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert "/guias/csv-universal" in client.get("/para/traders-acciones-futuros-cripto").text
    assert "/guides/universal-csv" in client.get("/for/stock-futures-crypto-traders").text
    # The short landing links the export guides, whose index lists the same guide.
    from quant_trade.audit.guides import guides_index_url

    for locale, home, guide in (
        ("es", "/", "/guias/csv-universal"),
        ("en", "/en", "/guides/universal-csv"),
    ):
        assert f"href='{guides_index_url(locale)}'" in client.get(home).text
        assert guide in client.get(guides_index_url(locale)).text


def test_named_platforms_match_the_universal_guide_and_show_on_the_pages(tmp_path: Path) -> None:
    from quant_trade.audit.audiences import RECOGNISED_PLATFORMS

    assert len(RECOGNISED_PLATFORMS) == 24
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
    for path, form in (
        ("/para/compradores-de-robots", "/auditar"),
        ("/for/robot-buyers", "/en/audit"),
    ):
        assert f"href='{form}?extras=1'" in client.get(path).text
    for path in ("/para/retos-prop-firm", "/for/investors-managers-funds"):
        assert "extras=1" not in client.get(path).text
    assert "<details class='adv extras' open>" in client.get("/auditar?extras=1").text
    assert "<details class='adv extras'>" in client.get("/auditar").text
    # Links shared before the form had its own page still open the extra boxes.
    old = client.get("/?lang=es&extras=1", follow_redirects=False)
    assert old.status_code == 303 and old.headers["location"] == "/auditar?extras=1"
    old_en = client.get("/en?extras=1", follow_redirects=False)
    assert old_en.status_code == 303 and old_en.headers["location"] == "/en/audit?extras=1"


@pytest.mark.parametrize(
    ("locale", "path", "words"),
    [
        ("es", "/para/copiar-senales", ("Martingala y rejilla", "Sin stop de pérdida", "captura")),
        ("en", "/for/signal-copiers", ("Martingale and grids", "No stop loss", "screenshot")),
    ],
)
def test_signal_copiers_have_their_own_page(
    tmp_path: Path, locale: str, path: str, words: tuple[str, ...]
) -> None:
    client = _client(tmp_path, free_mode=False, access_codes=True, price_usd_cents=2900)
    text = client.get(path).text
    for word in words:
        assert word in text
    # The upload line links the export guide for the provider's account.
    assert "cuenta-proveedor" in text or "provider-account" in text
    assert find_claims(text) == []
    # The landing keeps four cards and links the fifth page under them.
    landing = client.get("/" if locale == "es" else "/en").text
    assert landing.count("class='card spot audience'") == 4
    assert "class='muted audience-also'" in landing and f"href='{path}'" in landing
    # The other case pages link to it too.
    other = client.get(audience_url("compradores-de-robots", locale)).text
    assert f"href='{path}'" in other


@pytest.mark.parametrize(
    ("locale", "path", "words"),
    [
        ("es", "/para/inversores-particulares", ("DEGIRO", "Trading 212", "dividendos")),
        ("en", "/for/retail-investors", ("DEGIRO", "Trading 212", "dividends")),
    ],
)
def test_retail_investors_have_their_own_page(
    tmp_path: Path, locale: str, path: str, words: tuple[str, ...]
) -> None:
    client = _client(tmp_path, free_mode=False, access_codes=True, price_usd_cents=2900)
    text = client.get(path).text
    for word in words:
        assert word in text
    # The page says what a trade history leaves out (open positions, dividends).
    assert find_claims(text) == []
    landing = client.get("/" if locale == "es" else "/en").text
    assert landing.count("class='card spot audience'") == 4
    assert f"href='{path}'" in landing


def test_prop_page_names_the_firm_fit_check(tmp_path: Path) -> None:
    client = _client(tmp_path)
    es = client.get("/para/retos-prop-firm").text
    en = client.get("/for/prop-firm-challenges").text
    assert "¿Con qué firma encaja tu historial?" in es and "mejor día" in es
    assert "Which firm does your history fit?" in en and "best-day" in en
    assert find_claims(es) == [] and find_claims(en) == []


def test_prop_page_counts_firm_challenges_apart_from_the_generic_one(tmp_path: Path) -> None:
    from quant_trade.audit.prop_presets import PRESETS

    firms = sum(1 for rules in PRESETS.values() if rules.firm != "Generic")
    programs = len({(r.firm, r.program) for r in PRESETS.values() if r.firm != "Generic"})
    assert firms == len(PRESETS) - 1
    # Each preset is one rule set of a firm's program (The5ers' Bootcamp one holds
    # for each of its three steps): the page counts rule sets and programs.
    assert programs < firms
    client = _client(tmp_path)
    es = client.get("/para/retos-prop-firm").text
    en = client.get("/for/prop-firm-challenges").text
    pt = client.get(audience_url("retos-prop-firm", "pt")).text
    count = len({r.firm for r in PRESETS.values() if r.firm != "Generic"})
    assert f"{firms} juegos de reglas de {programs} programas de {count} firmas" in es
    assert "más la fase 1 de un reto genérico de dos fases" in es
    assert f"{firms} rule sets from {programs} programs of {count} firms" in en
    assert f"{firms} conjuntos de regras de {programs} programas de {count} firmas" in pt
    # The firms they count, named in a sentence of their own.
    assert "Las firmas: FTMO, FundedNext" in es and "The firms: FTMO, FundedNext" in en
    assert f"{firms} fases de" not in es and f"{firms} phases of" not in en
    assert f"{firms} retos de FTMO" not in es and f"{firms} desafios da FTMO" not in pt
