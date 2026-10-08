"""Pricing stays localized, truthful and driven by runtime configuration."""

from __future__ import annotations

import html
import json
import re
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.institutional import REVIEW_PATHS  # noqa: E402
from quant_trade.audit.pages import (  # noqa: E402
    _COPY,
    CONTACT_PATHS,
    _dimension_titles,
    card_markets_line,
)
from quant_trade.audit.pricing import PRICING_COPY, PRICING_PATH, pricing_page  # noqa: E402
from quant_trade.audit.report import evidence_label, localize_tags  # noqa: E402
from quant_trade.audit.seo import PUBLIC_PAGES  # noqa: E402
from quant_trade.audit.settings import PACK_CREDITS, AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")


def _settings(**environ: str) -> AuditSettings:
    return AuditSettings.from_env(
        {
            "AUDIT_BASE_URL": BASE,
            "AUDIT_FREE_MODE": "false",
            "AUDIT_ACCESS_CODES": "true",
            "AUDIT_PUBLIC_DATA": "false",
            "AUDIT_SKIP_EMAIL_DNS": "true",
            **environ,
        }
    )


def _card_settings(**environ: str) -> AuditSettings:
    return _settings(
        STRIPE_SECRET_KEY="sk_live_pricing_test_only",
        STRIPE_WEBHOOK_SECRET="whsec_pricing_test_only",
        **environ,
    )


def _product(page: str) -> dict:
    blocks = re.findall(r"<script type='application/ld\+json'>(.*?)</script>", page, re.S)
    documents = [json.loads(block) for block in blocks]
    products = [document for document in documents if document.get("@type") == "Product"]
    assert len(products) == 1
    product = products[0]
    assert product["@context"] == "https://schema.org"
    assert "aggregateRating" not in product
    assert "review" not in product
    return product


def _offers(product: dict) -> list[dict]:
    offers = product.get("offers", [])
    return [offers] if isinstance(offers, dict) else offers


class _Table(HTMLParser):
    """Inspect accessible row text independently of the page's CSS markup."""

    def __init__(self, page: str) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._in_table = False
        self._in_cell = False
        self.feed(page)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table = True
        elif self._in_table and tag == "tr":
            self.rows.append([])
        elif self._in_table and tag in {"th", "td"}:
            self._in_cell = True
            self.rows[-1].append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._in_table = False
        elif tag in {"th", "td"}:
            self._in_cell = False

    def handle_data(self, data: str) -> None:
        if self._in_table and self._in_cell:
            self.rows[-1][-1] += data


@pytest.mark.parametrize("locale", LOCALES)
def test_localized_copy_and_paid_and_free_pages_pass_guard(locale: str) -> None:
    for value in PRICING_COPY[locale].values():
        assert find_claims(value) == []
    configurations = (
        AuditSettings(),
        _settings(AUDIT_EMAIL_VERIFICATION_REQUIRED="true"),
        _card_settings(AUDIT_APPROVED_MARKETS="MX,BR"),
    )
    for settings in configurations:
        page = pricing_page(settings, locale=locale, base_url=BASE)
        assert find_claims(page) == []
        assert html.escape(_COPY[locale]["not"], quote=True) in page
        if locale == "pt":
            assert not any(word in page for word in ("archivo", "informe", "Sube "))


@pytest.mark.parametrize("locale", LOCALES)
def test_both_full_reports_include_the_same_dimensions_and_evidence(locale: str) -> None:
    page = pricing_page(_settings(), locale=locale)
    rows = _Table(page).rows
    assert rows and len(rows[0]) == 3  # Row label and the two report plans.
    for title in _dimension_titles(locale).values():
        matching = [row for row in rows if title in row[0]]
        assert len(matching) == 1
        assert len(matching[0]) == 3
        assert matching[0][1] == matching[0][2]
        assert matching[0][1].strip()
    for tag in ("MEASURED", "DECLARED", "NOT_MEASURED"):
        assert evidence_label(tag, locale) in html.unescape(page)
    pdf_rows = [row for row in rows if "PDF" in row[0]]
    assert len(pdf_rows) == 1
    assert pdf_rows[0][1] == pdf_rows[0][2]
    words = PRICING_COPY[locale]
    for feature in ("evidence", "public", "compare", "support"):
        matching = [row for row in rows if row[0] == words[feature]]
        assert len(matching) == 1
        assert matching[0][1] == matching[0][2]
    for key in ("intro", "optional", "compare_note"):
        assert words[key] in html.unescape(page)


@pytest.mark.parametrize("locale", LOCALES)
def test_single_and_pack_prices_preserve_cents_from_settings(locale: str) -> None:
    first = _settings(AUDIT_PRICE_USD_CENTS="1735", AUDIT_PACK_PRICE_USD_CENTS="4155")
    second = _settings(AUDIT_PRICE_USD_CENTS="4860", AUDIT_PACK_PRICE_USD_CENTS="10725")
    first_page = pricing_page(first, locale=locale)
    second_page = pricing_page(second, locale=locale)
    for settings, page in ((first, first_page), (second, second_page)):
        assert f"USD {settings.price_usd:.2f}" in page
        assert f"USD {settings.pack_price_usd:.2f}" in page
        assert str(PACK_CREDITS) in html.unescape(page)
    assert f"USD {first.price_usd:.2f}" not in second_page
    assert f"USD {first.pack_price_usd:.2f}" not in second_page


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("pack_cents", ("0", "8675", "10000"))
def test_unavailable_or_non_discounted_pack_is_not_offered(locale: str, pack_cents: str) -> None:
    settings = _settings(AUDIT_PRICE_USD_CENTS="1735", AUDIT_PACK_PRICE_USD_CENTS=pack_cents)
    assert settings.pack_price_usd == 0
    page = pricing_page(settings, locale=locale)
    offers = _offers(_product(page))
    assert len(offers) == 1
    assert float(offers[0]["price"]) == settings.price_usd
    assert PRICING_COPY[locale]["pack_name"].format(n=PACK_CREDITS) not in page


@pytest.mark.parametrize("locale", LOCALES)
def test_pack_quantity_uses_the_settings_constant(
    locale: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("quant_trade.audit.settings.PACK_CREDITS", 5)
    monkeypatch.setattr("quant_trade.audit.pricing.PACK_CREDITS", 5)
    settings = _settings(AUDIT_PRICE_USD_CENTS="1735", AUDIT_PACK_PRICE_USD_CENTS="4155")
    page = pricing_page(settings, locale=locale)
    expected = PRICING_COPY[locale]["pack"].format(n=5, price=settings.pack_price_usd)
    # The evidence tag is localized during rendering, so check the quantity via
    # the localized pack name too, independently of that label's translation.
    assert expected.split(" · ", 1)[1] in html.unescape(page)
    assert PRICING_COPY[locale]["pack_name"].format(n=5) in {
        offer["name"] for offer in _offers(_product(page))
    }


@pytest.mark.parametrize("locale", LOCALES)
def test_card_countries_only_come_from_public_runtime_markets(locale: str) -> None:
    for countries in ("MX", "BR,ES", "US,MX", "BR,ES,MX,US"):
        settings = _card_settings(AUDIT_APPROVED_MARKETS=countries)
        assert settings.card_public
        page = pricing_page(settings, locale=locale)
        expected = card_markets_line(tuple(settings.approved_markets), locale)
        assert expected in html.unescape(page)
    active = _card_settings(AUDIT_APPROVED_MARKETS="MX")
    unavailable = (
        _card_settings(AUDIT_APPROVED_MARKETS=""),
        replace(active, free_mode=True),
        replace(active, stripe_secret_key="sk_test_pricing_test_only"),
        _settings(AUDIT_APPROVED_MARKETS="MX"),
    )
    for settings in unavailable:
        assert not settings.card_public
        page = pricing_page(settings, locale=locale)
        assert card_markets_line(("MX",), locale) not in html.unescape(page)


@pytest.mark.parametrize("locale", LOCALES)
def test_product_offers_match_runtime_prices_and_localized_canonical(locale: str) -> None:
    settings = _card_settings(AUDIT_PRICE_USD_CENTS="4265", AUDIT_PACK_PRICE_USD_CENTS="10245")
    page = pricing_page(settings, locale=locale)
    product = _product(page)
    offers = _offers(product)
    assert len(offers) == 2
    assert {float(offer["price"]) for offer in offers} == {
        settings.price_usd,
        settings.pack_price_usd,
    }
    for offer in offers:
        assert offer["@type"] == "Offer"
        assert offer["priceCurrency"] == "USD"
        assert offer["availability"] == "https://schema.org/InStock"
        assert offer["url"] == BASE + PRICING_PATH[locale]


@pytest.mark.parametrize("locale", LOCALES)
def test_free_mode_hides_paid_prices_and_offers(locale: str) -> None:
    settings = replace(
        _card_settings(AUDIT_PRICE_USD_CENTS="4265", AUDIT_PACK_PRICE_USD_CENTS="10245"),
        free_mode=True,
    )
    page = pricing_page(settings, locale=locale)
    assert "USD " not in page
    assert "42.65" not in page
    assert "102.45" not in page
    assert _offers(_product(page)) == []
    assert PRICING_COPY[locale]["free"] in html.unescape(page)
    assert localize_tags(PRICING_COPY[locale]["first_quantity"], locale) not in html.unescape(page)
    for title in _dimension_titles(locale).values():
        assert title in html.unescape(page)


@pytest.mark.parametrize("locale", LOCALES)
def test_first_free_report_email_requirement_follows_settings(locale: str) -> None:
    settings = _settings()
    note = PRICING_COPY[locale]["email_note"]
    required = replace(settings, email_verification_required=True)
    optional = replace(settings, email_verification_required=False)
    assert note in html.unescape(pricing_page(required, locale=locale))
    assert note not in html.unescape(pricing_page(optional, locale=locale))
    assert note not in html.unescape(pricing_page(replace(required, free_mode=True), locale=locale))


@pytest.mark.parametrize("locale", LOCALES)
def test_email_support_and_institutional_links_are_truthful(locale: str) -> None:
    words = PRICING_COPY[locale]
    for email in ("", "Contact us using our form", "support@example.test"):
        settings = replace(_settings(), operator_contact=email)
        page = pricing_page(settings, locale=locale)
        expected = "support_note" if "@" in email else "no_email"
        assert words[expected] in html.unescape(page)
        assert f"href='{CONTACT_PATHS[locale]}'" in page
        assert f"href='{REVIEW_PATHS[locale]}'" in page
        assert words["one_off"] in html.unescape(page)


def test_indexed_routes_translations_sitemap_and_home_links(tmp_path: Path) -> None:
    settings = replace(_settings(), database_url=f"sqlite:///{tmp_path}/pricing.db")
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    assert PRICING_PATH in PUBLIC_PAGES
    assert PRICING_PATH == {"es": "/precios", "en": "/en/pricing", "pt": "/pt/precos"}
    for locale, path in PRICING_PATH.items():
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers.get("x-robots-tag") is None
        page = response.text
        assert f"<html lang='{locale}'>" in page
        assert f"<link rel='canonical' href='{BASE}{path}'>" in page
        assert "<meta name='robots' content='index, follow'>" in page
        assert find_claims(page) == []
        for language, alternate in PRICING_PATH.items():
            assert f"hreflang='{language}' href='{BASE}{alternate}'" in page
        home = {"es": "/", "en": "/en", "pt": "/pt"}[locale]
        landing = client.get(home).text
        assert "id='pricing'" in landing
        assert f"href='{path}'" in landing
    sitemap = ElementTree.fromstring(client.get("/sitemap.xml").text)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locations = {entry.text for entry in sitemap.findall("s:url/s:loc", namespace)}
    assert {BASE + path for path in PRICING_PATH.values()} <= locations


def test_unknown_locale_falls_back_to_spanish() -> None:
    assert "<html lang='es'>" in pricing_page(AuditSettings(), locale="xx")
