"""End-to-end tests for the crypto low-cap campaign on a sealed fixture.

The properties under test are the ones that make the campaign's numbers mean
something: the holdout is never read during selection, the declared trial
budget is what deflation uses, a run is refused whenever its inputs are not
the locked ones, the freeze is at most one primary candidate, the reveal
happens once, and a rendered document cannot claim money was made.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from crypto_lowcap_fixture import AT, HOLDOUT, SELECTION, build_experiment

from quant_trade.research.crypto_lowcap import campaign, reveal
from quant_trade.research.crypto_lowcap.campaign import (
    FROZEN_FILENAME,
    LEDGER_FILENAME,
    CampaignError,
    fold_windows,
    load_frozen,
    load_panel,
    run_select,
    selection_slice,
)
from quant_trade.research.crypto_lowcap.config import CampaignConfigError, lock_payload, write_lock
from quant_trade.research.crypto_lowcap.report import (
    ProfitClaimError,
    assert_no_profit_claims,
    programme_state,
    render_results_markdown,
)
from quant_trade.research.crypto_lowcap.reveal import STATE_NO_CANDIDATE, STATE_REVEALED, run_reveal
from quant_trade.research.holdout_seal import (
    HoldoutSealError,
    load_seal,
    read_reveals,
    record_reveal,
)
from quant_trade.research.ledger import read_trials
from quant_trade.research.preregistration import assert_within_budget, load_preregistration

CODE = "deadbeef"


def _select(fx: dict) -> dict:
    return run_select(
        fx["experiment"], fx["trials"], fx["panel"], evaluated_at_utc=AT, code_sha=CODE
    )


def test_selection_slice_never_returns_a_holdout_date(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    panel = load_panel(fx["panel"])
    seal = load_seal(fx["experiment"])
    sliced = selection_slice(panel, seal)
    days = sliced["timestamp"].dt.strftime("%Y-%m-%d")
    assert days.max() == SELECTION[1]
    assert (days >= HOLDOUT[0]).sum() == 0
    with pytest.raises(HoldoutSealError, match="outside the selection window"):
        campaign.assert_within_selection(seal, [HOLDOUT[0]])


def test_folds_are_calendar_years_with_an_embargoed_expanding_train(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    seal = load_seal(fx["experiment"])
    folds = fold_windows(seal, [2019, 2020, 2021], 30)
    assert [f.test_start for f in folds] == ["2019-01-01", "2020-01-01", "2021-01-01"]
    assert [f.train_start for f in folds] == [SELECTION[0]] * 3
    assert folds[1].train_end == "2019-12-01"  # 30 days + 1 before the test window
    with pytest.raises(CampaignError, match="no train span"):
        fold_windows(seal, [2018], 30)


def test_select_end_to_end_and_the_reveal_is_one_shot(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    exp = fx["experiment"]
    results = _select(fx)

    # Every declared trial ran, and every sealed hypothesis stayed within budget.
    assert len(results["trials"]) == 4
    assert results["deflated_sharpe"]["n_trials_declared"] == 4
    assert results["deflated_sharpe"]["n_trials_spent"] == 4
    floor = results["deflated_sharpe"]["sharpe_variance_floor"]
    assert results["deflated_sharpe"]["sharpe_variance_used"] >= floor
    records = read_trials(None, registry_path=exp / LEDGER_FILENAME)
    sealed = [r for r in records if r["preregistration_seal"]]
    assert len(sealed) == 4
    assert {r["source"] for r in records} >= {
        "crypto_lowcap_select:candidate",
        "crypto_lowcap_select:control",
        "crypto_lowcap_select:benchmark",
    }
    for experiment_id in (
        "crypto_lowcap_h3_rebalancing_premium",
        "crypto_lowcap_h5_midcap_momentum",
    ):
        assert_within_budget(load_preregistration(exp / experiment_id), records)

    # Every trial carries both delisting assumptions and every declared gate.
    for row in results["trials"]:
        for rec in ("1.0", "0.0"):
            block = row[f"recovery_{rec}"]
            assert set(block["gates"]) == {row["primary_gate"], "conservative"}
            assert block["dsr_declared"] is not None
            assert block["cost_drag_bps_per_year"] >= 0.0

    # The permissive gate freezes exactly one primary and at most one secondary.
    frozen = load_frozen(exp)
    assert frozen is not None and frozen["primary"] is not None
    assert len(frozen["secondaries"]) <= 1
    assert frozen["primary"]["experiment_id"] != (
        frozen["secondaries"][0]["experiment_id"] if frozen["secondaries"] else None
    )
    assert programme_state(exp) == "SELECTED_CANDIDATE_FROZEN"
    assert read_reveals(exp) == []

    verdict = run_reveal(
        exp, fx["panel"], reason="fixture reveal", evaluated_at_utc=AT, code_sha=CODE
    )
    assert verdict["state"] == STATE_REVEALED
    assert verdict["reveals_used"] == 1
    assert verdict["holdout_window"] == list(HOLDOUT)
    primary = verdict["candidates"][0]["by_recovery"]["0.0"]
    assert primary["sharpe_range"]["status"] == "MEASURED"
    assert primary["sharpe_range"]["sharpe_se"] > 0
    low, high = primary["sharpe_range"]["range_1se"]
    assert low <= primary["sharpe_range"]["sharpe_annualised"] <= high
    assert primary["sharpe_range"]["verdict_class"] in {
        "RANGE_ABOVE_ZERO",
        "RANGE_INCLUDES_ZERO",
        "RANGE_BELOW_ZERO",
    }
    assert primary["equity"]["dates"][0] >= HOLDOUT[0]
    assert primary["equity"]["dates"][-1] <= HOLDOUT[1]
    assert programme_state(exp) == "REVEALED"

    before = reveal.verdict_path(exp).read_bytes()
    with pytest.raises(CampaignError, match="read once"):
        run_reveal(exp, fx["panel"], reason="again", evaluated_at_utc=AT, code_sha=CODE)
    assert reveal.verdict_path(exp).read_bytes() == before
    assert len(read_reveals(exp)) == 1

    text = render_results_markdown(exp)
    assert "REVEALED" in text
    assert "MEASURED" in text and "NOT_MEASURED" in text
    assert "| `crypto_lowcap_h3_rebalancing_premium:t1` |" in text


def test_select_runs_once_per_experiment(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    _select(fx)
    with pytest.raises(CampaignError, match="runs once"):
        _select(fx)


def test_select_refuses_after_a_reveal_without_reading_the_panel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fx = build_experiment(tmp_path)
    record_reveal(fx["experiment"], reason="early", at_utc=AT, frozen_selection={"trial_id": "x"})

    def _boom(path):  # pragma: no cover - must never run
        raise AssertionError("the panel was loaded after a reveal")

    monkeypatch.setattr(campaign, "load_panel", _boom)
    with pytest.raises(HoldoutSealError, match="already revealed"):
        _select(fx)


def test_select_refuses_a_trials_config_that_differs_from_the_lock(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    write_lock(
        fx["experiment"],
        lock_payload(
            seal_id="fixture_2026",
            panel_digest=fx["digest"],
            panel_content_sha256=json.loads(
                (fx["experiment"] / "panel_verification.json").read_text(encoding="utf-8")
            )["panel_content_sha256"],
            digest_recipe={},
            trials_config_path="other.yaml",
            trials_config_sha256="0" * 64,
            gate_shas={},
            code_sha=CODE,
            at_utc=AT,
        ),
    )
    with pytest.raises(CampaignConfigError, match="declared grid was edited"):
        _select(fx)


def test_select_refuses_an_unverified_or_changed_panel(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    verification = fx["experiment"] / "panel_verification.json"
    saved = verification.read_bytes()
    verification.unlink()
    with pytest.raises(CampaignError, match="verify-panel"):
        _select(fx)
    verification.write_bytes(saved)
    fx["panel"].write_bytes(fx["panel"].read_bytes() + b"\n")
    with pytest.raises(CampaignError, match="panel bytes differ"):
        _select(fx)


def test_no_candidate_leaves_the_holdout_sealed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fx = build_experiment(tmp_path, strict=True)
    results = _select(fx)
    assert results["frozen"]["primary_trial_id"] is None
    assert "no trial passed" in results["frozen"]["no_candidate_reason"]
    assert programme_state(fx["experiment"]) == "SELECTED_NO_CANDIDATE"

    def _boom(path):  # pragma: no cover - must never run
        raise AssertionError("the panel was loaded without a candidate")

    monkeypatch.setattr(reveal, "load_panel", _boom)
    verdict = run_reveal(
        fx["experiment"], fx["panel"], reason="try", evaluated_at_utc=AT, code_sha=CODE
    )
    assert verdict["state"] == STATE_NO_CANDIDATE
    assert verdict["revealed"] is False
    assert read_reveals(fx["experiment"]) == []
    text = render_results_markdown(fx["experiment"])
    assert STATE_NO_CANDIDATE in text


def test_an_edited_frozen_selection_is_refused(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    _select(fx)
    path = fx["experiment"] / FROZEN_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["primary"]["strategy_params"]["top_n"] = 99
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CampaignError, match="edited after it was frozen"):
        load_frozen(fx["experiment"])
    with pytest.raises(CampaignError, match="edited after it was frozen"):
        run_reveal(fx["experiment"], fx["panel"], reason="x", evaluated_at_utc=AT, code_sha=CODE)
    assert read_reveals(fx["experiment"]) == []


def _normalised(results: dict) -> dict:
    clone = json.loads(json.dumps(results))
    # The fixture's trials file embeds absolute gate paths, so its sha differs
    # between two roots while its declared content does not; the gate shas
    # themselves are content-based and must agree.
    clone["trials_config"] = "<trials>"
    clone["ledger"]["path"] = "<path>"
    return clone


def test_results_are_deterministic_given_the_same_inputs(tmp_path: Path) -> None:
    a = build_experiment(tmp_path / "a")
    b = build_experiment(tmp_path / "b")
    assert a["digest"] == b["digest"]
    ra = _select(a)
    rb = _select(b)
    assert _normalised(ra) == _normalised(rb)
    ta = sorted((a["experiment"] / "selection" / "trials").glob("*.json"))
    tb = sorted((b["experiment"] / "selection" / "trials").glob("*.json"))
    assert [p.name for p in ta] == [p.name for p in tb]
    for left, right in zip(ta, tb, strict=True):
        assert left.read_bytes() == right.read_bytes()


def test_report_refuses_profit_claims() -> None:
    with pytest.raises(ProfitClaimError):
        assert_no_profit_claims("This strategy is profitable and makes money.")
    assert_no_profit_claims("This strategy returned +12% over the window (MEASURED).")
