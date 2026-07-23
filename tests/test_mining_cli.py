Exit code: 0
Wall time: 0.8 seconds
Output:
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

