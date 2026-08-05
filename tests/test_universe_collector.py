"""Tests for the point-in-time universe collector: chained journal, lease,
gaps, resume, frozen policy, injected-clock provenance. Fixtures only."""

from __future__ import annotations

import json
from datetime import date

import pytest

import quant_trade.data.universe as universe_module
from quant_trade.data.universe import (
    UniverseCollectorError,
    collect_universe,
    read_journal,
    verify_journal_chain,
)


def _snapshot_bytes(coins: list[tuple[int, str, int, float]]) -> bytes:
    data = [
        {
            "id": coin_id,
            "symbol": symbol,
            "name": symbol.title(),
            "cmcRank": rank,
            "circulatingSupply": 1_000_000.0,
            "quotes": [{"marketCap": mcap, "volume24h": mcap * 0.05}],
        }
        for coin_id, symbol, rank, mcap in coins
    ]
    return json.dumps({"data": data}).encode()


def _fetcher(by_date: dict[str, bytes]):
    def fetch(url: str) -> bytes:
        for day_iso, payload in by_date.items():
            if f"date={day_iso}" in url:
                if "start=1&" in url or url.endswith("start=1"):
                    return payload
                return json.dumps({"data": []}).encode()  # no second page
        raise OSError(f"no fixture for {url}")

    return fetch


_COINS = [(1, "AAA", 1, 5e8), (2, "BBB", 2, 6e7), (3, "CCC", 3, 5e6)]
_THREE_DAYS = {
    "2026-01-01": _snapshot_bytes(_COINS),
    "2026-01-02": _snapshot_bytes(_COINS),
    "2026-01-03": _snapshot_bytes(_COINS[:2]),
}


def _clock():
    state = {"t": 1_760_000_000.0}

    def tick() -> float:
        state["t"] += 30.0
        return state["t"]

    return tick


def test_collect_writes_chained_journal_days_and_receipts(tmp_path):
    result = collect_universe(
        tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        fetcher=_fetcher(_THREE_DAYS),
        clock=_clock(),
    )
    assert result.status == "OK"
    assert result.days_collected == 3
    records = read_journal(tmp_path / "journal.jsonl")
    verify_journal_chain(records)  # must not raise
    assert [r["type"] for r in records] == ["header", "day", "day", "day"]
    assert records[0]["policy_sha256"] == universe_module.UNIVERSE_POLICY_SHA256
    assert (tmp_path / "days" / "2026-01-02.jsonl").exists()
    assert (tmp_path / "receipts.jsonl").exists()
    day3 = [
        json.loads(line)
        for line in (tmp_path / "days" / "2026-01-03.jsonl").read_text().splitlines()
    ]
    assert len(day3) == 2  # the day CCC was not in the snapshot


def test_resume_skips_days_already_collected(tmp_path):
    for _ in range(2):
        result = collect_universe(
            tmp_path,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 3),
            fetcher=_fetcher(_THREE_DAYS),
            clock=_clock(),
        )
    assert result.days_already_done == 3
    assert result.days_collected == 0
    records = read_journal(tmp_path / "journal.jsonl")
    assert len(records) == 4  # header + 3 days, no duplicates from the resume


def test_gap_is_first_class_and_retryable(tmp_path):
    broken = dict(_THREE_DAYS)
    del broken["2026-01-02"]  # fetcher raises OSError for the middle day
    result = collect_universe(
        tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        fetcher=_fetcher(broken),
        clock=_clock(),
    )
    assert result.status == "PARTIAL"
    assert result.gap_dates == ["2026-01-02"]
    records = read_journal(tmp_path / "journal.jsonl")
    gap = next(r for r in records if r["type"] == "gap")
    assert "NOT_RUN_NETWORK_BLOCKED" in gap["error"]
    assert "no fixture for" in gap["error"]  # verbatim error preserved

    # The next run retries the gap date; the gap record stays in history.
    result = collect_universe(
        tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        fetcher=_fetcher(_THREE_DAYS),
        clock=_clock(),
    )
    assert result.status == "OK"
    assert result.days_collected == 1
    records = read_journal(tmp_path / "journal.jsonl")
    types = [r["type"] for r in records]
    assert types.count("gap") == 1 and types.count("day") == 3
    verify_journal_chain(records)


def test_tampered_journal_is_refused(tmp_path):
    collect_universe(
        tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        fetcher=_fetcher(_THREE_DAYS),
        clock=_clock(),
    )
    journal = tmp_path / "journal.jsonl"
    lines = journal.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace('"row_count":3', '"row_count":9999')
    journal.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(UniverseCollectorError, match="chain broken"):
        verify_journal_chain(read_journal(journal))
    result = collect_universe(
        tmp_path,
        start_date=date(2026, 1, 3),
        end_date=date(2026, 1, 3),
        fetcher=_fetcher(_THREE_DAYS),
        clock=_clock(),
    )
    assert result.status == "NOT_RUN_JOURNAL_INVALID"
    assert "chain broken" in result.error


def test_lease_blocks_a_second_writer(tmp_path):
    import time as time_module

    (tmp_path / "journal.lease").write_text(f"123:{time_module.time()}", encoding="utf-8")
    with pytest.raises(UniverseCollectorError, match="lease"):
        collect_universe(
            tmp_path,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 1),
            fetcher=_fetcher(_THREE_DAYS),
            clock=_clock(),
        )


def test_injected_clock_is_test_only_forever(tmp_path):
    result = collect_universe(
        tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
        fetcher=_fetcher(_THREE_DAYS),
        clock=_clock(),
    )
    assert result.provenance == "test_only"
    records = read_journal(tmp_path / "journal.jsonl")
    assert records[0]["clock_source"] == "injected_test"
    # Even a later system-clock resume cannot launder the injected past.
    result = collect_universe(
        tmp_path,
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 2),
        fetcher=_fetcher(_THREE_DAYS),
    )
    assert result.provenance == "test_only"


def test_changed_policy_is_a_new_dataset(tmp_path, monkeypatch):
    collect_universe(
        tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
        fetcher=_fetcher(_THREE_DAYS),
        clock=_clock(),
    )
    monkeypatch.setattr(universe_module, "UNIVERSE_POLICY_SHA256", "deadbeef")
    result = collect_universe(
        tmp_path,
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 2),
        fetcher=_fetcher(_THREE_DAYS),
        clock=_clock(),
    )
    assert result.status == "NOT_RUN_JOURNAL_INVALID"
    assert "new dataset" in result.error


def test_consecutive_failures_abort_the_run(tmp_path):
    def dead_network(url: str) -> bytes:
        raise OSError("egress blackhole")

    result = collect_universe(
        tmp_path,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 10),
        fetcher=dead_network,
        clock=_clock(),
    )
    assert result.status == "NOT_RUN_NETWORK_BLOCKED"
    assert len(result.gap_dates) == 5  # abort threshold, not ten hammer blows
    assert "egress blackhole" in result.error
