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
