"""Public sharing and examples keep the owner's existing attribution rules."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import funnel  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import Store, make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BROWSER = {"User-Agent": "Mozilla/5.0 Firefox/130.0"}


def _client(tmp_path: Path) -> tuple[TestClient, Store]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        base_url="https://audit.example",
    )
    store = make_store(settings.database_url)
    return TestClient(
        create_app(settings, store), base_url="https://testserver", headers=BROWSER
    ), store


def _browser(client: TestClient) -> TestClient:
    return TestClient(client.app, base_url="https://testserver", headers=BROWSER)


def _visits(client: TestClient) -> dict[tuple[str, str], int]:
    client.app.state.visits.flush()  # type: ignore[attr-defined]
    rows = client.app.state.store.funnel_events(  # type: ignore[attr-defined]
        funnel.day_of(datetime.now(UTC))
    )["visits"]
    return {(locale, ref): count for _, locale, ref, count in rows}


@pytest.fixture
def published(tmp_path: Path) -> tuple[TestClient, Store, str, str, str]:
    client, store = _client(tmp_path)
    signed_in(client)
    uploaded = client.post(
        "/audits",
        files={"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")},
        data={"trials": "3", "consent": "on"},
        follow_redirects=False,
    )
    assert uploaded.status_code == 303
    report_path = uploaded.headers["location"]
    audit_id = report_path.split("/audits/")[1].split("?")[0]
    publication = store.publish(audit_id, at=datetime.now(UTC))
    return client, store, audit_id, report_path, publication.public_id


def test_share_and_examples_are_named_bounded_tags() -> None:
    for tag in ("share", "ejemplos"):
        assert funnel.clean_ref(f" {tag.upper()} ") == tag
        assert find_claims(funnel.ref_label(tag)) == []
        result = funnel.build({"visits": [("2026-10-07", "es", tag, 2)]})
        assert result.by_ref[tag].counts["visits"] == 2
        assert funnel.DIRECT not in result.by_ref
    for value in ("share-unknown", "ejemplos-unknown", "share<script>", "share x"):
        assert funnel.clean_ref(value) == ""


def test_active_verification_counts_share_like_x_in_each_language(
    published: tuple[TestClient, Store, str, str, str],
) -> None:
    client, _, _, _, public_id = published
    for locale in ("es", "en", "pt"):
        for tag in ("share", "x"):
            response = _browser(client).get(f"/v/{public_id}?ref={tag}&lang={locale}")
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.cookies.get(funnel.REF_COOKIE) == tag
            assert response.cookies.get(funnel.SEEN_COOKIE) == funnel.day_of(datetime.now(UTC))
    assert _visits(client) == {
        (locale, tag): 1 for locale in ("es", "en", "pt") for tag in ("share", "x")
    }


def test_public_share_keeps_first_touch_and_counts_browser_once_a_day(
    published: tuple[TestClient, Store, str, str, str],
) -> None:
    client, _, _, _, public_id = published
    visitor = _browser(client)
    visitor.cookies.set(funnel.REF_COOKIE, "x")
    first = visitor.get(f"/v/{public_id}?ref=share&lang=en")
    assert first.status_code == 200
    assert funnel.REF_COOKIE not in first.cookies
    assert visitor.cookies.get(funnel.REF_COOKIE) == "x"
    assert visitor.get("/calculator?ref=ejemplos").status_code == 200
    returning = visitor.get(f"/v/{public_id}?ref=share&lang=pt")
    assert returning.status_code == 200
    assert returning.headers["cache-control"] == "no-store"
    assert _visits(client) == {("en", "x"): 1}


def test_assets_robots_prefetch_and_private_reports_do_not_count(
    published: tuple[TestClient, Store, str, str, str],
) -> None:
    client, _, _, report_path, public_id = published
    page = f"/v/{public_id}?ref=share"
    for suffix in ("card.svg", "card.png", "badge.svg"):
        assert _browser(client).get(f"/v/{public_id}/{suffix}?ref=share").status_code == 200
    for headers in (
        {"User-Agent": "Twitterbot/1.0"},
        {"User-Agent": "WhatsApp/2.23"},
        {"User-Agent": ""},
        {"Purpose": "prefetch"},
        {"Sec-Purpose": "prefetch"},
    ):
        response = _browser(client).get(page, headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
    _browser(client).head(page)
    assert _browser(client).get(f"/v/{public_id}/extra?ref=share").status_code == 404
    assert _browser(client).get("/v/missing?ref=share").status_code == 404
    assert client.get(report_path + "&ref=share").status_code == 200
    assert _visits(client) == {}


def test_withdrawn_verification_does_not_set_attribution_or_count(
    published: tuple[TestClient, Store, str, str, str],
) -> None:
    client, store, audit_id, _, public_id = published
    assert store.unpublish(audit_id)
    response = _browser(client).get(f"/v/{public_id}?ref=share")
    assert response.status_code == 404
    assert funnel.REF_COOKIE not in response.cookies
    assert funnel.SEEN_COOKIE not in response.cookies
    assert _visits(client) == {}


def test_examples_and_calculator_count_with_their_tag(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    paths = {
        "es": ("/ejemplos", "/calculadora"),
        "en": ("/en/examples", "/calculator"),
        "pt": ("/pt/exemplos", "/pt/calculadora"),
    }
    for locale, localized_paths in paths.items():
        for path in localized_paths:
            response = _browser(client).get(f"{path}?ref=ejemplos")
            assert response.status_code == 200, (locale, path)
            assert response.cookies.get(funnel.REF_COOKIE) == "ejemplos"
    assert _visits(client) == {(locale, "ejemplos"): 2 for locale in paths}
