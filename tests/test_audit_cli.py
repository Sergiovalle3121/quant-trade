"""``quant-trade audit run`` writes the record, the report and the seal."""

from __future__ import annotations

import json
from pathlib import Path

from audit_fixtures import csv_bytes, positive_drift, trades_frame
from typer.testing import CliRunner

from quant_trade.cli import app
from quant_trade.research.holdout_seal import load_seal

runner = CliRunner()


def _write(tmp_path: Path) -> tuple[Path, Path]:
    equity = tmp_path / "equity.csv"
    trades = tmp_path / "trades.csv"
    equity.write_bytes(csv_bytes(positive_drift(700)))
    trades.write_bytes(csv_bytes(trades_frame(20)))
    return equity, trades


def test_run_writes_json_html_and_seal(tmp_path: Path) -> None:
    equity, trades = _write(tmp_path)
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "audit",
            "run",
            "--equity",
            str(equity),
            "--trades",
            str(trades),
            "--trials",
            "3",
            "--cost-bps",
            "5",
            "--oos-start",
            "2020-06-01",
            "--output-dir",
            str(out),
            "--bootstrap-samples",
            "100",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads((out / "audit.json").read_text(encoding="utf-8"))
    assert payload["verdict"]["overall"] in "ABCD"
    assert payload["declared"]["trials"]["value"] == 3
    html_text = (out / "report.html").read_text(encoding="utf-8")
    assert "VISTA PREVIA" in html_text
    seal = load_seal(out)
    assert seal.seal_id == payload["audit_id"]
    assert "class" in result.output


def test_run_paid_has_no_watermark_and_english(tmp_path: Path) -> None:
    equity, _ = _write(tmp_path)
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "audit",
            "run",
            "--equity",
            str(equity),
            "--output-dir",
            str(out),
            "--paid",
            "--locale",
            "en",
            "--bootstrap-samples",
            "100",
        ],
    )
    assert result.exit_code == 0, result.output
    html_text = (out / "report.html").read_text(encoding="utf-8")
    assert "PREVIEW" not in html_text
    assert "Backtest audit" in html_text
    assert not (out / "holdout_seal.json").exists()


def test_run_refuses_an_unreadable_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("a,b\n1,2\n", encoding="utf-8")
    result = runner.invoke(
        app, ["audit", "run", "--equity", str(bad), "--output-dir", str(tmp_path / "o")]
    )
    assert result.exit_code == 2
    assert "timestamp column" in result.output


def test_run_rejects_bad_locale(tmp_path: Path) -> None:
    equity, _ = _write(tmp_path)
    result = runner.invoke(
        app,
        ["audit", "run", "--equity", str(equity), "--output-dir", str(tmp_path), "--locale", "fr"],
    )
    assert result.exit_code != 0


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["audit", "--help"])
    assert result.exit_code == 0
    for command in ("run", "serve", "purge"):
        assert command in result.output
    root = runner.invoke(app, ["--help"])
    assert "audit" in root.output
