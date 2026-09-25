"""NinjaTrader exports as users send them: the Executions tab and a French terminal.

The row layouts follow public importers of real NinjaTrader files
(tradetally's NinjaTrader tests, deltalytix's French column names); the
values here are synthetic.
"""

from __future__ import annotations

import pytest

from quant_trade.audit.guard import find_claims
from quant_trade.audit.importers import (
    FUTURES_POINT_VALUE_USD,
    NINJATRADER_CSV,
    NINJATRADER_EXECUTIONS_CSV,
    ReportFormatError,
    detect_format,
    import_report,
)

EXEC_HEADER = (
    "Instrument;Action;Quantity;Price;Time;ID;E/X;Position;Order ID;Name;Commission;Rate;"
    "Account display name;Connection;"
)


def _fill(instrument: str, action: str, qty: int, price: str, time: str, ex: str) -> str:
    account = "0,62 $;1;Playback101;Playback;"
    return f"{instrument};{action};{qty};{price};{time};id;{ex};-;o;{ex};{account}"


def _executions(extra: list[str] | None = None) -> bytes:
    rows = [
        # A long MES: 4 points at 5 USD, minus 1.24 of commission.
        _fill("MES JUN26", "Buy", 1, "7200,75", "27/04/2026 6:05:02", "Entry"),
        _fill("MES JUN26", "Sell", 1, "7204,75", "27/04/2026 6:10:02", "Exit"),
        # A short NQ of 2 contracts closed in two fills.
        _fill("NQ JUN26", "Sell", 2, "23960,00", "28/04/2026 9:30:00", "Entry"),
        _fill("NQ JUN26", "Buy", 1, "23950,00", "28/04/2026 9:35:00", "Exit"),
        _fill("NQ JUN26", "Buy", 1, "23970,00", "28/04/2026 9:40:00", "Exit"),
        *(extra or []),
    ]
    return ("\n".join([EXEC_HEADER, *rows]) + "\n").encode()


def test_an_executions_export_is_paired_into_priced_round_trips() -> None:
    assert detect_format(_executions()) == NINJATRADER_EXECUTIONS_CSV
    report = import_report(_executions(), "NinjaTrader Executions.csv")
    trades = report.trades.trades
    assert len(trades) == 3
    first = trades[0]
    assert (first.entry_price, first.exit_price) == (7200.75, 7204.75)
    fees = report.trades.fees or []
    net = [round(trade.pnl - fee, 2) for trade, fee in zip(trades, fees, strict=True)]
    # MES: +4 points x 5 USD - 0.62 per fill. NQ: the 0.62 of the 2-lot entry is split
    # between its two exits, so each closes +-10 points x 20 USD - (0.31 + 0.62).
    assert net == [18.76, 199.07, -200.93]


def test_a_position_still_open_is_left_out_and_said() -> None:
    extra = [_fill("MES JUN26", "Buy", 1, "7210,00", "29/04/2026 6:00:00", "Entry")]
    report = import_report(_executions(extra), "NinjaTrader Executions.csv")
    assert len(report.trades.trades) == 3
    assert any("still open" in warning for warning in report.warnings)


def test_an_unknown_contract_asks_for_the_trades_tab() -> None:
    extra = [
        _fill("FDAX 06-26", "Buy", 1, "18000,0", "29/04/2026 6:00:00", "Entry"),
        _fill("FDAX 06-26", "Sell", 1, "18010,0", "29/04/2026 6:05:00", "Exit"),
    ]
    with pytest.raises(ReportFormatError) as error:
        import_report(_executions(extra), "NinjaTrader Executions.csv")
    assert error.value.code == "ninjatrader_executions_symbol"
    assert "FDAX" in str(error.value) and "Trades" in error.value.message_es
    assert find_claims(str(error.value)) == [] and find_claims(error.value.message_es) == []
    assert "FDAX" not in FUTURES_POINT_VALUE_USD


FRENCH_HEADER = (
    "Numéro d’ordre;Instrument;Compte;Stratégie;Pos. marché.;Qté;Prix d'entrée;"
    "Prix de sortie;Heure d'entrée;Heure de sortie;Nom d'entrée;Nom de la sortie;Profit;"
    "Commission;MAE;MFE;ETD"
)


def test_a_french_trades_export_is_read() -> None:
    rows = [
        f"{i};NQ JUN26;Sim101;S1;{'Short' if i % 2 else 'Long'};1;23960,00;23955,50;"
        f"{i + 12}/04/2026 10:00:00;{i + 12}/04/2026 10:03:00;Entrée;Sortie;"
        f"{'90,00' if i % 2 else '-90,00'} $;0,00 $;0,00 $;0,00 $;0,00 $"
        for i in range(1, 13)
    ]
    data = ("\n".join([FRENCH_HEADER, *rows]) + "\n").encode()
    assert detect_format(data) == NINJATRADER_CSV
    parsed = import_report(data, "NinjaTrader Grid.csv").trades
    trades = parsed.trades
    assert len(trades) == 12
    assert parsed.sides[:2] == ["short", "long"]
    assert round(sum(trade.pnl for trade in trades), 2) == 0.0


def test_english_trades_rows_with_a_dollar_suffix_and_day_first_times_are_read() -> None:
    header = (
        "Trade number,Instrument,Account,Strategy,Market pos.,Qty,Entry price,Exit price,"
        "Entry time,Exit time,Entry name,Exit name,Profit,Cum. net profit,Commission,"
        "Clearing Fee,Exchange Fee,IP Fee,NFA Fee,MAE,MFE,ETD,Bars,"
    )
    row = (
        "1,NQ JUN26,PA-APEX-1!Apex!Apex,100-100-5,Short,1,23960.00,23955.50,"
        "13-04-2026 00:27:56,13-04-2026 00:30:54,Entry,Target1,90.00 $,90.00 $,0.00 $,0.00 $,"
        "0.00 $,0.00 $,0.00 $,160.00 $,105.00 $,15.00 $,0,"
    )
    trades = import_report(f"{header}\n{row}\n".encode(), "Apex.csv").trades.trades
    assert len(trades) == 1
    assert trades[0].pnl == pytest.approx(90.0)
    assert trades[0].entry_time.day == 13 and trades[0].entry_time.month == 4
