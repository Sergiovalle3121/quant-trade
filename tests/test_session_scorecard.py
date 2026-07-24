"""Tests for the consolidated session verdict scorecard."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from quant_trade.cli import app
from quant_trade.reporting.session_scorecard import (
    FIXED_STATUSES,
    build_session_scorecard,
    load_promotion_decisions,
    render_markdown,
)

runner = CliRunner()


def test_fixed_statuses_are_non_negotiable():
    sc = build_session_scorecard()
    assert sc.fixed_statuses["REAL_MONEY"] == "NO-GO"
    assert sc.fixed_statuses["MINING_HARDWARE_CONTROL"] == "DISABLED"
    assert sc.fixed_statuses["AWS_RESOURCES_CREATED"] == "FALSE"
    assert FIXED_STATUSES["REAL_MONEY"] == "NO-GO"


def test_promotion_rollup_states():
    none = build_session_scorecard(promotions=[])
    assert any(r.name == "STRATEGY_PROMOTION" and r.status == "NONE-EVALUATED" for r in none.rows)
    rejected = build_session_scorecard(promotions=[{"status": "rejected"}, {"status": "rejected"}])
    assert any(r.name == "STRATEGY_PROMOTION" and r.status == "NO-GO" for r in rejected.rows)
    promoted = build_session_scorecard(
        promotions=[{"status": "paper_candidate"}, {"status": "rejected"}]
    )
    row = next(r for r in promoted.rows if r.name == "STRATEGY_PROMOTION")
    assert row.status == "PAPER-CANDIDATE"
    assert "1/2" in row.detail


def test_load_promotion_decisions(tmp_path):
    (tmp_path / "d1.json").write_text(
        json.dumps({"status": "rejected", "gates": []}), encoding="utf-8"
    )
    (tmp_path / "other.json").write_text(json.dumps({"unrelated": True}), encoding="utf-8")
    decisions = load_promotion_decisions(tmp_path)
    assert len(decisions) == 1
    assert decisions[0]["status"] == "rejected"


def test_render_markdown_has_safety_and_verdicts():
    sc = build_session_scorecard(carry_decision="NOT-RUN", mining_decision="NO-GO")
    md = render_markdown(sc)
    assert "REAL_MONEY: NO-GO" in md
    assert "TRADING_EDGE_CASH_AND_CARRY" in md
    assert "authorizes real money" in md
    assert "never a GO" in md


def test_status_cli_prints_safety_posture(tmp_path):
    out = tmp_path / "scorecard.md"
    result = runner.invoke(
        app,
        ["status", "--carry-decision", "NOT-RUN", "--mining-decision", "NO-GO",
         "--output", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert "REAL_MONEY" in result.output
    assert "NO-GO" in result.output
    assert out.exists()
    assert "Non-negotiable safety posture" in out.read_text()
