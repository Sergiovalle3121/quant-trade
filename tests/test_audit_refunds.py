"""Signed Stripe refund snapshots; no test issues a real or sandbox refund."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from audit_fixtures import csv_bytes, positive_drift, signed_in  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import funnel  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app, sign_stripe_payload  # noqa: E402

SECRET = "whsec_refund_test"
ADMIN_KEY = "k" * 40


def _client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/refunds.db",
        base_url="https://rigor.example",
        stripe_secret_key="sk_live_example",
        stripe_webhook_secret=SECRET,
        free_mode=False,
        admin_key=ADMIN_KEY,
        bootstrap_samples=100,
    )
    return signed_in(TestClient(create_app(settings, make_store(settings.database_url))))


def _upload(client: TestClient) -> str:
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    response = client.post(
        "/audits",
        files=files,
        data={"trials": "3", "cost_bps": "5", "consent": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"].split("/audits/")[1].split("?")[0]


def _event(
    client: TestClient,
    kind: str,
    obj: dict[str, Any],
    event_id: str,
    *,
    livemode: bool = True,
) -> int:
    payload = json.dumps(
        {"id": event_id, "type": kind, "livemode": livemode, "data": {"object": obj}}
    ).encode()
    signature = sign_stripe_payload(payload, SECRET, timestamp=int(time.time()))
    return client.post(
        "/webhooks/stripe", content=payload, headers={"stripe-signature": signature}
    ).status_code


def _paid(
    client: TestClient,
    audit_id: str,
    *,
    pi: str = "pi_example",
    sid: str = "cs_example",
    livemode: bool = True,
) -> None:
    session = {
        "id": sid,
        "payment_intent": pi,
        "payment_status": "paid",
        "livemode": livemode,
        "currency": "usd",
        "amount_total": 2900,
        "metadata": {"audit_id": audit_id, "plan": "single", "app": "rigor"},
    }
    assert (
        _event(client, "checkout.session.completed", session, "evt_paid_" + pi, livemode=livemode)
        == 200
    )


def _refund(
    *,
    refund_id: str,
    pi: str = "pi_example",
    amount: int = 500,
    status: str = "succeeded",
    currency: str = "usd",
) -> dict[str, Any]:
    return {
        "id": refund_id,
        "object": "refund",
        "payment_intent": pi,
        "charge": "ch_" + pi.removeprefix("pi_"),
        "amount": amount,
        "currency": currency,
        "status": status,
    }


def _refunded_usd(client: TestClient) -> int:
    store = client.app.state.store
    today = datetime.now(UTC).date().isoformat()
    return funnel.build(store.funnel_events(today)).total.counts["refund_usd_cents"]


def test_two_partial_refunds_replay_and_late_failure_change_only_refund_metric(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    audit_id = _upload(client)
    _paid(client, audit_id)
    store = client.app.state.store
    before = funnel.build(store.funnel_events(datetime.now(UTC).date().isoformat())).total.counts
    assert before["gross_usd_cents"] == 2900 and before["rights_sold"] == 1

    first = _refund(refund_id="re_first", amount=500)
    second = _refund(refund_id="re_second", amount=300, status="pending")
    assert _event(client, "refund.created", first, "evt_refund_first") == 200
    assert _event(client, "refund.created", second, "evt_refund_second") == 200
    assert _refunded_usd(client) == 500
    assert (
        _event(client, "refund.updated", {**second, "status": "succeeded"}, "evt_refund_second_ok")
        == 200
    )
    assert _refunded_usd(client) == 800
    assert _event(client, "refund.created", first, "evt_refund_first") == 200
    assert (
        _event(client, "refund.created", {**second, "status": "pending"}, "evt_refund_second_old")
        == 200
    )
    assert _refunded_usd(client) == 800

    # Stripe can report succeeded first and a card refund failure later.
    assert (
        _event(client, "refund.failed", {**second, "status": "failed"}, "evt_refund_second_fail")
        == 200
    )
    assert (
        _event(
            client, "refund.updated", {**second, "status": "succeeded"}, "evt_refund_second_late"
        )
        == 200
    )
    assert _refunded_usd(client) == 500
    rows = {r.refund_id: r for r in store.list_stripe_refunds()}
    assert rows["re_first"].status == "succeeded" and rows["re_second"].status == "failed"
    after = funnel.build(store.funnel_events(datetime.now(UTC).date().isoformat())).total.counts
    assert after["gross_usd_cents"] == 2900 and after["rights_sold"] == 1
    assert store.get_audit(audit_id).paid
    panel = client.post("/panel", data={"key": ADMIN_KEY}).text
    assert "Devoluciones observadas en Stripe" in panel
    assert "re_first" in panel and "re_second" in panel
    assert "Devoluciones USD registradas" in panel
    assert "Saldo de cobros USD tras devoluciones registradas" in panel
    assert "<td>24.00</td>" in panel


def test_refund_before_checkout_is_linked_later_but_other_modes_and_currencies_are_not(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    audit_id = _upload(client)
    early = _refund(refund_id="re_early", pi="pi_early", amount=700)
    assert _event(client, "refund.created", early, "evt_early") == 200
    store = client.app.state.store
    assert store.list_stripe_refunds()[0].order_id == ""
    assert _refunded_usd(client) == 0
    _paid(client, audit_id, pi="pi_early", sid="cs_early")
    assert store.list_stripe_refunds()[0].order_id
    assert _refunded_usd(client) == 700

    foreign_mode = _refund(refund_id="re_test_mode", pi="pi_early")
    assert _event(client, "refund.created", foreign_mode, "evt_test_mode", livemode=False) == 200
    mxn = _refund(refund_id="re_mxn", pi="pi_early", currency="mxn", amount=5000)
    assert _event(client, "refund.created", mxn, "evt_mxn") == 200
    unrelated = _refund(refund_id="re_other_app", pi="pi_other_app")
    assert _event(client, "refund.created", unrelated, "evt_other_app") == 200
    rows = {r.refund_id: r for r in store.list_stripe_refunds()}
    assert rows["re_test_mode"].order_id == ""
    assert rows["re_other_app"].order_id == ""
    assert rows["re_mxn"].order_id
    assert _refunded_usd(client) == 700

    bad = json.dumps(
        {
            "id": "evt_unsigned",
            "type": "refund.created",
            "livemode": True,
            "data": {"object": _refund(refund_id="re_unsigned")},
        }
    ).encode()
    assert (
        client.post(
            "/webhooks/stripe", content=bad, headers={"stripe-signature": "not-signed"}
        ).status_code
        == 400
    )
    assert "re_unsigned" not in {r.refund_id for r in store.list_stripe_refunds()}


def test_signed_sandbox_sale_and_refund_are_visible_but_excluded_from_commercial_funnel(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path}/sandbox.db"
    common = dict(
        database_url=database_url,
        base_url="https://rigor.example",
        stripe_secret_key="sk_test_example",
        stripe_webhook_secret=SECRET,
        free_mode=False,
        admin_key=ADMIN_KEY,
        bootstrap_samples=100,
    )
    setup = AuditSettings(**common)
    setup_client = signed_in(TestClient(create_app(setup, make_store(database_url))))
    audit_id = _upload(setup_client)
    listed = AuditSettings(**common, stripe_test_audits={audit_id})
    client = signed_in(TestClient(create_app(listed, make_store(database_url))))
    _paid(client, audit_id, pi="pi_sandbox", sid="cs_sandbox", livemode=False)
    assert (
        _event(
            client,
            "refund.created",
            _refund(refund_id="re_sandbox", pi="pi_sandbox"),
            "evt_sandbox_refund",
            livemode=False,
        )
        == 200
    )
    store = client.app.state.store
    assert store.get_audit(audit_id).paid
    assert store.list_checkout_orders()[0].livemode is False
    assert store.list_stripe_refunds()[0].order_id
    counts = funnel.build(store.funnel_events(datetime.now(UTC).date().isoformat())).total.counts
    assert counts["purchases"] == counts["gross_usd_cents"] == counts["refund_usd_cents"] == 0
