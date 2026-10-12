"""Institutional intake: declared context only, with no files or public client prose."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from quant_trade.audit import accounts, inbox
from quant_trade.audit.guard import find_claims, scan_client_text

REVIEW_PATHS = {
    "es": "/revision-institucional",
    "en": "/en/institutional-review",
    "pt": "/pt/revisao-institucional",
}
#: One shared, fictional return-table download in the site's accepted format.
#: Variants use a separate CSV: extra columns here would not ingest as variants.
TEMPLATE_PATH = "/revision-institucional/plantilla.csv"
TEMPLATE_FILENAME = "institutional-fictional-template.csv"
TEMPLATE_CSV = (
    b"date,gross_return,net_return,benchmark\n"
    b"2000-01-31,0.010,0.009,0.005\n"
    b"2000-02-29,-0.020,-0.021,-0.010\n"
    b"2000-03-31,0.000,-0.001,0.000\n"
    b"2000-04-30,0.020,0.019,0.010\n"
)
#: The sample institutional review (``institutional_sample``): its public page with
#: the methodology notes, the full report with the notes on top, and its PDF.
SAMPLE_PATHS = {
    "es": "/revision-institucional/ejemplo",
    "en": "/en/institutional-review/sample",
    "pt": "/pt/revisao-institucional/exemplo",
}
SAMPLE_REPORT_PATHS = {
    "es": "/revision-institucional/ejemplo/informe",
    "en": "/en/institutional-review/sample/report",
    "pt": "/pt/revisao-institucional/exemplo/relatorio",
}
SAMPLE_PDF_PATHS = {locale: f"{path}.pdf" for locale, path in SAMPLE_PATHS.items()}
MAX_REQUESTS_PER_HOUR = 5
BODY_LIMIT = 16_384

#: The institutional review's prices, in whole US dollars. This is the only place
#: they live: the page, its structured data and the tests read them from here, so
#: changing the offer means changing these two numbers. The standard review starts
#: at the first; the extended one goes up to the second. Neither depends on the
#: result of the review.
STANDARD_PRICE_USD = 2_500
EXTENDED_PRICE_USD = 4_000
#: The offer's other figures, spelled once: business days from complete data to the
#: standard delivery, the call's minutes, the days after a delivery when the re-run
#: happens and when the whole audit is deleted (``audit delete``: files, report,
#: private link and the issued files ``/comprobar`` reads), and the share paid on
#: acceptance (the rest is paid on delivery).
DELIVERY_BUSINESS_DAYS = 10
CALL_MINUTES = 60
RERUN_DAYS = 30
DELETE_DAYS = 30
DEPOSIT_PERCENT = 50
#: The day the offer's copy last changed (the sitemap's ``lastmod`` of its pages).
OFFER_UPDATED = "2026-10-11"
FORM_FIELDS = frozenset(
    {
        "name",
        "organization",
        "email",
        "strategy_type",
        "frequency",
        "history_years",
        "has_benchmark",
        "variants",
        "description",
        "website",
        "ref",
    }
)

COPY: dict[str, dict[str, Any]] = {
    "es": {
        "title": "Solicitar una revisión institucional",
        "lead": "Cuéntanos sobre tu señal, cartera modelo, fondo o EA para preparar la revisión.",
        "name": "Nombre",
        "organization": "Organización",
        "email": "Correo",
        "strategy_type": "Tipo de estrategia",
        "frequency": "Frecuencia de la serie",
        "history_years": "Años de historial",
        "has_benchmark": "¿Tienes benchmark?",
        "variants": "Número aproximado de variantes probadas",
        "description": "Contexto adicional (hasta 1.000 caracteres)",
        "types": {
            "signal": "Señal",
            "model_portfolio": "Cartera modelo",
            "fund": "Fondo",
            "ea": "EA",
        },
        "frequencies": {"daily": "Diaria", "weekly": "Semanal", "monthly": "Mensual"},
        "benchmark": {"yes": "Sí", "no": "No"},
        "choose": "Selecciona una opción",
        "submit": "Enviar solicitud",
        "note": "Estos datos llevan la etiqueta «DECLARED»: los aporta quien solicita la "
        "revisión. Aquí no se adjuntan archivos ni hace falta escribir datos confidenciales: la "
        "serie y los detalles van después del NDA, por el flujo habitual.",
        "privacy": "Privacidad",
        "received": "Solicitud recibida",
        "next": (
            "Te escribimos en 1 día hábil. Firmamos el NDA mutuo antes de recibir tus archivos."
        ),
        "back": "Volver al inicio",
        "invalid": "Revisa los campos. Usa texto sin HTML y un correo válido.",
        "limited": "Se alcanzó el límite de solicitudes. Inténtalo dentro de una hora.",
        "too_large": "La solicitud es demasiado grande. Reduce el texto e inténtalo de nuevo.",
        "unavailable": "No pudimos guardar la solicitud. Inténtalo de nuevo más tarde.",
    },
    "en": {
        "title": "Request an institutional review",
        "lead": "Tell us about your signal, model portfolio, fund or EA to prepare the review.",
        "name": "Name",
        "organization": "Organization",
        "email": "Email",
        "strategy_type": "Strategy type",
        "frequency": "Series frequency",
        "history_years": "Years of history",
        "has_benchmark": "Do you have a benchmark?",
        "variants": "Approximate number of variants tested",
        "description": "Additional context (up to 1,000 characters)",
        "types": {
            "signal": "Signal",
            "model_portfolio": "Model portfolio",
            "fund": "Fund",
            "ea": "EA",
        },
        "frequencies": {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"},
        "benchmark": {"yes": "Yes", "no": "No"},
        "choose": "Choose an option",
        "submit": "Send request",
        "note": "These details carry the DECLARED label: they are supplied by the person "
        "requesting the review. This form has no attachments and needs no confidential data: "
        "the series and the details come after the NDA, through the usual flow.",
        "privacy": "Privacy",
        "received": "Request received",
        "next": (
            "We will write within 1 business day. "
            "We sign the mutual NDA before receiving your files."
        ),
        "back": "Back to home",
        "invalid": "Check the fields. Use text without HTML and a valid email address.",
        "limited": "The request limit has been reached. Try again in one hour.",
        "too_large": "The request is too large. Shorten the text and try again.",
        "unavailable": "We could not save the request. Please try again later.",
    },
    "pt": {
        "title": "Solicitar uma revisão institucional",
        "lead": "Conte sobre seu sinal, carteira modelo, fundo ou EA para preparar a revisão.",
        "name": "Nome",
        "organization": "Organização",
        "email": "E-mail",
        "strategy_type": "Tipo de estratégia",
        "frequency": "Frequência da série",
        "history_years": "Anos de histórico",
        "has_benchmark": "Você tem benchmark?",
        "variants": "Número aproximado de variantes testadas",
        "description": "Contexto adicional (até 1.000 caracteres)",
        "types": {
            "signal": "Sinal",
            "model_portfolio": "Carteira modelo",
            "fund": "Fundo",
            "ea": "EA",
        },
        "frequencies": {"daily": "Diária", "weekly": "Semanal", "monthly": "Mensal"},
        "benchmark": {"yes": "Sim", "no": "Não"},
        "choose": "Selecione uma opção",
        "submit": "Enviar solicitação",
        "note": "Estes dados levam a etiqueta «DECLARED»: são fornecidos por quem solicita a "
        "revisão. Este formulário não recebe arquivos nem precisa de dados confidenciais: a "
        "série e os detalhes vêm depois do NDA, pelo fluxo habitual.",
        "privacy": "Privacidade",
        "received": "Solicitação recebida",
        "next": "Escrevemos em 1 dia útil. Assinamos o NDA mútuo antes de receber seus arquivos.",
        "back": "Voltar ao início",
        "invalid": "Revise os campos. Use texto sem HTML e um e-mail válido.",
        "limited": "O limite de solicitações foi atingido. Tente novamente em uma hora.",
        "too_large": "A solicitação é muito grande. Reduza o texto e tente novamente.",
        "unavailable": "Não foi possível salvar a solicitação. Tente novamente mais tarde.",
    },
}


@dataclass(frozen=True)
class Intake:
    name: str
    organization: str
    email: str
    strategy_type: str
    frequency: str
    history_years: str
    has_benchmark: bool
    variants: int
    description: str
    claim_findings: list[dict[str, Any]]


def parse_intake(values: Mapping[str, str]) -> Intake:
    """Reject markup and invalid declarations; keep scanned client prose verbatim."""
    limits = {"name": 100, "organization": 160, "email": 254, "description": 1000}
    for field, value in values.items():
        if field not in FORM_FIELDS or len(value) > limits.get(field, 32):
            raise ValueError("invalid intake")
        if any(char in html.unescape(value) for char in "<>"):
            raise ValueError("invalid intake")
        allowed_controls = "\r\n\t" if field == "description" else ""
        if any(not char.isprintable() and char not in allowed_controls for char in value):
            raise ValueError("invalid intake")
    name = values.get("name", "").strip()
    organization = values.get("organization", "").strip()
    email = accounts.normalise_email(values.get("email", ""))
    if not name or not organization or find_claims(f"{name}\n{organization}\n{email}"):
        raise ValueError("invalid intake")
    if not accounts.simple_email(email) or inbox.is_disposable(email) or inbox.is_reserved(email):
        raise ValueError("invalid intake")
    strategy_type = values.get("strategy_type", "")
    frequency = values.get("frequency", "")
    if strategy_type not in COPY["en"]["types"] or frequency not in COPY["en"]["frequencies"]:
        raise ValueError("invalid intake")
    years = values.get("history_years", "")
    variants = values.get("variants", "")
    if not re.fullmatch(r"\d{1,3}(?:\.\d{1,2})?", years) or not 0 < float(years) <= 100:
        raise ValueError("invalid intake")
    if not re.fullmatch(r"\d{1,9}", variants):
        raise ValueError("invalid intake")
    benchmark = values.get("has_benchmark", "")
    if benchmark not in {"yes", "no"}:
        raise ValueError("invalid intake")
    description = values.get("description", "")
    return Intake(
        name,
        organization,
        email,
        strategy_type,
        frequency,
        years,
        benchmark == "yes",
        int(variants),
        description,
        scan_client_text(description),
    )


def form_html(locale: str, *, ref: str = "") -> str:
    words = COPY[locale]
    controls = {}
    for name, kind, extra in (
        ("name", "text", "maxlength='100' autocomplete='name'"),
        ("organization", "text", "maxlength='160' autocomplete='organization'"),
        ("email", "email", "maxlength='254' autocomplete='email'"),
        ("history_years", "number", "min='0.01' max='100' step='0.01'"),
        ("variants", "number", "min='0' max='999999999' step='1'"),
    ):
        controls[name] = f"<input id='intake-{name}' type='{kind}' name='{name}' {extra} required>"
    for name, choices in (
        ("strategy_type", "types"),
        ("frequency", "frequencies"),
        ("has_benchmark", "benchmark"),
    ):
        options = f"<option value=''>{html.escape(words['choose'])}</option>" + "".join(
            f"<option value='{value}'>{html.escape(label)}</option>"
            for value, label in words[choices].items()
        )
        controls[name] = f"<select id='intake-{name}' name='{name}' required>{options}</select>"
    controls["description"] = (
        "<textarea id='intake-description' name='description' maxlength='1000' rows='5'></textarea>"
    )
    fields = "".join(
        f"<div class='field'><label for='intake-{name}'>{html.escape(words[name])}</label>"
        f"{controls[name]}</div>"
        for name in (
            "name",
            "organization",
            "email",
            "strategy_type",
            "frequency",
            "history_years",
            "has_benchmark",
            "variants",
            "description",
        )
    )
    return (
        f"<form method='post' action='{REVIEW_PATHS[locale]}'>"
        f"<input type='hidden' name='ref' value='{html.escape(ref, quote=True)}'>"
        "<div hidden aria-hidden='true'><label>Website"
        "<input name='website' tabindex='-1' autocomplete='off'></label></div>"
        + fields
        + f"<button class='btn btn-dark' type='submit'>{html.escape(words['submit'])}</button>"
        "</form>"
    )


# ---------------------------------------------------------------------------
# The offer: scope, deliverables, timeline and terms of the institutional review
# ---------------------------------------------------------------------------

#: The offer's words. ``{standard}``, ``{extended}``, ``{days}``, ``{minutes}``,
#: ``{rerun}``, ``{delete}``, ``{deposit}`` and ``{rest}`` are filled from the
#: constants at the top of this module when a page is built, never typed here.
#: The review reads the series a client supplies; the page says it is not an
#: accounting or regulatory audit.
OFFER_COPY: dict[str, dict[str, Any]] = {
    "es": {
        "eyebrow": "Revisión institucional",
        "title": "Revisión independiente de una cartera o una señal",
        "seo_title": "Revisión institucional independiente desde {standard}",
        "summary": (
            "Revisión estadística independiente de una cartera o una señal: alcance, "
            "entregables, entrega en {days} días hábiles y condiciones. Desde {standard}."
        ),
        "lead": (
            "Para vendedores de señales y de datos y para gestores emergentes que tienen que "
            "presentar su serie a un inversor, un comité o una plataforma: el motor de Rigor "
            "sobre tu serie, con notas escritas para quien decide."
        ),
        "not_audit": (
            "Es una revisión independiente: no es una auditoría contable ni regulatoria, ni "
            "asesoría de inversión."
        ),
        "plans_title": "Dos alcances",
        "standard": "Revisión estándar",
        "standard_price": "Desde {standard}",
        "standard_items": (
            "Una cartera o serie de retornos, un benchmark y las variantes que declares.",
            "Informe escrito con notas de metodología, el informe Rigor completo y su PDF.",
            "Una llamada de {minutes} minutos para repasar los resultados.",
            "Una re-ejecución a los {rerun} días, con la serie actualizada.",
            "Entrega en {days} días hábiles desde que llegan los datos completos.",
        ),
        "extended": "Revisión ampliada",
        "extended_price": "Hasta {extended}",
        "extended_lead": "Todo lo de la revisión estándar, y además:",
        "extended_items": (
            "Varias carteras o universos.",
            "Atribución a varios factores, calculada aparte del informe Rigor.",
            "Capacidad y costos por escenario, calculados aparte del informe Rigor.",
            "Una segunda re-ejecución.",
        ),
        "request": "Solicitar una revisión",
        "deliverables_title": "Qué recibes",
        "deliverables": (
            "Notas de metodología: qué se midió, cómo, qué no se mide y qué significa cada "
            "resultado. Cada cifra sale del informe Rigor, salvo las que la revisión ampliada "
            "calcula aparte (varios factores, capacidad), con la metodología que se acuerda en "
            "la cotización.",
            "El informe Rigor completo: cada valor dice si se midió en tu serie, si lo "
            "declaraste o si no se pudo medir.",
            "El PDF del informe, para compartirlo con quien tú decidas: se puede comprobar en "
            "/comprobar mientras la auditoría no se borre.",
            "La llamada y las re-ejecuciones de tu alcance.",
        ),
        "send_title": "Qué mandar",
        "send_items": (
            "Retornos de la cartera modelo, mensuales o diarios, en un CSV con una columna de "
            "fecha y una de retorno (date,return), o una serie de NAV (date,nav). Si tienes "
            "bruto y neto de costos, van como retornos en dos columnas del mismo CSV "
            "(gross_return y net_return), como en la plantilla: una serie de NAV lleva una sola "
            "columna. Si no, bruto más el supuesto de costos.",
            "Índice de referencia: su serie en el mismo formato (en un CSV aparte o como columna "
            "benchmark del mismo CSV), o solo su nombre si es un índice estándar.",
            "Cuántas variantes probaste antes de fijar las reglas. Si tienes sus series, "
            "envíalas en un CSV aparte con una columna de fecha y una por variante "
            "(date,variant_1,variant_2), con las mismas fechas que la cartera: al menos 2 "
            "variantes y 16 fechas, hasta 500 variantes y 5 MB, sin celdas vacías. Si no, basta "
            "el número y el informe lo marca como declarado.",
            "Periodo reservado (fuera de muestra): la fecha desde la que las reglas quedaron "
            "fijas y si la serie anterior se usó para elegirlas.",
            "Supuestos de costos: rotación de la cartera y costo por rebalanceo expresado en "
            "puntos básicos (pb).",
        ),
        "template_link": "Descargar plantilla CSV con datos ficticios",
        "template_note": (
            "La plantilla usa date,gross_return,net_return,benchmark: bruto, neto e índice "
            "de referencia; las variantes van en el CSV aparte. Las cuatro filas son "
            "totalmente ficticias y solo muestran el formato: sustitúyelas por tu historial "
            "completo. Usa fechas AAAA-MM-DD y retornos en fracciones (0.01 = 1 %), con punto "
            "decimal. Quita las columnas net_return o benchmark si no tienes esas series."
        ),
        "nda": "Firmamos un NDA mutuo antes de que nos mandes nada; puedes mandar el tuyo.",
        "publication_note": (
            "Ningún informe, tampoco el primero, se publica ni se menciona a la empresa sin "
            "permiso escrito."
        ),
        "scope_limit": (
            "La revisión no concilia las cifras con el bróker ni con el administrador, no es "
            "diligencia operativa y no es una presentación GIPS."
        ),
        "timeline_title": "Plazos",
        "timeline": (
            "Respondemos tu solicitud en 1 día hábil.",
            "Revisión estándar: entrega en {days} días hábiles desde que llegan los datos "
            "completos.",
            "Revisión ampliada: el plazo se acuerda en la cotización, según cuántas carteras "
            "incluya.",
            "Re-ejecución: a los {rerun} días de la entrega, con la serie actualizada que nos "
            "envíes.",
        ),
        "terms_title": "Condiciones",
        "terms": (
            "El precio no depende del resultado.",
            "La revisión se rige por la cotización escrita que aceptas: alcance, precio, pagos, "
            "confidencialidad y borrado. Los términos del sitio describen el informe automático.",
            "Nada se publica sin tu permiso escrito.",
            "A los {delete} días de cada entrega, o antes si lo pides, borramos la auditoría "
            "completa: los archivos, el informe, su enlace privado y el registro de sus "
            "archivos. Desde entonces /comprobar ya no reconoce su PDF, así que guarda tu "
            "copia. Ese plazo de borrado queda escrito en la cotización.",
            "La serie se sube con el código de acceso que te enviamos al aceptar la cotización: "
            "así la auditoría queda como pagada y la limpieza de las auditorías no pagadas no la "
            "borra antes de ese plazo.",
            "Pago: {deposit} % al aceptar la cotización y {rest} % al entregar.",
            "Es una lectura estadística independiente de la serie que aportas, no una "
            "verificación de cómo se construyó la señal.",
        ),
        "privacy_note": "Qué guarda el sitio de cada informe lo explica la",
        "privacy_link": "política de privacidad",
        "sample_title": "Una revisión de ejemplo",
        "sample_text": (
            "Una cartera de momentum y sus 10 variantes, con datos sintéticos: las notas de "
            "metodología, el informe Rigor y el PDF, como los recibiría un cliente."
        ),
        "sample_link": "Ver la revisión de ejemplo",
        "form_lead": "Cuéntanos sobre tu serie y te enviamos el alcance y la cotización.",
    },
    "en": {
        "eyebrow": "Institutional review",
        "title": "An independent review of a portfolio or a signal",
        "seo_title": "Independent institutional review from {standard}",
        "summary": (
            "Independent statistical review of a portfolio or a signal: scope, deliverables, "
            "delivery in {days} business days and terms. From {standard}."
        ),
        "lead": (
            "For signal and data vendors and emerging managers who have to present their "
            "series to an investor, a committee or a platform: Rigor's engine on your series, "
            "with written notes for whoever decides."
        ),
        "not_audit": (
            "It is an independent review: not an accounting or regulatory audit, and not "
            "investment advice."
        ),
        "plans_title": "Two scopes",
        "standard": "Standard review",
        "standard_price": "From {standard}",
        "standard_items": (
            "One portfolio or return series, one benchmark and the variants you declare.",
            "A written report with methodology notes, the full Rigor report and its PDF.",
            "A {minutes}-minute call to go through the results.",
            "A re-run after {rerun} days, with the updated series.",
            "Delivery in {days} business days from the arrival of the complete data.",
        ),
        "extended": "Extended review",
        "extended_price": "Up to {extended}",
        "extended_lead": "Everything in the standard review, plus:",
        "extended_items": (
            "Several portfolios or universes.",
            "Attribution to several factors, computed apart from the Rigor report.",
            "Capacity and costs by scenario, computed apart from the Rigor report.",
            "A second re-run.",
        ),
        "request": "Request a review",
        "deliverables_title": "What you receive",
        "deliverables": (
            "Methodology notes: what was measured, how, what is not measured and what each "
            "result means. Every figure comes from the Rigor report, except those the extended "
            "review computes apart (several factors, capacity), with the methodology agreed in "
            "the quote.",
            "The full Rigor report: each value says whether it was measured on your series, "
            "declared by you or could not be measured.",
            "The report's PDF, to share with whoever you choose: it can be checked on /check "
            "until the audit is deleted.",
            "The call and the re-runs of your scope.",
        ),
        "send_title": "What to send",
        "send_items": (
            "Monthly or daily model portfolio returns in a CSV with a date column and a return "
            "column (date,return), or a NAV series (date,nav). If you have returns gross and "
            "net of costs, send them as two columns of the same CSV (gross_return and "
            "net_return), as in the template: a NAV series holds a single column. Otherwise, "
            "gross returns plus the cost assumption.",
            "Benchmark: its series in the same format (in a separate CSV or as a benchmark "
            "column of the same CSV), or just its name if it is a standard index.",
            "How many variants you tested before freezing the rules. If you have their series, "
            "send them in a separate CSV with a date column and one column per variant "
            "(date,variant_1,variant_2), using the same dates as the portfolio: at least 2 "
            "variants and 16 dates, up to 500 variants and 5 MB, with no empty cells. "
            "Otherwise, the count is enough and the report marks it as declared.",
            "Out-of-sample (holdout) period: the date from which the rules have stayed fixed, "
            "and whether the earlier data was used to choose them.",
            "Cost assumptions: portfolio turnover and cost per rebalance expressed in "
            "basis points (bps).",
        ),
        "template_link": "Download CSV template with fictional data",
        "template_note": (
            "The template uses date,gross_return,net_return,benchmark: gross, net and "
            "benchmark returns; variants go in the separate CSV. All four rows are entirely "
            "fictional and only show the format: replace them with your complete history. "
            "Use YYYY-MM-DD dates and fractional returns (0.01 = 1 %), with a decimal point. "
            "Remove the net_return or benchmark columns if you do not have those series."
        ),
        "nda": "We sign a mutual NDA before you send anything; you are welcome to send your own.",
        "publication_note": (
            "Without your written permission, no report is published, the first one included, "
            "and the company is not named."
        ),
        "scope_limit": (
            "The review does not reconcile the figures with your broker or fund administrator, "
            "is not operational due diligence and is not a GIPS presentation."
        ),
        "timeline_title": "Timeline",
        "timeline": (
            "We answer your request within 1 business day.",
            "Standard review: delivery in {days} business days from the arrival of the "
            "complete data.",
            "Extended review: the timeline is agreed in the quote, depending on how many "
            "portfolios it covers.",
            "Re-run: {rerun} days after delivery, with the updated series you send us.",
        ),
        "terms_title": "Terms",
        "terms": (
            "The price does not depend on the result.",
            "The review is governed by the written quote you accept: scope, price, payments, "
            "confidentiality and deletion. The site's terms describe the automated report.",
            "Nothing is published without your written permission.",
            "{delete} days after each delivery, or sooner if you ask, we delete the whole "
            "audit: the files, the report, its private link and the record of its files. From "
            "then on /check no longer recognises its PDF, so keep your copy. That deletion "
            "date is written into the quote.",
            "The series is uploaded with the access code we send when you accept the quote: "
            "the audit then counts as paid, and the clean-up of unpaid audits does not delete it "
            "before that date.",
            "Payment: {deposit} % on accepting the quote and {rest} % on delivery.",
            "It is an independent statistical reading of the series you supply, not a "
            "verification of how the signal was built.",
        ),
        "privacy_note": "What the site keeps of each report is set out in the",
        "privacy_link": "privacy policy",
        "sample_title": "A sample review",
        "sample_text": (
            "A momentum portfolio and its 10 variants, with synthetic data: the methodology "
            "notes, the Rigor report and the PDF, as a client would receive them."
        ),
        "sample_link": "See the sample review",
        "form_lead": "Tell us about your series and we will send you the scope and the quote.",
    },
    "pt": {
        "eyebrow": "Revisão institucional",
        "title": "Uma revisão independente de uma carteira ou de um sinal",
        "seo_title": "Revisão institucional independente a partir de {standard}",
        "summary": (
            "Revisão estatística independente de uma carteira ou de um sinal: escopo, "
            "entregáveis, entrega em {days} dias úteis e condições. A partir de {standard}."
        ),
        "lead": (
            "Para vendedores de sinais e de dados e para gestores emergentes que precisam "
            "apresentar sua série a um investidor, a um comitê ou a uma plataforma: o motor do "
            "Rigor sobre a sua série, com notas escritas para quem decide."
        ),
        "not_audit": (
            "É uma revisão independente: não é uma auditoria contábil nem regulatória, nem "
            "recomendação de investimento."
        ),
        "plans_title": "Dois escopos",
        "standard": "Revisão padrão",
        "standard_price": "A partir de {standard}",
        "standard_items": (
            "Uma carteira ou série de retornos, um benchmark e as variantes que você declarar.",
            "Relatório escrito com notas de metodologia, o relatório Rigor completo e o PDF.",
            "Uma chamada de {minutes} minutos para repassar os resultados.",
            "Uma nova execução após {rerun} dias, com a série atualizada.",
            "Entrega em {days} dias úteis a partir da chegada dos dados completos.",
        ),
        "extended": "Revisão ampliada",
        "extended_price": "Até {extended}",
        "extended_lead": "Tudo o que a revisão padrão inclui e, além disso:",
        "extended_items": (
            "Várias carteiras ou universos.",
            "Atribuição a vários fatores, calculada à parte do relatório Rigor.",
            "Capacidade e custos por cenário, calculados à parte do relatório Rigor.",
            "Uma segunda nova execução.",
        ),
        "request": "Solicitar uma revisão",
        "deliverables_title": "O que você recebe",
        "deliverables": (
            "Notas de metodologia: o que foi medido, como, o que não é medido e o que significa "
            "cada resultado. Cada número sai do relatório Rigor, exceto os que a revisão "
            "ampliada calcula à parte (vários fatores, capacidade), com a metodologia combinada "
            "na cotação.",
            "O relatório Rigor completo: cada valor diz se foi medido na sua série, se foi "
            "declarado por você ou se não pôde ser medido.",
            "O PDF do relatório, para compartilhar com quem você decidir: pode ser conferido em "
            "/pt/comprovar enquanto a auditoria não for excluída.",
            "A chamada e as novas execuções do seu escopo.",
        ),
        "send_title": "O que enviar",
        "send_items": (
            "Retornos mensais ou diários da carteira modelo em um CSV com uma coluna de data e "
            "uma de retorno (date,return), ou uma série de NAV (date,nav). Se tiver retornos "
            "brutos e líquidos de custos, envie-os como duas colunas do mesmo CSV (gross_return "
            "e net_return), como no modelo: uma série de NAV tem uma só coluna. Caso contrário, "
            "brutos mais a premissa de custos.",
            "Índice de referência: sua série no mesmo formato (em um CSV separado ou como coluna "
            "benchmark do mesmo CSV), ou apenas o nome se for um índice padrão.",
            "Quantas variantes você testou antes de fixar as regras. Se tiver as séries das "
            "variantes, envie-as em um CSV separado com uma coluna de data e uma por variante "
            "(date,variant_1,variant_2), com as mesmas datas da carteira: pelo menos 2 "
            "variantes e 16 datas, até 500 variantes e 5 MB, sem células vazias. Caso "
            "contrário, basta o número e o relatório o marca como declarado.",
            "Período reservado (fora da amostra): a data a partir da qual as regras ficaram "
            "fixas e se a série anterior foi usada para escolhê-las.",
            "Premissas de custos: giro da carteira e custo por rebalanceamento expresso em "
            "pontos-base (bps).",
        ),
        "template_link": "Baixar modelo CSV com dados fictícios",
        "template_note": (
            "O modelo usa date,gross_return,net_return,benchmark: retornos brutos, líquidos "
            "e do índice de referência; as variantes vão no CSV separado. As quatro linhas "
            "são totalmente fictícias e só mostram o formato: substitua-as pelo histórico "
            "completo. Use datas AAAA-MM-DD e retornos em frações (0.01 = 1 %), com ponto "
            "decimal. Remova as colunas net_return ou benchmark se não tiver essas séries."
        ),
        "nda": "Assinamos um NDA mútuo antes de você enviar qualquer dado; pode enviar o seu.",
        "publication_note": (
            "Sem permissão por escrito, nenhum relatório, nem o primeiro, é publicado e a "
            "empresa não é mencionada."
        ),
        "scope_limit": (
            "A revisão não concilia os números com a corretora nem com o administrador, não é "
            "uma due diligence operacional e não é uma apresentação GIPS."
        ),
        "timeline_title": "Prazos",
        "timeline": (
            "Respondemos à sua solicitação em 1 dia útil.",
            "Revisão padrão: entrega em {days} dias úteis a partir da chegada dos dados completos.",
            "Revisão ampliada: o prazo é combinado na cotação, conforme quantas carteiras ela "
            "incluir.",
            "Nova execução: {rerun} dias após a entrega, com a série atualizada que você nos "
            "enviar.",
        ),
        "terms_title": "Condições",
        "terms": (
            "O preço não depende do resultado.",
            "A revisão é regida pela cotação escrita que você aceita: escopo, preço, pagamentos, "
            "confidencialidade e exclusão. Os termos do site descrevem o relatório automático.",
            "Nada é publicado sem a sua permissão por escrito.",
            "{delete} dias após cada entrega, ou antes se você pedir, excluímos a auditoria "
            "inteira: os arquivos, o relatório, o link privado e o registro dos seus arquivos. "
            "A partir daí, /pt/comprovar não reconhece mais o PDF, então guarde a sua cópia. "
            "Esse prazo de exclusão fica escrito na cotação.",
            "A série é enviada com o código de acesso que mandamos quando você aceita a cotação: "
            "assim a auditoria fica como paga e a limpeza das auditorias não pagas não a exclui "
            "antes desse prazo.",
            "Pagamento: {deposit} % ao aceitar a cotação e {rest} % na entrega.",
            "É uma leitura estatística independente da série que você fornece, não uma "
            "verificação de como o sinal foi construído.",
        ),
        "privacy_note": "O que o site guarda de cada relatório está explicado na",
        "privacy_link": "política de privacidade",
        "sample_title": "Uma revisão de exemplo",
        "sample_text": (
            "Uma carteira de momentum e suas 10 variantes, com dados sintéticos: as notas de "
            "metodologia, o relatório Rigor e o PDF, como um cliente os receberia."
        ),
        "sample_link": "Ver a revisão de exemplo",
        "form_lead": "Conte sobre a sua série e enviamos o escopo e a cotação.",
    },
}

#: The anchor of the request form on the review page.
FORM_ANCHOR = "solicitar"


def price_text(amount: int) -> str:
    """A whole-dollar price as the offer shows it: ``USD 2,500``."""
    return f"USD {amount:,}"


def offer_values() -> dict[str, str | int]:
    """The offer's figures, read from this module's constants when called, so that
    changing a constant changes every page that shows it."""
    return {
        "standard": price_text(STANDARD_PRICE_USD),
        "extended": price_text(EXTENDED_PRICE_USD),
        "days": DELIVERY_BUSINESS_DAYS,
        "minutes": CALL_MINUTES,
        "rerun": RERUN_DAYS,
        "delete": DELETE_DAYS,
        "deposit": DEPOSIT_PERCENT,
        "rest": 100 - DEPOSIT_PERCENT,
    }


def offer_text(locale: str, key: str) -> str:
    """One of the offer's sentences in ``locale`` with its figures filled in."""
    words = OFFER_COPY.get(locale, OFFER_COPY["es"])
    return str(words[key]).format(**offer_values())


def offer_lines(locale: str, key: str) -> tuple[str, ...]:
    """One of the offer's lists in ``locale`` with its figures filled in."""
    words = OFFER_COPY.get(locale, OFFER_COPY["es"])
    values = offer_values()
    return tuple(str(line).format(**values) for line in words[key])


def offer_structured_data(locale: str, url: str) -> dict[str, Any]:
    """The review as a schema.org ``Service`` with its two price bounds: only the
    words and prices the page shows."""
    return {
        "@context": "https://schema.org",
        "@type": "Service",
        "name": offer_text(locale, "title"),
        "description": offer_text(locale, "summary"),
        "serviceType": offer_text(locale, "eyebrow"),
        "areaServed": "Worldwide",
        "inLanguage": locale,
        "provider": {"@type": "Organization", "name": "Rigor"},
        **({"url": url} if url else {}),
        "offers": [
            {
                "@type": "Offer",
                "name": offer_text(locale, "standard"),
                "priceCurrency": "USD",
                "priceSpecification": {
                    "@type": "PriceSpecification",
                    "minPrice": STANDARD_PRICE_USD,
                    "priceCurrency": "USD",
                },
            },
            {
                "@type": "Offer",
                "name": offer_text(locale, "extended"),
                "priceCurrency": "USD",
                "priceSpecification": {
                    "@type": "PriceSpecification",
                    "maxPrice": EXTENDED_PRICE_USD,
                    "priceCurrency": "USD",
                },
            },
        ],
    }


def offer_html(locale: str, *, privacy_url: str) -> str:
    """The review page's description of the offer: the two scopes with their prices,
    what the client receives and sends, the timeline, terms and sample review."""
    # Imported here: ``theme`` imports ``seo``, which reads this module's paths.
    from quant_trade.audit.theme import icon

    locale = locale if locale in OFFER_COPY else "es"

    def e(value: object) -> str:
        return html.escape(str(value), quote=True)

    def checks(lines: tuple[str, ...]) -> str:
        return (
            "<ul class='checks'>"
            + "".join(f"<li>{icon('check')}<span>{e(line)}</span></li>" for line in lines)
            + "</ul>"
        )

    def card(name: str, price: str, lead: str, items: str) -> str:
        return (
            f"<div class='plan-card'><h2>{e(offer_text(locale, name))}</h2>"
            f"<p class='plan-price'>{e(offer_text(locale, price))}</p>"
            + (f"<p class='plan-note'>{e(offer_text(locale, lead))}</p>" if lead else "")
            + checks(offer_lines(locale, items))
            + f"<a class='btn btn-dark' href='#{FORM_ANCHOR}'>{e(offer_text(locale, 'request'))}"
            "</a></div>"
        )

    plans = card("standard", "standard_price", "", "standard_items") + card(
        "extended", "extended_price", "extended_lead", "extended_items"
    )

    def section(title: str, inner: str) -> str:
        return f"<section class='rsec'><h2>{e(offer_text(locale, title))}</h2>{inner}</section>"

    # The page's first screen already says it is not an accounting or regulatory audit.
    privacy = (
        f"<p>{e(offer_text(locale, 'privacy_note'))} "
        f"<a href='{e(privacy_url)}'>{e(offer_text(locale, 'privacy_link'))}</a>.</p>"
    )
    sample = (
        f"<p>{e(offer_text(locale, 'sample_text'))}</p>"
        f"<p><a class='link-more' href='{SAMPLE_PATHS[locale]}'>"
        f"{e(offer_text(locale, 'sample_link'))}{icon('arrow')}</a></p>"
    )
    send = (
        "<ol>"
        + "".join(f"<li>{e(line)}</li>" for line in offer_lines(locale, "send_items"))
        + "</ol>"
        + f"<p><a class='link-more' href='{TEMPLATE_PATH}' download>"
        f"{e(offer_text(locale, 'template_link'))}</a></p>"
        f"<p>{e(offer_text(locale, 'template_note'))}</p>"
        f"<p>{e(offer_text(locale, 'nda'))}</p>"
        f"<p>{e(offer_text(locale, 'publication_note'))}</p>"
    )
    return (
        # The cards' names are the section's headings, as on the pricing page.
        f"<section class='rsec' aria-label='{e(offer_text(locale, 'plans_title'))}'>"
        f"<div class='plan-cards'>{plans}</div></section>"
        + section("deliverables_title", checks(offer_lines(locale, "deliverables")))
        + section("send_title", send)
        + section("timeline_title", checks(offer_lines(locale, "timeline")))
        + section(
            "terms_title",
            checks(offer_lines(locale, "terms"))
            + f"<p>{e(offer_text(locale, 'scope_limit'))}</p>"
            + privacy,
        )
        + section("sample_title", sample)
    )
