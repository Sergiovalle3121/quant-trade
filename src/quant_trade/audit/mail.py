"""Durable account and purchase email delivery.

The outbox stores a random message id, recipient, purpose and delivery state.
Challenge URL tokens are derived from the id and a deployment HMAC secret
only while composing. Purchase messages contain no token. Delivery is at
least once: a crash after SMTP acceptance can resend the same Message-ID,
while the confirmation itself is consumed only once.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import smtplib
import ssl
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any

from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import Store

logger = logging.getLogger("quant_trade.audit.mail")
TOKEN_RE = re.compile(r"^([0-9a-f]{32})\.([A-Za-z0-9_-]{43})$")
MAIL_POLL_SECONDS = 10

PATHS = {
    "es": {"verify": "/confirmar-correo", "change": "/confirmar-correo", "reset": "/restablecer"},
    "en": {"verify": "/confirm-email", "change": "/confirm-email", "reset": "/reset"},
    "pt": {
        "verify": "/pt/confirmar-email",
        "change": "/pt/confirmar-email",
        "reset": "/pt/redefinir",
    },
}
WORDS = {
    "es": {
        "verify": (
            "Confirma tu correo en Rigor",
            "Confirma que este correo es tuyo abriendo el enlace:",
            "Este enlace caduca en 24 horas.",
        ),
        "change": (
            "Confirma tu nuevo correo en Rigor",
            "Confirma el cambio de correo abriendo el enlace:",
            "Este enlace caduca en 24 horas.",
        ),
        "reset": (
            "Restablece tu contraseña de Rigor",
            "Si pediste restablecer tu contraseña, abre el enlace:",
            "Este enlace caduca en una hora. Si no lo pediste, ignora este mensaje.",
        ),
    },
    "en": {
        "verify": (
            "Confirm your Rigor email",
            "Confirm that this email belongs to you by opening:",
            "This link expires in 24 hours.",
        ),
        "change": (
            "Confirm your new Rigor email",
            "Confirm your email change by opening:",
            "This link expires in 24 hours.",
        ),
        "reset": (
            "Reset your Rigor password",
            "If you requested a password reset, open:",
            "This link expires in one hour. If you did not request it, ignore this message.",
        ),
    },
    "pt": {
        "verify": (
            "Confirme seu e-mail no Rigor",
            "Confirme que este e-mail é seu abrindo:",
            "Este link expira em 24 horas.",
        ),
        "change": (
            "Confirme seu novo e-mail no Rigor",
            "Confirme a mudança de e-mail abrindo:",
            "Este link expira em 24 horas.",
        ),
        "reset": (
            "Redefina sua senha do Rigor",
            "Se você pediu a redefinição da senha, abra:",
            "Este link expira em uma hora. Se não pediu, ignore esta mensagem.",
        ),
    },
}

PURCHASE_WORDS = {
    "es": {
        "purchase": (
            "Compra registrada en Rigor",
            "Registramos tu pago y habilitamos tu compra.",
        ),
        "charge_review": (
            "Cargo adicional en revisión en Rigor",
            "Registramos otro cargo para un informe ya habilitado. "
            "Revisaremos este cargo manualmente; este mensaje no confirma un reembolso.",
        ),
        "single": "Informe individual",
        "pack": "Paquete de tres informes",
        "reference": "Referencia",
        "paid": "Importe cobrado",
    },
    "en": {
        "purchase": (
            "Rigor purchase recorded",
            "We recorded your payment and enabled your purchase.",
        ),
        "charge_review": (
            "Additional Rigor charge under review",
            "We recorded another charge for an already unlocked report. "
            "We will review this charge manually; this message does not confirm a refund.",
        ),
        "single": "Single report",
        "pack": "Three-report pack",
        "reference": "Reference",
        "paid": "Amount charged",
    },
    "pt": {
        "purchase": (
            "Compra registrada no Rigor",
            "Registramos seu pagamento e liberamos sua compra.",
        ),
        "charge_review": (
            "Cobrança adicional em análise no Rigor",
            "Registramos outra cobrança para um relatório já liberado. "
            "Analisaremos esta cobrança manualmente; esta mensagem não confirma um reembolso.",
        ),
        "single": "Relatório individual",
        "pack": "Pacote de três relatórios",
        "reference": "Referência",
        "paid": "Valor cobrado",
    },
}


def token_for(challenge_id: str, secret: str) -> str:
    """Derive an unguessable URL token without storing its clear value."""
    if not re.fullmatch(r"[0-9a-f]{32}", challenge_id) or len(secret) < 32:
        raise ValueError("invalid email challenge or secret")
    digest = hmac.new(
        secret.encode("utf-8"), b"rigor-email-v1:" + challenge_id.encode(), hashlib.sha256
    ).digest()
    return challenge_id + "." + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def challenge_from_token(token: str, secret: str) -> str | None:
    match = TOKEN_RE.fullmatch(token[:100]) if len(token) <= 100 else None
    if match is None or len(secret) < 32:
        return None
    challenge_id = match.group(1)
    return challenge_id if hmac.compare_digest(token_for(challenge_id, secret), token) else None


def compose(
    row: Mapping[str, Any], settings: AuditSettings, store: Store | None = None
) -> EmailMessage:
    locale = str(row["locale"]) if row["locale"] in PATHS else "es"
    kind = str(row["kind"])
    if kind in ("purchase", "charge_review"):
        if store is None:
            raise ValueError("purchase notice needs its order ledger")
        order = store.get_checkout_order(str(row["id"]))
        if order is None or order.status not in ("delivered", "duplicate"):
            raise ValueError("purchase notice has no settled order")
        words = PURCHASE_WORDS[locale]
        subject, lead = words[kind]
        body = (
            f"{lead}\n\n"
            f"{words['reference']}: {order.id}\n"
            f"{words[order.plan]}\n"
            f"{words['paid']}: USD {order.paid_amount_cents / 100:.2f}\n"
        )
    else:
        subject, lead, expiry = WORDS[locale][kind]
        token = token_for(str(row["id"]), settings.email_token_secret)
        url = settings.base_url.rstrip("/") + PATHS[locale][kind] + "?token=" + token
        body = f"{lead}\n\n{url}\n\n{expiry}\n"
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = str(row["email"])
    message["Subject"] = subject
    domain = parseaddr(settings.smtp_from)[1].rsplit("@", 1)[-1]
    message["Message-ID"] = f"<rigor-{row['id']}@{domain}>"
    message.set_content(body)
    return message


def send_smtp(message: EmailMessage, settings: AuditSettings) -> None:
    """Send one message over TLS; callers can inject a fake sender in tests."""
    if not settings.email_delivery_ready:
        raise RuntimeError("email transport is not configured")
    context = ssl.create_default_context()
    if settings.smtp_security == "ssl":
        transport: Any = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=15, context=context
        )
    else:
        transport = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
    with transport as smtp:
        if settings.smtp_security == "starttls":
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def deliver_pending(
    store: Store,
    settings: AuditSettings,
    *,
    sender: Callable[[EmailMessage, AuditSettings], None] = send_smtp,
    limit: int = 10,
    now: datetime | None = None,
) -> int:
    """Attempt due messages once each and persist success or retry state."""
    delivered = 0
    for _ in range(limit):
        current = now or datetime.now(UTC)
        row = store.claim_email_delivery(current)
        if row is None:
            break
        challenge_id = str(row["id"])
        try:
            sender(compose(row, settings, store), settings)
        except Exception:  # noqa: BLE001 - an SMTP failure must not lose the queue
            logger.warning("email delivery failed for outbox id %s", challenge_id)
            store.retry_email_delivery(challenge_id, at=current)
        else:
            store.finish_email_delivery(challenge_id, at=current)
            delivered += 1
    return delivered


class MailWorker:
    """Poll the shared database so restarts and multiple replicas can retry."""

    def __init__(self, store: Store, settings: AuditSettings) -> None:
        self.store = store
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.settings.email_delivery_ready or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="rigor-mail", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                deliver_pending(self.store, self.settings)
            except Exception:  # noqa: BLE001 - retry after transient DB failure
                logger.warning("email outbox poll failed")
            self._stop.wait(MAIL_POLL_SECONDS)
