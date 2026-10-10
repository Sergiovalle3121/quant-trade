"""The sample institutional review (``/revision-institucional/ejemplo``).

What a client of the standard review receives, built in memory: the Rigor report
of one return series, with its benchmark and the variants it was chosen from, and
the written methodology notes on top. Here the series is the top decile of ten
portfolios sorted on past returns (momentum), the variants are the ten deciles,
declared as the ten attempts the series was chosen from, and the benchmark is the
market. It is nobody's portfolio.

Why the data is synthetic. The brief asked for the Kenneth R. French Data
Library's "10 Portfolios Formed on Momentum" and its market factor. Their files
were downloaded on 2026-10-10 (built, they say, with the 202608 CRSP database).
Each ends with "Copyright 2026 Eugene F. Fama and Kenneth R. French" and the
library's page gives no licence to copy or redistribute them; the repository
also keeps market data out of git (``AGENTS.md``). So no month of that data is
stored or shown: the series are generated from a fixed seed, with each decile's
monthly alpha, market and momentum loadings and residual volatility, and the
market's and the momentum factor's moments, set from summary statistics of those
files (value-weighted deciles, January 1963 to December 2025, 756 months; an
ordinary least squares fit of each decile's excess return on the market's
excess return and the momentum factor). Those rounded statistics are the
constants below; nothing else from the files is kept.

The engine, the report and the PDF are the production ones. The run is offline
(no public market data is read, so cash is taken as zero and the report says
so), with a fixed clock and id, so the page and the PDF never change between
restarts. The notes read every figure from the result (``note_figures``), so
they cannot disagree with the report; the engine attributes the return to one
factor (the benchmark) only, so attribution to several factors is left to the
extended review, without figures.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit import institutional
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.report import DIMENSION_TITLES, STATUS_TEXT, evidence_label
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs
from quant_trade.audit.verdict import DIMENSION_ORDER, class_text

#: The generator's seed (the day the sample was made) and its months: twenty years
#: of month ends, January 2006 to December 2025.
SEED = 20261010
MONTHS = 240
FIRST_MONTH_END = "2006-01-31"
#: A fixed clock and id, so the result, its seal and the PDF never change.
NOW = datetime(2026, 10, 10, tzinfo=UTC)
AUDIT_ID = "sample"
BOOTSTRAP = 500
#: Ten portfolios, the tenth (past winners) being the series under review.
VARIANTS = 10
SELECTED = 10

#: Where the summary statistics come from, when they were downloaded and the window
#: they were computed on.
SOURCE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html"
SOURCE_DOWNLOADED = "2026-10-10"
SOURCE_WINDOW = ("1963-01", "2025-12")
#: Each decile's monthly alpha, market beta, momentum beta and residual standard
#: deviation, from Lo PRIOR (1) to Hi PRIOR (10), rounded.
DECILE_ALPHA = (-0.0026, 0.0019, 0.0031, 0.0024, 0.0012, 0.0009, 0.0003, 0.0002, -0.0006, 0.0003)
DECILE_MARKET_BETA = (1.34, 1.11, 0.96, 0.93, 0.90, 0.93, 0.92, 0.96, 1.01, 1.25)
DECILE_MOMENTUM_BETA = (-0.96, -0.73, -0.56, -0.33, -0.19, -0.08, 0.05, 0.22, 0.32, 0.58)
DECILE_RESIDUAL_SD = (0.033, 0.017, 0.016, 0.017, 0.016, 0.017, 0.017, 0.015, 0.016, 0.023)
#: The market's monthly excess return (mean and standard deviation; Student's t
#: with 6 degrees of freedom for its fat tails) and the monthly cash rate.
MARKET_EXCESS_MEAN = 0.0060
MARKET_EXCESS_SD = 0.0445
MARKET_T_DOF = 6
CASH_MONTHLY = 0.0036
#: The momentum factor: intercept and slope on the market, and its own shock, a
#: mix of ordinary months and a few crash months chosen by hand to give the
#: residual's standard deviation (0.041) a fat left tail, as momentum crashes do.
MOMENTUM_INTERCEPT = 0.0069
MOMENTUM_ON_MARKET = -0.161
MOMENTUM_CRASH_SHARE = 0.03
MOMENTUM_CRASH = (-0.12, 0.05)
MOMENTUM_ORDINARY = (0.0037, 0.032)

#: The word the report's tab title and the PDF's name use for this sample.
REPORT_NAMES = {
    "es": "revision-institucional-ejemplo",
    "en": "institutional-review-sample",
    "pt": "revisao-institucional-exemplo",
}


def synthetic_panel() -> pd.DataFrame:
    """The ten decile portfolios and the market, monthly total returns in
    fractions: ``date``, ``decile_1`` to ``decile_10`` and ``market``."""
    rng = np.random.default_rng(SEED)
    scale = MARKET_EXCESS_SD / np.sqrt(MARKET_T_DOF / (MARKET_T_DOF - 2))
    market = MARKET_EXCESS_MEAN + scale * rng.standard_t(MARKET_T_DOF, size=MONTHS)
    crash = rng.random(MONTHS) < MOMENTUM_CRASH_SHARE
    shock = np.where(
        crash,
        rng.normal(*MOMENTUM_CRASH, size=MONTHS),
        rng.normal(*MOMENTUM_ORDINARY, size=MONTHS),
    )
    momentum = MOMENTUM_INTERCEPT + MOMENTUM_ON_MARKET * market + shock
    residuals = rng.normal(size=(MONTHS, VARIANTS)) * np.array(DECILE_RESIDUAL_SD)
    deciles = (
        CASH_MONTHLY
        + np.array(DECILE_ALPHA)
        + np.outer(market, DECILE_MARKET_BETA)
        + np.outer(momentum, DECILE_MOMENTUM_BETA)
        + residuals
    )
    frame = pd.DataFrame(deciles, columns=[f"decile_{i}" for i in range(1, VARIANTS + 1)])
    frame.insert(0, "date", pd.date_range(FIRST_MONTH_END, periods=MONTHS, freq="ME"))
    frame["market"] = CASH_MONTHLY + market
    return frame


def _csv(frame: pd.DataFrame, columns: list[str], names: list[str]) -> bytes:
    lines = ["date," + ",".join(names)]
    for row in frame.itertuples(index=False):
        values = ",".join(f"{getattr(row, column):.6f}" for column in columns)
        lines.append(f"{row.date:%Y-%m-%d},{values}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def sample_files() -> dict[str, bytes]:
    """The three uploads of the sample: the series, its benchmark and its variants."""
    panel = synthetic_panel()
    deciles = [f"decile_{i}" for i in range(1, VARIANTS + 1)]
    return {
        "series": _csv(panel, [f"decile_{SELECTED}"], ["return"]),
        "benchmark": _csv(panel, ["market"], ["return"]),
        "variants": _csv(panel, deciles, deciles),
    }


def sample_result(locale: str = "es", *, bootstrap_samples: int = BOOTSTRAP) -> AuditResult:
    """The sample's audit in ``locale``, offline and deterministic.

    Declared as a return table (monthly, in fractions) a provider offers to
    others, with the market as benchmark and ten trials, one per column of the
    variants file. No cost and no out-of-sample start are declared: the series
    carries neither, and the report says what that leaves unmeasured."""
    files = sample_files()
    declared = DeclaredMetadata(
        trials=VARIANTS,
        cost_bps_per_side=0.0,
        cost_declared=False,
        oos_start=None,
        description="",
        benchmark_applicable=True,
        locale=locale if locale in ("es", "en", "pt") else "es",
        return_frequency="monthly",
        return_unit="fraction",
        ownership="provider",
    )
    inputs = build_inputs(
        files["series"],
        declared,
        benchmark_bytes=files["benchmark"],
        variants_bytes=files["variants"],
        now=NOW,
    )
    return run_audit(inputs, bootstrap_samples=bootstrap_samples, now=NOW, audit_id=AUDIT_ID)


# ---------------------------------------------------------------------------
# The figures the notes quote, read from the result
# ---------------------------------------------------------------------------

#: Where each figure the notes quote lives in the result, and how it is shown.
FIGURE_PATHS: dict[str, tuple[tuple[str, ...], str]] = {
    "months": (("inputs", "observations"), "int"),
    "cagr": (("performance", "cagr"), "pct"),
    "volatility": (("performance", "volatility"), "pct"),
    "sharpe": (("performance", "sharpe"), "ratio"),
    "max_drawdown": (("performance", "max_drawdown"), "pct"),
    "under_water": (("fund", "longest_under_water"), "int"),
    "psr": (("significance", "psr"), "prob"),
    "trials": (("multiplicity", "trials_used"), "int"),
    "dsr": (("multiplicity", "dsr_at_trials_used"), "prob"),
    "luck_sharpe": (("luck", "luck_sharpe"), "ratio"),
    "years_needed": (("luck", "years_needed"), "years"),
    "pbo": (("cscv", "pbo"), "pct"),
    "index_cagr": (("fund", "benchmark", "index_cagr"), "pct"),
    "excess": (("fund", "benchmark", "excess"), "signed"),
    "tracking_error": (("fund", "benchmark", "tracking_error"), "pct"),
    "information_ratio": (("fund", "benchmark", "information_ratio"), "ratio"),
    "beta": (("fund", "benchmark", "skill", "beta"), "ratio"),
    "exposure_share": (("fund", "benchmark", "skill", "attribution", "exposure_share"), "pct"),
    "alpha": (("fund", "benchmark", "skill", "alpha"), "signed"),
    "alpha_low": (("fund", "benchmark", "skill", "alpha_range", "low"), "signed"),
    "alpha_high": (("fund", "benchmark", "skill", "alpha_range", "high"), "signed"),
    "alpha_t": (("fund", "benchmark", "skill", "alpha_t_stat"), "ratio"),
}


@dataclass(frozen=True)
class Figure:
    """One figure as the notes show it: the value from the result, its evidence
    tag and its text ("—" when the report could not measure it)."""

    key: str
    value: float | int | None
    evidence: str
    shown: str


def _lookup(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = data
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _show(value: float | int, style: str) -> str:
    if style == "int":
        return f"{int(value):,}"
    if style == "pct":
        return f"{value:.1%}"
    if style == "signed":
        return f"{value:+.1%}"
    if style == "prob":
        return f"{value:.3f}"
    if style == "years":
        return f"{value:.1f}"
    return f"{value:.2f}"


def note_figures(result: AuditResult | dict[str, Any]) -> dict[str, Figure]:
    """Every figure the notes quote, straight from ``result``."""
    data = result if isinstance(result, dict) else result.model_dump(mode="json")
    figures = {}
    for key, (path, style) in FIGURE_PATHS.items():
        item = _lookup(data, path)
        value = item.get("value") if isinstance(item, dict) else None
        evidence = str(item.get("evidence", "NOT_MEASURED")) if isinstance(item, dict) else ""
        if isinstance(value, bool) or not isinstance(value, int | float):
            figures[key] = Figure(key, None, "NOT_MEASURED", "—")
        else:
            figures[key] = Figure(key, value, evidence or "NOT_MEASURED", _show(value, style))
    return figures


# ---------------------------------------------------------------------------
# The notes' words
# ---------------------------------------------------------------------------

#: The notes in each language. Placeholders are filled from the result (figures,
#: dates, thresholds), from this module's constants and from the offer's.
COPY: dict[str, dict[str, Any]] = {
    "es": {
        "eyebrow": "Revisión institucional · ejemplo",
        "title": "Revisión de ejemplo: una cartera de momentum y sus 10 variantes",
        "seo_title": "Revisión institucional de ejemplo con 10 variantes",
        "lead": (
            "Lo que recibe un cliente de la revisión estándar: notas de metodología escritas "
            "sobre el informe Rigor, con cada cifra tomada del informe."
        ),
        "description": (
            "Revisión institucional de ejemplo con datos sintéticos: notas de metodología, "
            "informe Rigor y PDF de una cartera de momentum con 10 variantes y su benchmark."
        ),
        "banner": (
            "Ejemplo con datos sintéticos generados con una semilla fija: no es la cartera de "
            "ningún cliente ni una serie real de mercado."
        ),
        "notes_title": "Notas de metodología",
        "open_report": "Abrir el informe Rigor completo",
        "download_pdf": "Descargar el PDF con las notas y el informe",
        "request": "Solicitar una revisión",
        "back": "Revisión institucional",
        "s_data": "De dónde salen los datos",
        "data": (
            "Las 11 series (10 carteras y el mercado) se generan con la semilla {seed}: "
            "{months} meses, de {first} a {last}. Ningún mes es un mes real.",
            "Sus parámetros salen de estadísticos resumidos de las «10 Portfolios Formed on "
            "Momentum» (ponderadas por valor) y de los factores de mercado y de momentum de la "
            "Kenneth R. French Data Library, de {window_first} a {window_last}, descargados el "
            "{downloaded}: el alfa, la exposición al mercado y al momentum y la volatilidad "
            "residual de cada decil, y la media y la volatilidad del mercado y del momentum.",
            "No guardamos ni mostramos esos datos: cada archivo lleva el aviso «Copyright 2026 "
            "Eugene F. Fama and Kenneth R. French», se construye con la base de datos de CRSP y "
            "la página de la biblioteca no da una licencia para copiarlos ni redistribuirlos. "
            "Por eso este ejemplo usa una serie sintética con la misma estructura.",
        ),
        "source_link": "Página de la Kenneth R. French Data Library",
        "s_reviewed": "Qué se revisó",
        "reviewed": {
            "series": (
                "La serie: el decil {selected}, la cartera de las acciones con mayor retorno en "
                "los 12 meses previos sin contar el último, como la ofrecería un vendedor de "
                "señales. Retornos mensuales, en fracción."
            ),
            "variants": (
                "Las variantes: las {variants} carteras por decil, una columna cada una, "
                "declaradas como los intentos de los que salió la serie. Rigor contó {trials} "
                "columnas."
            ),
            "benchmark": "El benchmark: el mercado, con la tasa de caja sumada (retorno total).",
            "role": (
                "Quién la presenta: un vendedor que ofrece la señal a otros, así que el informe "
                "habla de lo que preguntarán sus clientes."
            ),
        },
        "s_how": "Cómo se midió",
        "how": {
            "engine": (
                "Con el motor de Rigor sin cambios, el mismo de cualquier informe del sitio: "
                "política de veredicto {policy}, semilla {engine_seed} y {bootstrap} "
                "remuestreos del bootstrap."
            ),
            "dates_ok": (
                "Las fechas de las variantes se compararon con las de la serie: son únicas, "
                "están en orden y coinciden."
            ),
            "dates_unchecked": "Las fechas de las variantes no se pudieron comparar con la serie.",
            "cash": (
                "Sin datos públicos descargados: en el alfa la tasa de caja se toma como cero, "
                "y el informe lo dice."
            ),
            "tags": (
                "Cada cifra lleva su etiqueta: Medido (calculado sobre la serie), Declarado (lo "
                "dice quien aporta los datos) o No medido (no se pudo calcular con lo aportado)."
            ),
        },
        "s_results": "Resultados y qué significa cada uno",
        "cols": ("Cifra", "Valor", "Evidencia", "Qué significa"),
        "figures": {
            "cagr": (
                "Rentabilidad anual compuesta",
                "Lo que creció la serie por año, compuesto, de {first} a {last}.",
            ),
            "volatility": ("Volatilidad anual", "Cuánto se mueve la serie en un año típico."),
            "sharpe": (
                "Sharpe anualizado",
                "Retorno medio sobre su volatilidad, anualizado, sin restar la caja.",
            ),
            "max_drawdown": ("Drawdown máximo", "La peor caída desde un máximo anterior."),
            "under_water": (
                "Meses bajo el agua",
                "El tramo más largo, en meses, sin recuperar un máximo anterior.",
            ),
            "psr": (
                "Probabilidad de que el Sharpe real sea mayor que cero (PSR)",
                "Como una sola prueba, con la longitud, la asimetría y las colas de la serie. "
                "Para superar hace falta {psr_pass} o más.",
            ),
            "dsr": (
                "Sharpe deflactado (DSR) con {trials} intentos",
                "La misma probabilidad, exigiendo superar al mejor de {trials} intentos sin "
                "habilidad. Con {dsr_pass} o más supera; entre {dsr_weak} y {dsr_pass} queda "
                "débil.",
            ),
            "luck_sharpe": (
                "Sharpe que darían {trials} intentos sin habilidad",
                "El mejor Sharpe esperable por pura suerte entre {trials} intentos con esta "
                "longitud de historial.",
            ),
            "years_needed": (
                "Años de historial para dejar atrás esa suerte",
                "Con menos años, un Sharpe como este podría venir de elegir el mejor de "
                "{trials} intentos.",
            ),
            "pbo": (
                "Probabilidad de sobreajuste (PBO, CSCV)",
                "En qué parte de las divisiones de los datos la mejor variante dentro de la "
                "muestra queda por debajo de la mediana fuera de ella. Por encima de {pbo_max} "
                "es mala señal.",
            ),
            "index_cagr": (
                "Rentabilidad anual compuesta del benchmark",
                "La misma medida para el mercado, en los mismos meses.",
            ),
            "excess": (
                "Diferencia anual frente al benchmark",
                "La rentabilidad anual compuesta de la serie menos la del benchmark.",
            ),
            "tracking_error": (
                "Error de seguimiento",
                "Cuánto se aparta la serie del benchmark en un año típico.",
            ),
            "information_ratio": (
                "Ratio de información",
                "La diferencia frente al benchmark por unidad de error de seguimiento.",
            ),
        },
        "s_dimensions": "Las seis preguntas del informe",
        "dim_cols": ("Pregunta", "Qué mide", "Resultado"),
        "questions": {
            "statistical_significance": "¿El resultado se distingue del azar como una sola prueba?",
            "multiplicity": "¿Sigue en pie después de contar los intentos de los que salió?",
            "costs": "¿Aguanta los costos de operar?",
            "out_of_sample": "¿Se sostiene en datos que no se usaron para elegirla?",
            "data_quality": "¿Los datos tienen huecos, saltos o patrones sospechosos?",
            "benchmark": "¿Aporta algo frente a tener el benchmark?",
        },
        "s_attribution": "Atribución a factores",
        "attribution_lead": (
            "El motor de Rigor reparte el retorno de la serie frente a un solo factor, el "
            "benchmark: cuánto explica la exposición al mercado y cuánto queda como alfa."
        ),
        "attribution": {
            "beta": (
                "Beta frente al benchmark",
                "Cuánto se mueve la serie por cada 1 % del mercado.",
            ),
            "exposure_share": (
                "Parte del retorno que explica la exposición al benchmark",
                "Lo que daría tener el mercado con esa beta; la caja va aparte.",
            ),
            "alpha": (
                "Alfa anual",
                "El retorno que la exposición al benchmark no explica; su rango al 95 % va de "
                "{alpha_low} a {alpha_high}.",
            ),
            "alpha_t": (
                "Estadístico t del alfa",
                "Con t entre -2 y 2, el alfa no se distingue de cero.",
            ),
        },
        "multi_factor": (
            "Atribución a varios factores (tamaño, valor, momentum y otros): en la versión "
            "ampliada. El motor todavía no la calcula, así que aquí no hay cifras."
        ),
        "s_not_measured": "Qué no se mide",
        "not_measured": {
            "costs": (
                "Costos: hacen falta la serie bruta y la neta, o las operaciones; sin ellas no se "
                "vuelven a aplicar los costos. Capacidad y costos por escenario están en la "
                "versión ampliada."
            ),
            "out_of_sample": (
                "Fuera de muestra: la serie no dice desde qué fecha su proceso no cambió; con esa "
                "fecha declarada, el informe mide ese tramo aparte."
            ),
            "construction": (
                "Cómo se construyó la señal: la revisión lee la serie aportada; no revisa el "
                "código, los datos de origen ni la ejecución, y no coteja nada con un bróker o "
                "un custodio."
            ),
            "future": "El futuro: ninguna cifra de esta revisión es una predicción.",
        },
        "s_deliverable": "Qué recibiría un cliente",
        "deliverable": (
            "Estas notas, escritas sobre su propia serie.",
            "El informe Rigor completo, con todas sus secciones.",
            "El PDF con las notas y el informe.",
            "Una llamada de {minutes} minutos y una re-ejecución a los {rerun} días.",
        ),
    },
    "en": {
        "eyebrow": "Institutional review · sample",
        "title": "Sample review: a momentum portfolio and its 10 variants",
        "seo_title": "Sample institutional review with 10 variants",
        "lead": (
            "What a client of the standard review receives: methodology notes written on top "
            "of the Rigor report, with every figure taken from the report."
        ),
        "description": (
            "Sample institutional review with synthetic data: methodology notes, Rigor report "
            "and PDF of a momentum portfolio with 10 variants and its benchmark."
        ),
        "banner": (
            "Sample built from synthetic data generated with a fixed seed: it is no client's "
            "portfolio and no real market series."
        ),
        "notes_title": "Methodology notes",
        "open_report": "Open the full Rigor report",
        "download_pdf": "Download the PDF with the notes and the report",
        "request": "Request a review",
        "back": "Institutional review",
        "s_data": "Where the data comes from",
        "data": (
            "The 11 series (10 portfolios and the market) are generated with seed {seed}: "
            "{months} months, from {first} to {last}. No month is a real month.",
            "Their parameters come from summary statistics of the “10 Portfolios Formed on "
            "Momentum” (value-weighted) and of the market and momentum factors of the Kenneth "
            "R. French Data Library, from {window_first} to {window_last}, downloaded on "
            "{downloaded}: each decile's alpha, market and momentum exposure and residual "
            "volatility, and the mean and volatility of the market and of momentum.",
            "We neither store nor show that data: each file carries the notice “Copyright 2026 "
            "Eugene F. Fama and Kenneth R. French”, is built from the CRSP database, and the "
            "library's page gives no licence to copy or redistribute it. That is why this "
            "sample uses a synthetic series with the same structure.",
        ),
        "source_link": "Kenneth R. French Data Library page",
        "s_reviewed": "What was reviewed",
        "reviewed": {
            "series": (
                "The series: decile {selected}, the portfolio of the stocks with the highest "
                "return over the previous 12 months leaving out the last one, as a signal vendor "
                "would offer it. Monthly returns, as fractions."
            ),
            "variants": (
                "The variants: the {variants} decile portfolios, one column each, declared as "
                "the attempts the series was chosen from. Rigor counted {trials} columns."
            ),
            "benchmark": "The benchmark: the market, with the cash rate added (total return).",
            "role": (
                "Who presents it: a vendor offering the signal to others, so the report speaks "
                "of what their clients will ask."
            ),
        },
        "s_how": "How it was measured",
        "how": {
            "engine": (
                "With Rigor's engine unchanged, the same as for any report on the site: verdict "
                "policy {policy}, seed {engine_seed} and {bootstrap} bootstrap resamples."
            ),
            "dates_ok": (
                "The variants' dates were compared with the series': they are unique, in order "
                "and the same."
            ),
            "dates_unchecked": "The variants' dates could not be compared with the series.",
            "cash": (
                "No public data downloaded: in the alpha the cash rate is taken as zero, and the "
                "report says so."
            ),
            "tags": (
                "Every figure carries its tag: Measured (computed on the series), Declared "
                "(stated by whoever supplies the data) or Not measured (could not be computed "
                "from what was supplied)."
            ),
        },
        "s_results": "Results and what each one means",
        "cols": ("Figure", "Value", "Evidence", "What it means"),
        "figures": {
            "cagr": (
                "Compound annual return",
                "How much the series grew per year, compounded, from {first} to {last}.",
            ),
            "volatility": ("Annual volatility", "How much the series moves in a typical year."),
            "sharpe": (
                "Annualised Sharpe",
                "Mean return over its volatility, annualised, with no cash subtracted.",
            ),
            "max_drawdown": ("Maximum drawdown", "The worst fall from an earlier peak."),
            "under_water": (
                "Months under water",
                "The longest stretch, in months, without regaining an earlier peak.",
            ),
            "psr": (
                "Probability that the true Sharpe is above zero (PSR)",
                "As a single test, with the series' length, skew and tails. Passing needs "
                "{psr_pass} or more.",
            ),
            "dsr": (
                "Deflated Sharpe (DSR) with {trials} trials",
                "The same probability, asking it to beat the best of {trials} trials with no "
                "skill. With {dsr_pass} or more it passes; between {dsr_weak} and {dsr_pass} it "
                "is weak.",
            ),
            "luck_sharpe": (
                "Sharpe {trials} trials with no skill would show",
                "The best Sharpe to expect from pure luck among {trials} trials with this "
                "length of history.",
            ),
            "years_needed": (
                "Years of history to leave that luck behind",
                "With fewer years, a Sharpe like this one could come from picking the best of "
                "{trials} trials.",
            ),
            "pbo": (
                "Probability of overfitting (PBO, CSCV)",
                "In what share of the data's splits the best variant in sample falls below the "
                "median out of sample. Above {pbo_max} is a bad sign.",
            ),
            "index_cagr": (
                "Benchmark's compound annual return",
                "The same measure for the market, over the same months.",
            ),
            "excess": (
                "Annual difference against the benchmark",
                "The series' compound annual return minus the benchmark's.",
            ),
            "tracking_error": (
                "Tracking error",
                "How far the series strays from the benchmark in a typical year.",
            ),
            "information_ratio": (
                "Information ratio",
                "The difference against the benchmark per unit of tracking error.",
            ),
        },
        "s_dimensions": "The report's six questions",
        "dim_cols": ("Question", "What it measures", "Result"),
        "questions": {
            "statistical_significance": "Does the result stand out from chance as a single test?",
            "multiplicity": "Does it still stand after counting the attempts it came from?",
            "costs": "Does it hold up against trading costs?",
            "out_of_sample": "Does it hold on data not used to choose it?",
            "data_quality": "Does the data have gaps, jumps or suspicious patterns?",
            "benchmark": "Does it add anything over holding the benchmark?",
        },
        "s_attribution": "Factor attribution",
        "attribution_lead": (
            "Rigor's engine splits the series' return against a single factor, the benchmark: "
            "how much the exposure to the market explains and how much is left as alpha."
        ),
        "attribution": {
            "beta": (
                "Beta against the benchmark",
                "How much the series moves for each 1 % of the market.",
            ),
            "exposure_share": (
                "Share of the return the exposure to the benchmark explains",
                "What holding the market with that beta would give; cash is counted apart.",
            ),
            "alpha": (
                "Annual alpha",
                "The return the exposure to the benchmark does not explain; its 95 % range runs "
                "from {alpha_low} to {alpha_high}.",
            ),
            "alpha_t": (
                "Alpha's t-statistic",
                "With t between -2 and 2, the alpha cannot be told apart from zero.",
            ),
        },
        "multi_factor": (
            "Attribution to several factors (size, value, momentum and others): in the extended "
            "review. The engine does not compute it yet, so there are no figures here."
        ),
        "s_not_measured": "What is not measured",
        "not_measured": {
            "costs": (
                "Costs: they need the gross and the net series, or the trades; without them the "
                "costs are not re-applied. Capacity and costs by scenario are in the extended "
                "review."
            ),
            "out_of_sample": (
                "Out of sample: the series does not say since which date its process has not "
                "changed; with that date declared, the report measures that stretch apart."
            ),
            "construction": (
                "How the signal was built: the review reads the series supplied; it does not "
                "review the code, the source data or the execution, and it checks nothing "
                "against a broker or a custodian."
            ),
            "future": "The future: no figure in this review is a prediction.",
        },
        "s_deliverable": "What a client would receive",
        "deliverable": (
            "These notes, written on their own series.",
            "The full Rigor report, with all its sections.",
            "The PDF with the notes and the report.",
            "A {minutes}-minute call and a re-run after {rerun} days.",
        ),
    },
    "pt": {
        "eyebrow": "Revisão institucional · exemplo",
        "title": "Revisão de exemplo: uma carteira de momentum e suas 10 variantes",
        "seo_title": "Revisão institucional de exemplo com 10 variantes",
        "lead": (
            "O que recebe um cliente da revisão padrão: notas de metodologia escritas sobre o "
            "relatório Rigor, com cada número tirado do relatório."
        ),
        "description": (
            "Revisão institucional de exemplo com dados sintéticos: notas de metodologia, "
            "relatório Rigor e PDF de uma carteira de momentum com 10 variantes e benchmark."
        ),
        "banner": (
            "Exemplo feito com dados sintéticos gerados com uma semente fixa: não é a carteira "
            "de nenhum cliente nem uma série real de mercado."
        ),
        "notes_title": "Notas de metodologia",
        "open_report": "Abrir o relatório Rigor completo",
        "download_pdf": "Baixar o PDF com as notas e o relatório",
        "request": "Solicitar uma revisão",
        "back": "Revisão institucional",
        "s_data": "De onde vêm os dados",
        "data": (
            "As 11 séries (10 carteiras e o mercado) são geradas com a semente {seed}: "
            "{months} meses, de {first} a {last}. Nenhum mês é um mês real.",
            "Seus parâmetros vêm de estatísticas resumidas das “10 Portfolios Formed on "
            "Momentum” (ponderadas por valor) e dos fatores de mercado e de momentum da Kenneth "
            "R. French Data Library, de {window_first} a {window_last}, baixados em "
            "{downloaded}: o alfa, a exposição ao mercado e ao momentum e a volatilidade "
            "residual de cada decil, e a média e a volatilidade do mercado e do momentum.",
            "Não guardamos nem mostramos esses dados: cada arquivo traz o aviso “Copyright 2026 "
            "Eugene F. Fama and Kenneth R. French”, é construído com a base de dados da CRSP e "
            "a página da biblioteca não dá uma licença para copiá-los nem redistribuí-los. Por "
            "isso este exemplo usa uma série sintética com a mesma estrutura.",
        ),
        "source_link": "Página da Kenneth R. French Data Library",
        "s_reviewed": "O que foi revisado",
        "reviewed": {
            "series": (
                "A série: o decil {selected}, a carteira das ações com maior retorno nos 12 meses "
                "anteriores sem contar o último, como um vendedor de sinais a ofereceria. "
                "Retornos mensais, em fração."
            ),
            "variants": (
                "As variantes: as {variants} carteiras por decil, uma coluna cada, declaradas "
                "como as tentativas de onde saiu a série. O Rigor contou {trials} colunas."
            ),
            "benchmark": "O benchmark: o mercado, com a taxa de caixa somada (retorno total).",
            "role": (
                "Quem a apresenta: um vendedor que oferece o sinal a outros, então o relatório "
                "fala do que os clientes dele vão perguntar."
            ),
        },
        "s_how": "Como foi medido",
        "how": {
            "engine": (
                "Com o motor do Rigor sem mudanças, o mesmo de qualquer relatório do site: "
                "política de veredito {policy}, semente {engine_seed} e {bootstrap} "
                "reamostragens do bootstrap."
            ),
            "dates_ok": (
                "As datas das variantes foram comparadas com as da série: são únicas, estão em "
                "ordem e coincidem."
            ),
            "dates_unchecked": "Não foi possível comparar as datas das variantes com a série.",
            "cash": (
                "Sem dados públicos baixados: no alfa a taxa de caixa é tomada como zero, e o "
                "relatório diz isso."
            ),
            "tags": (
                "Cada número leva a sua etiqueta: Medido (calculado sobre a série), Declarado "
                "(dito por quem fornece os dados) ou Não medido (não pôde ser calculado com o "
                "que foi fornecido)."
            ),
        },
        "s_results": "Resultados e o que significa cada um",
        "cols": ("Número", "Valor", "Evidência", "O que significa"),
        "figures": {
            "cagr": (
                "Retorno anual composto",
                "Quanto a série cresceu por ano, composto, de {first} a {last}.",
            ),
            "volatility": ("Volatilidade anual", "Quanto a série se move em um ano típico."),
            "sharpe": (
                "Sharpe anualizado",
                "Retorno médio sobre a sua volatilidade, anualizado, sem descontar o caixa.",
            ),
            "max_drawdown": ("Drawdown máximo", "A pior queda desde um pico anterior."),
            "under_water": (
                "Meses abaixo do pico",
                "O trecho mais longo, em meses, sem recuperar um pico anterior.",
            ),
            "psr": (
                "Probabilidade de o Sharpe real ser maior que zero (PSR)",
                "Como um único teste, com o tamanho, a assimetria e as caudas da série. Para "
                "passar são necessários {psr_pass} ou mais.",
            ),
            "dsr": (
                "Sharpe deflacionado (DSR) com {trials} tentativas",
                "A mesma probabilidade, exigindo superar a melhor de {trials} tentativas sem "
                "habilidade. Com {dsr_pass} ou mais passa; entre {dsr_weak} e {dsr_pass} fica "
                "fraca.",
            ),
            "luck_sharpe": (
                "Sharpe que {trials} tentativas sem habilidade dariam",
                "O melhor Sharpe esperado por pura sorte entre {trials} tentativas com este "
                "tamanho de histórico.",
            ),
            "years_needed": (
                "Anos de histórico para deixar essa sorte para trás",
                "Com menos anos, um Sharpe como este poderia vir de escolher a melhor de "
                "{trials} tentativas.",
            ),
            "pbo": (
                "Probabilidade de sobreajuste (PBO, CSCV)",
                "Em que parte das divisões dos dados a melhor variante dentro da amostra fica "
                "abaixo da mediana fora dela. Acima de {pbo_max} é mau sinal.",
            ),
            "index_cagr": (
                "Retorno anual composto do benchmark",
                "A mesma medida para o mercado, nos mesmos meses.",
            ),
            "excess": (
                "Diferença anual frente ao benchmark",
                "O retorno anual composto da série menos o do benchmark.",
            ),
            "tracking_error": (
                "Erro de acompanhamento",
                "Quanto a série se afasta do benchmark em um ano típico.",
            ),
            "information_ratio": (
                "Índice de informação",
                "A diferença frente ao benchmark por unidade de erro de acompanhamento.",
            ),
        },
        "s_dimensions": "As seis perguntas do relatório",
        "dim_cols": ("Pergunta", "O que mede", "Resultado"),
        "questions": {
            "statistical_significance": "O resultado se distingue do acaso como um único teste?",
            "multiplicity": "Continua de pé depois de contar as tentativas de onde saiu?",
            "costs": "Aguenta os custos de operar?",
            "out_of_sample": "Se sustenta em dados que não foram usados para escolhê-la?",
            "data_quality": "Os dados têm buracos, saltos ou padrões suspeitos?",
            "benchmark": "Acrescenta algo frente a ter o benchmark?",
        },
        "s_attribution": "Atribuição a fatores",
        "attribution_lead": (
            "O motor do Rigor reparte o retorno da série frente a um único fator, o benchmark: "
            "quanto a exposição ao mercado explica e quanto fica como alfa."
        ),
        "attribution": {
            "beta": ("Beta frente ao benchmark", "Quanto a série se move a cada 1 % do mercado."),
            "exposure_share": (
                "Parte do retorno que a exposição ao benchmark explica",
                "O que daria ter o mercado com esse beta; o caixa fica à parte.",
            ),
            "alpha": (
                "Alfa anual",
                "O retorno que a exposição ao benchmark não explica; o seu intervalo de 95 % vai "
                "de {alpha_low} a {alpha_high}.",
            ),
            "alpha_t": (
                "Estatística t do alfa",
                "Com t entre -2 e 2, o alfa não se distingue de zero.",
            ),
        },
        "multi_factor": (
            "Atribuição a vários fatores (tamanho, valor, momentum e outros): na revisão "
            "ampliada. O motor ainda não a calcula, então aqui não há números."
        ),
        "s_not_measured": "O que não é medido",
        "not_measured": {
            "costs": (
                "Custos: são necessárias a série bruta e a líquida, ou as operações; sem elas os "
                "custos não são reaplicados. Capacidade e custos por cenário estão na revisão "
                "ampliada."
            ),
            "out_of_sample": (
                "Fora da amostra: a série não diz desde que data o seu processo não mudou; com "
                "essa data declarada, o relatório mede esse trecho à parte."
            ),
            "construction": (
                "Como o sinal foi construído: a revisão lê a série fornecida; não revisa o "
                "código, os dados de origem nem a execução, e não confronta nada com uma "
                "corretora ou um custodiante."
            ),
            "future": "O futuro: nenhum número desta revisão é uma previsão.",
        },
        "s_deliverable": "O que um cliente receberia",
        "deliverable": (
            "Estas notas, escritas sobre a própria série.",
            "O relatório Rigor completo, com todas as suas seções.",
            "O PDF com as notas e o relatório.",
            "Uma chamada de {minutes} minutos e uma nova execução após {rerun} dias.",
        ),
    },
}

#: The figures of the results table and of the attribution table, in order.
RESULT_KEYS = (
    "cagr",
    "volatility",
    "sharpe",
    "max_drawdown",
    "under_water",
    "psr",
    "dsr",
    "luck_sharpe",
    "years_needed",
    "pbo",
    "index_cagr",
    "excess",
    "tracking_error",
    "information_ratio",
)
ATTRIBUTION_KEYS = ("beta", "exposure_share", "alpha", "alpha_t")


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _locale(locale: str) -> str:
    return locale if locale in COPY else "es"


def _dimension_words(locale: str) -> tuple[dict[str, str], dict[str, str]]:
    """The report's own dimension titles and status words in ``locale``."""
    if locale == "pt":
        from quant_trade.audit.portuguese import DIMENSION_TITLES_PT, STATUS_TEXT_PT

        return DIMENSION_TITLES_PT, STATUS_TEXT_PT
    return DIMENSION_TITLES[locale], STATUS_TEXT[locale]


def _badge(tag: str, locale: str) -> str:
    return f"<span class='badge {_e(tag)}'>{_e(evidence_label(tag, locale))}</span>"


def _values(data: dict[str, Any], figures: dict[str, Figure]) -> dict[str, Any]:
    """Every placeholder the notes fill: figures, dates, thresholds and constants."""
    thresholds = data.get("verdict", {}).get("thresholds", {})
    engine = data.get("engine", {})
    first = str(data.get("inputs", {}).get("first_timestamp") or "")[:7]
    last = str(data.get("inputs", {}).get("last_timestamp") or "")[:7]
    return {
        **{key: figure.shown for key, figure in figures.items()},
        "first": first,
        "last": last,
        "seed": SEED,
        "selected": SELECTED,
        "variants": VARIANTS,
        "window_first": SOURCE_WINDOW[0],
        "window_last": SOURCE_WINDOW[1],
        "downloaded": SOURCE_DOWNLOADED,
        "policy": engine.get("verdict_policy_version", ""),
        "engine_seed": engine.get("seed", ""),
        "bootstrap": engine.get("bootstrap_samples", ""),
        "psr_pass": thresholds.get("psr_pass", ""),
        "dsr_pass": thresholds.get("dsr_pass", ""),
        "dsr_weak": thresholds.get("dsr_weak", ""),
        "pbo_max": thresholds.get("pbo_max", ""),
        "minutes": institutional.CALL_MINUTES,
        "rerun": institutional.RERUN_DAYS,
    }


def _figure_rows(
    keys: tuple[str, ...],
    labels: dict[str, tuple[str, str]],
    figures: dict[str, Figure],
    values: dict[str, Any],
    locale: str,
) -> str:
    rows = []
    for key in keys:
        label, meaning = labels[key]
        figure = figures[key]
        rows.append(
            f"<tr><td>{_e(label.format(**values))}</td><td class='val'>{_e(figure.shown)}</td>"
            f"<td>{_badge(figure.evidence, locale)}</td>"
            f"<td>{_e(meaning.format(**values))}</td></tr>"
        )
    return "".join(rows)


def _table(cols: tuple[str, ...], rows: str, *, evidence: bool = True) -> str:
    """A table of figures; ``evidence`` is the report's layout with an evidence column
    (figure, value, tag, meaning), which stacks into cards on a phone."""
    head = "".join(f"<th>{_e(col)}</th>" for col in cols)
    kind = "metrics ev" if evidence else "metrics"
    return f"<div class='tscroll'><table class='{kind}'><thead><tr>{head}</tr></thead>" + (
        f"<tbody>{rows}</tbody></table></div>"
    )


def _tagged(items: list[tuple[str, str]], locale: str) -> str:
    """A list whose every line starts with its evidence tag."""
    return (
        "<ul class='mtags'>"
        + "".join(f"<li>{_badge(tag, locale)}<span>{_e(text)}</span></li>" for tag, text in items)
        + "</ul>"
    )


def _plain(items: tuple[str, ...] | list[str]) -> str:
    return "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in items) + "</ul>"


def notes_sections(result: AuditResult, locale: str) -> list[tuple[str, str]]:
    """The methodology notes as (heading, HTML) sections, every figure from ``result``."""
    locale = _locale(locale)
    words = COPY[locale]
    data = result.model_dump(mode="json")
    figures = note_figures(data)
    values = _values(data, figures)
    dims = {str(item["name"]): str(item["status"]) for item in data["verdict"]["dimensions"]}
    titles, statuses = _dimension_words(locale)

    source = "".join(f"<p>{_e(line.format(**values))}</p>" for line in words["data"]) + (
        f"<p><a href='{_e(SOURCE_URL)}' rel='noopener'>{_e(words['source_link'])}</a></p>"
    )
    reviewed = words["reviewed"]
    trials = figures["trials"]
    reviewed_html = _tagged(
        [
            ("DECLARED", reviewed["series"].format(**values)),
            (trials.evidence, reviewed["variants"].format(**values)),
            ("DECLARED", reviewed["benchmark"]),
            ("DECLARED", reviewed["role"]),
        ],
        locale,
    )
    how = words["how"]
    validation = (data.get("cscv") or {}).get("source_validation") or {}
    dates_ok = validation.get("status") == "MEASURED"
    how_html = _plain(
        [
            how["engine"].format(**values),
            how["dates_ok" if dates_ok else "dates_unchecked"],
            how["cash"],
            how["tags"],
        ]
    )
    overall = str(data["verdict"]["overall"])
    results_html = (
        f"<p><b>{_e(class_text(overall, locale, kind='fund'))}</b></p>"
        + _table(
            words["cols"],
            _figure_rows(RESULT_KEYS, words["figures"], figures, values, locale),
        )
        + f"<h3>{_e(words['s_dimensions'])}</h3>"
        + _table(
            words["dim_cols"],
            "".join(
                f"<tr><td>{_e(titles[name])}</td><td>{_e(words['questions'][name])}</td>"
                f"<td class='val'>{_e(statuses.get(dims[name], dims[name]))}</td></tr>"
                for name in DIMENSION_ORDER
                if name in dims
            ),
            evidence=False,
        )
    )
    attribution_html = (
        f"<p>{_e(words['attribution_lead'])}</p>"
        + _table(
            words["cols"],
            _figure_rows(ATTRIBUTION_KEYS, words["attribution"], figures, values, locale),
        )
        + f"<p>{_badge('NOT_MEASURED', locale)} {_e(words['multi_factor'])}</p>"
    )
    missing = words["not_measured"]
    not_measured_html = _tagged(
        [
            (
                "NOT_MEASURED" if dims.get("costs") == "NOT_MEASURED" else "MEASURED",
                missing["costs"],
            ),
            (
                "NOT_MEASURED" if dims.get("out_of_sample") == "NOT_MEASURED" else "MEASURED",
                missing["out_of_sample"],
            ),
            ("NOT_MEASURED", missing["construction"]),
            ("NOT_MEASURED", missing["future"]),
        ],
        locale,
    )
    deliverable = _plain([line.format(**values) for line in words["deliverable"]])
    return [
        (words["s_data"], source),
        (words["s_reviewed"], reviewed_html),
        (words["s_how"], how_html),
        (words["s_results"], results_html),
        (words["s_attribution"], attribution_html),
        (words["s_not_measured"], not_measured_html),
        (words["s_deliverable"], deliverable),
    ]


def _guarded(markup: str) -> str:
    """The notes' own words pass the profit-claim guard, or nothing is shown."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", markup))
    assert_report_clean(text)
    return markup


# ---------------------------------------------------------------------------
# The pages: the public notes page, and the report with the notes on top
# ---------------------------------------------------------------------------


def sample_page(
    result: AuditResult, *, locale: str = "es", base_url: str = "", pdf_ok: bool = False
) -> str:
    """The public page: the methodology notes, with links to the full report, its
    PDF (when this process can lay one out) and the request form."""
    from quant_trade.audit.pages import (
        _doc,
        _home,
        _language_crumbs,
        _page,
        _page_hero,
        _public_meta,
    )
    from quant_trade.audit.seo import BRAND
    from quant_trade.audit.theme import icon

    locale = _locale(locale)
    words = COPY[locale]
    # The tab and the search result: short enough for a results page.
    title = f"{words['seo_title']} · {BRAND}"
    meta = _public_meta(
        title, words["description"], locale, institutional.SAMPLE_PATHS[locale], base_url
    )
    crumbs = (
        f"<a href='{_home(locale)}'>{_e(institutional.COPY[locale]['back'])}</a><span>/</span>"
        f"<a href='{institutional.REVIEW_PATHS[locale]}'>{_e(words['back'])}</a>"
        + _language_crumbs(institutional.SAMPLE_PATHS, locale)
    )
    buttons = (
        f"<a class='btn btn-dark' href='{institutional.SAMPLE_REPORT_PATHS[locale]}'>"
        f"{_e(words['open_report'])}<span class='go'>{icon('arrow')}</span></a>"
        + (
            f" <a class='btn btn-ghost' href='{institutional.SAMPLE_PDF_PATHS[locale]}' download>"
            f"{_e(words['download_pdf'])}</a>"
            if pdf_ok
            else ""
        )
    )
    request = (
        f"<a class='btn btn-dark btn-sm toc-cta' href='{institutional.REVIEW_PATHS[locale]}"
        f"#{institutional.FORM_ANCHOR}'>{_e(words['request'])}"
        f"<span class='go'>{icon('arrow')}</span></a>"
    )
    sections = notes_sections(result, locale)
    content = _guarded(
        f"<div class='notice' role='note'>{_e(words['banner'])}</div>"
        f"<p>{_e(institutional.offer_text(locale, 'not_audit'))}</p>"
        f"<p class='actions'>{buttons}</p>" + _doc(sections, locale, aside=request)
    )
    body = (
        _page_hero(words["eyebrow"], words["title"], words["lead"], crumbs)
        + "<div class='paper page-main'><div class='wrap'>"
        + content
        + "</div></div>"
    )
    return _page(
        title,
        locale,
        body,
        meta_html=meta,
        alternates=institutional.SAMPLE_PATHS,
        solid_nav=True,
    )


#: Where the notes go in the report: right inside its main column.
_REPORT_MAIN = re.compile(r"<main\b[^>]*>(?:\s*<div class='wrap wrap-mid'>)?")


def report_with_notes(
    result: AuditResult, *, locale: str = "es", pdf_url: str | None = None
) -> str:
    """The full Rigor report with the methodology notes as its first sections: the
    page behind "open the report", and, without ``pdf_url``, the PDF's source.
    Not indexed: the notes page is the public one."""
    from quant_trade.audit.report import render

    locale = _locale(locale)
    words = COPY[locale]
    page, _ = render(
        result,
        watermark=False,
        free_mode=True,
        notice=words["banner"],
        legal_links=True,
        locale=locale,
        pdf_url=pdf_url,
        tools_link=True,
    )
    page = page.replace(" · sample</title>", f" · {REPORT_NAMES[locale]}</title>", 1)
    notes = _guarded(
        f"<section class='rsec' id='r-notes'><h2>{_e(words['notes_title'])}</h2>"
        f"<p>{_e(words['lead'])} {_e(institutional.offer_text(locale, 'not_audit'))}</p>"
        f"<p><a href='{institutional.SAMPLE_PATHS[locale]}'>{_e(words['title'])}</a></p></section>"
        + "".join(
            f"<section class='rsec' id='r-notes-{number}'><h2>{_e(heading)}</h2>{body}</section>"
            for number, (heading, body) in enumerate(notes_sections(result, locale), start=1)
        )
    )
    anchor = _REPORT_MAIN.search(page)
    if anchor is None:
        raise ValueError("the report has no main column to put the notes in")
    return page[: anchor.end()] + notes + page[anchor.end() :]


__all__ = [
    "AUDIT_ID",
    "COPY",
    "FIGURE_PATHS",
    "REPORT_NAMES",
    "SEED",
    "Figure",
    "note_figures",
    "notes_sections",
    "report_with_notes",
    "sample_files",
    "sample_page",
    "sample_result",
    "synthetic_panel",
]
