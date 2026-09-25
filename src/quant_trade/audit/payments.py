"""Card payments through Stripe Checkout: one audit, or a pack of three.

The buyer pays on Stripe's page and comes back to the report. The payment
is confirmed twice, and either path is enough on its own:

* the signed ``checkout.session.completed`` webhook, which arrives even when
  the buyer closes the tab before coming back;
* the return URL, which carries the Checkout session id; the service asks
  Stripe for that session before showing anything as paid.

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
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from quant_trade.audit.seo import BRAND
from quant_trade.audit.settings import PACK_CREDITS, AuditSettings
from quant_trade.audit.store import (
    CODE_ALPHABET,
    CODE_GROUP_LENGTH,
    CODE_GROUPS,
    CODE_PREFIX,
    Store,
)

PLAN_SINGLE = "single"
PLAN_PACK = "pack"
PLANS = (PLAN_SINGLE, PLAN_PACK)
#: Checkout session statuses that mean the money is on its way.
PAID_STATUSES = ("paid", "no_payment_required")
#: Stripe Checkout session ids start with this; code-paid audits carry ``code:``.
SESSION_PREFIX = "cs_"

PRODUCT_NAMES = {
    "es": {
        PLAN_SINGLE: f"{BRAND} · informe completo",
        PLAN_PACK: f"{BRAND} · paquete de {PACK_CREDITS} informes",
    },
    "en": {
        PLAN_SINGLE: f"{BRAND} · full report",
        PLAN_PACK: f"{BRAND} · pack of {PACK_CREDITS} reports",
    },
}


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
    lang = "en" if locale == "en" else "es"
    query = f"?client_reference_id={audit_id}&locale={lang}"
    single = settings.stripe_link_single + query if settings.stripe_link_single else ""
    pack = (
        settings.stripe_link_pack + query
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


def checkout_params(
    settings: AuditSettings, audit_id: str, token: str, *, plan: str, locale: str
) -> dict[str, Any]:
    """The Checkout session Stripe is asked to create; pure, so it is tested."""
    if plan not in PLANS:
        raise ValueError(f"unknown plan {plan!r}")
    lang = "en" if locale == "en" else "es"
    back = f"{settings.base_url}/audits/{audit_id}?token={token}&lang={lang}"
    if plan == PLAN_SINGLE and settings.stripe_price_id:
        line: dict[str, Any] = {"price": settings.stripe_price_id, "quantity": 1}
    else:
        line = {
            "price_data": {
                "currency": "usd",
                "unit_amount": plan_price_cents(settings, plan),
                "product_data": {"name": PRODUCT_NAMES[lang][plan]},
            },
            "quantity": 1,
        }
    metadata = {"audit_id": audit_id, "plan": plan}
    return {
        "mode": "payment",
        "line_items": [line],
        # Stripe fills in {CHECKOUT_SESSION_ID}; the return page confirms it.
        "success_url": back + "&session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": back + "&pay=cancelled",
        "metadata": metadata,
        "payment_intent_data": {"metadata": metadata},
        "client_reference_id": audit_id,
        "locale": lang,
    }


def _plain(value: Any) -> dict[str, Any]:
    to_dict = getattr(value, "to_dict", None)
    return dict(to_dict() if callable(to_dict) else value)


def stripe_checkout(
    settings: AuditSettings, audit_id: str, token: str, *, plan: str, locale: str
) -> str:
    """Create a Stripe Checkout session and return its URL (needs the SDK)."""
    import stripe

    params = checkout_params(settings, audit_id, token, plan=plan, locale=locale)
    session = stripe.checkout.Session.create(api_key=settings.stripe_secret_key, **params)
    return str(session.url)


def stripe_session(settings: AuditSettings, session_id: str) -> dict[str, Any]:
    """Ask Stripe for a Checkout session (needs the SDK)."""
    import stripe

    session = stripe.checkout.Session.retrieve(session_id, api_key=settings.stripe_secret_key)
    return _plain(session)


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
    if not session_id.startswith(SESSION_PREFIX) or not audit_id:
        return None
    # Anyone can pay a test-mode checkout with Stripe's public test card, so
    # a test payment unlocks only an audit listed for testing.
    if session.get("livemode") is not True and audit_id not in settings.stripe_test_audits:
        return None
    if store.get_audit(audit_id) is None:
        return None
    store.mark_paid(audit_id, stripe_session_id=session_id, at=at)
    if plan == PLAN_PACK and settings.stripe_webhook_secret:
        store.ensure_access_code(
            pack_code(settings.stripe_webhook_secret, session_id),
            credits=PACK_CREDITS - 1,
            note=f"Paquete pagado con tarjeta desde el informe {audit_id}",
            at=at,
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
    "plan_price_cents",
    "stripe_checkout",
    "stripe_session",
]
