from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from quant_trade.audit.cli import audit_app


def test_audit_cli_writes_reports(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "audit"
    result = CliRunner().invoke(
        audit_app,
        [
            "run",
            "--config",
            str(repo_root / "configs" / "audit" / "clean.yaml"),
            "--out-dir",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["verdict"] == "PASS"
    assert payload["expected_profit_established"] is False
    assert payload["real_money_authorized"] is False
    assert (output / "audit.json").is_file()
    assert (output / "audit.html").is_file()
