"""The web service, end to end, with Stripe simulated and no network."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift, trades_frame

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import error_page, landing  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import (  # noqa: E402
    create_app,
    sign_stripe_payload,
    verify_stripe_signature,
)

STRIPE = {
    "stripe_secret_key": "sk_test_x",
    "stripe_webhook_secret": "whsec_test",
    "stripe_price_id": "price_x",
}


def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100, **overrides
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _upload(client: TestClient, **data):
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    payload = {"trials": "3", "cost_bps": "5", "consent": "on", **data}
    return client.post("/audits", files=files, data=payload, follow_redirects=False)


def _id_and_token(location: str) -> tuple[str, str]:
    path, _, query = location.partition("?")
    return path.rsplit("/", 1)[1], query.split("token=")[1]


def test_health_and_landing_pages_pass_the_guard(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/health").json() == {
        "status": "ok",
        "free_mode": True,
        "stripe_enabled": False,
        "database": "sqlite",
    }
    for lang in ("es", "en"):
        page = client.get(f"/?lang={lang}")
        assert page.status_code == 200
        assert find_claims(page.text) == []
        assert page.headers["cache-control"] == "no-store"
    assert find_claims(landing(locale="en", free_mode=False, price_usd=49)) == []
    assert find_claims(error_page("x", locale="es")) == []


def test_upload_redirects_to_a_tokenised_report(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = _upload(client, oos_start="2020-06-01", description="<script>x</script>")
    assert response.status_code == 303
    audit_id, token = _id_and_token(response.headers["location"])
    page = client.get(f"/audits/{audit_id}?token={token}")
    assert page.status_code == 200
    assert "VISTA PREVIA" in page.text
    assert "<script>x</script>" not in page.text
    assert client.get(f"/audits/{audit_id}?token=wrong").status_code == 404
    assert client.get(f"/audits/{audit_id}").status_code == 404
    assert client.get("/audits/nothere?token=x").status_code == 404
    as_json = client.get(f"/audits/{audit_id}.json?token={token}")
    assert as_json.status_code == 200
    body = as_json.json()
    assert body["audit_id"] == audit_id
    assert body["declared"]["description"] == "<script>x</script>"


def test_upload_with_json_accept_returns_the_location(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {
        "equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv"),
        "trades": ("trades.csv", csv_bytes(trades_frame(10)), "text/csv"),
    }
    response = client.post(
        "/audits",
        files=files,
        data={"consent": "on"},
        headers={"accept": "application/json"},
    )
    assert response.status_code == 201
    assert response.json()["location"].startswith("/audits/")


def test_bad_uploads_are_refused_plainly(tmp_path: Path) -> None:
    client = _client(tmp_path, max_upload_bytes=10_000)
    no_consent = client.post(
        "/audits", files={"equity": ("e.csv", b"timestamp,equity\n", "text/csv")}, data={}
    )
    assert no_consent.status_code == 400
    bad = client.post(
        "/audits", files={"equity": ("e.csv", b"a,b\n1,2\n", "text/csv")}, data={"consent": "on"}
    )
    assert bad.status_code == 400
    assert "timestamp column" in bad.text
    big = client.post(
        "/audits",
        files={"equity": ("e.csv", b"x" * 20_000, "text/csv")},
        data={"consent": "on"},
        headers={"accept": "application/json"},
    )
    assert big.status_code == 413
    bad_trials = _upload(_client(tmp_path / "b"), trials="0")
    assert bad_trials.status_code == 400


def test_rate_limit_per_ip(tmp_path: Path) -> None:
    client = _client(tmp_path, max_uploads_per_hour_per_ip=2)
    assert _upload(client).status_code == 303
    assert _upload(client).status_code == 303
    assert _upload(client).status_code == 429
    other = client.post(
        "/audits",
        files={"equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv")},
        data={"consent": "on"},
        headers={"x-forwarded-for": "8.8.8.8"},
        follow_redirects=False,
    )
    assert other.status_code == 303


def test_waitlist(tmp_path: Path) -> None:
    client = _client(tmp_path)
    ok = client.post("/waitlist", data={"email": "a@b.co", "lang": "en"}, follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/?lang=en&joined=1"
    bad = client.post("/waitlist", data={"email": "nope"}, follow_redirects=False)
    assert bad.headers["location"].endswith("error=email")
    assert client.get("/?lang=en&joined=1").text.count("Joined") == 1


def test_checkout_is_off_in_free_mode_and_webhook_is_absent(tmp_path: Path) -> None:
    client = _client(tmp_path)
    audit_id, token = _id_and_token(_upload(client).headers["location"])
    assert client.post(f"/audits/{audit_id}/checkout?token={token}").status_code == 503
    assert client.post("/webhooks/stripe", content=b"{}").status_code == 404


def test_paid_mode_locks_until_the_signed_webhook_arrives(tmp_path: Path) -> None:
    client = _client(tmp_path, free_mode=False, **STRIPE)
    assert client.get("/health").json()["stripe_enabled"] is True
    audit_id, token = _id_and_token(_upload(client).headers["location"])

    locked = client.get(f"/audits/{audit_id}?token={token}")
    assert "class='locked'" in locked.text
    assert f"/audits/{audit_id}/checkout?token={token}" in locked.text
    assert client.get(f"/audits/{audit_id}.json?token={token}").status_code == 402

    seen: list[tuple[str, str]] = []

    def fake_checkout(settings: AuditSettings, aid: str, tok: str) -> str:
        seen.append((aid, tok))
        return "https://checkout.stripe.test/session"

    client.app.state.checkout_factory = fake_checkout
    redirect = client.post(f"/audits/{audit_id}/checkout?token={token}", follow_redirects=False)
    assert redirect.status_code == 303
    assert redirect.headers["location"] == "https://checkout.stripe.test/session"
    assert seen == [(audit_id, token)]

    event = json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test_1", "metadata": {"audit_id": audit_id}}},
        }
    ).encode()
    bad = client.post(
        "/webhooks/stripe", content=event, headers={"stripe-signature": "t=1,v1=deadbeef"}
    )
    assert bad.status_code == 400
    header = sign_stripe_payload(event, "whsec_test", timestamp=int(time.time()))
    good = client.post("/webhooks/stripe", content=event, headers={"stripe-signature": header})
    assert good.status_code == 200
    again = client.post("/webhooks/stripe", content=event, headers={"stripe-signature": header})
    assert again.status_code == 200  # idempotent

    unlocked = client.get(f"/audits/{audit_id}?token={token}")
    assert "class='locked'" not in unlocked.text
    assert "PREVIEW" not in unlocked.text and "VISTA PREVIA" not in unlocked.text
    assert client.get(f"/audits/{audit_id}.json?token={token}").status_code == 200
    assert (
        client.post(
            f"/audits/{audit_id}/checkout?token={token}", follow_redirects=False
        ).status_code
        == 303
    )


def test_stripe_signature_scheme() -> None:
    payload = b'{"hello": "world"}'
    header = sign_stripe_payload(payload, "s", timestamp=1_000)
    assert verify_stripe_signature(payload, header, "s", now=1_100.0)
    assert not verify_stripe_signature(payload, header, "s", now=2_000.0)  # stale
    assert not verify_stripe_signature(payload + b" ", header, "s", now=1_100.0)
    assert not verify_stripe_signature(payload, header, "other", now=1_100.0)
    assert not verify_stripe_signature(payload, None, "s")
    assert not verify_stripe_signature(payload, "v1=abc", "s")
    assert not verify_stripe_signature(payload, "t=x,v1=abc", "s")
    assert not verify_stripe_signature(payload, header, "")


def test_purged_audit_is_gone(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    client = _client(tmp_path)
    audit_id, token = _id_and_token(_upload(client).headers["location"])
    store = client.app.state.store
    future = datetime.now(UTC) + timedelta(days=45)
    assert store.purge_expired(future, retention_days=30) == 1
    assert client.get(f"/audits/{audit_id}?token={token}").status_code == 410
