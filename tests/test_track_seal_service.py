"""The continuous track record's service layer, on SQLite and offline.

Reports are created through the store's own API (``create_audit``,
``mark_paid``, ``link_audit``), statements come from the fixtures cut with
``forensics.edit.cut_statement``, and nothing here reaches the network.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from quant_trade.audit import importers, store_hooks, track_seal
from quant_trade.audit import track_seal_service as service
from quant_trade.audit.forensics import edit, rows
from quant_trade.audit.forensics.review import METHOD_VERSION
from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.schema import MIN_OBSERVATIONS
from quant_trade.audit.store import VIA_SAVED, VIA_UPLOAD, Store, make_store

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
MT4 = "mt4_statement.htm"
MT5 = "mt5_history.html"
MT4_FORMAT = importers.MT4_STATEMENT_HTML

D1 = datetime(2024, 3, 4, 23, 59, 59)
D2 = datetime(2024, 3, 5, 23, 59, 59)
T1 = datetime(2024, 3, 5, 12, 0, tzinfo=UTC)
T2 = datetime(2024, 3, 6, 12, 0, tzinfo=UTC)
T3 = datetime(2024, 3, 9, 12, 0, tzinfo=UTC)
BOOTSTRAP = 60

#: Text of the fixtures that must never reach a seal row or a view.
PRIVATE_TEXT = ("12345678", "Demo Trader", "FixtureEA", "SyntheticBroker", "to #", ".htm")
FIXTURE_SYMBOLS = ("eurusd", "xauusd")
FIXTURE_TICKETS = ("1000001", "1000002", "1000003", "1000005", "1000006", "1000007")


def _bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _store(tmp_path: Path) -> Store:
    return make_store(f"sqlite:///{tmp_path}/audit.db")


def _account(store: Store, email: str = "holder@example.com") -> str:
    account = store.create_account(email=email, password_hash="x", locale="es", at=T1)
    assert account is not None
    return account.id


def _audit(
    store: Store,
    account_id: str | None,
    audit_id: str,
    data: bytes,
    *,
    name: str = "report.htm",
    paid: bool = True,
    via: str = VIA_UPLOAD,
    overall: str = "B",
    digest: str | None = None,
    source_format: str | None = None,
) -> str:
    """A report with one stored platform file, paid and on the account."""
    fmt = source_format or importers.detect_format(data, name)
    result = {
        "audit_id": audit_id,
        "inputs": {"source_format": fmt},
        "verdict": {"overall": overall},
    }
    store.create_audit(
        audit_id=audit_id,
        created_at=T1,
        token_hash="h" * 64,
        client_ip="1.2.3.4",
        declared_json="{}",
        result_json=json.dumps(result),
        report_html="<html></html>",
        overall_class=overall,
        digests={name: digest or hashlib.sha256(data).hexdigest()},
        equity_csv=None,
        files={name: data},
    )
    if paid:
        store.mark_paid(audit_id, stripe_session_id="cs_test_x", at=T1)
    if account_id is not None:
        store.link_audit(account_id, audit_id, at=T1, via=via)
    return audit_id


def _monthly_audit(store: Store, account_id: str, audit_id: str, csv: bytes) -> str:
    result = {"audit_id": audit_id, "inputs": {"source": "equity"}, "verdict": {"overall": "C"}}
    store.create_audit(
        audit_id=audit_id,
        created_at=T1,
        token_hash="h" * 64,
        client_ip="1.2.3.4",
        declared_json="{}",
        result_json=json.dumps(result),
        report_html="<html></html>",
        overall_class="C",
        digests={"equity.csv": hashlib.sha256(csv).hexdigest()},
        equity_csv=csv,
    )
    store.mark_paid(audit_id, stripe_session_id="cs_test_m", at=T1)
    store.link_audit(account_id, audit_id, at=T1, via=VIA_UPLOAD)
    return audit_id


def _rows(store: Store, table: Any, **where: object) -> list[dict[str, Any]]:
    sa = store._sa
    query = sa.select(table)
    for key, value in where.items():
        query = query.where(getattr(table.c, key) == value)
    with store.engine.connect() as conn:
        return [dict(row) for row in conn.execute(query).mappings().all()]


def _seal(store: Store, seal_id: str) -> dict[str, Any]:
    (row,) = _rows(store, store.track_seals, id=seal_id)
    return row


def _opened(result: object) -> service.Opened:
    assert isinstance(result, service.Opened), result
    return result


def _added(result: object) -> service.Added:
    assert isinstance(result, service.Added), result
    return result


def _grid_csv(months: dict[str, float]) -> bytes:
    """A factsheet grid (``Year,Jan..Dec``) with the months given as percentages."""
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    years = sorted({ym[:4] for ym in months})
    lines = ["Year," + ",".join(names)]
    for year in years:
        cells = [months.get(f"{year}-{m:02d}") for m in range(1, 13)]
        lines.append(year + "," + ",".join("" if c is None else f"{c:.2f}" for c in cells))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _long_mt4() -> bytes:
    """The MT4 fixture with forty copies of its first trade, one per day
    after it, each with a fresh ticket: enough closed trades for a class."""
    data = _bytes(MT4)
    for i in range(1, 41):
        table = rows.load(data, MT4_FORMAT)
        trade = next(
            r for r in table.rows if r.kind == rows.KIND_MT4_TRADE and r.text(0) == "1000002"
        )
        data = edit.duplicate_row(
            data, trade.index, {0: str(2000000 + i)}, shift=timedelta(days=i, minutes=i)
        )
    return data


def _open_cut1(store: Store, account_id: str) -> tuple[str, service.Opened]:
    audit_id = _audit(
        store, account_id, "opening-report", edit.cut_statement(_bytes(MT4), keep_to=D1)
    )
    opened = _opened(
        service.open_record(
            store, account_id=account_id, audit_id=audit_id, now=T1, bootstrap_samples=BOOTSTRAP
        )
    )
    return audit_id, opened


# ---------------------------------------------------------------------------
# Opening
# ---------------------------------------------------------------------------


def test_open_writes_the_seal_upload_event_and_quota_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    audit_id, opened = _open_cut1(store, account_id)
    assert len(opened.seal_id) == 22 and len(opened.public_id) == 22
    assert opened.seal_id != opened.public_id and audit_id not in opened.seal_id
    assert opened.opened_at == "2024-03-05T12:00:00Z"

    seal = _seal(store, opened.seal_id)
    assert seal["status"] == store_hooks.STATUS_OPEN and seal["account_id"] == account_id
    assert seal["opened_at"] == opened.opened_at and seal["last_upload_at"] == opened.opened_at
    assert seal["source_format"] == MT4_FORMAT and seal["currency"] == "USD"
    assert seal["method_version"] == METHOD_VERSION
    assert seal["recipe_version"] == track_seal.RECIPE_VERSION
    assert seal["upload_count"] == 1 and seal["head_hash"] == opened.head_hash
    assert seal["published"] is False and seal["published_since"] is None
    assert seal["last_cutoff"] == "2024-03-04T13:02:44Z"

    (upload,) = _rows(store, store.track_seal_uploads, seal_id=opened.seal_id)
    assert upload["id"] == opened.upload_id and upload["position"] == 1
    assert upload["audit_id"] == audit_id and upload["previous_hash"] == ""
    assert upload["at"] == opened.opened_at and upload["cutoff"] == seal["last_cutoff"]
    entry = json.loads(upload["entry_json"])
    assert entry["position"] == 1 and entry["event_kind"] == "uploaded"
    assert entry["closed_count"] == upload["closed_count"] == 1
    assert entry["flow_count"] == upload["flow_count"] == 1
    assert upload["hash"] == track_seal.entry_hash(entry) == opened.head_hash
    snap = track_seal.load_snapshot(upload["snapshot_json"])
    assert upload["trades_sha256"] == entry["trades_sha256"] == track_seal.trades_sha256(snap)

    (event,) = _rows(store, store.track_seal_events, seal_id=opened.seal_id)
    assert event["kind"] == "opened" and event["count"] == 0
    assert event["upload_id"] == opened.upload_id and event["at"] == opened.opened_at
    assert _rows(store, store.track_seal_quota, account_id=account_id) == [
        {"account_id": account_id, "opened": 1}
    ]
    assert service.quota(store, account_id) == (1, service.MAX_RECORDS_PER_ACCOUNT)

    sealed = json.loads(seal["sealed_json"])
    assert sealed["class"] == "" and sealed["pending_reason"] == service.TOO_FEW_OBSERVATIONS
    assert sealed["observations"] == {"value": "0", "evidence": "MEASURED"}
    assert sealed["min_observations"] == {"value": str(MIN_OBSERVATIONS), "evidence": "DECLARED"}
    assert sealed["full_class"]["value"] == "B" and sealed["full_class"]["evidence"] == "MEASURED"
    assert sealed["start"] == "2024-03-06T12:00:00Z"
    assert sealed["computed_at"] == opened.opened_at


def test_quota_is_five_openings_ever(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    data = _bytes(MT4)
    seal_ids = []
    for i in range(5):
        audit_id = _audit(store, account_id, f"audit{i}", data)
        seal_ids.append(
            _opened(
                service.open_record(
                    store,
                    account_id=account_id,
                    audit_id=audit_id,
                    now=T3,
                    bootstrap_samples=BOOTSTRAP,
                )
            ).seal_id
        )
    sixth = _audit(store, account_id, "audit6", data)
    assert service.open_record(
        store, account_id=account_id, audit_id=sixth, now=T3, bootstrap_samples=BOOTSTRAP
    ) == track_seal.Refusal("quota")
    # Deleting a record never frees its slot.
    assert service.delete_record(store, seal_id=seal_ids[0], account_id=account_id, now=T3) is None
    assert service.open_record(
        store, account_id=account_id, audit_id=sixth, now=T3, bootstrap_samples=BOOTSTRAP
    ) == track_seal.Refusal("quota")
    assert service.quota(store, account_id) == (5, 5)
    assert len(service.list_records(store, account_id)) == 4


def test_opening_refuses_unpaid_foreign_saved_tester_purged_and_mismatched(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    stranger = _account(store, "other@example.com")
    data = _bytes(MT4)

    def attempt(audit_id: str) -> object:
        return service.open_record(
            store, account_id=account_id, audit_id=audit_id, now=T3, bootstrap_samples=BOOTSTRAP
        )

    assert attempt("missing") == track_seal.Refusal("not_found")
    assert attempt(_audit(store, stranger, "theirs", data)) == track_seal.Refusal("not_found")
    assert attempt(_audit(store, None, "unlinked", data)) == track_seal.Refusal("not_found")
    assert attempt(_audit(store, account_id, "saved", data, via=VIA_SAVED)) == track_seal.Refusal(
        "not_own"
    )
    assert attempt(_audit(store, account_id, "unpaid", data, paid=False)) == track_seal.Refusal(
        "unpaid"
    )
    tester = _bytes("mt5_tester.html")
    assert attempt(
        _audit(store, account_id, "tester", tester, name="report.html")
    ) == track_seal.Refusal("unsupported_file")
    assert attempt(
        _audit(store, account_id, "wrong_digest", data, digest="0" * 64)
    ) == track_seal.Refusal("stored_file_mismatch")
    purged = _audit(store, account_id, "purged", data)
    with store.engine.begin() as conn:
        conn.execute(
            store.audits.update()
            .where(store.audits.c.id == purged)
            .values(purged_at="2024-03-08T00:00:00Z")
        )
    assert attempt(purged) == track_seal.Refusal("purged")
    # A plain equity curve is neither a statement nor a monthly table.
    curve = _monthly_audit(store, account_id, "curve", b"timestamp,equity\n2024-01-01,100\n")
    assert attempt(curve) == track_seal.Refusal("unsupported_file")
    # Refusals write nothing.
    assert _rows(store, store.track_seals) == []
    assert _rows(store, store.track_seal_uploads) == []
    assert _rows(store, store.track_seal_events) == []
    assert _rows(store, store.track_seal_quota) == []


# ---------------------------------------------------------------------------
# Continuing
# ---------------------------------------------------------------------------


def test_uploads_continue_the_record_and_the_head_recomputes_with_hashlib(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    _, opened = _open_cut1(store, account_id)
    second = _audit(store, account_id, "second", edit.cut_statement(_bytes(MT4), keep_to=D2))
    added = _added(
        service.add_upload(
            store,
            seal_id=opened.seal_id,
            account_id=account_id,
            audit_id=second,
            now=T2,
            bootstrap_samples=BOOTSTRAP,
        )
    )
    assert added.position == 2 and added.event == "uploaded" and added.count == 0
    third = _audit(store, account_id, "third", _bytes(MT4))
    last = _added(
        service.add_upload(
            store,
            seal_id=opened.seal_id,
            account_id=account_id,
            audit_id=third,
            now=T3,
            bootstrap_samples=BOOTSTRAP,
        )
    )
    assert last.position == 3 and last.event == "uploaded"
    seal = _seal(store, opened.seal_id)
    assert seal["upload_count"] == 3 and seal["head_hash"] == last.head_hash
    assert seal["last_upload_at"] == "2024-03-09T12:00:00Z"
    assert seal["last_cutoff"] == "2024-03-07T10:00:00Z"

    # The head, from the stored entries with hashlib and json only.
    uploads = sorted(
        _rows(store, store.track_seal_uploads, seal_id=opened.seal_id), key=lambda r: r["position"]
    )
    previous = ""
    for row in uploads:
        entry = json.loads(row["entry_json"])
        assert entry["previous_hash"] == previous
        text = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        previous = hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert row["hash"] == previous
    assert previous == seal["head_hash"]
    assert service.verify(store, opened.seal_id) == (True, None)

    chain = service.chain_json(store, opened.seal_id)
    assert chain["head_hash"] == seal["head_hash"] and chain["chain_ok"] is True
    assert [entry["position"] for entry in chain["entries"]] == [1, 2, 3]
    assert chain["entries"][-1]["hash"] == seal["head_hash"]
    assert chain["recipe_version"] == track_seal.RECIPE_VERSION
    assert set(chain["recipe"]) == {
        "entry_hash",
        "canonical_json",
        "previous_hash",
        "head_hash",
        "at",
    }
    events = [
        e["kind"]
        for e in sorted(
            _rows(store, store.track_seal_events, seal_id=opened.seal_id), key=lambda r: r["at"]
        )
    ]
    assert events == ["opened", "uploaded", "uploaded"]
    views = service.record_uploads(store, opened.seal_id)
    assert [view.position for view in views] == [1, 2, 3]
    assert [view.audit_id for view in views] == ["opening-report", "second", "third"]


def test_a_seeded_deletion_is_a_mismatch_event_with_its_detail(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    _, opened = _open_cut1(store, account_id)
    full = _bytes(MT4)
    table = rows.load(full, MT4_FORMAT)
    # Ticket 1000003 closed before the first cut: its removal is a deletion.
    victim = next(r for r in table.rows if r.kind == rows.KIND_MT4_TRADE and r.text(0) == "1000003")
    edited = _audit(store, account_id, "edited", edit.delete_row(full, victim.index))
    added = _added(
        service.add_upload(
            store,
            seal_id=opened.seal_id,
            account_id=account_id,
            audit_id=edited,
            now=T3,
            bootstrap_samples=BOOTSTRAP,
        )
    )
    assert added.event == "mismatch" and added.count == 1
    (event,) = _rows(store, store.track_seal_events, seal_id=opened.seal_id, kind="mismatch")
    assert event["count"] == 1 and event["upload_id"] == added.upload_id
    detail = json.loads(event["detail_json"])
    assert len(detail) == 1 and detail[0]["kind"] == "deleted" and detail[0]["k"] == "t"
    entry = json.loads(_rows(store, store.track_seal_uploads, id=added.upload_id)[0]["entry_json"])
    assert entry["event_kind"] == "mismatch" and entry["event_count"] == 1
    views = service.record_events(store, opened.seal_id)
    assert [view.kind for view in views] == ["opened", "mismatch"]
    (operation,) = views[1].detail
    assert operation.kind == "deleted" and operation.k == "t"
    assert operation.at == "2024-03-04T13:02:44Z" and operation.fields == ()
    assert not hasattr(operation, "ref")


def test_refusals_of_an_upload_write_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    full = _bytes(MT4)
    later = _audit(store, account_id, "later", edit.cut_statement(full, keep_to=D2))
    opened = _opened(
        service.open_record(
            store, account_id=account_id, audit_id=later, now=T2, bootstrap_samples=BOOTSTRAP
        )
    )

    def rows_now() -> tuple[int, int, str]:
        return (
            len(_rows(store, store.track_seal_uploads)),
            len(_rows(store, store.track_seal_events)),
            _seal(store, opened.seal_id)["head_hash"],
        )

    before = rows_now()

    def attempt(audit_id: str, *, seal_id: str = opened.seal_id, who: str = account_id) -> object:
        return service.add_upload(
            store,
            seal_id=seal_id,
            account_id=who,
            audit_id=audit_id,
            now=T3,
            bootstrap_samples=BOOTSTRAP,
        )

    earlier = _audit(store, account_id, "earlier", edit.cut_statement(full, keep_to=D1))
    assert attempt(earlier) == track_seal.Refusal("cutoff_not_advanced")
    assert attempt(later) == track_seal.Refusal("already_linked")
    other_account = _audit(store, account_id, "other", full.replace(b"12345678", b"87654321"))
    assert attempt(other_account) == track_seal.Refusal("account_differs")
    workbook = _audit(store, account_id, "mt5", _bytes(MT5), name="report.html")
    assert attempt(workbook) == track_seal.Refusal("format_changed")
    assert attempt(_audit(store, account_id, "unpaid", full, paid=False)) == track_seal.Refusal(
        "unpaid"
    )
    stranger = _account(store, "other@example.com")
    assert attempt(full and _audit(store, stranger, "theirs", full), who=stranger) == (
        track_seal.Refusal("record_not_open")
    )
    assert attempt("missing", seal_id="nope") == track_seal.Refusal("record_not_open")
    assert rows_now() == before
    # The record still continues with the complete history.
    assert _added(attempt(_audit(store, account_id, "full", full))).event == "uploaded"


# ---------------------------------------------------------------------------
# The sealed stretch
# ---------------------------------------------------------------------------


def test_sealed_stretch_gets_a_class_once_it_holds_enough_observations(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    long = _long_mt4()
    start = _audit(store, account_id, "start", edit.cut_statement(long, keep_to=D2))
    opened = _opened(
        service.open_record(
            store, account_id=account_id, audit_id=start, now=T2, bootstrap_samples=BOOTSTRAP
        )
    )
    pending = service.get_record(store, opened.seal_id)
    assert pending is not None and pending.sealed is not None
    assert pending.sealed.stretch_class == "" and pending.sealed.observations == "0"

    middle = _audit(
        store,
        account_id,
        "middle",
        edit.cut_statement(long, keep_to=datetime(2024, 3, 25, 23, 59, 59)),
    )
    _added(
        service.add_upload(
            store,
            seal_id=opened.seal_id,
            account_id=account_id,
            audit_id=middle,
            now=datetime(2024, 3, 26, 12, 0, tzinfo=UTC),
            bootstrap_samples=BOOTSTRAP,
        )
    )
    partway = service.get_record(store, opened.seal_id)
    assert partway is not None and partway.sealed is not None
    sealed = partway.sealed
    assert 0 < int(sealed.observations) < MIN_OBSERVATIONS
    assert sealed.stretch_class == "" and sealed.pending_reason == service.TOO_FEW_OBSERVATIONS
    assert sealed.min_observations == str(MIN_OBSERVATIONS)
    assert sealed.months_to_know_evidence == "MEASURED" and int(sealed.months_to_know) >= 1
    assert sealed.pace_evidence == "MEASURED" and float(sealed.pace_per_month) > 0
    assert sealed.full_class == "B" and sealed.full_class_scope.startswith("whole_file")

    final = _audit(store, account_id, "final", long)
    _added(
        service.add_upload(
            store,
            seal_id=opened.seal_id,
            account_id=account_id,
            audit_id=final,
            now=datetime(2024, 5, 1, 12, 0, tzinfo=UTC),
            bootstrap_samples=BOOTSTRAP,
        )
    )
    done = service.get_record(store, opened.seal_id)
    assert done is not None and done.sealed is not None
    assert int(done.sealed.observations) >= MIN_OBSERVATIONS
    assert done.sealed.stretch_class in ("A", "B", "C", "D") and done.sealed.pending_reason == ""
    assert done.sealed.months_to_know == "0" and done.sealed.months_reason == ""
    # The balance curve is daily: the first observation is the day of S.
    assert done.sealed.first_observation.startswith("2024-03-07")
    assert done.sealed.computed_at == "2024-05-01T12:00:00Z"
    stored = json.loads(_seal(store, opened.seal_id)["sealed_json"])
    assert service.SealedStretch.from_dict(stored) == done.sealed
    for figure in ("observations", "min_observations", "months_to_know", "full_class"):
        assert stored[figure]["evidence"] in ("MEASURED", "DECLARED", "NOT_MEASURED")


def test_months_to_know_reasons() -> None:
    measured = {"value": 0.2, "evidence": "MEASURED"}
    first, last = datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 3, 1, tzinfo=UTC)
    positive = {
        "sharpe_per_period": measured,
        "min_track_record_length": {"value": 40.0, "evidence": "MEASURED"},
    }
    months, evidence, reason, pace = service._months_to_know(positive, 20, first, last)
    # 20 observations in two months: 10 a month; 20 more to reach 40.
    assert (months, evidence, reason, pace) == ("2", "MEASURED", "", "10.1")
    assert service._months_to_know(positive, 45, first, last) == ("0", "MEASURED", "", "")
    flat = {
        "sharpe_per_period": {"value": -0.1, "evidence": "MEASURED"},
        "min_track_record_length": {"value": None, "evidence": "NOT_MEASURED"},
    }
    assert service._months_to_know(flat, 20, first, last) == (
        "",
        "NOT_MEASURED",
        service.NO_POSITIVE_MEAN,
        "",
    )
    few = {"sharpe_per_period": {"value": None, "evidence": "NOT_MEASURED"}}
    assert service._months_to_know(few, 2, first, last) == (
        "",
        "NOT_MEASURED",
        service.TOO_FEW_OBSERVATIONS,
        "",
    )
    assert service._months_to_know(positive, 20, first, first)[2] == service.TOO_FEW_OBSERVATIONS
    # Under MIN_OBSERVATIONS the estimate counts to MIN_OBSERVATIONS at least.
    small = {
        "sharpe_per_period": measured,
        "min_track_record_length": {"value": 5.0, "evidence": "MEASURED"},
    }
    assert service._months_to_know(small, 20, first, last)[0] == "1"


# ---------------------------------------------------------------------------
# Monthly tables
# ---------------------------------------------------------------------------


def test_monthly_record_opens_continues_and_gets_a_class(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    year_one = {f"2020-{m:02d}": 1.0 + (m % 3) * 0.4 - 0.5 for m in range(1, 13)}
    first = _monthly_audit(store, account_id, "m1", _grid_csv(year_one))
    opened = _opened(
        service.open_record(
            store,
            account_id=account_id,
            audit_id=first,
            now=datetime(2021, 1, 15, tzinfo=UTC),
            bootstrap_samples=BOOTSTRAP,
        )
    )
    seal = _seal(store, opened.seal_id)
    assert seal["source_format"] == track_seal.MONTHLY_FORMAT
    assert seal["last_cutoff"] == "2020-12-31T23:59:59Z"
    sealed = json.loads(seal["sealed_json"])
    assert sealed["class"] == "" and sealed["start"] == "2021-02"
    later = dict(year_one)
    for year in (2021, 2022, 2023):
        for m in range(1, 13):
            later[f"{year}-{m:02d}"] = 0.8 + ((year + m) % 4) * 0.5 - 0.6
    for m in range(1, 7):
        later[f"2024-{m:02d}"] = 0.9 + (m % 2) * 0.3
    second = _monthly_audit(store, account_id, "m2", _grid_csv(later))
    added = _added(
        service.add_upload(
            store,
            seal_id=opened.seal_id,
            account_id=account_id,
            audit_id=second,
            now=datetime(2024, 7, 5, tzinfo=UTC),
            bootstrap_samples=BOOTSTRAP,
        )
    )
    assert added.event == "uploaded" and added.count == 0
    record = service.get_record(store, opened.seal_id)
    assert record is not None and record.sealed is not None
    # Sealed months: 2021-02 .. 2024-06, 41 returns.
    assert record.sealed.observations == "41"
    assert record.sealed.stretch_class in ("A", "B", "C", "D")
    assert record.sealed.full_class == "C"
    # A revised past month, in an export that adds a month, is a mismatch event.
    revised = dict(later)
    revised["2020-03"] = later["2020-03"] + 0.5
    revised["2024-07"] = 0.4
    third = _monthly_audit(store, account_id, "m3", _grid_csv(revised))
    mismatch = _added(
        service.add_upload(
            store,
            seal_id=opened.seal_id,
            account_id=account_id,
            audit_id=third,
            now=datetime(2024, 8, 5, tzinfo=UTC),
            bootstrap_samples=BOOTSTRAP,
        )
    )
    assert mismatch.event == "mismatch" and mismatch.count == 1
    # Freshness: 75 days for a monthly table.
    record = service.get_record(store, opened.seal_id)
    assert record is not None
    assert service.freshness(record, datetime(2024, 10, 10, tzinfo=UTC)) == (
        "current",
        "2024-08-05T00:00:00Z",
    )
    assert service.freshness(record, datetime(2024, 10, 25, tzinfo=UTC))[0] == "stale"
    # Two different monthly records never share a publication hash.
    other = _monthly_audit(store, account_id, "m4", _grid_csv({"2023-01": 0.4, "2023-02": 0.2}))
    twin = _opened(
        service.open_record(
            store,
            account_id=account_id,
            audit_id=other,
            now=datetime(2024, 8, 5, tzinfo=UTC),
            bootstrap_samples=BOOTSTRAP,
        )
    )
    uploads = {
        row["seal_id"]: row["trades_sha256"]
        for row in _rows(store, store.track_seal_uploads, position=1)
    }
    assert uploads[opened.seal_id] != uploads[twin.seal_id]


# ---------------------------------------------------------------------------
# Freshness, verification, publication, panel
# ---------------------------------------------------------------------------


def test_freshness_is_45_days_for_a_statement(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    _, opened = _open_cut1(store, account_id)
    record = service.get_record(store, opened.seal_id, account_id=account_id)
    assert record is not None
    assert service.freshness(record, T1 + timedelta(days=44)) == ("current", "2024-03-05T12:00:00Z")
    assert service.freshness(record, T1 + timedelta(days=45)) == ("stale", "2024-03-05T12:00:00Z")
    assert service.get_record(store, opened.seal_id, account_id="someone-else") is None


def test_a_tampered_entry_breaks_verification(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    _, opened = _open_cut1(store, account_id)
    second = _audit(store, account_id, "second", edit.cut_statement(_bytes(MT4), keep_to=D2))
    _added(
        service.add_upload(
            store,
            seal_id=opened.seal_id,
            account_id=account_id,
            audit_id=second,
            now=T2,
            bootstrap_samples=BOOTSTRAP,
        )
    )
    assert service.verify(store, opened.seal_id) == (True, None)
    uploads = store.track_seal_uploads
    (row,) = _rows(store, uploads, seal_id=opened.seal_id, position=2)
    entry = json.loads(row["entry_json"])
    entry["closed_count"] += 1
    with store.engine.begin() as conn:
        conn.execute(
            uploads.update()
            .where(uploads.c.id == row["id"])
            .values(entry_json=json.dumps(entry, sort_keys=True, separators=(",", ":")))
        )
    assert service.verify(store, opened.seal_id) == (False, 2)
    assert service.chain_json(store, opened.seal_id)["broken_position"] == 2
    # A page never shows the class of a broken chain: the flag travels with the view.
    assert service.public_record(store, opened.public_id) is None  # not published yet


def test_publish_unpublish_hide_and_the_tombstone(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    _, opened = _open_cut1(store, account_id)
    public_id = opened.public_id
    assert service.public_record(store, public_id) is None
    assert service.public_record(store, "missing") is None
    assert service.publish(
        store, seal_id=opened.seal_id, account_id=account_id, now=T2, holder_confirmed=False
    ) == track_seal.Refusal("holder_not_confirmed")
    assert service.publish(
        store, seal_id=opened.seal_id, account_id="stranger", now=T2, holder_confirmed=True
    ) == track_seal.Refusal("record_not_found")
    published = service.publish(
        store, seal_id=opened.seal_id, account_id=account_id, now=T2, holder_confirmed=True
    )
    assert published == service.Published(opened.seal_id, public_id, "2024-03-06T12:00:00Z")
    seal = _seal(store, opened.seal_id)
    assert seal["published"] is True and seal["published_since"] == "2024-03-06T12:00:00Z"
    assert seal["holder_confirmed_at"] == "2024-03-06T12:00:00Z"
    (upload,) = _rows(store, store.track_seal_uploads, seal_id=opened.seal_id)
    assert seal["publish_hash"] == upload["trades_sha256"]

    view = service.public_record(store, public_id)
    assert view is not None and view.status == "open" and view.withdrawn_at == ""
    assert view.published_since == "2024-03-06T12:00:00Z" and view.upload_count == 1
    assert view.head_hash == seal["head_hash"] and view.chain_ok is True
    assert view.account_records == 1 and view.method_version == METHOD_VERSION
    assert [(event.kind, event.count, event.detail) for event in view.events] == [
        ("opened", 0, ()),
        ("published", 0, ()),
    ]
    assert view.sealed is not None and view.sealed.stretch_class == ""

    # Hidden by the owner: the same 404, reversibly, with events.
    assert service.hide(store, seal_id=opened.seal_id, now=T3) is None
    assert service.public_record(store, public_id) is None
    assert _seal(store, opened.seal_id)["hidden_at"] == "2024-03-09T12:00:00Z"
    assert service.hide(store, seal_id=opened.seal_id, now=T3) is None  # idempotent
    assert service.unhide(store, seal_id=opened.seal_id, now=T3) is None
    assert service.public_record(store, public_id) is not None
    assert service.hide(store, seal_id="missing", now=T3) == track_seal.Refusal("record_not_found")

    # Unpublished: published_since stays, the unpublication is an event.
    assert service.unpublish(store, seal_id=opened.seal_id, account_id=account_id, now=T3) is None
    seal = _seal(store, opened.seal_id)
    assert seal["published"] is False and seal["published_since"] == "2024-03-06T12:00:00Z"
    assert service.public_record(store, public_id) is None
    again = service.publish(
        store,
        seal_id=opened.seal_id,
        account_id=account_id,
        now=T3 + timedelta(days=1),
        holder_confirmed=True,
    )
    assert isinstance(again, service.Published) and again.published_since == "2024-03-06T12:00:00Z"
    kinds = [
        e["kind"]
        for e in sorted(
            _rows(store, store.track_seal_events, seal_id=opened.seal_id), key=lambda r: r["at"]
        )
    ]
    assert kinds == ["opened", "published", "hidden", "shown", "unpublished", "published"]
    assert set(kinds) <= set(store_hooks.EVENT_KINDS)

    # The same operations admit one public record.
    twin_audit = _audit(store, account_id, "twin", edit.cut_statement(_bytes(MT4), keep_to=D1))
    twin = _opened(
        service.open_record(
            store, account_id=account_id, audit_id=twin_audit, now=T3, bootstrap_samples=BOOTSTRAP
        )
    )
    assert service.publish(
        store, seal_id=twin.seal_id, account_id=account_id, now=T3, holder_confirmed=True
    ) == track_seal.Refusal("already_public")
    listed = service.list_records(store, account_id)
    assert [record.id for record in listed] == [opened.seal_id, twin.seal_id]
    assert listed[0].published is True and listed[1].published is False

    # Deleted: a published record leaves a tombstone, an unpublished one vanishes.
    assert (
        service.delete_record(store, seal_id=opened.seal_id, account_id=account_id, now=T3) is None
    )
    tomb = service.public_record(store, public_id)
    assert tomb == service.PublicView(
        public_id=public_id, status="withdrawn", withdrawn_at="2024-03-09T12:00:00Z"
    )
    assert service.delete_record(store, seal_id=twin.seal_id, account_id=account_id, now=T3) is None
    assert service.public_record(store, twin.public_id) is None
    assert service.list_records(store, account_id) == []
    assert service.get_record(store, twin.seal_id) is None
    assert service.delete_record(store, seal_id=twin.seal_id, account_id=account_id, now=T3) == (
        track_seal.Refusal("record_not_found")
    )


def test_ending_freezes_the_record(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    _, opened = _open_cut1(store, account_id)
    assert service.end_record(store, seal_id=opened.seal_id, account_id="x", now=T2) == (
        track_seal.Refusal("record_not_found")
    )
    assert service.end_record(store, seal_id=opened.seal_id, account_id=account_id, now=T2) is None
    record = service.get_record(store, opened.seal_id)
    assert record is not None and record.status == "ended"
    assert record.ended_reason == store_hooks.ENDED_BY_HOLDER and record.ended_at
    assert service.end_record(store, seal_id=opened.seal_id, account_id=account_id, now=T2) == (
        track_seal.Refusal("record_not_open")
    )
    second = _audit(store, account_id, "second", _bytes(MT4))
    assert service.add_upload(
        store,
        seal_id=opened.seal_id,
        account_id=account_id,
        audit_id=second,
        now=T3,
        bootstrap_samples=BOOTSTRAP,
    ) == track_seal.Refusal("record_not_open")
    # An ended record can still be published, frozen with its date.
    assert isinstance(
        service.publish(
            store, seal_id=opened.seal_id, account_id=account_id, now=T3, holder_confirmed=True
        ),
        service.Published,
    )
    view = service.public_record(store, opened.public_id)
    assert view is not None and view.status == "ended" and view.ended_at


def test_store_hooks_end_withdraw_and_export_the_records(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    first, opened = _open_cut1(store, account_id)
    export = store.account_export(account_id)
    assert export is not None
    (exported,) = export["track_records"]
    assert exported["id"] == opened.seal_id and exported["uploads"][0]["report"] == first
    assert "snapshot_json" not in json.dumps(export)

    assert store.delete_audit(first) is True
    record = service.get_record(store, opened.seal_id)
    assert record is not None and record.status == "ended"
    assert record.ended_reason == store_hooks.ENDED_REPORT_DELETED
    (upload,) = service.record_uploads(store, opened.seal_id)
    assert upload.audit_id == ""
    assert service.chain_json(store, opened.seal_id)["chain_ok"] is True

    assert store.delete_account(account_id) == []
    assert service.get_record(store, opened.seal_id) is None
    assert service.quota(store, account_id) == (0, 5)
    assert _rows(store, store.track_seal_uploads) == []
    assert _rows(store, store.track_seal_events) == []


# ---------------------------------------------------------------------------
# Nothing private, and wording
# ---------------------------------------------------------------------------


def test_nothing_from_the_file_reaches_rows_or_views(tmp_path: Path) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    _, opened = _open_cut1(store, account_id)
    full = _bytes(MT4)
    table = rows.load(full, MT4_FORMAT)
    # Ticket 1000003 closed before the first cut: its removal is a deletion.
    victim = next(r for r in table.rows if r.kind == rows.KIND_MT4_TRADE and r.text(0) == "1000003")
    edited = _audit(store, account_id, "edited", edit.delete_row(full, victim.index))
    _added(
        service.add_upload(
            store,
            seal_id=opened.seal_id,
            account_id=account_id,
            audit_id=edited,
            now=T3,
            bootstrap_samples=BOOTSTRAP,
        )
    )
    service.publish(
        store, seal_id=opened.seal_id, account_id=account_id, now=T3, holder_confirmed=True
    )
    seal_rows = _rows(store, store.track_seals)
    upload_rows = [
        {key: value for key, value in row.items() if key != "snapshot_json"}
        for row in _rows(store, store.track_seal_uploads)
    ]
    event_rows = [
        {key: value for key, value in row.items() if key != "detail_json"}
        for row in _rows(store, store.track_seal_events)
    ]
    details = " ".join(row["detail_json"] for row in _rows(store, store.track_seal_events))
    record = service.get_record(store, opened.seal_id)
    public = service.public_record(store, opened.public_id)
    views = "\n".join(
        [
            repr(record),
            repr(public),
            repr(service.record_events(store, opened.seal_id)),
            repr(service.record_uploads(store, opened.seal_id)),
            repr(service.list_records(store, account_id)),
            json.dumps(service.chain_json(store, opened.seal_id)),
        ]
    )
    stored = json.dumps([seal_rows, upload_rows, event_rows], default=str)
    everything = stored + "\n" + views
    lowered = everything.lower()
    for private in PRIVATE_TEXT:
        assert private not in everything, private
        assert private.lower() not in details.lower(), private
    for symbol in FIXTURE_SYMBOLS:
        assert symbol not in lowered, symbol
        assert symbol not in details.lower(), symbol
    for ticket in FIXTURE_TICKETS:
        assert ticket not in everything, ticket
    # The public view carries neither the account nor a report id.
    assert public is not None
    assert account_id not in repr(public) and "edited" not in repr(public)
    assert "opening-report" not in json.dumps(dataclasses.asdict(public))


def test_codes_are_closed_lists_and_recipe_words_pass_the_guard() -> None:
    assert len(set(service.REFUSAL_CODES)) == len(service.REFUSAL_CODES)
    assert set(track_seal.REFUSAL_CODES) <= set(service.REFUSAL_CODES)
    assert_report_clean(*service.CHAIN_RECIPE.values())
    for text in service.CHAIN_RECIPE.values():
        assert "verified" not in text.lower() and "authentic" not in text.lower()
    expected = {
        "mt4_statement_html",
        "mt5_history_html",
        "mt5_history_xlsx",
        "myfxbook_csv",
        "mql5_signal_csv",
        "fxblue_csv",
    }
    formats = set(service.SUPPORTED_FORMATS)
    assert formats == expected


@pytest.mark.parametrize("name", (MT4, MT5))
def test_both_html_fixtures_open(tmp_path: Path, name: str) -> None:
    store = _store(tmp_path)
    account_id = _account(store)
    audit_id = _audit(store, account_id, "one", _bytes(name), name="report.html")
    opened = _opened(
        service.open_record(
            store, account_id=account_id, audit_id=audit_id, now=T3, bootstrap_samples=BOOTSTRAP
        )
    )
    record = service.get_record(store, opened.seal_id)
    assert record is not None and record.upload_count == 1 and record.currency == "USD"
