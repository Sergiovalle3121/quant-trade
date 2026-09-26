"""SLTP_FILL, PNL_SIGN, PRICE_IMPLIED_PNL and PRICE_PRECISION (spec §3.11-3.14).

Every test loads a synthetic fixture (or a one-step alteration of its bytes)
offline, runs the check module directly and reads the figures as text. The
CSV samples copy the header shapes of real Myfxbook, MQL5-signal and FX Blue
exports. Nothing here touches the network or a real file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from quant_trade.audit import importers
from quant_trade.audit.forensics import families, rows
from quant_trade.audit.forensics.calibration import CALIBRATION
from quant_trade.audit.forensics.checks import Context, prices
from quant_trade.audit.forensics.header import read_header
from quant_trade.audit.forensics.results import (
    EVIDENCE,
    STATUS_CLEAN,
    STATUS_INFO,
    STATUS_NOT_MEASURED,
    STATUS_SIGNAL,
    RawOutcome,
)
from quant_trade.audit.forensics.review import REASONS, decide

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
MT4 = "mt4_statement.htm"
MT5 = "mt5_history.html"
MT5_TESTER = "mt5_tester.html"
MT4_TESTER = "mt4_tester.htm"
TV_G1 = "tradingview_g1.csv"
TV_G3B = "tradingview_g3b.csv"
NINJA = "ninjatrader.csv"
PRIVATE = ("12345678", "Demo Trader", "Synthetic", "FixtureEA")
COUNT = re.compile(r"^-?\d+$")


def _hit_status(check: str, family: str) -> str:
    """A hit is SIGNAL only on a granted calibration cell, else INFO."""
    cell = CALIBRATION.get((check, family))
    return STATUS_SIGNAL if cell is not None and cell.granted else STATUS_INFO


MYFXBOOK = (
    "\n".join(
        [
            "Tags,Ticket,Open Date,Close Date,Symbol,Action,Units/Lots,SL,TP,Open Price,"
            "Close Price,Commission,Swap,Pips,Profit,Gain,Comment,Magic Number",
            ",1001,01/02/2024 09:00,,,Deposit,0.010,0,0,0,0,0,0,0.0,1000.00,0,Deposit,0",
            ",1002,01/03/2024 10:00,01/03/2024 12:00,EURUSD,Buy,0.10,0,0,1.10000,1.10200,"
            "-0.7000,-0.3000,20.0,19.00,1.90,,7",
            ",1003,01/15/2024 10:00,01/15/2024 18:30,EURUSD,Sell,0.10,0,0,1.09500,1.09600,"
            "-0.7000,0.0000,-10.0,-10.70,-1.05,,7",
            ",1004,01/20/2024 08:00,,,Withdrawal,0.010,0,0,0,0,0,0,0.0,-200.00,0,Withdrawal,0",
            ",1005,01/22/2024 10:00,01/23/2024 11:00,EURUSD,Buy,0.20,0,0,1.26000,1.26100,"
            "-1.4000,0.0000,10.0,18.60,2.30,,7",
            "Open Trades",
            "Tags,Ticket,Open Date,Symbol,Action,Lots,Open Price,TP,SL,Profit",
            ",1006,01/25/2024 10:00,EURUSD,Buy,0.10,1.09000,0,0,-55.00",
        ]
    )
    + "\n"
).encode("utf-8")
MQL5_SIGNAL = (
    "﻿"
    + "\n".join(
        [
            "Time;Type;Volume;Symbol;Price;S/L;T/P;Time;Price;Commission;Swap;Profit;Comment",
            "2024.03.01 08:00:00;Balance;;;;;;;;;;1 000.00;Deposit",
            "2024.03.04 09:00:00;Buy;0.10;EURUSD;1.08000;;;2024.03.04 15:00:00;1.08150;-0.50;"
            "-0.10;15.00;",
            "2024.03.05 09:00:00;Sell;0.10;EURUSD;1.08500;;;2024.03.05 11:00:00;1.08400;-0.50;"
            "0.00;10.00;",
            "2024.03.06 09:00:00;Buy;0.20;EURUSD;1.08200;1.08000;;2024.03.06 12:00:00;1.08300;"
            "-1.00;0.00;20.00;",
            "2024.03.07 09:00:00;Buy Stop;0.10;EURUSD;1.09000;;;2024.03.07 12:00:00;1.09000;;;;"
            "cancelled",
            "2024.03.08 12:00:00;Balance;;;;;;;;;;-100.00;Withdrawal",
        ]
    )
).encode("utf-8")
FXBLUE_HEAD = (
    "Type,Ticket,Symbol,Lots,Buy/sell,Open price,Close price,Open time,Close time,"
    "Open date,Close date,Profit,Swap,Commission,Net profit,T/P,S/L,Pips,Result,"
    "Trade duration (hours),Magic number,Order comment,Account"
)


def fxblue(accounts: tuple[str, ...] = ("main",)) -> bytes:
    lines = ["sep=,", FXBLUE_HEAD]
    for account in accounts:
        lines += [
            f"Deposit,1,,0,,0,0,2024/10/01 08:00:00,2024/10/01 08:00:00,2024/10/01,2024/10/01,"
            f"5000,0,0,5000,0,0,0,n/a,0,0,,{account}",
            f"Closed position,2,EURUSD,1,Buy,1.1000,1.1010,2024/10/02 09:00:00,"
            f"2024/10/02 10:00:00,2024/10/02,2024/10/02,100,-2,-5,93,0,0,10,Win,1,1,,{account}",
            f"Closed position,3,EURUSD,1,Sell,1.1020,1.1030,2024/10/03 09:00:00,"
            f"2024/10/03 11:00:00,2024/10/03,2024/10/03,-100,0,-5,-105,0,0,-10,Loss,2,1,,{account}",
            f"Closed position,5,EURUSD,0.5,Buy,1.1000,1.1020,2024/10/05 09:00:00,"
            f"2024/10/05 11:00:00,2024/10/05,2024/10/05,100,0,-3,97,0,0,20,Win,2,1,,{account}",
            f"Open position,4,EURUSD,1,Buy,1.1000,1.0900,2024/10/04 09:00:00,"
            f"1970/01/01 00:00:00,2024/10/04,1970/01/01,-1000,0,0,-1000,0,0,-100,Loss,0,1,,"
            f"{account}",
        ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def table_of(data: bytes, source_format: str | None = None) -> rows.RawTable:
    return rows.load(data, source_format or importers.detect_format(data))


def outcome(
    check: str, data: bytes, source_format: str | None = None, currency: str | None = None
) -> RawOutcome:
    table = table_of(data, source_format)
    header = read_header(table, currency)
    ctx = Context(family=table.family, header=header, currency=header.currency)
    runner = getattr(prices, f"run_{check}")
    result: RawOutcome = runner(table, ctx)
    return result


def figure(result: RawOutcome, key: str) -> str:
    for name, value, _evidence in result.figures:
        if name == key:
            return value
    raise KeyError(key)


def index_of(data: bytes, text: str, source_format: str | None = None) -> int:
    """The raw index of the first row carrying ``text`` in one of its cells."""
    for row in table_of(data, source_format).rows:
        if text in row.texts:
            return row.index
    raise AssertionError(text)


def replaced(data: bytes, old: str, new: str) -> bytes:
    assert data.count(old.encode()) == 1, old
    return data.replace(old.encode(), new.encode())


def without_line(data: bytes, marker: str) -> bytes:
    lines = data.splitlines(keepends=True)
    kept = [line for line in lines if marker.encode() not in line]
    assert len(kept) == len(lines) - 1, marker
    return b"".join(kept)


def with_line_after(data: bytes, marker: str, line: str) -> bytes:
    out: list[bytes] = []
    added = 0
    for item in data.splitlines(keepends=True):
        out.append(item)
        if marker.encode() in item:
            out.append(line.encode() + b"\n")
            added += 1
    assert added == 1, marker
    return b"".join(out)


def assert_well_formed(result: RawOutcome) -> None:
    keys = [name for name, _value, _evidence in result.figures]
    assert "n_rows" in keys and "n_hits" in keys
    assert len(keys) == len(set(keys))
    for name, value, evidence in result.figures:
        assert isinstance(name, str) and isinstance(value, str)
        assert evidence in EVIDENCE
        assert COUNT.match(value), (name, value)
    assert list(result.examples) == sorted(result.examples)
    assert len(result.examples) <= 5
    serialised = json.dumps([list(item) for item in result.figures])
    for secret in PRIVATE:
        assert secret not in serialised


def assert_skipped(result: RawOutcome, reason: str) -> None:
    assert result.not_measured
    assert result.reason == reason
    assert result.reason in REASONS
    assert result.hits == 0 and result.examples == ()


# ---------------------------------------------------------------------------
# SLTP_FILL
# ---------------------------------------------------------------------------

MT4_TP_CLOSE = "<td>1.08700</td><td class=mspt>-7.00</td>"
MT4_SL_CLOSE = "<td>2083.00</td><td class=mspt>-3.50</td>"
MT5_TP_DEAL = "<td nowrap>0.10</td><td nowrap>1.08700</td>"
MT5_SL_DEAL = "<td nowrap>0.02</td><td nowrap>2084.60</td>"
TESTER_SL_DEAL = "<td>1.09900</td><td>4</td>"
TESTER_TP_DEAL = "<td>2035.00</td><td>7</td>"


@pytest.mark.parametrize("name", [MT4, MT5, MT5_TESTER])
def test_sltp_fill_clean_on_fixtures(name: str) -> None:
    result = outcome("SLTP_FILL", fixture(name))
    assert_well_formed(result)
    assert not result.not_measured
    assert result.hits == 0 and result.examples == ()
    assert figure(result, "n_rows") == "2"
    assert figure(result, "n_tp") == "1"
    assert figure(result, "n_sl") == "1"
    assert figure(result, "tp_hits") == "0"
    assert figure(result, "sl_hits") == "0"
    assert figure(result, "sl_better_fills") == "0"
    assert figure(result, "levels_cleared") == "0"
    assert decide("SLTP_FILL", table_of(fixture(name)).family, result) == STATUS_CLEAN


@pytest.mark.parametrize(
    ("name", "old", "new", "counter", "ticket"),
    [
        # a long closed [tp] below its T/P
        (MT4, MT4_TP_CLOSE, MT4_TP_CLOSE.replace("1.08700", "1.08690"), "tp_hits", "1000002"),
        # a sell-out deal (closes a long) [tp 1.08700] filled below the level
        (MT5, MT5_TP_DEAL, MT5_TP_DEAL.replace("1.08700", "1.08690"), "tp_hits", "9004"),
        # a sell-out deal (closes a long) sl 1.09900 filled above the level: the
        # tester executes a stop at its level or beyond, never better
        (MT5_TESTER, TESTER_SL_DEAL, TESTER_SL_DEAL.replace("1.09900", "1.09910"), "sl_hits", "4"),
        # a buy-out deal (closes a short) tp 2035.00 filled above the level
        (MT5_TESTER, TESTER_TP_DEAL, TESTER_TP_DEAL.replace("2035.00", "2035.10"), "tp_hits", "7"),
    ],
)
def test_sltp_fill_hit_when_the_fill_is_on_the_wrong_side(
    name: str, old: str, new: str, counter: str, ticket: str
) -> None:
    data = replaced(fixture(name), old, new)
    result = outcome("SLTP_FILL", data)
    assert_well_formed(result)
    assert result.hits == 1
    assert figure(result, "n_hits") == "1"
    assert figure(result, counter) == "1"
    assert result.examples == (index_of(data, ticket),)
    assert decide("SLTP_FILL", table_of(data).family, result) == _hit_status(
        "SLTP_FILL", table_of(data).family
    )


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        # a short closed [sl] below its S/L (better than the stop)
        (MT4, MT4_SL_CLOSE, MT4_SL_CLOSE.replace("2083.00", "2082.90")),
        # a buy-out deal (closes a short) [sl 2084.60] filled below the level
        (MT5, MT5_SL_DEAL, MT5_SL_DEAL.replace("2084.60", "2084.50")),
    ],
)
def test_sltp_fill_better_stop_fill_on_a_live_account_is_a_figure_not_a_hit(
    name: str, old: str, new: str
) -> None:
    """Genuine statements show stops filled a few points better than their
    level (market execution): counted, never a hit outside the tester."""
    data = replaced(fixture(name), old, new)
    result = outcome("SLTP_FILL", data)
    assert_well_formed(result)
    assert result.hits == 0 and result.examples == ()
    assert figure(result, "sl_better_fills") == "1"
    assert figure(result, "sl_hits") == "0"
    assert figure(result, "n_sl") == "1"
    assert decide("SLTP_FILL", table_of(data).family, result) == STATUS_CLEAN


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        (MT4, MT4_TP_CLOSE, MT4_TP_CLOSE.replace("1.08700", "1.08710")),
        (MT4, MT4_SL_CLOSE, MT4_SL_CLOSE.replace("2083.00", "2083.10")),
        (MT5, MT5_TP_DEAL, MT5_TP_DEAL.replace("1.08700", "1.08710")),
        (MT5, MT5_SL_DEAL, MT5_SL_DEAL.replace("2084.60", "2084.70")),
        (MT5_TESTER, TESTER_SL_DEAL, TESTER_SL_DEAL.replace("1.09900", "1.09890")),
        (MT5_TESTER, TESTER_TP_DEAL, TESTER_TP_DEAL.replace("2035.00", "2034.90")),
    ],
)
def test_sltp_fill_positive_slippage_is_allowed(name: str, old: str, new: str) -> None:
    result = outcome("SLTP_FILL", replaced(fixture(name), old, new))
    assert_well_formed(result)
    assert result.hits == 0


def test_sltp_fill_cleared_level_is_not_measured_for_that_row() -> None:
    data = replaced(
        fixture(MT4),
        "<td>2080.10</td><td>2083.00</td><td>0.00</td>",
        "<td>2080.10</td><td>0.00</td><td>0.00</td>",
    )
    result = outcome("SLTP_FILL", data)
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_rows") == "2"
    assert figure(result, "n_sl") == "0"
    assert figure(result, "n_tp") == "1"
    assert figure(result, "levels_cleared") == "1"


def test_sltp_fill_reads_the_comment_row_of_2009_builds() -> None:
    data = re.sub(rb' title="[^"]*"', b"", fixture(MT4))
    assert b"title=" not in data
    data = with_line_after(
        data,
        "<td>1.08700</td><td class=mspt>-7.00</td>",
        "<tr><td></td><td></td><td>[tp]</td></tr>",
    )
    data = with_line_after(
        data, MT4_SL_CLOSE, "<tr><td></td><td></td><td>from #1000003[sl]</td></tr>"
    )
    result = outcome("SLTP_FILL", data)
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_tp") == "1"
    assert figure(result, "n_sl") == "1"
    altered = replaced(data, MT4_TP_CLOSE, MT4_TP_CLOSE.replace("1.08700", "1.08690"))
    result = outcome("SLTP_FILL", altered)
    assert result.hits == 1
    assert result.examples == (index_of(altered, "1000002"),)


def test_sltp_fill_without_markers_is_not_measured() -> None:
    data = replaced(fixture(MT4), 'title="[tp]"', 'title=""')
    data = replaced(data, 'title="from #1000003[sl]"', 'title="from #1000003"')
    result = outcome("SLTP_FILL", data)
    assert_skipped(result, "no_qualifying_row")
    assert figure(result, "n_rows") == "0"
    data = replaced(fixture(MT5_TESTER), "sl 1.09900", "stop")
    data = replaced(data, "tp 2035.00", "target")
    assert_skipped(outcome("SLTP_FILL", data), "no_qualifying_row")


def test_sltp_fill_ignores_deals_that_are_not_exits() -> None:
    data = replaced(
        fixture(MT5),
        "<td nowrap>sell</td><td nowrap>out</td>",
        "<td nowrap>sell</td><td nowrap>in</td>",
    )
    result = outcome("SLTP_FILL", data)
    assert figure(result, "n_tp") == "0"
    assert figure(result, "n_sl") == "1"


@pytest.mark.parametrize("name", [MT4_TESTER, TV_G1, TV_G3B, NINJA])
def test_sltp_fill_other_families_are_not_covered(name: str) -> None:
    assert_skipped(outcome("SLTP_FILL", fixture(name)), "format_not_covered")


# ---------------------------------------------------------------------------
# PNL_SIGN
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "n_rows"),
    [(MT4, "3"), (MT5, "2"), (TV_G3B, "2"), (NINJA, "2")],
)
def test_pnl_sign_clean_on_fixtures(name: str, n_rows: str) -> None:
    result = outcome("PNL_SIGN", fixture(name))
    assert_well_formed(result)
    assert not result.not_measured
    assert result.hits == 0 and result.examples == ()
    assert figure(result, "n_rows") == n_rows
    assert figure(result, "n_zero_gross") == "0"
    assert figure(result, "rows_unparsed") == "0"
    assert decide("PNL_SIGN", table_of(fixture(name)).family, result) == STATUS_CLEAN


@pytest.mark.parametrize(
    ("name", "old", "new", "ticket"),
    [
        (MT4, "<td class=mspt>200.00</td>", "<td class=mspt>-200.00</td>", "1000002"),
        (MT5, '<td colspan="2">20.00</td>', '<td colspan="2">-20.00</td>', "5001"),
        # the short of trade 2 lost money on a rising price; its exit row says it won
        (TV_G3B, "Short,5342.75,3,15990.75,-41.1", "Short,5342.75,3,15990.75,41.1", "5342.75"),
        (NINJA, "($410.16),($102.74)", "$410.16,($102.74)", "2"),
    ],
)
def test_pnl_sign_hit_when_the_result_contradicts_the_move(
    name: str, old: str, new: str, ticket: str
) -> None:
    data = replaced(fixture(name), old, new)
    result = outcome("PNL_SIGN", data)
    assert_well_formed(result)
    assert result.hits == 1
    assert figure(result, "n_hits") == "1"
    assert result.examples == (index_of(data, ticket),)
    assert decide("PNL_SIGN", table_of(data).family, result) == _hit_status(
        "PNL_SIGN", table_of(data).family
    )


def test_pnl_sign_zero_result_legs_are_skipped() -> None:
    data = replaced(fixture(MT4), "<td class=mspt>200.00</td>", "<td class=mspt>0.00</td>")
    result = outcome("PNL_SIGN", data)
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_rows") == "3"
    assert figure(result, "n_zero_gross") == "1"


def test_pnl_sign_zero_move_is_not_a_hit() -> None:
    data = replaced(fixture(MT4), MT4_TP_CLOSE, MT4_TP_CLOSE.replace("1.08700", "1.08500"))
    result = outcome("PNL_SIGN", data)
    assert result.hits == 0
    assert figure(result, "n_zero_move") == "1"


def test_pnl_sign_myfxbook_reconstructs_the_gross() -> None:
    result = outcome("PNL_SIGN", MYFXBOOK)
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_rows") == "3"
    # net -10.70 becomes +10.70: gross 11.40 on a short whose price rose
    altered = replaced(MYFXBOOK, "-10.0,-10.70,-1.05", "-10.0,10.70,-1.05")
    result = outcome("PNL_SIGN", altered)
    assert result.hits == 1
    assert result.examples == (index_of(altered, "1003"),)


def test_pnl_sign_mql5_signal() -> None:
    result = outcome("PNL_SIGN", MQL5_SIGNAL)
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_rows") == "3"
    altered = replaced(MQL5_SIGNAL, "-0.10;15.00;", "-0.10;-15.00;")
    result = outcome("PNL_SIGN", altered)
    assert result.hits == 1
    assert result.examples == (index_of(altered, "1.08150"),)


def test_pnl_sign_fxblue_reads_closed_positions_only() -> None:
    data = fxblue()
    result = outcome("PNL_SIGN", data)
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_rows") == "3"
    altered = replaced(data, "2024/10/03,-100,0,-5,-105", "2024/10/03,100,0,-5,-105")
    result = outcome("PNL_SIGN", altered)
    assert result.hits == 1
    assert result.examples == (index_of(altered, "3"),)


def test_pnl_sign_tradingview_without_commission_is_not_measured() -> None:
    assert_skipped(outcome("PNL_SIGN", fixture(TV_G1)), "no_column")


def test_pnl_sign_without_positions_table_is_not_measured() -> None:
    data = without_line(fixture(MT5), '<td>5001</td><td>EURUSD</td><td>buy</td><td class="hidden"')
    data = without_line(data, '<td>5003</td><td>XAUUSD</td><td>sell</td><td class="hidden"')
    assert_skipped(outcome("PNL_SIGN", data), "no_table")


@pytest.mark.parametrize("name", [MT4_TESTER, MT5_TESTER])
def test_pnl_sign_testers_are_not_covered(name: str) -> None:
    assert_skipped(outcome("PNL_SIGN", fixture(name)), "format_not_covered")


# ---------------------------------------------------------------------------
# PRICE_IMPLIED_PNL
# ---------------------------------------------------------------------------

MT4_THIRD_GOLD_ROW = (
    '<tr align=right><td title="[tp]">1000008</td><td class=msdate nowrap>2024.03.06 10:00:00</td>'
    "<td>sell</td><td class=mspt>0.50</td><td>xauusd</td><td>2080.10</td><td>0.00</td>"
    "<td>2079.10</td><td class=msdate nowrap>2024.03.06 12:00:00</td><td>2079.10</td>"
    "<td class=mspt>-3.50</td><td class=mspt>0.00</td><td class=mspt>0.00</td>"
    "<td class=mspt>50.00</td></tr>"
)
MT5_SECOND_EURUSD_ROW = (
    '<tr bgcolor="#FFFFFF" align="right"><td>2024.03.06 09:15:02</td><td>5005</td><td>EURUSD</td>'
    '<td>sell</td><td class="hidden" colspan="8"></td><td class="">0.20</td>'
    '<td class="">1.08900</td>'
    '<td class=""></td><td class=""></td><td class="">2024.03.06 11:40:31</td>'
    '<td class="">1.08800</td><td class="">-1.40</td><td class="">0.00</td>'
    '<td colspan="2">20.00</td></tr>'
)


def test_price_implied_pnl_fixture_measures_gold_only() -> None:
    result = outcome("PRICE_IMPLIED_PNL", fixture(MT4))
    assert_well_formed(result)
    assert not result.not_measured
    assert result.hits == 0
    # xauusd: 0.50 x 4.50 x 100 = 225.00 and 0.50 x 2.90 x 100 = 145.00 (short)
    assert figure(result, "n_rows") == "2"
    assert figure(result, "n_symbols_measured") == "1"
    assert figure(result, "symbols_single_row") == "1"  # eurusd has one row
    assert figure(result, "symbols_no_fit") == "0"
    assert figure(result, "symbols_quote_differs") == "0"
    assert decide("PRICE_IMPLIED_PNL", families.MT4_STATEMENT, result) == STATUS_CLEAN


def test_price_implied_pnl_hit_when_one_row_leaves_the_contract() -> None:
    data = with_line_after(fixture(MT4), 'title="from #1000003[sl]"', MT4_THIRD_GOLD_ROW)
    result = outcome("PRICE_IMPLIED_PNL", data, currency="USD")
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_rows") == "3"
    altered = replaced(data, "<td class=mspt>-145.00</td>", "<td class=mspt>-146.00</td>")
    result = outcome("PRICE_IMPLIED_PNL", altered, currency="USD")
    assert_well_formed(result)
    assert result.hits == 1
    assert figure(result, "n_hits") == "1"
    assert figure(result, "n_symbols_measured") == "1"
    assert result.examples == (index_of(altered, "1000005"),)
    assert decide("PRICE_IMPLIED_PNL", families.MT4_STATEMENT, result) == STATUS_INFO


def test_price_implied_pnl_two_rows_disagreeing_is_no_fit_not_a_hit() -> None:
    altered = replaced(fixture(MT4), "<td class=mspt>-145.00</td>", "<td class=mspt>-146.00</td>")
    result = outcome("PRICE_IMPLIED_PNL", altered, currency="USD")
    assert_skipped(result, "no_qualifying_row")
    assert figure(result, "symbols_no_fit") == "1"
    assert figure(result, "n_symbols_measured") == "0"


def test_price_implied_pnl_quote_currency_must_match_the_account() -> None:
    data = replaced(fixture(MT4), "Currency: USD", "Currency: EUR")
    result = outcome("PRICE_IMPLIED_PNL", data)
    assert_skipped(result, "quote_currency_differs")
    assert figure(result, "symbols_quote_differs") == "2"
    # the currency hint of the import wins over the header
    result = outcome("PRICE_IMPLIED_PNL", data, currency="USD")
    assert not result.not_measured
    assert figure(result, "n_symbols_measured") == "1"


def test_price_implied_pnl_mt5_positions() -> None:
    result = outcome("PRICE_IMPLIED_PNL", fixture(MT5))
    assert_skipped(result, "no_qualifying_row")
    assert figure(result, "symbols_single_row") == "2"
    data = with_line_after(fixture(MT5), "<td>5003</td><td>XAUUSD</td>", MT5_SECOND_EURUSD_ROW)
    result = outcome("PRICE_IMPLIED_PNL", data, currency="USD")
    assert_well_formed(result)
    assert not result.not_measured
    assert result.hits == 0
    assert figure(result, "n_rows") == "2"
    assert figure(result, "n_symbols_measured") == "1"


def test_price_implied_pnl_tradingview_size_in_value_route() -> None:
    result = outcome("PRICE_IMPLIED_PNL", fixture(TV_G3B))
    assert_well_formed(result)
    assert not result.not_measured
    assert result.hits == 0
    assert figure(result, "n_rows") == "2"
    assert figure(result, "n_symbols_measured") == "1"
    with_third = replaced(
        fixture(TV_G3B), "Exit long,2026-03-04 15:00,Open", "Exit long,2026-03-04 15:00,TP"
    )
    result = outcome("PRICE_IMPLIED_PNL", with_third)
    assert figure(result, "n_rows") == "3"
    assert result.hits == 0
    altered = replaced(with_third, "TP,5361,1,5350,10.4", "TP,5361,1,5350,12.4")
    result = outcome("PRICE_IMPLIED_PNL", altered, currency="USD")
    assert result.hits == 1
    assert result.examples == (index_of(altered, "5361"),)
    # an exit row without a signal is a trade without an exit order (still open)
    unsignalled = replaced(
        fixture(TV_G3B), "Exit long,2026-03-04 15:00,Open", "Exit long,2026-03-04 15:00,"
    )
    result = outcome("PRICE_IMPLIED_PNL", unsignalled)
    assert figure(result, "n_rows") == "2"
    assert figure(outcome("PNL_SIGN", unsignalled), "n_rows") == "2"
    assert_skipped(outcome("PRICE_IMPLIED_PNL", fixture(TV_G1)), "no_column")


def test_price_implied_pnl_myfxbook_mql5_fxblue() -> None:
    result = outcome("PRICE_IMPLIED_PNL", MYFXBOOK, currency="USD")
    assert_well_formed(result)
    assert not result.not_measured
    assert result.hits == 0
    assert figure(result, "n_rows") == "3"
    altered = replaced(MYFXBOOK, "10.0,18.60,2.30", "10.0,28.60,2.30")
    result = outcome("PRICE_IMPLIED_PNL", altered, currency="USD")
    assert result.hits == 1
    assert result.examples == (index_of(altered, "1005"),)

    result = outcome("PRICE_IMPLIED_PNL", MQL5_SIGNAL, currency="USD")
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_rows") == "3"
    altered = replaced(MQL5_SIGNAL, "-1.00;0.00;20.00;", "-1.00;0.00;21.00;")
    result = outcome("PRICE_IMPLIED_PNL", altered, currency="USD")
    assert result.hits == 1
    assert result.examples == (index_of(altered, "1.08300"),)

    data = fxblue()
    result = outcome("PRICE_IMPLIED_PNL", data, currency="USD")
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_rows") == "3"
    assert figure(result, "accounts_in_file") == "1"
    altered = replaced(data, "2024/10/05,100,0,-3,97", "2024/10/05,110,0,-3,97")
    result = outcome("PRICE_IMPLIED_PNL", altered, currency="USD")
    assert result.hits == 1
    assert result.examples == (index_of(altered, "5"),)


def test_price_implied_pnl_fxblue_with_several_accounts_reads_the_busiest() -> None:
    result = outcome("PRICE_IMPLIED_PNL", fxblue(("a", "b")), currency="USD")
    assert_well_formed(result)
    assert not result.not_measured
    assert figure(result, "accounts_in_file") == "2"
    assert figure(result, "n_rows") == "3"  # a tie goes to the account printed first
    data = fxblue(("a", "b"))
    altered = replaced(
        data, "2024/10/05,100,0,-3,97,0,0,20,Win,2,1,,a", "2024/10/05,110,0,-3,97,0,0,20,Win,2,1,,a"
    )
    result = outcome("PRICE_IMPLIED_PNL", altered, currency="USD")
    assert result.hits == 1
    altered = replaced(
        data, "2024/10/05,100,0,-3,97,0,0,20,Win,2,1,,b", "2024/10/05,110,0,-3,97,0,0,20,Win,2,1,,b"
    )
    result = outcome("PRICE_IMPLIED_PNL", altered, currency="USD")
    assert result.hits == 0  # the second account is not read


@pytest.mark.parametrize("name", [MT4_TESTER, MT5_TESTER, NINJA])
def test_price_implied_pnl_other_families_are_not_covered(name: str) -> None:
    assert_skipped(outcome("PRICE_IMPLIED_PNL", fixture(name)), "format_not_covered")


# ---------------------------------------------------------------------------
# PRICE_PRECISION
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "n_symbols", "n_rows"),
    [(MT4, "2", "3"), (MT5, "2", "8"), (MT5_TESTER, "3", "10"), (MT4_TESTER, "1", "12")],
)
def test_price_precision_clean_on_fixtures(name: str, n_symbols: str, n_rows: str) -> None:
    result = outcome("PRICE_PRECISION", fixture(name))
    assert_well_formed(result)
    assert not result.not_measured
    assert result.hits == 0 and result.examples == ()
    assert figure(result, "n_symbols") == n_symbols
    assert figure(result, "n_rows") == n_rows
    assert figure(result, "n_rows_off_mode") == "0"
    assert figure(result, "split_symbols") == "0"
    assert decide("PRICE_PRECISION", table_of(fixture(name)).family, result) == STATUS_CLEAN


@pytest.mark.parametrize(
    ("name", "old", "new", "ticket"),
    [
        (MT4, MT4_SL_CLOSE, MT4_SL_CLOSE.replace("2083.00", "2083.0"), "1000005"),
        (MT4, "<td>1.08000</td><td>1.08700</td>", "<td>1.0800</td><td>1.08700</td>", "1000002"),
        (MT5, MT5_SL_DEAL, MT5_SL_DEAL.replace("2084.60", "2084.6"), "9003"),
        (
            MT5,
            "<td>1.08000</td><td>1.08700</td><td>2024",
            "<td>1.0800</td><td>1.08700</td><td>2024",
            "1.0800",  # the Orders row of position 5001
        ),
        (MT5_TESTER, TESTER_TP_DEAL, TESTER_TP_DEAL.replace("2035.00", "2035.000"), "7"),
        (MT5_TESTER, "<td>0.00</td><td>1.09900</td>", "<td>0.00</td><td>1.099</td>", "2"),
        (MT4_TESTER, "<td>1.09655</td>", "<td>1.0965</td>", "12"),
    ],
)
def test_price_precision_hit_when_one_cell_changes_digits(
    name: str, old: str, new: str, ticket: str
) -> None:
    data = replaced(fixture(name), old, new)
    result = outcome("PRICE_PRECISION", data)
    assert_well_formed(result)
    assert result.hits == 1
    assert figure(result, "n_hits") == "1"
    assert figure(result, "n_rows_off_mode") == "1"
    assert result.examples == (index_of(data, ticket),)
    assert decide("PRICE_PRECISION", table_of(data).family, result) == _hit_status(
        "PRICE_PRECISION", table_of(data).family
    )


def test_price_precision_one_time_migration_is_a_split_not_a_hit() -> None:
    data = replaced(
        fixture(MT4),
        "<td>2080.10</td><td>2083.00</td><td>0.00</td>",
        "<td>2080.100</td><td>2083.000</td><td>0.00</td>",
    )
    data = replaced(data, MT4_SL_CLOSE, MT4_SL_CLOSE.replace("2083.00", "2083.000"))
    result = outcome("PRICE_PRECISION", data)
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "split_symbols") == "1"
    assert figure(result, "split_at_row") == str(index_of(data, "1000005"))
    assert figure(result, "n_rows_off_mode") == "0"
    # a row mixing both counts is not a clean split
    mixed = replaced(
        data, "<td>2080.100</td><td>2083.000</td>", "<td>2080.10</td><td>2083.000</td>"
    )
    result = outcome("PRICE_PRECISION", mixed)
    assert result.hits == 1
    assert figure(result, "split_symbols") == "0"


def test_price_precision_zero_levels_are_skipped() -> None:
    data = replaced(
        fixture(MT4),
        "<td>2080.10</td><td>0.00</td><td>0.00</td>",
        "<td>2080.10</td><td>0.0</td><td>0</td>",
    )
    result = outcome("PRICE_PRECISION", data)
    assert result.hits == 0


MT4_TESTER_SWAP_ROWS = (
    "<tr align=right><td>13</td><td class=msdate>2024.01.05 13:00</td><td>swap open</td><td>6</td>"
    "<td class=mspt>0.10</td><td>1.094123</td><td align=right>0.00000</td>"
    "<td align=right>0.00000</td><td colspan=2></td></tr>\n"
    "<tr align=right><td>14</td><td class=msdate>2024.01.05 14:00</td><td>modify</td><td>6</td>"
    "<td class=mspt>0.10</td><td>1.094123</td><td align=right>1.09000</td>"
    "<td align=right>1.10000</td><td colspan=2></td></tr>"
)
MT4_TESTER_MODIFY_ROW = (
    "<tr align=right><td>15</td><td class=msdate>2024.01.05 15:00</td><td>modify</td><td>4</td>"
    "<td class=mspt>0.10</td><td>1.094123</td><td align=right>1.09000</td>"
    "<td align=right>1.10000</td><td colspan=2></td></tr>"
)


def test_price_precision_mt4_tester_swap_reopened_price_is_scoped_out() -> None:
    """A position closed and reopened at rollover carries a swap-adjusted
    open price beyond the symbol's digits on its swap open and modify rows
    (seen on a genuine tester report); its S/L and T/P are still read."""
    data = with_line_after(fixture(MT4_TESTER), "<td>delete</td>", MT4_TESTER_SWAP_ROWS)
    result = outcome("PRICE_PRECISION", data)
    assert_well_formed(result)
    assert result.hits == 0
    assert figure(result, "n_rows") == "13"  # the swap open row's levels are zero
    # the same modify row on an order that was never reopened is a hit
    data = with_line_after(data, "<td>delete</td>", MT4_TESTER_MODIFY_ROW)
    result = outcome("PRICE_PRECISION", data)
    assert result.hits == 1
    assert result.examples == (index_of(data, "15"),)


def test_price_precision_mql5_signal_trims_zeros() -> None:
    """The MQL5 signal export prints prices as floats (``2084.6``, float
    noise): its digits say nothing, whatever the spec assumed."""
    assert_skipped(outcome("PRICE_PRECISION", MQL5_SIGNAL), "variable_precision_format")


def test_price_precision_spreadsheets_lost_their_zeros() -> None:
    for source_format in (importers.MT5_HISTORY_XLSX, importers.MT5_TESTER_XLSX):
        table = rows.RawTable(
            source_format,
            families.family_of(source_format),
            (),
            (),
            "none",
            "none",
            "none",
            0,
            False,
        )
        ctx = Context(family=table.family, header=read_header(table))
        assert_skipped(prices.run_PRICE_PRECISION(table, ctx), "xlsx_precision_lost")


@pytest.mark.parametrize(
    ("data", "source_format"),
    [
        (fixture(TV_G1), None),
        (fixture(NINJA), None),
        (MYFXBOOK, None),
        (fxblue(), None),
        (MQL5_SIGNAL, None),
    ],
)
def test_price_precision_trimmed_exports_are_not_measured(
    data: bytes, source_format: str | None
) -> None:
    assert_skipped(outcome("PRICE_PRECISION", data, source_format), "variable_precision_format")


def test_price_precision_without_prices_is_not_measured() -> None:
    lines = fixture(MT5_TESTER).splitlines(keepends=True)
    kept = [line for line in lines if not re.search(rb"<td>(EURUSD|XAUUSD|GBPUSD)</td>", line)]
    assert len(kept) < len(lines)
    result = outcome("PRICE_PRECISION", b"".join(kept), importers.MT5_TESTER_HTML)
    assert_skipped(result, "no_qualifying_row")


# ---------------------------------------------------------------------------
# Determinism, status rule and privacy
# ---------------------------------------------------------------------------

CHECKS = ("SLTP_FILL", "PNL_SIGN", "PRICE_IMPLIED_PNL", "PRICE_PRECISION")


@pytest.mark.parametrize("check", CHECKS)
@pytest.mark.parametrize("name", [MT4, MT5, MT5_TESTER, MT4_TESTER, TV_G3B, NINJA])
def test_outcomes_are_deterministic_and_carry_nothing_private(check: str, name: str) -> None:
    first = outcome(check, fixture(name))
    second = outcome(check, fixture(name))
    assert first == second
    serialised = json.dumps(
        {"figures": [list(f) for f in first.figures], "examples": list(first.examples)}
    )
    for secret in PRIVATE:
        assert secret not in serialised
    assert "1000002" not in serialised and "5001" not in serialised
    for name_, value, evidence in first.figures:
        assert evidence in EVIDENCE
        assert COUNT.match(value), (name_, value)
    if first.not_measured:
        assert first.reason in REASONS
    status = decide(check, table_of(fixture(name)).family, first)
    if first.not_measured:
        assert status == STATUS_NOT_MEASURED
    else:
        assert status == STATUS_CLEAN


def test_fill_rule_is_an_inequality_in_both_directions() -> None:
    from decimal import Decimal as D

    long, short, tp, sl = prices.SIDE_LONG, prices.SIDE_SHORT, prices.MARKER_TP, prices.MARKER_SL
    assert not prices._fill_violates(tp, long, D("1.1"), D("1.1"))
    assert not prices._fill_violates(tp, long, D("1.2"), D("1.1"))
    assert prices._fill_violates(tp, long, D("1.0"), D("1.1"))
    assert not prices._fill_violates(tp, short, D("1.0"), D("1.1"))
    assert prices._fill_violates(tp, short, D("1.2"), D("1.1"))
    assert not prices._fill_violates(sl, long, D("1.0"), D("1.1"))
    assert prices._fill_violates(sl, long, D("1.2"), D("1.1"))
    assert not prices._fill_violates(sl, short, D("1.2"), D("1.1"))
    assert prices._fill_violates(sl, short, D("1.0"), D("1.1"))


def test_mt5_marker_shapes_seen_on_real_files() -> None:
    for text, marker, level in (
        ("[tp 1.08700]", "tp", "1.08700"),
        ("sl 1.09900", "sl", "1.09900"),
        ("[sl 99999.99]", "sl", "99999.99"),
        ("TP 2035.00", "tp", "2035.00"),
    ):
        match = prices._MT5_MARKER.search(text)
        assert match is not None, text
        assert (match.group(1).lower(), match.group(2)) == (marker, level)
    for text in ("end of test", "partial", "QQ[T1/S23]", "[so]", "ma cross", ""):
        assert prices._MT5_MARKER.search(text) is None, text
