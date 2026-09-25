# MetaTrader reports in other languages

Checked on 2026-09-25. A MetaTrader terminal set to another language prints
the report's summary labels in that language. Until then the importer knew
Russian MT5 labels (from one real report) and Spanish labels taken from the
MetaTrader 5 help. This check ran 19 real public reports in seven languages
through `import_report` and the full `quant-trade audit run --report ...`,
and compared "Lectura de tu archivo" (trades and net result read from the
rows against the platform's own summary).

The files were downloaded to a scratch directory outside the repository and
are **not committed** (one of them shows an account holder's name). The
tests in `tests/test_audit_importers.py` and
`tests/test_audit_mt_languages.py` rewrite the synthetic fixtures, never the
contents of these files.

## Files

All came from public GitHub repositories.

| Language | Files | Type | Where published |
|---|---|---|---|
| Spanish | 3 (one EA, EURUSD H1, 2010 to 2021, 938 to 988 trades) | MT5 tester, UTF-16 | kecoma1/Trading_BOT |
| Italian | 5 (one EA, XAGUSD M12, 2025, 34 to 121 trades) | MT5 tester, UTF-16 | Marco210210/AI-Enhanced-HFT |
| Portuguese | 3 (US30, USDCAD, EURUSD; 25 to 684 trades) | MT4 tester, cp1252 without charset | DiogoRolo19/mql4 |
| Portuguese | 2 (Brazilian stocks CMIG4 and BRKM5, BRL account) | MT5 tester, UTF-16 | William-Brandao/Trade-mql5 |
| Russian | 3 (EURUSD 3,659 and 3,662 trades; GBPUSD D1 87 trades) | MT4 tester, cp1251 without charset | joaotorresmarques/mql4, PanPip/MQL4_experts |
| Chinese (simplified) | 1 (XAUUSD H1, 554 trades) | MT5 tester, UTF-16 | Jason767445898/QA_SQX |
| Chinese (traditional) | 1 (38 trades) | MT5 account history, UTF-8 | DaraGaloX233/MQL5_TradeRecord |
| Czech | 1 (prop-firm challenge, 14 symbols) | MT5 account history, XLSX | svopex/forex-MT5-report |

No public report exported in German or French, and no Spanish MT4 or
account history, was found (GitHub search, Sourcegraph and the mql5.com
forums, which no longer accept report attachments). Numbers in every real
report used a dot for decimals (`20 000.00` in MT5, `10000.00` in MT4)
whatever the language.

## What broke and what changed

| Issue | Before | After |
|---|---|---|
| Real Spanish terminals print "Total de operaciones ejecutadas", "Factor de Beneficio", "Reducción máxima del balance" and others the help does not use | the trade count was not compared | read |
| Italian, Portuguese, Chinese and Czech MT5 labels were unknown | no currency, nothing compared with the platform's summary | read, on tester reports and account histories |
| MT4 tester labels were read in English only | a Portuguese or Russian report's deposit was missed and 10,000 assumed (a Russian report of a 200 account was audited as 10,000) | read in Russian and Portuguese |
| A Russian MT4 report is cp1251 with no charset; it was decoded as cp1252 | every Russian label became unreadable symbols | decoded as cp1251 when Russian report words appear |
| MT4 "swap close" / "swap open" rows (a broker that closes and reopens positions at rollover) were not known | 21 of 87 trades lost, net result 755.67 read as -98.16 | the close is a trade and the reopened ticket continues the position: 87 of 87, 755.67 |
| An MT4 partial close moves the rest of the position to a new ticket | 312 positions reported "never closed" on a 684-trade report | the rest keeps its original entry time and price; no false warning |
| An MT5 account history whose account line carries the leverage (`USD, 1:500, server, ...`) | the leverage was read as the server name | leverage and server read separately |
| MetaTrader counts each partial close as a trade; the Positions table has one row per position | "Lectura de tu archivo" showed 60 against 61 | compared with the file's own closing deals (61 = 61) |
| A net swap credit (swap paid to the account) | left out of the net result, so the reading card showed 634.50 against MetaTrader's 636.20 | counted; the stress tests still count only costs (stricter) |
| Net result of thousands of trades | a 0.32 difference on 3,659 trades (each printed result rounded to the cent) showed "No coincide" | up to half a cent per trade is treated as rounding |
| A figure with a decimal comma (`1 234,56`, `1.234,56`) | read as 123456 or 1.23456 without a warning | read as 1234.56; `1,234` stays a thousands separator (no real report uses a comma; synthetic test) |

## Result

"Lectura de tu archivo" (trades and net result against the platform's own
summary), full audit through the command line:

| | Before | After |
|---|---|---|
| All 19 real reports | 0 of 19 fully compared and matching | 19 of 19 match |

## Limits

- German, French and other languages rely on the English labels a terminal
  may keep; a report whose labels are all translated there is read from its
  trade rows only, and the reading card then has nothing to compare against.
- MT4 account statements in other languages were not found and not tested.
