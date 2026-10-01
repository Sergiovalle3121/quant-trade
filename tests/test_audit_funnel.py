"""The owner's sales funnel in /panel: visits, accounts and payments per tag."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import funnel  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.legal import LegalContext, privacy_text  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

KEY = "k" * 40
PASSWORD = "una frase larga y segura"
BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0"}
CSRF_FIELD = re.compile(r"name='csrf' value='([^']+)'")
PLAYBOOK = Path(__file__).resolve().parents[1] / "docs" / "AUDIT_LAUNCH_PLAYBOOK.md"


def _client(tmp_path: Path) -> tuple[TestClient, object]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        free_mode=False,
        access_codes=True,
        admin_key=KEY,
    )
    store = make_store(settings.database_url)
    return TestClient(create_app(settings, store), headers=BROWSER), store


def _today() -> str:
    return funnel.day_of(datetime.now(UTC))


def _visits(client: TestClient) -> dict[tuple[str, str], int]:
    client.app.state.visits.flush()  # type: ignore[attr-defined]
    rows = client.app.state.store.funnel_events(_today())["visits"]  # type: ignore[attr-defined]
    return {(locale, ref): count for _, locale, ref, count in rows}


def _signup(client: TestClient, email: str) -> None:
    match = CSRF_FIELD.search(client.get("/registro").text)
    assert match
    response = client.post(
        "/registro",
        data={"email": email, "password": PASSWORD, "csrf": match.group(1)},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _upload(client: TestClient) -> str:
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    data = {"trials": "3", "cost_bps": "5", "consent": "on"}
    response = client.post("/audits", files=files, data=data, follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"].split("/audits/")[1].split("?")[0]


def test_only_listed_tags_count() -> None:
    assert funnel.clean_ref("f4") == "f4"
    assert funnel.clean_ref(" F4 ") == "f4"
    for channel in ("telegram", "reddit", "discord", "dc-en-01", "tg-es-01", "fo-en-03", "hn"):
        assert funnel.clean_ref(channel) == channel
    for bad in ("", None, "zzz", "f4'", "../x", "f" * 40, "<b>", "f4 x"):
        assert funnel.clean_ref(bad) == ""
    assert all(funnel.REF_PATTERN.fullmatch(tag) for tag in funnel.REF_TAGS)


def test_campaign_tags_count_without_being_listed() -> None:
    for tag in ("dc-us-103", "tg-mx-161", "dir-04", "ev-mx-01", "x-us-201", "fo-mx-02"):
        assert tag not in funnel.REF_TAGS
        assert funnel.clean_ref(tag) == tag
        assert funnel.ref_label(tag).startswith("Campaña · ")
    assert funnel.ref_label("dc-us-103") == "Campaña · Discord"
    assert funnel.ref_label("telegram") == "Telegram"
    for bad in ("zz-us-01", "dc-usa-01", "dc-us-1", "dc-us-1234", "dc-us-01x", "-dc-01"):
        assert funnel.clean_ref(bad) == ""
    counts = funnel.Funnel()
    counts.add("visits", day="2026-10-01", locale="es", ref="tg-mx-161")
    counts.add("visits", day="2026-10-01", locale="es", ref="zz-us-01")
    assert counts.by_ref["tg-mx-161"].counts["visits"] == 1
    assert counts.by_ref[funnel.DIRECT].counts["visits"] == 1


def test_robots_and_link_previews_are_not_people() -> None:
    assert funnel.is_person(BROWSER["User-Agent"])
    for agent in ("", None, "WhatsApp/2.23", "Googlebot/2.1", "curl/8.0", "TelegramBot"):
        assert not funnel.is_person(agent)


def _browser(client: TestClient) -> TestClient:
    """A new browser (no cookies) on the same app."""
    return TestClient(client.app, headers=BROWSER)


def test_visits_are_bare_counters_per_day_language_and_tag(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    assert client.get("/").status_code == 200
    tagged = _browser(client)
    first = tagged.get("/para/retos-prop-firm?ref=f6")
    assert first.cookies.get(funnel.REF_COOKIE) == "f6"
    assert first.cookies.get(funnel.SEEN_COOKIE) == _today()
    # The first tag stays, and the same browser counts once a day.
    for _ in range(5):
        assert tagged.get("/pt?ref=f4").status_code == 200
    later = _browser(client)
    later.cookies.set(funnel.REF_COOKIE, "f6")
    assert later.get("/pt?ref=f4").status_code == 200
    assert _browser(client).get("/en").status_code == 200
    assert _browser(client).get("/?lang=en").status_code == 200
    assert _browser(client).get("/?lang=pt").status_code == 200
    # "/" shows Spanish whatever ``lang`` says, unless it asks for English.
    assert _visits(client) == {
        ("es", ""): 2,
        ("es", "f6"): 1,
        ("pt", "f6"): 1,
        ("en", ""): 2,
    }
    columns = {column.name for column in store.funnel_visits.columns}  # type: ignore[attr-defined]
    assert columns == {"day", "locale", "ref", "visits"}


def test_unknown_tags_robots_and_other_pages_do_not_count(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    unknown = client.get("/?ref=spam-tag")
    assert funnel.REF_COOKIE not in unknown.cookies
    _browser(client).get("/", headers={"User-Agent": "WhatsApp/2.23"})
    _browser(client).get("/", headers={"Sec-Purpose": "prefetch"})
    _browser(client).head("/")
    _browser(client).get("/guias")
    _browser(client).get("/metodologia")
    assert _visits(client) == {("es", ""): 1}


def test_a_slow_or_failing_database_never_touches_a_page(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    calls: list[int] = []

    def broken(**kwargs: object) -> None:
        calls.append(1)
        raise RuntimeError("database away")

    store.count_visit = broken  # type: ignore[attr-defined]
    for _ in range(3):
        assert _browser(client).get("/").status_code == 200
    assert calls == []  # nothing is written during a request
    client.app.state.visits.flush()  # type: ignore[attr-defined]
    assert calls == [1]  # one batched write, which failed and is kept
    del store.count_visit  # type: ignore[attr-defined]
    assert _visits(client) == {("es", ""): 3}


def test_accounts_reports_and_payments_follow_their_tag(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    client.get("/para/retos-prop-firm?ref=f6")
    _signup(client, "ana@example.com")
    account = store.find_account("ana@example.com")  # type: ignore[attr-defined]
    _upload(client)  # the free first full report
    preview_id = _upload(client)  # a free preview
    code, _ = store.create_access_code(  # type: ignore[attr-defined]
        credits=1, note="", at=datetime.now(UTC)
    )
    assert store.redeem_for_audit(preview_id, code, at=datetime.now(UTC))  # type: ignore[attr-defined]

    other = _browser(client)
    _signup(other, "bea@example.com")

    client.app.state.visits.flush()  # type: ignore[attr-defined]
    built = funnel.build(store.funnel_events(_today()))  # type: ignore[attr-defined]
    f6 = built.by_ref["f6"].counts
    assert f6 == {
        "visits": 1,
        "signups": 1,
        "email_verified": 0,
        "uploads": 2,
        "welcome": 1,
        "previews": 1,
        "referrals_accepted": 0,
        "checkout_started": 0,
        "credit_used": 1,
        "gift_credits": 0,
        "purchases": 0,
        "buyers": 0,
        "repeat_purchases": 0,
        "deliveries": 0,
        "rights_sold": 0,
        "gross_usd_cents": 0,
        "refund_usd_cents": 0,
    }
    assert built.by_ref["f6"].paid == 0  # a code without verified payment is no sale
    assert built.by_ref[funnel.DIRECT].counts["signups"] == 1
    assert built.by_day[(_today(), "es")].counts["signups"] == 2

    # The tag goes with the account.
    store.delete_account(account.id)  # type: ignore[attr-defined]
    left = store.funnel_events(_today())["signups"]  # type: ignore[attr-defined]
    assert all(ref != "f6" for _, _, ref, _ in left)


def test_observed_funnel_stages_keep_checkout_distinct_from_charge(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    now = datetime.now(UTC)
    client.get("/?ref=f4")
    _signup(client, "buyer@example.com")
    buyer = store.find_account("buyer@example.com")  # type: ignore[attr-defined]
    assert buyer is not None
    with store.engine.begin() as conn:  # type: ignore[attr-defined]
        conn.execute(
            store.verified_emails.insert().values(  # type: ignore[attr-defined]
                account_id=buyer.id, email=buyer.email, verified_at=now.isoformat()
            )
        )
    _upload(client)  # full welcome report
    audit_id = _upload(client)  # persisted preview, not a paid delivery

    invitee = store.create_account(  # type: ignore[attr-defined]
        email="invitee@example.com", password_hash="unused", locale="es", at=now
    )
    assert invitee is not None
    assert store.record_referral(invitee.id, buyer.id, device_sha256="", at=now)  # type: ignore[attr-defined]

    order = store.reserve_checkout(  # type: ignore[attr-defined]
        audit_id, account_id=buyer.id, plan="single", amount_cents=2900, currency="usd", at=now
    )
    before = funnel.build(store.funnel_events(_today())).total.counts  # type: ignore[attr-defined]
    assert before["email_verified"] == 1
    assert before["uploads"] == 2
    assert before["referrals_accepted"] == 1
    assert before["checkout_started"] == 0  # reservation alone never reached Checkout
    assert before["deliveries"] == before["purchases"] == 0

    store.attach_checkout_session(  # type: ignore[attr-defined]
        order.id,
        session_id="cs_live_funnel",
        checkout_url="https://checkout.stripe.test/funnel",
        expires_at=None,
    )
    opened = funnel.build(store.funnel_events(_today())).total.counts  # type: ignore[attr-defined]
    assert opened["checkout_started"] == 1
    assert opened["purchases"] == opened["deliveries"] == 0

    store.settle_card_payment(  # type: ignore[attr-defined]
        order_id=order.id,
        session_id="cs_live_funnel",
        audit_id=audit_id,
        plan="single",
        expected_cents=2900,
        paid_cents=2900,
        currency="usd",
        pack_code="",
        at=now,
        payment_livemode=True,
    )
    paid = funnel.build(store.funnel_events(_today()))  # type: ignore[attr-defined]
    assert paid.total.counts["checkout_started"] == 1
    assert paid.total.counts["purchases"] == paid.total.counts["deliveries"] == 1
    assert paid.total.counts["gross_usd_cents"] == 2900
    assert paid.by_ref["f4"].counts["email_verified"] == 1
    assert paid.by_ref["f4"].counts["uploads"] == 2
    assert paid.by_ref_locale[("f4", "es")].counts["purchases"] == 1
    assert paid.by_ref[funnel.DIRECT].counts["referrals_accepted"] == 1


def test_one_invitee_can_grant_only_one_credit_under_concurrent_settlement(tmp_path: Path) -> None:
    store = make_store(f"sqlite:///{tmp_path}/referrals.db")
    now = datetime.now(UTC)
    inviter = store.create_account(
        email="inviter@example.com", password_hash="unused", locale="es", at=now
    )
    invitee = store.create_account(
        email="invitee@example.com", password_hash="unused", locale="es", at=now
    )
    assert inviter is not None and invitee is not None
    assert store.record_referral(invitee.id, inviter.id, device_sha256="", at=now)

    def settle(_: int) -> str:
        return store.reward_referral(
            invitee.id, device_sha256="", client_ip="", at=now, credits=1, monthly_cap=5
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(settle, (1, 2)))
    assert sorted(outcomes) == ["", "credited"]
    assert store.account_credits(inviter.id, now) == 1
    with store.engine.connect() as conn:
        grants = conn.execute(store.credit_grants.select()).mappings().all()
    assert len(grants) == 1 and grants[0]["origin"] == "referral"


def test_reward_switch_hides_new_invites_but_keeps_earned_credits(tmp_path: Path) -> None:
    client, store = _client(tmp_path)
    _signup(client, "ana@example.com")
    now = datetime.now(UTC)
    inviter = store.find_account("ana@example.com")
    invitee = store.create_account(
        email="bea@example.com", password_hash="unused", locale="es", at=now
    )
    assert inviter is not None and invitee is not None
    assert store.record_referral(invitee.id, inviter.id, device_sha256="", at=now)
    assert (
        store.reward_referral(
            invitee.id, device_sha256="", client_ip="", at=now, credits=1, monthly_cap=5
        )
        == "credited"
    )
    disabled = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        free_mode=False,
        access_codes=True,
        referral_rewards=False,
    )
    after = TestClient(create_app(disabled, store), headers=BROWSER)
    after.cookies.update(client.cookies)
    page = after.get("/cuenta").text
    assert "Invita a un colega" not in page
    assert store.account_credits(inviter.id, now) == 1


def test_the_panel_shows_the_funnel_behind_the_key(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    client.get("/?ref=f4")
    _signup(client, "ana@example.com")
    assert "Embudo de ventas" not in client.get("/panel").text
    page = client.post("/panel", data={"key": KEY}).text
    assert "Embudo de ventas: últimos 30 días" in page
    assert "<td>f4</td><td>F4 · Sharpe por pura suerte</td><td>1</td><td>1</td>" in page
    for label in (
        "Correos confirmados",
        "Cargas guardadas",
        "Invitaciones aceptadas",
        "Sesiones Checkout creadas",
        "Compras live entregadas",
        "Contribución USD",
        "Por canal e idioma",
        "Por país del comprador",
    ):
        assert label in page
    assert "NOT_MEASURED" in page
    assert "no se deduce el país del idioma" in page.lower()
    assert "Contribución = cobro bruto confirmado" in page
    assert "no es beneficio ni ingreso neto" in page
    cohort_tables = [
        table
        for table in re.findall(r"<table>.*?</table>", page, re.S)
        if "Contribución USD" in table
    ]
    assert len(cohort_tables) == 3
    for table in cohort_tables:
        head = re.search(r"<thead><tr>(.*?)</tr></thead>", table, re.S)
        first_row = re.search(r"<tbody><tr>(.*?)</tr>", table, re.S)
        assert head is not None and first_row is not None
        assert head.group(1).count("<th>") == first_row.group(1).count("<td>")
    assert "?ref=f6" in page
    assert "ana@example.com" not in page
    assert find_claims(page) == []


def test_an_empty_funnel_says_so(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    page = client.post("/panel", data={"key": KEY}).text
    assert "Todavía no hay nada que contar" in page


def test_privacy_page_names_the_tag_cookie_in_both_languages() -> None:
    for locale in ("es", "en"):
        text = str(privacy_text(LegalContext(), locale=locale))
        assert funnel.REF_COOKIE in text
        assert "?ref=f4" in text


def test_every_template_that_is_posted_has_its_tag() -> None:
    """Posts, forum texts and first messages; the WhatsApp replies are answers."""
    text = PLAYBOOK.read_text(encoding="utf-8")
    ids = set(re.findall(r"^#### ([PFDV]\d+) · ES", text, re.M)) - {"V2"}
    assert {"P1", "F1", "F4", "F7", "D1", "V1"} <= ids
    assert {i.lower() for i in ids} <= set(funnel.REF_TAGS)


def test_a_failing_tag_store_never_breaks_a_sign_up(tmp_path: Path) -> None:
    client, store = _client(tmp_path)

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database away")

    store.set_account_ref = broken  # type: ignore[attr-defined]
    client.get("/?ref=f4")
    _signup(client, "ana@example.com")
    assert client.get("/cuenta", follow_redirects=False).status_code == 200


def test_what_we_keep_names_the_tag_in_every_language(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    # Sign-up shows one line; the full list, tag included, is the policy's.
    for path in ("/privacidad", "/privacy", "/pt/privacidade"):
        assert "?ref=f4" in client.get(path).text, path


def test_my_data_download_carries_the_tag(tmp_path: Path) -> None:
    import json

    client, _ = _client(tmp_path)
    client.get("/para/retos-prop-firm?ref=f6")
    _signup(client, "ana@example.com")
    data = json.loads(client.get("/cuenta/datos").text)
    assert data["arrived_through_link_tag"] == "f6"

    other = TestClient(client.app, headers=BROWSER)
    _signup(other, "bea@example.com")
    assert json.loads(other.get("/cuenta/datos").text)["arrived_through_link_tag"] == ""


def test_the_background_writer_flushes_on_shutdown(tmp_path: Path) -> None:
    _, store = _client(tmp_path)
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", admin_key=KEY)
    with TestClient(create_app(settings, store), headers=BROWSER) as client:
        assert client.get("/").status_code == 200
    rows = store.funnel_events(_today())["visits"]  # type: ignore[attr-defined]
    assert [(locale, ref, count) for _, locale, ref, count in rows] == [("es", "", 1)]
