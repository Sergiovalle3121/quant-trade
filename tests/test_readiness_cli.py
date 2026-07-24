"""CLI test for drill-evidence paper readiness."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from quant_trade.cli import app
from quant_trade.paper.readiness import REQUIRED_DRILLS, record_drill

runner = CliRunner()
NOW = "2026-07-24T12:00:00Z"


def _write_config(tmp_path, evidence_dir) -> str:
    cfg = tmp_path / "readiness.yaml"
    cfg.write_text(
        "broker_mode: paper\n"
        "broker_endpoint: https://paper-api.alpaca.markets\n"
        "live_trading: false\n"
        "exporter_enabled: true\n"
        "recovery_enabled: true\n"
        "kill_switch_enabled: true\n"
        "orphan_detection_enabled: true\n"
        "heartbeat_interval_seconds: 30\n"
        "reconciliation_enabled: true\n"
        f"drill_evidence_dir: {evidence_dir}\n",
        encoding="utf-8",
    )
    return str(cfg)


def test_readiness_cli_not_ready_without_drills(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    cfg = _write_config(tmp_path, evidence)
    result = runner.invoke(
        app, ["paper", "readiness-evidence", "--config", cfg, "--evaluated-at-utc", NOW]
    )
    assert result.exit_code == 1
    assert "NOT_READY" in result.output
    assert "missing" in result.output


def test_readiness_cli_ready_with_executed_drills(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for name in REQUIRED_DRILLS:
        if name == "parity":
            continue  # executed for real via --run-parity-drill below
        record_drill(
            evidence, name=name, result="pass",
            executed_at_utc="2026-07-20T00:00:00Z",
            failure_injected=name in ("kill_switch", "recovery", "orphan_detection"),
            details={"note": "operator drill"},
        )
    cfg = _write_config(tmp_path, evidence)
    out = tmp_path / "report.json"
    result = runner.invoke(
        app,
        ["paper", "readiness-evidence", "--config", cfg, "--run-parity-drill",
         "--output", str(out), "--evaluated-at-utc", NOW],
    )
    assert result.exit_code == 0, result.output
    assert "READY_FOR_PAPER_TRIAL" in result.output
    assert "parity drill executed" in result.output
    payload = json.loads(out.read_text())
    assert payload["real_money_authorized"] is False
    assert payload["drill_summary"]["parity"] == "ok"
