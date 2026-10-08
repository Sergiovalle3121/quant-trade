"""Private, in-memory public-card form; the web layer owns authentication.

The panel authenticates each POST with its owner key, rather than creating an
account session. Downloads submit the same declaration and render it again;
neither declarations nor generated images need a store or a filesystem path.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from quant_trade.audit import raster
from quant_trade.audit.guard import AuditReportError
from quant_trade.audit.pages import _e, _field, _page, _page_hero
from quant_trade.audit.public_card import COPY as CARD_COPY
from quant_trade.audit.public_card import PublicClaim, public_card_svg

FORM_FIELDS = (
    "source_handle",
    "source_url",
    "trades",
    "win_rate_percent",
    "profit_factor",
    "sharpe",
    "years",
    "trials",
    "target_r",
    "stop_r",
    "locale",
)
COPY = {
    "es": {
        "title": "Tarjeta pública",
        "private": "Panel privado",
        "lead": (
            "Escribe las cifras de una publicación. Son declaraciones, sin archivo de respaldo."
        ),
        "optional": "Deja vacío lo que no figure en la publicación: aparecerá como NOT_MEASURED.",
        "handle": "Autor o atribución",
        "url": "URL de la publicación",
        "rate": "Aciertos (%)",
        "language": "Idioma",
        "preview": "Crear tarjeta",
        "result": "Vista previa",
        "svg": "Descargar .svg",
        "png": "Descargar .png",
        "back": "Volver al panel",
        "png_unavailable": (
            "La conversión a PNG no está disponible aquí. Descarga el SVG y expórtalo como PNG "
            "fuera de Rigor, por ejemplo con Inkscape."
        ),
        "source": (
            "Revisa la atribución y la URL: usa texto breve, sin caracteres de control "
            "ni afirmaciones restringidas."
        ),
        "counts": (
            "Operaciones y configuraciones deben ser enteros positivos dentro del límite "
            "del formulario."
        ),
        "figures": "Revisa las cifras: usa números finitos dentro de los límites del formulario.",
        "rate_error": "Escribe el porcentaje de aciertos dentro de los límites del formulario.",
        "positive": "Años, objetivo y stop deben ser mayores que cero.",
        "factor": "El profit factor no puede ser negativo.",
        "locale": "Elige español, inglés o portugués.",
        "invalid": "Revisa los campos; no se pudo crear la tarjeta.",
    },
    "en": {
        "title": "Public card",
        "private": "Private panel",
        "lead": (
            "Enter the figures from a public post. These are declarations "
            "without a supporting file."
        ),
        "optional": "Leave figures absent from the post empty: they will appear as NOT_MEASURED.",
        "handle": "Author or attribution",
        "url": "Post URL",
        "rate": "Win rate (%)",
        "language": "Language",
        "preview": "Create card",
        "result": "Preview",
        "svg": "Download .svg",
        "png": "Download .png",
        "back": "Back to panel",
        "png_unavailable": (
            "PNG conversion is unavailable here. Download the SVG and export it as PNG outside "
            "Rigor, for example with Inkscape."
        ),
        "source": (
            "Check the attribution and URL: use brief text without control characters "
            "or restricted claims."
        ),
        "counts": "Trades and configurations must be positive integers within the form limits.",
        "figures": "Check the figures: use finite numbers within the form limits.",
        "rate_error": "Enter the win rate as a percentage within the form limits.",
        "positive": "Years, target and stop must be greater than zero.",
        "factor": "Profit factor cannot be negative.",
        "locale": "Choose Spanish, English or Portuguese.",
        "invalid": "Check the fields; the card could not be created.",
    },
    "pt": {
        "title": "Cartão público",
        "private": "Painel privado",
        "lead": "Informe os números de uma publicação. São declarações sem arquivo de suporte.",
        "optional": "Deixe vazio o que não constar na publicação: aparecerá como NOT_MEASURED.",
        "handle": "Autor ou atribuição",
        "url": "URL da publicação",
        "rate": "Acertos (%)",
        "language": "Idioma",
        "preview": "Criar cartão",
        "result": "Prévia",
        "svg": "Baixar .svg",
        "png": "Baixar .png",
        "back": "Voltar ao painel",
        "png_unavailable": (
            "A conversão para PNG não está disponível aqui. Baixe o SVG e exporte como PNG fora "
            "do Rigor, por exemplo com Inkscape."
        ),
        "source": (
            "Revise a atribuição e a URL: use texto breve, sem caracteres de controle "
            "nem afirmações restritas."
        ),
        "counts": (
            "Operações e configurações devem ser inteiros positivos dentro dos limites "
            "do formulário."
        ),
        "figures": "Revise os números: use valores finitos dentro dos limites do formulário.",
        "rate_error": "Informe a porcentagem de acertos dentro dos limites do formulário.",
        "positive": "Anos, alvo e stop devem ser maiores que zero.",
        "factor": "O profit factor não pode ser negativo.",
        "locale": "Escolha espanhol, inglês ou português.",
        "invalid": "Revise os campos; não foi possível criar o cartão.",
    },
}


class ClaimInputError(ValueError):
    """A stable, localizable error code; never echo an untrusted field."""


def claim_from_form(values: Mapping[str, str]) -> PublicClaim:
    """Convert the displayed percentage, then use the CLI's PublicClaim limits."""
    locale = values.get("locale", "es")
    if locale not in COPY:
        raise ClaimInputError("locale")
    parsed: dict[str, Any] = {
        "source_handle": values.get("source_handle", ""),
        "source_url": values.get("source_url", ""),
        "locale": locale,
    }
    for name in FORM_FIELDS[2:-1]:
        raw = values.get(name, "").strip()
        if not raw:
            continue
        try:
            if len(raw) > 40:
                raise ValueError("number too long")
            parsed[name] = int(raw) if name in ("trades", "trials") else float(raw)
        except ValueError as exc:
            raise ClaimInputError("counts" if name in ("trades", "trials") else "figures") from exc
    if "win_rate_percent" in parsed:
        parsed["win_rate"] = parsed.pop("win_rate_percent") / 100
    try:
        return PublicClaim(**parsed)
    except ValueError as exc:
        code = "invalid"
        message = str(exc)
        for prefix, mapped in (
            ("source", "source"),
            ("counts", "counts"),
            ("figures", "figures"),
            ("win_rate", "rate_error"),
            ("years,", "positive"),
            ("profit_factor", "factor"),
            ("locale", "locale"),
        ):
            if message.startswith(prefix):
                code = mapped
                break
        raise ClaimInputError(code) from exc


def render_form(values: Mapping[str, str]) -> tuple[PublicClaim, str]:
    claim = claim_from_form(values)
    try:
        return claim, public_card_svg(claim)
    except (ValueError, AuditReportError) as exc:
        # The card also checks a shortened source label before rendering it.
        raise ClaimInputError("source") from exc


def png_available() -> bool:
    """Probe conversion too: an import alone cannot establish PNG support."""
    probe = '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
    return raster.card_png(probe) is not None


def svg_to_png(svg: str) -> bytes | None:
    """Convert our generated SVG in memory; never accept user-provided markup."""
    return raster.card_png(svg)


def _values(claim: PublicClaim | None) -> dict[str, str]:
    if claim is None:
        return {}
    result = {}
    for name in FORM_FIELDS:
        value = claim.win_rate if name == "win_rate_percent" else getattr(claim, name)
        if value is None:
            result[name] = ""
        elif name == "win_rate_percent":
            result[name] = format(value * 100, ".15g")
        else:
            result[name] = str(value)
    return result


def page(
    *,
    key: str,
    panel_path: str,
    locale: str = "es",
    claim: PublicClaim | None = None,
    svg: str = "",
    error: str = "",
    png_enabled: bool = False,
) -> str:
    """Render only validated values. Rejected source text never reaches HTML."""
    locale = claim.locale if claim else locale if locale in COPY else "es"
    words, card = COPY[locale], CARD_COPY[locale]
    values = _values(claim)
    key_input = f"<input type='hidden' name='key' value='{_e(key)}'>"
    body = (
        f"<form method='post' action='{_e(panel_path)}'>{key_input}"
        f"<button class='btn btn-ghost' type='submit'>{_e(words['back'])}</button></form>"
    )
    if error:
        body += f"<p class='error' role='alert'>{_e(words.get(error, words['invalid']))}</p>"
    body += (
        f"<p>{_e(words['optional'])}</p>"
        f"<form method='post' action='{_e(panel_path)}/public-card'>{key_input}"
    )
    labels = {
        "source_handle": words["handle"],
        "source_url": words["url"],
        "win_rate_percent": words["rate"],
    }
    for name in FORM_FIELDS[:-1]:
        attrs = (
            "type='text' maxlength='2048'"
            if name.startswith("source_")
            else (
                "type='number' step='1' min='1' max='10000000'"
                if name in ("trades", "trials")
                else "type='number' step='any' min='0' max='100'"
                if name == "win_rate_percent"
                else "type='number' step='any' min='-1000000' max='1000000'"
                if name == "sharpe"
                else "type='number' step='any' min='0' max='1000000'"
            )
        )
        body += _field(
            f"{labels.get(name, card.get(name, name))} · DECLARED",
            f"<input {attrs} name='{name}' value='{_e(values.get(name, ''))}' autocomplete='off'>",
        )
    options = "".join(
        f"<option value='{lang}'{' selected' if lang == locale else ''}>{label}</option>"
        for lang, label in (("es", "Español"), ("en", "English"), ("pt", "Português"))
    )
    body += _field(words["language"], f"<select name='locale'>{options}</select>")
    body += (
        f"<button class='btn btn-dark' type='submit' name='action' value='preview'>"
        f"{_e(words['preview'])}</button></form>"
    )
    if svg and claim is not None:
        body += (
            f"<section><h2>{_e(words['result'])}</h2><div class='public-card-preview'>{svg}</div>"
        )
        body += f"<form method='post' action='{_e(panel_path)}/public-card'>{key_input}"
        body += "".join(
            f"<input type='hidden' name='{name}' value='{_e(value)}'>"
            for name, value in values.items()
        )
        body += (
            f"<button class='btn btn-dark' type='submit' name='action' value='svg'>"
            f"{_e(words['svg'])}</button>"
        )
        if png_enabled:
            body += (
                f"<button class='btn btn-ghost' type='submit' name='action' value='png'>"
                f"{_e(words['png'])}</button>"
            )
        body += "</form>"
        if not png_enabled:
            body += f"<p>{_e(words['png_unavailable'])}</p>"
        body += "</section>"
    return _page(
        words["title"],
        locale,
        _page_hero(words["private"], words["title"], words["lead"])
        + f"<div class='paper page-main'><div class='wrap wrap-narrow'>{body}</div></div>",
        solid_nav=True,
    )
