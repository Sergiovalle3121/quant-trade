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
import json
import secrets
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
        self.metadata.create_all(self.engine)

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
            deleted = conn.execute(self.audits.delete().where(self.audits.c.id == audit_id))
        return bool(deleted.rowcount)

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
            # The upload IP only serves the hourly limit: past the retention
            # window it goes for every audit, paid ones included.
            conn.execute(
                self.audits.update()
                .where((self.audits.c.created_at < cutoff) & (self.audits.c.client_ip != ""))
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
