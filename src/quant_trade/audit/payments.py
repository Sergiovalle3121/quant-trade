"""Card payments through Stripe Checkout: one audit, or a pack of three.

The buyer pays on Stripe's page and comes back to the report. The payment
is confirmed twice, and either path is enough on its own:

* the signed ``checkout.session.completed`` webhook, which arrives even when
  the buyer closes the tab before coming back;
* the return URL, which carries the Checkout session id; the service asks
  Stripe for that session before showing anything as paid.

When the report is on a customer account, a pack's code goes on that
account too, so its credits show in "My reports".

Both paths call :func:`fulfil`, which is idempotent.

A pack unlocks the report it was bought from and adds an access code with
the remaining credits. The code is derived from the Checkout session id
and the webhook secret with HMAC, so the service stores only its hash (as
for any access code) and can still show it to the buyer on their own
report, which only the report token opens. Nothing is charged by this
module: Stripe charges the card; this module only reads what Stripe says.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from quant_trade.audit.seo import BRAND
from quant_trade.audit.settings import PACK_CREDITS, AuditSettings
from quant_trade.audit.store import (
    ACCOUNT_ORDER_PREFIX,
    CODE_ALPHABET,
    CODE_GROUP_LENGTH,
    CODE_GROUPS,
    CODE_PREFIX,
    Store,
    account_order_ref,
)

logger = logging.getLogger("quant_trade.audit.payments")

PLAN_SINGLE = "single"
PLAN_PACK = "pack"
PLANS = (PLAN_SINGLE, PLAN_PACK)
#: The only Checkout status that unlocks anything: a 100%-off session reads
#: ``no_payment_required`` and is refused (access codes cover free reports).
PAID_STATUSES = ("paid",)
#: Metadata only Rigor's own sessions and Payment Links carry. Stripe copies a
#: link's metadata onto its sessions, so a paid session from any other link or
#: app on the same Stripe account never unlocks a report.
APP_KEY = "app"
APP_MARKER = "rigor"
CURRENCY = "usd"
#: Stripe lookups from the return page, per address and per audit per hour.
#: The signed webhook unlocks a report without any lookup, so a limit here
#: only protects the account's API rate from a script looping the return URL.
CARD_LOOKUPS_PER_HOUR = 10
#: Stripe Checkout session ids start with this; code-paid audits carry ``code:``.
SESSION_PREFIX = "cs_"
#: The lowest advertised price before the order ledger existed. Historical
#: sessions have no frozen order id, so their paid amount is checked against
#: this floor when today's configured price has increased.
LEGACY_PRICE_FLOOR_CENTS = {PLAN_SINGLE: 2900, PLAN_PACK: 6900}

PRODUCT_NAMES = {
    "es": {
        PLAN_SINGLE: f"{BRAND} · informe completo",
        PLAN_PACK: f"{BRAND} · paquete de {PACK_CREDITS} informes",
    },
    "en": {
        PLAN_SINGLE: f"{BRAND} · full report",
        PLAN_PACK: f"{BRAND} · pack of {PACK_CREDITS} reports",
    },
    "pt": {
        PLAN_SINGLE: f"{BRAND} · relatório completo",
        PLAN_PACK: f"{BRAND} · pacote de {PACK_CREDITS} relatórios",
    },
}


def _payment_locales(locale: str) -> tuple[str, str]:
    """Return the app language and the corresponding Stripe locale."""
    lang = locale if locale in PRODUCT_NAMES else "es"
    return lang, "pt-BR" if lang == "pt" else lang


def card_mode(settings: AuditSettings) -> str:
    """``off``, ``test`` or ``live``: read from a key or link prefix, never a secret."""
    if not (settings.stripe_enabled or settings.links_enabled):
        return "off"
    return "test" if settings.card_test_mode else "live"


def card_via(settings: AuditSettings) -> str:
    """How a card payment starts: a Checkout session the service creates, or a Payment Link."""
    if settings.stripe_enabled:
        return "checkout"
    return "links" if settings.links_enabled else "off"


def payment_link_urls(settings: AuditSettings, audit_id: str, locale: str) -> tuple[str, str]:
    """The Payment Links for one audit and for the pack, tagged with the audit id.

    ``client_reference_id`` is how the webhook knows which audit was paid;
    the pack link is empty when the pack is not on sale or has no link.
    """
    _, stripe_locale = _payment_locales(locale)

    def tagged(url: str) -> str:
        if not url:
            return ""
        parts = urlsplit(url)
        query = [
            pair
            for pair in parse_qsl(parts.query, keep_blank_values=True)
            if pair[0] not in ("client_reference_id", "locale")
        ]
        query.extend((("client_reference_id", audit_id), ("locale", stripe_locale)))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))

    single = tagged(settings.stripe_link_single)
    pack = (
        tagged(settings.stripe_link_pack)
        if settings.stripe_link_pack and settings.pack_price_usd
        else ""
    )
    return single, pack


def pack_code(secret: str, session_id: str) -> str:
    """The pack's access code, ``AUD-XXXX-XXXX-XXXX``, derived from the session.

    Only someone holding the webhook secret can compute it, and the same
    session always gives the same code, so a second confirmation of the
    same payment never creates a second code.
    """
    return _session_code(secret, b"pack:", session_id)


def credit_code(secret: str, session_id: str) -> str:
    """The code that carries credits bought from "My account", like :func:`pack_code`.

    It is linked to the buyer's account, so the buyer never needs to see it.
    """
    return _session_code(secret, b"credits:", session_id)


def _session_code(secret: str, label: bytes, session_id: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), label + session_id.encode("utf-8"), hashlib.sha256
    ).digest()
    chars = [CODE_ALPHABET[byte % len(CODE_ALPHABET)] for byte in digest]
    groups = [
        "".join(chars[i * CODE_GROUP_LENGTH : (i + 1) * CODE_GROUP_LENGTH])
        for i in range(CODE_GROUPS)
    ]
    return "-".join([CODE_PREFIX, *groups])


def plan_price_cents(settings: AuditSettings, plan: str) -> int:
    return settings.pack_price_usd_cents if plan == PLAN_PACK else settings.price_usd_cents


def legacy_price_cents(settings: AuditSettings, plan: str) -> int:
    current = plan_price_cents(settings, plan)
    floor = LEGACY_PRICE_FLOOR_CENTS[plan]
    return min(current, floor) if current > 0 else floor


def checkout_params(
    settings: AuditSettings,
    audit_id: str,
    token: str,
    *,
    plan: str,
    locale: str,
    order_id: str = "",
    amount_cents: int | None = None,
) -> dict[str, Any]:
    """The Checkout session Stripe is asked to create; pure, so it is tested."""
    if plan not in PLANS:
        raise ValueError(f"unknown plan {plan!r}")
    lang, stripe_locale = _payment_locales(locale)
    back = f"{settings.base_url}/audits/{audit_id}?token={token}&lang={lang}"
    if plan == PLAN_SINGLE and settings.stripe_price_id and amount_cents is None:
        line: dict[str, Any] = {"price": settings.stripe_price_id, "quantity": 1}
    else:
        line = {
            "price_data": {
                "currency": "usd",
                "unit_amount": amount_cents or plan_price_cents(settings, plan),
                "product_data": {"name": PRODUCT_NAMES[lang][plan]},
            },
            "quantity": 1,
        }
    metadata = {"audit_id": audit_id, "plan": plan, APP_KEY: APP_MARKER}
    if order_id:
        metadata["order_id"] = order_id
    params = {
        "mode": "payment",
        "line_items": [line],
        # Stripe fills in {CHECKOUT_SESSION_ID}; the return page confirms it.
        "success_url": back + "&session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": back + "&pay=cancelled",
        "metadata": metadata,
        "payment_intent_data": {"metadata": metadata},
        "client_reference_id": audit_id,
        "locale": stripe_locale,
    }
    if not settings.card_test_mode and settings.approved_markets:
        params["billing_address_collection"] = "required"
    return params


#: Where "My account" lives in each language; the credit Checkout comes back there.
ACCOUNT_PATHS = {"es": "/cuenta", "en": "/account", "pt": "/pt/conta"}
#: Credits a plan puts on an account: one report, or the pack.
PLAN_CREDITS = {PLAN_SINGLE: 1, PLAN_PACK: PACK_CREDITS}


def account_checkout_params(
    settings: AuditSettings,
    account_id: str,
    *,
    plan: str,
    locale: str,
    order_id: str,
    amount_cents: int,
) -> dict[str, Any]:
    """The Checkout session for credits bought from "My account"; pure, so it is tested.

    The metadata names the account, never a report: the paid session puts
    the credits on that account and unlocks nothing else.
    """
    if plan not in PLANS:
        raise ValueError(f"unknown plan {plan!r}")
    lang, stripe_locale = _payment_locales(locale)
    back = f"{settings.base_url}{ACCOUNT_PATHS[lang]}"
    metadata = {
        "account_id": account_id,
        "plan": plan,
        "order_id": order_id,
        APP_KEY: APP_MARKER,
    }
    return {
        "mode": "payment",
        "line_items": [
            {
                "price_data": {
                    "currency": "usd",
                    "unit_amount": amount_cents,
                    "product_data": {"name": PRODUCT_NAMES[lang][plan]},
                },
                "quantity": 1,
            }
        ],
        "success_url": back + "?done=card_paid",
        "cancel_url": back,
        "metadata": metadata,
        "payment_intent_data": {"metadata": metadata},
        "client_reference_id": account_order_ref(account_id),
        "locale": stripe_locale,
        "billing_address_collection": "required",
    }


def stripe_account_checkout(
    settings: AuditSettings,
    account_id: str,
    *,
    plan: str,
    locale: str,
    order_id: str,
    amount_cents: int,
) -> dict[str, Any]:
    """Create/retrieve the credit Checkout session, the order id as idempotency key."""
    import stripe

    params = account_checkout_params(
        settings,
        account_id,
        plan=plan,
        locale=locale,
        order_id=order_id,
        amount_cents=amount_cents,
    )
    session = stripe.checkout.Session.create(
        api_key=settings.stripe_secret_key,
        idempotency_key=f"rigor-checkout-{order_id}",
        **params,
    )
    return _plain(session)


def _plain(value: Any) -> dict[str, Any]:
    to_dict = getattr(value, "to_dict", None)
    return dict(to_dict() if callable(to_dict) else value)


def stripe_checkout(
    settings: AuditSettings,
    audit_id: str,
    token: str,
    *,
    plan: str,
    locale: str,
    order_id: str = "",
    amount_cents: int | None = None,
) -> dict[str, Any]:
    """Create/retrieve a Checkout session with the persistent order as idempotency key."""
    import stripe

    params = checkout_params(
        settings,
        audit_id,
        token,
        plan=plan,
        locale=locale,
        order_id=order_id,
        amount_cents=amount_cents,
    )
    options = {"api_key": settings.stripe_secret_key}
    if order_id:
        options["idempotency_key"] = f"rigor-checkout-{order_id}"
    session = stripe.checkout.Session.create(**options, **params)
    return _plain(session)


def stripe_session(settings: AuditSettings, session_id: str) -> dict[str, Any]:
    """Ask Stripe for a Checkout session (needs the SDK)."""
    import stripe

    session = stripe.checkout.Session.retrieve(session_id, api_key=settings.stripe_secret_key)
    return _plain(session)


def refusal(
    settings: AuditSettings,
    session: Mapping[str, Any],
    plan: str,
    *,
    expected_cents: int | None = None,
) -> str | None:
    """Why a paid session is not Rigor's own full payment for ``plan``; ``None`` if it is.

    The buyer controls ``client_reference_id`` through the link URL, so the
    amount, the currency and Rigor's marker are what tie a payment to a plan:
    a cheaper link, another app's link or a single-report price never unlock
    a pack or a report.
    """
    if plan not in PLANS:
        return "unknown plan"
    metadata = session.get("metadata") or {}
    if metadata.get(APP_KEY) != APP_MARKER:
        return "no Rigor marker"
    # Since Stripe API 2025-03-31 a session paid in the buyer's own currency
    # (Adaptive Pricing) still reads in USD, with the local amount under
    # ``presentment_details``. Older API versions put the local currency on
    # the session and the USD amount under ``currency_conversion``.
    source = session.get("currency_conversion") or session
    currency = source.get("source_currency") or source.get("currency")
    if str(currency or "").lower() != CURRENCY:
        return "not USD"
    amount = source.get("amount_total")
    if isinstance(amount, bool) or not isinstance(amount, int):
        return "no amount"
    if not amount >= (expected_cents or plan_price_cents(settings, plan)) > 0:
        return "below the plan price"
    return None


def paid_in_full(settings: AuditSettings, session: Mapping[str, Any], plan: str) -> bool:
    """Whether a session is Rigor's own and paid at least the plan's price in USD."""
    return refusal(settings, session, plan) is None


def _safe(value: str) -> str:
    """An id for a log line: no line breaks or odd characters from a URL."""
    return "".join(ch for ch in value[:80] if ch.isalnum() or ch in "_-") or "-"


def fulfil(
    store: Store, settings: AuditSettings, session: Mapping[str, Any], *, at: datetime
) -> str | None:
    """Unlock what a paid Checkout session bought; the audit id, or ``None``.

    Idempotent: the audit flips to paid once, and the pack code is keyed by
    the session, so the webhook and the return page can both call it.
    """
    if session.get("payment_status") not in PAID_STATUSES:
        return None
    session_id = str(session.get("id") or "")
    metadata = session.get("metadata") or {}
    if metadata.get("account_id"):
        return _fulfil_credits(store, settings, session, at=at)
    # A Checkout session this service created names the audit in its
    # metadata; a Payment Link carries it as ``client_reference_id``.
    audit_id = str(metadata.get("audit_id") or session.get("client_reference_id") or "")
    plan = str(metadata.get("plan") or PLAN_SINGLE)
    order_id = str(metadata.get("order_id") or "")
    order = store.get_checkout_order(order_id) if order_id else None
    reason: str | None
    if not session_id.startswith(SESSION_PREFIX) or not audit_id:
        reason = "no Checkout session or no audit id"
    elif session.get("livemode") is not (not settings.card_test_mode):
        reason = "payment mode mismatch"
    # Anyone can pay a test-mode checkout with Stripe's public test card, so
    # a test payment unlocks only an audit listed for testing.
    elif session.get("livemode") is not True and audit_id not in settings.stripe_test_audits:
        reason = "test payment for an audit not listed for testing"
    elif store.get_audit(audit_id) is None:
        reason = "unknown audit"
    elif order_id and order is None:
        reason = "unknown order"
    elif order is not None and (order.audit_id != audit_id or order.plan != plan):
        reason = "order mismatch"
    else:
        reason = refusal(
            settings,
            session,
            plan,
            expected_cents=(
                order.amount_cents
                if order
                else legacy_price_cents(settings, plan)
                if plan in PLANS
                else None
            ),
        )
    if reason is not None:
        # A charged buyer who stays locked must leave a trace; ids only, never
        # an amount, an email or a card detail.
        logger.warning(
            "paid Stripe session %s refused for audit %s: %s",
            _safe(session_id),
            _safe(audit_id),
            reason,
        )
        # Live ones also go to /panel, where the owner looks. Test payments
        # stay in the log: anyone can pay a test link with the public card.
        # Only sessions that are about Rigor: a sale from another app on the
        # same Stripe account names no audit and carries no marker.
        about_rigor = bool(audit_id) or metadata.get(APP_KEY) == APP_MARKER
        if (
            session.get("livemode") is True
            and session_id.startswith(SESSION_PREFIX)
            and about_rigor
        ):
            store.record_refused_payment(
                session_id=_safe(session_id), audit_id=_safe(audit_id), reason=reason, at=at
            )
        return None
    source = session.get("currency_conversion") or session
    amount = source.get("amount_total")
    if not isinstance(amount, int) or isinstance(amount, bool):
        return None  # refusal already checked it; defensive for Mapping implementations
    payment_intent = session.get("payment_intent")
    if isinstance(payment_intent, Mapping):
        payment_intent = payment_intent.get("id")
    declared_country = ""
    billing_country = ""
    if order is not None and session.get("livemode") is True:
        market = store.checkout_market(order.id)
        if market is not None:
            declared_country, _ = market
            customer_details = session.get("customer_details") or {}
            address = (
                customer_details.get("address") or {}
                if isinstance(customer_details, Mapping)
                else {}
            )
            billing_country = (
                str(address.get("country") or "").upper() if isinstance(address, Mapping) else ""
            )
            if (
                billing_country != declared_country
                or billing_country not in settings.approved_markets
            ):
                store.record_market_review(
                    order_id=order.id,
                    session_id=session_id,
                    audit_id=audit_id,
                    billing_country=billing_country,
                    paid_cents=amount,
                    payment_intent_id=str(payment_intent or ""),
                    reason="billing country mismatch or unavailable",
                    at=at,
                    queue_receipt=settings.email_delivery_ready,
                )
                logger.warning(
                    "paid Stripe session %s held for market review on audit %s",
                    _safe(session_id),
                    _safe(audit_id),
                )
                return None
    try:
        outcome = store.settle_card_payment(
            order_id=order_id,
            session_id=session_id,
            audit_id=audit_id,
            plan=plan,
            expected_cents=order.amount_cents if order else amount,
            paid_cents=amount,
            currency=CURRENCY,
            pack_code=(
                pack_code(settings.stripe_webhook_secret, session_id)
                if plan == PLAN_PACK and settings.stripe_webhook_secret
                else ""
            ),
            at=at,
            payment_intent_id=str(payment_intent or ""),
            payment_livemode=session.get("livemode"),
            queue_receipt=settings.email_delivery_ready and session.get("livemode") is True,
        )
    except ValueError:
        logger.warning(
            "paid Stripe session %s disagrees with order %s",
            _safe(session_id),
            _safe(order_id),
        )
        if session.get("livemode") is True:
            store.record_refused_payment(
                session_id=_safe(session_id),
                audit_id=_safe(audit_id),
                reason="order mismatch",
                at=at,
            )
        return None
    if declared_country:
        store.record_checkout_market(
            outcome.order_id,
            billing_country,
            declared_country=declared_country,
            at=at,
        )
    if outcome.status == "duplicate":
        logger.warning(
            "paid Stripe session %s is a second charge for audit %s; manual refund review",
            _safe(session_id),
            _safe(audit_id),
        )
    return audit_id


def _billing_country(session: Mapping[str, Any]) -> str:
    details = session.get("customer_details") or {}
    address = details.get("address") or {} if isinstance(details, Mapping) else {}
    return str(address.get("country") or "").upper() if isinstance(address, Mapping) else ""


def _fulfil_credits(
    store: Store, settings: AuditSettings, session: Mapping[str, Any], *, at: datetime
) -> str | None:
    """Put the credits of a paid "My account" purchase on its account; its reference.

    Stricter than a report purchase: only a live payment of an order frozen
    at Checkout start, for the same account, plan and price, from an
    approved billing country. Anything else stays locked for the owner's
    review in /panel, like any other refused payment.
    """
    session_id = str(session.get("id") or "")
    metadata = session.get("metadata") or {}
    account_id = str(metadata.get("account_id") or "")
    plan = str(metadata.get("plan") or "")
    order_id = str(metadata.get("order_id") or "")
    order = store.get_checkout_order(order_id) if order_id else None
    try:
        reference = account_order_ref(account_id)
    except ValueError:
        reference = ""
    reason: str | None
    if not session_id.startswith(SESSION_PREFIX) or not reference:
        reason = "no Checkout session or no account id"
    # Stripe's public test card must never put credits on an account.
    elif session.get("livemode") is not True or settings.card_test_mode:
        reason = "test payment for account credits"
    elif order is None:
        reason = "unknown order"
    elif order.audit_id != reference or order.plan != plan or plan not in PLAN_CREDITS:
        reason = "order mismatch"
    elif store.checkout_market(order.id) is None:
        reason = "no declared market"
    else:
        reason = refusal(settings, session, plan, expected_cents=order.amount_cents)
    if reason is not None:
        logger.warning(
            "paid Stripe session %s refused for account credits: %s", _safe(session_id), reason
        )
        if session.get("livemode") is True and session_id.startswith(SESSION_PREFIX):
            store.record_refused_payment(
                session_id=_safe(session_id),
                audit_id=(reference or ACCOUNT_ORDER_PREFIX)[:80],
                reason=reason,
                at=at,
            )
        return None
    assert order is not None  # narrowed by the checks above
    source = session.get("currency_conversion") or session
    amount = source.get("amount_total")
    if not isinstance(amount, int) or isinstance(amount, bool):
        return None
    payment_intent = session.get("payment_intent")
    if isinstance(payment_intent, Mapping):
        payment_intent = payment_intent.get("id")
    market = store.checkout_market(order.id)
    declared_country = market[0] if market is not None else ""
    billing_country = _billing_country(session)
    if billing_country != declared_country or billing_country not in settings.approved_markets:
        store.record_market_review(
            order_id=order.id,
            session_id=session_id,
            audit_id=reference,
            billing_country=billing_country,
            paid_cents=amount,
            payment_intent_id=str(payment_intent or ""),
            reason="billing country mismatch or unavailable",
            at=at,
            queue_receipt=settings.email_delivery_ready,
        )
        logger.warning(
            "paid Stripe session %s for account credits held for market review",
            _safe(session_id),
        )
        return None
    try:
        store.settle_credit_purchase(
            order_id=order.id,
            session_id=session_id,
            account_id=account_id,
            plan=plan,
            credits=PLAN_CREDITS[plan],
            paid_cents=amount,
            code=credit_code(settings.stripe_webhook_secret, session_id),
            at=at,
            payment_intent_id=str(payment_intent or ""),
            payment_livemode=True,
            queue_receipt=settings.email_delivery_ready,
        )
    except ValueError:
        logger.warning(
            "paid Stripe session %s disagrees with credit order %s",
            _safe(session_id),
            _safe(order.id),
        )
        store.record_refused_payment(
            session_id=_safe(session_id), audit_id=reference, reason="order mismatch", at=at
        )
        return None
    store.record_checkout_market(
        order.id, billing_country, declared_country=declared_country, at=at
    )
    return reference


def pack_for(store: Store, settings: AuditSettings, session_id: str | None) -> tuple[str, int]:
    """The pack code a card payment created and its credits left, or ``("", 0)``."""
    if not session_id or not session_id.startswith(SESSION_PREFIX):
        return "", 0
    if not settings.stripe_webhook_secret:
        return "", 0
    code = pack_code(settings.stripe_webhook_secret, session_id)
    record = store.get_access_code(code)
    if record is None or record.disabled:
        return "", 0
    return code, record.credits_left


__all__ = [
    "ACCOUNT_PATHS",
    "APP_KEY",
    "CARD_LOOKUPS_PER_HOUR",
    "APP_MARKER",
    "PAID_STATUSES",
    "PLANS",
    "PLAN_PACK",
    "PLAN_SINGLE",
    "PRODUCT_NAMES",
    "card_mode",
    "card_via",
    "payment_link_urls",
    "PLAN_CREDITS",
    "account_checkout_params",
    "checkout_params",
    "credit_code",
    "fulfil",
    "pack_code",
    "pack_for",
    "paid_in_full",
    "plan_price_cents",
    "refusal",
    "stripe_account_checkout",
    "stripe_checkout",
    "stripe_session",
]
