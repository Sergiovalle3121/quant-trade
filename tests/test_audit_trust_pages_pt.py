"""The trust pages /pt links to exist in Portuguese: methodology, check and compare."""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import check, compare, method  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

PT_PAGES = {
    "method": {"es": "/metodologia", "en": "/methodology", "pt": "/pt/metodologia"},
    "check": {"es": "/comprobar", "en": "/check", "pt": "/pt/comprovar"},
    "compare": {"es": "/comparar", "en": "/compare", "pt": "/pt/comparar"},
}
SPANISH_WORDS = ("Cómo auditamos", "Comprobar", "informe", "archivo", "Pega ", "Sube ")


def _client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", free_mode=True)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _text(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def test_the_portuguese_words_cover_every_spanish_one() -> None:
    for copy in (method.COPY, check.COPY, compare.COPY):
        assert set(copy["es"]) == set(copy["pt"])
    rows_pt, rows_en = method.dimension_rows("pt"), method.dimension_rows("en")
    assert len(rows_pt) == len(rows_en)
    # The thresholds are the engine's, in every language.
    for (_, _, rule_pt), (_, _, rule_en) in zip(rows_pt, rows_en, strict=True):
        assert re.findall(r"\d+\.\d+|\d+x", rule_pt) == re.findall(r"\d+\.\d+|\d+x", rule_en)


@pytest.mark.parametrize("page", sorted(PT_PAGES))
def test_each_trust_page_opens_in_portuguese(tmp_path: Path, page: str) -> None:
    client = _client(tmp_path)
    paths = PT_PAGES[page]
    response = client.get(paths["pt"])
    assert response.status_code == 200
    assert "<html lang='pt'>" in response.text
    text = _text(response.text)
    assert find_claims(text) == []
    for spanish in SPANISH_WORDS:
        assert spanish not in text, spanish
    # The language bar offers the same page in Spanish and English, and they offer it back.
    for lang in ("es", "en"):
        assert f"href='{paths[lang]}' hreflang='{lang}'" in response.text, lang
        other = client.get(paths[lang]).text
        assert f"href='{paths['pt']}' hreflang='pt'" in other, lang


def test_the_portuguese_landing_links_to_the_portuguese_trust_pages(tmp_path: Path) -> None:
    page = _client(tmp_path).get("/pt").text
    for paths in PT_PAGES.values():
        assert f"href='{paths['pt']}'" in page, paths["pt"]
    for english in ("/methodology", "/check'", "/compare'", "/sample?lang=en"):
        assert f"href='{english}" not in page, english


def test_a_file_checked_from_pt_is_answered_in_portuguese(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"report": ("relatorio.pdf", b"%PDF-1.4 nada", "application/pdf")}
    response = client.post("/pt/comprovar", files=files)
    assert response.status_code == 200
    text = _text(response.text)
    assert "O Rigor não tem registro deste arquivo" in text
    assert "action='/pt/comprovar'" in response.text
    empty = client.post("/pt/comprovar", files={"report": ("x.pdf", b"", "application/pdf")})
    assert empty.status_code == 400
    assert "Escolha o arquivo do relatório" in _text(empty.text)


def test_links_pasted_on_the_pt_compare_page_are_answered_in_portuguese(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post("/pt/comparar", data={"link_a": "abc", "link_b": "def"})
    assert response.status_code == 400
    assert "Não reconhecemos um dos links" in _text(response.text)
    assert "action='/pt/comparar'" in response.text


def test_the_sitemap_lists_the_portuguese_trust_pages(tmp_path: Path) -> None:
    sitemap = _client(tmp_path).get("/sitemap.xml").text
    assert "/pt/metodologia" in sitemap and "/pt/comprovar" in sitemap
