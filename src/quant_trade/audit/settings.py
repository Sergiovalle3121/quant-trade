"""Environment-driven settings for the audit web service. No secret has a default.

Free mode is the safe default: without every Stripe variable the service
serves watermarked reports and never creates a checkout session, so a
misconfigured deployment degrades to "free preview", never to "charged but
not delivered". The one other way out of free mode is an explicit opt-in to
selling with access codes (``AUDIT_ACCESS_CODES=true``): the owner is paid
outside the service and hands out a code, so nothing is charged online.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from quant_trade.audit.schema import MAX_UPLOAD_BYTES

DEFAULT_DATABASE_URL = "sqlite:///state/audit/audit.db"
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_PRICE_USD_CENTS = 4900
DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_UPLOADS_PER_HOUR_PER_IP = 10
DEFAULT_BOOTSTRAP_SAMPLES = 1000
#: 0 ignores ``X-Forwarded-For`` and uses the socket address; behind one
#: reverse proxy (Railway) set ``AUDIT_TRUSTED_PROXY_HOPS=1``.
DEFAULT_TRUSTED_PROXY_HOPS = 0
MAX_TRUSTED_PROXY_HOPS = 10

TRUE_VALUES = {"1", "true", "yes", "on"}


def normalise_database_url(url: str) -> str:
    """Railway hands out ``postgres://``; SQLAlchemy wants the driver spelled out."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def _safe_url(value: str) -> str:
    """Only an ``https://`` (or ``mailto:``) link is shown; anything else is dropped."""
    value = value.strip()
    return value if value.startswith(("https://", "mailto:")) else ""


def _text(value: str) -> str:
    """A one-line operator detail, trimmed and bounded."""
    return " ".join(value.split())[:300]


@dataclass(frozen=True)
class AuditSettings:
    database_url: str = DEFAULT_DATABASE_URL
    base_url: str = DEFAULT_BASE_URL
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""
    free_mode: bool = True
    max_upload_bytes: int = MAX_UPLOAD_BYTES
    max_uploads_per_hour_per_ip: int = DEFAULT_MAX_UPLOADS_PER_HOUR_PER_IP
    price_usd_cents: int = DEFAULT_PRICE_USD_CENTS
    retention_days: int = DEFAULT_RETENTION_DAYS
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES
    trusted_proxy_hops: int = DEFAULT_TRUSTED_PROXY_HOPS
    #: The owner sells access codes (bank transfer, Mercado Pago, WhatsApp).
    access_codes: bool = False
    #: Where a client asks the owner for a code; shown on the landing page.
    contact_url: str = ""
    #: Operator details for the terms and privacy pages. None has a default:
    #: until they are set the pages say so in place of a name.
    operator_name: str = ""
    operator_contact: str = ""
    operator_address: str = ""
    jurisdiction: str = ""

    def __post_init__(self) -> None:
        if not 0 <= self.trusted_proxy_hops <= MAX_TRUSTED_PROXY_HOPS:
            raise ValueError(
                f"trusted_proxy_hops must be between 0 and {MAX_TRUSTED_PROXY_HOPS}, "
                f"got {self.trusted_proxy_hops}"
            )

    @property
    def stripe_configured(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_webhook_secret and self.stripe_price_id)

    @property
    def stripe_enabled(self) -> bool:
        return self.stripe_configured and not self.free_mode

    @property
    def access_codes_enabled(self) -> bool:
        """Codes unlock reports only in paid mode; in free mode nothing is locked."""
        return self.access_codes and not self.free_mode

    @property
    def legal_configured(self) -> bool:
        """Every operator detail the terms and privacy pages need is set."""
        return bool(
            self.operator_name
            and self.operator_contact
            and self.operator_address
            and self.jurisdiction
        )

    @property
    def price_usd(self) -> float:
        return self.price_usd_cents / 100.0

    @property
    def database_kind(self) -> str:
        return "sqlite" if self.database_url.startswith("sqlite") else "postgresql"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AuditSettings:
        env = os.environ if environ is None else environ
        stripe_secret_key = env.get("STRIPE_SECRET_KEY", "").strip()
        stripe_webhook_secret = env.get("STRIPE_WEBHOOK_SECRET", "").strip()
        stripe_price_id = env.get("STRIPE_PRICE_ID", "").strip()
        configured = bool(stripe_secret_key and stripe_webhook_secret and stripe_price_id)
        requested_free = env.get("AUDIT_FREE_MODE", "true").strip().lower() in TRUE_VALUES
        access_codes = env.get("AUDIT_ACCESS_CODES", "").strip().lower() in TRUE_VALUES
        return cls(
            database_url=normalise_database_url(
                env.get("DATABASE_URL", DEFAULT_DATABASE_URL).strip() or DEFAULT_DATABASE_URL
            ),
            base_url=env.get("AUDIT_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
            or DEFAULT_BASE_URL,
            stripe_secret_key=stripe_secret_key,
            stripe_webhook_secret=stripe_webhook_secret,
            stripe_price_id=stripe_price_id,
            # Free mode is forced unless Stripe is fully configured or the
            # owner opted into selling access codes.
            free_mode=requested_free or not (configured or access_codes),
            max_upload_bytes=int(env.get("AUDIT_MAX_UPLOAD_BYTES", MAX_UPLOAD_BYTES)),
            max_uploads_per_hour_per_ip=int(
                env.get("AUDIT_MAX_UPLOADS_PER_HOUR_PER_IP", DEFAULT_MAX_UPLOADS_PER_HOUR_PER_IP)
            ),
            price_usd_cents=int(env.get("AUDIT_PRICE_USD_CENTS", DEFAULT_PRICE_USD_CENTS)),
            retention_days=int(env.get("AUDIT_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)),
            bootstrap_samples=int(env.get("AUDIT_BOOTSTRAP_SAMPLES", DEFAULT_BOOTSTRAP_SAMPLES)),
            trusted_proxy_hops=int(
                env.get("AUDIT_TRUSTED_PROXY_HOPS", "").strip() or DEFAULT_TRUSTED_PROXY_HOPS
            ),
            access_codes=access_codes,
            contact_url=_safe_url(env.get("AUDIT_CONTACT_URL", "")),
            operator_name=_text(env.get("AUDIT_OPERATOR_NAME", "")),
            operator_contact=_text(env.get("AUDIT_OPERATOR_CONTACT", "")),
            operator_address=_text(env.get("AUDIT_OPERATOR_ADDRESS", "")),
            jurisdiction=_text(env.get("AUDIT_JURISDICTION", "")),
        )


__all__ = ["AuditSettings", "normalise_database_url"]
