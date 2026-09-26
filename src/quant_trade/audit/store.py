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

from quant_trade.audit.schema import AuditResult
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text

REQUIRE_WEB = 'audit web requires: python -m pip install -e ".[web]"'

#: No 0/O or 1/I/L: a code read aloud over the phone survives.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_PREFIX = "AUD"
CODE_GROUPS = 3
CODE_GROUP_LENGTH = 4
#: The reference a code-paid audit carries instead of a Stripe session.
CODE_REFERENCE_PREFIX = "code:"
#: The payment reference of the free first full report of a new account.
WELCOME_REFERENCE_PREFIX = "welcome:"


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
class RefusedPayment:
    """A live card payment Stripe charged that unlocked nothing: ids only."""

    session_id: str
    audit_id: str
    reason: str
    created_at: str


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
)
#: How long an account event is kept, and how many at most per account.
ACCOUNT_EVENT_DAYS = 90
ACCOUNT_EVENT_MAX = 50
#: Wrong-password lines kept per account: their own cap, so a flood of
#: failures never pushes real events out of the ACCOUNT_EVENT_MAX.
FAILED_SIGNIN_MAX = 20


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


class Store:
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
        self.waitlist = sa.Table(
            "waitlist",
            self.metadata,
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("email", sa.String(255), nullable=False, unique=True),
            sa.Column("created_at", sa.String(40), nullable=False),
            sa.Column("note", sa.Text, nullable=False, default=""),
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
        self.metadata.create_all(self.engine)

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
    ) -> bool:
        """Insert an audit. ``files`` maps a digest name (``report.html``,
        ``optimization.xml``) to its bytes; its hash comes from ``digests``.

        With ``access_code`` one credit is redeemed in the same transaction
        and the audit is born paid. Returns whether it is paid; a code that is
        unknown, used up, expired or disabled simply yields ``False``.
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
        """Remove every trace of one audit: row, hashes, files and publication.

        Unlike the retention purge nothing verifiable is kept: this answers a
        client's deletion request. ``False`` when the id is unknown.
        """
        if not _usable_key(audit_id):
            return False
        with self.engine.begin() as conn:
            conn.execute(self.publications.delete().where(self.publications.c.audit_id == audit_id))
            conn.execute(
                self.publication_views.delete().where(self.publication_views.c.audit_id == audit_id)
            )
            conn.execute(self.audit_files.delete().where(self.audit_files.c.audit_id == audit_id))
            conn.execute(self.issued_files.delete().where(self.issued_files.c.audit_id == audit_id))
            conn.execute(
                self.account_audits.delete().where(self.account_audits.c.audit_id == audit_id)
            )
            conn.execute(
                self.strategy_reports.delete().where(self.strategy_reports.c.audit_id == audit_id)
            )
            deleted = conn.execute(self.audits.delete().where(self.audits.c.id == audit_id))
        return bool(deleted.rowcount)

    # -- accounts ----------------------------------------------------------
    def create_account(
        self, *, email: str, password_hash: str, locale: str, at: datetime
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
            for table in (
                self.account_sessions,
                self.account_resets,
                self.account_codes,
                self.account_audits,
                self.column_maps,
                self.strategies,
                self.strategy_reports,
                self.account_refs,
                self.recovery_keys,
                self.two_step,
                self.two_step_challenges,
                self.session_info,
                self.account_events,
                self.failed_signins,
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
    ) -> str:
        """Credit the inviter once ``invitee_id`` got its free first report.

        Call it only after :meth:`grant_welcome` succeeded for the invitee.
        Returns ``credited``, ``self`` (the invitee's browser or address is
        one the inviter used), ``cap`` (the inviter's calendar month already
        holds ``monthly_cap`` credited invites) or ``""`` (no pending invite).
        """
        if credits < 1:
            raise ValueError("credits must be at least 1")
        from quant_trade.audit.accounts import network_address

        sa = self._sa
        r = self.referrals
        now = _iso(at)
        month = now[:7]
        with self.engine.begin() as conn:
            row = conn.execute(
                sa.select(r.c.inviter_id, r.c.device_sha256)
                .where(r.c.invitee_id == invitee_id)
                .where(r.c.outcome == "")
            ).first()
            if row is None:
                return ""
            inviter_id, signup_device = str(row[0]), str(row[1] or "")
            devices, addresses = self._inviter_marks(conn, inviter_id)
            marks = {device_sha256, signup_device} - {""}
            outcome = ""
            if marks & devices or (client_ip and network_address(client_ip) in addresses):
                outcome = "self"
            slot = ""
            if not outcome:
                for n in range(monthly_cap):
                    candidate = f"{inviter_id}:{month}:{n}"
                    try:
                        with conn.begin_nested():
                            conn.execute(
                                r.update()
                                .where(r.c.invitee_id == invitee_id)
                                .values(reward_slot=candidate)
                            )
                    except sa.exc.IntegrityError:
                        continue
                    slot = candidate
                    break
                outcome = "credited" if slot else "cap"
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
                    self.account_codes.insert().values(
                        code_id=code_id, account_id=inviter_id, linked_at=now
                    )
                )
            conn.execute(
                r.update()
                .where(r.c.invitee_id == invitee_id)
                .where(r.c.outcome == "")
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
            audits = self.audits
            paid = conn.execute(
                sa.select(audits.c.paid_at, audits.c.stripe_session_id, acc.c.locale, refs.c.ref)
                .select_from(
                    audits.outerjoin(links, links.c.audit_id == audits.c.id)
                    .outerjoin(acc, acc.c.id == links.c.account_id)
                    .outerjoin(refs, refs.c.account_id == links.c.account_id)
                )
                .where(audits.c.paid.is_(True))
                .where(audits.c.paid_at >= since_day)
            ).all()
        out["paid_code"], out["paid_card"] = [], []
        for when, reference, locale, ref in paid:
            reference = str(reference or "")
            if reference.startswith(WELCOME_REFERENCE_PREFIX):
                continue
            stage = "paid_code" if reference.startswith(CODE_REFERENCE_PREFIX) else "paid_card"
            out[stage].append((str(when)[:10], str(locale or "-"), str(ref or ""), 1))
        return out

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

    Nothing else survives: no description, no client text findings, no
    series, trades, statistics or files.
    """
    result = AuditResult.model_validate_json(result_json)
    data = result.model_dump(mode="json")
    inputs = data.get("inputs", {})
    verdict = data["verdict"]
    view = {
        "generated_at_utc": data.get("generated_at_utc", ""),
        "verdict": {
            "overall": verdict["overall"],
            "dimensions": [
                {"name": d["name"], "status": d["status"]} for d in verdict["dimensions"]
            ],
        },
        "inputs": {
            key: inputs[key]
            for key in ("digests", "dataset_digest", "source_format", "source")
            if key in inputs
        },
        "engine": {key: data.get("engine", {}).get(key) for key in ("name", "package_version")},
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


def make_store(url: str) -> Store:
    return Store(url)


__all__ = [
    "CODE_REFERENCE_PREFIX",
    "WELCOME_REFERENCE_PREFIX",
    "AccountAudit",
    "AccountCode",
    "AccountRecord",
    "OWN_VIAS",
    "VIA_PAID",
    "VIA_SAVED",
    "VIA_UPLOAD",
    "REQUIRE_WEB",
    "AccessCodeRecord",
    "AuditRecord",
    "PublicationRecord",
    "Store",
    "hash_access_code",
    "make_store",
    "new_access_code",
    "normalise_access_code",
    "public_view",
]
