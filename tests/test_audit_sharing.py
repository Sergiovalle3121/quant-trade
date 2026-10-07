"""Public sharing cannot carry private report data or outlive publication."""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from test_audit_verification_card import PRIVATE, _published

from quant_trade.audit.guard import find_claims
from quant_trade.audit.pages import verification_page
from quant_trade.audit.sharing import COPY, share_block, share_text


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("overall", list("ABCD"))
def test_fixed_share_text_is_guard_clean_and_x_uses_the_same_text(locale, overall):
    text = share_text(overall=overall, public_id="public123", locale=locale)
    block = share_block(overall=overall, public_id="public123", locale=locale)
    assert find_claims(text) == []
    assert find_claims(" ".join(COPY[locale].values())) == []
    assert "https://rigorscore.com/v/public123?ref=share" in text
    assert f"/v/public123/card.svg?lang={locale}" in block
    intent = html.unescape(re.search(r"href='([^']+)'", block).group(1))
    assert intent.startswith("https://x.com/intent/post?")
    assert parse_qs(urlsplit(intent).query)["text"] == [text]
    assert html.escape(text) in block
    assert "data-copy='share-text'" in block and "readonly" in block


def test_share_fields_escape_text_and_url_components():
    block = share_block(overall="A", public_id="x'><script>alert(1)</script>")
    assert "<script>" not in block
    assert "%3Cscript%3E" in block
    assert "onerror=" not in block
    assert share_block(overall="<script>", public_id="public123") == ""


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_public_page_and_report_follow_publication_lifecycle(tmp_path: Path, locale: str):
    client, store, audit_id, token, public_id = _published(tmp_path)
    private_url = f"/audits/{audit_id}?token={token}&lang={locale}"
    for url in (private_url, f"/v/{public_id}?lang={locale}"):
        response = client.get(url)
        assert response.status_code == 200
        assert "data-public-share" in response.text
        block = re.search(r"<section[^>]+data-public-share>.*?</section>", response.text).group()
        assert f"/v/{public_id}?ref=share" in block
        assert find_claims(html.unescape(block)) == []
        for secret in (audit_id, token, PRIVATE, "equity.csv", "token="):
            assert secret not in block
    store.unpublish(audit_id)
    assert client.get(f"/v/{public_id}").status_code == 404
    assert "data-public-share" not in client.get(private_url).text
    # A previously published audit becomes private again, with its publish action.
    assert "/publish?" in client.get(private_url).text


def test_public_allow_list_does_not_expand_for_sharing():
    data = {
        "verdict": {"overall": "B", "dimensions": [], "summary": PRIVATE},
        "generated_at_utc": "2026-10-07T00:00:00Z",
        "inputs": {"filename": PRIVATE},
        "declared": {"description": PRIVATE},
        "audit_id": PRIVATE,
        "token": PRIVATE,
        "description": PRIVATE,
        "files": [PRIVATE],
        "trades": [PRIVATE],
        "performance": {"sharpe": PRIVATE},
    }
    page = verification_page(
        data,
        public_id="public123",
        published_at="2026-10-07T00:00:00Z",
        result_sha256="abc",
        base_url="https://rigorscore.com",
    )
    assert PRIVATE not in page
    assert "data-public-share" in page
    assert find_claims(page) == []
