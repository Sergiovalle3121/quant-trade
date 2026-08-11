"""Tests for the Bybit venue-kline collector: unlisted symbols are a journaled
outcome, delisted history survives, chained journal, lease, resume, frozen
policy and window, injected-clock provenance. Fixtures only."""

from __future__ import annotations

import json
from datetime import date

import pytest

from quant_trade.data.universe import UniverseCollectorError, read_journal, verify_journal_chain
from quant_trade.data.venue_klines import (
    MS_PER_DAY,
    OUTCOME_EMPTY,
    OUTCOME_LISTED,
    OUTCOME_NOT_LISTED,
    SymbolNotListed,
    VenueKlineError,
    collect_venue_klines,
    parse_kline_page,
)

DAY0 = 1_514_764_800_000  # 2018-01-01T00:00:00Z


def _page(symbol: str, bars: list[tuple[int, float]]) -> bytes:
    return json.dumps(
        {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "symbol": symbol,
                "list": [
                    [str(ms), str(px), str(px * 1.1), str(px * 0.9), str(px), "10", "100"]
                    for ms, px in reversed(bars)  # bybit pages arrive newest-first
                ],
            },
        }
    ).encode()


def _unlisted() -> bytes:
    return json.dumps({"retCode": 10001, "retMsg": "Not supported symbols"}).encode()


def _fetcher(pages: dict[str, bytes]):
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        for symbol, payload in pages.items():
            if f"symbol={symbol}&" in url:
                return payload
        raise OSError(f"no fixture for {url}")

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def test_parse_rejects_relabelled_klines() -> None:
    with pytest.raises(ValueError, match="identity mismatch"):
        parse_kline_page(_page("ETHUSDT", [(DAY0, 1.0)]), symbol="BTCUSDT")


def test_parse_raises_symbol_not_listed_distinctly() -> None:
    with pytest.raises(SymbolNotListed):
        parse_kline_page(_unlisted(), symbol="GHOSTUSDT")


def test_parse_rejects_non_positive_prices() -> None:
    bad = json.dumps(
        {
            "retCode": 0,
            "result": {"symbol": "X", "list": [[str(DAY0), "0", "1", "1", "1", "1", "1"]]},
        }
    ).encode()
    with pytest.raises(ValueError, match="non-positive"):
        parse_kline_page(bad, symbol="X")


def test_unlisted_symbol_is_a_journaled_outcome_not_a_skip(tmp_path) -> None:
    fetch = _fetcher({"AUSDT": _page("AUSDT", [(DAY0, 1.0)]), "GHOSTUSDT": _unlisted()})
    result = collect_venue_klines(
        tmp_path,
        ["AUSDT", "GHOSTUSDT"],
        start_date=date(2018, 1, 1),
        end_date=date(2018, 1, 10),
        fetcher=fetch,
        clock=lambda: 1_700_000_000.0,
    )
    assert result.symbols_listed == 1
    assert result.symbols_not_listed == 1
    outcomes = {
        r["symbol"]: r["outcome"] for r in read_journal(tmp_path / "journal.jsonl")
        if r.get("type") == "symbol"
    }
    assert outcomes == {"AUSDT": OUTCOME_LISTED, "GHOSTUSDT": OUTCOME_NOT_LISTED}
    # the absent coin leaves a record, so a later reader can tell "venue never
    # listed it" from "we never asked"
    assert not (tmp_path / "series" / "GHOSTUSDT.jsonl").exists()


def test_delisted_symbol_keeps_its_history_and_death_date(tmp_path) -> None:
    bars = [(DAY0 + i * MS_PER_DAY, 1.0 + i) for i in range(3)]
    fetch = _fetcher({"DEADUSDT": _page("DEADUSDT", bars)})
    collect_venue_klines(
        tmp_path,
        ["DEADUSDT"],
        start_date=date(2018, 1, 1),
        end_date=date(2020, 1, 1),
        fetcher=fetch,
        clock=lambda: 1_700_000_000.0,
    )
    record = next(
        r for r in read_journal(tmp_path / "journal.jsonl") if r.get("type") == "symbol"
    )
    assert record["first_date"] == "2018-01-01"
    assert record["last_date"] == "2018-01-03"  # the series simply stops: that is the death
    series = (tmp_path / "series" / "DEADUSDT.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in series.splitlines()]
    assert [r["date"] for r in rows] == ["2018-01-01", "2018-01-02", "2018-01-03"]


def test_bars_past_the_window_end_are_not_written(tmp_path) -> None:
    bars = [(DAY0 + i * MS_PER_DAY, 1.0) for i in range(10)]
    fetch = _fetcher({"AUSDT": _page("AUSDT", bars)})
    collect_venue_klines(
        tmp_path,
        ["AUSDT"],
        start_date=date(2018, 1, 1),
        end_date=date(2018, 1, 5),
        fetcher=fetch,
        clock=lambda: 1_700_000_000.0,
    )
    rows = [
        json.loads(line)
        for line in (tmp_path / "series" / "AUSDT.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[-1]["date"] == "2018-01-05"


def _collect_two_symbols(tmp_path):
    fetch = _fetcher(
        {"AUSDT": _page("AUSDT", [(DAY0, 1.0)]), "BUSDT": _page("BUSDT", [(DAY0, 2.0)])}
    )
    return collect_venue_klines(
        tmp_path,
        ["AUSDT", "BUSDT"],
        start_date=date(2018, 1, 1),
        end_date=date(2018, 1, 10),
        fetcher=fetch,
        clock=lambda: 1_700_000_000.0,
    )


def test_journal_is_hash_chained_and_tamper_evident(tmp_path) -> None:
    _collect_two_symbols(tmp_path)
    journal = tmp_path / "journal.jsonl"
    verify_journal_chain(read_journal(journal))
    lines = journal.read_text(encoding="utf-8").splitlines()
    edited = json.loads(lines[-2])  # any record with a successor is protected
    edited["row_count"] = 999
    lines[-2] = json.dumps(edited, sort_keys=True, separators=(",", ":"))
    journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(UniverseCollectorError):
        verify_journal_chain(read_journal(journal))


def test_chain_does_not_protect_its_own_last_record(tmp_path) -> None:
    """Documented boundary, not an aspiration.

    ``previous_sha256`` links each record to its predecessor, so the final
    record has nothing committing to it and an edit there passes the chain
    walk. This is inherent to a forward-only hash chain without a sealed tail.
    What still catches such an edit is the per-file digest recorded alongside
    it: the journal claims ``series_file_sha256`` and the validator re-hashes
    the bytes, so tampering with the payload is caught even when tampering
    with the tail record is not. Asserting the limitation keeps it from being
    quietly assumed away.
    """
    _collect_two_symbols(tmp_path)
    journal = tmp_path / "journal.jsonl"
    lines = journal.read_text(encoding="utf-8").splitlines()
    edited = json.loads(lines[-1])
    edited["row_count"] = 999
    lines[-1] = json.dumps(edited, sort_keys=True, separators=(",", ":"))
    journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    verify_journal_chain(read_journal(journal))  # passes: nothing commits to the tail
    tail = read_journal(journal)[-1]
    assert tail["row_count"] == 999
    # but the claim it makes about bytes on disk is still checkable
    series = (tmp_path / "series" / f"{tail['symbol']}.jsonl").read_bytes()
    from quant_trade.evidence.canonical_json import sha256_of_bytes

    assert sha256_of_bytes(series) == tail["series_file_sha256"]
    assert len(series.decode().strip().splitlines()) != tail["row_count"]


def test_resume_skips_terminal_symbols_and_retries_gaps(tmp_path) -> None:
    calls = {"n": 0}

    def flaky(url: str) -> bytes:
        if "symbol=BUSDT&" in url:
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("transient")
            return _page("BUSDT", [(DAY0, 2.0)])
        return _page("AUSDT", [(DAY0, 1.0)])

    common = dict(
        start_date=date(2018, 1, 1),
        end_date=date(2018, 1, 10),
        fetcher=flaky,
        clock=lambda: 1_700_000_000.0,
    )
    first = collect_venue_klines(tmp_path, ["AUSDT", "BUSDT"], **common)
    assert first.status == "PARTIAL"
    assert first.gap_symbols == ["BUSDT"]

    second = collect_venue_klines(tmp_path, ["AUSDT", "BUSDT"], **common)
    assert second.symbols_already_done == 1  # AUSDT terminal, BUSDT retried
    assert second.symbols_listed == 1
    gaps = [r for r in read_journal(tmp_path / "journal.jsonl") if r.get("type") == "gap"]
    assert len(gaps) == 1  # the failure record survives the successful retry
    assert "transient" in gaps[0]["error"]


def test_changed_policy_refuses_to_continue(tmp_path, monkeypatch) -> None:
    fetch = _fetcher({"AUSDT": _page("AUSDT", [(DAY0, 1.0)])})
    common = dict(
        start_date=date(2018, 1, 1),
        end_date=date(2018, 1, 10),
        fetcher=fetch,
        clock=lambda: 1_700_000_000.0,
    )
    collect_venue_klines(tmp_path, ["AUSDT"], **common)
    monkeypatch.setattr(
        "quant_trade.data.venue_klines.VENUE_POLICY_SHA256", "0" * 64
    )
    result = collect_venue_klines(tmp_path, ["BUSDT"], **common)
    assert result.status == "NOT_RUN_JOURNAL_INVALID"
    assert "new dataset" in result.error


def test_changed_window_refuses_to_continue(tmp_path) -> None:
    fetch = _fetcher({"AUSDT": _page("AUSDT", [(DAY0, 1.0)])})
    collect_venue_klines(
        tmp_path,
        ["AUSDT"],
        start_date=date(2018, 1, 1),
        end_date=date(2018, 1, 10),
        fetcher=fetch,
        clock=lambda: 1_700_000_000.0,
    )
    result = collect_venue_klines(
        tmp_path,
        ["AUSDT"],
        start_date=date(2018, 1, 1),
        end_date=date(2019, 1, 10),
        fetcher=fetch,
        clock=lambda: 1_700_000_000.0,
    )
    assert result.status == "NOT_RUN_JOURNAL_INVALID"
    assert "misreport coverage" in result.error


def test_injected_clock_marks_provenance_test_only_forever(tmp_path) -> None:
    fetch = _fetcher({"AUSDT": _page("AUSDT", [(DAY0, 1.0)])})
    common = dict(start_date=date(2018, 1, 1), end_date=date(2018, 1, 10), fetcher=fetch)
    first = collect_venue_klines(
        tmp_path, ["AUSDT"], clock=lambda: 1_700_000_000.0, **common
    )
    assert first.provenance == "test_only"
    # a later run without an injected clock cannot launder the earlier journal
    second = collect_venue_klines(tmp_path, ["BUSDT"], **common)
    assert second.provenance == "test_only"


def test_live_lease_blocks_a_second_writer(tmp_path) -> None:
    import time

    (tmp_path).mkdir(parents=True, exist_ok=True)
    (tmp_path / "journal.lease").write_text(f"999:{time.time()}", encoding="utf-8")
    with pytest.raises(VenueKlineError, match="lease"):
        collect_venue_klines(
            tmp_path,
            ["AUSDT"],
            start_date=date(2018, 1, 1),
            end_date=date(2018, 1, 10),
            fetcher=_fetcher({"AUSDT": _page("AUSDT", [(DAY0, 1.0)])}),
            clock=lambda: 1_700_000_000.0,
        )


def test_consecutive_failures_abort_rather_than_grinding(tmp_path) -> None:
    def always_down(url: str) -> bytes:
        raise OSError("network down")

    result = collect_venue_klines(
        tmp_path,
        [f"S{i}USDT" for i in range(20)],
        start_date=date(2018, 1, 1),
        end_date=date(2018, 1, 10),
        fetcher=always_down,
        clock=lambda: 1_700_000_000.0,
    )
    assert result.status == "NOT_RUN_NETWORK_BLOCKED"
    assert len(result.gap_symbols) == 5
    assert "network down" in result.error


def test_listed_but_no_bars_is_its_own_outcome(tmp_path) -> None:
    fetch = _fetcher({"QUIETUSDT": _page("QUIETUSDT", [])})
    result = collect_venue_klines(
        tmp_path,
        ["QUIETUSDT"],
        start_date=date(2018, 1, 1),
        end_date=date(2018, 1, 10),
        fetcher=fetch,
        clock=lambda: 1_700_000_000.0,
    )
    assert result.symbols_empty == 1
    assert result.symbols_not_listed == 0
    record = next(
        r for r in read_journal(tmp_path / "journal.jsonl") if r.get("type") == "symbol"
    )
    assert record["outcome"] == OUTCOME_EMPTY
