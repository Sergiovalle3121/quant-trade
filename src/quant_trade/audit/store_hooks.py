"""Tables and store hooks of the continuous track record (``track_seal``).

The seal keeps its own tables in the ``Store``'s metadata, defined here so
that ``store.py`` carries one line per hook. Every hook is inert while the
tables are empty, and the tables stay empty until the pages behind
``track_seal_pages.TRACK_SEAL_ENABLED`` are switched on: deleting, exporting
and purging then behave exactly as before.

The tables never gain a column later (there is no ALTER path in this
service), so everything the pages will need is here from day one:
``published_since`` (never reset), ``withdrawn_at``, every unpublication
(an event row), the date of the holder's checkbox and the publication hash.
No table holds an account number, not even hashed.

Hooks run inside the store's own transaction and never catch SQL errors:
on PostgreSQL a caught error would leave the transaction aborted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

#: Seal states. A withdrawn seal that was once published keeps a tombstone
#: row whose public page says only when it was withdrawn.
STATUS_OPEN = "open"
STATUS_ENDED = "ended"
STATUS_WITHDRAWN = "withdrawn"

#: Why a seal ended, stored on the seal and on its last event.
ENDED_BY_HOLDER = "holder"
ENDED_REPORT_DELETED = "report_deleted"

#: Event kinds. ``uploaded`` and ``mismatch`` carry the operations counted;
#: ``ended``, ``published``, ``unpublished``, ``hidden`` and ``shown`` are
#: administrative and count nothing.
EVENT_KINDS = (
    "opened",
    "uploaded",
    "mismatch",
    "ended",
    "published",
    "unpublished",
    "hidden",
    "shown",
)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def define_tables(store: Any) -> None:
    """Declare the seal's tables on ``store.metadata`` (before ``create_all``)."""
    sa = store._sa
    store.track_seals = sa.Table(
        "track_seals",
        store.metadata,
        sa.Column("id", sa.String(32), primary_key=True),
        #: The public path segment; independent of the id and of any audit id.
        sa.Column("public_id", sa.String(32), nullable=False, unique=True),
        sa.Column("account_id", sa.String(32), index=True),
        sa.Column("opened_at", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, default=STATUS_OPEN),
        sa.Column("source_format", sa.String(40), nullable=False, default=""),
        sa.Column("currency", sa.String(8), nullable=False, default=""),
        sa.Column("method_version", sa.String(16), nullable=False, default=""),
        sa.Column("recipe_version", sa.String(16), nullable=False, default=""),
        sa.Column("upload_count", sa.Integer, nullable=False, default=0),
        sa.Column("head_hash", sa.String(64), nullable=False, default=""),
        sa.Column("last_upload_at", sa.String(40)),
        sa.Column("last_cutoff", sa.String(40)),
        #: The re-audit of the sealed stretch, as canonical JSON (class,
        #: observations, months to know); never the trades.
        sa.Column("sealed_json", sa.Text),
        sa.Column("ended_at", sa.String(40)),
        sa.Column("ended_reason", sa.String(40)),
        sa.Column("withdrawn_at", sa.String(40)),
        #: First publication; never reset by an unpublication.
        sa.Column("published_since", sa.String(40)),
        sa.Column("published", sa.Boolean, nullable=False, default=False),
        #: SHA-256 of the canonical closed trades at publication: one public
        #: seal per set of operations.
        sa.Column("publish_hash", sa.String(64)),
        sa.Column("holder_confirmed_at", sa.String(40)),
        #: Set by the owner from the panel while a complaint is looked at.
        sa.Column("hidden_at", sa.String(40)),
    )
    store.track_seal_uploads = sa.Table(
        "track_seal_uploads",
        store.metadata,
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("seal_id", sa.String(32), nullable=False, index=True),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("at", sa.String(40), nullable=False),
        #: The report this statement came from; cleared when it is deleted.
        sa.Column("audit_id", sa.String(64), index=True),
        sa.Column("source_format", sa.String(40), nullable=False, default=""),
        sa.Column("cutoff", sa.String(40), nullable=False, default=""),
        sa.Column("closed_count", sa.Integer, nullable=False, default=0),
        sa.Column("flow_count", sa.Integer, nullable=False, default=0),
        sa.Column("currency", sa.String(8), nullable=False, default=""),
        sa.Column("trades_sha256", sa.String(64), nullable=False, default=""),
        sa.Column("previous_hash", sa.String(64), nullable=False, default=""),
        sa.Column("hash", sa.String(64), nullable=False, default=""),
        sa.Column("recipe_version", sa.String(16), nullable=False, default=""),
        #: The public part of the chain entry, as canonical JSON.
        sa.Column("entry_json", sa.Text, nullable=False, default=""),
        #: The closed trades and flows up to the cutoff, canonical JSON, so
        #: the next statement can be compared without the previous file.
        sa.Column("snapshot_json", sa.Text),
    )
    store.track_seal_events = sa.Table(
        "track_seal_events",
        store.metadata,
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("seal_id", sa.String(32), nullable=False, index=True),
        sa.Column("upload_id", sa.String(32)),
        sa.Column("at", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("count", sa.Integer, nullable=False, default=0),
        #: Private detail (which operations differ), canonical JSON.
        sa.Column("detail_json", sa.Text, nullable=False, default=""),
    )
    #: How many seals an account has opened, ever: deleting one never
    #: frees the slot.
    store.track_seal_quota = sa.Table(
        "track_seal_quota",
        store.metadata,
        sa.Column("account_id", sa.String(32), primary_key=True),
        sa.Column("opened", sa.Integer, nullable=False, default=0),
    )


def _seal_ids(store: Any, conn: Any, condition: Any) -> list[str]:
    sa = store._sa
    return [
        str(row[0])
        for row in conn.execute(sa.select(store.track_seals.c.id).where(condition)).all()
    ]


def _drop_seal_rows(store: Any, conn: Any, seal_ids: list[str]) -> None:
    if not seal_ids:
        return
    uploads, events = store.track_seal_uploads, store.track_seal_events
    conn.execute(uploads.delete().where(uploads.c.seal_id.in_(seal_ids)))
    conn.execute(events.delete().where(events.c.seal_id.in_(seal_ids)))


def _event(
    store: Any, conn: Any, seal_id: str, *, kind: str, at: str, count: int = 0, detail: str = ""
) -> None:
    import secrets

    conn.execute(
        store.track_seal_events.insert().values(
            id=secrets.token_urlsafe(16),
            seal_id=seal_id,
            upload_id=None,
            at=at,
            kind=kind,
            count=count,
            detail_json=detail,
        )
    )


def end_seals(
    store: Any, conn: Any, seal_ids: list[str], *, reason: str, now: datetime
) -> list[str]:
    """End the open seals among ``seal_ids`` with an event; returns those ended."""
    seals = store.track_seals
    if not seal_ids:
        return []
    open_ids = _seal_ids(store, conn, seals.c.id.in_(seal_ids) & (seals.c.status == STATUS_OPEN))
    stamp = _iso(now)
    for seal_id in open_ids:
        conn.execute(
            seals.update()
            .where(seals.c.id == seal_id)
            .values(status=STATUS_ENDED, ended_at=stamp, ended_reason=reason)
        )
        _event(store, conn, seal_id, kind="ended", at=stamp, detail=reason)
    return open_ids


def withdraw_seals(store: Any, conn: Any, seal_ids: list[str], *, now: datetime) -> None:
    """Delete seals. One that was ever published leaves a tombstone row whose
    page says only when it was withdrawn; the rest vanish."""
    seals = store.track_seals
    if not seal_ids:
        return
    _drop_seal_rows(store, conn, seal_ids)
    stamp = _iso(now)
    conn.execute(
        seals.update()
        .where(seals.c.id.in_(seal_ids) & seals.c.published_since.is_not(None))
        .values(
            account_id=None,
            status=STATUS_WITHDRAWN,
            withdrawn_at=stamp,
            published=False,
            hidden_at=None,
            sealed_json=None,
            head_hash="",
            last_upload_at=None,
            last_cutoff=None,
            publish_hash=None,
            holder_confirmed_at=None,
            source_format="",
            currency="",
        )
    )
    conn.execute(seals.delete().where(seals.c.id.in_(seal_ids) & seals.c.published_since.is_(None)))


def on_delete_audit(store: Any, conn: Any, audit_id: str) -> None:
    """A deleted report that is a link of a seal ends that seal with an event;
    the chain entry stays, without its report."""
    uploads = store.track_seal_uploads
    sa = store._sa
    seal_ids = [
        str(row[0])
        for row in conn.execute(
            sa.select(uploads.c.seal_id).where(uploads.c.audit_id == audit_id).distinct()
        ).all()
    ]
    if not seal_ids:
        return
    conn.execute(uploads.update().where(uploads.c.audit_id == audit_id).values(audit_id=None))
    end_seals(store, conn, seal_ids, reason=ENDED_REPORT_DELETED, now=datetime.now(UTC))


def on_delete_account(store: Any, conn: Any, account_id: str) -> None:
    """The account's seals go with it (a published one leaves its tombstone)."""
    seals = store.track_seals
    withdraw_seals(
        store,
        conn,
        _seal_ids(store, conn, seals.c.account_id == account_id),
        now=datetime.now(UTC),
    )
    quota = store.track_seal_quota
    conn.execute(quota.delete().where(quota.c.account_id == account_id))


def on_purge(store: Any, conn: Any, *, cutoff: str) -> None:
    """Drop ended seals that were never published once their end is past the
    retention window. A published seal, or its tombstone, is never purged."""
    seals = store.track_seals
    seal_ids = _seal_ids(
        store,
        conn,
        (seals.c.status == STATUS_ENDED)
        & seals.c.published_since.is_(None)
        & (seals.c.ended_at < cutoff),
    )
    if not seal_ids:
        return
    _drop_seal_rows(store, conn, seal_ids)
    conn.execute(seals.delete().where(seals.c.id.in_(seal_ids)))


def export_account(store: Any, account_id: str) -> list[dict[str, Any]]:
    """The account's seals for "Descargar mis datos": dates, counts, hashes
    and events; never a file, an account number or another person's data."""
    sa = store._sa
    seals, uploads, events = store.track_seals, store.track_seal_uploads, store.track_seal_events
    out: list[dict[str, Any]] = []
    with store.engine.connect() as conn:
        rows = (
            conn.execute(
                sa.select(seals).where(seals.c.account_id == account_id).order_by(seals.c.opened_at)
            )
            .mappings()
            .all()
        )
        for row in rows:
            links = (
                conn.execute(
                    sa.select(uploads)
                    .where(uploads.c.seal_id == row["id"])
                    .order_by(uploads.c.position)
                )
                .mappings()
                .all()
            )
            marks = (
                conn.execute(
                    sa.select(events).where(events.c.seal_id == row["id"]).order_by(events.c.at)
                )
                .mappings()
                .all()
            )
            out.append(
                {
                    "id": row["id"],
                    "public_id": row["public_id"],
                    "opened_at": row["opened_at"],
                    "status": row["status"],
                    "source_format": row["source_format"],
                    "currency": row["currency"],
                    "method_version": row["method_version"],
                    "uploads": [
                        {
                            "position": link["position"],
                            "at": link["at"],
                            "report": link["audit_id"],
                            "cutoff": link["cutoff"],
                            "closed_operations": link["closed_count"],
                            "cash_movements": link["flow_count"],
                            "trades_sha256": link["trades_sha256"],
                            "previous_hash": link["previous_hash"],
                            "hash": link["hash"],
                        }
                        for link in links
                    ],
                    "events": [
                        {"at": mark["at"], "kind": mark["kind"], "operations": mark["count"]}
                        for mark in marks
                    ],
                    "ended_at": row["ended_at"],
                    "ended_reason": row["ended_reason"],
                    "published_since": row["published_since"],
                    "published": bool(row["published"]),
                    "holder_confirmed_at": row["holder_confirmed_at"],
                }
            )
    return out


__all__ = [
    "ENDED_BY_HOLDER",
    "ENDED_REPORT_DELETED",
    "EVENT_KINDS",
    "STATUS_ENDED",
    "STATUS_OPEN",
    "STATUS_WITHDRAWN",
    "define_tables",
    "end_seals",
    "export_account",
    "on_delete_account",
    "on_delete_audit",
    "on_purge",
    "withdraw_seals",
]
