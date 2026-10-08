"""Public pricing: the same full report, with quantities and prices from settings.

This page describes existing entitlements only; it never enables a payment or
grants a report. Missing evidence still limits what a full report can measure.
"""

from __future__ import annotations

from typing import Any

from quant_trade.audit.settings import PACK_CREDITS, AuditSettings

PRICING_PATH: dict[str, str] = {"es": "/precios", "en": "/en/pricing", "pt": "/pt/precos"}
PRICING_COPY: dict[str, dict[str, str]] = {
    "es": {
        "title": "Precios de los informes",
        "summary": (
            "Compara el primer informe completo gratis de Rigor con los informes adicionales. "
            "Consulta lo que incluyen, precios y países con tarjeta."
        ),
        "intro": (
            "El primer informe gratis es el mismo informe completo. Lo que cambia es cuántos "
            "informes puedes obtener, no el análisis incluido."
        ),
        "detail": "Ver detalle",
        "back": "Volver al inicio",
        "included_title": "Qué incluye cada informe",
        "feature": "Contenido",
        "first": "Primer informe completo, gratis al crear cuenta",
        "full": "Informe completo",
        "included": "Incluido",
        "quantity": "Cuántos informes",
        "first_quantity": "DECLARED · Un primer informe completo por cuenta.",
        "single": "DECLARED · USD {price:.2f} por informe adicional.",
        "pack": "DECLARED · Paquete de {n} informes completos: USD {price:.2f}.",
        "pack_name": "Paquete de {n} informes completos",
        "evidence": "Etiquetas de evidencia",
        "public": "Verificación pública y tarjeta",
        "optional": "Opcional: tú decides si publicas la página y compartes la tarjeta.",
        "compare": "Comparación de dos informes",
        "compare_note": "Incluida; requiere dos informes completos.",
        "support": "Soporte por correo",
        "support_note": "El mismo canal de contacto para ambos informes.",
        "no_email": "El operador aún no ha publicado un correo de soporte.",
        "contact": "Ver los medios de contacto",
        "data_note": (
            "Las seis dimensiones se evalúan según los datos aportados. Lo que no puede "
            "medirse se indica como NOT_MEASURED; pagar no añade evidencia al archivo."
        ),
        "email_note": "Para el primer informe gratis debes confirmar el correo de tu cuenta.",
        "free": "Ahora todos los informes completos son gratis.",
        "all_reports": "Todos los informes completos",
        "payment": "Cómo se paga",
        "no_card": "Actualmente el pago público con tarjeta no está disponible.",
        "one_off": "Los pagos son únicos: no hay suscripción ni cargos recurrentes.",
        "institutional": "Para gestoras: solicitar una revisión institucional",
        "limits": "Lo que Rigor no hace",
    },
    "en": {
        "title": "Full report pricing",
        "summary": (
            "Compare Rigor's first free full report with additional reports. "
            "See what is included, current prices and countries with card payment."
        ),
        "intro": (
            "The first free report is the same full report. What changes is how many "
            "reports you can obtain, not the analysis included."
        ),
        "detail": "See details",
        "back": "Back to the home page",
        "included_title": "What each report includes",
        "feature": "Content",
        "first": "First full report, free when you create an account",
        "full": "Full report",
        "included": "Included",
        "quantity": "How many reports",
        "first_quantity": "DECLARED · One first full report per account.",
        "single": "DECLARED · USD {price:.2f} per additional report.",
        "pack": "DECLARED · Pack of {n} full reports: USD {price:.2f}.",
        "pack_name": "Pack of {n} full reports",
        "evidence": "Evidence labels",
        "public": "Public verification and card",
        "optional": "Optional: you decide whether to publish the page and share the card.",
        "compare": "Compare two reports",
        "compare_note": "Included; requires two full reports.",
        "support": "E-mail support",
        "support_note": "The same contact channel for both reports.",
        "no_email": "The operator has not published a support e-mail yet.",
        "contact": "See contact channels",
        "data_note": (
            "The six dimensions are assessed from the supplied data. Anything that cannot "
            "be measured is marked NOT_MEASURED; payment adds no evidence to the file."
        ),
        "email_note": "For the first free report, you must confirm your account e-mail.",
        "free": "All full reports are currently free.",
        "all_reports": "All full reports",
        "payment": "How to pay",
        "no_card": "Public card payment is currently unavailable.",
        "one_off": "Payments are one-off: there is no subscription or recurring charge.",
        "institutional": "For asset managers: request an institutional review",
        "limits": "What Rigor does not do",
    },
    "pt": {
        "title": "Preços dos relatórios",
        "summary": (
            "Compare o primeiro relatório completo grátis da Rigor com os relatórios adicionais. "
            "Veja o que incluem, preços e países com cartão."
        ),
        "intro": (
            "O primeiro relatório grátis é o mesmo relatório completo. O que muda é quantos "
            "relatórios você pode obter, não a análise incluída."
        ),
        "detail": "Ver detalhes",
        "back": "Voltar ao início",
        "included_title": "O que cada relatório inclui",
        "feature": "Conteúdo",
        "first": "Primeiro relatório completo, grátis ao criar uma conta",
        "full": "Relatório completo",
        "included": "Incluído",
        "quantity": "Quantos relatórios",
        "first_quantity": "DECLARED · Um primeiro relatório completo por conta.",
        "single": "DECLARED · USD {price:.2f} por relatório adicional.",
        "pack": "DECLARED · Pacote de {n} relatórios completos: USD {price:.2f}.",
        "pack_name": "Pacote de {n} relatórios completos",
        "evidence": "Rótulos de evidência",
        "public": "Verificação pública e cartão",
        "optional": "Opcional: você decide se publica a página e compartilha o cartão.",
        "compare": "Comparação de dois relatórios",
        "compare_note": "Incluída; requer dois relatórios completos.",
        "support": "Suporte por e-mail",
        "support_note": "O mesmo canal de contato para ambos os relatórios.",
        "no_email": "O operador ainda não publicou um e-mail de suporte.",
        "contact": "Ver os meios de contato",
        "data_note": (
            "As seis dimensões são avaliadas conforme os dados enviados. O que não pode "
            "ser medido aparece como NOT_MEASURED; pagar não acrescenta evidência ao arquivo."
        ),
        "email_note": "Para o primeiro relatório grátis, é preciso confirmar o e-mail da conta.",
        "free": "Agora todos os relatórios completos são grátis.",
        "all_reports": "Todos os relatórios completos",
        "payment": "Como pagar",
        "no_card": "O pagamento público com cartão não está disponível no momento.",
        "one_off": "Os pagamentos são únicos: não há assinatura nem cobranças recorrentes.",
        "institutional": "Para gestoras: solicitar uma revisão institucional",
        "limits": "O que a Rigor não faz",
    },
}


def pricing_page(
    settings: AuditSettings, *, locale: str = "es", base_url: str | None = None
) -> str:
    """An indexable description of existing reports, without a checkout action."""
    # Lazy imports let seo/pages use PRICING_PATH without an import cycle.
    from quant_trade.audit.institutional import REVIEW_PATHS
    from quant_trade.audit.pages import (
        _COPY,
        CONTACT_PATHS,
        _articles_cta,
        _e,
        _home,
        _language_crumbs,
        _page,
        _page_hero,
        _public_meta,
        card_markets_line,
    )
    from quant_trade.audit.report import DIMENSION_TITLES
    from quant_trade.audit.seo import BRAND, _json_ld
    from quant_trade.audit.verdict import DIMENSION_ORDER

    locale = locale if locale in PRICING_PATH else "es"
    words = PRICING_COPY[locale]
    landing = _COPY[locale]
    base = (settings.base_url if base_url is None else base_url).rstrip("/")
    url = base + PRICING_PATH[locale]
    title = f"{words['title']} · {BRAND}"
    meta = _public_meta(title, words["summary"], locale, PRICING_PATH[locale], base)
    product: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": f"{BRAND} · {words['full']}",
        "description": words["free"] if settings.free_mode else words["intro"],
        "url": url,
    }
    prices = ""
    if not settings.free_mode:
        offers = [(words["full"], settings.price_usd)]
        prices = f"<p>{_e(words['single'].format(price=settings.price_usd))}</p>"
        if settings.pack_price_usd:
            offers.append((words["pack_name"].format(n=PACK_CREDITS), settings.pack_price_usd))
            prices += (
                f"<p>{_e(words['pack'].format(n=PACK_CREDITS, price=settings.pack_price_usd))}</p>"
            )
        product["offers"] = [
            {
                "@type": "Offer",
                "name": name,
                "price": f"{price:.2f}",
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock",
                "url": url,
            }
            for name, price in offers
        ]
    meta += _json_ld(product)

    email_available = "@" in settings.operator_contact and " " not in settings.operator_contact
    contact = f"<a href='{CONTACT_PATHS[locale]}'>{_e(words['contact'])}</a>"
    support = _e(words["support_note"] if email_available else words["no_email"])
    features = [
        (DIMENSION_TITLES[locale][name], _e(words["included"])) for name in DIMENSION_ORDER
    ] + [
        (words["evidence"], "MEASURED · DECLARED · NOT_MEASURED"),
        ("PDF", _e(words["included"])),
        (words["public"], _e(words["optional"])),
        (words["compare"], _e(words["compare_note"])),
        (words["support"], f"{support} {contact}"),
    ]
    # Two report columns in paid mode; one shared column when everything is free.
    columns = 1 if settings.free_mode else 2
    rows = "".join(
        f"<tr><th scope='row'>{_e(label)}</th>" + f"<td>{value}</td>" * columns + "</tr>"
        for label, value in features
    )
    if settings.free_mode:
        plan_headers = f"<th scope='col'>{_e(words['all_reports'])}</th>"
        intro = words["free"]
        note = f"<p>{_e(landing['price_free_mode'])}</p>"
    else:
        plan_headers = (
            f"<th scope='col'>{_e(words['first'])}</th><th scope='col'>{_e(words['full'])}</th>"
        )
        rows = (
            f"<tr><th scope='row'>{_e(words['quantity'])}</th>"
            f"<td>{_e(words['first_quantity'])}</td><td>{prices}</td></tr>"
        ) + rows
        intro = words["intro"]
        note = f"<p>{_e(words['email_note'])}</p>" if settings.email_verification_required else ""
    markets = (
        "DECLARED · " + card_markets_line(tuple(settings.approved_markets), locale)
        if settings.card_public
        else words["no_card"]
    )
    payment = (
        f"<p>{_e(words['free'])}</p>"
        if settings.free_mode
        else f"<p>{_e(markets)}</p><p>{_e(words['one_off'])}</p>"
    )
    if settings.access_codes_enabled:
        payment += f"<p>{_e(landing['pay_code'])} {contact}</p>"
    crumbs = f"<a href='{_home(locale)}'>{_e(words['back'])}</a>" + _language_crumbs(
        PRICING_PATH, locale
    )
    body = (
        _page_hero(words["title"], words["title"], intro, crumbs)
        + "<div class='paper page-main'><div class='wrap'>"
        f"<section class='rsec'><h2>{_e(words['included_title'])}</h2>{note}"
        "<div style='overflow-x:auto'><table>"
        f"<thead><tr><th scope='col'>{_e(words['feature'])}</th>{plan_headers}</tr></thead>"
        f"<tbody>{rows}</tbody></table></div><p>{_e(words['data_note'])}</p></section>"
        f"<section class='rsec'><h2>{_e(words['payment'])}</h2>{payment}"
        f"<p><a href='{REVIEW_PATHS[locale]}'>{_e(words['institutional'])}</a></p></section>"
        f"<section class='rsec'><h2>{_e(words['limits'])}</h2>"
        f"<p>{_e(landing['not'])}</p></section>" + _articles_cta(locale) + "</div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=PRICING_PATH, solid_nav=True)
