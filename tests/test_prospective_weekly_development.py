from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from quant_trade.data.venue_klines import (
    VENUE_POLICIES,
    HttpResponse,
    parse_kline_page,
)
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text
from quant_trade.evidence.receipts import IngestionReceipt, append_receipt, normalized_rows_sha256
from quant_trade.research import prospective_weekly_development as development
from quant_trade.research.prospective_weekly_development import (
    WeeklyDevelopmentVerdict,
    evaluate_weekly_momentum_development,
)
from quant_trade.research.prospective_weekly_momentum import load_weekly_momentum_spec

CONFIG = Path("configs/experiments/binance_btc_weekly_momentum_1w_long_cash_v1.yaml")


def _spec():  # type: ignore[no-untyped-def]
    return load_weekly_momentum_spec(CONFIG)


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return ("".join(canonical_dumps(row) + "\n" for row in rows)).encode("utf-8")


def _chain(records: list[dict[str, Any]]) -> bytes:
    chained: list[dict[str, Any]] = []
    for record in records:
        current = dict(record)
        current["previous_sha256"] = sha256_of_text(canonical_dumps(chained[-1])) if chained else ""
        chained.append(current)
    return _jsonl(chained)


def _write_collection(
    root: Path,
    *,
    first_date: str = "2017-08-17",
    end_date: str = "2023-11-28",
    policy: dict[str, Any] | None = None,
    symbols: tuple[str, ...] = ("BTCUSDT",),
    gap_date: str | None = None,
) -> None:
    series_dir = root / "series"
    series_dir.mkdir(parents=True)
    dates = pd.date_range(first_date, end_date, freq="D", tz="UTC")
    if gap_date is not None:
        dates = dates[dates != pd.Timestamp(gap_date, tz="UTC")]
    symbol_records: list[dict[str, Any]] = []
    for symbol in symbols:
        rows: list[dict[str, Any]] = []
        for index, timestamp in enumerate(dates):
            week = index // 7
            close = 10_000.0 * math.exp(0.00015 * index) * (1.02 if week % 2 else 0.98)
            open_price = close * (0.998 if index % 2 else 1.002)
            rows.append(
                {
                    "date": timestamp.date().isoformat(),
                    "start_ms": int(timestamp.timestamp() * 1_000),
                    "open": open_price,
                    "high": max(open_price, close) * 1.005,
                    "low": min(open_price, close) * 0.995,
                    "close": close,
                    "volume_base": 10_000.0,
                    "turnover_quote": close * 10_000.0,
                }
            )
        payload = _jsonl(rows)
        (series_dir / f"{symbol}.jsonl").write_bytes(payload)
        raw_payload = json.dumps(
            [
                [
                    row["start_ms"],
                    str(row["open"]),
                    str(row["high"]),
                    str(row["low"]),
                    str(row["close"]),
                    str(row["volume_base"]),
                    row["start_ms"] + 86_399_999,
                    str(row["turnover_quote"]),
                ]
                for row in rows
            ],
            separators=(",", ":"),
        ).encode()
        raw_sha = hashlib.sha256(raw_payload).hexdigest()
        raw_dir = root / "raw"
        raw_dir.mkdir(exist_ok=True)
        raw_path = raw_dir / f"{raw_sha}.json"
        raw_path.write_bytes(raw_payload)
        parsed = parse_kline_page(HttpResponse(200, raw_payload), symbol=symbol, venue="binance")
        append_receipt(
            root / "receipts.jsonl",
            IngestionReceipt(
                provider_or_venue="binance",
                endpoint=str(VENUE_POLICIES["binance"]["endpoint"]),
                request_parameters={
                    "symbol": symbol,
                    "start_ms": int(dates[0].timestamp() * 1_000),
                    "end_ms": 1_701_129_600_000,
                },
                http_status=200,
                captured_at_utc="2026-08-13T00:00:00Z",
                adapter_name="data.venue_klines.binance_spot",
                adapter_version="1",
                raw_path=f"raw/{raw_sha}.json",
                raw_sha256=raw_sha,
                normalized_rows_sha256=normalized_rows_sha256(parsed),
                source_kind="live",
            ),
        )
        symbol_records.append(
            {
                "type": "symbol",
                "symbol": symbol,
                "outcome": "listed",
                "row_count": len(rows),
                "pages_fetched": 3,
                "raw_sha256s": [raw_sha],
                "first_date": first_date,
                "last_date": end_date,
                "series_file_sha256": hashlib.sha256(payload).hexdigest(),
                "clock_source": "system",
            }
        )
    active_policy = dict(policy or VENUE_POLICIES["binance"])
    header = {
        "type": "header",
        "schema_version": 1,
        "venue": "binance",
        "policy_sha256": sha256_of_text(canonical_dumps(active_policy)),
        "policy": active_policy,
        "normalized_fields": [
            "date",
            "start_ms",
            "open",
            "high",
            "low",
            "close",
            "volume_base",
            "turnover_quote",
        ],
        "window": [first_date, end_date],
        "wall_clock_utc": "2026-08-13T00:00:00Z",
        "clock_source": "system",
    }
    (root / "journal.jsonl").write_bytes(_chain([header, *symbol_records]))


def test_reproducible_offline_evaluation_is_next_bar_and_never_promotional(
    tmp_path: Path,
) -> None:
    _write_collection(tmp_path)

    first = evaluate_weekly_momentum_development(tmp_path, _spec())
    second = evaluate_weekly_momentum_development(tmp_path, _spec())

    assert first.to_dict() == second.to_dict()
    assert first.report_sha256() == second.report_sha256()
    assert first.status in {"NO_GO", "INSUFFICIENT_EVIDENCE"}
    assert first.completed_decisions == 326
    assert first.signal_count >= 30
    assert set(first.scenarios) == {"normal", "stress_2x_long_fills_50pct"}
    normal = first.scenarios["normal"]
    stress = first.scenarios["stress_2x_long_fills_50pct"]
    assert normal.cost_bps_per_side == 15.0
    assert normal.long_fill_fraction == 1.0
    assert stress.cost_bps_per_side == 30.0
    assert stress.long_fill_fraction == 0.5
    assert normal.strategy.same_bar_fill_count == 0
    assert normal.strategy.first_fill_date == "2017-08-28"
    assert set(normal.benchmarks) == {"btc_usdt_buy_and_hold", "zero_yield_cash"}
    assert set(normal.block_outperformance_counts) == set(normal.benchmarks)
    assert first.evidence_hashes["spec"] == _spec().seal()
    assert not first.promotion_authorized
    assert not first.live_execution_authorized
    assert not first.real_money_authorized


def test_block_partition_counts_every_return_interval_exactly_once() -> None:
    timestamps = pd.date_range("2020-01-01", periods=9, freq="D", tz="UTC")
    strategy = pd.DataFrame(
        {
            "timestamp": timestamps,
            "equity": [100.0, 100.0, 100.0, 100.0, 100.0, 200.0, 200.0, 200.0, 200.0],
        }
    )
    benchmark = pd.DataFrame({"timestamp": timestamps, "equity": [100.0] * len(timestamps)})

    counts = development._block_counts(strategy, {"cash": benchmark}, 2)

    # The 100% return between observations 4 and 5 belongs to the second
    # interval block. Splitting equity points would silently drop that return.
    assert counts == {"cash": 1}


def test_future_journal_window_is_rejected_before_series_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_collection(tmp_path, end_date="2023-11-29")

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("future series must not be opened")

    monkeypatch.setattr(development, "_parse_series", forbidden)
    verdict = evaluate_weekly_momentum_development(tmp_path, _spec())

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "JOURNAL_WINDOW_MUST_END_AT_EXACT_CUTOFF" in verdict.reasons
    assert not verdict.scenarios


def test_legacy_policy_without_endtime_is_rejected_before_series_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = dict(VENUE_POLICIES["binance"])
    policy["url_template"] = (
        "{endpoint}?symbol={symbol}&interval=1d&startTime={start_ms}&limit={limit}"
    )
    _write_collection(tmp_path, policy=policy)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("old-policy series must not be opened")

    monkeypatch.setattr(development, "_parse_series", forbidden)
    verdict = evaluate_weekly_momentum_development(tmp_path, _spec())

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "JOURNAL_REQUEST_POLICY_IS_NOT_CURRENT_BINANCE" in verdict.reasons


def test_series_sha_mismatch_fails_closed(tmp_path: Path) -> None:
    _write_collection(tmp_path)
    with (tmp_path / "series" / "BTCUSDT.jsonl").open("ab") as handle:
        handle.write(b"{}\n")

    verdict = evaluate_weekly_momentum_development(tmp_path, _spec())

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "BTCUSDT_SERIES_DIGEST_MISMATCH" in verdict.reasons
    assert not verdict.scenarios


def test_tampered_series_and_uncommitted_tail_metadata_cannot_bypass_raw_rebuild(
    tmp_path: Path,
) -> None:
    _write_collection(tmp_path)
    series = tmp_path / "series" / "BTCUSDT.jsonl"
    rows = series.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(rows[100])
    tampered["close"] *= 2.0
    tampered["high"] = max(tampered["high"], tampered["close"])
    rows[100] = canonical_dumps(tampered)
    payload = ("\n".join(rows) + "\n").encode()
    series.write_bytes(payload)
    journal = tmp_path / "journal.jsonl"
    records = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    # The terminal symbol row has no successor, so its own content hash is not
    # anchored by the journal chain. Raw receipt reconstruction still catches it.
    records[-1]["series_file_sha256"] = hashlib.sha256(payload).hexdigest()
    records[-1]["row_count"] = len(rows)
    journal.write_bytes(_jsonl(records))

    verdict = evaluate_weekly_momentum_development(tmp_path, _spec())

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "BTCUSDT_SERIES_DOES_NOT_EQUAL_RECEIPT_REBUILD" in verdict.reasons


def test_receipt_chain_tamper_fails_closed(tmp_path: Path) -> None:
    _write_collection(tmp_path)
    path = tmp_path / "receipts.jsonl"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["captured_at_utc"] = "2099-01-01T00:00:00Z"
    path.write_text(canonical_dumps(receipt) + "\n", encoding="utf-8")

    verdict = evaluate_weekly_momentum_development(tmp_path, _spec())

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "RECEIPT_CHAIN_INVALID" in verdict.reasons


def test_receipt_request_endtime_mismatch_fails_closed(tmp_path: Path) -> None:
    _write_collection(tmp_path)
    path = tmp_path / "receipts.jsonl"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["request_parameters"]["end_ms"] += 86_400_000
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = sha256_of_text(canonical_dumps(payload))
    path.write_text(canonical_dumps(receipt) + "\n", encoding="utf-8")

    verdict = evaluate_weekly_momentum_development(tmp_path, _spec())

    assert "RECEIPT_REQUEST_IS_NOT_CAUSAL_LIVE_BINANCE_BTC" in verdict.reasons


def test_fixture_receipt_fails_closed(tmp_path: Path) -> None:
    _write_collection(tmp_path)
    path = tmp_path / "receipts.jsonl"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["source_kind"] = "fixture"
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = sha256_of_text(canonical_dumps(payload))
    path.write_text(canonical_dumps(receipt) + "\n", encoding="utf-8")

    verdict = evaluate_weekly_momentum_development(tmp_path, _spec())

    assert "RECEIPT_REQUEST_IS_NOT_CAUSAL_LIVE_BINANCE_BTC" in verdict.reasons


def test_receipt_raw_bytes_tamper_fails_closed(tmp_path: Path) -> None:
    _write_collection(tmp_path)
    receipt = json.loads((tmp_path / "receipts.jsonl").read_text(encoding="utf-8"))
    with (tmp_path / receipt["raw_path"]).open("ab") as handle:
        handle.write(b" ")

    verdict = evaluate_weekly_momentum_development(tmp_path, _spec())

    assert "RECEIPT_RAW_SHA256_MISMATCH" in verdict.reasons


def test_receipt_normalized_hash_tamper_fails_closed(tmp_path: Path) -> None:
    _write_collection(tmp_path)
    path = tmp_path / "receipts.jsonl"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["normalized_rows_sha256"] = "f" * 64
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = sha256_of_text(canonical_dumps(payload))
    path.write_text(canonical_dumps(receipt) + "\n", encoding="utf-8")

    verdict = evaluate_weekly_momentum_development(tmp_path, _spec())

    assert "RECEIPT_NORMALIZED_ROWS_SHA256_MISMATCH" in verdict.reasons


def test_independent_trade_count_is_closed_long_episodes_not_fill_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_collection(tmp_path)
    original = development.development_weekly_momentum_targets

    def only_one_episode(*args: Any, **kwargs: Any) -> pd.DataFrame:
        targets = original(*args, **kwargs)
        return targets.iloc[:2].copy()

    monkeypatch.setattr(development, "development_weekly_momentum_targets", only_one_episode)
    verdict = evaluate_weekly_momentum_development(tmp_path, _spec())

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert any("REQUIRED_CLOSED_LONG_EPISODES" in reason for reason in verdict.reasons)


def test_gapless_daily_calendar_is_required(tmp_path: Path) -> None:
    _write_collection(tmp_path, gap_date="2020-03-15")

    verdict = evaluate_weekly_momentum_development(tmp_path, _spec())

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "BTCUSDT_DAILY_UTC_CALENDAR_HAS_GAPS_OR_DUPLICATES" in verdict.reasons


def test_mixed_symbol_collection_is_rejected_before_series_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_collection(tmp_path, symbols=("BTCUSDT", "ETHUSDT"))

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("mixed collection series must not be opened")

    monkeypatch.setattr(development, "_parse_series", forbidden)
    verdict = evaluate_weekly_momentum_development(tmp_path, _spec())

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "JOURNAL_SYMBOL_SET_IS_NOT_BTC_ONLY" in verdict.reasons


def test_weekly_development_verdict_cannot_pass_or_authorize_money() -> None:
    with pytest.raises(ValueError, match="never be PASS"):
        WeeklyDevelopmentVerdict(
            status="PASS",  # type: ignore[arg-type]
            strategy_id="binance_btc_weekly_momentum_1w_long_cash_v1",
            decision_start="2017-08-27",
            decision_end="2023-11-26",
            evidence_end="2023-11-28",
            evidence_hashes={},
            completed_decisions=0,
            signal_count=0,
            scenarios={},
            reasons=("forbidden",),
        )

    base = WeeklyDevelopmentVerdict(
        status="INSUFFICIENT_EVIDENCE",
        strategy_id="binance_btc_weekly_momentum_1w_long_cash_v1",
        decision_start="2017-08-27",
        decision_end="2023-11-26",
        evidence_end="2023-11-28",
        evidence_hashes={},
        completed_decisions=0,
        signal_count=0,
        scenarios={},
        reasons=("research only",),
    )
    with pytest.raises(ValueError, match="cannot authorize"):
        replace(base, real_money_authorized=True)
