"""The 3-report pack and the misread-file refund, on the landing, the report and the terms."""

from __future__ import annotations

from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

SELLING = {
    "free_mode": False,
    "access_codes": True,
    "contact_url": "https://wa.me/000",
    "price_usd_cents": 2900,
}


def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100, **overrides
    )
    return signed_in(TestClient(create_app(settings, make_store(settings.database_url))))


def test_pack_is_on_sale_only_with_codes_and_a_real_discount() -> None:
    assert AuditSettings(**SELLING).pack_price_usd == 69.0
    assert AuditSettings(**{**SELLING, "pack_price_usd_cents": 0}).pack_price_usd == 0.0
    assert AuditSettings(**{**SELLING, "pack_price_usd_cents": 8700}).pack_price_usd == 0.0
    assert AuditSettings(**{**SELLING, "access_codes": False}).pack_price_usd == 0.0
    assert AuditSettings().pack_price_usd == 0.0  # free mode
    env = {"AUDIT_FREE_MODE": "false", "AUDIT_ACCESS_CODES": "true"}
    assert AuditSettings.from_env({**env, "AUDIT_PRICE_USD_CENTS": "2900"}).pack_price_usd == 69.0
    hidden = AuditSettings.from_env({**env, "AUDIT_PACK_PRICE_USD_CENTS": "0"})
    assert hidden.pack_price_usd == 0.0


def test_landing_shows_pack_and_refund_when_selling(tmp_path: Path) -> None:
    client = _client(tmp_path, **SELLING)
    es = client.get("/?lang=es").text
    assert "Pack de 3 informes: USD 69 (USD 23 cada uno)." in es
    assert "te devolvemos el importe de ese informe" in es
    en = client.get("/?lang=en").text
    assert "Pack of 3 reports: USD 69 (USD 23 each)." in en
    assert "we refund that report" in en
    assert find_claims(es) == [] and find_claims(en) == []


def test_free_mode_shows_neither(tmp_path: Path) -> None:
    page = _client(tmp_path).get("/?lang=es").text
    assert "Pack de 3" not in page
    assert "te devolvemos" not in page


def test_locked_report_offers_the_pack(tmp_path: Path) -> None:
    client = _client(tmp_path, **SELLING)
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(400)), "text/csv")}
    data = {"trials": "3", "cost_bps": "5", "consent": "on"}
    response = client.post("/audits", files=files, data=data, follow_redirects=False)
    report = client.get(response.headers["location"]).text
    assert "pack de 3 informes: USD 69" in report


def test_terms_state_the_pack_and_the_refund(tmp_path: Path) -> None:
    client = _client(tmp_path, **SELLING)
    es = client.get("/terminos").text
    assert "códigos de 3 créditos por USD 69.00" in es
    assert "lee mal tu archivo" in es
    en = client.get("/terms").text
    assert "codes with 3 credits for USD 69.00" in en
    assert "misreads your file" in en
    assert find_claims(es) == [] and find_claims(en) == []
