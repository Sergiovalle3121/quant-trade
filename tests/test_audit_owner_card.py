"""Private public-card workflow, without files, persistence, or external fetches."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import owner_card  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.public_card import PublicClaim, public_card_svg  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

KEY = "k" * 40
FIELDS = {
    "source_handle": "@public_source",
    "source_url": "https://example.test/public-post",
    "trades": "45",
    "win_rate_percent": "71",
    "profit_factor": "3.24",
    "sharpe": "1.8",
    "years": "3",
    "trials": "1000",
    "target_r": "1",
    "stop_r": "1",
}


def _client(tmp_path: Path, *, key: str = KEY, panel: str = "/panel") -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        admin_key=key,
        panel_path=panel,
        bootstrap_samples=100,
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_form_uses_the_cli_claim_model_and_percentage(locale: str) -> None:
    claim, svg = owner_card.render_form({**FIELDS, "locale": locale})
    expected = PublicClaim(
        source_handle=FIELDS["source_handle"],
        source_url=FIELDS["source_url"],
        trades=45,
        win_rate=0.71,
        profit_factor=3.24,
        sharpe=1.8,
        years=3,
        trials=1000,
        target_r=1,
        stop_r=1,
        locale=locale,  # type: ignore[arg-type]
    )
    assert claim == expected
    assert svg == public_card_svg(expected)
    root = ElementTree.fromstring(svg)
    assert root.tag.endswith("svg")
    # The card's typography: a decimal comma in es and pt, a point in en.
    assert ("71.0 %" if locale == "en" else "71,0 %") in svg
    assert ("3.24" if locale == "en" else "3,24") in svg
    assert find_claims(svg) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_all_form_copy_and_error_pages_pass_guard(locale: str) -> None:
    for code, text in owner_card.COPY[locale].items():
        assert find_claims(text) == [], code
        page = owner_card.page(key=KEY, panel_path="/panel", locale=locale, error=code)
        assert find_claims(page) == [], code
    claim, svg = owner_card.render_form({**FIELDS, "locale": locale})
    for enabled in (False, True):
        page = owner_card.page(
            key=KEY,
            panel_path="/panel",
            claim=claim,
            svg=svg,
            png_enabled=enabled,
        )
        assert find_claims(page) == []
        assert "DECLARED" in page
        assert "value='71'" in page
        assert "value='png'" in page if enabled else "value='png'" not in page


@pytest.mark.parametrize(
    "name,value",
    [
        ("source_handle", "rentable"),
        ("source_handle", "certified"),
        ("source_handle", "aprovado"),
        ("source_url", "https://example.test/garantiza"),
        ("source_handle", "a" * 2049),
        ("source_url", "a" * 2049),
        ("source_handle", "a\x00b"),
        ("trades", "0"),
        ("trials", "10000001"),
        ("trades", "3.5"),
        ("trials", "true"),
        ("win_rate_percent", "101"),
        ("win_rate_percent", "-1"),
        ("win_rate_percent", "NaN"),
        ("years", "0"),
        ("stop_r", "-1"),
        ("target_r", "0"),
        ("profit_factor", "-1"),
        ("sharpe", "1000001"),
        ("sharpe", "inf"),
        ("years", "1e999"),
        ("profit_factor", "1" * 41),
        ("locale", "fr"),
    ],
)
def test_invalid_fields_use_clear_error_codes_without_echo(name: str, value: str) -> None:
    with pytest.raises(owner_card.ClaimInputError) as found:
        owner_card.render_form({**FIELDS, name: value})
    assert str(found.value) in owner_card.COPY["es"]


def test_missing_declarations_are_not_invented() -> None:
    claim, svg = owner_card.render_form({})
    assert claim == PublicClaim()
    assert "NOT_MEASURED" in svg


def test_model_boundary_values_are_supported() -> None:
    claim = owner_card.claim_from_form(
        {
            "trades": "10000000",
            "trials": "10000000",
            "win_rate_percent": "100",
            "sharpe": "-1000000",
            "profit_factor": "0",
            "years": "1000000",
        }
    )
    assert claim.trades == 10_000_000
    assert claim.win_rate == 1
    assert claim.sharpe == -1_000_000


def test_attribution_is_escaped_and_never_becomes_svg_markup() -> None:
    claim, svg = owner_card.render_form({"source_handle": "<script>alert('x')</script>"})
    page = owner_card.page(key=KEY, panel_path="/panel", claim=claim, svg=svg)
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page
    root = ElementTree.fromstring(svg)
    assert all(not element.tag.endswith("script") for element in root.iter())
    assert all(not key.startswith("on") for element in root.iter() for key in element.attrib)


@pytest.mark.parametrize("key", ["", "short", KEY])
def test_route_without_owner_credentials_is_hidden(tmp_path: Path, key: str) -> None:
    client = _client(tmp_path, key=key)
    assert client.get("/panel/public-card").status_code == 404
    for action in ("", "preview", "svg", "png"):
        assert client.post("/panel/public-card", data={**FIELDS, "action": action}).status_code in (
            403,
            404,
        )
    if not key or key == "short":
        assert client.post("/panel/public-card", data={"key": key}).status_code == 404


def test_wrong_key_and_cross_site_requests_are_refused(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.post("/panel/public-card", data={"key": "x" * 40}).status_code in (403, 404)
    for headers in ({"Sec-Fetch-Site": "cross-site"}, {"Origin": "https://elsewhere.test"}):
        answer = client.post(
            "/panel/public-card",
            data={"key": KEY, "action": "preview", **FIELDS},
            headers=headers,
        )
        assert answer.status_code in (403, 404)
        assert "<div class='public-card-preview'>" not in answer.text


def test_card_route_shares_the_owner_failed_key_limit(tmp_path: Path) -> None:
    from quant_trade.audit.owner import MAX_FAILED_LOGINS_PER_HOUR

    client = _client(tmp_path)
    for _ in range(MAX_FAILED_LOGINS_PER_HOUR):
        answer = client.post("/panel/public-card", data={"key": "x" * 40})
        assert answer.status_code in (403, 404)
    blocked = client.post("/panel/public-card", data={"key": KEY, "action": "preview", **FIELDS})
    assert blocked.status_code == 429
    assert "<div class='public-card-preview'>" not in blocked.text


def test_hidden_owner_key_is_not_treated_as_a_visible_public_claim(tmp_path: Path) -> None:
    key = "certified-" + KEY
    client = _client(tmp_path, key=key)
    form = client.post("/panel", data={"key": key, "action": "public_card"})
    assert form.status_code == 200
    preview = client.post("/panel/public-card", data={"key": key, "action": "preview", **FIELDS})
    assert preview.status_code == 200
    assert "<div class='public-card-preview'>" in preview.text
    # Only the hidden authentication field contains the key; it is not card copy.
    svg = client.post("/panel/public-card", data={"key": key, "action": "svg", **FIELDS})
    assert svg.status_code == 200
    assert key not in svg.text
    assert find_claims(svg.text) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_valid_request_preview_and_download_are_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    locale: str,
) -> None:
    monkeypatch.setitem(sys.modules, "cairosvg", None)
    client = _client(tmp_path)
    data = {"key": KEY, "action": "preview", "locale": locale, **FIELDS}
    answer = client.post("/panel/public-card", data=data)
    assert answer.status_code == 200
    assert "<svg" in answer.text
    assert ("71.0 %" if locale == "en" else "71,0 %") in answer.text
    assert owner_card.COPY[locale]["png_unavailable"] in answer.text
    assert "value='svg'" in answer.text
    assert "value='png'" not in answer.text
    assert find_claims(answer.text) == []
    assert answer.headers["Cache-Control"] == "no-store"
    assert "noindex" in answer.headers["X-Robots-Tag"]
    svg = client.post("/panel/public-card", data={**data, "action": "svg"})
    assert svg.status_code == 200
    assert svg.headers["content-type"].startswith("image/svg+xml")
    assert "attachment" in svg.headers["content-disposition"]
    assert ".svg" in svg.headers["content-disposition"]
    assert svg.content.decode() == owner_card.render_form(data)[1]


def test_png_uses_memory_only_and_falls_back_to_svg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    png = b"\x89PNG\r\n\x1a\nlocal-test"
    received = []

    def svg2png(**kwargs: bytes) -> bytes:
        assert set(kwargs) == {"bytestring"}
        assert kwargs["bytestring"].startswith(b"<svg")
        received.append(kwargs)
        return png

    monkeypatch.setitem(sys.modules, "cairosvg", SimpleNamespace(svg2png=svg2png))
    client = _client(tmp_path)
    data = {"key": KEY, "action": "preview", **FIELDS}
    preview = client.post("/panel/public-card", data=data)
    assert "value='png'" in preview.text
    answer = client.post("/panel/public-card", data={**data, "action": "png"})
    assert answer.status_code == 200
    assert answer.content == png
    assert answer.headers["content-type"].startswith("image/png")
    assert "attachment" in answer.headers["content-disposition"]
    # The preview probes native rendering; the download converts the actual card.
    assert len(received) == 2
    assert b'width="1" height="1"' in received[0]["bytestring"]
    assert received[1]["bytestring"] == owner_card.render_form(data)[1].encode("utf-8")
    monkeypatch.setitem(sys.modules, "cairosvg", None)
    fallback = client.post("/panel/public-card", data={**data, "action": "png"})
    assert "<svg" in fallback.text
    assert owner_card.COPY["es"]["png_unavailable"] in fallback.text


def test_rejected_source_is_not_reflected_in_an_error_page(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for locale, bad in (("es", "rentable"), ("en", "certified"), ("pt", "aprovado")):
        answer = client.post(
            "/panel/public-card",
            data={
                "key": KEY,
                "action": "preview",
                "locale": locale,
                "source_handle": bad,
            },
        )
        assert answer.status_code == 400
        assert bad not in answer.text
        assert "<div class='public-card-preview'>" not in answer.text
        assert owner_card.COPY[locale]["source"] in answer.text
        assert find_claims(answer.text) == []


def test_panel_links_to_the_tool_at_its_configured_path(tmp_path: Path) -> None:
    client = _client(tmp_path, panel="/private-office/entry")
    page = client.post("/private-office/entry", data={"key": KEY})
    assert "name='action' value='public_card'" in page.text
    assert "Tarjeta pública" in page.text
    tool = client.post("/private-office/entry", data={"key": KEY, "action": "public_card"})
    assert tool.status_code == 200
    assert "name='win_rate_percent'" in tool.text
    actions = re.findall(r"<form method='post' action='([^']*)'", tool.text)
    assert "/private-office/entry/public-card" in actions
    assert client.post("/panel/public-card", data={"key": KEY}).status_code == 404


def test_successful_generation_writes_neither_database_nor_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "cairosvg", None)
    client = _client(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    marker = tmp_path / "state" / "untouched.txt"
    marker.write_text("existing state", encoding="utf-8")
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    for action in ("preview", "svg", "png"):
        answer = client.post("/panel/public-card", data={"key": KEY, "action": action, **FIELDS})
        assert answer.status_code == 200
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
