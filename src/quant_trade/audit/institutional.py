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
MAX_REQUESTS_PER_HOUR = 5
BODY_LIMIT = 16_384
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
        "note": "Los datos son DECLARED: los aporta quien solicita la revisión. "
        "Aquí no se adjuntan archivos; la serie se sube después por el flujo habitual.",
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
        "note": "These details are DECLARED: supplied by the person requesting the review. "
        "This form has no attachments; upload the series later through the usual flow.",
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
        "note": "Os dados são DECLARED: fornecidos por quem solicita a revisão. "
        "Este formulário não recebe arquivos; a série será enviada depois pelo fluxo habitual.",
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
