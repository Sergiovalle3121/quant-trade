"""Tests for the cash-and-carry research campaign runner (offline)."""

from __future__ import annotations

import yaml

from quant_trade.carry.data import synthetic_funding_snapshots, write_snapshots_json
from quant_trade.carry.models import CarryCostModel
from quant_trade.carry.research import (
    carry_campaign_returns,
    run_carry_research,
    write_carry_artifacts,
)
from quant_trade.research.ledger import ledger_integrity_report


def _config():
    return yaml.safe_load(open("configs/carry/cash_and_carry_synthetic.yaml"))


def test_campaign_returns_are_causal_warmup_is_flat():
    snaps = synthetic_funding_snapshots(periods=40, seed=2)
    df = carry_campaign_returns(snaps, CarryCostModel(), entry_threshold=0.0, trailing_window=6)
    # during the warm-up window the position is flat
    assert (df["position"].iloc[:6] == 0.0).all()
    assert len(df) == 40


def test_synthetic_campaign_can_never_advance():
    result = run_carry_research(_config())
    assert result.decision == "NOT_RUN_INSUFFICIENT_REAL_DATA"
    assert result.data_source == "synthetic"
    assert any("real" in r.lower() for r in result.reasons)


def test_synthetic_campaign_still_produces_full_evidence(tmp_path):
    result = run_carry_research(_config())
    assert "sharpe_per_period" in result.metrics
    assert result.bootstrap["available"] in (True, False)
    assert isinstance(result.walk_forward, list)
    out = write_carry_artifacts(tmp_path, _config(), result)
    assert out.exists()
    payload = yaml.safe_load(out.read_text())
    assert payload["decision"] == "NOT_RUN_INSUFFICIENT_REAL_DATA"
    # a ledger entry was recorded (as discarded, since NOT_RUN)
    report = ledger_integrity_report(tmp_path)
    assert report.valid_records == 1
    assert report.n_discarded == 1


def test_real_labelled_sufficient_data_reaches_an_economic_verdict(tmp_path):
    # A "real"-labelled snapshot file with sufficient history must reach an
    # ECONOMIC verdict (REJECTED or PAPER_CANDIDATE) — never the insufficiency
    # outcome, proving the sufficiency guard is data-based, and never a bare GO.
    snaps = synthetic_funding_snapshots(periods=120, seed=1)
    real = [__import__("dataclasses").replace(s, data_source="real") for s in snaps]
    path = write_snapshots_json(tmp_path / "real.json", real)
    config = _config()
    config["data"] = {"source": "json", "path": str(path)}
    result = run_carry_research(config)
    assert result.decision in ("REJECTED", "PAPER_CANDIDATE")
    assert result.data_source == "real"
    # the economics now include the basis and capital views
    assert "basis_pnl_total" in result.metrics
    assert "return_on_capital" in result.metrics
    assert "total_return_2x_costs" in result.metrics
