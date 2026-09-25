"""The ``/ejemplo`` report: a full audit of synthetic data, built in memory.

A visitor sees what a paid report contains before uploading anything. The
input is an MT5 Strategy Tester report, an optimisation export and a live
account statement generated from a fixed seed: nobody's account, strategy
or market data. The engine, the importers and the renderer are the
production ones, so the sample shows exactly what a client gets, including
an unflattering class when the synthetic data earns one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from quant_trade.audit.engine import run_audit
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs

SAMPLE_SEED = 20260924
SAMPLE_DAYS = 500
#: Business days before the main 500, from their own random stream, so the
#: history starts on 2 January 2020: it covers the covid fall and the 2022
#: windows in full, and the recent-period section is measured.
SAMPLE_LEAD_DAYS = 782
SAMPLE_PASSES = 120
#: The sample robot trades two majors (the same pip value in a USD account), so
#: the per-instrument section has something to show; each trade's result is
#: the same whichever pair it lands on.
SAMPLE_SYMBOLS = ("EURUSD", "AUDUSD")
#: Where each synthetic pair's price path starts.
_START_PRICE = {"EURUSD": 1.1, "GBPUSD": 1.27, "AUDUSD": 0.66}
#: Hours a sample trade stays open, drawn apart from its result, so the hold
#: times vary as a real robot's do.
SAMPLE_HOLD_HOURS = (1.0, 7.0)
#: A fixed clock so the sample (and its hashes) never change between restarts.
SAMPLE_NOW = datetime(2026, 9, 24, tzinfo=UTC)
SAMPLE_BOOTSTRAP = 500
#: The sample's live account: 120 business days after the backtest, a fifth of
#: its size and a thinner edge, as live trading often has.
SAMPLE_LIVE_DAYS = 120
SAMPLE_LIVE_START = "2025-01-06"
#: Business days of the backtest the live account also traded, for pairing.
SAMPLE_LIVE_OVERLAP = 60
#: The live account's money: first deposit, a top-up, a withdrawal and the
#: floating result of the position still open at the end.
SAMPLE_LIVE_DEPOSIT = 1_000.0
SAMPLE_LIVE_TOP_UP = 500.0
SAMPLE_LIVE_WITHDRAWAL = 300.0
SAMPLE_LIVE_FLOATING = 35.0


def _money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def synthetic_mt5_report(
    days: int = SAMPLE_DAYS,
    *,
    edge_pips: float = 4.0,
    seed: int = SAMPLE_SEED,
    lots: float = 0.5,
    start: str = "2023-01-02",
    lead_days: int = 0,
    symbols: tuple[str, ...] = ("EURUSD",),
    hold_hours: tuple[float, float] | None = None,
) -> bytes:
    """An MT5 tester HTML report (UTF-16 LE with BOM, as the terminal writes
    it) with one round trip per business day. Synthetic by design.

    ``lead_days`` business days before ``start`` come from their own random
    stream, so the ``days`` from ``start`` on keep the same results. The pair
    of each trade (from ``symbols``, pips worth the same) and, with
    ``hold_hours``, how long it stays open come from their own streams too,
    so neither changes any result; without it every trade lasts 3.5 hours."""
    rng = np.random.default_rng(seed)
    lead_rng = np.random.default_rng(seed + 2)
    # Entry hours come from their own stream so the trades' results stay the
    # same; they spread the entries over the day like an intraday strategy.
    hours = np.random.default_rng(seed + 1).choice([2, 5, 9, 11, 14, 16, 19], size=days)
    lead_hours = np.random.default_rng(seed + 3).choice([2, 5, 9, 11, 14, 16, 19], size=lead_days)
    main_dates = pd.bdate_range(start, periods=days)
    lead_dates = pd.bdate_range(end=main_dates[0] - pd.offsets.BDay(1), periods=lead_days)
    dates = lead_dates.append(main_dates) if lead_days else main_dates
    hours = np.concatenate([lead_hours, hours])
    streams = [lead_rng] * lead_days + [rng] * days
    pairs = np.random.default_rng(seed + 4).choice(len(symbols), size=len(dates))
    holds = np.random.default_rng(seed + 5).uniform(*(hold_hours or (3.5, 3.5)), size=len(dates))
    balance = 10_000.0
    prices = {symbol: _START_PRICE.get(symbol, 1.1) for symbol in symbols}
    first = dates[0].strftime("%Y.%m.%d")
    rows = [
        f"<tr><td>{first} 00:00:00</td><td>1</td><td></td><td>balance</td><td></td><td></td>"
        "<td></td><td></td><td>0.00</td><td>0.00</td><td>10 000.00</td><td>10 000.00</td>"
        "<td></td></tr>"
    ]
    deal = 2
    # 7.00 per lot per side: 3.50 at the sample's 0.5 lots.
    fee = round(7.0 * lots, 2)
    for day, hour, draw, pair, hold in zip(dates, hours, streams, pairs, holds, strict=True):
        symbol = symbols[pair]
        side = "buy" if draw.random() < 0.5 else "sell"
        sign = 1.0 if side == "buy" else -1.0
        entry = round(prices[symbol], 5)
        pips = edge_pips + draw.normal(0.0, 25.0)
        exit_price = round(entry + sign * pips * 0.0001, 5)
        prices[symbol] = exit_price
        # Whole minutes, and never past the day's last hour.
        minutes = int(round(min(hold, 23.9 - hour) * 60))
        exit_at = day + pd.Timedelta(hours=int(hour), minutes=minutes)
        profit = round(pips * 10.0 * lots, 2)
        stamp = day.strftime("%Y.%m.%d")
        balance -= fee
        rows.append(
            f"<tr><td>{stamp} {hour:02d}:00:00</td><td>{deal}</td><td>{symbol}</td><td>{side}</td>"
            f"<td>in</td><td>{lots}</td><td>{entry:.5f}</td><td>{deal}</td><td>{-fee:.2f}</td>"
            f"<td>0.00</td><td>0.00</td><td>{_money(balance)}</td><td></td></tr>"
        )
        balance += profit - fee
        close = "sell" if side == "buy" else "buy"
        rows.append(
            f"<tr><td>{exit_at:%Y.%m.%d %H:%M}:00</td><td>{deal + 1}</td><td>{symbol}</td>"
            f"<td>{close}</td>"
            f"<td>out</td><td>{lots}</td><td>{exit_price:.5f}</td><td>{deal + 1}</td>"
            f"<td>{-fee:.2f}</td><td>0.00</td><td>{profit:.2f}</td><td>{_money(balance)}</td>"
            "<td></td></tr>"
        )
        deal += 2
    header = (
        "<tr><td><b>Time</b></td><td><b>Deal</b></td><td><b>Symbol</b></td><td><b>Type</b></td>"
        "<td><b>Direction</b></td><td><b>Volume</b></td><td><b>Price</b></td>"
        "<td><b>Order</b></td><td><b>Commission</b></td><td><b>Swap</b></td>"
        "<td><b>Profit</b></td><td><b>Balance</b></td><td><b>Comment</b></td></tr>"
    )
    end = dates[-1].strftime("%Y.%m.%d")
    html_text = (
        "<html><head><title>Strategy Tester Report</title></head><body><table>"
        "<tr><td colspan='13'><b>Strategy Tester Report</b></td></tr>"
        "<tr><td colspan='3'>Expert:</td><td colspan='10'><b>SyntheticSampleEA</b></td></tr>"
        "<tr><td colspan='3'>Symbol:</td><td colspan='10'><b>EURUSD</b></td></tr>"
        f"<tr><td colspan='3'>Period:</td><td colspan='10'><b>H1 ({first} - {end})</b>"
        "</td></tr>"
        "<tr><td colspan='3'>Currency:</td><td colspan='10'><b>USD</b></td></tr>"
        "<tr><td colspan='3'>Initial Deposit:</td><td colspan='10'><b>10 000.00</b></td></tr>"
        "</table><table>"
        "<tr><th colspan='13'><b>Deals</b></th></tr>" + header + "".join(rows) + "</table>"
        "</body></html>"
    )
    return b"\xff\xfe" + html_text.encode("utf-16-le")


_MYFXBOOK_HEAD = (
    "Tags,Ticket,Open Date,Close Date,Symbol,Action,Units/Lots,SL,TP,Open Price,Close Price,"
    "Commission,Swap,Pips,Profit,Gain,Comment,Magic Number,Duration (DD:HH:MM:SS)"
)


def _stamp(moment: pd.Timestamp) -> str:
    return moment.strftime("%m/%d/%Y %H:%M")


def _sample_report() -> bytes:
    """The sample's backtest: two pairs, varied hold times, over two years."""
    return synthetic_mt5_report(
        lead_days=SAMPLE_LEAD_DAYS, symbols=SAMPLE_SYMBOLS, hold_hours=SAMPLE_HOLD_HOURS
    )


def synthetic_live_statement() -> bytes:
    """The sample's live account as a Myfxbook CSV export. Synthetic by design.

    It runs the same robot at 0.1 lots on the last ``SAMPLE_LIVE_OVERLAP``
    business days of the backtest and on ``SAMPLE_LIVE_DAYS`` after it, so the
    report can pair trades on the shared dates (a few are skipped and a few
    are extra, as on a real account) and compare the rest. A deposit arrives
    after the deepest losing stretch, a withdrawal near the end and one
    position is still open when the statement is printed, so every part of
    "the real money of the account" has something to show.
    """
    from quant_trade.audit.importers import import_report

    imported = import_report(_sample_report(), "SyntheticSampleEA.html")
    backtest = imported.trades
    rng = np.random.default_rng(SAMPLE_SEED + 7)
    # The pair of each trade after the backtest, from its own stream.
    pair_rng = np.random.default_rng(SAMPLE_SEED + 8)
    lots, fee, pip = 0.1, 0.70, 0.0001
    trades: list[tuple[pd.Timestamp, pd.Timestamp, str, float, float, str]] = []
    shared = sorted(
        zip(backtest.trades, backtest.sides, imported.symbols, strict=True),
        key=lambda pair: pair[0].entry_time,
    )[-SAMPLE_LIVE_OVERLAP:]
    for trade, side, symbol in shared:
        if rng.random() < 0.12:
            continue  # the account skipped this signal
        sign = 1.0 if side == "long" else -1.0
        delay = pd.Timedelta(minutes=int(rng.integers(0, 25)))
        # Live fills are a little worse than the tester's on both ends.
        entry = trade.entry_price + sign * pip * 0.4
        exit_price = trade.exit_price - sign * pip * 0.6
        opened = pd.Timestamp(trade.entry_time).tz_localize(None) + delay
        closed = pd.Timestamp(trade.exit_time).tz_localize(None) + delay
        trades.append((opened, closed, side, entry, exit_price, symbol))
    prices = {symbol: trade.exit_price for trade, _, symbol in shared}
    for index, day in enumerate(pd.bdate_range(SAMPLE_LIVE_START, periods=SAMPLE_LIVE_DAYS)):
        symbol = SAMPLE_SYMBOLS[int(pair_rng.integers(0, len(SAMPLE_SYMBOLS)))]
        side = "long" if rng.random() < 0.5 else "short"
        sign = 1.0 if side == "long" else -1.0
        # A bad stretch a month in, then the thinner live edge.
        pips = (-22.0 if 20 <= index < 32 else 1.0) + rng.normal(0.0, 25.0)
        opened = day + pd.Timedelta(hours=int(rng.choice([2, 5, 9, 11, 14, 16, 19])))
        entry = round(prices.get(symbol, _START_PRICE.get(symbol, 1.1)), 5)
        prices[symbol] = round(entry + sign * pips * pip, 5)
        closed = opened + pd.Timedelta(hours=3, minutes=30)
        trades.append((opened, closed, side, entry, prices[symbol], symbol))
    for _ in range(4):
        # Trades the backtest never took: the same robot rarely matches every signal.
        trade, _, symbol = shared[int(rng.integers(0, len(shared)))]
        opened = pd.Timestamp(trade.entry_time).tz_localize(None) + pd.Timedelta(hours=5)
        entry = trade.entry_price
        closed = opened + pd.Timedelta(hours=2)
        trades.append((opened, closed, "long", entry, entry + 3 * pip, symbol))
    trades.sort()

    # The top-up lands after the bad stretch's deepest point.
    stretch_end = pd.bdate_range(SAMPLE_LIVE_START, periods=SAMPLE_LIVE_DAYS)[32]
    first = trades[0][0].normalize()
    flows: list[tuple[pd.Timestamp, float]] = [(first, SAMPLE_LIVE_DEPOSIT)]
    balance, peak, worst, worst_at = SAMPLE_LIVE_DEPOSIT, SAMPLE_LIVE_DEPOSIT, 0.0, trades[0][1]
    rows: list[str] = []
    ticket = 5000
    for opened, closed, side, entry, exit_price, symbol in trades:
        sign = 1.0 if side == "long" else -1.0
        pips = sign * (exit_price - entry) / pip
        profit = round(pips * 10.0 * lots - fee, 2)
        balance += profit
        peak = max(peak, balance)
        if closed < stretch_end and balance / peak - 1.0 < worst:
            worst, worst_at = balance / peak - 1.0, closed
        rows.append(
            f",{ticket},{_stamp(opened)},{_stamp(closed)},{symbol},"
            f"{'Buy' if side == 'long' else 'Sell'},{lots:.2f},0,0,{entry:.5f},{exit_price:.5f},"
            f"{-fee:.4f},0.0000,{pips:.1f},{profit:.2f},0,,7,00:03:30:00"
        )
        ticket += 1
    flows.append((worst_at + pd.Timedelta(hours=2), SAMPLE_LIVE_TOP_UP))
    flows.append((trades[-12][1] + pd.Timedelta(hours=2), -SAMPLE_LIVE_WITHDRAWAL))
    for moment, amount in flows:
        action = "Deposit" if amount > 0 else "Withdrawal"
        rows.append(
            f",{ticket},{_stamp(moment)},,,{action},0.010,0,0,0,0,0,0,0.0,{amount:.2f},0,"
            f"{action},0,00:00:00:00"
        )
        ticket += 1
    rows.sort(key=lambda row: pd.Timestamp(row.split(",")[2]))
    last = trades[-1][1] + pd.Timedelta(hours=1)
    open_rows = [
        "",
        "Open Trades",
        "Tags,Ticket,Open Date,Symbol,Action,Lots,Open Price,TP,SL,Profit,Pips,Swap",
        f",{ticket},{_stamp(last)},EURUSD,Sell,{lots:.2f},1.10000,0,0,"
        f"{-SAMPLE_LIVE_FLOATING:.2f},{-SAMPLE_LIVE_FLOATING:.1f},0",
    ]
    return ("\n".join([_MYFXBOOK_HEAD, *rows, *open_rows]) + "\n").encode("utf-8")


def synthetic_mt5_optimization(passes: int = SAMPLE_PASSES) -> bytes:
    """An MT5 optimisation export (SpreadsheetML) listing ``passes`` passes."""
    names = ["Pass", "Result", "Profit", "Trades", "FastMA", "SlowMA"]
    head = "".join(f'<Cell><Data ss:Type="String">{name}</Data></Cell>' for name in names)
    rows = []
    for index in range(passes):
        values = [index, 10_000 + index, index, 100, 5 + index % 20, 50 + index // 20]
        rows.append(
            "<Row>"
            + "".join(f'<Cell><Data ss:Type="Number">{value}</Data></Cell>' for value in values)
            + "</Row>"
        )
    return (
        '<?xml version="1.0"?>\n<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        '<Worksheet ss:Name="Tester Optimizator Results"><Table>'
        f"<Row>{head}</Row>" + "".join(rows) + "</Table></Worksheet></Workbook>"
    ).encode("utf-8")


def sample_result(locale: str = "es", *, bootstrap_samples: int = SAMPLE_BOOTSTRAP) -> AuditResult:
    """The sample audit in ``locale``; deterministic for a given sample size."""
    declared = DeclaredMetadata(
        trials=SAMPLE_PASSES,
        cost_bps_per_side=1.0,
        oos_start="2024-06-03",
        description="",
        benchmark_applicable=False,
        locale=locale if locale in ("es", "en") else "es",
        challenge=None,
    )
    inputs = build_inputs(
        None,
        declared,
        report_bytes=_sample_report(),
        report_filename="SyntheticSampleEA.html",
        optimization_bytes=synthetic_mt5_optimization(),
        live_bytes=synthetic_live_statement(),
        live_filename="SyntheticSampleLive.csv",
    )
    return run_audit(inputs, bootstrap_samples=bootstrap_samples, now=SAMPLE_NOW)


__all__ = [
    "SAMPLE_NOW",
    "sample_result",
    "synthetic_live_statement",
    "synthetic_mt5_optimization",
    "synthetic_mt5_report",
]
