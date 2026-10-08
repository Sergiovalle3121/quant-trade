"""Public sharing cannot carry private report data or outlive publication."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from audit_fixtures import signed_in
from fastapi.testclient import TestClient
from test_audit_report import _result
from test_audit_verification_card import BASE, PRIVATE, _published

from quant_trade.audit.account import is_account_history
from quant_trade.audit.guard import find_claims
from quant_trade.audit.importers import MT5_HISTORY_HTML
from quant_trade.audit.pages import verification_page
from quant_trade.audit.report import LABELS, _title, render_html, report_kind
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.sharing import COPY, share_block, share_text
from quant_trade.audit.store import Store, make_store, public_view
from quant_trade.audit.web import create_app

SHARE_PHRASES = {
    "es": {
        "account": "Audité el historial de mi cuenta",
        "backtest": "Audité mi backtest",
        "fund": "Audité el historial de mi fondo",
    },
    "en": {
        "account": "I audited my account history",
        "backtest": "I audited my backtest",
        "fund": "I audited my fund's track record",
    },
    "pt": {
        "account": "Auditei o histórico da minha conta",
        "backtest": "Auditei meu backtest",
        "fund": "Auditei o histórico do meu fundo",
    },
}


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("overall", list("ABCD"))
@pytest.mark.parametrize("kind", ["backtest", "account", "fund"])
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


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("kind", ["backtest", "account", "fund"])
def test_share_channels_keep_kind_and_attribution_without_duplicating_telegram_url(
    locale: str, kind: str
) -> None:
    text = share_text(overall="B", public_id="public123", locale=locale, kind=kind)
    block = share_block(overall="B", public_id="public123", locale=locale, kind=kind)
    phrase = SHARE_PHRASES[locale][kind]
    assert text.startswith(phrase)
    assert html.escape(phrase) in block
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
    anchors = re.findall(r"<a\b[^>]+>", block)
    assert len(anchors) == 3
    assert all("target='_blank'" in anchor for anchor in anchors)
    assert all("rel='noopener noreferrer'" in anchor for anchor in anchors)
    if kind == "backtest":
        assert text == share_text(overall="B", public_id="public123", locale=locale)


@pytest.mark.parametrize("kind", ["backtest", "account", "fund"])
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


def _published_history(tmp_path: Path, kind: str) -> tuple[TestClient, Store, str, str, str]:
    """Upload the synthetic account or fund file through the ordinary HTTP form."""
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        base_url=BASE,
    )
    store = make_store(settings.database_url)
    client = signed_in(TestClient(create_app(settings, store)))
    data = {"trials": "3", "consent": "on", "description": PRIVATE}
    if kind == "account":
        fixture = Path(__file__).parent / "fixtures" / "audit_imports" / "mt5_history.html"
        files = {"report": ("mt5_history.html", fixture.read_bytes(), "text/html")}
    else:
        rows = ["date,return"]
        for year in (2022, 2023):
            for month in range(1, 13):
                value = (1.0, -2.0, 3.0, 1.5)[(month - 1) % 4]
                rows.append(f"{year}-{month:02d}-01,{value}")
        files = {"equity": ("fund.csv", "\n".join(rows).encode(), "text/csv")}
        data.update(return_frequency="monthly", return_unit="percent")
    response = client.post("/audits", files=files, data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    location = urlsplit(response.headers["location"])
    audit_id = location.path.removeprefix("/audits/")
    token = parse_qs(location.query)["token"][0]
    record = store.get_audit(audit_id)
    assert record is not None and record.result_json is not None
    result = json.loads(record.result_json)
    assert report_kind(result) == kind
    if kind == "account":
        assert result["inputs"]["source_format"] == MT5_HISTORY_HTML
    else:
        assert result["fund"]["track_record"] is True
    publication = client.post(
        f"/audits/{audit_id}/publish?token={token}", headers={"accept": "application/json"}
    )
    assert publication.status_code == 201
    return client, store, audit_id, token, publication.json()["public_id"]


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("kind", ["backtest", "account", "fund"])
def test_public_page_and_report_follow_publication_lifecycle(
    tmp_path: Path, locale: str, kind: str
):
    client, store, audit_id, token, public_id = (
        _published(tmp_path) if kind == "backtest" else _published_history(tmp_path, kind)
    )
    private_url = f"/audits/{audit_id}?token={token}&lang={locale}"
    for url in (private_url, f"/v/{public_id}?lang={locale}"):
        response = client.get(url)
        assert response.status_code == 200
        assert "data-public-share" in response.text
        block = re.search(r"<section[^>]+data-public-share>.*?</section>", response.text).group()
        assert f"/v/{public_id}?ref=share" in block
        assert "https://wa.me/?" in block
        assert "https://t.me/share/url?" in block
        assert html.escape(SHARE_PHRASES[locale][kind]) in block
        assert find_claims(html.unescape(response.text)) == []
        assert find_claims(html.unescape(block)) == []
        for secret in (audit_id, token, PRIVATE, "equity.csv", "token="):
            assert secret not in block
    store.unpublish(audit_id)
    assert client.get(f"/v/{public_id}").status_code == 404
    assert "data-public-share" not in client.get(private_url).text
    # A previously published audit becomes private again, with its publish action.
    assert "/publish?" in client.get(private_url).text


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize(
    ("data", "kind", "title_key"),
    [
        ({}, "backtest", "title"),
        ({"inputs": {"source_format": MT5_HISTORY_HTML}}, "account", "title_account"),
        ({"fund": {"track_record": True}}, "fund", "title_fund"),
        (
            {"fund": {"track_record": True}, "inputs": {"source_format": MT5_HISTORY_HTML}},
            "fund",
            "title_fund",
        ),
    ],
)
def test_report_title_and_share_kind_use_the_same_classification(
    locale: str, data: dict, kind: str, title_key: str
) -> None:
    assert report_kind(data) == kind
    assert _title(data, LABELS[locale]) == LABELS[locale][title_key]


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
