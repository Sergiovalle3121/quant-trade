"""The money of a real account: deposits, withdrawals and open positions.

An investor choosing a signal, a copy-trading provider or a manager usually
holds an account history, not a backtest. Three things in such a history
can make its headline figure say more than the money does, and track-record
sites show none of them side by side:

* The percentage gain is time-weighted: deposits and withdrawals are taken
  out, so a small account that grew fast and then lost a larger deposit can
  still show a large gain. The money the trading made or lost is the other
  half of the story, and the two are shown together.
* Money added while the account is deep in a drawdown ("topping up") keeps
  a losing account alive and dilutes the loss in percentage terms.
* The balance counts closed trades only. Positions still open when the
  statement was printed can carry a floating loss the balance does not show.

Every figure comes from the uploaded file as supplied: MEASURED when the
audit recomputes it from the rows, DECLARED when it is the platform's own
summary (equity and floating result). Nothing is checked with the broker,
and none of it says how the account will do.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import pandas as pd

from quant_trade.audit.importers import (
    FXBLUE_CSV,
    MQL5_SIGNAL_CSV,
    MT4_STATEMENT_HTML,
    MT5_HISTORY_HTML,
    MT5_HISTORY_XLSX,
    MYFXBOOK_CSV,
    NEAR_EMPTY_DAYS,
    NEAR_EMPTY_FIRST,
    _lead_num,
)
from quant_trade.audit.redflags import RedFlag
from quant_trade.audit.schema import ParsedTrades, declared, measured, not_measured

#: Formats that are account histories rather than backtests.
ACCOUNT_FORMATS: frozenset[str] = frozenset(
    {
        MT5_HISTORY_HTML,
        MT5_HISTORY_XLSX,
        MT4_STATEMENT_HTML,
        # Account-tracking exports: Myfxbook, an MQL5.com signal, FX Blue.
        MYFXBOOK_CSV,
        MQL5_SIGNAL_CSV,
        FXBLUE_CSV,
    }
)

#: The percentage gain overstates the money when it is at least this large ...
INFLATED_MIN_GAIN = 0.10
#: ... and the result on the money deposited is below this share of it.
INFLATED_SHARE = 1.0 / 3.0
#: A deposit made while the flow-adjusted drawdown is this deep is a top-up.
TOP_UP_DRAWDOWN = 0.20
#: Floating loss at the end of the statement, as a share of the balance.
FLOATING_WARN = 0.10
FLOATING_FAIL = 0.30
#: Deposits listed in the report, largest first.
MAX_LISTED = 8

NOT_ACCOUNT = "the file is a backtest, not an account history"
GAIN_NOTE = (
    "time-weighted: deposits and withdrawals are taken out, as track-record sites compute gain"
)
MONEY_NOTE = "closed trades after commission and swap, in the account currency"
ON_DEPOSITS_NOTE = "trading result / money deposited"
NEAR_EMPTY_NOTE = (
    "days with a trade result larger than the balance a withdrawal left, measured on the "
    "balance before that withdrawal"
)
BALANCE_BEFORE_NOTE = "earlier deposits and withdrawals plus trades closed before it"
FLOATING_NOTE = "the platform's own summary at the time of the statement"


def is_account_history(data: dict[str, Any]) -> bool:
    """True when a stored audit result was run on an account history."""
    return str((data.get("inputs") or {}).get("source_format")) in ACCOUNT_FORMATS


def _drawdown_on(frame: pd.DataFrame, moment: datetime) -> float | None:
    """Flow-adjusted drawdown on the last curve point before ``moment``."""
    stamps = pd.to_datetime(frame["timestamp"], utc=True)
    before = frame["equity"].to_numpy(dtype=float)[(stamps < pd.Timestamp(moment)).to_numpy()]
    if len(before) == 0:
        return None
    peak = float(before.max())
    return float(before[-1] / peak - 1.0) if peak > 0 else None


def _balance_before(
    moment: datetime, flows: Sequence[tuple[datetime, float]], trades: ParsedTrades
) -> float:
    fees = trades.fees or [0.0] * len(trades.trades)
    closed = sum(
        trade.pnl - fee
        for trade, fee in zip(trades.trades, fees, strict=True)
        if trade.exit_time < moment
    )
    return float(sum(amount for when, amount in flows if when < moment) + closed)


def _declared_number(metadata: dict[str, str], key: str) -> float | None:
    return _lead_num(metadata.get(key))


def account_review(
    *,
    source_format: str,
    cash_flows: Sequence[tuple[datetime, float]],
    trades: ParsedTrades | None,
    frame: pd.DataFrame,
    metadata: dict[str, str],
) -> tuple[dict[str, Any], list[RedFlag]]:
    """Deposits, withdrawals and open positions of an uploaded account history."""
    if source_format not in ACCOUNT_FORMATS or trades is None or not trades.trades:
        return {"status": "NOT_MEASURED", "reason": NOT_ACCOUNT}, []
    flows = sorted(cash_flows)
    first_entry = min(trade.entry_time for trade in trades.trades)
    deposits = [(when, amount) for when, amount in flows if amount > 0]
    withdrawals = [(when, amount) for when, amount in flows if amount < 0]
    deposited = float(sum(amount for _, amount in deposits))
    withdrawn = float(-sum(amount for _, amount in withdrawals))
    fees = trades.fees or [0.0] * len(trades.trades)
    money = float(sum(t.pnl for t in trades.trades) - sum(fees))
    equity = frame["equity"].to_numpy(dtype=float)
    gain = float(equity[-1] / equity[0] - 1.0) if equity[0] > 0 else None

    later: list[dict[str, Any]] = []
    for when, amount in deposits:
        if when <= first_entry:
            continue
        drawdown = _drawdown_on(frame, when)
        later.append(
            {
                "time": when.isoformat(),
                "amount": measured(amount),
                "balance_before": measured(
                    _balance_before(when, flows, trades), BALANCE_BEFORE_NOTE
                ),
                "drawdown": (
                    measured(drawdown, "flow-adjusted drawdown on the day before")
                    if drawdown is not None
                    else not_measured("no curve point before the deposit")
                ),
                "top_up": drawdown is not None and drawdown <= -TOP_UP_DRAWDOWN,
            }
        )
    top_ups = [item for item in later if item["top_up"]]

    floating = _declared_number(metadata, "declared_floating_pnl")
    final_equity = _declared_number(metadata, "declared_final_equity")
    if final_equity is None:
        final_equity = _declared_number(metadata, "declared_equity")
    balance = _declared_number(metadata, "declared_balance")
    if balance is None and final_equity is not None and floating is not None:
        balance = final_equity - floating
    floating_share = (
        floating / balance if floating is not None and balance and balance > 0 else None
    )

    on_deposits = money / deposited if deposited > 0 else None
    review: dict[str, Any] = {
        "status": "MEASURED",
        "deposits": {"count": measured(len(deposits)), "total": measured(deposited)},
        "withdrawals": {"count": measured(len(withdrawals)), "total": measured(withdrawn)},
        "later_deposits": measured(len(later)),
        "trading_result": measured(money, MONEY_NOTE),
        "percent_gain": measured(gain, GAIN_NOTE) if gain is not None else not_measured("n/a"),
        "result_on_deposits": (
            measured(on_deposits, ON_DEPOSITS_NOTE)
            if on_deposits is not None
            else not_measured("the file lists no deposit")
        ),
        "withdrawn_share": (
            measured(withdrawn / deposited, "withdrawn / deposited")
            if deposited > 0
            else not_measured("the file lists no deposit")
        ),
        "top_ups": measured(len(top_ups)),
        "floating_pnl": (
            declared(floating, FLOATING_NOTE)
            if floating is not None
            else not_measured("the file does not state the floating result")
        ),
        "floating_share": (
            declared(floating_share, "floating result / balance")
            if floating_share is not None
            else not_measured("the file does not state the floating result")
        ),
        "deposit_list": sorted(later, key=lambda item: -item["amount"]["value"])[:MAX_LISTED],
        # A history that opens with trades, not with the deposit that funded
        # the account, may have been cut at the start (an export from a date,
        # a later account); the percentage then starts from a mid-way balance.
        "starts_with_deposit": any(when <= first_entry for when, _ in deposits),
        "first_trade": first_entry.isoformat(),
    }
    near_empty = _lead_num(metadata.get(NEAR_EMPTY_DAYS))
    if near_empty:
        # A trade won or lost more than a withdrawal left: it was traded on an
        # almost empty account, and the curve measures it on the balance before.
        review["near_empty"] = {
            "days": measured(int(near_empty), NEAR_EMPTY_NOTE),
            "first": str(metadata.get(NEAR_EMPTY_FIRST, "")),
        }

    flags: list[RedFlag] = []
    if (
        gain is not None
        and gain >= INFLATED_MIN_GAIN
        and (money <= 0 or (on_deposits is not None and on_deposits < gain * INFLATED_SHARE))
    ):
        flags.append(
            RedFlag(
                "GAIN_INFLATED_BY_FLOWS",
                "WARN",
                f"the time-weighted gain is {gain:.0%} while trading made {money:,.2f} on "
                f"{deposited:,.2f} deposited; deposits and withdrawals shape the percentage",
                gain,
            )
        )
    if top_ups:
        flags.append(
            RedFlag(
                "DEPOSIT_DURING_DRAWDOWN",
                "WARN",
                f"{len(top_ups)} deposit(s) arrived while the account was at least "
                f"{TOP_UP_DRAWDOWN:.0%} below its peak",
                len(top_ups),
            )
        )
    if floating_share is not None and floating_share <= -FLOATING_WARN:
        flags.append(
            RedFlag(
                "FLOATING_LOSS_AT_END",
                "FAIL" if floating_share <= -FLOATING_FAIL else "WARN",
                f"open positions carried a floating loss of {-floating_share:.0%} of the "
                "balance when the statement was printed; the balance does not show it",
                floating_share,
            )
        )
    review["clean"] = not flags
    return review, flags


__all__ = [
    "ACCOUNT_FORMATS",
    "FLOATING_FAIL",
    "FLOATING_WARN",
    "INFLATED_MIN_GAIN",
    "TOP_UP_DRAWDOWN",
    "account_review",
    "is_account_history",
]
