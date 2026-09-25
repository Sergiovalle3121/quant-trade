"""Spanish for the English sentences the audit writes into a result.

The engine, the importers and the red-flag checks write their notes in
English, and the result JSON keeps them that way: it is the evidence record
and its hash must not depend on the reader's language. A Spanish page
translates them when it is rendered, with the fixed templates below.

Each rule is an English template with ``{name}`` placeholders, as the
sentence appears in the source, and its Spanish twin. The placeholders catch
the numbers and names the sentence carries (counts, symbols, file labels),
which are copied unchanged. A sentence no rule knows is shown in English:
a new warning degrades to English, never to an empty cell. The tests run
every importer fixture and scenario through ``untranslated`` so a new
English sentence without a rule fails the build.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from quant_trade.audit.verdict import NOT_MEASURED_ES

#: Where a parse warning came from, as ``schema.build_inputs`` prefixes it.
_PREFIXES: dict[str, str] = {
    "report": "informe",
    "equity": "curva de equity",
    "trades": "operaciones",
    "benchmark": "benchmark",
    "optimization": "optimización",
    "live": "cuenta real",
}

#: Labels the importers put in front of a totals mismatch (``_compare``).
_COMPARED: dict[str, str] = {
    "closing deals vs Total Trades": "operaciones de cierre frente a Total Trades",
    "net profit": "resultado neto",
    "net profit of closed positions": "resultado neto de las posiciones cerradas",
    "close rows vs Total trades": "filas de cierre frente a Total trades",
    "closed trade P/L": "P/L de las operaciones cerradas",
    "balance drawdown maximal": "caída máxima del balance (Balance Drawdown Maximal)",
    "cumulative P&L": "P&L acumulado",
    "Cum. net profit": "Cum. net profit",
}

#: Where an importer took the starting balance from (``_Draft.initial_note``).
_INITIAL_SOURCES: dict[str, str] = {
    "Initial Deposit": "Initial Deposit (depósito inicial del informe)",
    "Initial deposit": "Initial deposit (depósito inicial del informe)",
    "first Balance row minus its own amount": "la primera fila de Balance menos su propio importe",
    "summary Balance minus Deposit/Withdrawal minus Closed Trade P/L": (
        "el Balance del resumen menos Deposit/Withdrawal menos Closed Trade P/L"
    ),
    "the cumulative P&L and cumulative P&L % columns": (
        "las columnas de P&L acumulado y P&L acumulado %"
    ),
    "Properties: Initial capital": "Propiedades: Initial capital (capital inicial)",
}

#: Where the number of trials comes from (``engine._trials_used``).
_TRIAL_SOURCES: dict[str, str] = {
    "not declared; computed with 1, the most favourable case": (
        "sin declarar; se calcula con 1, el caso más favorable"
    ),
    "not declared; 1 assumed": "sin declarar; se calcula con 1, el caso más favorable",
    "declared by the client": "declarado por el cliente",
    "passes in the MT5 optimisation export": "pasadas de la exportación de optimización de MT5",
    "columns of the uploaded variants matrix": "columnas de la matriz de variantes subida",
    "parameter variants in the uploaded report": "variantes de parámetros del informe subido",
}

_RULES_SOURCE: tuple[tuple[str, str], ...] = (
    # --- Parse warnings: equity, trades and benchmark CSV (schema.py) ---
    ("both {a} and {b} present; using {c}", "hay columnas {a} y {b}; se usa {c}"),
    (
        "returns were percent-formatted; divided by 100",
        "los retornos venían en %; se dividieron entre 100",
    ),
    (
        "returns look like percentages (median |r| > 0.5); divided by 100",
        "los retornos parecen porcentajes (mediana |r| > 0.5); se dividieron entre 100",
    ),
    (
        "{n} row(s) with an unreadable timestamp or value dropped",
        "se descartaron {n} fila(s) con fecha o valor ilegible",
    ),
    (
        "{n} future period(s) with no change dropped (they have not happened yet)",
        "se descartaron {n} periodo(s) futuros sin cambio (todavía no han ocurrido)",
    ),
    (
        "no side column; every trade treated as long",
        "no hay columna de lado; cada operación se trata como larga",
    ),
    (
        "{n} trade row(s) with unreadable or non-positive fields dropped",
        "se descartaron {n} fila(s) de operaciones con campos ilegibles o no positivos",
    ),
    (
        "{n} row(s) with unreadable or non-positive fields dropped",
        "se descartaron {n} fila(s) con campos ilegibles o no positivos",
    ),
    (
        "the uploaded equity file is used for returns; the report supplies the trades",
        "los retornos salen de la curva de equity subida; el informe aporta las operaciones",
    ),
    # --- Parse warnings: platform reports (importers.py) ---
    (
        "hedging account: the report does not say which entry each close belongs to; closes "
        "were matched to the open entry whose price explains their profit, else first-in "
        "first-out, so per-trade entry price and holding time are approximate (money "
        "results stay exact)",
        "cuenta con cobertura (hedging): el informe no dice a qué entrada corresponde cada "
        "cierre; cada cierre se emparejó con la entrada abierta cuyo precio explica su "
        "beneficio, o si no por orden de llegada (FIFO), así que el precio de entrada y la "
        "duración de cada operación son aproximados (los importes de dinero son exactos)",
    ),
    (
        "{n} closing deal(s) had no matching open volume; their money is in the balance but "
        "not in the trade list",
        "{n} cierre(s) no tenían volumen abierto con el que emparejarse; su dinero está en el "
        "balance pero no en la lista de operaciones",
    ),
    (
        "{n} position(s) still open at the end of the report; excluded from the closed trades",
        "{n} posición(es) seguían abiertas al final del informe; quedan fuera de las "
        "operaciones cerradas",
    ),
    (
        "{n} deal(s) closed by the tester at the end of the test",
        "el probador cerró {n} operación(es) al final de la prueba",
    ),
    (
        "{n} trade(s) closed by the tester at the end of the test",
        "el probador cerró {n} operación(es) al final de la prueba",
    ),
    (
        "{what}: the report states {declared} but the rows add up to {measured}",
        "{what}: el informe indica {declared} pero las filas suman {measured}",
    ),
    (
        "the Deals table charges {amount} in fees that the Positions table does not itemise "
        "per trade; they are in the balance curve only",
        "la tabla de operaciones (Deals) cobra {amount} en comisiones que la tabla de "
        "posiciones no desglosa por operación; solo están en la curva de balance",
    ),
    (
        "{n} position(s) opened in the report were not closed; excluded",
        "{n} posición(es) abiertas en el informe no se cerraron; quedan fuera",
    ),
    (
        "MetaTrader 4 tester profit already includes swap and commission; costs are not "
        "itemised, so the trade P&L is net",
        "el beneficio del probador de MetaTrader 4 ya incluye swap y comisión; los costes no "
        "vienen desglosados, así que el resultado de cada operación es neto",
    ),
    (
        "{n} close row(s) referenced an unknown ticket and were linked to the one open ticket "
        "with the same size",
        "{n} fila(s) de cierre citaban un ticket desconocido y se unieron al único ticket "
        "abierto del mismo tamaño",
    ),
    (
        "{n} close row(s) could not be paired with an entry; their money is in the balance "
        "but not in the trade list",
        "{n} fila(s) de cierre no se pudieron emparejar con una entrada; su dinero está en el "
        "balance pero no en la lista de operaciones",
    ),
    ("{n} position(s) never closed; excluded", "{n} posición(es) nunca se cerraron; quedan fuera"),
    (
        "{symbol}: a fill with an unreadable time ({time}) was left out; the trade it opened or "
        "closed is missing from the results",
        "{symbol}: se dejó fuera una ejecución con hora ilegible ({time}); la operación que "
        "abrió o cerró falta en los resultados",
    ),
    (
        "{symbol}: a trade with an unreadable time ({time}) was left out; it is missing from the "
        "results",
        "{symbol}: se dejó fuera una operación con hora ilegible ({time}); falta en los resultados",
    ),
    (
        "{n} more row(s) with an unreadable time were left out",
        "se dejaron fuera {n} fila(s) más con hora ilegible",
    ),
    (
        "the curve was built from each trade's date and result only; without prices, "
        "quantities or entry times, holding times, entry timing and trade-level checks "
        "cannot be measured",
        "la curva se armó solo con la fecha y el resultado de cada operación; sin precios, "
        "cantidades ni horas de entrada no se pueden medir la duración de las operaciones, "
        "el momento de entrada ni las comprobaciones por operación",
    ),
    (
        "the curve was read from the balance column you named; the file lists no trades, so "
        "trade-level checks cannot be measured",
        "la curva se leyó de la columna de saldo que indicaste; el archivo no lista "
        "operaciones, así que no se pueden medir las comprobaciones por operación",
    ),
    (
        "{n} row(s) without a readable date or amount were left out",
        "se dejaron fuera {n} fila(s) sin fecha o cifra legible",
    ),
    (
        "{n} repeated row(s) (the same position listed twice) counted once",
        "{n} fila(s) repetida(s) (la misma posición listada dos veces) se contaron una sola vez",
    ),
    (
        "{n} credit row(s) excluded: broker credit is not the trader's balance",
        "se excluyeron {n} fila(s) de crédito: el crédito del bróker no es balance del trader",
    ),
    (
        "this TradingView export does not itemise commission; trade P&L is net of the "
        "commission set in the strategy properties",
        "esta exportación de TradingView no desglosa la comisión; el resultado de cada "
        "operación ya descuenta la comisión configurada en la estrategia",
    ),
    (
        "{n} open trade(s) at the end of the export; excluded",
        "{n} operación(es) abiertas al final de la exportación; quedan fuera",
    ),
    (
        "{n} trade number(s) without one entry and one exit row",
        "{n} número(s) de operación sin una fila de entrada y una de salida",
    ),
    (
        "every trade has zero commission and fees",
        "todas las operaciones tienen comisión y costes cero",
    ),
    # --- Parse warnings: any trade or fill list (universal.py) ---
    (
        "futures results computed with each contract's point value: {listed}",
        "resultados de futuros calculados con el valor por punto de cada contrato: {listed}",
    ),
    (
        "the profit column already subtracts commission (it matches the price move after "
        "costs), so it was read as net",
        "la columna de resultado ya descuenta la comisión (cuadra con el movimiento del "
        "precio después de costes), así que se leyó como neta",
    ),
    (
        "the file has no profit column: each trade's result is the price move times the "
        "quantity, with no contract multiplier",
        "el archivo no tiene columna de resultado: el de cada operación es el movimiento del "
        "precio por la cantidad, sin multiplicador de contrato",
    ),
    (
        "no side column; the side was taken from the sign of the quantity",
        "no hay columna de lado; se tomó del signo de la cantidad",
    ),
    (
        "no side column; the side was taken from the sign of the profit",
        "no hay columna de lado; se tomó del signo del resultado",
    ),
    (
        "{n} fee(s) charged in another coin than the price were left out of the costs, so "
        "costs are understated",
        "{n} comisión(es) cobradas en otra moneda distinta a la del precio quedaron fuera de "
        "los costes, así que los costes están subestimados",
    ),
    (
        "{n} multi-leg trade(s) kept as single trades",
        "{n} operación(es) de varias patas se tratan como una sola",
    ),
    (
        "this backtesting.py version folds commission into the fill prices; costs are not itemised",
        "esta versión de backtesting.py incluye la comisión en los precios de ejecución; los "
        "costes no vienen desglosados",
    ),
    (
        "the file holds {n} parameter variants; only the first ({name}) was imported",
        "el archivo contiene {n} variantes de parámetros; solo se importó la primera ({name})",
    ),
    ("{n} open trade(s) excluded", "se excluyeron {n} operación(es) abiertas"),
    (
        "the stated initial balance {stated} differs from the deposits before the first "
        "trade ({deposits}); the deposits were used",
        "el balance inicial indicado ({stated}) no coincide con los depósitos previos a la "
        "primera operación ({deposits}); se usaron los depósitos",
    ),
    ("initial balance {amount} taken from {source}", "balance inicial {amount} tomado de {source}"),
    (
        "the file does not state a starting balance; {amount} was assumed, which scales every "
        "return and drawdown",
        "el archivo no indica un balance inicial; se supuso {amount}, lo que escala cada "
        "retorno y cada drawdown",
    ),
    (
        "the file holds {n} accounts; only the one with the most closed trades ({m}) was read",
        "el archivo trae {n} cuentas; solo se leyó la que tiene más operaciones cerradas ({m})",
    ),
    (
        "{n} day(s) with a trade result larger than the balance a withdrawal left (first on "
        "{date}) were measured on the balance before that withdrawal",
        "{n} día(s) con un resultado mayor que el saldo que dejó un retiro (el primero, "
        "{date}) se midieron sobre el saldo previo a ese retiro",
    ),
    (
        "{n} cash flow(s) after the last trade ignored",
        "se ignoraron {n} movimiento(s) de dinero posteriores a la última operación",
    ),
    (
        "{n} Balance cell(s) do not equal the previous balance plus the row's money; the "
        "reported Balance was kept",
        "{n} celda(s) de Balance no son el balance anterior más el dinero de la fila; se "
        "mantuvo el Balance del informe",
    ),
    (
        "deposits or withdrawals were removed: the curve is a flow-adjusted index that starts "
        "at the initial balance",
        "se quitaron depósitos y retiros: la curva es un índice ajustado por flujos que "
        "empieza en el balance inicial",
    ),
    (
        "contract size inferred from reported profit: {sizes}",
        "tamaño de contrato deducido del beneficio del informe: {sizes}",
    ),
    (
        "money per point changes with the conversion to the account currency, so the size "
        "was inferred per trade from its reported profit: {symbols}",
        "el dinero por punto cambia con la conversión a la divisa de la cuenta, así que el "
        "tamaño se dedujo operación por operación de su beneficio en el informe: {symbols}",
    ),
    (
        "the file's times carry no timezone (platform or server time); they were read as UTC",
        "las horas del archivo no indican zona horaria (hora de la plataforma o del "
        "servidor); se leyeron como UTC",
    ),
    (
        "the balance curve is built from closed trades only; it does not show floating "
        "(open-trade) drawdown, so the real drawdown was at least as deep",
        "la curva de balance se construye solo con operaciones cerradas; no muestra el "
        "drawdown flotante (de las operaciones abiertas), así que el drawdown real fue al "
        "menos igual de profundo",
    ),
    # --- Parse warnings: MT5 optimisation export ---
    (
        "{n} repeated pass number(s) counted once",
        "{n} número(s) de pasada repetidos se contaron una vez",
    ),
    (
        "the pass count is the number of configurations the optimiser tried; a genetic "
        "optimisation lists only the passes it evaluated",
        "el número de pasadas es el de configuraciones que probó el optimizador; una "
        "optimización genética solo lista las pasadas que evaluó",
    ),
    # --- Red-flag details (redflags.py) ---
    (
        "{n} return observations; at least {m} are needed",
        "{n} retornos observados; hacen falta al menos {m}",
    ),
    (
        "{n} return observations; conclusions below {m} are fragile",
        "{n} retornos observados; por debajo de {m} las conclusiones son frágiles",
    ),
    (
        "{n} equity value(s) at or below zero; returns are undefined there",
        "{n} valor(es) de equity en cero o por debajo; ahí los retornos no están definidos",
    ),
    (
        "{n} duplicated timestamp(s); the last value was kept",
        "{n} fecha(s) duplicadas; se conservó el último valor",
    ),
    (
        "rows were not in chronological order; sorted before analysis",
        "las filas no estaban en orden cronológico; se ordenaron antes del análisis",
    ),
    ("{n} of {m} rows could not be read", "no se pudieron leer {n} de {m} filas"),
    (
        "every return is identical; nothing to measure",
        "todos los retornos son idénticos; no hay nada que medir",
    ),
    (
        "{n} consecutive identical non-zero returns; looks forward-filled",
        "{n} retornos distintos de cero idénticos seguidos; parece relleno hacia delante",
    ),
    (
        "{n} consecutive identical non-zero returns",
        "{n} retornos distintos de cero idénticos seguidos",
    ),
    (
        "{n} single-period moves are extreme outliers (>{a} and >{b} robust sigmas)",
        "{n} movimientos de un solo periodo son atípicos extremos (>{a} y >{b} sigmas robustas)",
    ),
    (
        "{n} single-period move(s) are extreme outliers; check for bad prints",
        "{n} movimiento(s) de un solo periodo son atípicos extremos; revisa si hay "
        "precios erróneos",
    ),
    (
        "annualised Sharpe {s} exceeds {t}; almost always a look-ahead or a costless fill "
        "assumption",
        "Sharpe anualizado {s} por encima de {t}; casi siempre indica mirar el futuro "
        "(look-ahead) o suponer ejecuciones sin coste",
    ),
    (
        "annualised Sharpe {s} exceeds {t}; rare outside intraday market making",
        "Sharpe anualizado {s} por encima de {t}; raro fuera del market making intradía",
    ),
    (
        "largest gap between rows is {m}x the median spacing",
        "el mayor hueco entre filas es {m}x la separación mediana",
    ),
    (
        "no trading cost declared; the cost dimension uses a reference assumption",
        "no se declaró coste de operación; la dimensión de costes usa un supuesto de referencia",
    ),
    (
        "{n} trial(s) declared but the files show {m} variants or optimisation passes; the "
        "declared count is too low",
        "se declararon {n} intento(s) pero los archivos muestran {m} variantes o pasadas de "
        "optimización; el número declarado es demasiado bajo",
    ),
    (
        "{n} trade row(s) dropped as unreadable",
        "se descartaron {n} fila(s) de operaciones ilegibles",
    ),
    (
        "client-reported pnl differs from recomputed pnl by {p} of gross; the trades file may "
        "carry costs or a different contract size",
        "el resultado que declara el archivo difiere del recalculado en un {p} del bruto; el "
        "archivo puede incluir costes o usar otro tamaño de contrato",
    ),
    (
        "after a loss the next trade is typically {r}x the size used after a win, and {p} of "
        "post-loss trades were larger ({a} after losses, {b} after wins)",
        "tras una pérdida la siguiente operación suele ser {r}x el tamaño usado tras una "
        "ganancia, y el {p} de las operaciones tras pérdida fueron mayores ({a} tras "
        "pérdidas, {b} tras ganancias)",
    ),
    (
        "after a loss the next trade is typically {r}x the size used after a win",
        "tras una pérdida la siguiente operación suele ser {r}x el tamaño usado tras una ganancia",
    ),
    (
        "{a} of {n} trades ({p}) were opened against an open position at a worse price: grid "
        "or averaging down",
        "{a} de {n} operaciones ({p}) se abrieron contra una posición abierta a peor precio: "
        "rejilla o promediar pérdidas",
    ),
    (
        "{a} of {n} trades ({p}) were opened against an open position at a worse price",
        "{a} de {n} operaciones ({p}) se abrieron contra una posición abierta a peor precio",
    ),
    (
        "the time-weighted gain is {g} while trading made {m} on {d} deposited; deposits "
        "and withdrawals shape the percentage",
        "la ganancia ponderada en el tiempo es {g} mientras que operar dejó {m} sobre {d} "
        "depositados; los depósitos y retiros dan forma al porcentaje",
    ),
    (
        "{n} deposit(s) arrived while the account was at least {p} below its peak",
        "{n} depósito(s) llegaron cuando la cuenta estaba al menos un {p} por debajo de su máximo",
    ),
    (
        "open positions carried a floating loss of {p} of the balance when the statement "
        "was printed; the balance does not show it",
        "las posiciones abiertas tenían una pérdida flotante del {p} del balance al imprimir "
        "el historial; el balance no la muestra",
    ),
    (
        "the test ran on control points: prices between those points were not simulated, so "
        "stops, targets and intrabar exits may have filled where the market never let them",
        "la prueba se hizo con puntos de control: los precios entre esos puntos no se "
        "simularon, así que stops, objetivos y salidas dentro de la vela pueden haberse "
        "llenado donde el mercado nunca lo permitió",
    ),
    (
        "the test ran on open prices only: prices between those points were not simulated, "
        "so stops, targets and intrabar exits may have filled where the market never let them",
        "la prueba se hizo solo con precios de apertura: los precios entre esos puntos no se "
        "simularon, así que stops, objetivos y salidas dentro de la vela pueden haberse "
        "llenado donde el mercado nunca lo permitió",
    ),
    (
        "the report states a data quality of {p}: part of the price history was missing or "
        "generated",
        "el informe declara una calidad de datos del {p}: parte del historial de precios "
        "faltaba o era generado",
    ),
    (
        "the header states {p} modelling quality with control points, which MT4 does not "
        "print for that mode; ask for the original report file",
        "el encabezado declara un {p} de calidad de modelado con puntos de control, algo que "
        "MT4 no imprime en ese modo; pide el archivo original del informe",
    ),
    (
        "the header states {p} modelling quality with open prices only, which MT4 does not "
        "print for that mode; ask for the original report file",
        "el encabezado declara un {p} de calidad de modelado con solo precios de apertura, "
        "algo que MT4 no imprime en ese modo; pide el archivo original del informe",
    ),
    (
        "{n} trade(s) fall outside the dates the header says were tested; ask for the "
        "original report file",
        "{n} operación(es) quedan fuera de las fechas que el encabezado dice que se probaron; "
        "pide el archivo original del informe",
    ),
    (
        "the tester's modelling mode, as printed in the report header",
        "el modo de modelado del probador, tal como lo imprime el encabezado del informe",
    ),
    (
        "share of the price history the tester had, as printed in the report header",
        "parte del historial de precios que tuvo el probador, tal como lo imprime el "
        "encabezado del informe",
    ),
    ("as printed in the report header", "tal como lo imprime el encabezado del informe"),
    (
        "as printed in the report header; 'Current' is the spread when the test ran",
        "tal como lo imprime el encabezado del informe; 'Current' es el spread del momento "
        "en que se hizo la prueba",
    ),
    (
        "trades that open or close outside the dates the header says were tested",
        "operaciones que abren o cierran fuera de las fechas que el encabezado dice que se "
        "probaron",
    ),
    (
        "the file is not a MetaTrader tester report",
        "el archivo no es un informe del probador de MetaTrader",
    ),
    (
        "the report does not state a modelling mode we recognise",
        "el informe no indica un modo de modelado que reconozcamos",
    ),
    (
        "the report prints no data quality (n/a)",
        "el informe no imprime la calidad de datos (n/a)",
    ),
    ("the report prints no test window", "el informe no imprime las fechas de la prueba"),
    (
        "no test window or no trades to compare",
        "no hay fechas de prueba u operaciones con las que comparar",
    ),
    ("the report does not print it", "el informe no lo imprime"),
    (
        "deepest fall in money over one year of trades drawn at random from the history, "
        "at the backtest's sizes",
        "mayor caída en dinero en un año de operaciones sorteadas al azar del historial, al "
        "tamaño del backtest",
    ),
    (
        "deepest fall in money of the closed trades in their own order",
        "mayor caída en dinero de las operaciones cerradas en su propio orden",
    ),
    (
        "the largest of the resampled 95th percentile, the history's own fall and any "
        "drawdown with open trades from the platform or the equity curve",
        "la mayor entre el percentil 95 remuestreado, la caída del propio historial y "
        "cualquier drawdown con operaciones abiertas de la plataforma o de la curva de equity",
    ),
    (
        "the closed trades end with a net loss, so no size is given for them: at any size the "
        "history loses",
        "las operaciones cerradas terminan con pérdida neta, así que no se da un tamaño para "
        "ellas: a cualquier tamaño el historial pierde",
    ),
    (
        "deepest fall in money of the uploaded equity curve, open trades included",
        "mayor caída en dinero de la curva de equity subida, con operaciones abiertas",
    ),
    (
        "no equity curve with open trades in money",
        "no hay una curva de equity en dinero con operaciones abiertas",
    ),
    (
        "the trades overlap as a grid or with hidden open losses, so closed trades understate "
        "the real fall; upload an equity curve that includes open trades or the platform report "
        "with its equity drawdown",
        "las operaciones se solapan en grid o con pérdidas abiertas ocultas, así que las "
        "operaciones cerradas subestiman la caída real; sube una curva de equity que incluya "
        "las operaciones abiertas o el informe de la plataforma con su drawdown de equity",
    ),
    (
        "the platform's maximal drawdown in money, open trades included",
        "el drawdown máximo de la plataforma en dinero, con operaciones abiertas",
    ),
    (
        "the file does not print the platform's drawdown in money",
        "el archivo no imprime el drawdown de la plataforma en dinero",
    ),
    (
        "days from the first entry to the last exit",
        "días desde la primera entrada hasta la última salida",
    ),
    (
        "reference fall / loss limit, at the backtest's sizes",
        "caída de referencia / límite de pérdida, al tamaño del backtest",
    ),
    (
        "loss limit x starting balance / reference fall",
        "límite de pérdida x balance inicial / caída de referencia",
    ),
    ("closed trades per year in the history", "operaciones cerradas por año en el historial"),
    (
        "closed trades per year at the history's pace; the history is shorter than a year",
        "operaciones cerradas por año al ritmo del historial; el historial dura menos de un año",
    ),
    ("starting balance of the uploaded file", "balance inicial del archivo subido"),
    ("the file states no starting balance", "el archivo no indica un balance inicial"),
    (
        "needs at least {n} closed trades; {m} supplied",
        "necesita al menos {n} operaciones cerradas; se aportaron {m}",
    ),
    (
        "needs trades spread over at least {n} days; a shorter history stretched to a year "
        "gives capital figures too uncertain to act on",
        "necesita operaciones repartidas en al menos {n} días; un historial más corto "
        "estirado a un año da cifras de capital demasiado inciertas para decidir con ellas",
    ),
    (
        "the trades show almost no fall to size against: under half a percent of the "
        "starting balance",
        "las operaciones casi no muestran una caída con la que dimensionar: menos de medio "
        "por ciento del balance inicial",
    ),
    (
        "the trades show no fall to size against",
        "las operaciones no muestran una caída con la que dimensionar",
    ),
    (
        "{n} settings one step away keep {p} of the chosen profit at the median and {q} of "
        "them end with a profit: the chosen settings look like a lone peak",
        "{n} configuraciones a un paso conservan en la mediana el {p} del beneficio elegido y "
        "el {q} de ellas gana: los parámetros elegidos parecen un pico aislado",
    ),
    ("from the rows of the optimisation export", "de las filas de la exportación de optimización"),
    ("rank of the chosen pass / passes", "puesto de la pasada elegida / pasadas"),
    (
        "median neighbour profit / chosen profit",
        "beneficio mediano de los vecinos / beneficio elegido",
    ),
    ("the chosen pass shows no profit", "la pasada elegida no tiene beneficio"),
    (
        "the optimisation did not try the settings one step away (genetic or sparse)",
        "la optimización no probó las configuraciones a un paso (genética o dispersa)",
    ),
    ("no optimisation file uploaded", "no se subió archivo de optimización"),
    (
        "the export has no Profit column; its Result column is the optimisation criterion "
        "(by default the final balance), not a profit",
        "la exportación no tiene columna Profit; su columna Result es el criterio de "
        "optimización (por defecto el balance final), no un beneficio",
    ),
    (
        "needs at least {n} passes with a profit column and a parameter that varies",
        "necesita al menos {n} pasadas con columna de beneficio y un parámetro que varíe",
    ),
    (
        "the file is a backtest, not an account history",
        "el archivo es un backtest, no el historial de una cuenta",
    ),
    (
        "time-weighted: deposits and withdrawals are taken out, as track-record sites compute gain",
        "ponderada en el tiempo: se quitan depósitos y retiros, como calculan la ganancia "
        "los sitios de historiales",
    ),
    (
        "closed trades after commission and swap, in the account currency",
        "operaciones cerradas después de comisiones y swap, en la divisa de la cuenta",
    ),
    ("trading result / money deposited", "resultado de operar / dinero depositado"),
    ("withdrawn / deposited", "retirado / depositado"),
    ("the file lists no deposit", "el archivo no incluye ningún depósito"),
    (
        "the platform's own summary at the time of the statement",
        "resumen de la propia plataforma al momento del historial",
    ),
    ("floating result / balance", "resultado flotante / balance"),
    (
        "the file does not state the floating result",
        "el archivo no indica el resultado flotante",
    ),
    (
        "earlier deposits and withdrawals plus trades closed before it",
        "depósitos y retiros anteriores más las operaciones cerradas antes",
    ),
    ("flow-adjusted drawdown on the day before", "drawdown ajustado por depósitos el día anterior"),
    ("no curve point before the deposit", "no hay un punto de la curva antes del depósito"),
    (
        "up to {n} positions were open at once on one symbol",
        "hubo hasta {n} posiciones abiertas a la vez en un mismo símbolo",
    ),
    (
        "the curve is rebuilt from closed trades while positions overlapped; floating losses "
        "of open positions are not visible in it",
        "la curva se reconstruye con operaciones cerradas mientras había posiciones "
        "solapadas; las pérdidas flotantes de las posiciones abiertas no se ven en ella",
    ),
    (
        "win rate {w} with the average loss {m}x the average win: rare large losses carry the risk",
        "aciertos del {w} con la pérdida media {m}x la ganancia media: el riesgo está en "
        "pérdidas grandes y poco frecuentes",
    ),
    (
        "the largest adverse excursion is {m}x the average loss; no sign of a fixed stop",
        "la mayor excursión adversa es {m}x la pérdida media; no hay señal de un stop fijo",
    ),
    (
        "the {k} best passes of the backtest end the forward period with a profit in {a} of "
        "cases, against {b} for all passes; rank correlation between the periods {r}",
        "las {k} mejores pasadas del backtest terminan el periodo forward con ganancia en el "
        "{a} de los casos, frente al {b} de todas las pasadas; correlación de rangos entre "
        "periodos {r}",
    ),
    (
        "rank correlation between the back and forward results {r}",
        "correlación de rangos entre los resultados del backtest y del forward {r}",
    ),
    (
        "the optimisation file has two result columns before Profit, as a forward export does, "
        "but they are not named Forward Result and Back Result; export it again from a terminal "
        "set to English",
        "el archivo de optimización tiene dos columnas de resultado antes de Profit, como una "
        "exportación forward, pero no se llaman Forward Result y Back Result; vuelve a "
        "exportarlo desde una terminal en inglés",
    ),
    (
        "the optimisation file is not a forward export (no Forward Result and Back Result columns)",
        "el archivo de optimización no es una exportación forward (no tiene las columnas "
        "Forward Result y Back Result)",
    ),
    (
        "needs at least {n} passes with a back and a forward result",
        "hacen falta al menos {n} pasadas con resultado de backtest y de forward",
    ),
    (
        "every pass has the same back or forward result",
        "todas las pasadas tienen el mismo resultado de backtest o de forward",
    ),
    ("from the rows of the forward optimisation export", "de las filas de la exportación forward"),
    (
        "Spearman correlation between the back and the forward result of every pass",
        "correlación de Spearman entre el resultado de backtest y el de forward de cada pasada",
    ),
    (
        "the best tenth of the passes by back result, at least five",
        "la mejor décima parte de las pasadas por resultado de backtest, al menos cinco",
    ),
    (
        "share of the best backtest passes with a forward profit",
        "parte de las mejores pasadas del backtest con ganancia en el forward",
    ),
    (
        "share of all passes with a forward profit",
        "parte de todas las pasadas con ganancia en el forward",
    ),
    (
        "median forward profit of the best backtest passes",
        "ganancia mediana en el forward de las mejores pasadas del backtest",
    ),
    ("median forward profit of all passes", "ganancia mediana en el forward de todas las pasadas"),
    (
        "the export has no Profit column for the forward period",
        "la exportación no tiene la columna Profit del periodo forward",
    ),
    (
        "share of the other passes with a lower forward result",
        "parte de las demás pasadas con un resultado forward menor",
    ),
    (
        "forward profit of the pass matching the tester report",
        "ganancia en el forward de la pasada que coincide con el informe del probador",
    ),
    (
        "no pass matches the inputs of the uploaded tester report",
        "ninguna pasada coincide con las entradas del informe del probador subido",
    ),
    (
        "a forward export: its Profit column is the forward period's; the forward section "
        "reads it, and this check needs the main optimisation export",
        "una exportación forward: su columna Profit es la del periodo forward; la sección "
        "forward la lee, y esta comprobación necesita la exportación principal de la "
        "optimización",
    ),
    (
        "the {n} trades since {d} (the last third of the history) average {a} per trade, "
        "against {b} for the {m} earlier ones; the drop is {z} standard errors",
        "las {n} operaciones desde el {d} (el último tercio del historial) promedian {a} por "
        "operación, frente a {b} de las {m} anteriores; la caída es de {z} errores estándar",
    ),
    ("needs at least {n} closed trades", "hacen falta al menos {n} operaciones cerradas"),
    (
        "the trades span less than two years, too short to compare periods",
        "las operaciones abarcan menos de dos años, demasiado poco para comparar periodos",
    ),
    (
        "needs at least {n} closed trades in the recent third of the history and in the "
        "earlier two thirds",
        "hacen falta al menos {n} operaciones cerradas en el último tercio del historial y en "
        "los dos tercios anteriores",
    ),
    ("a trade result is not a finite number", "un resultado de operación no es un número finito"),
    (
        "closed trades by exit date; net result after the fees the file itemises",
        "operaciones cerradas por fecha de cierre; resultado neto tras los costes que detalla "
        "el archivo",
    ),
    ("average net result per trade", "resultado neto medio por operación"),
    (
        "needs at least {n} winning and {m} losing trades",
        "hacen falta al menos {n} operaciones ganadoras y {m} perdedoras",
    ),
    (
        "closed trades by entry and exit time; net result after the fees the file itemises",
        "operaciones cerradas por hora de entrada y de cierre; resultado neto tras los costes "
        "que detalla el archivo",
    ),
    ("median hours a winning trade stays open", "horas medianas que sigue abierta una ganadora"),
    ("median hours a losing trade stays open", "horas medianas que sigue abierta una perdedora"),
    (
        "median losing hold over median winning hold",
        "duración mediana de las perdedoras entre la de las ganadoras",
    ),
    (
        "share of trades after a loss opened within 15 minutes of it",
        "parte de las operaciones tras una pérdida abiertas en menos de 15 minutos",
    ),
    (
        "share of trades after a win opened within 15 minutes of it",
        "parte de las operaciones tras una ganancia abiertas en menos de 15 minutos",
    ),
    (
        "after the fees the file itemises per trade",
        "después de los costes que el archivo detalla por operación",
    ),
    (
        "share of trades with a net profit after the fees the file itemises",
        "parte de las operaciones con resultado neto positivo, después de los costes que "
        "detalla el archivo",
    ),
    ("share of trades with a net profit", "parte de las operaciones con resultado neto positivo"),
    ("the file has no time of day", "el archivo no tiene hora del día"),
    ("the file is not a monthly track record", "el archivo no es un historial mensual"),
    (
        "the fund's own returns after its fees; costs were not measured",
        "rentabilidades del propio fondo tras sus comisiones; los costes no se midieron",
    ),
    (
        "the net-of-fees declaration applies only to a monthly fund track record; costs are "
        "checked as usual",
        "la declaración de rentabilidades netas de comisiones solo vale para el historial "
        "mensual de un fondo; los costes se revisan como siempre",
    ),
    ("needs at least {n} monthly returns", "hacen falta al menos {n} rentabilidades mensuales"),
    ("the monthly returns do not vary", "las rentabilidades mensuales no varían"),
    (
        "every published preset simulated on the same resampled daily paths, rules as each "
        "firm's page stated them on its as_of date; a program's phases are taken as fresh "
        "starts, so the chance of passing them all is the product of each phase's",
        "cada reto publicado simulado sobre los mismos recorridos diarios remuestreados, con "
        "las reglas que la página de cada firma indicaba en su fecha; las fases de un "
        "programa se toman como comienzos nuevos, así que la probabilidad de pasarlas todas "
        "es el producto de la de cada fase",
    ),
    (
        "share of the resampled passes whose best day breaks the firm's best-day rule, "
        "checked at the pass on daily closes",
        "proporción de los pases remuestreados cuyo mejor día rompe la regla del mejor día "
        "de la firma, comprobada al pasar con cierres diarios",
    ),
    (
        "share of all resampled paths that reach the target with the best day inside the "
        "firm's best-day rule; the rule is checked at the pass, on daily closes",
        "proporción de todos los recorridos remuestreados que llegan al objetivo con el mejor "
        "día dentro de la regla del mejor día de la firma; la regla se comprueba al pasar, con "
        "cierres diarios",
    ),
    (
        "the curve covers none of the dated market falls in full",
        "la curva no cubre completa ninguna de las caídas de mercado con fecha",
    ),
    ("the curve is shorter than two months", "la curva dura menos de dos meses"),
    (
        "the monthly returns with each yearly fee taken out month by month; shown because the "
        "figures were not declared net of fees",
        "las rentabilidades mensuales con cada comisión anual descontada mes a mes; se muestra "
        "porque las cifras no se declararon netas de comisiones",
    ),
    (
        "the yearly fee that would leave the fund's months level with the benchmark's over "
        "the months they share",
        "la comisión anual que dejaría los meses del fondo al nivel de los del índice en los "
        "meses en común",
    ),
    (
        "the curve never moves 0.1 % from its start",
        "la curva nunca se aleja un 0.1 % de su inicio",
    ),
    (
        "fixed calendar windows of widely recorded market falls; the curve's month-end "
        "returns compounded over each window it covers in full",
        "periodos fijos de caídas de mercado de fecha pública; las rentabilidades de fin de "
        "mes de la curva compuestas en cada periodo que cubre completo",
    ),
    (
        "the curve has no usable month-end levels",
        "la curva no tiene saldos de fin de mes utilizables",
    ),
    (
        "month-end returns as the file states them",
        "rentabilidades de fin de mes tal como las da el archivo",
    ),
    ("annualised standard deviation", "desviación típica anualizada"),
    (
        "first-order autocorrelation of monthly returns",
        "autocorrelación de primer orden de las rentabilidades mensuales",
    ),
    (
        "annualised volatility of the unsmoothed returns",
        "volatilidad anualizada de las rentabilidades sin suavizar",
    ),
    (
        "read as a monthly returns table (one row per year, one column per month); values taken "
        "as percentages",
        "leído como tabla de rentabilidades mensuales (una fila por año, una columna por mes); "
        "valores tomados como porcentajes",
    ),
    (
        "read as a monthly returns table (one row per year, one column per month); values taken "
        "as fractions",
        "leído como tabla de rentabilidades mensuales (una fila por año, una columna por mes); "
        "valores tomados como fracciones",
    ),
    (
        "read as a monthly returns table (one row per year, one column per month); values taken "
        "as fractions, as the year totals confirm",
        "leído como tabla de rentabilidades mensuales (una fila por año, una columna por mes); "
        "valores tomados como fracciones, como confirman los totales anuales",
    ),
    (
        "read as a monthly returns table (one row per year, one column per month); values taken "
        "as percentages, as the year totals confirm",
        "leído como tabla de rentabilidades mensuales (una fila por año, una columna por mes); "
        "valores tomados como porcentajes, como confirman los totales anuales",
    ),
    (
        "read as a monthly returns table (one row per year, one column per month); values taken "
        "as percentages (the file shows no % sign: check one month against the factsheet)",
        "leído como tabla de rentabilidades mensuales (una fila por año, una columna por mes); "
        "valores tomados como porcentajes (el archivo no muestra el signo %: compara un mes con "
        "la ficha del fondo)",
    ),
    (
        "read as a monthly returns table (one row per year, one column per month); values taken "
        "as fractions (four or more decimals and none reaching 1, with no % sign: check one "
        "month against the factsheet)",
        "leído como tabla de rentabilidades mensuales (una fila por año, una columna por mes); "
        "valores tomados como fracciones (cuatro o más decimales y ninguno llega a 1, sin signo "
        "%: compara un mes con la ficha del fondo)",
    ),
    (
        "{count} unreadable month(s) left out of the table: {cells}",
        "{count} mes(es) ilegibles fuera de la tabla: {cells}",
    ),
    (
        "benchmark rows read from the table: the fund section compares the fund with them",
        "filas del índice de referencia leídas de la tabla: la sección de fondos compara el "
        "fondo con ellas",
    ),
    (
        "{n} row(s) of differences between the fund and its benchmark left out",
        "{n} fila(s) de diferencias entre el fondo y su índice de referencia fuera del análisis",
    ),
    (
        "benchmark column {column} read: the fund section compares the fund with it",
        "columna de índice de referencia {column} leída: la sección de fondos compara el fondo "
        "con ella",
    ),
    (
        "the benchmark column {column} could not be read; left out",
        "la columna de índice de referencia {column} no se pudo leer; queda fuera",
    ),
    (
        "the benchmark's returns as supplied; Rigor did not check them against the index",
        "rentabilidades del índice de referencia tal como se aportaron; Rigor no las comprobó "
        "con el índice",
    ),
    (
        "needs at least {n} months shared with the benchmark",
        "necesita al menos {n} meses en común con el índice de referencia",
    ),
    (
        "the benchmark's monthly returns do not vary",
        "las rentabilidades mensuales del índice de referencia no varían",
    ),
    (
        "needs at least {n} months with the benchmark up",
        "necesita al menos {n} meses con el índice de referencia al alza",
    ),
    (
        "needs at least {n} months with the benchmark down",
        "necesita al menos {n} meses con el índice de referencia a la baja",
    ),
    (
        "fund's compound annual return minus the benchmark's",
        "rentabilidad anual compuesta del fondo menos la del índice de referencia",
    ),
    (
        "annualised standard deviation of the monthly differences",
        "desviación típica anualizada de las diferencias mensuales",
    ),
    (
        "fixed calendar windows of widely recorded market falls; the fund's months "
        "compounded over each window it covers in full",
        "periodos fijos de caídas de mercado de fecha pública; los meses del fondo compuestos "
        "en cada periodo que cubre completo",
    ),
    (
        "the stated year total does not match its months for {years}",
        "el total anual indicado no cuadra con sus meses en {years}",
    ),
    (
        "the file does not name each trade's instrument",
        "el archivo no indica el instrumento de cada operación",
    ),
    ("every trade is on one instrument", "todas las operaciones son del mismo instrumento"),
    (
        "closed trades by the instrument the file names; net result after the fees the file "
        "itemises",
        "operaciones cerradas por el instrumento que indica el archivo; resultado neto tras los "
        "costes que detalla el archivo",
    ),
    (
        "share with a net profit among trades that follow {n} losses in a row",
        "parte con resultado neto positivo entre las operaciones que siguen a {n} pérdidas "
        "seguidas",
    ),
    (
        "distance of the recent average from the earlier one, in standard errors",
        "distancia de la media reciente respecto de la anterior, en errores estándar",
    ),
    (
        "the best trade makes {share} of the total of the winning trades; without it and the "
        "worst loss the rest keep {keep} of the net result ({n} trades)",
        "la mejor operación aporta el {share} del total de las operaciones ganadoras; sin ella "
        "y sin la peor pérdida, el resto conserva el {keep} del resultado neto ({n} operaciones)",
    ),
    (
        "the best {k} trades make {share} of the total of the winning trades; without them and "
        "the {j} worst losses the rest keep {keep} of the net result ({n} trades)",
        "las {k} mejores operaciones aportan el {share} del total de las operaciones ganadoras; "
        "sin ellas y sin las {j} peores pérdidas, el resto conserva el {keep} del resultado "
        "neto ({n} operaciones)",
    ),
    (
        "the largest loss is {m}x the average loss; no sign of a fixed stop",
        "la mayor pérdida es {m}x la pérdida media; no hay señal de un stop fijo",
    ),
    (
        "{a} of {n} trades ({p}) close outside the dates of the equity curve; the two files "
        "may not describe the same account",
        "{a} de {n} operaciones ({p}) cierran fuera de las fechas de la curva de equity; puede "
        "que los dos archivos no describan la misma cuenta",
    ),
    (
        "month by month the realised trade pnl and the equity change correlate at {c} over "
        "{n} months; the trades may not belong to this equity curve, so the cost dimension "
        "may not describe it",
        "mes a mes, el resultado realizado de las operaciones y el cambio de la equity "
        "tienen una correlación de {c} en {n} meses; puede que las operaciones no sean de "
        "esta curva, y entonces la dimensión de costes no la describe",
    ),
    # --- Not-measured reasons and evidence notes (engine, analytics, costs) ---
    ("no long trades", "no hay operaciones largas"),
    ("no short trades", "no hay operaciones cortas"),
    ("no trades uploaded", "no se subieron operaciones"),
    (
        "under a year of history; annualising it would exaggerate",
        "menos de un año de historial; anualizarlo lo exageraría",
    ),
    ("no variants uploaded", "no se subió la matriz de variantes"),
    ("fewer than ten returns", "menos de diez retornos"),
    (
        "the simulator needs daily or finer data; the upload is coarser",
        "el simulador necesita datos diarios o más finos; los subidos son más gruesos",
    ),
    ("before commission and swap", "antes de comisión y swap"),
    ("share of trades with pnl > 0", "proporción de operaciones con resultado > 0"),
    (
        "commission and swap as reported, a positive cost",
        "comisión y swap del informe, como coste positivo",
    ),
    ("no commission or swap total supplied", "no se aportó el total de comisión o swap"),
    ("gross pnl minus reported fees", "resultado bruto menos los costes del informe"),
    (
        "the uploaded history with its best outcomes removed; not a forecast",
        "el historial subido sin sus mejores resultados; no es una previsión",
    ),
    ("compounded total return of the uploaded curve", "retorno total compuesto de la curva subida"),
    (
        "net result of the closed trades after reported fees",
        "resultado neto de las operaciones cerradas tras los costes del informe",
    ),
    ("best five trades / net result", "cinco mejores operaciones / resultado neto"),
    ("the curve is too short or not positive", "la curva es muy corta o no es positiva"),
    ("fewer than two closed trades", "menos de dos operaciones cerradas"),
    ("fewer than {n} closed trades", "menos de {n} operaciones cerradas"),
    ("the backtest has no closed trades", "el backtest no tiene operaciones cerradas"),
    (
        "the backtest has fewer than {n} closed trades",
        "el backtest tiene menos de {n} operaciones cerradas",
    ),
    (
        "the live statement has fewer than {n} closed trades",
        "la cuenta real tiene menos de {n} operaciones cerradas",
    ),
    (
        "Backtest trades resampled with replacement, as many as the live statement holds; "
        "costs itemised per trade subtracted on both sides. Streaks are not preserved.",
        "Operaciones del backtest tomadas al azar con reemplazo, tantas como tiene la cuenta "
        "real; los costes detallados por operación se restan en ambos lados. No conserva las "
        "rachas.",
    ),
    (
        "Paired by side, symbol and entry time within 60 minutes, as the files state the "
        "times; price differences in basis points (0.01 %), positive when worse for the "
        "account; result differences at the backtest trade's size.",
        "Emparejadas por lado, símbolo y hora de entrada a menos de 60 minutos, con las horas "
        "tal como las dan los archivos; diferencias de precio en puntos básicos (0,01 %), "
        "positivas cuando son peores para la cuenta; diferencias de resultado al tamaño de la "
        "operación del backtest.",
    ),
    (
        "deepest drawdown the platform prints with open trades counted",
        "el drawdown más profundo que imprime la plataforma contando las operaciones abiertas",
    ),
    (
        "per side on {pair} at {price}, the median entry price",
        "por lado en {pair} a {price}, el precio de entrada mediano",
    ),
    ("paired live trades / live trades", "operaciones reales emparejadas / operaciones reales"),
    ("fewer than {n} paired trades", "menos de {n} operaciones emparejadas"),
    ("no live trades on the shared dates", "no hay operaciones reales en las fechas comunes"),
    (
        "{s} resampled histories of {n} backtest trades, seed {seed}",
        "{s} historias remuestreadas de {n} operaciones del backtest, semilla {seed}",
    ),
    (
        "Entry times as the file states them (platform or server time); "
        "net result after the fees the file itemises per trade.",
        "Horas de entrada tal como las da el archivo (hora de la plataforma o del servidor); "
        "resultado neto después de los costes que el archivo detalla por operación.",
    ),
    (
        "average net result per trade, account currency",
        "resultado neto medio por operación, en la divisa de la cuenta",
    ),
    ("gross profit / gross loss", "beneficio bruto / pérdida bruta"),
    (
        "gross profit / gross loss, before commission and swap; a platform that counts "
        "them inside each trade can show a slightly lower figure",
        "beneficio bruto / pérdida bruta, antes de comisiones y swap; una plataforma que los "
        "cuenta dentro de cada operación puede mostrar una cifra algo menor",
    ),
    (
        "no losing trades; the ratio is undefined",
        "no hay operaciones perdedoras; el ratio no está definido",
    ),
    ("no winning trades", "no hay operaciones ganadoras"),
    ("no losing trades", "no hay operaciones perdedoras"),
    ("average win / average loss", "ganancia media / pérdida media"),
    ("needs at least one win and one loss", "necesita al menos una ganadora y una perdedora"),
    ("largest single win / gross profit", "mayor ganadora / beneficio bruto"),
    (
        "sqrt(min(N, {cap})) x mean / std of per-trade gross pnl",
        "raíz(mín(N, {cap})) x media / desviación del resultado bruto por operación",
    ),
    (
        "needs at least two trades with different results",
        "necesita al menos dos operaciones con resultados distintos",
    ),
    ("first entry to last exit", "de la primera entrada a la última salida"),
    ("trades span less than one day", "las operaciones abarcan menos de un día"),
    (
        "needs at least {n} daily returns that are not all identical; {m} supplied",
        "necesita al menos {n} retornos diarios que no sean todos idénticos; se aportaron {m}",
    ),
    (
        "needs at least {n} returns that are not all identical; {m} supplied",
        "necesita al menos {n} retornos que no sean todos idénticos; se aportaron {m}",
    ),
    (
        "the history is too short to resample a year at this frequency",
        "el historial es demasiado corto para remuestrear un año con esta frecuencia",
    ),
    (
        "resampled from the uploaded history, not a forecast",
        "remuestreado del historial aportado, no es una predicción",
    ),
    (
        "business days, resampled from the uploaded history, not a forecast",
        "días hábiles, remuestreado del historial aportado, no es una predicción",
    ),
    (
        "Wilson 95 % interval over the resampled paths; it ignores model error",
        "intervalo de Wilson al 95 % sobre las trayectorias remuestreadas; no incluye el "
        "error del modelo",
    ),
    (
        "no resampled path reached the target within the limits",
        "ninguna trayectoria remuestreada alcanzó el objetivo dentro de los límites",
    ),
    (
        "P[true Sharpe > 0] given length, skew and kurtosis",
        "P[Sharpe real > 0] dada la longitud, la asimetría y la curtosis",
    ),
    (
        "observations needed for PSR to reach 0.95",
        "observaciones necesarias para que el PSR llegue a 0.95",
    ),
    (
        "observed Sharpe <= 0; no track record length reaches 0.95",
        "Sharpe observado <= 0; ninguna longitud de historial llega a 0.95",
    ),
    ("unreachable", "inalcanzable"),
    ("variance across {n} variants", "varianza entre {n} variantes"),
    ("sampling variance of the Sharpe estimator", "varianza de muestreo del estimador de Sharpe"),
    ("PSR against E[max Sharpe] of 1 trial", "PSR frente a E[Sharpe máximo] de 1 intento"),
    (
        "PSR against E[max Sharpe] of 1 trial, {source}",
        "PSR frente a E[Sharpe máximo] de 1 intento, {source}",
    ),
    ("PSR against E[max Sharpe] of {n} trials", "PSR frente a E[Sharpe máximo] de {n} intentos"),
    (
        "PSR against E[max Sharpe] of {n} trials, {source}",
        "PSR frente a E[Sharpe máximo] de {n} intentos, {source}",
    ),
    (
        "PSR against E[max Sharpe] of {n} trial(s)",
        "PSR frente a E[Sharpe máximo] de {n} intento(s)",
    ),
    (
        "PSR against E[max Sharpe] of {n} trial(s), {source}",
        "PSR frente a E[Sharpe máximo] de {n} intento(s), {source}",
    ),
    (
        "smallest power-of-two trial count with DSR < 0.5",
        "menor número de intentos, en potencias de dos, con DSR < 0.5",
    ),
    ("DSR stays >= 0.5 up to {n} trials", "el DSR sigue >= 0.5 hasta {n} intentos"),
    ("too short", "demasiado corto"),
    ("declared by the client; not verifiable", "declarado por el cliente; no se puede comprobar"),
    (
        "in-sample minus out-of-sample annualised Sharpe",
        "Sharpe anualizado dentro de muestra menos fuera de muestra",
    ),
    (
        "strategy max drawdown over benchmark max drawdown",
        "drawdown máximo de la estrategia entre el del benchmark",
    ),
    ("benchmark has no drawdown", "el benchmark no tiene drawdown"),
    (
        "benchmark overlaps only {p} of the strategy timestamps",
        "el benchmark solo coincide con el {p} de las fechas de la estrategia",
    ),
    (
        "fraction of CSCV splits where the IS winner is below the OOS median",
        "fracción de divisiones CSCV en las que la mejor dentro de muestra queda por debajo "
        "de la mediana fuera de muestra",
    ),
    (
        "CSCV requires at least two parameter variants",
        "el CSCV necesita al menos dos variantes de parámetros",
    ),
    (
        "variant_returns must contain only finite values",
        "la matriz de variantes solo puede contener valores finitos",
    ),
    (
        "observations must be divisible into equal CSCV partitions ({n} observations, {m} "
        "partitions)",
        "las observaciones deben dividirse en particiones CSCV iguales ({n} observaciones, "
        "{m} particiones)",
    ),
    (
        "a side has fewer than {n} returns (in-sample {a}, out-of-sample {b})",
        "uno de los tramos tiene menos de {n} retornos (dentro de muestra {a}, fuera de "
        "muestra {b})",
    ),
    ("split failed: {error}", "no se pudo dividir la serie: {error}"),
    (
        "extra cost per side, on top of the report's fees, at which the ledger nets to zero",
        "coste extra por lado, además de los costes del informe, con el que el resultado "
        "queda en cero",
    ),
    (
        "cost per side at which the ledger nets to zero",
        "coste por lado con el que el resultado queda en cero",
    ),
    ("no traded notional", "no hay volumen operado"),
    ("undefined", "no definido"),
    (
        "signed total the report itemises; negative is a cost",
        "total con signo que desglosa el informe; negativo es un coste",
    ),
    (
        "assumed slippage: the client declared zero cost; charged on top of the fees the "
        "report itemises",
        "deslizamiento supuesto: el cliente declaró coste cero; se cobra además de los "
        "costes que desglosa el informe",
    ),
    ("assumed: client declared zero cost", "supuesto: el cliente declaró coste cero"),
    (
        "assumed slippage: an account history's prices are the broker's fills, so the spread "
        "is already in each result; charged on top",
        "deslizamiento supuesto: los precios de un historial de cuenta son las ejecuciones "
        "del bróker, así que el spread ya está en cada resultado; se cobra además",
    ),
    (
        "declared by the client; charged on top of the fees the report itemises",
        "declarado por el cliente; se cobra además de los costes que desglosa el informe",
    ),
    ("inferred from the timestamps", "deducido de las fechas"),
    ("starting balance of the imported report", "balance inicial del informe importado"),
    ("no report imported", "no se importó un informe"),
    ("rows of the export", "filas de la exportación"),
    ("not declared", "no declarado"),
    ("holdout not evaluated", "tramo fuera de muestra no evaluado"),
    (
        "balance rebuilt from closed trades; floating drawdown is not visible",
        "balance reconstruido con operaciones cerradas; el drawdown flotante no se ve",
    ),
    ("as uploaded", "tal como se subió"),
    ("[withheld: promotional wording]", "[omitido: lenguaje promocional]"),
    # --- Prop-firm rule notes and generic names (prop_presets.py) ---
    ("Generic", "Genérico"),
    ("Two-step evaluation, phase 1", "Evaluación en dos fases, fase 1"),
    ("each of steps 1-3", "cada una de las fases 1-3"),
    (
        "Reference rules typical of two-step evaluations; not any one firm's terms.",
        "Reglas de referencia típicas de las evaluaciones en dos fases; no son las de "
        "ninguna firma concreta.",
    ),
    (
        "Daily loss: 5 % of the initial balance below the balance recorded at 00:00 CE(S)T.",
        "Pérdida diaria: 5 % del balance inicial por debajo del balance registrado a las "
        "00:00 CE(S)T.",
    ),
    ("No time limit ({url}).", "Sin límite de tiempo ({url})."),
    (
        "Maximum loss is an end-of-day trailing limit; whether it stops trailing was not "
        "stated on the page read, so the simulator lets it trail (stricter).",
        "La pérdida máxima es un límite que sigue al cierre de cada día; la página leída no "
        "dice si deja de moverse, así que el simulador lo deja moverse (más estricto).",
    ),
    (
        "Best Day Rule: the best day may not exceed 50 % of the positive days' profit; "
        "checked when a path reaches the target, on daily closes.",
        "Regla del mejor día: el mejor día no puede superar el 50 % del beneficio de los días "
        "positivos; se comprueba cuando un recorrido llega al objetivo, con cierres diarios.",
    ),
    (
        "No minimum trading days; no time limit ({url}).",
        "Sin mínimo de días operados; sin límite de tiempo ({url}).",
    ),
    (
        "Daily loss: a percentage of the initial balance below the start-of-day balance, "
        "reset at 0:00 server time; it counts open losses, swap and commission.",
        "Pérdida diaria: un porcentaje del balance inicial por debajo del balance al empezar "
        "el día, que se reinicia a las 0:00 hora del servidor; cuenta pérdidas abiertas, "
        "swap y comisión.",
    ),
    (
        "No deadline; accounts with no trade for 60 days are deactivated.",
        "Sin plazo; las cuentas sin operaciones durante 60 días se desactivan.",
    ),
    (
        "Expert advisors are not allowed on this model.",
        "Este modelo no permite asesores expertos (EA).",
    ),
    (
        "Expert advisors allowed only on accounts below 50K.",
        "Asesores expertos (EA) permitidos solo en cuentas de menos de 50K.",
    ),
    (
        "Daily loss: 5 % below the higher of the previous day's closing balance or equity ({url}).",
        "Pérdida diaria: 5 % por debajo del mayor entre el balance y la equity al cierre del "
        "día anterior ({url}).",
    ),
    (
        "Needs 3 days each closing at least 0.5 % of the initial balance in gain; the "
        "simulator counts any day with a non-zero return, so it is optimistic here.",
        "Exige 3 días que cierren cada uno con al menos un 0.5 % del balance inicial a favor; "
        "el simulador cuenta cualquier día con retorno distinto de cero, así que aquí es "
        "optimista.",
    ),
    (
        "No trading from 2 minutes before to 2 minutes after high-impact news; not simulated.",
        "No se opera desde 2 minutos antes hasta 2 minutos después de noticias de alto "
        "impacto; no se simula.",
    ),
    (
        "The 3 % daily limit suspends trading for the day instead of ending the account; not "
        "simulated.",
        "El límite diario del 3 % suspende la operativa ese día en lugar de cerrar la cuenta; "
        "no se simula.",
    ),
    (
        "Static stop-out at 6 %: stated on The5ers' blog, not on the rules page.",
        "Stop-out fijo al 6 %: lo indica el blog de The5ers, no la página de reglas.",
    ),
    ("No minimum days; unlimited time.", "Sin mínimo de días; tiempo ilimitado."),
    (
        "The rules page table asks for 3 days that close in gain, while its text says there "
        "is no minimum days requirement; the simulator uses none (optimistic if the table "
        "applies).",
        "La tabla de la página de reglas pide 3 días que cierren en ganancia, pero su texto dice "
        "que no hay mínimo de días; el simulador no aplica ninguno (optimista si rige la tabla).",
    ),
    ("Unlimited time.", "Tiempo ilimitado."),
    (
        "No daily limit during the evaluation steps; static loss stated on The5ers' blog.",
        "Sin límite diario en las fases de evaluación; la pérdida fija la indica el blog "
        "de The5ers.",
    ),
    (
        "No position may risk more than 2 % of the balance at its stop loss; not simulated.",
        "Ninguna posición puede arriesgar más del 2 % del balance en su stop de pérdida; "
        "no se simula.",
    ),
    (
        "Unlimited time, but each level is reachable for 48 hours after the previous one.",
        "Tiempo ilimitado, pero cada nivel solo se puede alcanzar durante 48 horas tras "
        "el anterior.",
    ),
    (
        "Maximum loss trails the highest end-of-day balance and locks once it reaches the "
        "starting balance; it is monitored in real time, which daily data cannot see.",
        "La pérdida máxima sigue al mayor balance de cierre diario y se fija al llegar al "
        "balance inicial; se vigila en tiempo real, cosa que los datos diarios no ven.",
    ),
    (
        "The daily loss limit is optional and not simulated.",
        "El límite de pérdida diaria es opcional y no se simula.",
    ),
    (
        "Consistency target: the best day must stay at or below 55 % of the profit target, "
        "otherwise the target rises; checked when a path reaches the target, on daily closes.",
        "Objetivo de consistencia: el mejor día debe quedar en el 55 % del objetivo de "
        "beneficio o menos; si no, el objetivo sube; se comprueba cuando un recorrido llega "
        "al objetivo, con cierres diarios.",
    ),
    ("No time limit stated on the pages read.", "Las páginas leídas no indican límite de tiempo."),
    (
        "Source for the target and consistency rule: {url}",
        "Fuente del objetivo y de la regla de consistencia: {url}",
    ),
    # audit/luck.py
    (
        "the curve never falls below a previous high",
        "la curva nunca cae por debajo de un máximo previo",
    ),
    (
        "the Sharpe ratio is zero or negative; there is no gain to discount",
        "el Sharpe es cero o negativo; no hay ganancia que descontar",
    ),
    ("too short a history to discount", "historial demasiado corto para descontar"),
    ("annualised Sharpe of the uploaded history", "Sharpe anualizado del historial aportado"),
    (
        "best annualised Sharpe {n} trials with no skill would show",
        "mejor Sharpe anualizado que mostrarían {n} intentos sin habilidad",
    ),
    ("first to last date of the uploaded history", "de la primera a la última fecha del historial"),
    (
        "years of history at which the luck of {n} trials falls below this Sharpe",
        "años de historial con los que la suerte de {n} intentos queda por debajo de este Sharpe",
    ),
    (
        "one-sided p-value of the Sharpe, one test, with the spread of the deflated Sharpe",
        "valor p unilateral del Sharpe, una sola prueba, con la dispersión del Sharpe deflactado",
    ),
    ("p-value x {n} (Bonferroni)", "valor p x {n} (Bonferroni)"),
    (
        "annualised Sharpe after discounting {n} trials",
        "Sharpe anualizado después de descontar {n} intentos",
    ),
    ("share of the Sharpe the haircut removes", "parte del Sharpe que quita el descuento"),
    (
        "E[max Sharpe] of unskilled trials (Bailey & Lopez de Prado); minimum backtest "
        "length (Bailey, Borwein, Lopez de Prado & Zhu); Bonferroni haircut (Harvey & Liu)",
        "E[Sharpe máximo] de intentos sin habilidad (Bailey y López de Prado); longitud "
        "mínima del backtest (Bailey, Borwein, López de Prado y Zhu); descuento de "
        "Bonferroni (Harvey y Liu)",
    ),
    # audit/account.py: trades on the little a withdrawal left
    (
        "days with a trade result larger than the balance a withdrawal left, measured on the "
        "balance before that withdrawal",
        "días con un resultado mayor que el saldo que dejó un retiro, medidos sobre el saldo "
        "de antes de ese retiro",
    ),
    # audit/streaks.py
    (
        "too many trades to count the streak exactly",
        "demasiadas operaciones para contar la racha con exactitud",
    ),
    ("needs both losing and other trades", "necesita operaciones perdedoras y no perdedoras"),
    (
        "median longest losing run when trades lose as often as these, in random order",
        "mediana de la racha perdedora más larga con el mismo porcentaje de perdedoras, "
        "en orden al azar",
    ),
    (
        "longest losing run chance reaches once in twenty, at the same loss rate",
        "racha perdedora que el azar alcanza 1 de cada 20 veces, con el mismo porcentaje "
        "de perdedoras",
    ),
    (
        "chance of a losing run at least this long, at the same loss rate",
        "probabilidad de una racha perdedora al menos así de larga, con el mismo "
        "porcentaje de perdedoras",
    ),
    # audit/ride.py
    ("fewer than twenty points on the curve", "menos de veinte puntos en la curva"),
    ("the curve reaches zero or below", "la curva llega a cero o por debajo"),
    (
        "calendar days from a high until it is regained",
        "días naturales desde un máximo hasta recuperarlo",
    ),
    ("deepest fall from a previous high", "mayor caída desde un máximo previo"),
    ("high to low", "del máximo al mínimo"),
    ("low to high", "del mínimo al máximo anterior"),
    (
        "not regained by the last date of the file",
        "no se recupera antes de la última fecha del archivo",
    ),
    ("from each day's last point", "con el último punto de cada día"),
    ("the curve has no point on most days", "la curva no tiene puntos en la mayoría de los días"),
    ("fewer than three calendar months", "menos de tres meses naturales"),
    (
        "calendar days from the uploaded equity curve; months from each month's last point",
        "días naturales de la curva de equity aportada; meses con el último punto de cada mes",
    ),
)

#: The same sentences when their count ``{n}`` is 1: English template ->
#: (English singular, Spanish singular). The result JSON keeps the ``(s)``
#: form; a page shows the singular for one item and the plural otherwise.
_SINGULAR: dict[str, tuple[str, str]] = {
    "{n} row(s) of differences between the fund and its benchmark left out": (
        "{n} row of differences between the fund and its benchmark left out",
        "{n} fila de diferencias entre el fondo y su índice de referencia fuera del análisis",
    ),
    "{n} future period(s) with no change dropped (they have not happened yet)": (
        "{n} future period with no change dropped (it has not happened yet)",
        "se descartó {n} periodo futuro sin cambio (todavía no ha ocurrido)",
    ),
    "{n} row(s) with an unreadable timestamp or value dropped": (
        "{n} row with an unreadable timestamp or value dropped",
        "se descartó {n} fila con fecha o valor ilegible",
    ),
    "{n} trade row(s) with unreadable or non-positive fields dropped": (
        "{n} trade row with unreadable or non-positive fields dropped",
        "se descartó {n} fila de operaciones con campos ilegibles o no positivos",
    ),
    "{n} row(s) with unreadable or non-positive fields dropped": (
        "{n} row with unreadable or non-positive fields dropped",
        "se descartó {n} fila con campos ilegibles o no positivos",
    ),
    "{n} closing deal(s) had no matching open volume; their money is in the balance but "
    "not in the trade list": (
        "{n} closing deal had no matching open volume; its money is in the balance but "
        "not in the trade list",
        "{n} cierre no tenía volumen abierto con el que emparejarse; su dinero está en el "
        "balance pero no en la lista de operaciones",
    ),
    "{n} position(s) still open at the end of the report; excluded from the closed trades": (
        "{n} position still open at the end of the report; excluded from the closed trades",
        "{n} posición seguía abierta al final del informe; queda fuera de las operaciones cerradas",
    ),
    "{n} deal(s) closed by the tester at the end of the test": (
        "{n} deal closed by the tester at the end of the test",
        "el probador cerró {n} operación al final de la prueba",
    ),
    "{n} trade(s) closed by the tester at the end of the test": (
        "{n} trade closed by the tester at the end of the test",
        "el probador cerró {n} operación al final de la prueba",
    ),
    "{n} row(s) without a readable date or amount were left out": (
        "{n} row without a readable date or amount was left out",
        "se dejó fuera {n} fila sin fecha o cifra legible",
    ),
    "{n} more row(s) with an unreadable time were left out": (
        "{n} more row with an unreadable time was left out",
        "se dejó fuera {n} fila más con hora ilegible",
    ),
    "{n} repeated row(s) (the same position listed twice) counted once": (
        "{n} repeated row (the same position listed twice) counted once",
        "{n} fila repetida (la misma posición listada dos veces) se contó una sola vez",
    ),
    "{n} position(s) opened in the report were not closed; excluded": (
        "{n} position opened in the report was not closed; excluded",
        "{n} posición abierta en el informe no se cerró; queda fuera",
    ),
    "{n} close row(s) referenced an unknown ticket and were linked to the one open ticket "
    "with the same size": (
        "{n} close row referenced an unknown ticket and was linked to the one open ticket "
        "with the same size",
        "{n} fila de cierre citaba un ticket desconocido y se unió al único ticket abierto "
        "del mismo tamaño",
    ),
    "{n} close row(s) could not be paired with an entry; their money is in the balance "
    "but not in the trade list": (
        "{n} close row could not be paired with an entry; its money is in the balance "
        "but not in the trade list",
        "{n} fila de cierre no se pudo emparejar con una entrada; su dinero está en el "
        "balance pero no en la lista de operaciones",
    ),
    "{n} position(s) never closed; excluded": (
        "{n} position never closed; excluded",
        "{n} posición nunca se cerró; queda fuera",
    ),
    "{n} credit row(s) excluded: broker credit is not the trader's balance": (
        "{n} credit row excluded: broker credit is not the trader's balance",
        "se excluyó {n} fila de crédito: el crédito del bróker no es balance del trader",
    ),
    "{n} open trade(s) at the end of the export; excluded": (
        "{n} open trade at the end of the export; excluded",
        "{n} operación abierta al final de la exportación; queda fuera",
    ),
    "{n} trade number(s) without one entry and one exit row": (
        "{n} trade number without one entry and one exit row",
        "{n} número de operación sin una fila de entrada y una de salida",
    ),
    "{n} fee(s) charged in another coin than the price were left out of the costs, so "
    "costs are understated": (
        "{n} fee charged in another coin than the price was left out of the costs, so costs "
        "are understated",
        "{n} comisión cobrada en otra moneda distinta a la del precio quedó fuera de los "
        "costes, así que los costes están subestimados",
    ),
    "{n} multi-leg trade(s) kept as single trades": (
        "{n} multi-leg trade kept as a single trade",
        "{n} operación de varias patas se trata como una sola",
    ),
    "{n} open trade(s) excluded": (
        "{n} open trade excluded",
        "se excluyó {n} operación abierta",
    ),
    "{n} day(s) with a trade result larger than the balance a withdrawal left (first on "
    "{date}) were measured on the balance before that withdrawal": (
        "{n} day with a trade result larger than the balance a withdrawal left (first on "
        "{date}) was measured on the balance before that withdrawal",
        "{n} día con un resultado mayor que el saldo que dejó un retiro (el primero, {date}) "
        "se midió sobre el saldo previo a ese retiro",
    ),
    "{n} cash flow(s) after the last trade ignored": (
        "{n} cash flow after the last trade ignored",
        "se ignoró {n} movimiento de dinero posterior a la última operación",
    ),
    "{n} Balance cell(s) do not equal the previous balance plus the row's money; the "
    "reported Balance was kept": (
        "{n} Balance cell does not equal the previous balance plus the row's money; the "
        "reported Balance was kept",
        "{n} celda de Balance no es el balance anterior más el dinero de la fila; se "
        "mantuvo el Balance del informe",
    ),
    "{n} repeated pass number(s) counted once": (
        "{n} repeated pass number counted once",
        "{n} número de pasada repetido se contó una vez",
    ),
    "{n} equity value(s) at or below zero; returns are undefined there": (
        "{n} equity value at or below zero; returns are undefined there",
        "{n} valor de equity en cero o por debajo; ahí los retornos no están definidos",
    ),
    "{n} duplicated timestamp(s); the last value was kept": (
        "{n} duplicated timestamp; the last value was kept",
        "{n} fecha duplicada; se conservó el último valor",
    ),
    "{n} single-period move(s) are extreme outliers; check for bad prints": (
        "{n} single-period move is an extreme outlier; check for bad prints",
        "{n} movimiento de un solo periodo es un atípico extremo; revisa si hay precios erróneos",
    ),
    "{n} trial(s) declared but the files show {m} variants or optimisation passes; the "
    "declared count is too low": (
        "{n} trial declared but the files show {m} variants or optimisation passes; the "
        "declared count is too low",
        "se declaró {n} intento pero los archivos muestran {m} variantes o pasadas de "
        "optimización; el número declarado es demasiado bajo",
    ),
    "{n} trade row(s) dropped as unreadable": (
        "{n} trade row dropped as unreadable",
        "se descartó {n} fila de operaciones ilegible",
    ),
    "{n} deposit(s) arrived while the account was at least {p} below its peak": (
        "{n} deposit arrived while the account was at least {p} below its peak",
        "{n} depósito llegó cuando la cuenta estaba al menos un {p} por debajo de su máximo",
    ),
    "{n} trade(s) fall outside the dates the header says were tested; ask for the "
    "original report file": (
        "{n} trade falls outside the dates the header says were tested; ask for the "
        "original report file",
        "{n} operación queda fuera de las fechas que el encabezado dice que se probaron; "
        "pide el archivo original del informe",
    ),
    "PSR against E[max Sharpe] of {n} trial(s)": (
        "PSR against E[max Sharpe] of {n} trial",
        "PSR frente a E[Sharpe máximo] de {n} intento",
    ),
    "PSR against E[max Sharpe] of {n} trial(s), {source}": (
        "PSR against E[max Sharpe] of {n} trial, {source}",
        "PSR frente a E[Sharpe máximo] de {n} intento, {source}",
    ),
}

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _compile(english: str) -> re.Pattern[str]:
    parts: list[str] = []
    position = 0
    for match in _PLACEHOLDER.finditer(english):
        parts.append(re.escape(english[position : match.start()]))
        parts.append(f"(?P<{match.group(1)}>.+?)")
        position = match.end()
    parts.append(re.escape(english[position:]))
    return re.compile("".join(parts), re.DOTALL)


_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = tuple(
    (english, _compile(english), spanish) for english, spanish in _RULES_SOURCE
)


def _translate_values(values: dict[str, str]) -> dict[str, str]:
    """Placeholders that are themselves fixed English phrases."""
    out = dict(values)
    if "what" in out:
        out["what"] = _COMPARED.get(out["what"], out["what"])
    if "source" in out:
        source = out["source"]
        out["source"] = _TRIAL_SOURCES.get(source, _INITIAL_SOURCES.get(source, source))
    return out


def _render(text: str, locale: str) -> str | None:
    """``text`` as a rule writes it in ``locale``, or ``None`` when no rule knows it.

    English comes back unchanged except for a count of one, which takes the
    singular sentence.
    """
    head, sep, rest = text.partition(": ")
    if sep and head in _PREFIXES:
        inner = _render(rest, locale)
        if inner is None:
            return None
        return f"{_PREFIXES[head] if locale == 'es' else head}: {inner}"
    if locale == "es" and text in NOT_MEASURED_ES:
        return NOT_MEASURED_ES[text]
    if locale == "es" and text in _TRIAL_SOURCES:
        return _TRIAL_SOURCES[text]
    for english, pattern, template in _RULES:
        match = pattern.fullmatch(text)
        if not match:
            continue
        values = match.groupdict()
        singular = _SINGULAR.get(english) if values.get("n") == "1" else None
        if locale == "es":
            chosen = singular[1] if singular else template
            return chosen.format(**_translate_values(values))
        return singular[0].format(**values) if singular else text
    return None


def spanish(text: str) -> str | None:
    """The Spanish for one of the audit's English sentences, or ``None``."""
    return _render(text, "es")


#: A word with an optional plural ending, as the English notes write it.
_PLURAL_MARK = re.compile(r"(\w+)\((e?s)\)")
_LAST_NUMBER = re.compile(r"(\d[\d,.]*)\D*$")


def _agree(text: str) -> str:
    """Resolve ``word(s)`` from the nearest count before it: one or many."""

    def fix(match: re.Match[str]) -> str:
        word, ending = match.group(1), match.group(2)
        count = _LAST_NUMBER.search(text[: match.start()])
        if count is not None and count.group(1) == "1":
            return word
        if ending == "es" and word.endswith("ión"):
            word = word[:-3] + "ion"
        return word + ending

    return _PLURAL_MARK.sub(fix, text)


def localize(text: str, locale: str) -> str:
    """``text`` in ``locale``: Spanish when a rule knows it, else unchanged.

    Either way a count reads as one item or several, never ``item(s)``.
    """
    if not text:
        return text
    rendered = _render(text, "es" if locale == "es" else "en")
    return _agree(text if rendered is None else rendered)


def _result_sentences(data: dict[str, Any]) -> Iterable[str]:
    """Every engine-written English sentence a Spanish page may show."""
    inputs = data.get("inputs", {})
    yield from inputs.get("parse_warnings", [])
    for flag in data.get("red_flags", []):
        yield flag.get("detail", "")
    challenge = data.get("challenge") or {}
    yield from (challenge.get("rules") or {}).get("notes") or []

    def walk(node: Any) -> Iterable[str]:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("note", "reason") and isinstance(value, str):
                    yield value
                elif key not in ("declared", "rules", "assumptions", "vendor_questions"):
                    yield from walk(value)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)

    for key, value in data.items():
        if key not in ("declared", "verdict", "red_flags", "vendor_questions"):
            yield from walk(value)
    yield from walk(data.get("declared", {}))


def untranslated(data: dict[str, Any]) -> list[str]:
    """Sentences of a result (as JSON) that no Spanish rule covers."""
    missing: list[str] = []
    for text in _result_sentences(data):
        if text and spanish(text) is None and text not in missing:
            missing.append(text)
    return missing


__all__ = ["localize", "spanish", "untranslated"]
