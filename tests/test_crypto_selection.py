"""Offline tests for the Binance H2 selection-only acquisition boundary."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from quant_trade.data.crypto_selection import (
    BINANCE_H2_SELECTION_SPEC,
    BINDING_FILENAME,
    MANIFEST_FILENAME,
    SELECTION_END,
    SELECTION_START,
    SYMBOLS_FILENAME,
    CryptoSelectionError,
    build_binance_h2_selection_plan,
    collect_binance_h2_selection_klines,
    evaluate_binance_h2_selection_research_readiness,
    load_binance_h2_selection_plan,
    require_binance_h2_selection_research_ready,
)
from quant_trade.data.venue_klines import HttpResponse
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes

_MISSING = object()


def _row(
    cmc_id: int,
    ticker: str,
    *,
    rank: int | None = 100,
    market_cap: float = 100_000_000.0,
    stable: object = _MISSING,
) -> dict[str, object]:
    row: dict[str, object] = {
        "cmc_id": cmc_id,
        "symbol": ticker,
        "name": ticker.title(),
        "cmc_rank": rank,
        "market_cap_usd": market_cap,
        "volume24h_usd": 1_000_000.0,
        "circulating_supply": 1_000_000.0,
    }
    if stable is not _MISSING:
        row["is_stablecoin"] = stable
    return row


def _write_day(root: Path, day: date, rows: list[dict[str, object]]) -> Path:
    target = root / "days" / f"{day.isoformat()}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(canonical_dumps(row) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )
    return target


def _manifest(plan_dir: Path) -> dict[str, object]:
    return json.loads((plan_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))


def _binance_page() -> HttpResponse:
    start_ms = int(
        datetime(
            SELECTION_START.year,
            SELECTION_START.month,
            SELECTION_START.day,
            tzinfo=UTC,
        ).timestamp()
        * 1000
    )
    return HttpResponse(
        200,
        json.dumps(
            [
                [
                    start_ms,
                    "1",
                    "1.1",
                    "0.9",
                    "1",
                    "10",
                    start_ms + 86_399_999,
                    "10",
                    1,
                    "5",
                    "5",
                    "0",
                ]
            ]
        ).encode("utf-8"),
    )


def test_spec_is_frozen_to_binance_spot_and_exact_selection_boundary() -> None:
    with pytest.raises(CryptoSelectionError, match="frozen"):
        replace(BINANCE_H2_SELECTION_SPEC, venue="bybit")
    with pytest.raises(CryptoSelectionError, match="frozen"):
        replace(BINANCE_H2_SELECTION_SPEC, end_date=date(2023, 11, 29))


def test_plan_streams_causal_rows_and_hashes_each_opened_source(tmp_path: Path) -> None:
    universe, plan = tmp_path / "universe", tmp_path / "plan"
    source = _write_day(universe, SELECTION_START, [_row(7, "AAA", stable=False)])

    result = build_binance_h2_selection_plan(universe, plan)

    assert (plan / SYMBOLS_FILENAME).read_bytes() == b"AAAUSDT\n"
    manifest = _manifest(plan)
    assert result.manifest_digest == manifest["digest"]
    assert manifest["sources"] == [
        {
            "bytes": source.stat().st_size,
            "date": "2017-08-17",
            "duplicate_cmc_id_rows_ignored": 0,
            "relative_path": "days/2017-08-17.jsonl",
            "rows": 1,
            "sha256": sha256_of_bytes(source.read_bytes()),
        }
    ]
    assert manifest["status"] == "READY_FOR_SELECTION_ACQUISITION"
    assert manifest["profitability_evidence"] is False
    assert load_binance_h2_selection_plan(plan)["digest"] == result.manifest_digest


def test_future_file_cannot_change_any_plan_byte_prefix_invariance(tmp_path: Path) -> None:
    universe = tmp_path / "universe"
    _write_day(universe, SELECTION_START, [_row(1, "AAA", stable=False)])
    build_binance_h2_selection_plan(universe, tmp_path / "before")
    _write_day(universe, date(2023, 11, 29), [_row(2, "FUTURE", stable=False)])
    build_binance_h2_selection_plan(universe, tmp_path / "after")

    for name in (SYMBOLS_FILENAME, MANIFEST_FILENAME):
        assert (tmp_path / "before" / name).read_bytes() == (tmp_path / "after" / name).read_bytes()


def test_only_exact_start_and_end_boundaries_are_opened(tmp_path: Path) -> None:
    universe, plan = tmp_path / "universe", tmp_path / "plan"
    _write_day(universe, date(2017, 8, 16), [_row(1, "PAST", stable=False)])
    _write_day(universe, SELECTION_START, [_row(2, "FIRST", stable=False)])
    _write_day(universe, SELECTION_END, [_row(3, "LAST", stable=False)])
    _write_day(universe, date(2023, 11, 29), [_row(4, "FUTURE", stable=False)])

    build_binance_h2_selection_plan(universe, plan)

    assert (plan / SYMBOLS_FILENAME).read_text().splitlines() == ["FIRSTUSDT", "LASTUSDT"]
    assert [entry["date"] for entry in _manifest(plan)["sources"]] == [
        "2017-08-17",
        "2023-11-28",
    ]


def test_explicit_historical_stablecoin_flag_excludes_entry(tmp_path: Path) -> None:
    universe, plan = tmp_path / "universe", tmp_path / "plan"
    _write_day(
        universe,
        SELECTION_START,
        [_row(1, "USDX", stable=True), _row(2, "RISK", stable=False)],
    )

    build_binance_h2_selection_plan(universe, plan)

    assert (plan / SYMBOLS_FILENAME).read_text().splitlines() == ["RISKUSDT"]
    manifest = _manifest(plan)
    assert manifest["status"] == "READY_FOR_SELECTION_ACQUISITION"
    assert manifest["discovery"]["stablecoin_true_rows_excluded_from_entry"] == 1


def test_missing_historical_stablecoin_field_is_machine_readable_blocker(
    tmp_path: Path,
) -> None:
    universe, plan = tmp_path / "universe", tmp_path / "plan"
    _write_day(universe, SELECTION_START, [_row(1, "UNKNOWN")])

    build_binance_h2_selection_plan(universe, plan)

    manifest = _manifest(plan)
    assert manifest["status"] == "INSUFFICIENT_EVIDENCE"
    assert manifest["blockers"] == [
        {
            "affected_rows": 1,
            "code": "HISTORICAL_STABLECOIN_CLASSIFICATION_MISSING",
            "effect": (
                "rows without a causal is_stablecoin field were not excluded; "
                "the plan is not a research-ready universe"
            ),
        }
    ]
    # Unknown is not guessed from its spelling or from a current list.
    assert (plan / SYMBOLS_FILENAME).read_text().splitlines() == ["UNKNOWNUSDT"]


def test_research_readiness_refuses_unknown_stablecoin_rows_and_authorizes_nothing(
    tmp_path: Path,
) -> None:
    universe, plan = tmp_path / "universe", tmp_path / "plan"
    _write_day(universe, SELECTION_START, [_row(1, "UNKNOWN")])
    build_binance_h2_selection_plan(universe, plan)

    verdict = evaluate_binance_h2_selection_research_readiness(plan)

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "HISTORICAL_STABLECOIN_CLASSIFICATION_INCOMPLETE" in verdict.blockers
    assert verdict.to_dict()["pnl_generation_authorized"] is False
    assert verdict.to_dict()["holdout_access_authorized"] is False
    assert verdict.to_dict()["real_money_authorized"] is False
    with pytest.raises(CryptoSelectionError, match="not research-ready"):
        require_binance_h2_selection_research_ready(plan)


def test_research_readiness_does_not_trust_ready_label_when_days_are_missing(
    tmp_path: Path,
) -> None:
    universe, plan = tmp_path / "universe", tmp_path / "plan"
    _write_day(universe, SELECTION_START, [_row(1, "AAA", stable=False)])
    build_binance_h2_selection_plan(universe, plan)

    assert _manifest(plan)["status"] == "READY_FOR_SELECTION_ACQUISITION"
    verdict = evaluate_binance_h2_selection_research_readiness(plan)

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "SELECTION_SOURCE_DAYS_INCOMPLETE" in verdict.blockers
    assert "SELECTION_DATES_MISSING" in verdict.blockers
    assert "SELECTION_SOURCE_SEQUENCE_INCOMPLETE" in verdict.blockers


def test_complete_explicit_selection_coverage_passes_only_the_panel_build_gate(
    tmp_path: Path,
) -> None:
    universe, plan = tmp_path / "universe", tmp_path / "plan"
    day = SELECTION_START
    while day <= SELECTION_END:
        rows = [_row(1, "AAA", stable=False)] if day == SELECTION_START else []
        _write_day(universe, day, rows)
        day += timedelta(days=1)
    built = build_binance_h2_selection_plan(universe, plan)

    verdict = evaluate_binance_h2_selection_research_readiness(plan)

    assert verdict.ready is True
    assert verdict.status == "READY_FOR_CAUSAL_PANEL_BUILD"
    assert verdict.source_days == verdict.expected_source_days
    assert verdict.blockers == ()
    assert verdict.to_dict()["pnl_generation_authorized"] is False
    assert require_binance_h2_selection_research_ready(plan)["digest"] == built.manifest_digest


def test_rename_is_kept_only_after_identity_first_becomes_eligible(tmp_path: Path) -> None:
    universe, plan = tmp_path / "universe", tmp_path / "plan"
    _write_day(
        universe,
        SELECTION_START,
        [_row(7, "PRE", market_cap=2_000_000.0, stable=False)],
    )
    _write_day(
        universe,
        date(2017, 8, 18),
        [_row(7, "LIVE", market_cap=20_000_000.0, stable=False)],
    )
    _write_day(
        universe,
        date(2017, 8, 19),
        [_row(7, "RENAMED", rank=1_500, stable=False)],
    )

    build_binance_h2_selection_plan(universe, plan)

    assert (plan / SYMBOLS_FILENAME).read_text().splitlines() == ["LIVEUSDT", "RENAMEDUSDT"]
    renamed = _manifest(plan)["discovery"]["renamed_instruments"]
    assert renamed == [{"instrument_id": "CMC:7", "tickers": ["LIVE", "RENAMED"]}]


def test_ticker_reuse_keeps_stable_cmc_id_mapping_explicit(tmp_path: Path) -> None:
    universe, plan = tmp_path / "universe", tmp_path / "plan"
    _write_day(
        universe,
        SELECTION_START,
        [_row(1, "SAME", stable=False), _row(2, "SAME", stable=False)],
    )

    build_binance_h2_selection_plan(universe, plan)

    assert (plan / SYMBOLS_FILENAME).read_text().splitlines() == ["SAMEUSDT"]
    assert _manifest(plan)["discovery"]["ticker_reuse"] == [
        {"instrument_ids": ["CMC:1", "CMC:2"], "ticker": "SAME"}
    ]


def test_non_exchange_ticker_is_rejected_with_reason(tmp_path: Path) -> None:
    universe, plan = tmp_path / "universe", tmp_path / "plan"
    _write_day(universe, SELECTION_START, [_row(1, "$BAD", stable=False)])

    build_binance_h2_selection_plan(universe, plan)

    assert (plan / SYMBOLS_FILENAME).read_bytes() == b""
    rejected = _manifest(plan)["discovery"]["rejected_ticker_observations"]
    assert rejected[0]["reason"] == "not_uppercase_alphanumeric_1_to_20"


def test_plan_output_must_be_new_or_empty(tmp_path: Path) -> None:
    universe, plan = tmp_path / "universe", tmp_path / "plan"
    _write_day(universe, SELECTION_START, [_row(1, "AAA", stable=False)])
    plan.mkdir()
    (plan / "old-cache").write_text("do not mix")

    with pytest.raises(CryptoSelectionError, match="not empty"):
        build_binance_h2_selection_plan(universe, plan)


@pytest.mark.parametrize("target", [MANIFEST_FILENAME, SYMBOLS_FILENAME])
def test_plan_loader_rejects_tampered_bound_bytes(tmp_path: Path, target: str) -> None:
    universe, plan = tmp_path / "universe", tmp_path / "plan"
    _write_day(universe, SELECTION_START, [_row(1, "AAA", stable=False)])
    build_binance_h2_selection_plan(universe, plan)
    with (plan / target).open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(CryptoSelectionError):
        load_binance_h2_selection_plan(plan)


def test_fetch_wrapper_refuses_venue_or_future_before_network(tmp_path: Path) -> None:
    universe, plan = tmp_path / "universe", tmp_path / "plan"
    _write_day(universe, SELECTION_START, [_row(1, "AAA", stable=False)])
    build_binance_h2_selection_plan(universe, plan)
    calls: list[str] = []

    def forbidden(url: str) -> HttpResponse:
        calls.append(url)
        raise AssertionError("network must not run")

    with pytest.raises(CryptoSelectionError, match="Binance only"):
        collect_binance_h2_selection_klines(
            plan, tmp_path / "venue-a", venue="bybit", fetcher=forbidden
        )
    with pytest.raises(CryptoSelectionError, match="hard-bound"):
        collect_binance_h2_selection_klines(
            plan,
            tmp_path / "venue-b",
            end_date=date(2023, 11, 29),
            fetcher=forbidden,
        )
    assert calls == []


def test_intent_binding_exists_before_first_request_and_request_has_end_time(
    tmp_path: Path,
) -> None:
    universe, plan, venue = tmp_path / "universe", tmp_path / "plan", tmp_path / "venue"
    _write_day(universe, SELECTION_START, [_row(1, "AAA", stable=False)])
    build_binance_h2_selection_plan(universe, plan)
    urls: list[str] = []

    def fetch(url: str) -> HttpResponse:
        assert (venue / BINDING_FILENAME).is_file()
        urls.append(url)
        return _binance_page()

    result = collect_binance_h2_selection_klines(
        plan, venue, fetcher=fetch, clock=lambda: 1_700_000_000.0
    )

    assert result.status == "OK"
    expected_end_ms = int(
        datetime(SELECTION_END.year, SELECTION_END.month, SELECTION_END.day, tzinfo=UTC).timestamp()
        * 1000
    )
    assert urls and f"endTime={expected_end_ms}" in urls[0]
    assert not any("bybit" in url for url in urls)


def test_exact_bound_partial_collection_resumes_in_batches(tmp_path: Path) -> None:
    universe, plan, venue = tmp_path / "universe", tmp_path / "plan", tmp_path / "venue"
    _write_day(
        universe,
        SELECTION_START,
        [_row(1, "AAA", stable=False), _row(2, "BBB", stable=False)],
    )
    build_binance_h2_selection_plan(universe, plan)
    calls: list[str] = []

    def fetch(url: str) -> HttpResponse:
        calls.append(url)
        return _binance_page()

    first = collect_binance_h2_selection_klines(
        plan,
        venue,
        fetcher=fetch,
        clock=lambda: 1_700_000_000.0,
        max_symbols_per_run=1,
    )
    binding_before = (venue / BINDING_FILENAME).read_bytes()
    second = collect_binance_h2_selection_klines(
        plan,
        venue,
        fetcher=fetch,
        clock=lambda: 1_700_000_001.0,
        max_symbols_per_run=1,
    )

    assert first.status == "PARTIAL"
    assert second.status == "OK"
    assert second.symbols_already_done == 1
    assert len(calls) == 2
    assert (venue / BINDING_FILENAME).read_bytes() == binding_before
    assert sorted(path.name for path in (venue / "series").iterdir()) == [
        "AAAUSDT.jsonl",
        "BBBUSDT.jsonl",
    ]


def test_nonempty_unbound_or_mixed_venue_output_is_rejected_without_network(
    tmp_path: Path,
) -> None:
    universe, plan, venue = tmp_path / "universe", tmp_path / "plan", tmp_path / "venue"
    _write_day(universe, SELECTION_START, [_row(1, "AAA", stable=False)])
    build_binance_h2_selection_plan(universe, plan)
    venue.mkdir()
    (venue / "journal.jsonl").write_text("old cache")
    called = False

    def forbidden(url: str) -> HttpResponse:
        nonlocal called
        called = True
        raise AssertionError(url)

    with pytest.raises(CryptoSelectionError, match="not bound byte-for-byte"):
        collect_binance_h2_selection_klines(plan, venue, fetcher=forbidden)
    assert called is False


def test_bound_orphaned_cache_without_journal_is_rejected(tmp_path: Path) -> None:
    universe, plan, venue = tmp_path / "universe", tmp_path / "plan", tmp_path / "venue"
    _write_day(universe, SELECTION_START, [_row(1, "AAA", stable=False)])
    build_binance_h2_selection_plan(universe, plan)

    # First establish the exact immutable intent without allowing an HTTP call.
    def crash(url: str) -> HttpResponse:
        raise KeyboardInterrupt(url)

    with pytest.raises(KeyboardInterrupt):
        collect_binance_h2_selection_klines(plan, venue, fetcher=crash)
    (venue / "journal.jsonl").unlink()
    (venue / "raw").mkdir()
    (venue / "raw" / "orphan.json").write_text("{}")

    with pytest.raises(CryptoSelectionError, match="no valid venue journal"):
        collect_binance_h2_selection_klines(plan, venue, fetcher=crash)
