"""H8: the periods_per_year knob, the declarations, and the subsumption test."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quant_trade.research.crypto_lowcap.majors import OverlapError, overlap
from quant_trade.research.signals.allocation import vol_targeted_equal_weight


def _panel(n: int = 300, sigma: float = 0.05) -> pd.DataFrame:
    ts = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    rng = np.random.default_rng(3)
    frames = []
    for symbol in ("A", "B"):
        close = 100.0 * np.cumprod(1 + rng.normal(0.0, sigma, n))
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": ts,
                    "symbol": symbol,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1.0,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def test_default_periods_per_year_keeps_the_etf_behaviour_byte_identical() -> None:
    panel = _panel()
    base = vol_targeted_equal_weight(panel, {"target_volatility": 0.2})
    explicit = vol_targeted_equal_weight(panel, {"target_volatility": 0.2, "periods_per_year": 252})
    pd.testing.assert_frame_equal(base, explicit)
    with pytest.raises(ValueError, match="periods_per_year"):
        vol_targeted_equal_weight(panel, {"periods_per_year": 0})


def test_a_crypto_calendar_derisks_harder_on_a_wild_panel() -> None:
    panel = _panel(sigma=0.05)
    w252 = vol_targeted_equal_weight(panel, {"target_volatility": 0.2, "periods_per_year": 252})
    w365 = vol_targeted_equal_weight(panel, {"target_volatility": 0.2, "periods_per_year": 365})
    total252 = w252.groupby("timestamp")["target_weight"].sum()
    total365 = w365.groupby("timestamp")["target_weight"].sum()
    common = total252.index.intersection(total365.index)
    assert (total365.loc[common] <= total252.loc[common] + 1e-12).all()
    assert (total365.loc[common] < total252.loc[common]).any()


def test_declarations_and_configs_load_and_declare_three_variants() -> None:
    declaration = yaml.safe_load(
        Path("configs/research/crypto_majors_voltarget_preregistration.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert declaration["experiment_id"] == "crypto_majors_h8_vol_target_derisk"
    assert declaration["max_trials"] == 3
    assert len(declaration["variants"]) == 3
    assert declaration["selection_criterion"]["subsumption"]["threshold"] == 0.9
    research = yaml.safe_load(
        Path("configs/research/crypto_majors_voltarget_preregistered.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert research["strategy"] == "vol_targeted_equal_weight"
    assert research["strategy_params"]["periods_per_year"] == 365
    walk = yaml.safe_load(
        Path("configs/research/walk_forward_crypto_majors_voltarget_preregistered.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert walk["parameter_grid"]["target_volatility"] == [0.2, 0.3, 0.4]
    h6 = yaml.safe_load(
        Path("configs/research/crypto_majors_trend_preregistration.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert "N=7" in h6["selection_criterion"]["deflated_sharpe"]["also_reported"]


def _equity_csv(directory: Path, equity: np.ndarray) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    ts = pd.date_range("2024-01-01", periods=len(equity), freq="D", tz="UTC")
    pd.DataFrame({"timestamp": ts, "equity": equity}).to_csv(
        directory / "equity_curve_test.csv", index=False
    )


def test_overlap_declares_identical_curves_subsumed_and_independent_ones_not(
    tmp_path: Path,
) -> None:
    rng = np.random.default_rng(5)
    a = 100 * np.cumprod(1 + rng.normal(0, 0.02, 200))
    b = 100 * np.cumprod(1 + rng.normal(0, 0.02, 200))
    _equity_csv(tmp_path / "h6", a)
    _equity_csv(tmp_path / "h8_same", a * 1.5)
    _equity_csv(tmp_path / "h8_other", b)
    same = overlap(tmp_path / "h8_same", tmp_path / "h6")
    assert same["subsumed"] is True
    assert same["correlation"] == pytest.approx(1.0)
    other = overlap(tmp_path / "h8_other", tmp_path / "h6")
    assert other["subsumed"] is False
    assert other["n_days"] == 199
    _equity_csv(tmp_path / "short", a[:10])
    with pytest.raises(OverlapError, match="aligned days"):
        overlap(tmp_path / "short", tmp_path / "h6")
    with pytest.raises(OverlapError, match="no equity_curve_test.csv"):
        overlap(tmp_path / "missing", tmp_path / "h6")
