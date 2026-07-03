from pathlib import Path

from typer.testing import CliRunner

from quant_trade.cli import app


def test_security_cli_works_offline(tmp_path: Path) -> None:
    cfg = tmp_path / "secret.yaml"
    scan_file = tmp_path / "safe.txt"
    scan_file.write_text("placeholder only\n", encoding="utf-8")
    cfg.write_text(f"scan_paths:\n  - {scan_file}\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(app, ["security", "scan-secrets", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "secret_scan_status=pass" in result.output
