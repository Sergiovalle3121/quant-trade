"""Public verification page, badge, the synthetic sample and the landing."""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import (  # noqa: E402
    BADGE_NOTICE,
    SAMPLE_BANNER,
    VERIFICATION_NOTICE,
    badge_svg,
    landing,
)
from quant_trade.audit.sample import sample_result  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

SECRET_DESCRIPTION = "my secret edge description zeta"


def _client(tmp_path: Path, **overrides) -> tuple[TestClient, object]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        base_url="https://audit.example",
        **overrides,
    )
    store = make_store(settings.database_url)
    return signed_in(TestClient(create_app(settings, store))), store


def _upload(client: TestClient) -> tuple[str, str]:
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    data = {"trials": "3", "consent": "on", "description": SECRET_DESCRIPTION}
    location = client.post("/audits", files=files, data=data, follow_redirects=False).headers[
        "location"
    ]
    return location.split("/audits/")[1].split("?")[0], location.split("token=")[1]


def test_fixed_wording_passes_the_guard_in_every_language() -> None:
    for texts in (BADGE_NOTICE, VERIFICATION_NOTICE, SAMPLE_BANNER):
        for text in texts.values():
            assert find_claims(text) == []
    assert "no verificados con el bróker" in BADGE_NOTICE["es"]
    assert "no garantiza resultados" in BADGE_NOTICE["es"]
    assert set(BADGE_NOTICE) == set(VERIFICATION_NOTICE) == {"es", "en", "pt"}
    assert "não garante resultados" in BADGE_NOTICE["pt"]
    for locale in ("es", "en", "pt"):
        svg = badge_svg(overall="B", public_id="abc", audited_on="2026-09-24", locale=locale)
        assert find_claims(svg) == []
        assert BADGE_NOTICE[locale] in svg
        assert "<script" not in svg


def test_badge_never_mentions_returns() -> None:
    for locale in ("es", "en", "pt"):
        svg = badge_svg(overall="A", public_id="abc", audited_on="2026-09-24", locale=locale)
        for word in (
            "rentab",
            "ganancia",
            "profit",
            "return",
            "%",
            "crecimiento",
            "growth",
            "lucro",
            "retorno",
            "ganho",
        ):
            assert word not in svg.lower(), (locale, word)


def test_publish_shows_only_the_allowed_fields(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    audit_id, token = _upload(client)
    report = client.get(f"/audits/{audit_id}?token={token}")
    assert f"/audits/{audit_id}/publish?token=" in report.text
    response = client.post(f"/audits/{audit_id}/publish?token={token}", follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    public_id = location.split("/v/")[1].split("?")[0]
    assert public_id != audit_id
    again = client.post(
        f"/audits/{audit_id}/publish?token={token}", headers={"accept": "application/json"}
    )
    assert again.json()["public_id"] == public_id  # idempotent

    page = client.get(f"/v/{public_id}")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "public, max-age=300"
    text = page.text
    assert VERIFICATION_NOTICE["es"] in text
    assert "Significación estadística" in text
    # Dimensions read as cards, and the hash and detail tables stack on phones.
    assert text.count("<div class='item s-") == 6 and "<div class='meaning'>" in text
    assert text.count("<table class='kv'>") == 2
    assert "None (" not in text
    for secret in (SECRET_DESCRIPTION, token, audit_id, "entry_time", "timestamp,equity"):
        assert secret not in text
    assert find_claims(text) == []
    english = client.get(f"/v/{public_id}?lang=en")
    assert VERIFICATION_NOTICE["en"] in english.text
    assert find_claims(english.text) == []
    assert f"https://audit.example/v/{public_id}/badge.svg" in text

    badge = client.get(f"/v/{public_id}/badge.svg")
    assert badge.status_code == 200
    assert badge.headers["content-type"].startswith("image/svg+xml")
    assert badge.headers["cache-control"] == "public, max-age=300"
    assert BADGE_NOTICE["es"] in badge.text
    assert find_claims(badge.text) == []

    # The private report keeps no-store.
    assert client.get(f"/audits/{audit_id}?token={token}").headers["cache-control"] == "no-store"


def test_the_public_page_and_badge_read_in_portuguese(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    audit_id, token = _upload(client)
    location = client.post(
        f"/audits/{audit_id}/publish?token={token}&lang=pt", follow_redirects=False
    ).headers["location"]
    assert location.endswith("?lang=pt")
    public_id = location.split("/v/")[1].split("?")[0]
    page = client.get(f"/v/{public_id}?lang=pt").text
    assert "<html lang='pt'>" in page
    bare = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    text = html.unescape(re.sub(r"<[^>]+>", " ", bare))
    assert VERIFICATION_NOTICE["pt"] in text
    assert "Verificação pública de auditoria" in text and "Classe " in text
    assert "Significância estatística" in text
    for spanish in ("Clase ", "Significación", "Dimensiones", "Sello para tu web", "Copia este"):
        assert spanish not in text, spanish
    for secret in (SECRET_DESCRIPTION, token, audit_id, "entry_time", "timestamp,equity"):
        assert secret not in page
    assert find_claims(text) == []
    # The badge, its snippet and the check link follow the page's language.
    assert f"/v/{public_id}/badge.svg?lang=pt" in page
    assert "href='/pt/comprovar'" in page
    # The language bar offers the same page in the three languages.
    assert f"href='/v/{public_id}' hreflang='es'" in page
    assert f"href='/v/{public_id}?lang=en' hreflang='en'" in page
    spanish = client.get(f"/v/{public_id}").text
    assert f"href='/v/{public_id}?lang=pt' hreflang='pt'" in spanish
    badge = client.get(f"/v/{public_id}/badge.svg?lang=pt").text
    assert BADGE_NOTICE["pt"] in badge and "Classe" in badge
    assert find_claims(badge) == []


def test_publish_needs_the_token_and_unknown_ids_are_404(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    audit_id, token = _upload(client)
    client.cookies.clear()  # a visitor without the account
    assert client.post(f"/audits/{audit_id}/publish?token=wrong").status_code == 404
    missing = client.get("/v/doesnotexist")
    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "no-store"
    assert client.get("/v/doesnotexist/badge.svg").status_code == 404


def test_unpublish_removes_the_page(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    audit_id, token = _upload(client)
    public_id = client.post(
        f"/audits/{audit_id}/publish?token={token}", headers={"accept": "application/json"}
    ).json()["public_id"]
    removed = client.post(
        f"/audits/{audit_id}/unpublish?token={token}", headers={"accept": "application/json"}
    )
    assert removed.json() == {"unpublished": True}
    assert client.get(f"/v/{public_id}").status_code == 404


def test_paid_mode_publishes_only_paid_audits(tmp_path: Path) -> None:
    client, store = _client(tmp_path, free_mode=False, access_codes=True)
    audit_id, token = _upload(client)
    preview = client.get(f"/audits/{audit_id}?token={token}")
    assert "/publish?token=" not in preview.text
    assert client.post(f"/audits/{audit_id}/publish?token={token}").status_code == 402
    code, _ = store.create_access_code(  # type: ignore[attr-defined]
        credits=1, note="", at=datetime.now(UTC)
    )
    client.post(f"/audits/{audit_id}/redeem?token={token}", data={"code": code})
    published = client.post(f"/audits/{audit_id}/publish?token={token}", follow_redirects=False)
    assert published.status_code == 303


def test_a_purged_unpublished_audit_answers_410(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    audit_id, token = _upload(client)
    public_id = client.post(
        f"/audits/{audit_id}/publish?token={token}", headers={"accept": "application/json"}
    ).json()["public_id"]
    client.post(f"/audits/{audit_id}/unpublish?token={token}")
    far = datetime(2100, 1, 1, tzinfo=UTC)
    assert store.purge_expired(far, retention_days=1) == 1  # type: ignore[attr-defined]
    assert client.get(f"/v/{public_id}").status_code == 404
    assert client.get(f"/audits/{audit_id}?token={token}").status_code == 410


def test_a_purged_published_audit_keeps_only_its_public_page(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    audit_id, token = _upload(client)
    public_id = client.post(
        f"/audits/{audit_id}/publish?token={token}", headers={"accept": "application/json"}
    ).json()["public_id"]
    before = client.get(f"/v/{public_id}").text
    badge_before = client.get(f"/v/{public_id}/badge.svg").text
    far = datetime(2100, 1, 1, tzinfo=UTC)
    assert store.purge_expired(far, retention_days=1) == 1  # type: ignore[attr-defined]

    # The private report and the uploads are gone...
    assert client.get(f"/audits/{audit_id}?token={token}").status_code == 410
    record = store.get_audit(audit_id, with_blobs=True)  # type: ignore[attr-defined]
    assert record.result_json is None and record.equity_csv is None
    assert record.declared_json is None and record.client_ip == ""
    # ...the public page and badge are unchanged, result hash included.
    assert client.get(f"/v/{public_id}").text == before
    assert client.get(f"/v/{public_id}/badge.svg").text == badge_before
    view, _ = store.publication_view(audit_id)  # type: ignore[attr-defined]
    assert SECRET_DESCRIPTION not in json.dumps(view)
    assert set(view) == {
        "generated_at_utc",
        "verdict",
        "inputs",
        "engine",
        "declared",
        "multiplicity",
    }
    assert set(view["declared"]) == {"trials"}

    # The owner can still withdraw it with the private link.
    wrong = client.post(f"/audits/{audit_id}/unpublish?token=nope", follow_redirects=False)
    assert wrong.status_code == 404
    done = client.post(f"/audits/{audit_id}/unpublish?token={token}", follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"].startswith("/?lang=")
    assert client.get(f"/v/{public_id}").status_code == 404
    assert store.publication_view(audit_id) is None  # type: ignore[attr-defined]


def test_sample_report_is_full_synthetic_and_guarded(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    spanish = client.get("/ejemplo")
    assert spanish.status_code == 200
    assert SAMPLE_BANNER["es"] in spanish.text
    assert "class='lockbox'" not in spanish.text and "VISTA PREVIA" not in spanish.text
    assert "<svg" in spanish.text
    assert find_claims(spanish.text) == []
    english = client.get("/sample")
    assert html.escape(SAMPLE_BANNER["en"]) in english.text
    assert find_claims(english.text) == []
    # Built once: the second response is the same document.
    assert client.get("/ejemplo").text == spanish.text


def test_sample_is_deterministic_and_uses_the_optimisation_passes() -> None:
    first = sample_result("es", bootstrap_samples=50)
    second = sample_result("es", bootstrap_samples=50)
    assert first.verdict == second.verdict
    assert first.performance == second.performance
    assert first.inputs == second.inputs
    trials = first.multiplicity["trials_used"]
    assert trials["evidence"] == "MEASURED" and trials["value"] >= 120
    assert first.inputs["source_format"] == "mt5_tester_html"


def test_landing_has_how_it_works_prices_faq_and_sample_link(tmp_path: Path) -> None:
    for locale, words in (
        ("es", ("Cómo funciona", "Precios", "Preguntas frecuentes", "/ejemplo")),
        ("en", ("How it works", "Pricing", "Frequently asked questions", "/sample")),
    ):
        free = landing(locale=locale, free_mode=True, price_usd=49)
        for word in words:
            assert word in free
        assert find_claims(free) == []
        paid = landing(
            locale=locale,
            free_mode=False,
            price_usd=19,
            access_codes=True,
            card_payments=True,
            contact_url="https://wa.me/000",
            retention_days=14,
        )
        assert "USD 19" in paid and "https://wa.me/000" in paid and "14" in paid
        assert find_claims(paid) == []
    client, _ = _client(tmp_path, price_usd_cents=2900)
    page = client.get("/")
    assert "/ejemplo" in page.text
