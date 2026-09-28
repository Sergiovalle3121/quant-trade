"""The monetary contradiction survives upload, storage and customer delivery."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from audit_fixtures import signed_in
from fastapi.testclient import TestClient

from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store
from quant_trade.audit.web import create_app, sign_stripe_payload

FIXTURE = Path(__file__).parent / "fixtures" / "audit_imports" / "mt5_tester.html"


def test_mt5_money_and_forensic_evidence_reaches_free_full_report(tmp_path: Path) -> None:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=50,
        free_mode=False,
        access_codes=True,
    )
    client = signed_in(
        TestClient(create_app(settings, make_store(settings.database_url))), welcome=True
    )
    uploaded = client.post(
        "/audits",
        files={"report": ("tester.html", FIXTURE.read_bytes(), "text/html")},
        data={"consent": "on", "locale": "es", "cost_bps": "1"},
        follow_redirects=False,
    )
    assert uploaded.status_code == 303, uploaded.text
    path, _, query = uploaded.headers["location"].partition("?")
    audit_id = path.rsplit("/", 1)[1]
    token = query.split("token=", 1)[1].split("&", 1)[0]
    record = client.app.state.store.get_audit(audit_id)
    assert record is not None and record.paid  # first complete report, no card
    body = client.get(f"/audits/{audit_id}.json?token={token}").json()
    assert body["reconciliation"]["status"] == "CONTRADICTION"
    assert body["reconciliation"]["difference"]["value"] == 1000.0
    assert any(
        check["id"] == "BALANCE_CHAIN" and check["status"] == "SIGNAL"
        for check in body["forensics"]["checks"]
    )
    html = client.get(f"/audits/{audit_id}?token={token}").text
    assert "1000" in html or "1,000" in html
    assert "BALANCE_CHAIN" in html
    assert "MONETARY_RECONCILIATION_MISMATCH" in {flag["code"] for flag in body["red_flags"]}


def test_paid_delivery_preserves_the_same_monetary_and_forensic_limits(tmp_path: Path) -> None:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=50,
        free_mode=False,
        access_codes=False,
        stripe_secret_key="sk_live_synthetic_test",
        stripe_webhook_secret="whsec_synthetic_test",
        approved_markets=frozenset({"MX"}),
    )
    client = signed_in(TestClient(create_app(settings, make_store(settings.database_url))))
    uploaded = client.post(
        "/audits",
        files={"report": ("tester.html", FIXTURE.read_bytes(), "text/html")},
        data={"consent": "on", "locale": "es", "cost_bps": "1"},
        follow_redirects=False,
    )
    assert uploaded.status_code == 303, uploaded.text
    path, _, query = uploaded.headers["location"].partition("?")
    audit_id = path.rsplit("/", 1)[1]
    token = query.split("token=", 1)[1].split("&", 1)[0]
    assert not client.app.state.store.get_audit(audit_id).paid

    session_id = "cs_synthetic_monetary"
    order_ids: list[str] = []

    def fake_checkout(
        cfg: AuditSettings,
        audit_id: str,
        token: str,
        *,
        plan: str,
        locale: str,
        order_id: str,
        amount_cents: int,
    ) -> dict[str, Any]:
        assert plan == "single" and amount_cents == 2900
        order_ids.append(order_id)
        return {"id": session_id, "url": "https://checkout.stripe.test/synthetic"}

    client.app.state.checkout_factory = fake_checkout
    checkout = client.post(
        f"/audits/{audit_id}/checkout?token={token}",
        data={"plan": "single", "billing_country": "MX"},
        follow_redirects=False,
    )
    assert checkout.status_code == 303 and len(order_ids) == 1
    event = json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": session_id,
                    "payment_status": "paid",
                    "livemode": True,
                    "currency": "usd",
                    "amount_total": 2900,
                    "customer_details": {"address": {"country": "MX"}},
                    "metadata": {
                        "audit_id": audit_id,
                        "plan": "single",
                        "app": "rigor",
                        "order_id": order_ids[0],
                    },
                }
            },
        }
    )
    signature = sign_stripe_payload(
        event.encode(), settings.stripe_webhook_secret, timestamp=int(time.time())
    )
    response = client.post(
        "/webhooks/stripe", content=event, headers={"stripe-signature": signature}
    )
    assert response.status_code == 200
    assert client.app.state.store.get_audit(audit_id).paid
    body = client.get(f"/audits/{audit_id}.json?token={token}").json()
    assert body["reconciliation"]["status"] == "CONTRADICTION"
    assert body["reconciliation"]["difference"]["value"] == 1000.0
    assert any(
        check["id"] == "BALANCE_CHAIN" and check["status"] == "SIGNAL"
        for check in body["forensics"]["checks"]
    )
    html = client.get(f"/audits/{audit_id}?token={token}").text
    assert "MONETARY_RECONCILIATION_MISMATCH" in html
    assert "BALANCE_CHAIN" in html
