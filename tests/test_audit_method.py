"""The public methodology page: numbers from the engine, guard-clean text."""

from __future__ import annotations

import html
import re

import pytest

from quant_trade.audit.guard import find_claims
from quant_trade.audit.method import METHOD_PATH, REFERENCES, dimension_rows, references
from quant_trade.audit.redflags import FLAG_TITLES
from quant_trade.audit.seo import PUBLIC_PAGES
from quant_trade.audit.verdict import DEFAULT_THRESHOLDS, Thresholds

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.web import create_app  # noqa: E402


def _text(page: str) -> str:
    body = page.split("<main", 1)[1].split("</main>", 1)[0]
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)))


@pytest.mark.parametrize("locale", ["es", "en"])
def test_method_page_lists_the_engines_thresholds_and_every_flag(locale: str) -> None:
    client = TestClient(create_app())
    response = client.get(METHOD_PATH[locale])
    assert response.status_code == 200
    text = _text(response.text)
    assert find_claims(text) == []
    assert f"{DEFAULT_THRESHOLDS.psr_pass:.2f}" in text
    assert f"{DEFAULT_THRESHOLDS.pbo_max:.2f}" in text
    for titles in FLAG_TITLES.values():
        assert titles[locale] in text
    # The authors are joined in the page's own language, never with a Spanish "y".
    assert references(locale)[0] in text
    assert ("López de Prado, M. y Zhu" in text) == (locale == "es")


def test_references_join_their_authors_in_each_language() -> None:
    assert references("es") == REFERENCES
    for locale, word in (("en", "and"), ("pt", "e")):
        listed = references(locale)
        assert len(listed) == len(REFERENCES)
        assert all(" y " not in ref for ref in listed)
        assert any(f"Politis, D. N. {word} Romano, J. P. (1994)" in ref for ref in listed)
    client = TestClient(create_app())
    assert "Politis, D. N. e Romano" in _text(client.get(METHOD_PATH["pt"]).text)


def test_dimension_rules_follow_the_thresholds() -> None:
    stricter = Thresholds(psr_pass=0.99, cost_pass_multiplier=5.0)
    for locale in ("es", "en"):
        rows = dimension_rows(locale, stricter)
        assert len(rows) == 6
        assert "0.99" in rows[0][2] and "5x" in rows[2][2]


def test_method_page_is_in_the_sitemap() -> None:
    assert dict(METHOD_PATH) in list(PUBLIC_PAGES)
