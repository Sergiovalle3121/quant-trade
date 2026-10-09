"""The public page, its card and the private report say what was audited and when.

An account history reads as an account on ``/v`` and its card (never "the
backtest"), the page and the view kept by the purge show the data period and
the days between the last data point and the audit, and a backtest keeps its
wording and its static class card. Nothing here reaches the network.
"""

from __future__ import annotations

import copy
import html
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest
from audit_fixtures import csv_bytes, positive_drift

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from test_audit_public import _client  # noqa: E402
from test_audit_sharing import _published_history  # noqa: E402

from quant_trade.audit import raster  # noqa: E402
from quant_trade.audit.articles import _num  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import _COPY, _plain_date, verification_page  # noqa: E402
from quant_trade.audit.report import (  # noqa: E402
    LABELS,
    _data_age_text,
    data_age_days,
    render_html,
)
from quant_trade.audit.sample import synthetic_live_statement  # noqa: E402
from quant_trade.audit.schema import AuditResult  # noqa: E402
from quant_trade.audit.seo import og_image_name  # noqa: E402
from quant_trade.audit.store import public_view  # noqa: E402
from quant_trade.audit.theme import STATIC_DIR  # noqa: E402
from quant_trade.audit.verdict import MEANING, class_text, meaning  # noqa: E402

LOCALES = ("es", "en", "pt")
SVG = "{http://www.w3.org/2000/svg}"
NEW_FIELDS = ("first_timestamp", "last_timestamp", "observations", "frequency_label")
#: Backtest wording an account's public page must never carry.
BACKTEST_PHRASES = (
    "el backtest no supera",
    "the backtest does not pass",
    "o backtest não passa",
    "El resultado del backtest depende",
    "The backtest result depends",
    "O resultado do backtest depende",
    "Indica la fecha en la que termina la optimización",
    "State the date the optimisation ends",
)
#: The data-quality sentence that pointed to lists ``/v`` does not show.
OLD_DATA_QUALITY = (
    "Revisa la lista de banderas rojas",
    "Check the red flags and the questions",
    "lista de sinais de alerta",
)


def _text(page: str) -> str:
    bare = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", bare)).split())


def _publish(client: TestClient, files: dict[str, Any], **form: str) -> tuple[str, str, str]:
    response = client.post(
        "/audits", files=files, data={"consent": "on", **form}, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    location = response.headers["location"]
    audit_id = location.split("/audits/")[1].split("?")[0]
    token = location.split("token=")[1]
    published = client.post(f"/audits/{audit_id}/publish?token={token}", follow_redirects=False)
    assert published.status_code == 303
    public_id = published.headers["location"].split("/v/")[1].split("?")[0]
    return audit_id, token, public_id


def _account(tmp_path: Path) -> tuple[TestClient, Any, str, str, str, dict[str, Any]]:
    client, store = _client(tmp_path)
    files = {"report": ("statement.csv", synthetic_live_statement(), "text/csv")}
    audit_id, token, public_id = _publish(client, files)
    data = client.get(f"/audits/{audit_id}.json?token={token}").json()
    assert data["inputs"]["source_format"] == "myfxbook_csv"
    return client, store, audit_id, token, public_id, data


def _days(data: dict[str, Any]) -> int:
    audited = date.fromisoformat(data["generated_at_utc"][:10])
    return (audited - date.fromisoformat(data["inputs"]["last_timestamp"][:10])).days


def _status(data: dict[str, Any], name: str) -> str:
    return next(d["status"] for d in data["verdict"]["dimensions"] if d["name"] == name)


def test_account_history_reads_as_an_account_on_the_public_page(tmp_path: Path) -> None:
    client, _, audit_id, token, public_id, data = _account(tmp_path)
    overall = data["verdict"]["overall"]
    first = data["inputs"]["first_timestamp"][:10]
    last = data["inputs"]["last_timestamp"][:10]
    days = _days(data)
    assert days > 30  # the synthetic account ends in 2025
    for locale in LOCALES:
        copy_ = _COPY[locale]
        page = client.get(f"/v/{public_id}?lang={locale}").text
        text = _text(page)
        assert class_text(overall, locale, kind="account") in text
        for phrase in BACKTEST_PHRASES + OLD_DATA_QUALITY:
            assert phrase not in text, (locale, phrase)
        if _status(data, "costs") == "FAIL":
            assert meaning("costs", "FAIL", locale, account=True) in text
        oos = _status(data, "out_of_sample")
        assert meaning("out_of_sample", oos, locale, account=True) in text
        assert copy_["v_period"] in text
        assert _plain_date(first, locale) in text and _plain_date(last, locale) in text
        trades = data["trade_stats"]["trade_count"]["value"]
        assert f"{_num(trades, locale, 0)} {copy_['v_trades']}" in text
        assert f"{copy_['v_age']} {_num(days, locale, 0)}" in text
        assert f"{copy_['v_kind']} {copy_['v_kind_account']}" in text
        assert copy_["v_trials_undeclared"] in text
        assert page.count("<table class='kv'>") == 2
        assert find_claims(text) == []
        for secret in (token, audit_id, "entry_time", "timestamp,equity"):
            assert secret not in page


def test_account_card_svg_and_png_do_not_say_backtest(tmp_path: Path) -> None:
    client, _, _, _, public_id, data = _account(tmp_path)
    overall = data["verdict"]["overall"]
    for locale in LOCALES:
        svg = client.get(f"/v/{public_id}/card.svg?lang={locale}").text
        root = ElementTree.fromstring(svg)
        lines = [" ".join(span.itertext()) for span in root.iter(f"{SVG}tspan")]
        assert lines and not any("backtest" in line.lower() for line in lines), lines
        desc = root.find(f"{SVG}desc")
        assert desc is not None and desc.text is not None
        assert _COPY[locale]["v_kind_account"] in desc.text
        assert data["inputs"]["last_timestamp"][:10] in desc.text
        assert find_claims(svg) == []
    spanish = ElementTree.fromstring(client.get(f"/v/{public_id}/card.svg?lang=es").text)
    assert any("historial" in " ".join(s.itertext()) for s in spanish.iter(f"{SVG}tspan"))

    png = client.get(f"/v/{public_id}/card.png?lang=es")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.headers["cache-control"] == "public, max-age=300"
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert png.content != (STATIC_DIR / f"og-class-{overall}-es.png").read_bytes()


def test_account_card_png_draws_the_account_card_when_the_renderer_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drawn: list[str] = []

    def fake_png(svg: str) -> bytes:
        drawn.append(svg)
        return b"\x89PNG\r\n\x1a\nfake"

    monkeypatch.setattr(raster, "card_png", fake_png)
    client, _, _, _, public_id, data = _account(tmp_path)
    for _ in range(2):
        png = client.get(f"/v/{public_id}/card.png?lang=en")
        assert png.status_code == 200 and png.content == b"\x89PNG\r\n\x1a\nfake"
        assert png.headers["cache-control"] == "public, max-age=300"
    assert len(drawn) == 1  # the same card is rendered once
    assert class_text(data["verdict"]["overall"], "en", kind="account") in _text(drawn[0])


def test_account_card_png_falls_back_to_the_generic_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(raster, "card_png", lambda svg: None)
    client, _, _, _, public_id, _ = _account(tmp_path)
    for locale in LOCALES:
        png = client.get(f"/v/{public_id}/card.png?lang={locale}")
        assert png.status_code == 200 and png.headers["content-type"] == "image/png"
        assert png.content == (STATIC_DIR / og_image_name("", locale)).read_bytes()


def test_fund_track_record_reads_as_a_fund(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(raster, "card_png", lambda svg: None)
    client, store, audit_id, _, public_id = _published_history(tmp_path, "fund")
    record = store.get_audit(audit_id)
    data = json.loads(record.result_json)
    overall = data["verdict"]["overall"]
    for locale in LOCALES:
        text = _text(client.get(f"/v/{public_id}?lang={locale}").text)
        assert class_text(overall, locale, kind="fund") in text
        assert _COPY[locale]["v_kind_fund"] in text
        assert _COPY[locale]["v_period"] in text
        for phrase in BACKTEST_PHRASES:
            assert phrase not in text, (locale, phrase)
        assert find_claims(text) == []
        png = client.get(f"/v/{public_id}/card.png?lang={locale}").content
        assert png == (STATIC_DIR / og_image_name("", locale)).read_bytes()


def test_backtest_public_page_keeps_its_wording_and_static_card(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    audit_id, token, public_id = _publish(client, files, trials="3")
    data = client.get(f"/audits/{audit_id}.json?token={token}").json()
    overall = data["verdict"]["overall"]
    page = client.get(f"/v/{public_id}").text
    copy_ = _COPY["es"]
    assert f"<td>{copy_['v_kind']}</td><td>{copy_['v_kind_backtest']}</td>" in page
    text = _text(page)
    assert class_text(overall, "es") in text
    details = _text(re.findall(r"<table class='kv'>(.*?)</table>", page, flags=re.S)[1])
    # An equity curve has a period and observations but no trade count.
    assert copy_["v_period"] in details and copy_["v_observations"] in details
    assert copy_["v_trades"] not in details
    assert copy_["v_trials_undeclared"] not in text  # three trials were declared
    assert page.count("<table class='kv'>") == 2
    assert find_claims(text) == []
    png = client.get(f"/v/{public_id}/card.png")
    expected = (STATIC_DIR / og_image_name(f"class-{overall}", "es")).read_bytes()
    assert png.status_code == 200 and png.content == expected
    report = _text(client.get(f"/audits/{audit_id}?token={token}").text)
    first, last = data["inputs"]["first_timestamp"][:10], data["inputs"]["last_timestamp"][:10]
    assert f"{LABELS['es']['data_period']} {first} → {last}" in report
    assert LABELS["es"]["data_age_account"] not in report  # only an account says it


def test_purged_view_keeps_period_and_kind(tmp_path: Path) -> None:
    client, store, audit_id, _, public_id, data = _account(tmp_path)
    view, digest = public_view(store.get_audit(audit_id).result_json)
    for key in NEW_FIELDS:
        assert view["inputs"][key] == data["inputs"][key]
    assert view["trade_stats"] == {"trade_count": data["trade_stats"]["trade_count"]}
    kept = json.dumps(view)
    for private in ("entry_time", "description", "series", "parse_warnings"):
        assert private not in kept, private

    page = verification_page(
        view,
        public_id="x",
        published_at="2026-10-08T00:00:00Z",
        result_sha256=digest,
        base_url="https://audit.example",
        locale="es",
    )
    text = _text(page)
    first, last = data["inputs"]["first_timestamp"][:10], data["inputs"]["last_timestamp"][:10]
    period = f"{_plain_date(first, 'es')} → {_plain_date(last, 'es')}"
    assert f"{_COPY['es']['v_period']} {period}" in text
    assert class_text(data["verdict"]["overall"], "es", kind="account") in text
    assert _COPY["es"]["v_kind_account"] in text

    # A view kept before the page showed the period renders without those rows.
    old = copy.deepcopy(view)
    for key in NEW_FIELDS:
        old["inputs"].pop(key)
    old.pop("trade_stats")
    legacy = verification_page(
        old,
        public_id="x",
        published_at="2026-10-08T00:00:00Z",
        result_sha256=digest,
        base_url="https://audit.example",
        locale="es",
    )
    legacy_text = _text(legacy)
    assert _COPY["es"]["v_period"] not in legacy_text
    assert _COPY["es"]["v_age"] not in legacy_text
    assert _COPY["es"]["v_kind_account"] in legacy_text
    assert legacy.count("<table class='kv'>") == 2

    # The purge keeps exactly what the page shows: the page reads the same after it.
    before = {locale: client.get(f"/v/{public_id}?lang={locale}").text for locale in LOCALES}
    assert store.purge_expired(datetime(2100, 1, 1, tzinfo=UTC), retention_days=1) == 1
    for locale in LOCALES:
        assert client.get(f"/v/{public_id}?lang={locale}").text == before[locale]


def test_private_report_shows_data_period_and_age(tmp_path: Path) -> None:
    client, store, audit_id, token, _, data = _account(tmp_path)
    first, last = data["inputs"]["first_timestamp"][:10], data["inputs"]["last_timestamp"][:10]
    days = _days(data)
    spanish = _text(client.get(f"/audits/{audit_id}?token={token}").text)
    result = AuditResult.model_validate_json(store.get_audit(audit_id).result_json)
    for locale in LOCALES:
        labels = LABELS[locale]
        text = (
            spanish
            if locale == "es"
            else _text(render_html(result, watermark=False, locale=locale))
        )
        assert f"{labels['data_period']} {first} → {last}" in text
        assert labels["data_age"].format(days=days) in text
        assert labels["data_age_account"] in text
        assert find_claims(text) == []


def test_data_age_counts_calendar_days_and_reads_in_the_singular() -> None:
    def data(audited: str, last: str | None) -> dict[str, Any]:
        return {"generated_at_utc": audited, "inputs": {"last_timestamp": last}}

    assert data_age_days(data("2026-10-08T00:10:00Z", "2026-10-07T23:50:00Z")) == 1
    assert data_age_days(data("2026-10-08T00:10:00Z", "2026-10-08T00:00:00Z")) == 0
    assert data_age_days(data("2026-10-08T00:10:00Z", None)) is None
    assert data_age_days(data("2026-10-08T00:10:00Z", "2026-10-09T00:00:00Z")) is None
    assert data_age_days({}) is None
    singular = {"es": "1 día entre", "en": "1 day between", "pt": "1 dia entre"}
    for locale in LOCALES:
        assert _data_age_text(1, LABELS[locale]).startswith(singular[locale])
        assert _data_age_text(2, LABELS[locale]).startswith("2 ")


def test_new_public_and_report_texts_exist_in_every_language_and_pass_the_guard() -> None:
    keys = (
        "v_kind",
        "v_kind_backtest",
        "v_kind_account",
        "v_kind_fund",
        "v_period",
        "v_observations",
        "v_observation_one",
        "v_trades",
        "v_trade_one",
        "v_age",
        "v_trials_undeclared",
    )
    for locale in LOCALES:
        for key in keys:
            assert _COPY[locale][key] and find_claims(_COPY[locale][key]) == [], (locale, key)
        for key in ("data_period", "data_age", "data_age_one", "data_age_account"):
            assert find_claims(LABELS[locale][key]) == [], (locale, key)
        for key in ("costs.FAIL.account", "data_quality.WEAK"):
            text = MEANING[locale][key]
            assert find_claims(text) == [] and "backtest" not in text.lower(), (locale, key)
    assert len({_COPY[locale]["v_kind_account"] for locale in LOCALES}) == 3
    assert len({LABELS[locale]["data_age_account"] for locale in LOCALES}) == 3
    assert len({MEANING[locale]["costs.FAIL.account"] for locale in LOCALES}) == 3
