"""Export guides: how to get, from each supported platform, the file the
audit reads.

One guide per platform, in Spanish and English, written from the format
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

    def slug_for(self, locale: str) -> str:
        return self.slug_en if locale == "en" and self.slug_en else self.slug

    def platform_for(self, locale: str) -> str:
        return self.platform_en if locale == "en" and self.platform_en else self.platform


#: Index and page paths per language. A guide lives at ``<index>/<slug>``.
GUIDES_PATH: dict[str, str] = {"es": "/guias", "en": "/guides"}

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
}

_BALANCE_ES = (
    "Este archivo no dice con cuánto capital empezaste: escríbelo en «Balance inicial». Sin él "
    "la auditoría supone 10 000 y lo avisa en el informe."
)
_BALANCE_EN = (
    "This file does not say how much capital you started with: type it in 'Starting balance'. "
    "Without it the audit assumes 10,000 and says so in the report."
)
_FLOATING_ES = (
    "El archivo solo trae operaciones cerradas: el drawdown flotante dentro de cada operación "
    "queda como NOT_MEASURED."
)
_FLOATING_EN = (
    "The file only holds closed trades: the floating drawdown inside each trade is reported "
    "as NOT_MEASURED."
)
_OPT_ES = (
    "Si optimizaste parámetros, sube también el XML de optimización de MT5: el número de "
    "intentos deja de ser una declaración y pasa a ser MEASURED."
)
_OPT_EN = (
    "If you optimised parameters, also upload the MT5 optimisation XML: the number of trials "
    "stops being a declaration and becomes MEASURED."
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
        },
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
        },
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
        },
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
                    "Si tu bróker, exchange o diario de trading no está en la lista, exporta su "
                    "historial de operaciones en CSV o Excel y súbelo: las columnas se "
                    "reconocen por su nombre."
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
                    "E*TRADE, Webull, tastytrade, eToro (posiciones cerradas), XTB (xStation 5, "
                    "historial de posiciones cerradas), DEGIRO (Transacciones, en cualquier "
                    "idioma), Trading 212 (historial), cTrader, Sierra Chart (Trade Activity "
                    "Log), Binance, Kraken, Coinbase y KuCoin (historial de ejecuciones).",
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
                    "If your broker, exchange or trading journal is not listed, export its "
                    "trade history as CSV or Excel and upload it: the columns are recognised "
                    "by their names."
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
                    "Fidelity, E*TRADE, Webull, tastytrade, eToro (closed positions), XTB "
                    "(xStation 5 closed position history), DEGIRO (Transactions, in any "
                    "language), Trading 212 (history), cTrader, Sierra Chart (Trade Activity "
                    "Log), Binance, Kraken, Coinbase and KuCoin (filled orders history).",
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
        },
    ),
)

GUIDES_BY_SLUG: dict[str, Guide] = {guide.slug: guide for guide in GUIDES}
#: Guides by their path segment in each language.
GUIDES_BY_PATH: dict[str, dict[str, Guide]] = {
    locale: {guide.slug_for(locale): guide for guide in GUIDES} for locale in ("es", "en")
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
