"""Publication share cards use the public allow-list and publication lifecycle."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import (  # noqa: E402
    BADGE_NOTICE,
    CLASS_WORD,
    verification_card_svg,
)
from quant_trade.audit.seo import OG_IMAGE_SIZE, og_image_name  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import Store, make_store  # noqa: E402
from quant_trade.audit.theme import STATIC_DIR  # noqa: E402
from quant_trade.audit.verdict import class_text  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
PRIVATE = "PRIVATE-INPUT-SENTINEL"
SVG = "{http://www.w3.org/2000/svg}"


def _assert_safe_svg(text: str) -> ElementTree.Element:
    root = ElementTree.fromstring(text)
    assert root.tag == f"{SVG}svg"
    assert root.attrib["role"] == "img"
    assert root.find(f"{SVG}title") is not None
    assert root.find(f"{SVG}desc") is not None
    assert root.attrib["viewBox"] == f"0 0 {OG_IMAGE_SIZE[0]} {OG_IMAGE_SIZE[1]}"
    assert (int(root.attrib["width"]), int(root.attrib["height"])) == OG_IMAGE_SIZE
    for element in root.iter():
        assert element.tag in {
            f"{SVG}{name}"
            for name in ("svg", "title", "desc", "g", "rect", "text", "tspan", "path")
        }
        assert not any(name.lower().startswith("on") for name in element.attrib)
        assert not any("href" in name.lower() for name in element.attrib)
    return root


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("overall", list("ABCD"))
def test_card_uses_only_public_fields_and_fixed_guard_clean_text(locale: str, overall: str) -> None:
    data = {
        "verdict": {"overall": overall, "summary": PRIVATE, "dimensions": [PRIVATE]},
        "generated_at_utc": "2026-09-24T12:34:56Z",
        "audit_id": PRIVATE,
        "token": PRIVATE,
        "description": PRIVATE,
        "declared": {"description": PRIVATE},
        "inputs": {"filename": PRIVATE, "parse_warnings": [PRIVATE]},
        "files": {"equity.csv": PRIVATE},
        "trades": [PRIVATE],
        "performance": {"sharpe": PRIVATE},
    }
    card = verification_card_svg(data, public_id="public123", locale=locale)
    root = _assert_safe_svg(card)
    text = " ".join(" ".join(root.itertext()).split())
    assert f"{CLASS_WORD[locale]} {overall}" in text
    assert "2026-09-24" in text and "public123" in text
    assert class_text(overall, locale) in text
    assert BADGE_NOTICE[locale] in text
    assert PRIVATE not in card
    assert find_claims(card) == []


def test_card_escapes_every_dynamic_text_and_defaults_to_spanish() -> None:
    hostile = "<script onload='alert(1)'>&\""
    data = {"verdict": {"overall": hostile}, "generated_at_utc": "<>&\"'"}
    card = verification_card_svg(data, public_id=hostile, locale="unknown")
    root = _assert_safe_svg(card)
    assert root.attrib["lang"] == "es"
    assert html.escape(hostile, quote=True) in card
    assert "<script" not in card
    assert hostile in " ".join(root.itertext())


def _published(tmp_path: Path) -> tuple[TestClient, Store, str, str, str]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        base_url=BASE,
    )
    store = make_store(settings.database_url)
    client = signed_in(TestClient(create_app(settings, store)))
    response = client.post(
        "/audits",
        files={"equity": (f"{PRIVATE}.csv", csv_bytes(positive_drift(500)), "text/csv")},
        data={"trials": "3", "consent": "on", "description": PRIVATE},
        follow_redirects=False,
    )
    location = response.headers["location"]
    audit_id = location.split("/audits/")[1].split("?")[0]
    token = location.split("token=")[1]
    publication = client.post(
        f"/audits/{audit_id}/publish?token={token}", headers={"accept": "application/json"}
    )
    assert publication.status_code == 201
    return client, store, audit_id, token, publication.json()["public_id"]


def test_card_endpoint_and_metadata_use_each_publications_language(tmp_path: Path) -> None:
    client, store, audit_id, token, public_id = _published(tmp_path)
    record = store.get_audit(audit_id)
    assert record is not None
    client.cookies.clear()  # The publication and its card need no owner session or token.
    for locale in ("es", "en", "pt"):
        response = client.get(f"/v/{public_id}/card.svg?lang={locale}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/svg+xml"
        assert response.headers["cache-control"] == "public, max-age=300"
        root = _assert_safe_svg(response.text)
        assert root.attrib["lang"] == locale
        assert find_claims(response.text) == []
        image_path = f"/v/{public_id}/card.png?lang={locale}"
        png = client.get(image_path)
        assert png.status_code == 200 and png.headers["content-type"] == "image/png"
        assert png.headers["cache-control"] == "public, max-age=300"
        assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert (
            int.from_bytes(png.content[16:20], "big"),
            int.from_bytes(png.content[20:24], "big"),
        ) == OG_IMAGE_SIZE
        # The complete bytes come from an existing safe class asset, never client data.
        name = og_image_name(f"class-{record.overall_class}", locale)
        assert png.content == (STATIC_DIR / name).read_bytes()
        page = client.get(f"/v/{public_id}?lang={locale}").text
        assert f"<meta property='og:image' content='{BASE}{image_path}'>" in page
        assert "<meta property='og:image:type' content='image/png'>" in page
        assert f"<meta property='og:image:width' content='{OG_IMAGE_SIZE[0]}'>" in page
        assert f"<meta property='og:image:height' content='{OG_IMAGE_SIZE[1]}'>" in page
        assert f"<meta name='twitter:image' content='{BASE}{image_path}'>" in page
        head = page.split("</head>")[0]
        for private in (PRIVATE, audit_id, token, "entry_time", "timestamp,equity"):
            assert private not in response.text and private not in head
    assert (
        client.get(f"/v/{public_id}/card.svg").text
        == client.get(f"/v/{public_id}/card.svg?lang=es").text
    )


@pytest.mark.parametrize("purge_first", [False, True])
def test_card_and_page_share_publication_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, purge_first: bool
) -> None:
    client, store, audit_id, token, public_id = _published(tmp_path)
    page_path = f"/v/{public_id}"
    card_paths = (f"{page_path}/card.svg", f"{page_path}/card.png")
    before = {path: client.get(path) for path in card_paths}
    assert client.get(page_path).status_code == 200
    assert all(response.status_code == 200 for response in before.values())
    if purge_first:
        assert store.purge_expired(datetime(2100, 1, 1, tzinfo=UTC), retention_days=1) == 1
        assert client.get(f"/audits/{audit_id}?token={token}").status_code == 410
        # AGENTS.md keeps published pages through retention; the card follows it.
        assert client.get(page_path).status_code == 200
        for path in card_paths:
            assert client.get(path).status_code == 200
            assert client.get(path).content == before[path].content
        # A legacy/missing retained public view is gone for both resources.
        with monkeypatch.context() as patch:
            patch.setattr(store, "publication_view", lambda _: None)
            for path in (page_path, *card_paths):
                response = client.get(path)
                assert response.status_code == 410
                assert response.headers["cache-control"] == "no-store"
    withdrawn = client.post(
        f"/audits/{audit_id}/unpublish?token={token}", headers={"accept": "application/json"}
    )
    assert withdrawn.json() == {"unpublished": True}
    for path in (page_path, *card_paths, "/v/unknown/card.svg", "/v/unknown/card.png"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-store"
        assert not re.search(r"<svg[^>]*aria-labelledby='verification-card", response.text)
