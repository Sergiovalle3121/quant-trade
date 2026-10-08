"""Public questions, derived from existing copy and runtime configuration.

This module describes existing behavior only. In particular, it neither enables
payments nor performs retention, publication, account or contact operations.
"""

from __future__ import annotations

from quant_trade.audit.settings import AuditSettings

FAQ_PATH: dict[str, str] = {"es": "/preguntas", "en": "/en/faq", "pt": "/pt/perguntas"}
FAQ_COPY: dict[str, dict[str, str]] = {
    "es": {
        "title": "Preguntas frecuentes",
        "summary": (
            "Respuestas sobre el informe gratis de Rigor, precios, archivos, evidencia, "
            "privacidad y contacto."
        ),
        "intro": (
            "Qué recibes al subir tu archivo, cómo se lee la evidencia y qué ocurre con tus datos."
        ),
        "back": "Volver al inicio",
        "privacy": "Leer la política de privacidad",
        "contact": "Ver los medios de contacto",
    },
    "en": {
        "title": "Frequently asked questions",
        "summary": (
            "Answers about Rigor's free report, prices, files, evidence, privacy and contact."
        ),
        "intro": (
            "What you receive when you upload a file, how to read the evidence "
            "and what happens to your data."
        ),
        "back": "Back to the home page",
        "privacy": "Read the privacy policy",
        "contact": "See contact channels",
    },
    "pt": {
        "title": "Perguntas frequentes",
        "summary": (
            "Respostas sobre o relatório grátis da Rigor, preços, arquivos, evidência, "
            "privacidade e contato."
        ),
        "intro": (
            "O que você recebe ao enviar um arquivo, como ler a evidência "
            "e o que acontece com seus dados."
        ),
        "back": "Voltar ao início",
        "privacy": "Ler a política de privacidade",
        "contact": "Ver os meios de contato",
    },
}

# Every answer cites the existing source of its behavior. Placeholders are
# resolved at request time, so prices, countries and retention cannot go stale.
_QUESTIONS: tuple[dict[str, tuple[str, str]], ...] = (
    # Sources: pages._COPY['faq'], pages._UI pricing, legal._price_es/_price_en/
    # _price_pt; settings.AuditSettings.free_mode and price_usd.
    {
        "es": (
            "¿Cuánto cuesta y qué incluye el informe gratis?",
            "Con tu cuenta, el primer informe completo es gratis. Incluye las cifras, "
            "gráficas, banderas rojas, pruebas de estrés, riesgo, simulador de retos y PDF, "
            "según los datos aportados. La vista previa gratuita muestra la clase, las "
            "gráficas, las banderas rojas y las dimensiones. {price}{email}",
        ),
        "en": (
            "What does it cost and what does the free report include?",
            "With an account, your first full report is free. It includes figures, charts, "
            "red flags, stress tests, risk, the challenge simulator and PDF, depending on "
            "the supplied data. The free preview shows the class, charts, red flags and "
            "dimensions. {price}{email}",
        ),
        "pt": (
            "Quanto custa e o que inclui o relatório grátis?",
            "Com uma conta, seu primeiro relatório completo é grátis. Inclui números, "
            "gráficos, alertas, testes de estresse, risco, simulador de desafios e PDF, "
            "conforme os dados enviados. A prévia gratuita mostra a classe, os gráficos, "
            "os alertas e as dimensões. {price}{email}",
        ),
    },
    # Sources: settings.AuditSettings.card_public/approved_markets, populated by
    # AUDIT_APPROVED_MARKETS; pages.card_markets_line supplies the country names.
    {
        "es": ("¿Desde qué países se puede pagar con tarjeta?", "{markets}"),
        "en": ("Which countries can pay by card?", "{markets}"),
        "pt": ("De quais países é possível pagar com cartão?", "{markets}"),
    },
    # Sources: pages._COPY['report_short'/'report_help'/'faq'], portuguese.COPY_PT;
    # settings.AuditSettings.max_upload_bytes controls the configured size limit.
    {
        "es": (
            "¿Qué formatos acepta Rigor?",
            "Informes HTML de MetaTrader, listas de operaciones CSV o XLSX de TradingView, "
            "historiales CSV o Excel de cuentas y series de equity o retornos. También "
            "estados de cuenta PDF con tabla de operaciones: revisas sus columnas antes "
            "de medir. DECLARED · Límite por archivo: {upload_mb} MB. Las guías explican "
            "cómo exportar desde cada plataforma.",
        ),
        "en": (
            "Which file formats does Rigor accept?",
            "MetaTrader HTML reports, TradingView CSV or XLSX trade lists, CSV or Excel "
            "account histories, and equity or return series. PDF statements with a trade "
            "table also work: you review their columns before measuring. DECLARED · "
            "Limit per file: {upload_mb} MB. The guides explain how to export from each platform.",
        ),
        "pt": (
            "Quais formatos a Rigor aceita?",
            "Relatórios HTML do MetaTrader, listas de operações CSV ou XLSX do TradingView, "
            "históricos de contas em CSV ou Excel e séries de equity ou retornos. Também "
            "extratos PDF com tabela de operações: você revisa as colunas antes de medir. "
            "DECLARED · Limite por arquivo: {upload_mb} MB. Os guias explicam como "
            "exportar de cada plataforma.",
        ),
    },
    # Sources: legal.terms_text service scope and pages.TRUST_COPY: no broker access,
    # execution, strategies or signals; pages._COPY['faq'] rules out forecasts.
    {
        "es": (
            "¿Qué no hace Rigor?",
            "No vende bots ni señales, no ejecuta órdenes, no se conecta a tu bróker ni "
            "pide sus claves. Analiza los archivos que aportas; no es asesoría de inversión "
            "ni una predicción de resultados o del desenlace de un reto.",
        ),
        "en": (
            "What does Rigor not do?",
            "It sells no bots or signals, places no orders, and neither connects to your "
            "broker nor asks for broker keys. It analyses the files you supply; it is not "
            "investment advice or a forecast of results or a challenge outcome.",
        ),
        "pt": (
            "O que a Rigor não faz?",
            "Não vende robôs nem sinais, não executa ordens, não se conecta à sua corretora "
            "nem pede suas chaves. Analisa os arquivos que você envia; não é assessoria "
            "de investimento nem previsão de resultados ou do desfecho de um desafio.",
        ),
    },
    # Sources: pages._COPY['faq'], pages._UI['evidence'], report.evidence_label.
    {
        "es": (
            "¿Qué significan Medido, Declarado y No medido?",
            "Medido se calculó desde tu archivo. Declarado lo "
            "indicaste tú o tu plataforma y no se pudo comprobar. No medido "
            "significa que faltan datos para calcularlo. Una cuenta matemática no convierte "
            "una declaración en una medición del historial.",
        ),
        "en": (
            "What do Measured, Declared and Not measured mean?",
            "Measured was computed from your file. Declared came "
            "from you or your platform and could not be checked. Not measured "
            "means that data needed for the calculation is missing. "
            "Arithmetic does not turn a declaration into a measured track record.",
        ),
        "pt": (
            "O que significam Medido, Declarado e Não medido?",
            "Medido foi calculado a partir do seu arquivo. Declarado "
            "veio de você ou da plataforma e não pôde ser conferido. Não medido "
            "indica que faltam dados para o cálculo. Uma conta matemática "
            "não transforma uma declaração em uma medição do histórico.",
        ),
    },
    # Sources: method.py dimensions, calculator.COPY['years_needed'/'beats']
    # and articles' deflated-Sharpe history-length explanation. No new threshold.
    {
        "es": (
            "¿Cuánto historial hace falta?",
            "La longitud necesaria depende del Sharpe, de cuántas configuraciones probaste "
            "y de la distribución de los retornos. La calculadora estima una duración "
            "bajo sus supuestos; eso no sustituye revisar costos, datos fuera de muestra "
            "y dependencia entre variantes. Sube el historial completo: lo que no pueda "
            "calcularse se marca NOT_MEASURED.",
        ),
        "en": (
            "How much history is needed?",
            "The required length depends on the Sharpe, how many configurations you tried "
            "and the distribution of returns. The calculator estimates a duration under "
            "its assumptions; that does not replace checking costs, out-of-sample data "
            "and dependence between variants. Upload the full history: anything that "
            "cannot be computed is marked NOT_MEASURED.",
        ),
        "pt": (
            "Quanto histórico é necessário?",
            "O período necessário depende do Sharpe, de quantas configurações você testou "
            "e da distribuição dos retornos. A calculadora estima uma duração sob suas "
            "suposições; isso não substitui revisar custos, dados fora da amostra e "
            "dependência entre variantes. Envie o histórico completo: o que não puder "
            "ser calculado recebe a marca NOT_MEASURED.",
        ),
    },
    # Sources: calculator.COPY['trials_help']; method.py data-mining dimension
    # uses the largest declared count, optimisation count and supplied variants.
    {
        "es": (
            "¿Cómo se cuentan las configuraciones probadas?",
            "Cuenta todas las versiones que probaste antes de elegir, también las que "
            "descartaste. Rigor usa el mayor conteo entre lo declarado, el XML de "
            "optimización aportado y las variantes enviadas. El Sharpe deflactado usa ese "
            "número para descontar la selección entre muchos intentos; no reconstruye "
            "búsquedas que no aportaste.",
        ),
        "en": (
            "How are tested configurations counted?",
            "Count every version tried before choosing, including discarded ones. Rigor "
            "uses the largest count from your declaration, the supplied optimisation "
            "XML and the uploaded variants. The deflated Sharpe uses that number to "
            "account for selection across many trials; it cannot reconstruct searches "
            "you did not supply.",
        ),
        "pt": (
            "Como se contam as configurações testadas?",
            "Conte todas as versões testadas antes da escolha, inclusive as descartadas. "
            "A Rigor usa a maior contagem entre a declaração, o XML de otimização e as "
            "variantes enviadas. O Sharpe deflacionado usa esse número para descontar a "
            "seleção entre muitas tentativas; não reconstrói buscas que você não enviou.",
        ),
    },
    # Sources: legal.privacy_text retention sections, including the first-free-report
    # exception and the public allow-list retained after a purge, in every language.
    {
        "es": (
            "¿Qué ocurre con mis archivos y cuánto tiempo se guardan?",
            "Tus archivos no se publican. DECLARED · Las auditorías no pagadas se "
            "eliminan a los {retention} días; quedan datos mínimos del registro. Las "
            "pagadas y el primer informe completo gratis se conservan hasta que los "
            "borres con tu cuenta o solicites su borrado. Una página de verificación "
            "que publicaste conserva solo sus campos públicos hasta que la retires. "
            "La política de privacidad detalla los datos y sus plazos.",
        ),
        "en": (
            "What happens to my files and how long are they kept?",
            "Your files are not published. DECLARED · Unpaid audits are deleted after "
            "{retention} days; minimal registry data remains. Paid audits and the first "
            "free full report are kept until you delete them with your account or "
            "request deletion. A verification page you published keeps only its public "
            "fields until you withdraw it. The privacy policy details the data and "
            "retention periods.",
        ),
        "pt": (
            "O que acontece com meus arquivos e por quanto tempo são guardados?",
            "Seus arquivos não são publicados. DECLARED · Auditorias não pagas são "
            "excluídas após {retention} dias; restam dados mínimos do registro. As pagas "
            "e o primeiro relatório completo grátis ficam até você excluí-los com a "
            "conta ou pedir sua exclusão. Uma página de verificação que você publicou "
            "mantém apenas seus campos públicos até ser retirada. A política de "
            "privacidade detalha os dados e os prazos.",
        ),
    },
    # Sources: web.publish/publish_locked, legal.terms_text badge section,
    # legal.privacy_text publication retention and pages.verification_page allow-list.
    {
        "es": (
            "¿Cómo se publica una página de verificación?",
            "Desde tu informe completo puedes elegir publicar su página de verificación "
            "y retirarla después. Muestra la clase, las dimensiones, las huellas de los "
            "archivos, las fechas y un aviso fijo; nunca tus archivos, operaciones, "
            "descripción ni enlace privado. El sello enlaza a esa página y no es una "
            "promesa de resultados.",
        ),
        "en": (
            "How do I publish a verification page?",
            "From your full report you can choose to publish its verification page and "
            "withdraw it later. It shows the class, dimensions, file hashes, dates and "
            "a fixed notice; never your files, trades, description or private link. "
            "The badge links to that page and is not a promise of results.",
        ),
        "pt": (
            "Como publico uma página de verificação?",
            "No relatório completo você pode escolher publicar a página de verificação "
            "e retirá-la depois. Ela mostra a classe, as dimensões, as impressões digitais "
            "dos arquivos, as datas e um aviso fixo; nunca arquivos, operações, descrição "
            "ou link privado. O selo aponta para essa página e não é uma promessa de resultados.",
        ),
    },
    # Source: pages.CONTACT_COPY and contact_page, whose public channels come
    # from settings.operator_contact/contact_url and have no invented default.
    {
        "es": (
            "¿Cómo contacto con Rigor?",
            "{contact} Si consultas sobre un informe, incluye su identificador. No envíes "
            "contraseñas, claves de recuperación ni datos de tarjeta. Puedes consultar "
            "los medios publicados en la página de contacto.",
        ),
        "en": (
            "How can I contact Rigor?",
            "{contact} For a report question, include its id. Do not send passwords, "
            "recovery keys or card details. You can find the published channels on the "
            "contact page.",
        ),
        "pt": (
            "Como entro em contato com a Rigor?",
            "{contact} Se a dúvida for sobre um relatório, inclua seu identificador. "
            "Não envie senhas, chaves de recuperação nem dados de cartão. Os meios "
            "publicados estão na página de contato.",
        ),
    },
)


def faq_items(settings: AuditSettings, locale: str = "es") -> tuple[tuple[str, str], ...]:
    """The same localized answers feed the visible page and FAQPage JSON-LD."""
    # Lazy imports keep FAQ_PATH usable by seo without a pages/seo cycle.
    from quant_trade.audit.pages import CONTACT_COPY, card_markets_line
    from quant_trade.audit.report import localize_tags

    locale = locale if locale in FAQ_PATH else "es"
    if settings.free_mode:
        price = {
            "es": "Ahora el servicio es gratuito y entrega el informe completo con marca de agua.",
            "en": "The service is currently free and delivers the full report with a watermark.",
            "pt": "Agora o serviço é gratuito e entrega o relatório completo com marca d'água.",
        }[locale]
    else:
        price = {
            "es": "DECLARED · Un informe completo adicional cuesta USD {amount:.2f}.",
            "en": "DECLARED · An additional full report costs USD {amount:.2f}.",
            "pt": "DECLARED · Um relatório completo adicional custa USD {amount:.2f}.",
        }[locale].format(amount=settings.price_usd)
    email = ""
    if settings.email_verification_required and not settings.free_mode:
        email = {
            "es": " Para el primer informe gratis debes confirmar el correo de tu cuenta.",
            "en": " For the first free report, you must confirm your account e-mail.",
            "pt": " Para o primeiro relatório grátis, é preciso confirmar o e-mail da conta.",
        }[locale]
    if settings.card_public:
        markets = "DECLARED · " + card_markets_line(tuple(settings.approved_markets), locale)
        markets += {
            "es": " Se usa el país de facturación, no tu idioma ni tu dirección de red.",
            "en": " This uses the billing country, not your language or network address.",
            "pt": " Vale o país de cobrança, não o idioma nem o endereço de rede.",
        }[locale]
    else:
        markets = {
            "es": "Actualmente el pago público con tarjeta no está disponible.",
            "en": "Public card payment is currently unavailable.",
            "pt": "O pagamento público com cartão não está disponível no momento.",
        }[locale]
    channels = [value for value in (settings.operator_contact, settings.contact_url) if value]
    contact = (
        {"es": "Medios de contacto: ", "en": "Contact channels: ", "pt": "Meios de contato: "}[
            locale
        ]
        + "; ".join(channels)
        + "."
        if channels
        else CONTACT_COPY[locale]["none"]
    )
    values = {
        "price": price,
        "email": email,
        "markets": markets,
        "upload_mb": f"{settings.max_upload_bytes / (1024 * 1024):g}",
        "retention": settings.retention_days,
        "contact": contact,
    }
    # _page localizes evidence tags in text nodes. Apply that same transformation
    # here so the structured answers are exactly the wording a reader sees.
    return tuple(
        (item[locale][0], localize_tags(item[locale][1].format(**values), locale))
        for item in _QUESTIONS
    )


def faq_page(settings: AuditSettings, *, locale: str = "es", base_url: str | None = None) -> str:
    """Render with the existing page shell, metadata, CTA and JSON-LD generator."""
    from quant_trade.audit.legal import legal_url
    from quant_trade.audit.pages import (
        CONTACT_PATHS,
        _articles_cta,
        _e,
        _home,
        _language_crumbs,
        _page,
        _page_hero,
        _public_meta,
    )
    from quant_trade.audit.seo import BRAND, faq_structured_data

    locale = locale if locale in FAQ_PATH else "es"
    words = FAQ_COPY[locale]
    title = f"{words['title']} · {BRAND}"
    pairs = faq_items(settings, locale)
    meta = _public_meta(
        title,
        words["summary"],
        locale,
        FAQ_PATH[locale],
        settings.base_url if base_url is None else base_url,
    )
    meta += faq_structured_data(pairs)
    crumbs = f"<a href='{_home(locale)}'>{_e(words['back'])}</a>" + _language_crumbs(
        FAQ_PATH, locale
    )
    answers = "".join(
        f"<details><summary>{_e(question)}</summary><p>{_e(answer)}</p></details>"
        for question, answer in pairs
    )
    body = (
        _page_hero(words["title"], words["title"], words["intro"], crumbs)
        + "<div class='paper page-main'><div class='wrap wrap-mid'>"
        f"<div class='faq'>{answers}</div>"
        f"<p><a href='{legal_url('privacy', locale)}'>{_e(words['privacy'])}</a> · "
        f"<a href='{CONTACT_PATHS[locale]}'>{_e(words['contact'])}</a></p>"
        + _articles_cta(locale)
        + "</div></div>"
    )
    return _page(title, locale, body, meta_html=meta, alternates=FAQ_PATH, solid_nav=True)
