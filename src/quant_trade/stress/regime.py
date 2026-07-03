"""Regime labels for stress reports."""

from __future__ import annotations


def classify_regime(max_drawdown: float, daily_loss: float) -> str:
    if max_drawdown <= -0.2 or daily_loss <= -0.05:
        return "crisis"
    if max_drawdown <= -0.1 or daily_loss <= -0.03:
        return "stress"
    return "normal"
