"""Format families: the calibration cell of a check is ``(check_id, family)``.

HTML and XLSX exports of one MetaTrader table are one family because the
importer's sheet reader yields the same rows; tester and account families
are never pooled, since live accounts carry corrections, dividends and
credits a tester never prints.
"""

from __future__ import annotations

from quant_trade.audit import importers

MT4_STATEMENT = "mt4_statement"
MT5_HISTORY = "mt5_history"
MT5_TESTER = "mt5_tester"
MT4_TESTER = "mt4_tester"
MYFXBOOK = "myfxbook"
MQL5_SIGNAL = "mql5_signal"
FXBLUE = "fxblue"
TRADINGVIEW = "tradingview"
NINJATRADER = "ninjatrader"
MONTHLY = "monthly"
OTHER = "other"

FAMILIES = (
    MT4_STATEMENT,
    MT5_HISTORY,
    MT5_TESTER,
    MT4_TESTER,
    MYFXBOOK,
    MQL5_SIGNAL,
    FXBLUE,
    TRADINGVIEW,
    NINJATRADER,
    MONTHLY,
    OTHER,
)

FAMILY_OF: dict[str, str] = {
    importers.MT4_STATEMENT_HTML: MT4_STATEMENT,
    importers.MT5_HISTORY_HTML: MT5_HISTORY,
    importers.MT5_HISTORY_XLSX: MT5_HISTORY,
    importers.MT5_TESTER_HTML: MT5_TESTER,
    importers.MT5_TESTER_XLSX: MT5_TESTER,
    importers.MT4_TESTER_HTML: MT4_TESTER,
    importers.MYFXBOOK_CSV: MYFXBOOK,
    importers.MQL5_SIGNAL_CSV: MQL5_SIGNAL,
    importers.FXBLUE_CSV: FXBLUE,
    importers.TRADINGVIEW_CSV: TRADINGVIEW,
    importers.TRADINGVIEW_XLSX: TRADINGVIEW,
    importers.NINJATRADER_CSV: NINJATRADER,
}

#: Families whose rows come from an HTML table reader (or its sheet twin).
HTML_FAMILIES = frozenset({MT4_STATEMENT, MT5_HISTORY, MT5_TESTER, MT4_TESTER})
#: Families whose rows come from a delimited text file.
CSV_FAMILIES = frozenset({MYFXBOOK, MQL5_SIGNAL, FXBLUE, TRADINGVIEW, NINJATRADER})
#: Formats whose spreadsheet cells lost their printed zeros.
XLSX_FORMATS = frozenset(
    {importers.MT5_HISTORY_XLSX, importers.MT5_TESTER_XLSX, importers.TRADINGVIEW_XLSX}
)
TESTER_FAMILIES = frozenset({MT5_TESTER, MT4_TESTER})


def family_of(source_format: str | None, *, monthly: bool = False) -> str:
    if monthly:
        return MONTHLY
    if source_format is None:
        return OTHER
    return FAMILY_OF.get(source_format, OTHER)
