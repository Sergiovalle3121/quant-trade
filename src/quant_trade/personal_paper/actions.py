"""Explicit raw-price actions and a causal total-return signal index."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quant_trade.personal_paper.config import PersonalPaperError
from quant_trade.personal_paper.store import PaperStore


def validate_actions(panel: pd.DataFrame) -> None:
    if not {"dividend", "split_ratio"} <= set(panel):
        raise PersonalPaperError("raw prices need explicit dividend and split_ratio columns")
    values = panel[["dividend", "split_ratio"]].apply(pd.to_numeric, errors="coerce")
    if (
        not np.isfinite(values.to_numpy()).all()
        or (values.dividend < 0).any()
        or (values.split_ratio <= 0).any()
    ):
        raise PersonalPaperError("corporate actions must be finite, nonnegative/positive")


def signal_panel(panel: pd.DataFrame, price_basis: str) -> pd.DataFrame:
    if price_basis == "adjusted_total_return":
        return panel
    validate_actions(panel)
    transformed = panel.copy()
    for _, frame in panel.groupby("symbol", sort=False):
        frame = frame.sort_values("timestamp")
        close = frame.close.astype(float)
        # Actions are ex-session values in post-split units. No future action is
        # used in the cumulative index, preserving the observable signal prefix.
        growth = ((close + frame.dividend) * frame.split_ratio / close.shift()).fillna(1.0)
        index_close = growth.cumprod() * close.iloc[0]
        ratio = index_close / close
        for name in ("open", "high", "low", "close"):
            transformed.loc[frame.index, name] = frame[name] * ratio
    if not np.isfinite(transformed[["open", "high", "low", "close"]].to_numpy()).all():
        raise PersonalPaperError("corporate-action signal index is non-finite")
    return transformed


def apply_actions(
    store: PaperStore,
    key: str,
    book: dict[str, Any],
    frame: pd.DataFrame,
    session_date: str,
) -> None:
    validate_actions(frame)
    for row in frame.itertuples():
        symbol = str(row.symbol)
        identity = f"{session_date}:{symbol}"
        action = [float(row.split_ratio), float(row.dividend)]
        seen = book["actions_seen"].get(identity)
        if seen is not None:
            if seen != action:
                raise PersonalPaperError("previously observed corporate action was revised")
            continue
        split, dividend = action
        quantity = book["positions"].get(symbol, 0.0)
        if quantity and (split != 1.0 or dividend != 0.0):
            cash_credit = quantity * split * dividend
            book["positions"][symbol] = quantity * split
            book["cash_usd"] += cash_credit
            if split != 1.0:
                book["last_prices"][symbol] /= split
            store.event(
                "corporate_action",
                {
                    "book": key,
                    "symbol": symbol,
                    "session_date": session_date,
                    "split_ratio": split,
                    "dividend_per_share": dividend,
                    "cash_credit_usd": cash_credit,
                    "dividend_timing": "SIMULATION_EX_DATE_NOT_PAYMENT_DATE",
                },
            )
        book["actions_seen"][identity] = action
