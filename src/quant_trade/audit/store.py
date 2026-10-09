"""Persistence for the audit service: audits, payments, access codes,
publications, waitlist, retention.

SQLAlchemy Core over a handful of tables, SQLite by default and Postgres by URL. The
uploaded bytes are stored so a paid report can be regenerated and so the
retention purge has something concrete to delete; hashes and the verdict
class survive the purge so a client can still prove what was audited.

Timestamps are ISO-8601 UTC strings: they sort correctly on every backend
and never lose their timezone in transit.

Access codes are stored only as their SHA-256: the clear code is returned
once by ``create_access_code`` and never again. Redemption is one
conditional ``UPDATE`` in the same transaction that inserts the audit, so two
uploads racing for the last credit cannot both win.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from quant_trade.audit import store_hooks
from quant_trade.audit.schema import AuditResult
from quant_trade.audit.store_ops import OpsStoreMixin
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text

REQUIRE_WEB = 'audit web requires: python -m pip install -e ".[web]"'
#: PostgreSQL advisory-lock key held while a starting process creates tables.
SCHEMA_LOCK_KEY = int.from_bytes(b"rigorddl", "big")

#: No 0/O or 1/I/L: a code read aloud over the phone survives.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_PREFIX = "AUD"
CODE_GROUPS = 3
CODE_GROUP_LENGTH = 4
#: The reference a code-paid audit carries instead of a Stripe session.
CODE_REFERENCE_PREFIX = "code:"
#: The payment reference of the free first full report of a new account.
WELCOME_REFERENCE_PREFIX = "welcome:"
#: The free-claim key a card verified for the free full report holds forever.
CARD_CLAIM_PREFIX = "welcome:card:"


#: The ``audit_id`` of an order that buys credits for an account rather than
#: unlocking one report: ``account:<account id>``. Such an order unlocks no
#: report; its credits go on an access code linked to that account.
ACCOUNT_ORDER_PREFIX = "account:"


def account_order_ref(account_id: str) -> str:
    """The order reference of a credit purchase for ``account_id``."""
    if not account_id or len(account_id) > 32 or not account_id.isalnum():
        raise ValueError("invalid account id")
    return ACCOUNT_ORDER_PREFIX + account_id


def new_access_code() -> str:
    """``AUD-XXXX-XXXX-XXXX`` from a CSPRNG (about 59 bits)."""
    groups = [
        "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_GROUP_LENGTH))
        for _ in range(CODE_GROUPS)
    ]
    return "-".join([CODE_PREFIX, *groups])


def normalise_access_code(code: str) -> str:
    """Upper case, spaces and dashes ignored, prefix optional: what a client
    types from a WhatsApp message still matches."""
    compact = "".join(ch for ch in code.upper() if ch.isalnum())
    if compact.startswith(CODE_PREFIX):
        compact = compact[len(CODE_PREFIX) :]
    return compact


def hash_access_code(code: str) -> str:
    return hashlib.sha256(normalise_access_code(code).encode("utf-8")).hexdigest()


def strategy_name(name: str) -> str:
    """A strategy name as stored: no control, format or bidi characters
    (Postgres refuses NUL; the others hide or reorder text), whitespace
    squeezed, at most 80 characters, and ``""`` unless something visible is left."""
    kept = "".join(ch for ch in name if unicodedata.category(ch) not in ("Cc", "Cf"))
    clean = " ".join(kept.split())[:80].strip()
    visible = any(unicodedata.category(ch)[0] not in ("M", "Z", "C") for ch in clean)
    return clean if visible else ""


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


#: Earlier reports of an account compared file by file with a new upload.
SAME_FILE_CANDIDATES = 20


@dataclass(frozen=True)
class AuditRecord:
    id: str
    created_at: str
    token_hash: str
    paid: bool
    paid_at: str | None
    stripe_session_id: str | None
    client_ip: str
    declared_json: str | None
    result_json: str | None
    report_html: str | None
    overall_class: str
    digests: dict[str, str]
    purged_at: str | None
    equity_csv: bytes | None = None
    trades_csv: bytes | None = None
    benchmark_csv: bytes | None = None
    variants_csv: bytes | None = None
    #: Other uploads by digest name (a platform report, an optimisation export).
    files: dict[str, bytes] | None = None


@dataclass(frozen=True)
class WelcomePending:
    """A preview uploaded before the account confirmed its e-mail: the free
    full report it may still become, with the marks it was uploaded with."""

    audit_id: str
    account_id: str
    device_sha256: str
    file_sha256: str
    client_ip: str
    created_at: str


@dataclass(frozen=True)
class RefusedPayment:
    """A live card payment Stripe charged that unlocked nothing: ids only."""

    session_id: str
    audit_id: str
    reason: str
    created_at: str


@dataclass(frozen=True)
class CheckoutOrder:
    """One frozen card order. A session can be paid without delivering twice."""

    id: str
    audit_id: str
    account_id: str
    plan: str
    amount_cents: int
    currency: str
    status: str
    session_id: str
    checkout_url: str
    expires_at: str
    paid_amount_cents: int
    confirmed_at: str
    resolution: str
    livemode: bool | None = None


@dataclass(frozen=True)
class EmailDeliveryIssue:
    """Operator-safe purchase notice state, without recipient or message body."""

    id: str
    kind: str
    status: str
    attempts: int
    created_at: str
    next_attempt_at: str


@dataclass(frozen=True)
class InstitutionalRequest:
    """A private prospect declaration, separate from audits and their evidence."""

    id: str
    created_at: str
    name: str
    organization: str
    email: str
    strategy_type: str
    frequency: str
    history_years: str
    has_benchmark: bool
    variants: int
    description: str
    claim_findings: list[dict[str, Any]]
    locale: str
    ref: str
    contacted_at: str


@dataclass(frozen=True)
class StripeRefundRecord:
    """A signed Stripe refund snapshot, including partial and failed attempts."""

    refund_id: str
    payment_intent_id: str
    charge_id: str
    order_id: str
    amount_minor: int
    currency: str
    status: str
    livemode: bool
    first_seen_at: str
    last_seen_at: str


@dataclass(frozen=True)
class PaymentOutcome:
    """Result of recording a paid session and its delivery in one transaction."""

    status: str
    order_id: str


@dataclass(frozen=True)
class AccessCodeRecord:
    """An access code as the owner may see it: never the code itself."""

    id: str
    note: str
    credits_total: int
    credits_used: int
    created_at: str
    expires_at: str | None
    disabled: bool

    @property
    def credits_left(self) -> int:
        return max(0, self.credits_total - self.credits_used)


@dataclass(frozen=True)
class PublicationRecord:
    public_id: str
    audit_id: str
    created_at: str


@dataclass(frozen=True)
class IssuedFile:
    """A report file the service handed out, found by its SHA-256."""

    audit_id: str
    kind: str
    issued_at: str
    #: ``None`` for the sample report, which has no audit row.
    overall_class: str | None
    public_id: str | None


@dataclass(frozen=True)
class AccountRecord:
    """A customer account as the service reads it: never the password hash."""

    id: str
    email: str
    locale: str
    created_at: str


@dataclass(frozen=True)
class AccountAudit:
    """One report on an account's list."""

    audit_id: str
    created_at: str
    linked_at: str
    overall_class: str
    paid: bool
    paid_at: str | None
    #: ``card``, ``code``, ``welcome`` (the free first report) or ``""`` (not paid).
    paid_with: str
    purged: bool
    published: bool
    description: str
    #: Uploaded by this account while signed in (deletable with it).
    own: bool = True
    #: The public verification page's id when the report is published.
    public_id: str = ""


@dataclass(frozen=True)
class StrategyRecord:
    """A named strategy on an account: the reports that are its versions."""

    id: str
    name: str
    created_at: str
    audit_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionView:
    """One open session on "Sesiones abiertas": never its token or its hash."""

    handle: str
    device: str
    network: str
    created_at: str
    last_seen: str
    current: bool


#: "Actividad reciente": what an account event may be, in the order shown.
ACCOUNT_EVENT_KINDS = (
    "signup",
    "signin",
    "signin_two_step",
    "signin_recovery_key",
    "password_changed",
    "password_recovered",
    "password_reset",
    "two_step_on",
    "two_step_off",
    "two_step_off_by_owner",
    "recovery_key_created",
    "session_ended",
    "sessions_ended",
    "signin_passkey",
    "passkey_added",
    "passkey_removed",
    "email_changed",
)
#: How long an account event is kept, and how many at most per account.
ACCOUNT_EVENT_DAYS = 90
ACCOUNT_EVENT_MAX = 50
#: Wrong-password lines kept per account: their own cap, so a flood of
#: failures never pushes real events out of the ACCOUNT_EVENT_MAX.
FAILED_SIGNIN_MAX = 20
#: Browsers whose last view of Mi cuenta is kept per account.
SEEN_DEVICES_MAX = 20


@dataclass(frozen=True)
class VisitNotice:
    """ "Desde tu última visita": what happened on the account while it was away."""

    failed_attempts: int = 0
    new_devices: tuple[str, ...] = ()


#: The event kinds that open a session, for "a sign-in from a new device".
SIGNIN_KINDS = ("signin", "signin_two_step", "signin_recovery_key", "signin_passkey")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PasskeyRecord:
    """A passkey on "Mi cuenta": its name and dates; the public key stays in the store."""

    credential_id: str
    label: str
    rp_id: str
    created_at: str
    last_used_at: str


@dataclass(frozen=True)
class AccountEvent:
    """One line of "Actividad reciente": what happened, when and from where."""

    kind: str
    device: str
    network: str
    at: str
    count: int = 1


@dataclass(frozen=True)
class InviteSummary:
    """ "Invita a un colega" on one account: who joined, never who they are."""

    joined: int = 0
    waiting: int = 0
    credited: int = 0
    credited_this_month: int = 0


@dataclass(frozen=True)
class AccountCode:
    """An access code on an account: its record plus when it was added."""

    code: AccessCodeRecord
    linked_at: str

    def usable(self, now: str) -> bool:
        return (
            not self.code.disabled
            and self.code.credits_left > 0
            and (self.code.expires_at is None or self.code.expires_at > now)
        )


#: How a report reached an account. Only a report the account uploaded can
#: be deleted with it; one paid for or saved from someone's link is unlinked,
#: since paying for a report does not make its uploader's copy yours to delete.
VIA_UPLOAD = "upload"
VIA_PAID = "paid"
VIA_SAVED = "saved"
OWN_VIAS = (VIA_UPLOAD,)


class _RedeemRace(RuntimeError):
    """Raised inside a transaction to roll back a credit spent for nothing."""


class Store(OpsStoreMixin):
    """One engine, a few tables, a handful of small transactions."""

    def __init__(self, url: str) -> None:
        try:
            import sqlalchemy as sa
        except ImportError as exc:  # pragma: no cover - exercised by the CLI guard
            raise ImportError(REQUIRE_WEB) from exc
        self._sa = sa
        if url.startswith("sqlite:///"):
            # Relative or absolute file path: make sure its directory exists.
            Path(url[len("sqlite:///") :]).parent.mkdir(parents=True, exist_ok=True)
        self.engine = sa.create_engine(url, future=True)
        self.metadata = sa.MetaData()
        self.audits = sa.Table(
            "audits",
            self.metadata,
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("created_at", sa.String(40), nullable=False, index=True),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("paid", sa.Boolean, nullable=False, default=False),
            sa.Column("paid_at", sa.String(40)),
            sa.Column("stripe_session_id", sa.String(255)),
            sa.Column("client_ip", sa.String(64), nullable=False, default="", index=True),
            sa.Column("declared_json", sa.Text),
            sa.Column("result_json", sa.Text),
            sa.Column("report_html", sa.Text),
            sa.Column("overall_class", sa.String(1), nullable=False),
            sa.Column("equity_sha256", sa.String(64)),
            sa.Column("trades_sha256", sa.String(64)),
            sa.Column("benchmark_sha256", sa.String(64)),
            sa.Column("variants_sha256", sa.String(64)),
            sa.Column("equity_csv", sa.LargeBinary),
            sa.Column("trades_csv", sa.LargeBinary),
            sa.Column("benchmark_csv", sa.LargeBinary),
            sa.Column("variants_csv", sa.LargeBinary),
            sa.Column("purged_at", sa.String(40)),
        )
        # Uploads beyond the four original CSVs, one row per file, so that new
        # upload kinds never need a column migration on an existing database.
        self.audit_files = sa.Table(
            "audit_files",
            self.metadata,
            sa.Column("audit_id", sa.String(64), primary_key=True),
            sa.Column("name", sa.String(64), primary_key=True),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("data", sa.LargeBinary),
        )
        # Only explicitly identified customer uploads contribute to the public
        # counter. An additive table leaves legacy rows and test fixtures out
        # without guessing their provenance or migrating existing columns.
        self.audit_count_eligibility = sa.Table(
            "audit_count_eligibility",
            self.metadata,
            sa.Column("audit_id", sa.String(64), primary_key=True),
        )
        self.waitlist = sa.Table(
            "waitlist",
            self.metadata,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("email", sa.String(255), nullable=False, unique=True),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("note", sa.Text, nullable=False, default=""),
        )
        # Additive table: prospects submit declarations here, never upload bytes.
        self.institutional_requests = sa.Table(
            "institutional_requests",
            self.metadata,
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("created_at", sa.String(40), nullable=False, index=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("organization", sa.String(160), nullable=False),
            sa.Column("email", sa.String(254), nullable=False),
            sa.Column("strategy_type", sa.String(24), nullable=False),
            sa.Column("frequency", sa.String(16), nullable=False),
            sa.Column("history_years", sa.String(32), nullable=False),
            sa.Column("has_benchmark", sa.Boolean, nullable=False),
            sa.Column("variants", sa.Integer, nullable=False),
            sa.Column("description", sa.Text, nullable=False),
            sa.Column("claim_findings_json", sa.Text, nullable=False),
            sa.Column("locale", sa.String(8), nullable=False),
            sa.Column("ref", sa.String(80), nullable=False),
            sa.Column("contacted_at", sa.String(40), nullable=False, default=""),
        )
        self.access_codes = sa.Table(
            "access_codes",
            self.metadata,
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("code_sha256", sa.String(64), nullable=False, unique=True),
            sa.Column("credits_total", sa.Integer, nullable=False),
            sa.Column("credits_used", sa.Integer, nullable=False, default=0),
            sa.Column("note", sa.Text, nullable=False, default=""),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("expires_at", sa.String(40)),
            sa.Column("disabled", sa.Boolean, nullable=False, default=False),
        )
        # Additive table for existing databases: the old access_codes table
        # has no source column, and its notes are not financial evidence.
        self.credit_grants = sa.Table(
            "credit_grants",
            self.metadata,
            sa.Column("code_id", sa.String(32), primary_key=True),
            sa.Column("origin", sa.String(16), nullable=False),
            sa.Column("order_id", sa.String(64), nullable=False, default=""),
            sa.Column("credits", sa.Integer, nullable=False),
            sa.Column("created_at", sa.String(40), nullable=False),
        )
        # One row per published audit; the public id is unrelated to the
        # audit id so a verification link never opens the private report.
        self.publications = sa.Table(
            "publications",
            self.metadata,
            sa.Column("public_id", sa.String(32), primary_key=True),
            sa.Column("audit_id", sa.String(64), nullable=False, unique=True),
            sa.Column("created_at", sa.String(40), nullable=False),
        )
        #: What a published verification page shows, kept when the retention
        #: purge deletes the rest of an unpaid audit, so embedded badges and
        #: /v pages stay up until the owner unpublishes or the audit is deleted.
        self.publication_views = sa.Table(
            "publication_views",
            self.metadata,
            sa.Column("audit_id", sa.String(64), primary_key=True),
            sa.Column("result_sha256", sa.String(64), nullable=False),
            sa.Column("view_json", sa.Text, nullable=False),
            sa.Column("kept_at", sa.String(40), nullable=False),
        )
        #: The SHA-256 of every report file the service handed out (PDF, JSON),
        #: so anyone holding one can check it was not edited afterwards. Only
        #: the hash is kept, never the file; it survives the retention purge
        #: like the audit's own hashes and goes with ``delete_audit``.
        self.issued_files = sa.Table(
            "issued_files",
            self.metadata,
            sa.Column("sha256", sa.String(64), primary_key=True),
            sa.Column("audit_id", sa.String(64), nullable=False, index=True),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("issued_at", sa.String(40), nullable=False),
        )
        #: Live card payments that were charged but unlocked nothing (wrong
        #: amount, another link, an unknown audit), so the owner can refund or
        #: unlock them from /panel. Ids and a reason only, never an amount, an
        #: email or card data; rows go with the retention purge.
        self.refused_payments = sa.Table(
            "refused_payments",
            self.metadata,
            sa.Column("session_id", sa.String(255), primary_key=True),
            sa.Column("audit_id", sa.String(80), nullable=False),
            sa.Column("reason", sa.String(80), nullable=False),
            sa.Column("created_at", sa.String(40), nullable=False, index=True),
        )
        # Every paid session has its own row. The audit's `paid` flag is the
        # entitlement; a second charge stays visible here for resolution.
        self.checkout_orders = sa.Table(
            "checkout_orders",
            self.metadata,
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("audit_id", sa.String(64), nullable=False, index=True),
            sa.Column("account_id", sa.String(32), nullable=False, default=""),
            sa.Column("plan", sa.String(16), nullable=False),
            sa.Column("amount_cents", sa.Integer, nullable=False),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("session_id", sa.String(255), unique=True),
            sa.Column("checkout_url", sa.Text, nullable=False, default=""),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("expires_at", sa.String(40), nullable=False),
            sa.Column("paid_amount_cents", sa.Integer, nullable=False, default=0),
            sa.Column("confirmed_at", sa.String(40), nullable=False, default=""),
            sa.Column("resolution", sa.String(80), nullable=False, default=""),
            sa.Column("livemode", sa.Boolean),
        )
        # Additive table: an existing deployment needs no ALTER on orders.
        # The buyer declares a market before Checkout; Stripe's billing country
        # is recorded separately after payment, with its different provenance.
        self.checkout_order_markets = sa.Table(
            "checkout_order_markets",
            self.metadata,
            sa.Column("order_id", sa.String(64), primary_key=True),
            sa.Column("declared_country", sa.String(2), nullable=False),
            sa.Column("billing_country", sa.String(2), nullable=False, default=""),
            sa.Column("checked_at", sa.String(40), nullable=False, default=""),
        )
        # Additive table: the buyer ticked "the report is delivered at once and
        # the purchase is not refundable" before Checkout, under these terms.
        self.checkout_order_terms = sa.Table(
            "checkout_order_terms",
            self.metadata,
            sa.Column("order_id", sa.String(64), primary_key=True),
            sa.Column("terms_version", sa.String(40), nullable=False),
            sa.Column("accepted_at", sa.String(40), nullable=False),
        )
        # Additive mapping: older databases need no ALTER TABLE. A refund can
        # arrive before the Checkout webhook and remain unlinked until it does.
        self.stripe_payment_intents = sa.Table(
            "stripe_payment_intents",
            self.metadata,
            sa.Column("payment_intent_id", sa.String(255), primary_key=True),
            sa.Column("order_id", sa.String(64), nullable=False, unique=True),
            sa.Column("session_id", sa.String(255), nullable=False),
            sa.Column("livemode", sa.Boolean),
            sa.Column("recorded_at", sa.String(40), nullable=False),
        )
        # One row per refund, rather than summing cumulative Charge snapshots.
        # Its final status can change from succeeded to failed days later.
        self.stripe_refunds = sa.Table(
            "stripe_refunds",
            self.metadata,
            sa.Column("refund_id", sa.String(255), primary_key=True),
            sa.Column("payment_intent_id", sa.String(255), nullable=False, default="", index=True),
            sa.Column("charge_id", sa.String(255), nullable=False, default=""),
            sa.Column("order_id", sa.String(64), nullable=False, default="", index=True),
            sa.Column("amount_minor", sa.Integer, nullable=False),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("livemode", sa.Boolean, nullable=False),
            sa.Column("first_seen_at", sa.String(40), nullable=False),
            sa.Column("last_seen_at", sa.String(40), nullable=False),
            sa.Column("succeeded_at", sa.String(40), nullable=False, default=""),
            sa.Column("event_id", sa.String(255), nullable=False, default=""),
        )
        # One reusable in-flight order per report and plan. The Stripe
        # idempotency key is the order id, including after a process restart.
        self.checkout_slots = sa.Table(
            "checkout_slots",
            self.metadata,
            sa.Column("audit_id", sa.String(64), primary_key=True),
            sa.Column("plan", sa.String(16), primary_key=True),
            sa.Column("order_id", sa.String(64), nullable=False),
        )
        # Customer accounts (``audit/accounts.py``). New tables only, so an
        # existing database gains them on start with no column migration.
        self.accounts = sa.Table(
            "accounts",
            self.metadata,
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("email", sa.String(254), nullable=False, unique=True),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("locale", sa.String(8), nullable=False, default="es"),
            sa.Column("created_at", sa.String(40), nullable=False),
        )
        # A separate table makes verification an additive migration: legacy
        # accounts have no row and must confirm before gated actions.
        self.verified_emails = sa.Table(
            "verified_emails",
            self.metadata,
            sa.Column("account_id", sa.String(32), primary_key=True),
            sa.Column("email", sa.String(254), nullable=False),
            sa.Column("verified_at", sa.String(40), nullable=False),
        )
        # Durable delivery and one-use challenges share an id. The database
        # stores no usable link/token: its HMAC is derived when sending.
        self.email_outbox = sa.Table(
            "email_outbox",
            self.metadata,
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("account_id", sa.String(32), nullable=False, index=True),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("email", sa.String(254), nullable=False),
            sa.Column("original_email", sa.String(254), nullable=False),
            sa.Column("locale", sa.String(8), nullable=False),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("expires_at", sa.String(40), nullable=False),
            sa.Column("used_at", sa.String(40)),
            sa.Column("status", sa.String(12), nullable=False),
            sa.Column("attempts", sa.Integer, nullable=False, default=0),
            sa.Column("next_attempt_at", sa.String(40), nullable=False),
            sa.Column("lease_until", sa.String(40), nullable=False, default=""),
            sa.Column("sent_at", sa.String(40), nullable=False, default=""),
        )
        # The readiness warning query runs often, including on old databases.
        # Create these explicitly after create_all so existing outboxes get them.
        self.email_outbox_due_index = sa.Index(
            "ix_email_outbox_kind_status_due",
            self.email_outbox.c.kind,
            self.email_outbox.c.status,
            self.email_outbox.c.next_attempt_at,
        )
        self.email_outbox_lease_index = sa.Index(
            "ix_email_outbox_kind_status_lease",
            self.email_outbox.c.kind,
            self.email_outbox.c.status,
            self.email_outbox.c.lease_until,
        )
        #: Only the SHA-256 of a session cookie is kept.
        self.account_sessions = sa.Table(
            "account_sessions",
            self.metadata,
            sa.Column("token_sha256", sa.String(64), primary_key=True),
            sa.Column("account_id", sa.String(32), nullable=False, index=True),
            sa.Column("csrf", sa.String(64), nullable=False),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("expires_at", sa.String(40), nullable=False),
        )
        # "Sesiones abiertas": a short device label (never the raw browser
        # string), the network (an IPv6 /64) and the last use of a session,
        # with a random handle to sign it out by. Goes with its session.
        self.session_info = sa.Table(
            "session_info",
            self.metadata,
            sa.Column("token_sha256", sa.String(64), primary_key=True),
            sa.Column("account_id", sa.String(32), nullable=False, index=True),
            sa.Column("handle", sa.String(32), nullable=False, unique=True),
            sa.Column("device", sa.String(80), nullable=False, default=""),
            sa.Column("network", sa.String(64), nullable=False, default=""),
            sa.Column("last_seen", sa.String(40), nullable=False),
        )
        # "Actividad reciente": sign-ins and security changes with the
        # device label and network, kept ACCOUNT_EVENT_DAYS days and at most
        # ACCOUNT_EVENT_MAX per account. Goes with the account.
        self.account_events = sa.Table(
            "account_events",
            self.metadata,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("account_id", sa.String(32), nullable=False, index=True),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("device", sa.String(80), nullable=False, default=""),
            sa.Column("network", sa.String(64), nullable=False, default=""),
            sa.Column("at", sa.String(40), nullable=False, index=True),
        )
        # Wrong passwords on an existing account, one row per network and
        # hour (the attempts are counted, the typed e-mail and password are
        # never kept), at most FAILED_SIGNIN_MAX per account for
        # ACCOUNT_EVENT_DAYS days. Goes with the account.
        self.failed_signins = sa.Table(
            "failed_signins",
            self.metadata,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("account_id", sa.String(32), nullable=False, index=True),
            sa.Column("network", sa.String(64), nullable=False, default=""),
            sa.Column("hour", sa.String(13), nullable=False),
            sa.Column("device", sa.String(80), nullable=False, default=""),
            sa.Column("attempts", sa.Integer, nullable=False, default=1),
            sa.Column("last_at", sa.String(40), nullable=False, index=True),
            sa.UniqueConstraint("account_id", "network", "hour"),
        )
        # "Desde tu última visita": when each browser (the hash of its
        # rigor_device cookie) last opened Mi cuenta, with its device label
        # for display, and how many tries each wrong-password line had then
        # (JSON, at most FAILED_SIGNIN_MAX ids), so only newer tries are
        # counted. Kept per browser so a sign-in elsewhere, even with the
        # same label, never clears the owner's notice. At most
        # SEEN_DEVICES_MAX rows (a newcomer past it is not stored), 90 days
        # without a view; goes with the account.
        self.account_seen = sa.Table(
            "account_seen",
            self.metadata,
            sa.Column("account_id", sa.String(32), primary_key=True),
            sa.Column("browser", sa.String(64), primary_key=True),
            sa.Column("device", sa.String(80), nullable=False, default=""),
            sa.Column("seen_at", sa.String(40), nullable=False),
            sa.Column("failed_json", sa.Text, nullable=False, default="{}"),
        )
        #: One account per audit: the report a customer uploaded or saved.
        self.account_audits = sa.Table(
            "account_audits",
            self.metadata,
            sa.Column("audit_id", sa.String(64), primary_key=True),
            sa.Column("account_id", sa.String(32), nullable=False, index=True),
            sa.Column("linked_at", sa.String(40), nullable=False),
            #: How it got there: ``upload`` or ``paid`` while signed in (the
            #: account's own report), or ``saved`` from a link someone shared.
            sa.Column("via", sa.String(8), nullable=False, default=VIA_SAVED),
        )
        #: One account per access code: its credits show on that account.
        self.account_codes = sa.Table(
            "account_codes",
            self.metadata,
            sa.Column("code_id", sa.String(32), primary_key=True),
            sa.Column("account_id", sa.String(32), nullable=False, index=True),
            sa.Column("linked_at", sa.String(40), nullable=False),
        )
        #: One-time password reset links the owner hands out; hash only.
        self.account_resets = sa.Table(
            "account_resets",
            self.metadata,
            sa.Column("token_sha256", sa.String(64), primary_key=True),
            sa.Column("account_id", sa.String(32), nullable=False, index=True),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("expires_at", sa.String(40), nullable=False),
            sa.Column("used_at", sa.String(40)),
        )
        #: Free previews an account used, to count them per calendar month.
        #: The address is kept only for the per-network monthly limit and is
        #: cleared by the retention purge like the audit's own.
        self.free_previews = sa.Table(
            "free_previews",
            self.metadata,
            sa.Column("audit_id", sa.String(32), primary_key=True),
            sa.Column("account_id", sa.String(32), nullable=False, index=True),
            sa.Column("client_ip", sa.String(64), nullable=False, default="", index=True),
            sa.Column("created_at", sa.String(40), nullable=False, index=True),
        )
        #: The one free full report each new account gets. The device (a hash
        #: of a random browser cookie) and the file's SHA-256 stay so that the
        #: same browser or file never gets a second one on another account;
        #: the address is cleared by the retention purge.
        self.welcome_reports = sa.Table(
            "welcome_reports",
            self.metadata,
            sa.Column("account_id", sa.String(32), primary_key=True),
            sa.Column("audit_id", sa.String(32), nullable=False, default=""),
            sa.Column("device_sha256", sa.String(64), nullable=False, default="", index=True),
            sa.Column("file_sha256", sa.String(64), nullable=False, default="", index=True),
            sa.Column("client_ip", sa.String(64), nullable=False, default="", index=True),
            sa.Column("created_at", sa.String(40), nullable=False, index=True),
        )
        # Additive mapping: older databases need no ALTER TABLE. A preview
        # uploaded before the e-mail was confirmed, which confirming it may
        # turn into the free full report; the browser mark, file fingerprint
        # and address are the upload's own, so the same limits are applied
        # again. Rows go with the report, the account and the retention purge.
        self.welcome_pending = sa.Table(
            "welcome_pending",
            self.metadata,
            sa.Column("audit_id", sa.String(32), primary_key=True),
            sa.Column("account_id", sa.String(32), nullable=False, default="", index=True),
            sa.Column("device_sha256", sa.String(64), nullable=False, default=""),
            sa.Column("file_sha256", sa.String(64), nullable=False, default=""),
            sa.Column("client_ip", sa.String(64), nullable=False, default=""),
            sa.Column("created_at", sa.String(40), nullable=False),
        )
        #: A preview uploaded without an account (``AUDIT_ANON_PREVIEW``), for
        #: the owner's funnel: the report's language, the link tag the browser
        #: came with and when, and when the report was put on an account. No
        #: address, browser mark or e-mail. Additive: older databases need no
        #: ALTER TABLE. Rows go with the report and the retention purge.
        self.anon_previews = sa.Table(
            "anon_previews",
            self.metadata,
            sa.Column("audit_id", sa.String(32), primary_key=True),
            sa.Column("locale", sa.String(8), nullable=False, default=""),
            sa.Column("ref", sa.String(32), nullable=False, default=""),
            sa.Column("created_at", sa.String(40), nullable=False, index=True),
            sa.Column("linked_at", sa.String(40), nullable=False, default=""),
        )
        #: A card an account verified with Stripe at no charge (Checkout in
        #: setup mode) so its free full report passes the browser and network
        #: limits. Only a SHA-256 of Stripe's card fingerprint, never a card
        #: number; the row goes with ``delete_account``, while the claim
        #: ``welcome:card:<sha256>`` stays so the card never frees a second one.
        self.card_checks = sa.Table(
            "card_checks",
            self.metadata,
            sa.Column("account_id", sa.String(32), primary_key=True),
            sa.Column("card_sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.String(40), nullable=False),
        )
        #: A customer's own column mapping for a file no importer knows, per
        #: account and header (``audit/mapping.py``): column names and a hash
        #: of the header only, never a row; it goes with ``delete_account``.
        self.column_maps = sa.Table(
            "column_maps",
            self.metadata,
            sa.Column("account_id", sa.String(32), primary_key=True),
            sa.Column("header_sha256", sa.String(64), primary_key=True),
            sa.Column("columns_json", sa.Text, nullable=False),
            sa.Column("updated_at", sa.String(40), nullable=False),
        )
        #: Claims that make the free tier's limits hold under simultaneous
        #: uploads: each free full report or free preview takes its keys (the
        #: account, the browser, the file, a numbered slot of the month) in one
        #: transaction before the audit runs, so two uploads can never both
        #: take the last one. Keys that carry a network address hold only its
        #: hash, and the retention purge deletes them.
        self.free_claims = sa.Table(
            "free_claims",
            self.metadata,
            sa.Column("claim_key", sa.String(200), primary_key=True),
            sa.Column("reservation", sa.String(64), nullable=False, index=True),
            sa.Column("created_at", sa.String(40), nullable=False, index=True),
        )
        #: "Mis estrategias": an account names a strategy and files its reports
        #: under it, each report in at most one strategy. Only reports already
        #: on the account's list can be filed; nothing here unlocks anything.
        self.strategies = sa.Table(
            "strategies",
            self.metadata,
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("account_id", sa.String(32), nullable=False, index=True),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("created_at", sa.String(40), nullable=False),
        )
        self.strategy_reports = sa.Table(
            "strategy_reports",
            self.metadata,
            sa.Column("audit_id", sa.String(32), primary_key=True),
            sa.Column("strategy_id", sa.String(32), nullable=False, index=True),
            sa.Column("account_id", sa.String(32), nullable=False, index=True),
            sa.Column("added_at", sa.String(40), nullable=False),
        )
        #: "Invita a un colega": each account's invite token, made the first
        #: time "Mi cuenta" shows it, and one row per account that signed up
        #: through someone's link. Only a random mark of the new account's
        #: browser is kept (a hash), to refuse a self-invite; the inviter is
        #: credited once the new account's free first report exists, through
        #: an access code linked to the inviter. Both go with either account.
        self.invite_links = sa.Table(
            "invite_links",
            self.metadata,
            sa.Column("account_id", sa.String(32), primary_key=True),
            sa.Column("token", sa.String(32), nullable=False, unique=True),
            sa.Column("created_at", sa.String(40), nullable=False),
        )
        # "Clave de recuperación": only the key's SHA-256 (the key has 100
        # random bits), one per account, spent when used.
        self.recovery_keys = sa.Table(
            "recovery_keys",
            self.metadata,
            sa.Column("account_id", sa.String(32), primary_key=True),
            sa.Column("key_sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.String(40), nullable=False),
        )
        # Two-step sign-in (TOTP): the secret an authenticator app shares,
        # pending until a first code confirms it (``enabled_at`` empty), and
        # the last step used so a code never works twice.
        self.two_step = sa.Table(
            "two_step",
            self.metadata,
            sa.Column("account_id", sa.String(32), primary_key=True),
            sa.Column("secret", sa.String(64), nullable=False),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("enabled_at", sa.String(40), nullable=False, default=""),
            sa.Column("last_step", sa.BigInteger, nullable=False, default=0),
        )
        # Passkeys (WebAuthn): only the credential id, its public key and the
        # device's counter; ``rp_id`` is the host it was made for (a new
        # domain needs new passkeys). Goes with the account.
        self.passkeys = sa.Table(
            "passkeys",
            self.metadata,
            sa.Column("credential_sha256", sa.String(64), primary_key=True),
            sa.Column("credential_id", sa.Text, nullable=False),
            sa.Column("account_id", sa.String(32), nullable=False, index=True),
            sa.Column("public_key", sa.Text, nullable=False),
            sa.Column("sign_count", sa.BigInteger, nullable=False, default=0),
            sa.Column("label", sa.String(80), nullable=False, default=""),
            sa.Column("rp_id", sa.String(255), nullable=False),
            sa.Column("transports", sa.String(200), nullable=False, default=""),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("last_used_at", sa.String(40), nullable=False, default=""),
        )
        # An open passkey page: the random challenge the browser must sign,
        # for whom (empty on the sign-in page, where the device chooses) and
        # what for. Five minutes, used once.
        self.passkey_challenges = sa.Table(
            "passkey_challenges",
            self.metadata,
            sa.Column("token_sha256", sa.String(64), primary_key=True),
            sa.Column("challenge", sa.String(64), nullable=False),
            sa.Column("account_id", sa.String(32), nullable=False, default="", index=True),
            sa.Column("purpose", sa.String(8), nullable=False),
            sa.Column("label", sa.String(80), nullable=False, default=""),
            sa.Column("expires_at", sa.String(40), nullable=False),
        )
        # A correct password on a two-step account waits here for its code.
        self.two_step_challenges = sa.Table(
            "two_step_challenges",
            self.metadata,
            sa.Column("token_sha256", sa.String(64), primary_key=True),
            sa.Column("account_id", sa.String(32), nullable=False, index=True),
            sa.Column("expires_at", sa.String(40), nullable=False),
        )
        self.referrals = sa.Table(
            "referrals",
            self.metadata,
            sa.Column("invitee_id", sa.String(32), primary_key=True),
            sa.Column("inviter_id", sa.String(32), nullable=False, index=True),
            sa.Column("device_sha256", sa.String(64), nullable=False, default=""),
            sa.Column("joined_at", sa.String(40), nullable=False),
            #: ``""`` while the new account has no free report yet; then
            #: ``credited``, ``self`` (the same browser or address as the
            #: inviter) or ``cap`` (the inviter's month was full).
            sa.Column("outcome", sa.String(8), nullable=False, default=""),
            sa.Column("decided_at", sa.String(40)),
            #: ``<inviter>:<YYYY-MM>:<n>``: unique, so the monthly cap holds
            #: when two invitees get their first report at once.
            sa.Column("reward_slot", sa.String(80), unique=True),
            sa.Column("code_id", sa.String(32)),
        )
        # A fixed monthly launch budget shared by all inviters. Slots remain
        # allocated even when an invitee later deletes their account.
        self.referral_global_slots = sa.Table(
            "referral_global_slots",
            self.metadata,
            sa.Column("month", sa.String(7), primary_key=True),
            sa.Column("slot", sa.Integer, primary_key=True),
            sa.Column("created_at", sa.String(40), nullable=False),
        )
        #: Failed sign-ins, sign-ups and panel keys in the last hour, so a
        #: deploy does not reset the limits. Keys are hashed (they hold an
        #: address or an e-mail) and rows older than the window are deleted.
        self.attempts = sa.Table(
            "attempts",
            self.metadata,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("key_sha256", sa.String(64), nullable=False, index=True),
            sa.Column("at", sa.String(40), nullable=False, index=True),
        )
        #: The owner's funnel (``audit/funnel.py``): visits to the landing and
        #: case pages as bare counters per day, language and tag, with no
        #: address, cookie or user agent.
        self.funnel_visits = sa.Table(
            "funnel_visits",
            self.metadata,
            sa.Column("day", sa.String(10), primary_key=True),
            sa.Column("locale", sa.String(8), primary_key=True),
            sa.Column("ref", sa.String(24), primary_key=True),
            sa.Column("visits", sa.Integer, nullable=False, default=0),
        )
        #: The listed tag of the link that brought an account, if any; it
        #: goes with ``delete_account``.
        self.account_refs = sa.Table(
            "account_refs",
            self.metadata,
            sa.Column("account_id", sa.String(32), primary_key=True),
            sa.Column("ref", sa.String(24), nullable=False),
            sa.Column("created_at", sa.String(40), nullable=False),
        )
        store_hooks.define_tables(self)  # the continuous track record's tables
        self.define_ops_tables()
        with self.engine.begin() as conn:
            if self.engine.dialect.name == "postgresql":
                # Replicas starting together take turns: without the lock the
                # second can hit UniqueViolation on pg_type and abort startup.
                # The lock ends with this transaction; then checkfirst sees
                # the tables the first replica committed.
                conn.execute(
                    sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_LOCK_KEY}
                )
            self.metadata.create_all(conn)
            self.email_outbox_due_index.create(conn, checkfirst=True)
            self.email_outbox_lease_index.create(conn, checkfirst=True)

    # -- column maps -------------------------------------------------------
    def save_column_map(
        self, account_id: str, header_sha256: str, columns_json: str, *, at: datetime
    ) -> None:
        """Keep (or replace) an account's mapping for one header."""
        table = self.column_maps
        with self.engine.begin() as conn:
            conn.execute(
                table.delete()
                .where(table.c.account_id == account_id)
                .where(table.c.header_sha256 == header_sha256)
            )
            conn.execute(
                table.insert().values(
                    account_id=account_id,
                    header_sha256=header_sha256,
                    columns_json=columns_json,
                    updated_at=_iso(at),
                )
            )

    def column_map(self, account_id: str, header_sha256: str) -> str | None:
        """The account's saved mapping for this header, as JSON, if any."""
        table = self.column_maps
        with self.engine.connect() as conn:
            found = conn.execute(
                self._sa.select(table.c.columns_json)
                .where(table.c.account_id == account_id)
                .where(table.c.header_sha256 == header_sha256)
            ).scalar()
        return str(found) if found is not None else None

    # -- audits ------------------------------------------------------------
    def create_audit(
        self,
        *,
        audit_id: str,
        created_at: datetime,
        token_hash: str,
        client_ip: str,
        declared_json: str,
        result_json: str,
        report_html: str,
        overall_class: str,
        digests: dict[str, str],
        equity_csv: bytes | None,
        trades_csv: bytes | None = None,
        benchmark_csv: bytes | None = None,
        variants_csv: bytes | None = None,
        files: dict[str, bytes] | None = None,
        access_code: str | None = None,
        public_count_eligible: bool = False,
    ) -> bool:
        """Insert an audit. ``files`` maps a digest name (``report.html``,
        ``optimization.xml``) to its bytes; its hash comes from ``digests``.

        With ``access_code`` one credit is redeemed in the same transaction
        and the audit is born paid. Returns whether it is paid; a code that is
        unknown, used up, expired or disabled simply yields ``False``.

        ``public_count_eligible`` must only be set for customer uploads after
        the engine and renderer finish. Existing rows, samples and callers
        such as test fixtures are not retroactively treated as customer work.
        """
        with self.engine.begin() as conn:
            code_id = self._redeem(conn, access_code, at=created_at) if access_code else None
            conn.execute(
                self.audits.insert().values(
                    id=audit_id,
                    created_at=_iso(created_at),
                    token_hash=token_hash,
                    paid=code_id is not None,
                    paid_at=_iso(created_at) if code_id is not None else None,
                    stripe_session_id=(
                        CODE_REFERENCE_PREFIX + code_id if code_id is not None else None
                    ),
                    client_ip=client_ip,
                    declared_json=declared_json,
                    result_json=result_json,
                    # PostgreSQL refuses text holding a NUL; a page never needs one.
                    report_html=report_html.replace("\x00", "") if report_html else report_html,
                    overall_class=overall_class,
                    equity_sha256=digests.get("equity.csv"),
                    trades_sha256=digests.get("trades.csv"),
                    benchmark_sha256=digests.get("benchmark.csv"),
                    variants_sha256=digests.get("variants.csv"),
                    equity_csv=equity_csv,
                    trades_csv=trades_csv,
                    benchmark_csv=benchmark_csv,
                    variants_csv=variants_csv,
                )
            )
            for name, data in sorted((files or {}).items()):
                conn.execute(
                    self.audit_files.insert().values(
                        audit_id=audit_id, name=name, sha256=digests[name], data=data
                    )
                )
            if (
                public_count_eligible
                and audit_id != "sample"
                and overall_class in ("A", "B", "C", "D")
                and result_json
                and report_html
            ):
                conn.execute(self.audit_count_eligibility.insert().values(audit_id=audit_id))
        return code_id is not None

    def get_audit(self, audit_id: str, *, with_blobs: bool = False) -> AuditRecord | None:
        if not _usable_key(audit_id):
            return None
        with self.engine.connect() as conn:
            row = (
                conn.execute(self._sa.select(self.audits).where(self.audits.c.id == audit_id))
                .mappings()
                .first()
            )
            if row is None:
                return None
            files = (
                conn.execute(
                    self._sa.select(self.audit_files).where(self.audit_files.c.audit_id == audit_id)
                )
                .mappings()
                .all()
            )
        return self._record(row, with_blobs=with_blobs, files=files)

    def _record(self, row: Any, *, with_blobs: bool, files: Any = ()) -> AuditRecord:
        digests = {
            name: row[column]
            for name, column in (
                ("equity.csv", "equity_sha256"),
                ("trades.csv", "trades_sha256"),
                ("benchmark.csv", "benchmark_sha256"),
                ("variants.csv", "variants_sha256"),
            )
            if row[column]
        }
        for file in files:
            digests[file["name"]] = file["sha256"]
        return AuditRecord(
            id=row["id"],
            created_at=row["created_at"],
            token_hash=row["token_hash"],
            paid=bool(row["paid"]),
            paid_at=row["paid_at"],
            stripe_session_id=row["stripe_session_id"],
            client_ip=row["client_ip"],
            declared_json=row["declared_json"],
            result_json=row["result_json"],
            report_html=row["report_html"],
            overall_class=row["overall_class"],
            digests=digests,
            purged_at=row["purged_at"],
            equity_csv=row["equity_csv"] if with_blobs else None,
            trades_csv=row["trades_csv"] if with_blobs else None,
            benchmark_csv=row["benchmark_csv"] if with_blobs else None,
            variants_csv=row["variants_csv"] if with_blobs else None,
            files=(
                {file["name"]: file["data"] for file in files if file["data"] is not None}
                if with_blobs
                else None
            ),
        )

    def mark_paid(self, audit_id: str, *, stripe_session_id: str, at: datetime) -> bool:
        """Flip an audit to paid. Idempotent: a second call changes nothing
        and returns ``False``; an unknown id returns ``False`` too."""
        if not _usable_key(audit_id):
            return False
        with self.engine.begin() as conn:
            result = conn.execute(
                self.audits.update()
                .where(self.audits.c.id == audit_id)
                .where(self.audits.c.paid.is_(False))
                .values(paid=True, paid_at=_iso(at), stripe_session_id=stripe_session_id)
            )
            return bool(result.rowcount)

    @staticmethod
    def _checkout_order(row: Any) -> CheckoutOrder:
        return CheckoutOrder(
            id=str(row["id"]),
            audit_id=str(row["audit_id"]),
            account_id=str(row["account_id"] or ""),
            plan=str(row["plan"]),
            amount_cents=int(row["amount_cents"]),
            currency=str(row["currency"]),
            status=str(row["status"]),
            session_id=str(row["session_id"] or ""),
            checkout_url=str(row["checkout_url"] or ""),
            expires_at=str(row["expires_at"]),
            paid_amount_cents=int(row["paid_amount_cents"]),
            confirmed_at=str(row["confirmed_at"] or ""),
            resolution=str(row["resolution"] or ""),
            livemode=row["livemode"],
        )

    def get_checkout_order(self, order_id: str) -> CheckoutOrder | None:
        if not _usable_key(order_id):
            return None
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    self._sa.select(self.checkout_orders).where(
                        self.checkout_orders.c.id == order_id
                    )
                )
                .mappings()
                .first()
            )
        return self._checkout_order(row) if row is not None else None

    def get_checkout_session(self, session_id: str) -> CheckoutOrder | None:
        if not _usable_key(session_id):
            return None
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    self._sa.select(self.checkout_orders).where(
                        self.checkout_orders.c.session_id == session_id
                    )
                )
                .mappings()
                .first()
            )
        return self._checkout_order(row) if row is not None else None

    def reserve_checkout(
        self,
        audit_id: str,
        *,
        account_id: str,
        plan: str,
        amount_cents: int,
        currency: str,
        at: datetime,
        declared_country: str = "",
        locale: str = "",
    ) -> CheckoutOrder:
        """Freeze a new order or reuse its valid in-flight Checkout session.

        Both an HTTP retry and a concurrent second click get the same order id,
        which is sent to Stripe as the idempotency key. The slot is rotated
        only after it expires or settles. ``locale`` is part of the slot, so a
        buyer who switches language gets a Checkout page in that language.
        """
        if plan not in ("single", "pack") or amount_cents < 1 or currency != "usd":
            raise ValueError("invalid checkout plan or amount")
        # A credit purchase has no report to lock: it belongs to its account.
        for_account = audit_id.startswith(ACCOUNT_ORDER_PREFIX)
        if for_account and audit_id != account_order_ref(account_id):
            raise ValueError("credit purchase for another account")
        if declared_country and (
            len(declared_country) != 2
            or not declared_country.isalpha()
            or not declared_country.isupper()
        ):
            raise ValueError("invalid declared market")
        if locale and (len(locale) > 5 or not locale.isalpha()):
            raise ValueError("invalid checkout locale")
        slot_plan = f"{plan}:{locale}" if locale else plan
        sa = self._sa
        orders, slots = self.checkout_orders, self.checkout_slots
        stamp = _iso(at)
        expires = _iso(at + timedelta(hours=23))
        for _ in range(3):
            try:
                with self.engine.begin() as conn:
                    audit = (
                        None
                        if for_account
                        else conn.execute(
                            sa.select(self.audits.c.paid)
                            .where(self.audits.c.id == audit_id)
                            .with_for_update()
                        ).first()
                    )
                    if not for_account and (audit is None or bool(audit[0])):
                        raise ValueError("audit unavailable for checkout")
                    unresolved = conn.execute(
                        sa.select(orders.c.id)
                        .where(orders.c.audit_id == audit_id)
                        .where(orders.c.status == "paid_review")
                        .with_for_update()
                        .limit(1)
                    ).first()
                    if unresolved is not None:
                        raise ValueError("checkout market review")
                    slot = conn.execute(
                        sa.select(slots.c.order_id)
                        .where(slots.c.audit_id == audit_id)
                        .where(slots.c.plan == slot_plan)
                        .with_for_update()
                    ).first()
                    if slot is not None:
                        old = (
                            conn.execute(
                                sa.select(orders).where(orders.c.id == slot[0]).with_for_update()
                            )
                            .mappings()
                            .first()
                        )
                        if (
                            old is not None
                            and old["status"] in ("creating", "open")
                            and str(old["expires_at"]) > stamp
                        ):
                            if declared_country:
                                frozen_market = conn.execute(
                                    sa.select(self.checkout_order_markets.c.declared_country).where(
                                        self.checkout_order_markets.c.order_id == old["id"]
                                    )
                                ).scalar_one_or_none()
                                if frozen_market != declared_country:
                                    raise ValueError("checkout market changed")
                            return self._checkout_order(old)
                    order_id = secrets.token_hex(16)
                    conn.execute(
                        orders.insert().values(
                            id=order_id,
                            audit_id=audit_id,
                            account_id=account_id,
                            plan=plan,
                            amount_cents=amount_cents,
                            currency=currency,
                            status="creating",
                            session_id=None,
                            checkout_url="",
                            created_at=stamp,
                            expires_at=expires,
                            paid_amount_cents=0,
                            confirmed_at="",
                            resolution="",
                        )
                    )
                    if declared_country:
                        conn.execute(
                            self.checkout_order_markets.insert().values(
                                order_id=order_id,
                                declared_country=declared_country,
                                billing_country="",
                                checked_at="",
                            )
                        )
                    if slot is None:
                        conn.execute(
                            slots.insert().values(
                                audit_id=audit_id, plan=slot_plan, order_id=order_id
                            )
                        )
                    else:
                        conn.execute(
                            slots.update()
                            .where(slots.c.audit_id == audit_id)
                            .where(slots.c.plan == slot_plan)
                            .values(order_id=order_id)
                        )
                    row = (
                        conn.execute(sa.select(orders).where(orders.c.id == order_id))
                        .mappings()
                        .one()
                    )
                    return self._checkout_order(row)
            except sa.exc.IntegrityError:
                # Another request inserted this report/plan slot. Read it on retry.
                continue
        raise RuntimeError("could not reserve checkout")

    def checkout_market(self, order_id: str) -> tuple[str, str] | None:
        """Return (buyer-declared country, Stripe billing country), if recorded."""
        if not _usable_key(order_id):
            return None
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    self._sa.select(self.checkout_order_markets).where(
                        self.checkout_order_markets.c.order_id == order_id
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return str(row["declared_country"]), str(row["billing_country"])

    def record_final_sale(self, order_id: str, *, terms_version: str, at: datetime) -> None:
        """Keep the buyer's first acceptance of a final sale for this order."""
        if not _usable_key(order_id):
            raise ValueError("invalid order id")
        table = self.checkout_order_terms
        if self.final_sale_acceptance(order_id) is not None:
            return
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    table.insert().values(
                        order_id=order_id, terms_version=terms_version, accepted_at=_iso(at)
                    )
                )
        except self._sa.exc.IntegrityError:
            pass  # a concurrent click recorded it first

    def final_sale_acceptance(self, order_id: str) -> tuple[str, str] | None:
        """(terms version, accepted at) of the order's final-sale checkbox, if ticked."""
        if not _usable_key(order_id):
            return None
        table = self.checkout_order_terms
        with self.engine.connect() as conn:
            row = conn.execute(
                self._sa.select(table.c.terms_version, table.c.accepted_at).where(
                    table.c.order_id == order_id
                )
            ).first()
        return (str(row[0]), str(row[1])) if row else None

    def has_checkout_review(self, audit_id: str) -> bool:
        """A charged audit awaiting operator resolution must not be sold again."""
        if not _usable_key(audit_id):
            return False
        with self.engine.connect() as conn:
            row = conn.execute(
                self._sa.select(self.checkout_orders.c.id)
                .where(self.checkout_orders.c.audit_id == audit_id)
                .where(self.checkout_orders.c.status == "paid_review")
                .limit(1)
            ).first()
        return row is not None

    def record_checkout_market(
        self, order_id: str, billing_country: str, *, declared_country: str, at: datetime
    ) -> None:
        """Keep both countries on the order that this paid session actually settled."""
        sa, markets = self._sa, self.checkout_order_markets
        for _ in range(3):
            try:
                with self.engine.begin() as conn:
                    row = conn.execute(
                        sa.select(markets.c.declared_country)
                        .where(markets.c.order_id == order_id)
                        .with_for_update()
                    ).first()
                    if row is None:
                        conn.execute(
                            markets.insert().values(
                                order_id=order_id,
                                declared_country=declared_country,
                                billing_country=billing_country,
                                checked_at=_iso(at),
                            )
                        )
                    else:
                        if str(row[0]) != declared_country:
                            raise ValueError("checkout market disagrees with order")
                        conn.execute(
                            markets.update()
                            .where(markets.c.order_id == order_id)
                            .values(billing_country=billing_country, checked_at=_iso(at))
                        )
                return
            except sa.exc.IntegrityError:
                continue  # a concurrent webhook inserted this order's market row
        raise RuntimeError("could not record checkout market")

    def record_market_review(
        self,
        *,
        order_id: str,
        session_id: str,
        audit_id: str,
        billing_country: str,
        paid_cents: int,
        payment_intent_id: str,
        reason: str,
        at: datetime,
        queue_receipt: bool = False,
    ) -> None:
        """Keep a charged, market-rejected order and operator issue atomically."""
        sa, orders, markets = self._sa, self.checkout_orders, self.checkout_order_markets
        stamp = _iso(at)
        for _ in range(3):
            try:
                with self.engine.begin() as conn:
                    conn.execute(
                        sa.select(self.audits.c.id)
                        .where(self.audits.c.id == audit_id)
                        .with_for_update()
                    ).first()
                    original = (
                        conn.execute(
                            sa.select(orders).where(orders.c.id == order_id).with_for_update()
                        )
                        .mappings()
                        .one()
                    )
                    original_market = conn.execute(
                        sa.select(markets.c.declared_country).where(markets.c.order_id == order_id)
                    ).scalar_one()
                    if original["audit_id"] != audit_id:
                        raise ValueError("market review audit disagrees with order")
                    target = (
                        conn.execute(
                            sa.select(orders)
                            .where(orders.c.session_id == session_id)
                            .with_for_update()
                        )
                        .mappings()
                        .first()
                    )
                    if target is None and not original["session_id"]:
                        target = original
                    if target is None and original["session_id"] == session_id:
                        target = original
                    if target is None:
                        # A second paid Stripe session retained the original
                        # metadata. It must have its own order and refund link.
                        resolved_order_id = secrets.token_hex(16)
                        conn.execute(
                            orders.insert().values(
                                id=resolved_order_id,
                                audit_id=audit_id,
                                account_id=original["account_id"],
                                plan=original["plan"],
                                amount_cents=original["amount_cents"],
                                currency=original["currency"],
                                status="paid_review",
                                session_id=session_id,
                                checkout_url="",
                                created_at=stamp,
                                expires_at=stamp,
                                paid_amount_cents=paid_cents,
                                confirmed_at=stamp,
                                resolution="manual_refund_review",
                                livemode=True,
                            )
                        )
                        conn.execute(
                            markets.insert().values(
                                order_id=resolved_order_id,
                                declared_country=original_market,
                                billing_country=billing_country,
                                checked_at=stamp,
                            )
                        )
                    else:
                        if (
                            target["audit_id"] != audit_id
                            or target["plan"] != original["plan"]
                            or target["amount_cents"] != original["amount_cents"]
                            or target["currency"] != original["currency"]
                        ):
                            raise ValueError("market review session disagrees with order")
                        resolved_order_id = str(target["id"])
                        if target["status"] not in ("delivered", "duplicate"):
                            conn.execute(
                                markets.update()
                                .where(markets.c.order_id == resolved_order_id)
                                .values(billing_country=billing_country, checked_at=stamp)
                            )
                            if target["status"] != "paid_review":
                                conn.execute(
                                    orders.update()
                                    .where(orders.c.id == resolved_order_id)
                                    .values(
                                        status="paid_review",
                                        session_id=session_id,
                                        paid_amount_cents=paid_cents,
                                        confirmed_at=stamp,
                                        resolution="manual_refund_review",
                                        livemode=True,
                                    )
                                )
                    self.record_payment_intent_in_tx(
                        conn,
                        resolved_order_id,
                        session_id,
                        payment_intent_id,
                        at,
                        livemode=True,
                    )
                    if target is not None and target["status"] in ("delivered", "duplicate"):
                        return
                    known = conn.execute(
                        sa.select(self.refused_payments.c.session_id).where(
                            self.refused_payments.c.session_id == session_id
                        )
                    ).first()
                    if known is None:
                        conn.execute(
                            self.refused_payments.insert().values(
                                session_id=session_id[:255],
                                audit_id=audit_id[:80],
                                reason=reason[:80],
                                created_at=stamp,
                            )
                        )
                    if queue_receipt:
                        self._queue_purchase_notice_in_tx(
                            conn, resolved_order_id, "market_review", at
                        )
                return
            except sa.exc.IntegrityError:
                continue  # a competing webhook recorded this session first
        raise RuntimeError("could not record market review")

    def _queue_purchase_notice_in_tx(
        self, conn: Any, order_id: str, kind: str, at: datetime
    ) -> None:
        """Commit one buyer notice with its charge, if the address is verified."""
        sa = self._sa
        account_id = conn.execute(
            sa.select(self.checkout_orders.c.account_id).where(
                self.checkout_orders.c.id == order_id
            )
        ).scalar()
        if not account_id:
            return
        address = (
            conn.execute(
                sa.select(self.accounts.c.email, self.accounts.c.locale)
                .join(
                    self.verified_emails,
                    self.verified_emails.c.account_id == self.accounts.c.id,
                )
                .where(self.accounts.c.id == account_id)
                .where(self.verified_emails.c.email == self.accounts.c.email)
            )
            .mappings()
            .first()
        )
        if address is None:
            return
        existing = conn.execute(
            sa.select(self.email_outbox.c.id).where(self.email_outbox.c.id == order_id)
        ).first()
        if existing is not None:
            return
        stamp = _iso(at)
        conn.execute(
            self.email_outbox.insert().values(
                id=order_id,
                account_id=str(account_id),
                kind=kind,
                email=str(address["email"]),
                original_email="",
                locale=str(address["locale"]),
                created_at=stamp,
                expires_at=_iso(at + timedelta(days=7)),
                used_at=None,
                status="queued",
                attempts=0,
                next_attempt_at=stamp,
                lease_until="",
                sent_at="",
            )
        )

    def attach_checkout_session(
        self, order_id: str, *, session_id: str, checkout_url: str, expires_at: datetime | None
    ) -> CheckoutOrder:
        """Persist Stripe's session before redirecting to its payment page."""
        if not checkout_url.startswith("https://") or len(checkout_url) > 2048:
            raise ValueError("invalid checkout URL")
        orders = self.checkout_orders
        sa = self._sa
        with self.engine.begin() as conn:
            row = conn.execute(sa.select(orders).where(orders.c.id == order_id)).mappings().first()
            if row is None or (row["session_id"] and row["session_id"] != session_id):
                raise ValueError("checkout session does not match order")
            values: dict[str, Any] = {"checkout_url": checkout_url}
            if session_id:
                values["session_id"] = session_id
            if expires_at is not None:
                values["expires_at"] = _iso(expires_at)
            if row["status"] == "creating":
                values["status"] = "open"
            conn.execute(orders.update().where(orders.c.id == order_id).values(**values))
            updated = (
                conn.execute(sa.select(orders).where(orders.c.id == order_id)).mappings().one()
            )
        return self._checkout_order(updated)

    def superseded_checkouts(self, order_id: str, *, at: datetime) -> list[CheckoutOrder]:
        """Open sessions of the same purchase that ``order_id`` replaces.

        Only orders another reuse slot of the same report (or account) and
        plan still holds: the same purchase started in another language. An
        order that is paid, in review, delivered or past its expiry is never
        listed, and nothing is listed until the new order has its own session.
        An order made after ``order_id`` is not listed either: a slow older
        request never closes the session the buyer moved on to.
        """
        if not _usable_key(order_id):
            return []
        sa = self._sa
        orders, slots = self.checkout_orders, self.checkout_slots
        stamp = _iso(at)
        with self.engine.connect() as conn:
            new = conn.execute(sa.select(orders).where(orders.c.id == order_id)).mappings().first()
            if (
                new is None
                or not new["audit_id"]
                or new["status"] != "open"
                or not new["checkout_url"]
            ):
                return []
            rows = (
                conn.execute(
                    sa.select(orders)
                    .join(slots, slots.c.order_id == orders.c.id)
                    .where(slots.c.audit_id == new["audit_id"])
                    .where(
                        sa.or_(
                            slots.c.plan == new["plan"],
                            slots.c.plan.like(f"{new['plan']}:%"),
                        )
                    )
                    .where(orders.c.id != order_id)
                    .where(orders.c.audit_id == new["audit_id"])
                    .where(orders.c.account_id == new["account_id"])
                    .where(orders.c.plan == new["plan"])
                    .where(orders.c.status == "open")
                    .where(orders.c.session_id.is_not(None))
                    .where(orders.c.session_id != "")
                    .where(orders.c.expires_at > stamp)
                    .where(orders.c.created_at <= new["created_at"])
                    .order_by(orders.c.created_at, orders.c.id)
                )
                .mappings()
                .all()
            )
        return [self._checkout_order(row) for row in rows]

    def mark_checkout_expired(self, order_id: str, *, session_id: str, at: datetime) -> bool:
        """Stop reusing an order whose session Stripe has just expired.

        The order stays ``open`` with its session id and an expiry of now,
        the same state as a session that expired by itself, so a late paid
        webhook for it still settles. An order that was paid, held for review
        or delivered in the meantime is left untouched (``False``).
        """
        if not _usable_key(order_id) or not session_id:
            return False
        orders = self.checkout_orders
        with self.engine.begin() as conn:
            result = conn.execute(
                orders.update()
                .where(orders.c.id == order_id)
                .where(orders.c.session_id == session_id)
                .where(orders.c.status == "open")
                .values(expires_at=_iso(at), resolution="expired_language_change")
            )
            return bool(result.rowcount)

    def settle_card_payment(
        self,
        *,
        order_id: str,
        session_id: str,
        audit_id: str,
        plan: str,
        expected_cents: int,
        paid_cents: int,
        currency: str,
        pack_code: str,
        at: datetime,
        payment_intent_id: str = "",
        payment_livemode: bool | None = None,
        queue_receipt: bool = False,
    ) -> PaymentOutcome:
        """Record one charge and deliver at most once, in a single DB transaction.

        A second paid session for an already unlocked audit is a separate
        `duplicate` order with a manual refund review, never another pack.
        Stripe retries are idempotent by its session id.
        """
        sa = self._sa
        orders, audits = self.checkout_orders, self.audits
        stamp = _iso(at)
        if payment_livemode is not None and type(payment_livemode) is not bool:
            raise ValueError("invalid paid session mode")

        def queue_purchase_notice(conn: Any, resolved_order_id: str, kind: str) -> None:
            """Commit a buyer notice with the charge, never a second notice on replay.

            The transport is intentionally outside this transaction. Only a
            previously verified address is eligible; legacy anonymous sales
            remain in the owner's reconciliation queue.
            """
            if not queue_receipt:
                return
            self._queue_purchase_notice_in_tx(conn, resolved_order_id, kind, at)

        def link_payment_intent(conn: Any, resolved_order_id: str) -> None:
            recorded_mode = conn.execute(
                sa.select(orders.c.livemode).where(orders.c.id == resolved_order_id)
            ).scalar()
            if (
                recorded_mode is not None
                and payment_livemode is not None
                and bool(recorded_mode) != payment_livemode
            ):
                raise ValueError("paid session mode disagrees with order")
            if recorded_mode is None and payment_livemode is not None:
                conn.execute(
                    orders.update()
                    .where(orders.c.id == resolved_order_id)
                    .values(livemode=payment_livemode)
                )
            if payment_intent_id:
                self.record_payment_intent_in_tx(
                    conn,
                    resolved_order_id,
                    session_id,
                    payment_intent_id,
                    at,
                    livemode=payment_livemode,
                )

        def ensure_pack(conn: Any, resolved_order_id: str) -> None:
            """Repair a legacy crash or grant two rights to a new pack once."""
            digest = hash_access_code(pack_code)
            code_id = conn.execute(
                sa.select(self.access_codes.c.id).where(self.access_codes.c.code_sha256 == digest)
            ).scalar()
            if code_id is None:
                code_id = secrets.token_hex(6)
                conn.execute(
                    self.access_codes.insert().values(
                        id=code_id,
                        code_sha256=digest,
                        credits_total=2,
                        credits_used=0,
                        note="Paquete pagado con tarjeta",
                        created_at=stamp,
                        expires_at=None,
                        disabled=False,
                    )
                )
            grant = conn.execute(
                sa.select(self.credit_grants.c.code_id).where(
                    self.credit_grants.c.code_id == code_id
                )
            ).first()
            if grant is None:
                conn.execute(
                    self.credit_grants.insert().values(
                        code_id=code_id,
                        origin="purchase",
                        order_id=resolved_order_id,
                        credits=2,
                        created_at=stamp,
                    )
                )
            else:
                conn.execute(
                    self.credit_grants.update()
                    .where(self.credit_grants.c.code_id == code_id)
                    .values(origin="purchase", order_id=resolved_order_id)
                )
            owner = conn.execute(
                sa.select(self.account_audits.c.account_id).where(
                    self.account_audits.c.audit_id == audit_id
                )
            ).scalar()
            linked = conn.execute(
                sa.select(self.account_codes.c.account_id).where(
                    self.account_codes.c.code_id == code_id
                )
            ).scalar()
            if owner and linked is None:
                conn.execute(
                    self.account_codes.insert().values(
                        code_id=code_id, account_id=str(owner), linked_at=stamp
                    )
                )

        for _ in range(3):
            try:
                with self.engine.begin() as conn:
                    by_session = (
                        conn.execute(
                            sa.select(orders)
                            .where(orders.c.session_id == session_id)
                            .with_for_update()
                        )
                        .mappings()
                        .first()
                    )
                    row = by_session
                    if row is None and order_id:
                        row = (
                            conn.execute(
                                sa.select(orders).where(orders.c.id == order_id).with_for_update()
                            )
                            .mappings()
                            .first()
                        )
                        if row is None:
                            raise ValueError("unknown checkout order")
                        if row["session_id"] and row["session_id"] != session_id:
                            # Stripe's idempotency window is finite. If it
                            # returns a different *paid* session for the
                            # same order metadata, preserve the first charge
                            # and record this session as a separate order.
                            row = None
                    if row is None:
                        # Payment Links from older deployments have no order at
                        # Checkout start. Record their paid session now.
                        order_id = secrets.token_hex(16)
                        owner = conn.execute(
                            sa.select(self.account_audits.c.account_id).where(
                                self.account_audits.c.audit_id == audit_id
                            )
                        ).scalar()
                        conn.execute(
                            orders.insert().values(
                                id=order_id,
                                audit_id=audit_id,
                                account_id=str(owner or ""),
                                plan=plan,
                                amount_cents=expected_cents,
                                currency=currency,
                                status="creating",
                                session_id=session_id,
                                checkout_url="",
                                created_at=stamp,
                                expires_at=stamp,
                                paid_amount_cents=0,
                                confirmed_at="",
                                resolution="",
                                livemode=payment_livemode,
                            )
                        )
                        row = (
                            conn.execute(sa.select(orders).where(orders.c.id == order_id))
                            .mappings()
                            .one()
                        )
                    if (
                        row["audit_id"] != audit_id
                        or row["plan"] != plan
                        or int(row["amount_cents"]) != expected_cents
                        or row["currency"] != currency
                        or (row["session_id"] and row["session_id"] != session_id)
                    ):
                        raise ValueError("paid session disagrees with frozen order")
                    if (
                        row["livemode"] is not None
                        and payment_livemode is not None
                        and bool(row["livemode"]) != payment_livemode
                    ):
                        raise ValueError("paid session mode disagrees with frozen order")
                    order_id = str(row["id"])
                    if row["status"] == "duplicate":
                        original_session = conn.execute(
                            sa.select(audits.c.stripe_session_id).where(audits.c.id == audit_id)
                        ).scalar()
                        if original_session == session_id:
                            # An older deployment could have recorded a
                            # false duplicate while migrating to this ledger.
                            if plan == "pack":
                                ensure_pack(conn, order_id)
                            conn.execute(
                                orders.update()
                                .where(orders.c.id == order_id)
                                .values(status="delivered", resolution="legacy_reconciled")
                            )
                            link_payment_intent(conn, order_id)
                            queue_purchase_notice(conn, order_id, "purchase")
                            return PaymentOutcome("delivered", order_id)
                    if row["status"] in ("delivered", "duplicate"):
                        link_payment_intent(conn, order_id)
                        queue_purchase_notice(
                            conn,
                            order_id,
                            "charge_review" if row["status"] == "duplicate" else "purchase",
                        )
                        return PaymentOutcome(str(row["status"]), order_id)
                    conn.execute(
                        orders.update()
                        .where(orders.c.id == order_id)
                        .values(
                            session_id=session_id,
                            paid_amount_cents=paid_cents,
                            confirmed_at=stamp,
                            livemode=payment_livemode,
                        )
                    )
                    delivered = conn.execute(
                        audits.update()
                        .where(audits.c.id == audit_id)
                        .where(audits.c.paid.is_(False))
                        .values(paid=True, paid_at=stamp, stripe_session_id=session_id)
                    ).rowcount
                    if not delivered:
                        original_session = conn.execute(
                            sa.select(audits.c.stripe_session_id).where(audits.c.id == audit_id)
                        ).scalar()
                        if original_session == session_id:
                            # A pre-ledger report was already delivered by
                            # this exact charge. Backfill its purchase row
                            # and repair a pack code missing after a crash.
                            if plan == "pack":
                                ensure_pack(conn, order_id)
                            conn.execute(
                                orders.update()
                                .where(orders.c.id == order_id)
                                .values(status="delivered", resolution="legacy_reconciled")
                            )
                            link_payment_intent(conn, order_id)
                            queue_purchase_notice(conn, order_id, "purchase")
                            return PaymentOutcome("delivered", order_id)
                        conn.execute(
                            orders.update()
                            .where(orders.c.id == order_id)
                            .values(status="duplicate", resolution="manual_refund_review")
                        )
                        link_payment_intent(conn, order_id)
                        queue_purchase_notice(conn, order_id, "charge_review")
                        return PaymentOutcome("duplicate", order_id)
                    if plan == "pack":
                        ensure_pack(conn, order_id)
                    conn.execute(
                        orders.update()
                        .where(orders.c.id == order_id)
                        .values(status="delivered", resolution="")
                    )
                    link_payment_intent(conn, order_id)
                    queue_purchase_notice(conn, order_id, "purchase")
                    return PaymentOutcome("delivered", order_id)
            except sa.exc.IntegrityError:
                # Competing webhook inserted this session. It has either
                # committed a result or will roll back; a fresh read decides.
                continue
        raise RuntimeError("could not settle card payment")

    def settle_credit_purchase(
        self,
        *,
        order_id: str,
        session_id: str,
        account_id: str,
        plan: str,
        credits: int,
        paid_cents: int,
        code: str,
        at: datetime,
        payment_intent_id: str = "",
        payment_livemode: bool | None = None,
        queue_receipt: bool = False,
    ) -> PaymentOutcome:
        """Put a paid credit purchase on its account once, in one transaction.

        The credits go on an access code linked to the account; the code is
        derived from the session, so a Stripe retry or the return page finds
        the same code and never grants twice. Only the order frozen at
        Checkout start is accepted: a credit purchase has no legacy path.
        """
        if credits < 1 or not code:
            raise ValueError("invalid credit purchase")
        if payment_livemode is not None and type(payment_livemode) is not bool:
            raise ValueError("invalid paid session mode")
        sa, orders = self._sa, self.checkout_orders
        reference = account_order_ref(account_id)
        stamp = _iso(at)
        for _ in range(3):
            try:
                with self.engine.begin() as conn:
                    row = (
                        conn.execute(
                            sa.select(orders).where(orders.c.id == order_id).with_for_update()
                        )
                        .mappings()
                        .first()
                    )
                    if row is None:
                        raise ValueError("unknown checkout order")
                    # An account deleted after Checkout gets nothing it could
                    # never use: the charge goes to the owner's review instead.
                    if (
                        conn.execute(
                            sa.select(self.accounts.c.id).where(self.accounts.c.id == account_id)
                        ).first()
                        is None
                    ):
                        raise ValueError("credit purchase for a deleted account")
                    if (
                        row["audit_id"] != reference
                        or row["account_id"] != account_id
                        or row["plan"] != plan
                        or row["currency"] != "usd"
                        or paid_cents < int(row["amount_cents"])
                        or (row["session_id"] and row["session_id"] != session_id)
                    ):
                        raise ValueError("paid session disagrees with frozen order")
                    if (
                        row["livemode"] is not None
                        and payment_livemode is not None
                        and bool(row["livemode"]) != payment_livemode
                    ):
                        raise ValueError("paid session mode disagrees with frozen order")
                    if row["status"] != "delivered":
                        conn.execute(
                            orders.update()
                            .where(orders.c.id == order_id)
                            .values(
                                session_id=session_id,
                                paid_amount_cents=paid_cents,
                                confirmed_at=stamp,
                                livemode=payment_livemode,
                            )
                        )
                        digest = hash_access_code(code)
                        code_id = conn.execute(
                            sa.select(self.access_codes.c.id).where(
                                self.access_codes.c.code_sha256 == digest
                            )
                        ).scalar()
                        if code_id is None:
                            code_id = secrets.token_hex(6)
                            conn.execute(
                                self.access_codes.insert().values(
                                    id=code_id,
                                    code_sha256=digest,
                                    credits_total=credits,
                                    credits_used=0,
                                    note="Créditos pagados con tarjeta",
                                    created_at=stamp,
                                    expires_at=None,
                                    disabled=False,
                                )
                            )
                            conn.execute(
                                self.credit_grants.insert().values(
                                    code_id=code_id,
                                    origin="purchase",
                                    order_id=order_id,
                                    credits=credits,
                                    created_at=stamp,
                                )
                            )
                        linked = conn.execute(
                            sa.select(self.account_codes.c.account_id).where(
                                self.account_codes.c.code_id == code_id
                            )
                        ).scalar()
                        if linked is None:
                            conn.execute(
                                self.account_codes.insert().values(
                                    code_id=code_id, account_id=account_id, linked_at=stamp
                                )
                            )
                        elif linked != account_id:
                            raise ValueError("credit code on another account")
                        conn.execute(
                            orders.update()
                            .where(orders.c.id == order_id)
                            .values(status="delivered", resolution="")
                        )
                    self.record_payment_intent_in_tx(
                        conn,
                        order_id,
                        session_id,
                        payment_intent_id,
                        at,
                        livemode=payment_livemode,
                    )
                    if queue_receipt:
                        self._queue_purchase_notice_in_tx(conn, order_id, "purchase", at)
                    return PaymentOutcome("delivered", order_id)
            except sa.exc.IntegrityError:
                # A competing webhook settled this order; a fresh read decides.
                continue
        raise RuntimeError("could not settle credit purchase")

    def list_checkout_orders(self, limit: int = 50) -> list[CheckoutOrder]:
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    self._sa.select(self.checkout_orders)
                    .order_by(self.checkout_orders.c.created_at.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return [self._checkout_order(row) for row in rows]

    def record_payment_intent_in_tx(
        self,
        conn: Any,
        order_id: str,
        session_id: str,
        pi_id: str,
        at: datetime,
        *,
        livemode: bool | None = None,
    ) -> None:
        """Bind a paid Checkout session to its PaymentIntent in the settlement transaction."""
        if not pi_id:
            return  # older Checkout payloads may not carry this field
        if not _stripe_object_id(pi_id, "pi_"):
            raise ValueError("invalid payment intent id")
        sa, links = self._sa, self.stripe_payment_intents
        prior = conn.execute(
            sa.select(links.c.order_id, links.c.session_id, links.c.livemode).where(
                links.c.payment_intent_id == pi_id
            )
        ).first()
        if prior is None:
            conn.execute(
                links.insert().values(
                    payment_intent_id=pi_id,
                    order_id=order_id,
                    session_id=session_id,
                    livemode=livemode,
                    recorded_at=_iso(at),
                )
            )
        elif str(prior[0]) != order_id or str(prior[1]) != session_id:
            raise ValueError("payment intent belongs to another order")
        elif prior[2] is not None and livemode is not None and bool(prior[2]) != livemode:
            raise ValueError("payment intent mode disagrees with order")
        elif prior[2] is None and livemode is not None:
            conn.execute(
                links.update().where(links.c.payment_intent_id == pi_id).values(livemode=livemode)
            )
        refunds = self.stripe_refunds
        if livemode is not None:
            conn.execute(
                refunds.update()
                .where(refunds.c.payment_intent_id == pi_id)
                .where(refunds.c.livemode == livemode)
                .where(refunds.c.order_id == "")
                .values(order_id=order_id)
            )

    @staticmethod
    def _stripe_refund(row: Any) -> StripeRefundRecord:
        return StripeRefundRecord(
            refund_id=str(row["refund_id"]),
            payment_intent_id=str(row["payment_intent_id"]),
            charge_id=str(row["charge_id"]),
            order_id=str(row["order_id"]),
            amount_minor=int(row["amount_minor"]),
            currency=str(row["currency"]),
            status=str(row["status"]),
            livemode=bool(row["livemode"]),
            first_seen_at=str(row["first_seen_at"]),
            last_seen_at=str(row["last_seen_at"]),
        )

    def record_stripe_refund(
        self,
        *,
        refund_id: str,
        payment_intent_id: str,
        charge_id: str,
        amount_minor: int,
        currency: str,
        status: str,
        livemode: bool,
        event_id: str,
        at: datetime,
    ) -> StripeRefundRecord:
        """Keep one signed snapshot per refund, robust to retries and stale events.

        A card refund can go from succeeded to failed. Failed and canceled
        therefore supersede earlier succeeded snapshots, while a late pending
        or succeeded snapshot can never undo a known failure. Conflicting
        immutable fields or terminal states need manual review and count zero.
        """
        if not _stripe_object_id(refund_id, "re_") or not _stripe_object_id(event_id, "evt_"):
            raise ValueError("invalid Stripe refund or event id")
        if not (
            (_stripe_object_id(payment_intent_id, "pi_") if payment_intent_id else True)
            and (_stripe_object_id(charge_id, "ch_") if charge_id else True)
            and (payment_intent_id or charge_id)
        ):
            raise ValueError("invalid Stripe payment reference")
        if (
            isinstance(amount_minor, bool)
            or not isinstance(amount_minor, int)
            or amount_minor < 1
            or len(currency) != 3
            or not currency.isascii()
            or not currency.isalpha()
            or currency.lower() != currency
            or type(livemode) is not bool
            or status not in ("pending", "requires_action", "succeeded", "failed", "canceled")
        ):
            raise ValueError("invalid Stripe refund data")
        table, links, sa = self.stripe_refunds, self.stripe_payment_intents, self._sa
        stamp = _iso(at)
        rank = {
            "pending": 0,
            "requires_action": 0,
            "succeeded": 1,
            "failed": 2,
            "canceled": 2,
            "review": 3,
        }
        for _ in range(3):
            try:
                with self.engine.begin() as conn:
                    order_id = ""
                    if payment_intent_id:
                        mapped = conn.execute(
                            sa.select(links.c.order_id, links.c.livemode).where(
                                links.c.payment_intent_id == payment_intent_id
                            )
                        ).first()
                        if (
                            mapped is not None
                            and mapped[1] is not None
                            and bool(mapped[1]) == livemode
                        ):
                            order_id = str(mapped[0])
                    prior = (
                        conn.execute(
                            sa.select(table).where(table.c.refund_id == refund_id).with_for_update()
                        )
                        .mappings()
                        .first()
                    )
                    if prior is None:
                        conn.execute(
                            table.insert().values(
                                refund_id=refund_id,
                                payment_intent_id=payment_intent_id,
                                charge_id=charge_id,
                                order_id=order_id,
                                amount_minor=amount_minor,
                                currency=currency,
                                status=status,
                                livemode=livemode,
                                first_seen_at=stamp,
                                last_seen_at=stamp,
                                succeeded_at=stamp if status == "succeeded" else "",
                                event_id=event_id,
                            )
                        )
                    else:
                        previous_status = str(prior["status"])
                        pi = str(prior["payment_intent_id"] or payment_intent_id)
                        charge = str(prior["charge_id"] or charge_id)
                        linked_order = str(prior["order_id"] or order_id)
                        conflict = (
                            int(prior["amount_minor"]) != amount_minor
                            or str(prior["currency"]) != currency
                            or bool(prior["livemode"]) != livemode
                            or bool(
                                prior["payment_intent_id"]
                                and payment_intent_id
                                and prior["payment_intent_id"] != payment_intent_id
                            )
                            or bool(
                                prior["charge_id"] and charge_id and prior["charge_id"] != charge_id
                            )
                            or bool(
                                prior["order_id"] and order_id and prior["order_id"] != order_id
                            )
                            or (
                                rank[previous_status] == rank[status] == 2
                                and previous_status != status
                            )
                        )
                        next_status = (
                            "review"
                            if conflict
                            else status
                            if rank[status] > rank[previous_status]
                            else previous_status
                        )
                        conn.execute(
                            table.update()
                            .where(table.c.refund_id == refund_id)
                            .values(
                                payment_intent_id=pi,
                                charge_id=charge,
                                order_id=linked_order,
                                status=next_status,
                                last_seen_at=stamp,
                                succeeded_at=(
                                    str(prior["succeeded_at"] or stamp)
                                    if next_status == "succeeded"
                                    else str(prior["succeeded_at"] or "")
                                ),
                                event_id=event_id,
                            )
                        )
                    saved = (
                        conn.execute(sa.select(table).where(table.c.refund_id == refund_id))
                        .mappings()
                        .one()
                    )
                    return self._stripe_refund(saved)
            except sa.exc.IntegrityError:
                continue  # another worker inserted the refund first
        raise RuntimeError("could not record Stripe refund")

    def list_stripe_refunds(self, limit: int = 50) -> list[StripeRefundRecord]:
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    self._sa.select(self.stripe_refunds)
                    .order_by(self.stripe_refunds.c.last_seen_at.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return [self._stripe_refund(row) for row in rows]

    def redeem_for_audit(self, audit_id: str, code: str, *, at: datetime) -> bool:
        """Unlock an existing unpaid audit with one credit of ``code``.

        Both updates share one transaction: a credit is spent only when the
        audit flips to paid, and an already paid audit spends nothing.
        """
        if not _usable_key(audit_id):
            return False
        try:
            with self.engine.begin() as conn:
                unpaid = conn.execute(
                    self._sa.select(self.audits.c.id)
                    .where(self.audits.c.id == audit_id)
                    .where(self.audits.c.paid.is_(False))
                ).first()
                if unpaid is None:
                    return False
                code_id = self._redeem(conn, code, at=at)
                if code_id is None:
                    return False
                result = conn.execute(
                    self.audits.update()
                    .where(self.audits.c.id == audit_id)
                    .where(self.audits.c.paid.is_(False))
                    .values(
                        paid=True,
                        paid_at=_iso(at),
                        stripe_session_id=CODE_REFERENCE_PREFIX + code_id,
                    )
                )
                if not result.rowcount:
                    raise _RedeemRace()
                return True
        except _RedeemRace:  # pragma: no cover - lost a race; the credit rolled back
            return False

    def count_uploads_since(self, client_ip: str, since: datetime) -> int:
        sa = self._sa
        with self.engine.connect() as conn:
            value = conn.execute(
                sa.select(sa.func.count())
                .select_from(self.audits)
                .where(self.audits.c.client_ip == client_ip)
                .where(self.audits.c.created_at >= _iso(since))
            ).scalar()
        return int(value or 0)

    def count_audits(self) -> int:
        sa = self._sa
        with self.engine.connect() as conn:
            value = conn.execute(sa.select(sa.func.count()).select_from(self.audits)).scalar()
        return int(value or 0)

    def count_completed_audits(self, *, excluded_ids: Sequence[str] = ()) -> int:
        """Completed, explicitly eligible uploads still present in this store.

        No result payload is fetched. The reserved sample id and supplied
        operator test ids are excluded even if accidentally marked eligible.
        A purged eligible audit remains completed; a deleted audit contributes
        nothing. Legacy rows without provenance are deliberately not counted.
        """
        sa, audits = self._sa, self.audits
        eligible = self.audit_count_eligibility
        completed = sa.or_(
            sa.and_(audits.c.result_json != "", audits.c.report_html != ""),
            audits.c.purged_at.is_not(None),
        )
        statement = (
            sa.select(sa.func.count())
            .select_from(audits.join(eligible, eligible.c.audit_id == audits.c.id))
            .where(audits.c.id != "sample")
            .where(audits.c.overall_class.in_(("A", "B", "C", "D")))
            .where(completed)
        )
        if excluded_ids:
            statement = statement.where(audits.c.id.not_in(tuple(excluded_ids)))
        with self.engine.connect() as conn:
            value = conn.execute(statement).scalar()
        return int(value or 0)

    # -- access codes ------------------------------------------------------
    def create_access_code(
        self,
        *,
        credits: int,
        note: str,
        at: datetime,
        expires_days: int | None = None,
    ) -> tuple[str, AccessCodeRecord]:
        """A new code and its record. The clear code exists only in the
        return value: print it once and hand it to the client."""
        if credits < 1:
            raise ValueError("credits must be at least 1")
        if expires_days is not None and expires_days < 1:
            raise ValueError("expires_days must be at least 1")
        code = new_access_code()
        code_id = secrets.token_hex(6)
        expires = _iso(at + timedelta(days=expires_days)) if expires_days else None
        with self.engine.begin() as conn:
            conn.execute(
                self.access_codes.insert().values(
                    id=code_id,
                    code_sha256=hash_access_code(code),
                    credits_total=credits,
                    credits_used=0,
                    note=note,
                    created_at=_iso(at),
                    expires_at=expires,
                    disabled=False,
                )
            )
            conn.execute(
                self.credit_grants.insert().values(
                    code_id=code_id,
                    origin="unknown",
                    order_id="",
                    credits=credits,
                    created_at=_iso(at),
                )
            )
        record = AccessCodeRecord(
            id=code_id,
            note=note,
            credits_total=credits,
            credits_used=0,
            created_at=_iso(at),
            expires_at=expires,
            disabled=False,
        )
        return code, record

    def ensure_access_code(self, code: str, *, credits: int, note: str, at: datetime) -> bool:
        """Store the hash of a code made elsewhere (a card-paid pack) once.

        ``True`` when it was added, ``False`` when it already existed.
        """
        if credits < 1:
            raise ValueError("credits must be at least 1")
        digest = hash_access_code(code)
        sa = self._sa
        try:
            with self.engine.begin() as conn:
                exists = conn.execute(
                    sa.select(self.access_codes.c.id).where(
                        self.access_codes.c.code_sha256 == digest
                    )
                ).first()
                if exists is not None:
                    return False
                conn.execute(
                    self.access_codes.insert().values(
                        id=secrets.token_hex(6),
                        code_sha256=digest,
                        credits_total=credits,
                        credits_used=0,
                        note=note,
                        created_at=_iso(at),
                        expires_at=None,
                        disabled=False,
                    )
                )
                code_id = conn.execute(
                    sa.select(self.access_codes.c.id).where(
                        self.access_codes.c.code_sha256 == digest
                    )
                ).scalar_one()
                conn.execute(
                    self.credit_grants.insert().values(
                        code_id=str(code_id),
                        origin="unknown",
                        order_id="",
                        credits=credits,
                        created_at=_iso(at),
                    )
                )
                return True
        except sa.exc.IntegrityError:  # pragma: no cover - lost a race to the same insert
            return False

    def get_access_code(self, code: str) -> AccessCodeRecord | None:
        """The record for ``code`` (looked up by hash), or ``None``."""
        if not normalise_access_code(code):
            return None
        table = self.access_codes
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    self._sa.select(table).where(table.c.code_sha256 == hash_access_code(code))
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return AccessCodeRecord(
            id=row["id"],
            note=row["note"],
            credits_total=int(row["credits_total"]),
            credits_used=int(row["credits_used"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            disabled=bool(row["disabled"]),
        )

    # -- refused card payments ------------------------------------------------
    def record_refused_payment(
        self, *, session_id: str, audit_id: str, reason: str, at: datetime
    ) -> bool:
        """Keep a charged payment that unlocked nothing, once per session."""
        sa = self._sa
        try:
            with self.engine.begin() as conn:
                table = self.refused_payments
                exists = conn.execute(
                    sa.select(table.c.session_id).where(table.c.session_id == session_id)
                ).first()
                if exists is not None:
                    return False
                conn.execute(
                    table.insert().values(
                        session_id=session_id[:255],
                        audit_id=audit_id[:80],
                        reason=reason[:80],
                        created_at=_iso(at),
                    )
                )
                return True
        except sa.exc.IntegrityError:  # pragma: no cover - lost a race to the same insert
            return False

    def list_refused_payments(self, limit: int = 50) -> list[RefusedPayment]:
        """The newest refused payments first."""
        table = self.refused_payments
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    self._sa.select(table)
                    .order_by(table.c.created_at.desc(), table.c.session_id)
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return [
            RefusedPayment(
                session_id=row["session_id"],
                audit_id=row["audit_id"],
                reason=row["reason"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def list_access_codes(self) -> list[AccessCodeRecord]:
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    self._sa.select(self.access_codes).order_by(
                        self.access_codes.c.created_at, self.access_codes.c.id
                    )
                )
                .mappings()
                .all()
            )
        return [
            AccessCodeRecord(
                id=row["id"],
                note=row["note"],
                credits_total=int(row["credits_total"]),
                credits_used=int(row["credits_used"]),
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                disabled=bool(row["disabled"]),
            )
            for row in rows
        ]

    def disable_access_code(self, code_id: str) -> bool:
        if not _usable_key(code_id):
            return False
        with self.engine.begin() as conn:
            result = conn.execute(
                self.access_codes.update()
                .where(self.access_codes.c.id == code_id)
                .where(self.access_codes.c.disabled.is_(False))
                .values(disabled=True)
            )
            return bool(result.rowcount)

    def _redeem(self, conn: Any, code: str, *, at: datetime) -> str | None:
        """Spend one credit inside ``conn``'s transaction; the code's id or ``None``.

        The conditions live in the ``UPDATE`` itself, so the check and the
        spend are one statement: no read-then-write window.
        """
        if not normalise_access_code(code):
            return None
        table = self.access_codes
        digest = hash_access_code(code)
        now = _iso(at)
        condition = (
            (table.c.code_sha256 == digest)
            & (table.c.credits_used < table.c.credits_total)
            & (table.c.disabled.is_(False))
            & ((table.c.expires_at.is_(None)) | (table.c.expires_at > now))
        )
        result = conn.execute(
            table.update().where(condition).values(credits_used=table.c.credits_used + 1)
        )
        if not result.rowcount:
            return None
        row = conn.execute(self._sa.select(table.c.id).where(table.c.code_sha256 == digest)).first()
        return str(row[0]) if row else None

    # -- publications ------------------------------------------------------
    def publish(self, audit_id: str, *, at: datetime) -> PublicationRecord:
        """The audit's publication, created on first call (idempotent)."""
        existing = self.publication_for_audit(audit_id)
        if existing is not None:
            return existing
        # Always 12 characters of A-Z a-z 0-9 _ - (9 random bytes in base64url), so
        # never one of the public samples' reserved ids, "ejemplo" (7) and
        # "ejemplo-senal" (13): /v answers those before any lookup
        # (sample_publication.SAMPLE_PUBLIC_IDS).
        public_id = secrets.token_urlsafe(9)
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    self.publications.insert().values(
                        public_id=public_id, audit_id=audit_id, created_at=_iso(at)
                    )
                )
        except self._sa.exc.IntegrityError:
            # A concurrent publish won; return its row.
            winner = self.publication_for_audit(audit_id)
            if winner is None:  # pragma: no cover - the constraint says it exists
                raise
            return winner
        return PublicationRecord(public_id=public_id, audit_id=audit_id, created_at=_iso(at))

    def unpublish(self, audit_id: str) -> bool:
        if not _usable_key(audit_id):
            return False
        with self.engine.begin() as conn:
            conn.execute(
                self.publication_views.delete().where(self.publication_views.c.audit_id == audit_id)
            )
            result = conn.execute(
                self.publications.delete().where(self.publications.c.audit_id == audit_id)
            )
            return bool(result.rowcount)

    def publication_for_audit(self, audit_id: str) -> PublicationRecord | None:
        if not _usable_key(audit_id):
            return None
        return self._publication(self.publications.c.audit_id == audit_id)

    def publication_view(self, audit_id: str) -> tuple[dict[str, Any], str] | None:
        """``(view, result_sha256)`` kept for a purged, published audit."""
        if not _usable_key(audit_id):
            return None
        sa = self._sa
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(
                    self.publication_views.c.view_json, self.publication_views.c.result_sha256
                ).where(self.publication_views.c.audit_id == audit_id)
            ).first()
        if row is None:
            return None
        return json.loads(row[0]), str(row[1])

    def get_publication(self, public_id: str) -> PublicationRecord | None:
        if not _usable_key(public_id):
            return None
        return self._publication(self.publications.c.public_id == public_id)

    def _publication(self, condition: Any) -> PublicationRecord | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(self._sa.select(self.publications).where(condition)).mappings().first()
            )
        if row is None:
            return None
        return PublicationRecord(
            public_id=row["public_id"], audit_id=row["audit_id"], created_at=row["created_at"]
        )

    # -- waitlist ----------------------------------------------------------
    def add_waitlist(self, email: str, *, at: datetime, note: str = "") -> bool:
        """Insert an e-mail once; a repeat is not an error and returns ``False``."""
        sa = self._sa
        clean = email.strip().lower()
        with self.engine.begin() as conn:
            exists = conn.execute(
                sa.select(self.waitlist.c.id).where(self.waitlist.c.email == clean)
            ).first()
            if exists:
                return False
            conn.execute(self.waitlist.insert().values(email=clean, created_at=_iso(at), note=note))
            return True

    def remove_waitlist(self, email: str, *, dry_run: bool = False) -> bool:
        """Remove an e-mail from the waitlist (a privacy request). ``True`` if it was there."""
        sa = self._sa
        condition = self.waitlist.c.email == email.strip().lower()
        with self.engine.begin() as conn:
            exists = conn.execute(sa.select(self.waitlist.c.id).where(condition)).first()
            if exists and not dry_run:
                conn.execute(self.waitlist.delete().where(condition))
        return exists is not None

    def waitlist_emails(self) -> list[str]:
        sa = self._sa
        with self.engine.connect() as conn:
            rows = conn.execute(sa.select(self.waitlist.c.email).order_by(self.waitlist.c.id)).all()
        return [row[0] for row in rows]

    # -- issued report files ---------------------------------------------
    def record_issued(self, content: bytes, *, audit_id: str, kind: str, at: datetime) -> str:
        """Remember the SHA-256 of a file handed out; the first issue date wins."""
        digest = hashlib.sha256(content).hexdigest()
        with self.engine.begin() as conn:
            known = conn.execute(
                self._sa.select(self.issued_files.c.sha256).where(
                    self.issued_files.c.sha256 == digest
                )
            ).first()
            if known is not None:
                return digest
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    self.issued_files.insert().values(
                        sha256=digest, audit_id=audit_id, kind=kind, issued_at=_iso(at)
                    )
                )
        except self._sa.exc.IntegrityError:  # two downloads of the same bytes at once
            pass
        return digest

    def find_issued(self, digest: str) -> IssuedFile | None:
        """The issued file with this SHA-256, with its audit's class and public id."""
        sa = self._sa
        if len(digest) != 64:
            return None
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(
                    self.issued_files.c.audit_id,
                    self.issued_files.c.kind,
                    self.issued_files.c.issued_at,
                    self.audits.c.overall_class,
                    self.publications.c.public_id,
                )
                .select_from(
                    self.issued_files.outerjoin(
                        self.audits, self.audits.c.id == self.issued_files.c.audit_id
                    ).outerjoin(
                        self.publications,
                        self.publications.c.audit_id == self.issued_files.c.audit_id,
                    )
                )
                .where(self.issued_files.c.sha256 == digest)
            ).first()
        if row is None:
            return None
        return IssuedFile(
            audit_id=row[0],
            kind=row[1],
            issued_at=row[2],
            overall_class=row[3],
            public_id=row[4],
        )

    # -- deletion on request ---------------------------------------------
    def delete_audit(self, audit_id: str) -> bool:
        """Remove one audit, its files and private links.

        Unlike the retention purge nothing verifiable is kept: this answers a
        client's deletion request. Charged order ids and amounts stay for
        accounting, but their report/account references are removed.
        ``False`` when the id is unknown.
        """
        if not _usable_key(audit_id):
            return False
        with self.engine.begin() as conn:
            conn.execute(
                self.checkout_orders.update()
                .where(self.checkout_orders.c.audit_id == audit_id)
                .values(audit_id="", account_id="", checkout_url="")
            )
            conn.execute(
                self.checkout_slots.delete().where(self.checkout_slots.c.audit_id == audit_id)
            )
            conn.execute(
                self.refused_payments.update()
                .where(self.refused_payments.c.audit_id == audit_id)
                .values(audit_id="")
            )
            conn.execute(self.publications.delete().where(self.publications.c.audit_id == audit_id))
            conn.execute(
                self.publication_views.delete().where(self.publication_views.c.audit_id == audit_id)
            )
            conn.execute(self.audit_files.delete().where(self.audit_files.c.audit_id == audit_id))
            conn.execute(
                self.audit_count_eligibility.delete().where(
                    self.audit_count_eligibility.c.audit_id == audit_id
                )
            )
            conn.execute(self.issued_files.delete().where(self.issued_files.c.audit_id == audit_id))
            conn.execute(
                self.account_audits.delete().where(self.account_audits.c.audit_id == audit_id)
            )
            conn.execute(
                self.strategy_reports.delete().where(self.strategy_reports.c.audit_id == audit_id)
            )
            conn.execute(
                self.welcome_pending.delete().where(self.welcome_pending.c.audit_id == audit_id)
            )
            conn.execute(
                self.anon_previews.delete().where(self.anon_previews.c.audit_id == audit_id)
            )
            store_hooks.on_delete_audit(self, conn, audit_id)
            deleted = conn.execute(self.audits.delete().where(self.audits.c.id == audit_id))
        return bool(deleted.rowcount)

    # -- accounts ----------------------------------------------------------
    def create_account(
        self,
        *,
        email: str,
        password_hash: str,
        locale: str,
        at: datetime,
        email_confirmation: bool = False,
    ) -> AccountRecord | None:
        """A new account, or ``None`` when that e-mail already has one."""
        sa = self._sa
        account_id = secrets.token_hex(8)
        try:
            with self.engine.begin() as conn:
                taken = conn.execute(
                    sa.select(self.accounts.c.id).where(self.accounts.c.email == email)
                ).first()
                if taken is not None:
                    return None
                conn.execute(
                    self.accounts.insert().values(
                        id=account_id,
                        email=email,
                        password_hash=password_hash,
                        locale=locale,
                        created_at=_iso(at),
                    )
                )
                if email_confirmation:
                    self._enqueue_email(
                        conn, account_id, "verify", email, email, locale, at, hours=24
                    )
        except sa.exc.IntegrityError:  # pragma: no cover - lost a race to the same e-mail
            return None
        return AccountRecord(id=account_id, email=email, locale=locale, created_at=_iso(at))

    def _account(self, condition: Any) -> tuple[AccountRecord, str] | None:
        with self.engine.connect() as conn:
            row = conn.execute(self._sa.select(self.accounts).where(condition)).mappings().first()
        if row is None:
            return None
        record = AccountRecord(
            id=row["id"], email=row["email"], locale=row["locale"], created_at=row["created_at"]
        )
        return record, str(row["password_hash"])

    def account_with_hash(self, email: str) -> tuple[AccountRecord, str] | None:
        """The account for ``email`` and its password hash, for sign-in only."""
        if not _usable_key(email):
            return None
        return self._account(self.accounts.c.email == email)

    def get_account(self, account_id: str) -> AccountRecord | None:
        if not _usable_key(account_id):
            return None
        found = self._account(self.accounts.c.id == account_id)
        return found[0] if found else None

    def password_hash(self, account_id: str) -> str | None:
        found = self._account(self.accounts.c.id == account_id)
        return found[1] if found else None

    def find_account(self, email: str) -> AccountRecord | None:
        found = self.account_with_hash(email)
        return found[0] if found else None

    def set_password(self, account_id: str, password_hash: str) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(
                self.accounts.update()
                .where(self.accounts.c.id == account_id)
                .values(password_hash=password_hash)
            )
        return bool(result.rowcount)

    def set_email(self, account_id: str, email: str) -> bool:
        """Move an account to a new sign-in e-mail; ``False`` when another account has it."""
        sa = self._sa
        try:
            with self.engine.begin() as conn:
                taken = conn.execute(
                    sa.select(self.accounts.c.id).where(
                        (self.accounts.c.email == email) & (self.accounts.c.id != account_id)
                    )
                ).first()
                if taken is not None:
                    return False
                result = conn.execute(
                    self.accounts.update()
                    .where(self.accounts.c.id == account_id)
                    .values(email=email)
                )
        except sa.exc.IntegrityError:  # pragma: no cover - lost a race to the same e-mail
            return False
        return bool(result.rowcount)

    # -- institutional prospects ------------------------------------------
    def add_institutional_request(
        self,
        *,
        name: str,
        organization: str,
        email: str,
        strategy_type: str,
        frequency: str,
        history_years: str,
        has_benchmark: bool,
        variants: int,
        description: str,
        claim_findings: list[dict[str, Any]],
        locale: str,
        ref: str,
        at: datetime,
        notification_email: str = "",
    ) -> str:
        """Save a validated request and its operator notice in one transaction.

        The caller supplies the configured operator address only when existing
        mail delivery is ready. Missing mail configuration never loses a lead.
        The outbox carries no prospect text: delivery reads four allowed fields.
        """
        request_id = secrets.token_hex(16)
        stamp = _iso(at)
        with self.engine.begin() as conn:
            conn.execute(
                self.institutional_requests.insert().values(
                    id=request_id,
                    created_at=stamp,
                    name=name,
                    organization=organization,
                    email=email,
                    strategy_type=strategy_type,
                    frequency=frequency,
                    history_years=history_years,
                    has_benchmark=has_benchmark,
                    variants=variants,
                    description=description,
                    claim_findings_json=json.dumps(claim_findings, ensure_ascii=False),
                    locale=locale,
                    ref=ref,
                    contacted_at="",
                )
            )
            if notification_email:
                conn.execute(
                    self.email_outbox.insert().values(
                        id=request_id,
                        account_id="",
                        kind="institutional",
                        email=notification_email,
                        original_email="",
                        locale="es",
                        created_at=stamp,
                        expires_at=_iso(at + timedelta(days=7)),
                        used_at=None,
                        status="queued",
                        attempts=0,
                        next_attempt_at=stamp,
                        lease_until="",
                        sent_at="",
                    )
                )
        return request_id

    def list_institutional_requests(self, limit: int = 100) -> list[InstitutionalRequest]:
        """Newest private requests first, for the authenticated owner panel."""
        table = self.institutional_requests
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    self._sa.select(table)
                    .order_by(table.c.created_at.desc(), table.c.id.desc())
                    .limit(max(0, min(limit, 1000)))
                )
                .mappings()
                .all()
            )
        records = []
        for row in rows:
            values = dict(row)
            values["claim_findings"] = json.loads(values.pop("claim_findings_json"))
            records.append(InstitutionalRequest(**values))
        return records

    def mark_institutional_contacted(self, request_id: str, *, at: datetime) -> bool:
        """Mark an existing request once; repeated clicks keep the first date."""
        if len(request_id) != 32 or any(ch not in "0123456789abcdef" for ch in request_id):
            return False
        table = self.institutional_requests
        with self.engine.begin() as conn:
            result = conn.execute(
                table.update()
                .where(table.c.id == request_id)
                .where(table.c.contacted_at == "")
                .values(contacted_at=_iso(at))
            )
            if result.rowcount:
                return True
            return (
                conn.execute(self._sa.select(table.c.id).where(table.c.id == request_id)).first()
                is not None
            )

    # -- verified email and durable delivery ------------------------------
    def _enqueue_email(
        self,
        conn: Any,
        account_id: str,
        kind: str,
        email: str,
        original_email: str,
        locale: str,
        at: datetime,
        *,
        hours: int,
    ) -> str:
        """Queue one challenge inside the caller's transaction.

        Repeated requests reuse its id/token until expiry. A sent challenge
        can be resent after ten minutes, without changing the token: the
        resend is a new message with its own retries (``attempts`` starts
        again), and ``sent_at`` keeps the last delivery so the message gets
        its own Message-ID (``mail.message_key``).
        """
        sa, table = self._sa, self.email_outbox
        now = _iso(at)
        existing = (
            conn.execute(
                sa.select(table)
                .where(table.c.account_id == account_id)
                .where(table.c.kind == kind)
                .where(table.c.email == email)
                .where(table.c.used_at.is_(None))
                .where(table.c.expires_at > now)
                .where(table.c.status != "dead")
                .order_by(table.c.created_at.desc())
            )
            .mappings()
            .first()
        )
        if existing is not None:
            resend = existing["status"] == "sent" and str(existing["sent_at"]) < _iso(
                at - timedelta(minutes=10)
            )
            # Queued with its tries used up: an earlier resend that kept the
            # old count and was never claimed again. The same for a last try
            # whose worker stopped: its lease ran out and nobody takes it.
            stalled = int(existing["attempts"]) >= 8 and (
                existing["status"] == "queued"
                or (existing["status"] == "sending" and str(existing["lease_until"]) < now)
            )
            if resend or stalled:
                conn.execute(
                    table.update()
                    .where(table.c.id == existing["id"])
                    .where(table.c.status == existing["status"])
                    .values(status="queued", attempts=0, next_attempt_at=now, lease_until="")
                )
            return str(existing["id"])
        challenge_id = secrets.token_hex(16)
        conn.execute(
            table.insert().values(
                id=challenge_id,
                account_id=account_id,
                kind=kind,
                email=email,
                original_email=original_email,
                locale=locale,
                created_at=now,
                expires_at=_iso(at + timedelta(hours=hours)),
                used_at=None,
                status="queued",
                attempts=0,
                next_attempt_at=now,
                lease_until="",
                sent_at="",
            )
        )
        return challenge_id

    def email_verified(self, account_id: str) -> bool:
        sa = self._sa
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(self.verified_emails.c.account_id)
                .select_from(
                    self.verified_emails.join(
                        self.accounts,
                        self.accounts.c.id == self.verified_emails.c.account_id,
                    )
                )
                .where(self.verified_emails.c.account_id == account_id)
                .where(self.verified_emails.c.email == self.accounts.c.email)
            ).first()
        return row is not None

    def pending_email_change(self, account_id: str, now: datetime) -> str:
        table = self.email_outbox
        with self.engine.connect() as conn:
            row = conn.execute(
                self._sa.select(table.c.email)
                .where(table.c.account_id == account_id)
                .where(table.c.kind == "change")
                .where(table.c.used_at.is_(None))
                .where(table.c.expires_at > _iso(now))
                .order_by(table.c.created_at.desc())
            ).first()
        return str(row[0]) if row else ""

    def request_email_verification(self, account_id: str, *, at: datetime) -> str:
        with self.engine.begin() as conn:
            row = conn.execute(
                self._sa.select(self.accounts.c.email, self.accounts.c.locale).where(
                    self.accounts.c.id == account_id
                )
            ).first()
            if row is None:
                return ""
            verified = conn.execute(
                self._sa.select(self.verified_emails.c.account_id)
                .where(self.verified_emails.c.account_id == account_id)
                .where(self.verified_emails.c.email == row[0])
            ).first()
            if verified is not None:
                return ""
            return self._enqueue_email(
                conn, account_id, "verify", str(row[0]), str(row[0]), str(row[1]), at, hours=24
            )

    def request_email_change(
        self, account_id: str, email: str, *, locale: str, at: datetime
    ) -> str:
        """Return ``pending``, ``same``, ``taken`` or ``missing``."""
        sa = self._sa
        with self.engine.begin() as conn:
            current = conn.execute(
                sa.select(self.accounts.c.email).where(self.accounts.c.id == account_id)
            ).scalar()
            if current is None:
                return "missing"
            if current == email:
                return "same"
            taken = conn.execute(
                sa.select(self.accounts.c.id).where(self.accounts.c.email == email)
            ).first()
            if taken is not None:
                return "taken"
            table = self.email_outbox
            conn.execute(
                table.update()
                .where(table.c.account_id == account_id)
                .where(table.c.kind == "change")
                .where(table.c.email != email)
                .where(table.c.used_at.is_(None))
                .values(used_at=_iso(at), status="dead")
            )
            self._enqueue_email(
                conn, account_id, "change", email, str(current), locale, at, hours=24
            )
        return "pending"

    def request_email_reset(self, email: str, *, locale: str, at: datetime) -> str:
        """Queue a reset only for a verified address; return empty for all others."""
        account = self.find_account(email)
        if account is None or not self.email_verified(account.id):
            return ""
        with self.engine.begin() as conn:
            return self._enqueue_email(conn, account.id, "reset", email, email, locale, at, hours=1)

    def email_confirmation_available(self, challenge_id: str, at: datetime) -> bool:
        """Read-only check for a preview-safe confirmation GET."""
        table = self.email_outbox
        with self.engine.connect() as conn:
            row = conn.execute(
                self._sa.select(table.c.id)
                .where(table.c.id == challenge_id)
                .where(table.c.kind.in_(("verify", "change")))
                .where(table.c.used_at.is_(None))
                .where(table.c.expires_at > _iso(at))
                .where(table.c.status != "dead")
            ).first()
        return row is not None

    def confirm_email_challenge(self, challenge_id: str, *, at: datetime) -> tuple[str, str] | None:
        """Atomically confirm current/change email once after HMAC validation."""
        sa, table = self._sa, self.email_outbox
        now = _iso(at)
        try:
            with self.engine.begin() as conn:
                row = (
                    conn.execute(
                        sa.select(table).where(table.c.id == challenge_id).with_for_update()
                    )
                    .mappings()
                    .first()
                )
                if (
                    row is None
                    or row["kind"] not in ("verify", "change")
                    or row["used_at"] is not None
                    or row["expires_at"] <= now
                    or row["status"] == "dead"
                ):
                    return None
                account_id = str(row["account_id"])
                if row["kind"] == "change":
                    changed = conn.execute(
                        self.accounts.update()
                        .where(self.accounts.c.id == account_id)
                        .where(self.accounts.c.email == row["original_email"])
                        .values(email=row["email"])
                    )
                    if not changed.rowcount:
                        return None
                else:
                    current = conn.execute(
                        sa.select(self.accounts.c.email).where(self.accounts.c.id == account_id)
                    ).scalar()
                    if current != row["email"]:
                        return None
                conn.execute(
                    self.verified_emails.delete().where(
                        self.verified_emails.c.account_id == account_id
                    )
                )
                conn.execute(
                    self.verified_emails.insert().values(
                        account_id=account_id, email=row["email"], verified_at=now
                    )
                )
                conn.execute(
                    table.update()
                    .where(table.c.id == challenge_id)
                    .where(table.c.used_at.is_(None))
                    .values(used_at=now)
                )
                return str(row["kind"]), account_id
        except sa.exc.IntegrityError:
            return None

    def consume_email_reset(
        self, challenge_id: str, password_hash: str, *, at: datetime
    ) -> str | None:
        """Use a reset token and change password/revoke sessions in one commit."""
        sa, table = self._sa, self.email_outbox
        now = _iso(at)
        with self.engine.begin() as conn:
            row = (
                conn.execute(sa.select(table).where(table.c.id == challenge_id).with_for_update())
                .mappings()
                .first()
            )
            if (
                row is None
                or row["kind"] != "reset"
                or row["used_at"] is not None
                or row["expires_at"] <= now
                or row["status"] == "dead"
            ):
                return None
            account_id = str(row["account_id"])
            changed = conn.execute(
                self.accounts.update()
                .where(self.accounts.c.id == account_id)
                .where(self.accounts.c.email == row["email"])
                .values(password_hash=password_hash)
            )
            if not changed.rowcount:
                return None
            conn.execute(
                self.account_sessions.delete().where(
                    self.account_sessions.c.account_id == account_id
                )
            )
            conn.execute(
                self.session_info.delete().where(self.session_info.c.account_id == account_id)
            )
            conn.execute(
                table.update()
                .where(table.c.id == challenge_id)
                .where(table.c.used_at.is_(None))
                .values(used_at=now)
            )
            return account_id

    def email_reset_account(self, challenge_id: str, now: datetime) -> str | None:
        """Read an unused reset challenge without consuming it."""
        table = self.email_outbox
        with self.engine.connect() as conn:
            row = conn.execute(
                self._sa.select(table.c.account_id)
                .where(table.c.id == challenge_id)
                .where(table.c.kind == "reset")
                .where(table.c.used_at.is_(None))
                .where(table.c.expires_at > _iso(now))
                .where(table.c.status != "dead")
            ).first()
        return str(row[0]) if row else None

    def _purchase_email_issue_filter(self, at: datetime) -> Any:
        table = self.email_outbox
        overdue_at = _iso(at - timedelta(minutes=15))
        overdue = ((table.c.status == "queued") & (table.c.next_attempt_at <= overdue_at)) | (
            (table.c.status == "sending") & (table.c.lease_until <= overdue_at)
        )
        return (
            table.c.kind.in_(("purchase", "charge_review", "market_review"))
            & table.c.used_at.is_(None)
            & ((table.c.status == "dead") | overdue)
        )

    def purchase_email_warning_counts(self, *, at: datetime) -> dict[str, int]:
        """Count dead or overdue purchase notices; never expose recipients."""
        sa, table = self._sa, self.email_outbox
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(table.c.status, sa.func.count())
                .where(self._purchase_email_issue_filter(at))
                .group_by(table.c.status)
            ).all()
        counts = {"dead": 0, "overdue": 0}
        for status, count in rows:
            counts["dead" if status == "dead" else "overdue"] += int(count)
        return counts

    def list_purchase_email_issues(
        self, *, at: datetime, limit: int = 50
    ) -> list[EmailDeliveryIssue]:
        """Return the oldest delivery problems with no address or token."""
        sa, table = self._sa, self.email_outbox
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    sa.select(
                        table.c.id,
                        table.c.kind,
                        table.c.status,
                        table.c.attempts,
                        table.c.created_at,
                        table.c.next_attempt_at,
                    )
                    .where(self._purchase_email_issue_filter(at))
                    .order_by(table.c.created_at, table.c.id)
                    .limit(max(0, min(limit, 200)))
                )
                .mappings()
                .all()
            )
        return [EmailDeliveryIssue(**dict(row)) for row in rows]

    def requeue_purchase_email(self, challenge_id: str, *, at: datetime) -> bool:
        """Retry one dead notice only while its live order and address still agree.

        The order, account and verification rows are locked with the outbox row
        on PostgreSQL. A conditional update prevents two operators from
        requeueing the same dead notice. Expiry is renewed for seven days.
        """
        if not challenge_id or len(challenge_id) > 32 or not _usable_key(challenge_id):
            return False
        sa, table, orders = self._sa, self.email_outbox, self.checkout_orders
        account, verified = self.accounts, self.verified_emails
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    sa.select(
                        table.c.kind,
                        table.c.expires_at,
                        orders.c.status,
                    )
                    .select_from(
                        table.join(orders, orders.c.id == table.c.id)
                        .join(account, account.c.id == table.c.account_id)
                        .join(verified, verified.c.account_id == account.c.id)
                    )
                    .where(table.c.id == challenge_id)
                    .where(table.c.kind.in_(("purchase", "charge_review", "market_review")))
                    .where(table.c.status == "dead")
                    .where(table.c.used_at.is_(None))
                    .where(table.c.sent_at == "")
                    .where(orders.c.account_id == table.c.account_id)
                    .where(orders.c.livemode.is_(True))
                    .where(account.c.email == table.c.email)
                    .where(verified.c.email == account.c.email)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            required_status = {
                "purchase": "delivered",
                "charge_review": "duplicate",
                "market_review": "paid_review",
            }
            if row is None or row["status"] != required_status[row["kind"]]:
                return False
            expires_at = max(str(row["expires_at"]), _iso(at + timedelta(days=7)))
            updated = conn.execute(
                table.update()
                .where(table.c.id == challenge_id)
                .where(table.c.status == "dead")
                .where(table.c.used_at.is_(None))
                .where(table.c.sent_at == "")
                .values(
                    status="queued",
                    attempts=0,
                    next_attempt_at=_iso(at),
                    lease_until="",
                    expires_at=expires_at,
                )
            )
            return bool(updated.rowcount)

    def claim_email_delivery(self, now: datetime) -> dict[str, Any] | None:
        """Lease one queued message. A crashed worker releases after 90 seconds."""
        sa, table = self._sa, self.email_outbox
        stamp = _iso(now)
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    sa.select(table)
                    .where(table.c.used_at.is_(None))
                    .where(table.c.expires_at > stamp)
                    .where(table.c.attempts < 8)
                    .where(
                        (table.c.status == "queued")
                        | ((table.c.status == "sending") & (table.c.lease_until < stamp))
                    )
                    .where(table.c.next_attempt_at <= stamp)
                    .order_by(table.c.next_attempt_at, table.c.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            result = conn.execute(
                table.update()
                .where(table.c.id == row["id"])
                .where(table.c.status == row["status"])
                .where(table.c.attempts == row["attempts"])
                .values(
                    status="sending",
                    attempts=int(row["attempts"]) + 1,
                    lease_until=_iso(now + timedelta(seconds=90)),
                )
            )
            if not result.rowcount:
                return None
            return {**dict(row), "attempts": int(row["attempts"]) + 1}

    def prepare_email_delivery(
        self, claimed: Mapping[str, Any], *, at: datetime
    ) -> dict[str, Any] | None:
        """Refresh a leased recipient or retire a challenge invalidated by an email change.

        Purchase notices follow a newly verified address on the same outbox id.
        Verification, change and reset tokens keep their original recipient;
        once that recipient no longer matches the account, the token is retired.
        """
        sa, table = self._sa, self.email_outbox
        challenge_id = str(claimed["id"])
        attempts = int(claimed["attempts"])
        stamp = _iso(at)
        with self.engine.begin() as conn:
            row = (
                conn.execute(sa.select(table).where(table.c.id == challenge_id).with_for_update())
                .mappings()
                .first()
            )
            if row is None or row["status"] != "sending" or int(row["attempts"]) != attempts:
                return None

            if row["kind"] == "institutional":
                prospects = self.institutional_requests
                contact = (
                    conn.execute(
                        sa.select(
                            prospects.c.name,
                            prospects.c.organization,
                            prospects.c.email,
                            prospects.c.strategy_type,
                        ).where(prospects.c.id == challenge_id)
                    )
                    .mappings()
                    .first()
                )
                if contact is None or row["used_at"] is not None or row["expires_at"] <= stamp:
                    conn.execute(
                        table.update()
                        .where(table.c.id == challenge_id)
                        .values(status="dead", used_at=stamp, lease_until="")
                    )
                    return None
                return {**dict(row), "institutional_contact": dict(contact)}

            account = (
                conn.execute(
                    sa.select(self.accounts.c.email, self.accounts.c.locale)
                    .where(self.accounts.c.id == row["account_id"])
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            kind = str(row["kind"])
            current_email = str(account["email"]) if account is not None else ""
            verified_email = conn.execute(
                sa.select(self.verified_emails.c.email).where(
                    self.verified_emails.c.account_id == row["account_id"]
                )
            ).scalar()
            verified = bool(current_email and verified_email == current_email)
            recipient = str(row["email"])
            valid = account is not None and row["used_at"] is None and row["expires_at"] > stamp
            purchase_notice = kind in ("purchase", "charge_review", "market_review")
            order = None
            if purchase_notice:
                order = conn.execute(
                    sa.select(self.checkout_orders.c.account_id).where(
                        self.checkout_orders.c.id == challenge_id
                    )
                ).scalar()
                valid = valid and verified and order == row["account_id"]
                if valid:
                    recipient = current_email
            elif kind == "reset":
                valid = valid and verified and recipient == current_email
            elif kind == "verify":
                valid = valid and recipient == current_email and not verified
            elif kind == "change":
                taken = conn.execute(
                    sa.select(self.accounts.c.id)
                    .where(self.accounts.c.email == recipient)
                    .where(self.accounts.c.id != row["account_id"])
                ).first()
                valid = (
                    valid
                    and current_email == row["original_email"]
                    and recipient != current_email
                    and taken is None
                )
            else:
                valid = False

            if not valid:
                # A charged buyer can verify the new address later. Keep the
                # same notice id and let the operator requeue it then. Account
                # deletion and obsolete account tokens are final instead.
                recoverable = (
                    purchase_notice
                    and account is not None
                    and row["used_at"] is None
                    and row["expires_at"] > stamp
                    and order == row["account_id"]
                    and not verified
                )
                values: dict[str, Any] = {"status": "dead", "lease_until": ""}
                if recoverable:
                    values.update(email=current_email, locale=str(account["locale"]))
                else:
                    values["used_at"] = stamp
                conn.execute(
                    table.update()
                    .where(table.c.id == challenge_id)
                    .where(table.c.status == "sending")
                    .where(table.c.attempts == attempts)
                    .values(**values)
                )
                return None
            locale = (
                str(account["locale"])
                if kind in ("purchase", "charge_review", "market_review")
                else str(row["locale"])
            )
            updated = conn.execute(
                table.update()
                .where(table.c.id == challenge_id)
                .where(table.c.status == "sending")
                .where(table.c.attempts == attempts)
                .values(email=recipient, locale=locale)
            )
            if not updated.rowcount:
                return None
            return {**dict(row), "email": recipient, "locale": locale}

    def finish_email_delivery(self, challenge_id: str, *, at: datetime) -> None:
        table = self.email_outbox
        with self.engine.begin() as conn:
            conn.execute(
                table.update()
                .where(table.c.id == challenge_id)
                .where(table.c.status == "sending")
                .values(status="sent", sent_at=_iso(at), lease_until="")
            )

    def retry_email_delivery(self, challenge_id: str, *, at: datetime) -> None:
        table = self.email_outbox
        with self.engine.begin() as conn:
            attempts = conn.execute(
                self._sa.select(table.c.attempts).where(table.c.id == challenge_id)
            ).scalar()
            if attempts is None:
                return
            terminal = int(attempts) >= 8
            delay = min(3600, 30 * 2 ** min(int(attempts), 7))
            conn.execute(
                table.update()
                .where(table.c.id == challenge_id)
                .where(table.c.status == "sending")
                .values(
                    status="dead" if terminal else "queued",
                    next_attempt_at=_iso(at + timedelta(seconds=delay)),
                    lease_until="",
                )
            )

    def email_referral_candidates(self, account_id: str) -> list[tuple[str, str, str]]:
        """Invites awaiting a free report and both addresses' confirmation."""
        sa, r, w = self._sa, self.referrals, self.welcome_reports
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(r.c.invitee_id, r.c.inviter_id, w.c.device_sha256)
                .select_from(r.join(w, w.c.account_id == r.c.invitee_id))
                .where(r.c.outcome == "")
                .where(w.c.audit_id != "")
                .where((r.c.invitee_id == account_id) | (r.c.inviter_id == account_id))
            ).all()
        return [(str(a), str(b), str(c or "")) for a, b, c in rows]

    def count_accounts(self) -> int:
        sa = self._sa
        with self.engine.connect() as conn:
            value = conn.execute(sa.select(sa.func.count()).select_from(self.accounts)).scalar()
        return int(value or 0)

    def delete_account(self, account_id: str, *, with_reports: bool = False) -> list[str]:
        """Remove an account, its sessions, reset links, links to codes and column maps.

        With ``with_reports`` the reports it uploaded are deleted too (as
        ``delete_audit``); a report paid for or saved from a link is only
        unlinked. Otherwise they stay reachable by their private link and follow the
        normal retention. Returns the ids of the reports deleted.
        """
        sa = self._sa
        with self.engine.connect() as conn:
            # A report saved from someone else's link is only unlinked.
            audit_ids = [
                str(row[0])
                for row in conn.execute(
                    sa.select(self.account_audits.c.audit_id)
                    .where(self.account_audits.c.account_id == account_id)
                    .where(self.account_audits.c.via.in_(OWN_VIAS))
                ).all()
            ]
        deleted = [a for a in audit_ids if self.delete_audit(a)] if with_reports else []
        with self.engine.begin() as conn:
            conn.execute(
                self.checkout_orders.update()
                .where(self.checkout_orders.c.account_id == account_id)
                .values(account_id="")
            )
            for table in (
                self.account_sessions,
                self.account_resets,
                self.verified_emails,
                self.email_outbox,
                self.account_codes,
                self.account_audits,
                self.column_maps,
                self.card_checks,
                self.strategies,
                self.strategy_reports,
                self.account_refs,
                self.recovery_keys,
                self.two_step,
                self.two_step_challenges,
                self.passkeys,
                self.passkey_challenges,
                self.session_info,
                self.account_events,
                self.failed_signins,
                self.account_seen,
                self.welcome_pending,
            ):
                conn.execute(table.delete().where(table.c.account_id == account_id))
            conn.execute(
                self.invite_links.delete().where(self.invite_links.c.account_id == account_id)
            )
            r = self.referrals
            conn.execute(r.delete().where(r.c.inviter_id == account_id))
            # An invitee that leaves: a pending invite goes; a decided one
            # keeps its outcome and monthly slot under a random id with no
            # browser mark, so deleting credited invitees never frees the
            # inviter's cap.
            conn.execute(r.delete().where((r.c.invitee_id == account_id) & (r.c.outcome == "")))
            conn.execute(
                r.update()
                .where(r.c.invitee_id == account_id)
                .values(invitee_id="gone" + secrets.token_hex(14), device_sha256="")
            )
            store_hooks.on_delete_account(self, conn, account_id)
            conn.execute(self.accounts.delete().where(self.accounts.c.id == account_id))
        return deleted

    # -- recovery keys ---------------------------------------------------
    def set_recovery_key(self, account_id: str, key_sha256: str, *, at: datetime) -> None:
        """Store a new recovery key (its hash); the previous one stops working."""
        table = self.recovery_keys
        with self.engine.begin() as conn:
            conn.execute(table.delete().where(table.c.account_id == account_id))
            conn.execute(
                table.insert().values(
                    account_id=account_id, key_sha256=key_sha256, created_at=_iso(at)
                )
            )

    def recovery_key_created(self, account_id: str) -> str | None:
        """When the account's recovery key was made, or ``None`` without one."""
        sa = self._sa
        table = self.recovery_keys
        with self.engine.connect() as conn:
            found = conn.execute(
                sa.select(table.c.created_at).where(table.c.account_id == account_id)
            ).first()
        return str(found[0]) if found is not None else None

    def recovery_key_matches(self, account_id: str, key_sha256: str) -> bool:
        """Whether ``key_sha256`` is the account's key, without spending it."""
        sa = self._sa
        table = self.recovery_keys
        with self.engine.connect() as conn:
            found = conn.execute(
                sa.select(table.c.key_sha256).where(table.c.account_id == account_id)
            ).first()
        return found is not None and hmac.compare_digest(str(found[0]), key_sha256)

    def use_recovery_key(self, account_id: str, key_sha256: str) -> bool:
        """Spend the account's recovery key if ``key_sha256`` is its hash.

        The delete names the hash, so a key works once even under
        simultaneous requests.
        """
        sa = self._sa
        table = self.recovery_keys
        with self.engine.connect() as conn:
            found = conn.execute(
                sa.select(table.c.key_sha256).where(table.c.account_id == account_id)
            ).first()
        if found is None or not hmac.compare_digest(str(found[0]), key_sha256):
            return False
        with self.engine.begin() as conn:
            result = conn.execute(
                table.delete()
                .where(table.c.account_id == account_id)
                .where(table.c.key_sha256 == key_sha256)
            )
        return bool(result.rowcount)

    # -- two-step sign-in ------------------------------------------------
    def two_step_state(self, account_id: str) -> tuple[str, str, int] | None:
        """``(secret, enabled_at, last_step)``; ``enabled_at`` is empty while pending."""
        sa = self._sa
        t = self.two_step
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(t.c.secret, t.c.enabled_at, t.c.last_step).where(
                    t.c.account_id == account_id
                )
            ).first()
        return (str(row[0]), str(row[1] or ""), int(row[2] or 0)) if row is not None else None

    def two_step_on(self, account_id: str) -> str:
        """When two-step sign-in was turned on, or ``""`` when it is off."""
        state = self.two_step_state(account_id)
        return state[1] if state is not None else ""

    def start_two_step(self, account_id: str, secret: str, *, at: datetime) -> bool:
        """Keep a new pending secret; refused while two-step is already on."""
        t = self.two_step
        with self.engine.begin() as conn:
            conn.execute(t.delete().where((t.c.account_id == account_id) & (t.c.enabled_at == "")))
            try:
                with conn.begin_nested():
                    conn.execute(
                        t.insert().values(
                            account_id=account_id,
                            secret=secret,
                            created_at=_iso(at),
                            enabled_at="",
                            last_step=0,
                        )
                    )
            except self._sa.exc.IntegrityError:
                return False  # already on
        return True

    def use_two_step_step(
        self, account_id: str, step: int, *, enable_at: datetime | None = None
    ) -> bool:
        """Record ``step`` as used if it is newer than the last one (one winner).

        With ``enable_at`` it also turns a pending secret on; without it the
        secret must already be on.
        """
        t = self.two_step
        query = t.update().where(t.c.account_id == account_id).where(t.c.last_step < step)
        if enable_at is not None:
            query = query.where(t.c.enabled_at == "").values(
                last_step=step, enabled_at=_iso(enable_at)
            )
        else:
            query = query.where(t.c.enabled_at != "").values(last_step=step)
        with self.engine.begin() as conn:
            result = conn.execute(query)
        return bool(result.rowcount)

    def stop_two_step(self, account_id: str) -> bool:
        t = self.two_step
        with self.engine.begin() as conn:
            result = conn.execute(t.delete().where(t.c.account_id == account_id))
            conn.execute(
                self.two_step_challenges.delete().where(
                    self.two_step_challenges.c.account_id == account_id
                )
            )
        return bool(result.rowcount)

    # -- passkeys --------------------------------------------------------------
    def add_passkey(
        self,
        account_id: str,
        *,
        credential_id: str,
        public_key: str,
        sign_count: int,
        label: str,
        rp_id: str,
        transports: str,
        at: datetime,
        limit: int,
    ) -> bool:
        """Store a new passkey; ``False`` if the account is full or it is already stored."""
        sa = self._sa
        p = self.passkeys
        with self.engine.begin() as conn:
            count = conn.execute(
                sa.select(sa.func.count()).select_from(p).where(p.c.account_id == account_id)
            ).scalar_one()
            if count >= limit:
                return False
            try:
                with conn.begin_nested():
                    conn.execute(
                        p.insert().values(
                            credential_sha256=_sha256(credential_id),
                            credential_id=credential_id,
                            account_id=account_id,
                            public_key=public_key,
                            sign_count=sign_count,
                            label=label[:80],
                            rp_id=rp_id[:255],
                            transports=transports[:200],
                            created_at=_iso(at),
                            last_used_at="",
                        )
                    )
            except sa.exc.IntegrityError:
                return False
        return True

    def list_passkeys(self, account_id: str) -> list[PasskeyRecord]:
        sa = self._sa
        p = self.passkeys
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(p.c.credential_id, p.c.label, p.c.rp_id, p.c.created_at, p.c.last_used_at)
                .where(p.c.account_id == account_id)
                .order_by(p.c.created_at)
            ).all()
        return [
            PasskeyRecord(str(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4] or "")) for r in rows
        ]

    def passkey_ids(self, account_id: str, rp_id: str) -> list[str]:
        """Credential ids of an account's passkeys made for ``rp_id``."""
        return [p.credential_id for p in self.list_passkeys(account_id) if p.rp_id == rp_id]

    def find_passkey(self, credential_id: str, rp_id: str) -> tuple[str, str, int] | None:
        """``(account id, public key, counter)`` of a passkey made for ``rp_id``."""
        sa = self._sa
        p = self.passkeys
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(p.c.account_id, p.c.public_key, p.c.sign_count)
                .where(p.c.credential_sha256 == _sha256(credential_id))
                .where(p.c.credential_id == credential_id)
                .where(p.c.rp_id == rp_id)
            ).first()
        return (str(row[0]), str(row[1]), int(row[2])) if row is not None else None

    def use_passkey(
        self, credential_id: str, *, old_count: int, new_count: int, at: datetime
    ) -> bool:
        """Record a sign-in; the counter moves only from the value just checked (one winner)."""
        p = self.passkeys
        query = (
            p.update()
            .where(p.c.credential_sha256 == _sha256(credential_id))
            .where(p.c.sign_count == old_count)
            .values(sign_count=new_count, last_used_at=_iso(at))
        )
        with self.engine.begin() as conn:
            result = conn.execute(query)
        return bool(result.rowcount)

    def remove_passkey(self, account_id: str, credential_id: str) -> bool:
        p = self.passkeys
        with self.engine.begin() as conn:
            result = conn.execute(
                p.delete()
                .where(p.c.account_id == account_id)
                .where(p.c.credential_sha256 == _sha256(credential_id))
            )
        return bool(result.rowcount)

    def create_passkey_challenge(
        self,
        token_sha256: str,
        *,
        challenge: str,
        purpose: str,
        account_id: str = "",
        label: str = "",
        at: datetime,
        minutes: int,
    ) -> None:
        c = self.passkey_challenges
        with self.engine.begin() as conn:
            conn.execute(c.delete().where(c.c.expires_at <= _iso(at)))
            conn.execute(
                c.insert().values(
                    token_sha256=token_sha256,
                    challenge=challenge,
                    account_id=account_id,
                    purpose=purpose,
                    label=label[:80],
                    expires_at=_iso(at + timedelta(minutes=minutes)),
                )
            )

    def take_passkey_challenge(
        self, token_sha256: str, purpose: str, now: datetime
    ) -> tuple[str, str, str] | None:
        """``(challenge, account id, label)`` of a still-valid page, used up on reading."""
        sa = self._sa
        c = self.passkey_challenges
        with self.engine.begin() as conn:
            row = conn.execute(
                sa.select(c.c.challenge, c.c.account_id, c.c.label)
                .where(c.c.token_sha256 == token_sha256)
                .where(c.c.purpose == purpose)
                .where(c.c.expires_at > _iso(now))
            ).first()
            if row is None:
                return None
            gone = conn.execute(c.delete().where(c.c.token_sha256 == token_sha256)).rowcount
        if not gone:
            return None  # pragma: no cover - read twice at once
        return (str(row[0]), str(row[1]), str(row[2]))

    def create_two_step_challenge(
        self, account_id: str, token_sha256: str, *, at: datetime, minutes: int
    ) -> None:
        c = self.two_step_challenges
        with self.engine.begin() as conn:
            conn.execute(c.delete().where(c.c.expires_at <= _iso(at)))
            conn.execute(
                c.insert().values(
                    token_sha256=token_sha256,
                    account_id=account_id,
                    expires_at=_iso(at + timedelta(minutes=minutes)),
                )
            )

    def two_step_challenge(self, token_sha256: str, now: datetime) -> str | None:
        """The account a still-valid challenge belongs to."""
        sa = self._sa
        c = self.two_step_challenges
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(c.c.account_id)
                .where(c.c.token_sha256 == token_sha256)
                .where(c.c.expires_at > _iso(now))
            ).first()
        return str(row[0]) if row is not None else None

    def end_two_step_challenge(self, token_sha256: str) -> bool:
        c = self.two_step_challenges
        with self.engine.begin() as conn:
            result = conn.execute(c.delete().where(c.c.token_sha256 == token_sha256))
        return bool(result.rowcount)

    # -- account sessions ------------------------------------------------
    def create_session(
        self, account_id: str, *, token_sha256: str, csrf: str, at: datetime, days: int
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                self.account_sessions.insert().values(
                    token_sha256=token_sha256,
                    account_id=account_id,
                    csrf=csrf,
                    created_at=_iso(at),
                    expires_at=_iso(at + timedelta(days=days)),
                )
            )

    def session_account(self, token_sha256: str, now: datetime) -> tuple[AccountRecord, str] | None:
        """The signed-in account and the session's CSRF token, if it is still valid."""
        sa = self._sa
        table = self.account_sessions
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(table.c.account_id, table.c.csrf)
                .where(table.c.token_sha256 == token_sha256)
                .where(table.c.expires_at > _iso(now))
            ).first()
        if row is None:
            return None
        account = self.get_account(str(row[0]))
        return (account, str(row[1])) if account is not None else None

    def delete_session(self, token_sha256: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                self.account_sessions.delete().where(
                    self.account_sessions.c.token_sha256 == token_sha256
                )
            )
            conn.execute(
                self.session_info.delete().where(self.session_info.c.token_sha256 == token_sha256)
            )

    def delete_sessions(self, account_id: str, *, keep: str = "") -> None:
        """Sign out everywhere, except the session ``keep`` (its hash)."""
        with self.engine.begin() as conn:
            for table in (self.account_sessions, self.session_info):
                conn.execute(
                    table.delete()
                    .where(table.c.account_id == account_id)
                    .where(table.c.token_sha256 != keep)
                )

    def purge_sessions(self, now: datetime) -> int:
        """Drop expired sessions and reset links; how many rows went."""
        sa = self._sa
        with self.engine.begin() as conn:
            gone = conn.execute(
                self.account_sessions.delete().where(
                    self.account_sessions.c.expires_at <= _iso(now)
                )
            ).rowcount
            gone += conn.execute(
                self.account_resets.delete().where(self.account_resets.c.expires_at <= _iso(now))
            ).rowcount
            # Session details outlive nothing: without a session they go.
            info = self.session_info
            conn.execute(
                info.delete().where(
                    ~info.c.token_sha256.in_(sa.select(self.account_sessions.c.token_sha256))
                )
            )
            cutoff = _iso(now - timedelta(days=ACCOUNT_EVENT_DAYS))
            conn.execute(self.account_seen.delete().where(self.account_seen.c.seen_at < cutoff))
            conn.execute(self.account_events.delete().where(self.account_events.c.at < cutoff))
            conn.execute(self.failed_signins.delete().where(self.failed_signins.c.last_at < cutoff))
        return int(gone or 0)

    def note_event(
        self, account_id: str, kind: str, *, device: str = "", network: str = "", now: datetime
    ) -> None:
        """Add a line to "Actividad reciente", keeping the newest ACCOUNT_EVENT_MAX."""
        if kind not in ACCOUNT_EVENT_KINDS:
            raise ValueError(f"unknown account event: {kind}")
        sa = self._sa
        ev = self.account_events
        with self.engine.begin() as conn:
            conn.execute(
                ev.insert().values(
                    account_id=account_id,
                    kind=kind,
                    device=device[:80],
                    network=network[:64],
                    at=_iso(now),
                )
            )
            ids = [
                int(row[0])
                for row in conn.execute(
                    sa.select(ev.c.id)
                    .where(ev.c.account_id == account_id)
                    .order_by(ev.c.id.desc())
                    .offset(ACCOUNT_EVENT_MAX)
                ).all()
            ]
            if ids:
                conn.execute(ev.delete().where(ev.c.id.in_(ids)))

    def note_failed_signin(
        self, account_id: str, *, device: str = "", network: str = "", now: datetime
    ) -> None:
        """Count a wrong password on the account's line for this network and hour."""
        sa = self._sa
        fs = self.failed_signins
        hour, stamp = _iso(now)[:13], _iso(now)
        key = (fs.c.account_id == account_id) & (fs.c.network == network[:64]) & (fs.c.hour == hour)
        bump = (
            fs.update()
            .where(key)
            .values(attempts=fs.c.attempts + 1, device=device[:80], last_at=stamp)
        )
        with self.engine.begin() as conn:
            if conn.execute(bump).rowcount:
                return
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    fs.insert().values(
                        account_id=account_id,
                        network=network[:64],
                        hour=hour,
                        device=device[:80],
                        attempts=1,
                        last_at=stamp,
                    )
                )
        except sa.exc.IntegrityError:
            with self.engine.begin() as conn:
                conn.execute(bump)  # a simultaneous try made the line first
        with self.engine.begin() as conn:
            ids = [
                int(row[0])
                for row in conn.execute(
                    sa.select(fs.c.id)
                    .where(fs.c.account_id == account_id)
                    .order_by(fs.c.last_at.desc(), fs.c.id.desc())
                    .offset(FAILED_SIGNIN_MAX)
                ).all()
            ]
            if ids:
                conn.execute(fs.delete().where(fs.c.id.in_(ids)))

    def take_visit_notice(
        self, account_id: str, now: datetime, *, browser: str, device: str = ""
    ) -> VisitNotice | None:
        """What happened since this browser last opened Mi cuenta, and mark it seen now.

        ``browser`` is the hash of the browser's own random cookie. Counts
        wrong-password tries added since and sign-ins from other device
        labels the account had not used before. Each browser keeps its own
        last view, so whoever signs in elsewhere never clears the owner's
        notice. A browser's first view shows nothing (and so tells a
        newcomer nothing). ``None`` when nothing happened.
        """
        sa = self._sa
        seen_t, ev, fs = self.account_seen, self.account_events, self.failed_signins
        mine = (seen_t.c.account_id == account_id) & (seen_t.c.browser == browser[:64])
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(seen_t.c.seen_at, seen_t.c.failed_json).where(mine)
            ).first()
            lines = {
                str(r[0]): int(r[1])
                for r in conn.execute(
                    sa.select(fs.c.id, fs.c.attempts).where(fs.c.account_id == account_id)
                ).all()
            }
            viewed = [
                (str(r[0]), str(r[1]))
                for r in conn.execute(
                    sa.select(seen_t.c.device, seen_t.c.seen_at).where(
                        seen_t.c.account_id == account_id
                    )
                ).all()
            ]
        values = {
            "device": device[:80],
            "seen_at": _iso(now),
            "failed_json": json.dumps(lines, sort_keys=True),
        }
        try:
            with self.engine.begin() as conn:
                if row is None:
                    # Past the cap a newcomer is not stored (its first view
                    # shows nothing anyway), so nobody can push the owner out.
                    if len(viewed) < SEEN_DEVICES_MAX:
                        conn.execute(
                            seen_t.insert().values(
                                account_id=account_id, browser=browser[:64], **values
                            )
                        )
                else:
                    conn.execute(seen_t.update().where(mine).values(**values))
        except sa.exc.IntegrityError:
            pass  # another tab marked it at the same moment
        if row is None:
            return None
        seen = str(row[0])
        try:
            before = {str(k): int(v) for k, v in json.loads(str(row[1] or "{}")).items()}
        except (ValueError, TypeError, AttributeError):
            before = {}
        # Only tries newer than the last view: a line that spans it counts
        # the tries added since.
        failed = sum(max(0, n - before.get(line, 0)) for line, n in lines.items())
        with self.engine.connect() as conn:
            # Devices that had opened Mi cuenta before this device's last view.
            known = {label for label, at in viewed if at <= seen} | {
                str(r[0])
                for r in conn.execute(
                    sa.select(ev.c.device)
                    .where(ev.c.account_id == account_id)
                    .where(ev.c.at <= seen)
                    .distinct()
                ).all()
            }
            recent = conn.execute(
                sa.select(ev.c.device)
                .where(ev.c.account_id == account_id)
                .where(ev.c.at > seen)
                .where(ev.c.kind.in_(SIGNIN_KINDS))
                .order_by(ev.c.id)
            ).all()
        new_devices: list[str] = []
        for (dev,) in recent:
            label = str(dev)
            if label == device or label in known or label in new_devices:
                continue
            new_devices.append(label)
        notice = VisitNotice(failed_attempts=int(failed or 0), new_devices=tuple(new_devices))
        return notice if notice.failed_attempts or notice.new_devices else None

    def list_failed_signins(
        self, account_id: str, *, limit: int = FAILED_SIGNIN_MAX
    ) -> list[AccountEvent]:
        """The account's wrong-password lines, newest first, as ``signin_failed`` events."""
        sa = self._sa
        fs = self.failed_signins
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(fs.c.device, fs.c.network, fs.c.last_at, fs.c.attempts)
                .where(fs.c.account_id == account_id)
                .order_by(fs.c.last_at.desc(), fs.c.id.desc())
                .limit(limit)
            ).all()
        return [
            AccountEvent(
                kind="signin_failed",
                device=str(r[0]),
                network=str(r[1]),
                at=str(r[2]),
                count=int(r[3]),
            )
            for r in rows
        ]

    def _seen_list(self, account_id: str) -> list[dict[str, str]]:
        sa = self._sa
        seen_t = self.account_seen
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(seen_t.c.device, seen_t.c.seen_at)
                .where(seen_t.c.account_id == account_id)
                .order_by(seen_t.c.seen_at.desc())
            ).all()
        return [{"device": str(r[0]), "seen_at": str(r[1])} for r in rows]

    def list_events(self, account_id: str, *, limit: int = ACCOUNT_EVENT_MAX) -> list[AccountEvent]:
        """The account's events, newest first."""
        sa = self._sa
        ev = self.account_events
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(ev.c.kind, ev.c.device, ev.c.network, ev.c.at)
                .where(ev.c.account_id == account_id)
                .order_by(ev.c.id.desc())
                .limit(limit)
            ).all()
        return [
            AccountEvent(kind=str(r[0]), device=str(r[1]), network=str(r[2]), at=str(r[3]))
            for r in rows
        ]

    def touch_session(
        self,
        token_sha256: str,
        account_id: str,
        *,
        device: str,
        network: str,
        now: datetime,
        every: timedelta = timedelta(minutes=10),
    ) -> None:
        """Note a session's device, network and last use (at most every ``every``)."""
        sa = self._sa
        info = self.session_info
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(info.c.last_seen).where(info.c.token_sha256 == token_sha256)
            ).first()
        values = {"device": device[:80], "network": network[:64], "last_seen": _iso(now)}
        if row is not None:
            if str(row[0]) > _iso(now - every):
                return
            with self.engine.begin() as conn:
                conn.execute(
                    info.update().where(info.c.token_sha256 == token_sha256).values(**values)
                )
            return
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    info.insert().values(
                        token_sha256=token_sha256,
                        account_id=account_id,
                        handle=secrets.token_urlsafe(12),
                        **values,
                    )
                )
        except sa.exc.IntegrityError:
            pass  # noted by a simultaneous request

    def list_sessions(
        self, account_id: str, now: datetime, *, current: str = ""
    ) -> list[SessionView]:
        """The account's open sessions, newest use first; ``current`` is this browser's hash."""
        sa = self._sa
        s_, info = self.account_sessions, self.session_info
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(
                    s_.c.token_sha256,
                    s_.c.created_at,
                    info.c.handle,
                    info.c.device,
                    info.c.network,
                    info.c.last_seen,
                )
                .select_from(s_.outerjoin(info, info.c.token_sha256 == s_.c.token_sha256))
                .where(s_.c.account_id == account_id)
                .where(s_.c.expires_at > _iso(now))
            ).all()
        views = [
            SessionView(
                handle=str(row[2] or ""),
                device=str(row[3] or ""),
                network=str(row[4] or ""),
                created_at=str(row[1]),
                last_seen=str(row[5] or ""),
                current=bool(current) and str(row[0]) == current,
            )
            for row in rows
        ]
        return sorted(views, key=lambda v: (v.current, v.last_seen or v.created_at), reverse=True)

    def end_session(self, account_id: str, handle: str) -> str | None:
        """Sign out the account's session with this handle; its hash, or ``None``."""
        sa = self._sa
        info = self.session_info
        with self.engine.connect() as conn:
            row = conn.execute(
                sa.select(info.c.token_sha256)
                .where(info.c.handle == handle)
                .where(info.c.account_id == account_id)
            ).first()
        if row is None:
            return None
        self.delete_session(str(row[0]))
        return str(row[0])

    # -- password reset links --------------------------------------------
    def create_reset(self, account_id: str, *, token_sha256: str, at: datetime, hours: int) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                self.account_resets.insert().values(
                    token_sha256=token_sha256,
                    account_id=account_id,
                    created_at=_iso(at),
                    expires_at=_iso(at + timedelta(hours=hours)),
                    used_at=None,
                )
            )

    def reset_account(self, token_sha256: str, now: datetime) -> str | None:
        """The account a valid, unused reset link belongs to (it stays unused)."""
        table = self.account_resets
        with self.engine.connect() as conn:
            row = conn.execute(
                self._sa.select(table.c.account_id)
                .where(table.c.token_sha256 == token_sha256)
                .where(table.c.used_at.is_(None))
                .where(table.c.expires_at > _iso(now))
            ).first()
        return str(row[0]) if row else None

    def use_reset(self, token_sha256: str, now: datetime) -> str | None:
        """Spend a reset link once; its account id, or ``None``."""
        table = self.account_resets
        with self.engine.begin() as conn:
            result = conn.execute(
                table.update()
                .where(table.c.token_sha256 == token_sha256)
                .where(table.c.used_at.is_(None))
                .where(table.c.expires_at > _iso(now))
                .values(used_at=_iso(now))
            )
            if not result.rowcount:
                return None
            row = conn.execute(
                self._sa.select(table.c.account_id).where(table.c.token_sha256 == token_sha256)
            ).first()
        return str(row[0]) if row else None

    # -- what an account holds -------------------------------------------
    def link_audit(
        self, account_id: str, audit_id: str, *, at: datetime, via: str = VIA_SAVED
    ) -> str:
        """Put a report on an account: ``linked``, ``already`` or ``other``.

        A report saved on this account is recorded as paid when the account
        pays for it; that never makes it deletable with the account.
        """
        outcome = self._link(
            self.account_audits, "audit_id", audit_id, account_id, at, extra={"via": via}
        )
        if outcome == "already" and via == VIA_PAID:
            table = self.account_audits
            with self.engine.begin() as conn:
                conn.execute(
                    table.update()
                    .where(table.c.audit_id == audit_id)
                    .where(table.c.account_id == account_id)
                    .where(table.c.via == VIA_SAVED)
                    .values(via=via)
                )
        return outcome

    def link_code(self, account_id: str, code_id: str, *, at: datetime) -> str:
        """Put an access code on an account: ``linked``, ``already`` or ``other``."""
        return self._link(self.account_codes, "code_id", code_id, account_id, at)

    def _link(
        self,
        table: Any,
        key: str,
        value: str,
        account_id: str,
        at: datetime,
        extra: dict[str, str] | None = None,
    ) -> str:
        sa = self._sa
        column = table.c[key]
        try:
            with self.engine.begin() as conn:
                owner = conn.execute(sa.select(table.c.account_id).where(column == value)).first()
                if owner is not None:
                    return "already" if owner[0] == account_id else "other"
                conn.execute(
                    table.insert().values(
                        **{key: value, "account_id": account_id, "linked_at": _iso(at)},
                        **(extra or {}),
                    )
                )
        except sa.exc.IntegrityError:  # pragma: no cover - lost a race to the same row
            return "other"
        return "linked"

    def earlier_audit_of_same_files(self, account_id: str, audit_id: str) -> str | None:
        """Another report on this account made from the same files as
        ``audit_id`` (the same set of SHA-256 digests) and uploaded before it,
        a full one first; ``None`` when there is none. Only reports linked to
        ``account_id`` are looked at, and purged ones are left out."""
        record = self.get_audit(audit_id)
        if not account_id or record is None or not record.digests:
            return None
        sa = self._sa
        a, link, files = self.audits, self.account_audits, self.audit_files
        # The prefilter uses the curve's digest, or, for an upload made from
        # a platform report (no curve of its own), the digest of that file.
        equity_sha256 = record.digests.get("equity.csv")
        if equity_sha256 is not None:
            same_file = a.c.equity_sha256 == equity_sha256
        else:
            other_digests = [
                digest
                for name, digest in sorted(record.digests.items())
                if name not in ("trades.csv", "benchmark.csv", "variants.csv")
            ]
            if not other_digests:
                return None
            same_file = sa.exists().where(
                (files.c.audit_id == a.c.id) & (files.c.sha256 == other_digests[0])
            )
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(a.c.id)
                .select_from(link.join(a, a.c.id == link.c.audit_id))
                .where(link.c.account_id == account_id)
                .where(a.c.id != audit_id)
                .where(a.c.purged_at.is_(None))
                .where(a.c.created_at < record.created_at)
                .where(same_file)
                .order_by(a.c.paid.desc(), a.c.created_at)
                .limit(SAME_FILE_CANDIDATES)
            ).all()
        for row in rows:
            other = self.get_audit(str(row[0]))
            if other is not None and other.digests == record.digests:
                return other.id
        return None

    def account_for_audit(self, audit_id: str) -> str | None:
        if not _usable_key(audit_id):
            return None
        table = self.account_audits
        with self.engine.connect() as conn:
            row = conn.execute(
                self._sa.select(table.c.account_id).where(table.c.audit_id == audit_id)
            ).first()
        return str(row[0]) if row else None

    def code_id(self, code: str) -> str | None:
        record = self.get_access_code(code)
        return record.id if record else None

    def code_usable(self, code: str, at: datetime) -> bool:
        """Whether a typed code exists and can still unlock a report."""
        record = self.get_access_code(code) if code else None
        return (
            record is not None
            and not record.disabled
            and record.credits_left > 0
            and (record.expires_at is None or record.expires_at > _iso(at))
        )

    # -- the free first full report ---------------------------------------
    def welcome_refusal(
        self,
        account_id: str,
        *,
        device_sha256: str,
        file_sha256: str,
        client_ip: str,
        since: datetime,
        per_ip: int,
    ) -> str:
        """Why this upload cannot be the account's free full report; ``""`` if it can."""
        sa = self._sa
        table = self.welcome_reports
        with self.engine.connect() as conn:

            def used(condition: Any) -> int:
                return int(
                    conn.execute(
                        sa.select(sa.func.count()).select_from(table).where(condition)
                    ).scalar()
                    or 0
                )

            if used(table.c.account_id == account_id):
                return "account"
            if device_sha256 and used(table.c.device_sha256 == device_sha256):
                return "device"
            if file_sha256 and used(table.c.file_sha256 == file_sha256):
                return "file"
            if client_ip and (
                used((table.c.client_ip == client_ip) & (table.c.created_at >= _iso(since)))
                >= per_ip
            ):
                return "network"
        return ""

    def welcome_used(self, account_id: str) -> bool:
        sa = self._sa
        table = self.welcome_reports
        with self.engine.connect() as conn:
            return (
                conn.execute(
                    sa.select(table.c.account_id).where(table.c.account_id == account_id)
                ).first()
                is not None
            )

    def grant_welcome(
        self,
        audit_id: str,
        account_id: str,
        *,
        device_sha256: str,
        file_sha256: str,
        client_ip: str,
        at: datetime,
    ) -> bool:
        """Unlock ``audit_id`` as the account's free full report; ``False`` if already used."""
        sa = self._sa
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    self.welcome_reports.insert().values(
                        account_id=account_id,
                        audit_id=audit_id,
                        device_sha256=device_sha256,
                        file_sha256=file_sha256,
                        client_ip=client_ip[:64],
                        created_at=_iso(at),
                    )
                )
                result = conn.execute(
                    self.audits.update()
                    .where(self.audits.c.id == audit_id)
                    .where(self.audits.c.paid.is_(False))
                    .values(
                        paid=True,
                        paid_at=_iso(at),
                        stripe_session_id=WELCOME_REFERENCE_PREFIX + audit_id,
                    )
                )
                if not result.rowcount:
                    raise LookupError(audit_id)
        except (sa.exc.IntegrityError, LookupError):
            return False
        return True

    def spend_welcome(self, account_id: str, *, at: datetime) -> None:
        """Mark the free full report as used without a report (the owner's tool, tests)."""
        sa = self._sa
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    self.welcome_reports.insert().values(account_id=account_id, created_at=_iso(at))
                )
        except sa.exc.IntegrityError:
            return

    # -- card check for the free full report ---------------------------------
    def record_card_check(self, account_id: str, card_sha256: str, *, at: datetime) -> str:
        """Note a card verified at no charge: ``ok``, or ``taken`` by another account.

        Idempotent: the webhook and the return page may both report the same
        card for the same account. A card gives one free full report ever,
        across accounts, deleted ones included.
        """
        sa = self._sa
        key = CARD_CLAIM_PREFIX + card_sha256
        with self.engine.connect() as conn:
            holder = conn.execute(
                sa.select(self.free_claims.c.reservation).where(self.free_claims.c.claim_key == key)
            ).first()
        if holder is not None and holder[0] != account_id:
            return "taken"
        try:
            with self.engine.begin() as conn:
                if holder is None:
                    conn.execute(
                        self.free_claims.insert().values(
                            claim_key=key, reservation=account_id, created_at=_iso(at)
                        )
                    )
                conn.execute(
                    self.card_checks.insert().values(
                        account_id=account_id, card_sha256=card_sha256, created_at=_iso(at)
                    )
                )
        except sa.exc.IntegrityError:
            # A simultaneous call: whoever holds the card now decides.
            return "ok" if self.card_checked(account_id) else "taken"
        return "ok"

    def card_checked(self, account_id: str) -> bool:
        with self.engine.connect() as conn:
            row = conn.execute(
                self._sa.select(self.card_checks.c.account_id).where(
                    self.card_checks.c.account_id == account_id
                )
            ).first()
        return row is not None

    # -- invites ("Invita a un colega") -------------------------------------
    def invite_token(self, account_id: str, *, at: datetime) -> str:
        """The account's invite token, made on first use."""
        sa = self._sa
        table = self.invite_links
        for _ in range(3):
            with self.engine.connect() as conn:
                found = conn.execute(
                    sa.select(table.c.token).where(table.c.account_id == account_id)
                ).first()
            if found is not None:
                return str(found[0])
            try:
                with self.engine.begin() as conn:
                    conn.execute(
                        table.insert().values(
                            account_id=account_id,
                            token=secrets.token_urlsafe(12),
                            created_at=_iso(at),
                        )
                    )
            except sa.exc.IntegrityError:
                continue  # made by a simultaneous request (or a token clash): read again
        raise RuntimeError("could not make an invite token")  # pragma: no cover

    def inviter_for_token(self, token: str) -> str | None:
        """The account behind an invite token, or ``None``."""
        if not (8 <= len(token) <= 32) or not all(c.isalnum() or c in "-_" for c in token):
            return None
        sa = self._sa
        table = self.invite_links
        with self.engine.connect() as conn:
            found = conn.execute(
                sa.select(table.c.account_id)
                .select_from(table.join(self.accounts, self.accounts.c.id == table.c.account_id))
                .where(table.c.token == token)
            ).first()
        return str(found[0]) if found is not None else None

    def _inviter_marks(self, conn: Any, inviter_id: str) -> tuple[set[str], set[str]]:
        """The inviter's browser marks and addresses that are still kept."""
        sa = self._sa
        w, fp, aa = self.welcome_reports, self.free_previews, self.account_audits
        devices: set[str] = set()
        addresses: set[str] = set()
        for device, address in conn.execute(
            sa.select(w.c.device_sha256, w.c.client_ip).where(w.c.account_id == inviter_id)
        ).all():
            devices.add(str(device or ""))
            addresses.add(str(address or ""))
        for (address,) in conn.execute(
            sa.select(fp.c.client_ip).where(fp.c.account_id == inviter_id)
        ).all():
            addresses.add(str(address or ""))
        for (address,) in conn.execute(
            sa.select(self.audits.c.client_ip)
            .select_from(aa.join(self.audits, self.audits.c.id == aa.c.audit_id))
            .where(aa.c.account_id == inviter_id)
            .where(aa.c.via.in_(OWN_VIAS))
        ).all():
            addresses.add(str(address or ""))
        devices.discard("")
        addresses.discard("")
        # Compared as networks, like the free tier's limits (an IPv6 /64).
        from quant_trade.audit.accounts import network_address

        return devices, {network_address(address) for address in addresses}

    def record_referral(
        self, invitee_id: str, inviter_id: str, *, device_sha256: str, at: datetime
    ) -> bool:
        """Note that a new account signed up through ``inviter_id``'s link.

        ``False`` (nothing noted) for the inviter itself, an unknown
        inviter, a browser the inviter used for its own free report, or an
        account that was already noted.
        """
        if not invitee_id or invitee_id == inviter_id:
            return False
        sa = self._sa
        try:
            with self.engine.begin() as conn:
                if (
                    conn.execute(
                        sa.select(self.accounts.c.id).where(self.accounts.c.id == inviter_id)
                    ).first()
                    is None
                ):
                    return False
                devices, _ = self._inviter_marks(conn, inviter_id)
                if device_sha256 and device_sha256 in devices:
                    return False
                conn.execute(
                    self.referrals.insert().values(
                        invitee_id=invitee_id,
                        inviter_id=inviter_id,
                        device_sha256=device_sha256,
                        joined_at=_iso(at),
                        outcome="",
                    )
                )
        except sa.exc.IntegrityError:
            return False
        return True

    def reward_referral(
        self,
        invitee_id: str,
        *,
        device_sha256: str,
        client_ip: str,
        at: datetime,
        credits: int,
        monthly_cap: int,
        global_monthly_cap: int = 100,
    ) -> str:
        """Credit the inviter once ``invitee_id`` got its free first report.

        Call it only after :meth:`grant_welcome` succeeded for the invitee.
        Returns ``credited``, ``self`` (the invitee's browser is one the
        inviter used), ``cap`` (the inviter's calendar month already
        holds ``monthly_cap`` credited invites), ``budget`` (the shared
        monthly reward budget is full) or ``""`` (no pending invite).
        """
        if credits < 1:
            raise ValueError("credits must be at least 1")
        if global_monthly_cap < 0:
            raise ValueError("global monthly cap cannot be negative")
        sa = self._sa
        r = self.referrals
        now = _iso(at)
        month = now[:7]
        with self.engine.begin() as conn:
            claimed = conn.execute(
                r.update()
                .where(r.c.invitee_id == invitee_id)
                .where(r.c.outcome == "")
                .values(outcome="settling")
            )
            if not claimed.rowcount:
                return ""
            row = conn.execute(
                sa.select(r.c.inviter_id, r.c.device_sha256).where(r.c.invitee_id == invitee_id)
            ).one()
            inviter_id, signup_device = str(row[0]), str(row[1] or "")
            devices, _ = self._inviter_marks(conn, inviter_id)
            marks = {device_sha256, signup_device} - {""}
            outcome = ""
            # A shared household or office network is not proof of self-referral.
            if marks & devices:
                outcome = "self"
            slot = ""
            if not outcome:
                for n in range(monthly_cap):
                    candidate = f"{inviter_id}:{month}:{n}"
                    try:
                        with conn.begin_nested():
                            claimed = conn.execute(
                                r.update()
                                .where(r.c.invitee_id == invitee_id)
                                .where(r.c.outcome == "settling")
                                .where(r.c.reward_slot.is_(None))
                                .values(reward_slot=candidate)
                            )
                            if not claimed.rowcount:
                                return ""
                    except sa.exc.IntegrityError:
                        continue
                    slot = candidate
                    break
                outcome = "credited" if slot else "cap"
            if outcome == "credited":
                budget_slot = False
                for n in range(global_monthly_cap):
                    try:
                        with conn.begin_nested():
                            conn.execute(
                                self.referral_global_slots.insert().values(
                                    month=month, slot=n, created_at=now
                                )
                            )
                    except sa.exc.IntegrityError:
                        continue
                    budget_slot = True
                    break
                if not budget_slot:
                    outcome = "budget"
                    conn.execute(
                        r.update()
                        .where(r.c.invitee_id == invitee_id)
                        .where(r.c.outcome == "settling")
                        .values(reward_slot=None)
                    )
            code_id = None
            if outcome == "credited":
                code_id = secrets.token_hex(6)
                # A code no one ever sees: its credits show on the inviter's
                # account and are spent from there like any other code's.
                conn.execute(
                    self.access_codes.insert().values(
                        id=code_id,
                        code_sha256=hash_access_code(new_access_code()),
                        credits_total=credits,
                        credits_used=0,
                        note="invite",
                        created_at=now,
                        expires_at=None,
                        disabled=False,
                    )
                )
                conn.execute(
                    self.credit_grants.insert().values(
                        code_id=code_id,
                        origin="referral",
                        order_id="",
                        credits=credits,
                        created_at=now,
                    )
                )
                conn.execute(
                    self.account_codes.insert().values(
                        code_id=code_id, account_id=inviter_id, linked_at=now
                    )
                )
            conn.execute(
                r.update()
                .where(r.c.invitee_id == invitee_id)
                .where(r.c.outcome == "settling")
                .values(outcome=outcome, decided_at=now, code_id=code_id)
            )
        return outcome

    def invite_summary(self, inviter_id: str, now: datetime) -> InviteSummary:
        sa = self._sa
        r = self.referrals
        month = _iso(now)[:7]
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(r.c.outcome, r.c.decided_at).where(r.c.inviter_id == inviter_id)
            ).all()
        credited = [row for row in rows if row[0] == "credited"]
        return InviteSummary(
            joined=len(rows),
            waiting=sum(1 for row in rows if not row[0]),
            credited=len(credited),
            credited_this_month=sum(1 for row in credited if str(row[1] or "")[:7] == month),
        )

    # -- strategies ("Mis estrategias") ------------------------------------
    MAX_STRATEGIES_PER_ACCOUNT = 50

    def create_strategy(self, account_id: str, name: str, *, at: datetime) -> str:
        """A new strategy on the account; ``""`` when the name is empty or the
        account already has :attr:`MAX_STRATEGIES_PER_ACCOUNT`."""
        sa = self._sa
        name = strategy_name(name)
        if not name:
            return ""
        table = self.strategies
        with self.engine.begin() as conn:
            count = int(
                conn.execute(
                    sa.select(sa.func.count())
                    .select_from(table)
                    .where(table.c.account_id == account_id)
                ).scalar()
                or 0
            )
            if count >= self.MAX_STRATEGIES_PER_ACCOUNT:
                return ""
            strategy_id = secrets.token_hex(16)
            conn.execute(
                table.insert().values(
                    id=strategy_id, account_id=account_id, name=name, created_at=_iso(at)
                )
            )
        return strategy_id

    def list_strategies(self, account_id: str) -> list[StrategyRecord]:
        """The account's strategies, oldest first, each with its reports oldest first."""
        sa = self._sa
        s, link, a = self.strategies, self.strategy_reports, self.audits
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(s.c.id, s.c.name, s.c.created_at)
                .where(s.c.account_id == account_id)
                .order_by(s.c.created_at, s.c.id)
            ).all()
            members = conn.execute(
                sa.select(link.c.strategy_id, link.c.audit_id)
                .select_from(link.join(a, a.c.id == link.c.audit_id))
                .where(link.c.account_id == account_id)
                .order_by(a.c.created_at, a.c.id)
            ).all()
        by_strategy: dict[str, list[str]] = {}
        for strategy_id, audit_id in members:
            by_strategy.setdefault(str(strategy_id), []).append(str(audit_id))
        return [
            StrategyRecord(
                id=str(row[0]),
                name=str(row[1]),
                created_at=str(row[2]),
                audit_ids=tuple(by_strategy.get(str(row[0]), ())),
            )
            for row in rows
        ]

    def get_strategy(self, account_id: str, strategy_id: str) -> StrategyRecord | None:
        for strategy in self.list_strategies(account_id):
            if strategy.id == strategy_id:
                return strategy
        return None

    def file_report(
        self, account_id: str, audit_id: str, strategy_id: str, *, at: datetime
    ) -> bool:
        """File a report of the account's list under one of its strategies;
        ``strategy_id=""`` takes it out of any. ``False`` if either is not the
        account's."""
        sa = self._sa
        link = self.strategy_reports
        with self.engine.begin() as conn:
            on_list = conn.execute(
                sa.select(self.account_audits.c.audit_id)
                .where(self.account_audits.c.account_id == account_id)
                .where(self.account_audits.c.audit_id == audit_id)
            ).first()
            if on_list is None:
                return False
            if strategy_id:
                owned = conn.execute(
                    sa.select(self.strategies.c.id)
                    .where(self.strategies.c.id == strategy_id)
                    .where(self.strategies.c.account_id == account_id)
                ).first()
                if owned is None:
                    return False
            conn.execute(link.delete().where(link.c.audit_id == audit_id))
            if strategy_id:
                conn.execute(
                    link.insert().values(
                        audit_id=audit_id,
                        strategy_id=strategy_id,
                        account_id=account_id,
                        added_at=_iso(at),
                    )
                )
        return True

    def rename_strategy(self, account_id: str, strategy_id: str, name: str) -> bool:
        name = strategy_name(name)
        if not name:
            return False
        table = self.strategies
        with self.engine.begin() as conn:
            result = conn.execute(
                table.update()
                .where((table.c.id == strategy_id) & (table.c.account_id == account_id))
                .values(name=name)
            )
        return bool(result.rowcount)

    def delete_strategy(self, account_id: str, strategy_id: str) -> bool:
        """Remove a strategy; its reports stay on the account's list."""
        table, link = self.strategies, self.strategy_reports
        with self.engine.begin() as conn:
            result = conn.execute(
                table.delete().where(
                    (table.c.id == strategy_id) & (table.c.account_id == account_id)
                )
            )
            if result.rowcount:
                conn.execute(link.delete().where(link.c.strategy_id == strategy_id))
        return bool(result.rowcount)

    # -- rate limits that survive a deploy ----------------------------------
    def attempt_hit(self, key: str, now: datetime, *, since: datetime) -> int:
        """Record an attempt for ``key``; return how many came before it since ``since``."""
        sa = self._sa
        table = self.attempts
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        with self.engine.begin() as conn:
            conn.execute(table.delete().where(table.c.at < _iso(since)))
            before = int(
                conn.execute(
                    sa.select(sa.func.count())
                    .select_from(table)
                    .where((table.c.key_sha256 == digest) & (table.c.at >= _iso(since)))
                ).scalar()
                or 0
            )
            conn.execute(table.insert().values(key_sha256=digest, at=_iso(now)))
        return before

    def attempt_count(self, key: str, *, since: datetime) -> int:
        sa = self._sa
        table = self.attempts
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        with self.engine.connect() as conn:
            return int(
                conn.execute(
                    sa.select(sa.func.count())
                    .select_from(table)
                    .where((table.c.key_sha256 == digest) & (table.c.at >= _iso(since)))
                ).scalar()
                or 0
            )

    # -- free-tier claims --------------------------------------------------
    def claim_free(
        self,
        reservation: str,
        *,
        keys: Sequence[str],
        slots: Mapping[str, Sequence[str]],
        at: datetime,
    ) -> str:
        """Take every key in ``keys`` and one key from each group in ``slots``,
        all or nothing, in one transaction.

        Returns ``""`` when everything was taken, ``"key"`` when a key was
        already taken, else the name of the first slot group that is full.
        """
        sa = self._sa
        table = self.free_claims
        created = _iso(at)
        failed = ""
        try:
            with self.engine.begin() as conn:
                for key in keys:
                    conn.execute(
                        table.insert().values(
                            claim_key=key[:200], reservation=reservation, created_at=created
                        )
                    )
                for name, group in slots.items():
                    for key in group:
                        try:
                            with conn.begin_nested():
                                conn.execute(
                                    table.insert().values(
                                        claim_key=key[:200],
                                        reservation=reservation,
                                        created_at=created,
                                    )
                                )
                        except sa.exc.IntegrityError:
                            continue
                        break
                    else:
                        failed = name
                        raise LookupError(name)
        except sa.exc.IntegrityError:
            return "key"
        except LookupError:
            return failed
        return ""

    def free_claim_taken(self, key: str) -> bool:
        """Whether :meth:`claim_free` already holds ``key``."""
        table = self.free_claims
        with self.engine.connect() as conn:
            row = conn.execute(
                self._sa.select(table.c.claim_key).where(table.c.claim_key == key[:200])
            ).first()
        return row is not None

    def release_free(self, reservation: str) -> None:
        """Give back what :meth:`claim_free` took for an upload that failed."""
        with self.engine.begin() as conn:
            conn.execute(
                self.free_claims.delete().where(self.free_claims.c.reservation == reservation)
            )

    # -- free previews -----------------------------------------------------
    def record_free_preview(
        self, audit_id: str, account_id: str, *, client_ip: str, at: datetime
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                self.free_previews.insert().values(
                    audit_id=audit_id,
                    account_id=account_id,
                    client_ip=client_ip[:64],
                    created_at=_iso(at),
                )
            )

    def delete_free_preview(self, audit_id: str) -> None:
        """Give the month's free preview back: ``audit_id`` became a full report."""
        with self.engine.begin() as conn:
            conn.execute(
                self.free_previews.delete().where(self.free_previews.c.audit_id == audit_id)
            )

    # -- the free full report waiting for a confirmed e-mail ----------------
    def record_welcome_pending(
        self,
        audit_id: str,
        account_id: str,
        *,
        device_sha256: str,
        file_sha256: str,
        client_ip: str,
        at: datetime,
    ) -> None:
        """Note a preview that confirming the e-mail may open in full."""
        sa = self._sa
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    self.welcome_pending.insert().values(
                        audit_id=audit_id,
                        account_id=account_id,
                        device_sha256=device_sha256[:64],
                        file_sha256=file_sha256[:64],
                        client_ip=client_ip[:64],
                        created_at=_iso(at),
                    )
                )
        except sa.exc.IntegrityError:  # pragma: no cover - one row per report
            return

    def welcome_pending_for(self, account_id: str, *, since: datetime) -> list[WelcomePending]:
        """The account's pending previews since ``since``, the most recent first."""
        sa = self._sa
        table = self.welcome_pending
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    sa.select(table)
                    .where(table.c.account_id == account_id)
                    .where(table.c.created_at >= _iso(since))
                    .order_by(table.c.created_at.desc(), table.c.audit_id)
                )
                .mappings()
                .all()
            )
        return [
            WelcomePending(
                audit_id=str(row["audit_id"]),
                account_id=str(row["account_id"]),
                device_sha256=str(row["device_sha256"] or ""),
                file_sha256=str(row["file_sha256"] or ""),
                client_ip=str(row["client_ip"] or ""),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def clear_welcome_pending(self, account_id: str) -> None:
        """Forget every pending preview of the account."""
        if not account_id:
            return  # never the previews uploaded without an account
        table = self.welcome_pending
        with self.engine.begin() as conn:
            conn.execute(table.delete().where(table.c.account_id == account_id))

    def anon_pending(self, audit_id: str) -> WelcomePending | None:
        """The pending row of a preview uploaded without an account, or ``None``.

        Only a row no account holds yet (``account_id == ""``).
        """
        if not _usable_key(audit_id):
            return None
        sa = self._sa
        table = self.welcome_pending
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    sa.select(table)
                    .where(table.c.audit_id == audit_id)
                    .where(table.c.account_id == "")
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return WelcomePending(
            audit_id=str(row["audit_id"]),
            account_id="",
            device_sha256=str(row["device_sha256"] or ""),
            file_sha256=str(row["file_sha256"] or ""),
            client_ip=str(row["client_ip"] or ""),
            created_at=str(row["created_at"]),
        )

    def welcome_pending_attach(self, audit_id: str, account_id: str) -> bool:
        """Give an account the pending row of a preview uploaded without one.

        Only a row no account holds yet changes, so two sign-ups from the same
        link cannot both take it. ``True`` when this call took it.
        """
        if not account_id or not _usable_key(audit_id):
            return False
        table = self.welcome_pending
        with self.engine.begin() as conn:
            result = conn.execute(
                table.update()
                .where(table.c.audit_id == audit_id)
                .where(table.c.account_id == "")
                .values(account_id=account_id)
            )
        return bool(result.rowcount)

    # -- previews uploaded without an account (the owner's funnel) ----------
    def record_anon_preview(self, audit_id: str, *, locale: str, ref: str, at: datetime) -> None:
        """Count a preview uploaded without an account."""
        sa = self._sa
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    self.anon_previews.insert().values(
                        audit_id=audit_id,
                        locale=locale[:8],
                        ref=ref[:32],
                        created_at=_iso(at),
                        linked_at="",
                    )
                )
        except sa.exc.IntegrityError:  # pragma: no cover - one row per report
            return

    def note_anon_linked(self, audit_id: str, *, at: datetime) -> bool:
        """Note that a preview uploaded without an account went on one; once."""
        if not _usable_key(audit_id):
            return False
        table = self.anon_previews
        with self.engine.begin() as conn:
            result = conn.execute(
                table.update()
                .where(table.c.audit_id == audit_id)
                .where(table.c.linked_at == "")
                .values(linked_at=_iso(at))
            )
        return bool(result.rowcount)

    def free_previews_since(
        self, since: datetime, *, account_id: str = "", client_ip: str = ""
    ) -> int:
        """Free previews since ``since``, for one account or one address."""
        sa = self._sa
        table = self.free_previews
        query = (
            sa.select(sa.func.count()).select_from(table).where(table.c.created_at >= _iso(since))
        )
        if account_id:
            query = query.where(table.c.account_id == account_id)
        elif client_ip:
            query = query.where(table.c.client_ip == client_ip)
        else:
            return 0
        with self.engine.connect() as conn:
            return int(conn.execute(query).scalar() or 0)

    def account_audits_list(self, account_id: str) -> list[AccountAudit]:
        """The account's reports, newest first."""
        sa = self._sa
        a, link = self.audits, self.account_audits
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(
                    a.c.id,
                    a.c.created_at,
                    link.c.linked_at,
                    a.c.overall_class,
                    a.c.paid,
                    a.c.paid_at,
                    a.c.stripe_session_id,
                    a.c.purged_at,
                    a.c.declared_json,
                    self.publications.c.public_id,
                    link.c.via,
                )
                .select_from(
                    link.join(a, a.c.id == link.c.audit_id).outerjoin(
                        self.publications, self.publications.c.audit_id == a.c.id
                    )
                )
                .where(link.c.account_id == account_id)
                .order_by(a.c.created_at.desc(), a.c.id)
            ).all()
        out = []
        for row in rows:
            reference = str(row[6] or "")
            paid_with = ""
            if row[4]:
                if reference.startswith(CODE_REFERENCE_PREFIX):
                    paid_with = "code"
                elif reference.startswith(WELCOME_REFERENCE_PREFIX):
                    paid_with = "welcome"
                else:
                    paid_with = "card"
            description = ""
            if row[8]:
                try:
                    description = str(json.loads(row[8]).get("description") or "")
                except (ValueError, AttributeError):
                    description = ""
            out.append(
                AccountAudit(
                    audit_id=str(row[0]),
                    created_at=str(row[1]),
                    linked_at=str(row[2]),
                    overall_class=str(row[3]),
                    paid=bool(row[4]),
                    paid_at=row[5],
                    paid_with=paid_with,
                    purged=bool(row[7]),
                    published=row[9] is not None,
                    description=" ".join(description.split())[:120],
                    own=row[10] in OWN_VIAS,
                    public_id=str(row[9] or ""),
                )
            )
        return out

    def account_codes_list(self, account_id: str) -> list[AccountCode]:
        """The account's access codes, oldest first."""
        sa = self._sa
        c, link = self.access_codes, self.account_codes
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    sa.select(c, link.c.linked_at)
                    .select_from(link.join(c, c.c.id == link.c.code_id))
                    .where(link.c.account_id == account_id)
                    .order_by(link.c.linked_at, c.c.id)
                )
                .mappings()
                .all()
            )
        return [
            AccountCode(
                code=AccessCodeRecord(
                    id=row["id"],
                    note=row["note"],
                    credits_total=int(row["credits_total"]),
                    credits_used=int(row["credits_used"]),
                    created_at=row["created_at"],
                    expires_at=row["expires_at"],
                    disabled=bool(row["disabled"]),
                ),
                linked_at=row["linked_at"],
            )
            for row in rows
        ]

    def account_export(self, account_id: str) -> dict[str, Any] | None:
        """Everything the service keeps about one account, for "Descargar mis datos".

        Only rows keyed to ``account_id``. Never the password hash, a session
        or reset token, a report link's token or a code in clear (none is kept
        in clear); a code's private note is the owner's, not the customer's.
        """
        sa = self._sa
        found = self.get_account(account_id)
        if found is None:
            return None
        with self.engine.connect() as conn:
            info = self.session_info
            sessions = conn.execute(
                sa.select(
                    self.account_sessions.c.created_at,
                    self.account_sessions.c.expires_at,
                    info.c.device,
                    info.c.network,
                    info.c.last_seen,
                )
                .select_from(
                    self.account_sessions.outerjoin(
                        info, info.c.token_sha256 == self.account_sessions.c.token_sha256
                    )
                )
                .where(self.account_sessions.c.account_id == account_id)
                .order_by(self.account_sessions.c.created_at)
            ).all()
            link = self.account_audits
            ips = dict(
                conn.execute(
                    sa.select(self.audits.c.id, self.audits.c.client_ip)
                    .select_from(link.join(self.audits, self.audits.c.id == link.c.audit_id))
                    .where((link.c.account_id == account_id) & link.c.via.in_(OWN_VIAS))
                ).all()
            )
            previews = conn.execute(
                sa.select(
                    self.free_previews.c.audit_id,
                    self.free_previews.c.created_at,
                    self.free_previews.c.client_ip,
                )
                .where(self.free_previews.c.account_id == account_id)
                .order_by(self.free_previews.c.created_at)
            ).all()
            welcome = (
                conn.execute(
                    sa.select(self.welcome_reports).where(
                        self.welcome_reports.c.account_id == account_id
                    )
                )
                .mappings()
                .first()
            )
            pending = self.welcome_pending
            waiting = conn.execute(
                sa.select(
                    pending.c.audit_id,
                    pending.c.created_at,
                    pending.c.client_ip,
                    pending.c.device_sha256,
                    pending.c.file_sha256,
                )
                .where(pending.c.account_id == account_id)
                .order_by(pending.c.created_at)
            ).all()
            card = conn.execute(
                sa.select(self.card_checks.c.created_at, self.card_checks.c.card_sha256).where(
                    self.card_checks.c.account_id == account_id
                )
            ).first()
            maps = conn.execute(
                sa.select(
                    self.column_maps.c.header_sha256,
                    self.column_maps.c.columns_json,
                    self.column_maps.c.updated_at,
                ).where(self.column_maps.c.account_id == account_id)
            ).all()
            invite = conn.execute(
                sa.select(self.invite_links.c.token).where(
                    self.invite_links.c.account_id == account_id
                )
            ).first()
            r = self.referrals
            invited = conn.execute(
                sa.select(r.c.joined_at, r.c.outcome, r.c.decided_at)
                .where(r.c.inviter_id == account_id)
                .order_by(r.c.joined_at)
            ).all()
            joined_through = conn.execute(
                sa.select(r.c.invitee_id).where(r.c.invitee_id == account_id)
            ).first()
        reports = [
            {
                "audit_id": item.audit_id,
                "created_at": item.created_at,
                "added_to_account_at": item.linked_at,
                "uploaded_by_this_account": item.own,
                "class": item.overall_class,
                "paid": item.paid,
                "paid_at": item.paid_at,
                "paid_with": item.paid_with,
                "files_deleted": item.purged,
                "public_verification_page": item.public_id or None,
                # A report saved from someone else's link keeps its uploader's
                # words private unless this account paid for it.
                "description": item.description if item.own or item.paid else "",
                "upload_ip": ips.get(item.audit_id, "") if item.own else "",
            }
            for item in self.account_audits_list(account_id)
        ]
        return {
            "account": {
                "email": found.email,
                "language": found.locale,
                "created_at": found.created_at,
            },
            "sessions": [
                {
                    "created_at": row[0],
                    "expires_at": row[1],
                    "device": row[2] or "",
                    "network": row[3] or "",
                    "last_used_at": row[4] or None,
                }
                for row in sessions
            ],
            "activity": [
                {"event": e.kind, "at": e.at, "device": e.device, "network": e.network}
                for e in self.list_events(account_id)
            ],
            "account_page_seen": self._seen_list(account_id),
            # The public half only; the private key never left the device.
            "passkeys": [
                {
                    "name": p.label,
                    "site": p.rp_id,
                    "created_at": p.created_at,
                    "last_used_at": p.last_used_at or None,
                }
                for p in self.list_passkeys(account_id)
            ],
            "failed_signins": [
                {"last_at": e.at, "attempts": e.count, "device": e.device, "network": e.network}
                for e in self.list_failed_signins(account_id)
            ],
            "reports": reports,
            "access_codes": [
                {
                    "id": item.code.id,
                    "credits_total": item.code.credits_total,
                    "credits_used": item.code.credits_used,
                    "created_at": item.code.created_at,
                    "expires_at": item.code.expires_at,
                    "disabled": item.code.disabled,
                    "added_to_account_at": item.linked_at,
                }
                for item in self.account_codes_list(account_id)
            ],
            "strategies": [
                {
                    "id": strategy.id,
                    "name": strategy.name,
                    "created_at": strategy.created_at,
                    "reports": list(strategy.audit_ids),
                }
                for strategy in self.list_strategies(account_id)
            ],
            "free_previews": [
                {"audit_id": row[0], "created_at": row[1], "upload_ip": row[2]} for row in previews
            ],
            "free_first_report": (
                {
                    "audit_id": welcome["audit_id"],
                    "created_at": welcome["created_at"],
                    "upload_ip": welcome["client_ip"],
                    "browser_mark_sha256": welcome["device_sha256"],
                    "file_fingerprint_sha256": welcome["file_sha256"],
                }
                if welcome is not None
                else None
            ),
            "free_first_report_pending": [
                {
                    "audit_id": row[0],
                    "created_at": row[1],
                    "upload_ip": row[2],
                    "browser_mark_sha256": row[3],
                    "file_fingerprint_sha256": row[4],
                }
                for row in waiting
            ],
            "card_check": (
                {"created_at": card[0], "card_fingerprint_sha256": card[1]}
                if card is not None
                else None
            ),
            "column_maps": [
                {"header_sha256": row[0], "columns": json.loads(row[1]), "updated_at": row[2]}
                for row in maps
            ],
            # Who joined through this account's link stays theirs: only dates
            # and outcomes, never the other account.
            "invites": {
                "link_token": invite[0] if invite is not None else "",
                "joined": [
                    {"joined_at": row[0], "outcome": row[1] or "waiting", "decided_at": row[2]}
                    for row in invited
                ],
                "joined_through_an_invite": joined_through is not None,
            },
            "arrived_through_link_tag": self.account_ref(account_id),
            "track_records": store_hooks.export_account(self, account_id),
            # Only when it was made: the key's hash never leaves the database.
            "recovery_key_created_at": self.recovery_key_created(account_id),
            # When two-step sign-in was turned on; never its secret.
            "two_step_on_since": self.two_step_on(account_id) or None,
        }

    def account_credits(self, account_id: str, now: datetime) -> int:
        """Audits the account's usable codes can still unlock."""
        stamp = _iso(now)
        return sum(
            item.code.credits_left
            for item in self.account_codes_list(account_id)
            if item.usable(stamp)
        )

    def redeem_with_account(self, audit_id: str, account_id: str, *, at: datetime) -> bool:
        """Unlock an unpaid audit with one credit from the account's codes.

        The code that expires first is spent first. The credit and the
        unlock share one transaction, as in :meth:`redeem_for_audit`.
        """
        if not _usable_key(audit_id):
            return False
        sa = self._sa
        c, link = self.access_codes, self.account_codes
        now = _iso(at)
        try:
            with self.engine.begin() as conn:
                unpaid = conn.execute(
                    sa.select(self.audits.c.id)
                    .where(self.audits.c.id == audit_id)
                    .where(self.audits.c.paid.is_(False))
                ).first()
                if unpaid is None:
                    return False
                candidates = conn.execute(
                    sa.select(c.c.id, c.c.expires_at)
                    .select_from(link.join(c, c.c.id == link.c.code_id))
                    .where(link.c.account_id == account_id)
                    .order_by(c.c.created_at, c.c.id)
                ).all()
                # Codes that expire go first, soonest first; then the rest.
                ordered = sorted(candidates, key=lambda r: (r[1] is None, r[1] or ""))
                for code_id, _ in ordered:
                    spent = conn.execute(
                        c.update()
                        .where(c.c.id == code_id)
                        .where(c.c.credits_used < c.c.credits_total)
                        .where(c.c.disabled.is_(False))
                        .where((c.c.expires_at.is_(None)) | (c.c.expires_at > now))
                        .values(credits_used=c.c.credits_used + 1)
                    )
                    if not spent.rowcount:
                        continue
                    result = conn.execute(
                        self.audits.update()
                        .where(self.audits.c.id == audit_id)
                        .where(self.audits.c.paid.is_(False))
                        .values(
                            paid=True,
                            paid_at=now,
                            stripe_session_id=CODE_REFERENCE_PREFIX + str(code_id),
                        )
                    )
                    if not result.rowcount:
                        raise _RedeemRace()
                    return True
                return False
        except _RedeemRace:  # pragma: no cover - lost a race; the credit rolled back
            return False

    # -- the owner's funnel ------------------------------------------------
    def count_visit(self, *, day: str, locale: str, ref: str, amount: int = 1) -> None:
        """Add ``amount`` visits to the counter of ``(day, locale, ref)``."""
        sa = self._sa
        table = self.funnel_visits
        key = (table.c.day == day) & (table.c.locale == locale[:8]) & (table.c.ref == ref[:24])
        for _ in range(2):
            with self.engine.begin() as conn:
                bumped = conn.execute(
                    table.update().where(key).values(visits=table.c.visits + amount)
                ).rowcount
                if bumped:
                    return
            try:
                with self.engine.begin() as conn:
                    conn.execute(
                        table.insert().values(
                            day=day, locale=locale[:8], ref=ref[:24], visits=amount
                        )
                    )
                return
            except sa.exc.IntegrityError:  # pragma: no cover - another request inserted it
                continue

    def set_account_ref(self, account_id: str, ref: str, *, at: datetime) -> None:
        """Keep the tag that brought a new account; the first one stays."""
        sa = self._sa
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    self.account_refs.insert().values(
                        account_id=account_id, ref=ref[:24], created_at=_iso(at)
                    )
                )
        except sa.exc.IntegrityError:
            return

    def account_ref(self, account_id: str) -> str:
        """The tag of the link that brought the account, or ``""``."""
        sa = self._sa
        with self.engine.connect() as conn:
            value = conn.execute(
                sa.select(self.account_refs.c.ref).where(
                    self.account_refs.c.account_id == account_id
                )
            ).scalar()
        return str(value or "")

    def funnel_events(self, since_day: str) -> dict[str, list[tuple[str, str, str, int]]]:
        """Rows ``(day, locale, ref, count)`` per funnel stage since ``since_day``.

        Visits come from their counters; the rest from the tables the service
        already keeps, with the language and tag of the account involved.
        An event with no account (or a deleted one) has language ``-`` and
        no tag.
        """
        sa = self._sa
        acc, refs, links = self.accounts, self.account_refs, self.account_audits
        visits_t = self.funnel_visits
        out: dict[str, list[tuple[str, str, str, int]]] = {}
        with self.engine.connect() as conn:
            out["visits"] = [
                (str(r[0]), str(r[1]), str(r[2]), int(r[3]))
                for r in conn.execute(
                    sa.select(
                        visits_t.c.day, visits_t.c.locale, visits_t.c.ref, visits_t.c.visits
                    ).where(visits_t.c.day >= since_day)
                ).all()
            ]

            def by_account(stage: str, when: Any, account_col: Any, source: Any) -> None:
                if source is not acc:
                    source = source.outerjoin(acc, acc.c.id == account_col)
                rows = conn.execute(
                    sa.select(when, acc.c.locale, refs.c.ref)
                    .select_from(source.outerjoin(refs, refs.c.account_id == account_col))
                    .where(when >= since_day)
                ).all()
                out[stage] = [(str(r[0])[:10], str(r[1] or "-"), str(r[2] or ""), 1) for r in rows]

            by_account("signups", acc.c.created_at, acc.c.id, acc)
            verified = self.verified_emails
            rows = conn.execute(
                sa.select(verified.c.verified_at, acc.c.locale, refs.c.ref)
                .select_from(
                    verified.join(acc, acc.c.id == verified.c.account_id).outerjoin(
                        refs, refs.c.account_id == verified.c.account_id
                    )
                )
                .where(verified.c.verified_at >= since_day)
                .where(verified.c.email == acc.c.email)
            ).all()
            out["email_verified"] = [
                (str(when)[:10], str(locale or "-"), str(ref or ""), 1)
                for when, locale, ref in rows
            ]
            audits = self.audits
            uploaded = conn.execute(
                sa.select(audits.c.created_at, acc.c.locale, refs.c.ref)
                .select_from(
                    audits.outerjoin(
                        links,
                        sa.and_(links.c.audit_id == audits.c.id, links.c.via == VIA_UPLOAD),
                    )
                    .outerjoin(acc, acc.c.id == links.c.account_id)
                    .outerjoin(refs, refs.c.account_id == links.c.account_id)
                )
                .where(audits.c.created_at >= since_day)
            ).all()
            out["uploads"] = [
                (str(when)[:10], str(locale or "-"), str(ref or ""), 1)
                for when, locale, ref in uploaded
            ]
            by_account(
                "referrals_accepted",
                self.referrals.c.joined_at,
                self.referrals.c.invitee_id,
                self.referrals,
            )
            welcome = self.welcome_reports
            rows = conn.execute(
                sa.select(welcome.c.created_at, acc.c.locale, refs.c.ref)
                .select_from(
                    welcome.outerjoin(acc, acc.c.id == welcome.c.account_id).outerjoin(
                        refs, refs.c.account_id == welcome.c.account_id
                    )
                )
                .where(welcome.c.created_at >= since_day)
                .where(welcome.c.audit_id != "")
            ).all()
            out["welcome"] = [(str(r[0])[:10], str(r[1] or "-"), str(r[2] or ""), 1) for r in rows]
            previews = self.free_previews
            by_account("previews", previews.c.created_at, previews.c.account_id, previews)
            anon = self.anon_previews
            out["anon_previews"] = [
                (str(when)[:10], str(locale or "-"), str(ref or ""), 1)
                for when, locale, ref in conn.execute(
                    sa.select(anon.c.created_at, anon.c.locale, anon.c.ref).where(
                        anon.c.created_at >= since_day
                    )
                ).all()
            ]
            out["anon_linked"] = [
                (str(when)[:10], str(locale or "-"), str(ref or ""), 1)
                for when, locale, ref in conn.execute(
                    sa.select(anon.c.linked_at, anon.c.locale, anon.c.ref)
                    .where(anon.c.linked_at != "")
                    .where(anon.c.linked_at >= since_day)
                ).all()
            ]
            redeemed = conn.execute(
                sa.select(audits.c.paid_at, acc.c.locale, refs.c.ref)
                .select_from(
                    audits.outerjoin(links, links.c.audit_id == audits.c.id)
                    .outerjoin(acc, acc.c.id == links.c.account_id)
                    .outerjoin(refs, refs.c.account_id == links.c.account_id)
                )
                .where(audits.c.paid.is_(True))
                .where(audits.c.paid_at >= since_day)
                .where(audits.c.stripe_session_id.like(CODE_REFERENCE_PREFIX + "%"))
            ).all()
            out["credit_used"] = [
                (str(when)[:10], str(locale or "-"), str(ref or ""), 1)
                for when, locale, ref in redeemed
            ]
            grants = self.credit_grants
            account_codes = self.account_codes
            gifts = conn.execute(
                sa.select(grants.c.created_at, acc.c.locale, refs.c.ref, grants.c.credits)
                .select_from(
                    grants.outerjoin(account_codes, account_codes.c.code_id == grants.c.code_id)
                    .outerjoin(acc, acc.c.id == account_codes.c.account_id)
                    .outerjoin(refs, refs.c.account_id == account_codes.c.account_id)
                )
                .where(grants.c.origin == "referral")
                .where(grants.c.created_at >= since_day)
            ).all()
            out["gift_credits"] = [
                (str(when)[:10], str(locale or "-"), str(ref or ""), int(credits))
                for when, locale, ref, credits in gifts
            ]
            orders = self.checkout_orders
            started = conn.execute(
                sa.select(orders.c.created_at, acc.c.locale, refs.c.ref)
                .select_from(
                    orders.outerjoin(acc, acc.c.id == orders.c.account_id).outerjoin(
                        refs, refs.c.account_id == orders.c.account_id
                    )
                )
                .where(orders.c.created_at >= since_day)
                .where(orders.c.checkout_url != "")
            ).all()
            out["checkout_started"] = [
                (str(when)[:10], str(locale or "-"), str(ref or ""), 1)
                for when, locale, ref in started
            ]
            refunds = self.stripe_refunds
            returned = conn.execute(
                sa.select(
                    refunds.c.succeeded_at,
                    refunds.c.amount_minor,
                    acc.c.locale,
                    refs.c.ref,
                )
                .select_from(
                    refunds.join(orders, orders.c.id == refunds.c.order_id)
                    .outerjoin(acc, acc.c.id == orders.c.account_id)
                    .outerjoin(refs, refs.c.account_id == orders.c.account_id)
                )
                .where(refunds.c.status == "succeeded")
                .where(refunds.c.currency == "usd")
                .where(refunds.c.livemode.is_(True))
                .where(orders.c.livemode.is_(True))
                .where(refunds.c.succeeded_at >= since_day)
            ).all()
            out["refund_usd_cents"] = [
                (str(when)[:10], str(locale or "-"), str(ref or ""), int(amount))
                for when, amount, locale, ref in returned
            ]
            purchases = conn.execute(
                sa.select(
                    orders.c.confirmed_at,
                    orders.c.account_id,
                    orders.c.plan,
                    orders.c.status,
                    orders.c.paid_amount_cents,
                    acc.c.locale,
                    refs.c.ref,
                )
                .select_from(
                    orders.outerjoin(acc, acc.c.id == orders.c.account_id).outerjoin(
                        refs, refs.c.account_id == orders.c.account_id
                    )
                )
                .where(orders.c.status.in_(("delivered", "duplicate", "paid_review")))
                .where(orders.c.livemode.is_(True))
                .order_by(orders.c.confirmed_at, orders.c.id)
            ).all()
        for stage in (
            "purchases",
            "buyers",
            "repeat_purchases",
            "deliveries",
            "rights_sold",
            "gross_usd_cents",
        ):
            out[stage] = []
        seen_buyers: set[str] = set()
        for when, account_id, plan, status, amount, locale, ref in purchases:
            account_id = str(account_id or "")
            repeat = bool(account_id and account_id in seen_buyers)
            if account_id:
                seen_buyers.add(account_id)
            if str(when) < since_day:
                continue
            event = (str(when)[:10], str(locale or "-"), str(ref or ""))
            out["purchases"].append((*event, 1))
            out["gross_usd_cents"].append((*event, int(amount)))
            if status == "delivered":
                out["deliveries"].append((*event, 1))
                out["rights_sold"].append((*event, 3 if plan == "pack" else 1))
            if account_id:
                out["repeat_purchases" if repeat else "buyers"].append((*event, 1))
        return out

    def funnel_country_events(self, since_day: str) -> list[tuple[str, int, int, int]]:
        """Live paid orders by provider billing country; older orders stay unknown.

        Returns (country, purchases, deliveries, gross USD cents). A country
        declared before Checkout is not substituted for Stripe's observed one.
        """
        sa = self._sa
        orders = self.checkout_orders
        markets = self.checkout_order_markets
        with self.engine.connect() as conn:
            rows = conn.execute(
                sa.select(
                    orders.c.status,
                    orders.c.paid_amount_cents,
                    markets.c.billing_country,
                )
                .select_from(orders.outerjoin(markets, markets.c.order_id == orders.c.id))
                .where(orders.c.status.in_(("delivered", "duplicate", "paid_review")))
                .where(orders.c.livemode.is_(True))
                .where(orders.c.confirmed_at >= since_day)
            ).all()
        buckets: dict[str, list[int]] = {}
        for status, amount, country in rows:
            code = str(country or "").upper()
            code = code if len(code) == 2 and code.isalpha() else "NOT_MEASURED"
            counts = buckets.setdefault(code, [0, 0, 0])
            counts[0] += 1
            counts[1] += int(status == "delivered")
            counts[2] += int(amount)
        return [
            (country, values[0], values[1], values[2])
            for country, values in sorted(buckets.items())
        ]

    # -- retention ---------------------------------------------------------
    def purge_expired(self, now: datetime, *, retention_days: int, dry_run: bool = False) -> int:
        """Drop uploads, reports and declared text of unpaid audits older than
        the retention window. Hashes, class and id stay so the record remains
        verifiable. A published audit keeps what its verification page shows
        (``public_view``) so the page and badge survive. The upload IP of
        every audit past the window is cleared, paid or not. Returns how many
        unpaid audits were (or would be) purged."""
        sa = self._sa
        cutoff = _iso(now - timedelta(days=retention_days))
        condition = (
            (self.audits.c.created_at < cutoff)
            & (self.audits.c.paid.is_(False))
            & (self.audits.c.purged_at.is_(None))
        )
        with self.engine.begin() as conn:
            count = int(
                conn.execute(
                    sa.select(sa.func.count()).select_from(self.audits).where(condition)
                ).scalar()
                or 0
            )
            if dry_run:
                return count
            store_hooks.on_purge(self, conn, cutoff=cutoff)
            conn.execute(
                self.email_outbox.delete().where(
                    self.email_outbox.c.expires_at < _iso(now - timedelta(days=30))
                )
            )
            conn.execute(
                self.refused_payments.delete().where(self.refused_payments.c.created_at < cutoff)
            )
            # The upload IP only serves the hourly limit: past the retention
            # window it goes for every audit, paid ones included.
            conn.execute(
                self.audits.update()
                .where((self.audits.c.created_at < cutoff) & (self.audits.c.client_ip != ""))
                .values(client_ip="")
            )
            conn.execute(
                self.welcome_reports.update()
                .where(
                    (self.welcome_reports.c.created_at < cutoff)
                    & (self.welcome_reports.c.client_ip != "")
                )
                .values(client_ip="")
            )
            conn.execute(
                self.free_claims.delete().where(
                    (self.free_claims.c.created_at < cutoff)
                    & self.free_claims.c.claim_key.like("%:ip:%")
                )
            )
            conn.execute(
                self.free_previews.update()
                .where(
                    (self.free_previews.c.created_at < cutoff)
                    & (self.free_previews.c.client_ip != "")
                )
                .values(client_ip="")
            )
            # A pending free report is only honoured for days: past the
            # window nothing of it is kept, its address included.
            conn.execute(
                self.welcome_pending.delete().where(self.welcome_pending.c.created_at < cutoff)
            )
            conn.execute(
                self.anon_previews.delete().where(self.anon_previews.c.created_at < cutoff)
            )
            if count == 0:
                return count
            expired = sa.select(self.audits.c.id).where(condition)
            published = conn.execute(
                sa.select(self.audits.c.id, self.audits.c.result_json)
                .where(condition & self.audits.c.id.in_(sa.select(self.publications.c.audit_id)))
                .where(self.audits.c.result_json.is_not(None))
            ).all()
            for audit_id, result_json in published:
                try:
                    view, digest = public_view(result_json)
                except ValueError:  # an unreadable result keeps nothing; its page answers 410
                    continue
                conn.execute(
                    self.publication_views.delete().where(
                        self.publication_views.c.audit_id == audit_id
                    )
                )
                conn.execute(
                    self.publication_views.insert().values(
                        audit_id=audit_id,
                        result_sha256=digest,
                        view_json=canonical_dumps(view),
                        kept_at=_iso(now),
                    )
                )
            conn.execute(
                self.audit_files.update()
                .where(self.audit_files.c.audit_id.in_(expired))
                .values(data=None)
            )
            conn.execute(
                self.audits.update()
                .where(condition)
                .values(
                    equity_csv=None,
                    trades_csv=None,
                    benchmark_csv=None,
                    variants_csv=None,
                    report_html=None,
                    result_json=None,
                    declared_json=None,
                    purged_at=_iso(now),
                )
            )
        return count


def public_view(result_json: str) -> tuple[dict[str, Any], str]:
    """The allow-listed fields the public verification page reads, and the
    SHA-256 of the full result it came from.

    The page also says what was audited and over which dates, so the view
    keeps the first and last timestamps and the sampling frequency. Nothing
    else survives: no description, no client text findings, no series, no
    trades (nor their count), no number of observations, no statistics and no
    files. The privacy policy and the terms (``legal.py``) list what the page
    shows and what the purge keeps; a new field here needs that text first.
    """
    result = AuditResult.model_validate_json(result_json)
    data = result.model_dump(mode="json")
    inputs = data.get("inputs", {})
    # Expose only the format fact, never the parser's warning text, publicly.
    from quant_trade.audit.importers import PDF_ROWS_WARNING

    source_is_pdf = any(
        str(warning).endswith(PDF_ROWS_WARNING) for warning in inputs.get("parse_warnings") or []
    )
    verdict = data["verdict"]
    # Whether the trial count was left undeclared: a fact the page's fixed
    # sentence for the multiplicity dimension depends on, never a number.
    from quant_trade.audit.verdict import trials_undeclared

    view = {
        "generated_at_utc": data.get("generated_at_utc", ""),
        "verdict": {
            "overall": verdict["overall"],
            "dimensions": [
                {
                    "name": d["name"],
                    "status": d["status"],
                    "undeclared": trials_undeclared(d.get("inputs")),
                }
                for d in verdict["dimensions"]
            ],
        },
        "inputs": {
            key: inputs[key]
            for key in (
                "digests",
                "dataset_digest",
                "source_format",
                "source",
                "first_timestamp",
                "last_timestamp",
                "frequency_label",
            )
            if key in inputs
        }
        | {"source_is_pdf": source_is_pdf},
        "engine": {key: data.get("engine", {}).get(key) for key in ("name", "package_version")},
        "fund": {"track_record": bool((data.get("fund") or {}).get("track_record"))},
        "declared": {"trials": data.get("declared", {}).get("trials")},
        "multiplicity": {"trials_used": data.get("multiplicity", {}).get("trials_used")},
    }
    digest = sha256_of_text(canonical_dumps(data))
    return view, digest


def _usable_key(value: str) -> bool:
    """Whether an id from a URL or form can be looked up at all.

    PostgreSQL refuses text holding a NUL, so ``/v/%00`` was a server error;
    no id ever holds one, so the lookup simply finds nothing."""
    return "\x00" not in value


def _stripe_object_id(value: str, prefix: str) -> bool:
    """Accept opaque Stripe ids, never control characters or unlimited input."""
    return (
        value.startswith(prefix)
        and len(prefix) < len(value) <= 255
        and all(
            ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for ch in value
        )
    )


def make_store(url: str) -> Store:
    return Store(url)


__all__ = [
    "CARD_CLAIM_PREFIX",
    "ACCOUNT_ORDER_PREFIX",
    "CODE_REFERENCE_PREFIX",
    "WELCOME_REFERENCE_PREFIX",
    "AccountAudit",
    "PasskeyRecord",
    "AccountCode",
    "AccountRecord",
    "OWN_VIAS",
    "VIA_PAID",
    "VIA_SAVED",
    "VIA_UPLOAD",
    "REQUIRE_WEB",
    "AccessCodeRecord",
    "AuditRecord",
    "InstitutionalRequest",
    "PublicationRecord",
    "Store",
    "account_order_ref",
    "hash_access_code",
    "make_store",
    "new_access_code",
    "normalise_access_code",
    "public_view",
]
