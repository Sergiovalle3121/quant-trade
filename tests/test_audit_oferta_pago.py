"""The paid offer: the class without an account, the full report paid from the first
one, and the 7-day refund (``AUDIT_WELCOME_FULL_REPORT=false``, brief "Oferta 12").

Most tests run the configuration planned for production: paid mode, e-mail
confirmation required with a fake mail transport (mail is queued and never
sent: no lifespan, so no worker), card payment with Stripe simulated by the
HMAC helper, ``anon_preview=True`` and ``welcome_full_report=False``.
Everything is offline. The default configuration (the free first report on)
keeps every page as before: ``paid_offer.rewrite_html`` changes nothing then.
"""

from __future__ import annotations

import html
import json
import re
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from audit_fixtures import csv_bytes, positive_drift

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from test_audit_email_routes_ui import _outbox_id  # noqa: E402

from quant_trade.audit import account_pages, accounts, legal, mail, paid_offer  # noqa: E402
from quant_trade.audit.accounts import (  # noqa: E402
    ANON_PREVIEWS_PER_IPV4_PER_DAY,
    ANON_PREVIEWS_PER_NETWORK_PER_DAY,
    FREE_PREVIEWS_PER_MONTH,
    month_start,
)
from quant_trade.audit.faq import FAQ_PATH  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.legal import (  # noqa: E402
    LEGAL_PATHS,
    LEGAL_UPDATED,
    LegalContext,
    privacy_text,
    terms_text,
)
from quant_trade.audit.pages import LANDING_PATHS  # noqa: E402
from quant_trade.audit.pricing import PRICING_PATH, start_cta  # noqa: E402
from quant_trade.audit.report import LABELS  # noqa: E402
from quant_trade.audit.seo import PUBLIC_PAGES  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import Store, make_store  # noqa: E402
from quant_trade.audit.web import create_app, sign_stripe_payload  # noqa: E402

BASE = "https://rigor.example"
SECRET = "stable secret shared across replicas 1234567890"
WEBHOOK = "whsec_oferta"
PASSWORD = "una frase larga y segura"
LOCALES = ("es", "en", "pt")
CSRF_FIELD = re.compile(r"name='csrf' value='([^']+)'")
ANON = re.compile(r"^/audits/([A-Za-z0-9_-]+)\?token=([A-Za-z0-9_-]+)&acct=anon_preview$")
FORMS = {"es": "/auditar", "en": "/en/audit", "pt": "/pt/auditar"}
SIGNUP = {"es": "/registro", "en": "/signup", "pt": "/pt/cadastro"}

#: Sentences that promise a free full report, as any page might word them.
PROMISES: dict[str, tuple[str, ...]] = {
    "es": (
        r"informe completo gratis",
        r"primer informe[^.]{0,60}gratis",
        r"informe gratis",
        r"completo,? (?:y )?gratis",
        r"gratis[^.]{0,20}primer informe",
        r"sale completo",
    ),
    "en": (
        r"free (?:first )?full report",
        r"free first report",
        r"first (?:full )?report[^.]{0,40}\bfree\b",
        r"free report",
        r"in full,? (?:and )?free",
        r"comes out in full",
    ),
    "pt": (
        r"relatório completo (?:grátis|gratuito)",
        r"primeiro relatório[^.]{0,60}(?:grátis|gratuito)",
        r"relatório (?:grátis|gratuito)",
        r"completo,? (?:e )?grátis",
        r"sai completo",
    ),
}
#: The words "7 days" and "the terms" every refund line carries.
REFUND_WORDS = {"es": ("7 días", "términos"), "en": ("7 days", "terms"), "pt": ("7 dias", "termos")}
#: How the paid offer words what the free first report kept for the accounts that
#: had it: in the same sentence, always in the past.
LEGACY = {"es": "cuando lo ofrecíamos", "en": "when we offered it", "pt": "quando o oferecíamos"}
#: The new "My account" words of the paid offer.
ACCOUNT_PAID_KEYS = (
    "email_unverified_status_paid",
    "email_delivery_unavailable_paid",
    "email_checkout_required_paid",
    "email_verified_paid",
    "welcome_confirm_paid",
)


def _settings(tmp_path: Path, **extra: object) -> AuditSettings:
    values: dict[str, object] = {
        "database_url": f"sqlite:///{tmp_path}/audit.db",
        "bootstrap_samples": 100,
        "base_url": BASE,
        "free_mode": False,
        "email_verification_required": True,
        "email_token_secret": SECRET,
        "resend_api_key": "re_test_0123456789abcdefghij",
        "smtp_from": "Rigor <hola@example.com>",
        "stripe_secret_key": "sk_live_x",
        "stripe_webhook_secret": WEBHOOK,
        "approved_markets": frozenset({"MX"}),
        "operator_contact": "soporte@example.com",
        "trusted_proxy_hops": 1,
        "anon_preview": True,
        "welcome_full_report": False,
    }
    values.update(extra)
    return AuditSettings(**values)  # type: ignore[arg-type]


def _app(tmp_path: Path, **extra: object) -> tuple[Any, Store, AuditSettings]:
    settings = _settings(tmp_path, **extra)
    store = make_store(settings.database_url)
    return create_app(settings, store), store, settings


def _browser(app: Any, ip: str = "203.0.113.7") -> TestClient:
    return TestClient(app, base_url=BASE, headers={"X-Forwarded-For": ip})


def _csrf(page: str) -> str:
    match = CSRF_FIELD.search(page)
    assert match is not None
    return match.group(1)


def _upload(client: TestClient, seed: int) -> Any:
    return client.post(
        "/audits",
        files={"equity": ("e.csv", csv_bytes(positive_drift(500, seed=seed)), "text/csv")},
        data={"consent": "on"},
        follow_redirects=False,
    )


def _location(answer: Any) -> tuple[str, str]:
    location = answer.headers["location"]
    audit_id = location.split("/audits/")[1].split("?")[0]
    token = location.split("token=")[1].split("&")[0]
    return audit_id, token


def _signup(client: TestClient, email: str, next_path: str = "", locale: str = "es") -> Any:
    path = SIGNUP[locale]
    page = client.get(path, params={"next": next_path} if next_path else None)
    return client.post(
        path,
        data={"email": email, "password": PASSWORD, "csrf": _csrf(page.text), "next": next_path},
        follow_redirects=False,
    )


def _confirm(app: Any, store: Store, account_id: str) -> Any:
    """Open the e-mailed link on another device, as a reader of the e-mail would."""
    phone = TestClient(app, base_url=BASE)
    token = mail.token_for(_outbox_id(store, account_id, "verify"), SECRET)
    path = mail.PATHS["es"]["verify"]
    page = phone.get(path, params={"token": token})
    answer = phone.post(
        path, data={"token": token, "csrf": _csrf(page.text)}, follow_redirects=False
    )
    assert answer.status_code == 303
    return answer


def _visible(page: str) -> str:
    """The words a reader or a search engine gets: text, descriptions and JSON-LD."""
    found: list[str] = []
    for payload in re.findall(r"<script type='application/ld\+json'>(.*?)</script>", page, re.S):
        found.append(json.dumps(json.loads(payload), ensure_ascii=False))
    found += [
        html.unescape(value)
        for value in re.findall(r"\b(?:content|title|aria-label|alt)='([^']*)'", page)
    ]
    body = re.sub(r"<(script|style|svg)\b[^>]*>.*?</\1>", " ", page, flags=re.S)
    found.append(html.unescape(re.sub(r"<[^>]+>", " ", body)))
    return " ".join(" ".join(found).split())


def _promises(text: str, locale: str) -> list[str]:
    return [m.group(0) for p in PROMISES[locale] for m in re.finditer(p, text, re.I)]


def _offered(text: str, locale: str) -> list[str]:
    """The sentences of ``text`` that name a free full report as an offer: every one
    but those that say what it kept back when we offered it (:data:`LEGACY`)."""
    found: list[str] = []
    for pattern in PROMISES[locale]:
        for match in re.finditer(pattern, text, re.I):
            start = text.rfind(".", 0, match.start()) + 1
            end = text.find(".", match.end())
            sentence = text[start : end if end >= 0 else len(text)].strip()
            if LEGACY[locale] not in sentence:
                found.append(sentence)
    return found


def _escaped(text: str) -> str:
    return html.escape(text, quote=True)


def _pay(app: Any, client: TestClient, settings: AuditSettings, audit_id: str, token: str) -> str:
    """Pay one audit by card with Stripe simulated: checkout, then the signed webhook."""
    observed: list[str] = []

    def fake_checkout(cfg: AuditSettings, aid: str, tok: str, **kwargs: Any) -> dict[str, Any]:
        assert aid == audit_id and tok == token and kwargs["plan"] == "single"
        observed.append(kwargs["order_id"])
        return {"id": "cs_oferta_1", "url": "https://checkout.stripe.test/oferta"}

    app.state.checkout_factory = fake_checkout
    answer = client.post(
        f"/audits/{audit_id}/checkout?token={token}&lang=es",
        data={"plan": "single", "billing_country": "MX", "final_sale": "yes"},
        follow_redirects=False,
    )
    assert answer.status_code == 303, answer.text[:300]
    assert answer.headers["location"] == "https://checkout.stripe.test/oferta"
    paid = {
        "id": "cs_oferta_1",
        "payment_status": "paid",
        "livemode": True,
        "currency": "usd",
        "amount_total": settings.price_usd_cents,
        "customer_details": {"address": {"country": "MX"}},
        "metadata": {
            "audit_id": audit_id,
            "plan": "single",
            "app": "rigor",
            "order_id": observed[0],
        },
    }
    event = json.dumps({"type": "checkout.session.completed", "data": {"object": paid}})
    signature = sign_stripe_payload(event.encode(), WEBHOOK, timestamp=int(time.time()))
    hook = client.post("/webhooks/stripe", content=event, headers={"stripe-signature": signature})
    assert hook.status_code == 200
    return observed[0]


# -- 1. The switch -----------------------------------------------------------------------
def test_the_switch_reads_the_environment_and_defaults_to_the_free_first_report() -> None:
    assert accounts.WELCOME_FULL_REPORT is True
    assert AuditSettings().welcome_full_report is True
    assert AuditSettings.from_env({}).welcome_full_report is True
    assert AuditSettings.from_env({"AUDIT_WELCOME_FULL_REPORT": ""}).welcome_full_report is True
    for off in ("false", "0", "no", "off", "FALSE"):
        env = {"AUDIT_WELCOME_FULL_REPORT": off}
        assert AuditSettings.from_env(env).welcome_full_report is False, off
    env = {"AUDIT_WELCOME_FULL_REPORT": "true"}
    assert AuditSettings.from_env(env).welcome_full_report is True
    assert paid_offer.offer_kind(AuditSettings()) == "free"
    paid = AuditSettings(free_mode=False, access_codes=True)
    assert paid_offer.offer_kind(paid) == "welcome"
    assert paid_offer.offer_kind(replace(paid, welcome_full_report=False)) == "paid"


@pytest.mark.parametrize("locale", LOCALES)
def test_the_rewrite_changes_nothing_without_the_paid_offer(locale: str) -> None:
    page = (
        "<p>Con tu cuenta, el primer informe completo es gratis, con PDF.</p>"
        "<p>With an account, your first full report is free too.</p>"
        "<p>O primeiro relatório completo é grátis com conta.</p>"
    )
    for offer in (None, "welcome", "free", paid_offer.Offer(), paid_offer.Offer(kind="free")):
        assert paid_offer.rewrite_html(page, locale, offer) == page
        assert paid_offer.rewrite_text(page, locale, offer) == page


# -- 2. The whole way, with the production configuration --------------------------------
def test_preview_sign_up_locked_report_purchase_and_unlock(tmp_path: Path) -> None:
    """Upload without an account, see the class, sign up from the report: the report
    goes on the account locked; confirming the e-mail opens nothing; the purchase does."""
    app, store, settings = _app(tmp_path)
    visitor = _browser(app)
    sent = _upload(visitor, 41)
    assert sent.status_code == 303
    match = ANON.match(sent.headers["location"])
    assert match is not None, sent.headers["location"]
    audit_id, token = match.group(1), match.group(2)
    record = store.get_audit(audit_id)
    assert record is not None and not record.paid
    # No file fingerprint is kept: no free report will ever check it.
    row = store.anon_pending(audit_id)
    assert row is not None and row.file_sha256 == "" and row.device_sha256

    preview = visitor.get(sent.headers["location"]).text
    assert f"Clase {record.overall_class}" in html.unescape(preview)
    offer = paid_offer.offer_of(settings)
    box = paid_offer.anon_box_text("es", offer)
    assert "USD 29" in box and "7 días" in box
    assert _escaped(box) in preview
    assert _escaped(paid_offer.words("es")["anon_signup"]) in preview
    assert _escaped(account_pages.COPY["es"]["anon_preview_link"]) in preview
    for key in ("anon_preview", "anon_preview_box", "anon_preview_signup"):
        assert _escaped(account_pages.COPY["es"][key]) not in preview, key
    assert _promises(_visible(preview), "es") == []

    # The box's main button: sign-up, with the report's key in its cookie.
    go = visitor.post(
        f"/audits/{audit_id}/account",
        params={"token": token, "lang": "es"},
        data={"go": "signup"},
        follow_redirects=False,
    )
    assert go.status_code == 303 and go.headers["location"].startswith("/registro?next=")
    next_path = f"/audits/{audit_id}?lang=es"
    made = _signup(visitor, "compradora@example.com", next_path)
    assert made.status_code == 303
    assert made.headers["location"] == (
        f"/audits/{audit_id}?token={token}&lang=es&acct=welcome_confirm"
    )
    account = store.find_account("compradora@example.com")
    assert account is not None
    # Linked to the account, locked, one of the month's previews; nothing pending.
    assert store.account_for_audit(audit_id) == account.id
    assert not store.get_audit(audit_id).paid
    assert not store.welcome_used(account.id)
    assert store.welcome_pending_for(account.id, since=datetime(2000, 1, 1, tzinfo=UTC)) == []
    now = datetime.now(UTC)
    assert store.free_previews_since(month_start(now), account_id=account.id) == 1
    back = visitor.get(made.headers["location"]).text
    assert _escaped(account_pages.COPY["es"]["welcome_confirm_paid"]) in back
    assert _escaped(account_pages.COPY["es"]["welcome_confirm"]) not in back
    assert "class='lockbox'" in back
    assert _promises(_visible(back), "es") == []

    # Confirming the e-mail opens nothing for free.
    confirmed = _confirm(app, store, account.id)
    assert "done=email_verified" in confirmed.headers["location"]
    assert "email_verified_report" not in confirmed.headers["location"]
    assert store.email_verified(account.id)
    assert not store.get_audit(audit_id).paid and not store.welcome_used(account.id)

    # The purchase of always: the box ticked records the terms' version.
    locked = visitor.get(f"/audits/{audit_id}?token={token}&lang=es").text
    assert _escaped(LABELS["es"]["final_sale"]) in locked
    order_id = _pay(app, visitor, settings, audit_id, token)
    assert store.get_audit(audit_id).paid
    acceptance = store.final_sale_acceptance(order_id)
    assert acceptance is not None and acceptance[0] == LEGAL_UPDATED == "2026-10-09"
    opened = visitor.get(f"/audits/{audit_id}?token={token}&lang=es").text
    assert "class='lockbox'" not in opened


def test_another_browser_with_the_link_gets_the_usual_box(tmp_path: Path) -> None:
    app, _store, _ = _app(tmp_path)
    audit_id, token = _location(_upload(_browser(app), 42))
    page = _browser(app, "198.51.100.9").get(f"/audits/{audit_id}?token={token}").text
    assert _escaped(account_pages.COPY["es"]["anon_box"]) in page
    assert _escaped(paid_offer.words("es")["anon_signup"]) not in page
    assert _promises(_visible(page), "es") == []


# -- 3. No way to a free full report ------------------------------------------------------
def test_no_path_grants_a_free_full_report(tmp_path: Path) -> None:
    """The first upload, a confirmed e-mail (before or after the upload), an invite
    and a card check: every report stays locked. An access code still opens one."""
    app, store, _ = _app(tmp_path, access_codes=True, contact_url="https://wa.me/000")
    inviter = _browser(app, "203.0.113.20")
    assert _signup(inviter, "anfitrion@example.com").status_code == 303
    host = store.find_account("anfitrion@example.com")
    assert host is not None
    _confirm(app, store, host.id)
    # No invite link: the reward needs a free first report.
    page = inviter.get(account_pages.path("account", "es")).text
    assert "id='invite-link'" not in page
    token = store.invite_token(host.id, at=datetime.now(UTC))

    # Uploads before confirming, then the confirmation: nothing opens.
    guest = _browser(app, "203.0.113.21")
    signup = guest.get("/registro", params={"invita": token}).text
    assert _escaped(account_pages.COPY["es"]["invited_banner"]) not in signup
    made = guest.post(
        "/registro",
        data={"email": "invitada@example.com", "password": PASSWORD, "csrf": _csrf(signup)},
        follow_redirects=False,
    )
    assert made.status_code == 303
    friend = store.find_account("invitada@example.com")
    assert friend is not None
    first = _upload(guest, 51)
    assert first.status_code == 303 and "acct=" not in first.headers["location"]
    first_id, first_token = _location(first)
    assert not store.get_audit(first_id).paid
    assert store.welcome_pending_for(friend.id, since=datetime(2000, 1, 1, tzinfo=UTC)) == []
    _confirm(app, store, friend.id)
    assert not store.get_audit(first_id).paid
    # And after confirming, the next upload is a preview too.
    second = _upload(guest, 52)
    second_id, _ = _location(second)
    assert not store.get_audit(second_id).paid
    assert not store.welcome_used(friend.id)
    now = datetime.now(UTC)
    assert store.account_credits(host.id, now) == 0
    assert store.invite_summary(host.id, now).credited == 0
    # The report offers no card check for a free report, and no notice promises one.
    report = guest.get(f"/audits/{first_id}?token={first_token}&lang=es").text
    assert _escaped(account_pages.COPY["es"]["card_offer"]) not in report
    assert _promises(_visible(report), "es") == []

    # Asked for anyway, the card check is never opened.
    def no_card_check(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a card check was opened under the paid offer")

    app.state.card_check_factory = no_card_check
    card = guest.post(
        f"/audits/{first_id}/tarjeta?token={first_token}&lang=es",
        data={"csrf": _csrf(guest.get(account_pages.path("account", "es")).text)},
        follow_redirects=False,
    )
    assert card.status_code == 303 and "checkout.stripe" not in card.headers["location"]
    # An access code works as always.
    code, _ = store.create_access_code(credits=1, note="test", at=now)
    redeemed = guest.post(
        f"/audits/{first_id}/redeem?token={first_token}&lang=es",
        data={"code": code},
        follow_redirects=False,
    )
    assert redeemed.status_code == 303
    assert store.get_audit(first_id).paid


def test_the_account_first_page_names_the_price_not_a_free_report(tmp_path: Path) -> None:
    """An upload the free tier does not cover without an account (here a working
    code, which still asks for the account) answers the paid offer's page."""
    app, store, settings = _app(tmp_path, access_codes=True)
    code, _ = store.create_access_code(credits=1, note="test", at=datetime.now(UTC))
    sent = _browser(app).post(
        "/audits",
        files={"equity": ("e.csv", csv_bytes(positive_drift(500, seed=71)), "text/csv")},
        data={"consent": "on", "access_code": code},
        follow_redirects=False,
    )
    assert sent.status_code == 401
    offer = paid_offer.offer_of(settings)
    for locale in LOCALES:
        page = (
            sent.text
            if locale == "es"
            else account_pages.gate_page(
                locale=locale, reason="signin", limit=FREE_PREVIEWS_PER_MONTH, offer=offer
            )
        )
        title, lead = paid_offer.gate_text(locale, offer, FREE_PREVIEWS_PER_MONTH)
        assert _escaped(title) in page and _escaped(lead) in page
        assert "USD 29" in lead and REFUND_WORDS[locale][0] in lead
        assert _promises(_visible(page), locale) == []
        assert find_claims(title) == [] and find_claims(lead) == []


# -- 4. Every public page, the forms and both reports --------------------------------------
def _pages(app: Any, store: Store) -> dict[str, list[tuple[str, str]]]:
    """Every sitemap page plus sign-up, the upload form, a preview made without an
    account, a locked report on an account, "My account" before and after
    confirming the e-mail and the payment refused before it ("checkout <locale>"),
    by language: (path, html)."""
    reader = _browser(app, "198.51.100.30")
    out: dict[str, list[tuple[str, str]]] = {locale: [] for locale in LOCALES}
    for paths in PUBLIC_PAGES:
        for locale, path in paths.items():
            answer = reader.get(path)
            assert answer.status_code == 200, path
            out[locale].append((path, answer.text))
    for locale in LOCALES:
        for path in (SIGNUP[locale], f"{SIGNUP[locale]}?next={FORMS[locale]}", FORMS[locale]):
            answer = reader.get(path)
            assert answer.status_code == 200, path
            out[locale].append((path, answer.text))
    anon = _browser(app, "198.51.100.31")
    anon_id, anon_token = _location(_upload(anon, 61))
    owner = _browser(app, "198.51.100.32")
    assert _signup(owner, "duena@example.com").status_code == 303
    mine_id, mine_token = _location(_upload(owner, 62))
    assert not store.get_audit(mine_id).paid
    for locale in LOCALES:
        for client, audit_id, token in ((anon, anon_id, anon_token), (owner, mine_id, mine_token)):
            path = f"/audits/{audit_id}?token={token}&lang={locale}"
            answer = client.get(path)
            assert answer.status_code == 200, path
            out[locale].append((path, answer.text))
    for locale in LOCALES:
        path = account_pages.path("account", locale)
        answer = owner.get(path)
        assert answer.status_code == 200, path
        out[locale].append((path, answer.text))
        refused = owner.post(
            f"/audits/{mine_id}/checkout?token={mine_token}&lang={locale}",
            data={"plan": "single", "billing_country": "MX", "final_sale": "yes"},
            follow_redirects=False,
        )
        assert refused.status_code == 403, refused.text[:300]
        out[locale].append((f"checkout {locale}", refused.text))
    duena = store.find_account("duena@example.com")
    assert duena is not None
    _confirm(app, store, duena.id)
    for locale in LOCALES:
        path = f"{account_pages.path('account', locale)}?done=email_verified"
        answer = owner.get(path)
        assert answer.status_code == 200, path
        out[locale].append((path, answer.text))
    return out


def test_no_page_promises_a_free_full_report(tmp_path: Path) -> None:
    """Every page in es/en/pt under the paid offer, "My account" and the payment
    refused before confirming the e-mail included. The privacy policy and "My
    account" still say what the free first report kept for the accounts that had
    it (its hashes stay), only in the past: never as an offer (:func:`_offered`)."""
    app, store, settings = _app(tmp_path)
    past = {paths["privacy"] for paths in LEGAL_PATHS.values()}
    for locale in LOCALES:
        account = account_pages.path("account", locale)
        past |= {account, f"{account}?done=email_verified"}
    offer = paid_offer.offer_of(settings)
    for locale, pages in _pages(app, store).items():
        for path, page in pages:
            text = _visible(page)
            if path in past:
                assert _offered(text, locale) == [], (path, _offered(text, locale))
            else:
                assert _promises(text, locale) == [], (path, _promises(text, locale))
        # The upload form and sign-up say the paid offer itself.
        form = dict(pages)[FORMS[locale]]
        assert _escaped(paid_offer.paid_text(locale, offer)) in form
        signup = dict(pages)[f"{SIGNUP[locale]}?next={FORMS[locale]}"]
        assert _escaped(paid_offer.next_report_text(locale, offer)) in signup
        assert _escaped(paid_offer.signup_lead(locale, offer, FREE_PREVIEWS_PER_MONTH)) in signup
        # "My account" and the refused payment say what confirming the e-mail does now.
        copy = account_pages.COPY[locale]
        account = account_pages.path("account", locale)
        before = dict(pages)[account]
        after = dict(pages)[f"{account}?done=email_verified"]
        refused = dict(pages)[f"checkout {locale}"]
        assert _escaped(copy["email_unverified_status_paid"]) in before
        assert _escaped(copy["email_unverified_status"]) not in before
        assert _escaped(copy["email_verified_paid"]) in after
        assert _escaped(copy["email_verified"]) not in after
        assert _escaped(copy["email_checkout_required_paid"]) in refused
        assert _escaped(copy["email_checkout_required"]) not in refused
        stores = copy["stores_paid"].format(days=settings.retention_days)
        for item in stores.split("|"):
            assert _escaped(item) in before, item
        assert _escaped(copy["stores"].format(days=settings.retention_days)) not in before


def test_every_rewritten_sentence_still_exists_with_the_free_first_report(
    tmp_path: Path,
) -> None:
    """With the free first report on, each pattern ``paid_offer`` rewrites still
    finds its sentence somewhere: a reworded promise cannot slip past the paid offer."""
    app, store, _ = _app(tmp_path, welcome_full_report=True)
    for locale, pages in _pages(app, store).items():
        text = " ".join(_visible(page) for _, page in pages)
        for pattern, _ in paid_offer.PROMISES[locale]:
            assert re.search(pattern, text), (locale, pattern)


# -- 5. The refund, in the same words everywhere -------------------------------------------
@pytest.mark.parametrize("locale", LOCALES)
def test_the_refund_shows_on_prices_questions_terms_and_the_boxes(
    tmp_path: Path, locale: str
) -> None:
    app, _store, settings = _app(tmp_path, access_codes=True)
    client = _browser(app)
    refund = paid_offer.refund_text(locale)
    pack = paid_offer.pack_refund_text(locale)
    question, answer = paid_offer.refund_question(locale, "soporte@example.com")
    days, terms = REFUND_WORDS[locale]
    for text in (refund, answer, LABELS_FOR[locale]["final_sale"]):
        assert days in text, text
    assert days.split()[0] in pack

    prices = client.get(PRICING_PATH[locale]).text
    assert f"<p class='plan-note plan-refund'>{_escaped(refund)}</p>" in prices
    assert f"<p class='plan-note plan-refund'>{_escaped(pack)}</p>" in prices
    faq = client.get(FAQ_PATH[locale]).text
    assert f"<summary>{_escaped(question)}</summary>" in faq
    assert _escaped(answer) in faq
    home = client.get(LANDING_PATHS[locale]).text
    assert f"<summary>{_escaped(question)}</summary>" in home
    assert _escaped(refund) in home

    sold = terms_text(_context(settings, locale), locale)
    price_lines = dict(sold.sections)[PRICE_SECTION[locale]]
    refund_line = next(line for line in price_lines if days in line)
    assert "soporte@example.com" in refund_line and "Stripe" in refund_line
    # A single credit bought from "My account" (whose box names the 7 days) is covered.
    assert SINGLE_CREDIT[locale] in refund_line and SINGLE_CREDIT[locale] in answer
    assert REFUND_ENDS[locale] in refund_line
    assert not any(FINAL_SALE[locale] in line for line in price_lines)

    report = LABELS_FOR[locale]["final_sale"]
    assert days in report and terms in report
    buy = account_pages.COPY[locale]["buy_final_sale"]
    assert days in buy and terms in buy
    assert days in account_pages.COPY[locale]["buy_final_sale_note"]
    for text in (refund, pack, answer, question, report, buy, refund_line):
        assert find_claims(text) == [], text


LABELS_FOR: dict[str, dict[str, str]] = {locale: LABELS[locale] for locale in LOCALES}
SINGLE_CREDIT = {"es": "crédito suelto", "en": "single credit", "pt": "crédito avulso"}
PRICE_SECTION = {"es": "Precio y pago", "en": "Price and payment", "pt": "Preço e pagamento"}
REFUND_ENDS = {
    "es": "Esto no limita los derechos que te conceda la ley aplicable.",
    "en": "This does not limit your rights under applicable law.",
    "pt": "Isso não limita os direitos previstos na lei aplicável.",
}
FINAL_SALE = {
    "es": "Todas las ventas son finales",
    "en": "All sales are final",
    "pt": "Todas as vendas são finais",
}


def _context(settings: AuditSettings, locale: str, **extra: object) -> LegalContext:
    values: dict[str, object] = {
        "operator_contact": settings.operator_contact,
        "free_mode": settings.free_mode,
        "price_usd": settings.price_usd,
        "card_payments": settings.card_public,
        "access_codes": settings.access_codes_enabled,
        "pack_price_usd": settings.pack_price_usd,
        "email_verification_required": settings.email_verification_required,
        "email_delivery_ready": settings.email_delivery_ready,
        "welcome_full_report": settings.welcome_full_report,
        "anon_preview": settings.anon_preview,
    }
    values.update(extra)
    return LegalContext(**values)  # type: ignore[arg-type]


# -- 6. The terms and the privacy policy ----------------------------------------------------
ACCOUNT_SECTION = {"es": "Tu cuenta", "en": "Your account", "pt": "Sua conta"}


@pytest.mark.parametrize("locale", LOCALES)
def test_the_terms_say_what_the_code_does_in_each_offer(tmp_path: Path, locale: str) -> None:
    settings = _settings(tmp_path)
    for welcome in (True, False):
        for anon in (True, False):
            ctx = _context(settings, locale, welcome_full_report=welcome, anon_preview=anon)
            text = terms_text(ctx, locale)
            sections = dict(text.sections)
            account = next(v for k, v in sections.items() if k.startswith(ACCOUNT_SECTION[locale]))
            line = account[0]
            assert str(FREE_PREVIEWS_PER_MONTH) in line
            if anon:
                assert f" {ANON_PREVIEWS_PER_NETWORK_PER_DAY} " in line
                assert f"({ANON_PREVIEWS_PER_IPV4_PER_DAY} " in line
            else:
                assert f"({ANON_PREVIEWS_PER_IPV4_PER_DAY} " not in line
            whole = " ".join(" ".join(lines) for _, lines in text.sections)
            if welcome:
                assert _promises(line, locale)
            else:
                assert _promises(whole, locale) == [], _promises(whole, locale)
            assert find_claims(whole) == []
            assert text.updated == "2026-10-09"
            privacy = privacy_text(ctx, locale)
            assert find_claims(" ".join(" ".join(lines) for _, lines in privacy.sections)) == []


ANON_PRIVACY = {
    "es": ("Si subes un archivo sin cuenta:", "para abrirlo como informe gratis"),
    "en": ("If you upload a file without an account:", "to open it as the free report"),
    "pt": ("Se você enviar um arquivo sem conta:", "para abri-lo como relatório grátis"),
}


@pytest.mark.parametrize("locale", LOCALES)
def test_the_privacy_policy_says_what_an_upload_without_an_account_keeps(
    tmp_path: Path, locale: str
) -> None:
    settings = _settings(tmp_path)
    start, welcome_words = ANON_PRIVACY[locale]

    def kept(**extra: object) -> list[str]:
        policy = privacy_text(_context(settings, locale, **extra), locale)
        return [line for _, lines in policy.sections for line in lines if line.startswith(start)]

    paid = kept()
    assert len(paid) == 1
    assert "rigor_ref" in paid[0] and "30" in paid[0]
    assert welcome_words not in paid[0] and "SHA-256" not in paid[0]
    welcome = kept(welcome_full_report=True)
    assert len(welcome) == 1 and welcome_words in welcome[0] and "SHA-256" in welcome[0]
    assert kept(anon_preview=False) == []
    assert find_claims(paid[0]) == [] and find_claims(welcome[0]) == []
    # The day's network count is not deleted with the report: only by the purge.
    for line in (paid[0], welcome[0]):
        assert NETWORK_HASH[locale] in line, line


NETWORK_HASH = {
    "es": "el hash de la red, a los 30 días",
    "en": "the network hash, after 30 days",
    "pt": "o hash da rede, após 30 dias",
}
INVITES_PAST = {
    "es": "cuando había invitaciones",
    "en": "when there were invites",
    "pt": "quando havia indicações",
}
INVITES_NOW = {
    "es": "Para «Invita a un colega»",
    "en": "For 'Invite a colleague'",
    "pt": "Para 'Indique",
}


@pytest.mark.parametrize("locale", LOCALES)
def test_the_privacy_policy_says_the_free_report_only_in_the_past(
    tmp_path: Path, locale: str
) -> None:
    """Under the paid offer nothing takes the free report's marks, opens a card
    check or records an invite: the policy says what they kept only of the accounts
    that had them, and the browser mark by what it does now."""
    settings = _settings(tmp_path)
    for card in (True, False):
        for anon in (True, False):
            ctx = _context(settings, locale, card_payments=card, anon_preview=anon)
            lines = [line for _, part in privacy_text(ctx, locale).sections for line in part]
            whole = " ".join(lines)
            assert _offered(whole, locale) == [], _offered(whole, locale)
            # The free report, its retention and, with card payments, the card check.
            assert sum(LEGACY[locale] in line for line in lines) == (3 if card else 2)
            assert INVITES_PAST[locale] in whole and INVITES_NOW[locale] not in whole
            use = legal._device_cookie_use(ctx, locale)
            assert use in whole and ("account" in use or "conta" in use or "cuenta" in use)
            assert ("sin cuenta" in use or "without an account" in use or "sem conta" in use) == (
                anon
            )
            assert all(find_claims(line) == [] for line in lines)
            welcome = privacy_text(replace(ctx, welcome_full_report=True), locale)
            said = " ".join(" ".join(part) for _, part in welcome.sections)
            assert LEGACY[locale] not in said and INVITES_NOW[locale] in said
            assert legal._device_cookie_use(replace(ctx, welcome_full_report=True), locale) in said


# -- 7. The words themselves ----------------------------------------------------------------
def test_every_new_text_passes_the_guard_and_names_no_endorsement() -> None:
    forbidden = re.compile(
        r"verificad|certificad|aprobad|garantiz|rentable|verified|certified|approved|"
        r"guarantee|profitable|garant|lucrativ",
        re.I,
    )
    offers = (
        paid_offer.Offer(kind="paid", price_usd=29.0, pack_price_usd=69.0, anon_preview=True),
        paid_offer.Offer(kind="paid", price_usd=29.0, pack_price_usd=69.0),
    )
    texts: list[str] = []
    for locale in LOCALES:
        copy = paid_offer.words(locale)
        texts += [value for value in copy.values() if isinstance(value, str)]
        texts += [step for key in ("how_anon", "how_account") for step in copy[key]]
        for offer in offers:
            texts += [
                paid_offer.paid_text(locale, offer),
                paid_offer.anon_box_text(locale, offer),
                paid_offer.next_report_text(locale, offer),
                paid_offer.signup_lead(locale, offer, FREE_PREVIEWS_PER_MONTH),
                *paid_offer.how_steps(locale, offer),
                *paid_offer.price_question(locale, offer),
                *paid_offer.refund_question(locale),
            ]
        texts += [
            account_pages.COPY[locale][key]
            for key in (
                *ACCOUNT_PAID_KEYS,
                "buy_final_sale",
                "buy_final_sale_note",
                "buy_final_sale_needed",
            )
        ]
        texts += account_pages.COPY[locale]["stores_paid"].format(days=30).split("|")
        texts += [LABELS_FOR[locale][key] for key in ("final_sale", "pay_secure")]
    for text in texts:
        assert find_claims(text) == [], text
        assert not forbidden.search(text), text
    # The same promise in the three languages: preview, price, refund.
    for locale in LOCALES:
        text = paid_offer.paid_text(locale, offers[0])
        assert "USD 29" in text and "7" in text and "A" in text and "D" in text
    # One name for the red flags in each language, the "create your account" page too.
    for locale, other in (("es", "señales de alerta"), ("pt", "bandeiras vermelhas")):
        copy = paid_offer.words(locale)
        said = [value for value in copy.values() if isinstance(value, str)]
        said += paid_offer.gate_text(locale, offers[0], FREE_PREVIEWS_PER_MONTH)
        assert not any(other in text for text in said), locale


@pytest.mark.parametrize("locale", LOCALES)
def test_my_account_words_under_the_paid_offer(locale: str) -> None:
    """The e-mail card, the notices and "What we keep" of the paid offer: confirming
    unlocks the purchases only, and the free first report is said in the past."""
    copy = account_pages.COPY[locale]
    for key in ACCOUNT_PAID_KEYS:
        assert _promises(copy[key], locale) == [], key
        assert find_claims(copy[key]) == [], key
    # The notice after sign-up says the e-mail must be confirmed to pay.
    assert {"es": "para pagar", "en": "to pay", "pt": "para pagar"}[locale] in copy[
        "welcome_confirm_paid"
    ]
    items, paid = copy["stores"].split("|"), copy["stores_paid"].split("|")
    assert len(items) == len(paid)
    assert sum(old != new for old, new in zip(items, paid, strict=True)) == 3
    stores = copy["stores_paid"].format(days=30)
    assert _offered(stores, locale) == [] and LEGACY[locale] in stores
    assert _promises(copy["stores"].format(days=30), locale)  # the welcome list, as it was

    def card(**extra: Any) -> str:
        values: dict[str, Any] = {
            "verified": False,
            "pending": "",
            "delivery_ready": False,
            "verification_required": True,
        }
        values.update(extra)
        return account_pages._email_status_card(copy, locale, "csrf", **values)

    paid_card = card(paid=True)
    for key in ("email_unverified_status_paid", "email_delivery_unavailable_paid"):
        assert _escaped(copy[key]) in paid_card, key
    assert _promises(_visible(paid_card), locale) == []
    welcome_card = card()
    for key in ("email_unverified_status", "email_delivery_unavailable"):
        assert _escaped(copy[key]) in welcome_card, key


def test_the_questions_page_rewrites_the_retention_answer_in_agreement(
    tmp_path: Path,
) -> None:
    app, _store, _ = _app(tmp_path)
    client = _browser(app)
    said = {
        "es": "Las pagadas se conservan hasta que las borres",
        "en": "Paid audits are kept until you delete them",
        "pt": "As pagas ficam até você excluí-las",
    }
    wrong = {"es": "se conservan hasta que los borres", "pt": "ficam até você excluí-los"}
    for locale in LOCALES:
        text = _visible(client.get(FAQ_PATH[locale]).text)
        assert said[locale] in text, locale
        if locale in wrong:
            assert wrong[locale] not in text, locale


def test_the_price_comes_from_the_settings(tmp_path: Path) -> None:
    settings = _settings(tmp_path, price_usd_cents=3500)
    assert "USD 35" in start_cta(settings, "es")
    assert "USD 29" not in start_cta(settings, "es")
    offer = paid_offer.offer_of(settings)
    assert "USD 35" in paid_offer.anon_box_text("pt", offer)


@pytest.mark.parametrize(
    "acct", ["welcome", "preview_network", "preview_device", "preview_file", "preview_unverified"]
)
def test_old_free_report_notices_stay_quiet_under_the_paid_offer(tmp_path: Path, acct: str) -> None:
    """No paid-offer flow sends these, but an old link may carry them: the report
    then shows no notice that promises or explains a free full report."""
    app, store, _ = _app(tmp_path)
    visitor = _browser(app)
    audit_id, token = _location(_upload(visitor, 77))
    page = visitor.get(f"/audits/{audit_id}", params={"token": token, "lang": "es", "acct": acct})
    assert page.status_code == 200
    text = _visible(page.text)
    for key in ("welcome_notice", "welcome_refused_network", "welcome_refused_device"):
        assert _escaped(account_pages.COPY["es"][key].split("{")[0][:40]) not in page.text, key
    assert _promises(text, "es") == []
