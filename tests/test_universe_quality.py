"""Tests for the universe validator: everything recomputed, nothing trusted."""

from __future__ import annotations

import json
from datetime import date

from quant_trade.data.quality.universe import validate_universe
from quant_trade.data.universe import collect_universe


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
                return json.dumps({"data": []}).encode()
        raise OSError(f"no fixture for {url}")

    return fetch


def _clock():
    state = {"t": 1_760_000_000.0}

    def tick() -> float:
        state["t"] += 30.0
        return state["t"]

    return tick


# A dies at year-end 2023; C is born in 2024 and reuses B's ticker "BBB".
_DAYS = {
    "2023-12-30": _snapshot_bytes([(1, "AAA", 1, 5e8), (2, "BBB", 2, 6e7)]),
    "2023-12-31": _snapshot_bytes([(1, "AAA", 1, 5e8), (2, "BBB", 2, 6e7)]),
    "2024-01-01": _snapshot_bytes([(1, "AAA", 1, 5e8), (3, "BBB", 3, 5e6)]),
    "2024-01-02": _snapshot_bytes([(1, "AAA", 1, 5e8), (3, "BBB", 3, 5e6)]),
}


def _collect(tmp_path):
    return collect_universe(
        tmp_path,
        start_date=date(2023, 12, 30),
        end_date=date(2024, 1, 2),
        fetcher=_fetcher(_DAYS),
        clock=_clock(),
    )


def test_clean_dataset_measures_coverage_churn_death_and_reuse(tmp_path):
    assert _collect(tmp_path).status == "OK"
    report = validate_universe(
        tmp_path,
        requested_start=date(2023, 12, 30),
        requested_end=date(2024, 1, 2),
        death_horizon_days=1,
        inactive_symbols={"BBB"},
    )
    assert report.check("journal_chain").status == "MEASURED"
    coverage = report.check("coverage")
    assert coverage.details["coverage_fraction"] == 1.0
    assert coverage.details["unobserved_days"] == 0
    assert report.check("day_file_integrity").status == "MEASURED"
    churn = report.check("churn")
    assert churn.details["by_year"]["2024"] == {"entered": 1, "exited": 1}
    death = report.check("death_cross_check")
    assert death.status == "MEASURED"
    assert death.details["dead_candidates"] == 1  # coin 2 last seen 2023-12-31
    assert death.details["corroborated_by_symbol"] == 1
    reuse = report.check("ticker_reuse")
    assert reuse.details["finding_count"] == 1  # BBB maps to ids 2 and 3
    # The injected test clock must be visible in the verdict.
    assert any("test-only" in w for w in report.warnings)


def test_missing_external_list_is_not_measured_not_clean(tmp_path):
    _collect(tmp_path)
    report = validate_universe(
        tmp_path,
        requested_start=date(2023, 12, 30),
        requested_end=date(2024, 1, 2),
        death_horizon_days=1,
    )
    death = report.check("death_cross_check")
    assert death.status == "NOT_MEASURED"
    assert death.details["dead_candidates"] == 1
    assert any("NOT_MEASURED" in w for w in report.warnings)


def test_unobserved_days_are_worse_than_gaps(tmp_path):
    _collect(tmp_path)
    report = validate_universe(
        tmp_path,
        requested_start=date(2023, 12, 30),
        requested_end=date(2024, 1, 4),  # two days nobody ever looked at
    )
    coverage = report.check("coverage")
    assert coverage.details["unobserved_days"] == 2
    assert any("UNOBSERVED" in w for w in report.warnings)


def test_tampered_day_file_fails_integrity(tmp_path):
    _collect(tmp_path)
    day_file = tmp_path / "days" / "2024-01-01.jsonl"
    content = day_file.read_text(encoding="utf-8")
    day_file.write_text(content.replace("500000000.0", "999.0"), encoding="utf-8")
    report = validate_universe(
        tmp_path,
        requested_start=date(2023, 12, 30),
        requested_end=date(2024, 1, 2),
    )
    integrity = report.check("day_file_integrity")
    assert integrity.status == "FAILED"
    assert integrity.details["sha256_mismatches"] == ["2024-01-01"]
    assert any("integrity FAILED" in w for w in report.warnings)


def test_zero_exit_churn_raises_the_survivorship_alarm(tmp_path):
    immortal = {
        "2023-12-31": _snapshot_bytes([(1, "AAA", 1, 5e8), (2, "BBB", 2, 6e7)]),
        "2024-01-01": _snapshot_bytes([(1, "AAA", 1, 5e8), (2, "BBB", 2, 6e7)]),
    }
    collect_universe(
        tmp_path,
        start_date=date(2023, 12, 31),
        end_date=date(2024, 1, 1),
        fetcher=_fetcher(immortal),
        clock=_clock(),
    )
    report = validate_universe(
        tmp_path,
        requested_start=date(2023, 12, 31),
        requested_end=date(2024, 1, 1),
    )
    assert any("survivorship alarm" in w for w in report.warnings)
