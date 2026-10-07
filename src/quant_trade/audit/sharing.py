"""Fixed sharing copy made only from the public class and publication id."""

from __future__ import annotations

import html
from urllib.parse import quote, urlencode

COPY = {
    "es": {
        "title": "Compartir",
        "text": (
            "Audité mi backtest con Rigor: clase {overall}. Consulta costos, fuera de muestra "
            "y configuraciones probadas, con etiquetas de evidencia. {url}"
        ),
        "copy": "Copiar texto",
        "done": "Texto copiado",
        "fallback": "Texto seleccionado. Usa la opción Copiar de tu dispositivo.",
        "post": "Publicar en X",
        "preview": "Tarjeta pública del informe",
    },
    "en": {
        "title": "Share",
        "text": (
            "I audited my backtest with Rigor: class {overall}. See costs, out-of-sample data "
            "and configurations tried, with evidence labels. {url}"
        ),
        "copy": "Copy text",
        "done": "Text copied",
        "fallback": "Text selected. Use your device's Copy command.",
        "post": "Post on X",
        "preview": "Public report card",
    },
    "pt": {
        "title": "Compartilhar",
        "text": (
            "Auditei meu backtest com o Rigor: classe {overall}. Veja custos, dados fora da "
            "amostra e configurações testadas, com etiquetas de evidência. {url}"
        ),
        "copy": "Copiar texto",
        "done": "Texto copiado",
        "fallback": "Texto selecionado. Use a opção Copiar do seu dispositivo.",
        "post": "Publicar no X",
        "preview": "Cartão público do relatório",
    },
}


def share_text(*, overall: str, public_id: str, locale: str = "es") -> str:
    """No result object or private report URL crosses this boundary."""
    locale = locale if locale in COPY else "es"
    if overall not in ("A", "B", "C", "D") or not public_id:
        return ""
    url = f"https://rigorscore.com/v/{quote(public_id, safe='')}?ref=share"
    if locale != "es":
        url += f"&lang={locale}"
    return COPY[locale]["text"].format(overall=overall, url=url)


def share_block(*, overall: str, public_id: str, locale: str = "es") -> str:
    """Call only after the store confirms an active publication."""
    locale = locale if locale in COPY else "es"
    text = share_text(overall=overall, public_id=public_id, locale=locale)
    if not text:
        return ""
    words = COPY[locale]
    escape = html.escape
    intent = "https://x.com/intent/post?" + urlencode({"text": text})
    image = f"/v/{quote(public_id, safe='')}/card.svg?lang={locale}"
    return (
        "<section class='rsec no-print' id='share-publication' data-public-share>"
        f"<h2>{escape(words['title'])}</h2>"
        f"<label class='muted' for='share-text'>{escape(words['copy'])}</label>"
        "<textarea id='share-text' readonly rows='5' style='width:100%'>"
        f"{escape(text)}</textarea>"
        "<div class='copy-row'><button class='btn btn-dark btn-sm' type='button' "
        f"data-copy='share-text' data-done='{escape(words['done'])}' "
        f"data-fallback='{escape(words['fallback'])}' hidden>{escape(words['copy'])}</button>"
        f"<a class='btn btn-ghost btn-sm' href='{escape(intent)}' "
        f"rel='noopener noreferrer'>{escape(words['post'])}</a></div>"
        "<p class='muted' data-copy-status role='status' aria-live='polite'></p>"
        f"<img src='{escape(image)}' alt='{escape(words['preview'])}' "
        "width='1200' height='630' loading='lazy' style='width:100%;height:auto'>"
        "</section>"
    )
