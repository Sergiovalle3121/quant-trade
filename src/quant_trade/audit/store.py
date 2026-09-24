"""Persistence for the audit service: audits, payments, waitlist, retention.

SQLAlchemy Core over two tables, SQLite by default and Postgres by URL. The
uploaded bytes are stored so a paid report can be regenerated and so the
retention purge has something concrete to delete; hashes and the verdict
class survive the purge so a client can still prove what was audited.

Timestamps are ISO-8601 UTC strings: they sort correctly on every backend
and never lose their timezone in transit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REQUIRE_WEB = 'audit web requires: python -m pip install -e ".[web]"'


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


class Store:
    """One engine, two tables, a handful of small transactions."""

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
    ) -> None:
        """Insert an audit. ``files`` maps a digest name (``report.html``,
        ``optimization.xml``) to its bytes; its hash comes from ``digests``."""
        with self.engine.begin() as conn:
            conn.execute(
                self.audits.insert().values(
                    id=audit_id,
                    created_at=_iso(created_at),
                    token_hash=token_hash,
                    paid=False,
                    client_ip=client_ip,
                    declared_json=declared_json,
                    result_json=result_json,
                    report_html=report_html,
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

    def get_audit(self, audit_id: str, *, with_blobs: bool = False) -> AuditRecord | None:
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
        with self.engine.begin() as conn:
            result = conn.execute(
                self.audits.update()
                .where(self.audits.c.id == audit_id)
                .where(self.audits.c.paid.is_(False))
                .values(paid=True, paid_at=_iso(at), stripe_session_id=stripe_session_id)
            )
            return bool(result.rowcount)

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

    def waitlist_emails(self) -> list[str]:
        sa = self._sa
        with self.engine.connect() as conn:
            rows = conn.execute(sa.select(self.waitlist.c.email).order_by(self.waitlist.c.id)).all()
        return [row[0] for row in rows]

    # -- retention ---------------------------------------------------------
    def purge_expired(self, now: datetime, *, retention_days: int, dry_run: bool = False) -> int:
        """Drop uploads, reports and declared text of unpaid audits older than
        the retention window. Hashes, class and id stay so the record remains
        verifiable. Returns how many audits were (or would be) purged."""
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
            if dry_run or count == 0:
                return count
            expired = sa.select(self.audits.c.id).where(condition)
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


def make_store(url: str) -> Store:
    return Store(url)


__all__ = ["REQUIRE_WEB", "AuditRecord", "Store", "make_store"]
