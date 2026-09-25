"""The Portuguese landing at /pt: every word in Portuguese, the guard applied,
and every page it links to that is not translated yet opens in English."""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.audiences import AUDIENCE_PAGES, audience_url  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guides import GUIDES, guide_url, guides_index_url  # noqa: E402
from quant_trade.audit.pages import _COPY, _UI, landing  # noqa: E402
from quant_trade.audit.portuguese import AUDIENCES_PT, INVESTOR_PT, link_locale  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

HREF = re.compile(r"href='([^']+)'")


def _client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        free_mode=False,
        access_codes=True,
        contact_url="https://wa.me/000",
        price_usd_cents=2900,
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _text(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def _paid(locale: str) -> str:
    return landing(
        locale=locale,
        free_mode=False,
        price_usd=29,
        access_codes=True,
        contact_url="https://wa.me/000",
        pack_price_usd=69,
        signed_in=False,
    )


def test_portuguese_has_every_landing_word() -> None:
    assert set(_COPY["es"]) <= set(_COPY["pt"])
    assert set(_UI["es"]) <= set(_UI["pt"])
    assert len(_COPY["pt"]["faq"]) >= len(_COPY["es"]["faq"])


def test_portuguese_landing_passes_the_guard_and_is_marked_portuguese() -> None:
    page = _paid("pt")
    assert "<html lang='pt'>" in page
    assert find_claims(_text(page)) == []
    for words in (AUDIENCES_PT, INVESTOR_PT, _COPY["pt"], _UI["pt"]):
        assert find_claims(repr(words)) == []
    # The honest limits stay: no prediction, no broker, no advice.
    text = _text(page)
    assert "não prevemos resultados" in text
    assert "não nos conectamos a nenhuma corretora" in text
    assert "não é uma promessa de resultados" in text


def test_portuguese_landing_has_no_spanish_left() -> None:
    text = _text(_paid("pt"))
    for spanish in ("Sube ", "archivo", "Precios", "Empezar", "cuenta gratis", "informe"):
        assert spanish not in text, spanish


def test_the_report_language_on_a_portuguese_page_is_portuguese() -> None:
    page = _paid("pt")
    assert "<option value='pt' selected>Português</option>" in page
    assert "O relatório sai em português, espanhol ou inglês." in page
    # Pages that have no Portuguese yet still link to English.
    assert link_locale("pt") == "en" and link_locale("es") == "es"


def test_every_landing_offers_the_other_two_languages() -> None:
    for locale, others in (("es", ("/en", "/pt")), ("en", ("/", "/pt")), ("pt", ("/", "/en"))):
        nav = _paid(locale).split("<main", 1)[0]
        for href in others:
            assert f"href='{href}' hreflang=" in nav, (locale, href)
        assert "Português" in nav or locale == "pt"


def test_every_link_on_the_portuguese_landing_opens(tmp_path: Path) -> None:
    client = _client(tmp_path)
    page = client.get("/pt")
    assert page.status_code == 200
    links = {
        href.split("#", 1)[0]
        for href in HREF.findall(page.text)
        if href.startswith("/") and not href.startswith("//")
    }
    assert "/pt" in links and "/pt/exemplo" in links and "/signup" in links
    for href in sorted(links - {""}):
        response = client.get(href, follow_redirects=False)
        assert response.status_code < 400, (href, response.status_code)
        # Pages not in Portuguese yet open in English, never in Spanish
        # ("/" is the language switch to Spanish).
        is_html = "text/html" in response.headers.get("content-type", "")
        if href != "/" and response.status_code == 200 and is_html:
            assert "<html lang='es'>" not in response.text, href


def test_the_portuguese_newsletter_form_comes_back_to_the_portuguese_page(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    page = client.get("/pt").text
    assert "<input type='hidden' name='lang' value='pt'>" in page
    joined = client.post(
        "/waitlist", data={"email": "ana@example.com", "lang": "pt"}, follow_redirects=False
    )
    assert joined.headers["location"] == "/pt?joined=1#news"
    assert "Inscrito. Obrigado." in client.get("/pt?joined=1").text
    bad = client.post("/waitlist", data={"email": "nope", "lang": "pt"}, follow_redirects=False)
    assert bad.headers["location"] == "/pt?error=email"
    assert "Esse endereço de e-mail não parece válido." in client.get("/pt?error=email").text


def test_search_engines_see_the_portuguese_landing(tmp_path: Path) -> None:
    client = _client(tmp_path)
    home = client.get("/").text
    assert "hreflang='pt' href='http://testserver/pt'" in home
    sitemap = client.get("/sitemap.xml").text
    assert "<loc>http://testserver/pt</loc>" in sitemap
    pt = client.get("/pt").text
    assert "<link rel='canonical' href='http://testserver/pt'>" in pt
    assert "content='pt_BR'" in pt
    assert "/static/og-en.png" in pt


@pytest.mark.parametrize("page", AUDIENCE_PAGES, ids=lambda page: page.slug)
def test_every_case_page_exists_in_portuguese(tmp_path: Path, page) -> None:
    client = _client(tmp_path)
    path = audience_url(page.slug, "pt")
    assert path.startswith("/pt/para/")
    response = client.get(path)
    assert response.status_code == 200
    assert "<html lang='pt'>" in response.text
    text = _text(response.text)
    assert find_claims(text) == []
    assert page.text["pt"].title in text
    for spanish in ("Qué subes", "Qué no hace", "Empezar gratis", "Otros casos", "archivo"):
        assert spanish not in text, spanish
    # The other languages, the start button and every link open.
    for lang in ("es", "en"):
        assert f"href='{audience_url(page.slug, lang)}' hreflang='{lang}'" in response.text
    assert "href='/pt" in response.text
    links = {
        href.split("#", 1)[0]
        for href in HREF.findall(response.text)
        if href.startswith("/") and not href.startswith("//")
    }
    for href in sorted(links - {""}):
        assert client.get(href, follow_redirects=False).status_code < 400, href


def test_a_case_page_slug_in_another_language_moves_to_the_portuguese_one(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    moved = client.get("/pt/para/retos-prop-firm", follow_redirects=False)
    assert moved.status_code == 301
    assert moved.headers["location"] == "/pt/para/desafios-prop-firm"
    assert (
        client.get("/pt/para/robot-buyers", follow_redirects=False).headers["location"]
        == "/pt/para/compradores-de-robos"
    )
    assert client.get("/pt/para/nothing-here").status_code == 404


def test_the_portuguese_landing_cards_open_the_portuguese_case_pages() -> None:
    page = _paid("pt")
    for case in AUDIENCE_PAGES:
        assert f"href='{audience_url(case.slug, 'pt')}'" in page


def _opens_every_link(client: TestClient, page: str) -> None:
    links = {
        href.split("#", 1)[0]
        for href in HREF.findall(page)
        if href.startswith("/") and not href.startswith("//")
    }
    for href in sorted(links - {""}):
        assert client.get(href, follow_redirects=False).status_code < 400, href


def test_the_guides_index_exists_in_portuguese(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert guides_index_url("pt") == "/pt/guias"
    response = client.get("/pt/guias")
    assert response.status_code == 200
    assert "<html lang='pt'>" in response.text
    assert find_claims(_text(response.text)) == []
    for guide in GUIDES:
        assert f"href='{guide_url(guide.slug, 'pt')}'" in response.text
    _opens_every_link(client, response.text)


@pytest.mark.parametrize("guide", GUIDES, ids=lambda guide: guide.slug)
def test_every_export_guide_exists_in_portuguese(tmp_path: Path, guide) -> None:
    client = _client(tmp_path)
    path = guide_url(guide.slug, "pt")
    assert path.startswith("/pt/guias/")
    response = client.get(path)
    assert response.status_code == 200
    text = _text(response.text)
    assert find_claims(text) == []
    assert guide.text["pt"].title in text
    for spanish in ("Pasos", "Dónde subirlo", "Antes de subirlo", "archivo", "Tu informe"):
        assert spanish not in text, spanish
    for lang in ("es", "en"):
        assert f"href='{guide_url(guide.slug, lang)}' hreflang='{lang}'" in response.text
    assert "href='/pt#subir'" in response.text
    _opens_every_link(client, response.text)


def test_portuguese_guides_name_the_portuguese_form_fields() -> None:
    labels = (_COPY["pt"]["report"], "Saldo inicial", "Adicionar mais arquivos")
    uploads = " ".join(
        guide.text["pt"].upload + " ".join(guide.text["pt"].tips) for guide in GUIDES
    )
    assert "Relatório da sua plataforma" in _COPY["pt"]["report"]
    assert "'Relatório da sua plataforma'" in uploads
    for label in labels[1:]:
        assert label in uploads
    for english in ("Your platform report", "Starting balance", "Add more files"):
        assert english not in uploads


def test_a_guide_slug_in_another_language_moves_to_the_portuguese_one(tmp_path: Path) -> None:
    client = _client(tmp_path)
    moved = client.get("/pt/guias/provider-account", follow_redirects=False)
    assert moved.status_code == 301
    assert moved.headers["location"] == "/pt/guias/conta-de-fornecedor"
    assert client.get("/pt/guias/nothing-here").status_code == 404
