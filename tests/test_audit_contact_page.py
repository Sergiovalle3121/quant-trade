"""The contact page: who to write to, only from what the operator configured."""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import CONTACT_COPY, CONTACT_PATHS, contact_page  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

EMAIL = "soporte@operador.example"
CHAT = "https://wa.me/10000000000"


def _client(tmp_path: Path, **overrides: object) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        **overrides,  # type: ignore[arg-type]
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _text(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def test_the_contact_page_exists_in_three_languages_with_the_configured_channels(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, operator_contact=EMAIL, contact_url=CHAT)
    for locale, path in CONTACT_PATHS.items():
        response = client.get(path)
        assert response.status_code == 200
        page = response.text
        assert f"<html lang='{locale}'>" in page
        assert f"href='mailto:{EMAIL}'" in page and f"href='{CHAT}'" in page
        assert CONTACT_COPY[locale]["before_title"] in page
        assert find_claims(_text(page)) == []
        # Every language links the other two.
        for other, other_path in CONTACT_PATHS.items():
            if other != locale:
                assert f"href='{other_path}'" in page
    pt = _text(client.get("/pt/contato").text)
    for spanish in ("Escríbenos", "Antes de escribir", "Preguntas frecuentes", "informe"):
        assert spanish not in pt, spanish


def test_nothing_is_invented_when_the_operator_set_no_contact(tmp_path: Path) -> None:
    page = _client(tmp_path).get("/contacto").text
    assert "mailto:" not in page and "wa.me" not in page
    assert CONTACT_COPY["es"]["none"] in page
    # Only something that looks like one address becomes a mail link.
    assert "mailto:" not in contact_page(email="no es un correo")


def test_other_names_for_the_page_redirect_and_every_footer_links_it(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for alias, target in (
        ("/soporte", "/contacto"),
        ("/contact", "/en/contact"),
        ("/support", "/en/contact"),
        ("/en/support", "/en/contact"),
        ("/pt/suporte", "/pt/contato"),
    ):
        response = client.get(alias, follow_redirects=False)
        assert response.status_code == 301 and response.headers["location"] == target
    for path, target in (("/", "/contacto"), ("/en", "/en/contact"), ("/pt", "/pt/contato")):
        foot = client.get(path).text.split("<footer", 1)[1]
        assert f"href='{target}'" in foot
