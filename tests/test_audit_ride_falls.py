"""The deepest falls, the Calmar ratio and the worst 5 % of days and months:
the figures a fund fact sheet lists, measured from the curve and never used in
the class. Offline and deterministic."""

from __future__ import annotations

import html
import math
import re
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from quant_trade.audit import report
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.ride import MIN_TAIL_DAYS, MIN_TAIL_MONTHS, WORST_FALLS, ride_review
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

NOW = datetime(2026, 1, 1, tzinfo=UTC)
LOCALES = ("es", "en", "pt")


def _frame(values: list[float], start: str = "2024-01-01", freq: str = "D") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(start, periods=len(values), freq=freq, tz="UTC"),
            "equity": values,
        }
    )


def _two_falls() -> list[float]:
    values = [100.0 + i for i in range(30)]  # high of 129 on day 29
    values += [120.0, 110.0, 100.0]  # low of 100 on day 32
    values += [115.0, 129.0]  # back at 129 on day 34
    values += [130.0 + i for i in range(20)]  # high of 149 on day 54
    values += [140.0, 145.0]  # low of 140 on day 55, still open
    return values


def test_each_fall_runs_from_its_high_to_its_low_and_back() -> None:
    falls = ride_review(_frame(_two_falls()))["worst_falls"]
    assert [round(f["depth"]["value"], 6) for f in falls] == [
        round(100 / 129 - 1, 6),
        round(140 / 149 - 1, 6),
    ]
    first, second = falls
    assert (first["from"], first["low"], first["to"]) == ("2024-01-30", "2024-02-02", "2024-02-04")
    assert (first["fall_days"], first["recovery_days"], first["days"]) == (3, 2, 5)
    # Still below its high at the file's end: open, measured to the last date.
    assert second["to"] is None and second["recovery_days"] is None
    assert second["until"] == "2024-02-26"
    assert second["days"] == 2


def test_the_deepest_fall_in_the_table_is_the_one_the_report_already_shows() -> None:
    rng = np.random.default_rng(4)
    values = list(10_000 * np.cumprod(1 + rng.normal(0.0003, 0.012, 700)))
    ride = ride_review(_frame(values))
    falls = ride["worst_falls"]
    assert len(falls) == WORST_FALLS
    assert math.isclose(falls[0]["depth"]["value"], ride["deepest"]["value"])
    assert (falls[0]["from"], falls[0]["low"]) == (ride["deepest_from"], ride["deepest_low"])
    depths = [f["depth"]["value"] for f in falls]
    assert depths == sorted(depths)
    # Falls never overlap: each starts at or after the previous one ended.
    spans = sorted((f["from"], f["until"]) for f in falls)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:], strict=False))


def test_calmar_is_the_annual_return_over_the_deepest_fall() -> None:
    rng = np.random.default_rng(9)
    values = list(10_000 * np.cumprod(1 + rng.normal(0.0005, 0.01, 800)))
    frame = _frame(values)
    ride = ride_review(frame)
    years = (frame["timestamp"].iloc[-1] - frame["timestamp"].iloc[0]).total_seconds() / (
        365.25 * 86400
    )
    cagr = (values[-1] / values[0]) ** (1 / years) - 1
    assert math.isclose(ride["calmar"]["value"], cagr / abs(ride["deepest"]["value"]))
    # The span goes beside it: a longer history has a deeper fall to divide by.
    assert ride["calmar"]["years"] == round(years, 1)
    # Under a year of history the ratio would divide an exaggerated annual return.
    short = ride_review(_frame(values[:300]))
    assert short["calmar"]["evidence"] == "NOT_MEASURED"
    rising = ride_review(_frame([100.0 + i for i in range(400)]))
    assert rising["calmar"]["evidence"] == "NOT_MEASURED"
    assert rising["worst_falls"] == []


def test_the_tail_averages_the_worst_five_percent() -> None:
    rng = np.random.default_rng(2)
    values = list(10_000 * np.cumprod(1 + rng.normal(0.0002, 0.01, 200)))
    ride = ride_review(_frame(values))
    returns = pd.Series(values).pct_change().dropna().to_numpy()
    worst = np.sort(returns)[: math.ceil(0.05 * len(returns))]
    assert ride["tail_day"]["count"] == len(worst) == 10
    assert math.isclose(ride["tail_day"]["value"], float(worst.mean()))
    # Too few days or months: the worst 5 % would be one of them or none.
    few = ride_review(_frame(values[: MIN_TAIL_DAYS - 1]))
    assert few["tail_day"]["evidence"] == "NOT_MEASURED"
    assert ride["tail_month"]["evidence"] == "NOT_MEASURED"
    months = ride_review(_frame(values[:MIN_TAIL_MONTHS] + [values[-1]], freq="ME"))
    assert months["tail_month"]["evidence"] == "MEASURED"
    assert (months["tail_month"]["count"], months["tail_month"]["of"]) == (2, MIN_TAIL_MONTHS)


def test_a_record_opening_on_its_base_month_counts_no_empty_month() -> None:
    # A fund record starts at the month before its first return.
    values = [100.0, 101.0, 99.0, 102.0, 103.0]
    ride = ride_review(_frame(values * 5, start="2019-12-31", freq="ME"))
    assert ride["months"]["value"] == 24


def _grid() -> bytes:
    rng = np.random.default_rng(5)
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    lines = [",".join(["Year", *months])]
    for year in range(6):
        values = rng.normal(0.006, 0.035, 12)
        lines.append(",".join([str(2018 + year), *(f"{v * 100:.2f}%" for v in values)]))
    return ("\n".join(lines) + "\n").encode()


def _daily() -> bytes:
    rng = np.random.default_rng(11)
    equity = 10_000 * np.cumprod(1 + rng.normal(0.0004, 0.01, 500))
    days = np.datetime64("2022-01-03") + np.arange(500)
    lines = ["timestamp,equity"] + [f"{d},{e:.2f}" for d, e in zip(days, equity, strict=True)]
    return ("\n".join(lines) + "\n").encode()


def _text(page: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


@pytest.mark.parametrize("upload", [_grid, _daily])
@pytest.mark.parametrize("locale", LOCALES)
def test_the_report_lists_the_falls_and_ratios_in_every_language(upload, locale: str) -> None:
    result = run_audit(
        build_inputs(upload(), DeclaredMetadata()), now=NOW, audit_id="falls", bootstrap_samples=60
    )
    data = result.model_dump(mode="json")
    assert untranslated(data) == []
    labels = report.LABELS[locale]
    shown = _text(report.render_html(result, watermark=False, locale=locale))
    assert labels["falls_title"] in shown
    calmar = labels["ride_calmar"].format(years=f"{data['ride']['calmar']['years']:.1f}")
    assert calmar in shown
    fund = (data.get("fund") or {}).get("status") == "MEASURED"
    assert labels["falls_below" if fund else "falls_total"] in shown
    tail = data["ride"]["tail_month" if fund else "tail_day"]
    key = "ride_tail_month" if fund else "ride_tail_day"
    assert labels[key].format(k=tail["count"], n=tail["of"]) in shown
    assert find_claims(shown) == []
