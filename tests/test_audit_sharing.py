"""Public sharing cannot carry private report data or outlive publication."""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from test_audit_report import _result
from test_audit_verification_card import PRIVATE, _published

from quant_trade.audit.account import is_account_history
from quant_trade.audit.guard import find_claims
from quant_trade.audit.importers import MT5_HISTORY_HTML
from quant_trade.audit.pages import verification_page
from quant_trade.audit.report import render_html
from quant_trade.audit.sharing import COPY, share_block, share_text
from quant_trade.audit.store import public_view


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("overall", list("ABCD"))
@pytest.mark.parametrize("kind", ["backtest", "account"])
def test_fixed_share_text_is_guard_clean_and_x_uses_the_same_text(locale, overall, kind):
    text = share_text(overall=overall, public_id="public123", locale=locale, kind=kind)
    block = share_block(overall=overall, public_id="public123", locale=locale, kind=kind)
    assert find_claims(text) == []
    assert find_claims(" ".join(COPY[locale].values())) == []
    assert "https://rigorscore.com/v/public123?ref=share" in text
    assert f"/v/public123/card.svg?lang={locale}" in block
    intent = html.unescape(re.search(r"href='([^']+)'", block).group(1))
    assert intent.startswith("https://x.com/intent/post?")
    assert parse_qs(urlsplit(intent).query)["text"] == [text]
    assert html.escape(text) in block
    assert "data-copy='share-text'" in block and "readonly" in block


@pytest.mark.parametrize(
    ("locale", "account_phrase", "backtest_phrase"),
    [
        ("es", "Audité el historial de mi cuenta", "Audité mi backtest"),
        ("en", "I audited my account history", "I audited my backtest"),
        ("pt", "Auditei o histórico da minha conta", "Auditei meu backtest"),
    ],
)
@pytest.mark.parametrize("kind", ["backtest", "account"])
def test_share_channels_keep_kind_and_attribution_without_duplicating_telegram_url(
    locale: str, account_phrase: str, backtest_phrase: str, kind: str
) -> None:
    text = share_text(overall="B", public_id="public123", locale=locale, kind=kind)
    block = share_block(overall="B", public_id="public123", locale=locale, kind=kind)
    phrase = account_phrase if kind == "account" else backtest_phrase
    assert text.startswith(phrase)
    assert phrase in block
    url = "https://rigorscore.com/v/public123?ref=share"
    if locale != "es":
        url += f"&lang={locale}"
    links = [html.unescape(link) for link in re.findall(r"href='([^']+)'", block)]
    whatsapp = next(link for link in links if link.startswith("https://wa.me/?"))
    telegram = next(link for link in links if link.startswith("https://t.me/share/url?"))
    assert parse_qs(urlsplit(whatsapp).query) == {"text": [text]}
    telegram_query = parse_qs(urlsplit(telegram).query)
    assert telegram_query == {"url": [url], "text": [text.removesuffix(url).rstrip()]}
    assert "https://" not in telegram_query["text"][0]
    assert COPY[locale]["whatsapp"] in block
    assert COPY[locale]["telegram"] in block
    if kind == "backtest":
        assert text == share_text(overall="B", public_id="public123", locale=locale)


@pytest.mark.parametrize("kind", ["backtest", "account"])
@pytest.mark.parametrize("overall", ["", "E", "a", "<script>"])
def test_invalid_class_never_has_share_text_or_buttons(overall: str, kind: str) -> None:
    assert share_text(overall=overall, public_id="public123", kind=kind) == ""
    assert share_block(overall=overall, public_id="public123", kind=kind) == ""


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


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("kind", ["backtest", "account"])
def test_report_and_public_page_keep_the_kind_with_the_retained_public_view(
    locale: str, kind: str
) -> None:
    result = _result(locale, description=PRIVATE)
    if kind == "account":
        result = result.model_copy(
            update={"inputs": {**result.inputs, "source_format": MT5_HISTORY_HTML}}
        )
    data = result.model_dump(mode="json")
    # This is the allow-listed view retained by purge_expired; no new fields are needed.
    retained, digest = public_view(result.model_dump_json())
    assert is_account_history(data) == is_account_history(retained) == (kind == "account")
    assert retained["inputs"]["source_format"] == data["inputs"]["source_format"]
    expected = share_text(
        overall=str(data["verdict"]["overall"]),
        public_id="public123",
        locale=locale,
        kind=kind,
    )
    pages = [render_html(result, watermark=False, locale=locale, public_id="public123")]
    pages.extend(
        verification_page(
            view,
            public_id="public123",
            published_at="2026-10-07T00:00:00Z",
            result_sha256=digest,
            base_url="https://rigorscore.com",
            locale=locale,
        )
        for view in (data, retained)
    )
    for page in pages:
        block = re.search(r"<section[^>]+data-public-share>.*?</section>", page)
        assert block is not None
        assert html.escape(expected) in block.group()
        assert "https://wa.me/?" in block.group()
        assert "https://t.me/share/url?" in block.group()
        assert PRIVATE not in block.group()
        assert find_claims(html.unescape(page)) == []


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
