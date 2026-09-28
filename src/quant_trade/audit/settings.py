"""Environment-driven settings for the audit web service. No secret has a default.

Free mode is the safe default: without both Stripe secrets the service
serves watermarked reports and never creates a checkout session, so a
misconfigured deployment degrades to "free preview", never to "charged but
not delivered". The one other way out of free mode is an explicit opt-in to
selling with access codes (``AUDIT_ACCESS_CODES=true``): the owner is paid
outside the service and hands out a code, so nothing is charged online.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from quant_trade.audit.schema import MAX_UPLOAD_BYTES

DEFAULT_DATABASE_URL = "sqlite:///state/audit/audit.db"
DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_PRICE_USD_CENTS = 2900
#: A pack of ``PACK_CREDITS`` audits sold as one access code. It is shown only
#: when codes are sold and it costs less than that many single audits;
#: ``AUDIT_PACK_PRICE_USD_CENTS=0`` hides it.
PACK_CREDITS = 3
DEFAULT_PACK_PRICE_USD_CENTS = 6900
DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_UPLOADS_PER_HOUR_PER_IP = 10
DEFAULT_BOOTSTRAP_SAMPLES = 1000
#: 0 ignores ``X-Forwarded-For`` and uses the socket address; behind one
#: reverse proxy (Railway) set ``AUDIT_TRUSTED_PROXY_HOPS=1``.
DEFAULT_TRUSTED_PROXY_HOPS = 0
MAX_TRUSTED_PROXY_HOPS = 10
#: Audits computed at the same time; more wait, then get a "busy" page.
DEFAULT_MAX_CONCURRENT_AUDITS = 2
DEFAULT_AUDIT_QUEUE_SECONDS = 30

TRUE_VALUES = {"1", "true", "yes", "on"}
#: The owner panel (``/panel``) stays off unless ``AUDIT_ADMIN_KEY`` is at
#: least this long: a short key could be guessed within the attempt limit.
MIN_ADMIN_KEY_LENGTH = 32


def normalise_database_url(url: str) -> str:
    """Railway hands out ``postgres://``; SQLAlchemy wants the driver spelled out."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def stripe_keys_valid(secret_key: str, webhook_secret: str) -> bool:
    """A secret (``sk_``) or restricted (``rk_``) key plus a ``whsec_`` secret.

    A publishable key (``pk_``) pasted by mistake leaves card payments off
    instead of failing at the first checkout.
    """
    return secret_key.startswith(("sk_", "rk_")) and webhook_secret.startswith("whsec_")


#: Stripe Payment Links live here; a test-mode link has ``/test_`` in its path.
PAYMENT_LINK_PREFIX = "https://buy.stripe.com/"


def resend_key_valid(key: str) -> bool:
    """A Resend API key has the ``re_`` prefix and fits in one header line."""
    return (
        key.startswith("re_")
        and len(key) >= 20
        and key.isascii()
        and not any(ch.isspace() for ch in key)
    )


def _email_token_secret(env: Mapping[str, str]) -> str:
    """The explicit secret, else one derived from the Resend key.

    Deriving it saves the owner a second secret variable. Rotating the Resend
    key then only voids links still waiting in inboxes (24 h at most).
    """
    explicit = env.get("AUDIT_EMAIL_TOKEN_SECRET", "")
    if explicit:
        return explicit
    key = env.get("AUDIT_RESEND_API_KEY", "").strip()
    if not resend_key_valid(key):
        return ""
    return hmac.new(key.encode(), b"rigor-email-token-v1", hashlib.sha256).hexdigest()


def payment_link_valid(url: str) -> bool:
    return url.startswith(PAYMENT_LINK_PREFIX) and len(url) <= 300 and " " not in url


def _ids(value: str) -> frozenset[str]:
    return frozenset(part.strip() for part in value.split(",") if part.strip())


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
    #: Payment Links (no secret key on the service): one audit, and the pack.
    #: Paid links are confirmed only by the signed webhook.
    stripe_link_single: str = ""
    stripe_link_pack: str = ""
    #: Historical compatibility only; public launch keeps this false.
    allow_legacy_payment_links: bool = False
    #: Audits that may be unlocked by a test-mode payment. Empty in normal
    #: operation, so Stripe's public test card never unlocks a real report.
    stripe_test_audits: frozenset[str] = frozenset()
    #: Live Checkout stays closed until approved buyer markets are configured.
    #: Country is declared before checkout and checked against Stripe billing
    #: country after payment; this list is not inferred from IP or language.
    approved_markets: frozenset[str] = frozenset()
    free_mode: bool = True
    max_upload_bytes: int = MAX_UPLOAD_BYTES
    max_uploads_per_hour_per_ip: int = DEFAULT_MAX_UPLOADS_PER_HOUR_PER_IP
    price_usd_cents: int = DEFAULT_PRICE_USD_CENTS
    pack_price_usd_cents: int = DEFAULT_PACK_PRICE_USD_CENTS
    retention_days: int = DEFAULT_RETENTION_DAYS
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES
    trusted_proxy_hops: int = DEFAULT_TRUSTED_PROXY_HOPS
    #: How many uploads are parsed and audited at once, and how long another
    #: upload waits for a free slot before it is told the service is busy.
    max_concurrent_audits: int = DEFAULT_MAX_CONCURRENT_AUDITS
    audit_queue_seconds: int = DEFAULT_AUDIT_QUEUE_SECONDS
    #: The owner sells access codes (bank transfer, Mercado Pago, WhatsApp).
    access_codes: bool = False
    #: Stop new referral rewards during an incident without disabling credits.
    referral_rewards: bool = True
    #: Maximum credited invites across the service in one UTC calendar month.
    referral_global_monthly_cap: int = 100
    #: Migration switch: when enabled, new Checkout and referral rewards
    #: require a confirmed email. Sign-up works; the free first report waits
    #: for a confirmed address.
    email_verification_required: bool = False
    email_token_secret: str = field(default="", repr=False)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = field(default="", repr=False)
    smtp_from: str = ""
    smtp_security: str = "starttls"
    #: Resend's HTTPS API key. Railway blocks outbound SMTP below the Pro
    #: plan, so this transport works where SMTP cannot. It wins over SMTP.
    resend_api_key: str = field(default="", repr=False)
    #: Where a client asks the owner for a code; shown on the landing page.
    contact_url: str = ""
    #: Run the retention purge inside the web service (at start, then daily).
    #: Turning it on is the owner's explicit confirmation of that delete.
    auto_purge: bool = False
    #: Operator details for the terms and privacy pages. None has a default:
    #: until they are set the pages say so in place of a name.
    operator_name: str = ""
    operator_contact: str = ""
    operator_address: str = ""
    jurisdiction: str = ""
    #: Secret for the owner panel where codes are created from a browser.
    #: No default: empty (or shorter than MIN_ADMIN_KEY_LENGTH) turns it off.
    admin_key: str = field(default="", repr=False)
    #: Read public market closes (FRED, no key) to compare a strategy with
    #: holding the market it trades. On by default in the service
    #: (``AUDIT_PUBLIC_DATA=false`` turns it off); off when built directly.
    public_data: bool = False
    #: Refuse sign-ups on example.com, .test and other reserved domains. On
    #: in the service (``AUDIT_ALLOW_RESERVED_EMAILS=true`` turns it off, for
    #: a staging copy); off when built directly, as in tests.
    refuse_reserved_emails: bool = False
    #: Refuse sign-ups whose domain DNS says takes no mail (no such domain,
    #: or neither MX nor address records). On in the service
    #: (``AUDIT_SKIP_EMAIL_DNS=true`` turns it off); off when built directly,
    #: so tests never reach the network.
    check_email_domains: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.trusted_proxy_hops <= MAX_TRUSTED_PROXY_HOPS:
            raise ValueError(
                f"trusted_proxy_hops must be between 0 and {MAX_TRUSTED_PROXY_HOPS}, "
                f"got {self.trusted_proxy_hops}"
            )
        if self.max_concurrent_audits < 1:
            raise ValueError("max_concurrent_audits must be at least 1")
        if self.audit_queue_seconds < 0:
            raise ValueError("audit_queue_seconds cannot be negative")
        if self.referral_global_monthly_cap < 0:
            raise ValueError("referral_global_monthly_cap cannot be negative")
        if not 1 <= self.smtp_port <= 65535:
            raise ValueError("smtp_port must be between 1 and 65535")
        if self.smtp_security not in ("starttls", "ssl"):
            raise ValueError("smtp_security must be starttls or ssl")
        if any(country not in {"MX", "US", "BR", "ES"} for country in self.approved_markets):
            raise ValueError("approved_markets must use reviewed ISO countries MX, US, BR or ES")

    @property
    def email_delivery_ready(self) -> bool:
        """An encrypted transport (Resend's API or SMTP) and a token key."""
        return bool(
            self.base_url.startswith("https://")
            and self.smtp_from.count("@") == 1
            and "\n" not in self.smtp_from
            and "\r" not in self.smtp_from
            and len(self.email_token_secret) >= 32
            and (self.resend_ready or self.smtp_ready)
        )

    @property
    def resend_ready(self) -> bool:
        return resend_key_valid(self.resend_api_key)

    @property
    def smtp_ready(self) -> bool:
        return bool(
            self.smtp_host
            and "\n" not in self.smtp_host
            and "\r" not in self.smtp_host
            and (not self.smtp_username or self.smtp_password)
        )

    @property
    def stripe_configured(self) -> bool:
        """A secret key and a webhook secret of the right kind. The price id is
        optional: without it Checkout is priced from ``price_usd_cents``."""
        return stripe_keys_valid(self.stripe_secret_key, self.stripe_webhook_secret)

    @property
    def stripe_enabled(self) -> bool:
        return self.stripe_configured and not self.free_mode

    @property
    def links_configured(self) -> bool:
        """Payment Links for one audit plus the webhook secret that confirms them."""
        return self.stripe_webhook_secret.startswith("whsec_") and payment_link_valid(
            self.stripe_link_single
        )

    @property
    def links_enabled(self) -> bool:
        return (
            self.allow_legacy_payment_links
            and self.links_configured
            and not self.free_mode
            and not self.stripe_enabled
        )

    @property
    def card_test_mode(self) -> bool:
        """The configured card payments are Stripe test mode (sandbox)."""
        if self.stripe_enabled:
            return "_live_" not in self.stripe_secret_key
        if self.links_enabled:
            return "/test_" in self.stripe_link_single
        return False

    @property
    def card_public(self) -> bool:
        """Live Checkout is public only after markets are explicitly approved.

        Historical Payment Links remain receivable by webhook, but cannot be
        offered as a new public buying path: they bypass the market selector.
        """
        return self.stripe_enabled and not self.card_test_mode and bool(self.approved_markets)

    def card_for(self, audit_id: str) -> bool:
        """Card payment is offered on this audit: live mode, or a listed test audit."""
        if not (self.stripe_enabled or self.links_enabled):
            return False
        return self.card_public or (self.card_test_mode and audit_id in self.stripe_test_audits)

    @property
    def access_codes_enabled(self) -> bool:
        """Codes unlock reports only in paid mode; in free mode nothing is locked."""
        return self.access_codes and not self.free_mode

    @property
    def admin_enabled(self) -> bool:
        return len(self.admin_key) >= MIN_ADMIN_KEY_LENGTH

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
    def pack_price_usd(self) -> float:
        """The pack's price when it is on sale, else 0."""
        on_sale = (
            self.access_codes_enabled or self.stripe_enabled or self.links_enabled
        ) and 0 < self.pack_price_usd_cents < PACK_CREDITS * self.price_usd_cents
        return self.pack_price_usd_cents / 100.0 if on_sale else 0.0

    @property
    def database_kind(self) -> str:
        return "sqlite" if self.database_url.startswith("sqlite") else "postgresql"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AuditSettings:
        env = os.environ if environ is None else environ
        stripe_secret_key = env.get("STRIPE_SECRET_KEY", "").strip()
        stripe_webhook_secret = env.get("STRIPE_WEBHOOK_SECRET", "").strip()
        stripe_price_id = env.get("STRIPE_PRICE_ID", "").strip()
        stripe_link_single = env.get("STRIPE_PAYMENT_LINK_SINGLE", "").strip()
        stripe_link_pack = env.get("STRIPE_PAYMENT_LINK_PACK", "").strip()
        allow_legacy_links = (
            env.get("AUDIT_LEGACY_PAYMENT_LINKS_ENABLED", "false").strip().lower() in TRUE_VALUES
        )
        configured = stripe_keys_valid(stripe_secret_key, stripe_webhook_secret) or (
            allow_legacy_links
            and stripe_webhook_secret.startswith("whsec_")
            and payment_link_valid(stripe_link_single)
        )
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
            stripe_link_single=stripe_link_single if payment_link_valid(stripe_link_single) else "",
            stripe_link_pack=stripe_link_pack if payment_link_valid(stripe_link_pack) else "",
            allow_legacy_payment_links=allow_legacy_links,
            stripe_test_audits=_ids(env.get("AUDIT_STRIPE_TEST_AUDITS", "")),
            approved_markets=frozenset(
                country.strip().upper()
                for country in env.get("AUDIT_APPROVED_MARKETS", "").split(",")
                if country.strip()
            ),
            # Free mode is forced unless Stripe is fully configured or the
            # owner opted into selling access codes.
            free_mode=requested_free or not (configured or access_codes),
            max_upload_bytes=int(env.get("AUDIT_MAX_UPLOAD_BYTES", MAX_UPLOAD_BYTES)),
            max_uploads_per_hour_per_ip=int(
                env.get("AUDIT_MAX_UPLOADS_PER_HOUR_PER_IP", DEFAULT_MAX_UPLOADS_PER_HOUR_PER_IP)
            ),
            price_usd_cents=int(env.get("AUDIT_PRICE_USD_CENTS", DEFAULT_PRICE_USD_CENTS)),
            pack_price_usd_cents=int(
                env.get("AUDIT_PACK_PRICE_USD_CENTS", "").strip() or DEFAULT_PACK_PRICE_USD_CENTS
            ),
            retention_days=int(env.get("AUDIT_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)),
            bootstrap_samples=int(env.get("AUDIT_BOOTSTRAP_SAMPLES", DEFAULT_BOOTSTRAP_SAMPLES)),
            trusted_proxy_hops=int(
                env.get("AUDIT_TRUSTED_PROXY_HOPS", "").strip() or DEFAULT_TRUSTED_PROXY_HOPS
            ),
            max_concurrent_audits=int(
                env.get("AUDIT_MAX_CONCURRENT_AUDITS", "").strip() or DEFAULT_MAX_CONCURRENT_AUDITS
            ),
            audit_queue_seconds=int(
                env.get("AUDIT_QUEUE_SECONDS", "").strip() or DEFAULT_AUDIT_QUEUE_SECONDS
            ),
            access_codes=access_codes,
            referral_rewards=env.get("AUDIT_REFERRAL_REWARDS", "true").strip().lower()
            in TRUE_VALUES,
            referral_global_monthly_cap=int(
                env.get("AUDIT_REFERRAL_GLOBAL_MONTHLY_CAP", "").strip() or "100"
            ),
            email_verification_required=env.get("AUDIT_EMAIL_VERIFICATION_REQUIRED", "false")
            .strip()
            .lower()
            in TRUE_VALUES,
            email_token_secret=_email_token_secret(env),
            smtp_host=env.get("AUDIT_SMTP_HOST", "").strip(),
            smtp_port=int(env.get("AUDIT_SMTP_PORT", "").strip() or "587"),
            smtp_username=env.get("AUDIT_SMTP_USERNAME", "").strip(),
            smtp_password=env.get("AUDIT_SMTP_PASSWORD", ""),
            smtp_from=(env.get("AUDIT_EMAIL_FROM", "") or env.get("AUDIT_SMTP_FROM", "")).strip(),
            smtp_security=env.get("AUDIT_SMTP_SECURITY", "starttls").strip().lower(),
            resend_api_key=env.get("AUDIT_RESEND_API_KEY", "").strip(),
            contact_url=_safe_url(env.get("AUDIT_CONTACT_URL", "")),
            auto_purge=env.get("AUDIT_AUTO_PURGE", "").strip().lower() in TRUE_VALUES,
            operator_name=_text(env.get("AUDIT_OPERATOR_NAME", "")),
            operator_contact=_text(env.get("AUDIT_OPERATOR_CONTACT", "")),
            operator_address=_text(env.get("AUDIT_OPERATOR_ADDRESS", "")),
            jurisdiction=_text(env.get("AUDIT_JURISDICTION", "")),
            admin_key=env.get("AUDIT_ADMIN_KEY", "").strip(),
            public_data=env.get("AUDIT_PUBLIC_DATA", "true").strip().lower() in TRUE_VALUES,
            refuse_reserved_emails=env.get("AUDIT_ALLOW_RESERVED_EMAILS", "").strip().lower()
            not in TRUE_VALUES,
            check_email_domains=env.get("AUDIT_SKIP_EMAIL_DNS", "").strip().lower()
            not in TRUE_VALUES,
        )


__all__ = ["MIN_ADMIN_KEY_LENGTH", "AuditSettings", "normalise_database_url"]
