"""V4 defect reproduction: these tests specify behaviour the platform MUST have.

Each test reproduces one confirmed defect (A-E, G from the V4 audit). They are
marked xfail(strict=True) while the defect stands; as each block fixes its
defect the marker is removed. strict=True guarantees a fixed defect cannot keep
its marker silently.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
import yaml

from quant_trade.carry.data import synthetic_funding_snapshots, write_snapshots_json
from quant_trade.carry.research import run_carry_research, write_carry_artifacts
from quant_trade.mining.market import MiningMarketData
from quant_trade.paper.readiness import evaluate_paper_readiness
from quant_trade.research.ledger import read_trials


def _carry_config() -> dict:
    return yaml.safe_load(open("configs/carry/cash_and_carry_synthetic.yaml"))


# --- Defect A: carry results.json is YAML, not JSON -----------------------


def test_defect_a_carry_results_json_is_parseable_json(tmp_path):
    cfg = _carry_config()
    result = run_carry_research(cfg)
    out = write_carry_artifacts(tmp_path, cfg, result)
    # A file named results.json MUST be valid JSON for promotion_v2 (json.loads).
    json.loads(out.read_text(encoding="utf-8"))


# --- Defect B: dataset binding hashes config, not file bytes --------------


def test_defect_b_changing_dataset_bytes_changes_binding(tmp_path):
    path = tmp_path / "snapshots.json"
    cfg = _carry_config()
    cfg["data"] = {"source": "json", "path": str(path)}

    write_snapshots_json(path, synthetic_funding_snapshots(periods=30, seed=1))
    run_a = run_carry_research(cfg)
    write_carry_artifacts(tmp_path / "run_a", cfg, run_a)

    # Same path, DIFFERENT bytes.
    write_snapshots_json(path, synthetic_funding_snapshots(periods=30, seed=2))
    run_b = run_carry_research(cfg)
    write_carry_artifacts(tmp_path / "run_b", cfg, run_b)

    sha_a = read_trials(tmp_path / "run_a")[0]["dataset_sha"]
    sha_b = read_trials(tmp_path / "run_b")[0]["dataset_sha"]
    assert sha_a != sha_b, "different dataset bytes must produce different bindings"


# --- Defect C: a handful of snapshots can reach GO ------------------------


def test_defect_c_thin_real_history_never_advances(tmp_path):
    # Forty real-labelled snapshots (~13 days of 8h funding) with constant
    # positive funding: today's gate emits GO with ZERO walk-forward windows.
    # (With <=6 snapshots the bootstrap incidentally blocks it because the
    # entry-cost interval dominates the p2.5, but nothing EXPLICITLY requires
    # minimum history, minimum walk-forward windows, DSR, or promotion V2.)
    snaps = [
        dataclasses.replace(s, data_source="real", realized_funding_rate=0.001)
        for s in synthetic_funding_snapshots(periods=40, seed=3)
    ]
    path = write_snapshots_json(tmp_path / "thin.json", snaps)
    cfg = _carry_config()
    cfg["data"] = {"source": "json", "path": str(path)}
    cfg["signal"] = {"entry_threshold": 0.0, "trailing_window": 1}
    result = run_carry_research(cfg)
    assert result.walk_forward == [], "construction sanity: no walk-forward possible"
    assert result.decision != "GO", (
        "forty snapshots and zero walk-forward windows must never produce GO"
    )


# --- Defect D: carry return series omits basis P&L ------------------------


def test_defect_d_basis_convergence_enters_pnl():
    from quant_trade.carry.models import CarryCostModel
    from quant_trade.carry.research import carry_campaign_returns

    # Zero funding, but the perp premium collapses from +1% to 0: a long-spot /
    # short-perp position GAINS that convergence. The return series must
    # expose a basis P&L component; funding-only accounting hides it.
    base = synthetic_funding_snapshots(periods=10, seed=4)
    snaps = []
    for i, s in enumerate(base):
        basis = 0.01 * (1 - i / 9)  # 1% premium converging to 0
        snaps.append(
            dataclasses.replace(
                s,
                realized_funding_rate=0.0,
                perp_mark_price=round(s.spot_price * (1 + basis), 2),
                perp_index_price=s.spot_price,
            )
        )
    frame = carry_campaign_returns(
        snaps, CarryCostModel(), entry_threshold=-1.0, trailing_window=1
    )
    assert "basis_pnl" in frame.columns, "return series must carry a basis P&L column"
    assert frame["basis_pnl"].abs().sum() > 0, "converging basis must produce basis P&L"


# --- Defect E: mining freshness trusts a caller-supplied staleness --------


@pytest.mark.xfail(reason="defect E: staleness not recomputed from captured_at", strict=True)
def test_defect_e_old_snapshot_with_zero_staleness_fails():
    from quant_trade.mining.market import require_fresh

    stale_but_lying = MiningMarketData(
        coin="BTC",
        algorithm="sha256",
        coin_price_usd=60000.0,
        network_hashrate_hs=6.0e20,
        difficulty=8.0e13,
        block_subsidy_coin=3.125,
        tx_fee_revenue_coin_per_block=0.15,
        blocks_per_day=144.0,
        captured_at_utc="2023-01-01T00:00:00Z",  # years old
        source_name="test",
        max_age_seconds=3600.0,
        staleness_seconds=0.0,  # caller claims it is fresh
    )
    with pytest.raises(ValueError, match="stale"):
        require_fresh(stale_but_lying, evaluated_at_utc="2026-07-24T00:00:00Z")


@pytest.mark.xfail(reason="defect E: future snapshots not rejected", strict=True)
def test_defect_e_future_snapshot_fails():
    from quant_trade.mining.market import require_fresh

    from_the_future = MiningMarketData(
        coin="BTC",
        algorithm="sha256",
        coin_price_usd=60000.0,
        network_hashrate_hs=6.0e20,
        difficulty=8.0e13,
        block_subsidy_coin=3.125,
        tx_fee_revenue_coin_per_block=0.15,
        blocks_per_day=144.0,
        captured_at_utc="2030-01-01T00:00:00Z",
        source_name="test",
        staleness_seconds=0.0,
    )
    with pytest.raises(ValueError, match="future"):
        require_fresh(from_the_future, evaluated_at_utc="2026-07-24T00:00:00Z")


# --- Defect G: paper readiness is declarative -----------------------------


@pytest.mark.xfail(reason="defect G: broker_mode defaults to paper", strict=True)
def test_defect_g_missing_broker_mode_fails():
    config = {
        "exporter_enabled": True,
        "recovery_enabled": True,
        "kill_switch_enabled": True,
        "orphan_detection_enabled": True,
        "heartbeat_interval_seconds": 30,
        "reconciliation_enabled": True,
        # broker_mode deliberately missing: must NOT default to paper-and-pass
    }
    report = evaluate_paper_readiness(config)
    assert report.status == "NOT_READY"
    assert "broker_is_paper_only" in report.blocking


@pytest.mark.xfail(reason="defect G: booleans accepted without drill artifacts", strict=True)
def test_defect_g_booleans_without_drill_evidence_are_not_ready():
    config = {
        "broker_mode": "paper",
        "live_trading": False,
        "exporter_enabled": True,
        "recovery_enabled": True,
        "kill_switch_enabled": True,
        "orphan_detection_enabled": True,
        "heartbeat_interval_seconds": 30,
        "reconciliation_enabled": True,
        # no executed-drill artifacts anywhere
    }
    report = evaluate_paper_readiness(config)
    assert report.status == "NOT_READY", (
        "configuration booleans alone must never certify readiness; executed "
        "drill artifacts are required"
    )
