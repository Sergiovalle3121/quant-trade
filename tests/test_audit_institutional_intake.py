"""Offline institutional requests: private declarations, bounded intake and durable notice."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import funnel, institutional, mail  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import institutional_review_page  # noqa: E402
from quant_trade.audit.seo import PUBLIC_PAGES  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402


def payload(**overrides: str) -> dict[str, str]:
    return {
        "name": "Ana",
        "organization": "Investigación Cuantitativa",
        "email": "ana@research.mx",
        "strategy_type": "model_portfolio",
        "frequency": "monthly",
        "history_years": "3.5",
        "has_benchmark": "yes",
        "variants": "120",
        "description": "  Contexto privado.\nSerie neta.  ",
        "website": "",
        "ref": "f7",
        **overrides,
    }


def make_client(tmp_path: Path, **overrides: object) -> TestClient:
    values: dict[str, object] = {
        "database_url": f"sqlite:///{tmp_path}/audit.db",
        "base_url": "https://audit.example",
        "operator_contact": "owner@research.mx",
        "smtp_from": "rigor@research.mx",
        "smtp_host": "smtp.invalid",
        "email_token_secret": "test-intake-secret-" * 2,
        **overrides,
    }
    settings = AuditSettings(**values)  # type: ignore[arg-type]
    return TestClient(
        create_app(settings, make_store(settings.database_url)), base_url="https://audit.example"
    )


def visible(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_form_confirmation_errors_guard_and_discovery(tmp_path: Path, locale: str) -> None:
    client = make_client(tmp_path)
    path = institutional.REVIEW_PATHS[locale]
    response = client.get(path)
    assert response.status_code == 200
    assert f"<html lang='{locale}'>" in response.text
    assert "type='file'" not in response.text and "multipart/form-data" not in response.text
    assert "maxlength='1000'" in response.text
    assert f"action='{path}'" in response.text
    assert institutional.REVIEW_PATHS in PUBLIC_PAGES
    assert f"https://audit.example{path}<" in client.get("/sitemap.xml").text
    for other_path in institutional.REVIEW_PATHS.values():
        assert other_path in response.text
    assert find_claims(visible(response.text)) == []
    for error in ("invalid", "limited", "unavailable", "too_large"):
        assert find_claims(visible(institutional_review_page(locale=locale, error=error))) == []
    response = client.post(path, data=payload())
    assert response.status_code == 200
    assert institutional.COPY[locale]["received"] in response.text
    assert institutional.COPY[locale]["next"] in response.text
    assert find_claims(visible(response.text)) == []
    assert "noindex" in response.headers["x-robots-tag"]
    assert "Contexto privado" not in response.text and "ana@research.mx" not in response.text
    record = client.app.state.store.list_institutional_requests()[0]
    assert record.locale == locale and record.ref == "f7"


def test_valid_request_preserves_prose_and_enqueues_only_allowed_notice_fields(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    response = client.post(institutional.REVIEW_PATHS["es"], data=payload())
    assert response.status_code == 200
    store = client.app.state.store
    record = store.list_institutional_requests()[0]
    assert record.description == payload()["description"]
    assert record.organization == payload()["organization"]
    assert record.variants == 120 and record.history_years == "3.5" and record.has_benchmark
    sent = []
    assert (
        mail.deliver_pending(
            store,
            client.app.state.settings,
            sender=lambda message, _: sent.append(message),
            now=datetime.now(UTC),
        )
        == 1
    )
    assert len(sent) == 1 and str(sent[0]["To"]) == "owner@research.mx"
    body = sent[0].get_content()
    for field in ("name", "organization", "email"):
        assert payload()[field] in body
    for private in ("Contexto privado", "Serie neta", "120", "3.5", "f7", "monthly"):
        assert private not in body
    assert find_claims(body) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "<b>Ana</b>"),
        ("organization", "&lt;script&gt;alert(1)&lt;/script&gt;"),
        ("email", "ana@research.mx\r\nBcc: stranger@research.mx"),
        ("email", "invalid"),
        ("email", "a@mailinator.com"),
        ("email", "a@example.com"),
        ("description", "<img src=x onerror=alert(1)>"),
        ("description", "a" * 1001),
        ("description", "text\x00"),
        ("name", "certificado"),
        ("organization", "rentable"),
        ("strategy_type", "other"),
        ("frequency", "yearly"),
        ("has_benchmark", "maybe"),
        ("history_years", "NaN"),
        ("history_years", "0"),
        ("history_years", "101"),
        ("variants", "-1"),
        ("variants", "1.5"),
        ("name", ""),
        ("organization", " "),
    ],
)
def test_invalid_fields_are_rejected_without_echo_or_storage(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    client = make_client(tmp_path)
    response = client.post(institutional.REVIEW_PATHS["en"], data=payload(**{field: value}))
    assert response.status_code == 400
    assert find_claims(visible(response.text)) == []
    assert client.app.state.store.list_institutional_requests() == []
    assert client.app.state.store.claim_email_delivery(datetime.now(UTC)) is None


@pytest.mark.parametrize("claim", ("rentable", "you'll pass", "lucro garantido"))
def test_client_claim_is_scanned_and_neutralized_by_never_rendering_it(
    tmp_path: Path,
    claim: str,
) -> None:
    client = make_client(tmp_path)
    description = f"  {claim}\n  "
    response = client.post(institutional.REVIEW_PATHS["es"], data=payload(description=description))
    assert response.status_code == 200
    record = client.app.state.store.list_institutional_requests()[0]
    assert record.description == description and record.claim_findings
    assert claim not in response.text
    assert find_claims(visible(response.text)) == []


def test_honeypot_cross_site_files_and_duplicate_fields_do_not_store(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    path = institutional.REVIEW_PATHS["es"]
    assert client.post(path, data=payload(website="spam")).status_code == 200
    assert (
        client.post(path, data=payload(), headers={"Origin": "https://other.invalid"}).status_code
        == 403
    )
    assert (
        client.post(path, data=payload(), files={"file": ("private.csv", b"private")}).status_code
        == 400
    )
    assert (
        client.post(
            path,
            content="name=A&name=B",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
        ).status_code
        == 400
    )
    assert client.app.state.store.list_institutional_requests() == []


def test_ip_limit_is_shared_across_languages_and_survives_restart(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    for _ in range(institutional.MAX_REQUESTS_PER_HOUR):
        assert client.post(institutional.REVIEW_PATHS["es"], data=payload()).status_code == 200
    response = make_client(tmp_path).post(institutional.REVIEW_PATHS["pt"], data=payload())
    assert response.status_code == 429 and find_claims(visible(response.text)) == []
    assert (
        len(client.app.state.store.list_institutional_requests())
        == institutional.MAX_REQUESTS_PER_HOUR
    )


def test_body_limit_and_ref_cookie(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    path = institutional.REVIEW_PATHS["en"]
    response = client.post(path, content="x" * (institutional.BODY_LIMIT + 1))
    assert response.status_code == 413
    assert institutional.COPY["en"]["too_large"] in response.text
    client.get(path + "?ref=linkedin")
    assert client.cookies.get(funnel.REF_COOKIE) == "linkedin"
    client.post(path, data=payload(ref="f7"))
    assert client.app.state.store.list_institutional_requests()[0].ref == "linkedin"


def test_missing_mail_configuration_keeps_request_and_never_sends(tmp_path: Path) -> None:
    client = make_client(tmp_path, smtp_host="")
    assert client.post(institutional.REVIEW_PATHS["es"], data=payload()).status_code == 200
    assert len(client.app.state.store.list_institutional_requests()) == 1
    assert client.app.state.store.claim_email_delivery(datetime.now(UTC)) is None


def test_intake_english_notices_have_spanish_i18n_rules() -> None:
    from quant_trade.audit.i18n import spanish

    for key in ("note", "invalid", "limited", "unavailable", "too_large"):
        assert spanish(institutional.COPY["en"][key]) == institutional.COPY["es"][key]


def test_database_failure_is_not_a_confirmation_and_does_not_log_client_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = make_client(tmp_path)

    def fail(**_: object) -> None:
        raise RuntimeError("private client text from database")

    monkeypatch.setattr(client.app.state.store, "add_institutional_request", fail)
    response = client.post(institutional.REVIEW_PATHS["es"], data=payload())
    assert response.status_code == 503
    assert "private client" not in caplog.text and "ana@research.mx" not in caplog.text
    assert find_claims(visible(response.text)) == []
