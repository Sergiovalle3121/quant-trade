from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from quant_trade.research import prospective_development as development
from quant_trade.research.prospective_crypto import ProspectiveStrategySpec
from quant_trade.research.prospective_development import (
    DevelopmentVerdict,
    evaluate_prospective_development,
)

CONFIG = Path("configs/experiments/binance_btc_eth_tsmom_long_cash_v1.yaml")


def _spec() -> ProspectiveStrategySpec:
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    raw.pop("seal")
    return ProspectiveStrategySpec(**raw)


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return (
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    ).encode("utf-8")


def _write_collection(
    root: Path,
    *,
    first_date: str = "2017-08-01",
    end_date: str = "2019-01-31",
) -> None:
    series = root / "series"
    series.mkdir(parents=True)
    dates = pd.date_range(first_date, end_date, freq="D", tz="UTC")
    symbol_records: list[dict[str, Any]] = []
    for symbol, daily_growth, scale in (
        ("BTCUSDT", 0.0010, 4_000.0),
        ("ETHUSDT", 0.0007, 300.0),
    ):
        rows = []
        for index, timestamp in enumerate(dates):
            close = scale * math.exp(daily_growth * index)
            open_price = close * (1.0 - daily_growth / 2.0)
            rows.append(
                {
                    "date": timestamp.date().isoformat(),
                    "start_ms": int(timestamp.timestamp() * 1_000),
                    "open": open_price,
                    "high": close * 1.01,
                    "low": open_price * 0.99,
                    "close": close,
                    "volume_base": 1_000_000.0,
                    "turnover_quote": close * 1_000_000.0,
                }
            )
        payload = _jsonl(rows)
        (series / f"{symbol}.jsonl").write_bytes(payload)
        symbol_records.append(
            {
                "type": "symbol",
                "symbol": symbol,
                "outcome": "listed",
                "first_date": first_date,
                "last_date": end_date,
                "row_count": len(rows),
                "series_file_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    header = {
        "type": "header",
        "venue": "binance",
        "window": [first_date, end_date],
        "policy": {
            "venue": "binance",
            "market": "spot",
            "interval": "1d",
            "quote_asset": "USDT",
        },
    }
    (root / "journal.jsonl").write_bytes(_jsonl([header, *symbol_records]))


def test_offline_verdict_is_reproducible_non_promotional_and_next_bar(tmp_path: Path) -> None:
    _write_collection(tmp_path)
    spec = _spec()

    first = evaluate_prospective_development(
        tmp_path,
        spec,
        decision_start="2018-08-31",
        end_date="2019-01-31",
    )
    second = evaluate_prospective_development(
        tmp_path,
        spec,
        decision_start="2018-08-31",
        end_date="2019-01-31",
    )

    assert first.to_dict() == second.to_dict()
    assert first.report_sha256() == second.report_sha256()
    assert first.status == "NO_GO"
    assert not first.promotion_authorized
    assert not first.real_money_authorized
    assert set(first.evidence_hashes) == {
        "journal.jsonl",
        "series/BTCUSDT.jsonl",
        "series/ETHUSDT.jsonl",
        "dataset",
        "spec",
    }
    assert first.scenarios["normal"].strategy.same_bar_fill_count == 0
    assert first.scenarios["normal"].strategy.first_fill_date == "2018-09-01"
    assert first.scenarios["normal"].cost_bps_per_side == 15.0
    assert first.scenarios["normal"].fill_fraction == 1.0
    assert first.scenarios["stress_2x_fills_50pct"].cost_bps_per_side == 30.0
    assert first.scenarios["stress_2x_fills_50pct"].fill_fraction == 0.5
    assert set(first.scenarios["normal"].block_outperformance_counts) == {
        "btc_usdt_buy_and_hold",
        "btc_eth_50_50_buy_and_hold",
    }
    assert any(reason.startswith("OUTPERFORMS_") for reason in first.reasons)


@pytest.mark.parametrize("end_date", ["2023-11-29", "2026-08-31"])
def test_end_beyond_sealed_development_is_rejected_before_loading_data(
    monkeypatch: pytest.MonkeyPatch,
    end_date: str,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("development evidence loader must not run")

    monkeypatch.setattr(development, "_load_evidence", forbidden)
    verdict = evaluate_prospective_development(
        "does-not-exist",
        _spec(),
        decision_start="2018-08-31",
        end_date=end_date,
    )

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "END_EXCEEDS_SEALED_DEVELOPMENT_EVIDENCE" in verdict.reasons


def test_start_before_sealed_development_is_rejected_before_loading_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("development evidence loader must not run")

    monkeypatch.setattr(development, "_load_evidence", forbidden)
    verdict = evaluate_prospective_development(
        "does-not-exist",
        _spec(),
        decision_start="2018-08-30",
        end_date="2019-01-31",
    )

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "START_PRECEDES_SEALED_DEVELOPMENT_EVIDENCE" in verdict.reasons


def test_journal_future_envelope_is_rejected_before_series_are_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_collection(tmp_path, end_date="2019-02-28")

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("series parser must not run")

    monkeypatch.setattr(development, "_parse_series", forbidden)
    verdict = evaluate_prospective_development(
        tmp_path,
        _spec(),
        decision_start="2018-08-31",
        end_date="2019-01-31",
    )

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "JOURNAL_WINDOW_ENTERS_UNREQUESTED_FUTURE" in verdict.reasons


def test_series_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    _write_collection(tmp_path)
    with (tmp_path / "series" / "BTCUSDT.jsonl").open("ab") as handle:
        handle.write(b"{}\n")

    verdict = evaluate_prospective_development(
        tmp_path,
        _spec(),
        decision_start="2018-08-31",
        end_date="2019-01-31",
    )

    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert "BTCUSDT_SERIES_DIGEST_MISMATCH" in verdict.reasons
    assert not verdict.scenarios


def test_development_verdict_cannot_be_constructed_as_pass() -> None:
    with pytest.raises(ValueError, match="never be PASS"):
        DevelopmentVerdict(
            status="PASS",  # type: ignore[arg-type]
            strategy_id="binance_btc_eth_tsmom_long_cash_v1",
            decision_start="2018-08-31",
            end_date="2019-01-31",
            evidence_hashes={},
            decision_months=0,
            signal_count=0,
            scenarios={},
            reasons=("forbidden",),
        )


def test_development_authorization_fields_cannot_be_enabled(tmp_path: Path) -> None:
    _write_collection(tmp_path)
    verdict = evaluate_prospective_development(
        tmp_path,
        _spec(),
        decision_start="2018-08-31",
        end_date="2019-01-31",
    )

    with pytest.raises(ValueError, match="cannot authorize"):
        replace(verdict, real_money_authorized=True)
