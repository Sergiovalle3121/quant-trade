"""The words of the "Coherencia del archivo" page in Spanish, English and
Portuguese.

The battery answers codes and numbers without language; every sentence a
customer reads lives here. Each dict carries the same keys in the three
languages (a test enforces it) and every fixed sentence passes the
profit-claim guard. Nothing here calls a file authentic, clean or false:
a finding is a measured fact and a question for whoever generated the file.
"""

from __future__ import annotations

import re

from quant_trade.audit.seo import BRAND

LOCALES = ("es", "en", "pt")

#: The page's fixed sentences.
COPY: dict[str, dict[str, str]] = {
    "es": {
        "title": "Coherencia del archivo",
        "eyebrow": "Página privada del informe",
        "lead": (
            "Una batería de chequeos aritméticos y estructurales sobre el archivo que se "
            "subió con este informe: saldos que deben encadenarse, tickets que deben avanzar "
            "con el tiempo, precios con una precisión por símbolo, horas posibles. Cada "
            "hallazgo es un hecho medido y una pregunta para quien generó el archivo, no una "
            "acusación."
        ),
        "method": "El método es público: detecta ediciones descuidadas, no a quien lo estudie.",
        "no_change": (
            f"Nada de lo que aparece aquí cambia la clase que {BRAND} dio al informe ni "
            "ninguna de sus dimensiones."
        ),
        "paid_note": (
            "Esta página la ve quien tiene el informe completo; pagar no cambia ningún resultado."
        ),
        "back": "Volver al informe",
        "file_heading": "Qué se revisó",
        "family": "Tipo de archivo",
        "format": "Formato reconocido al subirlo",
        "method_version": "Versión del método",
        "rows_read": "Filas leídas",
        "truncated": (
            "El archivo supera el tope de filas de la batería: los chequeos que dependen del "
            "orden completo de la tabla no se midieron."
        ),
        "summary_heading": "Resumen",
        "counts": (
            "Señales: {signal} · Datos: {info} · Sin hallazgo: {clean} · No medidos: {not_measured}"
        ),
        "no_findings": (
            "No encontramos las huellas que revisamos; eso no prueba que el archivo sea original."
        ),
        "legit": (
            "Puede tener explicaciones legítimas; conviene aclararlo con quien generó el archivo."
        ),
        "info_uncalibrated": (
            "Este chequeo aún no está calibrado con suficientes archivos reales de este "
            "formato (n = {n}); no cuenta como señal."
        ),
        "info_descriptive": "Es una cifra descriptiva; no cuenta como señal.",
        "examples": "Filas de ejemplo, por su índice en la tabla leída: {rows}.",
        "table_heading": "Los chequeos, uno por uno",
        "col_check": "Chequeo",
        "col_status": "Estado",
        "col_figures": "Cifras medidas",
        "col_notes": "Notas",
        "clean_note": "Sin huellas en este chequeo.",
        "not_measured_prefix": "No se pudo medir: {reason}.",
        "calibration": (
            "{n} archivos reales de este formato; señales sin explicar: {unexplained}; "
            "cota superior 95 %: {cp95} %."
        ),
        "no_calibration": (
            "Sin calibración con archivos reales de este formato todavía: un hallazgo "
            "cuenta como dato, no como señal."
        ),
        "evidence_heading": "Cómo leer las etiquetas",
        "limits_heading": "Qué no puede decir esta página",
        "limits": (
            "Un archivo editado con cuidado pasa estas pruebas.|"
            "Nada aquí prueba que el bróker emitió el archivo, ni que la cuenta exista.|"
            "Cada chequeo mide una huella concreta; un chequeo no medido no dice nada, ni a "
            "favor ni en contra.|"
            "Una señal solo se otorga cuando el chequeo se probó en al menos veinte "
            "archivos reales de este formato sin señales sin explicar; hasta entonces un "
            "hallazgo es un dato.|"
            "Los ejemplos son índices de fila: aquí no aparece ningún texto del archivo."
        ),
        "digest_mismatch": (
            "No se pudo revisar el archivo guardado: su huella SHA-256 no coincide con la "
            "registrada al subirlo, así que la batería no lo leyó. Un informe nuevo con el "
            "mismo archivo permite revisarlo."
        ),
        "nothing_to_review": (
            "Este informe no tiene un archivo de plataforma ni una tabla mensual que la "
            "batería sepa leer: la coherencia se mide sobre extractos e historiales de "
            "MetaTrader, exportaciones CSV de plataformas conocidas y tablas mensuales."
        ),
        "review_failed": (
            "La batería no pudo leer este archivo hasta el final; ningún chequeo se midió. "
            "El informe no cambia."
        ),
        "busy": (
            "Ahora mismo no hay capacidad libre para revisar el archivo. En un minuto "
            "vuelve a haberla."
        ),
        "too_many": (
            "Demasiadas revisiones desde esta dirección en la última hora. Más tarde la "
            "página vuelve a estar disponible."
        ),
    },
    "en": {
        "title": "File consistency",
        "eyebrow": "Private page of the report",
        "lead": (
            "A battery of arithmetic and structural checks over the file uploaded with this "
            "report: balances that must chain, tickets that must advance with time, prices "
            "printed with one precision per symbol, hours that are possible. Each finding is "
            "a measured fact and a question for whoever generated the file, not an "
            "accusation."
        ),
        "method": ("The method is public: it detects careless edits, not whoever studies it."),
        "no_change": (
            f"Nothing shown here changes the class {BRAND} gave the report or any of its "
            "dimensions."
        ),
        "paid_note": (
            "This page is seen by whoever holds the full report; paying changes no result."
        ),
        "back": "Back to the report",
        "file_heading": "What was reviewed",
        "family": "File type",
        "format": "Format recognised at upload",
        "method_version": "Method version",
        "rows_read": "Rows read",
        "truncated": (
            "The file exceeds the battery's row cap: the checks that depend on the table's "
            "complete order were not measured."
        ),
        "summary_heading": "Summary",
        "counts": (
            "Signals: {signal} · Notes: {info} · No finding: {clean} · Not measured: {not_measured}"
        ),
        "no_findings": (
            "We did not find the traces we look for; that does not prove the file is original."
        ),
        "legit": (
            "It may have legitimate explanations; it is worth clarifying with whoever "
            "generated the file."
        ),
        "info_uncalibrated": (
            "This check is not yet calibrated on enough real files of this format "
            "(n = {n}); it does not count as a signal."
        ),
        "info_descriptive": "It is a descriptive figure; it does not count as a signal.",
        "examples": "Example rows, by their index in the table read: {rows}.",
        "table_heading": "The checks, one by one",
        "col_check": "Check",
        "col_status": "Status",
        "col_figures": "Measured figures",
        "col_notes": "Notes",
        "clean_note": "No traces in this check.",
        "not_measured_prefix": "Could not be measured: {reason}.",
        "calibration": (
            "{n} real files of this format; unexplained signals: {unexplained}; "
            "95 % upper bound: {cp95} %."
        ),
        "no_calibration": (
            "No calibration on real files of this format yet: a finding counts as a note, "
            "not as a signal."
        ),
        "evidence_heading": "How to read the tags",
        "limits_heading": "What this page cannot tell",
        "limits": (
            "A carefully edited file passes these tests.|"
            "Nothing here proves the broker issued the file, or that the account exists.|"
            "Each check measures one concrete trace; a check not measured says nothing, "
            "for or against.|"
            "A signal is granted only when the check was tried on at least twenty real "
            "files of this format with no unexplained signal; until then a finding is a "
            "note.|"
            "Examples are row indexes: no text from the file appears here."
        ),
        "digest_mismatch": (
            "The stored file could not be reviewed: its SHA-256 does not match the one "
            "recorded at upload, so the battery did not read it. A new report with the "
            "same file allows a review."
        ),
        "nothing_to_review": (
            "This report has no platform file or monthly table the battery can read: "
            "consistency is measured on MetaTrader statements and histories, CSV exports "
            "of known platforms and monthly tables."
        ),
        "review_failed": (
            "The battery could not read this file to the end; no check was measured. "
            "The report does not change."
        ),
        "busy": (
            "There is no free capacity to review the file right now. It comes back within a minute."
        ),
        "too_many": (
            "Too many reviews from this address in the last hour. The page is available "
            "again later."
        ),
    },
    "pt": {
        "title": "Coerência do arquivo",
        "eyebrow": "Página privada do relatório",
        "lead": (
            "Uma bateria de checagens aritméticas e estruturais sobre o arquivo enviado com "
            "este relatório: saldos que devem se encadear, tickets que devem avançar com o "
            "tempo, preços com uma precisão por símbolo, horários possíveis. Cada achado é "
            "um fato medido e uma pergunta para quem gerou o arquivo, não uma acusação."
        ),
        "method": "O método é público: detecta edições descuidadas, não quem o estude.",
        "no_change": (
            f"Nada do que aparece aqui muda a classe que o {BRAND} deu ao relatório nem "
            "nenhuma de suas dimensões."
        ),
        "paid_note": (
            "Esta página é vista por quem tem o relatório completo; pagar não muda nenhum "
            "resultado."
        ),
        "back": "Voltar ao relatório",
        "file_heading": "O que foi revisado",
        "family": "Tipo de arquivo",
        "format": "Formato reconhecido no envio",
        "method_version": "Versão do método",
        "rows_read": "Linhas lidas",
        "truncated": (
            "O arquivo excede o limite de linhas da bateria: as checagens que dependem da "
            "ordem completa da tabela não foram medidas."
        ),
        "summary_heading": "Resumo",
        "counts": (
            "Sinais: {signal} · Dados: {info} · Sem achado: {clean} · Não medidos: {not_measured}"
        ),
        "no_findings": (
            "Não encontramos os rastros que revisamos; isso não prova que o arquivo seja original."
        ),
        "legit": ("Pode ter explicações legítimas; convém esclarecer com quem gerou o arquivo."),
        "info_uncalibrated": (
            "Esta checagem ainda não está calibrada com arquivos reais suficientes deste "
            "formato (n = {n}); não conta como sinal."
        ),
        "info_descriptive": "É um número descritivo; não conta como sinal.",
        "examples": "Linhas de exemplo, pelo índice na tabela lida: {rows}.",
        "table_heading": "As checagens, uma a uma",
        "col_check": "Checagem",
        "col_status": "Estado",
        "col_figures": "Números medidos",
        "col_notes": "Notas",
        "clean_note": "Sem rastros nesta checagem.",
        "not_measured_prefix": "Não foi possível medir: {reason}.",
        "calibration": (
            "{n} arquivos reais deste formato; sinais sem explicação: {unexplained}; "
            "limite superior 95 %: {cp95} %."
        ),
        "no_calibration": (
            "Ainda sem calibração com arquivos reais deste formato: um achado conta como "
            "dado, não como sinal."
        ),
        "evidence_heading": "Como ler as etiquetas",
        "limits_heading": "O que esta página não pode dizer",
        "limits": (
            "Um arquivo editado com cuidado passa nestes testes.|"
            "Nada aqui prova que a corretora emitiu o arquivo, nem que a conta exista.|"
            "Cada checagem mede um rastro concreto; uma checagem não medida não diz nada, "
            "nem a favor nem contra.|"
            "Um sinal só é concedido quando a checagem foi testada em pelo menos vinte "
            "arquivos reais deste formato sem sinais sem explicação; até lá um achado é um "
            "dado.|"
            "Os exemplos são índices de linha: nenhum texto do arquivo aparece aqui."
        ),
        "digest_mismatch": (
            "Não foi possível revisar o arquivo guardado: seu SHA-256 não coincide com o "
            "registrado no envio, então a bateria não o leu. Um relatório novo com o mesmo "
            "arquivo permite revisá-lo."
        ),
        "nothing_to_review": (
            "Este relatório não tem um arquivo de plataforma nem uma tabela mensal que a "
            "bateria saiba ler: a coerência é medida em extratos e históricos do "
            "MetaTrader, exportações CSV de plataformas conhecidas e tabelas mensais."
        ),
        "review_failed": (
            "A bateria não conseguiu ler este arquivo até o fim; nenhuma checagem foi "
            "medida. O relatório não muda."
        ),
        "busy": ("Agora não há capacidade livre para revisar o arquivo. Em um minuto ela volta."),
        "too_many": (
            "Revisões demais a partir deste endereço na última hora. Mais tarde a página "
            "volta a estar disponível."
        ),
    },
}

#: The status chips: never "limpio" / "clean" on screen.
STATUS_WORDS: dict[str, dict[str, str]] = {
    "es": {
        "SIGNAL": "Señal",
        "INFO": "Dato",
        "CLEAN": "Sin hallazgo",
        "NOT_MEASURED": "No medido",
    },
    "en": {
        "SIGNAL": "Signal",
        "INFO": "Note",
        "CLEAN": "No finding",
        "NOT_MEASURED": "Not measured",
    },
    "pt": {
        "SIGNAL": "Sinal",
        "INFO": "Dado",
        "CLEAN": "Sem achado",
        "NOT_MEASURED": "Não medido",
    },
}

#: The evidence tags next to every figure.
EVIDENCE_WORDS: dict[str, dict[str, str]] = {
    "es": {"MEASURED": "Medido", "DECLARED": "Declarado", "NOT_MEASURED": "No medido"},
    "en": {"MEASURED": "Measured", "DECLARED": "Declared", "NOT_MEASURED": "Not measured"},
    "pt": {"MEASURED": "Medido", "DECLARED": "Declarado", "NOT_MEASURED": "Não medido"},
}

#: What each evidence tag means, one line each.
EVIDENCE_HELP: dict[str, dict[str, str]] = {
    "es": {
        "MEASURED": "Lo contamos nosotros a partir de las filas del archivo.",
        "DECLARED": "Lo dice el archivo o su plataforma; no lo podemos comprobar.",
        "NOT_MEASURED": "Faltaban datos para medirlo, y decimos cuáles.",
    },
    "en": {
        "MEASURED": "We counted it from the file's rows.",
        "DECLARED": "The file or its platform states it; we cannot check it.",
        "NOT_MEASURED": "Data was missing to measure it, and we say which.",
    },
    "pt": {
        "MEASURED": "Contamos a partir das linhas do arquivo.",
        "DECLARED": "O arquivo ou sua plataforma declara; não podemos conferir.",
        "NOT_MEASURED": "Faltavam dados para medir, e dizemos quais.",
    },
}

#: The format family of the file, in words.
FAMILY_NAMES: dict[str, dict[str, str]] = {
    "es": {
        "mt4_statement": "Extracto de cuenta de MetaTrader 4",
        "mt5_history": "Historial de cuenta de MetaTrader 5",
        "mt5_tester": "Informe del probador de estrategias de MetaTrader 5",
        "mt4_tester": "Informe del probador de estrategias de MetaTrader 4",
        "myfxbook": "Exportación CSV de Myfxbook",
        "mql5_signal": "Exportación CSV de una señal de MQL5",
        "fxblue": "Exportación CSV de FX Blue",
        "tradingview": "Exportación de TradingView",
        "ninjatrader": "Exportación de NinjaTrader",
        "monthly": "Tabla mensual de rendimientos",
        "other": "Formato que la batería no cubre",
    },
    "en": {
        "mt4_statement": "MetaTrader 4 account statement",
        "mt5_history": "MetaTrader 5 account history",
        "mt5_tester": "MetaTrader 5 Strategy Tester report",
        "mt4_tester": "MetaTrader 4 Strategy Tester report",
        "myfxbook": "Myfxbook CSV export",
        "mql5_signal": "MQL5 signal CSV export",
        "fxblue": "FX Blue CSV export",
        "tradingview": "TradingView export",
        "ninjatrader": "NinjaTrader export",
        "monthly": "Monthly returns table",
        "other": "Format the battery does not cover",
    },
    "pt": {
        "mt4_statement": "Extrato de conta do MetaTrader 4",
        "mt5_history": "Histórico de conta do MetaTrader 5",
        "mt5_tester": "Relatório do testador de estratégias do MetaTrader 5",
        "mt4_tester": "Relatório do testador de estratégias do MetaTrader 4",
        "myfxbook": "Exportação CSV do Myfxbook",
        "mql5_signal": "Exportação CSV de um sinal do MQL5",
        "fxblue": "Exportação CSV do FX Blue",
        "tradingview": "Exportação do TradingView",
        "ninjatrader": "Exportação do NinjaTrader",
        "monthly": "Tabela mensal de retornos",
        "other": "Formato que a bateria não cobre",
    },
}

#: The name of every check, in ``review.CHECK_ORDER``.
CHECK_NAMES: dict[str, dict[str, str]] = {
    "es": {
        "FILE_TRACE": "Rastro del archivo",
        "TOTALS_VS_ROWS": "Totales del resumen frente a las filas",
        "SUMMARY_IDENTITIES": "Identidades entre totales del resumen",
        "BALANCE_CHAIN": "Cadena de saldos",
        "DEAL_SEQUENCE": "Secuencia de deals y órdenes",
        "TESTER_NUMBERING": "Numeración del probador",
        "TICKET_ORDER": "Orden de los tickets",
        "DUPLICATE_TICKET": "Tickets duplicados",
        "TICKET_LINKS": "Enlaces entre tickets",
        "CROSS_COPIES": "Copias entre tablas",
        "SLTP_FILL": "Cierres por stop y take profit",
        "PNL_SIGN": "Signo del resultado",
        "PRICE_IMPLIED_PNL": "Resultado implícito en los precios",
        "PRICE_PRECISION": "Precisión de los precios",
        "TIME_SANITY": "Horas posibles",
        "ROW_ORDER": "Orden de las filas",
        "MARKET_HOURS": "Horario del mercado",
        "HIDDEN_CONTENT": "Contenido oculto",
        "VOLUME_IN_OUT": "Volumen que entra y sale",
        "STATEMENT_PERIOD": "Periodo del extracto",
        "TV_INVARIANTS": "Invariantes de TradingView",
        "NT_INVARIANTS": "Invariantes de NinjaTrader",
        "MONTHLY_DIGITS": "Dígitos de la tabla mensual",
    },
    "en": {
        "FILE_TRACE": "File trace",
        "TOTALS_VS_ROWS": "Summary totals against the rows",
        "SUMMARY_IDENTITIES": "Identities between summary totals",
        "BALANCE_CHAIN": "Balance chain",
        "DEAL_SEQUENCE": "Deal and order sequence",
        "TESTER_NUMBERING": "Tester numbering",
        "TICKET_ORDER": "Ticket order",
        "DUPLICATE_TICKET": "Duplicate tickets",
        "TICKET_LINKS": "Links between tickets",
        "CROSS_COPIES": "Copies between tables",
        "SLTP_FILL": "Stop and take-profit fills",
        "PNL_SIGN": "Sign of the result",
        "PRICE_IMPLIED_PNL": "Result implied by the prices",
        "PRICE_PRECISION": "Price precision",
        "TIME_SANITY": "Possible hours",
        "ROW_ORDER": "Row order",
        "MARKET_HOURS": "Market hours",
        "HIDDEN_CONTENT": "Hidden content",
        "VOLUME_IN_OUT": "Volume in and out",
        "STATEMENT_PERIOD": "Statement period",
        "TV_INVARIANTS": "TradingView invariants",
        "NT_INVARIANTS": "NinjaTrader invariants",
        "MONTHLY_DIGITS": "Digits of the monthly table",
    },
    "pt": {
        "FILE_TRACE": "Rastro do arquivo",
        "TOTALS_VS_ROWS": "Totais do resumo frente às linhas",
        "SUMMARY_IDENTITIES": "Identidades entre totais do resumo",
        "BALANCE_CHAIN": "Cadeia de saldos",
        "DEAL_SEQUENCE": "Sequência de deals e ordens",
        "TESTER_NUMBERING": "Numeração do testador",
        "TICKET_ORDER": "Ordem dos tickets",
        "DUPLICATE_TICKET": "Tickets duplicados",
        "TICKET_LINKS": "Vínculos entre tickets",
        "CROSS_COPIES": "Cópias entre tabelas",
        "SLTP_FILL": "Fechamentos por stop e take profit",
        "PNL_SIGN": "Sinal do resultado",
        "PRICE_IMPLIED_PNL": "Resultado implícito nos preços",
        "PRICE_PRECISION": "Precisão dos preços",
        "TIME_SANITY": "Horários possíveis",
        "ROW_ORDER": "Ordem das linhas",
        "MARKET_HOURS": "Horário do mercado",
        "HIDDEN_CONTENT": "Conteúdo oculto",
        "VOLUME_IN_OUT": "Volume que entra e sai",
        "STATEMENT_PERIOD": "Período do extrato",
        "TV_INVARIANTS": "Invariantes do TradingView",
        "NT_INVARIANTS": "Invariantes do NinjaTrader",
        "MONTHLY_DIGITS": "Dígitos da tabela mensal",
    },
}

#: The measured fact of a check with hits, formatted from ``n_hits`` and
#: ``n_rows`` only (every check that can hit reports both).
CHECK_FACTS: dict[str, dict[str, str]] = {
    "es": {
        "FILE_TRACE": (
            "Entre {n_rows} filas leídas, {n_hits} rasgo(s) del archivo (codificación, "
            "generador o marcas de otro programa) no coinciden con los que deja la "
            "plataforma al escribirlo"
        ),
        "TOTALS_VS_ROWS": (
            "En {n_hits} total(es) el resumen del archivo no coincide con lo que suman sus filas"
        ),
        "SUMMARY_IDENTITIES": (
            "{n_hits} identidad(es) entre los totales del resumen no cuadran entre sí"
        ),
        "BALANCE_CHAIN": (
            "En {n_hits} de {n_rows} filas el saldo impreso no es el saldo anterior más el "
            "resultado de la fila"
        ),
        "DEAL_SEQUENCE": (
            "En {n_hits} de {n_rows} filas la numeración de deals u órdenes no avanza con el tiempo"
        ),
        "TESTER_NUMBERING": (
            "En {n_hits} de {n_rows} filas la numeración del probador salta, se repite o retrocede"
        ),
        "TICKET_ORDER": (
            "En {n_hits} de {n_rows} filas el orden de los tickets no sigue el orden de las horas"
        ),
        "DUPLICATE_TICKET": "{n_hits} ticket(s) aparecen más de una vez entre {n_rows} filas",
        "TICKET_LINKS": (
            "{n_hits} referencia(s) «to #» o «from #» no enlazan con el ticket que citan"
        ),
        "CROSS_COPIES": (
            "{n_hits} fila(s) de una tabla repiten valores de otra tabla del mismo archivo"
        ),
        "SLTP_FILL": (
            "En {n_hits} de {n_rows} filas cerradas por stop o take profit el precio de "
            "cierre no coincide con el nivel impreso"
        ),
        "PNL_SIGN": (
            "En {n_hits} de {n_rows} filas el signo del resultado no coincide con la "
            "dirección del precio"
        ),
        "PRICE_IMPLIED_PNL": (
            "En {n_hits} de {n_rows} filas el resultado impreso se aparta del que implican "
            "los precios y el volumen"
        ),
        "PRICE_PRECISION": (
            "{n_hits} de {n_rows} filas imprimen un precio con una precisión distinta de la "
            "del resto de su símbolo"
        ),
        "TIME_SANITY": (
            "{n_hits} de {n_rows} filas tienen horas imposibles (cierre antes de la "
            "apertura o fuera de secuencia)"
        ),
        "ROW_ORDER": (
            "{n_hits} de {n_rows} filas rompen el orden en que la plataforma escribe la tabla"
        ),
        "MARKET_HOURS": (
            "{n_hits} de {n_rows} filas están fechadas con el mercado de su símbolo cerrado"
        ),
        "HIDDEN_CONTENT": (
            "{n_hits} celda(s) o fila(s) ocultas con contenido entre {n_rows} filas"
        ),
        "VOLUME_IN_OUT": (
            "En {n_hits} de {n_rows} filas el volumen que sale supera al que había entrado"
        ),
        "STATEMENT_PERIOD": "Periodo del extracto medido en {n_rows} filas ({n_hits} hallazgos)",
        "TV_INVARIANTS": (
            "{n_hits} de {n_rows} filas rompen las relaciones internas de una exportación "
            "de TradingView"
        ),
        "NT_INVARIANTS": (
            "{n_hits} de {n_rows} filas rompen las relaciones internas de una exportación "
            "de NinjaTrader"
        ),
        "MONTHLY_DIGITS": (
            "{n_hits} rasgo(s) en los dígitos finales o en valores repetidos de {n_rows} "
            "celdas mensuales"
        ),
    },
    "en": {
        "FILE_TRACE": (
            "Among {n_rows} rows read, {n_hits} trait(s) of the file (encoding, generator "
            "or marks of another program) differ from those the platform leaves when it "
            "writes it"
        ),
        "TOTALS_VS_ROWS": (
            "In {n_hits} total(s) the file's summary does not match what its rows add up to"
        ),
        "SUMMARY_IDENTITIES": (
            "{n_hits} identity(ies) between the summary totals do not hold together"
        ),
        "BALANCE_CHAIN": (
            "In {n_hits} of {n_rows} rows the printed balance is not the previous balance "
            "plus the row's result"
        ),
        "DEAL_SEQUENCE": (
            "In {n_hits} of {n_rows} rows the deal or order numbering does not advance with time"
        ),
        "TESTER_NUMBERING": (
            "In {n_hits} of {n_rows} rows the tester's numbering skips, repeats or goes back"
        ),
        "TICKET_ORDER": (
            "In {n_hits} of {n_rows} rows the ticket order does not follow the order of the times"
        ),
        "DUPLICATE_TICKET": "{n_hits} ticket(s) appear more than once among {n_rows} rows",
        "TICKET_LINKS": (
            "{n_hits} “to #” or “from #” reference(s) do not link to the ticket they cite"
        ),
        "CROSS_COPIES": (
            "{n_hits} row(s) of one table repeat values of another table in the same file"
        ),
        "SLTP_FILL": (
            "In {n_hits} of {n_rows} rows closed by stop or take profit the close price "
            "does not match the printed level"
        ),
        "PNL_SIGN": (
            "In {n_hits} of {n_rows} rows the sign of the result does not match the "
            "direction of the price"
        ),
        "PRICE_IMPLIED_PNL": (
            "In {n_hits} of {n_rows} rows the printed result departs from the one the "
            "prices and volume imply"
        ),
        "PRICE_PRECISION": (
            "{n_hits} of {n_rows} rows print a price with a precision unlike the rest of "
            "their symbol"
        ),
        "TIME_SANITY": (
            "{n_hits} of {n_rows} rows carry impossible hours (a close before the open, or "
            "out of sequence)"
        ),
        "ROW_ORDER": (
            "{n_hits} of {n_rows} rows break the order in which the platform writes the table"
        ),
        "MARKET_HOURS": (
            "{n_hits} of {n_rows} rows are dated while the market of their symbol is closed"
        ),
        "HIDDEN_CONTENT": "{n_hits} hidden cell(s) or row(s) with content among {n_rows} rows",
        "VOLUME_IN_OUT": (
            "In {n_hits} of {n_rows} rows the volume going out exceeds what had come in"
        ),
        "STATEMENT_PERIOD": "Statement period measured on {n_rows} rows ({n_hits} findings)",
        "TV_INVARIANTS": (
            "{n_hits} of {n_rows} rows break the internal relations of a TradingView export"
        ),
        "NT_INVARIANTS": (
            "{n_hits} of {n_rows} rows break the internal relations of a NinjaTrader export"
        ),
        "MONTHLY_DIGITS": (
            "{n_hits} trait(s) in the last digits or in repeated values of {n_rows} monthly cells"
        ),
    },
    "pt": {
        "FILE_TRACE": (
            "Entre {n_rows} linhas lidas, {n_hits} traço(s) do arquivo (codificação, "
            "gerador ou marcas de outro programa) não coincidem com os que a plataforma "
            "deixa ao escrevê-lo"
        ),
        "TOTALS_VS_ROWS": (
            "Em {n_hits} total(is) o resumo do arquivo não coincide com o que suas linhas somam"
        ),
        "SUMMARY_IDENTITIES": (
            "{n_hits} identidade(s) entre os totais do resumo não fecham entre si"
        ),
        "BALANCE_CHAIN": (
            "Em {n_hits} de {n_rows} linhas o saldo impresso não é o saldo anterior mais o "
            "resultado da linha"
        ),
        "DEAL_SEQUENCE": (
            "Em {n_hits} de {n_rows} linhas a numeração de deals ou ordens não avança com o tempo"
        ),
        "TESTER_NUMBERING": (
            "Em {n_hits} de {n_rows} linhas a numeração do testador salta, se repete ou retrocede"
        ),
        "TICKET_ORDER": (
            "Em {n_hits} de {n_rows} linhas a ordem dos tickets não segue a ordem dos horários"
        ),
        "DUPLICATE_TICKET": "{n_hits} ticket(s) aparecem mais de uma vez entre {n_rows} linhas",
        "TICKET_LINKS": (
            "{n_hits} referência(s) «to #» ou «from #» não se vinculam ao ticket que citam"
        ),
        "CROSS_COPIES": (
            "{n_hits} linha(s) de uma tabela repetem valores de outra tabela do mesmo arquivo"
        ),
        "SLTP_FILL": (
            "Em {n_hits} de {n_rows} linhas fechadas por stop ou take profit o preço de "
            "fechamento não coincide com o nível impresso"
        ),
        "PNL_SIGN": (
            "Em {n_hits} de {n_rows} linhas o sinal do resultado não coincide com a "
            "direção do preço"
        ),
        "PRICE_IMPLIED_PNL": (
            "Em {n_hits} de {n_rows} linhas o resultado impresso se afasta do que os "
            "preços e o volume implicam"
        ),
        "PRICE_PRECISION": (
            "{n_hits} de {n_rows} linhas imprimem um preço com precisão diferente da do "
            "resto de seu símbolo"
        ),
        "TIME_SANITY": (
            "{n_hits} de {n_rows} linhas têm horários impossíveis (fechamento antes da "
            "abertura ou fora de sequência)"
        ),
        "ROW_ORDER": (
            "{n_hits} de {n_rows} linhas quebram a ordem em que a plataforma escreve a tabela"
        ),
        "MARKET_HOURS": (
            "{n_hits} de {n_rows} linhas estão datadas com o mercado de seu símbolo fechado"
        ),
        "HIDDEN_CONTENT": (
            "{n_hits} célula(s) ou linha(s) ocultas com conteúdo entre {n_rows} linhas"
        ),
        "VOLUME_IN_OUT": (
            "Em {n_hits} de {n_rows} linhas o volume que sai supera o que havia entrado"
        ),
        "STATEMENT_PERIOD": "Período do extrato medido em {n_rows} linhas ({n_hits} achados)",
        "TV_INVARIANTS": (
            "{n_hits} de {n_rows} linhas quebram as relações internas de uma exportação do "
            "TradingView"
        ),
        "NT_INVARIANTS": (
            "{n_hits} de {n_rows} linhas quebram as relações internas de uma exportação do "
            "NinjaTrader"
        ),
        "MONTHLY_DIGITS": (
            "{n_hits} traço(s) nos dígitos finais ou em valores repetidos de {n_rows} "
            "células mensais"
        ),
    },
}

#: The closed list of ``NOT_MEASURED`` reasons (``review.REASONS``) in words.
REASON_TEXT: dict[str, dict[str, str]] = {
    "es": {
        "format_not_covered": "este chequeo no está definido para este formato de archivo",
        "no_table": "el archivo no tiene la tabla que este chequeo lee",
        "no_column": "la tabla no tiene la columna que este chequeo necesita",
        "no_qualifying_row": "ninguna fila cumple las condiciones del chequeo",
        "no_listed_symbol": "los símbolos del archivo no están en la lista de horarios conocidos",
        "xlsx_precision_lost": "la hoja de cálculo no conserva los ceros impresos de los precios",
        "variable_precision_format": "este formato imprime los precios con precisión variable",
        "no_header_date": "el archivo no declara la fecha del informe en su cabecera",
        "no_declared_totals": "el archivo no declara los totales que este chequeo compara",
        "netting_or_unknown_margin_mode": (
            "la cuenta usa netting o no declara su modo de margen, y el chequeo requiere hedging"
        ),
        "no_orders_table": "el archivo no tiene tabla de órdenes",
        "several_accounts": "el archivo contiene más de una cuenta",
        "too_few_values": "hay pocos valores para medirlo",
        "quote_currency_differs": (
            "la moneda de cotización de los símbolos no es la de la cuenta, y el cambio no "
            "está en el archivo"
        ),
        "truncated": "el archivo supera el tope de filas y este chequeo depende del orden completo",
        "caps_hit": "el archivo supera un tope de tamaño del chequeo",
    },
    "en": {
        "format_not_covered": "this check is not defined for this file format",
        "no_table": "the file has no table this check reads",
        "no_column": "the table lacks the column this check needs",
        "no_qualifying_row": "no row meets the check's conditions",
        "no_listed_symbol": "the file's symbols are not in the list of known market hours",
        "xlsx_precision_lost": "the spreadsheet does not keep the printed zeros of the prices",
        "variable_precision_format": "this format prints prices with variable precision",
        "no_header_date": "the file does not state the report date in its header",
        "no_declared_totals": "the file does not state the totals this check compares",
        "netting_or_unknown_margin_mode": (
            "the account uses netting or does not state its margin mode, and the check "
            "requires hedging"
        ),
        "no_orders_table": "the file has no orders table",
        "several_accounts": "the file holds more than one account",
        "too_few_values": "there are too few values to measure it",
        "quote_currency_differs": (
            "the symbols' quote currency is not the account's, and the rate is not in the file"
        ),
        "truncated": "the file exceeds the row cap and this check depends on the complete order",
        "caps_hit": "the file exceeds a size cap of the check",
    },
    "pt": {
        "format_not_covered": "esta checagem não está definida para este formato de arquivo",
        "no_table": "o arquivo não tem a tabela que esta checagem lê",
        "no_column": "a tabela não tem a coluna de que esta checagem precisa",
        "no_qualifying_row": "nenhuma linha cumpre as condições da checagem",
        "no_listed_symbol": "os símbolos do arquivo não estão na lista de horários conhecidos",
        "xlsx_precision_lost": "a planilha não conserva os zeros impressos dos preços",
        "variable_precision_format": "este formato imprime os preços com precisão variável",
        "no_header_date": "o arquivo não declara a data do relatório em seu cabeçalho",
        "no_declared_totals": "o arquivo não declara os totais que esta checagem compara",
        "netting_or_unknown_margin_mode": (
            "a conta usa netting ou não declara seu modo de margem, e a checagem exige hedging"
        ),
        "no_orders_table": "o arquivo não tem tabela de ordens",
        "several_accounts": "o arquivo contém mais de uma conta",
        "too_few_values": "há poucos valores para medir",
        "quote_currency_differs": (
            "a moeda de cotação dos símbolos não é a da conta, e o câmbio não está no arquivo"
        ),
        "truncated": (
            "o arquivo excede o limite de linhas e esta checagem depende da ordem completa"
        ),
        "caps_hit": "o arquivo excede um limite de tamanho da checagem",
    },
}

#: Labels of the figure keys the checks emit. A key not listed renders as
#: its code with the underscores replaced; a ``_left`` / ``_right`` /
#: ``_examined`` suffix or a trailing ``_2`` is derived from the base key.
FIGURE_LABELS: dict[str, dict[str, str]] = {
    "es": {
        "n_rows": "filas",
        "n_hits": "hallazgos",
        "n_ids": "identificadores",
        "n_deals": "deals",
        "n_orders": "órdenes",
        "n_trades": "operaciones",
        "n_closed": "cerradas",
        "n_open": "abiertas",
        "n_positions": "posiciones",
        "n_symbols": "símbolos",
        "n_symbols_measured": "símbolos medidos",
        "n_accounts": "cuentas",
        "n_identities": "identidades",
        "n_links": "enlaces",
        "n_tp": "cierres por take profit",
        "n_sl": "cierres por stop",
        "n_hidden_cells": "celdas ocultas",
        "n_zero_gross": "resultados brutos a cero",
        "n_zero_move": "movimientos de precio a cero",
        "n_rows_off_mode": "filas fuera de la precisión habitual",
        "accounts": "cuentas",
        "accounts_in_file": "cuentas en el archivo",
        "after_report_date": "filas posteriores a la fecha del informe",
        "report_date": "fecha del informe",
        "report_date_source": "origen de la fecha del informe",
        "max_ahead_seconds": "máximo adelanto (segundos)",
        "backwards_within_1h": "retrocesos de menos de una hora",
        "close_before_open_over_1h": "cierres más de una hora antes de la apertura",
        "zero_duration": "duración cero",
        "unparseable": "horas ilegibles",
        "copies_compared": "copias comparadas",
        "core_hits": "hallazgos en horario central",
        "holiday_hits": "hallazgos en festivos",
        "timestamps_measured": "marcas de tiempo medidas",
        "symbols_measured": "símbolos medidos",
        "inferred_offset_minutes": "desfase horario inferido (minutos)",
        "window": "ventana de cierre (código)",
        "deal_gaps": "huecos entre deals",
        "order_gaps": "huecos entre órdenes",
        "gaps": "huecos",
        "decimals": "decimales",
        "declared": "valor declarado",
        "measured": "valor medido",
        "what_code": "total comparado (código)",
        "direction": "dirección de la tabla",
        "direction_rule": "regla de dirección",
        "order_key": "clave de orden",
        "ties": "empates",
        "ties_fixed": "empates resueltos",
        "duplicates": "duplicados",
        "numbering_duplicates": "números repetidos",
        "numbering_gaps": "huecos de numeración",
        "numbering_start": "primer número",
        "encoding": "codificación",
        "line_endings": "fin de línea",
        "generator": "generador",
        "generator_native": "generador de la plataforma",
        "resave_markers": "marcas de reguardado",
        "platform_markers": "marcas de la plataforma",
        "title_attrs": "atributos de título",
        "hidden_cells": "celdas ocultas",
        "hidden_nonempty": "celdas ocultas con contenido",
        "hidden_rows": "filas ocultas",
        "hidden_cost_rows": "filas de coste ocultas",
        "decimal_comma": "coma decimal",
        "sections": "secciones (código)",
        "entries_inconsistent": "entradas incoherentes",
        "exits_inconsistent": "salidas incoherentes",
        "exits_partial": "salidas parciales",
        "expected_max": "máximo esperado",
        "seen": "vistos",
        "out_of_order": "fuera de orden",
        "first_break_row": "primera ruptura (fila)",
        "first_negative_row": "primer volumen negativo (fila)",
        "largest_gap": "mayor diferencia",
        "restarts": "reinicios",
        "importer_balance_breaks": "rupturas de saldo del importador",
        "identical_rows": "filas idénticas",
        "initial_balance_implied": "saldo inicial implícito",
        "inversions_open_time": "inversiones por hora de apertura",
        "inversions_close_time": "inversiones por hora de cierre",
        "max_backwards_seconds": "mayor retroceso (segundos)",
        "max_backwards_seconds_close": "mayor retroceso al cierre (segundos)",
        "ticket_inversions": "inversiones de ticket",
        "time_inversions": "inversiones de hora",
        "order_inversions": "inversiones de orden",
        "last_trade_excluded": "última operación excluida",
        "open_last_trade": "última operación abierta",
        "levels_cleared": "niveles superados",
        "links_inconsistent": "enlaces incoherentes",
        "links_unresolved": "enlaces sin resolver",
        "orders_inconsistent": "órdenes incoherentes",
        "orders_unresolved": "órdenes sin resolver",
        "orders_missing_for_deals": "deals sin orden",
        "orders_single_row": "órdenes de una sola fila",
        "no_orders_table": "sin tabla de órdenes",
        "max_multiplicity": "máxima repetición",
        "values_repeated_3plus": "valores repetidos tres o más veces",
        "zero_months": "meses a cero",
        "year_mismatch": "años con total distinto",
        "rounding_grid": "tabla redondeada",
        "last_digit_chi2": "chi cuadrado del último dígito",
        "opens_with_deposit": "abre con depósito",
        "first_row_at": "primera fila",
        "last_row_at": "última fila",
        "positions_before_period": "posiciones anteriores al periodo",
        "pre_period_positions": "posiciones anteriores al periodo",
        "rows_unparsed": "filas ilegibles",
        "rows_without_number": "filas sin número",
        "skipped_first": "primeras filas omitidas",
        "sl_better_fills": "stops ejecutados a mejor precio",
        "sl_hits": "hallazgos en stops",
        "tp_hits": "hallazgos en take profit",
        "split_at_row": "cambio de precisión (fila)",
        "split_symbols": "símbolos con dos precisiones",
        "symbols_no_fit": "símbolos sin ajuste",
        "symbols_quote_differs": "símbolos con otra moneda de cotización",
        "symbols_single_row": "símbolos de una sola fila",
        "size_multiplier": "multiplicador de tamaño",
        "size_value": "tamaño por valor",
        "cumulative": "acumulado",
        "etd": "excursión",
        "return_pct": "rendimiento en porcentaje",
        "time_examined": "horas examinadas",
        "exit_before_entry": "salidas antes de la entrada",
        "pair_shape": "forma de los pares",
        "pair_values": "valores de los pares",
        "balance_flows_pnl": "saldo = flujos + resultado",
        "closed_pnl_summary": "resultado cerrado = resumen",
        "equity_balance_floating": "equity = saldo + flotante",
        "free_margin_equity_margin": "margen libre = equity − margen",
        "net_profit_gross": "neto = bruto ganado − bruto perdido",
        "profit_factor_gross": "factor de beneficio = brutos",
        "trades_profit_loss": "operaciones = ganadoras + perdedoras",
        "trades_short_long": "operaciones = cortas + largas",
    },
    "en": {
        "n_rows": "rows",
        "n_hits": "findings",
        "n_ids": "identifiers",
        "n_deals": "deals",
        "n_orders": "orders",
        "n_trades": "trades",
        "n_closed": "closed",
        "n_open": "open",
        "n_positions": "positions",
        "n_symbols": "symbols",
        "n_symbols_measured": "symbols measured",
        "n_accounts": "accounts",
        "n_identities": "identities",
        "n_links": "links",
        "n_tp": "take-profit closes",
        "n_sl": "stop closes",
        "n_hidden_cells": "hidden cells",
        "n_zero_gross": "zero gross results",
        "n_zero_move": "zero price moves",
        "n_rows_off_mode": "rows off the usual precision",
        "accounts": "accounts",
        "accounts_in_file": "accounts in the file",
        "after_report_date": "rows after the report date",
        "report_date": "report date",
        "report_date_source": "source of the report date",
        "max_ahead_seconds": "largest lead (seconds)",
        "backwards_within_1h": "steps back under one hour",
        "close_before_open_over_1h": "closes over an hour before the open",
        "zero_duration": "zero duration",
        "unparseable": "unreadable times",
        "copies_compared": "copies compared",
        "core_hits": "findings in core hours",
        "holiday_hits": "findings on holidays",
        "timestamps_measured": "timestamps measured",
        "symbols_measured": "symbols measured",
        "inferred_offset_minutes": "inferred clock offset (minutes)",
        "window": "closure window (code)",
        "deal_gaps": "gaps between deals",
        "order_gaps": "gaps between orders",
        "gaps": "gaps",
        "decimals": "decimals",
        "declared": "declared value",
        "measured": "measured value",
        "what_code": "total compared (code)",
        "direction": "table direction",
        "direction_rule": "direction rule",
        "order_key": "order key",
        "ties": "ties",
        "ties_fixed": "ties resolved",
        "duplicates": "duplicates",
        "numbering_duplicates": "repeated numbers",
        "numbering_gaps": "numbering gaps",
        "numbering_start": "first number",
        "encoding": "encoding",
        "line_endings": "line endings",
        "generator": "generator",
        "generator_native": "platform generator",
        "resave_markers": "re-save marks",
        "platform_markers": "platform marks",
        "title_attrs": "title attributes",
        "hidden_cells": "hidden cells",
        "hidden_nonempty": "hidden cells with content",
        "hidden_rows": "hidden rows",
        "hidden_cost_rows": "hidden cost rows",
        "decimal_comma": "decimal comma",
        "sections": "sections (code)",
        "entries_inconsistent": "inconsistent entries",
        "exits_inconsistent": "inconsistent exits",
        "exits_partial": "partial exits",
        "expected_max": "expected maximum",
        "seen": "seen",
        "out_of_order": "out of order",
        "first_break_row": "first break (row)",
        "first_negative_row": "first negative volume (row)",
        "largest_gap": "largest difference",
        "restarts": "restarts",
        "importer_balance_breaks": "importer balance breaks",
        "identical_rows": "identical rows",
        "initial_balance_implied": "implied initial balance",
        "inversions_open_time": "inversions by open time",
        "inversions_close_time": "inversions by close time",
        "max_backwards_seconds": "largest step back (seconds)",
        "max_backwards_seconds_close": "largest step back at close (seconds)",
        "ticket_inversions": "ticket inversions",
        "time_inversions": "time inversions",
        "order_inversions": "order inversions",
        "last_trade_excluded": "last trade excluded",
        "open_last_trade": "last trade open",
        "levels_cleared": "levels cleared",
        "links_inconsistent": "inconsistent links",
        "links_unresolved": "unresolved links",
        "orders_inconsistent": "inconsistent orders",
        "orders_unresolved": "unresolved orders",
        "orders_missing_for_deals": "deals without an order",
        "orders_single_row": "single-row orders",
        "no_orders_table": "no orders table",
        "max_multiplicity": "largest repetition",
        "values_repeated_3plus": "values repeated three or more times",
        "zero_months": "zero months",
        "year_mismatch": "years with a different total",
        "rounding_grid": "rounded table",
        "last_digit_chi2": "last-digit chi-square",
        "opens_with_deposit": "opens with a deposit",
        "first_row_at": "first row",
        "last_row_at": "last row",
        "positions_before_period": "positions before the period",
        "pre_period_positions": "positions before the period",
        "rows_unparsed": "unreadable rows",
        "rows_without_number": "rows without a number",
        "skipped_first": "first rows skipped",
        "sl_better_fills": "stops filled at a better price",
        "sl_hits": "findings on stops",
        "tp_hits": "findings on take profit",
        "split_at_row": "precision change (row)",
        "split_symbols": "symbols with two precisions",
        "symbols_no_fit": "symbols with no fit",
        "symbols_quote_differs": "symbols with another quote currency",
        "symbols_single_row": "single-row symbols",
        "size_multiplier": "size multiplier",
        "size_value": "size by value",
        "cumulative": "cumulative",
        "etd": "excursion",
        "return_pct": "return in percent",
        "time_examined": "times examined",
        "exit_before_entry": "exits before the entry",
        "pair_shape": "pair shape",
        "pair_values": "pair values",
        "balance_flows_pnl": "balance = flows + result",
        "closed_pnl_summary": "closed result = summary",
        "equity_balance_floating": "equity = balance + floating",
        "free_margin_equity_margin": "free margin = equity − margin",
        "net_profit_gross": "net = gross won − gross lost",
        "profit_factor_gross": "profit factor = gross figures",
        "trades_profit_loss": "trades = winners + losers",
        "trades_short_long": "trades = short + long",
    },
    "pt": {
        "n_rows": "linhas",
        "n_hits": "achados",
        "n_ids": "identificadores",
        "n_deals": "deals",
        "n_orders": "ordens",
        "n_trades": "operações",
        "n_closed": "fechadas",
        "n_open": "abertas",
        "n_positions": "posições",
        "n_symbols": "símbolos",
        "n_symbols_measured": "símbolos medidos",
        "n_accounts": "contas",
        "n_identities": "identidades",
        "n_links": "vínculos",
        "n_tp": "fechamentos por take profit",
        "n_sl": "fechamentos por stop",
        "n_hidden_cells": "células ocultas",
        "n_zero_gross": "resultados brutos zerados",
        "n_zero_move": "movimentos de preço zerados",
        "n_rows_off_mode": "linhas fora da precisão habitual",
        "accounts": "contas",
        "accounts_in_file": "contas no arquivo",
        "after_report_date": "linhas posteriores à data do relatório",
        "report_date": "data do relatório",
        "report_date_source": "origem da data do relatório",
        "max_ahead_seconds": "maior adiantamento (segundos)",
        "backwards_within_1h": "retrocessos de menos de uma hora",
        "close_before_open_over_1h": "fechamentos mais de uma hora antes da abertura",
        "zero_duration": "duração zero",
        "unparseable": "horários ilegíveis",
        "copies_compared": "cópias comparadas",
        "core_hits": "achados em horário central",
        "holiday_hits": "achados em feriados",
        "timestamps_measured": "marcas de tempo medidas",
        "symbols_measured": "símbolos medidos",
        "inferred_offset_minutes": "defasagem de relógio inferida (minutos)",
        "window": "janela de fechamento (código)",
        "deal_gaps": "lacunas entre deals",
        "order_gaps": "lacunas entre ordens",
        "gaps": "lacunas",
        "decimals": "decimais",
        "declared": "valor declarado",
        "measured": "valor medido",
        "what_code": "total comparado (código)",
        "direction": "direção da tabela",
        "direction_rule": "regra de direção",
        "order_key": "chave de ordenação",
        "ties": "empates",
        "ties_fixed": "empates resolvidos",
        "duplicates": "duplicados",
        "numbering_duplicates": "números repetidos",
        "numbering_gaps": "lacunas de numeração",
        "numbering_start": "primeiro número",
        "encoding": "codificação",
        "line_endings": "fim de linha",
        "generator": "gerador",
        "generator_native": "gerador da plataforma",
        "resave_markers": "marcas de novo salvamento",
        "platform_markers": "marcas da plataforma",
        "title_attrs": "atributos de título",
        "hidden_cells": "células ocultas",
        "hidden_nonempty": "células ocultas com conteúdo",
        "hidden_rows": "linhas ocultas",
        "hidden_cost_rows": "linhas de custo ocultas",
        "decimal_comma": "vírgula decimal",
        "sections": "seções (código)",
        "entries_inconsistent": "entradas incoerentes",
        "exits_inconsistent": "saídas incoerentes",
        "exits_partial": "saídas parciais",
        "expected_max": "máximo esperado",
        "seen": "vistos",
        "out_of_order": "fora de ordem",
        "first_break_row": "primeira quebra (linha)",
        "first_negative_row": "primeiro volume negativo (linha)",
        "largest_gap": "maior diferença",
        "restarts": "reinícios",
        "importer_balance_breaks": "quebras de saldo do importador",
        "identical_rows": "linhas idênticas",
        "initial_balance_implied": "saldo inicial implícito",
        "inversions_open_time": "inversões por horário de abertura",
        "inversions_close_time": "inversões por horário de fechamento",
        "max_backwards_seconds": "maior retrocesso (segundos)",
        "max_backwards_seconds_close": "maior retrocesso no fechamento (segundos)",
        "ticket_inversions": "inversões de ticket",
        "time_inversions": "inversões de horário",
        "order_inversions": "inversões de ordem",
        "last_trade_excluded": "última operação excluída",
        "open_last_trade": "última operação aberta",
        "levels_cleared": "níveis superados",
        "links_inconsistent": "vínculos incoerentes",
        "links_unresolved": "vínculos sem resolução",
        "orders_inconsistent": "ordens incoerentes",
        "orders_unresolved": "ordens sem resolução",
        "orders_missing_for_deals": "deals sem ordem",
        "orders_single_row": "ordens de uma só linha",
        "no_orders_table": "sem tabela de ordens",
        "max_multiplicity": "maior repetição",
        "values_repeated_3plus": "valores repetidos três ou mais vezes",
        "zero_months": "meses zerados",
        "year_mismatch": "anos com total diferente",
        "rounding_grid": "tabela arredondada",
        "last_digit_chi2": "qui-quadrado do último dígito",
        "opens_with_deposit": "abre com depósito",
        "first_row_at": "primeira linha",
        "last_row_at": "última linha",
        "positions_before_period": "posições anteriores ao período",
        "pre_period_positions": "posições anteriores ao período",
        "rows_unparsed": "linhas ilegíveis",
        "rows_without_number": "linhas sem número",
        "skipped_first": "primeiras linhas omitidas",
        "sl_better_fills": "stops executados a preço melhor",
        "sl_hits": "achados em stops",
        "tp_hits": "achados em take profit",
        "split_at_row": "mudança de precisão (linha)",
        "split_symbols": "símbolos com duas precisões",
        "symbols_no_fit": "símbolos sem ajuste",
        "symbols_quote_differs": "símbolos com outra moeda de cotação",
        "symbols_single_row": "símbolos de uma só linha",
        "size_multiplier": "multiplicador de tamanho",
        "size_value": "tamanho por valor",
        "cumulative": "acumulado",
        "etd": "excursão",
        "return_pct": "retorno em porcentagem",
        "time_examined": "horários examinados",
        "exit_before_entry": "saídas antes da entrada",
        "pair_shape": "forma dos pares",
        "pair_values": "valores dos pares",
        "balance_flows_pnl": "saldo = fluxos + resultado",
        "closed_pnl_summary": "resultado fechado = resumo",
        "equity_balance_floating": "equity = saldo + flutuante",
        "free_margin_equity_margin": "margem livre = equity − margem",
        "net_profit_gross": "líquido = bruto ganho − bruto perdido",
        "profit_factor_gross": "fator de lucro = brutos",
        "trades_profit_loss": "operações = vencedoras + perdedoras",
        "trades_short_long": "operações = vendidas + compradas",
    },
}

#: Words for the derived suffixes of a figure key.
SUFFIX_WORDS: dict[str, dict[str, str]] = {
    "es": {"_left": "lado izquierdo", "_right": "lado derecho", "_examined": "examinados"},
    "en": {"_left": "left side", "_right": "right side", "_examined": "examined"},
    "pt": {"_left": "lado esquerdo", "_right": "lado direito", "_examined": "examinados"},
}

#: Every copy table, so one test can check the keys of each language.
TABLES: dict[str, dict[str, dict[str, str]]] = {
    "COPY": COPY,
    "STATUS_WORDS": STATUS_WORDS,
    "EVIDENCE_WORDS": EVIDENCE_WORDS,
    "EVIDENCE_HELP": EVIDENCE_HELP,
    "FAMILY_NAMES": FAMILY_NAMES,
    "CHECK_NAMES": CHECK_NAMES,
    "CHECK_FACTS": CHECK_FACTS,
    "REASON_TEXT": REASON_TEXT,
    "FIGURE_LABELS": FIGURE_LABELS,
    "SUFFIX_WORDS": SUFFIX_WORDS,
}

_TRAILING_INDEX = re.compile(r"_\d+$")


def figure_label(key: str, locale: str) -> str:
    """The label of figure ``key``: listed, derived from its base, or the code."""
    labels = FIGURE_LABELS[locale]
    if key in labels:
        return labels[key]
    base = _TRAILING_INDEX.sub("", key)
    if base in labels:
        return labels[base]
    for suffix, word in SUFFIX_WORDS[locale].items():
        if base.endswith(suffix) and base[: -len(suffix)] in labels:
            return f"{labels[base[: -len(suffix)]]} ({word})"
    return base.replace("_", " ")


def fixed_sentences(locale: str) -> list[str]:
    """Every fixed sentence of ``locale``, for the guard tests."""
    texts: list[str] = []
    for table in TABLES.values():
        texts.extend(table[locale].values())
    return texts


__all__ = [
    "CHECK_FACTS",
    "CHECK_NAMES",
    "COPY",
    "EVIDENCE_HELP",
    "EVIDENCE_WORDS",
    "FAMILY_NAMES",
    "FIGURE_LABELS",
    "LOCALES",
    "REASON_TEXT",
    "STATUS_WORDS",
    "SUFFIX_WORDS",
    "TABLES",
    "figure_label",
    "fixed_sentences",
]
