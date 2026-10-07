"""Private worker CLI summaries retain pause explanations without changing state."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from typer.testing import CliRunner

from quant_trade.personal_paper.cli import app


@pytest.mark.parametrize("upstream_approval", [False, True])
def test_worker_summary_keeps_each_pause_reason_warning_and_existing_fields(
    monkeypatch, upstream_approval: bool
) -> None:
    payload = {
        "status": "PAUSED",
        "manifest": {"last_checked_at": "2026-10-05T15:00:00Z", "closed_sessions": 4},
        "worker": {"quotes": "WAITING", "budget": {"status": "UNOBSERVED"}},
        "books": {
            "cost_paused": {
                "paused": True,
                "pause_reason": "observed monthly budget exceeded",
                "drawdown": 0.01,
            },
            "risk_paused": {
                "paused": True,
                "pause_reason": "daily_loss_limit",
                "drawdown": 0.02,
            },
            "active": {"paused": False, "pause_reason": None, "drawdown": 0.001},
        },
        "warning": "Simulated observations only. Completion does not establish an economic edge.",
        "real_money_approved": upstream_approval,
    }
    original = deepcopy(payload)
    monkeypatch.setattr("quant_trade.personal_paper.worker.run_once", lambda *a, **kw: payload)
    result = CliRunner().invoke(
        app,
        ["worker", "--config", "fixture.yaml", "--database", "fixture.sqlite", "--cache", "cache"],
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary == {
        "checked_at": "2026-10-05T15:00:00Z",
        "status": "PAUSED",
        "closed_sessions": 4,
        "quotes": "WAITING",
        "budget": {"status": "UNOBSERVED"},
        "paused_books": ["cost_paused", "risk_paused"],
        "pause_reasons": {
            "cost_paused": "observed monthly budget exceeded",
            "risk_paused": "daily_loss_limit",
        },
        "max_drawdown": 0.02,
        "warning": payload["warning"],
        "real_money_approved": False,
    }
    assert payload == original


def test_budget_pause_without_manifest_remains_legible_and_unchanged(monkeypatch) -> None:
    payload = {
        "status": "BUDGET_PAUSED",
        "budget": {"status": "OVER_BUDGET", "observed_mxn": 501},
        "real_money_approved": False,
    }
    original = deepcopy(payload)
    monkeypatch.setattr("quant_trade.personal_paper.worker.run_once", lambda *a, **kw: payload)
    result = CliRunner().invoke(
        app,
        ["worker", "--config", "fixture.yaml", "--database", "fixture.sqlite", "--cache", "cache"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == payload
    assert payload == original
