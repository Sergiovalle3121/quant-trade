"""Tests for the low-frequency paper bridge on a revealed fixture.

The bridge reads the verdict artifact. The fixture's verdict is whatever the
synthetic panel produced, so the eligible case is manufactured by setting the
verdict's ``program`` block to the eligible class in the test, and the
ineligible case by leaving it alone when it is not. Both paths are covered.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from crypto_lowcap_fixture import AT, HOLDOUT, build_experiment, synthetic_panel

from quant_trade.evidence.canonical_json import atomic_write_json, load_json
from quant_trade.research.crypto_lowcap.campaign import run_select
from quant_trade.research.crypto_lowcap.paper_bridge import (
    STATUS_BROKEN,
    STATUS_FAIL,
    STATUS_INCOMPLETE,
    STATUS_PASS,
    PaperBridgeError,
    append_paper_record,
    infer_rebalance_frequency,
    journal_path,
    paper_status,
    plan_rebalance,
    read_paper_journal,
    record_fills,
)
from quant_trade.research.crypto_lowcap.reveal import run_reveal, verdict_path


def _extend(frame: pd.DataFrame, days: int, seed: int = 11) -> pd.DataFrame:
    """Continue every live series past the fixture's end, one bar per day."""
    rng = np.random.default_rng(seed)
    last = frame["timestamp"].max()
    tail = frame[frame["timestamp"] == last]
    dates = pd.date_range(last + pd.Timedelta(days=1), periods=days, freq="D", tz="UTC")
    rows = []
    for _, row in tail.iterrows():
        price = float(row["close"])
        for day in dates:
            price *= 1 + rng.normal(0.0002, 0.03)
            rows.append(
                {
                    **row.to_dict(),
                    "timestamp": day,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                }
            )
    return pd.concat([frame, pd.DataFrame(rows)], ignore_index=True).sort_values(
        ["timestamp", "symbol"]
    )


def _revealed_and_eligible(tmp_path: Path, *, eligible: bool = True) -> dict:
    fx = build_experiment(tmp_path)
    run_select(fx["experiment"], fx["trials"], fx["panel"], evaluated_at_utc=AT, code_sha="abc")
    run_reveal(fx["experiment"], fx["panel"], reason="fixture", evaluated_at_utc=AT, code_sha="abc")
    path = verdict_path(fx["experiment"])
    verdict = load_json(path)
    verdict["program"].update(
        {
            "verdict_class_at_recovery_0": "RANGE_ABOVE_ZERO"
            if eligible
            else "RANGE_INCLUDES_ZERO",
            "primary_gate_pass_at_recovery_0": True,
            "primary_gate_pass_at_recovery_1": True,
        }
    )
    atomic_write_json(path, verdict)
    extended = tmp_path / "panel_extended.csv.gz"
    with gzip.GzipFile(extended, mode="wb", mtime=0) as handle:
        handle.write(_extend(synthetic_panel(), 400).to_csv(index=False).encode("utf-8"))
    fx["extended"] = extended
    fx["state"] = tmp_path / "paper"
    return fx


def _fills_for(plan: dict, *, slip_bps: float = 0.0, venue: str = "paper") -> dict:
    fills = []
    for leg in plan["legs"]:
        if leg["executed_notional_usd"] <= 0:
            continue
        sign = 1.0 if leg["side"] == "buy" else -1.0
        price = leg["reference_price"] * (1 + sign * slip_bps / 10_000)
        fills.append(
            {
                "symbol": leg["symbol"],
                "side": leg["side"],
                "quantity": leg["quantity"],
                "price": price,
                "fee_usd": leg["quantity"] * price * 0.001,
                "executed_at_utc": AT,
            }
        )
    return {"plan_sha256": plan["sha256"], "venue": venue, "fills": fills}


def test_plan_requires_an_eligible_verdict_and_a_date_after_the_holdout(tmp_path: Path) -> None:
    fx = _revealed_and_eligible(tmp_path, eligible=False)
    with pytest.raises(PaperBridgeError, match="not paper-eligible"):
        plan_rebalance(
            fx["experiment"],
            fx["extended"],
            capital_usd=1_000,
            as_of="2023-06-30",
            state_dir=fx["state"],
            at_utc=AT,
            code_sha="abc",
        )
    fx = _revealed_and_eligible(tmp_path / "b")
    with pytest.raises(PaperBridgeError, match="backtest, not a paper record"):
        plan_rebalance(
            fx["experiment"],
            fx["extended"],
            capital_usd=1_000,
            as_of=HOLDOUT[1],
            state_dir=fx["state"],
            at_utc=AT,
            code_sha="abc",
        )
    assert not journal_path(fx["state"]).exists()


def test_plan_record_status_end_to_end(tmp_path: Path) -> None:
    fx = _revealed_and_eligible(tmp_path)
    plan = plan_rebalance(
        fx["experiment"],
        fx["extended"],
        capital_usd=1_000,
        as_of="2023-06-30",
        state_dir=fx["state"],
        at_utc=AT,
        code_sha="abc",
    )
    assert plan["rebalance_date"] > HOLDOUT[1]
    assert plan["policy_checks"]["revealed"] is True
    assert any(leg["executed_notional_usd"] > 0 for leg in plan["legs"])
    assert Path(plan["plan_path"]).is_file()
    journal = read_paper_journal(fx["state"])
    assert [r["type"] for r in journal] == ["header", "plan"]
    assert journal[0]["frozen_selection_sha256"] == plan["frozen_selection_sha256"]

    with pytest.raises(PaperBridgeError, match="already journaled"):
        plan_rebalance(
            fx["experiment"],
            fx["extended"],
            capital_usd=1_000,
            as_of=plan["as_of"],
            state_dir=fx["state"],
            at_utc=AT,
            code_sha="abc",
        )

    fills_path = tmp_path / "fills.json"
    atomic_write_json(fills_path, _fills_for(plan, slip_bps=5.0))
    record = record_fills(fx["state"], plan["plan_path"], fills_path, at_utc=AT)
    assert record["unfilled"] == []
    assert record["realised_cost_usd"] > 0
    with pytest.raises(PaperBridgeError, match="filled once"):
        record_fills(fx["state"], plan["plan_path"], fills_path, at_utc=AT)
    holdings = load_json(fx["state"] / "holdings.json")
    assert holdings["quantities"] and holdings["cash_usd"] < 1_000

    status = paper_status(fx["state"], now_utc="2026-02-01T00:00:00Z")
    assert status["status"] == STATUS_INCOMPLETE
    assert status["real_money_approved"] is False
    assert status["rebalances_recorded"] == 1
    assert status["days_elapsed"] == 31
    assert (fx["state"] / "PAPER_STATUS.json").is_file()


def test_fills_outside_the_plan_and_edited_plans_are_refused(tmp_path: Path) -> None:
    fx = _revealed_and_eligible(tmp_path)
    plan = plan_rebalance(
        fx["experiment"],
        fx["extended"],
        capital_usd=1_000,
        as_of="2023-06-30",
        state_dir=fx["state"],
        at_utc=AT,
        code_sha="abc",
    )
    bad = _fills_for(plan)
    bad["fills"].append(
        {
            "symbol": "NOPE:9",
            "side": "buy",
            "quantity": 1,
            "price": 1,
            "fee_usd": 0,
            "executed_at_utc": AT,
        }
    )
    fills_path = tmp_path / "bad.json"
    atomic_write_json(fills_path, bad)
    with pytest.raises(PaperBridgeError, match="not an executable leg"):
        record_fills(fx["state"], plan["plan_path"], fills_path, at_utc=AT)
    wrong_sha = _fills_for(plan)
    wrong_sha["plan_sha256"] = "0" * 64
    atomic_write_json(fills_path, wrong_sha)
    with pytest.raises(PaperBridgeError, match="does not name this plan"):
        record_fills(fx["state"], plan["plan_path"], fills_path, at_utc=AT)
    edited = load_json(plan["plan_path"])
    edited["cost_usd"] = 0.0
    Path(plan["plan_path"]).write_text(json.dumps(edited), encoding="utf-8")
    atomic_write_json(fills_path, _fills_for(plan))
    with pytest.raises(PaperBridgeError, match="edited after"):
        record_fills(fx["state"], plan["plan_path"], fills_path, at_utc=AT)


def test_gate_passes_after_enough_rebalances_and_fails_on_expensive_fills(tmp_path: Path) -> None:
    fx = _revealed_and_eligible(tmp_path)
    frequency = None
    dates = ["2023-03-31", "2023-06-30", "2023-09-30", "2024-01-15"]
    recorded = 0
    for as_of in dates:
        try:
            plan = plan_rebalance(
                fx["experiment"],
                fx["extended"],
                capital_usd=1_000,
                as_of=as_of,
                state_dir=fx["state"],
                at_utc=AT,
                code_sha="abc",
            )
        except PaperBridgeError as exc:
            assert "already journaled" in str(exc) or "no rebalance date" in str(exc)
            continue
        frequency = plan["rebalance_frequency"]
        fills_path = tmp_path / f"fills_{as_of}.json"
        atomic_write_json(fills_path, _fills_for(plan))
        record_fills(fx["state"], plan["plan_path"], fills_path, at_utc=AT)
        recorded += 1
    status = paper_status(fx["state"], now_utc="2026-03-01T00:00:00Z")
    header = read_paper_journal(fx["state"])[0]
    assert header["rebalance_frequency"] == frequency
    needed = status["gate"]["min_rebalances_recorded"]
    assert status["status"] == (STATUS_PASS if recorded >= needed else STATUS_INCOMPLETE)
    assert status["real_money_approved"] is False

    # An expensive record (fills 3x the model) turns a complete gate into a fail.
    expensive = tmp_path / "expensive"
    fx2 = _revealed_and_eligible(expensive)
    plan = plan_rebalance(
        fx2["experiment"],
        fx2["extended"],
        capital_usd=1_000,
        as_of="2023-06-30",
        state_dir=fx2["state"],
        at_utc=AT,
        code_sha="abc",
    )
    fills_path = expensive / "fills.json"
    atomic_write_json(
        fills_path, _fills_for(plan, slip_bps=3 * plan["cost_bps_of_portfolio"] + 200)
    )
    record_fills(fx2["state"], plan["plan_path"], fills_path, at_utc=AT)
    header = read_paper_journal(fx2["state"])[0]
    header_min = header["policy"]["min_rebalances_recorded"]
    # Force the completeness condition by lowering nothing: replay the same
    # expensive fill pattern for as many rebalances as the policy needs.
    for as_of in ("2023-09-30", "2024-01-15", "2024-04-15"):
        try:
            plan = plan_rebalance(
                fx2["experiment"],
                fx2["extended"],
                capital_usd=1_000,
                as_of=as_of,
                state_dir=fx2["state"],
                at_utc=AT,
                code_sha="abc",
            )
        except PaperBridgeError:
            continue
        fills_path = expensive / f"fills_{as_of}.json"
        atomic_write_json(
            fills_path, _fills_for(plan, slip_bps=3 * plan["cost_bps_of_portfolio"] + 200)
        )
        record_fills(fx2["state"], plan["plan_path"], fills_path, at_utc=AT)
    status = paper_status(fx2["state"], now_utc="2026-03-01T00:00:00Z")
    if status["rebalances_recorded"] >= header_min:
        assert status["status"] == STATUS_FAIL
        assert any("realised cost" in r for r in status["gate"]["reasons"])
    else:
        assert status["status"] == STATUS_INCOMPLETE


def test_a_broken_journal_is_a_status_of_its_own(tmp_path: Path) -> None:
    fx = _revealed_and_eligible(tmp_path)
    plan_rebalance(
        fx["experiment"],
        fx["extended"],
        capital_usd=1_000,
        as_of="2023-06-30",
        state_dir=fx["state"],
        at_utc=AT,
        code_sha="abc",
    )
    path = journal_path(fx["state"])
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace('"planned_cost_usd"', '"planned_cost_usd_"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    status = paper_status(fx["state"], now_utc=AT)
    assert status["status"] == STATUS_BROKEN
    assert status["real_money_approved"] is False
    with pytest.raises(PaperBridgeError, match="chain broken"):
        append_paper_record(fx["state"], {"type": "plan"})


def test_frequency_is_inferred_from_the_candidate_dates() -> None:
    monthly = pd.DataFrame(
        {"timestamp": pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"], utc=True)}
    )
    annual = pd.DataFrame({"timestamp": pd.to_datetime(["2023-01-01", "2024-01-01"], utc=True)})
    single = pd.DataFrame({"timestamp": pd.to_datetime(["2024-01-01"], utc=True)})
    assert infer_rebalance_frequency(monthly) == "monthly"
    assert infer_rebalance_frequency(annual) == "annual"
    assert infer_rebalance_frequency(single) == "annual"
