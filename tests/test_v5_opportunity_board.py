"""Trading scanner, unified opportunity board, and paper allocator (V5-6)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
import yaml

from quant_trade.opportunities.board import (
    allocate_paper_capital,
    build_opportunity_board,
)
from quant_trade.opportunities.trading_scan import (
    load_trading_scan_config,
    scan_trading_opportunities,
)

NOW = "2026-07-24T21:30:00Z"


def _campaign_for(dataset_path: str) -> dict:
    with open("configs/carry/cash_and_carry_synthetic.yaml") as fh:
        cfg = yaml.safe_load(fh)
    cfg["data"] = {"source": "json", "path": dataset_path}
    cfg["signal"] = {"entry_threshold": 0.0, "trailing_window": 3}
    return cfg


def test_v5_scan_reports_missing_datasets_with_backfill_evidence():
    cfg = load_trading_scan_config("configs/opportunities/trading_scan_v5.yaml")
    result = scan_trading_opportunities(cfg, evaluated_at_utc=NOW)
    assert len(result.rows) == 3
    assert {r.status for r in result.rows} == {"NOT_RUN_NO_DATASET"}
    h1 = next(r for r in result.rows if r.hypothesis_id == "H1")
    # the committed backfill attempts log is quoted as verifiable evidence
    assert any("NOT_RUN_NETWORK_BLOCKED" in reason for reason in h1.reasons)
    assert any("403" in reason for reason in h1.reasons)


def test_scan_runs_registered_campaign_when_dataset_exists(tmp_path):
    from quant_trade.carry.data import synthetic_funding_snapshots, write_snapshots_json

    snaps = [
        dataclasses.replace(s, data_source="real", realized_funding_rate=0.001)
        for s in synthetic_funding_snapshots(periods=120, seed=4)
    ]
    dataset = write_snapshots_json(tmp_path / "real.json", snaps)
    cfg = {
        "hypotheses": [
            {
                "id": "HT",
                "name": "test hypothesis",
                "campaign": _campaign_for(str(dataset)),
            }
        ]
    }
    result = scan_trading_opportunities(cfg, evaluated_at_utc=NOW)
    row = result.rows[0]
    assert row.status in ("PAPER_CANDIDATE", "REJECTED")
    assert row.data_source == "real"
    assert row.walk_forward_windows > 0
    assert row.metrics["sharpe_per_period"] is not None


def test_scan_rejects_bad_dataset_without_dying(tmp_path):
    from quant_trade.carry.backfill import run_backfill

    # settlement-only store: no quote observations -> fail-closed rejection
    store = tmp_path / "settlements_only.jsonl"
    run_backfill(
        "bybit", "BTC", store, fixture_path="tests/fixtures/bybit_funding_history.json"
    )
    cfg = {
        "hypotheses": [
            {
                "id": "HB",
                "name": "bad dataset",
                "campaign": {
                    "experiment_name": "bad",
                    "data": {"source": "jsonl_observations", "path": str(store)},
                    "signal": {"entry_threshold": 0.0, "trailing_window": 3},
                },
            }
        ]
    }
    result = scan_trading_opportunities(cfg, evaluated_at_utc=NOW)
    row = result.rows[0]
    assert row.status == "NOT_RUN_DATASET_REJECTED"
    assert "quote" in row.reasons[0]


# --- board + allocator ----------------------------------------------------


def _mining_cells():
    return json.loads(Path("artifacts/v5/MINING_RENTAL_MATRIX.json").read_text())[
        "cells"
    ]


def test_board_with_no_eligible_candidates_crowns_cash():
    cfg = load_trading_scan_config("configs/opportunities/trading_scan_v5.yaml")
    trading = scan_trading_opportunities(cfg, evaluated_at_utc=NOW)
    board = build_opportunity_board(
        trading_rows=[r.to_dict() for r in trading.rows],
        mining_cells=_mining_cells(),
        cash_yield_annual=0.04,
        evaluated_at_utc=NOW,
    )
    assert board["champion"]["entry_id"] == "cash_usd"
    eligible = [e for e in board["entries"] if e["eligible"]]
    assert len(eligible) == 1  # cash only
    # blocked/missing rows are tracked, never ranked
    assert all(e["rank"] is None for e in board["entries"] if not e["eligible"])
    assert board["real_money_authorized"] is False


def test_board_ranks_eligible_candidate_above_cash_and_allocates_capped():
    trading_rows = [
        {
            "hypothesis_id": "H1",
            "status": "PAPER_CANDIDATE",
            "data_source": "real",
            "metrics": {"sharpe_per_period": 0.9},
            "reasons": [],
        },
        {
            "hypothesis_id": "H2",
            "status": "NOT_RUN_NO_DATASET",
            "data_source": "",
            "metrics": {},
            "reasons": ["registered dataset missing"],
        },
    ]
    board = build_opportunity_board(
        trading_rows=trading_rows,
        mining_cells=_mining_cells(),
        cash_yield_annual=0.04,
        evaluated_at_utc=NOW,
    )
    assert board["champion"]["entry_id"] == "trading:H1"
    allocation = allocate_paper_capital(board, 100_000.0)
    by_id = {a["entry_id"]: a for a in allocation["allocations"]}
    assert by_id["trading:H1"]["capital_usd"] == pytest.approx(25_000.0)  # capped
    assert by_id["cash_usd"]["capital_usd"] == pytest.approx(75_000.0)
    assert by_id["trading:H2"]["capital_usd"] == 0.0
    total = sum(a["capital_usd"] for a in allocation["allocations"])
    assert total == pytest.approx(100_000.0)
    assert allocation["paper_only"] is True
    assert allocation["real_money_authorized"] is False


def test_test_only_mining_candidate_is_never_eligible():
    cells = [
        {
            "identity": "aws|us-east-1|g5.xlarge|NVIDIA A10G|sha256|BTC",
            "status": "TEST_ONLY_ECONOMIC_CANDIDATE_PAPER_ONLY",
            "test_only": True,
            "conditional_economics": {"margin_per_hour_usd": 5.0},
            "reasons": [],
        },
        {
            "identity": "aws|us-east-1|g5.xlarge|NVIDIA A10G|sha256|LTC",
            "status": "ECONOMIC_CANDIDATE_PAPER_ONLY",
            "test_only": True,  # even with the plain status, the flag blocks it
            "conditional_economics": {"margin_per_hour_usd": 5.0},
            "reasons": [],
        },
    ]
    board = build_opportunity_board(
        trading_rows=[],
        mining_cells=cells,
        cash_yield_annual=0.04,
        evaluated_at_utc=NOW,
    )
    assert board["champion"]["entry_id"] == "cash_usd"
    assert all(not e["eligible"] for e in board["entries"] if e["kind"] == "mining")


def test_allocation_with_no_candidates_is_all_cash():
    board = build_opportunity_board(
        trading_rows=[],
        mining_cells=[],
        cash_yield_annual=0.04,
        evaluated_at_utc=NOW,
    )
    allocation = allocate_paper_capital(board, 50_000.0)
    assert allocation["allocations"][0]["entry_id"] == "cash_usd"
    assert allocation["allocations"][0]["capital_usd"] == pytest.approx(50_000.0)
    assert allocation["allocations"][0]["fraction"] == pytest.approx(1.0)


def test_cli_scan_rank_allocate_roundtrip(tmp_path):
    from typer.testing import CliRunner

    from quant_trade.cli import app

    runner = CliRunner()
    leaderboard = tmp_path / "TRADING_OPPORTUNITY_LEADERBOARD.json"
    board = tmp_path / "UNIFIED_OPPORTUNITY_BOARD.json"
    allocation = tmp_path / "PAPER_CAPITAL_ALLOCATION.json"

    scan = runner.invoke(
        app,
        [
            "opportunities",
            "scan-trading",
            "--config",
            "configs/opportunities/trading_scan_v5.yaml",
            "--output",
            str(leaderboard),
            "--evaluated-at-utc",
            NOW,
        ],
    )
    assert scan.exit_code == 0, scan.output
    assert "NOT_RUN_NO_DATASET" in scan.output

    ranked = runner.invoke(
        app,
        [
            "opportunities",
            "rank",
            "--trading",
            str(leaderboard),
            "--mining",
            "artifacts/v5/MINING_RENTAL_MATRIX.json",
            "--output",
            str(board),
            "--evaluated-at-utc",
            NOW,
        ],
    )
    assert ranked.exit_code == 0, ranked.output
    assert "Champion: cash_usd" in ranked.output

    allocated = runner.invoke(
        app,
        [
            "opportunities",
            "allocate-paper",
            "--board",
            str(board),
            "--capital",
            "100000",
            "--output",
            str(allocation),
        ],
    )
    assert allocated.exit_code == 0, allocated.output
    payload = json.loads(allocation.read_text())
    assert payload["paper_only"] is True
    cash_line = payload["allocations"][0]
    assert cash_line["entry_id"] == "cash_usd"
    assert cash_line["fraction"] == pytest.approx(1.0)
