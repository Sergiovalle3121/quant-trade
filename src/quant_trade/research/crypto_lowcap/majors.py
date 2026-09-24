"""H8's declared subsumption test: is the vol-target candidate the same bet as H6?

Two strategies whose daily returns move together are one bet, and one bet gets
one count in the deflation. The declaration names the statistic (Pearson
correlation of daily test-window returns) and the threshold (0.9); this
computes it from the two research runs' ``equity_curve_test.csv`` files and
nothing else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

EQUITY_FILENAME = "equity_curve_test.csv"
DEFAULT_THRESHOLD = 0.9


class OverlapError(RuntimeError):
    """Raised when the two runs cannot be compared honestly."""


def _daily_returns(run_dir: Path) -> pd.Series:
    path = run_dir / EQUITY_FILENAME
    if not path.is_file():
        raise OverlapError(f"no {EQUITY_FILENAME} in {run_dir}")
    frame = pd.read_csv(path)
    if "timestamp" not in frame.columns or "equity" not in frame.columns:
        raise OverlapError(f"{path} lacks timestamp/equity columns")
    series = (
        pd.Series(
            pd.to_numeric(frame["equity"], errors="coerce").to_numpy(),
            index=pd.to_datetime(frame["timestamp"], utc=True),
        )
        .dropna()
        .pct_change()
        .dropna()
    )
    return series


def overlap(
    candidate_run_dir: str | Path,
    reference_run_dir: str | Path,
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    if not 0 < threshold <= 1:
        raise OverlapError("threshold must be in (0, 1]")
    left = _daily_returns(Path(candidate_run_dir))
    right = _daily_returns(Path(reference_run_dir))
    aligned = pd.concat([left.rename("candidate"), right.rename("reference")], axis=1).dropna()
    if len(aligned) < 30:
        raise OverlapError(
            f"only {len(aligned)} aligned days; a correlation on fewer than 30 says nothing"
        )
    if aligned["candidate"].std() == 0 or aligned["reference"].std() == 0:
        correlation = 0.0
    else:
        correlation = float(np.corrcoef(aligned["candidate"], aligned["reference"])[0, 1])
    return {
        "artifact": "MAJORS_OVERLAP",
        "evidence_class": "MEASURED",
        "statistic": "pearson correlation of daily test-window returns",
        "candidate_dir": str(candidate_run_dir),
        "reference_dir": str(reference_run_dir),
        "n_days": int(len(aligned)),
        "correlation": correlation,
        "threshold": threshold,
        "subsumed": bool(correlation > threshold),
        "note": (
            "SUBSUMED means the same bet measured twice; it is reported as such, never as a "
            "second confirmation"
        ),
    }


__all__ = ["DEFAULT_THRESHOLD", "EQUITY_FILENAME", "OverlapError", "overlap"]
