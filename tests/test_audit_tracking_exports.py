"""Account histories exported by tracking sites: Myfxbook, MQL5 signals, FX Blue.

The layouts come from 15 real public exports (see
docs/research/audit_iteration4/tracking_exports_check.md); every fixture
here is synthetic and only copies their shape.
"""

from __future__ import annotations

import pytest

from quant_trade.audit.account import ACCOUNT_FORMATS
from quant_trade.audit.importers import (
    FXBLUE_CSV,
    MQL5_SIGNAL_CSV,
    MYFXBOOK_CSV,
    ReportFormatError,
    detect_format,
    import_report,
)

MYFXBOOK_HEAD = (
    "Tags,Ticket,Open Date,Close Date,Symbol,Action,Units/Lots,SL,TP,Open Price,Close Price,"
    "Commission,Swap,Pips,Profit,Gain,Comment,Magic Number,Duration (DD:HH:MM:SS),"
    "Profitable(%),Profitable(time duration),Drawdown,Risk:Reward,Max(pips),Max(USD),"
    "Min(pips),Min(USD),Entry Accuracy(%),Exit Accuracy(%),ProfitMissed(pips),"
    "ProfitMissed(USD)"
)
TAIL = ",,,,,,,,,,,,"


def _myfxbook() -> bytes:
    rows = [
        MYFXBOOK_HEAD,
        ",1001,01/02/2024 09:00,,,Deposit,0.010,0,0,0,0,0,0,0.0,1000.00,0,Deposit,0,"
        "00:00:00:00" + TAIL,
        # Net profit 19.00 = gross 20.00 - commission 0.70 - swap 0.30.
        ",1002,01/03/2024 10:00,01/03/2024 12:00,EURUSD,Buy,0.10,0,0,1.10000,1.10200,"
        "-0.7000,-0.3000,20.0,19.00,1.90,,7,00:02:00:00" + TAIL,
        ",1003,01/15/2024 10:00,01/15/2024 18:30,EURUSD.m,Sell,0.10,0,0,1.09500,1.09600,"
        "-0.7000,0.0000,-10.0,-10.70,-1.05,[sl],7,00:08:30:00" + TAIL,
        ",1004,01/20/2024 08:00,,,Withdrawal,0.010,0,0,0,0,0,0,0.0,-200.00,0,Withdrawal,0,"
        "00:00:00:00" + TAIL,
        ",1005,01/22/2024 10:00,01/23/2024 11:00,GBPUSD,Buy,0.20,0,0,1.27000,1.27100,"
        "-1.4000,0.0000,10.0,18.60,2.29,,7,01:01:00:00" + TAIL,
        "",
        "Open Trades",
        "Tags,Ticket,Open Date,Symbol,Action,Lots,Open Price,TP,SL,Profit,Pips,Swap",
        ",1006,01/25/2024 10:00,EURUSD,Buy,0.10,1.09000,0,0,-55.00,-55.0,0",
    ]
    return ("\n".join(rows) + "\n").encode("utf-8")


def test_myfxbook_export() -> None:
    data = _myfxbook()
    assert detect_format(data, "statement.csv") == MYFXBOOK_CSV
    report = import_report(data, "statement.csv")
    trades = report.trades
    assert len(trades.trades) == 3  # the open trade after "Open Trades" is left out
    assert trades.sides == ["long", "short", "long"]
    # Myfxbook's Profit is net: the gross adds the costs back.
    assert [round(t.pnl, 2) for t in trades.trades] == [20.0, -10.0, 20.0]
    assert trades.fees == pytest.approx([1.0, 0.7, 1.4])
    assert [amount for _, amount in report.cash_flows] == [1000.0, -200.0]
    assert report.initial_balance == 1000.0
    assert report.fees == {"commission": pytest.approx(-2.8), "swap": pytest.approx(-0.3)}
    assert report.source_format in ACCOUNT_FORMATS
    # The open trade's result is kept as the file's floating result.
    assert report.metadata["declared_floating_pnl"] == "-55.00"
    assert report.metadata["declared_balance"] == "826.90"


MQL5_HISTORY = "\n".join(
    [
        "﻿Time;Type;Volume;Symbol;Price;S/L;T/P;Time;Price;Commission;Swap;Profit;Comment",
        "2024.03.01 08:00:00;Balance;;;;;;;;;;1 000.00;Deposit",
        "2024.03.04 09:00:00;Buy;0.10;EURUSD;1.08000;;;2024.03.04 15:00:00;1.08150;-0.50;"
        "-0.10;15.00;",
        "2024.03.05 09:00:00;Sell;0.10;EURUSD;1.08500;;;2024.03.05 11:00:00;1.08400;-0.50;"
        "0.00;10.00;",
        "2024.03.06 09:00:00;Buy Stop;0.10;EURUSD;1.09000;;;2024.03.06 12:00:00;1.09000;;;;"
        "cancelled",
        "2024.03.07 09:00:00;Sell;0.20;XAUUSD;2 150.00;;;2024.03.07 10:00:00;2 145.00;-1.00;"
        "0.00;100.00;",
        "2024.03.08 12:00:00;Balance;;;;;;;;;;-100.00;Withdrawal",
    ]
).encode("utf-8")
MQL5_POSITIONS = "\n".join(
    [
        "Time;Type;Volume;Symbol;Price;Volume;Time;Price;Commission;Swap;Profit",
        "2024.03.01 08:00:00;Balance;;;;;;;;;500.00",
        "2024.03.04 09:00:00;Buy;0.10;EURUSD;1.08000;0.10;2024.03.04 15:00:00;1.08150;;;15.00",
        "2024.03.05 09:00:00;Sell;0.10;EURUSD;1.08500;0.10;2024.03.05 11:00:00;1.08400;;;10.00",
    ]
).encode("utf-8")


def test_mql5_signal_history_export() -> None:
    assert detect_format(MQL5_HISTORY) == MQL5_SIGNAL_CSV
    report = import_report(MQL5_HISTORY, "history.csv")
    trades = report.trades
    assert len(trades.trades) == 3  # the cancelled Buy Stop is not a trade
    assert [round(t.pnl, 2) for t in trades.trades] == [15.0, 10.0, 100.0]
    assert trades.trades[2].entry_price == 2150.0  # a space thousands separator
    assert trades.fees == pytest.approx([0.6, 0.5, 1.0])
    assert [amount for _, amount in report.cash_flows] == [1000.0, -100.0]
    assert report.initial_balance == 1000.0


def test_mql5_signal_positions_export() -> None:
    report = import_report(MQL5_POSITIONS, "positions.csv")
    assert report.source_format == MQL5_SIGNAL_CSV
    assert [t.exit_price for t in report.trades.trades] == [1.0815, 1.084]
    assert report.initial_balance == 500.0


def _fxblue(accounts: tuple[str, ...] = ("main",)) -> bytes:
    head = (
        "Type,Ticket,Symbol,Lots,Buy/sell,Open price,Close price,Open time,Close time,"
        "Open date,Close date,Profit,Swap,Commission,Net profit,T/P,S/L,Pips,Result,"
        "Trade duration (hours),Magic number,Order comment,Account"
    )
    rows = ["sep=,", head]
    for account in accounts:
        rows += [
            f"Deposit,1,,0,,0,0,2024/10/01 08:00:00,2024/10/01 08:00:00,2024/10/01,2024/10/01,"
            f"5000,0,0,5000,0,0,0,n/a,0,0,,{account}",
            f"Closed position,2,EURUSD,1,Buy,1.1000,1.1010,2024/10/02 09:00:00,"
            f"2024/10/02 10:00:00,2024/10/02,2024/10/02,100,-2,-5,93,0,0,10,Win,1,1,,{account}",
            f"Closed position,3,EURUSD,1,Sell,1.1020,1.1030,2024/10/03 09:00:00,"
            f"2024/10/03 11:00:00,2024/10/03,2024/10/03,-100,0,-5,-105,0,0,-10,Loss,2,1,,{account}",
            f"Open position,4,EURUSD,1,Buy,1.1000,1.0900,2024/10/04 09:00:00,"
            f"1970/01/01 00:00:00,2024/10/04,1970/01/01,-1000,0,0,-1000,0,0,-100,Loss,0,1,,"
            f"{account}",
            f"Pending order,5,EURUSD,1,Buy Stop,1.2000,0,2024/10/04 09:00:00,"
            f"1970/01/01 00:00:00,2024/10/04,1970/01/01,0,0,0,0,0,0,0,n/a,0,1,,{account}",
        ]
    return ("\r\n".join(rows) + "\r\n").encode("utf-8")


def test_fxblue_export() -> None:
    data = _fxblue()
    assert detect_format(data) == FXBLUE_CSV
    report = import_report(data, "orders.csv")
    trades = report.trades
    assert len(trades.trades) == 2  # the open position and the pending order are left out
    assert [t.pnl for t in trades.trades] == [100.0, -100.0]
    assert trades.fees == pytest.approx([7.0, 5.0])
    assert report.initial_balance == 5000.0
    assert not any("accounts" in w for w in report.warnings)


def test_fxblue_with_two_accounts_reads_one_and_says_so() -> None:
    report = import_report(_fxblue(("a", "b")), "orders.csv")
    assert len(report.trades.trades) == 2
    assert [amount for _, amount in report.cash_flows] == [5000.0]
    warning = next(w for w in report.warnings if "2 accounts" in w)
    from quant_trade.audit.i18n import localize

    assert localize(warning, "es").startswith("el archivo trae 2 cuentas")


def test_a_file_with_only_deposits_is_refused_plainly() -> None:
    data = MYFXBOOK_HEAD + "\n,1,01/02/2024 09:00,,,Deposit,0,0,0,0,0,0,0,0,1000.00" + TAIL
    with pytest.raises(ReportFormatError):
        import_report(data.encode("utf-8"), "statement.csv")


@pytest.mark.parametrize("locale", ["es", "en"])
def test_an_uploaded_tracking_export_gets_the_account_money_review(locale: str) -> None:
    from quant_trade.audit.engine import run_audit
    from quant_trade.audit.guard import find_claims
    from quant_trade.audit.i18n import localize
    from quant_trade.audit.report import render_html
    from quant_trade.audit.schema import DeclaredMetadata, build_inputs

    inputs = build_inputs(
        None, DeclaredMetadata(), report_bytes=MQL5_HISTORY, report_filename="history.csv"
    )
    result = run_audit(inputs, bootstrap_samples=50, risk_samples=50, challenge_samples=50)
    data = result.model_dump() if hasattr(result, "model_dump") else result.to_dict()
    assert data["account"]["status"] == "MEASURED"
    page = render_html(result, watermark=False, locale=locale)
    assert "MQL5 signal (CSV)" in page
    assert find_claims(page) == []
    for warning in data["inputs"]["parse_warnings"]:
        if locale == "es":
            assert localize(warning, "es") != warning, warning
