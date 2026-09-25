# MetaTrader reports in other languages

Checked on 2026-09-25. A MetaTrader terminal set to another language prints
the tester report's summary labels in that language. Until then the importer
knew Russian labels (from one real report) and Spanish labels taken from the
MetaTrader 5 help. This check ran real public reports exported in Spanish
and Italian through `import_report` and the full `quant-trade audit run
--report ...`.

The files were downloaded to a scratch directory outside the repository and
are **not committed**. The tests in `tests/test_audit_importers.py` use the
synthetic `mt5_tester.html` fixture with its labels replaced, never the
contents of these files.

## Files

| Language | Files | Where published |
|---|---|---|
| Spanish (MT5 tester) | 3 reports of one EA (MACD_RSI_STOCH V1, V2, V5; EURUSD H1, 2010 to 2021; 938 to 988 trades) | GitHub user kecoma1 |
| Italian (MT5 tester) | 5 reports of one EA (XAGUSD M12, 2025; 34 to 121 trades) | GitHub user Marco210210 |

No public report exported in Portuguese, German or French was found (GitHub
code search, Sourcegraph and the mql5.com forums). Numbers in every real
report used a dot for decimals and a space for thousands (`20 000.00`)
whatever the language.

## What broke and what changed

| Issue | Before | After |
|---|---|---|
| Real Spanish terminals print "Total de operaciones ejecutadas", "Reducción máxima del balance", "Reducción máxima de la equidad", "Reducción relativa de la equidad", "Factor de Beneficio", "Experto" and "Corredor", not the words in the help | the trade count was missing from "Lectura de tu archivo", and drawdown and profit factor were not compared | all read; the reading card shows trades and net profit matching (3 of 3) |
| Italian labels ("Deposito Iniziale", "Valuta", "Profitto Totale Netto", "Numero di Operazioni di Trading Totali", ...) were unknown | trades were read, but the currency was missing and nothing was compared with the platform's summary | all read; trades and net profit match (5 of 5) |
| A number written with a decimal comma (`1 234,56` or `1.234,56`) | read as 123456 or 1.23456 without a warning | read as 1234.56; a comma followed by exactly three digits (`1,234`) is still a thousands separator |

The decimal comma has no real public example; it is covered by a synthetic
test that rewrites every figure of the fixture (`10 000,00`, `0,2 / 0,2`) and
checks that trades, sizes, prices, costs and the deposit read the same.

## Result

| | Trades match the summary | Net profit matches | Currency and deposit read |
|---|---|---|---|
| Spanish, 3 files | 3 of 3 (was 0 of 3) | 3 of 3 | 3 of 3 |
| Italian, 5 files | 5 of 5 (was 0 of 5) | 5 of 5 (was 0 of 5) | 5 of 5 (currency was 0 of 5) |

## Limits

- Portuguese, German, French and other languages still rely on the English
  labels a terminal may keep; a report whose summary labels are all
  translated there is read from its trade rows only, and the reading card
  then has nothing to compare against.
- MetaTrader 4 reports in other languages were not found and were not tested.
