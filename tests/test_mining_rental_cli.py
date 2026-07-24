"""Tests for mining rental-evaluate and the V1 legacy deprecation."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from quant_trade.mining.cli import mining_app

runner = CliRunner()

AWS_HW = "configs/cloud_rental/aws_hashing_worker.example.yaml"


def _market_yaml(tmp_path, *, captured="2024-05-01T00:00:00Z", direct=None) -> str:
    direct_line = (
        f"  direct_hashprice_usd_per_th_day: {direct}\n" if direct is not None else ""
    )
    path = tmp_path / "market.yaml"
    path.write_text(
        "rig:\n"
        "  name: probe\n"
        "  algorithm: sha256\n"
        "  hashrate_hs: 200000000000000\n"
        "  power_watts: 3500.0\n"
        "market:\n"
        "  coin: BTC\n"
        "  algorithm: sha256\n"
        "  coin_price_usd: 60000.0\n"
        "  network_hashrate_hs: 600000000000000000000\n"
        "  difficulty: 80000000000000\n"
        "  block_subsidy_coin: 3.125\n"
        "  tx_fee_revenue_coin_per_block: 0.15\n"
        "  blocks_per_day: 144.0\n"
        f"  captured_at_utc: \"{captured}\"\n"
        "  source_name: test_fixture\n"
        "  max_age_seconds: 3600\n"
        f"{direct_line}"
        "assumptions:\n"
        "  horizon_days: 30\n",
        encoding="utf-8",
    )
    return str(path)


def test_rental_evaluate_blocked_pending_approval(tmp_path):
    market = _market_yaml(tmp_path)
    out = tmp_path / "decision.json"
    result = runner.invoke(
        mining_app,
        ["rental-evaluate", "--rental-config", AWS_HW, "--market-config", market,
         "--output", str(out), "--evaluated-at-utc", "2024-05-01T00:30:00Z"],
    )
    assert result.exit_code == 1
    assert "BLOCKED_PENDING_WRITTEN_APPROVAL" in result.output
    assert "generic_cloud_compute" in result.output
    payload = json.loads(out.read_text())
    assert payload["deployment_model"] == "generic_cloud_compute"
    assert payload["safety"]["miner_execution"] is False


def test_rental_evaluate_rejects_stale_market(tmp_path):
    market = _market_yaml(tmp_path, captured="2024-05-01T00:00:00Z")
    result = runner.invoke(
        mining_app,
        ["rental-evaluate", "--rental-config", AWS_HW, "--market-config", market,
         "--evaluated-at-utc", "2024-05-02T00:00:00Z"],  # a day later, max age 1h
    )
    assert result.exit_code == 1
    assert "stale" in result.output


def test_rental_evaluate_fails_closed_on_hashprice_divergence(tmp_path):
    market = _market_yaml(tmp_path, direct=0.10)  # bottom-up ~0.047 → huge divergence
    result = runner.invoke(
        mining_app,
        ["rental-evaluate", "--rental-config", AWS_HW, "--market-config", market,
         "--evaluated-at-utc", "2024-05-01T00:30:00Z"],
    )
    assert result.exit_code == 1
    assert "ALERT" in result.output
    assert "failing closed" in result.output


def test_v1_evaluate_is_marked_legacy_non_promotable(tmp_path):
    out = tmp_path / "report.json"
    result = runner.invoke(
        mining_app,
        ["evaluate", "--config", "configs/mining/s21_xp_dated_example.yaml",
         "--output", str(out), "--as-of-utc", "2026-02-06T00:00:00Z"],
    )
    assert result.exit_code == 0, result.output
    assert "legacy_non_promotable=true" in result.output
    payload = json.loads(out.read_text())
    assert payload["legacy_non_promotable"] is True
    assert payload["promotable_engine"] == "mining project"
