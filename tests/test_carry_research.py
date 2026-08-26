"""Tests for the cash-and-carry research campaign runner (offline)."""

from __future__ import annotations

import dataclasses

import yaml

from quant_trade.carry import research as research_module
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


def test_self_labelled_real_json_downgrades_to_unverified_legacy(tmp_path):
    # V6-D: a "real" label typed into a JSON file is a CLAIM, not evidence.
    # Without verified ingestion receipts the dataset is unverified_legacy —
    # the full pipeline still runs (metrics, walk-forward, ledger), but the
    # verdict is honest insufficiency, never an economic candidacy.
    snaps = synthetic_funding_snapshots(periods=120, seed=1)
    real = [__import__("dataclasses").replace(s, data_source="real") for s in snaps]
    path = write_snapshots_json(tmp_path / "real.json", real)
    config = _config()
    config["data"] = {"source": "json", "path": str(path)}
    result = run_carry_research(config)
    assert result.decision == "NOT_RUN_INSUFFICIENT_REAL_DATA"
    assert result.data_source == "unverified_legacy"
    assert "downgraded" in result.dataset_manifest["provenance_notes"]
    # the economics still computed end-to-end on the downgraded data
    assert "basis_pnl_total" in result.metrics
    assert result.ledger_summary["reconciled"] is True
    assert "return_on_capital" in result.metrics
    assert "total_return_2x_costs" in result.metrics


def test_sufficient_campaign_without_cscv_cannot_be_candidate(monkeypatch):
    original = research_module._load_snapshots

    def force_verified_manifest(config):
        snapshots, manifest, settlements, signal = original(config)
        return (
            snapshots,
            dataclasses.replace(manifest, data_source="real"),
            settlements,
            signal,
        )

    monkeypatch.setattr(research_module, "_load_snapshots", force_verified_manifest)
    config = _config()
    config["gate"] = {
        "min_funding_events": 1,
        "min_span_days": 0,
        "min_walk_forward_windows": 0,
        "min_probabilistic_sharpe": 0,
    }
    result = run_carry_research(config)
    assert result.decision == "REJECTED"
    assert result.cscv["available"] is False
    assert any("CSCV rank-based PBO unavailable" in reason for reason in result.reasons)
    assert any("trial ledger is not configured" in reason for reason in result.reasons)
    assert result.metrics["deflated_sharpe"] == 0.0


def test_sufficient_campaign_with_missing_configured_ledger_fails_closed(monkeypatch, tmp_path):
    original = research_module._load_snapshots

    def force_verified_manifest(config):
        snapshots, manifest, settlements, signal = original(config)
        return snapshots, dataclasses.replace(manifest, data_source="real"), settlements, signal

    monkeypatch.setattr(research_module, "_load_snapshots", force_verified_manifest)
    config = _config()
    config["trial_registry_path"] = str(tmp_path / "missing-ledger.jsonl")
    config["gate"] = {
        "min_funding_events": 1,
        "min_span_days": 0,
        "min_walk_forward_windows": 0,
        "min_probabilistic_sharpe": 0,
    }
    result = run_carry_research(config)
    assert result.decision == "REJECTED"
    assert any("trial ledger does not exist" in reason for reason in result.reasons)
    assert result.metrics["deflated_sharpe"] == 0.0


def test_carry_builds_cscv_from_preregistered_signal_variants():
    config = _config()
    config["statistics"] = {
        "cscv": {
            "partitions": 4,
            "max_pbo": 1.0,
            "variants": [
                {
                    "id": "primary",
                    "entry_threshold": config["signal"]["entry_threshold"],
                    "trailing_window": config["signal"]["trailing_window"],
                },
                {
                    "id": "higher_threshold",
                    "entry_threshold": 0.0002,
                    "trailing_window": config["signal"]["trailing_window"],
                },
            ],
        }
    }
    result = run_carry_research(config)
    assert result.cscv["available"] is True
    assert result.cscv["method"] == "cscv_rank_based"
    assert result.cscv["parameter_variants"] == 2
    assert result.cscv["combinations"] == 6
