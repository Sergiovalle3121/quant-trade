"""Environment-driven settings for the audit web service. No secret has a default.

Free mode is the safe default: without every Stripe variable the service
serves watermarked reports and never creates a checkout session, so a
misconfigured deployment degrades to "free preview", never to "charged but
not delivered".
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

TRUE_VALUES = {"1", "true", "yes", "on"}


def normalise_database_url(url: str) -> str:
    """Railway hands out ``postgres://``; SQLAlchemy wants the driver spelled out."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


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

    @property
    def stripe_configured(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_webhook_secret and self.stripe_price_id)

    @property
    def stripe_enabled(self) -> bool:
        return self.stripe_configured and not self.free_mode

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
        return cls(
            database_url=normalise_database_url(
                env.get("DATABASE_URL", DEFAULT_DATABASE_URL).strip() or DEFAULT_DATABASE_URL
            ),
            base_url=env.get("AUDIT_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
            or DEFAULT_BASE_URL,
            stripe_secret_key=stripe_secret_key,
            stripe_webhook_secret=stripe_webhook_secret,
            stripe_price_id=stripe_price_id,
            # Free mode is forced whenever Stripe is not fully configured.
            free_mode=requested_free or not configured,
            max_upload_bytes=int(env.get("AUDIT_MAX_UPLOAD_BYTES", MAX_UPLOAD_BYTES)),
            max_uploads_per_hour_per_ip=int(
                env.get("AUDIT_MAX_UPLOADS_PER_HOUR_PER_IP", DEFAULT_MAX_UPLOADS_PER_HOUR_PER_IP)
            ),
            price_usd_cents=int(env.get("AUDIT_PRICE_USD_CENTS", DEFAULT_PRICE_USD_CENTS)),
            retention_days=int(env.get("AUDIT_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)),
            bootstrap_samples=int(env.get("AUDIT_BOOTSTRAP_SAMPLES", DEFAULT_BOOTSTRAP_SAMPLES)),
        )


__all__ = ["AuditSettings", "normalise_database_url"]
