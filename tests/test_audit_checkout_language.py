"""A language switch expires the Checkout session it replaced; Stripe is simulated."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from audit_fixtures import csv_bytes, positive_drift, signed_in  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import payments  # noqa: E402
from quant_trade.audit.payments import PLAN_PACK, PLAN_SINGLE  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import account_order_ref, make_store  # noqa: E402
from quant_trade.audit.web import create_app, sign_stripe_payload  # noqa: E402

WEBHOOK_SECRET = "whsec_test"
SELLING = {
    "stripe_secret_key": "sk_live_x",
    "stripe_webhook_secret": WEBHOOK_SECRET,
    "free_mode": False,
    "access_codes": True,
    "price_usd_cents": 2900,
    "pack_price_usd_cents": 6900,
    "contact_url": "https://wa.me/5200000000",
    "base_url": "https://rigor.example",
    "approved_markets": frozenset({"MX"}),
}
PAID = {PLAN_SINGLE: 2900, PLAN_PACK: 6900}
FORM = {"billing_country": "MX", "final_sale": "yes"}
ACCOUNT_BUY = {"es": "/cuenta", "en": "/account", "pt": "/pt/conta"}


class FakeStripe:
    """Checkout sessions as Stripe keeps them: open, complete or expired."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.status: dict[str, str] = {}
        self.expire_calls: list[str] = []
        self.expire_error: Exception | None = None

    def _open(self, **call: Any) -> dict[str, Any]:
        self.created.append(call)
        session_id = f"cs_live_{len(self.created)}"
        self.status[session_id] = "open"
        return {
            "id": session_id,
            "url": f"https://checkout.stripe.test/{len(self.created)}",
            "expires_at": int(time.time()) + 3600,
        }

    def checkout(self, cfg: AuditSettings, audit_id: str, token: str, **kwargs: Any) -> dict:
        return self._open(audit_id=audit_id, **kwargs)

    def account_checkout(self, cfg: AuditSettings, account_id: str, **kwargs: Any) -> dict:
        return self._open(account_id=account_id, **kwargs)

    def expire(self, cfg: AuditSettings, session_id: str) -> dict[str, Any]:
        self.expire_calls.append(session_id)
        if self.expire_error is not None:
            raise self.expire_error
        if self.status.get(session_id) != "open":
            # Stripe answers 400 for a session that is complete or expired.
            raise ValueError("only Checkout Sessions with a status of open can be expired")
        self.status[session_id] = "expired"
        return {"id": session_id, "status": "expired"}


def _client(tmp_path: Path, **overrides: Any) -> tuple[TestClient, FakeStripe]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        **{**SELLING, **overrides},
    )
    client = signed_in(TestClient(create_app(settings, make_store(settings.database_url))))
    fake = FakeStripe()
    client.app.state.checkout_factory = fake.checkout
    client.app.state.account_checkout_factory = fake.account_checkout
    client.app.state.session_expirer = fake.expire
    return client, fake


def _upload(client: TestClient) -> tuple[str, str]:
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    data = {"trials": "3", "cost_bps": "5", "consent": "on"}
    location = client.post("/audits", files=files, data=data, follow_redirects=False).headers[
        "location"
    ]
    path, _, query = location.partition("?")
    return path.rsplit("/", 1)[1], query.split("token=")[1].split("&")[0]


def _pay(client: TestClient, audit_id: str, token: str, lang: str, plan: str = "single") -> str:
    response = client.post(
        f"/audits/{audit_id}/checkout?token={token}&lang={lang}",
        data={"plan": plan, **FORM},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:300]
    return response.headers["location"]


def _buy(client: TestClient, lang: str, plan: str = "single") -> str:
    base = ACCOUNT_BUY[lang]
    csrf = re.search(r"name='csrf' value='([^']+)'", client.get(base).text)
    assert csrf
    response = client.post(
        f"{base}/comprar",
        data={"csrf": csrf.group(1), "plan": plan, **FORM},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"]


def _paid(metadata: dict[str, str], sid: str, plan: str = PLAN_SINGLE) -> dict[str, Any]:
    return {
        "id": sid,
        "payment_status": "paid",
        "livemode": True,
        "currency": "usd",
        "amount_total": PAID[plan],
        "customer_details": {"address": {"country": "MX"}},
        "metadata": {**metadata, "plan": plan, "app": "rigor"},
    }


def _webhook(client: TestClient, session: dict[str, Any]) -> int:
    event = json.dumps({"type": "checkout.session.completed", "data": {"object": session}})
    header = sign_stripe_payload(event.encode(), WEBHOOK_SECRET, timestamp=int(time.time()))
    return client.post(
        "/webhooks/stripe", content=event, headers={"stripe-signature": header}
    ).status_code


def _account_id(client: TestClient) -> str:
    account = client.app.state.store.find_account("tester@example.com")
    assert account is not None
    return account.id


# -- a report ---------------------------------------------------------------------
def test_a_language_switch_expires_the_session_of_the_other_language(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    audit_id, token = _upload(client)
    store = client.app.state.store
    assert _pay(client, audit_id, token, "es") == "https://checkout.stripe.test/1"
    assert fake.expire_calls == []
    # The same language again reuses the open session: nothing to expire.
    assert _pay(client, audit_id, token, "es") == "https://checkout.stripe.test/1"
    assert fake.expire_calls == [] and len(fake.created) == 1

    assert _pay(client, audit_id, token, "en") == "https://checkout.stripe.test/2"
    assert fake.expire_calls == ["cs_live_1"]
    assert fake.status == {"cs_live_1": "expired", "cs_live_2": "open"}
    old = store.get_checkout_session("cs_live_1")
    new = store.get_checkout_session("cs_live_2")
    assert old.status == "open" and old.resolution == "expired_language_change"
    assert old.expires_at < new.expires_at
    assert new.resolution == ""
    # The final-sale acceptance of each order stays as evidence.
    assert store.final_sale_acceptance(old.id) and store.final_sale_acceptance(new.id)

    # Back in Spanish: the expired session is not offered again.
    assert _pay(client, audit_id, token, "es") == "https://checkout.stripe.test/3"
    assert fake.expire_calls == ["cs_live_1", "cs_live_2"]
    assert fake.status == {
        "cs_live_1": "expired",
        "cs_live_2": "expired",
        "cs_live_3": "open",
    }
    assert [call["locale"] for call in fake.created] == ["es", "en", "es"]


def test_another_plan_or_another_report_is_left_open(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    audit_id, token = _upload(client)
    other_id, other_token = _upload(client)
    _pay(client, audit_id, token, "es")
    _pay(client, audit_id, token, "en", plan="pack")
    _pay(client, other_id, other_token, "pt")
    assert fake.expire_calls == []
    assert set(fake.status.values()) == {"open"}


def test_a_failed_expiry_never_blocks_the_new_session(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    client, fake = _client(tmp_path)
    audit_id, token = _upload(client)
    store = client.app.state.store
    _pay(client, audit_id, token, "es")
    fake.expire_error = TimeoutError("sk_live_x timed out")
    with caplog.at_level(logging.WARNING, logger="quant_trade.audit.payments"):
        assert _pay(client, audit_id, token, "en") == "https://checkout.stripe.test/2"
    assert fake.expire_calls == ["cs_live_1"]
    assert "could not expire superseded Checkout session cs_live_1: TimeoutError" in caplog.text
    # Ids and the error class only: never the key or the error's own text.
    assert "sk_live_x" not in caplog.text and "timed out" not in caplog.text
    # Stripe still has the old session open, so the old order stays reusable.
    old = store.get_checkout_session("cs_live_1")
    assert old.status == "open" and old.resolution == ""
    assert store.get_checkout_session("cs_live_2").status == "open"
    assert _pay(client, audit_id, token, "es") == "https://checkout.stripe.test/1"
    assert len(fake.created) == 2


def test_an_answer_that_is_not_an_expiry_changes_nothing(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    audit_id, token = _upload(client)
    _pay(client, audit_id, token, "es")
    client.app.state.session_expirer = lambda cfg, sid: {"id": sid, "status": "open"}
    _pay(client, audit_id, token, "en")
    old = client.app.state.store.get_checkout_session("cs_live_1")
    assert old.resolution == "" and old.expires_at > "2026"


def test_a_session_paid_at_stripe_is_refused_and_its_webhook_delivers(tmp_path: Path) -> None:
    """The payment won the race: Stripe refuses the expiry and the order is kept."""
    client, fake = _client(tmp_path)
    audit_id, token = _upload(client)
    store = client.app.state.store
    _pay(client, audit_id, token, "es")
    order_id = fake.created[0]["order_id"]
    fake.status["cs_live_1"] = "complete"  # paid at Stripe; the webhook is on its way
    _pay(client, audit_id, token, "en")
    assert fake.expire_calls == ["cs_live_1"] and fake.status["cs_live_1"] == "complete"
    assert store.get_checkout_order(order_id).resolution == ""

    session = _paid({"audit_id": audit_id, "order_id": order_id}, "cs_live_1")
    assert _webhook(client, session) == 200
    assert store.get_audit(audit_id).paid
    assert store.get_checkout_order(order_id).status == "delivered"
    # A paid report sells nothing else: no new session and nothing expired.
    location = _pay(client, audit_id, token, "pt")
    assert location == f"/audits/{audit_id}?token={token}&lang=pt"
    assert len(fake.created) == 2 and fake.expire_calls == ["cs_live_1"]


def test_a_late_webhook_for_an_expired_session_still_delivers_once(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    audit_id, token = _upload(client)
    store = client.app.state.store
    _pay(client, audit_id, token, "es")
    _pay(client, audit_id, token, "en")
    old_order, new_order = (call["order_id"] for call in fake.created)
    assert store.get_checkout_order(old_order).resolution == "expired_language_change"

    late = _paid({"audit_id": audit_id, "order_id": old_order}, "cs_live_1")
    assert _webhook(client, late) == 200
    assert store.get_audit(audit_id).paid
    settled = store.get_checkout_order(old_order)
    assert settled.status == "delivered" and settled.resolution == ""
    assert settled.paid_amount_cents == 2900
    # Stripe retries the event: the same single delivery.
    assert _webhook(client, late) == 200
    assert store.get_checkout_order(old_order).status == "delivered"

    # The new session is paid too: a second charge for review, never a second delivery.
    second = _paid({"audit_id": audit_id, "order_id": new_order}, "cs_live_2")
    assert _webhook(client, second) == 200
    duplicate = store.get_checkout_order(new_order)
    assert duplicate.status == "duplicate"
    assert duplicate.resolution == "manual_refund_review"
    assert store.get_audit(audit_id).stripe_session_id == "cs_live_1"


def test_a_late_pack_payment_on_an_expired_session_gives_one_pack(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    audit_id, token = _upload(client)
    store = client.app.state.store
    _pay(client, audit_id, token, "es", plan="pack")
    _pay(client, audit_id, token, "pt", plan="pack")
    assert fake.expire_calls == ["cs_live_1"]
    old_order = fake.created[0]["order_id"]
    late = _paid({"audit_id": audit_id, "order_id": old_order}, "cs_live_1", PLAN_PACK)
    assert _webhook(client, late) == 200 and _webhook(client, late) == 200
    assert store.get_checkout_order(old_order).status == "delivered"
    code = payments.pack_code(WEBHOOK_SECRET, "cs_live_1")
    assert payments.pack_for(store, client.app.state.settings, "cs_live_1") == (code, 2)


def test_an_order_held_for_review_is_never_expired(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    audit_id, token = _upload(client)
    store = client.app.state.store
    _pay(client, audit_id, token, "es")
    order_id = fake.created[0]["order_id"]
    held = _paid({"audit_id": audit_id, "order_id": order_id}, "cs_live_1")
    held["customer_details"] = {"address": {"country": "US"}}
    assert _webhook(client, held) == 200
    assert store.get_checkout_order(order_id).status == "paid_review"
    # The review blocks a new purchase, so nothing is created or expired.
    response = client.post(
        f"/audits/{audit_id}/checkout?token={token}&lang=en",
        data={"plan": "single", **FORM},
        follow_redirects=False,
    )
    assert response.status_code == 409
    assert fake.expire_calls == [] and len(fake.created) == 1


def test_alternating_languages_stops_opening_new_sessions(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Past the hourly limit the old session is reused, as before the expiry existed."""
    client, fake = _client(tmp_path)
    audit_id, token = _upload(client)
    limit = payments.EXPIRIES_PER_HOUR
    with caplog.at_level(logging.WARNING, logger="quant_trade.audit.payments"):
        seen = [_pay(client, audit_id, token, ("es", "en")[turn % 2]) for turn in range(limit + 8)]
    assert len(fake.expire_calls) == limit
    assert len(fake.created) == limit + 2
    # The last two sessions stay open at Stripe and each language reuses its own.
    assert sorted(sid for sid, status in fake.status.items() if status == "open") == [
        f"cs_live_{limit + 1}",
        f"cs_live_{limit + 2}",
    ]
    assert set(seen[limit + 2 :]) == {
        f"https://checkout.stripe.test/{limit + 1}",
        f"https://checkout.stripe.test/{limit + 2}",
    }
    assert f"expiry limit reached: superseded Checkout session cs_live_{limit + 1}" in caplog.text
    # The limit is the account's too: its credit purchases expire nothing this hour.
    _buy(client, "es")
    _buy(client, "en")
    assert len(fake.expire_calls) == limit
    assert len(fake.created) == limit + 4


# -- the store --------------------------------------------------------------------
def test_only_open_unexpired_orders_of_the_same_purchase_are_superseded(
    tmp_path: Path,
) -> None:
    store = make_store(f"sqlite:///{tmp_path}/s.db")
    now = datetime(2026, 9, 25, tzinfo=UTC)
    account = "ab" * 16
    ref = account_order_ref(account)
    kwargs = {"account_id": account, "amount_cents": 2900, "currency": "usd"}

    def opened(locale: str, sid: str, *, plan: str = PLAN_SINGLE, at: datetime = now) -> str:
        order = store.reserve_checkout(ref, plan=plan, at=at, locale=locale, **kwargs)
        store.attach_checkout_session(
            order.id,
            session_id=sid,
            checkout_url=f"https://checkout.stripe.test/{sid}",
            expires_at=at + timedelta(hours=1),
        )
        return order.id

    es = opened("es", "cs_live_es")
    pack = opened("es", "cs_live_pack", plan=PLAN_PACK)
    # Reserved but without a session yet: it replaces nothing and is not replaced.
    pending = store.reserve_checkout(ref, plan=PLAN_SINGLE, at=now, locale="pt", **kwargs)
    assert store.superseded_checkouts(pending.id, at=now) == []
    en = opened("en", "cs_live_en")
    assert [order.id for order in store.superseded_checkouts(en, at=now)] == [es]
    assert store.superseded_checkouts(pack, at=now) == []
    assert store.superseded_checkouts("missing", at=now) == []
    # Past its own expiry there is nothing left to close at Stripe.
    assert store.superseded_checkouts(en, at=now + timedelta(hours=2)) == []

    # The session id must match, and only an open order is marked.
    assert not store.mark_checkout_expired(es, session_id="cs_live_other", at=now)
    assert store.mark_checkout_expired(es, session_id="cs_live_es", at=now)
    assert store.superseded_checkouts(en, at=now) == []
    marked = store.get_checkout_order(es)
    assert marked.status == "open" and marked.session_id == "cs_live_es"
    assert marked.checkout_url  # the funnel still counts the started checkout
    # The Spanish slot rotates to a new order instead of reusing the expired one.
    assert store.reserve_checkout(ref, plan=PLAN_SINGLE, at=now, locale="es", **kwargs).id != es


def test_a_slow_older_request_never_supersedes_the_newer_session(tmp_path: Path) -> None:
    store = make_store(f"sqlite:///{tmp_path}/s.db")
    now = datetime(2026, 9, 25, tzinfo=UTC)
    account = "ab" * 16
    ref = account_order_ref(account)
    kwargs = {"account_id": account, "plan": PLAN_SINGLE, "amount_cents": 2900, "currency": "usd"}
    # Spanish is reserved first, but Stripe answers it after the English one.
    slow = store.reserve_checkout(ref, at=now, locale="es", **kwargs)
    later = now + timedelta(seconds=2)
    fast = store.reserve_checkout(ref, at=later, locale="en", **kwargs)
    for order, sid in ((fast, "cs_live_en"), (slow, "cs_live_es")):
        store.attach_checkout_session(
            order.id,
            session_id=sid,
            checkout_url=f"https://checkout.stripe.test/{sid}",
            expires_at=later + timedelta(hours=1),
        )
    done = later + timedelta(seconds=5)
    # The older request finishes last: the buyer's newer session is not its to close.
    assert store.superseded_checkouts(slow.id, at=done) == []
    assert [order.id for order in store.superseded_checkouts(fast.id, at=done)] == [slow.id]


def test_a_refused_permission_leaves_the_old_session_open(tmp_path: Path) -> None:
    store = make_store(f"sqlite:///{tmp_path}/s.db")
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/s.db", **SELLING)
    now = datetime(2026, 9, 25, tzinfo=UTC)
    account = "ab" * 16
    ref = account_order_ref(account)
    kwargs = {"account_id": account, "plan": PLAN_SINGLE, "amount_cents": 2900, "currency": "usd"}
    orders = []
    for locale in ("es", "en"):
        order = store.reserve_checkout(ref, at=now, locale=locale, **kwargs)
        store.attach_checkout_session(
            order.id,
            session_id=f"cs_live_{locale}",
            checkout_url=f"https://checkout.stripe.test/{locale}",
            expires_at=now + timedelta(hours=1),
        )
        orders.append(order.id)
    calls: list[str] = []
    done = payments.expire_superseded(
        store,
        settings,
        orders[1],
        expirer=lambda cfg, sid: calls.append(sid) or {"id": sid, "status": "expired"},
        at=now,
        allowed=lambda: False,
    )
    assert done == 0 and calls == []
    assert store.get_checkout_order(orders[0]).resolution == ""
    assert store.reserve_checkout(ref, at=now, locale="es", **kwargs).id == orders[0]


def test_expire_superseded_never_raises(tmp_path: Path) -> None:
    store = make_store(f"sqlite:///{tmp_path}/s.db")
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/s.db", **SELLING)

    def broken(order_id: str, *, at: datetime) -> list[Any]:
        raise RuntimeError("database away")

    store.superseded_checkouts = broken  # type: ignore[method-assign]
    calls: list[str] = []
    done = payments.expire_superseded(
        store,
        settings,
        "0" * 32,
        expirer=lambda cfg, sid: calls.append(sid) or {},
        at=datetime(2026, 9, 25, tzinfo=UTC),
    )
    assert done == 0 and calls == []


def test_the_expire_call_is_one_post_to_stripes_expire_endpoint(tmp_path: Path) -> None:
    stripe = pytest.importorskip("stripe")
    seen: list[tuple[str, str, Any]] = []

    class Recorder(stripe.HTTPClient):
        name = "recorder"

        def request(self, method: str, url: str, headers: Any, post_data: Any = None) -> Any:
            seen.append((method, url, post_data))
            body = json.dumps(
                {"id": "cs_live_old", "object": "checkout.session", "status": "expired"}
            )
            return body, 200, {"Request-Id": "req_1"}

    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/s.db", **SELLING)
    answer = payments.stripe_expire_session(settings, "cs_live_old", http_client=Recorder())
    assert answer["id"] == "cs_live_old" and answer["status"] == "expired"
    ((method, url, post_data),) = seen
    assert method == "post" and not post_data
    assert url == "https://api.stripe.com/v1/checkout/sessions/cs_live_old/expire"
    assert payments.EXPIRE_TIMEOUT_SECONDS == 10


def _stripe_answers(stripe: Any, status: str, seen: list[tuple[str, str]]) -> Any:
    """Stripe refusing the expiry of a session it holds in ``status``."""

    class Refuser(stripe.HTTPClient):
        name = "refuser"

        def request(self, method: str, url: str, headers: Any, post_data: Any = None) -> Any:
            seen.append((method, url))
            if method == "post":
                error = {"type": "invalid_request_error", "message": "not open"}
                return json.dumps({"error": error}), 400, {"Request-Id": "req_1"}
            body = {"id": "cs_live_old", "object": "checkout.session", "status": status}
            return json.dumps(body), 200, {"Request-Id": "req_2"}

    return Refuser()


def test_a_session_stripe_already_expired_counts_as_expired(tmp_path: Path) -> None:
    """The answer was lost, or another request expired it: one read settles it."""
    stripe = pytest.importorskip("stripe")
    seen: list[tuple[str, str]] = []
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/s.db", **SELLING)
    answer = payments.stripe_expire_session(
        settings, "cs_live_old", http_client=_stripe_answers(stripe, "expired", seen)
    )
    assert answer["id"] == "cs_live_old" and answer["status"] == "expired"
    assert seen == [
        ("post", "https://api.stripe.com/v1/checkout/sessions/cs_live_old/expire"),
        ("get", "https://api.stripe.com/v1/checkout/sessions/cs_live_old"),
    ]


@pytest.mark.parametrize("status", ["complete", "open"])
def test_a_refused_expiry_of_a_paid_or_open_session_stays_an_error(
    tmp_path: Path, status: str
) -> None:
    stripe = pytest.importorskip("stripe")
    seen: list[tuple[str, str]] = []
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/s.db", **SELLING)
    with pytest.raises(stripe.InvalidRequestError):
        payments.stripe_expire_session(
            settings, "cs_live_old", http_client=_stripe_answers(stripe, status, seen)
        )
    assert len(seen) == 2


def test_the_expire_call_works_on_an_sdk_without_the_v1_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stripe = pytest.importorskip("stripe")
    built: list[dict[str, Any]] = []

    class Sessions:
        def expire(self, session_id: str) -> dict[str, Any]:
            return {"id": session_id, "status": "expired"}

    class Checkout:
        sessions = Sessions()

    class OldClient:
        checkout = Checkout()

        def __init__(self, key: str, **options: Any) -> None:
            built.append(options)

    monkeypatch.setattr(stripe, "StripeClient", OldClient)
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/s.db", **SELLING)
    answer = payments.stripe_expire_session(settings, "cs_live_old", http_client=object())
    assert answer == {"id": "cs_live_old", "status": "expired"}
    assert built[0]["max_network_retries"] == 0


def test_a_session_expired_behind_our_back_is_repaired_on_the_next_switch(
    tmp_path: Path,
) -> None:
    """Stripe expired it but the order was never marked: the next switch marks it."""
    client, fake = _client(tmp_path)
    audit_id, token = _upload(client)
    store = client.app.state.store
    _pay(client, audit_id, token, "es")
    fake.status["cs_live_1"] = "expired"  # expired at Stripe, the answer never arrived

    def expirer(cfg: AuditSettings, session_id: str) -> dict[str, Any]:
        # What ``stripe_expire_session`` returns after its read of the session.
        fake.expire_calls.append(session_id)
        return {"id": session_id, "status": fake.status[session_id]}

    client.app.state.session_expirer = expirer
    _pay(client, audit_id, token, "en")
    assert store.get_checkout_session("cs_live_1").resolution == "expired_language_change"
    # Spanish again opens a fresh session instead of the dead one.
    assert _pay(client, audit_id, token, "es") == "https://checkout.stripe.test/3"


# -- credits from "My account" ------------------------------------------------------
def test_account_credits_expire_the_other_language_and_settle_a_late_payment(
    tmp_path: Path,
) -> None:
    client, fake = _client(tmp_path)
    store = client.app.state.store
    account_id = _account_id(client)
    before = store.account_credits(account_id, datetime.now(UTC))
    assert _buy(client, "es") == "https://checkout.stripe.test/1"
    assert _buy(client, "pt") == "https://checkout.stripe.test/2"
    assert fake.expire_calls == ["cs_live_1"]
    assert [call["locale"] for call in fake.created] == ["es", "pt"]
    old_order, new_order = (call["order_id"] for call in fake.created)
    assert store.get_checkout_order(old_order).resolution == "expired_language_change"
    # The pack is another purchase: its session stays open.
    assert _buy(client, "en", plan="pack") == "https://checkout.stripe.test/3"
    assert fake.expire_calls == ["cs_live_1"]

    # A payment that raced the expiry still puts its credit on the account, once.
    late = _paid({"account_id": account_id, "order_id": old_order}, "cs_live_1")
    assert _webhook(client, late) == 200 and _webhook(client, late) == 200
    assert store.get_checkout_order(old_order).status == "delivered"
    assert store.account_credits(account_id, datetime.now(UTC)) == before + 1
    # The new session was charged as well: each charge has its own order and credit.
    second = _paid({"account_id": account_id, "order_id": new_order}, "cs_live_2")
    assert _webhook(client, second) == 200
    assert store.account_credits(account_id, datetime.now(UTC)) == before + 2


def test_a_delivered_credit_order_is_never_expired(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    store = client.app.state.store
    account_id = _account_id(client)
    _buy(client, "es")
    order_id = fake.created[0]["order_id"]
    fake.status["cs_live_1"] = "complete"
    paid = _paid({"account_id": account_id, "order_id": order_id}, "cs_live_1")
    assert _webhook(client, paid) == 200
    assert store.get_checkout_order(order_id).status == "delivered"
    assert _buy(client, "en") == "https://checkout.stripe.test/2"
    assert fake.expire_calls == []
    assert store.get_checkout_order(order_id).resolution == ""
    # Even asked directly, a delivered order is not marked.
    assert not store.mark_checkout_expired(order_id, session_id="cs_live_1", at=datetime.now(UTC))
    assert store.get_checkout_order(order_id).status == "delivered"


# -- the no-charge card check -------------------------------------------------------
def test_a_card_check_in_another_language_expires_nothing(tmp_path: Path) -> None:
    """Setup sessions charge nothing and keep no order: they are left to expire."""
    from test_audit_card_check import _CSRF, _app, _shared_browser
    from test_audit_card_check import _upload as upload_preview

    app, store, fake = _app(tmp_path)
    expired: list[str] = []
    app.state.session_expirer = lambda cfg, sid: expired.append(sid) or {}
    client, _ = _shared_browser(app, store)
    audit_id, token, location = upload_preview(client, 2)
    csrf = _CSRF.findall(client.get(location).text)[-1]
    for lang in ("es", "en", "pt"):
        started = client.post(
            f"/audits/{audit_id}/tarjeta?token={token}&lang={lang}",
            data={"csrf": csrf},
            follow_redirects=False,
        )
        assert started.headers["location"] == "https://checkout.stripe.test/s"
    assert [params["locale"] for params in fake.created] == ["es", "en", "pt-BR"]
    assert expired == [] and store.list_checkout_orders() == []


# -- the token in a redirect ----------------------------------------------------------
def test_a_checkout_without_a_token_never_redirects_to_token_none(tmp_path: Path) -> None:
    client, fake = _client(tmp_path)
    audit_id, _ = _upload(client)
    store = client.app.state.store
    store.mark_paid(audit_id, stripe_session_id="code:test", at=datetime.now(UTC))
    # The signed-in owner opens the report without its token.
    response = client.post(
        f"/audits/{audit_id}/checkout?lang=en",
        data={"plan": "single", **FORM},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/audits/{audit_id}?token=&lang=en"
    assert fake.created == []


def test_a_refused_reservation_without_a_token_never_redirects_to_token_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, fake = _client(tmp_path)
    audit_id, _ = _upload(client)

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("audit unavailable for checkout")

    monkeypatch.setattr(client.app.state.store, "reserve_checkout", refuse)
    response = client.post(
        f"/audits/{audit_id}/checkout?lang=pt",
        data={"plan": "single", **FORM},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/audits/{audit_id}?token=&lang=pt"
    assert fake.created == []
