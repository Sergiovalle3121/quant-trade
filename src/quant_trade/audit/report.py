"""Render an ``AuditResult`` as JSON and as a self-contained HTML page.

The JSON is the record: canonical, NaN-free, hashed, and the thing a client
can hand to a third party together with the file digests to prove what was
audited. The HTML is the same numbers with labels, an evidence badge on every
value, and a fixed disclaimer. The client's free-text description never
reaches the HTML (only its length and hash do); it lives in the JSON, where
it is theirs.

Both renderings pass the profit-claim guard before they are returned. A
report that fails the guard is a bug in this module, not a report.
"""

from __future__ import annotations

import html
import math
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from quant_trade.audit import charts, report_pt
from quant_trade.audit.account import is_account_history
from quant_trade.audit.crises import MARKET, MARKET_AS_OF
from quant_trade.audit.decay import is_weaker
from quant_trade.audit.decay import signed_amount as _signed_amount
from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.holding import EDGE_SE
from quant_trade.audit.i18n import localize
from quant_trade.audit.importers import NEAR_EMPTY_DAYS, NEAR_EMPTY_FIRST, lead_number
from quant_trade.audit.instruments import MIN_EACH as _INSTRUMENTS_MIN
from quant_trade.audit.instruments import OTHER as _INSTRUMENTS_OTHER
from quant_trade.audit.legal import LINK_TEXT, legal_url
from quant_trade.audit.method import COPY as METHOD_COPY
from quant_trade.audit.method import method_url
from quant_trade.audit.plan import improvement_plan
from quant_trade.audit.prop_presets import preset_label
from quant_trade.audit.redflags import flag_title
from quant_trade.audit.schema import AuditResult, Dimension
from quant_trade.audit.seo import BRAND, TAGLINE, private_meta
from quant_trade.audit.sizing import scale_text as sizing_scale_text
from quant_trade.audit.streaks import CLUSTERED
from quant_trade.audit.theme import (
    CLASS_COLOURS,
    SCRIPT_TAG,
    STYLE,
    aurora,
    class_ring,
    grid_bg,
    icon,
    logo,
    logo_mark,
    ring_svg,
)
from quant_trade.audit.verdict import (
    DEFAULT_THRESHOLDS,
    DIMENSION_ORDER,
    NOT_MEASURED_ES,
    Locale,
    meaning,
    summary,
)
from quant_trade.evidence.canonical_json import (
    canonical_dumps,
    pretty_dumps,
    sha256_of_text,
)

WATERMARK_TEXT = {"es": "VISTA PREVIA — SIN PAGAR", "en": "PREVIEW — UNPAID"}

DISCLAIMER = {
    "es": (
        "Esta auditoría es una herramienta de investigación estadística aplicada a datos "
        "aportados por el cliente. No es asesoría de inversión, no ejecuta operaciones, no "
        "custodia fondos ni claves, y no predice resultados futuros. Cada valor lleva su "
        "etiqueta de evidencia: MEASURED se calculó desde el archivo, DECLARED lo afirmó el "
        "cliente y no se pudo verificar, NOT_MEASURED no se pudo calcular con lo aportado."
    ),
    "en": (
        "This audit is a statistical research tool applied to client-supplied data. It is "
        "not investment advice, executes no trades, holds no funds or keys, and does not "
        "predict future results. Every value carries its evidence tag: MEASURED was computed "
        "from the file, DECLARED was asserted by the client and could not be verified, "
        "NOT_MEASURED could not be computed from what was supplied."
    ),
}

#: Years of history needed above this read "more than" it: the figure only
#: says the search is far too wide for the history.
LUCK_YEARS_SHOWN = 100

#: The full sample report, linked from a locked preview.
SAMPLE_PATHS: dict[str, str] = {"es": "/ejemplo", "en": "/sample"}

#: What each locked section tells the buyer, in plain words: the lockbox lists
#: these instead of the sections' technical titles, which stay in the report.
LOCKED_GAINS: dict[str, dict[str, str]] = {
    "es": {
        "plan": "Qué cambiar para subir de clase, con tus cifras",
        "reasons_detail": "Por qué recibió cada nota, dimensión por dimensión",
        "account": "Cuánto es resultado de operar y cuánto son depósitos",
        "live": "Si la cuenta real se parece a su backtest",
        "test_data": "Con qué datos y qué calidad de ticks se hizo la prueba",
        "stress": "Qué queda sin sus mejores operaciones y meses",
        "timing": "En qué horas y días se concentra el resultado",
        "recent": "Si sigue funcionando en el periodo más reciente",
        "crises": "Cómo le fue en 2008, el covid, 2022 y otras caídas conocidas",
        "holding": "Si le gana a simplemente comprar y mantener el mercado que opera",
        "regime": "Cómo le fue con el mercado tranquilo y con el mercado agitado (VIX)",
        "luck": (
            "Cuánto Sharpe queda al descontar la suerte y cuántos años de historial harían falta"
        ),
        "ride": "Tiempo sin nuevos máximos, peor día, peor mes y meses en positivo",
        "behaviour": "Si sube el riesgo después de perder (martingala, promediar)",
        "fund": "Calendario año por mes, peor mes, caída más profunda y tiempo en recuperarse",
        "instruments": "Si funciona en cada mercado o uno carga con el resto",
        "trade_stats": "Tasa de acierto, operación media y rachas",
        "risk": "Caídas posibles en un año, según miles de historias remuestreadas",
        "plateau": "Si los parámetros elegidos son un pico aislado o una zona estable",
        "forward": "Si aguanta en el tramo forward que no se usó para ajustarla",
        "capital": "Qué capital pide y a qué tamaño de posición",
        "challenge": "Con qué frecuencia tocaría los límites de un reto de prop firm",
        "questions": "Qué preguntarle al vendedor o al gestor",
        "performance": "Rentabilidad anual, volatilidad y caída máxima medidas",
        "significance": "Si el resultado se distingue de la suerte",
        "multiplicity": "Cuánto queda al descontar las configuraciones que se probaron",
        "bootstrap": "El rango de resultados plausibles, con intervalos de confianza",
        "cscv": "La probabilidad de que la mejor configuración sea sobreajuste",
        "subperiods": "El resultado año por año",
        "rolling": "Cómo cambia el resultado a lo largo del tiempo",
        "red_flags": "Cada bandera roja con sus cifras y qué hacer",
        "costs": "Qué pasa con costes más altos",
        "holdout": "El tramo fuera de muestra que declaraste, medido aparte",
        "benchmark": "La comparación con el benchmark que subiste",
    },
    "en": {
        "plan": "What to change to reach a better class, with your figures",
        "reasons_detail": "Why each dimension got its grade",
        "account": "How much is trading result and how much is deposits",
        "live": "Whether the live account looks like its backtest",
        "test_data": "What data and tick quality the test ran on",
        "stress": "What is left without its best trades and months",
        "timing": "Which hours and days the result comes from",
        "recent": "Whether it still works in the most recent period",
        "crises": "How it did in 2008, covid, 2022 and other known falls",
        "holding": "Whether it beats simply buying and holding the market it trades",
        "regime": "How it did in calm and in turbulent markets (VIX)",
        "luck": "How much Sharpe is left once luck is discounted, and how many years it would take",
        "ride": "Time without new highs, worst day, worst month and months that ended up",
        "behaviour": "Whether it raises risk after a loss (martingale, averaging down)",
        "fund": "Year-by-month calendar, worst month, deepest fall and time to recover",
        "instruments": "Whether it works on each market or one carries the rest",
        "trade_stats": "Hit rate, average trade and streaks",
        "risk": "Possible falls within a year, from thousands of resampled histories",
        "plateau": "Whether the chosen settings are a lone peak or a stable area",
        "forward": "Whether it holds in the forward period not used for tuning",
        "capital": "How much capital it needs and at what position size",
        "challenge": "How often it would hit a prop-firm challenge's limits",
        "questions": "What to ask the vendor or manager",
        "performance": "Annual return, volatility and maximum drawdown as measured",
        "significance": "Whether the result stands out from luck",
        "multiplicity": "What is left after discounting the configurations tried",
        "bootstrap": "The range of plausible results, with confidence intervals",
        "cscv": "The probability that the best configuration is overfit",
        "subperiods": "The result year by year",
        "rolling": "How the result changes over time",
        "red_flags": "Each red flag with its figures and what to do",
        "costs": "What happens with higher costs",
        "holdout": "The out-of-sample period you declared, measured separately",
        "benchmark": "The comparison with the benchmark you uploaded",
    },
}

LABELS: dict[str, dict[str, str]] = {
    "es": {
        "title": f"{BRAND} · Auditoría de backtest",
        "title_fund": f"{BRAND} · Auditoría de historial de fondo",
        "fund_net": (
            "Rentabilidades declaradas netas de comisiones: son las cifras del propio fondo "
            "tras sus comisiones y Rigor no midió los costes."
        ),
        "generated": "Generada",
        "audit_id": "Identificador",
        "inputs": "Archivos auditados (sha256)",
        "verdict": "Veredicto",
        "dimensions": "Dimensiones",
        "dimension": "Dimensión",
        "status": "Estado",
        "reasons": "Razones",
        "performance": "Rendimiento anualizado",
        "significance": "Significación estadística",
        "multiplicity": "Multiplicidad (número de intentos)",
        "sensitivity": "Sensibilidad del Sharpe deflactado al número de intentos",
        "bootstrap": "Bootstrap estacionario (por período)",
        "holdout": "Fuera de muestra declarado",
        "costs": "Costes de operación",
        "benchmark": "Benchmark aportado",
        "cscv": "Sobreajuste por validación cruzada combinatoria (CSCV)",
        "subperiods": "Subperíodos (años naturales)",
        "rolling": "Ventanas móviles",
        "red_flags": "Banderas rojas",
        "not_measured": "No medido",
        "declared": "Declarado por el cliente",
        "metric": "Métrica",
        "value": "Valor",
        "evidence": "Evidencia",
        "note": "Nota",
        "none": "ninguna",
        "flags_none": "Sin banderas rojas en los archivos auditados.",
        "trials": "intentos",
        "expected_max": "Sharpe máximo esperado sin habilidad",
        "dsr": "Sharpe deflactado (DSR)",
        "multiplier": "Multiplicador",
        "cost_recomputed": (
            "Esta tabla recalcula cada operación con sus precios y su tamaño: sin coste "
            "extra da {table}, {gap} de diferencia con el resultado neto de las operaciones "
            "({trades}), por el redondeo de precios o la conversión de divisa."
        ),
        "bps": "pb por lado",
        "gross": "Bruto",
        "cost": "Coste",
        "net": "Neto",
        "win_rate": "Aciertos",
        "win_rate_gross": "Aciertos antes de comisiones",
        "trades": "Operaciones",
        "in_sample": "En muestra",
        "out_of_sample": "Fuera de muestra",
        "year": "Año",
        "return": "Retorno",
        "max_drawdown": "Drawdown máximo",
        "window": "Ventana",
        "min_return": "Retorno mínimo",
        "min_drawdown": "Drawdown mínimo",
        "share_negative": "Fracción negativa",
        "code": "Código",
        "severity": "Severidad",
        "detail": "Detalle",
        "warnings": "Avisos de lectura",
        "client_text": "Descripción del cliente",
        "client_text_none": "No se escribió una descripción de la estrategia.",
        "chars": "{n} caracteres",
        "client_text_note": (
            "La descripción no se reproduce en este informe; consta en el JSON. Expresiones de "
            "promesa de resultados detectadas en ella"
        ),
        "seal": "Sello del holdout declarado",
        "pay": "Pagar con tarjeta",
        "pay_pack": "Comprar el paquete de 3 (USD {price:.0f})",
        "pay_secure": (
            "Pago seguro con Stripe. Ves el informe completo en cuanto se confirma el pago; "
            "nosotros no vemos ni guardamos los datos de tu tarjeta."
        ),
        "pay_links_note": (
            "El pago se abre en otra pestaña. Cuando termines, vuelve aquí: el informe se "
            "desbloquea en cuanto Stripe confirma el pago."
        ),
        "paid_check": "Ya pagué: ver mi informe",
        "buy_code_alt": "¿Prefieres pagar por transferencia? Pide un código aquí",
        "pack_left": (
            "Te quedan {n} informes de tu paquete. Para usarlos, escribe este código al "
            "desbloquear tus próximos informes:"
        ),
        "pack_used": "Ya usaste los informes de tu paquete (código {code}).",
        "pack_keep": "Guárdalo: también aparece aquí cada vez que abres este informe.",
        "locked": "Sección disponible en el informe completo",
        "disclaimer": "Aviso",
        "json_sha": "sha256 del JSON de la auditoría",
        "thresholds": "Umbrales aplicados",
        "print": "Imprimir / guardar PDF",
        "pdf": "Descargar PDF",
        "obs": "observaciones",
        "source_equity": "curva de equity",
        "source_returns": "serie de retornos",
        "variance_policy": (
            "Varianza usada: la mayor entre la observada en las variantes que subiste y la "
            "que produce el error de muestreo."
        ),
        "pdf_long": "Descargar el informe en PDF",
        "pdf_busy": "Generando tu PDF… (unos segundos)",
        "pdf_wait": "El PDF tarda unos segundos en generarse.",
        "pdf_check": "Quien reciba el PDF o el JSON puede comprobar que no se editó.",
        "pdf_check_link": "Cómo lo comprueba",
        "switch": "English",
        "my_account": "Mi cuenta",
        "yes": "sí",
        "no": "no",
        "redeem": "¿Tienes un código de acceso? Escríbelo para ver el informe completo",
        "redeem_button": "Canjear código",
        "code_error": (
            "Ese código no desbloqueó el informe: no existe, ya se usó o caducó. "
            "Cópialo tal como te llegó y vuelve a canjearlo."
        ),
        "code_error_contact": "Si sigue sin funcionar, escríbenos por el botón de arriba.",
        "buy_code": "Comprar por WhatsApp",
        "buy_code_how": (
            "Nos escribes por WhatsApp; el mensaje ya lleva el número de este informe.|"
            "Te respondemos con los datos para pagar.|"
            "Al confirmarse el pago recibes un código: lo escribes aquí abajo y el informe "
            "se abre completo."
        ),
        "buy_code_wait": (
            "Responde una persona. Si escribes de noche o en fin de semana, te contestamos en "
            "cuanto lo veamos; mientras tanto tu informe sigue en este enlace."
        ),
        "generic_rules": "Reglas de referencia genéricas, no las de una firma concreta.",
        "unlock_jump": "Desbloquear el informe completo",
        "unlock_nav": "Desbloquear",
        "account": "El dinero real de la cuenta",
        "test_data": "Con qué datos se hizo la prueba",
        "capital": "Qué capital necesita y a qué tamaño",
        "plateau": "¿Pico aislado o meseta?",
        "plateau_intro": (
            "Comparamos la configuración elegida con las que están a un paso en cada parámetro "
            "dentro de tu archivo de optimización. Si al mover un parámetro un paso el "
            "resultado se hunde, la configuración se ajustó al ruido del historial."
        ),
        "plateau_by_report": "Elegida: la que coincide con las entradas del informe del probador.",
        "plateau_by_best": (
            "Elegida: la pasada con más beneficio, porque el informe no trae entradas que "
            "coincidan con una pasada."
        ),
        "plateau_keep": "Del beneficio elegido que conservan los vecinos (mediana).",
        "plateau_in_profit": "De los vecinos que ganan.",
        "plateau_neighbours": "Vecinos a un paso",
        "plateau_parameter": "Parámetro",
        "plateau_value": "Valor",
        "plateau_result": "Beneficio",
        "plateau_clean": "Los vecinos conservan buena parte del resultado: parece una meseta.",
        "plateau_peak": (
            "Los vecinos pierden buena parte del resultado: parece un pico aislado. "
            "Lo verás también en las banderas rojas."
        ),
        "plateau_badge_clean": "Meseta",
        "plateau_badge_peak": "Pico aislado",
        "plateau_forward_hint": (
            "Si en el probador de MT5 activas el periodo forward y subes esa optimización, el "
            "informe añade «¿Aguanta en el periodo forward?»: compara cada configuración en el "
            "periodo optimizado y en uno posterior que el optimizador no usó para elegir."
        ),
        "forward": "¿Aguanta en el periodo forward?",
        "forward_intro": (
            "MetaTrader puede probar las mismas configuraciones en un periodo posterior que el "
            "optimizador no usó para elegir (forward). Comparamos el orden que da el backtest "
            "con lo que pasa después en ese periodo."
        ),
        "forward_rank": (
            "Correlación de rangos entre backtest y forward (1 = mismo orden, 0 = sin relación)."
        ),
        "forward_top": "De las {n} mejores pasadas del backtest terminan el forward con ganancia.",
        "forward_all": "De todas las pasadas terminan el forward con ganancia.",
        "forward_chosen": "De las demás pasadas quedan por debajo de la elegida en el forward.",
        "forward_held": (
            "Las mejores pasadas del backtest siguen por delante en el periodo forward."
        ),
        "forward_lost": (
            "El orden del backtest no se sostiene en el periodo forward. "
            "Lo verás también en las banderas rojas."
        ),
        "forward_badge_held": "Aguanta",
        "forward_badge_lost": "No aguanta",
        "capital_intro": (
            "Cuánto dinero hace falta para que un año malo no se lleve más de cierto porcentaje "
            "de la cuenta, con las operaciones de este archivo. Sorteamos {samples:,} años de "
            "operaciones al azar y tomamos la caída que solo un 5 % de ellos supera, o la del "
            "propio historial si es mayor."
        ),
        "capital_fall": "Caída de referencia en dinero, al tamaño del backtest.",
        "capital_history": "Mayor caída del historial en su propio orden.",
        "capital_platform": "Drawdown de la plataforma con operaciones abiertas.",
        "capital_short": (
            "Atención: el archivo cubre solo {days} días. Estas cifras estiran ese tramo a un "
            "año y pueden quedarse cortas o pasarse; tómalas como orden de magnitud y pide un "
            "historial de al menos un año antes de decidir el capital."
        ),
        "capital_limit": "Si aceptas perder hasta",
        "capital_needed": "Capital necesario al tamaño del backtest",
        "capital_scale": "Tamaño sobre el balance inicial del archivo ({balance})",
        "capital_scale_plain": "Tamaño sobre el balance inicial",
        "capital_scale_help": (
            "1x es el tamaño de lote del backtest; 0.50x es la mitad. Por encima de 1x la "
            "caída en dinero crece en la misma proporción."
        ),
        # The same labels when the file is a real or demo account history.
        "capital_fall_account": "Caída de referencia en dinero, al tamaño que usó la cuenta.",
        "capital_needed_account": "Capital necesario al tamaño que usó la cuenta",
        "capital_scale_help_account": (
            "1x es el tamaño de lote que usó la cuenta; 0.50x es la mitad. Por encima de 1x "
            "la caída en dinero crece en la misma proporción."
        ),
        "capital_open_loss": (
            "Tu plataforma imprime un drawdown de {platform} con las operaciones abiertas, "
            "frente a {closed} con las cerradas. Esta sección solo ve las operaciones "
            "cerradas: con las pérdidas abiertas hace falta más capital que el de la tabla."
        ),
        "capital_open_loss_floored": (
            "Tu plataforma imprime un drawdown de {platform} con las operaciones abiertas, "
            "frente a {closed} con las cerradas. Por eso las cifras de capital usan como mínimo "
            "el drawdown en dinero que imprime la plataforma con las operaciones abiertas."
        ),
        "capital_closed_only": (
            "Solo cuenta operaciones cerradas: las pérdidas de las posiciones mientras seguían "
            "abiertas no entran, así que el capital necesario puede ser mayor."
        ),
        "what_to_do": "Qué hacer:",
        "capital_missing": (
            "Para calcular el capital y el tamaño, sube al menos 30 operaciones cerradas "
            "repartidas en 3 meses o más del mismo sistema; con un año completo las cifras son "
            "más firmes."
        ),
        "test_data_intro": (
            "El encabezado del informe dice cómo se simularon los precios, qué parte del "
            "historial tuvo el probador y qué fechas se probaron. Conviene verificarlo, así que "
            "aquí lo comparamos con sus propias operaciones."
        ),
        "test_data_clean": (
            "El modelado, la calidad de datos y las fechas declaradas no levantan ninguna bandera."
        ),
        "test_data_scope": (
            "Leído del encabezado tal como lo subiste: si alguien lo editó, solo lo detectamos "
            "cuando no cuadra consigo mismo o con las operaciones."
        ),
        "account_intro": (
            "El porcentaje de ganancia que muestran los sitios de historiales quita los "
            "depósitos y los retiros. Aquí lo ponemos junto al dinero que la cuenta ganó o "
            "perdió operando, los depósitos hechos en plena pérdida y las posiciones que "
            "seguían abiertas al imprimir el historial."
        ),
        "account_backtest": (
            "Esta revisión es para historiales de cuentas reales o demo de MetaTrader 4 o 5. "
            "Tu archivo es un backtest."
        ),
        "account_gain": "Ganancia en %, como la muestran los sitios de historiales.",
        "account_money": "Resultado de operar, en dinero, sobre {deposited} depositados.",
        "account_floating": "Pérdida abierta sobre el balance al imprimir el historial.",
        "account_clean": (
            "No vimos depósitos en plena pérdida, ni una pérdida abierta grande, ni un "
            "porcentaje que se aparte del dinero."
        ),
        "account_clean_unseen": (
            "No vimos depósitos en plena pérdida ni un porcentaje que se aparte del dinero. "
            "El archivo no dice cuánto perdían las posiciones abiertas: pide al proveedor la "
            "curva de equity con flotante."
        ),
        "account_live": (
            "Revisión del historial que subiste como cuenta real. Sus banderas se muestran "
            "aquí y no cambian la clase del backtest."
        ),
        "account_deposits": "Depósitos después de empezar a operar, de mayor a menor",
        "account_date": "Fecha",
        "account_amount": "Importe",
        "account_before": "Balance antes",
        "account_drawdown": "Drawdown entonces",
        "account_scope": ("Leído del archivo tal como lo subiste; nada se comprobó con el bróker."),
        "account_trimmed_badge": "Para preguntar",
        "account_near_empty": (
            "El {date} una operación ganó o perdió más de lo que un retiro había dejado en la "
            "cuenta: se operó con la cuenta casi vacía ({days}). Un porcentaje calculado sobre "
            "casi nada se dispara, así que medimos esos días sobre el saldo de antes del "
            "retiro. Pregunta por qué se retiró casi todo y se siguió operando con lo que quedó."
        ),
        "account_near_empty_days": "{n} día",
        "account_near_empty_days_many": "{n} días",
        "account_trimmed": (
            "El archivo empieza con operaciones el {date}, sin el depósito que abrió la cuenta: "
            "puede faltar el principio del historial. La ganancia en % se mide desde el primer "
            "saldo del archivo. Pide la exportación completa desde la apertura de la cuenta."
        ),
        "luck": "¿Cuánto queda al descontar la suerte?",
        "luck_intro": (
            "Cuantas más configuraciones se prueban, más alto sale la mejor aunque ninguna tenga "
            "ventaja. Aquí ponemos el Sharpe del archivo junto al que daría la pura suerte con "
            "las configuraciones contadas, con la matemática publicada de Bailey y López de "
            "Prado y de Harvey y Liu. Es la misma cuenta que decide la dimensión «Número de "
            "configuraciones probadas», dicha en números."
        ),
        "luck_badge_beats": "Supera a la suerte",
        "luck_badge_below": "No supera a la suerte",
        "luck_badge_narrow": "Supera a la suerte, sin margen",
        "luck_narrow": (
            "El Sharpe de {sharpe} supera al {luck} que darían {n} configuraciones sin "
            "habilidad, pero no con el margen que pedimos: la confianza de que no sea suerte "
            "(DSR) es del {dsr}, y para aprobar esta dimensión pedimos {need}."
        ),
        "luck_beats": (
            "El Sharpe de {sharpe} supera al {luck} que darían {n} configuraciones sin habilidad."
        ),
        "luck_below": (
            "Con {n} configuraciones, la pura suerte daría un Sharpe de {luck}, igual o más "
            "que el {sharpe} de este historial."
        ),
        "luck_sharpe": (
            "Sharpe que darían {n} configuraciones sin habilidad (el del archivo: {sharpe})"
        ),
        "luck_years": (
            "Años de historial con los que esa suerte queda por debajo de este Sharpe "
            "(el archivo tiene {span})"
        ),
        "luck_after": "Sharpe que queda tras descontar {n} configuraciones (Harvey y Liu)",
        "luck_years_unit": "años",
        "luck_uncounted": (
            "Los archivos no dicen cuántas configuraciones se probaron antes de elegir esta. "
            "La tabla muestra cuánto historial haría falta según cuántas fueran: pregúntaselo "
            "al vendedor."
        ),
        "luck_span_line": "Sharpe del archivo: {sharpe}. Historial: {span}.",
        "luck_table_trials": "Configuraciones probadas",
        "luck_table_luck": "Sharpe que daría la suerte",
        "luck_table_years": "Historial necesario",
        "luck_table_enough": "¿Alcanza este historial?",
        "luck_short": (
            "Con menos de un año de historial, un Sharpe anualizado cambia mucho con pocos "
            "datos: tómalo como orden de magnitud."
        ),
        "luck_more_than": "más de {n} años",
        "luck_months": "{n} meses",
        "luck_month_one": "1 mes",
        "luck_under_month": "menos de 1 mes",
        "ride": "Cómo se vivió este historial",
        "ride_intro": (
            "Un total y una caída máxima no dicen cómo se vivió el historial: cuánto tiempo pasó "
            "sin un nuevo máximo, cuánto tardó en volver la peor caída, y cómo fueron el peor "
            "día y el peor mes. Son las cifras que hacen que alguien apague un sistema."
        ),
        "ride_days": "{n} días",
        "ride_under": "Tiempo más largo sin un nuevo máximo ({start} a {end})",
        "ride_under_open": (
            "Tiempo sin un nuevo máximo desde el {start}: sigue abierto al final del archivo"
        ),
        "ride_fall": "Peor caída: días del máximo ({start}) al mínimo ({low})",
        "ride_recovery": "Días desde ese mínimo hasta volver al máximo",
        "ride_not_back": "sin volver",
        "ride_not_back_note": "La peor caída no se recupera antes de la última fecha del archivo.",
        "ride_worst_day": "Peor día ({date})",
        "ride_worst_month": "Peor mes ({month})",
        "ride_positive": (
            "Meses en positivo ({k} de {n}); racha más larga de meses en negativo: {run}"
        ),
        "ride_closed": (
            "La curva se reconstruye con operaciones cerradas: las pérdidas abiertas no se ven, "
            "así que las caídas reales duraron y midieron al menos esto."
        ),
        "recent": "¿Sigue funcionando en el periodo reciente?",
        "recent_intro": (
            "Un historial largo puede verse bien en total aunque su último tramo ya no sume. "
            "Partimos el tiempo del historial en tres tramos iguales y comparamos el último con "
            "los dos anteriores, operación por operación."
        ),
        "recent_early": "Media por operación antes del {date}",
        "recent_late": "Media por operación desde el {date}",
        "recent_net": "Resultado neto desde el {date} ({n} operaciones)",
        "recent_z": (
            "Distancia entre ambas medias, en errores estándar (-2 o menos: una caída "
            "que el azar difícilmente explica)"
        ),
        "recent_held": (
            "El último tercio del historial no muestra una caída a pérdidas que el azar no "
            "explique."
        ),
        "recent_faded": (
            "El último tercio del historial promedia cero o pérdidas por operación, una caída "
            "que el azar difícilmente explica. Lo verás también en las banderas rojas."
        ),
        "recent_badge_held": "Se mantiene",
        "recent_badge_weaker": "Más débil",
        "recent_weaker": (
            "La media por operación bajó de {early} a {late} ({change}) en el último tercio. "
            "Sigue sobre cero y la caída cabe en lo que el azar explica, pero conviene "
            "vigilarla."
        ),
        "recent_badge_faded": "Se apaga",
        "recent_year": "Año de cierre",
        "fund": "Lo que revisaría quien invierte en un fondo",
        "fund_intro": (
            "Las cifras de una ficha de fondo y dos pruebas que usan los analistas de fondos: "
            "si las rentabilidades mensuales están suavizadas y si faltan meses con una pérdida "
            "pequeña. No cambia la clase: son preguntas para hacer."
        ),
        "fund_year": "Año",
        "fund_total": "Total",
        "fund_months": "Ene,Feb,Mar,Abr,May,Jun,Jul,Ago,Sep,Oct,Nov,Dic",
        "fund_cagr": "Rentabilidad anual compuesta",
        "fund_vol": "Volatilidad anual",
        "fund_vol_u": "Volatilidad anual sin suavizar (antes: {vol})",
        "fund_positive": "Meses en positivo ({n} meses)",
        "fund_worst": "Peor mes (mejor: {best})",
        "fund_dd": "Caída máxima",
        "fund_under": "Meses seguidos por debajo de un máximo anterior",
        "fund_under_open": "Meses seguidos por debajo de un máximo anterior (aún sin recuperar)",
        "fund_losing": "Meses seguidos en pérdida, como máximo",
        "fund_smoothed": (
            "Cada mes se parece demasiado al anterior (autocorrelación de {rho}). Suele pasar "
            "con activos poco líquidos o valorados con retraso, y hace que la volatilidad "
            "parezca menor: sin ese suavizado sería {vol_u} al año en vez de {vol}. Pregunta "
            "cómo y cada cuánto se valoran las posiciones."
        ),
        "fund_few_small_losses": (
            "Hay muchos meses con una ganancia pequeña y muy pocos con una pérdida pequeña "
            "({gains} frente a {losses}), menos de lo que hacen esperar los meses vecinos. "
            "Los estudios sobre fondos relacionan ese patrón con valoraciones que evitan cerrar "
            "un mes en negativo. Pregunta quién calcula el valor liquidativo y si lo revisa "
            "un tercero."
        ),
        "fund_clean": "Ni suavizado ni falta de meses con pérdida pequeña.",
        "fund_badge_clean": "Sin patrones",
        "fund_bench": "Frente a su índice de referencia",
        "fund_bench_file": (
            "Del {first} al {last}, {n} meses en común con el índice que trae el propio archivo, "
            "con sus cifras tal como vienen."
        ),
        "fund_bench_upload": (
            "Del {first} al {last}, {n} meses en común con el archivo de benchmark que subiste."
        ),
        "fund_bench_gross": (
            "Si las cifras del fondo son antes de comisiones, esta comparación lo favorece."
        ),
        "fund_fees": "¿Cuánto se llevarían las comisiones?",
        "fund_fees_intro": (
            "Las cifras no se declararon netas de comisiones. Así quedaría el mismo historial "
            "con las comisiones anuales habituales de un fondo activo, descontadas mes a mes."
        ),
        "fund_fees_rate": "Comisión anual",
        "fund_fees_cagr": "Rentabilidad anual",
        "fund_fees_growth": "Crecimiento total",
        "fund_fees_none": "Sin comisión",
        "fund_fees_management": (
            "Solo comisión de gestión. Muchos fondos cobran además una comisión de éxito, a "
            "menudo el 20 % de las ganancias, así que el 2.5 % no es el peor caso."
        ),
        "fund_fees_break_even": (
            "Con una comisión de {rate} al año o más, el fondo habría quedado igual o por "
            "debajo de su índice en los meses en común."
        ),
        "fund_fees_behind": (
            "El fondo ya queda igual o por debajo de su índice antes de cualquier comisión."
        ),
        "fund_bench_excess": "Diferencia anual frente al índice (fondo {fund}, índice {index})",
        "fund_bench_beat": "Meses en que superó al índice",
        "fund_bench_te": "Error de seguimiento anual (ratio de información {ir})",
        "fund_bench_beta": "Beta frente al índice (correlación {corr})",
        "fund_bench_up": "Captura al alza: parte de las subidas del índice que recoge",
        "fund_bench_down": "Captura a la baja: parte de las caídas del índice que recoge",
        "fund_bench_trails": (
            "Rindió menos que su índice: {excess} al año en los meses en común. Pregunta qué "
            "justifica pagar una gestión activa frente a un fondo indexado."
        ),
        "fund_bench_index_like": (
            "Sigue a su índice muy de cerca (correlación {corr}, error de seguimiento {te} al "
            "año), lo que los estudios llaman gestión indexada encubierta. Pregunta qué aportan "
            "sus comisiones que no dé un fondo indexado."
        ),
        "fund_bench_worse": (
            "Recoge menos de las subidas del índice ({up}) y más de sus caídas ({down}). "
            "Pregunta en qué tipo de mercado espera el gestor hacerlo mejor."
        ),
        "fund_bench_clean": (
            "Por delante de su índice en los meses en común y sin seguirlo como un fondo indexado."
        ),
        "fund_bench_badge_clean": "Por delante",
        "fund_bench_nm": "Comparación con el índice:",
        "fund_stress": "¿Cómo le fue en las crisis conocidas?",
        "crises": "¿Cómo le fue en las crisis conocidas?",
        "crises_intro": (
            "Rentabilidad de la curva, con sus saldos de fin de mes, en cada caída de mercado "
            "de fecha pública que cubre completa (del máximo al mínimo del mercado). Un mes "
            "sin operaciones cuenta como plano. Las fechas son fijas: no se ajustan al archivo."
        ),
        "crises_subject": "Estrategia",
        "holding": "¿Le gana a comprar y mantener el mercado?",
        "holding_intro": (
            "La estrategia opera sobre todo el {label}. Estos son sus cierres diarios junto a "
            "los de simplemente comprar y mantener el {label} los mismos días, del {first} al "
            "{last} ({days} días). El Sharpe mide lo que paga cada unidad de riesgo: no cambia "
            "con el tamaño de la posición, así que compara bien una estrategia apalancada con "
            "el mercado sin apalancar."
        ),
        "holding_not_measured": "Sin comparación con el {label}: {reason}.",
        "holding_strategy": "Estrategia",
        "holding_market": "Mantener el {label}",
        "holding_return": "Rentabilidad en el periodo",
        "holding_drawdown": "Peor caída",
        "holding_sharpe": "Sharpe en los mismos {days} días (rentabilidad por unidad de riesgo)",
        "holding_together": (
            "Correlación semanal (de viernes a viernes) con el {label}: {corr}. Por cada 1 % "
            "que se movió el mercado en una semana, la estrategia se movió en promedio {beta} %. "
            "Se usan semanas porque la hora de cierre del archivo y la del mercado pueden no "
            "coincidir."
        ),
        "holding_no_clear_edge": (
            "La diferencia de Sharpe ({z} errores estándar, medida con rentabilidades "
            "semanales) no basta para decir que le gana al mercado."
        ),
        "holding_rides": (
            "Se mueve casi al mismo paso que el {label} y no muestra una ventaja clara sobre "
            "mantenerlo: la diferencia de Sharpe queda dentro del ruido de {weeks} semanas. "
            "¿Qué agrega frente a comprar el mercado y esperar?"
        ),
        "holding_closed_only": (
            "El archivo solo trae el balance al cerrar operaciones: los días con posiciones "
            "abiertas no se ven, así que la correlación y la peor caída de la estrategia "
            "quedan cortas."
        ),
        "holding_source": (
            "Cierres del {label}: datos públicos de {source} leídos al generar el "
            "informe. Ninguno de los dos Sharpe resta la tasa del efectivo. No cambia la clase."
        ),
        "regime": "¿Cómo le fue con el mercado tranquilo y con el mercado agitado?",
        "regime_intro": (
            "Cada rentabilidad del archivo se asigna según el VIX (cuánto espera el mercado de "
            "opciones que se mueva el S&P 500 el mes siguiente) al cierre del día de mercado "
            "anterior a que empiece: mercado tranquilo por debajo de 20, agitado desde 20. "
            "Desde 1990 el VIX cerró en 20 o más aproximadamente un día de cada tres. Periodo: del "
            "{first} al {last}."
        ),
        "regime_not_measured": "Sin separación por el VIX: {reason}.",
        "regime_calm": "Mercado tranquilo (VIX < 20)",
        "regime_turbulent": "Mercado agitado (VIX ≥ 20)",
        "regime_time": "Parte del tiempo",
        "regime_returns": "Rentabilidades contadas",
        "regime_monthly": "Rentabilidad por mes (compuesta)",
        "regime_sharpe": "Sharpe (rentabilidad por unidad de riesgo)",
        "regime_better_calm": (
            "Le fue mejor con el mercado tranquilo: la diferencia de rentabilidad media "
            "({z} errores estándar) es mayor que el ruido."
        ),
        "regime_better_turbulent": (
            "Le fue mejor con el mercado agitado: la diferencia de rentabilidad media "
            "({z} errores estándar) es mayor que el ruido."
        ),
        "regime_no_clear_gap": (
            "La diferencia de rentabilidad media entre las dos columnas ({z} errores "
            "estándar) no basta para decir que se comporta distinto según el mercado."
        ),
        "regime_source": (
            "VIX: datos públicos de {source} (serie VIXCLS, de CBOE) leídos al generar el "
            "informe. Mide acciones de EE. UU.: si la estrategia opera otro mercado, tómalo "
            "como termómetro general del miedo en los mercados. No cambia la clase."
        ),
        "crises_market": "Mercado en esas fechas",
        "crises_market_note": (
            "Mercado: cierre del mes previo a la ventana contra el cierre de su último mes, "
            "datos públicos de FRED consultados el {as_of} ({sources}). Son acciones de "
            "EE. UU. y bitcoin: si la estrategia opera otro mercado (divisas, materias "
            "primas, otro país), tómelos solo como contexto de lo que vivía el mercado, no "
            "como su punto de comparación."
        ),
        "crises_no_trades": "sin operaciones cerradas en la ventana",
        "crises_worse": (
            "En {worse} de {n} crisis cayó más que su índice. Pregunta al vendedor qué la "
            "protege cuando el mercado cae."
        ),
        "fund_stress_intro": (
            "Rentabilidad del fondo en cada caída de mercado de fecha pública que su historial "
            "cubre completa (del máximo al mínimo del mercado). Las fechas son fijas: no se "
            "ajustan al archivo."
        ),
        "fund_stress_none": (
            "El historial no cubre completa ninguna de las caídas de la lista (puntocom, 2008, "
            "euro 2011, 2015-16, final de 2018, covid, 2022, cripto 2022)."
        ),
        "fund_stress_head": "Crisis",
        "fund_stress_fund": "Fondo",
        "fund_stress_index": "Índice",
        "fund_stress_12m": (
            "Peores 12 meses seguidos: {worst}; mejores: {best}. Terminaron en positivo el "
            "{share} de los periodos de 12 meses."
        ),
        "fund_stress_worse": (
            "En {worse} de {n} crisis cayó más que su índice. Pregunta qué protege la cartera "
            "cuando el mercado cae."
        ),
        "fund_stress_dotcom": "Estallido de las puntocom",
        "fund_stress_gfc": "Crisis financiera de 2008",
        "fund_stress_euro": "Crisis de deuda del euro",
        "fund_stress_china_oil": "China y caída del petróleo",
        "fund_stress_late_2018": "Final de 2018",
        "fund_stress_covid": "Caída por el covid",
        "fund_stress_rates_2022": "Inflación y tipos, 2022",
        "fund_stress_crypto_2022": "Invierno cripto 2022",
        "instruments": "¿Funciona en cada instrumento?",
        "ins_intro": (
            "Cuando un robot o una señal opera varios mercados, el total puede venir de uno "
            "solo mientras los demás pierden. No cambia la clase: son preguntas para hacer."
        ),
        "ins_head": "Instrumento",
        "ins_other": "Otros ({n} con menos de {m} operaciones)",
        "ins_best": "Parte del resultado neto que viene de {best}",
        "ins_one_carries": (
            "Un solo instrumento sostiene el resultado: sin {best}, los demás juntos quedan en "
            "cero o en pérdida. Pregunta por qué se operan los demás."
        ),
        "ins_mostly_one": (
            "Casi todo el resultado viene de {best} ({share}). Pregunta qué aportan los demás."
        ),
        "ins_best_over": "Más que el resultado neto viene de {best}: los demás juntos restan",
        "ins_most_lose": (
            "La mayoría de los instrumentos terminan en cero o en pérdida ({losing} de "
            "{readable}). Pregunta si la estrategia se ajustó a unos pocos mercados."
        ),
        "ins_clean": "Ningún instrumento carga él solo con el resultado.",
        "ins_badge_clean": "Repartido",
        "behaviour": "Cómo se comporta al perder",
        "behaviour_intro": (
            "Lo que te diría un diario de trading: si las pérdidas se aguantan más que las "
            "ganancias, si se vuelve a entrar deprisa tras perder y cómo salen las operaciones "
            "tras una racha de pérdidas. No cambia la clase: son preguntas para hacer."
        ),
        "beh_hold": (
            "Lo que dura una perdedora frente a una ganadora (mediana: {loss} frente a {win})"
        ),
        "beh_quick": (
            "Operaciones tras una pérdida abiertas en menos de 15 minutos "
            "(tras una ganancia: {win})"
        ),
        "beh_streak": (
            "Aciertos tras {k} pérdidas seguidas ({n} operaciones; en todo el historial: {all})"
        ),
        "beh_losers_held_longer": (
            "Las perdedoras siguen abiertas bastante más que las ganadoras. Pregunta dónde va "
            "el stop y si se mueve."
        ),
        "beh_quick_after_loss": (
            "Vuelve a entrar deprisa tras perder. Pregunta qué regla frena la siguiente "
            "operación después de una pérdida."
        ),
        "beh_worse_after_streak": (
            "Acierta menos tras una racha de pérdidas. Pregunta si el tamaño o las reglas "
            "cambian en esas rachas."
        ),
        "beh_quick_nm": "Reentrada rápida tras perder:",
        "beh_clean": "Nada destaca en cómo opera después de perder.",
        "beh_badge_clean": "Sin patrones",
        "beh_badge_found": "Para preguntar",
        "timing": "Cuándo gana y cuándo pierde",
        "timing_intro": (
            "Tus operaciones agrupadas por el día y la hora de entrada. Si casi todo el "
            "resultado sale de un solo día o de una sola franja, un cambio de horario del "
            "servidor, de festivos o de noticias puede borrarlo."
        ),
        "timing_best_day": "El {share:.0%} del resultado neto sale de los {day}.",
        "timing_best_block": "El {share:.0%} del resultado neto sale de la franja {block}.",
        "timing_day": "Día de entrada",
        "timing_block": "Hora de entrada",
        "timing_trades": "Operaciones",
        "timing_net": "Resultado neto",
        "timing_hits": "Aciertos",
        "live": "Backtest frente a cuenta real",
        "live_intro": (
            "Si las operaciones de la cuenta real salieran del mismo backtest, ¿qué tan raro "
            "sería su resultado? Tomamos al azar operaciones del backtest, tantas como tiene "
            "la cuenta real, {samples:,} veces, y ubicamos la cuenta real entre esas historias."
        ),
        "live_CONSISTENT": (
            "La cuenta real se comporta como el backtest: su resultado neto y su peor caída "
            "caen dentro de lo que el backtest hacía esperar."
        ),
        "live_EDGE": (
            "La cuenta real está en el borde: su resultado neto o su peor caída quedan peor "
            "que en el 95 % de las historias del backtest. Puede ser una mala racha, pero "
            "merece preguntas al vendedor."
        ),
        "live_INCONSISTENT": (
            "La cuenta real no se comporta como el backtest: su resultado neto o su peor caída "
            "quedan peor que en el 99 % de las historias del backtest."
        ),
        "live_ABOVE": (
            "La cuenta real queda por encima del 99 % de las historias del backtest. Un "
            "resultado así suele indicar que los dos archivos no son de la misma "
            "configuración, tamaño o cuenta: pregúntalo."
        ),
        "hero_live": "Cuenta real: {badge}.",
        "hero_live_money": "Resultado de operar: {result} sobre {deposits} depositados.",
        "hero_live_link": "Ver la comparación con el backtest",
        "live_badge_CONSISTENT": "Coherente",
        "live_badge_EDGE": "En el borde",
        "live_badge_INCONSISTENT": "No coherente",
        "live_badge_ABOVE": "Revisar",
        "live_col_backtest": "Backtest",
        "live_col_live": "Cuenta real",
        "live_col_live_rescaled": "Cuenta real, a tamaño del backtest",
        "live_col_expected": "Rango esperado (90 %)",
        "live_trades": "Operaciones",
        "live_period": "Periodo",
        "live_per_month": "Operaciones al mes",
        "live_win_rate": "Aciertos",
        "live_net": "Resultado neto",
        "live_fall": "Peor caída",
        "live_avg_win": "Ganancia media",
        "live_avg_loss": "Pérdida media",
        "live_below": "Historias del backtest con un resultado neto igual o peor",
        "live_fall_above": "Historias del backtest con una caída igual o más profunda",
        "live_rescaled": (
            "La cuenta real opera {ratio:.2f} veces el tamaño del backtest: cada operación "
            "real se ajustó al tamaño mediano del backtest antes de comparar."
        ),
        "live_same_size": "Mismo tamaño de posición (±25 %): se compara tal cual.",
        "live_pace": (
            "La cuenta real hace {ratio:.1f} veces las operaciones al mes del backtest: puede "
            "no ser la misma configuración."
        ),
        "live_overlap": (
            "Parte de la cuenta real cae dentro del periodo del backtest: esas fechas pudieron "
            "usarse para ajustar el backtest, así que la comparación es menos exigente."
        ),
        "live_symbols": "La cuenta real opera símbolos que el backtest no tiene: {symbols}.",
        "live_pair": "Mismas fechas, operación por operación",
        "live_pair_intro": (
            "Del {start} al {end} los dos archivos cubren los mismos días. Buscamos cada "
            "operación real en el backtest: mismo lado, mismo símbolo y entrada a menos de "
            "60 minutos."
        ),
        "live_pair_found": "Operaciones reales encontradas en el backtest",
        "live_pair_of": "{matched} de {total} ({share})",
        "live_pair_missing": "Operaciones del backtest que la cuenta real no hizo",
        "live_pair_entry": "Diferencia mediana de precio al entrar",
        "live_pair_exit": "Diferencia mediana de precio al salir",
        "live_pair_gap": "Diferencia de resultado en las emparejadas",
        "live_pair_gap_value": "{total} ({each} por operación)",
        "live_pair_bps": "{bps} pb",
        "live_pair_low": (
            "Menos de la mitad de las operaciones reales aparecen en el backtest en esas "
            "fechas: probablemente no es la misma configuración. Pide al vendedor el backtest "
            "exacto de esa cuenta."
        ),
        "live_pair_help": (
            "pb = puntos básicos (0,01 % del precio); positivo es peor para la cuenta. La "
            "diferencia de resultado está al tamaño del backtest; negativa es lo que la cuenta "
            "real hizo por debajo del backtest en las mismas operaciones."
        ),
        "reading": "Lectura de tu archivo",
        "reading_intro": (
            "Antes de analizar nada, volvimos a contar tus operaciones fila por fila y lo "
            "comparamos con el resumen que imprime tu plataforma."
        ),
        "reading_platform": "Tu plataforma",
        "reading_rows": "Leído de las filas",
        "reading_ok": "Coincide",
        "reading_bad": "No coincide",
        "reading_all_ok": "Todo coincide: el análisis parte de los mismos números que ves tú.",
        "reading_some_bad": (
            "Algo no coincide. Revisa los avisos de lectura más abajo y, si crees que leímos "
            "mal tu archivo, escríbenos con el identificador del informe."
        ),
        "boot_line": "Bootstrap estacionario por bloques, remuestreos:",
        "boot_block": "bloque",
        "point": "Estimación",
        "engine": "versión del motor",
        "seed": "semilla de las simulaciones",
        "code_request": f"Hola, quiero un código de {BRAND} para el informe {{id}}.",
        "code_request_price": (
            f"Hola, quiero comprar el informe completo de {BRAND} {{id}} ({{price}}). ¿Cómo pago?"
        ),
        "keep_link": (
            "Guarda el enlace de esta página: con él vuelves a tu informe. Si lo subiste con tu "
            "cuenta, también lo tienes en «Mi cuenta»."
        ),
        "pack": "pack de 3 informes: USD {price:.0f}",
        "buy_includes": (
            "Todas las cifras de cada sección|PDF para guardar o enviar|"
            "Página pública de verificación para compartir|"
            "Reembolso si el informe lee mal tu archivo"
        ),
        "publish": "Publicar verificación pública",
        "publish_help": (
            "Crea una página pública con la clase, las dimensiones y los hashes, y un sello "
            "para tu web. Nunca muestra tus archivos, operaciones ni descripción."
        ),
        "evidence_legend": (
            "Cada cifra lleva su etiqueta: MEASURED, calculada de tus archivos; DECLARED, "
            "declarada por ti o por el vendedor, sin verificar; NOT_MEASURED, faltó un dato "
            "para calcularla."
        ),
        "next": "Qué hacer ahora",
        "next_intro": (
            "Si compraste o vas a comprar este robot o señal, esto es lo que conviene aclarar "
            "primero, según lo que encontró la auditoría."
        ),
        "next_live": (
            "Pregunta al vendedor por qué tu cuenta real queda fuera de lo que el backtest "
            "hacía esperar."
        ),
        "next_costs": (
            "Compara el spread y la comisión de tu bróker con los costes que aguanta el "
            "resultado: con un coste algo mayor que el de referencia, el margen se pierde."
        ),
        "next_costs_fail": (
            "Compara el spread y la comisión de tu bróker con el coste de referencia: con ese "
            "coste las operaciones ya pierden dinero en neto."
        ),
        "next_trials": (
            "Pregunta cuántas configuraciones se probaron antes de elegir esta y con qué "
            "periodo se eligió."
        ),
        "next_oos": (
            "Pide un informe del mismo robot, sin cambios, en fechas posteriores a su optimización."
        ),
        "next_flags": (
            "Revisa las banderas rojas: señalan cifras que no se pueden tomar tal cual."
        ),
        "next_questions": "Lleva al vendedor las preguntas de este informe.",
        "next_keep": (
            "Guarda este informe y su identificador; si el robot cambia, pide que se audite "
            "de nuevo."
        ),
        "next_link": "Ir al apartado",
        "meaning": "Qué significa para ti",
        "ladder": "Qué pide cada clase",
        "ladder_intro": (
            "La clase no mide cuánto ganó el backtest, sino cuántas preguntas responden tus "
            "archivos. Una clase mejor no significa que la estrategia vaya a funcionar."
        ),
        "ladder_class": "Clase",
        "ladder_needs": "Qué hace falta",
        "ladder_you": "Tu informe",
        "charts": "Gráficas",
        "detail_heading": "Detalle",
        "locked_intro": (
            "El veredicto, las gráficas y las explicaciones son gratis. El informe completo "
            "te dice, con las cifras de tu archivo"
        ),
        "sample_full": "Ver cómo es un informe completo (ejemplo con datos sintéticos)",
        "trade_stats": "Estadísticas de las operaciones",
        "streak_line": (
            "Con el mismo porcentaje de perdedoras y en orden al azar, lo normal es una "
            "racha máxima de {chance} perdedoras seguidas, y 1 de cada 20 historiales "
            "llega a {rare}. Este historial tuvo {observed}."
        ),
        "streak_clustered": (
            "Las perdedoras llegaron más juntas de lo que el azar explica: una racha así "
            "sale en menos de 1 de cada 20 órdenes al azar. Suele indicar pérdidas que "
            "dependen del tipo de mercado o posiciones abiertas a la vez."
        ),
        "long": "Largos",
        "short": "Cortos",
        "risk": "Riesgo remuestreado a un año",
        "risk_dd": "Drawdown máximo a un año",
        "risk_prob": "Probabilidad de una caída de al menos",
        "risk_underwater": "Periodos seguidos bajo el máximo, en las simulaciones",
        "risk_under_median": "mediana",
        "risk_under_p95": "en 1 de cada 20",
        "challenge": "Simulador de reto de prop firm",
        "challenge_rules": "Reglas simuladas",
        "open_loss_badge": "Pérdidas abiertas",
        "hidden_loss": (
            "El archivo solo muestra el balance y las banderas rojas encontraron pérdidas "
            "abiertas que el balance oculta (Drawdown flotante oculto). Aquí no entran, así "
            "que estas cifras salen optimistas: no decidas con ellas sin la curva de equity "
            "con flotante."
        ),
        "challenge_open_loss": (
            "Tu plataforma imprime un drawdown de {dd} con las operaciones abiertas, más que "
            "el límite de pérdida total del reto ({limit}). La simulación usa el balance de "
            "operaciones cerradas, que no ve esas pérdidas abiertas: con ellas la cuenta del "
            "reto pudo tocar el límite."
        ),
        "outcome": "Resultado",
        "probability": "En las simulaciones del historial",
        "pass": "Llega al objetivo",
        "fail_daily_loss": "Rompe la pérdida diaria",
        "fail_total_loss": "Rompe la pérdida total",
        "unfinished": "No termina a tiempo",
        "ci95": "Intervalo del 95 % de llegar al objetivo",
        "days_to_target": "Días hábiles hasta el objetivo (p25 / p50 / p75)",
        "best_day_line": (
            "Regla del mejor día de esta firma: en el {share} de las veces que pasa, el mejor "
            "día queda por encima del límite. Según la firma, eso sube el objetivo o bloquea "
            "el retiro."
        ),
        "ff_title": "¿Con qué firma encaja tu historial?",
        "ff_intro": (
            "El mismo historial, remuestreado igual, con las reglas publicadas de cada firma, "
            "de más a menos probabilidad de pasar todas las fases del programa dentro de la "
            "regla del mejor día, si la firma la tiene; a igual cifra, por nombre. Compara "
            "reglas; no recomienda comprar ningún reto."
        ),
        "ff_program": "Reto",
        "ff_pass": "Pasa",
        "ff_clean": "Pasa dentro de la regla del mejor día",
        "ff_risk": "Lo que más lo tumba",
        "ff_no_rule": "sin regla",
        "ff_risk_none": "Nada en las simulaciones",
        "ff_risk_fail_daily_loss": "romper la pérdida diaria",
        "ff_risk_fail_total_loss": "romper la pérdida total",
        "ff_risk_unfinished": "no llegar al objetivo a tiempo",
        "ff_optimistic": (
            "Las mismas cifras optimistas de arriba aplican a esta tabla: el balance esconde "
            "pérdidas abiertas."
        ),
        "ff_all_pass": (
            "Con este historial todos los programas se pasan en al menos el 99 % de las "
            "simulaciones: sus reglas no los distinguen."
        ),
        "ff_all_fail": (
            "Con este historial casi ningún programa se pasa (1 % de las simulaciones o "
            "menos); lo que más lo impide es {risk}."
        ),
        "ff_phases": "{n} fases",
        "ff_phase": "1 fase",
        "assumptions": "Supuestos",
        "source": "Fuente",
        "as_of": "leída el",
        "questions": "Preguntas para hacerle al vendedor",
        "flags_free": "Banderas rojas detectadas",
        "report_source": "Formato del archivo",
        "platform": "Datos que declara la plataforma",
        "colmap": "Cómo se leyó cada columna de tu archivo",
        "optimization": "Exportación de optimización",
        "passes": "configuraciones probadas",
        "trials_used": "Intentos usados en el Sharpe deflactado",
        "horizon": "1 año",
        "reasons_detail": "Detalle técnico de cada dimensión",
        "fees": "Costes que detalla el informe",
        "plan": "Plan para subir de clase",
        "plan_intro": (
            "Lo que las reglas de la auditoría necesitarían ver en cada dimensión abierta, "
            "de lo más decisivo a lo menos. Una clase mejor significa que los archivos "
            "responden más preguntas, no que la estrategia vaya a funcionar."
        ),
        "plan_class": "Si esta dimensión pasara y las demás quedaran igual, la clase sería",
        "plan_none": "Todas las dimensiones pasan: no queda ningún paso abierto.",
        "plan_locked": "pasos concretos, con las cifras de tu archivo, en el informe completo",
        "kpis": "Resumen ejecutivo",
        "toc": "Secciones del informe",
        "toc_unlock": "Informe completo",
        "kpis_locked": "Las cifras clave de tu archivo se muestran en el informe completo.",
        "kpi_return": "Retorno total",
        "kpi_drawdown": "Drawdown máximo",
        "kpi_dd_platform": "Drawdown con operaciones abiertas, según tu plataforma",
        "kpi_dd_p95": "Drawdown p95 remuestreado, 1 año",
        "kpi_drawdown_closed": "Drawdown máximo (solo cerradas)",
        "kpi_dd_p95_closed": "Drawdown p95 a 1 año (solo cerradas)",
        "kpi_sharpe": "Sharpe anualizado",
        "kpi_pf": "Profit factor",
        "kpi_trades": "Operaciones · % de aciertos",
        "kpi_breakeven": "Coste extra que lo lleva a cero",
        "kpi_breakeven_negative": "ya pierde sin coste extra",
        "kpi_stress": "Sin las 5 mejores operaciones",
        "kpi_stress_curve": "Sin los 5 mejores periodos",
        "kpi_hint_return": "cuánto cambió la cuenta en todo el historial",
        "kpi_hint_drawdown": "la peor caída desde un máximo",
        "kpi_hint_dd_p95": "caída que se supera en 1 de cada 20 años simulados",
        "kpi_hint_sharpe": "rendimiento frente a sus altibajos; más alto, más estable",
        "cash_sharpe": (
            "Restando lo que pagaba el efectivo en dólares en esas mismas fechas (letras del "
            "Tesoro de EE. UU. a 3 meses, {rate} al año en promedio), el Sharpe queda en "
            "{sharpe}."
        ),
        "cash_below": (
            "Rindió menos que el efectivo en dólares en esas fechas ({ret} al año frente a "
            "{rate} de las letras del Tesoro a 3 meses)."
        ),
        "cash_note": (
            "El Sharpe de arriba no resta ninguna tasa. Si la cuenta no es en dólares, lo justo "
            "sería restar la tasa de su propia moneda. Fuente: {source}."
        ),
        "kpi_hint_pf": "lo ganado por cada 1 perdido",
        "kpi_hint_breakeven": "cuánto más puede costar operar antes de quedar en cero",
        "bps_side": "pb por lado",
        "stress": "Pruebas de estrés: sin los mejores resultados",
        "stress_intro": (
            "Quitamos los mejores periodos y operaciones de lo que subiste y medimos lo que "
            "queda. Si el total cae a cero o menos, depende de unos pocos eventos que pueden "
            "no repetirse. No es una previsión."
        ),
        "stress_curve": "Sobre la curva (retorno total compuesto)",
        "stress_trades": "Sobre las operaciones cerradas (resultado neto tras comisiones y swap)",
        "scenario": "Escenario",
        "stress_result": "Queda",
        "stress_change": "Cambio",
        "stress_positive": "¿Sigue sobre cero?",
        "original": "Original",
        "stress_count": "de {total} escenarios quedan en cero o por debajo",
        "top5_share": "Las 5 mejores operaciones suman este múltiplo del resultado neto",
    },
    "en": {
        "title": f"{BRAND} · Backtest audit",
        "title_fund": f"{BRAND} · Fund track record audit",
        "fund_net": (
            "Returns declared net of fees: they are the fund's own figures after its fees, "
            "and Rigor did not measure costs."
        ),
        "generated": "Generated",
        "audit_id": "Identifier",
        "inputs": "Audited files (sha256)",
        "verdict": "Verdict",
        "dimensions": "Dimensions",
        "dimension": "Dimension",
        "status": "Status",
        "reasons": "Reasons",
        "performance": "Annualised performance",
        "significance": "Statistical significance",
        "multiplicity": "Multiplicity (number of trials)",
        "sensitivity": "Deflated Sharpe sensitivity to the number of trials",
        "bootstrap": "Stationary bootstrap (per period)",
        "holdout": "Declared out-of-sample",
        "costs": "Trading costs",
        "benchmark": "Supplied benchmark",
        "cscv": "Combinatorially symmetric cross-validation (CSCV) overfitting",
        "subperiods": "Sub-periods (calendar years)",
        "rolling": "Rolling windows",
        "red_flags": "Red flags",
        "not_measured": "Not measured",
        "declared": "Declared by the client",
        "metric": "Metric",
        "value": "Value",
        "evidence": "Evidence",
        "note": "Note",
        "none": "none",
        "flags_none": "No red flags in the audited files.",
        "trials": "trials",
        "expected_max": "Expected max Sharpe without skill",
        "dsr": "Deflated Sharpe (DSR)",
        "multiplier": "Multiplier",
        "cost_recomputed": (
            "This table recomputes each trade from its prices and size: with no extra cost "
            "it gives {table}, {gap} away from the trades' net result ({trades}), from "
            "price rounding or currency conversion."
        ),
        "bps": "bps per side",
        "gross": "Gross",
        "cost": "Cost",
        "net": "Net",
        "win_rate": "Win rate",
        "win_rate_gross": "Win rate before fees",
        "trades": "Trades",
        "in_sample": "In sample",
        "out_of_sample": "Out of sample",
        "year": "Year",
        "return": "Return",
        "max_drawdown": "Max drawdown",
        "window": "Window",
        "min_return": "Min return",
        "min_drawdown": "Min drawdown",
        "share_negative": "Share negative",
        "code": "Code",
        "severity": "Severity",
        "detail": "Detail",
        "warnings": "Parse warnings",
        "client_text": "Client description",
        "client_text_none": "No strategy description was written.",
        "chars": "{n} characters",
        "client_text_note": (
            "The description is not reproduced here; it is in the JSON. Result-promise "
            "expressions detected in it"
        ),
        "seal": "Declared holdout seal",
        "pay": "Pay by card",
        "pay_pack": "Buy the pack of 3 (USD {price:.0f})",
        "pay_secure": (
            "Secure payment with Stripe. You see the full report as soon as the payment is "
            "confirmed; we never see or store your card details."
        ),
        "pay_links_note": (
            "The payment opens in another tab. When you finish, come back here: the report "
            "unlocks as soon as Stripe confirms the payment."
        ),
        "paid_check": "I have paid: show my report",
        "buy_code_alt": "Prefer a bank transfer? Ask for a code here",
        "pack_left": (
            "You have {n} reports left in your pack. To use them, enter this code when you "
            "unlock your next reports:"
        ),
        "pack_used": "You have used the reports in your pack (code {code}).",
        "pack_keep": "Keep it: it also shows here every time you open this report.",
        "locked": "Section available in the full report",
        "disclaimer": "Notice",
        "json_sha": "sha256 of the audit JSON",
        "thresholds": "Thresholds applied",
        "print": "Print / save PDF",
        "pdf": "Download PDF",
        "obs": "observations",
        "source_equity": "equity curve",
        "source_returns": "return series",
        "variance_policy": (
            "Variance used: the larger of the one observed across the variants you uploaded "
            "and the one sampling error produces."
        ),
        "pdf_long": "Download the report as PDF",
        "pdf_busy": "Preparing your PDF… (a few seconds)",
        "pdf_wait": "The PDF takes a few seconds to prepare.",
        "pdf_check": "Whoever receives the PDF or JSON can check that it was not edited.",
        "pdf_check_link": "How they check",
        "switch": "Español",
        "my_account": "My account",
        "yes": "yes",
        "no": "no",
        "redeem": "Have an access code? Enter it to see the full report",
        "redeem_button": "Redeem code",
        "code_error": (
            "That code did not unlock the report: it does not exist, was already used "
            "or has expired. Copy it exactly as you received it and redeem it again."
        ),
        "code_error_contact": "If it still does not work, message us with the button above.",
        "buy_code": "Buy on WhatsApp",
        "buy_code_how": (
            "You message us on WhatsApp; the message already carries this report's number.|"
            "We reply with the payment details.|"
            "Once the payment is confirmed you get a code: enter it below and the full "
            "report opens."
        ),
        "buy_code_wait": (
            "A person replies. If you write at night or at the weekend, we answer as soon as "
            "we see it; meanwhile your report stays at this link."
        ),
        "generic_rules": "Generic reference rules, not any one firm's terms.",
        "unlock_jump": "Unlock the full report",
        "unlock_nav": "Unlock",
        "account": "The account's real money",
        "test_data": "What data the test ran on",
        "capital": "How much capital it needs, at what size",
        "plateau": "Lone peak or plateau?",
        "plateau_intro": (
            "We compare the chosen settings with those one step away on each parameter in your "
            "optimisation file. If moving one parameter by one step sinks the result, the "
            "settings were fitted to the history's noise."
        ),
        "plateau_by_report": "Chosen: the pass matching the tester report's inputs.",
        "plateau_by_best": (
            "Chosen: the pass with the highest profit, because the report has no inputs "
            "matching a pass."
        ),
        "plateau_keep": "Of the chosen profit the neighbours keep (median).",
        "plateau_in_profit": "Of the neighbours end with a profit.",
        "plateau_neighbours": "Neighbours one step away",
        "plateau_parameter": "Parameter",
        "plateau_value": "Value",
        "plateau_result": "Profit",
        "plateau_clean": "The neighbours keep much of the result: it looks like a plateau.",
        "plateau_peak": (
            "The neighbours lose much of the result: it looks like a lone peak. "
            "It also shows among the red flags."
        ),
        "plateau_badge_clean": "Plateau",
        "plateau_badge_peak": "Lone peak",
        "plateau_forward_hint": (
            "If you turn on the forward period in the MT5 tester and upload that optimisation, "
            "the report adds \u201cDoes it hold in the forward period?\u201d: it compares every "
            "pass on the optimised period and on a later one the optimiser did not use to choose."
        ),
        "forward": "Does it hold in the forward period?",
        "forward_intro": (
            "MetaTrader can run the same settings on a later period the optimiser did not use "
            "to choose (forward). We compare the order the backtest gives with what happens "
            "afterwards in that period."
        ),
        "forward_rank": (
            "Rank correlation between backtest and forward (1 = same order, 0 = no relation)."
        ),
        "forward_top": "Of the {n} best backtest passes end the forward period with a profit.",
        "forward_all": "Of all passes end the forward period with a profit.",
        "forward_chosen": "Of the other passes land below the chosen one in the forward period.",
        "forward_held": "The best backtest passes stay ahead in the forward period.",
        "forward_lost": (
            "The backtest's order does not hold in the forward period. "
            "You will also see it in the red flags."
        ),
        "forward_badge_held": "Holds",
        "forward_badge_lost": "Does not hold",
        "capital_intro": (
            "How much money it takes so that a bad year does not take more than a given share "
            "of the account, with this file's trades. We drew {samples:,} years of trades at "
            "random and took the fall only 5 % of them exceed, or the history's own if larger."
        ),
        "capital_fall": "Reference fall in money, at the backtest's size.",
        "capital_history": "Deepest fall of the history in its own order.",
        "capital_platform": "Platform drawdown with open trades.",
        "capital_short": (
            "Warning: the file covers only {days} days. These figures stretch that stretch to a "
            "year and can fall short or overshoot; read them as an order of magnitude and ask "
            "for at least a year of history before settling the capital."
        ),
        "capital_limit": "If you accept losing up to",
        "capital_needed": "Capital needed at the backtest's size",
        "capital_scale": "Size on the file's starting balance ({balance})",
        "capital_scale_plain": "Size on the starting balance",
        "capital_scale_help": (
            "1x is the backtest's lot size; 0.50x is half of it. Above 1x the fall in money "
            "grows in the same proportion."
        ),
        "capital_fall_account": "Reference fall in money, at the size the account used.",
        "capital_needed_account": "Capital needed at the size the account used",
        "capital_scale_help_account": (
            "1x is the lot size the account used; 0.50x is half of it. Above 1x the fall in "
            "money grows in the same proportion."
        ),
        "capital_open_loss": (
            "Your platform prints a {platform} drawdown with open trades, against {closed} "
            "with closed trades. This section sees closed trades only: with the open losses "
            "it takes more capital than the table shows."
        ),
        "capital_open_loss_floored": (
            "Your platform prints a {platform} drawdown with open trades, against {closed} "
            "with closed trades. So the capital figures use at least the drawdown in money the "
            "platform prints with open trades."
        ),
        "capital_closed_only": (
            "It counts closed trades only: losses of positions while they were still open are "
            "not included, so the capital needed may be larger."
        ),
        "what_to_do": "What to do:",
        "capital_missing": (
            "To work out the capital and the size, upload at least 30 closed trades spread "
            "over 3 months or more of the same system; a full year makes the figures firmer."
        ),
        "test_data_intro": (
            "The report header says how prices were simulated, how much of the history the "
            "tester had and which dates were tested. It is worth verifying, so here it is "
            "checked against its own trades."
        ),
        "test_data_clean": ("The modelling mode, data quality and stated dates raise no flag."),
        "test_data_scope": (
            "Read from the header as uploaded: an edit is caught only when the header does not "
            "fit itself or the trades."
        ),
        "account_intro": (
            "The percentage gain track-record sites show takes deposits and withdrawals out. "
            "Here it sits next to the money the account made or lost by trading, deposits "
            "made in a deep drawdown, and positions still open when the history was printed."
        ),
        "account_backtest": (
            "This review is for real or demo account histories from MetaTrader 4 or 5. "
            "Your file is a backtest."
        ),
        "account_gain": "Percentage gain, as track-record sites show it.",
        "account_money": "Trading result, in money, on {deposited} deposited.",
        "account_floating": "Open loss over the balance when the history was printed.",
        "account_clean": (
            "We saw no deposit in a deep drawdown, no large open loss and no percentage that "
            "departs from the money."
        ),
        "account_clean_unseen": (
            "We saw no deposit in a deep drawdown and no percentage that departs from the "
            "money. The file does not say how much the open positions were losing: ask the "
            "provider for the equity curve with floating results."
        ),
        "account_live": (
            "Review of the history you uploaded as the live account. Its flags are shown "
            "here and do not change the backtest's class."
        ),
        "account_deposits": "Deposits after trading began, largest first",
        "account_date": "Date",
        "account_amount": "Amount",
        "account_before": "Balance before",
        "account_drawdown": "Drawdown then",
        "account_scope": "Read from the file as uploaded; nothing was checked with the broker.",
        "account_trimmed_badge": "To ask",
        "account_near_empty": (
            "On {date} a trade won or lost more than a withdrawal had left in the account: it "
            "was traded on an almost empty account ({days}). A percentage on almost nothing "
            "explodes, so we measure those days on the balance before the withdrawal. Ask why "
            "almost everything was withdrawn and trading went on with what was left."
        ),
        "account_near_empty_days": "{n} day",
        "account_near_empty_days_many": "{n} days",
        "account_trimmed": (
            "The file opens with trades on {date}, without the deposit that funded the account: "
            "the start of the history may be missing. The % gain is measured from the file's "
            "first balance. Ask for the full export from the day the account opened."
        ),
        "luck": "What is left once luck is discounted?",
        "luck_intro": (
            "The more configurations are tried, the higher the best one comes out even when "
            "none has an edge. Here the file's Sharpe sits next to what pure luck would give "
            "with the configurations counted, using the published math of Bailey and López de "
            "Prado and of Harvey and Liu. It is the same calculation that decides the "
            '"Number of settings tried" dimension, in numbers.'
        ),
        "luck_badge_beats": "Beats luck",
        "luck_badge_below": "Does not beat luck",
        "luck_badge_narrow": "Beats luck, without margin",
        "luck_narrow": (
            "The Sharpe of {sharpe} beats the {luck} that {n} settings with no skill would "
            "show, but not by the margin we ask: the confidence that it is not luck (DSR) is "
            "{dsr}, and passing this dimension needs {need}."
        ),
        "luck_beats": (
            "The Sharpe of {sharpe} beats the {luck} that {n} settings with no skill would show."
        ),
        "luck_below": (
            "With {n} settings, pure luck would show a Sharpe of {luck}, as much as or more "
            "than this history's {sharpe}."
        ),
        "luck_sharpe": "Sharpe {n} settings with no skill would show (the file's: {sharpe})",
        "luck_years": (
            "Years of history at which that luck falls below this Sharpe (the file has {span})"
        ),
        "luck_after": "Sharpe left after discounting {n} settings (Harvey and Liu)",
        "luck_years_unit": "years",
        "luck_uncounted": (
            "The files do not say how many configurations were tried before this one was "
            "picked. The table shows how much history each search size would need: ask the "
            "vendor."
        ),
        "luck_span_line": "The file's Sharpe: {sharpe}. History: {span}.",
        "luck_table_trials": "Configurations tried",
        "luck_table_luck": "Sharpe luck would show",
        "luck_table_years": "History needed",
        "luck_table_enough": "Is this history enough?",
        "luck_short": (
            "With under a year of history, an annualised Sharpe moves a lot on little data: "
            "read it as an order of magnitude."
        ),
        "luck_more_than": "over {n} years",
        "luck_months": "{n} months",
        "luck_month_one": "1 month",
        "luck_under_month": "under 1 month",
        "ride": "What living through this history was like",
        "ride_intro": (
            "A total and a maximum drawdown do not say what the history was like to live "
            "through: how long it went without a new high, how long the worst fall took to "
            "come back, and what the worst day and month were. These are the numbers that "
            "make people switch a system off."
        ),
        "ride_days": "{n} days",
        "ride_under": "Longest time without a new high ({start} to {end})",
        "ride_under_open": "Time without a new high since {start}: still open at the file's end",
        "ride_fall": "Worst fall: days from the high ({start}) to the low ({low})",
        "ride_recovery": "Days from that low back to the high",
        "ride_not_back": "not back",
        "ride_not_back_note": "The worst fall is not regained by the file's last date.",
        "ride_worst_day": "Worst day ({date})",
        "ride_worst_month": "Worst month ({month})",
        "ride_positive": "Months that ended up ({k} of {n}); longest run of losing months: {run}",
        "ride_closed": (
            "The curve is rebuilt from closed trades: open losses do not show, so the real "
            "falls lasted and measured at least this much."
        ),
        "recent": "Does it still work in the recent period?",
        "recent_intro": (
            "A long history can look good in total while its last stretch no longer adds up. "
            "We cut the history's time in three equal stretches and compare the last one with "
            "the two before it, trade by trade."
        ),
        "recent_early": "Average per trade before {date}",
        "recent_late": "Average per trade since {date}",
        "recent_net": "Net result since {date} ({n} trades)",
        "recent_z": (
            "Distance between the two averages, in standard errors (-2 or lower: a drop "
            "chance hardly explains)"
        ),
        "recent_held": (
            "The last third of the history shows no drop into losses beyond what chance explains."
        ),
        "recent_faded": (
            "The last third of the history averages zero or a loss per trade, a drop chance "
            "hardly explains. You will also see it in the red flags."
        ),
        "recent_badge_held": "Holds",
        "recent_badge_weaker": "Weaker",
        "recent_weaker": (
            "The average per trade fell from {early} to {late} ({change}) in the last third. "
            "It stays above zero and the drop is within what chance explains, but it is "
            "worth watching."
        ),
        "recent_badge_faded": "Fades",
        "recent_year": "Exit year",
        "fund": "What a fund investor would check",
        "fund_intro": (
            "A fund factsheet's figures and two tests fund analysts use: whether the monthly "
            "returns are smoothed and whether months with a small loss are missing. It does "
            "not change the class: these are questions to ask."
        ),
        "fund_year": "Year",
        "fund_total": "Full year",
        "fund_months": "Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec",
        "fund_cagr": "Compound annual return",
        "fund_vol": "Annual volatility",
        "fund_vol_u": "Annual volatility unsmoothed (before: {vol})",
        "fund_positive": "Positive months ({n} months)",
        "fund_worst": "Worst month (best: {best})",
        "fund_dd": "Deepest fall",
        "fund_under": "Months in a row below a previous high",
        "fund_under_open": "Months in a row below a previous high (not yet recovered)",
        "fund_losing": "Losing months in a row, at most",
        "fund_smoothed": (
            "Each month looks too much like the one before (autocorrelation of {rho}). That "
            "is typical of illiquid or late-priced holdings, and it makes volatility look "
            "lower: unsmoothed it would be {vol_u} a year instead of {vol}. Ask how and how "
            "often the positions are valued."
        ),
        "fund_few_small_losses": (
            "There are many months with a small gain and very few with a small loss ({gains} "
            "against {losses}), fewer than the neighbouring months lead you to expect. Studies "
            "of funds link that pattern to valuations that avoid closing a month negative. Ask "
            "who calculates the net asset value and whether a third party checks it."
        ),
        "fund_clean": "No smoothing and no shortage of months with a small loss.",
        "fund_badge_clean": "No pattern",
        "fund_bench": "Against its benchmark",
        "fund_bench_file": (
            "From {first} to {last}, {n} months shared with the benchmark the file itself "
            "carries, with its figures as they come."
        ),
        "fund_bench_upload": (
            "From {first} to {last}, {n} months shared with the benchmark file you uploaded."
        ),
        "fund_bench_gross": ("If the fund's figures are before fees, this comparison flatters it."),
        "fund_fees": "How much would fees take?",
        "fund_fees_intro": (
            "The figures were not declared net of fees. This is the same history with the "
            "yearly fees an active fund commonly charges, taken out month by month."
        ),
        "fund_fees_rate": "Yearly fee",
        "fund_fees_cagr": "Yearly return",
        "fund_fees_growth": "Total growth",
        "fund_fees_none": "No fee",
        "fund_fees_management": (
            "Management fees only. Many funds also take a performance fee, often 20 % of "
            "gains, so the 2.5 % row is not the worst case."
        ),
        "fund_fees_break_even": (
            "At a fee of {rate} a year or more, the fund would have ended level with or below "
            "its benchmark over the months they share."
        ),
        "fund_fees_behind": (
            "The fund already ends level with or below its benchmark before any fee."
        ),
        "fund_bench_excess": "Annual difference against the benchmark (fund {fund}, index {index})",
        "fund_bench_beat": "Months it beat the benchmark",
        "fund_bench_te": "Annual tracking error (information ratio {ir})",
        "fund_bench_beta": "Beta to the benchmark (correlation {corr})",
        "fund_bench_up": "Up capture: share of the benchmark's rises it takes",
        "fund_bench_down": "Down capture: share of the benchmark's falls it takes",
        "fund_bench_trails": (
            "It returned less than its benchmark: {excess} a year over the shared months. Ask "
            "what justifies paying for active management over an index fund."
        ),
        "fund_bench_index_like": (
            "It follows its benchmark very closely (correlation {corr}, tracking error {te} a "
            "year), what studies call closet indexing. Ask what its fees buy that an index fund "
            "does not."
        ),
        "fund_bench_worse": (
            "It takes less of the benchmark's rises ({up}) and more of its falls ({down}). Ask "
            "in which kind of market the manager expects to do better."
        ),
        "fund_bench_clean": (
            "Ahead of its benchmark over the shared months, without tracking it like an index fund."
        ),
        "fund_bench_badge_clean": "Ahead",
        "fund_bench_nm": "Comparison with the benchmark:",
        "fund_stress": "How did it do in the known crises?",
        "crises": "How did it do in the known crises?",
        "crises_intro": (
            "The curve's return, from its month-end balances, through each market fall on the "
            "public record that it covers in full (the market's peak to its trough). A month "
            "with no trades counts as flat. The dates are fixed: they are not fitted to the file."
        ),
        "crises_subject": "Strategy",
        "holding": "Does it beat buying and holding the market?",
        "holding_intro": (
            "The strategy trades mostly the {label}. These are its daily closes beside simply "
            "buying and holding the {label} on the same days, from {first} to {last} ({days} "
            "days). The Sharpe ratio measures what each unit of risk pays: it does not change "
            "with position size, so it compares a leveraged strategy fairly with the unleveraged "
            "market."
        ),
        "holding_not_measured": "No comparison with the {label}: {reason}.",
        "holding_strategy": "Strategy",
        "holding_market": "Holding the {label}",
        "holding_return": "Return over the period",
        "holding_drawdown": "Worst fall",
        "holding_sharpe": "Sharpe on the same {days} days (return per unit of risk)",
        "holding_together": (
            "Weekly correlation (Friday to Friday) with the {label}: {corr}. For each 1 % the "
            "market moved in a week, the strategy moved {beta} % on average. Weeks are used "
            "because the file's closing time and the market's may not match."
        ),
        "holding_no_clear_edge": (
            "The Sharpe gap ({z} standard errors, measured on weekly returns) is not enough "
            "to say it beats the market."
        ),
        "holding_rides": (
            "It moves almost in step with the {label} and shows no clear edge over holding "
            "it: the Sharpe gap is within the noise of {weeks} weeks. What does it add over "
            "buying the market and waiting?"
        ),
        "holding_closed_only": (
            "The file only has the balance at each close: days with open positions are not "
            "seen, so the strategy's correlation and worst fall read short."
        ),
        "holding_source": (
            "{label} closes: public {source} data read when the report was made. No "
            "cash rate is subtracted in either Sharpe ratio. It does not change the class."
        ),
        "regime": "How did it do in calm and in turbulent markets?",
        "regime_intro": (
            "Each return in the file is placed by the VIX (how much the options market expects "
            "the S&P 500 to move over the next month) at the close of the market day before it "
            "starts: a calm market below 20, a turbulent one from 20. Since 1990 the VIX has "
            "closed at 20 or more on about one day in three. Period: {first} to {last}."
        ),
        "regime_not_measured": "No split by the VIX: {reason}.",
        "regime_calm": "Calm market (VIX < 20)",
        "regime_turbulent": "Turbulent market (VIX ≥ 20)",
        "regime_time": "Share of the time",
        "regime_returns": "Returns counted",
        "regime_monthly": "Return per month (compounded)",
        "regime_sharpe": "Sharpe (return per unit of risk)",
        "regime_better_calm": (
            "It did better in calm markets: the gap in mean return ({z} standard errors) "
            "is larger than the noise."
        ),
        "regime_better_turbulent": (
            "It did better in turbulent markets: the gap in mean return ({z} standard "
            "errors) is larger than the noise."
        ),
        "regime_no_clear_gap": (
            "The gap in mean return between the two columns ({z} standard errors) is not "
            "enough to say it behaves differently depending on the market."
        ),
        "regime_source": (
            "VIX: public data from {source} (series VIXCLS, from CBOE) read when the report "
            "was made. It measures US equities: if the strategy trades another market, read "
            "it as a general gauge of fear in markets. It does not change the class."
        ),
        "crises_market": "Market over those months",
        "crises_market_note": (
            "Market: the close of the month before the window against the close of its last "
            "month, public FRED data read on {as_of} ({sources}). These are US equities and "
            "bitcoin: if the strategy trades another market (currencies, commodities, another "
            "country), take them only as context for what the market went through, not as its "
            "yardstick."
        ),
        "crises_no_trades": "no trades closed in the window",
        "crises_worse": (
            "In {worse} of {n} crises it fell more than its benchmark. Ask the seller what "
            "protects it when markets fall."
        ),
        "fund_stress_intro": (
            "The fund's return through each market fall on the public record that its history "
            "covers in full (the market's peak to its trough). The dates are fixed: they are not "
            "fitted to the file."
        ),
        "fund_stress_none": (
            "The history does not cover any fall on the list in full (dot-com, 2008, euro 2011, "
            "2015-16, late 2018, covid, 2022, crypto 2022)."
        ),
        "fund_stress_head": "Crisis",
        "fund_stress_fund": "Fund",
        "fund_stress_index": "Index",
        "fund_stress_12m": (
            "Worst 12 months in a row: {worst}; best: {best}. {share} of the 12-month periods "
            "ended positive."
        ),
        "fund_stress_worse": (
            "In {worse} of {n} crises it fell more than its benchmark. Ask what protects the "
            "portfolio when markets fall."
        ),
        "fund_stress_dotcom": "Dot-com bust",
        "fund_stress_gfc": "2008 financial crisis",
        "fund_stress_euro": "Euro debt crisis",
        "fund_stress_china_oil": "China and the oil fall",
        "fund_stress_late_2018": "Late 2018",
        "fund_stress_covid": "Covid crash",
        "fund_stress_rates_2022": "Inflation and rates, 2022",
        "fund_stress_crypto_2022": "Crypto winter 2022",
        "instruments": "Does it work on each instrument?",
        "ins_intro": (
            "When a robot or a signal trades several markets, the total can come from one of "
            "them while the others lose. It does not change the class: these are questions to ask."
        ),
        "ins_head": "Instrument",
        "ins_other": "Others ({n} with fewer than {m} trades)",
        "ins_best": "Share of the net result that comes from {best}",
        "ins_one_carries": (
            "One instrument carries the result: without {best}, the others together net zero "
            "or a loss. Ask why the others are traded."
        ),
        "ins_mostly_one": (
            "Almost all of the result comes from {best} ({share}). Ask what the others add."
        ),
        "ins_best_over": "More than the net result comes from {best}: the others together subtract",
        "ins_most_lose": (
            "Most instruments end at zero or a loss ({losing} of {readable}). Ask whether the "
            "strategy was fitted to a few markets."
        ),
        "ins_clean": "No single instrument carries the result on its own.",
        "ins_badge_clean": "Spread out",
        "behaviour": "How it behaves after losing",
        "behaviour_intro": (
            "What a trading journal would tell you: whether losses are held longer than gains, "
            "whether a new trade follows a loss quickly, and how trades do after a losing "
            "streak. It does not change the class: these are questions to ask."
        ),
        "beh_hold": (
            "How long a losing trade lasts against a winning one (median: {loss} against {win})"
        ),
        "beh_quick": ("Trades after a loss opened within 15 minutes of it (after a win: {win})"),
        "beh_streak": "Win rate after {k} losses in a row ({n} trades; whole history: {all})",
        "beh_losers_held_longer": (
            "Losing trades stay open much longer than winning ones. Ask where the stop is and "
            "whether it moves."
        ),
        "beh_quick_after_loss": (
            "A new trade follows a loss quickly. Ask what rule holds back the next trade "
            "after a loss."
        ),
        "beh_worse_after_streak": (
            "It wins less often after a losing streak. Ask whether size or rules change "
            "during those streaks."
        ),
        "beh_quick_nm": "Quick re-entry after a loss:",
        "beh_clean": "Nothing stands out in how it trades after losing.",
        "beh_badge_clean": "No pattern",
        "beh_badge_found": "To ask",
        "timing": "When it wins and when it loses",
        "timing_intro": (
            "Your trades grouped by entry day and time. If nearly all the result comes from "
            "one day or one session, a change of server time, holidays or news can erase it."
        ),
        "timing_best_day": "{share:.0%} of the net result comes from {day}s.",
        "timing_best_block": "{share:.0%} of the net result comes from the {block} session.",
        "timing_day": "Entry day",
        "timing_block": "Entry time",
        "timing_trades": "Trades",
        "timing_net": "Net result",
        "timing_hits": "Win rate",
        "live": "Backtest against the live account",
        "live_intro": (
            "If the live account's trades came from the same backtest, how unusual would its "
            "result be? We drew backtest trades at random, as many as the live account holds, "
            "{samples:,} times, and placed the live account among those histories."
        ),
        "live_CONSISTENT": (
            "The live account behaves like the backtest: its net result and its deepest fall "
            "lie within what the backtest led to expect."
        ),
        "live_EDGE": (
            "The live account is at the edge: its net result or its deepest fall is worse "
            "than in 95 % of the backtest's histories. It may be a bad streak, but it deserves "
            "questions to the seller."
        ),
        "live_INCONSISTENT": (
            "The live account does not behave like the backtest: its net result or its "
            "deepest fall is worse than in 99 % of the backtest's histories."
        ),
        "live_ABOVE": (
            "The live account sits above 99 % of the backtest's histories. A result like "
            "this usually means the two files do not share the same configuration, size or "
            "account: ask."
        ),
        "hero_live": "Live account: {badge}.",
        "hero_live_money": "Trading result: {result} on {deposits} deposited.",
        "hero_live_link": "See the comparison with the backtest",
        "live_badge_CONSISTENT": "Consistent",
        "live_badge_EDGE": "At the edge",
        "live_badge_INCONSISTENT": "Not consistent",
        "live_badge_ABOVE": "Check",
        "live_col_backtest": "Backtest",
        "live_col_live": "Live account",
        "live_col_live_rescaled": "Live, at the backtest's size",
        "live_col_expected": "Expected range (90 %)",
        "live_trades": "Trades",
        "live_period": "Period",
        "live_per_month": "Trades per month",
        "live_win_rate": "Win rate",
        "live_net": "Net result",
        "live_fall": "Deepest fall",
        "live_avg_win": "Average win",
        "live_avg_loss": "Average loss",
        "live_below": "Backtest histories with a net result as low or lower",
        "live_fall_above": "Backtest histories with a fall as deep or deeper",
        "live_rescaled": (
            "The live account trades {ratio:.2f} times the backtest's size: each live trade "
            "was scaled to the backtest's median size before comparing."
        ),
        "live_same_size": "Same position size (±25 %): compared as traded.",
        "live_pace": (
            "The live account makes {ratio:.1f} times the backtest's trades per month: it may "
            "not be the same configuration."
        ),
        "live_overlap": (
            "Part of the live account falls inside the backtest's period: those dates may "
            "have been used to fit the backtest, so the comparison is less demanding."
        ),
        "live_symbols": "The live account trades symbols the backtest lacks: {symbols}.",
        "live_pair": "Same dates, trade by trade",
        "live_pair_intro": (
            "From {start} to {end} both files cover the same days. Each live trade was "
            "looked up in the backtest: same side, same symbol and an entry less than 60 "
            "minutes apart."
        ),
        "live_pair_found": "Live trades found in the backtest",
        "live_pair_of": "{matched} of {total} ({share})",
        "live_pair_missing": "Backtest trades the live account did not take",
        "live_pair_entry": "Median price difference at entry",
        "live_pair_exit": "Median price difference at exit",
        "live_pair_gap": "Result difference on the paired trades",
        "live_pair_gap_value": "{total} ({each} per trade)",
        "live_pair_bps": "{bps} bp",
        "live_pair_low": (
            "Fewer than half the live trades appear in the backtest on those dates: it is "
            "probably not the same configuration. Ask the seller for that account's exact "
            "backtest."
        ),
        "live_pair_help": (
            "bp = basis points (0.01 % of the price); positive is worse for the account. The "
            "result difference is at the backtest's size; negative is what the live account "
            "made below the backtest on the same trades."
        ),
        "reading": "How your file was read",
        "reading_intro": (
            "Before analysing anything, we re-counted your trades row by row and compared "
            "them with the summary your platform prints."
        ),
        "reading_platform": "Your platform",
        "reading_rows": "Read from the rows",
        "reading_ok": "Matches",
        "reading_bad": "Does not match",
        "reading_all_ok": "Everything matches: the analysis starts from the same numbers you see.",
        "reading_some_bad": (
            "Something does not match. Check the reading notes further down and, if you think "
            "your file was misread, write to us with the report id."
        ),
        "boot_line": "Stationary block bootstrap, resamples:",
        "boot_block": "block",
        "point": "Estimate",
        "engine": "engine version",
        "seed": "simulation seed",
        "code_request": f"Hello, I would like a {BRAND} code for report {{id}}.",
        "code_request_price": (
            f"Hello, I would like to buy the full {BRAND} report {{id}} ({{price}}). How do I pay?"
        ),
        "keep_link": (
            "Save this page's link: it brings you back to your report. If you uploaded it with "
            "your account, it is also in «My account»."
        ),
        "pack": "pack of 3 reports: USD {price:.0f}",
        "buy_includes": (
            "Every figure in every section|A PDF to keep or send|"
            "A public verification page to share|"
            "A refund if the report misreads your file"
        ),
        "publish": "Publish a public verification",
        "publish_help": (
            "Creates a public page with the class, the dimensions and the hashes, and a badge "
            "for your site. It never shows your files, trades or description."
        ),
        "evidence_legend": (
            "Every figure carries its tag: MEASURED, computed from your files; DECLARED, "
            "stated by you or the seller, not verified; NOT_MEASURED, a piece was missing to "
            "compute it."
        ),
        "next": "What to do now",
        "next_intro": (
            "If you bought or are about to buy this robot or signal, this is what is worth "
            "clearing up first, from what the audit found."
        ),
        "next_live": (
            "Ask the seller why your live account falls outside what the backtest led you "
            "to expect."
        ),
        "next_costs": (
            "Compare your broker's spread and commission with the costs the result can bear: "
            "a cost a little above the reference erases the margin."
        ),
        "next_costs_fail": (
            "Compare your broker's spread and commission with the reference cost: at that "
            "cost the trades already lose money net."
        ),
        "next_trials": (
            "Ask how many configurations were tried before this one was chosen, and on which "
            "period it was chosen."
        ),
        "next_oos": (
            "Ask for a report of the same robot, unchanged, on dates after its optimisation."
        ),
        "next_flags": "Read the red flags: they mark figures that cannot be taken as they stand.",
        "next_questions": "Take this report's questions to the seller.",
        "next_keep": (
            "Keep this report and its identifier; if the robot changes, ask for a new audit."
        ),
        "next_link": "Go to the section",
        "meaning": "What this means for you",
        "ladder": "What each class requires",
        "ladder_intro": (
            "The class does not measure how much the backtest made, but how many questions "
            "your files answer. A better class does not mean the strategy will work."
        ),
        "ladder_class": "Class",
        "ladder_needs": "What it takes",
        "ladder_you": "Your report",
        "charts": "Charts",
        "detail_heading": "Detail",
        "locked_intro": (
            "The verdict, charts and explanations are free. The full report tells you, with "
            "your file's figures"
        ),
        "sample_full": "See what a full report looks like (sample built from synthetic data)",
        "trade_stats": "Trade statistics",
        "streak_line": (
            "At the same share of losing trades and in random order, the longest losing "
            "run is typically {chance} in a row, and 1 history in 20 reaches {rare}. "
            "This history had {observed}."
        ),
        "streak_clustered": (
            "The losses came closer together than chance explains: a run like this shows "
            "up in fewer than 1 in 20 random orders. It usually points to losses that "
            "depend on the kind of market, or to positions open at the same time."
        ),
        "long": "Long",
        "short": "Short",
        "risk": "Resampled one-year risk",
        "risk_dd": "Maximum drawdown over one year",
        "risk_prob": "Probability of a fall of at least",
        "risk_underwater": "Consecutive periods below the peak, in the simulations",
        "risk_under_median": "median",
        "risk_under_p95": "in 1 of every 20",
        "challenge": "Prop-firm challenge simulator",
        "challenge_rules": "Rules simulated",
        "open_loss_badge": "Open losses",
        "hidden_loss": (
            "The file shows the balance only, and the red flags found open losses the balance "
            "hides (Hidden floating drawdown). They are not counted here, so these figures come "
            "out optimistic: do not decide with them without the equity curve with floating "
            "results."
        ),
        "challenge_open_loss": (
            "Your platform prints a {dd} drawdown with open trades, deeper than the "
            "challenge's total loss limit ({limit}). The simulation uses the closed-trade "
            "balance, which does not see those open losses: with them the challenge account "
            "may have hit the limit."
        ),
        "outcome": "Outcome",
        "probability": "In the simulations of the history",
        "pass": "Reaches the target",
        "fail_daily_loss": "Breaks the daily loss limit",
        "fail_total_loss": "Breaks the total loss limit",
        "unfinished": "Does not finish in time",
        "ci95": "95 % interval of reaching the target",
        "days_to_target": "Business days to the target (p25 / p50 / p75)",
        "best_day_line": (
            "This firm's best-day rule: in {share} of the passes, the best day is above the "
            "limit. Depending on the firm, that raises the target or blocks the withdrawal."
        ),
        "ff_title": "Which firm's rules does your history fit?",
        "ff_intro": (
            "The same history, resampled the same way, under each firm's published rules, "
            "from most to least likely to pass every phase of the program within the best-day "
            "rule, where the firm has one; ties go by name. It compares rules; it does not "
            "recommend buying any challenge."
        ),
        "ff_program": "Challenge",
        "ff_pass": "Passes",
        "ff_clean": "Passes within the best-day rule",
        "ff_risk": "What stops it most",
        "ff_no_rule": "no rule",
        "ff_risk_none": "Nothing in the simulations",
        "ff_risk_fail_daily_loss": "breaking the daily loss limit",
        "ff_risk_fail_total_loss": "breaking the total loss limit",
        "ff_risk_unfinished": "not reaching the target in time",
        "ff_optimistic": (
            "The same optimistic figures as above apply to this table: the balance hides open "
            "losses."
        ),
        "ff_all_pass": (
            "With this history every program passes in at least 99 % of the simulations: their "
            "rules do not tell them apart."
        ),
        "ff_all_fail": (
            "With this history almost no program passes (1 % of the simulations or less); "
            "what stops it most is {risk}."
        ),
        "ff_phases": "{n} phases",
        "ff_phase": "1 phase",
        "assumptions": "Assumptions",
        "source": "Source",
        "as_of": "read on",
        "questions": "Questions to ask the vendor",
        "flags_free": "Red flags found",
        "report_source": "File format",
        "platform": "Figures the platform states",
        "colmap": "How each column of your file was read",
        "optimization": "Optimisation export",
        "passes": "configurations tried",
        "trials_used": "Trials used in the deflated Sharpe",
        "horizon": "1 year",
        "reasons_detail": "Technical detail by dimension",
        "fees": "Costs the report itemises",
        "plan": "Plan to reach a better class",
        "plan_intro": (
            "What the audit's rules would need to see in each open dimension, most decisive "
            "first. A better class means the files answer more questions, not that the "
            "strategy will work."
        ),
        "plan_class": "If this dimension passed and the rest stayed the same, the class would be",
        "plan_none": "Every dimension passes: no step is left open.",
        "plan_locked": "concrete steps, with your file's figures, in the full report",
        "kpis": "Executive summary",
        "toc": "Report sections",
        "toc_unlock": "Full report",
        "kpis_locked": "Your file's key figures are shown in the full report.",
        "kpi_return": "Total return",
        "kpi_drawdown": "Maximum drawdown",
        "kpi_dd_platform": "Drawdown with open trades, per your platform",
        "kpi_dd_p95": "Resampled drawdown p95, 1 year",
        "kpi_drawdown_closed": "Maximum drawdown (closed trades only)",
        "kpi_dd_p95_closed": "Drawdown p95, 1 year (closed trades only)",
        "kpi_sharpe": "Annualised Sharpe",
        "kpi_pf": "Profit factor",
        "kpi_trades": "Trades · win rate",
        "kpi_breakeven": "Extra cost that takes it to zero",
        "kpi_breakeven_negative": "already negative before any extra cost",
        "kpi_stress": "Without the best 5 trades",
        "kpi_stress_curve": "Without the best 5 periods",
        "kpi_hint_return": "how much the account changed over the whole history",
        "kpi_hint_drawdown": "the worst fall from a peak",
        "kpi_hint_dd_p95": "a fall exceeded in 1 of every 20 simulated years",
        "kpi_hint_sharpe": "return against its ups and downs; higher is steadier",
        "cash_sharpe": (
            "After subtracting what cash in dollars paid over the same dates (3-month US "
            "Treasury bills, {rate} a year on average), the Sharpe is {sharpe}."
        ),
        "cash_below": (
            "It earned less than cash in dollars over those dates ({ret} a year against {rate} "
            "for 3-month Treasury bills)."
        ),
        "cash_note": (
            "The Sharpe above subtracts no rate. If the account is not in dollars, the fair "
            "rate to subtract is its own currency's. Source: {source}."
        ),
        "kpi_hint_pf": "what was won for every 1 lost",
        "kpi_hint_breakeven": "how much more trading can cost before it reaches zero",
        "bps_side": "bps per side",
        "stress": "Stress tests: without the best outcomes",
        "stress_intro": (
            "We remove the best periods and trades from what you uploaded and measure what "
            "is left. If the total falls to zero or below, it rests on a few events that may "
            "not repeat. This is not a forecast."
        ),
        "stress_curve": "On the curve (compounded total return)",
        "stress_trades": "On the closed trades (net result after commission and swap)",
        "scenario": "Scenario",
        "stress_result": "Left",
        "stress_change": "Change",
        "stress_positive": "Still above zero?",
        "original": "Original",
        "stress_count": "of {total} scenarios end at zero or below",
        "top5_share": "The best 5 trades add up to this multiple of the net result",
    },
}

DIMENSION_TITLES: dict[str, dict[str, str]] = {
    "es": {
        "statistical_significance": "Significación estadística",
        "multiplicity": "Número de configuraciones probadas",
        "costs": "Costes",
        "out_of_sample": "Fuera de muestra",
        "data_quality": "Calidad de datos y forma de operar",
        "benchmark": "Benchmark",
    },
    "en": {
        "statistical_significance": "Statistical significance",
        "multiplicity": "Number of settings tried",
        "costs": "Costs",
        "out_of_sample": "Out of sample",
        "data_quality": "Data quality and trading pattern",
        "benchmark": "Benchmark",
    },
}

STATUS_TEXT: dict[str, dict[str, str]] = {
    "es": {
        "PASS": "Supera",
        "WEAK": "Débil",
        "FAIL": "No supera",
        "NOT_MEASURED": "No medido",
        "NOT_APPLICABLE": "No aplica",
    },
    "en": {
        "PASS": "Pass",
        "WEAK": "Weak",
        "FAIL": "Fail",
        "NOT_MEASURED": "Not measured",
        "NOT_APPLICABLE": "Not applicable",
    },
}

#: Reader-facing names of the numeric keys; the key itself when absent.
KEY_LABELS: dict[str, dict[str, str]] = {
    "es": {
        "sharpe_annualised": "Sharpe anualizado",
        "gap": "Diferencia de Sharpe (dentro menos fuera)",
        "seal_id": "Identificador del sello",
        "selection_start": "Inicio de la selección",
        "selection_end": "Fin de la selección",
        "holdout_start": "Inicio del tramo reservado",
        "holdout_end": "Fin del tramo reservado",
        "sealed_at_utc": "Sellado (UTC)",
        "seal": "Sello (sha256)",
        "total_return": "Retorno total",
        "cagr": "Retorno anual compuesto",
        "volatility": "Volatilidad anual",
        "sharpe": "Sharpe",
        "sortino": "Sortino",
        "max_drawdown": "Drawdown máximo",
        "win_rate": "Aciertos",
        "win_rate_gross": "Aciertos antes de comisiones",
        "trade_count": "Operaciones",
        "gross_profit": "Beneficio bruto de las ganadoras",
        "gross_loss": "Pérdida bruta de las perdedoras",
        "fees_total": "Comisiones y swap",
        "net_pnl": "Resultado neto",
        "profit_factor": "Factor de beneficio",
        "expectancy": "Esperanza por operación",
        "average_win": "Ganancia media",
        "average_loss": "Pérdida media",
        "payoff_ratio": "Ratio ganancia/pérdida media",
        "largest_win_share": "Peso de la mayor ganadora",
        "deposits_count": "Depósitos",
        "deposits_total": "Dinero depositado",
        "withdrawals_count": "Retiros",
        "withdrawals_total": "Dinero retirado",
        "later_deposits": "Depósitos después de empezar a operar",
        "trading_result": "Resultado de operar, en dinero",
        "percent_gain": "Ganancia en %",
        "result_on_deposits": "Resultado sobre lo depositado",
        "withdrawn_share": "Parte retirada de lo depositado",
        "top_ups": "Depósitos en plena pérdida",
        "floating_pnl": "Resultado flotante al imprimir",
        "floating_share": "Flotante sobre el balance",
        "tick_model": "Modelado de precios",
        "trades_per_year": "Operaciones por año",
        "chosen_result": "Beneficio de la configuración elegida",
        "passes": "Pasadas de la optimización",
        "passes_in_profit": "Pasadas con beneficio",
        "chosen_top_share": "Posición de la elegida (percentil superior)",
        "neighbours_found": "Vecinos encontrados",
        "neighbours_in_profit": "Vecinos con beneficio",
        "neighbours_keep": "Beneficio que conservan los vecinos",
        "data_quality": "Calidad de datos",
        "tested_from": "Prueba desde",
        "tested_to": "Prueba hasta",
        "trades_outside_window": "Operaciones fuera de esas fechas",
        "mismatched_chart_errors": "Errores de gráficos no coincidentes",
        "tester_spread": "Spread del probador",
        "max_consecutive_wins": "Máximo de ganadoras seguidas",
        "max_consecutive_losses": "Máximo de perdedoras seguidas",
        "losing_run_chance": "Racha máxima normal por azar",
        "losing_run_rare": "Racha máxima por azar, 1 de cada 20",
        "losing_run_odds": "Probabilidad de una racha así por azar",
        "mean_holding_hours": "Horas medias por operación",
        "median_holding_hours": "Horas medianas por operación",
        "sqn": "SQN",
        "trades_per_month": "Operaciones por mes",
        "observations": "Observaciones",
        "psr": "Sharpe probabilístico (PSR)",
        "min_track_record_length": "Historial mínimo necesario",
        "observations_short_by": "Observaciones que faltan",
        "trials": "Intentos",
        "cost_bps_per_side": "Coste por lado (pb)",
        "oos_start": "Inicio fuera de muestra",
        "benchmark_applicable": "Aplica benchmark",
        "initial_balance": "Balance inicial",
        "dsr_at_declared": "DSR con los intentos declarados",
        "dsr_at_trials_used": "DSR con los intentos usados",
        "trials_to_half": "Intentos que bajan el DSR a 0.5",
        "trials_used": "Intentos usados",
        "skewness": "Asimetría",
        "kurtosis": "Curtosis",
        "floor": "Mínimo por error de muestreo",
        "observed_across_variants": "Observado en las variantes",
        "sharpe_variance_used": "Varianza del Sharpe usada",
        "sharpe_per_period": "Sharpe por periodo",
        "break_even_bps": "Coste de equilibrio (pb por lado)",
        "break_even_pips": "Coste de equilibrio (pips por lado)",
        "reference_pips": "Coste de referencia (pips por lado)",
        "platform_equity_drawdown": "Drawdown con operaciones abiertas (tu plataforma)",
        "commission": "Comisión",
        "swap": "Swap",
        "break_even_multiple": "Múltiplo de coste de equilibrio",
        "reference_bps": "Coste de referencia (pb por lado)",
        "dataset_digest": "Huella del conjunto de datos",
    },
    "en": {
        "sharpe_annualised": "Annualised Sharpe",
        "gap": "Sharpe gap (in minus out of sample)",
        "seal_id": "Seal id",
        "selection_start": "Selection start",
        "selection_end": "Selection end",
        "holdout_start": "Holdout start",
        "holdout_end": "Holdout end",
        "sealed_at_utc": "Sealed at (UTC)",
        "seal": "Seal (sha256)",
        "total_return": "Total return",
        "cagr": "Compound annual return",
        "volatility": "Annual volatility",
        "max_drawdown": "Maximum drawdown",
        "win_rate": "Win rate",
        "win_rate_gross": "Win rate before fees",
        "trade_count": "Trades",
        "gross_profit": "Gross profit of winners",
        "gross_loss": "Gross loss of losers",
        "fees_total": "Commission and swap",
        "net_pnl": "Net result",
        "profit_factor": "Profit factor",
        "expectancy": "Expectancy per trade",
        "average_win": "Average win",
        "average_loss": "Average loss",
        "payoff_ratio": "Average win / average loss",
        "largest_win_share": "Share of the largest win",
        "deposits_count": "Deposits",
        "deposits_total": "Money deposited",
        "withdrawals_count": "Withdrawals",
        "withdrawals_total": "Money withdrawn",
        "later_deposits": "Deposits after trading began",
        "trading_result": "Trading result, in money",
        "percent_gain": "Percentage gain",
        "result_on_deposits": "Result on the money deposited",
        "withdrawn_share": "Share of deposits withdrawn",
        "top_ups": "Deposits in a deep drawdown",
        "floating_pnl": "Floating result when printed",
        "floating_share": "Floating result / balance",
        "tick_model": "Price modelling",
        "trades_per_year": "Trades per year",
        "chosen_result": "Profit of the chosen settings",
        "passes": "Optimisation passes",
        "passes_in_profit": "Passes with a profit",
        "chosen_top_share": "Chosen pass position (top share)",
        "neighbours_found": "Neighbours found",
        "neighbours_in_profit": "Neighbours with a profit",
        "neighbours_keep": "Profit the neighbours keep",
        "data_quality": "Data quality",
        "tested_from": "Tested from",
        "tested_to": "Tested to",
        "trades_outside_window": "Trades outside those dates",
        "mismatched_chart_errors": "Mismatched chart errors",
        "tester_spread": "Tester spread",
        "max_consecutive_wins": "Most consecutive wins",
        "max_consecutive_losses": "Most consecutive losses",
        "losing_run_chance": "Typical longest losing run by chance",
        "losing_run_rare": "Longest losing run by chance, 1 in 20",
        "losing_run_odds": "Chance of a run this long",
        "mean_holding_hours": "Mean hours per trade",
        "median_holding_hours": "Median hours per trade",
        "trades_per_month": "Trades per month",
        "psr": "Probabilistic Sharpe (PSR)",
        "min_track_record_length": "Minimum track record needed",
        "observations_short_by": "Observations missing",
        "cost_bps_per_side": "Cost per side (bps)",
        "oos_start": "Out-of-sample start",
        "benchmark_applicable": "Benchmark applies",
        "initial_balance": "Initial balance",
        "dsr_at_declared": "DSR at the declared trials",
        "dsr_at_trials_used": "DSR at the trials used",
        "trials_to_half": "Trials that bring DSR to 0.5",
        "trials_used": "Trials used",
        "trials": "Trials",
        "observations": "Observations",
        "sharpe": "Sharpe",
        "sortino": "Sortino",
        "sqn": "SQN",
        "skewness": "Skewness",
        "kurtosis": "Kurtosis",
        "floor": "Sampling-error floor",
        "observed_across_variants": "Observed across variants",
        "sharpe_variance_used": "Sharpe variance used",
        "sharpe_per_period": "Sharpe per period",
        "break_even_bps": "Break-even cost (bps per side)",
        "break_even_pips": "Break-even cost (pips per side)",
        "reference_pips": "Reference cost (pips per side)",
        "platform_equity_drawdown": "Drawdown with open trades (your platform)",
        "commission": "Commission",
        "swap": "Swap",
        "break_even_multiple": "Break-even cost multiple",
        "reference_bps": "Reference cost (bps per side)",
        "dataset_digest": "Dataset digest",
    },
}

#: Amounts in the account currency: always two decimals, like the platforms.
#: Counts of observations a float only estimates: shown as the next whole one.
COUNT_UP_KEYS = {"min_track_record_length", "observations_short_by"}
MONEY_KEYS = {
    "chosen_result",
    "plateau_result",
    "fall_reference",
    "fall_history",
    "fall_platform",
    "capital",
    "gross_profit",
    "gross_loss",
    "fees_total",
    "net_pnl",
    "gross_pnl",
    "total_cost",
    "expectancy",
    "average_win",
    "average_loss",
    "commission",
    "swap",
    "deposits_total",
    "withdrawals_total",
    "trading_result",
    "floating_pnl",
    "amount",
    "balance_before",
}
#: Ratios a trader reads at two decimals (a profit factor of 1.25, not 1.2453).
RATIO_KEYS = {
    "profit_factor",
    "payoff_ratio",
    "cost_bps_per_side",
    "break_even_pips",
    "reference_pips",
}

PERCENT_KEYS = {
    "passes_in_profit",
    "chosen_top_share",
    "neighbours_in_profit",
    "neighbours_keep",
    "data_quality",
    "platform_equity_drawdown",
    "total_return",
    "cagr",
    "volatility",
    "max_drawdown",
    "win_rate",
    "win_rate_gross",
    "excess_return",
    "strategy_total_return",
    "benchmark_total_return",
    "tracking_error",
    "strategy_max_drawdown",
    "benchmark_max_drawdown",
    "overlap_share",
    "return",
    "min_return",
    "min_drawdown",
    "share_negative",
    "psr",
    "dsr",
    "pbo",
    "p5",
    "p50",
    "p95",
    "p99",
    "point_estimate",
    "largest_win_share",
    "losing_run_odds",
    "dsr_at_declared",
    "dsr_at_trials_used",
    "percent_gain",
    "result_on_deposits",
    "withdrawn_share",
    "floating_share",
    "drawdown",
}


def to_json(result: AuditResult) -> str:
    return pretty_dumps(result.model_dump(mode="json")) + "\n"


def result_sha256(result: AuditResult) -> str:
    return sha256_of_text(canonical_dumps(result.model_dump(mode="json")))


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})T00:00:00(?:\.0+)?(?:Z|\+00:00)?$")


def _table_pct(value: float) -> str:
    """A percentage with two decimals, or two significant digits when it is
    smaller than that (``-0.000012%`` on a history in tiny units); never a
    signed zero."""
    if not math.isfinite(value) or abs(value) >= 0.00005:
        return f"{value:,.2%}"
    if value == 0:
        return "0.00%"
    digits = min(10, 1 - math.floor(math.log10(abs(value * 100))))
    text = f"{value * 100:.{digits}f}"
    if float(text) == 0:
        return "0.00%"
    return f"{text}%"


def _table_money(value: float) -> str:
    """A money or price amount with two decimals, or four significant digits
    when it is under one (``0.0042`` on a history in tiny units); never a
    signed zero."""
    if not math.isfinite(value):
        return f"{value:,.2f}"
    return _signed_amount(value).removeprefix("+")


def _fmt(value: Any, *, key: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if key in COUNT_UP_KEYS and math.isfinite(value):
            return f"{math.ceil(value):,}"
        if key in PERCENT_KEYS:
            return _table_pct(value)
        if key in MONEY_KEYS:
            return _table_money(value)
        if key in RATIO_KEYS:
            return f"{value:,.2f}"
        if value.is_integer() and abs(value) < 1e15:
            return f"{int(value):,}"
        # Four decimals only where they carry information (a per-period Sharpe of
        # 0.1856); anything at or above one reads at two, like the platforms.
        if abs(value) >= 1:
            return f"{value:,.2f}"
        return f"{value:.4f}"
    if isinstance(value, str) and (midnight := _MIDNIGHT.match(value)):
        # A declared date arrives as 2024-06-03T00:00:00Z; the day is what was declared.
        return midnight.group(1)
    return _e(value)


def _badge(cls: str) -> str:
    return f'<span class="badge {_e(cls)}">{_e(cls)}</span>'


#: Red-flag severities as a reader says them; the class keeps the colour.
SEVERITY_TEXT: dict[str, dict[str, str]] = {
    "es": {"FAIL": "Grave", "WARN": "Aviso", "INFO": "Nota"},
    "en": {"FAIL": "Serious", "WARN": "Warning", "INFO": "Note"},
}


def _sentence(text: str) -> str:
    """Capitalised and closed with a period, for a detail shown on its own line."""
    text = text.strip()
    return text[:1].upper() + text[1:].rstrip(".") + "." if text else ""


def _nm_item(item: str) -> str:
    """ "Benchmark aportado: no se subió un benchmark" as a bold name over its reason."""
    name, sep, reason = item.partition(": ")
    if not sep:
        return f"<li><b>{_e(item)}</b></li>"
    return f"<li><b>{_e(name)}</b><span>{_e(_sentence(reason))}</span></li>"


def _severity_badge(severity: str, locale: str) -> str:
    text = SEVERITY_TEXT.get(locale, SEVERITY_TEXT["en"]).get(severity, severity)
    return f'<span class="badge {_e(severity)}">{_e(text)}</span>'


#: The platform's own summary fields, named as the customer knows them.
PLATFORM_LABELS: dict[str, dict[str, str]] = {
    "es": {
        "strategy": "Estrategia",
        "symbol": "Símbolo",
        "period": "Periodo",
        "broker": "Bróker",
        "server": "Servidor",
        "account_type": "Tipo de cuenta",
        "margin_mode": "Modo de margen",
        "leverage": "Apalancamiento",
        "history_quality": "Calidad del historial",
        "report_date": "Fecha del informe",
        "start": "Inicio",
        "end": "Fin",
        "inputs": "Parámetros",
        "input_names": "Nombres de los parámetros",
        "input_values": "Valores elegidos",
        "variants": "Variantes",
        "declared_total_net_profit": "Beneficio neto total",
        "declared_total_trades": "Operaciones totales",
        "declared_total_deals": "Transacciones totales",
        "declared_balance_drawdown_maximal": "Drawdown máximo del balance",
        "declared_equity_drawdown_maximal": "Drawdown máximo de la equity",
        "declared_equity_drawdown_relative": "Drawdown relativo de la equity",
        "declared_maximal_drawdown": "Drawdown máximo",
        "declared_relative_drawdown": "Drawdown relativo",
        "declared_sharpe_ratio": "Sharpe",
        "declared_profit_factor": "Profit factor",
        "declared_balance": "Balance",
        "declared_equity": "Equity",
        "declared_final_equity": "Equity final",
        "declared_closed_trade_pnl": "Resultado de operaciones cerradas",
        "declared_floating_pnl": "Resultado flotante",
        "initial_deposit": "Depósito inicial",
        "model": "Modelado",
        "modelling_quality": "Calidad del modelado",
        "mismatched_chart_errors": "Errores de gráficos no coincidentes",
        "parameters": "Valores de los parámetros",
        "spread": "Spread",
        "closing_deals": "Transacciones de cierre",
        "column_symbol": "Columna leída como símbolo",
        "column_side": "Columna leída como lado",
        "column_quantity": "Columna leída como cantidad",
        "column_entry_time": "Columna leída como hora de entrada",
        "column_exit_time": "Columna leída como hora de salida",
        "column_entry_price": "Columna leída como precio de entrada",
        "column_exit_price": "Columna leída como precio de salida",
        "column_time": "Columna leída como hora de ejecución",
        "column_price": "Columna leída como precio de ejecución",
        "column_profit": "Columna leída como resultado",
        "column_commission": "Columnas leídas como comisión",
        "column_swap": "Columna leída como swap",
        "column_multiplier": "Columna leída como multiplicador",
        "column_account": "Columna leída como cuenta",
    },
    "en": {
        "strategy": "Strategy",
        "symbol": "Symbol",
        "period": "Period",
        "broker": "Broker",
        "server": "Server",
        "account_type": "Account type",
        "margin_mode": "Margin mode",
        "leverage": "Leverage",
        "history_quality": "History quality",
        "report_date": "Report date",
        "start": "Start",
        "end": "End",
        "inputs": "Inputs",
        "input_names": "Input names",
        "input_values": "Chosen values",
        "variants": "Variants",
        "declared_total_net_profit": "Total net profit",
        "declared_total_trades": "Total trades",
        "declared_total_deals": "Total deals",
        "declared_balance_drawdown_maximal": "Balance drawdown maximal",
        "declared_equity_drawdown_maximal": "Equity drawdown maximal",
        "declared_equity_drawdown_relative": "Equity drawdown relative",
        "declared_maximal_drawdown": "Maximal drawdown",
        "declared_relative_drawdown": "Relative drawdown",
        "declared_sharpe_ratio": "Sharpe ratio",
        "declared_profit_factor": "Profit factor",
        "declared_balance": "Balance",
        "declared_equity": "Equity",
        "declared_final_equity": "Final equity",
        "declared_closed_trade_pnl": "Closed trade P/L",
        "declared_floating_pnl": "Floating P/L",
        "initial_deposit": "Initial deposit",
        "model": "Modelling",
        "modelling_quality": "Modelling quality",
        "mismatched_chart_errors": "Mismatched chart errors",
        "parameters": "Parameter values",
        "spread": "Spread",
        "closing_deals": "Closing deals",
        "column_symbol": "Column read as symbol",
        "column_side": "Column read as side",
        "column_quantity": "Column read as quantity",
        "column_entry_time": "Column read as entry time",
        "column_exit_time": "Column read as exit time",
        "column_entry_price": "Column read as entry price",
        "column_exit_price": "Column read as exit price",
        "column_time": "Column read as fill time",
        "column_price": "Column read as fill price",
        "column_profit": "Column read as result",
        "column_commission": "Columns read as commission",
        "column_swap": "Column read as swap",
        "column_multiplier": "Column read as multiplier",
        "column_account": "Column read as account",
    },
}


def platform_label(key: str, locale: str) -> str:
    """A platform field's name; an unknown key is shown as plain words."""
    names = PLATFORM_LABELS.get(locale, PLATFORM_LABELS["en"])
    return names.get(key) or key.replace("_", " ").capitalize()


def _is_evidence(value: Any) -> bool:
    return isinstance(value, dict) and "evidence" in value and "value" in value


def _locale_of(labels: dict[str, str]) -> str:
    return next((locale for locale, table in LABELS.items() if table is labels), "en")


#: What the customer's file was, as they know it; the same in both languages.
SOURCE_NAMES: dict[str, str] = {
    "mt5_tester_html": "MetaTrader 5 Strategy Tester (HTML)",
    "mt5_tester_xlsx": "MetaTrader 5 Strategy Tester (Excel)",
    "mt5_history_html": "MetaTrader 5 history (HTML)",
    "mt5_history_xlsx": "MetaTrader 5 history (Excel)",
    "mt4_tester_html": "MetaTrader 4 Strategy Tester (HTML)",
    "mt4_statement_html": "MetaTrader 4 statement (HTML)",
    "tradingview_csv": "TradingView (CSV)",
    "tradingview_xlsx": "TradingView (Excel)",
    "ninjatrader_csv": "NinjaTrader (CSV)",
    "ninjatrader_executions_csv": "NinjaTrader executions (CSV)",
    "quantconnect_trades_csv": "QuantConnect (CSV)",
    "backtestingpy_csv": "backtesting.py (CSV)",
    "vectorbt_csv": "vectorbt (CSV)",
    "myfxbook_csv": "Myfxbook (CSV)",
    "mql5_signal_csv": "MQL5 signal (CSV)",
    "fxblue_csv": "FX Blue (CSV)",
    "robinhood_csv": "Robinhood (CSV)",
    "universal_trades_csv": "CSV / Excel",
    "universal_fills_csv": "CSV / Excel (fills / ejecuciones)",
}


#: How often the uploaded series is sampled, as ``schema.infer_frequency`` labels it.
FREQUENCY_TEXT: dict[str, dict[str, str]] = {
    "es": {
        "monthly": "mensual",
        "weekly": "semanal",
        "daily_trading": "diario (días hábiles)",
        "daily_calendar": "diario (todos los días)",
        "hourly": "por hora",
        "intraday": "intradía",
    },
    "en": {
        "monthly": "monthly",
        "weekly": "weekly",
        "daily_trading": "daily (trading days)",
        "daily_calendar": "daily (calendar days)",
        "hourly": "hourly",
        "intraday": "intraday",
    },
}


#: The verdict's thresholds as a reader names them.
THRESHOLD_LABELS: dict[str, dict[str, str]] = {
    "es": {
        "psr_pass": "PSR para superar",
        "psr_weak": "PSR mínimo",
        "dsr_pass": "DSR para superar",
        "dsr_weak": "DSR mínimo",
        "pbo_max": "PBO máximo",
        "cost_pass_multiplier": "múltiplo de coste que debe aguantar",
        "oos_sharpe_pass": "Sharpe fuera de muestra mínimo",
        "oos_gap_max": "caída máxima del Sharpe fuera de muestra",
        "benchmark_drawdown_ratio_max": "drawdown máximo frente al benchmark (veces)",
    },
    "en": {
        "psr_pass": "PSR to pass",
        "psr_weak": "minimum PSR",
        "dsr_pass": "DSR to pass",
        "dsr_weak": "minimum DSR",
        "pbo_max": "maximum PBO",
        "cost_pass_multiplier": "cost multiple it must withstand",
        "oos_sharpe_pass": "minimum out-of-sample Sharpe",
        "oos_gap_max": "maximum out-of-sample Sharpe drop",
        "benchmark_drawdown_ratio_max": "maximum drawdown versus the benchmark (times)",
    },
}


def _key_label(key: str, labels: dict[str, str]) -> str:
    return KEY_LABELS[_locale_of(labels)].get(key, key)


def _evidence_rows(section: dict[str, Any], labels: dict[str, str], *, skip: set[str]) -> str:
    rows = []
    for key, value in section.items():
        if key in skip or not _is_evidence(value):
            continue
        raw = value["value"]
        shown = _e(labels["yes" if raw else "no"]) if isinstance(raw, bool) else _fmt(raw, key=key)
        note = localize(value.get("note", ""), _locale_of(labels))
        rows.append(
            f"<tr><td>{_e(_key_label(key, labels))}</td><td class='val'>{shown}</td>"
            f"<td>{_badge(value['evidence'])}</td><td class='muted'>{_e(note)}</td></tr>"
        )
    if not rows:
        # A not-measured section already says why; "none" under it adds nothing.
        if section.get("status") == "NOT_MEASURED":
            return ""
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    return (
        "<table class='metrics ev'><colgroup><col class='c-k'><col class='c-v'>"
        "<col class='c-e'><col></colgroup>"
        f"<thead><tr><th>{_e(labels['metric'])}</th><th class='val'>{_e(labels['value'])}</th>"
        f"<th>{_e(labels['evidence'])}</th><th>{_e(labels['note'])}</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _status_line(section: dict[str, Any], labels: dict[str, str]) -> str:
    status = section.get("status")
    if status == "NOT_MEASURED":
        return (
            f"<p>{_badge('NOT_MEASURED')} <span class='muted'>"
            f"{_e(_localized_reason(section.get('reason', ''), _locale_of(labels)))}"
            "</span></p>"
        )
    return ""


#: Spanish for the not-measured reasons the engine writes, beyond the verdict's.
REASONS_ES: dict[str, str] = {
    "the curve is too short or not positive": "la curva es muy corta o no es positiva",
    "fewer than two closed trades": "menos de dos operaciones cerradas",
    **NOT_MEASURED_ES,
    "no trades uploaded": "no se subieron operaciones",
    "no variants uploaded": "no se subió la matriz de variantes",
    "fewer than ten returns": "menos de diez retornos",
    "the simulator needs daily or finer data; the upload is coarser": (
        "el simulador necesita datos diarios o más finos; los subidos son más gruesos"
    ),
}


def _localized_reason(reason: str, locale: str) -> str:
    if locale == "pt":
        return localize(reason, locale)
    if locale != "es":
        return reason
    return REASONS_ES.get(reason) or localize(reason, locale)


def _status_badge(status: str, locale: str) -> str:
    text = STATUS_TEXT.get(locale, STATUS_TEXT["es"]).get(status, status)
    return f'<span class="badge {_e(status)}">{_e(text)}</span>'


def _dimension_title(name: str, locale: str) -> str:
    return DIMENSION_TITLES.get(locale, DIMENSION_TITLES["es"]).get(name, name)


def _meaning_html(verdict: dict[str, Any], locale: str, *, account: bool = False) -> str:
    by_name = {d["name"]: d for d in verdict["dimensions"]}
    items = []
    for name in DIMENSION_ORDER:
        dimension = by_name.get(name)
        if dimension is None:
            continue
        items.append(
            f"<div class='item s-{_e(dimension['status'])}'>"
            f"<h3>{_e(_dimension_title(name, locale))} "
            f"{_status_badge(dimension['status'], locale)}</h3>"
            f"<p>{_e(meaning(name, dimension['status'], locale, account=account))}</p></div>"
        )
    return "<div class='meaning'>" + "".join(items) + "</div>"


def _reasons_html(verdict: dict[str, Any], locale: str, labels: dict[str, str]) -> str:
    rows = []
    for d in verdict["dimensions"]:
        reasons = d.get("reasons_es") if locale == "es" and d.get("reasons_es") else d["reasons"]
        if locale == "pt":
            reasons = [localize(reason, locale) for reason in d["reasons"]]
        rows.append(
            f"<tr><td>{_e(_dimension_title(d['name'], locale))}</td>"
            f"<td>{_status_badge(d['status'], locale)}</td><td>{_e('; '.join(reasons))}</td></tr>"
        )
    return (
        f"<table class='reasons'><tr><th>{_e(labels['dimension'])}</th>"
        f"<th>{_e(labels['status'])}</th><th>{_e(labels['reasons'])}</th></tr>"
        f"{''.join(rows)}</table>"
        f"<p class='muted'>{_e(labels['thresholds'])}: "
        + _e(
            " · ".join(
                f"{THRESHOLD_LABELS[locale].get(k, k)} {v:g}"
                for k, v in verdict["thresholds"].items()
            )
        )
        + "</p>"
    )


def _charts_html(data: dict[str, Any], locale: str) -> str:
    series = data.get("series")
    if not series:
        return ""
    note = series.get("note") if series.get("note") != "as uploaded" else None
    if note and locale == "es":
        note = "Balance reconstruido con operaciones cerradas: no muestra el drawdown flotante."
    elif note and locale == "pt":
        note = "Saldo reconstruído com operações fechadas: não mostra o drawdown flutuante."
    figures = [
        charts.equity_chart(series["timestamps"], series["equity"], locale=locale, note=note),
        charts.drawdown_chart(series["timestamps"], series["equity"], locale=locale, note=note),
    ]
    risk = data.get("risk") or {}
    fan = risk.get("fan")
    if fan:
        paths = {key: fan[key] for key in charts.FAN_PERCENTILES if key in fan}
        figures.append(
            charts.fan_chart(
                paths, locale=locale, horizon_label=LABELS.get(locale, LABELS["es"])["horizon"]
            )
        )
    figures.append(
        charts.monthly_heatmap(
            series["month_end_timestamps"], series["month_end_equity"], locale=locale
        )
    )
    return "".join(figures)


PLAN_CSS = (
    ".plan{grid-template-columns:minmax(0,1fr)}"
    ".plan .item h3{justify-content:flex-start;gap:12px}"
    ".plan .item h3 .step-n{font-family:var(--mono);color:var(--text-3);font-weight:500}"
    ".plan .item h3 .step-t{flex:1;min-width:0}"
    ".plan .item ul{margin:10px 0 0;padding-left:1.1rem;color:var(--text-2);font-size:.92rem}"
    ".plan .item li{margin:4px 0}"
    ".plan .item .plan-class{margin-top:10px;font-size:.85rem;color:var(--text-3)}"
)


def _plan_html(data: dict[str, Any], locale: str, labels: dict[str, str], *, locked: bool) -> str:
    """The improvement plan; locked pages show only each step's title."""
    steps = improvement_plan(data, locale)
    if not steps:
        return f"<p class='muted'>{_e(labels['plan_none'])}</p>"
    items = []
    for number, step in enumerate(steps, start=1):
        head = (
            f"<h3><span class='step-n'>{number:02d}</span> "
            f"<span class='step-t'>{_e(step.title)}</span> "
            f"{_status_badge(step.status, locale)}</h3>"
        )
        if locked:
            items.append(f"<div class='item s-{_e(step.status)}'>{head}</div>")
            continue
        actions = (
            "<ul>" + "".join(f"<li>{_e(action)}</li>" for action in step.actions) + "</ul>"
            if step.actions
            else ""
        )
        better = (
            f"<p class='plan-class'>{_e(labels['plan_class'])} "
            f"<strong>{_e(step.class_if_passed)}</strong>.</p>"
            if step.class_if_passed
            else ""
        )
        items.append(
            f"<div class='item s-{_e(step.status)}'>{head}<p>{_e(step.finding)}</p>"
            f"{actions}{better}</div>"
        )
    intro = (
        f"<p class='muted'>{len(steps)} {_e(labels['plan_locked'])}.</p>"
        if locked
        else f"<p class='muted'>{_e(labels['plan_intro'])}</p>"
    )
    return intro + "<div class='meaning plan'>" + "".join(items) + "</div>"


KPI_CSS = (
    ".kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0}"
    "@media (max-width:760px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}"
    ".kpis>.kpi:last-child:nth-child(odd){grid-column:1/-1}}"
    ".kpi{border:1px solid var(--border);border-radius:16px;padding:16px 18px;background:#fff}"
    ".kpi b{display:block;font-family:var(--serif);font-weight:400;"
    "font-size:clamp(1.6rem,3vw,2.1rem);line-height:1.1;letter-spacing:-.01em}"
    # A long figure (+191,136.0%, +3,472.25) steps down so it fits a phone's half-width tile.
    ".kpi.long b{font-size:clamp(1.1rem,2.1vw,1.55rem)}"
    ".kpi.xlong b{font-size:clamp(.85rem,1.5vw,1.2rem)}"
    ".kpi b{overflow-wrap:anywhere}"
    ".kpi span{display:block;margin-top:6px;color:var(--text-2);font-size:.82rem}"
    ".kpi small{display:block;margin-top:3px;color:var(--text-2);font-size:.72rem;"
    "line-height:1.35;opacity:.85}"
    ".kpi.bad b{color:var(--bad)}.kpi.good b{color:var(--ok)}"
    ".kpi.locked b{display:flex;align-items:center;gap:10px;height:1.1em;color:var(--text-3)}"
    ".kpi.locked svg{width:.62em;height:.62em;flex:none}"
    "a.kpi.locked{display:block;color:inherit;text-decoration:none;"
    "transition:border-color .2s,box-shadow .2s}"
    "a.kpi.locked:hover,a.kpi.locked:focus-visible{border-color:var(--text-3);"
    "box-shadow:0 6px 18px rgba(0,0,0,.06)}"
    "a.kpi.locked:hover svg{color:var(--text)}"
    ".kpi.locked i{display:block;height:.5em;width:62%;border-radius:999px;"
    "background:linear-gradient(90deg,#ececef 0%,#f6f6f8 50%,#ececef 100%);"
    "background-size:200% 100%;"
    "animation:kpi-sk 2.4s ease-in-out infinite}"
    "@keyframes kpi-sk{from{background-position:100% 0}to{background-position:-100% 0}}"
    "@media (prefers-reduced-motion:reduce){.kpi.locked i{animation:none}}"
)


def _ev_value(block: Any) -> float | None:
    if isinstance(block, dict) and block.get("evidence") != "NOT_MEASURED":
        value = block.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _pct(value: float, *, signed: bool = False, places: int = 1, _widened: bool = False) -> str:
    """A share at ``places`` decimals, readable at the edges.

    A tiny negative never prints as "-0.0%", and a share short of a whole
    (-99.7 %) never rounds to "-100%", which would read as a total loss: it
    gets one more decimal, and past that it reads as a bound (">99.9%").
    """
    spec = f"{'+' if signed else ''},.{places}%"
    shown = f"{value:{spec}}"
    if float(shown.rstrip("%").replace(",", "")) == 0:
        return f"{0:.{places}%}"
    if abs(value) != 1 and abs(float(shown.rstrip("%").replace(",", ""))) == 100:
        if not _widened:
            return _pct(value, signed=signed, places=places + 1, _widened=True)
        if abs(value) > 1:
            return shown
        # Still a whole at one more decimal: say which side of it the value is.
        bound = f"{1 - 10 ** -(places + 2):.{places}%}"
        return f">{'+' if signed else ''}{bound}" if value > 0 else f"<-{bound}"
    return shown


def _kpi_list(data: dict[str, Any], labels: dict[str, str]) -> list[tuple[str, str, str]]:
    """``(label, shown value, tone)`` for each key figure that was measured."""
    perf = data.get("performance") or {}
    stats = data.get("trade_stats") or {}
    costs = data.get("costs") or {}
    risk = data.get("risk") or {}
    stress = data.get("stress") or {}
    out: list[tuple[str, str, str]] = []

    def add(label: str, value: float | None, shown: str, tone: str = "") -> None:
        if value is not None:
            out.append((labels[label], shown, tone))

    total = _ev_value(perf.get("total_return"))
    add("kpi_return", total, _pct(total, signed=True) if total is not None else "")
    # A balance rebuilt from closed trades cannot see open losses; the tiles say so,
    # and turn red when the red flags found losses the balance hides.
    closed = bool((data.get("inputs") or {}).get("balance_only"))
    hidden = closed and any(
        flag.get("code") == "HIDDEN_FLOATING_DRAWDOWN" for flag in data.get("red_flags") or []
    )
    dd = _ev_value(perf.get("max_drawdown"))
    add(
        "kpi_drawdown_closed" if closed else "kpi_drawdown",
        dd,
        _pct(dd) if dd is not None else "",
        "bad" if hidden else "",
    )
    platform_dd = _ev_value(perf.get("platform_equity_drawdown"))
    if platform_dd is not None and (dd is None or platform_dd < dd - 0.005):
        # Deeper than the closed-trade curve shows: the buyer sees both, side by side.
        out.append((labels["kpi_dd_platform"], f"{platform_dd:.1%}", "bad"))
    p95 = _ev_value((risk.get("max_drawdown") or {}).get("p95"))
    # Shown with the same sign as the maximum drawdown beside it (a fall, so negative);
    # the resampled-risk section reads the same depths as positive "caída" sizes.
    add(
        "kpi_dd_p95_closed" if closed else "kpi_dd_p95",
        p95,
        _pct(-abs(p95)) if p95 is not None else "",
    )
    sharpe = _ev_value(perf.get("sharpe"))
    add("kpi_sharpe", sharpe, f"{sharpe:.2f}" if sharpe is not None else "")
    pf = _ev_value(stats.get("profit_factor"))
    add("kpi_pf", pf, f"{pf:,.2f}" if pf is not None else "")
    count = _ev_value(stats.get("trade_count"))
    rate = _ev_value(stats.get("win_rate"))
    if count is not None and rate is not None:
        out.append((labels["kpi_trades"], f"{count:,.0f} · {rate:.0%}", ""))
    breakeven = _ev_value(costs.get("break_even_bps"))
    reference = _ev_value(costs.get("reference_bps")) or 0.0
    if breakeven is not None and breakeven <= 0:
        # Negative already before any extra cost: "-0.56 bp" would read as a cost.
        label = f"{labels['kpi_breakeven']} ({labels['kpi_breakeven_negative']})"
        out.append((label, "0", "bad"))
    elif breakeven is not None:
        tone = "bad" if breakeven < 3 * reference else "good"
        label = f"{labels['kpi_breakeven']} ({labels['bps_side']})"
        pips = _ev_value(costs.get("break_even_pips"))
        if pips is not None:
            # The pips go under the figure, so the tile keeps one short number.
            label = f"{labels['kpi_breakeven']} ({labels['bps_side']}; {pips:,.1f} pips)"
        out.append((label, f"{breakeven:,.2f}", tone))
    for block, scenario, label, percent in (
        (stress.get("trades") or {}, "best_5_trades", "kpi_stress", False),
        (stress.get("returns") or {}, "best_5_periods", "kpi_stress_curve", True),
    ):
        row = next((r for r in block.get("rows", []) if r.get("scenario") == scenario), None)
        value = _ev_value(row["result"]) if row else None
        if value is not None:
            shown = _stress_value(value, percent=percent, signed=True)
            out.append((labels[label], shown, "good" if value > 0 else "bad"))
    return out


def _kpi_size(shown: str) -> str:
    """A size class so a long figure still fits a phone's half-width tile."""
    length = len(shown.replace(" ", ""))
    return " xlong" if length >= 12 else " long" if length >= 9 else ""


#: Tiles whose name is a trader's term get a plain line under it.
_KPI_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("kpi_return",), "kpi_hint_return"),
    (("kpi_drawdown", "kpi_drawdown_closed"), "kpi_hint_drawdown"),
    (("kpi_dd_p95", "kpi_dd_p95_closed"), "kpi_hint_dd_p95"),
    (("kpi_sharpe",), "kpi_hint_sharpe"),
    (("kpi_pf",), "kpi_hint_pf"),
    (("kpi_breakeven",), "kpi_hint_breakeven"),
)


def _kpi_hint(label: str, labels: dict[str, str]) -> str:
    for keys, hint in _KPI_HINTS:
        if any(label == labels[key] or label.startswith(labels[key] + " (") for key in keys):
            return f"<small>{_e(labels[hint])}</small>"
    return ""


def _kpis_html(data: dict[str, Any], labels: dict[str, str], *, locked: bool) -> str:
    kpis = _kpi_list(data, labels)
    if not kpis:
        return ""
    tiles = "".join(
        # A locked figure is a way in: tapping it goes to the unlock box.
        f"<a class='kpi locked' href='#unlock' "
        f"aria-label='{_e(label)}: {_e(labels['unlock_nav'])}'>"
        f"<b aria-hidden='true'>{icon('lock')}<i></i></b><span>{_e(label)}</span></a>"
        if locked
        else f"<div class='kpi {tone}{_kpi_size(shown)}'><b>{_e(shown)}</b>"
        f"<span>{_e(label)}</span>{_kpi_hint(label, labels)}</div>"
        for label, shown, tone in kpis
    )
    note = f"<p class='muted'>{_e(labels['kpis_locked'])}</p>" if locked else ""
    return note + f"<div class='kpis'>{tiles}</div>" + ("" if locked else _cash_html(data, labels))


def _cash_html(data: dict[str, Any], labels: dict[str, str]) -> str:
    """The Sharpe after what a US Treasury bill paid, under the tiles."""
    cash = data.get("cash_rate") or {}
    if cash.get("status") != "MEASURED":
        return ""
    rate = _pct(float(cash["mean_rate"]["value"]), places=2)
    if cash.get("below_cash"):
        first = labels["cash_below"].format(
            ret=_pct(float(cash["strategy_yearly"]["value"]), places=2), rate=rate
        )
    else:
        first = labels["cash_sharpe"].format(
            rate=rate, sharpe=f"{float(cash['sharpe_excess']['value']):.2f}"
        )
    text = first + " " + labels["cash_note"].format(source="\x00")
    link = f"<a href='{_e(str(cash.get('source_url', '')))}' rel='noopener'>FRED</a>"
    return (
        f"<p class='muted'>{_e(text).replace(chr(0), link)} {_badge('MEASURED')}</p>"
    )


STRESS_SCENARIOS: dict[str, dict[str, str]] = {
    "es": {
        "best_1pct_periods": "Sin el mejor 1 % de periodos ({removed})",
        "best_5_periods": "Sin los 5 mejores periodos",
        "best_10_periods": "Sin los 10 mejores periodos",
        "best_1_trades": "Sin la mejor operación",
        "best_5_trades": "Sin las 5 mejores operaciones",
        "best_10pct_trades": "Sin el mejor 10 % de operaciones ({removed})",
        "best_month": "Sin el mejor mes ({month})",
    },
    "en": {
        "best_1pct_periods": "Without the best 1 % of periods ({removed})",
        "best_5_periods": "Without the best 5 periods",
        "best_10_periods": "Without the best 10 periods",
        "best_1_trades": "Without the best trade",
        "best_5_trades": "Without the best 5 trades",
        "best_10pct_trades": "Without the best 10 % of trades ({removed})",
        "best_month": "Without the best month ({month})",
    },
}


def _stress_value(value: Any, *, percent: bool, signed: bool = False) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    if percent:
        return _pct(value, signed=signed)
    shown = f"{value:+,.2f}" if signed else f"{value:,.2f}"
    return "0.00" if float(shown.replace(",", "")) == 0 else shown


def _stress_table(
    block: dict[str, Any], locale: str, labels: dict[str, str], *, percent: bool
) -> str:
    names = STRESS_SCENARIOS.get(locale, STRESS_SCENARIOS["es"])
    original = block["original"]
    rows = [
        f"<tr class='base'><td>{_e(labels['original'])} {_badge(original['evidence'])}</td>"
        f"<td class='val' data-l='{_e(labels['stress_result'])}'>"
        f"{_stress_value(original['value'], percent=percent)}</td>"
        "<td class='empty'></td><td class='empty'></td></tr>"
    ]
    for row in block.get("rows", []):
        name = names.get(row["scenario"], row["scenario"]).format(
            removed=row.get("removed", ""), month=row.get("month", "")
        )
        ok = row.get("stays_positive")
        below = row["result"]["value"] <= 0
        rows.append(
            f"<tr><td>{_e(name)}</td>"
            f"<td class='val{' neg' if below else ''}' data-l='{_e(labels['stress_result'])}'>"
            f"{_stress_value(row['result']['value'], percent=percent)}</td>"
            f"<td class='val delta' data-l='{_e(labels['stress_change'])}'>"
            f"{_stress_value(row['change']['value'], percent=percent, signed=True)}</td>"
            f"<td data-l='{_e(labels['stress_positive'])}'>"
            f"<span class='badge {'PASS' if ok else 'FAIL'}'>"
            f"{_e((labels['yes'] if ok else labels['no']).capitalize())}</span></td></tr>"
        )
    return (
        "<table class='stress'><colgroup><col><col class='c-n'><col class='c-n'>"
        "<col class='c-b'></colgroup><thead>"
        f"<tr><th>{_e(labels['scenario'])}</th><th class='val'>{_e(labels['stress_result'])}</th>"
        f"<th class='val'>{_e(labels['stress_change'])}</th>"
        f"<th>{_e(labels['stress_positive'])}</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _stress_html(stress: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    if not stress:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    blocks = [
        (labels["stress_curve"], stress.get("returns") or {}, True),
        (labels["stress_trades"], stress.get("trades") or {}, False),
    ]
    measured_rows = [
        row
        for _, block, _ in blocks
        if block.get("status") == "MEASURED"
        for row in block.get("rows", [])
    ]
    out = f"<p class='muted'>{_e(labels['stress_intro'])}</p>"
    if measured_rows:
        broken = sum(1 for row in measured_rows if not row.get("stays_positive"))
        out += (
            f"<p><strong>{broken}</strong> "
            f"{_e(labels['stress_count'].format(total=len(measured_rows)))}.</p>"
        )
    for title, block, percent in blocks:
        out += f"<h3>{_e(title)}</h3>"
        if block.get("status") != "MEASURED":
            out += _status_line(block, labels)
            continue
        out += _stress_table(block, locale, labels, percent=percent)
        share = block.get("top5_share")
        if share:
            out += (
                f"<p>{_e(labels['top5_share'])}: {share['value']:.2f}x "
                f"{_badge(share['evidence'])}</p>"
            )
    return out


def _no_flags_html(labels: dict[str, str]) -> str:
    """An empty red-flag list as a calm line, not a bare "none"."""
    return f"<p class='no-flags'>{icon('check')}<span>{_e(labels['flags_none'])}</span></p>"


def _flags_free_html(flags: list[dict[str, Any]], locale: str, labels: dict[str, str]) -> str:
    if not flags:
        return _no_flags_html(labels)
    # Same card as the full report, without the detail that the payment unlocks.
    order = {"FAIL": 0, "WARN": 1}
    return (
        "<ul class='flag-list acct-flags flag-cards'>"
        + "".join(
            f"<li>{_severity_badge(flag['severity'], locale)}"
            f"<div><b>{_e(flag_title(flag['code'], locale))}</b>"
            f"<p class='flag-code'>{_e(flag['code'])}</p></div></li>"
            for flag in sorted(flags, key=lambda f: order.get(f["severity"], 2))
        )
        + "</ul>"
    )


def _streak_html(stats: dict[str, Any], labels: dict[str, str]) -> str:
    """The longest losing run next to the one chance gives at the same loss rate."""
    chance, rare, odds, observed = (
        stats.get(key) or {}
        for key in (
            "losing_run_chance",
            "losing_run_rare",
            "losing_run_odds",
            "max_consecutive_losses",
        )
    )
    if not all(item.get("evidence") == "MEASURED" for item in (chance, rare, odds, observed)):
        return ""
    line = labels["streak_line"].format(
        chance=chance["value"], rare=rare["value"], observed=observed["value"]
    )
    out = f"<p>{_e(line)} {_badge('MEASURED')}</p>"
    if float(odds["value"]) < CLUSTERED:
        out += f"<p class='live-verdict lv-WEAK'>{_e(labels['streak_clustered'])}</p>"
    return out


def _trade_stats_html(stats: dict[str, Any] | None, labels: dict[str, str]) -> str:
    if not stats:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    html_text = _status_line(stats, labels)
    if stats.get("status") != "MEASURED":
        return html_text
    html_text += _streak_html(stats, labels)
    html_text += _evidence_rows(stats, labels, skip={"long", "short"})
    for side in ("long", "short"):
        if isinstance(stats.get(side), dict):
            html_text += f"<h3>{_e(labels[side])}</h3>" + _evidence_rows(
                stats[side], labels, skip=set()
            )
    return html_text


def _range_fact(
    items: list[dict[str, Any]], joiner: str, label: str, fmt: Callable[[float], str]
) -> str:
    """A fact card for a range of estimates, with one evidence tag for the whole range."""
    values = [item.get("value") for item in items]
    evidence = {str(item.get("evidence", "NOT_MEASURED")) for item in items}
    tag = evidence.pop() if len(evidence) == 1 else "NOT_MEASURED"
    shown = joiner.join(
        fmt(float(v)) if isinstance(v, (int, float)) and math.isfinite(v) else "—" for v in values
    )
    return f"<div class='fact'><b>{_e(shown)}</b><p>{_e(label)} {_badge(tag)}</p></div>"


def _value_cell(item: dict[str, Any], *, percent: bool) -> str:
    value = item.get("value")
    shown = _fmt(value, key="p50" if percent else "")
    return f"<span class='vc'>{shown} {_badge(item.get('evidence', 'NOT_MEASURED'))}</span>"


def _assumptions(block: Any, locale: str, labels: dict[str, str]) -> str:
    if not isinstance(block, dict):
        return ""
    items = block.get(locale) or block.get("es") or []
    if locale == "pt":
        # A result stores its assumptions in Spanish and English only.
        items = [localize(item, locale) for item in block.get("en") or []]
    return (
        f"<p class='muted'>{_e(labels['assumptions'])}:</p><ul class='muted'>"
        + "".join(f"<li>{_e(item)}</li>" for item in items)
        + "</ul>"
    )


def _hidden_loss_note(data: dict[str, Any], labels: dict[str, str]) -> str:
    """A callout when the red flags found open losses a balance-only file hides."""
    codes = {flag.get("code") for flag in data.get("red_flags") or []}
    if "HIDDEN_FLOATING_DRAWDOWN" not in codes:
        return ""
    return (
        f"<p class='live-verdict lv-FAIL'><span class='badge FAIL'>"
        f"{_e(labels['open_loss_badge'])}</span> {_e(labels['hidden_loss'])}</p>"
    )


def _risk_html(
    risk: dict[str, Any] | None, locale: str, labels: dict[str, str], hidden_note: str = ""
) -> str:
    if not risk:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    html_text = _status_line(risk, labels)
    if risk.get("status") == "MEASURED":
        html_text += hidden_note
    if risk.get("status") == "MEASURED":
        dd = risk["max_drawdown"]
        html_text += (
            "<div class='facts'>"
            + "".join(
                f"<div class='fact'><b>{_e(_fmt(dd[q].get('value'), key='p50'))}</b>"
                f"<p>{_e(labels['risk_dd'])} · {q} "
                f"{_badge(dd[q].get('evidence', 'NOT_MEASURED'))}</p></div>"
                for q in ("p50", "p95", "p99")
            )
            + "</div>"
        )
        probs = risk["probability_drawdown_at_least"]
        html_text += (
            f"<table><tr><th>{_e(labels['risk_prob'])}</th><th>{_e(labels['probability'])}</th>"
            "</tr>"
            + "".join(
                f"<tr><td>{float(level):.0%}</td><td>{_value_cell(item, percent=True)}</td></tr>"
                for level, item in probs.items()
            )
            + "</table>"
        )
        under = risk["longest_underwater_periods"]
        html_text += (
            f"<p>{_e(labels['risk_underwater'])}: {_e(labels['risk_under_median'])} "
            f"{_value_cell(under['p50'], percent=False)}, {_e(labels['risk_under_p95'])} "
            f"{_value_cell(under['p95'], percent=False)}</p>"
        )
    return html_text + _assumptions(risk.get("assumptions"), locale, labels)


def _cost_gap_note(
    rows: list[dict[str, Any]], stats: dict[str, Any], labels: dict[str, str]
) -> str:
    """Say why the cost table's no-extra-cost row can differ from the trade net."""
    base = next((row for row in rows if float(row.get("multiplier", -1)) == 0.0), None)
    trades_net = _ev_value(stats.get("net_pnl"))
    table_net = _ev_value((base or {}).get("net_pnl"))
    if trades_net is None or table_net is None or abs(table_net - trades_net) < 0.005:
        return ""
    return (
        "<p class='muted'>"
        + _e(
            labels["cost_recomputed"].format(
                table=_fmt(table_net, key="net_pnl"),
                gap=_fmt(abs(table_net - trades_net), key="net_pnl"),
                trades=_fmt(trades_net, key="net_pnl"),
            )
        )
        + "</p>"
    )


def _open_loss_note(
    challenge: dict[str, Any], platform_dd: float | None, labels: dict[str, str]
) -> str:
    """A line when the platform's open-trade drawdown already breaks the total loss limit."""
    limit = (challenge.get("rules") or {}).get("max_total_loss")
    if platform_dd is None or not isinstance(limit, (int, float)) or limit <= 0:
        return ""
    if abs(platform_dd) < limit:
        return ""
    text = labels["challenge_open_loss"].format(dd=f"{abs(platform_dd):.1%}", limit=f"{limit:.0%}")
    return (
        f"<p class='live-verdict lv-FAIL'><span class='badge FAIL'>"
        f"{_e(labels['open_loss_badge'])}</span> {_e(text)}</p>"
    )


def _challenge_html(
    challenge: dict[str, Any] | None,
    locale: str,
    labels: dict[str, str],
    platform_dd: float | None = None,
    hidden_note: str = "",
) -> str:
    if not challenge:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    rules = challenge.get("rules", {})
    html_text = (
        f"<p><strong>{_e(labels['challenge_rules'])}:</strong> "
        + _e(
            preset_label(
                str(rules.get("firm", "")),
                str(rules.get("program", "")),
                str(rules.get("phase", "")),
                locale,
            )
        )
        + (
            f" (<code>{_e(challenge.get('preset', ''))}</code>). "
            if str(rules.get("source_url", "")).startswith("https://")
            else ". "
        )
        + (
            f"{_e(labels['source'])}: {_e(rules.get('source_url', ''))}, {_e(labels['as_of'])} "
            f"{_e(rules.get('as_of', ''))}.</p>"
            if str(rules.get("source_url", "")).startswith("https://")
            else f"{_e(labels['generic_rules'])}</p>"
        )
    )
    html_text += _status_line(challenge, labels)
    open_loss = _open_loss_note(challenge, platform_dd, labels)
    html_text += open_loss or (hidden_note if challenge.get("status") == "MEASURED" else "")
    if challenge.get("status") == "MEASURED":
        probability = challenge["probability"]
        html_text += (
            f"<table><tr><th>{_e(labels['outcome'])}</th><th>{_e(labels['probability'])}</th></tr>"
            + "".join(
                f"<tr><td>{_e(labels[key])}</td>"
                f"<td>{_value_cell(probability[key], percent=True)}</td></tr>"
                for key in ("pass", "fail_daily_loss", "fail_total_loss", "unfinished")
            )
            + "</table>"
        )
        ci = challenge["pass_probability_ci95"]
        days = challenge["days_to_target"]
        html_text += (
            "<div class='facts'>"
            + _range_fact([ci["low"], ci["high"]], " – ", labels["ci95"], lambda v: f"{v:.1%}")
            + _range_fact(
                [days[q] for q in ("p25", "p50", "p75")],
                " / ",
                labels["days_to_target"],
                lambda v: f"{v:.0f}",
            )
            + "</div>"
        )
        best_day = challenge.get("best_day") or {}
        if best_day.get("breach_share_of_passes"):
            share = float(best_day["breach_share_of_passes"]["value"])
            html_text += (
                f"<p>{_e(labels['best_day_line'].format(share=_share_pct(share)))} "
                f"{_badge('MEASURED')}</p>"
            )
    notes = rules.get("notes") or []
    if notes:
        html_text += (
            "<ul class='muted'>"
            + "".join(f"<li>{_e(localize(n, locale))}</li>" for n in notes)
            + "</ul>"
        )
    html_text += _assumptions(challenge.get("assumptions"), locale, labels)
    return html_text + _firm_fit_html(
        challenge.get("firm_fit"),
        labels,
        optimistic=bool(open_loss or (hidden_note and challenge.get("status") == "MEASURED")),
    )


def _phases(count: int, labels: dict[str, str]) -> str:
    return labels["ff_phase"] if count == 1 else labels["ff_phases"].format(n=count)


def _share_pct(value: float) -> str:
    """A share rounded to whole percent that never rounds to all or nothing
    when it is not."""
    if 0.995 <= value < 1:
        return ">99%"
    if 0 < value < 0.005:
        return "<1%"
    return f"{value:.0%}"


def _firm_pct(value: float) -> str:
    """A pass chance, capped so a resampled figure never reads as a certainty."""
    if value >= 0.99:
        return "≥99%"
    if 0 < value <= 0.01:
        return "≤1%"
    return f"{value:.0%}"


def _firm_fit_html(
    fit: dict[str, Any] | None, labels: dict[str, str], *, optimistic: bool = False
) -> str:
    """Every published challenge on the same resampled history, best odds first."""
    if not fit or fit.get("status") != "MEASURED" or not fit.get("firms"):
        return ""
    out = (
        f"<h3>{_e(labels['ff_title'])}</h3>"
        f"<p class='muted'>{_e(labels['ff_intro'])} {_badge('MEASURED')}</p>"
    )
    if optimistic:
        out += f"<p><strong>{_e(labels['ff_optimistic'])}</strong></p>"
    uniform = fit.get("uniform")
    if uniform == "all_pass":
        return out + f"<p>{_e(labels['ff_all_pass'])}</p>"
    if uniform == "all_fail":
        common = fit.get("common_risk") or "none"
        text = labels["ff_all_fail"].format(risk=labels[f"ff_risk_{common}"].lower())
        return out + f"<p>{_e(text)}</p>"

    def pct(item: dict[str, Any] | None, label: str) -> str:
        if not item:
            return f"<td class='val muted' data-l='{_e(label)}'>{_e(labels['ff_no_rule'])}</td>"
        return f"<td class='val' data-l='{_e(label)}'>{_e(_firm_pct(float(item['value'])))}</td>"

    def risk(key: str) -> str:
        return labels["ff_risk_none"] if key == "none" else labels[key]

    body = "".join(
        "<tr><td>"
        + _e(f"{row['firm']} · {row['program']}")
        + f"<br><small class='muted'>{_e(_phases(row['phases'], labels))}</small>"
        + "</td>"
        + pct(row["pass"], labels["ff_pass"])
        + pct(row.get("pass_within_best_day"), labels["ff_clean"])
        + f"<td data-l='{_e(labels['ff_risk'])}'>{_e(risk(row['main_risk']))}</td></tr>"
        for row in fit["firms"]
    )
    return out + (
        f"<table class='timing firms'><thead><tr><th>{_e(labels['ff_program'])}</th>"
        f"<th class='val'>{_e(labels['ff_pass'])}</th>"
        f"<th class='val'>{_e(labels['ff_clean'])}</th>"
        f"<th>{_e(labels['ff_risk'])}</th></tr></thead><tbody>{body}</tbody></table>"
    )


def _question_text(question: dict[str, str], locale: str) -> str:
    if locale == "pt":
        # A result stores its questions in Spanish and English only.
        return localize(question.get("en", ""), locale)
    return question.get(locale) or question.get("es", "")


def _questions_html(questions: list[dict[str, str]], locale: str, labels: dict[str, str]) -> str:
    if not questions:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    return (
        "<ol>" + "".join(f"<li>{_e(_question_text(q, locale))}</li>" for q in questions) + "</ol>"
    )


def _source_html(data: dict[str, Any], labels: dict[str, str]) -> str:
    inputs = data["inputs"]
    out = ""
    source_format = inputs.get("source_format")
    if source_format and source_format != "csv":
        shown = SOURCE_NAMES.get(source_format, source_format)
        out += f"<p>{_e(labels['report_source'])}: {_e(shown)}</p>"
    optimization = inputs.get("optimization")
    if optimization:
        passes = optimization["passes"]
        out += (
            f"<p>{_e(labels['optimization'])}: {_fmt(passes['value'])} {_e(labels['passes'])} "
            f"{_badge(passes['evidence'])}</p>"
        )
    metadata = dict(inputs.get("report_metadata") or {})
    out += _column_map_html(metadata, labels)
    metadata = {
        k: v
        for k, v in metadata.items()
        if not k.startswith("column_") and k not in (NEAR_EMPTY_DAYS, NEAR_EMPTY_FIRST)
    }
    if metadata:
        out += (
            f"<p class='muted'>{_e(labels['platform'])} {_badge('DECLARED')}</p><table>"
            + "".join(
                f"<tr><td>{_e(platform_label(key, _locale_of(labels)))}</td>"
                f"<td>{_e(value)}</td></tr>"
                for key, value in metadata.items()
            )
            + "</table>"
        )
    return out


def _column_map_html(metadata: dict[str, Any], labels: dict[str, str]) -> str:
    """Which of the customer's columns was read as what, one column per row."""
    locale = _locale_of(labels)
    order = [key for key in PLATFORM_LABELS["en"] if key.startswith("column_")]
    keys = sorted(
        (key for key in metadata if key.startswith("column_")),
        key=lambda key: order.index(key) if key in order else len(order),
    )
    if not keys:
        return ""
    rows = []
    for key in keys:
        # "Columna leída como precio de entrada" -> "precio de entrada".
        field = platform_label(key, locale).rpartition(" as " if locale == "en" else " como ")[2]
        rows.append(
            f"<li><code>{_e(metadata[key])}</code>{icon('arrow')}<span>{_e(field)}</span></li>"
        )
    return (
        f"<div class='colmap'><p class='colmap-title'>{_e(labels['colmap'])}</p>"
        f"<ul class='colmap-list'>{''.join(rows)}</ul></div>"
    )


def _other(locale: str) -> str:
    return "en" if locale == "es" else "es"


def _summary_in(data: dict[str, Any], locale: str) -> str:
    """The verdict sentence rebuilt in ``locale`` from the stored dimensions."""
    trials = data["multiplicity"].get("trials_used") or data["declared"].get("trials") or {}
    chosen: Locale = "pt" if locale == "pt" else "en" if locale == "en" else "es"
    dimensions = [Dimension.model_validate(d) for d in data["verdict"]["dimensions"]]
    if chosen == "pt":
        # A result stores its reasons in English and Spanish only.
        dimensions = [
            d.model_copy(update={"reasons": [localize(r, "pt") for r in d.reasons]})
            for d in dimensions
        ]
    return summary(
        dimensions,
        data["verdict"]["overall"],
        locale=chosen,
        trials=int(trials.get("value") or 1),
        trials_evidence=str(trials.get("evidence") or "DECLARED"),
        account=is_account_history(data),
    )


def _prefilled(contact_url: str, message: str) -> str:
    """A WhatsApp link that opens with ``message`` typed; other links unchanged."""
    parts = urlsplit(contact_url)
    if parts.netloc not in {"wa.me", "api.whatsapp.com"} or "text=" in parts.query:
        return contact_url
    query = (parts.query + "&" if parts.query else "") + "text=" + quote(message)
    return urlunsplit(parts._replace(query=query))


def _short_time(stamp: str) -> str:
    """``2026-09-24T19:40:12.123456Z`` as ``2026-09-24 19:40 UTC``."""
    stamp = str(stamp)
    return f"{stamp[:10]} {stamp[11:16]} UTC" if len(stamp) >= 16 else stamp


#: Totals a platform prints that the audit re-counts from the file's rows:
#: ``(metadata key, trade-stats key, tolerance, is a count)``. The profit
#: factor is left out: platforms count commission and swap in it differently.
READING_CHECKS: tuple[tuple[str, str, float, bool], ...] = (
    ("declared_total_trades", "trade_count", 0.5, True),
    ("declared_total_net_profit", "net_pnl", 0.011, False),
)


def _lead_number(text: object) -> float | None:
    """The first number in a platform figure such as ``'1 279.20 (38.80%)'``.

    Read as the importers read it, so ``'1 279,20'`` from a terminal set to
    Spanish or Portuguese is 1279.20 too.
    """
    number = lead_number(str(text or ""))
    if number is not None:
        return number
    match = re.match(r"\s*(-?[\d\s]+(?:\.\d+)?)", str(text or ""))
    if not match:
        return None
    try:
        return float(match.group(1).replace(" ", "").replace("\u00a0", ""))
    except ValueError:
        return None


def _reading_rows(data: dict[str, Any]) -> list[tuple[str, float, float, bool]]:
    """``(label key, platform value, value read from the rows, matches)``."""
    meta = (data.get("inputs") or {}).get("report_metadata") or {}
    stats = data.get("trade_stats") or {}
    rows = []
    for meta_key, stat_key, tolerance, _count in READING_CHECKS:
        declared = _lead_number(meta.get(meta_key))
        measured = _ev_value(stats.get(stat_key))
        closing = _lead_number(meta.get("closing_deals"))
        if stat_key == "trade_count" and closing is not None and closing == declared:
            # MetaTrader counts each partial close as a trade: its figure is
            # the file's own closing deals, one per row of the Deals table.
            measured = closing
        if declared is None or measured is None:
            continue
        if stat_key == "net_pnl":
            # Each printed trade result is rounded to the cent, the platform's
            # total is not: up to half a cent per trade is rounding.
            trades = _ev_value(stats.get("trade_count")) or 0
            tolerance = max(tolerance, 0.005 * trades)
        rows.append((stat_key, declared, measured, abs(declared - measured) <= tolerance))
    return rows


def _reading_html(data: dict[str, Any], labels: dict[str, str]) -> str:
    """Did the audit read the file the way the platform did? Shown before
    payment too: these are the customer's own totals, re-counted."""
    rows = _reading_rows(data)
    if not rows:
        return ""

    def number(key: str, value: float) -> str:
        return f"{value:,.0f}" if key == "trade_count" else f"{value:,.2f}"

    body = "".join(
        f"<div class='recon-row {'ok' if ok else 'bad'}'>"
        f"<div class='recon-k'>{_e(_key_label(key, labels))}</div>"
        f"<div class='recon-v'><span><small>{_e(labels['reading_platform'])}</small>"
        f"<b>{_e(number(key, declared))}</b></span>"
        f"<i aria-hidden='true'>{'=' if ok else '≠'}</i>"
        f"<span><small>{_e(labels['reading_rows'])}</small>"
        f"<b>{_e(number(key, measured))}</b></span></div>"
        f"<span class='badge {'PASS' if ok else 'FAIL'}'>"
        f"{_e(labels['reading_ok'] if ok else labels['reading_bad'])}</span></div>"
        for key, declared, measured, ok in rows
    )
    all_ok = all(ok for *_, ok in rows)
    return (
        f"<p class='muted'>{_e(labels['reading_intro'])}</p>"
        f"<div class='recon'>{body}</div>"
        f"<p class='recon-foot {'ok' if all_ok else 'bad'}'>"
        f"{_e(labels['reading_all_ok' if all_ok else 'reading_some_bad'])}</p>"
    )


WEEKDAYS: dict[str, tuple[str, ...]] = {
    "es": ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"),
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
}


def _block_name(key: int) -> str:
    start = key * 4
    return f"{start:02d}:00–{start + 3:02d}:59"


LIVE_TONE = {"CONSISTENT": "PASS", "EDGE": "WEAK", "INCONSISTENT": "FAIL", "ABOVE": "WEAK"}


def _live_html(live: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    """The live statement placed among resampled backtest histories."""
    if not live:
        return ""
    if live.get("status") != "MEASURED":
        return _status_line(live, labels)
    outcome = live["outcome"]
    bt, lv, expected = live["backtest"], live["live"], live["expected"]

    def money(value: float) -> str:
        return f"{value:,.2f}"

    def pct(value: float) -> str:
        return f"{value:.0%}"

    def band(key: str, fmt: Any) -> str:
        return f"{fmt(expected[key]['p5'])} … {fmt(expected[key]['p95'])}"

    def cell(side: dict[str, Any], key: str, fmt: Any) -> str:
        item = side.get(key)
        return fmt(item["value"]) if item else "—"

    rows = [
        (labels["live_trades"], f"{bt['trades']['value']:,}", f"{lv['trades']['value']:,}", ""),
        (
            labels["live_period"],
            f"{bt['start']} – {bt['end']}",
            f"{lv['start']} – {lv['end']}",
            "",
        ),
        (
            labels["live_per_month"],
            f"{bt['per_month']['value']:.1f}",
            f"{lv['per_month']['value']:.1f}",
            "",
        ),
        (
            labels["live_win_rate"],
            cell(bt, "win_rate", pct),
            cell(lv, "win_rate", pct),
            band("win_rate", pct),
        ),
        (labels["live_net"], cell(bt, "net", money), cell(lv, "net", money), band("net", money)),
        (
            labels["live_fall"],
            cell(bt, "max_fall", money),
            cell(lv, "max_fall", money),
            band("max_fall", money),
        ),
        (labels["live_avg_win"], cell(bt, "avg_win", money), cell(lv, "avg_win", money), ""),
        (labels["live_avg_loss"], cell(bt, "avg_loss", money), cell(lv, "avg_loss", money), ""),
    ]
    live_head = "live_col_live_rescaled" if live.get("rescaled") else "live_col_live"
    table = (
        "<table class='live'><thead><tr><th></th>"
        f"<th class='val'>{_e(labels[live_head])}</th>"
        f"<th class='val'>{_e(labels['live_col_expected'])}</th>"
        f"<th class='val'>{_e(labels['live_col_backtest'])}</th></tr></thead><tbody>"
        + "".join(
            f"<tr><td>{_e(name)}</td>"
            f"<td class='val' data-l='{_e(labels[live_head])}'><strong>{_e(b)}</strong></td>"
            f"<td class='val{'' if c else ' empty'}' data-l='{_e(labels['live_col_expected'])}'>"
            f"{_e(c)}</td>"
            f"<td class='val' data-l='{_e(labels['live_col_backtest'])}'>{_e(a)}</td></tr>"
            for name, a, b, c in rows
        )
        + "</tbody></table>"
    )
    notes = [
        labels["live_rescaled"].format(ratio=live["size_ratio"]["value"])
        if live.get("rescaled")
        else labels["live_same_size"]
    ]
    if live.get("pace_differs"):
        notes.append(labels["live_pace"].format(ratio=live["pace_ratio"]["value"]))
    if live.get("overlap"):
        notes.append(labels["live_overlap"])
    if live.get("new_symbols"):
        notes.append(labels["live_symbols"].format(symbols=", ".join(live["new_symbols"])))
    tails = (
        "<div class='facts'>"
        + "".join(
            f"<div class='fact'><b>{pct(live[key]['value'])}</b>"
            f"<p>{_e(labels[label])} {_badge(live[key]['evidence'])}</p></div>"
            for label, key in (("live_below", "net_below"), ("live_fall_above", "fall_above"))
        )
        + "</div>"
    )
    return (
        f"<p class='muted'>{_e(labels['live_intro'].format(samples=live['samples']))}</p>"
        f"<p class='live-verdict lv-{LIVE_TONE[outcome]}'><span class='badge {LIVE_TONE[outcome]}'>"
        f"{_e(labels['live_badge_' + outcome])}</span> {_e(labels['live_' + outcome])}</p>"
        + table
        + tails
        + "".join(f"<p class='muted'>{_e(note)}</p>" for note in notes)
        + f"<p class='muted'>{_e(localize(live.get('note', ''), locale))}</p>"
        + _pairing_html(live.get("pairing"), locale, labels)
    )


def _pairing_html(pairing: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    """Live trades paired with the backtest's on the dates both files cover."""
    if not pairing or pairing.get("status") != "MEASURED":
        return ""

    def number(value: float, digits: int = 2) -> str:
        return f"{value:,.{digits}f}"

    def value(item: dict[str, Any], fmt: Any) -> str:
        if item.get("evidence") != "MEASURED":
            reason = _localized_reason(item.get("note", ""), locale)
            return f"{_badge('NOT_MEASURED')} <span class='muted'>{_e(reason)}</span>"
        return f"{_e(fmt(item['value']))} {_badge('MEASURED')}"

    share = pairing["matched_share"]
    found = labels["live_pair_of"].format(
        matched=pairing["matched"]["value"],
        total=pairing["live_trades"]["value"],
        share=f"{share['value']:.0%}" if share.get("value") is not None else "—",
    )
    rows = [
        (labels["live_pair_found"], f"{_e(found)} {_badge('MEASURED')}"),
        (
            labels["live_pair_missing"],
            _e(
                labels["live_pair_of"].format(
                    matched=pairing["missing_live"]["value"],
                    total=pairing["backtest_trades"]["value"],
                    share=f"{pairing['missing_live']['value'] / backtest_total:.0%}",
                )
            )
            + f" {_badge('MEASURED')}"
            if (backtest_total := pairing["backtest_trades"]["value"])
            else f"{pairing['missing_live']['value']:,} {_badge('MEASURED')}",
        ),
        (
            labels["live_pair_entry"],
            value(pairing["entry_bps"], lambda v: labels["live_pair_bps"].format(bps=number(v, 1))),
        ),
        (
            labels["live_pair_exit"],
            value(pairing["exit_bps"], lambda v: labels["live_pair_bps"].format(bps=number(v, 1))),
        ),
    ]
    gap = pairing["result_gap"]
    if gap.get("evidence") == "MEASURED":
        each = pairing["result_gap_per_trade"]["value"]
        text = labels["live_pair_gap_value"].format(total=number(gap["value"]), each=number(each))
        rows.append((labels["live_pair_gap"], f"{_e(text)} {_badge('MEASURED')}"))
    else:
        rows.append((labels["live_pair_gap"], value(gap, str)))
    intro = labels["live_pair_intro"].format(start=pairing["start"], end=pairing["end"])
    low = (
        f"<p><span class='badge WEAK'>{_e(labels['live_badge_ABOVE'])}</span> "
        f"{_e(labels['live_pair_low'])}</p>"
        if pairing.get("low_match")
        else ""
    )
    return (
        f"<h3>{_e(labels['live_pair'])}</h3><p class='muted'>{_e(intro)}</p>"
        + low
        + "<table class='pair'><tbody>"
        + "".join(f"<tr><td>{_e(name)}</td><td class='val'>{cell}</td></tr>" for name, cell in rows)
        + "</tbody></table>"
        + f"<p class='muted'>{_e(labels['live_pair_help'])}</p>"
    )


def _timing_table(rows: list[dict[str, Any]], head: str, name: Any, labels: dict[str, str]) -> str:
    widest = max((abs(row["net"]["value"]) for row in rows), default=0.0) or 1.0

    def net_cell(net: float) -> str:
        width = max(2.0, abs(net) / widest * 100)
        side = "neg" if net < 0 else "pos"
        return (
            f"<td class='val tbar {side}' data-l='{_e(labels['timing_net'])}'>"
            "<span class='tbar-track' aria-hidden='true'>"
            f"<span style='--w:{width:.0f}%'></span></span><b>{_signed_amount(net)}</b></td>"
        )

    body = "".join(
        f"<tr><td>{_e(name(row['key']))}</td>"
        f"<td class='val' data-l='{_e(labels['timing_trades'])}'>{row['trades']['value']:,}</td>"
        f"{net_cell(row['net']['value'])}"
        f"<td class='val' data-l='{_e(labels['timing_hits'])}'>{row['win_rate']['value']:.0%}</td>"
        "</tr>"
        for row in rows
    )
    return (
        "<table class='timing'><colgroup><col class='c-k'><col class='c-n'><col>"
        "<col class='c-n'></colgroup>"
        f"<thead><tr><th>{_e(head)}</th><th class='val'>{_e(labels['timing_trades'])}</th>"
        f"<th class='val'>{_e(labels['timing_net'])}</th>"
        f"<th class='val'>{_e(labels['timing_hits'])}</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _account_html(account: dict[str, Any] | None, labels: dict[str, str]) -> str:
    """Deposits, withdrawals and open positions of an account history."""
    if not account or account.get("status") != "MEASURED":
        return (
            f"<p>{_badge('NOT_MEASURED')} <span class='muted'>"
            f"{_e(labels['account_backtest'])}</span></p>"
        )
    out = f"<p class='muted'>{_e(labels['account_intro'])}</p>"
    if account.get("source") == "live":
        out += f"<p>{_e(labels['account_live'])}</p>"
        found = account.get("flags") or []
        if found:
            locale = _locale_of(labels)
            out += (
                "<ul class='flag-list acct-flags'>"
                + "".join(
                    f"<li>{_severity_badge(flag['severity'], locale)}"
                    f"<div><b>{_e(flag_title(flag['code'], locale))}</b>"
                    f"<p>{_e(localize(flag['detail'], locale))}</p></div></li>"
                    for flag in found
                )
                + "</ul>"
            )
    facts = []
    gain = account["percent_gain"]["value"]
    if gain is not None:
        facts.append(
            f"<div class='fact{' neg' if gain < 0 else ''}'><b>{_pct(gain, places=0)}</b>"
            f"<p>{_e(labels['account_gain'])} "
            f"{_badge(account['percent_gain']['evidence'])}</p></div>"
        )
    money = account["trading_result"]["value"]
    deposited = _fmt(float(account["deposits"]["total"]["value"]), key="deposits_total")
    facts.append(
        f"<div class='fact{' neg' if float(money) < 0 else ''}'>"
        f"<b>{_fmt(float(money), key='trading_result')}</b>"
        f"<p>{_e(labels['account_money'].format(deposited=deposited))} "
        f"{_badge(account['trading_result']['evidence'])}</p></div>"
    )
    floating = account["floating_share"]["value"]
    if floating is not None and floating < 0:
        facts.append(
            f"<div class='fact neg'><b>{_pct(-floating, places=0)}</b>"
            f"<p>{_e(labels['account_floating'])} "
            f"{_badge(account['floating_share']['evidence'])}</p></div>"
        )
    out += f"<div class='facts'>{''.join(facts)}</div>"
    near_empty = account.get("near_empty")
    if isinstance(near_empty, dict) and near_empty.get("first"):
        count = int(near_empty["days"]["value"])
        days = labels[
            "account_near_empty_days" if count == 1 else "account_near_empty_days_many"
        ].format(n=count)
        line = labels["account_near_empty"].format(
            date=_date_text(str(near_empty["first"]), _locale_of(labels)), days=days
        )
        out += (
            f"<p class='live-verdict lv-WEAK'><span class='badge WEAK'>"
            f"{_e(labels['account_trimmed_badge'])}</span> {_e(line)} "
            f"{_badge(near_empty['days']['evidence'])}</p>"
        )
    if account.get("starts_with_deposit") is False:
        opened = _date_text(str(account["first_trade"]), _locale_of(labels))
        out += (
            f"<p class='live-verdict lv-WEAK'><span class='badge WEAK'>"
            f"{_e(labels['account_trimmed_badge'])}</span> "
            f"{_e(labels['account_trimmed'].format(date=opened))}</p>"
        )
    flat = {
        "deposits_count": account["deposits"]["count"],
        "deposits_total": account["deposits"]["total"],
        "withdrawals_count": account["withdrawals"]["count"],
        "withdrawals_total": account["withdrawals"]["total"],
        **{
            key: account[key]
            for key in (
                "trading_result",
                "percent_gain",
                "result_on_deposits",
                "withdrawn_share",
                "later_deposits",
                "top_ups",
                "floating_pnl",
                "floating_share",
            )
        },
    }
    out += _evidence_rows(flat, labels, skip=set())
    listed = account.get("deposit_list") or []
    if listed:
        rows = "".join(
            f"<tr><td>{_e(str(item['time'])[:10])}</td>"
            f"<td class='val' data-l='{_e(labels['account_amount'])}'>"
            f"{_fmt(float(item['amount']['value']), key='amount')}</td>"
            f"<td class='val' data-l='{_e(labels['account_before'])}'>"
            f"{_fmt(item['balance_before']['value'], key='balance_before')}</td>"
            f"<td class='val' data-l='{_e(labels['account_drawdown'])}'>"
            f"{_fmt(item['drawdown']['value'], key='drawdown')}</td></tr>"
            for item in listed
        )
        out += (
            f"<h3>{_e(labels['account_deposits'])}</h3>"
            "<table class='metrics deposits'><thead><tr>"
            f"<th>{_e(labels['account_date'])}</th>"
            f"<th class='val'>{_e(labels['account_amount'])}</th>"
            f"<th class='val'>{_e(labels['account_before'])}</th>"
            f"<th class='val'>{_e(labels['account_drawdown'])}</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    if account.get("clean"):
        # "No large open loss" only when the file states the open result at all.
        seen = (account.get("floating_pnl") or {}).get("evidence") != "NOT_MEASURED"
        key = "account_clean" if seen else "account_clean_unseen"
        tone = " lv-PASS" if seen else ""
        out += f"<p class='live-verdict{tone}'>{_e(labels[key])}</p>"
    out += f"<p class='muted'>{_e(labels['account_scope'])}</p>"
    return out


def _forward_html(forward: dict[str, Any] | None, labels: dict[str, str]) -> str:
    """The optimisation's backtest ranking against its forward period."""
    if not forward or forward.get("status") != "MEASURED":
        return ""
    out = f"<p class='muted'>{_e(labels['forward_intro'])}</p>"
    tone = " neg" if forward.get("clean") is False else ""
    rho = forward["rank_correlation"]
    facts = [
        f"<div class='fact{tone}'><b>{float(rho['value']):.2f}</b>"
        f"<p>{_e(labels['forward_rank'])} {_badge(rho['evidence'])}</p></div>"
    ]
    top_n = int(forward["top_count"]["value"])
    for key, label in (
        ("top_in_profit", labels["forward_top"].format(n=top_n)),
        ("all_in_profit", labels["forward_all"]),
        ("chosen_forward_share", labels["forward_chosen"]),
    ):
        item = forward.get(key) or {}
        if item.get("value") is not None:
            facts.append(
                f"<div class='fact{tone if key == 'top_in_profit' else ''}'>"
                f"<b>{float(item['value']):.0%}</b>"
                f"<p>{_e(label)} {_badge(item['evidence'])}</p></div>"
            )
    # The answer first, then the four figures behind it as a two-by-two grid.
    if forward.get("clean"):
        out += (
            f"<p class='live-verdict lv-PASS'><span class='badge PASS'>"
            f"{_e(labels['forward_badge_held'])}</span> {_e(labels['forward_held'])}</p>"
        )
    else:
        out += (
            f"<p class='live-verdict lv-WEAK'><span class='badge WEAK'>"
            f"{_e(labels['forward_badge_lost'])}</span> {_e(labels['forward_lost'])}</p>"
        )
    grid = " pairs" if len(facts) % 2 == 0 else ""
    return out + f"<div class='facts{grid}'>{''.join(facts)}</div>"


def _plateau_html(plateau: dict[str, Any] | None, labels: dict[str, str]) -> str:
    """The chosen optimisation pass against its neighbours."""
    if not plateau or plateau.get("status") != "MEASURED":
        return ""
    out = f"<p class='muted'>{_e(labels['plateau_intro'])}</p>"
    by = "plateau_by_report" if plateau.get("chosen_by") == "report" else "plateau_by_best"
    chips = "".join(
        f"<span class='param'>{_e(name)} <b>{_e(_fmt(value))}</b></span>"
        for name, value in plateau["chosen"].items()
    )
    out += f"<p class='chosen'>{_e(labels[by])}</p><p class='params'>{chips}</p>"
    tone = " neg" if plateau.get("clean") is False else ""
    facts = []
    for key, label in (
        ("neighbours_keep", "plateau_keep"),
        ("neighbours_in_profit", "plateau_in_profit"),
    ):
        value = plateau[key]["value"]
        if value is not None:
            facts.append(
                f"<div class='fact{tone}'><b>{max(float(value), 0.0):.0%}</b>"
                f"<p>{_e(labels[label])} {_badge(plateau[key]['evidence'])}</p></div>"
            )
    verdict = ""
    if plateau["neighbours_keep"]["value"] is not None:
        if plateau.get("clean"):
            verdict = (
                f"<p class='live-verdict lv-PASS'><span class='badge PASS'>"
                f"{_e(labels['plateau_badge_clean'])}</span> {_e(labels['plateau_clean'])}</p>"
            )
        else:
            verdict = (
                f"<p class='live-verdict lv-WEAK'><span class='badge WEAK'>"
                f"{_e(labels['plateau_badge_peak'])}</span> {_e(labels['plateau_peak'])}</p>"
            )
    if facts:
        out += f"<div class='facts'>{''.join(facts)}</div>"
    out += verdict
    listed = plateau.get("neighbour_list") or []
    if listed:
        rows = "".join(
            f"<tr><td>{_e(item['parameter'])}</td>"
            f"<td class='val' data-l='{_e(labels['plateau_value'])}'>{_fmt(item['value'])}</td>"
            f"<td class='val{' neg' if float(item['result']) < 0 else ''}' "
            f"data-l='{_e(labels['plateau_result'])}'>"
            f"{_fmt(float(item['result']), key='plateau_result')}</td></tr>"
            for item in listed
        )
        out += (
            f"<h3>{_e(labels['plateau_neighbours'])}</h3>"
            "<table class='metrics neighbours'><thead><tr>"
            f"<th>{_e(labels['plateau_parameter'])}</th>"
            f"<th class='val'>{_e(labels['plateau_value'])}</th>"
            f"<th class='val'>{_e(labels['plateau_result'])}</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    rows_data = {
        key: plateau[key]
        for key in (
            "chosen_result",
            "passes",
            "passes_in_profit",
            "chosen_top_share",
            "neighbours_found",
            "neighbours_in_profit",
            "neighbours_keep",
        )
    }
    out += _evidence_rows(rows_data, labels, skip=set())
    # A normal export: say what a forward one adds, since the plateau steps aside for it.
    out += f"<p class='muted'>{_e(labels['plateau_forward_hint'])}</p>"
    return out


def _capital_shown(capital: dict[str, Any] | None) -> bool:
    """The capital section shows for any file with trades, measured or not."""
    if not capital:
        return False
    return capital.get("status") == "MEASURED" or capital.get("reason") != "no trades uploaded"


def _capital_html(
    capital: dict[str, Any] | None,
    locale: str,
    labels: dict[str, str],
    *,
    account: bool = False,
    closed_dd: float | None = None,
    platform_dd: float | None = None,
    closed_only: bool = False,
    hidden_note: str = "",
) -> str:
    """Capital and size for each loss limit.

    ``account`` words the sizes as the account's own; ``platform_dd`` (deeper
    than ``closed_dd``) or ``closed_only`` say that open losses are left out."""
    if not capital:
        return ""
    if capital.get("status") != "MEASURED":
        # The hint answers "too few trades" or "too short"; not "no fall to size".
        short = str(capital.get("reason", "")).startswith("needs ")
        hint = f"<p class='muted'>{_e(labels['capital_missing'])}</p>" if short else ""
        reason = _localized_reason(str(capital.get("reason", "")), locale)
        parts = re.split(r";\s+(?=(?:sube|upload)\b)", reason, maxsplit=1)
        if len(parts) == 2:
            # "...understate the real fall; upload an equity curve..." puts the fix on its own line.
            head = parts[0][:1].upper() + parts[0][1:]
            fix = parts[1][:1].upper() + parts[1][1:].rstrip(".") + "."
            return (
                f"<div class='live-verdict held'><p>{_badge('NOT_MEASURED')} "
                f"<span class='muted'>{_e(head)}.</span></p>"
                f"<p class='muted'><b>{_e(labels['what_to_do'])}</b> {_e(fix)}</p>{hint}</div>"
            )
        # One capitalised, closed sentence, like the reasons that carry a fix.
        text = reason[:1].upper() + reason[1:].rstrip(".") + "." if reason else ""
        return (
            f"<div class='live-verdict held'><p>{_badge('NOT_MEASURED')} "
            f"<span class='muted'>{_e(text)}</span></p>{hint}</div>"
        )

    def label(key: str) -> str:
        return labels.get(f"{key}_account", labels[key]) if account else labels[key]

    samples = int((capital.get("method") or {}).get("samples") or 0)
    out = f"<p class='muted'>{_e(labels['capital_intro'].format(samples=samples))}</p>"
    if capital.get("short_history"):
        days = int((capital.get("span_days") or {}).get("value") or 0)
        head, _, rest = labels["capital_short"].format(days=days).partition(". ")
        out += f"<p class='live-verdict lv-WEAK'><b>{_e(head)}.</b> {_e(rest)}</p>"
    out += hidden_note
    reference = float(capital["fall_reference"]["value"])
    history = float(capital["fall_history"]["value"])
    platform = (capital.get("fall_platform") or {}).get("value")
    per_year = capital["trades_per_year"]
    pace_note = localize(per_year.get("note", ""), locale)
    # The note already says what the number is; the label is the fallback.
    pace_text = (
        pace_note[:1].upper() + pace_note[1:]
        if pace_note
        else _key_label("trades_per_year", labels)
    )
    out += (
        "<div class='facts'>"
        f"<div class='fact'><b>{_fmt(reference, key='fall_reference')}</b>"
        f"<p>{_e(label('capital_fall'))} {_badge(capital['fall_reference']['evidence'])}</p></div>"
        f"<div class='fact'><b>{_fmt(history, key='fall_history')}</b>"
        f"<p>{_e(labels['capital_history'])} "
        f"{_badge(capital['fall_history']['evidence'])}</p></div>"
        + (
            f"<div class='fact'><b>{_fmt(float(platform), key='fall_platform')}</b>"
            f"<p>{_e(labels['capital_platform'])} "
            f"{_badge(capital['fall_platform']['evidence'])}</p></div>"
            if platform is not None
            else ""
        )
        # The pace the year is drawn at, as a card beside the falls it sizes.
        + f"<div class='fact'><b>{_fmt(per_year['value'])}</b>"
        f"<p>{_e(pace_text)} {_badge(per_year['evidence'])}</p></div>" + "</div>"
    )
    balance = capital["starting_balance"]["value"]
    scale_head = (
        labels["capital_scale"].format(balance=_fmt(float(balance), key="starting_balance"))
        if balance
        else labels["capital_scale_plain"]
    )

    def size_text(row: dict[str, Any]) -> str:
        share = row["size_share"]["value"]
        return sizing_scale_text(float(share), locale) if share is not None else "—"

    # One card per loss limit: a reader compares four numbers, not a table.
    tiles = "".join(
        "<li class='cap'>"
        f"<span class='cap-lim'>{_e(labels['capital_limit'])} "
        f"<b>{float(row['limit']):.0%}</b></span>"
        f"<b class='cap-money'>{_fmt(row['capital']['value'], key='capital')}</b>"
        f"<span class='cap-sub'>{_e(label('capital_needed'))}</span>"
        f"<span class='cap-size'><b>{_e(size_text(row))}</b> {_e(scale_head)}</span></li>"
        for row in capital["rows"]
    )
    out += f"<ol class='caps'>{tiles}</ol><p class='muted'>{_e(label('capital_scale_help'))}</p>"
    if platform_dd is not None and closed_dd is not None and platform_dd < closed_dd - 0.005:
        key = "capital_open_loss_floored" if platform is not None else "capital_open_loss"
        text = labels[key].format(
            platform=f"{abs(platform_dd):.1%}", closed=f"{abs(closed_dd):.1%}"
        )
        out += (
            f"<p class='live-verdict lv-FAIL'><span class='badge FAIL'>"
            f"{_e(labels['open_loss_badge'])}</span> {_e(text)}</p>"
        )
    elif closed_only:
        out += f"<p class='muted'>{_e(labels['capital_closed_only'])}</p>"
    return out + _assumptions(capital.get("assumptions"), locale, labels)


#: The tester's modelling modes as a reader says them.
TICK_MODEL_TEXT: dict[str, dict[str, str]] = {
    "es": {
        "every tick": "Cada tick",
        "control points": "Puntos de control",
        "open prices only": "Solo precios de apertura",
        "real ticks": "Ticks reales",
    },
    "en": {
        "every tick": "Every tick",
        "control points": "Control points",
        "open prices only": "Open prices only",
        "real ticks": "Real ticks",
    },
}


def _test_data_html(review: dict[str, Any] | None, labels: dict[str, str]) -> str:
    """Tick model, data quality and test window of a tester report."""
    if not review or review.get("status") != "MEASURED":
        return ""
    locale = _locale_of(labels)
    rows = {key: dict(value) for key, value in review.items() if _is_evidence(value)}
    model = rows.get("tick_model")
    if model and isinstance(model.get("value"), str):
        model["value"] = TICK_MODEL_TEXT[locale].get(model["value"], model["value"])
    out = f"<p class='muted'>{_e(labels['test_data_intro'])}</p>"
    out += _evidence_rows(rows, labels, skip=set())
    if review.get("clean"):
        out += f"<p class='live-verdict lv-PASS'>{_e(labels['test_data_clean'])}</p>"
    out += f"<p class='muted'>{_e(labels['test_data_scope'])}</p>"
    return out


def _timing_fact(share: float, sentence: str, evidence: str = "MEASURED") -> str:
    return f"<div class='fact'><b>{share:.0%}</b><p>{_e(sentence)} {_badge(evidence)}</p></div>"


def _timing_html(timing: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    """Trades by weekday and four-hour block, with the best group's share."""
    if not timing or timing.get("status") != "MEASURED":
        reason = (timing or {}).get("reason", "")
        return (
            f"<p>{_badge('NOT_MEASURED')} <span class='muted'>"
            f"{_e(localize(reason, locale))}</span></p>"
        )
    days = WEEKDAYS.get(locale, WEEKDAYS["es"])
    out = f"<p class='muted'>{_e(labels['timing_intro'])}</p>"
    facts = ""
    best_day = timing.get("best_weekday")
    if best_day:
        share = best_day["share"]["value"]
        text = labels["timing_best_day"].format(share=share, day=days[best_day["key"]])
        facts += _timing_fact(share, text, best_day["share"].get("evidence", "MEASURED"))
    best_block = timing.get("best_block")
    if best_block:
        share = best_block["share"]["value"]
        text = labels["timing_best_block"].format(share=share, block=_block_name(best_block["key"]))
        facts += _timing_fact(share, text, best_block["share"].get("evidence", "MEASURED"))
    if facts:
        out += f"<div class='facts'>{facts}</div>"
    out += _timing_table(timing["weekdays"], labels["timing_day"], lambda k: days[k], labels)
    if timing.get("blocks"):
        out += _timing_table(timing["blocks"], labels["timing_block"], _block_name, labels)
    out += f"<p class='muted'>{_e(localize(timing.get('note', ''), locale))}</p>"
    return out


_MONTHS_SHORT = {
    "es": ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"),
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
}


def _date_text(iso: str, locale: str) -> str:
    """``2024-01-05`` as ``5 ene 2024`` or ``5 Jan 2024``."""
    year, month, day = (int(part) for part in iso[:10].split("-"))
    months = _MONTHS_SHORT.get(locale, _MONTHS_SHORT["es"])
    return f"{day} {months[month - 1]} {year}"


def _signed_z(value: float) -> str:
    text = f"{value:+.1f}"
    return "0.0" if text in ("+0.0", "-0.0") else text


def _recent_html(recent: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    """The last third of the history against the two before it."""
    if not recent or recent.get("status") != "MEASURED":
        reason = (recent or {}).get("reason", "")
        return (
            f"<p>{_badge('NOT_MEASURED')} <span class='muted'>"
            f"{_e(localize(reason, locale))}</span></p>"
        )
    out = f"<p class='muted'>{_e(labels['recent_intro'])}</p>"
    early_mean = _ev_value(recent["early"].get("mean"))
    late_mean = _ev_value(recent["recent"].get("mean"))
    if is_weaker(recent) and early_mean is not None and late_mean is not None:
        text = labels["recent_weaker"].format(
            early=_signed_amount(early_mean),
            late=_signed_amount(late_mean),
            change=f"{late_mean / early_mean - 1:+.0%}",
        )
        out += (
            f"<p class='live-verdict lv-WEAK'><span class='badge WEAK'>"
            f"{_e(labels['recent_badge_weaker'])}</span> {_e(text)}</p>"
        )
    elif recent.get("clean"):
        out += (
            f"<p class='live-verdict lv-PASS'><span class='badge PASS'>"
            f"{_e(labels['recent_badge_held'])}</span> {_e(labels['recent_held'])}</p>"
        )
    else:
        out += (
            f"<p class='live-verdict lv-WEAK'><span class='badge WEAK'>"
            f"{_e(labels['recent_badge_faded'])}</span> {_e(labels['recent_faded'])}</p>"
        )
    date = _date_text(recent["recent_from"], locale)
    tone = " neg" if recent.get("clean") is False else ""
    late = recent["recent"]
    cells = [
        ("", recent["early"]["mean"], labels["recent_early"].format(date=date), "money"),
        (tone, late["mean"], labels["recent_late"].format(date=date), "money"),
        (
            tone,
            late["net"],
            labels["recent_net"].format(date=date, n=f"{int(late['trades']['value']):,}"),
            "money",
        ),
    ]
    if recent.get("drop_z"):
        cells.append((tone, recent["drop_z"], labels["recent_z"], "z"))
    facts = "".join(
        f"<div class='fact{cls}'><b>"
        + (
            _signed_amount(float(item["value"]))
            if kind == "money"
            else _signed_z(float(item["value"]))
        )
        + f"</b><p>{_e(text)} {_badge(item['evidence'])}</p></div>"
        for cls, item, text, kind in cells
    )
    grid = " pairs" if len(cells) % 2 == 0 else ""
    out += f"<div class='facts{grid}'>{facts}</div>"
    out += _timing_table(recent["years"], labels["recent_year"], str, labels)
    out += f"<p class='muted'>{_e(_sentence(localize(recent.get('note', ''), locale)))}</p>"
    return out


def _luck_html(
    luck: dict[str, Any] | None,
    locale: str,
    labels: dict[str, str],
    multiplicity: dict[str, Any] | None = None,
    dsr_pass: float = DEFAULT_THRESHOLDS.dsr_pass,
) -> str:
    """The file's Sharpe next to the luck of the configurations counted, and
    what a search of 10, 100 or 1,000 would need.

    Beating the luck is a DSR of at least 0.5; the multiplicity dimension
    passes only at 0.95, so a Sharpe between the two says it beats the luck
    without the margin the dimension asks."""
    if not luck or luck.get("status") != "MEASURED":
        return ""
    sharpe = f"{float(luck['sharpe']['value']):.2f}"

    def years(value: float) -> str:
        if value > LUCK_YEARS_SHOWN:
            return labels["luck_more_than"].format(n=LUCK_YEARS_SHOWN)
        if value >= 1:
            return f"{value:.1f} {labels['luck_years_unit']}"
        months = round(value * 12)
        if months < 1:
            return labels["luck_under_month"]
        return labels["luck_month_one" if months == 1 else "luck_months"].format(n=months)

    span_value = float(luck["span_years"]["value"])
    span = years(span_value)
    out = f"<p class='muted'>{_e(labels['luck_intro'])}</p>"
    if luck.get("counted"):
        n = f"{int(luck['trials']):,}"
        chance = f"{float(luck['luck_sharpe']['value']):.2f}"
        beats = bool(luck.get("beats_luck"))
        dsr_item = (multiplicity or {}).get("dsr_at_trials_used") or {}
        dsr = dsr_item.get("value") if dsr_item.get("evidence") == "MEASURED" else None
        narrow = beats and isinstance(dsr, (int, float)) and dsr < dsr_pass
        key = "narrow" if narrow else "beats" if beats else "below"
        tone = "PASS" if key == "beats" else "WEAK"
        line = labels["luck_" + key].format(
            sharpe=sharpe,
            luck=chance,
            n=n,
            dsr=f"{float(dsr or 0):.0%}",
            need=f"{dsr_pass:.0%}",
        )
        out += (
            f"<p class='live-verdict lv-{tone}'><span class='badge {tone}'>"
            f"{_e(labels['luck_badge_' + key])}</span> {_e(line)}</p>"
        )
        cells = [
            (chance, luck["luck_sharpe"], labels["luck_sharpe"].format(n=n, sharpe=sharpe)),
            (
                years(float(luck["years_needed"]["value"])),
                luck["years_needed"],
                labels["luck_years"].format(span=span),
            ),
            (
                f"{float(luck['sharpe_after']['value']):.2f}",
                luck["sharpe_after"],
                labels["luck_after"].format(n=n),
            ),
        ]
        tone = "" if beats else " neg"
        facts = "".join(
            f"<div class='fact{tone}'><b>{_e(value)}</b><p>{_e(text)} "
            f"{_badge(item['evidence'])}</p></div>"
            for value, item, text in cells
        )
        out += f"<div class='facts'>{facts}</div>"
    else:
        out += (
            f"<p>{_e(labels['luck_uncounted'])}</p>"
            f"<p>{_e(labels['luck_span_line'].format(sharpe=sharpe, span=span))} "
            f"{_badge(luck['sharpe']['evidence'])}</p>"
        )

    def enough(row: dict[str, Any]) -> str:
        return "yes" if float(row["years_needed"]["value"]) <= span_value else "no"

    rows = "".join(
        f"<tr><td data-l='{_e(labels['luck_table_trials'])}'>{int(row['trials']):,}</td>"
        f"<td class='val' data-l='{_e(labels['luck_table_luck'])}'>"
        f"{float(row['luck_sharpe']['value']):.2f}</td>"
        f"<td class='val' data-l='{_e(labels['luck_table_years'])}'>"
        f"{_e(years(float(row['years_needed']['value'])))}</td>"
        f"<td class='val enough-{enough(row)}' data-l='{_e(labels['luck_table_enough'])}'>"
        f"{_e(labels[enough(row)])}</td></tr>"
        for row in luck.get("what_if") or []
    )
    if rows:
        out += (
            f"<table class='luck'><thead><tr><th>{_e(labels['luck_table_trials'])}</th>"
            f"<th class='val'>{_e(labels['luck_table_luck'])}</th>"
            f"<th class='val'>{_e(labels['luck_table_years'])}</th>"
            f"<th class='val'>{_e(labels['luck_table_enough'])}</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    if span_value < 1:
        out += f"<p class='muted'>{_e(labels['luck_short'])}</p>"
    out += f"<p class='muted'>{_e(_sentence(localize(luck.get('note', ''), locale)))}</p>"
    return out


def _ride_html(
    ride: dict[str, Any] | None, locale: str, labels: dict[str, str], *, closed_only: bool
) -> str:
    """Time under water, the worst fall's way down and back, worst day and month."""
    if not ride or ride.get("status") != "MEASURED":
        return ""
    out = f"<p class='muted'>{_e(labels['ride_intro'])}</p>"

    def days(value: Any) -> str:
        return labels["ride_days"].format(n=f"{int(value):,}")

    def day(iso: str) -> str:
        return _date_text(iso, locale)

    under_text = (
        labels["ride_under"].format(
            start=day(ride["longest_under_from"]), end=day(ride["longest_under_to"])
        )
        if ride.get("longest_under_recovered")
        else labels["ride_under_open"].format(start=day(ride["longest_under_from"]))
    )
    cells: list[tuple[str, str, dict[str, Any], str]] = [
        ("", days(ride["longest_under"]["value"]), ride["longest_under"], under_text),
    ]
    fell = ride["fall_days"].get("evidence") == "MEASURED"
    if fell:
        back = ride["recovery_days"]
        cells.append(
            (
                "",
                days(ride["fall_days"]["value"]),
                ride["fall_days"],
                labels["ride_fall"].format(
                    start=day(ride["deepest_from"]), low=day(ride["deepest_low"])
                ),
            )
        )
        cells.append(
            (
                "" if ride.get("recovered") else " neg",
                days(back["value"])
                if back.get("evidence") == "MEASURED"
                else labels["ride_not_back"],
                back if back.get("evidence") == "MEASURED" else {"evidence": "MEASURED"},
                labels["ride_recovery"],
            )
        )
    worst_day = ride.get("worst_day") or {}
    if worst_day.get("evidence") == "MEASURED":
        cells.append(
            (
                " neg",
                _pct(float(worst_day["value"]), signed=True),
                worst_day,
                labels["ride_worst_day"].format(date=day(ride["worst_day_on"])),
            )
        )
    months = ride.get("months") or {}
    if months.get("evidence") == "MEASURED":
        total = int(months["value"])
        share = float(ride["positive_months"]["value"])
        cells.append(
            (
                " neg",
                _pct(float(ride["worst_month"]["value"]), signed=True),
                ride["worst_month"],
                labels["ride_worst_month"].format(
                    month=_date_text(ride["worst_month_in"] + "-01", locale).split(" ", 1)[1]
                ),
            )
        )
        cells.append(
            (
                "",
                _pct(share, places=0),
                ride["positive_months"],
                labels["ride_positive"].format(
                    k=round(share * total),
                    n=total,
                    run=int(ride["losing_months_run"]["value"]),
                ),
            )
        )
    facts = "".join(
        f"<div class='fact{cls}'><b>{_e(value)}</b><p>{_e(text)} {_badge(item['evidence'])}"
        "</p></div>"
        for cls, value, item, text in cells
    )
    grid = " pairs" if len(cells) % 2 == 0 else ""
    out += f"<div class='facts{grid}'>{facts}</div>"
    if fell and not ride.get("recovered"):
        out += f"<p class='muted'>{_e(labels['ride_not_back_note'])}</p>"
    if closed_only:
        out += f"<p class='muted'>{_e(labels['ride_closed'])}</p>"
    out += f"<p class='muted'>{_e(_sentence(localize(ride.get('note', ''), locale)))}</p>"
    return out


def _duration_text(hours: float, locale: str) -> str:
    """``0.5`` as ``30 min``, ``5.25`` as ``5.3 h``, ``50`` as ``2.1 días``."""
    if hours < 1:
        return f"{max(1, round(hours * 60))} min"
    if hours < 48:
        return f"{hours:.1f} h"
    return f"{hours / 24:.1f} " + {"es": "días", "pt": "dias"}.get(locale, "days")


def _behaviour_ask(text: str) -> str:
    """One finding: what the trades show, then the question to put to the seller."""
    for lead in (" Pregunta ", " Ask "):
        what, sep, ask = text.partition("." + lead)
        if sep:
            return (
                f"<li><p class='beh-what'>{_e(what)}.</p>"
                f"<p class='beh-ask'>{icon('chat')}<span>{_e(lead.strip())} {_e(ask)}</span>"
                "</p></li>"
            )
    return f"<li><p class='beh-what'>{_e(text)}</p></li>"


def _ratio_text(ratio: float) -> str:
    """``4.5`` as ``4.5``, ``0.036`` as ``0.036``: never a bare ``0.0``."""
    return f"{ratio:.1f}" if ratio >= 0.1 else f"{ratio:.2g}"


def _behaviour_html(behaviour: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    """Hold times, re-entries and streaks around losses; no class change."""
    if not behaviour or behaviour.get("status") != "MEASURED":
        return ""
    findings = list(behaviour.get("findings") or [])
    out = f"<p class='muted'>{_e(labels['behaviour_intro'])}</p>"
    if findings:
        items = "".join(_behaviour_ask(labels["beh_" + code]) for code in findings)
        out += (
            f"<div class='live-verdict lv-WEAK beh'><span class='badge WEAK'>"
            f"{_e(labels['beh_badge_found'])}</span><ul class='beh-asks'>{items}</ul></div>"
        )
    else:
        out += (
            f"<p class='live-verdict lv-PASS'><span class='badge PASS'>"
            f"{_e(labels['beh_badge_clean'])}</span> {_e(labels['beh_clean'])}</p>"
        )
    facts: list[str] = []
    ratio = behaviour.get("hold_ratio")
    if ratio:
        tone = " neg" if "losers_held_longer" in findings else ""
        text = labels["beh_hold"].format(
            loss=_duration_text(float(behaviour["hold_loss_hours"]["value"]), locale),
            win=_duration_text(float(behaviour["hold_win_hours"]["value"]), locale),
        )
        facts.append(
            f"<div class='fact{tone}'><b>{_ratio_text(float(ratio['value']))}×</b>"
            f"<p>{_e(text)} {_badge(ratio['evidence'])}</p></div>"
        )
    quick = behaviour.get("quick_after_loss")
    # Only worth a line when re-entries after a loss outnumber those after a win.
    if (
        quick
        and quick["evidence"] == "MEASURED"
        and float(quick["value"]) > float(behaviour["quick_after_win"]["value"])
    ):
        tone = " neg" if "quick_after_loss" in findings else ""
        text = labels["beh_quick"].format(win=f"{float(behaviour['quick_after_win']['value']):.0%}")
        facts.append(
            f"<div class='fact{tone}'><b>{float(quick['value']):.0%}</b>"
            f"<p>{_e(text)} {_badge(quick['evidence'])}</p></div>"
        )
    streak = behaviour.get("hit_rate_after_streak")
    if streak:
        tone = " neg" if "worse_after_streak" in findings else ""
        text = labels["beh_streak"].format(
            k=2,
            n=f"{int(behaviour['after_streak_trades']['value']):,}",
            all=f"{float(behaviour['hit_rate']['value']):.0%}",
        )
        facts.append(
            f"<div class='fact{tone}'><b>{float(streak['value']):.0%}</b>"
            f"<p>{_e(text)} {_badge(streak['evidence'])}</p></div>"
        )
    if facts:
        grid = " pairs" if len(facts) % 2 == 0 else ""
        out += f"<div class='facts{grid}'>{''.join(facts)}</div>"
    if quick and quick["evidence"] == "NOT_MEASURED":
        out += (
            f"<p class='muted'>{_e(labels['beh_quick_nm'])} {_badge('NOT_MEASURED')} "
            f"{_e(_sentence(localize(quick.get('note', ''), locale)))}</p>"
        )
    out += f"<p class='muted'>{_e(_sentence(localize(behaviour.get('note', ''), locale)))}</p>"
    return out


def _instruments_html(review: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    """Count, net result and hit rate per instrument; no class change."""
    if not review or review.get("status") != "MEASURED":
        return ""
    findings = list(review.get("findings") or [])
    best = (review.get("best") or {}).get("key", "")
    out = f"<p class='muted'>{_e(labels['ins_intro'])}</p>"
    if findings:
        texts = {
            "one_carries": labels["ins_one_carries"].format(best=best),
            "mostly_one": labels["ins_mostly_one"].format(
                best=best, share=f"{float(review['best']['share']['value']):.0%}"
            ),
            "most_lose": labels["ins_most_lose"].format(
                losing=int((review.get("losing") or {}).get("value", 0)),
                readable=int(review["readable"]["value"]),
            ),
        }
        items = "".join(_behaviour_ask(texts[code]) for code in findings)
        out += (
            f"<div class='live-verdict lv-WEAK beh'><span class='badge WEAK'>"
            f"{_e(labels['beh_badge_found'])}</span><ul class='beh-asks'>{items}</ul></div>"
        )
    elif review.get("best"):
        out += (
            f"<p class='live-verdict lv-PASS'><span class='badge PASS'>"
            f"{_e(labels['ins_badge_clean'])}</span> {_e(labels['ins_clean'])}</p>"
        )
    if review.get("best"):
        share = float(review["best"]["share"]["value"])
        tone = " neg" if {"one_carries", "mostly_one"} & set(findings) else ""
        out += (
            f"<div class='facts'><div class='fact{tone}'><b>{share:.0%}</b>"
            f"<p>{_e(labels['ins_best_over' if share > 1 else 'ins_best'].format(best=best))} "
            f"{_badge(review['best']['share']['evidence'])}</p></div></div>"
        )

    def name(key: str) -> str:
        if key != _INSTRUMENTS_OTHER:
            return key
        row = next(row for row in review["rows"] if row["key"] == key)
        return labels["ins_other"].format(n=int(row["instruments"]["value"]), m=_INSTRUMENTS_MIN)

    out += _timing_table(review["rows"], labels["ins_head"], name, labels)
    out += f"<p class='muted'>{_e(_sentence(localize(review.get('note', ''), locale)))}</p>"
    return out


def _fund_pct(value: float, places: int = 1) -> str:
    """A monthly or annual return as a signed percentage, never ``-0.0%``."""
    text = f"{value * 100:+.{places}f}%"
    return text[1:] if float(text[:-1]) == 0 else text


def _fund_calendar(years: list[dict[str, Any]], labels: dict[str, str]) -> str:
    head = "".join(f"<th>{_e(name)}</th>" for name in labels["fund_months"].split(","))
    rows = []
    for year in years:
        months = {int(k): v for k, v in (year.get("months") or {}).items()}
        cells = []
        for month in range(1, 13):
            cell = months.get(month)
            if cell is None or cell.get("value") is None:
                cells.append("<td class='empty'></td>")
                continue
            value = float(cell["value"])
            cells.append(f"<td class='{'neg' if value < 0 else 'pos'}'>{_fund_pct(value)}</td>")
        total = float(year["total"]["value"])
        rows.append(
            f"<tr><th scope='row'>{int(year['key'])}</th>{''.join(cells)}"
            f"<td class='tot {'neg' if total < 0 else 'pos'}'>{_fund_pct(total)}</td></tr>"
        )
    return (
        "<div class='fund-cal-wrap'><table class='fund-cal'>"
        f"<thead><tr><th>{_e(labels['fund_year'])}</th>{head}"
        f"<th class='tot'>{_e(labels['fund_total'])}</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _fund_html(fund: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    """A monthly track record read the way a fund investor reads it."""
    if not fund or fund.get("status") != "MEASURED":
        return ""
    findings = list(fund.get("findings") or [])
    vol = f"{float(fund['volatility']['value']):.1%}"
    vol_u = (fund.get("volatility_unsmoothed") or {}).get("value")
    out = f"<p class='muted'>{_e(labels['fund_intro'])}</p>"
    if findings:
        texts = {
            "smoothed": labels["fund_smoothed"].format(
                rho=f"{float(fund['autocorrelation']['value']):.2f}",
                vol_u=f"{float(vol_u):.1%}" if vol_u is not None else vol,
                vol=vol,
            ),
            "few_small_losses": labels["fund_few_small_losses"].format(
                gains=int(fund["small_gains"]["value"]),
                losses=int(fund["small_losses"]["value"]),
            ),
        }
        items = "".join(_behaviour_ask(texts[code]) for code in findings)
        out += (
            f"<div class='live-verdict lv-WEAK beh'><span class='badge WEAK'>"
            f"{_e(labels['beh_badge_found'])}</span><ul class='beh-asks'>{items}</ul></div>"
        )
    else:
        out += (
            f"<p class='live-verdict lv-PASS'><span class='badge PASS'>"
            f"{_e(labels['fund_badge_clean'])}</span> {_e(labels['fund_clean'])}</p>"
        )

    def tile(value: str, text: str, evidence: str, *, neg: bool = False) -> str:
        return (
            f"<div class='fact{' neg' if neg else ''}'><b>{_e(value)}</b>"
            f"<p>{_e(text)} {_badge(evidence)}</p></div>"
        )

    cagr = float(fund["cagr"]["value"])
    recovered = bool(fund["recovered"]["value"])
    facts = [
        tile(_fund_pct(cagr), labels["fund_cagr"], fund["cagr"]["evidence"], neg=cagr < 0),
        (
            tile(
                f"{float(vol_u):.1%}",
                labels["fund_vol_u"].format(vol=vol),
                fund["volatility_unsmoothed"]["evidence"],
                neg="smoothed" in findings,
            )
            if vol_u is not None
            else tile(vol, labels["fund_vol"], fund["volatility"]["evidence"])
        ),
        tile(
            f"{float(fund['positive_share']['value']):.0%}",
            labels["fund_positive"].format(n=int(fund["months"]["value"])),
            fund["positive_share"]["evidence"],
        ),
        tile(
            _fund_pct(float(fund["worst_month"]["value"])),
            labels["fund_worst"].format(best=_fund_pct(float(fund["best_month"]["value"]))),
            fund["worst_month"]["evidence"],
        ),
        tile(
            _fund_pct(float(fund["max_drawdown"]["value"])),
            labels["fund_dd"],
            fund["max_drawdown"]["evidence"],
        ),
        tile(
            str(int(fund["longest_under_water"]["value"])),
            labels["fund_under" if recovered else "fund_under_open"],
            fund["longest_under_water"]["evidence"],
            neg=not recovered,
        ),
    ]
    out += f"<div class='facts pairs'>{''.join(facts)}</div>"
    out += _fund_calendar(fund.get("years") or [], labels)
    out += _fund_benchmark_html(fund, locale, labels)
    out += _fund_fees_html(fund.get("fees"), labels)
    out += f"<h3>{_e(labels['fund_stress'])}</h3>" if _crises_shown(fund.get("crises")) else ""
    out += _crises_html(fund.get("crises"), labels, fund=True)
    if fund.get("net_of_fees"):
        out += (
            f"<p class='muted'>{_badge(fund['net_of_fees']['evidence'])} "
            f"{_e(labels['fund_net'])}</p>"
        )
    out += f"<p class='muted'>{_e(_sentence(localize(fund.get('note', ''), locale)))}</p>"
    return out


def _market_cell(key: str, label: str) -> str:
    """What the public indices did over one window, as context."""
    moves = MARKET.get(key) or ()
    if not moves:
        return f"<td class='val muted' data-l='{_e(label)}'>—</td>"
    lines = "<br>".join(
        f"<small class='muted'>{_e(move.index)}</small> {_e(_fund_pct(move.change))}"
        for move in moves
    )
    return f"<td class='val' data-l='{_e(label)}'>{lines}</td>"


def _market_note(keys: list[str], labels: dict[str, str]) -> str:
    """Where the market figures come from and when they do not fit."""
    sources: dict[str, str] = {}
    for key in keys:
        for move in MARKET.get(key) or ():
            sources.setdefault(move.index, move.source_url)
    if not sources:
        return ""
    listed = ", ".join(
        f"<a href='{_e(url)}' rel='noopener'>{_e(name)}</a>" for name, url in sources.items()
    )
    text = _e(labels["crises_market_note"].format(as_of=MARKET_AS_OF, sources="\x00"))
    return f"<p class='muted'><small>{text.replace(chr(0), listed)}</small></p>"


def _holding_html(
    holding: dict[str, Any] | None,
    locale: str,
    labels: dict[str, str],
    *,
    closed_only: bool = False,
) -> str:
    """The strategy beside simply holding the market it trades, on the same days."""
    if not holding:
        return ""
    label = str(holding.get("label", ""))
    if holding.get("status") != "MEASURED":
        text = labels["holding_not_measured"].format(
            label=label, reason=localize(str(holding.get("reason", "")), locale)
        )
        return f"<p class='muted'>{_e(text)} {_badge('NOT_MEASURED')}</p>"
    out = ""
    days = int(holding["days"]["value"])
    if "rides_the_market" in (holding.get("findings") or []):
        rides = labels["holding_rides"].format(
            label=label, weeks=int(holding["weeks"]["value"])
        )
        out += (
            f"<div class='live-verdict lv-WEAK beh'><span class='badge WEAK'>"
            f"{_e(labels['beh_badge_found'])}</span><ul class='beh-asks'>"
            f"{_behaviour_ask(rides)}</ul></div>"
        )
    intro = labels["holding_intro"].format(
        label=label,
        first=holding.get("first", ""),
        last=holding.get("last", ""),
        days=days,
    )
    out += f"<p class='muted'>{_e(intro)} {_badge('MEASURED')}</p>"
    strategy_head = labels["holding_strategy"]
    market_head = labels["holding_market"].format(label=label)

    def row(name: str, key: str, text: Callable[[float], str]) -> str:
        cells = ""
        for side, head in (("strategy", strategy_head), ("market", market_head)):
            field = f"{side}_{key}"
            if field == "strategy_sharpe":
                field = "strategy_sharpe_shared_days"
            value = float(holding[field]["value"])
            neg = " neg" if value < 0 and key != "sharpe" else ""
            cells += f"<td class='val{neg}' data-l='{_e(head)}'>{_e(text(value))}</td>"
        return f"<tr><td>{_e(labels[name].format(days=days))}</td>{cells}</tr>"

    body = (
        row("holding_return", "return", _fund_pct)
        + row("holding_drawdown", "drawdown", _fund_pct)
        + row("holding_sharpe", "sharpe", lambda v: f"{v:.2f}")
    )
    out += (
        f"<table class='timing holding'><thead><tr><th></th>"
        f"<th class='val'>{_e(strategy_head)}</th><th class='val'>{_e(market_head)}</th>"
        f"</tr></thead><tbody>{body}</tbody></table>"
    )
    z = float(holding["sharpe_gap_in_se"]["value"])
    if "rides_the_market" not in (holding.get("findings") or []) and z < EDGE_SE:
        edge = labels["holding_no_clear_edge"].format(z=f"{z:.2f}")
        out += f"<p class='muted'>{_e(edge)} {_badge('MEASURED')}</p>"
    together = labels["holding_together"].format(
        label=label,
        corr=f"{float(holding['correlation']['value']):.2f}",
        beta=f"{float(holding['beta']['value']):.2f}",
    )
    out += f"<p>{_e(together)} {_badge('MEASURED')}</p>"
    if closed_only:
        out += f"<p class='muted'>{_e(labels['holding_closed_only'])}</p>"
    link = (
        f"<a href='{_e(str(holding.get('source_url', '')))}' rel='noopener'>FRED</a>"
    )
    source = _e(labels["holding_source"].format(label=label, source="\x00"))
    out += f"<p class='muted'><small>{source.replace(chr(0), link)}</small></p>"
    return out


def _regime_html(regime: dict[str, Any] | None, locale: str, labels: dict[str, str]) -> str:
    """The returns split by calm and turbulent markets, by the VIX known before each."""
    if not regime:
        return ""
    if regime.get("status") != "MEASURED":
        text = labels["regime_not_measured"].format(
            reason=localize(str(regime.get("reason", "")), locale)
        )
        return f"<p class='muted'>{_e(text)} {_badge('NOT_MEASURED')}</p>"
    intro = labels["regime_intro"].format(
        first=regime.get("first", ""), last=regime.get("last", "")
    )
    out = f"<p class='muted'>{_e(intro)} {_badge('MEASURED')}</p>"
    heads = (("calm", labels["regime_calm"]), ("turbulent", labels["regime_turbulent"]))

    def row(name: str, key: str, text: Callable[[float], str], signed: bool) -> str:
        cells = ""
        for side, head in heads:
            field = (regime.get(side) or {}).get(key)
            if field is None:
                cells += f"<td class='val' data-l='{_e(head)}'>—</td>"
                continue
            value = float(field["value"])
            neg = " neg" if signed and value < 0 else ""
            cells += f"<td class='val{neg}' data-l='{_e(head)}'>{_e(text(value))}</td>"
        return f"<tr><td>{_e(labels[name])}</td>{cells}</tr>"

    body = (
        row("regime_time", "time_share", lambda v: _pct(v, places=0), False)
        + row("regime_returns", "returns", lambda v: f"{int(v)}", False)
        + row("regime_monthly", "monthly_return", lambda v: _pct(v, places=2), True)
        + row("regime_sharpe", "sharpe", lambda v: f"{v:.2f}", False)
    )
    out += (
        "<table class='timing holding'><thead><tr><th></th>"
        + "".join(f"<th class='val'>{_e(head)}</th>" for _, head in heads)
        + f"</tr></thead><tbody>{body}</tbody></table>"
    )
    gap = regime.get("gap_in_se")
    if gap is not None:
        z = float(gap["value"])
        better = regime.get("better")
        name = (
            f"regime_better_{better}"
            if better in ("calm", "turbulent")
            else "regime_no_clear_gap"
        )
        out += f"<p>{_e(labels[name].format(z=f'{abs(z):.2f}'))} {_badge('MEASURED')}</p>"
    link = f"<a href='{_e(str(regime.get('source_url', '')))}' rel='noopener'>FRED</a>"
    source = _e(labels["regime_source"].format(source="\x00"))
    out += f"<p class='muted'><small>{source.replace(chr(0), link)}</small></p>"
    return out


def _crises_shown(stress: dict[str, Any] | None) -> bool:
    return bool(stress) and (stress or {}).get("status") == "MEASURED"


def _crises_html(
    stress: dict[str, Any] | None, labels: dict[str, str], *, fund: bool = False
) -> str:
    """A fund or any dated curve through the dated market falls it covers."""
    if not stress or not _crises_shown(stress):
        return ""
    out = ""
    subject = labels["fund_stress_fund" if fund else "crises_subject"]
    rows = stress.get("windows") or []
    with_index = any("benchmark" in row for row in rows)
    if "fell_more_in_crises" in (stress.get("findings") or []):
        text = labels["fund_stress_worse" if fund else "crises_worse"].format(
            worse=int(stress["worse_than_benchmark"]["value"]), n=int(stress["compared"]["value"])
        )
        out += (
            f"<div class='live-verdict lv-WEAK beh'><span class='badge WEAK'>"
            f"{_e(labels['beh_badge_found'])}</span><ul class='beh-asks'>"
            f"{_behaviour_ask(text)}</ul></div>"
        )
    if rows:
        intro = labels["fund_stress_intro" if fund else "crises_intro"]
        out += f"<p class='muted'>{_e(intro)} {_badge('MEASURED')}</p>"

        def cell(item: dict[str, Any] | None, label: str) -> str:
            if not item:
                return f"<td class='val' data-l='{_e(label)}'>—</td>"
            value = float(item["value"])
            side = " neg" if value < 0 else ""
            return f"<td class='val{side}' data-l='{_e(label)}'>{_e(_fund_pct(value))}</td>"

        body = "".join(
            f"<tr><td>{_e(labels['fund_stress_' + row['key']])}<br>"
            f"<small class='muted'>{_e(row['first'])} – {_e(row['last'])}</small></td>"
            + (
                f"<td class='val muted' data-l='{_e(subject)}'>"
                f"{_e(labels['crises_no_trades'])}</td>"
                if row.get("no_trades")
                else cell(row["fund"], subject)
            )
            + (cell(row.get("benchmark"), labels["fund_stress_index"]) if with_index else "")
            + _market_cell(row["key"], labels["crises_market"])
            + "</tr>"
            for row in rows
        )
        head = (
            f"<th>{_e(labels['fund_stress_head'])}</th>"
            f"<th class='val'>{_e(subject)}</th>"
            + (f"<th class='val'>{_e(labels['fund_stress_index'])}</th>" if with_index else "")
            + f"<th class='val'>{_e(labels['crises_market'])}</th>"
        )
        out += (
            f"<table class='timing crises'><thead><tr>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )
        out += _market_note([row["key"] for row in rows], labels)
    else:
        out += f"<p class='muted'>{_e(labels['fund_stress_none'])}</p>"
    if stress.get("worst_12m"):
        out += (
            "<p class='muted'>"
            + _e(
                labels["fund_stress_12m"].format(
                    worst=_fund_pct(float(stress["worst_12m"]["value"])),
                    best=_fund_pct(float(stress["best_12m"]["value"])),
                    share=f"{float(stress['positive_12m']['value']):.0%}",
                )
            )
            + f" {_badge('MEASURED')}</p>"
        )
    return out


def _fund_fees_html(fees: dict[str, Any] | None, labels: dict[str, str]) -> str:
    """The record under common yearly fees, when it was not declared net."""
    if not fees or fees.get("status") != "MEASURED":
        return ""
    gross_growth = fees.get("gross_growth")
    gross = _fund_pct(float(gross_growth["value"])) if gross_growth else "—"
    first = (
        f"<tr><td>{_e(labels['fund_fees_none'])}</td>"
        f"<td class='val'>{_e(_fund_pct(float(fees['gross_cagr']['value'])))}</td>"
        f"<td class='val'>{_e(gross)}</td></tr>"
    )
    body = first + "".join(
        f"<tr><td>{float(row['rate']) * 100:.1f} %</td>"
        f"<td class='val'>{_e(_fund_pct(float(row['cagr']['value'])))}</td>"
        f"<td class='val'>{_e(_fund_pct(float(row['growth']['value'])))}</td></tr>"
        for row in fees.get("rows") or []
    )
    out = (
        f"<h3>{_e(labels['fund_fees'])}</h3>"
        f"<p class='muted'>{_e(labels['fund_fees_intro'])} {_badge('MEASURED')}</p>"
        f"<table class='timing'><thead><tr><th>{_e(labels['fund_fees_rate'])}</th>"
        f"<th class='val'>{_e(labels['fund_fees_cagr'])}</th>"
        f"<th class='val'>{_e(labels['fund_fees_growth'])}</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
        f"<p class='muted'>{_e(labels['fund_fees_management'])}</p>"
    )
    break_even = fees.get("break_even")
    if break_even:
        rate = float(break_even["value"])
        text = (
            labels["fund_fees_break_even"].format(
                rate=f"{rate * 100:.2f} %" if rate < 0.001 else f"{rate * 100:.1f} %"
            )
            if rate >= 0.00005
            else labels["fund_fees_behind"]
        )
        out += f"<p>{_e(text)} {_badge('MEASURED')}</p>"
    return out


def _fund_benchmark_html(fund: dict[str, Any], locale: str, labels: dict[str, str]) -> str:
    """The fund against the benchmark its file carries or the customer uploaded."""
    bench = fund.get("benchmark")
    if not bench:
        return ""
    out = f"<h3>{_e(labels['fund_bench'])}</h3>"
    if bench.get("status") != "MEASURED":
        return out + (
            f"<p class='muted'>{_e(labels['fund_bench_nm'])} {_badge('NOT_MEASURED')} "
            f"{_e(_sentence(localize(bench.get('reason', ''), locale)))}</p>"
        )
    intro = labels["fund_bench_upload" if bench.get("source") == "upload" else "fund_bench_file"]
    out += (
        "<p class='muted'>"
        + _e(
            intro.format(first=bench["first"], last=bench["last"], n=int(bench["months"]["value"]))
        )
        + ("" if fund.get("net_of_fees") else f" {_e(labels['fund_bench_gross'])}")
        + "</p>"
    )
    excess = float(bench["excess"]["value"])
    corr = f"{float(bench['correlation']['value']):.2f}"
    te = f"{float(bench['tracking_error']['value']):.1%}"
    up = (bench.get("up_capture") or {}).get("value")
    down = (bench.get("down_capture") or {}).get("value")
    findings = list(bench.get("findings") or [])
    if findings:
        texts = {
            "trails": labels["fund_bench_trails"].format(excess=_fund_pct(excess)),
            "index_like": labels["fund_bench_index_like"].format(corr=corr, te=te),
            "worse_both_ways": labels["fund_bench_worse"].format(
                up=f"{float(up or 0):.0%}", down=f"{float(down or 0):.0%}"
            ),
        }
        items = "".join(_behaviour_ask(texts[code]) for code in findings)
        out += (
            f"<div class='live-verdict lv-WEAK beh'><span class='badge WEAK'>"
            f"{_e(labels['beh_badge_found'])}</span><ul class='beh-asks'>{items}</ul></div>"
        )
    else:
        out += (
            f"<p class='live-verdict lv-PASS'><span class='badge PASS'>"
            f"{_e(labels['fund_bench_badge_clean'])}</span> {_e(labels['fund_bench_clean'])}</p>"
        )

    def tile(value: str, text: str, evidence: str, *, neg: bool = False) -> str:
        return (
            f"<div class='fact{' neg' if neg else ''}'><b>{_e(value)}</b>"
            f"<p>{_e(text)} {_badge(evidence)}</p></div>"
        )

    ir = (bench.get("information_ratio") or {}).get("value")
    facts = [
        tile(
            _fund_pct(excess),
            labels["fund_bench_excess"].format(
                fund=_fund_pct(float(bench["fund_cagr"]["value"])),
                index=_fund_pct(float(bench["index_cagr"]["value"])),
            ),
            bench["excess"]["evidence"],
            neg=excess < 0,
        ),
        tile(
            f"{float(bench['beat_share']['value']):.0%}",
            labels["fund_bench_beat"],
            bench["beat_share"]["evidence"],
        ),
        tile(
            te,
            labels["fund_bench_te"].format(ir=f"{float(ir):.2f}" if ir is not None else "—"),
            bench["tracking_error"]["evidence"],
        ),
        tile(
            f"{float(bench['beta']['value']):.2f}",
            labels["fund_bench_beta"].format(corr=corr),
            bench["beta"]["evidence"],
        ),
    ]
    for key, label in (("up_capture", "fund_bench_up"), ("down_capture", "fund_bench_down")):
        item = bench.get(key) or {}
        if item.get("evidence") == "MEASURED" and item.get("value") is not None:
            facts.append(
                tile(
                    f"{float(item['value']):.0%}",
                    labels[label],
                    item["evidence"],
                    neg="worse_both_ways" in findings,
                )
            )
    out += f"<div class='facts pairs'>{''.join(facts)}</div>"
    out += f"<p class='muted'>{_e(_sentence(localize(bench.get('note', ''), locale)))}</p>"
    return out


def _title(data: dict[str, Any], labels: dict[str, str]) -> str:
    """The report's name: a fund's track record, or a backtest."""
    fund = data.get("fund") or {}
    return labels["title_fund" if fund.get("track_record") else "title"]


#: What each class requires, in the words of ``verdict.overall_class``.
CLASS_LADDER: dict[str, tuple[tuple[str, str], ...]] = {
    "es": (
        (
            "A",
            "La estadística y el número de intentos superan; costes, fuera de muestra y "
            "benchmark superan o no aplican; los datos no tienen banderas graves ni avisos.",
        ),
        (
            "B",
            "La estadística y el número de intentos superan y nada falla, pero falta medir "
            "o reforzar costes, fuera de muestra, benchmark o calidad de datos.",
        ),
        (
            "C",
            "Una dimensión no supera, o la estadística o el número de intentos quedan en débil.",
        ),
        (
            "D",
            "Los datos o la estadística no superan, o no superan dos dimensiones o más.",
        ),
    ),
    "en": (
        (
            "A",
            "Statistics and number of trials pass; costs, out-of-sample and benchmark pass "
            "or do not apply; the data has no serious or warning flags.",
        ),
        (
            "B",
            "Statistics and number of trials pass and nothing fails, but costs, "
            "out-of-sample, benchmark or data quality still need measuring or strengthening.",
        ),
        ("C", "One dimension fails, or statistics or number of trials are weak."),
        ("D", "The data or the statistics fail, or two dimensions or more fail."),
    ),
}


def _ladder_html(current: str, labels: dict[str, str]) -> str:
    """The four classes and what each requires, with this report's marked."""
    rows = "".join(
        f"<li class='rung{' you' if cls == current else ''}' style='--c:{CLASS_COLOURS[cls]}'>"
        f"<span class='rung-cls'>{cls}</span><p>{_e(text)}</p>"
        + (f"<span class='rung-you'>{_e(labels['ladder_you'])}</span>" if cls == current else "")
        + "</li>"
        for cls, text in CLASS_LADDER[_locale_of(labels)]
    )
    return (
        f"<p class='muted'>{_e(labels['ladder_intro'])}</p>"
        f"<ol class='ladder' aria-label='{_e(labels['ladder_class'])}'>{rows}</ol>"
    )


def _locked_gains(titles: list[str], labels: dict[str, str], locale: str) -> list[str]:
    """Each locked section as what it tells the buyer, in the report's order."""
    gains = LOCKED_GAINS.get(locale, LOCKED_GAINS["es"])
    by_title = {labels[key]: text for key, text in gains.items() if key in labels}
    out: list[str] = []
    for title in titles:
        gain = by_title.get(title, title)
        if gain not in out:
            out.append(gain)
    return out


def _only_unmeasured(body: str) -> bool:
    """True when a section has nothing but NOT_MEASURED marks to show."""
    return "badge NOT_MEASURED" in body and not any(
        f"badge {tag}" in body
        for tag in ('MEASURED"', "MEASURED'", "DECLARED", "PASS", "WEAK", "FAIL")
    )


def _notice_html(notice: str | None, *, ok: bool) -> str:
    """The message on top of a report; a payment or code that worked reads as done."""
    if not notice:
        return ""
    if ok:
        return (
            f"<div class='notice ok' role='status'>{icon('check')}<span>{_e(notice)}</span></div>"
        )
    return f"<div class='notice'>{_e(notice)}</div>"


def _pack_notice(labels: dict[str, str], code: str, left: int) -> str:
    """The code a card-paid pack left for the next reports, on the paid report."""
    if not code:
        return ""
    if left < 1:
        return f"<div class='notice'>{_e(labels['pack_used'].format(code=code))}</div>"
    return (
        f"<div class='notice'><p>{_e(labels['pack_left'].format(n=left))}</p>"
        f"<p><code>{_e(code)}</code></p>"
        f"<p class='muted'>{_e(labels['pack_keep'])}</p></div>"
    )


def render_html(
    result: AuditResult,
    *,
    watermark: bool,
    free_mode: bool = True,
    price_usd: float | None = None,
    checkout_url: str | None = None,
    redeem_url: str | None = None,
    publish_url: str | None = None,
    notice: str | None = None,
    contact_url: str | None = None,
    legal_links: bool = False,
    locale: str | None = None,
    switch_url: str | None = None,
    head_meta: str | None = None,
    compare_link: str | None = None,
    pack_price_usd: float = 0.0,
    pdf_url: str | None = None,
    pack_code: str = "",
    pack_credits_left: int = 0,
    code_error: bool = False,
    pay_links: tuple[str, str, str] | None = None,
    notice_ok: bool = False,
    account_box: str = "",
) -> str:
    """The audit as one HTML document.

    ``locale`` shows the page in a language other than the one chosen at
    upload: the verdict sentence is rebuilt from its fixed templates and the
    engine's English notes are translated; the result itself is unchanged.
    ``switch_url`` is the same page in the other language. ``head_meta`` is
    the page's search and preview tags; without it the page is ``noindex``,
    as every client report is.

    The verdict, the plain-language explanations, the charts, the input
    hashes and the list of red flags are always shown. In paid mode an
    unpaid audit gets the detail sections as titles only: their numbers are
    not rendered, so they are not in the page source either. Free mode shows
    everything under a watermark.
    """
    data = result.model_dump(mode="json")
    declared_locale = data["declared"].get("locale", "es")
    locale = locale if locale in LABELS else declared_locale
    labels = LABELS.get(locale, LABELS["es"])
    locked = watermark and not free_mode
    verdict = data["verdict"]
    if locale != declared_locale or locale == "pt":
        # Stored reasons are English and Spanish only, so Portuguese always rebuilds.
        verdict = {**verdict, "summary": _summary_in(data, locale)}

    paybox = ""
    price = f"USD {price_usd:,.0f}" if price_usd else ""
    pack = labels["pack"].format(price=pack_price_usd) if pack_price_usd else ""
    price_html = (
        f"<div class='buy-price'><b>{_e(price)}</b>"
        + (f"<span>{_e(pack)}</span>" if pack else "")
        + "</div>"
        if price
        else ""
    )
    # What the payment unlocks, under the price in every buy box.
    includes_html = (
        "<ul class='buy-incl'>"
        + "".join(
            f"<li>{icon('check')}<span>{_e(item)}</span></li>"
            for item in labels["buy_includes"].split("|")
        )
        + "</ul>"
    )
    card_on = bool(checkout_url or pay_links)
    if locked and pay_links and not checkout_url:
        # Payment Links open Stripe in another tab; the webhook unlocks this
        # report and "Ya pagué" reloads it.
        single_url, pack_url, done_url = pay_links
        pack_link = (
            f"<a class='btn btn-ghost btn-lg' href='{_e(pack_url)}' target='_blank' "
            f"rel='noopener'>{_e(labels['pay_pack'].format(price=pack_price_usd))}</a>"
            if pack_url and pack_price_usd
            else ""
        )
        paybox = (
            "<div class='paybox buy'>" + price_html + "<div><div class='inline-form'>"
            f"<a class='btn btn-primary btn-lg' href='{_e(single_url)}' target='_blank' "
            f"rel='noopener'>{icon('card')}{_e(labels['pay'])}</a>{pack_link}</div>"
            f"<p class='muted pay-secure'>{icon('lock')}<span>{_e(labels['pay_secure'])}</span></p>"
            f"<p class='muted'>{_e(labels['pay_links_note'])} "
            f"<a href='{_e(done_url)}'>{_e(labels['paid_check'])}</a></p>"
            f"</div>{includes_html}</div>"
        )
    if locked and checkout_url:
        # Card payment is the main way to pay; the pack is the second button.
        pack_button = (
            "<button class='btn btn-ghost btn-lg' type='submit' name='plan' value='pack'>"
            f"{_e(labels['pay_pack'].format(price=pack_price_usd))}</button>"
            if pack_price_usd
            else ""
        )
        paybox = (
            f"<form class='paybox buy' method='post' action='{_e(checkout_url)}'>"
            + price_html
            + "<div><div class='inline-form'>"
            "<button class='btn btn-primary btn-lg' type='submit' name='plan' value='single'>"
            f"{icon('card')}{_e(labels['pay'])}</button>{pack_button}</div>"
            f"<p class='muted pay-secure'>{icon('lock')}<span>{_e(labels['pay_secure'])}</span></p>"
            f"</div>{includes_html}</form>"
        )
    if locked and redeem_url:
        if contact_url:
            # Where a client without a code buys one (bank transfer, WhatsApp).
            request = (
                labels["code_request_price"].format(id=data["audit_id"], price=price)
                if price
                else labels["code_request"].format(id=data["audit_id"])
            )
            contact_url = _prefilled(contact_url, request)
            if card_on:
                # With card payment on, WhatsApp is the alternative, not the main button.
                paybox += (
                    f"<p class='paybox pay-alt'><a href='{_e(contact_url)}' "
                    f"rel='noopener noreferrer' target='_blank'>{icon('chat')}"
                    f"<span>{_e(labels['buy_code_alt'])}</span></a></p>"
                )
            else:
                paybox += (
                    "<div class='paybox buy'>"
                    + price_html
                    + f"<a class='btn btn-primary btn-lg' href='{_e(contact_url)}' "
                    f"rel='noopener noreferrer' target='_blank'>{icon('chat')}"
                    f"{_e(labels['buy_code'])}</a>"
                    "<ol class='buy-steps'>"
                    + "".join(f"<li>{_e(step)}</li>" for step in labels["buy_code_how"].split("|"))
                    + f"</ol><p class='muted pay-secure'>{_e(labels['buy_code_wait'])}</p>"
                    f"{includes_html}</div>"
                )
        main_button = contact_url or card_on
        error_html, invalid = "", ""
        if code_error:
            # Next to the field the customer just used, with what to do next.
            advice = labels["code_error"] + (
                " " + labels["code_error_contact"] if main_button else ""
            )
            error_html = (
                f"<p class='code-error' id='redeem-error' role='alert'>{icon('alert')}"
                f"<span>{_e(advice)}</span></p>"
            )
            invalid = " aria-invalid='true' aria-describedby='redeem-error' autofocus"
        # The fragment survives the redirect, so the page comes back at this form.
        paybox += (
            f"<form class='paybox redeem' id='canjear' method='post' "
            f"action='{_e(redeem_url)}#canjear'>"
            f"<label for='redeem-code'>{_e(labels['redeem'])}</label><div class='inline-form'>"
            "<input id='redeem-code' type='text' name='code' required maxlength='40' "
            f"autocomplete='off' spellcheck='false' placeholder='AUD-XXXX-XXXX-XXXX'{invalid}>"
            f"<button class='btn {'btn-ghost' if main_button else 'btn-primary'}' type='submit'>"
            f"{_e(labels['redeem_button'])}</button></div>{error_html}</form>"
        )
    compare_html = ""
    if compare_link and not locked:
        from quant_trade.audit.compare import COPY as COMPARE_COPY
        from quant_trade.audit.compare import MAX_LINK_CHARS

        # The comparison page has Spanish and English; Portuguese uses the English one.
        ccopy = COMPARE_COPY["es" if locale == "es" else "en"]
        action = "/comparar" if locale == "es" else "/compare"
        compare_html = (
            f"<form class='publish no-print' method='post' action='{action}'>"
            f"<p class='muted'>{_e(ccopy['from_report_help'])}</p>"
            f"<input type='hidden' name='lang' value='{_e(locale)}'>"
            f"<input type='hidden' name='link_a' value='{_e(compare_link)}'>"
            f"<div class='inline-form'><input type='url' name='link_b' required "
            f"maxlength='{MAX_LINK_CHARS}' autocomplete='off' spellcheck='false' "
            f"aria-label='{_e(ccopy['link_b'])}' placeholder='{_e(ccopy['placeholder'])}'>"
            f"<button class='btn btn-dark' type='submit'>{_e(ccopy['submit'])}</button></div>"
            "</form>"
        )
    publish_html = ""
    if publish_url and not locked:
        publish_html = (
            f"<form class='publish' method='post' action='{_e(publish_url)}'>"
            f"<p class='muted'>{_e(labels['publish_help'])}</p>"
            f"<button class='btn btn-dark' type='submit'>{_e(labels['publish'])}</button></form>"
        )

    inputs_html = (
        "<table>"
        + "".join(
            f"<tr><td>{_e(name)}</td><td><code>{_e(digest)}</code></td></tr>"
            for name, digest in data["inputs"]["digests"].items()
        )
        + (
            f"<tr><td>{_e(_key_label('dataset_digest', labels))}</td>"
            f"<td><code>{_e(data['inputs']['dataset_digest'])}</code>"
            "</td></tr></table>"
        )
    )
    inputs_html += (
        f"<p class='muted'>{_e(_short_time(data['inputs']['first_timestamp'])[:10])} → "
        f"{_e(_short_time(data['inputs']['last_timestamp'])[:10])} · "
        f"{_e(FREQUENCY_TEXT[locale].get(data['inputs']['frequency_label'], ''))} · "
        f"{_fmt(data['inputs']['observations']['value'])} {_e(labels['obs'])} · "
        f"{_e(labels['source_' + data['inputs']['source']])}</p>"
    )
    if data["inputs"]["parse_warnings"]:
        items = "".join(
            f"<li>{_e(localize(w, locale))}</li>" for w in data["inputs"]["parse_warnings"]
        )
        inputs_html += (
            f"<div class='read-notes'><p>{_e(labels['warnings'])}</p><ul>{items}</ul></div>"
        )

    declared_html = _evidence_rows(data["declared"], labels, skip=set())
    description = data["declared"].get("description", "")
    findings = data.get("client_text_findings", [])
    if description:
        declared_html += (
            f"<p class='muted'>{_e(labels['client_text'])}: "
            f"{_e(labels['chars'].format(n=len(description)))}, sha256 "
            f"<code>{_e(sha256_of_text(description))}</code>. {_e(labels['client_text_note'])}: "
            f"{len(findings)}.</p>"
        )
    else:
        declared_html += f"<p class='muted'>{_e(labels['client_text_none'])}</p>"

    sens = data["multiplicity"].get("sensitivity", [])
    sens_html = ""
    if sens:
        sens_html = (
            f"<table><tr><th>{_e(labels['trials'])}</th><th>{_e(labels['expected_max'])}</th>"
            f"<th>{_e(labels['dsr'])}</th></tr>"
            + "".join(
                f"<tr><td>{_fmt(row['n_trials'])}</td>"
                f"<td>{_fmt(row['expected_max_sharpe_per_period']['value'])}</td>"
                f"<td>{_fmt(row['dsr']['value'], key='dsr')}</td></tr>"
                for row in sens
            )
            + "</table>"
        )
    multiplicity_html = (
        _status_line(data["multiplicity"], labels)
        + _evidence_rows(data["multiplicity"], labels, skip={"sensitivity"})
        + f"<p class='muted'>{_e(labels['variance_policy'])}</p>"
        + sens_html
    )

    boot = data["bootstrap"]
    boot_html = _status_line(boot, labels)
    if boot.get("status") == "MEASURED":
        boot_html += (
            f"<p class='muted'>{_e(labels['boot_line'])}"
            f" {_fmt(boot['samples'])} · {_e(labels['boot_block'])} {_fmt(boot['block_size'])}</p>"
            f"<table><tr><th></th><th>{_e(labels['point'])}</th><th>p5</th>"
            "<th>p50</th><th>p95</th></tr>"
        )
        for stat in ("sharpe_per_period", "total_return"):
            band = boot[stat]
            key = "p5" if stat == "total_return" else ""
            boot_html += (
                f"<tr><td>{_e(_key_label(stat, labels))}</td>"
                + "".join(
                    f"<td>{_fmt(band[p]['value'], key=key)} {_badge(band[p]['evidence'])}</td>"
                    for p in ("point_estimate", "p5", "p50", "p95")
                )
                + "</tr>"
            )
        boot_html += "</table>"

    hold = data["holdout"]
    hold_html = _status_line(hold, labels) + _evidence_rows(
        hold, labels, skip={"in_sample", "out_of_sample"}
    )
    if hold.get("status") == "MEASURED":
        for side in ("in_sample", "out_of_sample"):
            hold_html += f"<h3>{_e(labels[side])}</h3>" + _evidence_rows(
                hold[side], labels, skip=set()
            )

    cost = data["costs"]
    cost_html = _status_line(cost, labels) + _evidence_rows(cost, labels, skip={"rows"})
    if cost.get("rows"):
        cost_html += (
            f"<div class='tscroll'><table><tr><th>{_e(labels['multiplier'])}</th>"
            f"<th>{_e(labels['bps'])}</th>"
            f"<th>{_e(labels['gross'])}</th><th>{_e(labels['cost'])}</th><th>{_e(labels['net'])}"
            f"</th><th>{_e(labels['win_rate'])}</th><th>{_e(labels['trades'])}</th></tr>"
            + "".join(
                f"<tr><td>{_fmt(row['multiplier'])}x</td>"
                f"<td>{_fmt(row['cost_bps_per_side'], key='cost_bps_per_side')}</td>"
                f"<td>{_fmt(row['gross_pnl']['value'], key='gross_pnl')}</td>"
                f"<td>{_fmt(row['total_cost']['value'], key='total_cost')}"
                f"</td><td>{_fmt(row['net_pnl']['value'], key='net_pnl')}</td>"
                f"<td>{_fmt(row['win_rate']['value'], key='win_rate')}</td>"
                f"<td>{_fmt(row['trades'])}</td></tr>"
                for row in cost["rows"]
            )
            + "</table></div>"
        )
        cost_html += _cost_gap_note(cost["rows"], data.get("trade_stats") or {}, labels)

    bench_html = _status_line(data["benchmark"], labels) + _evidence_rows(
        data["benchmark"], labels, skip=set()
    )
    cscv_html = _status_line(data["cscv"], labels) + _evidence_rows(
        data["cscv"], labels, skip=set()
    )
    if data["cscv"].get("status") == "MEASURED":
        cscv_html += (
            "<p class='muted'>"
            + _e(
                ", ".join(
                    f"{k}={data['cscv'][k]}"
                    for k in (
                        "partitions",
                        "combinations",
                        "parameter_variants",
                        "observations_used",
                    )
                )
            )
            + "</p>"
        )

    sub_html = (
        f"<table><tr><th>{_e(labels['year'])}</th><th>{_e(labels['return'])}</th>"
        f"<th>{_e(labels['max_drawdown'])}</th></tr>"
        + "".join(
            f"<tr><td>{row['year']}</td><td>{_fmt(row['return']['value'], key='return')}</td>"
            f"<td>{_fmt(row['max_drawdown']['value'], key='max_drawdown')}</td></tr>"
            for row in data["subperiods"]
        )
        + "</table>"
        if data["subperiods"]
        else f"<p class='muted'>{_e(labels['none'])}</p>"
    )
    roll_html = (
        f"<table><tr><th>{_e(labels['window'])}</th><th>{_e(labels['min_return'])}</th>"
        f"<th>{_e(labels['min_drawdown'])}</th><th>{_e(labels['share_negative'])}</th></tr>"
        + "".join(
            f"<tr><td>{row['window']}</td>"
            f"<td>{_fmt(row['min_return']['value'], key='min_return')}</td>"
            f"<td>{_fmt(row['min_drawdown']['value'], key='min_drawdown')}</td>"
            f"<td>{_fmt(row['share_negative']['value'], key='share_negative')}</td></tr>"
            for row in data["rolling"]
        )
        + "</table>"
        if data["rolling"]
        else f"<p class='muted'>{_e(labels['none'])}</p>"
    )

    order = {"FAIL": 0, "WARN": 1}
    flags_html = (
        "<ul class='flag-list acct-flags flag-cards'>"
        + "".join(
            f"<li>{_severity_badge(flag['severity'], locale)}"
            f"<div><b>{_e(flag_title(flag['code'], locale))}</b>"
            f"<p>{_e(_sentence(localize(flag['detail'], locale)))}</p>"
            f"<p class='flag-code'>{_e(flag['code'])}</p></div></li>"
            for flag in sorted(data["red_flags"], key=lambda f: order.get(f["severity"], 2))
        )
        + "</ul>"
        if data["red_flags"]
        else _no_flags_html(labels)
    )

    seal = data["seal"]
    seal_html = _status_line(seal, labels)
    if seal.get("holdout_seal"):
        hs = seal["holdout_seal"]
        seal_html += (
            "<table>"
            + "".join(
                f"<tr><td>{_e(_key_label(k, labels))}</td><td><code>{_fmt(hs[k])}</code></td></tr>"
                for k in (
                    "seal_id",
                    "selection_start",
                    "selection_end",
                    "holdout_start",
                    "holdout_end",
                    "sealed_at_utc",
                    "seal",
                )
            )
            + "</table>"
        )

    not_measured = [
        f"{labels[name]}: {_localized_reason(section.get('reason', ''), locale)}"
        for name, section in (
            ("significance", data["significance"]),
            ("multiplicity", data["multiplicity"]),
            ("bootstrap", data["bootstrap"]),
            ("holdout", data["holdout"]),
            ("costs", data["costs"]),
            ("benchmark", data["benchmark"]),
            ("cscv", data["cscv"]),
            ("risk", data.get("risk") or {}),
            ("challenge", data.get("challenge") or {}),
        )
        if section.get("status") == "NOT_MEASURED"
    ]
    nm_html = (
        "<ul class='nm-list'>" + "".join(_nm_item(item) for item in not_measured) + "</ul>"
        if not_measured
        else f"<p class='muted'>{_e(labels['none'])}</p>"
    )

    trials = data["multiplicity"].get("trials_used")
    if trials:
        multiplicity_html = (
            f"<p>{_e(labels['trials_used'])}: {_fmt(trials['value'])} {_badge(trials['evidence'])}"
            f" <span class='muted'>{_e(localize(trials.get('note', ''), locale))}</span></p>"
            + multiplicity_html
        )
    fees = data["costs"].get("reported_fees")
    if fees:
        cost_html += f"<h3>{_e(labels['fees'])}</h3>" + _evidence_rows(fees, labels, skip=set())

    hidden = _hidden_loss_note(data, labels)
    detail: list[tuple[str, str]] = [
        (labels["plan"], _plan_html(data, locale, labels, locked=False)),
        *(
            [(labels["live"], _live_html(data.get("live"), locale, labels))]
            if data.get("live")
            else []
        ),
        *(
            [(labels["account"], _account_html(data.get("account"), labels))]
            if (data.get("account") or {}).get("status") == "MEASURED"
            else []
        ),
        *(
            [(labels["test_data"], _test_data_html(data.get("test_data"), labels))]
            if (data.get("test_data") or {}).get("status") == "MEASURED"
            else []
        ),
        (labels["stress"], _stress_html(data.get("stress"), locale, labels)),
        *(
            [
                (
                    labels["ride"],
                    _ride_html(
                        data.get("ride"),
                        locale,
                        labels,
                        closed_only=bool((data.get("inputs") or {}).get("balance_only")),
                    ),
                )
            ]
            # A fund record's section already shows its months and time under water.
            if (data.get("ride") or {}).get("status") == "MEASURED"
            and (data.get("fund") or {}).get("status") != "MEASURED"
            else []
        ),
        (labels["timing"], _timing_html(data.get("timing"), locale, labels)),
        *(
            [(labels["recent"], _recent_html(data.get("recent"), locale, labels))]
            if (data.get("recent") or {}).get("status") == "MEASURED"
            else []
        ),
        *(
            [(labels["crises"], _crises_html(data.get("crises"), labels))]
            if _crises_shown(data.get("crises"))
            else []
        ),
        *(
            [
                (
                    labels["holding"],
                    _holding_html(
                        data.get("holding"),
                        locale,
                        labels,
                        closed_only=bool((data.get("inputs") or {}).get("balance_only")),
                    ),
                )
            ]
            if data.get("holding")
            else []
        ),
        *(
            [(labels["regime"], _regime_html(data.get("vix_regime"), locale, labels))]
            if data.get("vix_regime")
            else []
        ),
        *(
            [(labels["behaviour"], _behaviour_html(data.get("behaviour"), locale, labels))]
            if (data.get("behaviour") or {}).get("status") == "MEASURED"
            else []
        ),
        *(
            [(labels["fund"], _fund_html(data.get("fund"), locale, labels))]
            if (data.get("fund") or {}).get("status") == "MEASURED"
            else []
        ),
        *(
            [(labels["instruments"], _instruments_html(data.get("instruments"), locale, labels))]
            if (data.get("instruments") or {}).get("status") == "MEASURED"
            else []
        ),
        (labels["trade_stats"], _trade_stats_html(data.get("trade_stats"), labels)),
        (labels["risk"], _risk_html(data.get("risk"), locale, labels, hidden)),
        *(
            [(labels["plateau"], _plateau_html(data.get("plateau"), labels))]
            if (data.get("plateau") or {}).get("status") == "MEASURED"
            else []
        ),
        *(
            [(labels["forward"], _forward_html(data.get("forward"), labels))]
            if (data.get("forward") or {}).get("status") == "MEASURED"
            else []
        ),
        *(
            [
                (
                    labels["luck"],
                    _luck_html(
                        data.get("luck"),
                        locale,
                        labels,
                        data.get("multiplicity"),
                        float(
                            ((data.get("verdict") or {}).get("thresholds") or {}).get(
                                "dsr_pass", DEFAULT_THRESHOLDS.dsr_pass
                            )
                        ),
                    ),
                )
            ]
            if (data.get("luck") or {}).get("status") == "MEASURED"
            else []
        ),
        *(
            [
                (
                    labels["capital"],
                    _capital_html(
                        data.get("capital"),
                        locale,
                        labels,
                        account=is_account_history(data),
                        closed_dd=_ev_value((data.get("performance") or {}).get("max_drawdown")),
                        platform_dd=_ev_value(
                            (data.get("performance") or {}).get("platform_equity_drawdown")
                        ),
                        # The red callout already says open losses are left out.
                        closed_only=bool((data.get("inputs") or {}).get("balance_only"))
                        and not hidden,
                        hidden_note=hidden,
                    ),
                )
            ]
            if _capital_shown(data.get("capital"))
            else []
        ),
        (
            labels["challenge"],
            _challenge_html(
                data.get("challenge"),
                locale,
                labels,
                _ev_value((data.get("performance") or {}).get("platform_equity_drawdown")),
                hidden,
            ),
        ),
        (labels["questions"], _questions_html(data.get("vendor_questions", []), locale, labels)),
        # The dimension reasons repeat the verdict in thresholds, so they open the
        # technical tables instead of sitting between the plan and the findings.
        (labels["reasons_detail"], _reasons_html(verdict, locale, labels)),
        (
            labels["performance"],
            _evidence_rows(
                data["performance"],
                labels,
                # The trade table carries the one win rate (after itemised fees).
                skip=(
                    {"win_rate", "trade_count"}
                    if (data.get("trade_stats") or {}).get("status") == "MEASURED"
                    else set()
                ),
            ),
        ),
        (
            labels["significance"],
            _status_line(data["significance"], labels)
            + _evidence_rows(data["significance"], labels, skip=set()),
        ),
        (labels["multiplicity"], multiplicity_html),
        (labels["bootstrap"], boot_html),
        (labels["holdout"], hold_html),
        (labels["costs"], cost_html),
        (labels["benchmark"], bench_html),
        (labels["cscv"], cscv_html),
        (labels["subperiods"], sub_html),
        (labels["rolling"], roll_html),
        (labels["red_flags"], flags_html),
    ]
    if locked:
        # The sample opens in a new tab: the report's link is the buyer's only way back.
        sample_href = SAMPLE_PATHS.get(locale, SAMPLE_PATHS["es"])
        detail_html = (
            f"<div class='lockbox' id='unlock'><p>{_e(labels['locked_intro'])}:</p><ul>"
            + "".join(
                f"<li>{_e(gain)}</li>"
                for gain in _locked_gains(
                    [title for title, body in detail if not _only_unmeasured(body)],
                    labels,
                    locale,
                )
            )
            + "</ul>"
            f"<p class='lock-sample'><a href='{sample_href}' target='_blank' rel='noopener'>"
            f"{_e(labels['sample_full'])}</a></p>{paybox}</div>"
        )
    else:
        detail_html = "".join(
            f"<section class='detail' id='r-d{i}'><h2>{_e(title)}</h2>{body}</section>"
            for i, (title, body) in enumerate(detail, 1)
        )

    watermark_html = ""
    if watermark:
        text = WATERMARK_TEXT.get(locale, WATERMARK_TEXT["es"])
        watermark_html = (
            f"<div class='watermark'>{_e(text)}</div><div class='banner'>{_e(text)}</div>"
        )

    if locked and (redeem_url or checkout_url or pay_links):
        # A watermarked preview is not worth printing: the header offers the unlock instead.
        print_html = (
            f"<a class='print-btn' href='#unlock'>{icon('lock')}{_e(labels['unlock_nav'])}</a>"
        )
    elif pdf_url and not locked:
        print_html = (
            f"<a class='print-btn' href='{_e(pdf_url)}' download "
            f"data-busy='{_e(labels['pdf_busy'])}'>{_e(labels['pdf'])}</a>"
        )
    else:
        print_html = (
            "<button type='button' class='print-btn' "
            f"onclick='window.print()'>{_e(labels['print'])}</button>"
        )
    account_href = {"es": "/cuenta", "pt": "/pt/conta"}.get(locale, "/account")
    toolbar = (
        "<div class='nav-end no-print'>"
        + f"<a class='nav-account' href='{account_href}'>{_e(labels['my_account'])}</a> "
        + print_html
        + (
            f" <a class='lang-switch' href='{_e(switch_url)}' hreflang='{_e(_other(locale))}'>"
            f"{_e(labels['switch'])}</a>"
            if switch_url
            else ""
        )
        + "</div>"
    )
    home = {"en": "/en", "pt": "/pt"}.get(locale, "/")
    header = (
        f"<header class='nav nav-solid'><div class='wrap nav-in'>{logo(home)}{toolbar}</div>"
        "</header>"
    )
    engine = data["engine"]
    meta = (
        f"<span>{_e(labels['audit_id'])} {_e(data['audit_id'])}</span>"
        f"<span>{_e(labels['generated'])} {_e(_short_time(data['generated_at_utc']))}</span>"
        f"<span class='meta-x'>{_e(labels['engine'])} {_e(engine['package_version'])}</span>"
        f"<span class='meta-x'>{_e(labels['seed'])} {_e(engine['seed'])}</span>"
    )
    live_anchor = next(
        (f"r-d{i}" for i, (title, _) in enumerate(detail, 1) if title == labels["live"]), ""
    )
    hero = (
        ("" if locked else _pdf_cover(data, verdict, labels, "" if notice_ok else notice or ""))
        + "<section class='report-hero'>"
        + aurora()
        + grid_bg()
        + "<div class='wrap wrap-mid'>"
        + watermark_html
        + _notice_html(notice, ok=notice_ok)
        + _pack_notice(labels, pack_code, pack_credits_left)
        + account_box
        + f"<div class='eyebrow rise'><span class='dot'></span>{_e(_title(data, labels))}</div>"
        + f"<h1 class='rise' style='--i:1'>{_e(labels['verdict'])} {_e(verdict['overall'])}</h1>"
        + f"<div class='meta-line rise' style='--i:2'>{meta}</div>"
        + "<div class='verdict rise' style='--i:3'>"
        + class_ring(str(verdict["overall"]), size="lg")
        + f"<div><div class='verdict-k'>{_e(labels['verdict'])}</div>"
        + _verdict_html(str(verdict["summary"]))
        + ("" if locked else _hero_live(data, labels, live_anchor))
        + f"<p class='muted evidence-legend'>{_e(labels['evidence_legend'])}</p>"
        + "</div></div>"
        + (
            f"<p class='rise no-print' style='--i:4'><a class='btn btn-primary' "
            f"href='{_e(pdf_url)}' download data-busy='{_e(labels['pdf_busy'])}'>"
            f"{_e(labels['pdf_long'])}</a>"
            f"<noscript> <span class='muted'>{_e(labels['pdf_wait'])}</span></noscript></p>"
            f"<p class='muted pdf-check rise no-print' style='--i:4'>{_e(labels['pdf_check'])} "
            f"<a href='{'/check' if locale == 'en' else '/comprobar'}'>"
            f"{_e(labels['pdf_check_link'])}</a></p>"
            if pdf_url and not locked
            else ""
        )
        + (
            f"<p class='rise' style='--i:4'><a class='btn btn-primary' href='#unlock'>"
            f"{_e(labels['unlock_jump'])}</a></p>"
            f"<p class='muted keep-link rise' style='--i:4'>{_e(labels['keep_link'])}</p>"
            if locked and (redeem_url or checkout_url or pay_links)
            else ""
        )
        + "</div></section>"
    )

    toc: list[tuple[str, str]] = []

    def section(title: str, content: str, key: str = "") -> str:
        if key:
            toc.append((key, title))
        anchor = f" id='{_e(key)}'" if key else ""
        return f"<section class='rsec'{anchor}><h2>{_e(title)}</h2>{content}</section>"

    links = [
        f"<a class='no-print' href='{_e(method_url(locale))}'>"
        f"{_e(METHOD_COPY.get(locale, METHOD_COPY['es'])['title'])}</a>"
    ]
    if legal_links:
        links += [
            f"<a href='{_e(legal_url(kind, locale))}'>{_e(LINK_TEXT[locale][kind])}</a>"
            for kind in ("terms", "privacy")
        ]
    footer = (
        "<div class='report-foot'>"
        f"<div class='disclaimer'><strong>{_e(labels['disclaimer'])}.</strong> "
        f"{_e(DISCLAIMER.get(locale, DISCLAIMER['es']))}</div>"
        f"<p class='rf-sha'><span>{_e(labels['json_sha'])}</span>"
        f"<code>{_e(result_sha256(result))}</code></p>"
        "<div class='rf-bar'>"
        f"<p class='rf-brand'><b>{_e(BRAND)}</b> · {_e(TAGLINE.get(locale, TAGLINE['es']))}</p>"
        f"<nav class='rf-links'>{''.join(links)}</nav></div></div>"
    )
    kpis_html = _kpis_html(data, labels, locked=locked)
    reading_html = _reading_html(data, labels)
    sections = [
        section(labels["reading"], reading_html, "r-reading") if reading_html else "",
        section(labels["kpis"], kpis_html, "r-kpis") if kpis_html else "",
        section(
            labels["meaning"],
            _meaning_html(verdict, locale, account=is_account_history(data)),
            "r-meaning",
        ),
        section(
            labels["next"],
            _next_steps_html(
                data,
                verdict,
                labels,
                {} if locked else {title: f"r-d{i}" for i, (title, _) in enumerate(detail, 1)},
            ),
            "r-next",
        ),
        section(labels["ladder"], _ladder_html(str(verdict["overall"]), labels), "r-ladder"),
        section(labels["charts"], _charts_html(data, locale), "r-charts"),
        section(
            labels["flags_free"], _flags_free_html(data["red_flags"], locale, labels), "r-flags"
        ),
        section(labels["plan"], _plan_html(data, locale, labels, locked=True), "r-plan")
        if locked
        else "",
        detail_html,
        publish_html,
        compare_html,
        section(labels["inputs"], inputs_html + _source_html(data, labels), "r-inputs"),
        section(labels["declared"], declared_html),
        section(labels["not_measured"], nm_html),
        section(labels["seal"], seal_html),
        footer,
    ]
    # The detail sections (or the lock box) sit between the plan and the inputs.
    detail_toc = (
        [("unlock", labels["toc_unlock"])]
        if locked
        else [(f"r-d{i}", title) for i, (title, _) in enumerate(detail, 1)]
    )
    toc = toc[:-1] + detail_toc + toc[-1:]
    page_title = f"{_title(data, labels)} {verdict['overall']} · {data['audit_id'][:8]}"
    return (
        "<!doctype html><html lang='"
        + _e(locale)
        + "'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, "
        "initial-scale=1'><meta name='theme-color' content='#05070b'><title>"
        + _e(page_title)
        + "</title>"
        + (head_meta if head_meta is not None else private_meta(page_title, locale))
        + "<style>"
        + STYLE
        + charts.CHART_CSS
        + PLAN_CSS
        + KPI_CSS
        + "</style>"
        + SCRIPT_TAG
        + "</head><body>"
        + header
        + hero
        + _report_toc(toc, labels["toc"])
        + "<main id='main' class='paper report-main'><div class='wrap wrap-mid'>"
        + "".join(sections)
        + "</div></main></body></html>"
    )


def _hero_live(data: dict[str, Any], labels: dict[str, str], anchor: str) -> str:
    """One line under the verdict when a live account was uploaded: the class
    grades the backtest, and a buyer must not have to scroll to learn how the
    real account compares with it and what it made or lost."""
    live = data.get("live") or {}
    if live.get("status") != "MEASURED":
        return ""
    outcome = str(live["outcome"])
    text = labels["hero_live"].format(badge=labels[f"live_badge_{outcome}"])
    account = data.get("account") or {}
    result = (account.get("trading_result") or {}).get("value")
    deposits = ((account.get("deposits") or {}).get("total") or {}).get("value")
    money = ""
    if account.get("status") == "MEASURED" and result is not None and deposits:
        money = " " + labels["hero_live_money"].format(
            result=_signed_amount(float(result)), deposits=f"{float(deposits):,.2f}"
        )
    link = f" <a href='#{_e(anchor)}'>{_e(labels['hero_live_link'])}</a>" if anchor else ""
    tone = {"PASS": "pass", "WEAK": "weak", "FAIL": "fail"}.get(LIVE_TONE.get(outcome, ""), "")
    return f"<p class='verdict-live {tone}'>{_e(text)}{_e(money)} {_badge('MEASURED')}{link}</p>"


def _pdf_cover(
    data: dict[str, Any], verdict: dict[str, Any], labels: dict[str, str], notice: str = ""
) -> str:
    """The PDF's first page, print only: the class, the verdict's headline, how each
    test came out, the key figures and the first things to do. Everything on it
    is already in the report; this puts it on one page for whoever reads the PDF.
    A page notice (the sample's "synthetic data") repeats here, so the cover alone
    never passes for a real account."""
    locale = _locale_of(labels)
    overall = str(verdict["overall"])
    ring = ring_svg(overall, css_class="pc-ring", letter=True)
    lead = str(verdict["summary"]).partition(". ")[0].rstrip(".") + "."
    by_name = {d["name"]: d for d in verdict["dimensions"]}
    dims = "".join(
        f"<li><span>{_e(_dimension_title(name, locale))}</span>"
        f"{_status_badge(by_name[name]['status'], locale)}</li>"
        for name in DIMENSION_ORDER
        if name in by_name
    )
    kpis = "".join(
        f"<div class='pc-kpi {tone}'><b>{_e(shown)}</b><span>{_e(label)}</span></div>"
        for label, shown, tone in _kpi_list(data, labels)[:4]
    )
    steps = [key for key, _ in _next_steps(data, verdict, labels) if key != "next_keep"][:3]
    next_html = "".join(f"<li>{_e(labels[key])}</li>" for key in steps or ["next_keep"])
    return (
        "<section class='pdf-cover'>"
        f"<div class='pc-top'><span class='pc-brand'>{logo_mark(22)}{_e(BRAND)}</span>"
        f"<span>{_e(labels['audit_id'])} {_e(data['audit_id'])} · "
        f"{_e(_short_time(data['generated_at_utc']))}</span></div>"
        + (f"<p class='pc-notice'>{_e(notice)}</p>" if notice else "")
        + f"<div class='pc-eyebrow'>{_e(_title(data, labels))}</div>"
        f"<div class='pc-hero'>{ring}<div><div class='verdict-k'>{_e(labels['verdict'])}</div>"
        f"<p class='pc-lead'>{_e(lead)}</p></div></div>"
        f"<h2 class='pc-h'>{_e(labels['dimensions'])}</h2><ul class='pc-dims'>{dims}</ul>"
        + (
            f"<h2 class='pc-h'>{_e(labels['kpis'])}</h2><div class='pc-kpis'>{kpis}</div>"
            if kpis
            else ""
        )
        + f"<h2 class='pc-h'>{_e(labels['next'])}</h2><ol class='pc-next'>{next_html}</ol>"
        f"<p class='pc-legend'>{_e(labels['evidence_legend'])}</p>"
        "</section>"
    )


def _next_steps(
    data: dict[str, Any], verdict: dict[str, Any], labels: dict[str, str]
) -> list[tuple[str, str]]:
    """The "what to do now" items as (label key, section title), in order."""
    status = {str(item["name"]): str(item["status"]) for item in verdict.get("dimensions", [])}
    open_ = {"WEAK", "FAIL"}
    account = is_account_history(data)
    steps: list[tuple[str, str]] = []
    live = data.get("live") or {}
    if live.get("status") == "MEASURED" and live.get("outcome") != "CONSISTENT":
        steps.append(("next_live", labels["live"]))
    if status.get("data_quality") == "FAIL":
        steps.append(("next_flags", labels["red_flags"]))
    if status.get("costs") == "FAIL":
        steps.append(("next_costs_fail", labels["costs"]))
    elif status.get("costs") == "WEAK":
        steps.append(("next_costs", labels["costs"]))
    if not account and status.get("multiplicity") in open_:
        steps.append(("next_trials", labels["plan"]))
    if not account and (status.get("out_of_sample") in open_ | {"NOT_MEASURED"}):
        steps.append(("next_oos", labels["plan"]))
    steps = steps[:3]
    if data.get("vendor_questions"):
        steps.append(("next_questions", labels["questions"]))
    steps.append(("next_keep", ""))
    return steps


def _next_steps_html(
    data: dict[str, Any],
    verdict: dict[str, Any],
    labels: dict[str, str],
    anchors: dict[str, str],
) -> str:
    """ "What to do now": the few things a buyer should clear up first, in
    order, from the dimensions that did not pass and the live comparison.
    The class plan speaks to whoever builds the robot; this speaks to whoever
    runs it. Questions to ask and checks to make, never a trading instruction."""
    steps = _next_steps(data, verdict, labels)

    def item(key: str, section: str) -> str:
        anchor = anchors.get(section, "")
        link = f" <a href='#{_e(anchor)}'>{_e(labels['next_link'])}</a>" if anchor else ""
        return f"<li>{_e(labels[key])}{link}</li>"

    return (
        f"<p class='muted'>{_e(labels['next_intro'])}</p>"
        f"<ol class='next-steps'>{''.join(item(key, section) for key, section in steps)}</ol>"
    )


def _verdict_html(summary: str) -> str:
    """The verdict: its first sentence as the headline, the rest as detail."""
    lead, sep, rest = summary.partition(". ")
    if not sep:
        return f"<p class='verdict-text'>{_e(summary)}</p>"
    return f"<p class='verdict-text'><span class='verdict-lead'>{_e(lead)}.</span> {_e(rest)}</p>"


def _report_toc(entries: list[tuple[str, str]], label: str) -> str:
    """A sticky row of links to the report's sections (hidden in print)."""
    links = "".join(f"<li><a href='#{_e(key)}'>{_e(title)}</a></li>" for key, title in entries)
    return (
        f"<nav class='report-toc no-print' aria-label='{_e(label)}'><div class='wrap wrap-mid'>"
        f"<ol data-toc>{links}</ol></div></nav>"
    )


def guard_texts(result: AuditResult, html_text: str) -> None:
    """Run the profit-claim guard over the HTML and over the JSON with the
    client's own text withheld (it is reported, never repeated)."""
    payload = result.model_dump(mode="json")
    payload["declared"]["description"] = "<client description withheld from guard>"
    payload["client_text_findings"] = [
        {"count": len(result.client_text_findings), "note": "withheld from guard"}
    ]
    assert_report_clean(html_text, canonical_dumps(payload))


def render(
    result: AuditResult,
    *,
    watermark: bool,
    free_mode: bool = True,
    price_usd: float | None = None,
    checkout_url: str | None = None,
    redeem_url: str | None = None,
    publish_url: str | None = None,
    notice: str | None = None,
    contact_url: str | None = None,
    legal_links: bool = False,
    locale: str | None = None,
    switch_url: str | None = None,
    head_meta: str | None = None,
    compare_link: str | None = None,
    pack_price_usd: float = 0.0,
    pdf_url: str | None = None,
    pack_code: str = "",
    pack_credits_left: int = 0,
    code_error: bool = False,
    pay_links: tuple[str, str, str] | None = None,
    notice_ok: bool = False,
    account_box: str = "",
) -> tuple[str, str]:
    """``(html, json)`` for a result, both guarded. Raises ``AuditReportError``."""
    html_text = render_html(
        result,
        watermark=watermark,
        free_mode=free_mode,
        price_usd=price_usd,
        checkout_url=checkout_url,
        redeem_url=redeem_url,
        publish_url=publish_url,
        notice=notice,
        contact_url=contact_url,
        legal_links=legal_links,
        locale=locale,
        switch_url=switch_url,
        head_meta=head_meta,
        compare_link=compare_link,
        pack_price_usd=pack_price_usd,
        pdf_url=pdf_url,
        pack_code=pack_code,
        pack_credits_left=pack_credits_left,
        code_error=code_error,
        pay_links=pay_links,
        notice_ok=notice_ok,
        account_box=account_box,
    )
    guard_texts(result, html_text)
    return html_text, to_json(result)


# The Portuguese of the tables above, over their English (see ``report_pt``).
report_pt.install(globals(), report_pt.REPORT)

__all__ = [
    "DISCLAIMER",
    "LABELS",
    "WATERMARK_TEXT",
    "guard_texts",
    "render",
    "render_html",
    "result_sha256",
    "to_json",
]
