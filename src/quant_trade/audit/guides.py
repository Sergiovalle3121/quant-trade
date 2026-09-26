"""Export guides: how to get, from each supported platform, the file the
audit reads.

One guide per platform, in Spanish, English and Portuguese, written from the format
research in ``docs/research/audit_iteration4/formats_*.json``. Each guide
names the menu path or code, the file it produces, the upload field it goes
in and the gaps the audit will report. The pages are public and indexable;
the test suite runs the profit-claim guard over every one of them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GuideText:
    title: str
    #: One sentence for the index and the page's meta description.
    summary: str
    #: The file the steps produce.
    file: str
    steps: tuple[str, ...]
    #: Where the file goes on the upload form.
    upload: str
    tips: tuple[str, ...]


@dataclass(frozen=True)
class Guide:
    slug: str
    platform: str
    #: The upload field the file goes in: ``report`` or ``optimization``.
    field: str
    text: dict[str, GuideText]
    #: The English path segment when it differs from the Spanish ``slug``.
    slug_en: str | None = None
    #: The English platform name when it differs from ``platform``.
    platform_en: str | None = None
    #: The Portuguese path segment and platform name, when they differ.
    slug_pt: str | None = None
    platform_pt: str | None = None

    def slug_for(self, locale: str) -> str:
        if locale == "pt":
            return self.slug_pt or self.slug
        return self.slug_en if locale == "en" and self.slug_en else self.slug

    def platform_for(self, locale: str) -> str:
        if locale == "pt":
            return self.platform_pt or self.platform
        return self.platform_en if locale == "en" and self.platform_en else self.platform


#: Index and page paths per language. A guide lives at ``<index>/<slug>``.
GUIDES_PATH: dict[str, str] = {"es": "/guias", "en": "/guides", "pt": "/pt/guias"}

GUIDES_COPY: dict[str, dict[str, str]] = {
    "es": {
        "title": "Guías para exportar tu archivo",
        "summary": (
            "Cómo exportar desde MetaTrader 5 y 4, TradingView, NinjaTrader, QuantConnect, "
            "backtesting.py y vectorbt el archivo que lee la auditoría de backtests, sin "
            "convertir nada."
        ),
        "intro": (
            "Sube el archivo tal como lo guarda tu plataforma. Elige la tuya y sigue los pasos."
        ),
        "file": "Qué archivo obtienes",
        "steps": "Pasos",
        "upload": "Dónde subirlo",
        "tips": "Antes de subirlo",
        "all": "Todas las guías",
        "form": "Ir al formulario",
        "back": "Volver al inicio",
    },
    "en": {
        "title": "Guides to export your file",
        "summary": (
            "How to export from MetaTrader 5 and 4, TradingView, NinjaTrader, QuantConnect, "
            "backtesting.py and vectorbt the file the backtest audit reads, with no conversion."
        ),
        "intro": (
            "Upload the file exactly as your platform saves it. Pick yours and follow the steps."
        ),
        "file": "The file you get",
        "steps": "Steps",
        "upload": "Where to upload it",
        "tips": "Before you upload",
        "all": "All guides",
        "form": "Go to the form",
        "back": "Back to the home page",
    },
    "pt": {
        "title": "Guias para exportar o seu arquivo",
        "summary": (
            "Como exportar do MetaTrader 5 e 4, TradingView, NinjaTrader, QuantConnect, "
            "backtesting.py e vectorbt o arquivo que a auditoria de backtests lê, sem converter "
            "nada."
        ),
        "intro": (
            "Envie o arquivo do jeito que a sua plataforma o salva. Escolha a sua e siga os passos."
        ),
        "file": "Que arquivo você obtém",
        "steps": "Passos",
        "upload": "Onde enviar",
        "tips": "Antes de enviar",
        "all": "Todos os guias",
        "form": "Ir ao formulário",
        "back": "Voltar ao início",
    },
}

_BALANCE_ES = (
    "Este archivo no dice con cuánto capital empezaste: escríbelo en «Balance inicial». Sin él "
    "la auditoría supone 10 000 y lo avisa en el informe."
)
_BALANCE_EN = (
    "This file does not say how much capital you started with: type it in 'Starting balance'. "
    "Without it the audit assumes 10,000 and says so in the report."
)
_BALANCE_PT = (
    "Este arquivo não diz com quanto capital você começou: escreva-o em 'Saldo inicial'. Sem "
    "ele a auditoria supõe 10 000 e avisa no relatório."
)
_FLOATING_ES = (
    "El archivo solo trae operaciones cerradas: el drawdown flotante dentro de cada operación "
    "queda como NOT_MEASURED."
)
_FLOATING_EN = (
    "The file only holds closed trades: the floating drawdown inside each trade is reported "
    "as NOT_MEASURED."
)
_FLOATING_PT = (
    "O arquivo só traz operações fechadas: o drawdown flutuante dentro de cada operação fica "
    "como NOT_MEASURED."
)
_OPT_ES = (
    "Si optimizaste parámetros, sube también el XML de optimización de MT5: el número de "
    "intentos deja de ser una declaración y pasa a ser MEASURED."
)
_OPT_EN = (
    "If you optimised parameters, also upload the MT5 optimisation XML: the number of trials "
    "stops being a declaration and becomes MEASURED."
)

_OPT_PT = (
    "Se você otimizou parâmetros, envie também o XML de otimização do MT5: o número de "
    "tentativas deixa de ser uma declaração e passa a ser MEASURED."
)

GUIDES: tuple[Guide, ...] = (
    Guide(
        slug="mt5",
        platform="MetaTrader 5",
        field="report",
        text={
            "es": GuideText(
                title="Cómo exportar el informe de MetaTrader 5",
                summary=(
                    "Guarda el informe HTML del probador de estrategias o del historial de la "
                    "cuenta de MT5 y súbelo tal cual a la auditoría."
                ),
                file=(
                    "Un archivo .html: ReportTester-<cuenta>.html (probador) o "
                    "ReportHistory-<cuenta>.html (historial de la cuenta). MT5 lo guarda en "
                    "UTF-16; no hace falta convertirlo."
                ),
                steps=(
                    "Probador: abre el Probador de estrategias (Ctrl+R) y ejecuta la prueba con "
                    "la configuración que quieres auditar.",
                    "En la pestaña Backtest, haz clic derecho sobre el informe y elige "
                    "Informe > HTML (en versiones antiguas, «Guardar como informe»).",
                    "Historial de una cuenta: abre la Caja de herramientas (Ctrl+T), pestaña "
                    "Historial, elige el periodo completo, clic derecho > Informe > HTML.",
                    "Guarda el archivo. Las imágenes PNG que MT5 guarda al lado no hacen falta.",
                ),
                upload="En el campo «Informe de tu plataforma».",
                tips=(
                    "Elige HTML, no «Open XML (MS Office Excel 2007)»: la auditoría lee el HTML.",
                    "Si el informe está en otro idioma, súbelo igual: las tablas se reconocen "
                    "por su estructura.",
                    "El informe del probador trae el depósito inicial y la comisión de cada "
                    "operación; la auditoría los usa como MEASURED.",
                    _OPT_ES,
                ),
            ),
            "en": GuideText(
                title="How to export the MetaTrader 5 report",
                summary=(
                    "Save the MT5 Strategy Tester or account history HTML report and upload it "
                    "to the audit as it is."
                ),
                file=(
                    "One .html file: ReportTester-<login>.html (tester) or "
                    "ReportHistory-<login>.html (account history). MT5 saves it as UTF-16; there "
                    "is no need to convert it."
                ),
                steps=(
                    "Tester: open the Strategy Tester (Ctrl+R) and run the test with the "
                    "settings you want audited.",
                    "On the Backtest tab, right-click the report and choose Report > HTML "
                    "(older builds: 'Save as Report').",
                    "Account history: open the Toolbox (Ctrl+T), History tab, pick the whole "
                    "period, then right-click > Report > HTML.",
                    "Save the file. The PNG images MT5 writes next to it are not needed.",
                ),
                upload="In the field 'Your platform report'.",
                tips=(
                    "Choose HTML, not 'Open XML (MS Office Excel 2007)': the audit reads the HTML.",
                    "If the report is in another language, upload it anyway: the tables are "
                    "recognised by their structure.",
                    "The tester report carries the initial deposit and each trade's commission; "
                    "the audit uses them as MEASURED.",
                    _OPT_EN,
                ),
            ),
            "pt": GuideText(
                title="Como exportar o relatório do MetaTrader 5",
                summary=(
                    "Salve o relatório HTML do Strategy Tester ou do histórico da conta do "
                    "MT5 e envie para a auditoria como está."
                ),
                file=(
                    "Um arquivo .html: ReportTester-<login>.html (testador) ou "
                    "ReportHistory-<login>.html (histórico da conta). O MT5 o salva em "
                    "UTF-16; não é preciso convertê-lo."
                ),
                steps=(
                    "Testador: abra o Strategy Tester (Ctrl+R) e rode o teste com a "
                    "configuração que você quer auditar.",
                    "Na aba Backtest, clique com o botão direito no relatório e escolha Report "
                    "> HTML (versões antigas: 'Save as Report').",
                    "Histórico da conta: abra a Toolbox (Ctrl+T), aba History, escolha o "
                    "período todo e depois botão direito > Report > HTML.",
                    "Salve o arquivo. As imagens PNG que o MT5 grava ao lado não são necessárias.",
                ),
                upload="No campo 'Relatório da sua plataforma'.",
                tips=(
                    "Escolha HTML, não 'Open XML (MS Office Excel 2007)': a auditoria lê o HTML.",
                    "Se o relatório estiver em outro idioma, envie mesmo assim: as tabelas são "
                    "reconhecidas pela estrutura.",
                    "O relatório do testador traz o depósito inicial e a comissão de cada "
                    "operação; a auditoria os usa como MEASURED.",
                    _OPT_PT,
                ),
            ),
        },
    ),
    Guide(
        slug="cuenta-proveedor",
        slug_en="provider-account",
        platform="Cuenta de un proveedor / Provider's account",
        field="report",
        text={
            "es": GuideText(
                title="Cómo revisar la cuenta de alguien antes de copiarlo o invertir",
                summary=(
                    "Pide al proveedor de la señal, del robot o de la gestión el historial "
                    "completo de su cuenta de MetaTrader y mira el dinero real detrás de su "
                    "porcentaje de ganancia."
                ),
                file=(
                    "El historial de la cuenta de MetaTrader 5 (ReportHistory-<cuenta>.html) o el "
                    "estado de cuenta detallado de MetaTrader 4 (DetailedStatement.htm), con "
                    "todo el periodo, incluidos depósitos y retiros."
                ),
                steps=(
                    "Pide al proveedor el historial completo desde el primer depósito, no solo "
                    "los últimos meses ni una captura de pantalla.",
                    "En MetaTrader 5: Caja de herramientas (Ctrl+T) > Historial > «Todo el "
                    "historial» > clic derecho > Informe > HTML.",
                    "En MetaTrader 4: Terminal > Historial de cuenta > clic derecho > «Todo el "
                    "historial» y luego «Guardar como informe detallado».",
                    "Sube el archivo y abre la sección «El dinero real de la cuenta» del informe.",
                ),
                upload="En el campo «Informe de tu plataforma».",
                tips=(
                    "El porcentaje que muestran los sitios de historiales quita los depósitos: "
                    "el informe lo pone junto al dinero que la cuenta ganó o perdió operando.",
                    "Un depósito grande justo después de una caída, o posiciones abiertas con "
                    "pérdida al imprimir el historial, salen como banderas rojas.",
                    "Pide que el historial se imprima el día que lo recibes: uno impreso hace "
                    "meses no muestra lo que pasó después.",
                    "El informe lee el archivo tal como llega; no lo comprueba con el bróker.",
                    "Si el proveedor solo publica su cuenta en Myfxbook, FX Blue o una señal de "
                    "MQL5, sirve el historial en CSV que exportan esos sitios.",
                ),
            ),
            "en": GuideText(
                title="How to review someone's account before you copy them or invest",
                summary=(
                    "Ask the signal, robot or managed-account provider for the full MetaTrader "
                    "account history and see the real money behind their percentage gain."
                ),
                file=(
                    "The MetaTrader 5 account history (ReportHistory-<login>.html) or the "
                    "MetaTrader 4 detailed statement (DetailedStatement.htm), for the whole "
                    "period, deposits and withdrawals included."
                ),
                steps=(
                    "Ask the provider for the full history since the first deposit, not only the "
                    "last few months or a screenshot.",
                    "In MetaTrader 5: Toolbox (Ctrl+T) > History > 'All history' > right-click > "
                    "Report > HTML.",
                    "In MetaTrader 4: Terminal > Account History > right-click > 'All History', "
                    "then 'Save as Detailed Report'.",
                    "Upload the file and open the report's section 'The account's real money'.",
                ),
                upload="In the field 'Your platform report'.",
                tips=(
                    "The percentage track-record sites show takes deposits out: the report puts "
                    "it next to the money the account made or lost by trading.",
                    "A large deposit right after a fall, or positions open at a loss when the "
                    "history was printed, show up as red flags.",
                    "Ask for the history to be printed the day you receive it: one printed months "
                    "ago does not show what happened since.",
                    "The report reads the file as it arrives; it does not check it with the "
                    "broker.",
                    "If the provider only publishes the account on Myfxbook, FX Blue or an MQL5 "
                    "signal, the CSV history those sites export works too.",
                ),
            ),
            "pt": GuideText(
                title="Como revisar a conta de alguém antes de copiar ou investir",
                summary=(
                    "Peça ao fornecedor do sinal, do robô ou da conta gerida o histórico "
                    "completo da conta de MetaTrader e veja o dinheiro real por trás da "
                    "porcentagem de ganho."
                ),
                file=(
                    "O histórico da conta do MetaTrader 5 (ReportHistory-<login>.html) ou o "
                    "extrato detalhado do MetaTrader 4 (DetailedStatement.htm), do período "
                    "todo, com depósitos e saques incluídos."
                ),
                steps=(
                    "Peça ao fornecedor o histórico completo desde o primeiro depósito, não só "
                    "os últimos meses nem um print.",
                    "No MetaTrader 5: Toolbox (Ctrl+T) > History > 'All history' > botão "
                    "direito > Report > HTML.",
                    "No MetaTrader 4: Terminal > Account History > botão direito > 'All "
                    "History', e depois 'Save as Detailed Report'.",
                    "Envie o arquivo e abra a seção do relatório 'The account's real money' (o "
                    "relatório sai em inglês).",
                ),
                upload="No campo 'Relatório da sua plataforma'.",
                tips=(
                    "A porcentagem que os sites de histórico mostram tira os depósitos: o "
                    "relatório a coloca ao lado do dinheiro que a conta ganhou ou perdeu "
                    "operando.",
                    "Um depósito grande logo depois de uma queda, ou posições abertas no "
                    "prejuízo quando o histórico foi impresso, aparecem como bandeiras "
                    "vermelhas.",
                    "Peça que o histórico seja impresso no dia em que você o recebe: um "
                    "impresso há meses não mostra o que aconteceu depois.",
                    "O relatório lê o arquivo como chega; não o confere com a corretora.",
                    "Se o fornecedor só publica a conta no Myfxbook, FX Blue ou num sinal da "
                    "MQL5, o histórico em CSV que esses sites exportam também serve.",
                ),
            ),
        },
        slug_pt="conta-de-fornecedor",
        platform_pt="Conta de um fornecedor",
    ),
    Guide(
        slug="mt5-optimization",
        platform="MetaTrader 5 (optimización / optimisation)",
        field="optimization",
        text={
            "es": GuideText(
                title="Cómo exportar el XML de optimización de MetaTrader 5",
                summary=(
                    "Exporta los resultados de la optimización de MT5 en XML para que la "
                    "auditoría cuente cuántas configuraciones probaste."
                ),
                file=(
                    "Un archivo .xml de Excel 2003: ReportOptimizer-<cuenta>.xml, con una fila "
                    "por pasada de la optimización."
                ),
                steps=(
                    "Termina la optimización en el Probador de estrategias.",
                    "Abre la pestaña Resultados de optimización.",
                    "Haz clic derecho sobre la tabla y elige Exportar a XML (MS Office Excel).",
                    "Ejecuta después una prueba simple con la configuración elegida y exporta "
                    "su informe HTML (ver la guía de MetaTrader 5).",
                ),
                upload=(
                    "En el campo «Exportación de optimización de MT5» (dentro de «Añadir más "
                    "archivos»), junto con el informe HTML de la configuración elegida en «Informe "
                    "de tu plataforma»."
                ),
                tips=(
                    "Cada fila es un intento. El Sharpe deflactado se calcula con ese número "
                    "real, que queda como MEASURED.",
                    "Exporta la tabla completa, sin filtrar pasadas: quitar filas esconde "
                    "intentos y el resultado deja de ser comparable.",
                    "El XML solo trae un resumen por pasada, sin operaciones: no sustituye al "
                    "informe.",
                ),
            ),
            "en": GuideText(
                title="How to export the MetaTrader 5 optimisation XML",
                summary=(
                    "Export the MT5 optimisation results as XML so the audit counts how many "
                    "configurations you tried."
                ),
                file=(
                    "One Excel 2003 .xml file: ReportOptimizer-<login>.xml, with one row per "
                    "optimisation pass."
                ),
                steps=(
                    "Let the optimisation finish in the Strategy Tester.",
                    "Open the Optimization Results tab.",
                    "Right-click the table and choose Export to XML (MS Office Excel).",
                    "Then run a single test with the chosen settings and export its HTML report "
                    "(see the MetaTrader 5 guide).",
                ),
                upload=(
                    "In the field 'MT5 optimisation export' (under 'Add more files'), together "
                    "with the chosen configuration's HTML report in 'Your platform report'."
                ),
                tips=(
                    "Each row is a trial. The deflated Sharpe uses that real number, reported "
                    "as MEASURED.",
                    "Export the whole table without filtering passes: dropping rows hides "
                    "trials and the result is no longer comparable.",
                    "The XML only holds a summary per pass, with no trades: it does not replace "
                    "the report.",
                ),
            ),
            "pt": GuideText(
                title="Como exportar o XML de otimização do MetaTrader 5",
                summary=(
                    "Exporte os resultados da otimização do MT5 em XML para que a "
                    "auditoria conte quantas configurações você testou."
                ),
                file=(
                    "Um arquivo .xml do Excel 2003: ReportOptimizer-<login>.xml, com uma "
                    "linha por passada da otimização."
                ),
                steps=(
                    "Deixe a otimização terminar no Strategy Tester.",
                    "Abra a aba Optimization Results.",
                    "Clique com o botão direito na tabela e escolha Export to XML (MS Office "
                    "Excel).",
                    "Depois rode um único teste com a configuração escolhida e exporte o "
                    "relatório HTML dele (veja o guia do MetaTrader 5).",
                ),
                upload=(
                    "No campo 'Exportação de otimização do MT5' (em 'Adicionar mais "
                    "arquivos'), junto com o relatório HTML da configuração escolhida em "
                    "'Relatório da sua plataforma'."
                ),
                tips=(
                    "Cada linha é uma tentativa. O Sharpe deflacionado usa esse número real, "
                    "informado como MEASURED.",
                    "Exporte a tabela inteira sem filtrar passadas: tirar linhas esconde "
                    "tentativas e o resultado deixa de ser comparável.",
                    "O XML só tem um resumo por passada, sem operações: não substitui o relatório.",
                ),
            ),
        },
        slug_pt="mt5-otimizacao",
        platform_pt="MetaTrader 5 (otimização)",
    ),
    Guide(
        slug="mt4",
        platform="MetaTrader 4",
        field="report",
        text={
            "es": GuideText(
                title="Cómo exportar el informe de MetaTrader 4",
                summary=(
                    "Guarda el informe del probador de MT4 o el estado de cuenta detallado y "
                    "súbelo tal cual a la auditoría."
                ),
                file=(
                    "Un archivo .htm: StrategyTester.htm (probador) o DetailedStatement.htm "
                    "(estado de cuenta detallado)."
                ),
                steps=(
                    "Probador: ejecuta la prueba en el Probador de estrategias.",
                    "En la pestaña Resultados o Informe, haz clic derecho y elige «Guardar como "
                    "informe».",
                    "Estado de cuenta: en la ventana Terminal, pestaña Historial de cuenta, "
                    "clic derecho > Todo el historial (o un periodo personalizado).",
                    "Clic derecho otra vez > «Guardar como informe detallado».",
                ),
                upload="En el campo «Informe de tu plataforma».",
                tips=(
                    "La imagen .gif que se guarda al lado no hace falta.",
                    "Si exportas solo un periodo del estado de cuenta, el balance inicial sale "
                    "del resumen y queda como DECLARED.",
                    "El probador de MT4 ya resta comisión y swap de cada ganancia pero no los "
                    "desglosa, así que la auditoría no puede medirlos aparte.",
                    _FLOATING_ES,
                ),
            ),
            "en": GuideText(
                title="How to export the MetaTrader 4 report",
                summary=(
                    "Save the MT4 Strategy Tester report or the detailed account statement and "
                    "upload it to the audit as it is."
                ),
                file=(
                    "One .htm file: StrategyTester.htm (tester) or DetailedStatement.htm "
                    "(detailed account statement)."
                ),
                steps=(
                    "Tester: run the test in the Strategy Tester.",
                    "On the Results or Report tab, right-click and choose 'Save as Report'.",
                    "Account statement: in the Terminal window, Account History tab, "
                    "right-click > All History (or a custom period).",
                    "Right-click again > 'Save as Detailed Report'.",
                ),
                upload="In the field 'Your platform report'.",
                tips=(
                    "The .gif image saved next to it is not needed.",
                    "If you export only part of the statement, the initial balance comes from "
                    "the summary and is reported as DECLARED.",
                    "The MT4 tester already deducts commission and swap from each profit but "
                    "does not itemise them, so the audit cannot measure them separately.",
                    _FLOATING_EN,
                ),
            ),
            "pt": GuideText(
                title="Como exportar o relatório do MetaTrader 4",
                summary=(
                    "Salve o relatório do Strategy Tester do MT4 ou o extrato detalhado da "
                    "conta e envie para a auditoria como está."
                ),
                file=(
                    "Um arquivo .htm: StrategyTester.htm (testador) ou DetailedStatement.htm "
                    "(extrato detalhado da conta)."
                ),
                steps=(
                    "Testador: rode o teste no Strategy Tester.",
                    "Na aba Results ou Report, clique com o botão direito e escolha 'Save as "
                    "Report'.",
                    "Extrato da conta: na janela Terminal, aba Account History, botão direito "
                    "> All History (ou um período personalizado).",
                    "Botão direito de novo > 'Save as Detailed Report'.",
                ),
                upload="No campo 'Relatório da sua plataforma'.",
                tips=(
                    "A imagem .gif salva ao lado não é necessária.",
                    "Se você exportar só parte do extrato, o saldo inicial vem do resumo e é "
                    "informado como DECLARED.",
                    "O testador do MT4 já desconta comissão e swap de cada lucro, mas não os "
                    "detalha, então a auditoria não pode medi-los em separado.",
                    _FLOATING_PT,
                ),
            ),
        },
    ),
    Guide(
        slug="tradingview",
        platform="TradingView",
        field="report",
        text={
            "es": GuideText(
                title="Cómo exportar la lista de operaciones de TradingView",
                summary=(
                    "Descarga la lista de operaciones del Probador de estrategias de "
                    "TradingView en CSV o el informe completo en XLSX y súbelo a la auditoría."
                ),
                file=(
                    "Un .csv con la lista de operaciones, o un .xlsx con todas las pestañas del "
                    "informe."
                ),
                steps=(
                    "Abre tu estrategia en el gráfico y el panel Probador de estrategias.",
                    "Ve a la pestaña Lista de operaciones y pulsa el botón de exportar o "
                    "descargar: obtienes el CSV.",
                    "O, desde el menú del informe (nombre de la estrategia o «...»), elige "
                    "Descargar datos como XLSX: obtienes el informe completo.",
                ),
                upload="En el campo «Informe de tu plataforma».",
                tips=(
                    "Solo la pestaña Lista de operaciones trae operaciones; las demás pestañas "
                    "sueltas no sirven.",
                    "El XLSX incluye las propiedades de la estrategia (capital inicial y "
                    "comisión), así que da más datos MEASURED que el CSV.",
                    "Con el CSV, escribe tu capital inicial en «Balance inicial» si la "
                    "auditoría no puede deducirlo.",
                    _FLOATING_ES,
                ),
            ),
            "en": GuideText(
                title="How to export the TradingView list of trades",
                summary=(
                    "Download the TradingView Strategy Tester list of trades as CSV or the full "
                    "report as XLSX and upload it to the audit."
                ),
                file="A .csv with the list of trades, or an .xlsx with every tab of the report.",
                steps=(
                    "Open your strategy on the chart and the Strategy Tester panel.",
                    "Go to the List of trades tab and press the export or download button: you "
                    "get the CSV.",
                    "Or, from the report menu (strategy name or '...'), choose Download data as "
                    "XLSX: you get the full report.",
                ),
                upload="In the field 'Your platform report'.",
                tips=(
                    "Only the List of trades tab holds trades; the other tabs on their own do "
                    "not work.",
                    "The XLSX includes the strategy properties (initial capital and "
                    "commission), so it gives more MEASURED data than the CSV.",
                    "With the CSV, type your initial capital in 'Starting balance' if the audit "
                    "cannot work it out.",
                    _FLOATING_EN,
                ),
            ),
            "pt": GuideText(
                title="Como exportar a lista de operações do TradingView",
                summary=(
                    "Baixe a lista de operações do Strategy Tester do TradingView em CSV "
                    "ou o relatório completo em XLSX e envie para a auditoria."
                ),
                file=(
                    "Um .csv com a lista de operações, ou um .xlsx com todas as abas do relatório."
                ),
                steps=(
                    "Abra a sua estratégia no gráfico e o painel do Strategy Tester.",
                    "Vá à aba List of trades e aperte o botão de exportar ou baixar: você "
                    "obtém o CSV.",
                    "Ou, no menu do relatório (nome da estratégia ou '...'), escolha Download "
                    "data as XLSX: você obtém o relatório completo.",
                ),
                upload="No campo 'Relatório da sua plataforma'.",
                tips=(
                    "Só a aba List of trades tem operações; as outras abas sozinhas não servem.",
                    "O XLSX inclui as propriedades da estratégia (capital inicial e comissão), "
                    "então dá mais dados MEASURED que o CSV.",
                    "Com o CSV, escreva o seu capital inicial em 'Saldo inicial' se a "
                    "auditoria não conseguir deduzi-lo.",
                    _FLOATING_PT,
                ),
            ),
        },
    ),
    Guide(
        slug="ninjatrader",
        platform="NinjaTrader 8",
        field="report",
        text={
            "es": GuideText(
                title="Cómo exportar las operaciones de NinjaTrader 8",
                summary=(
                    "Exporta la tabla de operaciones del Strategy Analyzer de NinjaTrader 8 en "
                    "CSV y súbela a la auditoría."
                ),
                file="Un .csv con una fila por operación (Trade number, Instrument, Market pos.).",
                steps=(
                    "Abre el Strategy Analyzer y selecciona el backtest.",
                    "En la vista, elige Trades.",
                    "Haz clic derecho sobre la tabla > Export... y guarda como CSV.",
                ),
                upload="En el campo «Informe de tu plataforma».",
                tips=(
                    "Da igual si tu Windows usa coma o punto decimal: la auditoría detecta el "
                    "separador.",
                    "Para una cuenta (Account Performance), la pestaña Trades es la mejor. "
                    "También se lee la pestaña Executions de futuros de CME (ES, NQ, CL, GC y "
                    "sus micros): cada operación se calcula con el valor por punto del contrato.",
                    "Un terminal en francés también sirve: se leen sus nombres de columna.",
                    _BALANCE_ES,
                    _FLOATING_ES,
                ),
            ),
            "en": GuideText(
                title="How to export NinjaTrader 8 trades",
                summary=(
                    "Export the NinjaTrader 8 Strategy Analyzer trades grid as CSV and upload it "
                    "to the audit."
                ),
                file="A .csv with one row per trade (Trade number, Instrument, Market pos.).",
                steps=(
                    "Open the Strategy Analyzer and select the backtest.",
                    "In the display, choose Trades.",
                    "Right-click the grid > Export... and save as CSV.",
                ),
                upload="In the field 'Your platform report'.",
                tips=(
                    "It does not matter whether Windows uses a comma or a dot as decimal "
                    "mark: the audit detects the separator.",
                    "For an account (Account Performance), the Trades tab is best. The "
                    "Executions tab of CME futures (ES, NQ, CL, GC and their micros) is read "
                    "too: each trade is priced with the contract's point value.",
                    "A terminal set to French works as well: its column names are read.",
                    _BALANCE_EN,
                    _FLOATING_EN,
                ),
            ),
            "pt": GuideText(
                title="Como exportar as operações do NinjaTrader 8",
                summary=(
                    "Exporte a grade de operações do Strategy Analyzer do NinjaTrader 8 em "
                    "CSV e envie para a auditoria."
                ),
                file="Um .csv com uma linha por operação (Trade number, Instrument, Market pos.).",
                steps=(
                    "Abra o Strategy Analyzer e selecione o backtest.",
                    "Na exibição, escolha Trades.",
                    "Botão direito na grade > Export... e salve como CSV.",
                ),
                upload="No campo 'Relatório da sua plataforma'.",
                tips=(
                    "Não importa se o Windows usa vírgula ou ponto como separador decimal: a "
                    "auditoria detecta o separador.",
                    "Para uma conta (Account Performance), a aba Trades é a melhor. A aba "
                    "Executions dos futuros da CME (ES, NQ, CL, GC e os seus micros) também é "
                    "lida: cada operação é valorizada com o valor do ponto do contrato.",
                    "Um terminal em francês também serve: os nomes das colunas são lidos.",
                    _BALANCE_PT,
                    _FLOATING_PT,
                ),
            ),
        },
    ),
    Guide(
        slug="quantconnect",
        platform="QuantConnect",
        field="report",
        text={
            "es": GuideText(
                title="Cómo exportar las operaciones de QuantConnect",
                summary=(
                    "Descarga el CSV de operaciones de un backtest de QuantConnect y súbelo a "
                    "la auditoría."
                ),
                file="Un .csv llamado <nombre del backtest>_trades.csv, con horas en UTC.",
                steps=(
                    "Abre la página de resultados del backtest en QuantConnect.",
                    "Ve a la pestaña Trades.",
                    "Pulsa Download Trades.",
                ),
                upload="En el campo «Informe de tu plataforma».",
                tips=(
                    "Usa Download Trades, no Download Orders: la auditoría lee las operaciones "
                    "cerradas.",
                    _BALANCE_ES,
                    _FLOATING_ES,
                ),
            ),
            "en": GuideText(
                title="How to export QuantConnect trades",
                summary=(
                    "Download the trades CSV of a QuantConnect backtest and upload it to the audit."
                ),
                file="A .csv named <backtest name>_trades.csv, with times in UTC.",
                steps=(
                    "Open the backtest results page on QuantConnect.",
                    "Go to the Trades tab.",
                    "Press Download Trades.",
                ),
                upload="In the field 'Your platform report'.",
                tips=(
                    "Use Download Trades, not Download Orders: the audit reads closed trades.",
                    _BALANCE_EN,
                    _FLOATING_EN,
                ),
            ),
            "pt": GuideText(
                title="Como exportar as operações do QuantConnect",
                summary=(
                    "Baixe o CSV de operações de um backtest do QuantConnect e envie para "
                    "a auditoria."
                ),
                file="Um .csv chamado <nome do backtest>_trades.csv, com horários em UTC.",
                steps=(
                    "Abra a página de resultados do backtest no QuantConnect.",
                    "Vá à aba Trades.",
                    "Aperte Download Trades.",
                ),
                upload="No campo 'Relatório da sua plataforma'.",
                tips=(
                    "Use Download Trades, não Download Orders: a auditoria lê operações fechadas.",
                    _BALANCE_PT,
                    _FLOATING_PT,
                ),
            ),
        },
    ),
    Guide(
        slug="backtesting-py",
        platform="backtesting.py",
        field="report",
        text={
            "es": GuideText(
                title="Cómo exportar las operaciones de backtesting.py",
                summary=(
                    "Guarda con pandas la tabla de operaciones de backtesting.py en CSV y "
                    "súbela a la auditoría."
                ),
                file=(
                    "Un .csv con las columnas Size, EntryBar, ExitBar, EntryPrice, ExitPrice y PnL."
                ),
                steps=(
                    "Ejecuta el backtest: stats = Backtest(...).run()",
                    "Guarda las operaciones: stats._trades.to_csv('trades.csv')",
                ),
                upload="En el campo «Informe de tu plataforma».",
                tips=(
                    "No cambies los nombres de las columnas: así se reconoce el formato.",
                    "Si tu versión incluye la columna Commission, la auditoría la usa como "
                    "coste MEASURED.",
                    _BALANCE_ES,
                    _FLOATING_ES,
                ),
            ),
            "en": GuideText(
                title="How to export backtesting.py trades",
                summary=(
                    "Save the backtesting.py trades table as CSV with pandas and upload it to "
                    "the audit."
                ),
                file=(
                    "A .csv with the columns Size, EntryBar, ExitBar, EntryPrice, ExitPrice "
                    "and PnL."
                ),
                steps=(
                    "Run the backtest: stats = Backtest(...).run()",
                    "Save the trades: stats._trades.to_csv('trades.csv')",
                ),
                upload="In the field 'Your platform report'.",
                tips=(
                    "Do not rename the columns: that is how the format is recognised.",
                    "If your version includes the Commission column, the audit uses it as a "
                    "MEASURED cost.",
                    _BALANCE_EN,
                    _FLOATING_EN,
                ),
            ),
            "pt": GuideText(
                title="Como exportar as operações do backtesting.py",
                summary=(
                    "Salve a tabela de operações do backtesting.py em CSV com o pandas e "
                    "envie para a auditoria."
                ),
                file="Um .csv com as colunas Size, EntryBar, ExitBar, EntryPrice, ExitPrice e PnL.",
                steps=(
                    "Rode o backtest: stats = Backtest(...).run()",
                    "Salve as operações: stats._trades.to_csv('trades.csv')",
                ),
                upload="No campo 'Relatório da sua plataforma'.",
                tips=(
                    "Não renomeie as colunas: é assim que o formato é reconhecido.",
                    "Se a sua versão incluir a coluna Commission, a auditoria a usa como custo "
                    "MEASURED.",
                    _BALANCE_PT,
                    _FLOATING_PT,
                ),
            ),
        },
    ),
    Guide(
        slug="vectorbt",
        platform="vectorbt",
        field="report",
        text={
            "es": GuideText(
                title="Cómo exportar las operaciones de vectorbt",
                summary=(
                    "Guarda en CSV la tabla legible de operaciones de un Portfolio de vectorbt "
                    "y súbela a la auditoría."
                ),
                file=(
                    "Un .csv con las columnas Column, Size, Avg Entry Price, Avg Exit Price, "
                    "PnL, Direction y Status."
                ),
                steps=(
                    "Construye el Portfolio: pf = vbt.Portfolio.from_signals(...)",
                    "Guarda las operaciones: pf.trades.records_readable.to_csv('trades.csv')",
                ),
                upload="En el campo «Informe de tu plataforma».",
                tips=(
                    "Si el Portfolio tiene varias columnas (variantes de parámetros), solo se "
                    "importa la primera. Exporta la que quieres auditar, por ejemplo "
                    "pf[columna].trades.records_readable.",
                    "Para que cuenten todas las variantes, declara el número de intentos o sube "
                    "la matriz de variantes.",
                    _BALANCE_ES,
                    _FLOATING_ES,
                ),
            ),
            "en": GuideText(
                title="How to export vectorbt trades",
                summary=(
                    "Save the readable trades table of a vectorbt Portfolio as CSV and upload "
                    "it to the audit."
                ),
                file=(
                    "A .csv with the columns Column, Size, Avg Entry Price, Avg Exit Price, PnL, "
                    "Direction and Status."
                ),
                steps=(
                    "Build the Portfolio: pf = vbt.Portfolio.from_signals(...)",
                    "Save the trades: pf.trades.records_readable.to_csv('trades.csv')",
                ),
                upload="In the field 'Your platform report'.",
                tips=(
                    "If the Portfolio has several columns (parameter variants), only the first "
                    "is imported. Export the one you want audited, for example "
                    "pf[column].trades.records_readable.",
                    "For every variant to count, declare the number of trials or upload the "
                    "variants matrix.",
                    _BALANCE_EN,
                    _FLOATING_EN,
                ),
            ),
            "pt": GuideText(
                title="Como exportar as operações do vectorbt",
                summary=(
                    "Salve a tabela legível de operações de um Portfolio do vectorbt em "
                    "CSV e envie para a auditoria."
                ),
                file=(
                    "Um .csv com as colunas Column, Size, Avg Entry Price, Avg Exit Price, "
                    "PnL, Direction e Status."
                ),
                steps=(
                    "Monte o Portfolio: pf = vbt.Portfolio.from_signals(...)",
                    "Salve as operações: pf.trades.records_readable.to_csv('trades.csv')",
                ),
                upload="No campo 'Relatório da sua plataforma'.",
                tips=(
                    "Se o Portfolio tiver várias colunas (variantes de parâmetros), só a "
                    "primeira é importada. Exporte a que você quer auditar, por exemplo "
                    "pf[column].trades.records_readable.",
                    "Para que cada variante conte, declare o número de tentativas ou envie a "
                    "matriz de variantes.",
                    _BALANCE_PT,
                    _FLOATING_PT,
                ),
            ),
        },
    ),
    Guide(
        slug="myfxbook",
        platform="Myfxbook",
        field="report",
        text={
            "es": GuideText(
                title="Cómo exportar el historial de una cuenta de Myfxbook",
                summary=(
                    "Descarga en CSV el historial de una cuenta de Myfxbook y súbelo para ver "
                    "sus operaciones, depósitos y retiros con las mismas pruebas que un backtest."
                ),
                file=(
                    "Un .csv con las columnas Open Date, Close Date, Symbol, Action, Units/Lots, "
                    "Open Price, Close Price, Commission, Swap, Pips y Profit."
                ),
                steps=(
                    "Abre la cuenta en Myfxbook y ve a la pestaña del historial de operaciones.",
                    "Usa la opción de exportar el historial y elige CSV.",
                    "Si la cuenta no es tuya, pide ese CSV a su dueño: Myfxbook deja exportar "
                    "al titular de la cuenta.",
                ),
                upload=(
                    "En «Informe de tu plataforma» para revisar la cuenta sola, o en «Estado de "
                    "cuenta real o demo» (dentro de «Añadir más archivos») junto al backtest del "
                    "robot."
                ),
                tips=(
                    "Los depósitos y retiros del archivo se leen como movimientos de dinero: el "
                    "informe separa lo que hizo la operativa de lo que se ingresó o retiró.",
                    "Las operaciones que siguen abiertas al final del archivo no se cuentan.",
                    "El archivo no dice la zona horaria: las horas se leen tal cual.",
                    _FLOATING_ES,
                ),
            ),
            "en": GuideText(
                title="How to export a Myfxbook account's history",
                summary=(
                    "Download a Myfxbook account's history as CSV and upload it to see its "
                    "trades, deposits and withdrawals under the same tests as a backtest."
                ),
                file=(
                    "A .csv with the columns Open Date, Close Date, Symbol, Action, Units/Lots, "
                    "Open Price, Close Price, Commission, Swap, Pips and Profit."
                ),
                steps=(
                    "Open the account on Myfxbook and go to its trading history tab.",
                    "Use the option to export the history and pick CSV.",
                    "If the account is not yours, ask its owner for that CSV: Myfxbook lets the "
                    "account holder export it.",
                ),
                upload=(
                    "In 'Your platform report' to review the account on its own, or in 'Live or "
                    "demo account statement' (under 'Add more files') next to the robot's "
                    "backtest."
                ),
                tips=(
                    "The file's deposits and withdrawals are read as money movements: the "
                    "report separates what the trading did from what was paid in or out.",
                    "Trades still open at the end of the file are not counted.",
                    "The file states no time zone: times are read as they are.",
                    _FLOATING_EN,
                ),
            ),
            "pt": GuideText(
                title="Como exportar o histórico de uma conta do Myfxbook",
                summary=(
                    "Baixe o histórico de uma conta do Myfxbook em CSV e envie para ver as "
                    "operações, depósitos e saques dela sob os mesmos testes de um "
                    "backtest."
                ),
                file=(
                    "Um .csv com as colunas Open Date, Close Date, Symbol, Action, "
                    "Units/Lots, Open Price, Close Price, Commission, Swap, Pips e Profit."
                ),
                steps=(
                    "Abra a conta no Myfxbook e vá à aba do histórico de operações.",
                    "Use a opção de exportar o histórico e escolha CSV.",
                    "Se a conta não for sua, peça esse CSV ao titular: o Myfxbook permite que "
                    "o titular da conta o exporte.",
                ),
                upload=(
                    "Em 'Relatório da sua plataforma' para revisar a conta sozinha, ou em "
                    "'Extrato da conta real ou demo' (em 'Adicionar mais arquivos') ao lado "
                    "do backtest do robô."
                ),
                tips=(
                    "Os depósitos e saques do arquivo são lidos como movimentos de dinheiro: o "
                    "relatório separa o que as operações fizeram do que entrou ou saiu.",
                    "Operações ainda abertas no final do arquivo não são contadas.",
                    "O arquivo não informa fuso horário: os horários são lidos como estão.",
                    _FLOATING_PT,
                ),
            ),
        },
    ),
    Guide(
        slug="mql5-signal",
        platform="MQL5 Signals",
        field="report",
        text={
            "es": GuideText(
                title="Cómo exportar el historial de una señal de MQL5",
                summary=(
                    "Descarga en CSV el historial de una señal de MQL5.com y súbelo para revisar "
                    "la cuenta antes de copiarla."
                ),
                file=(
                    "Un .csv separado por punto y coma con las columnas Time, Type, Volume, "
                    "Symbol, Price, Time, Price, Commission, Swap y Profit."
                ),
                steps=(
                    "Abre la página de la señal en mql5.com e inicia sesión.",
                    "En la pestaña del historial de operaciones, usa la opción de exportar a CSV.",
                ),
                upload=(
                    "En «Informe de tu plataforma» para revisar la señal sola, o en «Estado de "
                    "cuenta real o demo» (dentro de «Añadir más archivos») junto al backtest del "
                    "robot."
                ),
                tips=(
                    "Las filas Balance (depósitos, retiros y ajustes) se leen como movimientos "
                    "de dinero, no como operaciones.",
                    "Las órdenes pendientes canceladas no se cuentan.",
                    _FLOATING_ES,
                ),
            ),
            "en": GuideText(
                title="How to export an MQL5 signal's history",
                summary=(
                    "Download an MQL5.com signal's history as CSV and upload it to review the "
                    "account before copying it."
                ),
                file=(
                    "A semicolon-separated .csv with the columns Time, Type, Volume, Symbol, "
                    "Price, Time, Price, Commission, Swap and Profit."
                ),
                steps=(
                    "Open the signal's page on mql5.com and log in.",
                    "In its trading history tab, use the option to export to CSV.",
                ),
                upload=(
                    "In 'Your platform report' to review the signal on its own, or in 'Live or "
                    "demo account statement' (under 'Add more files') next to the robot's "
                    "backtest."
                ),
                tips=(
                    "Balance rows (deposits, withdrawals and adjustments) are read as money "
                    "movements, not as trades.",
                    "Cancelled pending orders are not counted.",
                    _FLOATING_EN,
                ),
            ),
            "pt": GuideText(
                title="Como exportar o histórico de um sinal da MQL5",
                summary=(
                    "Baixe o histórico de um sinal do MQL5.com em CSV e envie para revisar "
                    "a conta antes de copiá-la."
                ),
                file=(
                    "Um .csv separado por ponto e vírgula com as colunas Time, Type, Volume, "
                    "Symbol, Price, Time, Price, Commission, Swap e Profit."
                ),
                steps=(
                    "Abra a página do sinal no mql5.com e entre com a sua conta.",
                    "Na aba do histórico de operações, use a opção de exportar para CSV.",
                ),
                upload=(
                    "Em 'Relatório da sua plataforma' para revisar o sinal sozinho, ou em "
                    "'Extrato da conta real ou demo' (em 'Adicionar mais arquivos') ao lado "
                    "do backtest do robô."
                ),
                tips=(
                    "As linhas de saldo (depósitos, saques e ajustes) são lidas como "
                    "movimentos de dinheiro, não como operações.",
                    "Ordens pendentes canceladas não são contadas.",
                    _FLOATING_PT,
                ),
            ),
        },
        slug_pt="sinal-mql5",
        platform_pt="Sinais da MQL5",
    ),
    Guide(
        slug="fxblue",
        platform="FX Blue",
        field="report",
        text={
            "es": GuideText(
                title="Cómo exportar las operaciones de una cuenta de FX Blue",
                summary=(
                    "Descarga en CSV las órdenes de una cuenta de FX Blue y súbelas para revisar "
                    "sus operaciones y sus depósitos."
                ),
                file=(
                    "Un .csv con las columnas Type, Ticket, Symbol, Lots, Buy/sell, Open price, "
                    "Close price, Open time, Close time, Profit, Swap, Commission y Net profit."
                ),
                steps=(
                    "Abre el estado de la cuenta en FX Blue.",
                    "Usa la opción de exportar las órdenes a CSV.",
                ),
                upload=(
                    "En «Informe de tu plataforma» para revisar la cuenta sola, o en «Estado de "
                    "cuenta real o demo» (dentro de «Añadir más archivos») junto al backtest del "
                    "robot."
                ),
                tips=(
                    "Se leen las filas Closed position; las posiciones abiertas y las órdenes "
                    "pendientes no se cuentan.",
                    "Si el archivo trae varias cuentas, se lee la que tiene más operaciones "
                    "cerradas y el informe lo avisa. Exporta una cuenta por archivo.",
                    _FLOATING_ES,
                ),
            ),
            "en": GuideText(
                title="How to export an FX Blue account's trades",
                summary=(
                    "Download an FX Blue account's orders as CSV and upload them to review its "
                    "trades and deposits."
                ),
                file=(
                    "A .csv with the columns Type, Ticket, Symbol, Lots, Buy/sell, Open price, "
                    "Close price, Open time, Close time, Profit, Swap, Commission and Net profit."
                ),
                steps=(
                    "Open the account's statement on FX Blue.",
                    "Use the option to export the orders to CSV.",
                ),
                upload=(
                    "In 'Your platform report' to review the account on its own, or in 'Live or "
                    "demo account statement' (under 'Add more files') next to the robot's "
                    "backtest."
                ),
                tips=(
                    "Closed position rows are read; open positions and pending orders are not "
                    "counted.",
                    "If the file holds several accounts, the one with the most closed trades is "
                    "read and the report says so. Export one account per file.",
                    _FLOATING_EN,
                ),
            ),
            "pt": GuideText(
                title="Como exportar as operações de uma conta do FX Blue",
                summary=(
                    "Baixe as ordens de uma conta do FX Blue em CSV e envie para revisar "
                    "as operações e os depósitos."
                ),
                file=(
                    "Um .csv com as colunas Type, Ticket, Symbol, Lots, Buy/sell, Open price, "
                    "Close price, Open time, Close time, Profit, Swap, Commission e Net "
                    "profit."
                ),
                steps=(
                    "Abra o extrato da conta no FX Blue.",
                    "Use a opção de exportar as ordens para CSV.",
                ),
                upload=(
                    "Em 'Relatório da sua plataforma' para revisar a conta sozinha, ou em "
                    "'Extrato da conta real ou demo' (em 'Adicionar mais arquivos') ao lado "
                    "do backtest do robô."
                ),
                tips=(
                    "São lidas as linhas de posições fechadas; posições abertas e ordens "
                    "pendentes não são contadas.",
                    "Se o arquivo tiver várias contas, é lida a que tem mais operações "
                    "fechadas e o relatório diz isso. Exporte uma conta por arquivo.",
                    _FLOATING_PT,
                ),
            ),
        },
    ),
    Guide(
        slug="robinhood",
        platform="Robinhood",
        field="report",
        text={
            "es": GuideText(
                title="Cómo exportar tus operaciones de Robinhood",
                summary=(
                    "Genera el informe Account Activity de Robinhood en CSV y súbelo para revisar "
                    "tus operaciones con acciones y opciones."
                ),
                file=(
                    "Un .csv con las columnas Activity Date, Process Date, Settle Date, "
                    "Instrument, Description, Trans Code, Quantity, Price y Amount."
                ),
                steps=(
                    "En Robinhood, abre tu cuenta, entra en Reports and statements y elige "
                    "Account activity report.",
                    "Pulsa Generate new report, elige la cuenta y el periodo completo (desde tu "
                    "primera compra) y pulsa Generate report.",
                    "Robinhood avisa cuando está listo (suele tardar unas 2 horas, hasta 24); "
                    "descárgalo desde Reports.",
                ),
                upload="En el campo «Informe de tu plataforma», tal cual.",
                tips=(
                    "Las opciones cuentan 100 acciones por contrato; una opción que vence, se "
                    "asigna o se ejerce cierra sin prima.",
                    "Los depósitos, dividendos, intereses y comisiones no son operaciones y no "
                    "se cuentan como tales.",
                    "Las ventas de acciones compradas antes de la primera fecha del archivo, o "
                    "traspasadas desde otro bróker, quedan fuera y el informe lo dice: elige el "
                    "periodo desde tu primera compra.",
                    "El informe no incluye futuros ni cripto de Robinhood.",
                ),
            ),
            "en": GuideText(
                title="How to export your Robinhood trades",
                summary=(
                    "Generate Robinhood's Account Activity report as CSV and upload it to review "
                    "your stock and option trades."
                ),
                file=(
                    "A .csv with the columns Activity Date, Process Date, Settle Date, "
                    "Instrument, Description, Trans Code, Quantity, Price and Amount."
                ),
                steps=(
                    "In Robinhood, open your account, go to Reports and statements and choose "
                    "Account activity report.",
                    "Select Generate new report, pick the account and the whole period (from "
                    "your first purchase) and select Generate report.",
                    "Robinhood tells you when it is ready (usually about 2 hours, up to 24); "
                    "download it from Reports.",
                ),
                upload="In the field 'Your platform report', as it is.",
                tips=(
                    "Options count 100 shares a contract; an option that expires, is assigned "
                    "or is exercised closes at no premium.",
                    "Deposits, dividends, interest and fees are not trades and are not counted "
                    "as such.",
                    "Sales of shares bought before the file's first date, or transferred in "
                    "from another broker, are left out and the report says so: pick the period "
                    "from your first purchase.",
                    "The report does not include Robinhood futures or crypto.",
                ),
            ),
            "pt": GuideText(
                title="Como exportar suas operações da Robinhood",
                summary=(
                    "Gere o relatório Account Activity da Robinhood em CSV e envie para revisar "
                    "suas operações com ações e opções."
                ),
                file=(
                    "Um .csv com as colunas Activity Date, Process Date, Settle Date, "
                    "Instrument, Description, Trans Code, Quantity, Price e Amount."
                ),
                steps=(
                    "Na Robinhood, abra sua conta, entre em Reports and statements e escolha "
                    "Account activity report.",
                    "Toque em Generate new report, escolha a conta e o período completo (desde "
                    "sua primeira compra) e toque em Generate report.",
                    "A Robinhood avisa quando estiver pronto (costuma levar umas 2 horas, até "
                    "24); baixe em Reports.",
                ),
                upload="No campo 'Relatório da sua plataforma', do jeito que vier.",
                tips=(
                    "As opções contam 100 ações por contrato; uma opção que vence, é exercida "
                    "ou atribuída fecha sem prêmio.",
                    "Depósitos, dividendos, juros e tarifas não são operações e não são "
                    "contados como tal.",
                    "Vendas de ações compradas antes da primeira data do arquivo, ou "
                    "transferidas de outra corretora, ficam de fora e o relatório diz isso: "
                    "escolha o período desde sua primeira compra.",
                    "O relatório não inclui futuros nem cripto da Robinhood.",
                ),
            ),
        },
    ),
    Guide(
        slug="csv-universal",
        slug_en="universal-csv",
        platform="Otra plataforma (CSV o Excel)",
        platform_en="Any other platform (CSV or Excel)",
        field="report",
        text={
            "es": GuideText(
                title="Cómo subir las operaciones de cualquier plataforma",
                summary=(
                    "Interactive Brokers, DEGIRO, Trading 212, XTB, eToro, Binance, KuCoin o "
                    "cualquier otro bróker, exchange o diario de trading: exporta su historial "
                    "de operaciones en CSV o Excel y súbelo; las columnas se reconocen por su "
                    "nombre."
                ),
                file=(
                    "Un .csv o .xlsx con una fila por operación cerrada (fecha de entrada y de "
                    "salida, cantidad, precio de entrada y de salida) o una fila por ejecución "
                    "(fecha, compra o venta, cantidad y precio)."
                ),
                steps=(
                    "En tu plataforma, busca el historial de operaciones, de órdenes ejecutadas "
                    "o de transacciones (Trade history, Order history, Fills o Executions).",
                    "Elige el periodo completo que quieres revisar y expórtalo en CSV o Excel.",
                    "Súbelo tal cual: no hace falta cambiar nada si las columnas tienen nombres "
                    "habituales en español, inglés, portugués, francés, alemán o italiano.",
                ),
                upload="En el campo «Informe de tu plataforma».",
                tips=(
                    "Reconoce las columnas de: Interactive Brokers (Flex Query de Trades o el "
                    "Activity Statement en CSV), Tradovate (Performance u Orders), TopstepX y "
                    "otras cuentas de ProjectX (Trades), TradeStation, thinkorswim (Account "
                    "Statement), Charles Schwab (Transactions o Realized Gain/Loss), Fidelity, "
                    "E*TRADE, Webull, Robinhood (informe Account Activity; las opciones a 100 "
                    "acciones por contrato), tastytrade, eToro (posiciones cerradas), XTB "
                    "(xStation 5, historial de posiciones cerradas), DEGIRO (Transacciones, en "
                    "cualquier idioma), Trading 212 (historial), Revolut (estado de cuenta de "
                    "acciones), Zerodha (Tradebook de Console, en CSV), cTrader (History), "
                    "Rithmic "
                    "(Completed Orders), Sierra Chart (Trade Activity Log), Binance, Kraken, "
                    "Coinbase y KuCoin (historial de ejecuciones).",
                    "Los costes de DEGIRO vienen en euros y se restan tal cual, también en "
                    "acciones que cotizan en otra moneda; el resultado de Trading 212 viene en "
                    "la moneda de tu cuenta y se usa como tal.",
                    "Con una fila por ejecución, las compras y ventas se emparejan por símbolo "
                    "en orden de llegada (FIFO); las posiciones que siguen abiertas al final "
                    "quedan fuera y el informe lo dice.",
                    "Si hay columna de resultado, se usa para el valor por punto de cada "
                    "contrato. Sin ella, los futuros de CME con código de contrato (ESZ6, "
                    "MNQ DEC26) usan su valor por punto oficial; para otros futuros u opciones "
                    "conviene una columna Multiplicador.",
                    "Las comisiones cobradas en otra moneda (por ejemplo BNB en un par USDT) "
                    "quedan fuera de los costes y el informe lo avisa.",
                    "En el informe verás qué columna se leyó como qué. Si alguna no se "
                    "reconoce, indícala en «¿Tu plataforma no aparece o su archivo da error? "
                    "Indica sus columnas», justo debajo del campo del informe.",
                    _BALANCE_ES,
                    _FLOATING_ES,
                ),
            ),
            "en": GuideText(
                title="How to upload the trades of any platform",
                summary=(
                    "Interactive Brokers, DEGIRO, Trading 212, XTB, eToro, Binance, KuCoin or "
                    "any other broker, exchange or trading journal: export its trade history "
                    "as CSV or Excel and upload it; the columns are recognised by their "
                    "names."
                ),
                file=(
                    "A .csv or .xlsx with one row per closed trade (entry and exit time, "
                    "quantity, entry and exit price) or one row per fill (time, buy or sell, "
                    "quantity and price)."
                ),
                steps=(
                    "On your platform, find the trade, filled order or transaction history "
                    "(Trade history, Order history, Fills or Executions).",
                    "Pick the full period you want reviewed and export it as CSV or Excel.",
                    "Upload it as it is: nothing needs changing when the columns carry common "
                    "names in English, Spanish, Portuguese, French, German or Italian.",
                ),
                upload="In the field 'Your platform report'.",
                tips=(
                    "It recognises the columns of: Interactive Brokers (a Trades Flex Query or "
                    "the Activity Statement as CSV), Tradovate (Performance or Orders), "
                    "TopstepX and other ProjectX accounts (Trades), TradeStation, thinkorswim "
                    "(Account Statement), Charles Schwab (Transactions or Realized Gain/Loss), "
                    "Fidelity, E*TRADE, Webull, Robinhood (Account Activity report; options at "
                    "100 shares a contract), tastytrade, eToro (closed positions), XTB "
                    "(xStation 5 closed position history), DEGIRO (Transactions, in any "
                    "language), Trading 212 (history), Revolut (stocks account statement), "
                    "Zerodha (Console Tradebook, as CSV), cTrader (History), Rithmic (Completed "
                    "Orders), Sierra Chart (Trade Activity Log), Binance, Kraken, Coinbase and "
                    "KuCoin (filled orders history).",
                    "DEGIRO's costs come in euros and are subtracted as they are, also on "
                    "shares quoted in another currency; Trading 212's result comes in your "
                    "account currency and is used as such.",
                    "With one row per fill, buys and sells are paired per symbol first in, "
                    "first out; positions still open at the end are left out and the report "
                    "says so.",
                    "A profit column, when there is one, gives each contract's value per "
                    "point. Without it, CME futures with a contract code (ESZ6, MNQ DEC26) use "
                    "their official point value; other futures or options need a Multiplier "
                    "column.",
                    "Fees charged in another coin (BNB on a USDT pair, for example) are left "
                    "out of the costs and the report says so.",
                    "The report shows which column was read as what. If one is not "
                    "recognised, name it under 'Platform not listed, or its file fails? Name "
                    "its columns', right below the report field.",
                    _BALANCE_EN,
                    _FLOATING_EN,
                ),
            ),
            "pt": GuideText(
                title="Como enviar as operações de qualquer plataforma",
                summary=(
                    "Interactive Brokers, DEGIRO, Trading 212, XTB, eToro, Binance, KuCoin "
                    "ou qualquer outra corretora, exchange ou diário de trading: exporte o "
                    "histórico de operações em CSV ou Excel e envie; as colunas são "
                    "reconhecidas pelo nome."
                ),
                file=(
                    "Um .csv ou .xlsx com uma linha por operação fechada (hora de entrada e "
                    "de saída, quantidade, preço de entrada e de saída) ou uma linha por "
                    "execução (hora, compra ou venda, quantidade e preço)."
                ),
                steps=(
                    "Na sua plataforma, procure o histórico de operações, de ordens executadas "
                    "ou de transações (Trade history, Order history, Fills ou Executions).",
                    "Escolha o período completo que você quer revisar e exporte em CSV ou Excel.",
                    "Envie como está: não é preciso mudar nada quando as colunas têm nomes "
                    "comuns em português, inglês, espanhol, francês, alemão ou italiano.",
                ),
                upload="No campo 'Relatório da sua plataforma'.",
                tips=(
                    "Reconhece as colunas de: Interactive Brokers (uma Flex Query de Trades ou "
                    "o Activity Statement em CSV), Tradovate (Performance ou Orders), TopstepX "
                    "e outras contas ProjectX (Trades), TradeStation, thinkorswim (Account "
                    "Statement), Charles Schwab (Transactions ou Realized Gain/Loss), "
                    "Fidelity, E*TRADE, Webull, Robinhood (relatório Account Activity; as opções a "
                    "100 ações por contrato), tastytrade, eToro (posições fechadas), XTB "
                    "(histórico de posições fechadas do xStation 5), DEGIRO (Transações, em "
                    "qualquer idioma), Trading 212 (histórico), Revolut (extrato da conta de "
                    "ações), Zerodha (Tradebook do Console, em CSV), cTrader (History), "
                    "Rithmic "
                    "(Completed Orders), Sierra Chart (Trade Activity Log), Binance, Kraken, "
                    "Coinbase e KuCoin (histórico de ordens executadas).",
                    "Os custos da DEGIRO vêm em euros e são descontados como estão, também em "
                    "ações cotadas em outra moeda; o resultado da Trading 212 vem na moeda da "
                    "sua conta e é usado assim.",
                    "Com uma linha por execução, compras e vendas são pareadas por símbolo na "
                    "ordem de chegada (primeiro a entrar, primeiro a sair); as posições ainda "
                    "abertas no final ficam de fora e o relatório diz isso.",
                    "Uma coluna de lucro, quando existe, dá o valor por ponto de cada "
                    "contrato. Sem ela, os futuros da CME com código de contrato (ESZ6, MNQ "
                    "DEC26) usam o valor oficial do ponto; outros futuros ou opções precisam "
                    "de uma coluna Multiplier.",
                    "Taxas cobradas em outra moeda (BNB num par em USDT, por exemplo) ficam "
                    "fora dos custos e o relatório diz isso.",
                    "O relatório mostra qual coluna foi lida como o quê. Se uma não for "
                    "reconhecida, indique-a em 'A sua plataforma não aparece ou o arquivo dá "
                    "erro? Indique as colunas', logo abaixo do campo do relatório.",
                    _BALANCE_PT,
                    _FLOATING_PT,
                ),
            ),
        },
        platform_pt="Outra plataforma (CSV ou Excel)",
    ),
)

GUIDES_BY_SLUG: dict[str, Guide] = {guide.slug: guide for guide in GUIDES}
#: Guides by their path segment in each language.
GUIDES_BY_PATH: dict[str, dict[str, Guide]] = {
    locale: {guide.slug_for(locale): guide for guide in GUIDES} for locale in ("es", "en", "pt")
}

#: Guides for the upload form's platform-report field, in display order.
REPORT_GUIDES: tuple[Guide, ...] = tuple(guide for guide in GUIDES if guide.field == "report")


def guides_index_url(locale: str) -> str:
    return GUIDES_PATH.get(locale, GUIDES_PATH["es"])


def guide_url(slug: str, locale: str) -> str:
    """The guide's path in ``locale``; ``slug`` is its Spanish slug."""
    guide = GUIDES_BY_SLUG.get(slug)
    return f"{guides_index_url(locale)}/{guide.slug_for(locale) if guide else slug}"


__all__ = [
    "GUIDES",
    "GUIDES_BY_PATH",
    "GUIDES_BY_SLUG",
    "GUIDES_COPY",
    "GUIDES_PATH",
    "REPORT_GUIDES",
    "Guide",
    "GuideText",
    "guide_url",
    "guides_index_url",
]
