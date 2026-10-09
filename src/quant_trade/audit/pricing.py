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
            "Cada informe trae el análisis completo y el PDF. El primero es gratis con tu "
            "cuenta; los siguientes son para la versión corregida de tu estrategia, otro robot "
            "antes de pagarlo o tu cuenta del mes siguiente."
        ),
        "detail": "Ver detalle",
        "back": "Volver al inicio",
        "included_title": "Qué incluye cada informe",
        "full": "Informe completo",
        "first_quantity": "Un primer informe completo por cuenta.",
        "first_text": "Completo, con PDF.",
        "single": "{price} por informe adicional.",
        "single_note": "por informe adicional",
        "pack": "Paquete de {n} informes completos: {price}.",
        "pack_name": "Paquete de {n} informes completos",
        "pack_title": "{n} informes",
        "pack_each": "{each} por informe",
        "pack_text": (
            "Audita {n} robots y compáralos lado a lado antes de comprar uno, o sigue tu "
            "cuenta {n} meses."
        ),
        # A pack larger than one comparison (compare.MAX_COMPARED) says less.
        "pack_text_plain": "Audita {n} robots antes de comprar uno o sigue tu cuenta {n} meses.",
        "card_button": "Subir mi archivo",
        "includes_title": "Cada informe completo incluye",
        "evidence": "Etiquetas de evidencia",
        "evidence_text": (
            "Cada cifra dice si se midió en tu archivo, si la declaraste tú (o tu plataforma) "
            "o si no se pudo medir."
        ),
        "public": "Verificación pública y tarjeta",
        "optional": "Opcional: tú decides si publicas la página y compartes la tarjeta.",
        "compare": "Comparación de hasta tres informes",
        "compare_note": "Desde tu cuenta, lado a lado con otros informes completos tuyos.",
        "support": "Soporte por correo",
        "support_note": "El mismo canal de contacto para todos los informes.",
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
        "start_title": "Empieza por el informe gratis",
        "start_text": (
            "El primer informe completo es el mismo informe que los de pago, con PDF. "
            "Necesitas una cuenta y el archivo que exporta tu plataforma."
        ),
        "start_button": "Crear cuenta y pedir mi primer informe",
        "start_text_free": (
            "Ahora todos los informes completos son gratis, con PDF. Solo necesitas el archivo "
            "que exporta tu plataforma."
        ),
        "start_button_free": "Pedir mi informe gratis",
        "start_sample": "Ver el informe de ejemplo",
        "start_guides": "Guías de exportación",
        "start_calculator": "¿Aún sin archivo? La calculadora de suerte es gratis y sin registro.",
    },
    "en": {
        "title": "Full report pricing",
        "summary": (
            "Compare Rigor's first free full report with additional reports. "
            "See what is included, current prices and countries with card payment."
        ),
        "intro": (
            "Every report carries the full analysis and the PDF. The first is free with your "
            "account; the next ones are for the corrected version of your strategy, another "
            "robot before you pay for it or next month's account."
        ),
        "detail": "See details",
        "back": "Back to the home page",
        "included_title": "What each report includes",
        "full": "Full report",
        "first_quantity": "One first full report per account.",
        "first_text": "Full, with the PDF.",
        "single": "{price} per additional report.",
        "single_note": "per additional report",
        "pack": "Pack of {n} full reports: {price}.",
        "pack_name": "Pack of {n} full reports",
        "pack_title": "{n} reports",
        "pack_each": "{each} per report",
        "pack_text": (
            "Audit {n} robots and compare them side by side before buying one, or follow "
            "your account for {n} months."
        ),
        "pack_text_plain": (
            "Audit {n} robots before buying one, or follow your account for {n} months."
        ),
        "card_button": "Upload my file",
        "includes_title": "Every full report includes",
        "evidence": "Evidence labels",
        "evidence_text": (
            "Every figure says whether it was measured in your file, declared by you (or your "
            "platform) or could not be measured."
        ),
        "public": "Public verification and card",
        "optional": "Optional: you decide whether to publish the page and share the card.",
        "compare": "Compare up to three reports",
        "compare_note": "From your account, side by side with other full reports of yours.",
        "support": "E-mail support",
        "support_note": "The same contact channel for every report.",
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
        "start_title": "Start with the free report",
        "start_text": (
            "The first full report is the same report as the paid ones, with the PDF. "
            "You need an account and the file your platform exports."
        ),
        "start_button": "Create an account and get my first report",
        "start_text_free": (
            "All full reports are currently free, with the PDF. You only need the file your "
            "platform exports."
        ),
        "start_button_free": "Get my free report",
        "start_sample": "See the sample report",
        "start_guides": "Export guides",
        "start_calculator": "No file yet? The luck calculator is free and needs no sign-up.",
    },
    "pt": {
        "title": "Preços dos relatórios",
        "summary": (
            "Compare o primeiro relatório completo grátis da Rigor com os relatórios adicionais. "
            "Veja o que incluem, preços e países com cartão."
        ),
        "intro": (
            "Cada relatório traz a análise completa e o PDF. O primeiro é grátis com a sua "
            "conta; os seguintes servem para a versão corrigida da sua estratégia, outro robô "
            "antes de pagar por ele ou a sua conta do mês seguinte."
        ),
        "detail": "Ver detalhes",
        "back": "Voltar ao início",
        "included_title": "O que cada relatório inclui",
        "full": "Relatório completo",
        "first_quantity": "Um primeiro relatório completo por conta.",
        "first_text": "Completo, com PDF.",
        "single": "{price} por relatório adicional.",
        "single_note": "por relatório adicional",
        "pack": "Pacote de {n} relatórios completos: {price}.",
        "pack_name": "Pacote de {n} relatórios completos",
        "pack_title": "{n} relatórios",
        "pack_each": "{each} por relatório",
        "pack_text": (
            "Audite {n} robôs e compare-os lado a lado antes de comprar um, ou acompanhe "
            "sua conta por {n} meses."
        ),
        "pack_text_plain": (
            "Audite {n} robôs antes de comprar um ou acompanhe sua conta por {n} meses."
        ),
        "card_button": "Enviar meu arquivo",
        "includes_title": "Cada relatório completo inclui",
        "evidence": "Rótulos de evidência",
        "evidence_text": (
            "Cada número diz se foi medido no seu arquivo, declarado por você (ou pela sua "
            "plataforma) ou se não pôde ser medido."
        ),
        "public": "Verificação pública e cartão",
        "optional": "Opcional: você decide se publica a página e compartilha o cartão.",
        "compare": "Comparação de até três relatórios",
        "compare_note": "Pela sua conta, lado a lado com outros relatórios completos seus.",
        "support": "Suporte por e-mail",
        "support_note": "O mesmo canal de contato para todos os relatórios.",
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
        "start_title": "Comece pelo relatório grátis",
        "start_text": (
            "O primeiro relatório completo é o mesmo relatório dos pagos, com o PDF. "
            "Você precisa de uma conta e do arquivo que a sua plataforma exporta."
        ),
        "start_button": "Criar conta e pedir o meu primeiro relatório",
        "start_text_free": (
            "Agora todos os relatórios completos são grátis, com o PDF. Você só precisa do "
            "arquivo que a sua plataforma exporta."
        ),
        "start_button_free": "Pedir o meu relatório grátis",
        "start_sample": "Ver o relatório de exemplo",
        "start_guides": "Guias de exportação",
        "start_calculator": "Ainda sem arquivo? A calculadora de sorte é grátis e sem cadastro.",
    },
}


def usd(amount: float) -> str:
    """A price as the pages show it: ``USD 29`` for whole dollars, ``USD 17.35`` with cents."""
    cents = round(amount * 100)
    whole, rest = divmod(cents, 100)
    return f"USD {whole}" if not rest else f"USD {whole}.{rest:02d}"


def offer_text(offer: str, locale: str, *, email_verification: bool = False) -> str:
    """The free-report sentence of :func:`start_cta` for ``offer``, so other pages
    repeat this promise instead of writing a new one.

    ``free`` (free mode): every full report is free and the form needs no account.
    ``welcome``: the first full report is free with an account, and a confirmed
    e-mail when ``email_verification``. Anything else (``paid``): "".
    """
    words = PRICING_COPY[locale if locale in PRICING_COPY else "es"]
    if offer == "free":
        return words["start_text_free"]
    if offer == "welcome":
        text = words["start_text"]
        return f"{text} {words['email_note']}" if email_verification else text
    return ""


def start_cta(settings: AuditSettings, locale: str) -> str:
    """The page's closing call: the free report first, as the configuration offers it.

    Free mode: every full report is free and the form needs no account. Otherwise,
    with the welcome report on, the first full report is free with an account (and
    a confirmed e-mail when that is required). Without either, the articles' call.
    """
    # Lazy imports, as in ``pricing_page``: pages imports this module.
    from quant_trade.audit.accounts import WELCOME_FULL_REPORT
    from quant_trade.audit.calculator import calculator_url
    from quant_trade.audit.guides import guides_index_url
    from quant_trade.audit.pages import SAMPLE_PAGE_PATHS, _articles_cta, _e, audit_path
    from quant_trade.audit.theme import icon

    locale = locale if locale in PRICING_COPY else "es"
    words = PRICING_COPY[locale]
    if settings.free_mode:
        offer, button = "free", words["start_button_free"]
    elif WELCOME_FULL_REPORT:
        offer, button = "welcome", words["start_button"]
    else:
        return _articles_cta(locale)
    text = offer_text(offer, locale, email_verification=settings.email_verification_required)
    return (
        f"<section class='article-cta'><h2>{_e(words['start_title'])}</h2><p>{_e(text)}</p>"
        "<div class='back-row'>"
        f"<a class='btn btn-dark' href='{_e(audit_path(locale))}'>{_e(button)}"
        f"<span class='go'>{icon('arrow')}</span></a>"
        f"<a class='link-more' href='{_e(SAMPLE_PAGE_PATHS[locale])}'>"
        f"{_e(words['start_sample'])}{icon('arrow')}</a>"
        f"<a class='link-more' href='{_e(guides_index_url(locale))}'>"
        f"{_e(words['start_guides'])}{icon('arrow')}</a></div>"
        f"<p class='start-calculator' style='margin-top:12px'>"
        f"<a href='{_e(calculator_url(locale))}'>{_e(words['start_calculator'])}</a></p>"
        "</section>"
    )


def pricing_page(
    settings: AuditSettings, *, locale: str = "es", base_url: str | None = None
) -> str:
    """An indexable description of existing reports, without a checkout action."""
    # Lazy imports let seo/pages use PRICING_PATH without an import cycle.
    from quant_trade.audit.compare import MAX_COMPARED
    from quant_trade.audit.institutional import REVIEW_PATHS
    from quant_trade.audit.pages import (
        _COPY,
        _UI,
        CONTACT_PATHS,
        _e,
        _home,
        _language_crumbs,
        _page,
        _page_hero,
        _public_meta,
        audit_path,
        card_markets_line,
    )
    from quant_trade.audit.report import DIMENSION_TITLES
    from quant_trade.audit.seo import BRAND, _json_ld
    from quant_trade.audit.theme import icon
    from quant_trade.audit.verdict import DIMENSION_ORDER

    locale = locale if locale in PRICING_PATH else "es"
    words = PRICING_COPY[locale]
    landing = _COPY[locale]
    ui = _UI[locale]
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
        prices = f"<p>{_e(words['single'].format(price=usd(settings.price_usd)))}</p>"
        if settings.pack_price_usd:
            offers.append((words["pack_name"].format(n=PACK_CREDITS), settings.pack_price_usd))
            pack = words["pack"].format(n=PACK_CREDITS, price=usd(settings.pack_price_usd))
            prices += f"<p>{_e(pack)}</p>"
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
    start = audit_path(locale)
    if settings.free_mode:
        cards = [(words["all_reports"], ui["plan_free_amount"], "", words["free"], "")]
        button = words["start_button_free"]
        intro = words["free"]
        note = f"<p>{_e(landing['price_free_mode'])}</p>"
    else:
        first = words["first_text"]
        if settings.email_verification_required:
            first += " " + words["email_note"]
        cards = [
            (
                landing["price_free_title"],
                ui["plan_free_amount"],
                words["first_quantity"],
                first,
                ui["cta_full"],
            ),
            (
                words["full"],
                usd(settings.price_usd),
                words["single_note"],
                landing["price_full"],
                "",
            ),
        ]
        if settings.pack_price_usd:
            each = usd(settings.pack_price_usd / PACK_CREDITS)
            cards.append(
                (
                    words["pack_title"].format(n=PACK_CREDITS),
                    usd(settings.pack_price_usd),
                    words["pack_each"].format(each=each),
                    # "Compare them side by side" only while one comparison holds the pack.
                    words[
                        "pack_text" if PACK_CREDITS <= MAX_COMPARED else "pack_text_plain"
                    ].format(n=PACK_CREDITS),
                    "",
                )
            )
        button = words["card_button"]
        intro = words["intro"]
        note = ""
    # Every card's button opens the upload page: payment happens from a report,
    # never from this page (see the module docstring).
    plans = "".join(
        "<div class='plan-card'>"
        f"<h2>{_e(name)}</h2><p class='plan-price'>{_e(amount)}</p>"
        + (f"<p class='plan-note'>{_e(small)}</p>" if small else "")
        + f"<p>{_e(text)}</p>"
        f"<a class='btn btn-dark' href='{_e(start)}'>{_e(label or button)}</a></div>"
        for name, amount, small, text, label in cards
    )
    included = [_e(DIMENSION_TITLES[locale][name]) for name in DIMENSION_ORDER] + [
        f"<b>{_e(words['evidence'])}</b> {_e(words['evidence_text'])}",
        "PDF",
        f"<b>{_e(words['public'])}</b> {_e(words['optional'])}",
        f"<b>{_e(words['compare'])}</b> {_e(words['compare_note'])}",
        f"<b>{_e(words['support'])}</b> {support} {contact}",
    ]
    items = "".join(f"<li>{icon('check')}<span>{item}</span></li>" for item in included)
    markets = (
        card_markets_line(tuple(settings.approved_markets), locale)
        if settings.card_public
        else words["no_card"]
    )
    payment = (
        f"<p>{_e(words['free'])}</p>"
        if settings.free_mode
        else f"{prices}<p>{_e(markets)}</p><p>{_e(words['one_off'])}</p>"
    )
    if settings.access_codes_enabled:
        payment += f"<p>{_e(landing['pay_code'])} {contact}</p>"
    crumbs = f"<a href='{_home(locale)}'>{_e(words['back'])}</a>" + _language_crumbs(
        PRICING_PATH, locale
    )
    body = (
        _page_hero(words["title"], words["title"], intro, crumbs)
        + "<div class='paper page-main'><div class='wrap'>"
        f"<section class='rsec'>{note}<div class='plan-cards'>{plans}</div></section>"
        f"<section class='rsec'><h2>{_e(words['includes_title'])}</h2>"
        f"<ul class='checks plan-includes'>{items}</ul><p>{_e(words['data_note'])}</p></section>"
        f"<section class='rsec'><h2>{_e(words['payment'])}</h2>{payment}"
        f"<p><a href='{REVIEW_PATHS[locale]}'>{_e(words['institutional'])}</a></p></section>"
        f"<section class='rsec'><h2>{_e(words['limits'])}</h2>"
        f"<p>{_e(landing['not'])}</p></section>" + start_cta(settings, locale) + "</div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=PRICING_PATH, solid_nav=True)
