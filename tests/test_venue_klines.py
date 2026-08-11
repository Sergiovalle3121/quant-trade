"""Tests for the venue-kline collector across Bybit and Binance: unlisted
symbols are a journaled outcome, delisted history survives, venues may disagree
about a death date, chained journal, lease, resume, frozen policy and window,
injected-clock provenance. Fixtures only."""

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
    VENUE_BINANCE,
    VENUE_BYBIT,
    VENUE_POLICY_SHA256,
    HttpResponse,
    SymbolNotListed,
    VenueKlineError,
    collect_venue_klines,
    parse_kline_page,
)

DAY0 = 1_514_764_800_000  # 2018-01-01T00:00:00Z


def _bybit_page(symbol: str, bars: list[tuple[int, float]]) -> HttpResponse:
    return HttpResponse(
        200,
        json.dumps(
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
        ).encode(),
    )


def _binance_page(bars: list[tuple[int, float]]) -> HttpResponse:
    return HttpResponse(
        200,
        json.dumps(
            [
                [
                    ms, str(px), str(px * 1.1), str(px * 0.9), str(px), "10",
                    ms + MS_PER_DAY - 1, "100", 5, "5", "50", "0",
                ]
                for ms, px in bars  # binance pages arrive oldest-first
            ]
        ).encode(),
    )


def _bybit_unlisted() -> HttpResponse:
    return HttpResponse(
        200, json.dumps({"retCode": 10001, "retMsg": "Not supported symbols"}).encode()
    )


def _binance_unlisted() -> HttpResponse:
    return HttpResponse(400, json.dumps({"code": -1121, "msg": "Invalid symbol."}).encode())


def _fetcher(pages: dict[str, HttpResponse]):
    def fetch(url: str) -> HttpResponse:
        for symbol, payload in pages.items():
            if f"symbol={symbol}&" in url:
                return payload
        raise OSError(f"no fixture for {url}")

    return fetch


def _collect(tmp_path, symbols, pages, *, venue=VENUE_BYBIT, start=None, end=None, **kw):
    return collect_venue_klines(
        tmp_path,
        symbols,
        venue=venue,
        start_date=start or date(2018, 1, 1),
        end_date=end or date(2018, 1, 10),
        fetcher=_fetcher(pages) if isinstance(pages, dict) else pages,
        clock=lambda: 1_700_000_000.0,
        **kw,
    )


# --- parsing ------------------------------------------------------------


def test_bybit_parse_rejects_relabelled_klines() -> None:
    with pytest.raises(ValueError, match="identity mismatch"):
        parse_kline_page(
            _bybit_page("ETHUSDT", [(DAY0, 1.0)]), symbol="BTCUSDT", venue=VENUE_BYBIT
        )


@pytest.mark.parametrize(
    ("venue", "response"),
    [(VENUE_BYBIT, _bybit_unlisted()), (VENUE_BINANCE, _binance_unlisted())],
)
def test_unlisted_is_raised_distinctly_on_every_venue(venue, response) -> None:
    with pytest.raises(SymbolNotListed):
        parse_kline_page(response, symbol="GHOSTUSDT", venue=venue)


def test_binance_http_error_that_is_not_unlisted_is_a_parse_error() -> None:
    response = HttpResponse(418, b'{"code":-1003,"msg":"Too many requests."}')
    with pytest.raises(ValueError, match="binance http 418"):
        parse_kline_page(response, symbol="AUSDT", venue=VENUE_BINANCE)


def test_both_venues_normalize_to_the_same_fields() -> None:
    bybit = parse_kline_page(
        _bybit_page("AUSDT", [(DAY0, 2.0)]), symbol="AUSDT", venue=VENUE_BYBIT
    )
    binance = parse_kline_page(
        _binance_page([(DAY0, 2.0)]), symbol="AUSDT", venue=VENUE_BINANCE
    )
    assert bybit == binance  # identical rows despite opposite wire formats


def test_parse_rejects_non_positive_prices() -> None:
    bad = HttpResponse(
        200,
        json.dumps(
            {
                "retCode": 0,
                "result": {"symbol": "X", "list": [[str(DAY0), "0", "1", "1", "1", "1", "1"]]},
            }
        ).encode(),
    )
    with pytest.raises(ValueError, match="non-positive"):
        parse_kline_page(bad, symbol="X", venue=VENUE_BYBIT)


def test_unknown_venue_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown venue"):
        parse_kline_page(_binance_page([]), symbol="X", venue="kraken")


# --- survivorship on the venue leg --------------------------------------


@pytest.mark.parametrize(
    ("venue", "listed", "unlisted"),
    [
        (VENUE_BYBIT, _bybit_page("AUSDT", [(DAY0, 1.0)]), _bybit_unlisted()),
        (VENUE_BINANCE, _binance_page([(DAY0, 1.0)]), _binance_unlisted()),
    ],
)
def test_unlisted_symbol_is_a_journaled_outcome_not_a_skip(
    tmp_path, venue, listed, unlisted
) -> None:
    result = _collect(
        tmp_path,
        ["AUSDT", "GHOSTUSDT"],
        {"AUSDT": listed, "GHOSTUSDT": unlisted},
        venue=venue,
    )
    assert result.symbols_listed == 1
    assert result.symbols_not_listed == 1
    outcomes = {
        r["symbol"]: r["outcome"]
        for r in read_journal(tmp_path / "journal.jsonl")
        if r.get("type") == "symbol"
    }
    assert outcomes == {"AUSDT": OUTCOME_LISTED, "GHOSTUSDT": OUTCOME_NOT_LISTED}
    # the absent coin leaves a record, so a later reader can tell "venue never
    # listed it" from "we never asked"
    assert not (tmp_path / "series" / "GHOSTUSDT.jsonl").exists()


def test_delisted_symbol_keeps_its_history_and_death_date(tmp_path) -> None:
    bars = [(DAY0 + i * MS_PER_DAY, 1.0 + i) for i in range(3)]
    _collect(
        tmp_path,
        ["DEADUSDT"],
        {"DEADUSDT": _bybit_page("DEADUSDT", bars)},
        end=date(2020, 1, 1),
    )
    record = next(
        r for r in read_journal(tmp_path / "journal.jsonl") if r.get("type") == "symbol"
    )
    assert record["first_date"] == "2018-01-01"
    assert record["last_date"] == "2018-01-03"  # the series stops: that is the death
    series = (tmp_path / "series" / "DEADUSDT.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in series.splitlines()]
    assert [r["date"] for r in rows] == ["2018-01-01", "2018-01-02", "2018-01-03"]


def test_venues_may_disagree_about_a_death_date(tmp_path) -> None:
    """One venue delisting is not the coin dying, and the panel must show both."""
    short = [(DAY0 + i * MS_PER_DAY, 1.0) for i in range(2)]
    long = [(DAY0 + i * MS_PER_DAY, 1.0) for i in range(5)]
    binance_dir, bybit_dir = tmp_path / "binance", tmp_path / "bybit"
    _collect(binance_dir, ["XUSDT"], {"XUSDT": _binance_page(short)}, venue=VENUE_BINANCE)
    _collect(bybit_dir, ["XUSDT"], {"XUSDT": _bybit_page("XUSDT", long)}, venue=VENUE_BYBIT)

    def last(directory):
        record = next(
            r for r in read_journal(directory / "journal.jsonl") if r.get("type") == "symbol"
        )
        return record["last_date"]

    assert last(binance_dir) == "2018-01-02"
    assert last(bybit_dir) == "2018-01-05"


def test_listed_but_no_bars_is_its_own_outcome(tmp_path) -> None:
    result = _collect(tmp_path, ["QUIETUSDT"], {"QUIETUSDT": _bybit_page("QUIETUSDT", [])})
    assert result.symbols_empty == 1
    assert result.symbols_not_listed == 0
    record = next(
        r for r in read_journal(tmp_path / "journal.jsonl") if r.get("type") == "symbol"
    )
    assert record["outcome"] == OUTCOME_EMPTY


def test_bars_past_the_window_end_are_not_written(tmp_path) -> None:
    bars = [(DAY0 + i * MS_PER_DAY, 1.0) for i in range(10)]
    _collect(tmp_path, ["AUSDT"], {"AUSDT": _bybit_page("AUSDT", bars)}, end=date(2018, 1, 5))
    series = (tmp_path / "series" / "AUSDT.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in series.splitlines()]
    assert rows[-1]["date"] == "2018-01-05"


# --- journal integrity ---------------------------------------------------


def _collect_two_symbols(tmp_path):
    return _collect(
        tmp_path,
        ["AUSDT", "BUSDT"],
        {
            "AUSDT": _bybit_page("AUSDT", [(DAY0, 1.0)]),
            "BUSDT": _bybit_page("BUSDT", [(DAY0, 2.0)]),
        },
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
    it: the journal claims ``series_file_sha256`` and the bytes can be
    re-hashed, so tampering with the payload is caught even when tampering
    with the tail record is not. Asserting the limitation keeps it from being
    quietly assumed away.
    """
    from quant_trade.evidence.canonical_json import sha256_of_bytes

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
    series = (tmp_path / "series" / f"{tail['symbol']}.jsonl").read_bytes()
    assert sha256_of_bytes(series) == tail["series_file_sha256"]
    assert len(series.decode().strip().splitlines()) != tail["row_count"]


def test_resume_skips_terminal_symbols_and_retries_gaps(tmp_path) -> None:
    calls = {"n": 0}

    def flaky(url: str) -> HttpResponse:
        if "symbol=BUSDT&" in url:
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("transient")
            return _bybit_page("BUSDT", [(DAY0, 2.0)])
        return _bybit_page("AUSDT", [(DAY0, 1.0)])

    first = _collect(tmp_path, ["AUSDT", "BUSDT"], flaky)
    assert first.status == "PARTIAL"
    assert first.gap_symbols == ["BUSDT"]

    second = _collect(tmp_path, ["AUSDT", "BUSDT"], flaky)
    assert second.symbols_already_done == 1  # AUSDT terminal, BUSDT retried
    assert second.symbols_listed == 1
    gaps = [r for r in read_journal(tmp_path / "journal.jsonl") if r.get("type") == "gap"]
    assert len(gaps) == 1  # the failure record survives the successful retry
    assert "transient" in gaps[0]["error"]


def test_a_second_venue_refuses_to_continue_the_first_venues_journal(tmp_path) -> None:
    _collect(tmp_path, ["AUSDT"], {"AUSDT": _bybit_page("AUSDT", [(DAY0, 1.0)])})
    result = _collect(
        tmp_path, ["AUSDT"], {"AUSDT": _binance_page([(DAY0, 1.0)])}, venue=VENUE_BINANCE
    )
    assert result.status == "NOT_RUN_JOURNAL_INVALID"
    assert "new dataset" in result.error
    assert VENUE_POLICY_SHA256[VENUE_BYBIT] != VENUE_POLICY_SHA256[VENUE_BINANCE]


def test_changed_window_refuses_to_continue(tmp_path) -> None:
    pages = {"AUSDT": _bybit_page("AUSDT", [(DAY0, 1.0)])}
    _collect(tmp_path, ["AUSDT"], pages)
    result = _collect(tmp_path, ["AUSDT"], pages, end=date(2019, 1, 10))
    assert result.status == "NOT_RUN_JOURNAL_INVALID"
    assert "misreport coverage" in result.error


def test_injected_clock_marks_provenance_test_only_forever(tmp_path) -> None:
    pages = {"AUSDT": _bybit_page("AUSDT", [(DAY0, 1.0)])}
    first = _collect(tmp_path, ["AUSDT"], pages)
    assert first.provenance == "test_only"
    # a later run without an injected clock cannot launder the earlier journal
    second = collect_venue_klines(
        tmp_path,
        ["BUSDT"],
        venue=VENUE_BYBIT,
        start_date=date(2018, 1, 1),
        end_date=date(2018, 1, 10),
        fetcher=_fetcher({"BUSDT": _bybit_page("BUSDT", [(DAY0, 1.0)])}),
    )
    assert second.provenance == "test_only"


def test_live_lease_blocks_a_second_writer(tmp_path) -> None:
    import time

    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "journal.lease").write_text(f"999:{time.time()}", encoding="utf-8")
    with pytest.raises(VenueKlineError, match="lease"):
        _collect(tmp_path, ["AUSDT"], {"AUSDT": _bybit_page("AUSDT", [(DAY0, 1.0)])})


def test_consecutive_failures_abort_rather_than_grinding(tmp_path) -> None:
    def always_down(url: str) -> HttpResponse:
        raise OSError("network down")

    result = _collect(tmp_path, [f"S{i}USDT" for i in range(20)], always_down)
    assert result.status == "NOT_RUN_NETWORK_BLOCKED"
    assert len(result.gap_symbols) == 5
    assert "network down" in result.error


def test_receipt_records_the_real_http_status(tmp_path) -> None:
    _collect(
        tmp_path,
        ["GHOSTUSDT"],
        {"GHOSTUSDT": _binance_unlisted()},
        venue=VENUE_BINANCE,
    )
    receipts = [
        json.loads(line)
        for line in (tmp_path / "receipts.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # the 400 body is archived too: it is the evidence that the venue answered
    assert receipts and receipts[0]["http_status"] == 400
    # and the exclusion it justifies points back at those bytes
    record = next(
        r for r in read_journal(tmp_path / "journal.jsonl") if r.get("type") == "symbol"
    )
    assert record["outcome"] == OUTCOME_NOT_LISTED
    assert record["raw_sha256s"] == [receipts[0]["raw_sha256"]]
    assert (tmp_path / "raw" / f"{receipts[0]['raw_sha256']}.json").exists()
