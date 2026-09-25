"""What a first-time buyer reads first: the live account under the verdict,
thresholds that say which side they fall on, and no step asking for a file
already uploaded. From a non-technical buyer's read of /ejemplo."""

from __future__ import annotations

from functools import lru_cache

from quant_trade.audit.report import render_html
from quant_trade.audit.sample import sample_result


@lru_cache(maxsize=2)
def _page(locale: str) -> str:
    return render_html(sample_result(locale, bootstrap_samples=60), watermark=False)


def test_the_live_account_shows_under_the_verdict() -> None:
    page = _page("es")
    hero = page[: page.index("<nav class='report-toc")]
    assert "Cuenta real: En el borde." in hero
    assert "Resultado de operar: -305.20 sobre 1,500.00 depositados." in hero
    assert "href='#r-d3'" in hero
    assert "Live account: At the edge." in _page("en")


def test_a_locked_report_keeps_the_live_line_back() -> None:
    page = render_html(
        sample_result("es", bootstrap_samples=60), watermark=True, free_mode=False
    )
    assert "Cuenta real: En el borde." not in page


def test_the_plan_says_which_side_of_each_bar_the_numbers_fall() -> None:
    page = _page("es")
    assert "supera con 0.95 o más, y por debajo de 0.5 no supera" in page
    assert "hace falta 0.5 o más (cumple)" in page
    assert "el máximo es 1.0 (no cumple)" in page
    # The optimisation export was uploaded: no step asks for it again.
    assert "Sube el XML de la optimización" not in page
    assert "El número de intentos ya sale de tus archivos" in page


def test_the_pairing_row_says_whose_trades_it_counts() -> None:
    page = _page("es")
    assert "Operaciones del backtest que la cuenta real no hizo" in page
    assert "Backtest trades the live account did not take" in _page("en")


def test_no_sentence_reads_as_an_accusation() -> None:
    for locale in ("es", "en"):
        page = _page(locale)
        for phrase in (
            "señal clásica",
            "huella típica",
            "más se retoca",
            "classic sign",
            "usual mark",
            "most often retouched",
        ):
            assert phrase not in page


def test_what_to_do_now_speaks_to_the_buyer_and_links_each_step() -> None:
    page = _page("es")
    start = page.index("id='r-next'")
    box = page[start : page.index("</section>", start)]
    assert "<h2>Qué hacer ahora</h2>" in box
    # The sample's open points, in order: live account, costs, trials; then the
    # questions and a closing step.
    order = [
        "tu cuenta real queda fuera",
        "Compara el spread",
        "cuántas configuraciones",
        "Lleva al vendedor las preguntas",
        "Guarda este informe",
    ]
    positions = [box.index(text) for text in order]
    assert positions == sorted(positions)
    assert box.count("Ir al apartado") == 4
    assert "What to do now" in _page("en")


def test_the_evidence_tags_are_explained_under_the_verdict() -> None:
    page = _page("es")
    hero = page[: page.index("<nav class='report-toc")]
    assert "MEASURED, calculada de tus archivos" in hero
    assert "MEASURED, computed from your files" in _page("en")


def test_generic_prop_firm_rules_show_no_internal_id_or_missing_date() -> None:
    page = _page("es")
    assert "generic-2step" not in page
    assert "publicadas en la fecha indicada" not in page
    assert "En las simulaciones del historial" in page


def test_one_win_rate_after_itemised_fees_across_the_report() -> None:
    from datetime import UTC, datetime, timedelta

    from quant_trade.audit.analytics import trade_statistics
    from quant_trade.audit.timing import timing_breakdown
    from quant_trade.core.models import Trade

    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    trades = [
        Trade(
            entry_time=t0 + timedelta(days=i),
            exit_time=t0 + timedelta(days=i, hours=3),
            quantity=1.0,
            entry_price=1.0,
            exit_price=1.0,
            pnl=pnl,
            return_pct=0.0,
        )
        for i, pnl in enumerate([5.0, 0.5, -3.0, 0.4] * 5)
    ]
    fees = [1.0] * len(trades)
    sides = ["long", "short"] * 10
    stats = trade_statistics(trades, sides, fees_total=20.0, trade_fees=fees)
    # 0.5 and 0.4 are gross wins that the 1.0 fee turns into losses.
    assert stats["win_rate"]["value"] == 0.25
    assert stats["win_rate_gross"]["value"] == 0.75
    assert stats["long"]["win_rate"]["value"] == 0.5
    timing = timing_breakdown(trades, fees)
    assert sum(row["net"]["value"] for row in timing["weekdays"]) == sum(
        t.pnl - 1.0 for t in trades
    )
    # Without itemised fees nothing changes.
    plain = trade_statistics(trades, sides, trade_fees=[0.0] * len(trades))
    assert plain["win_rate"]["value"] == 0.75 and "win_rate_gross" not in plain


def test_the_sample_shows_the_net_win_rate_once_in_the_tiles_and_tables() -> None:
    page = _page("es")
    assert "560 · 54%" in page
    assert "Aciertos antes de comisiones" in page
    # The gross share (55.54%) shows once, on its own labelled row, not
    # again in the annualised table.
    assert page.count("55.54%") == 1


def test_figures_carry_their_unit_and_plain_names() -> None:
    page = _page("es")
    # Header: the engine version and seed say what they are.
    assert "versión del motor 0.1.0" in page and "semilla de las simulaciones" in page
    assert "quant_trade.audit" not in page
    # Resampled time under the peak says median and 1 in 20, not p50/p95.
    assert "Periodos seguidos bajo el máximo, en las simulaciones: mediana" in page
    assert "en 1 de cada 20" in page
    # The capital cards say whose balance they scale to.
    assert "Tamaño sobre el balance inicial del archivo (10,000)" in page
    # The drop distance says which values matter.
    assert "(-2 o menos: una caída que el azar difícilmente explica)" in page
    # The cost table explains its few cents of difference with the trades' net.
    assert "sin coste extra da 6,425.50, 0.47 de diferencia" in page
    english = _page("en")
    assert "engine version 0.1.0" in english and "in 1 of every 20" in english
    assert "with no extra cost it gives 6,425.50" in english


def test_long_and_short_results_are_net_after_itemised_fees() -> None:
    page = _page("es")
    # Long plus short now add up to the trades' net result.
    assert "después de los costes que el archivo detalla por operación" in page
    assert "antes de comisión y swap" not in page
