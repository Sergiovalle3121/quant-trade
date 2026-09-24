"""Comparing two reports: only the owner's links, only unlocked reports, never in a URL."""

from __future__ import annotations

from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift, returns_frame, trades_frame

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.compare import COPY, parse_report_link  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

TOKEN = "A" * 43


def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100, **overrides
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _upload(client: TestClient, frame, *, trades: bool = True) -> str:
    files = {"equity": ("equity.csv", csv_bytes(frame), "text/csv")}
    if trades:
        files["trades"] = ("trades.csv", csv_bytes(trades_frame(20)), "text/csv")
    data = {"trials": "3", "cost_bps": "5", "consent": "on"}
    response = client.post("/audits", files=files, data=data, follow_redirects=False)
    assert response.status_code == 303
    return "https://rigor.example" + response.headers["location"]


def test_links_are_read_from_urls_and_paths() -> None:
    assert parse_report_link(f"https://x.app/audits/abc123def?token={TOKEN}&lang=es") == (
        "abc123def",
        TOKEN,
    )
    assert parse_report_link(f"/audits/abc123def?token={TOKEN}") == ("abc123def", TOKEN)
    assert parse_report_link(f"  audits/abc123def?token={TOKEN}  ") == ("abc123def", TOKEN)
    for bad in (
        "",
        "https://x.app/audits/abc123def",
        f"https://x.app/v/abc123def?token={TOKEN}",
        f"https://x.app/audits/abc123def?token={TOKEN}&token={TOKEN}",
        "https://x.app/audits/abc123def?token=short",
        f"https://x.app/audits/a'b<c?token={TOKEN}",
        "https://x.app/audits/" + "a" * 700 + f"?token={TOKEN}",
    ):
        assert parse_report_link(bad) is None, bad


def test_two_reports_side_by_side_in_both_languages(tmp_path: Path) -> None:
    client = _client(tmp_path)
    first = _upload(client, positive_drift(500))
    second = _upload(client, returns_frame(300, mean=0.0, seed=4), trades=False)
    for path, locale in (("/comparar", "es"), ("/compare", "en")):
        page = client.post(path, data={"link_a": first, "link_b": second, "lang": locale})
        assert page.status_code == 200, page.text[:300]
        assert COPY[locale]["dimensions"] in page.text
        assert COPY[locale]["report_b"] in page.text
        assert "noindex" in page.text
        assert find_claims(page.text) == []


def test_form_pages_exist_in_both_languages(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path, locale in (("/comparar", "es"), ("/compare", "en")):
        page = client.get(path)
        assert page.status_code == 200
        assert COPY[locale]["submit"] in page.text
        assert find_claims(page.text) == []


def test_wrong_token_same_report_and_bad_links_are_refused(tmp_path: Path) -> None:
    client = _client(tmp_path)
    first = _upload(client, positive_drift(500))
    second = _upload(client, positive_drift(400))
    forged = second.split("token=")[0] + "token=" + TOKEN
    refused = client.post("/comparar", data={"link_a": first, "link_b": forged})
    assert refused.status_code == 404
    assert COPY["es"]["not_found"] in refused.text
    same = client.post("/comparar", data={"link_a": first, "link_b": first})
    assert same.status_code == 400
    bad = client.post("/comparar", data={"link_a": first, "link_b": "hola"})
    assert bad.status_code == 400
    assert COPY["es"]["bad_link"] in bad.text


def test_locked_reports_cannot_be_compared(tmp_path: Path) -> None:
    client = _client(tmp_path, free_mode=False, access_codes=True, contact_url="https://wa.me/0")
    first = _upload(client, positive_drift(500))
    second = _upload(client, positive_drift(400))
    page = client.post("/comparar", data={"link_a": first, "link_b": second})
    assert page.status_code == 402
    assert COPY["es"]["locked"] in page.text
    # A locked report offers no compare form either.
    report = client.get(first.replace("https://rigor.example", ""))
    assert "name='link_b'" not in report.text


def test_an_unlocked_report_offers_the_compare_form(tmp_path: Path) -> None:
    client = _client(tmp_path)
    first = _upload(client, positive_drift(500))
    report = client.get(first.replace("https://rigor.example", ""))
    assert "action='/comparar'" in report.text
    assert "name='link_b'" in report.text
