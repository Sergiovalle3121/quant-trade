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


def test_synthetic_campaign_is_never_go():
    result = run_carry_research(_config())
    assert result.decision == "NOT-RUN"
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
    assert payload["decision"] == "NOT-RUN"
    # a ledger entry was recorded (as discarded, since NOT-RUN)
    report = ledger_integrity_report(tmp_path)
    assert report.valid_records == 1
    assert report.n_discarded == 1


def test_real_labelled_data_can_reach_a_gono_decision(tmp_path):
    # Fabricate a "real"-labelled snapshot file; the verdict must be GO or NO-GO
    # (not NOT-RUN), proving the synthetic guard is provenance-based.
    snaps = synthetic_funding_snapshots(periods=120, seed=1)
    real = [__import__("dataclasses").replace(s, data_source="real") for s in snaps]
    path = write_snapshots_json(tmp_path / "real.json", real)
    config = _config()
    config["data"] = {"source": "json", "path": str(path)}
    result = run_carry_research(config)
    assert result.decision in ("GO", "NO-GO")
    assert result.data_source == "real"
