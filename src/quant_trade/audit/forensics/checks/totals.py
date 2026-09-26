"""``TOTALS_VS_ROWS`` and ``SUMMARY_IDENTITIES``: what the report declares.

``TOTALS_VS_ROWS`` never re-implements the importers' summary-vs-rows
arithmetic (D11). It reads the ``"<what>: the report states X but the rows
add up to Y"`` lines the importer already wrote into
``ImportedReport.warnings`` and turns each into a hit with the declared and
the measured figure as text.

``SUMMARY_IDENTITIES`` compares declared labels with declared labels only,
never a label with the rows: a terminal prints one quantity twice, or as the
sum of other printed quantities (``Total Net Profit = Gross Profit −
|Gross Loss|``), and an edit that touches one copy leaves the others. Labels
are read through the importers' alias tables plus the localised names seen
in the public corpus; an identity whose labels are unknown to the tables is
``NOT_MEASURED`` for that file, never a hit.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from quant_trade.audit import importers
from quant_trade.audit.forensics import families, money, thresholds
from quant_trade.audit.forensics.checks import Context
from quant_trade.audit.forensics.results import (
    DECLARED,
    MAX_EXAMPLES,
    MEASURED,
    NOT_MEASURED,
    Figure,
    RawOutcome,
)
from quant_trade.audit.forensics.rows import (
    KIND_CSV,
    KIND_LABEL,
    KIND_MT4_CASH,
    KIND_MT4_TRADE,
    SECTION_CLOSED,
    RawRow,
    RawTable,
    mt4_columns,
)

# ---------------------------------------------------------------------------
# Declared labels, by concept
# ---------------------------------------------------------------------------

#: Summary labels the tester and history reports print in other languages,
#: beyond the importers' own alias tables. Every name comes from a real
#: public report (docs/research/audit_iteration4/mt_languages_check.md and
#: the forensics corpus); matched without case, against the cell text with
#: its trailing colon removed.
_MT5_EXTRA_ALIASES: dict[str, tuple[str, ...]] = {
    "Gross Profit": (
        "Beneficio Bruto",
        "Profitto Lordo",
        "Lucro Bruto",
        "Общая прибыль",
        "毛利",
        "Hrubý zisk",
    ),
    "Gross Loss": (
        "Pérdidas Brutas",
        "Perdita Lorda",
        "Perda Bruta",
        "Общий убыток",
        "毛损",
        "毛損",
        "Hrubá ztráta",
    ),
    "Short Trades (won %)": (
        "Posiciones cortas (% rentables)",
        "Operazioni di Trading Short (vincenti %)",
        "Posições Vendidas (% e ganhos)",
        "Короткие трейды (% выигравших)",
        "卖出交易 (赢得 %)",
        "賣出交易 (won %)",
        "Krátké pozice (zisk %)",
    ),
    "Long Trades (won %)": (
        "Posiciones largas (% rentables)",
        "Operazioni di Trading Long (vincenti %)",
        "Posições Compradas (% de ganhos)",
        "Длинные трейды (% выигравших)",
        "买入交易 (赢得 %)",
        "買入交易 (贏得 %)",
        "Dlouhé pozice (výdělek %)",
    ),
    "Profit Trades (% of total)": (
        "Posiciones rentables (% del total)",
        "Operazioni di Trading in Profitto (% del totale)",
        "Negociações com Lucro (% of total)",
        "Прибыльные трейды (% от всех)",
        "盈利交易 (% 全部)",
        "盈利交易(%在全部)",
        "Zisk z obchodů (% celkem)",
    ),
    "Loss Trades (% of total)": (
        "Posiciones no rentables (% del total)",
        "Operazioni di Trading in Perdita (% del totale)",
        "Negociações com Perda (% of total)",
        "Убыточные трейды (% от всех)",
        "亏损交易 (% 全部)",
        "虧損交易 (%總計)",
        "Ztrátové obchody (% celkem)",
    ),
    "Balance": ("本日餘額", "Zůstatek"),
    "Credit Facility": ("信用貸款", "Úvěrový rámec"),
    "Margin": ("保證金", "Marže"),
    "Free Margin": ("可用保證金", "Dostupná marže"),
}
_MT4_TESTER_EXTRA_ALIASES: dict[str, tuple[str, ...]] = {
    "Gross profit": ("Lucro Bruto", "Общая прибыль"),
    "Gross loss": ("Perda Bruta", "Общий убыток"),
    "Short positions (won %)": ("Posições Vendidas (ganhos %)", "Короткие позиции (% выигравших)"),
    "Long positions (won %)": ("Posições Compradas (ganhos %)", "Длинные позиции (% выигравших)"),
    "Profit trades (% of total)": (
        "Negociações com Lucro (% do total)",
        "Прибыльные сделки (% от всех)",
    ),
    "Loss trades (% of total)": (
        "Negociações com perdas (% do total)",
        "Убыточные сделки (% от всех)",
    ),
}

#: Concept code -> the English label per layout (MT4 statement, MT4 tester,
#: MT5 history and tester). An empty name means the layout never prints it.
_CONCEPTS: tuple[tuple[str, str, str, str], ...] = (
    ("net_profit", "Total Net Profit", "Total net profit", "Total Net Profit"),
    ("gross_profit", "Gross Profit", "Gross profit", "Gross Profit"),
    ("gross_loss", "Gross Loss", "Gross loss", "Gross Loss"),
    ("profit_factor", "Profit Factor", "Profit factor", "Profit Factor"),
    ("total_trades", "Total Trades", "Total trades", "Total Trades"),
    ("short_trades", "Short Positions (won %)", "Short positions (won %)", "Short Trades (won %)"),
    ("long_trades", "Long Positions (won %)", "Long positions (won %)", "Long Trades (won %)"),
    (
        "profit_trades",
        "Profit Trades (% of total)",
        "Profit trades (% of total)",
        "Profit Trades (% of total)",
    ),
    (
        "loss_trades",
        "Loss Trades (% of total)",
        "Loss trades (% of total)",
        "Loss Trades (% of total)",
    ),
    ("balance", "Balance", "", "Balance"),
    ("credit", "Credit Facility", "", "Credit Facility"),
    ("floating", "Floating P/L", "", "Floating P/L"),
    ("equity", "Equity", "", "Equity"),
    ("margin", "Margin", "", "Margin"),
    ("free_margin", "Free Margin", "", "Free Margin"),
    ("deposit_withdrawal", "Deposit/Withdrawal", "", ""),
    ("closed_trade_pnl", "Closed Trade P/L", "", ""),
    ("closed_pnl", "Closed P/L", "", ""),
    ("balance_drawdown_maximal", "", "", "Balance Drawdown Maximal"),
)
_LAYOUT_OF_FAMILY = {
    families.MT4_STATEMENT: 1,
    families.MT4_TESTER: 2,
    families.MT5_HISTORY: 3,
    families.MT5_TESTER: 3,
}


def _alias_map(layout: int) -> dict[str, str]:
    """Lower-cased label text -> concept code for one layout."""
    aliases: dict[str, tuple[str, ...]] = {}
    if layout == 2:
        aliases = {**importers._MT4_LABEL_ALIASES, **_MT4_TESTER_EXTRA_ALIASES}
    elif layout == 3:
        aliases = {**importers._MT5_LABEL_ALIASES, **_MT5_EXTRA_ALIASES}
    found: dict[str, str] = {}
    for concept, *names in _CONCEPTS:
        english = names[layout - 1]
        if not english:
            continue
        found.setdefault(english.lower(), concept)
        for alias in aliases.get(english, ()):
            found.setdefault(alias.lower(), concept)
    return found


_ALIASES: dict[str, dict[str, str]] = {
    family: _alias_map(layout) for family, layout in _LAYOUT_OF_FAMILY.items()
}


@dataclass(frozen=True)
class _Label:
    value: str
    row: int


def _label_rows(table: RawTable) -> dict[str, _Label]:
    """Concept -> printed value and raw row index, first occurrence wins.

    The importers' ``_labels`` / ``_mt4_pairs`` rule, re-declared: a label
    cell (``Balance:``, or a known bare name in a tester summary) followed by
    its value cell.
    """
    aliases = _ALIASES.get(table.family, {})
    found: dict[str, _Label] = {}
    if not aliases:
        return found
    for row in table.rows:
        if row.kind != KIND_LABEL:
            continue
        texts = row.texts
        for position in range(len(texts) - 1):
            text = texts[position].strip()
            if text.endswith(":"):
                text = text[:-1].strip()
            concept = aliases.get(text.lower())
            if concept is None:
                continue
            value = texts[position + 1].strip()
            if not value or value.endswith(":"):
                continue
            found.setdefault(concept, _Label(value, row.index))
    return found


def _lead_money(value: str) -> Decimal | None:
    """The first number of a summary cell such as ``7 025.85 (11.00%)``."""
    return money.parse_money(value.split("(", 1)[0])


# ---------------------------------------------------------------------------
# TOTALS_VS_ROWS
# ---------------------------------------------------------------------------

_TOTALS_LINE = re.compile(
    r"^(?:report: )?(?P<what>.+?): the report states (?P<declared>[-\d.,]+)"
    r" but the rows add up to (?P<measured>[-\d.,]+)$"
)
_BALANCE_LINE = re.compile(
    r"^(?:report: )?(?P<n>\d+) Balance cell\(s\) do not equal the previous balance"
    r" plus the row's money"
)
#: The importer read one account out of several (NinjaTrader grids): the
#: file's cumulative column spans every account, so no declared total is
#: comparable with the rows that were read.
_ACCOUNTS_LINE = re.compile(
    r"^(?:report: )?the file holds (?P<n>\d+) accounts; only the one with the most closed"
)
_WHAT_CODES = frozenset(
    {
        "net_profit",
        "closed_trade_pnl",
        "net_profit_of_closed_positions",
        "closing_deals_vs_total_trades",
        "close_rows_vs_total_trades",
        "balance_drawdown_maximal",
    }
)
#: The concept whose label row is the example of each ``what`` code.
_WHAT_CONCEPT = {
    "net_profit": ("net_profit",),
    "net_profit_of_closed_positions": ("net_profit",),
    "closed_trade_pnl": ("closed_pnl", "closed_trade_pnl"),
    "closing_deals_vs_total_trades": ("total_trades",),
    "close_rows_vs_total_trades": ("total_trades",),
    "balance_drawdown_maximal": ("balance_drawdown_maximal",),
}
#: The English labels the importer reads a declared total from, per family:
#: any of them present means such a comparison could exist for the file.
_DECLARED_LABELS: dict[str, tuple[str, ...]] = {
    families.MT4_STATEMENT: ("Closed P/L", "Closed Trade P/L"),
    families.MT5_HISTORY: ("Total Net Profit",),
    families.MT5_TESTER: ("Total Trades", "Total Net Profit", "Balance Drawdown Maximal"),
    families.MT4_TESTER: ("Total trades", "Total net profit"),
}


def _what_code(what: str) -> str:
    text = what.lower().replace("p/l", "pnl").replace("p&l", "pnl")
    slug = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return slug if slug in _WHAT_CODES else "other"


def _number_text(printed: str) -> str:
    """A number the importer wrote (``1,234.50``) as canonical text."""
    number = money.parse_money(printed)
    return money.as_text(number) if number is not None else printed.replace(",", "")


def _declared_totals_present(table: RawTable) -> bool:
    family = table.family
    if family in _DECLARED_LABELS:
        return any(table.label(name) for name in _DECLARED_LABELS[family])
    if family == families.TRADINGVIEW:
        names = [name.strip().lower() for name in table.header]
        pattern = importers._TV_PATTERNS["cum"]
        return any(pattern.match(name) for name in names) or (len(names) in importers._TV_POSITIONS)
    if family == families.NINJATRADER:
        return "cum. net profit" in importers._ninjatrader_index(list(table.header))
    return False


def _suffix(position: int) -> str:
    return "" if position == 1 else f"_{position}"


def _first_count(pattern: re.Pattern[str], lines: tuple[str, ...]) -> int:
    """The ``n`` of the first line matching ``pattern``, ``0`` when none."""
    for line in lines:
        found = pattern.match(line)
        if found is not None:
            return int(found.group("n"))
    return 0


def run_TOTALS_VS_ROWS(table: RawTable, ctx: Context) -> RawOutcome:
    lines = tuple(line.strip() for line in ctx.imported_warnings)
    matches = [found for found in (_TOTALS_LINE.match(line) for line in lines) if found]
    breaks = _first_count(_BALANCE_LINE, lines)
    accounts = _first_count(_ACCOUNTS_LINE, lines)
    figures: list[Figure] = [("n_rows", str(len(lines)), MEASURED)]
    if not matches and not _declared_totals_present(table):
        return RawOutcome.skip("no_declared_totals", figures=tuple(figures))
    several = accounts > 1
    figures.append(("n_hits", "0" if several else str(len(matches)), MEASURED))
    labels = _label_rows(table)
    csv_rows = table.kind(KIND_CSV)
    examples: set[int] = set()
    for position, found in enumerate(matches, 1):
        code = _what_code(found.group("what"))
        suffix = _suffix(position)
        figures.append((f"what_code{suffix}", code, MEASURED))
        figures.append((f"declared{suffix}", _number_text(found.group("declared")), DECLARED))
        figures.append((f"measured{suffix}", _number_text(found.group("measured")), MEASURED))
        for concept in _WHAT_CONCEPT.get(code, ()):
            if concept in labels:
                examples.add(labels[concept].row)
                break
        else:
            if code == "other" and csv_rows:
                examples.add(csv_rows[-1].index)
    figures.append(("importer_balance_breaks", str(breaks), MEASURED))
    if several:
        figures.append(("accounts", str(accounts), MEASURED))
        return RawOutcome.skip("several_accounts", figures=tuple(figures))
    return RawOutcome(
        hits=len(matches),
        figures=tuple(figures),
        examples=tuple(sorted(examples)[:MAX_EXAMPLES]),
    )


# ---------------------------------------------------------------------------
# SUMMARY_IDENTITIES
# ---------------------------------------------------------------------------

KIND_MONEY = "money"
KIND_COUNT = "count"
KIND_RATIO = "ratio"

Compute = Callable[[tuple[Decimal, ...]], Decimal | None]


def _sum(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, Decimal(0))


def _gross_net(values: tuple[Decimal, ...]) -> Decimal:
    """Gross loss is printed negative by the testers and unsigned by the MT4
    statement's details block: the net is the gross profit less its size."""
    return values[0] - abs(values[1])


def _profit_factor(values: tuple[Decimal, ...]) -> Decimal | None:
    loss = abs(values[1])
    return values[0] / loss if loss != 0 else None


def _difference(values: tuple[Decimal, ...]) -> Decimal:
    return values[0] - values[1]


def _first(values: tuple[Decimal, ...]) -> Decimal:
    return values[0]


@dataclass(frozen=True)
class _Identity:
    code: str
    left: str
    right: tuple[str, ...]
    kind: str
    compute: Compute
    optional: tuple[str, ...] = ()
    """Operands read as zero when the file does not print them."""


#: Identities of the MT4 statement that hold only on a full-history export:
#: ``Deposit/Withdrawal`` and ``Credit Facility`` are the money moved inside
#: the statement period, while ``Balance`` and ``Equity`` are the account's
#: standing figures (a period export of an account carrying a 155.00 welcome
#: credit from before the period printed ``Credit Facility: 0.00``).
_MT4_FULL_HISTORY_ONLY = ("balance_flows_pnl", "equity_balance_floating")


_NET_PROFIT = _Identity(
    "net_profit_gross", "net_profit", ("gross_profit", "gross_loss"), KIND_MONEY, _gross_net
)
_TRADES_SIDES = _Identity(
    "trades_short_long", "total_trades", ("short_trades", "long_trades"), KIND_COUNT, _sum
)
_TRADES_OUTCOME = _Identity(
    "trades_profit_loss", "total_trades", ("profit_trades", "loss_trades"), KIND_COUNT, _sum
)
_PROFIT_FACTOR = _Identity(
    "profit_factor_gross",
    "profit_factor",
    ("gross_profit", "gross_loss"),
    KIND_RATIO,
    _profit_factor,
)
_BALANCE_FLOWS = _Identity(
    "balance_flows_pnl", "balance", ("deposit_withdrawal", "closed_trade_pnl"), KIND_MONEY, _sum
)
_EQUITY = _Identity(
    "equity_balance_floating",
    "equity",
    ("balance", "credit", "floating"),
    KIND_MONEY,
    _sum,
    optional=("credit",),
)
_FREE_MARGIN = _Identity(
    "free_margin_equity_margin", "free_margin", ("equity", "margin"), KIND_MONEY, _difference
)
_CLOSED_PNL = _Identity(
    "closed_pnl_summary", "closed_trade_pnl", ("closed_pnl",), KIND_MONEY, _first
)

#: The identities each family prints, in output order. The MT4 statement
#: never gets ``Free Margin = Equity − Margin``: a genuine export showed
#: free margin 14.24 below equity with nothing open, no working order and
#: ``Margin: 0.00`` (the server's free-margin mode and pending-order margin
#: are settings the statement does not print).
_IDENTITIES: dict[str, tuple[_Identity, ...]] = {
    families.MT4_STATEMENT: (
        _BALANCE_FLOWS,
        _EQUITY,
        _CLOSED_PNL,
        _NET_PROFIT,
        _TRADES_SIDES,
        _TRADES_OUTCOME,
        _PROFIT_FACTOR,
    ),
    families.MT5_HISTORY: (
        _NET_PROFIT,
        _EQUITY,
        _FREE_MARGIN,
        _TRADES_SIDES,
        _TRADES_OUTCOME,
        _PROFIT_FACTOR,
    ),
    families.MT5_TESTER: (_NET_PROFIT, _TRADES_SIDES, _TRADES_OUTCOME, _PROFIT_FACTOR),
    families.MT4_TESTER: (_NET_PROFIT, _TRADES_SIDES, _TRADES_OUTCOME, _PROFIT_FACTOR),
}


def _mt4_full_history(table: RawTable) -> bool:
    """Whether the closed table opens with the account's deposit: the first
    cash row is a ``balance`` deposit dated at or before the first trade's
    open. A period export fails this and its balance identity is skipped."""
    cash: RawRow | None = None
    trade: RawRow | None = None
    for row in table.rows:
        if row.section != SECTION_CLOSED:
            continue
        if row.kind == KIND_MT4_CASH and cash is None:
            cash = row
        elif row.kind == KIND_MT4_TRADE and trade is None:
            trade = row
        if cash is not None and trade is not None:
            break
    if cash is None:
        return False
    amounts = [money.parse_money(text) for text in cash.texts if text.strip()]
    amount = amounts[-1] if amounts else None
    if amount is None or amount <= 0:
        return False
    cash_time = importers._one_time(cash.text(mt4_columns(table, cash)["open_time"]))
    if cash_time is None:
        return False
    if trade is None:
        return True
    trade_time = importers._one_time(trade.text(mt4_columns(table, trade)["open_time"]))
    return trade_time is not None and cash_time <= trade_time


def _flat(labels: dict[str, _Label]) -> bool:
    """Whether the printed ``Floating P/L`` is zero: the server's free-margin
    mode (unrealised profit or loss counted or not) cannot act, so
    ``Free Margin = Equity − Margin`` is the terminal's own arithmetic."""
    floating = labels.get("floating")
    number = _lead_money(floating.value) if floating is not None else None
    return number is not None and number == 0


def _operands(identity: _Identity, labels: dict[str, _Label]) -> tuple[Decimal, ...] | None:
    values: list[Decimal] = []
    for concept in identity.right:
        label = labels.get(concept)
        if label is None:
            if concept in identity.optional:
                values.append(Decimal(0))
                continue
            return None
        number = _lead_money(label.value)
        if number is None:
            return None
        values.append(number)
    return tuple(values)


def _agree(kind: str, left: Decimal, right: Decimal) -> bool:
    gap = abs(left - right)
    if kind == KIND_MONEY:
        return gap <= thresholds.MONEY_TOLERANCE
    if kind == KIND_RATIO:
        return gap <= thresholds.RATIO_TOLERANCE
    return gap == 0


def _right_text(kind: str, value: Decimal) -> str:
    return money.as_text(value, 3) if kind == KIND_RATIO else money.as_text(value)


def run_SUMMARY_IDENTITIES(table: RawTable, ctx: Context) -> RawOutcome:
    identities = _IDENTITIES.get(table.family)
    if identities is None:
        return RawOutcome.skip("format_not_covered")
    labels = _label_rows(table)
    n_rows = sum(1 for row in table.rows if row.kind == KIND_LABEL)
    mt4 = table.family == families.MT4_STATEMENT
    full_history = mt4 and _mt4_full_history(table)
    details: list[Figure] = []
    examples: set[int] = set()
    evaluated = 0
    hits = 0
    for identity in identities:
        left_label = labels.get(identity.left)
        left = _lead_money(left_label.value) if left_label is not None else None
        operands = _operands(identity, labels)
        if left_label is None or left is None or operands is None:
            details.append((identity.code, "no_declared_totals", NOT_MEASURED))
            continue
        if identity.code in _MT4_FULL_HISTORY_ONLY and mt4 and not full_history:
            details.append((identity.code, "no_qualifying_row", NOT_MEASURED))
            continue
        if identity is _FREE_MARGIN and not _flat(labels):
            details.append((identity.code, "no_qualifying_row", NOT_MEASURED))
            continue
        right = identity.compute(operands)
        if right is None:
            details.append((identity.code, "no_qualifying_row", NOT_MEASURED))
            continue
        evaluated += 1
        hit = not _agree(identity.kind, left, right)
        if hit:
            hits += 1
            examples.add(left_label.row)
        details.append((identity.code, "1" if hit else "0", MEASURED))
        details.append((f"{identity.code}_left", money.as_text(left), DECLARED))
        details.append((f"{identity.code}_right", _right_text(identity.kind, right), DECLARED))
    figures: tuple[Figure, ...] = (
        ("n_rows", str(n_rows), MEASURED),
        ("n_hits", str(hits), MEASURED),
        ("n_identities", str(evaluated), MEASURED),
        *details,
    )
    if evaluated == 0:
        return RawOutcome.skip("no_declared_totals", figures=figures)
    return RawOutcome(hits=hits, figures=figures, examples=tuple(sorted(examples)[:MAX_EXAMPLES]))
