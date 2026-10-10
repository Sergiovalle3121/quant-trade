"""Fixed sharing copy using only the class, publication id and report kind."""

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
        "text_account": (
            "Audité el historial de mi cuenta con Rigor: clase {overall}. Consulta costos, "
            "fuera de muestra y configuraciones probadas, con etiquetas de evidencia. {url}"
        ),
        "text_fund": (
            "Audité el historial de mi fondo con Rigor: clase {overall}. Consulta las "
            "comprobaciones del historial, con etiquetas de evidencia. {url}"
        ),
        "copy": "Copiar texto",
        "done": "Texto copiado",
        "fallback": "Texto seleccionado. Usa la opción Copiar de tu dispositivo.",
        "post": "Publicar en X",
        "whatsapp": "Enviar por WhatsApp",
        "telegram": "Compartir en Telegram",
        "preview": "Tarjeta pública del informe",
    },
    "en": {
        "title": "Share",
        "text": (
            "I audited my backtest with Rigor: class {overall}. See costs, out-of-sample data "
            "and configurations tried, with evidence labels. {url}"
        ),
        "text_account": (
            "I audited my account history with Rigor: class {overall}. See costs, "
            "out-of-sample data and configurations tried, with evidence labels. {url}"
        ),
        "text_fund": (
            "I audited my fund's track record with Rigor: class {overall}. See the "
            "history checks, with evidence labels. {url}"
        ),
        "copy": "Copy text",
        "done": "Text copied",
        "fallback": "Text selected. Use your device's Copy command.",
        "post": "Post on X",
        "whatsapp": "Send on WhatsApp",
        "telegram": "Share on Telegram",
        "preview": "Public report card",
    },
    "pt": {
        "title": "Compartilhar",
        "text": (
            "Auditei meu backtest com o Rigor: classe {overall}. Veja custos, dados fora da "
            "amostra e configurações testadas, com etiquetas de evidência. {url}"
        ),
        "text_account": (
            "Auditei o histórico da minha conta com o Rigor: classe {overall}. Veja custos, "
            "dados fora da amostra e configurações testadas, com etiquetas de evidência. {url}"
        ),
        "text_fund": (
            "Auditei o histórico do meu fundo com o Rigor: classe {overall}. Veja as "
            "verificações do histórico, com etiquetas de evidência. {url}"
        ),
        "copy": "Copiar texto",
        "done": "Texto copiado",
        "fallback": "Texto selecionado. Use a opção Copiar do seu dispositivo.",
        "post": "Publicar no X",
        "whatsapp": "Enviar pelo WhatsApp",
        "telegram": "Compartilhar no Telegram",
        "preview": "Cartão público do relatório",
    },
}


def public_report_url(public_id: str, locale: str, *, ref: str = "share") -> str:
    """The public page of a published report, tagged with ``ref`` (``funnel.REF_TAGS``)."""
    url = f"https://rigorscore.com/v/{quote(public_id, safe='')}?ref={ref}"
    if locale != "es":
        url += f"&lang={locale}"
    return url


def share_text(
    *,
    overall: str,
    public_id: str,
    locale: str = "es",
    kind: str = "backtest",
    template: str | None = None,
    ref: str = "share",
) -> str:
    """No result object or private report URL crosses this boundary.

    ``template`` and ``ref`` replace the owner's words and the "share" tag only on a
    public sample's page (``sample_publication.sample_page``), which is nobody's
    audit."""
    locale = locale if locale in COPY else "es"
    if overall not in ("A", "B", "C", "D") or not public_id:
        return ""
    if template is None:
        template = COPY[locale][{"account": "text_account", "fund": "text_fund"}.get(kind, "text")]
    return template.format(overall=overall, url=public_report_url(public_id, locale, ref=ref))


def share_block(
    *,
    overall: str,
    public_id: str,
    locale: str = "es",
    kind: str = "backtest",
    template: str | None = None,
    ref: str = "share",
) -> str:
    """Call only after the store confirms an active publication, or for a public
    sample's page with its own ``template`` and ``ref`` (``share_text``)."""
    locale = locale if locale in COPY else "es"
    text = share_text(
        overall=overall, public_id=public_id, locale=locale, kind=kind, template=template, ref=ref
    )
    if not text:
        return ""
    words = COPY[locale]
    escape = html.escape
    intent = "https://x.com/intent/post?" + urlencode({"text": text})
    whatsapp = "https://wa.me/?text=" + quote(text, safe="")
    url = public_report_url(public_id, locale, ref=ref)
    text_without_url = text.removesuffix(url).rstrip()
    telegram = (
        "https://t.me/share/url?url="
        + quote(url, safe="")
        + "&text="
        + quote(text_without_url, safe="")
    )
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
        f"target='_blank' rel='noopener noreferrer'>{escape(words['post'])}</a>"
        f"<a class='btn btn-ghost btn-sm' href='{escape(whatsapp)}' "
        f"target='_blank' rel='noopener noreferrer'>{escape(words['whatsapp'])}</a>"
        f"<a class='btn btn-ghost btn-sm' href='{escape(telegram)}' "
        f"target='_blank' rel='noopener noreferrer'>{escape(words['telegram'])}</a></div>"
        "<p class='muted' data-copy-status role='status' aria-live='polite'></p>"
        f"<img src='{escape(image)}' alt='{escape(words['preview'])}' "
        "width='1200' height='630' loading='lazy' style='width:100%;height:auto'>"
        "</section>"
    )
