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
