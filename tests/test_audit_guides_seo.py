"""Export guides, page metadata, Open Graph previews, robots.txt and sitemap."""

from __future__ import annotations

import html
import re
from pathlib import Path
from xml.etree import ElementTree

import pytest
from audit_fixtures import csv_bytes, positive_drift

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guides import (  # noqa: E402
    GUIDES,
    GUIDES_COPY,
    REPORT_GUIDES,
    guide_url,
    guides_index_url,
)
from quant_trade.audit.importers import REPORT_FORMATS  # noqa: E402
from quant_trade.audit.pages import BADGE_NOTICE  # noqa: E402
from quant_trade.audit.seo import PUBLIC_PAGES  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
SECRET_DESCRIPTION = "my secret edge description omega"
SITEMAP_NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        **{"base_url": BASE, **overrides},
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _upload(client: TestClient) -> tuple[str, str]:
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    data = {"trials": "3", "consent": "on", "description": SECRET_DESCRIPTION}
    location = client.post("/audits", files=files, data=data, follow_redirects=False).headers[
        "location"
    ]
    return location.split("/audits/")[1].split("?")[0], location.split("token=")[1]


def _meta(text: str, key: str) -> str | None:
    match = re.search(rf"<meta (?:name|property)='{re.escape(key)}' content='([^']*)'>", text)
    return html.unescape(match.group(1)) if match else None


def _canonical(text: str) -> str | None:
    match = re.search(r"<link rel='canonical' href='([^']*)'>", text)
    return html.unescape(match.group(1)) if match else None


def _all_guide_texts() -> list[str]:
    texts: list[str] = []
    for guide in GUIDES:
        for text in guide.text.values():
            texts += [text.title, text.summary, text.file, text.upload, *text.steps, *text.tips]
    for copy in GUIDES_COPY.values():
        texts += list(copy.values())
    return texts


def test_every_guide_exists_in_both_languages_and_passes_the_guard() -> None:
    slugs = {guide.slug for guide in GUIDES}
    assert slugs == {
        "mt5",
        "mt5-optimization",
        "mt4",
        "tradingview",
        "ninjatrader",
        "quantconnect",
        "backtesting-py",
        "vectorbt",
    }
    for guide in GUIDES:
        assert set(guide.text) == {"es", "en"}
        assert guide.field in {"report", "optimization"}
        for text in guide.text.values():
            assert text.steps and text.tips
    for text in _all_guide_texts():
        assert find_claims(text) == [], text


def test_guides_cover_every_report_format_family() -> None:
    covered = " ".join(guide.slug for guide in REPORT_GUIDES)
    for fmt in REPORT_FORMATS:
        family = fmt.split("_")[0].replace("backtestingpy", "backtesting-py")
        assert family in covered, fmt


def test_guide_pages_render_with_metadata_and_a_language_switch(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for locale, other in (("es", "en"), ("en", "es")):
        index = client.get(guides_index_url(locale))
        assert index.status_code == 200
        assert f"<html lang='{locale}'>" in index.text
        assert find_claims(index.text) == []
        for guide in GUIDES:
            assert guide_url(guide.slug, locale) in index.text
            page = client.get(guide_url(guide.slug, locale))
            assert page.status_code == 200
            text = page.text
            assert f"<html lang='{locale}'>" in text
            assert html.escape(guide.text[locale].title, quote=True) in text
            assert _meta(text, "description") == guide.text[locale].summary
            assert _meta(text, "robots") == "index, follow"
            assert _canonical(text) == BASE + guide_url(guide.slug, locale)
            assert f"hreflang='{other}' href='{BASE}{guide_url(guide.slug, other)}'" in text
            assert f"href='{guide_url(guide.slug, other)}'" in text  # the switch
            assert find_claims(text) == []
    missing = client.get("/guias/amibroker")
    assert missing.status_code == 404
    assert missing.headers["x-robots-tag"] == "noindex, nofollow"


def test_upload_form_and_landing_link_the_guides(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path, locale in (("/", "es"), ("/en", "en")):
        text = client.get(path).text
        assert f"href='{guides_index_url(locale)}'" in text
        for guide in GUIDES:
            assert f"href='{guide_url(guide.slug, locale)}'" in text, guide.slug
        assert "id='subir'" in text


def test_error_pages_link_the_guides(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"report": ("x.csv", b"a,b\n1,2\n", "text/csv")}
    response = client.post("/audits", files=files, data={"trials": "1", "consent": "on"})
    assert response.status_code == 400
    assert f"href='{guides_index_url('es')}'" in response.text
    assert _meta(response.text, "robots") == "noindex, nofollow"


def test_public_pages_have_title_description_canonical_and_open_graph(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for pair in PUBLIC_PAGES:
        for locale, path in pair.items():
            response = client.get(path)
            assert response.status_code == 200, path
            text = response.text
            assert "X-Robots-Tag".lower() not in response.headers, path
            title = re.search(r"<title>([^<]+)</title>", text)
            assert title and title.group(1).strip(), path
            description = _meta(text, "description")
            assert description and len(description) >= 40, path
            assert _meta(text, "robots") == "index, follow", path
            assert _canonical(text) == BASE + path, path
            assert _meta(text, "og:url") == BASE + path, path
            assert _meta(text, "og:title"), path
            assert _meta(text, "og:description") == description, path
            assert _meta(text, "og:locale") == {"es": "es_ES", "en": "en_US"}[locale]
            assert "hreflang='x-default'" in text, path
            assert find_claims(text) == [], path


def test_query_language_variants_point_to_one_canonical_address(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert _canonical(client.get("/?lang=en").text) == f"{BASE}/en"
    assert _canonical(client.get("/ejemplo?lang=en").text) == f"{BASE}/sample"
    assert _canonical(client.get("/terminos?lang=en").text) == f"{BASE}/terms"


def test_robots_txt_blocks_private_paths_and_points_to_the_sitemap(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    lines = response.text.splitlines()
    assert "User-agent: *" in lines
    assert "Disallow: /audits/" in lines
    assert "Disallow: /webhooks/" in lines
    assert f"Sitemap: {BASE}/sitemap.xml" in lines
    assert "Disallow: /v/" not in lines  # link previews must reach /v pages


def test_sitemap_lists_only_the_public_pages_in_both_languages(tmp_path: Path) -> None:
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    client.post(f"/audits/{audit_id}/publish?token={token}")
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    root = ElementTree.fromstring(response.content)
    locs = [loc.text for loc in root.findall("s:url/s:loc", SITEMAP_NS)]
    expected = [BASE + pair[lang] for pair in PUBLIC_PAGES for lang in ("es", "en")]
    assert locs == expected
    assert len(locs) == len(set(locs))
    for required in ("/", "/en", "/ejemplo", "/sample", "/guias", "/guides", "/terminos"):
        assert BASE + required in locs
    for private in ("/audits", "/v/", "/health", "/webhooks", "token"):
        assert not any(private in loc for loc in locs if loc), private
    assert audit_id not in response.text
    assert "hreflang='en'" in response.text


def test_verification_page_previews_class_and_date_and_nothing_private(tmp_path: Path) -> None:
    client = _client(tmp_path)
    audit_id, token = _upload(client)
    response = client.post(
        f"/audits/{audit_id}/publish?token={token}", headers={"accept": "application/json"}
    )
    public_id = response.json()["public_id"]
    page = client.get(f"/v/{public_id}")
    text = page.text
    overall = re.search(r"<span class='cls'[^>]*>([A-D])</span>", text)
    assert overall
    og_title = _meta(text, "og:title")
    og_description = _meta(text, "og:description")
    assert og_title and f"Clase {overall.group(1)}" in og_title
    assert og_description and re.search(r"\d{4}-\d{2}-\d{2}", og_description)
    assert BADGE_NOTICE["es"] in og_description
    assert _meta(text, "og:url") == f"{BASE}/v/{public_id}"
    assert _meta(text, "robots") == "noindex, nofollow"
    head = text.split("</head>")[0]
    for secret in (SECRET_DESCRIPTION, token, audit_id):
        assert secret not in head
    english = client.get(f"/v/{public_id}?lang=en").text
    assert f"Class {overall.group(1)}" in (_meta(english, "og:title") or "")
    assert find_claims(text) == [] and find_claims(english) == []


def test_private_report_and_preview_pages_are_noindex(tmp_path: Path) -> None:
    for overrides in ({}, {"free_mode": False, "access_codes": True}):
        folder = tmp_path / str(len(overrides))
        folder.mkdir()
        client = _client(folder, **overrides)
        audit_id, token = _upload(client)
        page = client.get(f"/audits/{audit_id}?token={token}")
        assert page.status_code == 200
        assert _meta(page.text, "robots") == "noindex, nofollow"
        assert page.headers["x-robots-tag"] == "noindex, nofollow"
        assert _canonical(page.text) is None
        assert _meta(page.text, "og:url") is None
        head = page.text.split("</head>")[0]
        assert token not in head
    assert client.get("/health").headers["x-robots-tag"] == "noindex, nofollow"


def test_without_a_base_url_links_use_the_address_reached(tmp_path: Path) -> None:
    client = _client(tmp_path, base_url="http://localhost:8000")
    assert "Sitemap: http://testserver/sitemap.xml" in client.get("/robots.txt").text
    assert _canonical(client.get("/guias").text) == "http://testserver/guias"
    (tmp_path / "proxy").mkdir()
    proxied = _client(tmp_path / "proxy", base_url="http://localhost:8000", trusted_proxy_hops=1)
    assert _canonical(proxied.get("/en").text) == "https://testserver/en"
