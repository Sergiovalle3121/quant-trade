"""A date after the upload is refused in every file; a fund table's months
that have not happened yet (blank, a dash or 0) are not. Fixed clock."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_trade.audit.i18n import untranslated
from quant_trade.audit.schema import (
    FUTURE_FLAT_WARNING,
    DeclaredMetadata,
    ParseError,
    build_inputs,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
MONTHS = "Year,Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec"


def _curve(last: str) -> bytes:
    days = [f"2026-09-{day:02d}" for day in range(1, 25)] + [last]
    rows = [f"{day},{10_000 + 10 * i}" for i, day in enumerate(days)]
    return ("date,equity\n" + "\n".join(rows) + "\n").encode()


def _grid(this_year: str) -> bytes:
    past = [f"{year}," + ",".join(["1.10%", "-0.40%"] * 6) for year in range(2022, 2026)]
    return "\n".join([MONTHS, *past, f"2026,{this_year}"]).encode() + b"\n"


def _trades(exit_day: str) -> bytes:
    lines = ["Symbol,Side,Quantity,Entry time,Exit time,Entry price,Exit price,Profit"]
    for day in range(1, 21):
        lines.append(f"AAPL,Buy,10,2026-08-{day:02d} 10:00,2026-08-{day:02d} 15:00,100,101,10")
    lines.append(f"AAPL,Buy,10,2026-08-21 10:00,{exit_day} 15:00,100,101,10")
    return ("\n".join(lines) + "\n").encode()


def _refused(**kwargs: object) -> ParseError:
    with pytest.raises(ParseError) as caught:
        build_inputs(now=NOW, declared=DeclaredMetadata(), **kwargs)  # type: ignore[arg-type]
    assert caught.value.code == "future_dates"
    return caught.value


def test_an_equity_curve_dated_in_the_future_is_refused_in_both_languages() -> None:
    error = _refused(equity_bytes=_curve("2150-01-01"))
    assert "2150-01-01" in str(error) and "in the future" in str(error)
    assert "fecha en el futuro (2150-01-01)" in error.localized("es")


def test_a_day_of_slack_is_allowed_for_time_zones() -> None:
    inputs = build_inputs(_curve("2026-09-26"), DeclaredMetadata(), now=NOW)
    assert inputs.equity.frame["timestamp"].iloc[-1].day == 26


def test_this_years_months_that_have_not_happened_yet_are_dropped() -> None:
    # Jan to Aug happened; Sep is running; Oct to Dec are 0, blank or a dash.
    done = ",".join(["0.50%", "-0.20%"] * 4) + ",0.30%"
    for rest in ("0.00%,0.00%,0.00%", ",,", "-,-,-", "0,0,0"):
        inputs = build_inputs(_grid(f"{done},{rest}"), DeclaredMetadata(), now=NOW)
        # September is this month: dated by its last day, still not the future.
        assert inputs.equity.frame["timestamp"].max().strftime("%Y-%m") == "2026-09"
        dropped = [w for w in inputs.warnings if "have not happened yet" in w]
        assert dropped == (["equity: 3 " + FUTURE_FLAT_WARNING] if "0" in rest else [])
        assert untranslated({"inputs": {"parse_warnings": inputs.warnings}}) == []


def test_a_future_month_that_moves_the_account_is_refused() -> None:
    done = ",".join(["0.50%", "-0.20%"] * 4) + ",0.30%"
    _refused(equity_bytes=_grid(f"{done},0.00%,2.00%,0.00%"))


def test_future_trades_are_refused_in_a_report_a_trades_file_and_a_live_statement() -> None:
    report = _refused(equity_bytes=None, report_bytes=_trades("2150-08-21"),
                      report_filename="trades.csv")  # fmt: skip
    assert "report file" in str(report)
    live = _refused(equity_bytes=None, report_bytes=_trades("2026-08-21"),
                    report_filename="trades.csv", live_bytes=_trades("2150-08-21"),
                    live_filename="live.csv")  # fmt: skip
    assert "live account statement" in str(live)
    assert "estado de cuenta real" in live.localized("es")


def test_a_benchmark_dated_in_the_future_is_refused() -> None:
    error = _refused(equity_bytes=_curve("2026-09-25"), benchmark_bytes=_curve("2150-01-01"))
    assert "benchmark file" in str(error)
