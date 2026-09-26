"""Historial continuo: the service layer between the pages and the core.

Pure functions over a ``Store``: each takes the store, ``now`` (Rigor's
clock, UTC; never a date read from a file) and ids, does every database
write of one action in one transaction, and returns a small frozen result
or a ``track_seal.Refusal`` whose code the page words. Nothing here renders
text, reads a request or holds a clock.

What the tables hold is what the pages may show: dates, counts, codes and
hashes, the canonical snapshot (records without account, name, broker or
comment) and the private detail of a mismatch. The account number printed
in a statement is read into a local variable of ``add_upload`` with
``forensics.rows.account_key``, compared there against the previous
statement's, and dropped: it is never stored, hashed, logged or returned.
Ids come from ``secrets.token_urlsafe`` and never derive from an audit id.

Paying never changes a status, a class, an event or an order: the only
thing payment decides is whether a report may be linked at all.
"""

from __future__ import annotations

import hashlib
import json
import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from quant_trade.audit import importers, schema, store_hooks, track_seal
from quant_trade.audit.engine import run_audit
from quant_trade.audit.factsheet import MonthlyGrid, monthly_grid
from quant_trade.audit.forensics import rows
from quant_trade.audit.forensics.review import METHOD_VERSION
from quant_trade.audit.importers import ImportedReport
from quant_trade.audit.schema import (
    MIN_OBSERVATIONS,
    AuditInputs,
    DeclaredMetadata,
    ParseError,
    build_inputs,
)
from quant_trade.audit.store import OWN_VIAS, AuditRecord
from quant_trade.audit.track_seal import Refusal, Snapshot
from quant_trade.evidence.canonical_json import canonical_dumps

__all__ = [
    "DEFAULT_BOOTSTRAP_SAMPLES",
    "EVIDENCE_DECLARED",
    "EVIDENCE_MEASURED",
    "EVIDENCE_NOT_MEASURED",
    "FRESHNESS_CURRENT",
    "FRESHNESS_STALE",
    "FRESH_DAYS",
    "FRESH_DAYS_MONTHLY",
    "MAX_RECORDS_PER_ACCOUNT",
    "NO_POSITIVE_MEAN",
    "REFUSAL_CODES",
    "SERVICE_REFUSAL_CODES",
    "SUPPORTED_FORMATS",
    "TOO_FEW_OBSERVATIONS",
    "Added",
    "EventView",
    "Opened",
    "OperationView",
    "PublicView",
    "Published",
    "RecordView",
    "SealedStretch",
    "UploadView",
    "add_upload",
    "chain_json",
    "delete_record",
    "end_record",
    "freshness",
    "get_record",
    "hide",
    "list_records",
    "open_record",
    "public_record",
    "publish",
    "quota",
    "record_events",
    "record_uploads",
    "unhide",
    "unpublish",
    "verify",
]

#: Records an account may open, ever: deleting one never frees the slot.
MAX_RECORDS_PER_ACCOUNT = 5
#: An upload younger than this keeps the record current (a monthly table
#: is published once a month, so it gets a longer window).
FRESH_DAYS = 45
FRESH_DAYS_MONTHLY = 75
FRESHNESS_CURRENT = "current"
FRESHNESS_STALE = "stale"
#: The bootstrap size ``web.create_app`` uses by default (``AuditSettings``).
DEFAULT_BOOTSTRAP_SAMPLES = 1000

EVIDENCE_MEASURED = "MEASURED"
EVIDENCE_DECLARED = "DECLARED"
EVIDENCE_NOT_MEASURED = "NOT_MEASURED"
#: Why the sealed stretch has no class or no estimate yet.
TOO_FEW_OBSERVATIONS = "too_few_observations"
NO_POSITIVE_MEAN = "no_positive_mean"

#: The export formats a record accepts, never a tester's.
SUPPORTED_FORMATS = frozenset(
    {
        importers.MT4_STATEMENT_HTML,
        importers.MT5_HISTORY_HTML,
        importers.MT5_HISTORY_XLSX,
        importers.MYFXBOOK_CSV,
        importers.MQL5_SIGNAL_CSV,
        importers.FXBLUE_CSV,
    }
)
#: Stored names of the files a record may start from, in order of preference.
_REPORT_STEMS = ("report.", "live.")
_MONTHLY_FILE = "equity.csv"

#: Refusals of this layer; the core's ``track_seal.REFUSAL_CODES`` follow.
SERVICE_REFUSAL_CODES = (
    "not_found",
    "not_own",
    "unpaid",
    "purged",
    "unsupported_file",
    "empty_statement",
    "stored_file_mismatch",
    "quota",
    "record_not_open",
    "record_not_found",
    "already_linked",
    "already_public",
    "holder_not_confirmed",
)
REFUSAL_CODES = SERVICE_REFUSAL_CODES + track_seal.REFUSAL_CODES

_DAYS_PER_MONTH = 30.4375
_FULL_CLASS_SCOPE = "whole_file_including_uncovered_pre_opening_stretch"


# ---------------------------------------------------------------------------
# Results and views: what a page may hold
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Opened:
    seal_id: str
    public_id: str
    upload_id: str
    head_hash: str
    opened_at: str


@dataclass(frozen=True)
class Added:
    seal_id: str
    upload_id: str
    position: int
    event: str
    count: int
    head_hash: str


@dataclass(frozen=True)
class Published:
    seal_id: str
    public_id: str
    published_since: str


@dataclass(frozen=True)
class SealedStretch:
    """The re-audit of the sealed stretch, as ``sealed_json`` stores it.

    Every figure is text with its evidence tag beside it. ``stretch_class``
    is ``""`` with ``pending_reason`` while the stretch holds fewer than
    ``min_observations`` observations (never a D from too little data).
    ``months_to_know`` is an estimate at the current pace of observations
    that changes with every upload, not a forecast; ``""`` with
    ``months_reason`` when there is nothing positive to measure or too few
    observations to see a pace. ``full_class`` is the class of the whole
    latest report, which includes the stretch before the opening that the
    record does not cover.
    """

    computed_at: str
    start: str
    observations: str
    observations_evidence: str
    min_observations: str
    min_observations_evidence: str
    stretch_class: str
    pending_reason: str
    months_to_know: str
    months_to_know_evidence: str
    months_reason: str
    pace_per_month: str
    pace_evidence: str
    first_observation: str
    last_observation: str
    full_class: str
    full_class_evidence: str
    full_class_scope: str

    def as_dict(self) -> dict[str, object]:
        return {
            "computed_at": self.computed_at,
            "start": self.start,
            "observations": {"value": self.observations, "evidence": self.observations_evidence},
            "min_observations": {
                "value": self.min_observations,
                "evidence": self.min_observations_evidence,
            },
            "class": self.stretch_class,
            "pending_reason": self.pending_reason,
            "months_to_know": {
                "value": self.months_to_know,
                "evidence": self.months_to_know_evidence,
                "reason": self.months_reason,
            },
            "pace_per_month": {"value": self.pace_per_month, "evidence": self.pace_evidence},
            "first_observation": self.first_observation,
            "last_observation": self.last_observation,
            "full_class": {
                "value": self.full_class,
                "evidence": self.full_class_evidence,
                "scope": self.full_class_scope,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SealedStretch:
        def figure(name: str) -> dict[str, Any]:
            value = data.get(name)
            return value if isinstance(value, dict) else {}

        return cls(
            computed_at=str(data.get("computed_at", "")),
            start=str(data.get("start", "")),
            observations=str(figure("observations").get("value", "")),
            observations_evidence=str(figure("observations").get("evidence", "")),
            min_observations=str(figure("min_observations").get("value", "")),
            min_observations_evidence=str(figure("min_observations").get("evidence", "")),
            stretch_class=str(data.get("class", "")),
            pending_reason=str(data.get("pending_reason", "")),
            months_to_know=str(figure("months_to_know").get("value", "")),
            months_to_know_evidence=str(figure("months_to_know").get("evidence", "")),
            months_reason=str(figure("months_to_know").get("reason", "")),
            pace_per_month=str(figure("pace_per_month").get("value", "")),
            pace_evidence=str(figure("pace_per_month").get("evidence", "")),
            first_observation=str(data.get("first_observation", "")),
            last_observation=str(data.get("last_observation", "")),
            full_class=str(figure("full_class").get("value", "")),
            full_class_evidence=str(figure("full_class").get("evidence", "")),
            full_class_scope=str(figure("full_class").get("scope", "")),
        )


@dataclass(frozen=True)
class RecordView:
    """One record as its account's page sees it: never an account number,
    a name, a file, a symbol or a trade."""

    id: str
    public_id: str
    opened_at: str
    status: str
    source_format: str
    currency: str
    method_version: str
    recipe_version: str
    upload_count: int
    head_hash: str
    last_upload_at: str
    last_cutoff: str
    sealed: SealedStretch | None
    ended_at: str
    ended_reason: str
    withdrawn_at: str
    published: bool
    published_since: str
    publish_hash: str
    holder_confirmed_at: str
    hidden_at: str


@dataclass(frozen=True)
class OperationView:
    """One operation of a mismatch: kind, record kind, when, which fields.
    The record's reference (a ticket) stays in the table; no page shows it."""

    kind: str
    k: str
    at: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class EventView:
    id: str
    at: str
    kind: str
    count: int
    detail: tuple[OperationView, ...]


@dataclass(frozen=True)
class UploadView:
    """One link of the chain. ``audit_id`` is the account's own report id
    (``""`` once that report is deleted); it never reaches the public page."""

    id: str
    position: int
    at: str
    audit_id: str
    source_format: str
    cutoff: str
    closed_count: int
    flow_count: int
    currency: str
    trades_sha256: str
    previous_hash: str
    hash: str


@dataclass(frozen=True)
class PublicView:
    """What the public page, the badge and ``chain.json`` may show. A
    withdrawn record that was once published gives only ``withdrawn_at``."""

    public_id: str
    status: str
    withdrawn_at: str
    opened_at: str = ""
    source_format: str = ""
    method_version: str = ""
    recipe_version: str = ""
    upload_count: int = 0
    head_hash: str = ""
    last_upload_at: str = ""
    last_cutoff: str = ""
    sealed: SealedStretch | None = None
    ended_at: str = ""
    published_since: str = ""
    chain_ok: bool = True
    #: Records this account has opened (not withdrawn), this one included.
    account_records: int = 0
    #: Date, kind and count only; never the private detail.
    events: tuple[EventView, ...] = ()


# ---------------------------------------------------------------------------
# Time and small helpers
# ---------------------------------------------------------------------------


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text: str) -> datetime | None:
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _new_id() -> str:
    return secrets.token_urlsafe(16)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# The report behind a link
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Source:
    """The supported file of a paid report: lives only inside one call."""

    name: str
    data: bytes
    source_format: str
    imported: ImportedReport | None
    grid: MonthlyGrid | None
    full_class: str

    @property
    def monthly(self) -> bool:
        return self.grid is not None


def _result_inputs(record: AuditRecord) -> dict[str, Any]:
    if not record.result_json:
        return {}
    try:
        loaded = json.loads(record.result_json)
    except ValueError:
        return {}
    inputs = loaded.get("inputs") if isinstance(loaded, dict) else None
    return inputs if isinstance(inputs, dict) else {}


def _full_class(record: AuditRecord) -> str:
    """The class of the whole report, from its stored result."""
    if record.result_json:
        try:
            loaded = json.loads(record.result_json)
        except ValueError:
            loaded = None
        verdict = loaded.get("verdict") if isinstance(loaded, dict) else None
        if isinstance(verdict, dict) and verdict.get("overall"):
            return str(verdict["overall"])
    return record.overall_class or ""


def _grid_of(data: bytes) -> MonthlyGrid | None:
    """The monthly table of an ``equity.csv``, read as the audit read it."""
    try:
        raw = schema._read_csv(data, what="equity")
    except ParseError:
        return None
    if schema._pick(raw, schema.TIMESTAMP_ALIASES) is not None:
        return None
    try:
        return monthly_grid(raw)
    except ParseError:
        return None


def _locate(record: AuditRecord) -> _Source | Refusal:
    """The stored file a record can start from, its digest verified."""
    files = record.files or {}
    inputs = _result_inputs(record)
    full_class = _full_class(record)
    candidates = [name for stem in _REPORT_STEMS for name in sorted(files) if name.startswith(stem)]
    for name in candidates:
        data = files[name]
        stated = inputs.get("live_format" if name.startswith("live.") else "source_format")
        source_format = str(stated) if stated else importers.detect_format(data, name)
        if source_format not in SUPPORTED_FORMATS:
            continue
        if _sha256(data) != record.digests.get(name):
            return Refusal("stored_file_mismatch")
        try:
            imported = importers.import_report(data, name)
        except ParseError:
            continue
        return _Source(name, data, source_format, imported, None, full_class)
    equity = record.equity_csv
    if equity:
        grid = _grid_of(equity)
        if grid is not None:
            if _sha256(equity) != record.digests.get(_MONTHLY_FILE):
                return Refusal("stored_file_mismatch")
            return _Source(_MONTHLY_FILE, equity, track_seal.MONTHLY_FORMAT, None, grid, full_class)
    return Refusal("unsupported_file")


def _account_via(store: Any, account_id: str, audit_id: str) -> str | None:
    sa = store._sa
    link = store.account_audits
    with store.engine.connect() as conn:
        row = conn.execute(
            sa.select(link.c.via).where(
                (link.c.audit_id == audit_id) & (link.c.account_id == account_id)
            )
        ).first()
    return str(row[0]) if row else None


def _own_source(store: Any, account_id: str, audit_id: str) -> _Source | Refusal:
    """The account's own, paid, unpurged report with a supported file."""
    record = store.get_audit(audit_id, with_blobs=True)
    if record is None or store.account_for_audit(audit_id) != account_id:
        return Refusal("not_found")
    if _account_via(store, account_id, audit_id) not in OWN_VIAS:
        return Refusal("not_own")
    if record.purged_at:
        return Refusal("purged")
    if not record.paid:
        return Refusal("unpaid")
    return _locate(record)


def _snapshot_of(source: _Source) -> Snapshot | Refusal:
    try:
        if source.grid is not None:
            snap = track_seal.snapshot_monthly(source.grid)
        else:
            snap = track_seal.snapshot(source.data, source.source_format, source.imported)
    except (ValueError, KeyError, IndexError):
        return Refusal("unsupported_file")
    if not snap.closed and not snap.cash and not snap.months:
        return Refusal("empty_statement")
    return snap


def _content_hash(snap: Snapshot) -> str:
    """One hash per set of operations: the core's ``trades_sha256``, or,
    for a monthly table (which has no trades), the sorted months."""
    if snap.months:
        months = sorted((record.as_dict() for record in snap.months), key=canonical_dumps)
        return hashlib.sha256(canonical_dumps(months).encode("utf-8")).hexdigest()
    return track_seal.trades_sha256(snap)


def _account_key(store: Any, audit_id: str | None) -> str | None:
    """The account number of a linked report, read now from the store into
    the caller's local variable; ``None`` when the report is gone."""
    if not audit_id:
        return None
    record = store.get_audit(audit_id, with_blobs=True)
    if record is None:
        return None
    source = _locate(record)
    if isinstance(source, Refusal) or source.monthly:
        return None
    return rows.account_key(source.data, source.source_format)


# ---------------------------------------------------------------------------
# The sealed stretch (§6.7)
# ---------------------------------------------------------------------------


def _stretch_inputs(source: _Source, opened_at: datetime, now: datetime) -> AuditInputs | None:
    """The latest file cut to what was opened a day or more after the
    record was opened (the months after the opening month for a monthly
    table), parsed the way ``POST /audits`` parses an upload; ``None`` when
    nothing is left to audit."""
    declared = DeclaredMetadata(trials_declared=False)
    if source.grid is not None:
        opening_month = opened_at.astimezone(UTC).strftime("%Y-%m")
        frame = source.grid.frame
        kept = frame[frame["timestamp"].dt.strftime("%Y-%m") > opening_month]
        if kept.empty:
            return None
        lines = ["timestamp,return"]
        for stamp, ret in zip(kept["timestamp"], kept["ret"], strict=True):
            lines.append(f"{stamp.strftime('%Y-%m-%d')},{float(ret)!r}")
        try:
            return build_inputs("\n".join(lines).encode("utf-8"), declared, now=now)
        except ParseError:
            return None
    try:
        cut, balance = track_seal.sealed_stretch_bytes(
            source.data, source.source_format, opened_at, imported=source.imported
        )
        if balance is not None and balance > 0:
            declared = DeclaredMetadata(trials_declared=False, initial_balance=float(balance))
        return build_inputs(None, declared, report_bytes=cut, report_filename=source.name, now=now)
    except ParseError:
        # The cut left no trade the importer can read: nothing sealed yet.
        return None


def _months_to_know(
    significance: dict[str, Any], observations: int, first: datetime | None, last: datetime | None
) -> tuple[str, str, str, str]:
    """``(months, evidence, reason, pace)``: months left, at the current
    pace, to reach the observations the significance section asks for
    (never fewer than ``MIN_OBSERVATIONS``); an estimate, not a forecast."""
    sharpe = significance.get("sharpe_per_period") or {}
    needed_figure = significance.get("min_track_record_length") or {}
    if sharpe.get("evidence") != EVIDENCE_MEASURED:
        return "", EVIDENCE_NOT_MEASURED, TOO_FEW_OBSERVATIONS, ""
    if float(sharpe.get("value") or 0.0) <= 0 or needed_figure.get("evidence") != EVIDENCE_MEASURED:
        return "", EVIDENCE_NOT_MEASURED, NO_POSITIVE_MEAN, ""
    needed = max(float(needed_figure["value"]), float(MIN_OBSERVATIONS))
    if observations >= needed:
        return "0", EVIDENCE_MEASURED, "", ""
    if first is None or last is None or last <= first or observations < 2:
        return "", EVIDENCE_NOT_MEASURED, TOO_FEW_OBSERVATIONS, ""
    months_elapsed = (last - first).total_seconds() / 86400.0 / _DAYS_PER_MONTH
    pace = observations / months_elapsed
    months = math.ceil((needed - observations) / pace)
    return str(int(months)), EVIDENCE_MEASURED, "", f"{pace:.1f}"


def _pending(source: _Source, start: str, now: datetime) -> SealedStretch:
    return SealedStretch(
        computed_at=_iso(now),
        start=start,
        observations="0",
        observations_evidence=EVIDENCE_MEASURED,
        min_observations=str(MIN_OBSERVATIONS),
        min_observations_evidence=EVIDENCE_DECLARED,
        stretch_class="",
        pending_reason=TOO_FEW_OBSERVATIONS,
        months_to_know="",
        months_to_know_evidence=EVIDENCE_NOT_MEASURED,
        months_reason=TOO_FEW_OBSERVATIONS,
        pace_per_month="",
        pace_evidence=EVIDENCE_NOT_MEASURED,
        first_observation="",
        last_observation="",
        full_class=source.full_class,
        full_class_evidence=EVIDENCE_MEASURED,
        full_class_scope=_FULL_CLASS_SCOPE,
    )


def _sealed_stretch(
    source: _Source, opened_at: datetime, now: datetime, bootstrap_samples: int
) -> SealedStretch:
    """Re-audit the sealed stretch with ``schema.build_inputs`` and
    ``engine.run_audit``, the engine path every upload takes."""
    if source.grid is not None:
        opened = opened_at.astimezone(UTC)
        start = f"{opened.year + opened.month // 12:04d}-{opened.month % 12 + 1:02d}"
    else:
        start = _iso(opened_at + track_seal.SEALED_MARGIN)
    inputs = _stretch_inputs(source, opened_at, now)
    if inputs is None:
        return _pending(source, start, now)
    result = run_audit(inputs, bootstrap_samples=bootstrap_samples, now=now)
    significance = result.significance
    observations = int((significance.get("observations") or {}).get("value") or 0)
    stamps = inputs.equity.frame["timestamp"]
    first = stamps.iloc[0].to_pydatetime() if len(stamps) else None
    last = stamps.iloc[-1].to_pydatetime() if len(stamps) else None
    months, months_evidence, reason, pace = _months_to_know(significance, observations, first, last)
    enough = observations >= MIN_OBSERVATIONS
    return SealedStretch(
        computed_at=_iso(now),
        start=start,
        observations=str(observations),
        observations_evidence=EVIDENCE_MEASURED,
        min_observations=str(MIN_OBSERVATIONS),
        min_observations_evidence=EVIDENCE_DECLARED,
        stretch_class=result.verdict.overall if enough else "",
        pending_reason="" if enough else TOO_FEW_OBSERVATIONS,
        months_to_know=months,
        months_to_know_evidence=months_evidence,
        months_reason=reason,
        pace_per_month=pace,
        pace_evidence=EVIDENCE_MEASURED if pace else EVIDENCE_NOT_MEASURED,
        first_observation=_iso(first) if first is not None else "",
        last_observation=_iso(last) if last is not None else "",
        full_class=source.full_class,
        full_class_evidence=EVIDENCE_MEASURED,
        full_class_scope=_FULL_CLASS_SCOPE,
    )


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _seal_row(store: Any, conn: Any, seal_id: str) -> Any:
    seals = store.track_seals
    return conn.execute(store._sa.select(seals).where(seals.c.id == seal_id)).mappings().first()


def _upload_rows(store: Any, conn: Any, seal_id: str) -> list[Any]:
    uploads = store.track_seal_uploads
    return list(
        conn.execute(
            store._sa.select(uploads)
            .where(uploads.c.seal_id == seal_id)
            .order_by(uploads.c.position)
        )
        .mappings()
        .all()
    )


def _event_rows(store: Any, conn: Any, seal_id: str) -> list[Any]:
    events = store.track_seal_events
    return list(
        conn.execute(
            store._sa.select(events)
            .where(events.c.seal_id == seal_id)
            .order_by(events.c.at, events.c.id)
        )
        .mappings()
        .all()
    )


def _insert_event(
    store: Any,
    conn: Any,
    seal_id: str,
    *,
    upload_id: str | None,
    at: str,
    kind: str,
    count: int = 0,
    detail: str = "",
) -> str:
    event_id = _new_id()
    conn.execute(
        store.track_seal_events.insert().values(
            id=event_id,
            seal_id=seal_id,
            upload_id=upload_id,
            at=at,
            kind=kind,
            count=count,
            detail_json=detail,
        )
    )
    return event_id


def _insert_upload(
    store: Any,
    conn: Any,
    *,
    seal_id: str,
    position: int,
    at: str,
    audit_id: str,
    snap: Snapshot,
    entry: dict[str, str | int],
    digest: str,
) -> str:
    upload_id = _new_id()
    conn.execute(
        store.track_seal_uploads.insert().values(
            id=upload_id,
            seal_id=seal_id,
            position=position,
            at=at,
            audit_id=audit_id,
            source_format=snap.source_format,
            cutoff=snap.cutoff,
            closed_count=len(snap.closed),
            flow_count=len(snap.cash),
            currency=snap.currency,
            trades_sha256=str(entry["trades_sha256"]),
            previous_hash=str(entry["previous_hash"]),
            hash=digest,
            recipe_version=track_seal.RECIPE_VERSION,
            entry_json=canonical_dumps(entry),
            snapshot_json=track_seal.snapshot_json(snap),
        )
    )
    return upload_id


def _entry(
    *,
    position: int,
    now: datetime,
    snap: Snapshot,
    event_kind: str,
    event_count: int,
    previous_hash: str,
) -> tuple[dict[str, str | int], str]:
    entry = track_seal.chain_entry(
        position=position,
        at=now,
        cutoff=snap.cutoff,
        closed_count=len(snap.closed),
        flow_count=len(snap.cash),
        currency=snap.currency,
        source_format=snap.source_format,
        trades_sha256=_content_hash(snap),
        event_kind=event_kind,
        event_count=event_count,
        previous_hash=previous_hash,
    )
    return entry, track_seal.entry_hash(entry)


def _take_quota(store: Any, conn: Any, account_id: str) -> bool:
    """Count one more opened record; ``False`` when the account has used
    its slots. One conditional UPDATE, so two openings at once cannot both
    pass on PostgreSQL."""
    quota_table = store.track_seal_quota
    sa = store._sa
    updated = conn.execute(
        quota_table.update()
        .where(
            (quota_table.c.account_id == account_id)
            & (quota_table.c.opened < MAX_RECORDS_PER_ACCOUNT)
        )
        .values(opened=quota_table.c.opened + 1)
    )
    if updated.rowcount:
        return True
    existing = conn.execute(
        sa.select(quota_table.c.opened).where(quota_table.c.account_id == account_id)
    ).first()
    if existing is not None:
        return False
    conn.execute(quota_table.insert().values(account_id=account_id, opened=1))
    return True


def _sealed_of(row: Any) -> SealedStretch | None:
    text = row["sealed_json"]
    if not text:
        return None
    try:
        loaded = json.loads(text)
    except ValueError:
        return None
    return SealedStretch.from_dict(loaded) if isinstance(loaded, dict) else None


def _record_view(row: Any) -> RecordView:
    return RecordView(
        id=str(row["id"]),
        public_id=str(row["public_id"]),
        opened_at=_text(row["opened_at"]),
        status=_text(row["status"]),
        source_format=_text(row["source_format"]),
        currency=_text(row["currency"]),
        method_version=_text(row["method_version"]),
        recipe_version=_text(row["recipe_version"]),
        upload_count=int(row["upload_count"] or 0),
        head_hash=_text(row["head_hash"]),
        last_upload_at=_text(row["last_upload_at"]),
        last_cutoff=_text(row["last_cutoff"]),
        sealed=_sealed_of(row),
        ended_at=_text(row["ended_at"]),
        ended_reason=_text(row["ended_reason"]),
        withdrawn_at=_text(row["withdrawn_at"]),
        published=bool(row["published"]),
        published_since=_text(row["published_since"]),
        publish_hash=_text(row["publish_hash"]),
        holder_confirmed_at=_text(row["holder_confirmed_at"]),
        hidden_at=_text(row["hidden_at"]),
    )


def _operations(detail_json: str) -> tuple[OperationView, ...]:
    if not detail_json:
        return ()
    try:
        loaded = json.loads(detail_json)
    except ValueError:
        return ()
    if not isinstance(loaded, list):
        return ()
    found: list[OperationView] = []
    for item in loaded:
        if not isinstance(item, dict):
            continue
        fields = item.get("fields") or []
        found.append(
            OperationView(
                kind=str(item.get("kind", "")),
                k=str(item.get("k", "")),
                at=str(item.get("at", "")),
                fields=tuple(str(name) for name in fields) if isinstance(fields, list) else (),
            )
        )
    return tuple(found)


def _event_view(row: Any, *, with_detail: bool) -> EventView:
    return EventView(
        id=str(row["id"]),
        at=_text(row["at"]),
        kind=_text(row["kind"]),
        count=int(row["count"] or 0),
        detail=_operations(_text(row["detail_json"])) if with_detail else (),
    )


def _upload_view(row: Any) -> UploadView:
    return UploadView(
        id=str(row["id"]),
        position=int(row["position"]),
        at=_text(row["at"]),
        audit_id=_text(row["audit_id"]),
        source_format=_text(row["source_format"]),
        cutoff=_text(row["cutoff"]),
        closed_count=int(row["closed_count"] or 0),
        flow_count=int(row["flow_count"] or 0),
        currency=_text(row["currency"]),
        trades_sha256=_text(row["trades_sha256"]),
        previous_hash=_text(row["previous_hash"]),
        hash=_text(row["hash"]),
    )


def _entries_of(upload_rows: list[Any]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for row in upload_rows:
        try:
            loaded = json.loads(row["entry_json"] or "{}")
        except ValueError:
            loaded = {}
        entry = dict(loaded) if isinstance(loaded, dict) else {}
        entry["hash"] = _text(row["hash"])
        entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def open_record(
    store: Any,
    *,
    account_id: str,
    audit_id: str,
    now: datetime,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
) -> Opened | Refusal:
    """Open a record on one of the account's own paid reports.

    The report must be the account's own (``via`` in ``OWN_VIAS``), paid
    through the normal flow, not purged, and hold a supported statement or
    a monthly table whose stored digest still matches. The opening date is
    ``now``, Rigor's clock. The account keeps at most
    ``MAX_RECORDS_PER_ACCOUNT`` openings, ever.
    """
    opened, _ = quota(store, account_id)
    if opened >= MAX_RECORDS_PER_ACCOUNT:
        return Refusal("quota")
    source = _own_source(store, account_id, audit_id)
    if isinstance(source, Refusal):
        return source
    snap = _snapshot_of(source)
    if isinstance(snap, Refusal):
        return snap
    entry, digest = _entry(
        position=1,
        now=now,
        snap=snap,
        event_kind=track_seal.EVENT_UPLOADED,
        event_count=0,
        previous_hash="",
    )
    sealed = _sealed_stretch(source, now, now, bootstrap_samples)
    stamp = _iso(now)
    seal_id, public_id = _new_id(), _new_id()
    with store.engine.begin() as conn:
        if not _take_quota(store, conn, account_id):
            return Refusal("quota")
        conn.execute(
            store.track_seals.insert().values(
                id=seal_id,
                public_id=public_id,
                account_id=account_id,
                opened_at=stamp,
                status=store_hooks.STATUS_OPEN,
                source_format=snap.source_format,
                currency=snap.currency,
                method_version=METHOD_VERSION,
                recipe_version=track_seal.RECIPE_VERSION,
                upload_count=1,
                head_hash=digest,
                last_upload_at=stamp,
                last_cutoff=snap.cutoff,
                sealed_json=canonical_dumps(sealed.as_dict()),
                published=False,
            )
        )
        upload_id = _insert_upload(
            store,
            conn,
            seal_id=seal_id,
            position=1,
            at=stamp,
            audit_id=audit_id,
            snap=snap,
            entry=entry,
            digest=digest,
        )
        _insert_event(store, conn, seal_id, upload_id=upload_id, at=stamp, kind="opened")
    return Opened(
        seal_id=seal_id, public_id=public_id, upload_id=upload_id, head_hash=digest, opened_at=stamp
    )


def add_upload(
    store: Any,
    *,
    seal_id: str,
    account_id: str,
    audit_id: str,
    now: datetime,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
) -> Added | Refusal:
    """Continue an open record with another of the account's paid reports.

    The new statement is compared with the previous snapshot
    (``track_seal.compare_uploads``); a refusal writes nothing. An accepted
    upload adds one chain entry, one event (``uploaded`` or ``mismatch``
    with its count and private detail) and recomputes the sealed stretch.
    The two account numbers are read here into local variables, compared
    inside the core and dropped.
    """
    with store.engine.connect() as conn:
        seal = _seal_row(store, conn, seal_id)
        uploads = _upload_rows(store, conn, seal_id) if seal is not None else []
    if (
        seal is None
        or seal["account_id"] != account_id
        or seal["status"] != store_hooks.STATUS_OPEN
        or not uploads
    ):
        return Refusal("record_not_open")
    if any(row["audit_id"] == audit_id for row in uploads):
        return Refusal("already_linked")
    source = _own_source(store, account_id, audit_id)
    if isinstance(source, Refusal):
        return source
    snap = _snapshot_of(source)
    if isinstance(snap, Refusal):
        return snap
    previous = uploads[-1]
    try:
        prev_snap = track_seal.load_snapshot(previous["snapshot_json"] or "")
    except ValueError:
        return Refusal("record_not_open")
    # Both keys live in these two locals until the comparison returns.
    prev_key = _account_key(store, previous["audit_id"])
    new_key = None if source.monthly else rows.account_key(source.data, source.source_format)
    outcome = track_seal.compare_uploads(
        prev_snap,
        snap,
        now=now,
        prev_key=prev_key,
        new_key=new_key,
        prev_at=_parse(_text(previous["at"])),
    )
    del prev_key, new_key
    if isinstance(outcome, Refusal):
        return outcome
    position = int(previous["position"]) + 1
    entry, digest = _entry(
        position=position,
        now=now,
        snap=snap,
        event_kind=outcome.event,
        event_count=outcome.count,
        previous_hash=_text(seal["head_hash"]),
    )
    opened_at = _parse(_text(seal["opened_at"])) or now
    sealed = _sealed_stretch(source, opened_at, now, bootstrap_samples)
    stamp = _iso(now)
    with store.engine.begin() as conn:
        current = _seal_row(store, conn, seal_id)
        if (
            current is None
            or current["status"] != store_hooks.STATUS_OPEN
            or int(current["upload_count"]) != len(uploads)
        ):
            return Refusal("record_not_open")
        upload_id = _insert_upload(
            store,
            conn,
            seal_id=seal_id,
            position=position,
            at=stamp,
            audit_id=audit_id,
            snap=snap,
            entry=entry,
            digest=digest,
        )
        _insert_event(
            store,
            conn,
            seal_id,
            upload_id=upload_id,
            at=stamp,
            kind=outcome.event,
            count=outcome.count,
            detail=outcome.detail_json() if outcome.count else "",
        )
        seals = store.track_seals
        conn.execute(
            seals.update()
            .where(seals.c.id == seal_id)
            .values(
                head_hash=digest,
                upload_count=position,
                last_upload_at=stamp,
                last_cutoff=snap.cutoff,
                sealed_json=canonical_dumps(sealed.as_dict()),
            )
        )
    return Added(
        seal_id=seal_id,
        upload_id=upload_id,
        position=position,
        event=outcome.event,
        count=outcome.count,
        head_hash=digest,
    )


def freshness(record: RecordView | PublicView, now: datetime) -> tuple[str, str]:
    """``("current" | "stale", last_upload_at)``: current while the last
    upload is younger than ``FRESH_DAYS`` (``FRESH_DAYS_MONTHLY`` for a
    monthly table)."""
    last = _parse(record.last_upload_at)
    if last is None:
        return FRESHNESS_STALE, record.last_upload_at
    days = FRESH_DAYS_MONTHLY if record.source_format == track_seal.MONTHLY_FORMAT else FRESH_DAYS
    age = now.astimezone(UTC) - last
    state = FRESHNESS_CURRENT if age < timedelta(days=days) else FRESHNESS_STALE
    return state, record.last_upload_at


def verify(store: Any, seal_id: str) -> tuple[bool, int | None]:
    """Recompute every hash and link of the record's chain."""
    with store.engine.connect() as conn:
        uploads = _upload_rows(store, conn, seal_id)
    return track_seal.verify_chain(_entries_of(uploads))


#: How every hash of a chain is computed, in words, for ``chain.json``.
CHAIN_RECIPE = {
    "entry_hash": (
        "SHA-256, as lower-case hex, of the UTF-8 bytes of the canonical JSON of the entry "
        "without its 'hash' key"
    ),
    "canonical_json": (
        "json.dumps(entry, sort_keys=True, separators=(',', ':'), ensure_ascii=False): keys "
        "sorted, no spaces, non-ASCII kept, every figure a string or an integer"
    ),
    "previous_hash": (
        "the 'hash' of the entry before; the first entry's previous_hash is the empty string"
    ),
    "head_hash": "the 'hash' of the last entry",
    "at": "the date of the upload by the service's own clock, UTC, never a date read from a file",
}


def chain_json(store: Any, seal_id: str) -> dict[str, Any]:
    """The chain of one record with the recipe of each hash, for
    ``chain.json`` and for a copy the reader keeps."""
    with store.engine.connect() as conn:
        seal = _seal_row(store, conn, seal_id)
        uploads = _upload_rows(store, conn, seal_id)
    entries = _entries_of(uploads)
    ok, broken = track_seal.verify_chain(entries)
    return {
        "recipe_version": track_seal.RECIPE_VERSION,
        "method_version": _text(seal["method_version"]) if seal is not None else "",
        "recipe": dict(CHAIN_RECIPE),
        "entries": entries,
        "head_hash": entries[-1]["hash"] if entries else "",
        "chain_ok": ok,
        "broken_position": broken,
    }


def end_record(store: Any, *, seal_id: str, account_id: str, now: datetime) -> Refusal | None:
    """The holder ends an open record: frozen with its date, with an event."""
    with store.engine.begin() as conn:
        seal = _seal_row(store, conn, seal_id)
        if seal is None or seal["account_id"] != account_id:
            return Refusal("record_not_found")
        ended = store_hooks.end_seals(
            store, conn, [seal_id], reason=store_hooks.ENDED_BY_HOLDER, now=now
        )
        if not ended:
            return Refusal("record_not_open")
    return None


def delete_record(store: Any, *, seal_id: str, account_id: str, now: datetime) -> Refusal | None:
    """The holder deletes a record; one that was ever published leaves a
    tombstone whose page says only when it was withdrawn."""
    with store.engine.begin() as conn:
        seal = _seal_row(store, conn, seal_id)
        if seal is None or seal["account_id"] != account_id:
            return Refusal("record_not_found")
        store_hooks.withdraw_seals(store, conn, [seal_id], now=now)
    return None


def publish(
    store: Any, *, seal_id: str, account_id: str, now: datetime, holder_confirmed: bool
) -> Published | Refusal:
    """Make the record public. The holder's checkbox is required and dated;
    one set of operations (the content hash of the latest upload) admits one
    public record. ``published_since`` is set once and never reset."""
    if not holder_confirmed:
        return Refusal("holder_not_confirmed")
    sa = store._sa
    seals = store.track_seals
    stamp = _iso(now)
    with store.engine.begin() as conn:
        seal = _seal_row(store, conn, seal_id)
        if (
            seal is None
            or seal["account_id"] != account_id
            or seal["status"] == store_hooks.STATUS_WITHDRAWN
        ):
            return Refusal("record_not_found")
        uploads = _upload_rows(store, conn, seal_id)
        if not uploads:
            return Refusal("record_not_found")
        publish_hash = _text(uploads[-1]["trades_sha256"])
        clash = conn.execute(
            sa.select(seals.c.id).where(
                (seals.c.publish_hash == publish_hash)
                & seals.c.published.is_(True)
                & (seals.c.id != seal_id)
            )
        ).first()
        if clash is not None:
            return Refusal("already_public")
        since = _text(seal["published_since"]) or stamp
        conn.execute(
            seals.update()
            .where(seals.c.id == seal_id)
            .values(
                published=True,
                published_since=since,
                publish_hash=publish_hash,
                holder_confirmed_at=stamp,
            )
        )
        _insert_event(store, conn, seal_id, upload_id=None, at=stamp, kind="published")
    return Published(seal_id=seal_id, public_id=str(seal["public_id"]), published_since=since)


def unpublish(store: Any, *, seal_id: str, account_id: str, now: datetime) -> Refusal | None:
    """Take the record off its public page; ``published_since`` stays and
    the unpublication is an event."""
    seals = store.track_seals
    with store.engine.begin() as conn:
        seal = _seal_row(store, conn, seal_id)
        if seal is None or seal["account_id"] != account_id:
            return Refusal("record_not_found")
        if not seal["published"]:
            return None
        conn.execute(seals.update().where(seals.c.id == seal_id).values(published=False))
        _insert_event(store, conn, seal_id, upload_id=None, at=_iso(now), kind="unpublished")
    return None


def _set_hidden(store: Any, seal_id: str, now: datetime, *, hidden: bool) -> Refusal | None:
    seals = store.track_seals
    with store.engine.begin() as conn:
        seal = _seal_row(store, conn, seal_id)
        if seal is None or seal["status"] == store_hooks.STATUS_WITHDRAWN:
            return Refusal("record_not_found")
        if bool(seal["hidden_at"]) == hidden:
            return None
        stamp = _iso(now)
        conn.execute(
            seals.update().where(seals.c.id == seal_id).values(hidden_at=stamp if hidden else None)
        )
        _insert_event(
            store, conn, seal_id, upload_id=None, at=stamp, kind="hidden" if hidden else "shown"
        )
    return None


def hide(store: Any, *, seal_id: str, now: datetime) -> Refusal | None:
    """The owner hides the public page, reversibly, while a complaint is
    looked at (the panel; no account check)."""
    return _set_hidden(store, seal_id, now, hidden=True)


def unhide(store: Any, *, seal_id: str, now: datetime) -> Refusal | None:
    return _set_hidden(store, seal_id, now, hidden=False)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def quota(store: Any, account_id: str) -> tuple[int, int]:
    """``(opened ever, allowed)`` for the account."""
    quota_table = store.track_seal_quota
    with store.engine.connect() as conn:
        row = conn.execute(
            store._sa.select(quota_table.c.opened).where(quota_table.c.account_id == account_id)
        ).first()
    return (int(row[0]) if row else 0), MAX_RECORDS_PER_ACCOUNT


def list_records(store: Any, account_id: str) -> list[RecordView]:
    """The account's records, oldest first (a withdrawn one is gone)."""
    seals = store.track_seals
    with store.engine.connect() as conn:
        found = (
            conn.execute(
                store._sa.select(seals)
                .where(seals.c.account_id == account_id)
                .order_by(seals.c.opened_at, seals.c.id)
            )
            .mappings()
            .all()
        )
    return [_record_view(row) for row in found]


def get_record(store: Any, seal_id: str, *, account_id: str | None = None) -> RecordView | None:
    """One record by id; with ``account_id`` only when that account owns it."""
    with store.engine.connect() as conn:
        row = _seal_row(store, conn, seal_id)
    if row is None or (account_id is not None and row["account_id"] != account_id):
        return None
    return _record_view(row)


def record_events(store: Any, seal_id: str) -> tuple[EventView, ...]:
    """Every event with its private detail, for the account's page."""
    with store.engine.connect() as conn:
        found = _event_rows(store, conn, seal_id)
    return tuple(_event_view(row, with_detail=True) for row in found)


def record_uploads(store: Any, seal_id: str) -> tuple[UploadView, ...]:
    with store.engine.connect() as conn:
        found = _upload_rows(store, conn, seal_id)
    return tuple(_upload_view(row) for row in found)


def public_record(store: Any, public_id: str) -> PublicView | None:
    """The public view by its public id: ``None`` when missing, hidden or
    not published now (the page answers the same 404); a withdrawn record
    that was once published gives only its ``withdrawn_at``."""
    sa = store._sa
    seals = store.track_seals
    with store.engine.connect() as conn:
        row = (
            conn.execute(sa.select(seals).where(seals.c.public_id == public_id)).mappings().first()
        )
        if row is None:
            return None
        if row["status"] == store_hooks.STATUS_WITHDRAWN:
            if not row["published_since"]:
                return None
            return PublicView(
                public_id=str(row["public_id"]),
                status=store_hooks.STATUS_WITHDRAWN,
                withdrawn_at=_text(row["withdrawn_at"]),
            )
        if row["hidden_at"] or not row["published"]:
            return None
        uploads = _upload_rows(store, conn, str(row["id"]))
        events = _event_rows(store, conn, str(row["id"]))
        siblings = conn.execute(
            sa.select(sa.func.count())
            .select_from(seals)
            .where(
                (seals.c.account_id == row["account_id"])
                & (seals.c.status != store_hooks.STATUS_WITHDRAWN)
            )
        ).scalar()
    ok, _ = track_seal.verify_chain(_entries_of(uploads))
    return PublicView(
        public_id=str(row["public_id"]),
        status=_text(row["status"]),
        withdrawn_at="",
        opened_at=_text(row["opened_at"]),
        source_format=_text(row["source_format"]),
        method_version=_text(row["method_version"]),
        recipe_version=_text(row["recipe_version"]),
        upload_count=int(row["upload_count"] or 0),
        head_hash=_text(row["head_hash"]),
        last_upload_at=_text(row["last_upload_at"]),
        last_cutoff=_text(row["last_cutoff"]),
        sealed=_sealed_of(row),
        ended_at=_text(row["ended_at"]),
        published_since=_text(row["published_since"]),
        chain_ok=ok,
        account_records=int(siblings or 0),
        events=tuple(_event_view(event, with_detail=False) for event in events),
    )
