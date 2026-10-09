"""The ``/ejemplo`` report: a full audit of synthetic data, built in memory.

A visitor sees what a paid report contains before uploading anything. The
input is an MT5 Strategy Tester report, an optimisation export and a live
account statement generated from a fixed seed: nobody's account, strategy
or market data. The engine, the importers and the renderer are the
production ones, so the sample shows exactly what a client gets, including
an unflattering class when the synthetic data earns one.

The ``/ejemplo-senal`` report is the second sample, for whoever is about to
copy a signal: the Myfxbook export of a made-up grid account
(``synthetic_signal_statement``), declared as a strategy the client is about
to buy or copy (``signal_sample_result``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
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


def sample_result(
    locale: str = "es",
    *,
    bootstrap_samples: int = SAMPLE_BOOTSTRAP,
    market: Callable[[str], pd.Series | None] | None = None,
) -> AuditResult:
    """The sample audit in ``locale``; deterministic for a given sample size.

    ``market`` reads public series already in memory (the service's cache),
    so the sample shows the same public-data lines an upload gets; without
    it the sample is built offline."""
    declared = DeclaredMetadata(
        trials=SAMPLE_PASSES,
        cost_bps_per_side=1.0,
        oos_start="2024-06-03",
        description="",
        benchmark_applicable=False,
        locale=locale if locale in ("es", "en", "pt") else "es",
        challenge=None,
        # An optimised EA, declared as the client's own: the landing speaks to
        # whoever is about to pay for a challenge with their own robot, so the
        # sample shows the developer's steps (``audit/ownership.py``).
        ownership="own",
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
    # The public sample is one fixed, synthetic record. A random id would
    # change its JSON seal and PDF bytes on every process restart.
    return run_audit(
        inputs,
        bootstrap_samples=bootstrap_samples,
        now=SAMPLE_NOW,
        audit_id="sample",
        market=market,
    )


# ---------------------------------------------------------------------------
# The signal sample (/ejemplo-senal): an account a copier is about to follow
# ---------------------------------------------------------------------------

#: The signal's Myfxbook export is generated from this seed: the hourly noise of
#: each pair from ``SIGNAL_SEED + i`` and the robot's own choices (pair, side,
#: pause between baskets) from ``SIGNAL_SEED + 10``.
SIGNAL_SEED = 20261009
#: Twelve months of trading, Monday to Friday, 01:00 to 21:00 on the hour.
SIGNAL_START = "2025-09-22"
SIGNAL_END = "2026-09-18"
SIGNAL_SYMBOLS = ("EURUSD", "GBPUSD")
#: The robot: a basket opens at ``SIGNAL_LOTS``, adds an entry
#: ``SIGNAL_GRID_FACTOR`` times larger each time the price moves
#: ``SIGNAL_GRID_PIPS`` against the last one (``SIGNAL_GRID_ENTRIES`` at most),
#: closes whole ``SIGNAL_TARGET_PIPS`` past its average price, or at a loss
#: ``SIGNAL_STOP_PIPS`` past its last entry once it is full; after each losing
#: basket the next one starts ``SIGNAL_RECOVERY`` times larger.
SIGNAL_LOTS = 0.04
SIGNAL_GRID_PIPS = 20.0
SIGNAL_GRID_FACTOR = 1.5
SIGNAL_GRID_ENTRIES = 6
SIGNAL_TARGET_PIPS = 10.0
SIGNAL_STOP_PIPS = 30.0
SIGNAL_RECOVERY = 2.0
#: Commission per lot (round trip) and swap per lot and night, in USD.
SIGNAL_COMMISSION = 7.0
SIGNAL_SWAP = 1.5
#: The market ranges most of the year, which is where a grid looks smooth: hourly
#: noise (pips) pulled back towards a level by ``SIGNAL_PULL`` of the gap each
#: hour.
SIGNAL_NOISE_PIPS = 6.0
SIGNAL_PULL = 0.03
#: Moves against the open basket, which is where a grid is not smooth: from a
#: date, ``pips`` an hour against each basket opened from then on, until
#: ``stops`` of them have closed at a loss. With ``settle``, the move stops
#: ``settle`` pips past the basket's last entry once the basket is full, and the
#: market ranges there (pulled by ``SIGNAL_SETTLED_PULL``): that basket is
#: still open, at a floating loss, when the statement is printed.
SIGNAL_TRENDS: tuple[tuple[str, int, float, float | None], ...] = (
    ("2026-03-16", 1, 4.0, None),
    ("2026-06-08", 2, 4.0, None),
    ("2026-09-14", 1, 4.0, None),
    ("2026-09-15", 1, 3.0, 10.0),
)
SIGNAL_SETTLED_PULL = 0.3
#: The account's money: the first deposit, the top-up made at 09:30 on the
#: business day after the first losing basket (deep in the drawdown) and a
#: withdrawal.
SIGNAL_DEPOSIT = 1_000.0
SIGNAL_TOP_UP = 4_000.0
SIGNAL_WITHDRAWAL = 600.0
SIGNAL_WITHDRAWAL_AT = "2026-08-03 10:00"
_PIP = 0.0001
#: The signal's pairs in a USD account: 100 000 units a lot, so a pip of one
#: lot is worth 10 on both.
_LOT_UNITS = 100_000
_SIGNAL_START_PRICE = {"EURUSD": 1.1, "GBPUSD": 1.27}
_SIGNAL_MAGIC = 92025


@dataclass
class _Basket:
    """The robot's open positions on one pair and side: (time, price, lots)."""

    symbol: str
    sign: float
    opened: pd.Timestamp
    entries: list[tuple[pd.Timestamp, float, float]] = field(default_factory=list)
    #: The move against it (an index of ``SIGNAL_TRENDS``), if any.
    trend: int | None = None
    settled: bool = False

    def behind(self, price: float) -> float:
        """Pips the price is past the last entry, against the basket."""
        return -self.sign * (price - self.entries[-1][1]) / _PIP

    def ahead(self, price: float) -> float:
        """Pips the price is past the average entry, in the basket's favour."""
        lots = sum(entry[2] for entry in self.entries)
        average = sum(entry[1] * entry[2] for entry in self.entries) / lots
        return self.sign * (price - average) / _PIP


#: A closed trade: opened, closed, symbol, sign, lots, entry, exit, commission, swap, gross.
_ClosedTrade = tuple[
    pd.Timestamp, pd.Timestamp, str, float, float, float, float, float, float, float
]


def _signal_history() -> tuple[
    list[_ClosedTrade], list[tuple[pd.Timestamp, float]], _Basket | None, dict[str, float]
]:
    """The robot's closed trades, the account's money moves, the basket still
    open at the end and the last price of each pair."""
    clock = pd.date_range(f"{SIGNAL_START} 01:00", f"{SIGNAL_END} 21:00", freq="h")
    clock = clock[(clock.dayofweek < 5) & (clock.hour >= 1) & (clock.hour <= 21)]
    noise = {
        symbol: np.random.default_rng(SIGNAL_SEED + i).normal(0.0, SIGNAL_NOISE_PIPS, len(clock))
        for i, symbol in enumerate(SIGNAL_SYMBOLS)
    }
    choices = np.random.default_rng(SIGNAL_SEED + 10)
    level = dict(_SIGNAL_START_PRICE)
    price = dict(_SIGNAL_START_PRICE)
    flows = [(clock[0] - pd.Timedelta(minutes=30), SIGNAL_DEPOSIT)]
    due = [(pd.Timestamp(SIGNAL_WITHDRAWAL_AT), -SIGNAL_WITHDRAWAL)]
    closed: list[_ClosedTrade] = []
    basket: _Basket | None = None
    pause = 0
    losses_in_row = 0
    stops = 0
    stopped = [0] * len(SIGNAL_TRENDS)
    for step, now in enumerate(clock):
        for moment, amount in [item for item in due if item[0] <= now]:
            due.remove((moment, amount))
            flows.append((moment, amount))
        # The move against the open basket, if one applies to it.
        push = 0.0
        if basket is not None and basket.trend is None:
            basket.trend = next(
                (
                    index
                    for index, (start, count, _, _) in enumerate(SIGNAL_TRENDS)
                    if pd.Timestamp(start) <= basket.opened and stopped[index] < count
                ),
                None,
            )
        if basket is not None and basket.trend is not None:
            _, _, pips, settle = SIGNAL_TRENDS[basket.trend]
            full = len(basket.entries) >= SIGNAL_GRID_ENTRIES
            if not basket.settled and settle is not None and full:
                basket.settled = basket.behind(price[basket.symbol]) >= settle
                if basket.settled:
                    level[basket.symbol] = price[basket.symbol]
            if not basket.settled:
                push = -basket.sign * pips
        for symbol in SIGNAL_SYMBOLS:
            mine = basket is not None and basket.symbol == symbol
            drift = push if mine else 0.0
            settled = mine and basket is not None and basket.settled
            pull = SIGNAL_SETTLED_PULL if settled else SIGNAL_PULL
            level[symbol] += drift * _PIP
            gap = (level[symbol] - price[symbol]) / _PIP
            move = drift + pull * gap + noise[symbol][step]
            price[symbol] = round(price[symbol] + move * _PIP, 5)
        if basket is None:
            if pause:
                pause -= 1
                continue
            symbol = SIGNAL_SYMBOLS[int(choices.integers(0, len(SIGNAL_SYMBOLS)))]
            sign = 1.0 if choices.random() < 0.5 else -1.0
            lots = round(SIGNAL_LOTS * SIGNAL_RECOVERY**losses_in_row, 2)
            basket = _Basket(symbol, sign, now, [(now, price[symbol], lots)])
            continue
        now_price = price[basket.symbol]
        target = basket.ahead(now_price) >= SIGNAL_TARGET_PIPS
        if not target:
            if len(basket.entries) < SIGNAL_GRID_ENTRIES:
                if basket.behind(now_price) >= SIGNAL_GRID_PIPS:
                    first = basket.entries[0][2]
                    lots = round(first * SIGNAL_GRID_FACTOR ** len(basket.entries), 2)
                    basket.entries.append((now, now_price, lots))
                continue
            if basket.behind(now_price) < SIGNAL_STOP_PIPS:
                continue
        result = 0.0
        for opened, entry, lots in basket.entries:
            gross = round(basket.sign * (now_price - entry) * _LOT_UNITS * lots, 2)
            commission = round(-SIGNAL_COMMISSION * lots, 2)
            swap = round(-SIGNAL_SWAP * lots * (now.normalize() - opened.normalize()).days, 2)
            trade = (opened, now, basket.symbol, basket.sign, lots, entry, now_price)
            closed.append((*trade, commission, swap, gross))
            result += gross + commission + swap
        if not target:
            stops += 1
            if basket.trend is not None:
                stopped[basket.trend] += 1
            if stops == 1:
                top_up = (now + pd.offsets.BDay(1)).normalize() + pd.Timedelta(hours=9, minutes=30)
                due.append((top_up, SIGNAL_TOP_UP))
        losses_in_row = losses_in_row + 1 if result < 0 else 0
        basket = None
        pause = int(choices.integers(1, 7))
    return closed, flows, basket, price


def _duration(start: pd.Timestamp, end: pd.Timestamp) -> str:
    seconds = int((end - start).total_seconds())
    days, seconds = divmod(seconds, 86_400)
    hours, seconds = divmod(seconds, 3_600)
    return f"{days:02d}:{hours:02d}:{seconds // 60:02d}:00"


def synthetic_signal_statement() -> bytes:
    """The signal sample's account as a Myfxbook CSV export. Synthetic by design.

    Twelve months of a grid robot on two majors (``_signal_history``): deposits
    and a withdrawal as Myfxbook lists them, the top-up made the business day
    after the first losing basket, and the basket the last move left full and
    open in the "Open Trades" block, with the floating loss the balance does
    not show. Rows are in the order the trades closed; ``Profit`` is net of
    commission and swap, as Myfxbook prints it.
    """
    closed, flows, basket, price = _signal_history()
    rows: list[tuple[pd.Timestamp, pd.Timestamp, str]] = []
    for opened, closed_at, symbol, sign, lots, entry, exit_price, commission, swap, gross in closed:
        rows.append(
            (
                closed_at,
                opened,
                f"{_stamp(opened)},{_stamp(closed_at)},{symbol},{'Buy' if sign > 0 else 'Sell'},"
                f"{lots:.2f},0,0,{entry:.5f},{exit_price:.5f},{commission:.2f},{swap:.2f},"
                f"{sign * (exit_price - entry) / _PIP:.1f},{gross + commission + swap:.2f},0.00,,"
                f"{_SIGNAL_MAGIC},{_duration(opened, closed_at)}",
            )
        )
    for moment, amount in flows:
        action = "Deposit" if amount > 0 else "Withdrawal"
        rows.append(
            (
                moment,
                moment,
                f"{_stamp(moment)},,,{action},0.00,0,0,0,0,0,0,0.0,{amount:.2f},0,{action},0,"
                "00:00:00:00",
            )
        )
    rows.sort(key=lambda row: (row[0], row[1]))
    ticket = 81_000
    lines = [_MYFXBOOK_HEAD]
    for _, _, text in rows:
        lines.append(f",{ticket},{text}")
        ticket += 1
    if basket is not None:
        lines += [
            "",
            "Open Trades",
            "Tags,Ticket,Open Date,Symbol,Action,Lots,Open Price,TP,SL,Profit,Pips,Swap",
        ]
        now_price = price[basket.symbol]
        for opened, entry, lots in basket.entries:
            gross = round(basket.sign * (now_price - entry) * _LOT_UNITS * lots, 2)
            lines.append(
                f",{ticket},{_stamp(opened)},{basket.symbol},"
                f"{'Buy' if basket.sign > 0 else 'Sell'},{lots:.2f},{entry:.5f},0,0,{gross:.2f},"
                f"{basket.sign * (now_price - entry) / _PIP:.1f},0.00"
            )
            ticket += 1
    return ("\n".join(lines) + "\n").encode("utf-8")


#: The file name the signal sample's export is audited under.
SIGNAL_FILENAME = "SyntheticSignal.csv"


def signal_sample_result(
    locale: str = "es",
    *,
    bootstrap_samples: int = SAMPLE_BOOTSTRAP,
    market: Callable[[str], pd.Series | None] | None = None,
) -> AuditResult:
    """The signal sample's audit in ``locale``; deterministic for a given sample size.

    Uploaded as a copier would: the account's Myfxbook export alone, the
    trials, cost and out-of-sample fields left blank, and the strategy
    declared as one the client bought or is about to buy or copy, so the
    report speaks to the buyer (``audit/ownership.py``)."""
    declared = DeclaredMetadata(
        trials=1,
        trials_declared=False,
        cost_bps_per_side=0.0,
        cost_declared=False,
        oos_start=None,
        description="",
        # A currency account: no index to hold instead, as the backtest sample.
        benchmark_applicable=False,
        locale=locale if locale in ("es", "en", "pt") else "es",
        challenge=None,
        ownership="buyer",
    )
    inputs = build_inputs(
        None,
        declared,
        report_bytes=synthetic_signal_statement(),
        report_filename=SIGNAL_FILENAME,
    )
    return run_audit(
        inputs,
        bootstrap_samples=bootstrap_samples,
        now=SAMPLE_NOW,
        audit_id="sample",
        market=market,
    )


__all__ = [
    "SAMPLE_NOW",
    "SIGNAL_SEED",
    "sample_result",
    "signal_sample_result",
    "synthetic_live_statement",
    "synthetic_mt5_optimization",
    "synthetic_mt5_report",
    "synthetic_signal_statement",
]
