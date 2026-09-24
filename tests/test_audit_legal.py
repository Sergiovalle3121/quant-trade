"""Terms and privacy pages, and the commands that keep the privacy promises."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.legal import (  # noqa: E402
    LEGAL_PATHS,
    LegalContext,
    legal_links_html,
    privacy_text,
    terms_text,
)
from quant_trade.audit.pages import error_page, landing, legal_page  # noqa: E402
from quant_trade.audit.retention import RetentionWorker, run_retention  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.theme import SCRIPT_TAG  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402
from quant_trade.cli import app  # noqa: E402

NOW = datetime(2026, 1, 31, tzinfo=UTC)
OPERATOR = {
    "operator_name": "Operador de Prueba SAS",
    "operator_contact": "privacidad@operador.example",
    "operator_address": "Calle Falsa 123, Ciudad Ejemplo",
    "jurisdiction": "Tribunales de Ciudad Ejemplo",
}
CONTEXTS = [
    LegalContext(),
    LegalContext(**OPERATOR),
    LegalContext(**OPERATOR, free_mode=False, price_usd=19, card_payments=True),
    LegalContext(**OPERATOR, free_mode=False, price_usd=19, access_codes=True),
]


def _client(tmp_path: Path, **overrides) -> tuple[TestClient, object]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        base_url="https://audit.example",
        **overrides,
    )
    store = make_store(settings.database_url)
    return TestClient(create_app(settings, store)), store


def _upload(client: TestClient) -> tuple[str, str]:
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    location = client.post(
        "/audits", files=files, data={"trials": "3", "consent": "on"}, follow_redirects=False
    ).headers["location"]
    return location.split("/audits/")[1].split("?")[0], location.split("token=")[1]


@pytest.mark.parametrize("ctx", CONTEXTS)
@pytest.mark.parametrize("locale", ["es", "en"])
def test_both_texts_pass_the_guard_in_every_mode(ctx: LegalContext, locale: str) -> None:
    for text in (terms_text(ctx, locale), privacy_text(ctx, locale)):
        page = legal_page(text, locale=locale)
        assert find_claims(page) == []
        assert "<script" not in page.replace(SCRIPT_TAG, "")


def test_unconfigured_operator_shows_a_placeholder_and_a_warning() -> None:
    for locale, placeholder in (("es", "[sin configurar]"), ("en", "[not configured]")):
        text = terms_text(LegalContext(), locale)
        assert text.warning
        page = legal_page(text, locale=locale)
        assert placeholder in page
    configured = terms_text(LegalContext(**OPERATOR), "es")
    assert configured.warning is None
    page = legal_page(configured, locale="es")
    for value in OPERATOR.values():
        assert value in page


def test_privacy_describes_what_the_store_keeps() -> None:
    ctx = LegalContext(**OPERATOR, retention_days=21, max_uploads_per_hour_per_ip=7)
    es = legal_page(privacy_text(ctx, "es"), locale="es")
    en = legal_page(privacy_text(ctx, "en"), locale="en")
    for needle in ("21 días", "IP", "7 subidas", "Stripe", "hash", "verificación", "bróker"):
        assert needle in es
    for needle in ("21 days", "IP", "7 uploads", "Stripe", "hash", "verification", "broker"):
        assert needle in en
    assert "https://stripe.com/privacy" in es
    assert OPERATOR["operator_contact"] in es


def test_terms_price_follows_the_payment_mode() -> None:
    free = legal_page(terms_text(LegalContext(), "es"), locale="es")
    assert "gratuito" in free and "Stripe" not in free
    card = legal_page(terms_text(CONTEXTS[2], "en"), locale="en")
    assert "USD 19.00" in card and "Stripe" in card and "access code" not in card
    codes = legal_page(terms_text(CONTEXTS[3], "es"), locale="es")
    assert "código de acceso" in codes and "Stripe" not in codes


def test_operator_values_are_escaped() -> None:
    ctx = LegalContext(operator_name="<script>x</script>")
    page = legal_page(terms_text(ctx, "es"), locale="es")
    assert "<script>" not in page and "&lt;script&gt;" in page


def test_settings_read_operator_details_without_defaults() -> None:
    empty = AuditSettings.from_env({})
    assert empty.operator_name == "" and not empty.legal_configured
    env = {
        "AUDIT_OPERATOR_NAME": "  Operador   SAS ",
        "AUDIT_OPERATOR_CONTACT": "a@b.example",
        "AUDIT_OPERATOR_ADDRESS": "Calle 1",
        "AUDIT_JURISDICTION": "Ciudad",
    }
    settings = AuditSettings.from_env(env)
    assert settings.operator_name == "Operador SAS"
    assert settings.legal_configured


def test_pages_are_served_in_both_languages_and_linked_everywhere(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, **OPERATOR)
    for locale, paths in LEGAL_PATHS.items():
        for path in paths.values():
            response = client.get(path)
            assert response.status_code == 200
            assert f"lang='{locale}'" in response.text
            assert find_claims(response.text) == []
    assert "lang='en'" in client.get("/terminos?lang=en").text
    assert client.get("/health").json()["legal_configured"] is True

    audit_id, token = _upload(client)
    pages = {
        "landing": client.get("/").text,
        "landing_en": client.get("/?lang=en").text,
        "report": client.get(f"/audits/{audit_id}?token={token}").text,
        "sample": client.get("/ejemplo").text,
        "error": client.get("/audits/nope?token=x").text,
    }
    public = client.post(f"/audits/{audit_id}/publish?token={token}", follow_redirects=False)
    pages["verification"] = client.get(public.headers["location"]).text
    for name, page in pages.items():
        assert "/terminos?lang=es" in page or "/terms?lang=en" in page, name
        assert "/privacidad?lang=es" in page or "/privacy?lang=en" in page, name
    # Next to the upload form, not only in the footer.
    form = pages["landing"].split("action='/audits'")[1].split("</form>")[0]
    assert "/terminos?lang=es" in form and "/privacidad?lang=es" in form


def test_consent_uses_the_configured_retention() -> None:
    assert "a los 14 días" in landing(retention_days=14)
    assert "after 14 days" in landing(locale="en", retention_days=14)
    assert legal_links_html("en") in error_page("x", locale="en")


def test_health_reports_missing_operator_details(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/health").json()["legal_configured"] is False
    assert "[sin configurar]" in client.get("/privacidad").text


# -- the promises the privacy page makes -----------------------------------


def _create(store, audit_id: str, *, at: datetime) -> None:
    store.create_audit(
        audit_id=audit_id,
        created_at=at,
        token_hash="h" * 64,
        client_ip="1.2.3.4",
        declared_json="{}",
        result_json=f'{{"audit_id": "{audit_id}"}}',
        report_html="<html></html>",
        overall_class="B",
        digests={"equity.csv": "e" * 64},
        equity_csv=b"timestamp,equity\n",
    )


def test_purge_clears_the_ip_of_every_old_audit_paid_included(tmp_path: Path) -> None:
    store = make_store(f"sqlite:///{tmp_path}/audit.db")
    _create(store, "old_paid", at=NOW - timedelta(days=40))
    _create(store, "recent", at=NOW - timedelta(days=5))
    store.mark_paid("old_paid", stripe_session_id="cs", at=NOW)
    assert store.purge_expired(NOW, retention_days=30, dry_run=True) == 0
    assert store.get_audit("old_paid").client_ip == "1.2.3.4"  # dry run changes nothing
    assert store.purge_expired(NOW, retention_days=30) == 0
    old = store.get_audit("old_paid", with_blobs=True)
    assert old.client_ip == "" and old.equity_csv is not None  # paid content stays
    assert store.get_audit("recent").client_ip == "1.2.3.4"


def test_delete_removes_everything_including_the_publication(tmp_path: Path) -> None:
    store = make_store(f"sqlite:///{tmp_path}/audit.db")
    _create(store, "a1", at=NOW)
    _create(store, "a2", at=NOW)
    publication = store.publish("a1", at=NOW)
    assert store.delete_audit("a1") is True
    assert store.get_audit("a1") is None
    assert store.get_publication(publication.public_id) is None
    assert store.get_audit("a2") is not None
    assert store.delete_audit("a1") is False


def test_remove_waitlist(tmp_path: Path) -> None:
    store = make_store(f"sqlite:///{tmp_path}/audit.db")
    store.add_waitlist("ana@example.com", at=NOW)
    assert store.remove_waitlist(" Ana@Example.com ", dry_run=True) is True
    assert store.waitlist_emails() == ["ana@example.com"]
    assert store.remove_waitlist("ana@example.com") is True
    assert store.waitlist_emails() == []
    assert store.remove_waitlist("ana@example.com") is False


def test_cli_export_delete_and_waitlist_remove(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/audit.db")
    store = make_store(f"sqlite:///{tmp_path}/audit.db")
    _create(store, "a1", at=NOW)
    store.add_waitlist("ana@example.com", at=NOW)
    runner = CliRunner()

    out = tmp_path / "export"
    result = runner.invoke(app, ["audit", "export", "a1", "--out", str(out)])
    assert result.exit_code == 0, result.output
    record = json.loads((out / "record.json").read_text(encoding="utf-8"))
    assert record["id"] == "a1" and record["client_ip"] == "1.2.3.4"
    assert (out / "upload_equity.csv").read_bytes() == b"timestamp,equity\n"
    assert (out / "report.html").exists()

    dry = runner.invoke(app, ["audit", "delete", "a1"])
    assert dry.exit_code == 0 and "would delete" in dry.output
    assert store.get_audit("a1") is not None
    done = runner.invoke(app, ["audit", "delete", "a1", "--yes"])
    assert done.exit_code == 0 and "deleted" in done.output
    assert store.get_audit("a1") is None
    assert runner.invoke(app, ["audit", "delete", "a1", "--yes"]).exit_code == 1
    assert runner.invoke(app, ["audit", "export", "a1"]).exit_code == 1

    assert runner.invoke(app, ["audit", "waitlist-remove", "ana@example.com"]).exit_code == 0
    assert store.waitlist_emails() == ["ana@example.com"]
    removed = runner.invoke(app, ["audit", "waitlist-remove", "ana@example.com", "--yes"])
    assert removed.exit_code == 0 and store.waitlist_emails() == []
    assert runner.invoke(app, ["audit", "waitlist-remove", "ana@example.com"]).exit_code == 1


# -- the purge runs inside the service --------------------------------------


def test_auto_purge_is_an_explicit_opt_in() -> None:
    assert AuditSettings.from_env({}).auto_purge is False
    assert AuditSettings.from_env({"AUDIT_AUTO_PURGE": "true"}).auto_purge is True


def test_service_purges_at_startup_when_auto_purge_is_on(tmp_path: Path) -> None:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", auto_purge=True)
    store = make_store(settings.database_url)
    _create(store, "old", at=datetime.now(UTC) - timedelta(days=40))
    _create(store, "new", at=datetime.now(UTC))
    with TestClient(create_app(settings, store)) as client:
        assert client.get("/health").json()["auto_purge"] is True
        worker = client.app.state.retention
        for _ in range(200):
            if worker.runs:
                break
            threading.Event().wait(0.01)
        assert worker.runs >= 1
    assert store.get_audit("old").purged_at is not None
    assert store.get_audit("new").purged_at is None


def test_service_never_purges_without_the_opt_in(tmp_path: Path) -> None:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db")
    store = make_store(settings.database_url)
    _create(store, "old", at=datetime.now(UTC) - timedelta(days=40))
    with TestClient(create_app(settings, store)) as client:
        assert client.get("/health").json()["auto_purge"] is False
        assert client.app.state.retention.runs == 0
    assert store.get_audit("old").purged_at is None


def test_worker_repeats_on_its_interval_and_survives_a_failure() -> None:
    calls: list[datetime] = []

    class FlakyStore:
        def purge_expired(self, now: datetime, *, retention_days: int) -> int:
            calls.append(now)
            if len(calls) == 1:
                raise RuntimeError("database away")
            return 0

    worker = RetentionWorker(
        FlakyStore(), retention_days=30, interval_seconds=0.01, clock=lambda: NOW
    )
    worker.start()
    for _ in range(500):
        if len(calls) >= 3:
            break
        threading.Event().wait(0.01)
    worker.stop()
    assert len(calls) >= 3 and calls[0] == NOW
    assert run_retention(FlakyStore(), retention_days=30, now=NOW) == 0


def test_cli_unpublish(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/audit.db")
    store = make_store(f"sqlite:///{tmp_path}/audit.db")
    _create(store, "a1", at=NOW)
    store.publish("a1", at=NOW)
    runner = CliRunner()
    assert runner.invoke(app, ["audit", "unpublish", "a1"]).exit_code == 0
    assert store.publication_for_audit("a1") is None
    assert runner.invoke(app, ["audit", "unpublish", "a1"]).exit_code == 1
