"""V6 P0 defect reproduction — red tests first, fixes after.

Each test asserts the DESIRED behavior and is marked xfail(strict=True) while
the defect exists: the suite stays green, the defect stays documented, and the
moment a fix lands the xfail marker must be removed (strict makes an
unexpected pass fail loudly). Letters follow the V6 sprint mandate.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
import yaml

from quant_trade.carry.data import synthetic_funding_snapshots, write_snapshots_json
from quant_trade.carry.models import CarryCostModel
from quant_trade.carry.research import run_carry_research
from quant_trade.carry.store import FundingObservation, append_observations

COSTS = CarryCostModel(half_spread_bps=2.0, slippage_bps=1.0, market_impact_bps=1.0)


def _real_json_campaign(tmp_path, periods=120, funding=0.001):
    snaps = [
        dataclasses.replace(s, data_source="real", realized_funding_rate=funding)
        for s in synthetic_funding_snapshots(periods=periods, seed=4)
    ]
    path = write_snapshots_json(tmp_path / "real.json", snaps)
    with open("configs/carry/cash_and_carry_synthetic.yaml") as fh:
        cfg = yaml.safe_load(fh)
    cfg["data"] = {"source": "json", "path": str(path)}
    cfg["signal"] = {"entry_threshold": 0.0, "trailing_window": 3}
    return cfg


def _poll_store(tmp_path, n=120):
    """A jsonl store containing ONLY quote polls — zero settlements."""
    base = {
        "venue": "bybit",
        "symbol": "BTC",
        "spot_bid": 100.0,
        "spot_ask": 100.1,
        "perp_bid": 100.2,
        "perp_ask": 100.3,
        "perp_mark": 100.25,
        "perp_index": 100.05,
        "realized_funding_rate": 0.001,
        "source_event": "poll",
        "source_name": "test",
    }
    obs = [
        FundingObservation(
            captured_at_utc=f"2026-06-{1 + i // 24:02d}T{i % 24:02d}:00:00Z",
            exchange_timestamp_utc=f"2026-06-{1 + i // 24:02d}T{i % 24:02d}:00:00Z",
            **base,
        )
        for i in range(n)
    ]
    path = tmp_path / "polls.jsonl"
    append_observations(path, obs)
    return path


# --- A. the stateful ledger is not wired into research/promotion ----------


def test_campaign_verdict_is_backed_by_a_reconciled_ledger(tmp_path):
    result = run_carry_research(_real_json_campaign(tmp_path))
    ledger = result.ledger_summary
    assert ledger["reconciled"] is True
    assert "unwind_costs" in ledger


def test_artifacts_include_ledger_reconciliation(tmp_path):
    from quant_trade.carry.research import write_carry_artifacts

    cfg = _real_json_campaign(tmp_path)
    result = run_carry_research(cfg)
    out = tmp_path / "artifacts"
    write_carry_artifacts(out, cfg, result)
    assert (out / "reconciliation.json").exists()
    assert (out / "equity_curve.csv").exists()


# --- B. sufficiency counts polls, not settlements --------------------------


def test_pure_poll_store_cannot_satisfy_the_sufficiency_gate(tmp_path):
    store = _poll_store(tmp_path, n=120)
    with open("configs/carry/cash_and_carry_synthetic.yaml") as fh:
        cfg = yaml.safe_load(fh)
    cfg["data"] = {"source": "jsonl_observations", "path": str(store)}
    cfg["signal"] = {"entry_threshold": 0.0, "trailing_window": 3}
    cfg["gate"] = {"min_funding_events": 90, "min_span_days": 1.0}
    result = run_carry_research(cfg)
    # 120 polls carry ZERO settled funding: sufficiency must fail on
    # settlement count, not pass on bar count
    assert result.decision.startswith("NOT_RUN")
    assert any("settlement" in r for r in result.reasons)
    assert result.metrics.get("unique_settlement_count") == 0


# --- C. cost stress does not propagate settlements or the full cost stack --


def test_cost_stress_keeps_settlement_semantics(tmp_path):
    store = _poll_store(tmp_path, n=120)  # zero settlements => zero funding
    with open("configs/carry/cash_and_carry_synthetic.yaml") as fh:
        cfg = yaml.safe_load(fh)
    cfg["data"] = {"source": "jsonl_observations", "path": str(store)}
    cfg["signal"] = {"entry_threshold": 0.0, "trailing_window": 3}
    result = run_carry_research(cfg)
    # with zero settled funding, stressing costs can only make things WORSE
    # than zero funding income; legacy fallback re-fabricates poll funding,
    # which can make 2x costs look profitable
    assert result.metrics["funding_pnl_total"] == 0.0
    assert result.metrics["total_return_2x_costs"] <= result.metrics["total_return"]
    assert result.metrics["total_return_2x_costs"] <= 0.0


def test_cost_stress_multiplies_every_cost_component(tmp_path):
    import inspect

    from quant_trade.carry import research as research_mod

    source = inspect.getsource(research_mod)
    stressed_block = source.split("def _stressed_total")[1].split("def ")[0]
    assert "taker_fee_bps" in stressed_block
    assert "settlements" in stressed_block


# --- D. provenance is self-declared ----------------------------------------


@pytest.mark.xfail(strict=True, reason="V6-D: data_source self-labels are trusted")
def test_relabelled_synthetic_data_cannot_promote(tmp_path):
    # exactly what our own test helpers do: dataclasses.replace(..., "real").
    # Desired: provenance must come from verified ingestion receipts, so a
    # relabelled dataset without receipts is UNVERIFIED, never "real".
    result = run_carry_research(_real_json_campaign(tmp_path))
    assert result.data_source != "real"
    assert result.decision != "PAPER_CANDIDATE"


@pytest.mark.xfail(strict=True, reason="V6-D: snapshot bridge hardcodes real")
def test_observation_bridge_does_not_invent_real_provenance():
    import inspect

    from quant_trade.carry import store as store_mod

    source = inspect.getsource(store_mod.observations_to_snapshot_records)
    assert '"real"' not in source, "provenance must come from receipts, not a literal"


# --- E. backfill and collector derive different identities ------------------


@pytest.mark.xfail(strict=True, reason="V6-E: no canonical instrument catalog")
def test_backfill_and_collector_share_one_canonical_identity():
    from quant_trade.carry.instruments import canonical_instrument_id

    assert canonical_instrument_id("bybit", "BTCUSDT") == canonical_instrument_id(
        "bybit", "BTC/USDT:USDT"
    )
    assert canonical_instrument_id("okx", "BTC-USDT-SWAP") == canonical_instrument_id(
        "okx", "BTC/USDT:USDT"
    )


# --- F. a successful backfill still cannot feed research -------------------


@pytest.mark.xfail(strict=True, reason="V6-F: no historical panel joins quotes+settlements")
def test_backfilled_settlements_can_power_research_via_panel(tmp_path):
    from quant_trade.carry.backfill import run_backfill

    store = tmp_path / "history.jsonl"
    run_backfill(
        "bybit", "BTC", store, fixture_path="tests/fixtures/bybit_funding_history.json"
    )
    with open("configs/carry/cash_and_carry_synthetic.yaml") as fh:
        cfg = yaml.safe_load(fh)
    cfg["data"] = {"source": "jsonl_observations", "path": str(store)}
    result = run_carry_research(cfg)  # today: "no quote observations" ValueError
    assert result.decision.startswith("NOT_RUN")


# --- G. the collector stores last as mark ----------------------------------


@pytest.mark.xfail(strict=True, reason="V6-G: perp last is used as perp_mark")
def test_collector_never_substitutes_last_for_mark():
    import inspect

    from quant_trade.carry.collector import CcxtFundingAdapter

    source = inspect.getsource(CcxtFundingAdapter.observe)
    assert 'perp_mark=float(perp["last"])' not in source


# --- H. H1/H2 signals consume polls, not settlements ------------------------


@pytest.mark.xfail(strict=True, reason="V6-H: trailing signal averages quoted polls")
def test_signal_uses_last_n_unique_settlements(tmp_path):
    # pre-registration: "trailing mean of the last 3 SETTLED rates". A store
    # whose polls quote 0.01 but whose settlements paid -0.01 must NOT enter.
    from quant_trade.carry.backfill import run_backfill

    store = tmp_path / "history.jsonl"
    run_backfill(
        "bybit", "BTC", store, fixture_path="tests/fixtures/bybit_funding_history.json"
    )
    # append optimistic polls quoting a rate far above what actually settled
    polls = _poll_store(tmp_path, n=30)
    merged = tmp_path / "merged.jsonl"
    merged.write_text(polls.read_text() + store.read_text())
    with open("configs/carry/cash_and_carry_synthetic.yaml") as fh:
        cfg = yaml.safe_load(fh)
    cfg["data"] = {"source": "jsonl_observations", "path": str(merged)}
    cfg["signal"] = {"entry_threshold": 0.005, "trailing_window": 3}
    result = run_carry_research(cfg)
    # settled rates max at 0.00013 << 0.005 threshold: no entry may occur
    assert result.metrics["active_intervals"] == 0


# --- I. H3 is not actually cross-venue --------------------------------------


@pytest.mark.xfail(strict=True, reason="V6-I: H3 runs a single-venue campaign")
def test_h3_is_cross_venue_or_absent():
    cfg = yaml.safe_load(
        Path("configs/opportunities/trading_scan_v5.yaml").read_text()
    )
    h3 = next(h for h in cfg["hypotheses"] if h["id"] == "H3")
    campaign = h3.get("campaign") or {}
    # a cross-venue dispersion hypothesis cannot be a single-venue campaign
    assert campaign.get("data", {}).get("path") != "data/carry/funding_history_bybit.jsonl"
    assert h3.get("kind") == "cross_venue_dispersion"


# --- J. DSR/PBO are documented, not enforced --------------------------------


@pytest.mark.xfail(strict=True, reason="V6-J: promotion checks PSR only")
def test_promotion_requires_dsr_and_pbo(tmp_path):
    from quant_trade.carry.research import evaluate_carry_promotion, write_carry_artifacts

    cfg = _real_json_campaign(tmp_path)
    result = run_carry_research(cfg)
    out = tmp_path / "artifacts"
    write_carry_artifacts(out, cfg, result)
    review = evaluate_carry_promotion(out / "results.json", ledger_dir=out)
    text = " ".join(review["failures"]).lower()
    assert "dsr" in text or "deflated" in text
    assert "pbo" in text or "overfitting" in text


# --- K. the board ranks incompatible units ----------------------------------


@pytest.mark.xfail(strict=True, reason="V6-K: sharpe vs USD/h vs annual yield")
def test_board_scores_share_one_unit():
    from quant_trade.opportunities.board import build_opportunity_board

    board = build_opportunity_board(
        trading_rows=[
            {
                "hypothesis_id": "HX",
                "status": "PAPER_CANDIDATE",
                "data_source": "real",
                "metrics": {"sharpe_per_period": 0.05},
                "reasons": [],
            }
        ],
        mining_cells=[
            {
                "identity": "x",
                "status": "ECONOMIC_CANDIDATE_PAPER_ONLY",
                "test_only": False,
                "conditional_economics": {"margin_per_hour_usd": 0.06},
                "reasons": [],
            }
        ],
        cash_yield_annual=0.04,
        evaluated_at_utc="2026-07-24T23:00:00Z",
    )
    units = {e.get("score_unit") for e in board["entries"] if e["eligible"]}
    assert units == {"annualized_net_return_on_capital"}


# --- L. the board trusts arbitrary artifacts --------------------------------


@pytest.mark.xfail(strict=True, reason="V6-L: rank verifies no schema/hash/lineage")
def test_board_rejects_hand_edited_artifacts(tmp_path):
    from quant_trade.opportunities.board import build_opportunity_board

    forged = {
        "hypothesis_id": "FORGED",
        "status": "PAPER_CANDIDATE",
        "data_source": "real",
        "metrics": {"sharpe_per_period": 99.0},
        "reasons": [],
    }
    with pytest.raises(ValueError, match="lineage"):
        build_opportunity_board(
            trading_rows=[forged],
            mining_cells=[],
            cash_yield_annual=0.04,
            evaluated_at_utc="2026-07-24T23:00:00Z",
        )


# --- M. multiasset caps and boundaries --------------------------------------


@pytest.mark.xfail(strict=True, reason="V6-M: leverage silently drops the cap in runner")
def test_runner_never_silently_drops_the_gross_cap():
    import inspect

    from quant_trade.research import multi_asset_runner as runner_mod

    source = inspect.getsource(runner_mod)
    # desired: an explicit leveraged-cap policy, not `and not allow_leverage`
    assert "not allow_leverage else None" not in source


@pytest.mark.xfail(strict=True, reason="V6-M: walk_forward_multi ignores gross cap")
def test_walk_forward_multi_propagates_gross_cap():
    import inspect

    from quant_trade.research import walk_forward_multi as wf_mod

    source = inspect.getsource(wf_mod)
    assert "max_gross_exposure" in source


# --- N. paper readiness/parity accept written evidence ----------------------


@pytest.mark.xfail(strict=True, reason="V6-N: evidence_sha256 is self-referential")
def test_readiness_evidence_hash_binds_external_logs():
    import inspect

    from quant_trade.paper import readiness as readiness_mod

    source = inspect.getsource(readiness_mod)
    # desired: the hash covers a raw evidence log file whose bytes are
    # re-verified at evaluation time, not a hash of the record itself
    assert "raw_log_path" in source or "evidence_path" in source


# --- O. mining accepts declared evidence ------------------------------------


@pytest.mark.xfail(strict=True, reason="V6-O: inline hashprice with no source")
def test_market_inputs_require_sourced_snapshots():
    cells = yaml.safe_load(
        Path("configs/opportunities/mining_scan_v5.yaml").read_text()
    )["cells"]
    # desired: revenue comes from a market snapshot artifact with source and
    # freshness, never an inline number
    assert all("hashprice_usd_per_th_day" not in (c.get("revenue") or {}) for c in cells)


@pytest.mark.xfail(strict=True, reason="V6-O: quote/spec carry no raw byte binding")
def test_quotes_and_specs_are_byte_bound():
    from quant_trade.cloud_rental.models import ComputeQuote, InstanceSpecification

    assert "raw_sha256" in ComputeQuote.__dataclass_fields__
    assert "raw_sha256" in InstanceSpecification.__dataclass_fields__


@pytest.mark.xfail(strict=True, reason="V6-O: KHeavyHash priced with a SHA-256 unit")
def test_algorithm_units_are_dimensional():
    cells = yaml.safe_load(
        Path("configs/opportunities/mining_scan_v5.yaml").read_text()
    )["cells"]
    kas = [c for c in cells if c.get("coin") == "KAS"]
    assert all((c.get("revenue") or {}).get("hashrate_unit") for c in kas), (
        "algorithms must declare their own hashrate unit; USD/TH/day is SHA-256-only"
    )


def _matrix_rows() -> list[dict]:
    """The defect matrix rows — kept in the test so the artifact stays honest."""
    return [
        {"defect": letter, "status": "REPRODUCED_RED_TEST"}
        for letter in "ABCDEFGHIJKLMNO"
    ]


def test_defect_matrix_artifact_matches_the_red_tests():
    matrix = json.loads(
        Path("artifacts/v6/DEFECT_REPRODUCTION_MATRIX.json").read_text()
    )
    letters = {row["defect"] for row in matrix["defects"]}
    assert letters == set("ABCDEFGHIJKLMNO")
