"""Research-only ML reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from quant_trade.ml.config import MLConfig

WARNING = (
    "Research-only supervised ML baseline. No live trading, broker orders, "
    "or profitability claim. real_money_ready=false."
)


def write_model_card(
    config: MLConfig, output_dir: Path, metrics: dict[str, Any], leakage: dict[str, Any]
) -> Path:
    path = output_dir / "model_card.md"
    text = f"""# ML Alpha Lab Model Card

{WARNING}

- Run ID: {config.run_id}
- Model: {config.model}
- Horizon days: {config.horizon_days}
- Leakage status: {leakage.get('status')}
- Direction accuracy: {metrics.get('prediction_direction_accuracy', 0.0):.4f}
- Rank IC approximation: {metrics.get('rank_ic', 0.0):.4f}
- real_money_ready: false

Limitations: deterministic offline baseline for research validation only.
Results may overfit and must not be interpreted as expected live performance.
"""
    path.write_text(text, encoding="utf-8")
    return path
