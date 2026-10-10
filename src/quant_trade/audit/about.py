"""Who is behind Rigor: the operator's public details on a page of their own.

Only what ``/terminos`` and the landing already publish appears here, each from
its setting and none with a default: the operator's name
(``AuditSettings.operator_name``), the country as the landing words it
(``operator_address_for``), the support e-mail (``operator_contact``) and the
WhatsApp link (``contact_url``). The street address and the telephone stay on the
legal pages, and there is no photo: the founder adds it himself. A detail that is
not set is left out, and with none set the page says so.
"""

from __future__ import annotations

from quant_trade.audit.settings import AuditSettings

#: The page in each language; ``/about`` and ``/pt/about`` forward here (``web``).
ABOUT_PATH: dict[str, str] = {"es": "/acerca", "en": "/en/about", "pt": "/pt/sobre"}
#: Addresses people guess for the page, and the one each forwards to.
ABOUT_ALIASES: dict[str, str] = {"/about": ABOUT_PATH["en"], "/pt/about": ABOUT_PATH["pt"]}

ABOUT_COPY: dict[str, dict[str, str]] = {
    "es": {
        "eyebrow": "Quién está detrás",
        "title": "Quién está detrás de Rigor",
        "lead": (
            "Quién opera Rigor, desde qué país y cómo escribirle: los mismos datos que "
            "publican los términos del servicio y la portada."
        ),
        "details": "Datos del responsable",
        "name": "Responsable del servicio",
        "country": "País",
        "email": "Correo",
        "whatsapp": "WhatsApp",
        "write": "Escribir por WhatsApp",
        "none": "El operador todavía no ha publicado sus datos.",
        "more": "Más información",
        "contact": "Ver los medios de contacto",
        "terms": "Leer los términos del servicio",
    },
    "en": {
        "eyebrow": "Who is behind it",
        "title": "Who is behind Rigor",
        "lead": (
            "Who runs Rigor, from which country and how to write to them: the same details "
            "the terms of service and the home page publish."
        ),
        "details": "Operator details",
        "name": "Service operator",
        "country": "Country",
        "email": "E-mail",
        "whatsapp": "WhatsApp",
        "write": "Write on WhatsApp",
        "none": "The operator has not published its details yet.",
        "more": "More information",
        "contact": "See contact channels",
        "terms": "Read the terms of service",
    },
    "pt": {
        "eyebrow": "Quem está por trás",
        "title": "Quem está por trás da Rigor",
        "lead": (
            "Quem opera a Rigor, de qual país e como escrever: os mesmos dados que os termos "
            "do serviço e a página inicial publicam."
        ),
        "details": "Dados do responsável",
        "name": "Responsável pelo serviço",
        "country": "País",
        "email": "E-mail",
        "whatsapp": "WhatsApp",
        "write": "Escrever pelo WhatsApp",
        "none": "O operador ainda não publicou seus dados.",
        "more": "Mais informações",
        "contact": "Ver os meios de contato",
        "terms": "Ler os termos do serviço",
    },
}


def about_rows(settings: AuditSettings, locale: str = "es") -> tuple[tuple[str, str, str], ...]:
    """``(label, text, link)`` per published detail, in the page's order; ``link`` is
    empty for plain text. Nothing is shown that the operator did not configure."""
    locale = locale if locale in ABOUT_PATH else "es"
    words = ABOUT_COPY[locale]
    email = settings.operator_contact
    rows = [
        (words["name"], settings.operator_name, ""),
        (words["country"], settings.operator_address_for(locale), ""),
        # The same test as the contact page: an address, not some other channel.
        (words["email"], email, f"mailto:{email}" if "@" in email and " " not in email else ""),
        (words["whatsapp"], words["write"] if settings.contact_url else "", settings.contact_url),
    ]
    return tuple(row for row in rows if row[1])


def about_page(settings: AuditSettings, *, locale: str = "es", base_url: str | None = None) -> str:
    """Render with the shared page shell, metadata and language links."""
    from quant_trade.audit.legal import legal_url
    from quant_trade.audit.pages import (
        CONTACT_PATHS,
        _e,
        _home,
        _language_crumbs,
        _page,
        _page_hero,
        _public_meta,
    )
    from quant_trade.audit.seo import BRAND

    locale = locale if locale in ABOUT_PATH else "es"
    words = ABOUT_COPY[locale]
    title = f"{words['eyebrow']} · {BRAND}"
    meta = _public_meta(
        title,
        words["lead"],
        locale,
        ABOUT_PATH[locale],
        settings.base_url if base_url is None else base_url,
    )
    back = {"es": "Volver al inicio", "en": "Back to the home page", "pt": "Voltar ao início"}
    crumbs = f"<a href='{_home(locale)}'>{_e(back[locale])}</a>" + _language_crumbs(
        ABOUT_PATH, locale
    )
    rows = about_rows(settings, locale)
    details = (
        "<table class='kv about-details'>"
        + "".join(
            f"<tr><th scope='row'>{_e(label)}</th><td>"
            + (f"<a href='{_e(link)}' rel='noopener'>{_e(text)}</a>" if link else _e(text))
            + "</td></tr>"
            for label, text, link in rows
        )
        + "</table>"
        if rows
        else f"<p class='muted'>{_e(words['none'])}</p>"
    )
    body = (
        _page_hero(words["eyebrow"], words["title"], words["lead"], crumbs)
        + "<div class='paper page-main'><div class='wrap wrap-mid'>"
        + f"<h2 class='label'>{_e(words['details'])}</h2>"
        + details
        + f"<h2 class='label' style='margin-top:28px'>{_e(words['more'])}</h2>"
        + f"<p><a href='{CONTACT_PATHS[locale]}'>{_e(words['contact'])}</a> · "
        f"<a href='{legal_url('terms', locale)}'>{_e(words['terms'])}</a></p>" + "</div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=ABOUT_PATH, solid_nav=True)


__all__ = ["ABOUT_ALIASES", "ABOUT_COPY", "ABOUT_PATH", "about_page", "about_rows"]
