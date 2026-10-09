"""Public FAQ: localized facts, runtime configuration and matching JSON-LD."""

from __future__ import annotations

import html
import json
import re
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.faq import (  # noqa: E402
    FAQ_COPY,
    FAQ_PATH,
    faq_items,
    faq_page,
    landing_only_questions,
)
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import (  # noqa: E402
    _COPY,
    _LANDING_FAQ,
    CONTACT_COPY,
    card_markets_line,
)
from quant_trade.audit.report import evidence_label  # noqa: E402
from quant_trade.audit.seo import PUBLIC_PAGES  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
#: Eleven questions of this page, plus the landing's questions it does not show
#: (five; six in Portuguese, which also answers the report's language).
COUNT = {"es": 16, "en": 16, "pt": 17}


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
        STRIPE_SECRET_KEY="sk_live_faq_test_only",
        STRIPE_WEBHOOK_SECRET="whsec_faq_test_only",
        **environ,
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_every_localized_question_and_all_copy_pass_the_guard(locale: str) -> None:
    configurations = (
        AuditSettings(),
        _settings(AUDIT_EMAIL_VERIFICATION_REQUIRED="true"),
        _card_settings(AUDIT_APPROVED_MARKETS="MX,BR"),
    )
    for settings in configurations:
        pairs = faq_items(settings, locale)
        assert len(pairs) == COUNT[locale]
        assert len({question for question, _ in pairs}) == COUNT[locale]
        for question, answer in pairs:
            assert question and answer
            assert find_claims(question) == []
            assert find_claims(answer) == []
            assert "{" not in answer
        for value in FAQ_COPY[locale].values():
            assert find_claims(value) == []
        page = faq_page(settings, locale=locale, base_url=BASE)
        assert find_claims(page) == []
        if locale == "pt":
            assert not any(word in page for word in ("archivo", "informe", "Sube "))


@pytest.mark.parametrize("locale", LOCALES)
def test_prices_follow_settings_and_free_mode(locale: str) -> None:
    first = _settings(AUDIT_PRICE_USD_CENTS="1735")
    second = _settings(AUDIT_PRICE_USD_CENTS="4860")
    assert evidence_label("DECLARED", locale) + " · " in faq_items(first, locale)[0][1]
    assert f"USD {first.price_usd:.2f}" in faq_items(first, locale)[0][1]
    assert f"USD {second.price_usd:.2f}" in faq_items(second, locale)[0][1]
    assert f"USD {first.price_usd:.2f}" not in faq_items(second, locale)[0][1]
    assert "USD " not in faq_items(replace(first, free_mode=True), locale)[0][1]
    needs_email = replace(first, email_verification_required=True)
    assert faq_items(needs_email, locale)[0][1] != faq_items(first, locale)[0][1]


@pytest.mark.parametrize("locale", LOCALES)
def test_card_countries_come_only_from_active_runtime_markets(locale: str) -> None:
    for countries in ("MX", "BR,ES", "US,MX", "BR,ES,MX,US"):
        settings = _card_settings(AUDIT_APPROVED_MARKETS=countries)
        assert settings.card_public
        answer = faq_items(settings, locale)[1][1]
        expected = card_markets_line(tuple(settings.approved_markets), locale)
        assert answer.startswith(evidence_label("DECLARED", locale) + " · " + expected)
        assert find_claims(answer) == []
    active = _card_settings(AUDIT_APPROVED_MARKETS="MX")
    empty = _card_settings(AUDIT_APPROVED_MARKETS="")
    # Configuring a country alone must not advertise unavailable card payment.
    free = replace(active, free_mode=True)
    test_mode = replace(active, stripe_secret_key="sk_test_faq_test_only")
    inactive = _settings(AUDIT_APPROVED_MARKETS="MX")
    for settings in (empty, free, test_mode, inactive):
        assert not settings.card_public
        answer = faq_items(settings, locale)[1][1]
        assert answer == faq_items(AuditSettings(), locale)[1][1]
        assert evidence_label("DECLARED", locale) not in answer


@pytest.mark.parametrize("locale", LOCALES)
def test_retention_upload_limit_and_contact_follow_configuration(locale: str) -> None:
    settings = replace(
        _settings(AUDIT_RETENTION_DAYS="47"),
        max_upload_bytes=7 * 1024 * 1024,
        operator_contact="support@example.test",
        contact_url="https://example.test/contact",
    )
    pairs = faq_items(settings, locale)
    declared = evidence_label("DECLARED", locale)
    assert declared in pairs[2][1] and "7 MB" in pairs[2][1]
    assert declared in pairs[8][1] and str(settings.retention_days) in pairs[8][1]
    assert "30" not in pairs[8][1]
    # The FAQ must preserve legal.py's exception for the first free full report.
    first_free = {
        "es": "primer informe completo gratis",
        "en": "first free full report",
        "pt": "primeiro relatório completo grátis",
    }
    assert first_free[locale] in pairs[8][1]
    assert settings.operator_contact in pairs[-1][1]
    assert settings.contact_url in pairs[-1][1]
    assert CONTACT_COPY[locale]["none"] in faq_items(AuditSettings(), locale)[-1][1]


@pytest.mark.parametrize("locale", LOCALES)
def test_faq_json_is_valid_and_matches_every_visible_answer(locale: str) -> None:
    settings = _card_settings(AUDIT_PRICE_USD_CENTS="1725", AUDIT_APPROVED_MARKETS="BR,ES")
    page = faq_page(settings, locale=locale)
    blocks = re.findall(r"<script type='application/ld\+json'>(.*?)</script>", page, re.S)
    assert len(blocks) == 1
    data = json.loads(blocks[0])
    assert data["@context"] == "https://schema.org"
    assert data["@type"] == "FAQPage"
    assert len(data["mainEntity"]) == COUNT[locale]
    for entry, (question, answer) in zip(
        data["mainEntity"], faq_items(settings, locale), strict=True
    ):
        assert entry == {
            "@type": "Question",
            "name": question,
            "acceptedAnswer": {"@type": "Answer", "text": answer},
        }
        assert f"<summary>{html.escape(question, quote=True)}</summary>" in page
        assert f"<p>{html.escape(answer, quote=True)}</p>" in page


@pytest.mark.parametrize("locale", LOCALES)
def test_the_landing_questions_it_does_not_show_are_answered_here(locale: str) -> None:
    # The landing shows six questions and links this page for the rest: each of
    # those answers is public here, worded as on the landing, before the contact one.
    rest = landing_only_questions(locale)
    shown = set(_LANDING_FAQ[locale])
    assert rest == tuple(
        pair for index, pair in enumerate(_COPY[locale]["faq"]) if index not in shown
    )
    assert len(rest) == COUNT[locale] - 11
    pairs = faq_items(AuditSettings(), locale)
    assert pairs[10 : 10 + len(rest)] == rest
    contact = {"es": "contacto", "en": "contact", "pt": "contato"}[locale]
    assert contact in pairs[-1][0]
    page = faq_page(AuditSettings(), locale=locale)
    for question, answer in rest:
        assert find_claims(question) == [] and find_claims(answer) == []
        assert f"<summary>{html.escape(question, quote=True)}</summary>" in page
        assert f"<p>{html.escape(answer, quote=True)}</p>" in page
    # A forgotten password, how an account is protected and the badge, by name.
    topics = {
        "es": ("contraseña", "protegida", "sello"),
        "en": ("password", "protected", "badge"),
        "pt": ("senha", "protegida", "selo"),
    }[locale]
    questions = " ".join(question for question, _ in rest)
    assert all(topic in questions for topic in topics)
    assert landing_only_questions("xx") == landing_only_questions("es")


def test_dynamic_contact_is_escaped_in_visible_copy_and_json() -> None:
    contact = "</script><img src=x onerror=alert(1)> & support"
    settings = replace(AuditSettings(base_url=BASE), operator_contact=contact)
    page = faq_page(settings)
    assert contact not in page
    assert html.escape(contact, quote=True) in page
    block = re.search(r"<script type='application/ld\+json'>(.*?)</script>", page, re.S)
    assert block is not None
    assert "\\u003c/script\\u003e" in block.group(1)
    answer = json.loads(block.group(1))["mainEntity"][-1]["acceptedAnswer"]["text"]
    assert contact in answer


def test_page_routes_metadata_languages_sitemap_and_footer(tmp_path: Path) -> None:
    settings = replace(
        _settings(AUDIT_PRICE_USD_CENTS="4265"), database_url=f"sqlite:///{tmp_path}/faq.db"
    )
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    assert FAQ_PATH in PUBLIC_PAGES
    assert FAQ_PATH == {"es": "/preguntas", "en": "/en/faq", "pt": "/pt/perguntas"}
    for locale, path in FAQ_PATH.items():
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers.get("x-robots-tag") is None
        page = response.text
        assert f"<html lang='{locale}'>" in page
        assert "<h1" in page and FAQ_COPY[locale]["title"] in page
        assert f"<link rel='canonical' href='{BASE}{path}'>" in page
        assert "<meta name='robots' content='index, follow'>" in page
        assert f"USD {settings.price_usd:.2f}" in page
        assert find_claims(page) == []
        for language, alternate in FAQ_PATH.items():
            assert f"hreflang='{language}' href='{BASE}{alternate}'" in page
        home = {"es": "/", "en": "/en", "pt": "/pt"}[locale]
        landing = client.get(home).text
        assert f"href='{path}'" in landing
    sitemap = ElementTree.fromstring(client.get("/sitemap.xml").text)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locations = {entry.text for entry in sitemap.findall("s:url/s:loc", namespace)}
    assert {BASE + path for path in FAQ_PATH.values()} <= locations


def test_unknown_locale_falls_back_to_spanish() -> None:
    settings = AuditSettings()
    assert faq_items(settings, "xx") == faq_items(settings, "es")
    assert "<html lang='es'>" in faq_page(settings, locale="xx")
