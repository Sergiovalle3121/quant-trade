"""The report shows when the strategy makes and loses money."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from audit_fixtures import csv_bytes, positive_drift, trades_frame

from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize
from quant_trade.audit.report import LABELS, _timing_html, render_html
from quant_trade.audit.schema import DeclaredMetadata, build_inputs
from quant_trade.audit.timing import MIN_TRADES, NOTE, timing_breakdown
from quant_trade.core.models import Trade

NOW = datetime(2026, 1, 1, tzinfo=UTC)
MONDAY = datetime(2025, 1, 6, tzinfo=UTC)


def _trade(entry: datetime, pnl: float) -> Trade:
    return Trade(
        entry_time=entry,
        exit_time=entry + timedelta(hours=2),
        quantity=1.0,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        pnl=pnl,
        return_pct=pnl / 100.0,
    )


def _week_trades() -> list[Trade]:
    """Four weeks: Mondays at 09:00 win 10, Fridays at 15:00 lose 2, others win 1."""
    out = []
    for week in range(4):
        for day in range(5):
            entry = MONDAY + timedelta(days=7 * week + day, hours=9 if day < 4 else 15)
            out.append(_trade(entry, 10.0 if day == 0 else (-2.0 if day == 4 else 1.0)))
    return out


def test_groups_by_weekday_and_block_and_names_the_best() -> None:
    timing = timing_breakdown(_week_trades())
    assert timing["status"] == "MEASURED" and timing["trades"] == 20
    assert timing["net"]["value"] == 4 * (10 + 1 + 1 + 1 - 2)
    monday = timing["weekdays"][0]
    assert monday["key"] == 0 and monday["trades"]["value"] == 4
    assert monday["net"]["value"] == 40 and monday["win_rate"]["value"] == 1.0
    assert timing["best_weekday"]["key"] == 0
    assert abs(timing["best_weekday"]["share"]["value"] - 40 / 44) < 1e-9
    assert [row["key"] for row in timing["blocks"]] == [2, 3]
    assert timing["weekdays"][4]["win_rate"]["value"] == 0.0


def test_too_few_trades_is_not_measured_in_both_languages() -> None:
    timing = timing_breakdown(_week_trades()[: MIN_TRADES - 1])
    assert timing["status"] == "NOT_MEASURED"
    assert localize(timing["reason"], "es") == "menos de 20 operaciones cerradas"
    assert "menos de 20" in _timing_html(timing, "es", LABELS["es"])


def test_daily_entries_have_no_time_of_day_table() -> None:
    trades = [_trade(MONDAY + timedelta(days=i), 1.0) for i in range(MIN_TRADES)]
    timing = timing_breakdown(trades)
    assert timing["blocks"] == [] and timing["best_block"] is None
    html = _timing_html(timing, "es", LABELS["es"])
    assert LABELS["es"]["timing_block"] not in html


def test_section_text_is_translated_and_passes_the_guard() -> None:
    timing = timing_breakdown(_week_trades())
    es = _timing_html(timing, "es", LABELS["es"])
    assert "lunes" in es and "09:" not in es and "08:00–11:59" in es
    assert localize(NOTE, "es") in es
    en = _timing_html(timing, "en", LABELS["en"])
    assert "Mondays" in en
    assert find_claims(es) == [] and find_claims(en) == []


def test_locked_report_shows_the_title_only() -> None:
    inputs = build_inputs(
        csv_bytes(positive_drift(300)),
        DeclaredMetadata(),
        trades_bytes=csv_bytes(trades_frame(30)),
    )
    result = run_audit(inputs, now=NOW, audit_id="tm1", bootstrap_samples=50)
    assert result.timing is not None and result.timing["status"] == "MEASURED"
    paid = render_html(result, watermark=False)
    assert LABELS["es"]["timing_intro"] in paid
    locked = render_html(result, watermark=True, free_mode=False, redeem_url="/r")
    assert LABELS["es"]["timing"] in locked
    assert LABELS["es"]["timing_intro"] not in locked


def test_timing_table_draws_a_bar_per_row_and_marks_losing_groups() -> None:
    from quant_trade.audit.report import LABELS, _timing_table

    def measured(value: float) -> dict[str, object]:
        return {"value": value, "evidence": "MEASURED"}

    rows = [
        {"key": k, "trades": measured(10), "net": measured(net), "win_rate": measured(0.5)}
        for k, net in ((0, 120.0), (1, -300.0), (2, 40.0))
    ]
    html = _timing_table(rows, "Día", lambda k: ("lun", "mar", "mié")[k], LABELS["es"])
    assert html.count("tbar neg") == 1 and html.count("tbar pos") == 2
    assert "--w:100%" in html and "<thead>" in html
