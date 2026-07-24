"""Reproducible promotion: clean-room rebuild, byte comparison, tamper rejection."""

from __future__ import annotations

import dataclasses
import json

import pytest
import yaml

from quant_trade.carry.data import synthetic_funding_snapshots, write_snapshots_json
from quant_trade.carry.promote import reproduce_campaign
from quant_trade.carry.research import run_carry_research, write_carry_artifacts


@pytest.fixture()
def campaign(tmp_path):
    """A real-labelled campaign with claimed artifacts on disk."""
    snaps = [
        dataclasses.replace(s, data_source="real", realized_funding_rate=0.001)
        for s in synthetic_funding_snapshots(periods=120, seed=4)
    ]
    dataset = write_snapshots_json(tmp_path / "real.json", snaps)
    with open("configs/carry/cash_and_carry_synthetic.yaml") as fh:
        cfg = yaml.safe_load(fh)
    cfg["data"] = {"source": "json", "path": str(dataset)}
    cfg["signal"] = {"entry_threshold": 0.0, "trailing_window": 3}
    claimed = tmp_path / "claimed"
    result = run_carry_research(cfg)
    write_carry_artifacts(claimed, cfg, result)
    return cfg, claimed, dataset


def test_clean_room_rebuild_reproduces_byte_for_byte(campaign, tmp_path):
    cfg, claimed, _ = campaign
    report = reproduce_campaign(cfg, claimed, rebuild_dir=tmp_path / "rebuild")
    assert report.reproduced is True
    assert report.mismatched_artifacts == []
    for hashes in report.artifact_hashes.values():
        assert hashes["claimed"] == hashes["rebuilt"] != ""
    # reproduction feeds the artifact-recomputing review; it never mints money
    assert report.real_money_authorized is False
    assert report.status in ("PAPER_CANDIDATE", "REJECTED")


def test_tampered_results_are_not_reproducible(campaign, tmp_path):
    cfg, claimed, _ = campaign
    results = claimed / "results.json"
    payload = json.loads(results.read_text())
    payload["test_metrics"]["total_return"] = payload["test_metrics"]["total_return"] + 0.01
    results.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    report = reproduce_campaign(cfg, claimed, rebuild_dir=tmp_path / "rebuild")
    assert report.status == "REJECTED_NOT_REPRODUCIBLE"
    assert report.reproduced is False
    assert "results.json" in report.mismatched_artifacts


def test_tampered_dataset_is_rejected_before_rebuild(campaign, tmp_path):
    cfg, claimed, dataset = campaign
    original = dataset.read_text()
    dataset.write_text(original.replace("0.001", "0.002", 1))
    report = reproduce_campaign(cfg, claimed, rebuild_dir=tmp_path / "rebuild")
    assert report.status == "REJECTED_DATASET_TAMPERED"
    assert report.reproduced is False


def test_missing_claim_is_rejected(tmp_path):
    with open("configs/carry/cash_and_carry_synthetic.yaml") as fh:
        cfg = yaml.safe_load(fh)
    report = reproduce_campaign(cfg, tmp_path / "nowhere")
    assert report.status == "REJECTED_MISSING_EVIDENCE"
    assert "missing" in report.error


def test_wrong_config_cannot_reproduce_the_claim(campaign, tmp_path):
    cfg, claimed, _ = campaign
    other = dict(cfg)
    other["signal"] = {"entry_threshold": 0.5, "trailing_window": 5}
    report = reproduce_campaign(other, claimed, rebuild_dir=tmp_path / "rebuild")
    assert report.status == "REJECTED_NOT_REPRODUCIBLE"


def test_cli_promote_roundtrip(campaign, tmp_path):
    from typer.testing import CliRunner

    from quant_trade.cli import app

    cfg, claimed, _ = campaign
    config_path = tmp_path / "campaign.yaml"
    config_path.write_text(yaml.safe_dump(cfg))
    report_path = tmp_path / "promotion_report.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "carry",
            "promote",
            "--config",
            str(config_path),
            "--claimed",
            str(claimed),
            "--rebuild-dir",
            str(tmp_path / "rebuild"),
            "--report",
            str(report_path),
        ],
    )
    assert "reproduced byte-for-byte: True" in result.output
    assert report_path.exists()
    payload = json.loads(report_path.read_text())
    assert payload["reproduced"] is True
    assert payload["real_money_authorized"] is False
    # exit 0 only on full PAPER_CANDIDATE; anything else is non-zero
    assert (result.exit_code == 0) == (payload["status"] == "PAPER_CANDIDATE")
