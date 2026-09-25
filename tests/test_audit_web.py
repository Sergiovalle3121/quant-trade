"""The web service, end to end, with Stripe simulated and no network."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from audit_fixtures import (
    csv_bytes,
    positive_drift,
    signed_in,
    synthetic_mt5_optimization,
    synthetic_mt5_report,
    trades_frame,
)

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import error_page, landing  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import (  # noqa: E402
    MESSAGES,
    client_ip,
    create_app,
    looks_like_platform_report,
    message,
    sign_stripe_payload,
    verify_stripe_signature,
)

STRIPE = {
    "stripe_secret_key": "sk_live_x",
    "stripe_webhook_secret": "whsec_test",
    "stripe_price_id": "price_x",
}


def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100, **overrides
    )
    return signed_in(TestClient(create_app(settings, make_store(settings.database_url))))


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
        "card_mode": "off",
        "card_via": "off",
        "access_codes": False,
        "database": "sqlite",
        "legal_configured": False,
        "auto_purge": False,
        "version": "unknown",
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
    client.cookies.clear()  # a visitor without the account
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
    assert "columna de fecha" in bad.text
    bad_en = client.post(
        "/audits",
        files={"equity": ("e.csv", b"a,b\n1,2\n", "text/csv")},
        data={"consent": "on", "locale": "en"},
    )
    assert bad_en.status_code == 400
    assert "timestamp column" in bad_en.text
    big = client.post(
        "/audits",
        # The equity field takes a report, so its limit is twice the setting.
        files={"equity": ("e.csv", b"x" * 25_000, "text/csv")},
        data={"consent": "on"},
        headers={"accept": "application/json"},
    )
    assert big.status_code == 413
    assert "el máximo que aceptamos" in big.json()["error"]
    bad_trials = _upload(_client(tmp_path / "b"), trials="0")
    assert bad_trials.status_code == 400
    assert "número de intentos" in bad_trials.text


def test_every_web_error_is_spanish_by_default_and_passes_the_guard(tmp_path: Path) -> None:
    client = _client(tmp_path)
    no_consent = client.post(
        "/audits", files={"equity": ("e.csv", b"timestamp,equity\n", "text/csv")}, data={}
    )
    assert "aceptar las condiciones" in no_consent.text
    no_file = client.post("/audits", data={"consent": "on"})
    assert no_file.status_code == 400
    assert "curva de equity" in no_file.text
    not_a_number = client.post(
        "/audits",
        files={"equity": ("e.csv", csv_bytes(positive_drift(50)), "text/csv")},
        data={"consent": "on", "trials": "many"},
    )
    assert not_a_number.status_code == 400
    assert "número de intentos" in not_a_number.text
    missing = client.get("/audits/nothere?token=x")
    assert missing.status_code == 404
    assert "No encontramos esa auditoría" in missing.text
    assert "could not find" in client.get("/audits/nothere?token=x&lang=en").text
    as_json = client.get("/audits/nothere?token=x", headers={"accept": "application/json"})
    assert as_json.status_code == 404 and "error" in as_json.json()
    assert "no parece válida" in client.get("/?error=email").text
    assert "<b>" not in client.get("/?error=%3Cb%3Ex").text
    for key, texts in MESSAGES.items():
        assert set(texts) == {"es", "en"}, key
        for locale in ("es", "en"):
            assert find_claims(message(key, locale, what="x", limit="1", passes="1")) == [], key


def test_the_audit_runs_off_the_event_loop(tmp_path: Path, monkeypatch) -> None:
    import asyncio

    from quant_trade.audit import web

    loops: list[bool] = []
    real_run_audit = web.run_audit
    real_build_inputs = web.build_inputs

    def _on_loop() -> bool:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False
        return True

    def spy_run_audit(*args, **kwargs):
        loops.append(_on_loop())
        return real_run_audit(*args, **kwargs)

    def spy_build_inputs(*args, **kwargs):
        loops.append(_on_loop())
        return real_build_inputs(*args, **kwargs)

    monkeypatch.setattr(web, "run_audit", spy_run_audit)
    monkeypatch.setattr(web, "build_inputs", spy_build_inputs)
    assert _upload(_client(tmp_path)).status_code == 303
    assert loops == [False, False]


def _upload_from(client: TestClient, forwarded_for: str):
    return client.post(
        "/audits",
        files={"equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv")},
        data={"consent": "on"},
        headers={"x-forwarded-for": forwarded_for},
        follow_redirects=False,
    )


def test_rate_limit_per_ip_ignores_a_spoofed_header_by_default(tmp_path: Path) -> None:
    client = _client(tmp_path, max_uploads_per_hour_per_ip=2)
    assert _upload(client).status_code == 303
    assert _upload(client).status_code == 303
    limited = _upload(client)
    assert limited.status_code == 429
    assert "Demasiadas auditorías" in limited.text
    # Without a trusted proxy the header is the client's to invent.
    assert _upload_from(client, "8.8.8.8").status_code == 429


def test_rate_limit_behind_one_trusted_proxy(tmp_path: Path) -> None:
    client = _client(tmp_path, max_uploads_per_hour_per_ip=1, trusted_proxy_hops=1)
    assert _upload_from(client, "1.1.1.1").status_code == 303
    # A spoofed left-most entry does not help: the proxy's entry is the last one.
    assert _upload_from(client, "9.9.9.9, 1.1.1.1").status_code == 429
    assert _upload_from(client, "2.2.2.2").status_code == 303


@pytest.mark.parametrize(
    ("header", "hops", "expected"),
    [
        ("6.6.6.6", 0, "10.0.0.1"),
        ("6.6.6.6, 1.1.1.1", 1, "1.1.1.1"),
        ("6.6.6.6, 1.1.1.1, 10.0.0.2", 2, "1.1.1.1"),
        ("1.1.1.1", 2, "10.0.0.1"),
        ("", 1, "10.0.0.1"),
        (None, 1, "10.0.0.1"),
        ("6.6.6.6, ", 1, "10.0.0.1"),
    ],
)
def test_client_ip_takes_the_nth_entry_from_the_right(
    header: str | None, hops: int, expected: str
) -> None:
    assert client_ip(header, "10.0.0.1", trusted_proxy_hops=hops) == expected
    assert client_ip(header, None, trusted_proxy_hops=0) == "unknown"


def test_waitlist(tmp_path: Path) -> None:
    client = _client(tmp_path)
    ok = client.post("/waitlist", data={"email": "a@b.co", "lang": "en"}, follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/?lang=en&joined=1#news"
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
    assert "class='lockbox'" in locked.text
    assert f"/audits/{audit_id}/checkout?token={token}" in locked.text
    assert client.get(f"/audits/{audit_id}.json?token={token}").status_code == 402

    seen: list[tuple[str, str]] = []

    def fake_checkout(settings: AuditSettings, aid: str, tok: str, **_: str) -> str:
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
            "data": {
                "object": {
                    "id": "cs_test_1",
                    "payment_status": "paid",
                    "livemode": True,
                    "currency": "usd",
                    "amount_total": 4900,
                    "metadata": {"audit_id": audit_id, "app": "rigor"},
                }
            },
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
    assert "class='lockbox'" not in unlocked.text
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


def test_a_platform_report_alone_is_audited_and_stored(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {
        "report": ("ReportTester.html", synthetic_mt5_report(days=120), "text/html"),
        "optimization": ("opt.xml", synthetic_mt5_optimization(30), "application/xml"),
    }
    data = {"consent": "on", "challenge": "ftmo-2step-phase1", "locale": "es"}
    response = client.post("/audits", files=files, data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    audit_id, token = _id_and_token(response.headers["location"])
    page = client.get(f"/audits/{audit_id}?token={token}")
    assert page.status_code == 200
    assert "Qué significa para ti" in page.text and "<svg" in page.text
    assert find_claims(page.text) == []
    body = client.get(f"/audits/{audit_id}.json?token={token}").json()
    assert body["inputs"]["source_format"] == "mt5_tester_html"
    assert body["multiplicity"]["trials_used"]["value"] == 30
    assert body["challenge"]["preset"] == "ftmo-2step-phase1"
    store = client.app.state.store  # type: ignore[attr-defined]
    record = store.get_audit(audit_id, with_blobs=True)
    assert record.equity_csv is None
    assert set(record.files) == {"report.html", "optimization.xml"}
    assert record.digests["report.html"] == body["inputs"]["digests"]["report.html"]


def test_a_report_dropped_in_the_equity_field_is_read_as_the_report(tmp_path: Path) -> None:
    client = _client(tmp_path)
    # No .html name: the content alone (UTF-16, as MetaTrader saves it) tells.
    utf16 = synthetic_mt5_report(days=120)
    assert utf16.startswith(b"\xff\xfe")
    files = {"equity": ("export", utf16, "application/octet-stream")}
    response = client.post("/audits", files=files, data={"consent": "on"}, follow_redirects=False)
    assert response.status_code == 303, response.text
    audit_id, token = _id_and_token(response.headers["location"])
    body = client.get(f"/audits/{audit_id}.json?token={token}").json()
    assert body["inputs"]["source_format"] == "mt5_tester_html"
    # A workbook is a report only when an importer recognises it; any other
    # (a curve, or a damaged file) is read as the equity curve it was sent as.
    assert not looks_like_platform_report("r.xlsx", b"PK\x03\x04")
    assert not looks_like_platform_report("e.csv", csv_bytes(positive_drift(50)))


def test_a_malformed_csv_is_explained_in_spanish_without_parser_text(tmp_path: Path) -> None:
    client = _client(tmp_path)
    bad = b"timestamp,equity,x\n2024-01-01,1,2\n2024-01-02,1,2\n2024-01-03,1,2,3,4\n"
    files = {"equity": ("e.csv", bad, "text/csv")}
    response = client.post("/audits", files=files, data={"consent": "on"})
    assert response.status_code == 400
    assert "mismo número de columnas" in response.text
    assert "Expected" not in response.text


def test_an_unknown_address_is_a_missing_page_not_a_missing_audit(tmp_path: Path) -> None:
    client = _client(tmp_path)
    page = client.get("/no-existe")
    assert page.status_code == 404
    assert "Página no encontrada" in page.text and "Esta página no existe" in page.text
    assert "No se pudo auditar" not in page.text
    assert "Page not found" in client.get("/no-existe?lang=en").text
    assert "No encontramos esa auditoría" in client.get("/audits/nothere?token=x").text


def test_report_uploads_are_purged_with_their_audit(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    client = _client(tmp_path)
    files = {"report": ("r.html", synthetic_mt5_report(days=60), "text/html")}
    response = client.post("/audits", files=files, data={"consent": "on"}, follow_redirects=False)
    audit_id, _ = _id_and_token(response.headers["location"])
    store = client.app.state.store  # type: ignore[attr-defined]
    later = datetime.now(UTC) + timedelta(days=40)
    assert store.purge_expired(later, retention_days=30) == 1
    record = store.get_audit(audit_id, with_blobs=True)
    assert record.files == {}
    assert "report.html" in record.digests


def test_bad_report_fields_are_refused_in_the_form_locale(tmp_path: Path) -> None:
    client = _client(tmp_path)
    nothing = client.post("/audits", data={"consent": "on"}, follow_redirects=False)
    assert nothing.status_code == 400 and "informe de tu plataforma" in nothing.text
    files = {"report": ("r.html", synthetic_mt5_report(days=60), "text/html")}
    for field, value in (("challenge", "nope"), ("initial_balance", "-5")):
        bad = client.post(
            "/audits", files=files, data={"consent": "on", field: value}, follow_redirects=False
        )
        assert bad.status_code == 400
        assert "reto" in bad.text
    unreadable = client.post(
        "/audits",
        files={"report": ("r.html", b"<html><body>hola</body></html>", "text/html")},
        data={"consent": "on", "locale": "es"},
        follow_redirects=False,
    )
    assert unreadable.status_code == 400
    assert "informe compatible" in unreadable.text


def test_health_names_the_deployed_commit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from quant_trade.audit.web import deployed_version

    assert deployed_version(
        {"RAILWAY_GIT_COMMIT_SHA": "015F16353D67D487F2923D8632768E57E1F159F5"}
    ) == ("015f163")
    assert deployed_version({"RAILWAY_GIT_COMMIT_SHA": "<script>"}) == "unknown"
    assert deployed_version({}) == "unknown"
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abcdef1234")
    assert _client(tmp_path).get("/health").json()["version"] == "abcdef1"
