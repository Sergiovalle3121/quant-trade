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
OFFER_UPDATED = "2026-10-10"
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
        "revisión. Aquí no se adjuntan archivos; la serie se sube después por el flujo habitual.",
        "privacy": "Privacidad",
        "received": "Solicitud recibida",
        "next": "Te escribimos en 1 día hábil. Prepara la serie bruta y neta y tu benchmark.",
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
        "requesting the review. This form has no attachments; upload the series later through "
        "the usual flow.",
        "privacy": "Privacy",
        "received": "Request received",
        "next": (
            "We will write within 1 business day. Prepare your gross and net series and benchmark."
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
        "revisão. Este formulário não recebe arquivos; a série será enviada depois pelo fluxo "
        "habitual.",
        "privacy": "Privacidade",
        "received": "Solicitação recebida",
        "next": "Escrevemos em 1 dia útil. Prepare a série bruta e líquida e seu benchmark.",
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
            "Ofrecemos un acuerdo de confidencialidad (NDA) mutuo.",
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
            "We offer a mutual non-disclosure agreement (NDA).",
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
            "Oferecemos um acordo de confidencialidade (NDA) mútuo.",
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
    what the client receives, the timeline, the terms and the sample review."""
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
    return (
        # The cards' names are the section's headings, as on the pricing page.
        f"<section class='rsec' aria-label='{e(offer_text(locale, 'plans_title'))}'>"
        f"<div class='plan-cards'>{plans}</div></section>"
        + section("deliverables_title", checks(offer_lines(locale, "deliverables")))
        + section("timeline_title", checks(offer_lines(locale, "timeline")))
        + section("terms_title", checks(offer_lines(locale, "terms")) + privacy)
        + section("sample_title", sample)
    )
