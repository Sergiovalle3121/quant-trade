"""Portuguese for the reasons an upload is refused.

Every ``ParseError`` carries its English message and a Spanish twin; a
visitor who uploads from ``/pt`` reads the refusal in Portuguese through
:func:`portuguese`, which matches the English message against the rules
below (the same way ``i18n`` translates the report's notes). A message no
rule knows stays in English, never half-translated, and a test walks every
refusal in the importers so a new one cannot ship without its rule.

Placeholders are values from the file (a date, a column name, a count) and
are kept as they are, except the few that are fixed English words (which
file, which field), translated from the small tables here.
"""

from __future__ import annotations

import re
from collections.abc import Callable

#: The uploaded file named in "the {what} file ...": the form field, or
#: ``schema._FILE_EN``'s words for it.
FILES_PT: dict[str, str] = {
    "equity": "da curva de equity",
    "benchmark": "do benchmark",
    "trades": "de operações",
    "variants": "de variantes",
    "report": "do relatório",
    "optimization": "de otimização",
    "live": "do extrato da conta real",
    "live account statement": "do extrato da conta real",
}

#: The fields of a list of trades, as ``universal._ROLE_TEXT["en"]`` and
#: ``universal.ROLE_WORDS`` name them.
FIELDS_PT: dict[str, str] = {
    "entry time": "hora de entrada",
    "exit time": "hora de saída",
    "quantity": "quantidade",
    "entry price": "preço de entrada",
    "exit price": "preço de saída",
    "time": "hora",
    "price": "preço",
    "symbol": "símbolo",
    "side": "lado",
    "profit": "resultado",
    "commission": "comissão",
    "swap": "swap",
    "multiplier": "multiplicador",
    "account": "conta",
    "fill time": "hora da execução",
    "fill price": "preço da execução",
    "trade result": "resultado da operação",
}

_KINDS_PT = {"dates": "datas", "numbers": "números"}
_TEST_PARTS_PT = {
    "robot": "robô",
    "symbol": "símbolo",
    "timeframe": "período gráfico",
    "inputs": "parâmetros",
}

_UNKNOWN_FORMAT_PT = (
    "o arquivo não é um relatório compatível. Esperado: um relatório ou extrato do "
    "MetaTrader 5 ou 4 (HTML, ou XLSX no MetaTrader 5), uma lista de operações do "
    "TradingView (CSV ou XLSX), um CSV de operações ou execuções do NinjaTrader, um CSV de "
    "operações do QuantConnect, backtesting.py ou vectorbt, um CSV de histórico de conta do "
    "Myfxbook, FX Blue ou de um sinal da MQL5, ou qualquer lista em CSV ou Excel com uma "
    "operação ou uma execução por linha (hora de entrada e de saída, quantidade e preços)"
)

#: (English as the importers write it, Portuguese). ``{name}`` is a value
#: kept or translated by :data:`_VALUES`.
RULES: tuple[tuple[str, str], ...] = (
    # schema.py: the equity curve, benchmark, trades and variants files.
    ("the {what} file is empty", "o arquivo {what} está vazio"),
    ("the {what} file is {size} bytes; the limit is {limit}",
     "o arquivo {what} tem {size} bytes; o limite é {limit}"),
    ("a line of the {what} file is longer than {limit} bytes; it does not look like a CSV "
     "with one row per line",
     "uma linha do arquivo {what} passa de {limit} bytes; não parece um CSV com uma linha "
     "por registro"),
    ("the {what} file is not UTF-8 text", "o arquivo {what} não é texto UTF-8"),
    ("the {what} file could not be read as CSV: {detail}",
     "o arquivo {what} não pôde ser lido como CSV: {detail}"),
    ("the {what} file has {rows} rows; the limit is {limit}",
     "o arquivo {what} tem {rows} linhas; o limite é {limit}"),
    ('the equity curve file looks like a list of trades, not a curve: upload it in the '
     '"Your platform report" box',
     'o arquivo da curva de equity parece uma lista de operações, não uma curva: envie-o no '
     'campo "Relatório da sua plataforma"'),
    ("the {what} file needs a timestamp column (one of: {names})",
     "o arquivo {what} precisa de uma coluna de data (uma de: {names})"),
    ("the {what} file needs an equity column (one of: {names}) or a return column (one of: "
     "{returns})",
     "o arquivo {what} precisa de uma coluna de equity (uma de: {names}) ou de uma coluna "
     "de retorno (uma de: {returns})"),
    ("the {what} file has fewer than two usable rows",
     "o arquivo {what} tem menos de duas linhas utilizáveis"),
    ("the {what} file has a value too large to be real on {when} (over {limit}): check "
     "that the file's values were exported correctly and upload it again",
     "o arquivo {what} tem um valor grande demais para ser real em {when} (acima de "
     "{limit}): confira se os valores do arquivo foram exportados corretamente e envie-o "
     "de novo"),
    ("the {what} file reaches zero or a negative value on {when}; the audit needs the "
     "account balance (for example 10000 growing to 12500), not a cumulative profit that "
     "starts at 0",
     "o arquivo {what} chega a zero ou a um valor negativo em {when}; a auditoria precisa "
     "do saldo da conta (por exemplo 10000 que cresce até 12500), não de um lucro acumulado "
     "que começa em 0"),
    ("the {what} file has a return of -100 % or worse on {when}, which would leave the "
     "account at zero or below",
     "o arquivo {what} tem um retorno de -100 % ou pior em {when}, o que deixaria a conta "
     "em zero ou abaixo"),
    ("the trades file has {rows} rows; the limit is {limit}",
     "o arquivo de operações tem {rows} linhas; o limite é {limit}"),
    ("the trades file is missing column(s): {columns} (entry_time, exit_time, quantity, "
     "entry_price, exit_price are required)",
     "faltam colunas no arquivo de operações: {columns} (são obrigatórias entry_time, "
     "exit_time, quantity, entry_price e exit_price)"),
    ("the trades file contains no usable trades",
     "o arquivo de operações não tem nenhuma operação utilizável"),
    ("the variants file needs at least two numeric return columns",
     "o arquivo de variantes precisa de pelo menos duas colunas numéricas de retorno"),
    ("the variants file has {columns} columns; the limit is {limit}",
     "o arquivo de variantes tem {columns} colunas; o limite é {limit}"),
    ("the variants file contains empty or non-numeric cells",
     "o arquivo de variantes tem células vazias ou não numéricas"),
    ("the variants file needs at least 16 rows",
     "o arquivo de variantes precisa de pelo menos 16 linhas"),
    ("the {what} file has a date in the future ({day}): a track record can only hold "
     "dates that have already happened; check the file's dates and upload it again",
     "o arquivo {what} tem uma data no futuro ({day}): um histórico só pode ter datas que "
     "já aconteceram; confira as datas do arquivo e envie-o de novo"),
    ("upload either a platform report or a trades file, not both",
     "envie um relatório da plataforma ou um arquivo de operações, não os dois"),
    ("an equity curve or a platform report is required",
     "é preciso uma curva de equity ou um relatório da plataforma"),
    ("the optimisation file is for another test ({part} {theirs}; the report says {ours}): "
     "upload the optimisation of the same robot, symbol and timeframe",
     "o arquivo de otimização é de outro teste ({part} {theirs}; o relatório diz {ours}): "
     "envie a otimização do mesmo robô, símbolo e período gráfico"),
    # importers.py: platform reports.
    ("the file is empty", "o arquivo está vazio"),
    ("the file is {size} bytes; the limit is {limit}",
     "o arquivo tem {size} bytes; o limite é {limit}"),
    ("the dates could be day/month or month/day; export them as YYYY-MM-DD (for example "
     "switch the platform to English) and upload again",
     "as datas podem ser dia/mês ou mês/dia; exporte-as como AAAA-MM-DD (por exemplo, "
     "com a plataforma em inglês) e envie de novo"),
    ("the file could not be read as a delimited list of trades",
     "o arquivo não pôde ser lido como uma lista de operações separada por vírgulas"),
    ("the file declares a document type, which is refused for safety",
     "o arquivo declara um tipo de documento, o que é recusado por segurança"),
    ("the XML could not be read: {detail}", "não foi possível ler o XML: {detail}"),
    ("the workbook inflates past the size limit; export the list of trades as CSV instead",
     "a planilha passa do limite de tamanho ao ser aberta; exporte a lista de operações "
     "como CSV"),
    ("the workbook could not be opened", "não foi possível abrir a planilha"),
    ("the workbook is damaged or encrypted and could not be read",
     "a planilha está danificada ou criptografada e não pôde ser lida"),
    ("the workbook has no sheets", "a planilha não tem nenhuma aba"),
    ("the TradingView list of trades is missing column(s): {columns}; export it with "
     "TradingView in English",
     "faltam colunas na lista de operações do TradingView: {columns}; exporte-a com o "
     "TradingView em inglês"),
    ("this NinjaTrader executions export has no profit per trade, and the point value of "
     "{symbols} is not in our table; export the Trades tab instead (Account Performance or "
     "Strategy Analyzer > Trades), which carries each trade's profit",
     "esta exportação de execuções do NinjaTrader não tem o resultado de cada operação, e "
     "o valor do ponto de {symbols} não está na nossa tabela; exporte a aba Trades "
     "(Account Performance ou Strategy Analyzer > Trades), que traz o resultado de cada "
     "operação"),
    ("the reconstructed balance reaches zero or below; state the real starting balance so "
     "returns can be computed",
     "o saldo reconstruído chega a zero ou abaixo; informe o saldo inicial real para que "
     "os retornos possam ser calculados"),
    ("the balance reaches zero or below on {day}: the account lost all its money, so "
     "returns after that day cannot be computed; upload the history up to that day to "
     "audit it",
     "o saldo chega a zero ou abaixo em {day}: a conta perdeu todo o dinheiro, então os "
     "retornos depois desse dia não podem ser calculados; envie o histórico até esse dia "
     "para auditá-lo"),
    ("the file has no closed trades: 1 position opened and never closed in the file",
     "o arquivo não tem operações fechadas: 1 posição foi aberta e não foi fechada no "
     "arquivo"),
    ("the file has no closed trades: {count} positions opened and never closed in the file",
     "o arquivo não tem operações fechadas: {count} posições foram abertas e não foram "
     "fechadas no arquivo"),
    ("no closed trade has positive prices and volume",
     "nenhuma operação fechada tem preços e volume positivos"),
    ("the file has no closed trades", "o arquivo não tem operações fechadas"),
    ("the file has {count} closed trades; the limit is {limit}",
     "o arquivo tem {count} operações fechadas; o limite é {limit}"),
    ("a trade closed on {when} has a price, quantity or profit too large to be real: check "
     "that the file's values were exported correctly and upload it again",
     "uma operação fechada em {when} tem um preço, uma quantidade ou um resultado grande "
     "demais para ser real: confira se os valores do arquivo foram exportados corretamente "
     "e envie-o de novo"),
    ("every trade closes before it opens: check that the entry and exit time columns are "
     "not swapped",
     "todas as operações fecham antes de abrir: confira se as colunas de hora de entrada "
     "e de saída não estão trocadas"),
    ("this is an old Excel workbook (.xls), which cannot be read: open it in Excel, "
     "LibreOffice or Google Sheets and save it as .xlsx or CSV, then upload that file",
     "esta é uma planilha antiga do Excel (.xls), que não pode ser lida: abra-a no Excel, "
     "LibreOffice ou Google Sheets, salve como .xlsx ou CSV e envie esse arquivo"),
    ("a PDF is a printed statement, not data that can be read: download the history from "
     "the platform as CSV, Excel or HTML instead (the guides show where)",
     "um PDF é um extrato impresso, não dados que possam ser lidos: baixe o histórico da "
     "plataforma em CSV, Excel ou HTML (os guias mostram onde)"),
    ("this is an OpenDocument sheet (.ods), which cannot be read: save it as .xlsx or CSV "
     "and upload that file",
     "esta é uma planilha OpenDocument (.ods), que não pode ser lida: salve como .xlsx ou "
     "CSV e envie esse arquivo"),
    ("the zip holds no CSV, Excel or HTML export; upload the export itself",
     "o zip não contém nenhuma exportação em CSV, Excel ou HTML; envie a própria "
     "exportação"),
    ("the zip holds {count} exports; upload the one with the trades on its own (CSV, Excel "
     "or HTML)",
     "o zip contém {count} exportações; envie sozinha a que tem as operações (CSV, Excel "
     "ou HTML)"),
    ("the file in the zip is larger than the limit of {limit} bytes",
     "o arquivo dentro do zip passa do limite de {limit} bytes"),
    ("the zip is damaged or encrypted and could not be read",
     "o zip está danificado ou criptografado e não pôde ser lido"),
    ("the file is not a supported report. Expected: a MetaTrader 5 or 4 report or statement "
     "(HTML, or XLSX for MetaTrader 5), a TradingView list of trades (CSV or XLSX), a trades "
     "or executions CSV from NinjaTrader, a trades CSV from QuantConnect, backtesting.py or "
     "vectorbt, an account history CSV from Myfxbook, FX Blue or an MQL5 signal, or any CSV "
     "or Excel list with one trade or one fill per row (entry and exit time, quantity and "
     "prices)",
     _UNKNOWN_FORMAT_PT),
    ("column mapping works on a CSV or Excel list of trades; this file is a report page: "
     "upload it without choosing columns",
     "a escolha de colunas funciona com uma lista de operações em CSV ou Excel; este "
     "arquivo é uma página de relatório: envie-o sem escolher colunas"),
    ("these columns are not in the file's header: {columns}; check their names",
     "estas colunas não estão no cabeçalho do arquivo: {columns}; confira os nomes"),
    ("the columns you chose are not in the file's header; check their names",
     "as colunas que você escolheu não estão no cabeçalho do arquivo; confira os nomes"),
    ("the starting balance must be a positive number",
     "o saldo inicial precisa ser um número positivo"),
    ("this is a MetaTrader 5 optimisation export: upload it as the optimisation file, and "
     "the single-test report as the report",
     "esta é uma exportação de otimização do MetaTrader 5: envie-a como arquivo de "
     "otimização, e o relatório do teste único como relatório"),
    ("expected a MetaTrader 5 optimisation export (XML, 'Tester Optimizator Results')",
     "esperava-se uma exportação de otimização do MetaTrader 5 (XML, 'Tester Optimizator "
     "Results')"),
    ("we do not recognise the column names of this optimisation file; export it with the "
     "terminal in English or Spanish (View > Languages)",
     "não reconhecemos os nomes das colunas deste arquivo de otimização; exporte-o com o "
     "terminal em inglês ou espanhol (Exibir > Idiomas)"),
    ("the optimisation file lists no passes",
     "o arquivo de otimização não traz nenhuma passagem"),
    # universal.py and mapping.py: any list of trades, and columns named by hand.
    ("the column '{name}' was chosen for two fields ({field} and {other}); choose a "
     "different column for each",
     "a coluna '{name}' foi escolhida para dois campos ({field} e {other}); escolha uma "
     "coluna diferente para cada um"),
    ("the column '{name}' is not in the file", "a coluna '{name}' não está no arquivo"),
    ("the file gives each trade's closing time but not its opening time, so holding times "
     "and entry timing cannot be measured: export the list of executions (fills) instead, "
     "for example Bybit's Trade History, and upload that",
     "o arquivo traz a hora de fechamento de cada operação, mas não a de abertura, então "
     "não dá para medir a duração nem o momento de entrada: exporte a lista de execuções, "
     "por exemplo o Trade History da Bybit, e envie esse arquivo"),
    ("the file has no column we recognise as {fields}. Columns found: {columns}. Name them "
     "under 'Platform not listed, or its file fails? Name its columns' on the form, or "
     "rename those columns in the file (for example Entry time, Exit time, Quantity, Entry "
     "price, Exit price) and upload it again",
     "o arquivo não tem uma coluna que reconheçamos como {fields}. Colunas encontradas: "
     "{columns}. Indique-as em 'A sua plataforma não aparece ou o arquivo dá erro? Indique "
     "as colunas' no formulário, ou renomeie essas colunas no arquivo (por exemplo Entry "
     "time, Exit time, Quantity, Entry price, Exit price) e envie-o de novo"),
    ('the column "{name}" you chose as {field} holds no {kind}',
     'a coluna "{name}" que você escolheu como {field} não tem {kind}'),
    ("Your file: with those columns fewer than two rows have a readable date and figure. "
     "Check that the date and the figure are the right columns.",
     "Seu arquivo: com essas colunas, menos de duas linhas têm data e valor legíveis. "
     "Confira se a data e o valor são as colunas certas."),
    ("the results add up to zero or less on {day} from a starting balance of {start}: state "
     "the account's starting balance on the form and upload it again",
     "os resultados somam zero ou menos em {day} a partir de um saldo inicial de {start}: "
     "informe o saldo inicial da conta no formulário e envie-o de novo"),
    # factsheet.py: a fund's table of monthly returns.
    ("the file looks like a monthly returns table (one column per month) but not every row "
     "with returns has a year such as 2021 in its first column",
     "o arquivo parece uma tabela de retornos mensais (uma coluna por mês), mas nem toda "
     "linha com retornos tem um ano como 2021 na primeira coluna"),
    ("the file looks like a monthly returns table (one column per month) but a benchmark "
     "row has no year and no fund row above it",
     "o arquivo parece uma tabela de retornos mensais (uma coluna por mês), mas uma linha "
     "do benchmark não tem ano nem uma linha do fundo acima dela"),
    ("the monthly returns table lists {years} more than once; keep one row per year",
     "a tabela de retornos mensais repete {years}; deixe uma linha por ano"),
)  # fmt: skip

#: The live statement's refusals are the report's, said of that file.
LIVE_PREFIX = ("the live account statement: ", "extrato da conta real: ")


def _fields(value: str) -> str:
    return ", ".join(FIELDS_PT.get(part, part) for part in value.split(", "))


_VALUES: dict[str, Callable[[str], str]] = {
    "what": lambda value: FILES_PT.get(value, value),
    "field": _fields,
    "other": _fields,
    "fields": _fields,
    "kind": lambda value: _KINDS_PT.get(value, value),
    "part": lambda value: _TEST_PARTS_PT.get(value, value),
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


_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (_compile(english), portuguese) for english, portuguese in RULES
)


def portuguese(message: str) -> str | None:
    """The Portuguese of one refusal, or ``None`` when no rule knows it."""
    text = message.strip()
    if text.startswith(LIVE_PREFIX[0]):
        inner = portuguese(text[len(LIVE_PREFIX[0]) :])
        return None if inner is None else LIVE_PREFIX[1] + inner
    for pattern, template in _COMPILED:
        match = pattern.fullmatch(text)
        if match:
            values = {
                name: _VALUES.get(name, str)(value) for name, value in match.groupdict().items()
            }
            return template.format(**values)
    return None


__all__ = ["FIELDS_PT", "FILES_PT", "LIVE_PREFIX", "RULES", "portuguese"]
