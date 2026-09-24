"""A complete, tiny, sealed crypto low-cap experiment for campaign tests.

Everything the real programme needs, at fixture scale: a crypto-shaped panel
with staggered listings and deaths, the dataset directories the digest is
computed over, a v2 panel digest, a sealed 70/30 holdout, sealed
pre-registrations bound to that digest, gate files, a declared trial grid,
and a recorded panel verification. Tests build it into ``tmp_path`` and run
the same functions the CLI runs.
"""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from quant_trade.data.panel_digest import DigestInputs, verify_panel_digest, write_panel_digest
from quant_trade.evidence.canonical_json import atomic_write_json, canonical_dumps, sha256_of_text
from quant_trade.research.crypto_lowcap.campaign import record_panel_verification
from quant_trade.research.holdout_seal import HoldoutSeal, seal_holdout
from quant_trade.research.preregistration import ExperimentPreregistration, seal_preregistration

SELECTION = ("2018-01-01", "2021-12-31")
HOLDOUT = ("2022-01-01", "2022-12-31")
AT = "2026-01-01T00:00:00Z"

PERMISSIVE_GATE: dict[str, Any] = {
    "min_test_sharpe": -100.0,
    "min_excess_return": -100.0,
    "max_test_drawdown": 1.0,
    "max_turnover": 1000.0,
    "require_beats_benchmark": False,
    "require_cost_sensitivity_pass": False,
    "min_test_months": 6,
    "max_train_test_sharpe_gap": 1000.0,
    "min_trade_count": 0,
    "min_probabilistic_sharpe": 0.0,
    "require_deflated_sharpe": True,
    "min_deflated_sharpe": 0.0,
    "require_walk_forward_overfitting_evidence": True,
    "max_walk_forward_pbo": 1.0,
    "min_walk_forward_windows": 2,
}
STRICT_GATE: dict[str, Any] = {**PERMISSIVE_GATE, "min_test_sharpe": 100.0}


def synthetic_panel(seed: int = 7, n_symbols: int = 10) -> pd.DataFrame:
    """Mid-tier coins with staggered entry and a few deaths, plus BTC."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(SELECTION[0], HOLDOUT[1], freq="D", tz="UTC")
    n = len(dates)
    rows: list[dict[str, Any]] = []
    for i in range(n_symbols):
        first = 0 if i < 4 else int(rng.integers(1, n // 3))
        last = n if i % 4 else int(rng.integers(n // 2, n))
        close = 10 * np.cumprod(1 + rng.normal(0.0004, 0.04, n))
        turnover = 5e5 * (i + 1) * np.exp(rng.normal(0, 0.3, n))
        for j in range(first, last):
            price = float(close[j])
            rows.append(
                {
                    "timestamp": dates[j],
                    "symbol": f"C{i}:{100 + i}",
                    "cmc_id": 100 + i,
                    "venue": "bybit",
                    "open": price,
                    "high": price * 1.03,
                    "low": price * 0.97,
                    "close": price,
                    "volume": 1000.0,
                    "venue_turnover_usd": float(turnover[j]),
                    "cmc_rank": float(50 + i * 20),
                    "market_cap_usd": 150e6 + 40e6 * i,
                    "reported_volume_usd": float(turnover[j]) * 3,
                }
            )
    btc = 20_000 * np.cumprod(1 + rng.normal(0.0005, 0.03, n))
    for j in range(n):
        price = float(btc[j])
        rows.append(
            {
                "timestamp": dates[j],
                "symbol": "BTC:1",
                "cmc_id": 1,
                "venue": "bybit",
                "open": price,
                "high": price * 1.02,
                "low": price * 0.98,
                "close": price,
                "volume": 100.0,
                "venue_turnover_usd": 1e9,
                "cmc_rank": 1.0,
                "market_cap_usd": 400e9,
                "reported_volume_usd": 3e9,
            }
        )
    return pd.DataFrame(rows).sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def _journal(directory: Path, tag: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    header = {"type": "header", "policy_sha256": tag, "previous_sha256": ""}
    day = {
        "type": "day",
        "date": "2020-01-01",
        "previous_sha256": sha256_of_text(canonical_dumps(header)),
    }
    with (directory / "journal.jsonl").open("w", encoding="utf-8") as handle:
        for record in (header, day):
            handle.write(canonical_dumps(record) + "\n")


def _prereg(
    experiment_id: str, hypothesis: str, digest: str, max_trials: int
) -> ExperimentPreregistration:
    return ExperimentPreregistration(
        experiment_id=experiment_id,
        hypothesis=hypothesis,
        universe=[f"crypto_lowcap_panel@{digest}", "fixture universe"],
        start_date=SELECTION[0],
        end_date=HOLDOUT[1],
        selection_criterion={
            "holdout": {"selection_window": list(SELECTION), "holdout_window": list(HOLDOUT)}
        },
        max_trials=max_trials,
        refutation="REFUTED if it does not beat its control over the holdout",
        registered_at_utc=AT,
        registered_at_commit="fixture",
    )


def build_experiment(
    root: Path, *, strict: bool = False, panel: pd.DataFrame | None = None
) -> dict[str, Any]:
    """Build the whole sealed experiment under ``root`` and return its paths."""
    root.mkdir(parents=True, exist_ok=True)
    exp = root / "experiment"
    exp.mkdir()
    frame = synthetic_panel() if panel is None else panel
    panel_path = exp / "panel.csv.gz"
    with gzip.GzipFile(panel_path, mode="wb", mtime=0) as handle:
        handle.write(frame.to_csv(index=False).encode("utf-8"))
    atomic_write_json(exp / "panel_build_report.json", {"rows_in_panel": int(len(frame))})
    _journal(root / "universe", "u")
    _journal(root / "bybit", "b")
    death = root / "deathlist"
    death.mkdir()
    atomic_write_json(death / "deathlist.json", {"raw_sha256": "a" * 64, "inactive_symbols": []})
    inputs = DigestInputs(
        universe_dir=root / "universe",
        venue_dirs={"bybit": root / "bybit"},
        deathlist_dir=death,
        build_report_path=exp / "panel_build_report.json",
        panel_path=panel_path,
    )
    digest = write_panel_digest(
        exp,
        inputs,
        rows=int(len(frame)),
        symbols=int(frame["symbol"].nunique()),
        window=(SELECTION[0], HOLDOUT[1]),
    )["digest"]
    seal_holdout(
        exp,
        HoldoutSeal(
            seal_id="fixture_2026",
            dataset_id="fixture_panel",
            dataset_digest=digest,
            selection_start=SELECTION[0],
            selection_end=SELECTION[1],
            holdout_start=HOLDOUT[0],
            holdout_end=HOLDOUT[1],
            rationale="fixture 70/30 (actually 80/20, declared)",
            sealed_at_utc=AT,
        ),
    )
    seal_preregistration(
        exp / "crypto_lowcap_h3_rebalancing_premium",
        _prereg("crypto_lowcap_h3_rebalancing_premium", "annual rebalancing pays", digest, 2),
    )
    seal_preregistration(
        exp / "crypto_lowcap_h5_midcap_momentum",
        _prereg("crypto_lowcap_h5_midcap_momentum", "mid-cap momentum survives costs", digest, 2),
    )
    gate = root / "gate.yaml"
    gate.write_text(yaml.safe_dump(STRICT_GATE if strict else PERMISSIVE_GATE), encoding="utf-8")
    conservative = root / "conservative.yaml"
    conservative.write_text(
        yaml.safe_dump({**PERMISSIVE_GATE, "min_test_sharpe": 0.5}), encoding="utf-8"
    )
    trials = root / "trials.yaml"
    trials.write_text(yaml.safe_dump(trials_config(str(gate), str(conservative))), encoding="utf-8")
    verification = verify_panel_digest(exp, inputs)
    assert verification.status == "PASS", verification.reasons
    record_panel_verification(exp, verification, panel_path=panel_path, at_utc=AT)
    return {
        "root": root,
        "experiment": exp,
        "panel": panel_path,
        "trials": trials,
        "gate": gate,
        "digest": digest,
        "inputs": inputs,
        "frame": frame,
    }


def trials_config(gate: str, conservative: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "common": {
            "order_notional_usd": 1000,
            "turnover_multiple": 50,
            "liquidity_window": 30,
            "initial_capital_usd": 1000,
            "quantile": "p75",
            "min_executable_fraction": 1.0,
            "cost_multipliers": [1.0, 2.0, 3.0],
            "bootstrap_seed": 11,
            "bootstrap_samples": 50,
            "bootstrap_block_size": 10,
            "cscv_partitions": 4,
        },
        "walk_forward": {
            "scheme": "calendar_year_purged_wf_v1",
            "test_years": [2020, 2021],
            "embargo_days": 30,
            "oos_start": "2020-01-01",
        },
        "turnover": {"basis": "raw_total"},
        "deflated_sharpe": {
            "n_trials_declared": 4,
            "sharpe_variance_floor": 0.0025817269775679735,
            "primary_benchmark": "ew_universe_buy_and_hold",
        },
        "gates": {"conservative": conservative},
        "benchmarks": {
            "ew_universe_buy_and_hold": {
                "strategy": "crypto_annual_equal_weight_rebalance",
                "params": {"top_n": 100000, "rebalance_once": True},
            },
            "btc_buy_and_hold": {"symbol": "BTC:1"},
        },
        "hypotheses": {
            "crypto_lowcap_h3_rebalancing_premium": {
                "strategy": "crypto_annual_equal_weight_rebalance",
                "gate": gate,
                "control": {"rebalance_once": True},
                "variants": [{"top_n": 2}, {"top_n": 3}],
            },
            "crypto_lowcap_h5_midcap_momentum": {
                "strategy": "crypto_midcap_momentum",
                "gate": gate,
                "control": {"equal_weight_control": True},
                "control_shared": True,
                "variants": [
                    {"lookback_days": 28, "top_n": 2, "tier": "mid"},
                    {"lookback_days": 84, "top_n": 2, "tier": "mid"},
                ],
            },
        },
    }
