from pathlib import Path

from quant_trade.security.permissions import check_config_safety


def test_live_endpoint_config_rejected(tmp_path: Path) -> None:
    p = tmp_path / "broker.yaml"
    p.write_text("endpoint: https://api.alpaca.markets\n", encoding="utf-8")
    report = check_config_safety([p])
    assert report.status == "fail"


def test_real_money_approval_rejected(tmp_path: Path) -> None:
    p = tmp_path / "decision.yaml"
    p.write_text("real_money_approved: true\n", encoding="utf-8")
    report = check_config_safety([p])
    assert report.status == "fail"
