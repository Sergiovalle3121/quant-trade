import json

import typer
from typer.testing import CliRunner

from quant_trade.mining.cli import mining_app


def test_mining_evaluate_cli_is_offline_and_does_not_start_resources(tmp_path):
    app = typer.Typer()
    app.add_typer(mining_app, name="mining")
    config = tmp_path / "mining.yaml"
    report = tmp_path / "report.json"
    config.write_text(
        """
rigs:
  - name: aws-test
    algorithm: sha256
    hashrate_hs: 1000000
    power_watts: 1000
    infrastructure_hourly_cost_usd: 2
    electricity_included: true
    temperature_c: 65
markets:
  - coin: TEST
    algorithm: sha256
    coin_price_usd: 100
    network_hashrate_hs: 1000000000
    block_reward_coin: 1
    blocks_per_day: 100
policy:
  electricity_usd_per_kwh: 0
  min_daily_profit_usd: 1
  max_temperature_c: 80
""",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app, ["mining", "evaluate", "--config", str(config), "--output", str(report)]
    )
    assert result.exit_code == 0
    assert "NO-GO" in result.output
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["authorized_to_start_miner"] is False
    assert payload["cloud_resources_created"] is False
    assert any("source" in reason for reason in payload["evaluations"][0]["reasons"])


def test_break_even_and_stress_commands_remain_offline(tmp_path):
    app = typer.Typer()
    app.add_typer(mining_app, name="mining")
    config = tmp_path / "mining.yaml"
    config.write_text(
        """
rigs:
  - name: owned-test
    algorithm: sha256
    hashrate_hs: 1000000
    power_watts: 1000
    hardware_cost_usd: 1000
    temperature_c: 65
    pue: 1.15
    stale_reject_rate: 0.02
markets:
  - coin: TEST
    algorithm: sha256
    coin_price_usd: 100
    network_hashrate_hs: 1000000000
    block_reward_coin: 1
    blocks_per_day: 100
    source: unit-test-snapshot
    captured_at_utc: "2026-07-23T00:00:00Z"
policy:
  electricity_usd_per_kwh: 0.10
  min_daily_profit_usd: 1
  max_temperature_c: 80
""",
        encoding="utf-8",
    )
    break_even_report = tmp_path / "break-even.json"
    break_even = CliRunner().invoke(
        app,
        [
            "mining",
            "break-even",
            "--config",
            str(config),
            "--output",
            str(break_even_report),
            "--as-of-utc",
            "2026-07-23T01:00:00Z",
        ],
    )
    assert break_even.exit_code == 0
    break_even_payload = json.loads(break_even_report.read_text(encoding="utf-8"))
    assert break_even_payload["break_even"][0]["break_even_coin_price_usd"] > 0
    assert len(break_even_payload["break_even"][0]["market_snapshot_sha256"]) == 64
    assert break_even_payload["authorized_to_start_miner"] is False

    stress_report = tmp_path / "stress.json"
    stress = CliRunner().invoke(
        app,
        [
            "mining",
            "stress",
            "--config",
            str(config),
            "--output",
            str(stress_report),
            "--as-of-utc",
            "2026-07-23T01:00:00Z",
        ],
    )
    assert stress.exit_code == 0
    stress_payload = json.loads(stress_report.read_text(encoding="utf-8"))
    assert len(stress_payload["scenarios"]) == 9
    assert stress_payload["no_go_count"] > 0
    assert stress_payload["cloud_resources_created"] is False
