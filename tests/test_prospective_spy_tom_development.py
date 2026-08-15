from __future__ import annotations

import calendar as month_calendar
import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes
from quant_trade.research.prospective_spy_tom import (
    ExchangeSession,
    ExplicitExchangeCalendar,
    SpyTomSpec,
    generate_spy_tom_targets,
    load_spy_tom_spec,
)
from quant_trade.research.prospective_spy_tom_development import (
    BOOTSTRAP_REPETITIONS,
    BOOTSTRAP_SEED,
    MANIFEST_SCHEMA,
    MARKET_COLLECTION_MODE,
    MINIMUM_REGULATORY_SELL_BPS,
    NORMAL_IMPACT_BPS_PER_SIDE,
    STRESS_IMPACT_BPS_PER_SIDE,
    ScenarioSnapshot,
    SpyTomDevelopmentVerdict,
    evaluate_spy_tom_development,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "experiments" / "spy_tom_dm1_p3_v1.yaml"
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class _Fixture:
    root: Path
    spec: SpyTomSpec
    calendar: ExplicitExchangeCalendar
    manifest_sha256: str
    cutoff: datetime
    as_of: datetime


def _market_receipt_scope(
    calendar: ExplicitExchangeCalendar,
    *,
    start: str,
    end: str,
) -> dict[str, Any]:
    grouped = calendar.sessions_by_month()
    sessions = calendar.session_by_date()
    event_dates: set[date] = set()
    for anchor, following in zip(
        calendar.complete_months,
        calendar.complete_months[1:],
        strict=False,
    ):
        pair_dates = (
            grouped[anchor][-2],
            grouped[following][2],
            grouped[following][7],
            grouped[following][11],
        )
        if all(
            sessions[session_date].close_timestamp.time().replace(tzinfo=None) >= time(15, 58)
            for session_date in pair_dates
        ):
            event_dates.update(pair_dates)
    windows = [
        {
            "end": datetime.combine(session_date, time(15, 58), tzinfo=NY)
            .astimezone(UTC)
            .isoformat(),
            "start": datetime.combine(session_date, time(15, 56), tzinfo=NY)
            .astimezone(UTC)
            .isoformat(),
        }
        for session_date in sorted(event_dates)
    ]
    return {
        "collection_mode": MARKET_COLLECTION_MODE,
        "event_window_count": len(windows),
        "event_windows_sha256": sha256_of_bytes(canonical_dumps(windows).encode("utf-8")),
        "feed": "SIP",
        "limit": 10_000,
        "scope_end": end,
        "scope_start": start,
        "sort": "asc",
        "symbol": "SPY",
    }


def _spec() -> SpyTomSpec:
    return load_spy_tom_spec(CONFIG)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return ("".join(canonical_dumps(row) + "\n" for row in rows)).encode("utf-8")


def _month_values(start_year: int, start_month: int, count: int) -> list[tuple[int, int]]:
    first = start_year * 12 + start_month - 1
    return [((first + offset) // 12, (first + offset) % 12 + 1) for offset in range(count)]


def _session(day: date, *, close_hour: int = 16) -> ExchangeSession:
    return ExchangeSession(
        session_date=day,
        open_timestamp=datetime.combine(day, time(9, 30), tzinfo=NY),
        close_timestamp=datetime.combine(day, time(close_hour, 0), tzinfo=NY),
    )


def _calendar(
    month_count: int, *, early_close_first_exit: bool = False
) -> ExplicitExchangeCalendar:
    months = _month_values(2016, 1, month_count)
    sessions: list[ExchangeSession] = []
    monthly_dates: list[list[date]] = []
    for year, month in months:
        dates = [
            day
            for number in range(1, month_calendar.monthrange(year, month)[1] + 1)
            if (day := date(year, month, number)).weekday() < 5
        ]
        monthly_dates.append(dates)
    early_date = monthly_dates[1][2] if early_close_first_exit else None
    for dates in monthly_dates:
        sessions.extend(_session(day, close_hour=13 if day == early_date else 16) for day in dates)
    return ExplicitExchangeCalendar(
        calendar_id="XNYS",
        complete_months=tuple(f"{year:04d}-{month:02d}" for year, month in months),
        sessions=tuple(sessions),
    )


def _source_receipt(
    *,
    role: str,
    raw_path: str,
    raw_sha256: str,
    start: str,
    end: str,
    captured: str,
    calendar: ExplicitExchangeCalendar,
) -> dict[str, Any]:
    endpoints = {
        "calendar": "/v2/calendar",
        "quotes": "/v2/stocks/SPY/quotes",
        "trades": "/v2/stocks/SPY/trades",
        "corporate_actions": "/v2/corporate_actions/announcements",
        "fees": "/disclosures/fees",
    }
    if role == "calendar":
        params: dict[str, Any] = {
            "calendar_id": "XNYS",
            "start_date": calendar.session_dates[0].isoformat(),
            "end_date": calendar.session_dates[-1].isoformat(),
        }
    elif role in {"quotes", "trades"}:
        params = _market_receipt_scope(calendar, start=start, end=end)
    elif role == "corporate_actions":
        params = {
            "action_types": ["cash_dividend", "split"],
            "end": end,
            "start": start,
            "symbol": "SPY",
        }
    else:
        params = {
            "effective_end": calendar.session_dates[-1].isoformat(),
            "effective_start": calendar.session_dates[0].isoformat(),
            "scope": "SPY_EQUITY_AND_REGULATORY_FEES",
        }
    return {
        "schema_version": 1,
        "receipt_id": f"synthetic-{role}",
        "provider": "ALPACA",
        "source_kind": (
            "ALPACA_OFFICIAL_DOCUMENT_CAPTURE" if role == "fees" else "ALPACA_HISTORICAL_API"
        ),
        "artifact_role": role,
        "endpoint": endpoints[role],
        "request_parameters": params,
        "http_status": 200,
        "captured_at_utc": captured,
        "raw_path": raw_path,
        "raw_sha256": raw_sha256,
    }


def _write_bundle(
    root: Path,
    *,
    month_count: int = 121,
    omit_first_entry_quote: bool = False,
    include_dividend: bool = True,
    post_cutoff_quote: bool = False,
    regulatory_bps: float = 0.2,
    early_close_first_exit: bool = False,
) -> _Fixture:
    spec = _spec()
    calendar = _calendar(month_count, early_close_first_exit=early_close_first_exit)
    start = calendar.sessions[0].open_timestamp.astimezone(UTC)
    cutoff = calendar.sessions[-1].close_timestamp.astimezone(UTC)
    captured = cutoff + timedelta(days=1)
    observations = tuple(
        datetime.combine(session.session_date, time(15, 55), tzinfo=NY)
        for session in calendar.sessions
        if session.close_timestamp.time().replace(tzinfo=None) == time(16, 0)
    )
    targets = generate_spy_tom_targets(spec, calendar, observations, as_of=cutoff)

    calendar_rows = [
        {
            "date": session.session_date.isoformat(),
            "open": _utc_text(session.open_timestamp),
            "close": _utc_text(session.close_timestamp),
        }
        for session in calendar.sessions
    ]
    quote_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    quote_sequence = 0
    for trade_sequence, target in enumerate(targets):
        if (
            omit_first_entry_quote
            and target.pair_id == "2016-01_TO_2016-02"
            and target.leg == "PRIMARY"
            and target.action == "ENTRY"
        ):
            include_quotes = False
        else:
            include_quotes = True
        if target.leg == "PRIMARY" and target.action == "ENTRY":
            prices = ((99.0, 100.0), (99.5, 101.0))
        elif target.leg == "PRIMARY":
            prices = ((103.0, 104.0), (102.0, 103.0))
        elif target.action == "ENTRY":
            prices = ((99.0, 100.0), (99.5, 101.0))
        else:
            prices = ((100.5, 101.0), (100.0, 100.5))
        if include_quotes:
            for offset_seconds, (bid, ask) in zip((0, 119), prices, strict=True):
                timestamp = target.earliest_execution_timestamp + timedelta(seconds=offset_seconds)
                quote_rows.append(
                    {
                        "timestamp": _utc_text(timestamp),
                        "symbol": "SPY",
                        "bid_price": bid,
                        "ask_price": ask,
                        "bid_size": 100.0,
                        "ask_size": 100.0,
                        "sequence": quote_sequence,
                    }
                )
                quote_sequence += 1
        trade_rows.append(
            {
                "timestamp": _utc_text(target.earliest_execution_timestamp + timedelta(seconds=60)),
                "symbol": "SPY",
                "price": 100.0,
                "size": 10.0,
                "exchange": "V",
                "sequence": trade_sequence,
            }
        )
    if post_cutoff_quote:
        quote_rows.append(
            {
                "timestamp": _utc_text(cutoff + timedelta(seconds=1)),
                "symbol": "SPY",
                "bid_price": 100.0,
                "ask_price": 101.0,
                "bid_size": 1.0,
                "ask_size": 1.0,
                "sequence": quote_sequence,
            }
        )

    first_following_sessions = calendar.sessions_by_month()[calendar.complete_months[1]]
    action_date = first_following_sessions[1]
    corporate_rows = [
        {
            "action_id": "synthetic-dividend-1" if include_dividend else "synthetic-split-1",
            "symbol": "SPY",
            "action_type": "CASH_DIVIDEND" if include_dividend else "SPLIT",
            "effective_date": action_date.isoformat(),
            "announced_at_utc": _utc_text(
                datetime.combine(action_date - timedelta(days=1), time(12), tzinfo=NY)
            ),
            "revised_at_utc": _utc_text(
                datetime.combine(action_date - timedelta(days=1), time(13), tzinfo=NY)
            ),
            "amount_per_share": 1.0 if include_dividend else None,
            "split_ratio": None if include_dividend else 1.0,
        }
    ]
    fee_rows = [
        {
            "effective_start": calendar.session_dates[0].isoformat(),
            "effective_end": calendar.session_dates[-1].isoformat(),
            "commission_bps_per_side": 0.0,
            "regulatory_sell_bps": regulatory_bps,
            "regulatory_sell_fixed_cents": 0,
            "source_url": "https://alpaca.markets/disclosures/fees",
        }
    ]

    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True)
    raw_payloads = {
        "calendar": _jsonl(calendar_rows),
        "quotes": _jsonl(quote_rows),
        "trades": _jsonl(trade_rows),
        "corporate_actions": _jsonl(corporate_rows),
        "fees": _jsonl(fee_rows),
    }
    files: dict[str, dict[str, str]] = {}
    for role, payload in raw_payloads.items():
        relative = f"raw/{role}.jsonl"
        (root / relative).write_bytes(payload)
        files[role] = {"path": relative, "sha256": sha256_of_bytes(payload)}

    start_text = _utc_text(start)
    end_text = _utc_text(cutoff)
    captured_text = _utc_text(captured)
    receipts = [
        _source_receipt(
            role=role,
            raw_path=files[role]["path"],
            raw_sha256=files[role]["sha256"],
            start=start_text,
            end=end_text,
            captured=captured_text,
            calendar=calendar,
        )
        for role in ("calendar", "quotes", "trades", "corporate_actions", "fees")
    ]
    receipt_payload = _jsonl(receipts)
    receipt_path = "raw/receipts.jsonl"
    (root / receipt_path).write_bytes(receipt_payload)
    files["receipts"] = {
        "path": receipt_path,
        "sha256": sha256_of_bytes(receipt_payload),
    }
    manifest = {
        "schema_version": 1,
        "manifest_schema": MANIFEST_SCHEMA,
        "provider": "ALPACA",
        "feed": "SIP",
        "symbol": "SPY",
        "calendar_id": "XNYS",
        "calendar_source": "ALPACA_CALENDAR_API",
        "start": start_text,
        "end": end_text,
        "captured_at_utc": captured_text,
        "development_only": True,
        "files": files,
    }
    manifest_payload = canonical_dumps(manifest).encode("utf-8")
    (root / "manifest.json").write_bytes(manifest_payload)
    return _Fixture(
        root=root,
        spec=spec,
        calendar=calendar,
        manifest_sha256=sha256_of_bytes(manifest_payload),
        cutoff=cutoff,
        as_of=captured,
    )


def _evaluate(fixture: _Fixture) -> SpyTomDevelopmentVerdict:
    return evaluate_spy_tom_development(
        fixture.root,
        fixture.spec,
        fixture.calendar,
        expected_manifest_sha256=fixture.manifest_sha256,
        development_cutoff=fixture.cutoff,
        as_of=fixture.as_of,
    )


def _rewrite_manifest(root: Path, change: dict[str, Any]) -> str:
    path = root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(change)
    payload = canonical_dumps(manifest).encode("utf-8")
    path.write_bytes(payload)
    return sha256_of_bytes(payload)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _rewrite_role_and_bind(
    root: Path,
    role: str,
    rows: list[dict[str, Any]],
) -> str:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    role_path = root / manifest["files"][role]["path"]
    role_payload = _jsonl(rows)
    role_path.write_bytes(role_payload)
    manifest["files"][role]["sha256"] = sha256_of_bytes(role_payload)
    if role != "receipts":
        receipt_path = root / manifest["files"]["receipts"]["path"]
        receipts = _read_jsonl(receipt_path)
        matching = [row for row in receipts if row["artifact_role"] == role]
        assert len(matching) == 1
        matching[0]["raw_sha256"] = sha256_of_bytes(role_payload)
        receipt_payload = _jsonl(receipts)
        receipt_path.write_bytes(receipt_payload)
        manifest["files"]["receipts"]["sha256"] = sha256_of_bytes(receipt_payload)
    manifest_payload = canonical_dumps(manifest).encode("utf-8")
    manifest_path.write_bytes(manifest_payload)
    return sha256_of_bytes(manifest_payload)


def test_reproducible_120_pair_evaluation_is_never_pass_or_live(tmp_path: Path) -> None:
    fixture = _write_bundle(tmp_path)

    first = _evaluate(fixture)
    second = _evaluate(fixture)

    assert first.to_dict() == second.to_dict()
    assert first.report_sha256() == second.report_sha256()
    assert first.status == "INSUFFICIENT_EVIDENCE"
    assert first.eligible_pairs == 120
    assert first.completed_pairs == 120
    assert set(first.scenarios) == {"normal", "stress_5bps_2x_fees"}
    normal = first.scenarios["normal"]
    stress = first.scenarios["stress_5bps_2x_fees"]
    assert normal.impact_bps_per_side == NORMAL_IMPACT_BPS_PER_SIDE
    assert stress.impact_bps_per_side == STRESS_IMPACT_BPS_PER_SIDE
    assert normal.fee_multiplier == 1.0
    assert stress.fee_multiplier == 2.0
    assert normal.bootstrap_repetitions == BOOTSTRAP_REPETITIONS
    assert normal.bootstrap_seed == BOOTSTRAP_SEED
    assert normal.primary_total_return > normal.control_total_return
    assert stress.primary_total_return < normal.primary_total_return
    assert first.evidence_hashes["spec"] == fixture.spec.seal()
    assert not first.pass_allowed
    assert first.metrics_diagnostic_only
    assert not first.external_data_authority_verified
    assert not first.promotion_authorized
    assert not first.live_execution_authorized
    assert not first.real_money_authorized
    assert not first.bank_transfer_authorized


def test_worst_quotes_cost_floor_and_dividend_are_recomputed_not_supplied(
    tmp_path: Path,
) -> None:
    fixture = _write_bundle(tmp_path)
    verdict = _evaluate(fixture)
    normal = verdict.scenarios["normal"]

    impact = Decimal(str(NORMAL_IMPACT_BPS_PER_SIDE)) / Decimal(10_000)
    regulatory = Decimal("0.2") / Decimal(10_000)
    quantity = Decimal(195) / (Decimal(101) * (Decimal(1) + impact))
    primary_exit = quantity * Decimal(102) * (Decimal(1) - impact)
    base_primary = float((Decimal(5) + primary_exit * (Decimal(1) - regulatory)) / 200 - 1)
    dividend_primary = float(
        (Decimal(5) + primary_exit * (Decimal(1) - regulatory) + quantity) / 200 - 1
    )
    expected_mean = (119 * base_primary + dividend_primary) / 120

    assert normal.primary_mean_monthly_return == pytest.approx(expected_mean)
    assert normal.primary_total_fees_usd > 0.0
    assert normal.mean_paired_excess > 0.0


def test_fewer_than_120_matched_months_is_insufficient_without_metrics(tmp_path: Path) -> None:
    fixture = _write_bundle(tmp_path, month_count=120)

    verdict = _evaluate(fixture)

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert verdict.completed_pairs == 119
    assert not verdict.scenarios
    assert "REQUIRES_120_MATCHED_MONTHS_HAS_119" in verdict.reasons


def test_early_close_excludes_entire_pair_and_cannot_select_survivors(tmp_path: Path) -> None:
    fixture = _write_bundle(tmp_path, early_close_first_exit=True)

    verdict = _evaluate(fixture)

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert verdict.completed_pairs == 119
    assert not verdict.scenarios


def test_raw_quote_tamper_is_rejected_before_metrics(tmp_path: Path) -> None:
    fixture = _write_bundle(tmp_path)
    with (tmp_path / "raw" / "quotes.jsonl").open("ab") as handle:
        handle.write(b" ")

    verdict = _evaluate(fixture)

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "RAW_QUOTES_SHA256_MISMATCH" in verdict.reasons
    assert not verdict.scenarios


def test_missing_exact_quote_window_has_no_midpoint_close_or_time_fallback(tmp_path: Path) -> None:
    fixture = _write_bundle(tmp_path, omit_first_entry_quote=True)

    verdict = _evaluate(fixture)

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert any(
        reason.startswith("EXACT_QUOTE_OR_TRADE_WINDOW_MISSING") for reason in verdict.reasons
    )
    assert verdict.completed_pairs == 0
    assert not verdict.scenarios


def test_fully_rehashed_post_cutoff_quote_is_still_rejected(tmp_path: Path) -> None:
    fixture = _write_bundle(tmp_path, post_cutoff_quote=True)

    verdict = _evaluate(fixture)

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "QUOTE_CONTAINS_POST_CUTOFF_OR_PRESTART_DATA" in verdict.reasons
    assert not verdict.scenarios


def test_future_capture_and_cutoff_after_as_of_fail_closed(tmp_path: Path) -> None:
    fixture = _write_bundle(tmp_path)
    before_capture = evaluate_spy_tom_development(
        fixture.root,
        fixture.spec,
        fixture.calendar,
        expected_manifest_sha256=fixture.manifest_sha256,
        development_cutoff=fixture.cutoff,
        as_of=fixture.cutoff,
    )
    future_cutoff = evaluate_spy_tom_development(
        fixture.root,
        fixture.spec,
        fixture.calendar,
        expected_manifest_sha256=fixture.manifest_sha256,
        development_cutoff=fixture.cutoff,
        as_of=fixture.cutoff - timedelta(seconds=1),
    )

    assert "MANIFEST_CAPTURE_IS_AFTER_AS_OF" in before_capture.reasons
    assert "DEVELOPMENT_CUTOFF_IS_AFTER_AS_OF" in future_cutoff.reasons
    assert not before_capture.scenarios
    assert not future_cutoff.scenarios


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"feed": "IEX"}, "MANIFEST_FEED_MISMATCH"),
        ({"symbol": "QQQ"}, "MANIFEST_SYMBOL_MISMATCH"),
        ({"metrics": {"return": 999.0}}, "MANIFEST_SCHEMA_FIELDS_MISMATCH"),
    ],
)
def test_rehashed_manifest_scope_or_caller_metrics_are_rejected(
    tmp_path: Path,
    change: dict[str, Any],
    reason: str,
) -> None:
    fixture = _write_bundle(tmp_path)
    changed_sha = _rewrite_manifest(tmp_path, change)

    verdict = evaluate_spy_tom_development(
        fixture.root,
        fixture.spec,
        fixture.calendar,
        expected_manifest_sha256=changed_sha,
        development_cutoff=fixture.cutoff,
        as_of=fixture.as_of,
    )

    assert reason in verdict.reasons
    assert not verdict.scenarios


def test_receipt_tamper_and_wrong_expected_manifest_digest_fail(tmp_path: Path) -> None:
    fixture = _write_bundle(tmp_path)
    receipt_path = tmp_path / "raw" / "receipts.jsonl"
    receipt_path.write_bytes(receipt_path.read_bytes().replace(b"synthetic-fees", b"forged-fees"))
    receipt_verdict = _evaluate(fixture)
    digest_verdict = evaluate_spy_tom_development(
        fixture.root,
        fixture.spec,
        fixture.calendar,
        expected_manifest_sha256="f" * 64,
        development_cutoff=fixture.cutoff,
        as_of=fixture.as_of,
    )

    assert "RAW_RECEIPTS_SHA256_MISMATCH" in receipt_verdict.reasons
    assert "MANIFEST_SHA256_MISMATCH" in digest_verdict.reasons


def test_legacy_full_range_market_receipt_is_rejected_even_when_rehashed(
    tmp_path: Path,
) -> None:
    fixture = _write_bundle(tmp_path)
    receipt_path = fixture.root / "raw" / "receipts.jsonl"
    receipts = _read_jsonl(receipt_path)
    quote_receipt = next(row for row in receipts if row["artifact_role"] == "quotes")
    quote_receipt["request_parameters"] = {
        "end": _utc_text(fixture.cutoff),
        "feed": "SIP",
        "start": _utc_text(datetime(2016, 1, 1, tzinfo=UTC)),
        "symbol": "SPY",
    }
    manifest_sha = _rewrite_role_and_bind(fixture.root, "receipts", receipts)

    verdict = evaluate_spy_tom_development(
        fixture.root,
        fixture.spec,
        fixture.calendar,
        expected_manifest_sha256=manifest_sha,
        development_cutoff=fixture.cutoff,
        as_of=fixture.as_of,
    )

    assert "RECEIPT_REQUEST_WINDOW_OR_SCOPE_MISMATCH" in verdict.reasons
    assert not verdict.scenarios


def test_missing_dividend_ledger_and_fee_below_floor_are_insufficient(tmp_path: Path) -> None:
    missing_dividend = _write_bundle(tmp_path / "actions", include_dividend=False)
    low_fee = _write_bundle(tmp_path / "fees", regulatory_bps=0.0)

    action_verdict = _evaluate(missing_dividend)
    fee_verdict = _evaluate(low_fee)

    assert "SPY_DIVIDEND_EVIDENCE_IS_MISSING" in action_verdict.reasons
    assert "REGULATORY_SELL_BPS_IS_BELOW_SEALED_FLOOR" in fee_verdict.reasons
    assert not action_verdict.scenarios
    assert not fee_verdict.scenarios


def test_calendar_hours_must_match_content_addressed_alpaca_schedule(tmp_path: Path) -> None:
    fixture = _write_bundle(tmp_path)
    sessions = list(fixture.calendar.sessions)
    original = sessions[10]
    sessions[10] = ExchangeSession(
        original.session_date,
        original.open_timestamp,
        original.close_timestamp.replace(hour=13),
    )
    forged = ExplicitExchangeCalendar(
        fixture.calendar.calendar_id,
        fixture.calendar.complete_months,
        sessions,
    )

    verdict = evaluate_spy_tom_development(
        fixture.root,
        fixture.spec,
        forged,
        expected_manifest_sha256=fixture.manifest_sha256,
        development_cutoff=fixture.cutoff,
        as_of=fixture.as_of,
    )

    assert "CALENDAR_HOURS_DO_NOT_MATCH_CALLER_ATTESTATION" in verdict.reasons
    assert not verdict.scenarios


def test_report_and_scenario_constructors_are_evaluator_only(tmp_path: Path) -> None:
    fixture = _write_bundle(tmp_path)
    base = _evaluate(fixture)

    with pytest.raises(ValueError, match="sealed evaluator"):
        replace(base, status="NO_GO")  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError), match="init=False"):
        replace(base, external_data_authority_verified=True)
    with pytest.raises(ValueError, match="sealed evaluator"):
        replace(base.scenarios["normal"], primary_total_return=999.0)

    with pytest.raises(ValueError, match="only come from the sealed evaluator"):
        SpyTomDevelopmentVerdict(
            status="INSUFFICIENT_EVIDENCE",
            strategy_id="SPY_TOM_Dm1_P3_v1",
            expected_manifest_sha256="a" * 64,
            development_cutoff="2026-01-30T21:00:00+00:00",
            as_of="2026-01-31T21:00:00+00:00",
            eligible_pairs=0,
            completed_pairs=0,
            evidence_hashes={},
            scenarios={},
            reasons=("EXTERNAL_DATA_AUTHORITY_NOT_CRYPTOGRAPHICALLY_VERIFIED",),
        )

    scenario = base.scenarios["normal"]
    with pytest.raises(ValueError, match="only be constructed"):
        ScenarioSnapshot(
            impact_bps_per_side=scenario.impact_bps_per_side,
            fee_multiplier=scenario.fee_multiplier,
            paired_months=scenario.paired_months,
            primary_total_return=999.0,
            control_total_return=scenario.control_total_return,
            primary_mean_monthly_return=scenario.primary_mean_monthly_return,
            control_mean_monthly_return=scenario.control_mean_monthly_return,
            mean_paired_excess=scenario.mean_paired_excess,
            primary_max_drawdown=scenario.primary_max_drawdown,
            control_max_drawdown=scenario.control_max_drawdown,
            bootstrap_year_count=scenario.bootstrap_year_count,
            bootstrap_repetitions=scenario.bootstrap_repetitions,
            bootstrap_seed=scenario.bootstrap_seed,
            paired_excess_ci_low=scenario.paired_excess_ci_low,
            paired_excess_ci_high=scenario.paired_excess_ci_high,
            primary_total_fees_usd=scenario.primary_total_fees_usd,
            control_total_fees_usd=scenario.control_total_fees_usd,
        )


def test_fee_and_impact_constants_are_conservative_and_sealed() -> None:
    assert NORMAL_IMPACT_BPS_PER_SIDE > 0.0
    assert STRESS_IMPACT_BPS_PER_SIDE == 5.0
    assert MINIMUM_REGULATORY_SELL_BPS > 0.0


def test_unhashable_receipt_role_and_corporate_action_type_fail_closed(
    tmp_path: Path,
) -> None:
    receipt_fixture = _write_bundle(tmp_path / "receipt", month_count=2)
    receipt_path = receipt_fixture.root / "raw" / "receipts.jsonl"
    receipts = _read_jsonl(receipt_path)
    receipts[0]["artifact_role"] = []
    receipt_sha = _rewrite_role_and_bind(receipt_fixture.root, "receipts", receipts)
    receipt_verdict = evaluate_spy_tom_development(
        receipt_fixture.root,
        receipt_fixture.spec,
        receipt_fixture.calendar,
        expected_manifest_sha256=receipt_sha,
        development_cutoff=receipt_fixture.cutoff,
        as_of=receipt_fixture.as_of,
    )

    action_fixture = _write_bundle(tmp_path / "action", month_count=2)
    action_path = action_fixture.root / "raw" / "corporate_actions.jsonl"
    actions = _read_jsonl(action_path)
    actions[0]["action_type"] = []
    action_sha = _rewrite_role_and_bind(action_fixture.root, "corporate_actions", actions)
    action_verdict = evaluate_spy_tom_development(
        action_fixture.root,
        action_fixture.spec,
        action_fixture.calendar,
        expected_manifest_sha256=action_sha,
        development_cutoff=action_fixture.cutoff,
        as_of=action_fixture.as_of,
    )

    assert "RECEIPT_ARTIFACT_ROLES_MISMATCH" in receipt_verdict.reasons
    assert "CORPORATE_ACTION_SCOPE_IS_INVALID" in action_verdict.reasons
    assert not receipt_verdict.scenarios
    assert not action_verdict.scenarios


def test_extreme_decimal_quote_and_fee_integer_fail_closed(tmp_path: Path) -> None:
    quote_fixture = _write_bundle(tmp_path / "quote", month_count=2)
    quote_path = quote_fixture.root / "raw" / "quotes.jsonl"
    quotes = _read_jsonl(quote_path)
    quotes[0]["bid_price"] = "1E+1000000"
    quotes[0]["ask_price"] = "1E+1000000"
    quote_sha = _rewrite_role_and_bind(quote_fixture.root, "quotes", quotes)
    quote_verdict = evaluate_spy_tom_development(
        quote_fixture.root,
        quote_fixture.spec,
        quote_fixture.calendar,
        expected_manifest_sha256=quote_sha,
        development_cutoff=quote_fixture.cutoff,
        as_of=quote_fixture.as_of,
    )

    fee_fixture = _write_bundle(tmp_path / "fee", month_count=2)
    fee_path = fee_fixture.root / "raw" / "fees.jsonl"
    fees = _read_jsonl(fee_path)
    fees[0]["regulatory_sell_bps"] = 10**400
    fee_sha = _rewrite_role_and_bind(fee_fixture.root, "fees", fees)
    fee_verdict = evaluate_spy_tom_development(
        fee_fixture.root,
        fee_fixture.spec,
        fee_fixture.calendar,
        expected_manifest_sha256=fee_sha,
        development_cutoff=fee_fixture.cutoff,
        as_of=fee_fixture.as_of,
    )

    assert "QUOTE_BID_IS_INVALID" in quote_verdict.reasons
    assert "FEE_REGULATORY_SELL_BPS_IS_OUTSIDE_ALLOWED_RANGE" in fee_verdict.reasons
    assert not quote_verdict.scenarios
    assert not fee_verdict.scenarios


def test_extreme_timestamp_and_cutoff_timezone_fail_closed(tmp_path: Path) -> None:
    fixture = _write_bundle(tmp_path, month_count=2)
    receipt_path = fixture.root / "raw" / "receipts.jsonl"
    receipts = _read_jsonl(receipt_path)
    receipts[0]["captured_at_utc"] = "0001-01-01T00:00:00+14:00"
    receipt_sha = _rewrite_role_and_bind(fixture.root, "receipts", receipts)
    receipt_verdict = evaluate_spy_tom_development(
        fixture.root,
        fixture.spec,
        fixture.calendar,
        expected_manifest_sha256=receipt_sha,
        development_cutoff=fixture.cutoff,
        as_of=fixture.as_of,
    )

    pathological_cutoff = datetime.min.replace(tzinfo=timezone(timedelta(hours=14)))
    cutoff_verdict = evaluate_spy_tom_development(
        fixture.root,
        fixture.spec,
        fixture.calendar,
        expected_manifest_sha256=receipt_sha,
        development_cutoff=pathological_cutoff,
        as_of=fixture.as_of,
    )

    assert receipt_verdict.status == "INSUFFICIENT_EVIDENCE"
    assert any("RECEIPT_CAPTURED_AT" in reason for reason in receipt_verdict.reasons)
    assert cutoff_verdict.status == "INSUFFICIENT_EVIDENCE"
    assert any("DEVELOPMENT_CUTOFF" in reason for reason in cutoff_verdict.reasons)
    assert not receipt_verdict.scenarios
    assert not cutoff_verdict.scenarios
