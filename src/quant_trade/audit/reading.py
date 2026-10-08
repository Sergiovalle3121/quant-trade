"""Public, reproducible declarations; no identity, file, audit or persistence."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlencode

from quant_trade.audit.public_card import PublicClaim

READING_PATH = {"es": "/lectura", "en": "/en/reading", "pt": "/pt/leitura"}
MAX_REQUESTS_PER_HOUR = 60
FIELDS = ("trades", "win_rate", "profit_factor", "sharpe", "years", "trials", "target_r", "stop_r")
COPY = {
    "es": {
        "title": "Lector de cifras",
        "eyebrow": "Herramienta gratis",
        "summary": (
            "Pon tus cifras declaradas en contexto estadístico y comparte la tarjeta. Sin registro."
        ),
        "attribution": "Cifras declaradas por quien usó la herramienta",
        "note": "Esta tarjeta no es una auditoría. No hay archivo ni clase de auditoría.",
        "optional": "Deja vacío lo que no conoces: aparecerá como NOT_MEASURED.",
        "public": (
            "El enlace compartido contiene las cifras que escribes; "
            "cualquiera con el enlace puede leerlas."
        ),
        "submit": "Crear tarjeta",
        "result": "Lectura de cifras declaradas",
        "download": "Descargar SVG",
        "download_png": "Descargar PNG",
        "copy_link": "Copiar enlace",
        "share_text": (
            "Mis cifras declaradas, en contexto con Rigor. Esta tarjeta no es una auditoría. {url}"
        ),
        "limited": "Demasiadas lecturas desde esta dirección. Inténtalo de nuevo más tarde.",
        "png_unavailable": "La imagen PNG no está disponible temporalmente.",
    },
    "en": {
        "title": "Figure reader",
        "eyebrow": "Free tool",
        "summary": (
            "Put your declared figures in statistical context and share the card. No signup."
        ),
        "attribution": "Figures declared by the person who used the tool",
        "note": "This card is not an audit. There is no file or audit class.",
        "optional": "Leave what you do not know empty: it will appear as NOT_MEASURED.",
        "public": (
            "The shared link contains the figures you enter; anyone with the link can read them."
        ),
        "submit": "Create card",
        "result": "Reading declared figures",
        "download": "Download SVG",
        "download_png": "Download PNG",
        "copy_link": "Copy link",
        "share_text": (
            "My declared figures, in context with Rigor. This card is not an audit. {url}"
        ),
        "limited": "Too many readings from this address. Try again later.",
        "png_unavailable": "The PNG image is temporarily unavailable.",
    },
    "pt": {
        "title": "Leitor de números",
        "eyebrow": "Ferramenta grátis",
        "summary": (
            "Coloque seus números declarados em contexto estatístico e compartilhe o cartão. "
            "Sem cadastro."
        ),
        "attribution": "Números declarados por quem usou a ferramenta",
        "note": "Este cartão não é uma auditoria. Não há arquivo nem classe de auditoria.",
        "optional": "Deixe vazio o que não sabe: aparecerá como NOT_MEASURED.",
        "public": (
            "O link compartilhado contém os números que você informa; "
            "qualquer pessoa com o link pode lê-los."
        ),
        "submit": "Criar cartão",
        "result": "Leitura de números declarados",
        "download": "Baixar SVG",
        "download_png": "Baixar PNG",
        "copy_link": "Copiar link",
        "share_text": (
            "Meus números declarados, em contexto com o Rigor. "
            "Este cartão não é uma auditoria. {url}"
        ),
        "limited": "Leituras demais a partir deste endereço. Tente novamente mais tarde.",
        "png_unavailable": "A imagem PNG está temporariamente indisponível.",
    },
}


def claim_from_query(values: Mapping[str, str], locale: str) -> PublicClaim:
    """Use the owner's numeric parser, admitting only public numeric fields.

    Imports stay local because the owner's form also uses the page shell.
    Identity and language never come from the query string.
    """
    from quant_trade.audit.owner_card import claim_from_form

    fields = {name: values.get(name, "") for name in FIELDS}
    fields["win_rate_percent"] = fields.pop("win_rate")
    return claim_from_form(
        {**fields, "locale": locale, "source_handle": COPY[locale]["attribution"]}
    )


def reading_url(locale: str, values: Mapping[str, str] | None = None) -> str:
    path = READING_PATH[locale]
    if values is None:
        return path
    # Keep validated numeric strings: re-serializing a percentage from its
    # binary fraction can change the last bit and break exact reproduction.
    query = {name: values.get(name, "").strip() for name in FIELDS}
    return path + "?" + urlencode({**query, "ref": "lectura"})
