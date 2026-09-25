"""The luck discount and the lived history: plain numbers from published math."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from quant_trade.audit.engine import _multiplicity, _significance
from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.i18n import spanish, untranslated
from quant_trade.audit.luck import luck_review
from quant_trade.audit.report import LABELS, render_html
from quant_trade.audit.ride import ride_review
from quant_trade.audit.sample import sample_result


def _luck_for(returns: pd.Series, trials: int) -> tuple[dict, dict]:
    _, moments = _significance(returns)
    multiplicity = _multiplicity(moments, declared_trials=trials, variants=None, trials_used=trials)
    luck = luck_review(
        moments,
        trials=trials,
        trials_source="declared by the client",
        sharpe_variance=float(multiplicity["sharpe_variance_used"]["value"]),
        periods_per_year=252.0,
        span_years=len(returns) / 252.0,
    )
    return luck, multiplicity


def _returns(mean: float, n: int = 750, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(mean, 0.01, n))


def test_luck_agrees_with_the_deflated_sharpe() -> None:
    for mean in (0.0002, 0.0006, 0.001, 0.002):
        for trials in (2, 10, 100, 1000):
            luck, multiplicity = _luck_for(_returns(mean), trials)
            if luck["status"] != "MEASURED":
                continue
            dsr = float(multiplicity["dsr_at_trials_used"]["value"])
            # Beating the luck is the same test as a DSR of at least 0.5.
            assert luck["beats_luck"] == (dsr >= 0.5)
            after = float(luck["sharpe_after"]["value"])
            if after > 0:
                assert luck["beats_luck"]
                assert after < float(luck["sharpe"]["value"])
            # Years needed sit below the span exactly when the Sharpe beats the luck.
            needed = float(luck["years_needed"]["value"])
            assert (needed < float(luck["span_years"]["value"])) == luck["beats_luck"]


def test_a_strong_history_keeps_part_of_its_sharpe() -> None:
    luck, _ = _luck_for(_returns(0.002), 10)
    assert luck["beats_luck"]
    assert 0 < float(luck["haircut"]["value"]) < 1
    assert math.isclose(
        float(luck["sharpe"]["value"]),
        float(_returns(0.002).mean() / _returns(0.002).std(ddof=1) * math.sqrt(252)),
        rel_tol=1e-6,
    )


def test_luck_needs_a_search_and_a_gain() -> None:
    assert _luck_for(_returns(0.002), 1)[0]["counted"] is False
    assert _luck_for(_returns(-0.002), 50)[0]["status"] == "NOT_MEASURED"
    assert (
        luck_review(
            None,
            trials=50,
            trials_source="",
            sharpe_variance=None,
            periods_per_year=252,
            span_years=3,
        )["status"]
        == "NOT_MEASURED"
    )


def _frame(values: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    stamps = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.DataFrame({"timestamp": stamps, "equity": values})


def test_ride_reads_the_stretches_under_water() -> None:
    values = [100.0 + i for i in range(30)]  # up to 129 on day 29
    values += [120.0, 110.0, 100.0]  # low of 100 on day 32
    values += [105.0, 115.0, 125.0, 130.0]  # back above 129 on day 36
    values += [131.0 + i for i in range(40)]
    ride = ride_review(_frame(values))
    assert ride["status"] == "MEASURED"
    assert ride["longest_under"]["value"] == 7
    assert (ride["longest_under_from"], ride["longest_under_to"]) == ("2024-01-30", "2024-02-06")
    assert ride["fall_days"]["value"] == 3
    assert ride["recovery_days"]["value"] == 4
    assert ride["recovered"] is True
    assert math.isclose(ride["deepest"]["value"], 100 / 129 - 1)
    assert math.isclose(ride["worst_day"]["value"], 100 / 110 - 1)
    assert ride["worst_day_on"] == "2024-02-02"
    assert ride["months"]["value"] == 3
    assert ride["positive_months"]["value"] == 1.0
    assert ride["losing_months_run"]["value"] == 0


def test_ride_says_when_the_fall_is_never_regained() -> None:
    values = [100.0 + i for i in range(40)] + [120.0 - i for i in range(60)]
    ride = ride_review(_frame(values))
    assert ride["recovered"] is False
    assert ride["recovery_days"]["evidence"] == "NOT_MEASURED"
    assert ride["longest_under_recovered"] is False
    assert ride["longest_under"]["value"] == 60
    assert ride["losing_months_run"]["value"] >= 2


def test_ride_leaves_out_what_the_curve_cannot_show() -> None:
    assert ride_review(_frame([100.0] * 5))["status"] == "NOT_MEASURED"
    weekly = pd.DataFrame(
        {
            "timestamp": pd.date_range("2020-01-03", periods=60, freq="W", tz="UTC"),
            "equity": [100.0 + i for i in range(60)],
        }
    )
    ride = ride_review(weekly)
    assert ride["worst_day"]["evidence"] == "NOT_MEASURED"
    assert ride["months"]["evidence"] == "MEASURED"


def test_the_report_shows_both_sections_in_both_languages() -> None:
    result = sample_result("es", bootstrap_samples=60)
    data = result.model_dump(mode="json")
    assert data["luck"]["status"] == "MEASURED" and data["ride"]["status"] == "MEASURED"
    assert untranslated(data) == []
    es = render_html(result, watermark=False)
    assert "¿Cuánto queda al descontar la suerte?</h2>" in es
    assert "No supera a la suerte" in es
    assert "Sharpe que darían 120 configuraciones sin habilidad" in es
    assert "Cómo se vivió este historial</h2>" in es
    assert "Tiempo más largo sin un nuevo máximo" in es
    en = render_html(sample_result("en", bootstrap_samples=60), watermark=False)
    assert "What is left once luck is discounted?</h2>" in en
    assert "What living through this history was like</h2>" in en
    for locale in ("es", "en"):
        assert_report_clean(
            " ".join(str(v) for k, v in LABELS[locale].items() if k.startswith(("luck", "ride")))
        )
    for note in (data["luck"]["note"], data["ride"]["note"]):
        assert spanish(note)
    # A locked preview names the sections without their figures.
    locked = render_html(result, watermark=True, free_mode=False)
    assert "Sharpe que darían 120 configuraciones" not in locked
    assert "Tiempo más largo sin un nuevo máximo" not in locked


def test_too_short_a_history_is_not_discounted() -> None:
    assert _luck_for(_returns(0.002, n=15), 50)[0]["status"] == "NOT_MEASURED"


def test_without_a_count_the_report_shows_what_each_search_would_need() -> None:
    result = sample_result("es", bootstrap_samples=60)
    uncounted, _ = _luck_for(_returns(0.002), 1)
    assert uncounted["counted"] is False and "beats_luck" not in uncounted
    assert [row["trials"] for row in uncounted["what_if"]] == [10, 100, 1000]
    page = render_html(result.model_copy(update={"luck": uncounted}), watermark=False)
    section = page[page.index("¿Cuánto queda al descontar la suerte?</h2>") :]
    section = section[: section.index("</section>")]
    assert "Los archivos no dicen cuántas configuraciones se probaron" in section
    assert "Supera a la suerte" not in section and "No supera a la suerte" not in section
    assert ">1,000</td>" in section and "¿Alcanza este historial?" in section
