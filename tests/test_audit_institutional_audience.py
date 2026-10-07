"""The institutional audience keeps its evidence limits and local contact path."""

from __future__ import annotations

import html
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.audiences import AUDIENCE_PAGES, audience_url  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import CONTACT_PATHS  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        base_url="https://audit.example",
        free_mode=False,
        access_codes=True,
        price_usd_cents=2900,
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


@pytest.mark.parametrize(
    ("locale", "path", "home"),
    [
        ("es", "/para/gestoras-y-senales", "/"),
        ("en", "/for/funds-and-signal-providers", "/en"),
        ("pt", "/pt/para/gestoras-e-sinais", "/pt"),
    ],
)
def test_institutional_page_is_indexable_and_routes_to_contact(
    client: TestClient, locale: str, path: str, home: str
) -> None:
    audience = next(page for page in AUDIENCE_PAGES if page.slug == "gestoras-y-senales")
    assert audience.contact_cta is True
    assert audience_url(audience.slug, locale) == path
    response = client.get(path)
    assert response.status_code == 200
    page = response.text
    assert f"<html lang='{locale}'>" in page
    assert html.escape(audience.text[locale].title) in page
    assert "index, follow" in page
    assert f"rel='canonical' href='https://audit.example{path}'" in page
    assert f"content='https://audit.example/static/og-{locale}.png'" in page
    assert client.get(f"/static/og-{locale}.png").status_code == 200
    for language in ("es", "en", "pt"):
        assert f"https://audit.example{audience_url(audience.slug, language)}" in page
    assert f"href='{CONTACT_PATHS[locale]}'" in page
    assert client.get(CONTACT_PATHS[locale]).status_code == 200
    assert "class='aud-price'" not in page
    assert f"https://audit.example{path}<" in client.get("/sitemap.xml").text
    assert f"href='{path}'" in client.get(home).text
    assert f"href='{path}'" in client.get(audience_url("compradores-de-robots", locale)).text
    assert find_claims(html.unescape(page)) == []


def test_institutional_copy_explains_evidence_and_missing_inputs() -> None:
    audience = next(page for page in AUDIENCE_PAGES if page.slug == "gestoras-y-senales")
    for locale, evidence, returns, benchmark in (
        ("es", "DECLARADO", "rendimientos", "benchmark"),
        ("en", "DECLARED", "returns", "benchmark"),
        ("pt", "DECLARADO", "retornos", "benchmark"),
    ):
        words = audience.text[locale]
        text = " ".join(
            [words.title, words.summary, *words.pains, *words.limits]
            + [part for pair in (*words.uploads, *words.checks, *words.faq) for part in pair]
        )
        assert evidence in text
        assert returns in text and benchmark in text
        assert find_claims(text) == []
