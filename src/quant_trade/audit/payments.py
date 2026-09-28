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
    CODE_ALPHABET,
    CODE_GROUP_LENGTH,
    CODE_GROUPS,
    CODE_PREFIX,
    Store,
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
    digest = hmac.new(
        secret.encode("utf-8"), b"pack:" + session_id.encode("utf-8"), hashlib.sha256
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
    return {
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
    if outcome.status == "duplicate":
        logger.warning(
            "paid Stripe session %s is a second charge for audit %s; manual refund review",
            _safe(session_id),
            _safe(audit_id),
        )
    return audit_id


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
    "checkout_params",
    "fulfil",
    "pack_code",
    "pack_for",
    "paid_in_full",
    "plan_price_cents",
    "refusal",
    "stripe_checkout",
    "stripe_session",
]
