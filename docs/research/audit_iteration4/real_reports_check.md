# Importers against real public reports

Checked on 2026-09-24 (thread K of audit iteration 4). Until then the
importers in `src/quant_trade/audit/importers.py` had only been tested with
synthetic files. This check ran 25 real files that their authors published
on GitHub, Hugging Face or mql5.com through `detect_format`, `import_report`
(or `parse_optimization`) and the full `quant-trade audit run --report ...`.

The files were downloaded to a scratch directory outside the repository and
are **not committed**. Every fix below has a synthetic fixture that
reproduces the structure, never the contents, in
`tests/test_audit_importers.py`.

## How a file counts as read correctly

For each report the importer's figures were compared with the report's own
summary: initial deposit, number of trades ("Total Trades", or the number of
closed rows for statements), net profit (sum of trade P&L plus itemised
costs, and the last balance minus the deposit), and for MetaTrader 5 tester
reports "Balance Drawdown Maximal" (the deepest fall of the report's own
Balance column). The audit's price-recomputed gross P&L was also compared
with the platform's per-trade profit; the audit raises `TRADE_PNL_MISMATCH`
above 1 % of gross.

## Result

| | Before | After |
|---|---|---|
| MetaTrader files read (22 reports and 1 optimisation XML) | 15 of 23 | 22 of 23 |
| Reports whose trades, net profit and deposit match their summary | 12 of 22 | 21 of 22 |
| Balance drawdown matches (MT5 tester, HTML and XLSX) | not checked | 13 of 13 |
| MT5 reports with a false `TRADE_PNL_MISMATCH` (counted once they could be read) | 6 of 16 | 0 of 16 |
| Full CLI audit runs to a report that passes the guard | not run | 21 of 21, plus one with the optimisation XML |

The one MetaTrader file still refused is a statement that a third-party
script rewrote (no lots column); it is not a terminal export. The two
non-MetaTrader files are formats the service does not claim to read.

## Files tried

Format names are the importer's. "Before" is main at 8c76c98; "after" is
this change. Trades and net profit are the importer's figure / the report's
own figure.

| # | Source URL | Format | Before | After (trades; net profit) |
|---|---|---|---|---|
| 1 | https://raw.githubusercontent.com/abiodunaremu/openea/HEAD/reports/v1_1/feb2025_default/ReportTester-v1_gbpusd_feb2025.html | mt5_tester_html (UTF-16) | read, matches | 59/59; 705.80/705.80 |
| 2 | https://raw.githubusercontent.com/pranay123-stack/forex-mt5-strategies/HEAD/Forex_trading_strategies_EA_scripts/ButterflyOscillator_EA/ReportTester-52688756.html | mt5_tester_html (UTF-16) | read, matches | 70/70; -904.65/-904.65 |
| 3 | https://raw.githubusercontent.com/pranay123-stack/forex-mt5-strategies/HEAD/Forex_trading_strategies_EA_scripts/LiquidityMarketMap_EA/ReportTester-52688756.html | mt5_tester_html (UTF-16, hedging) | 881 trades vs 840; P&L mismatch 4.4 % | 840/840; -9 895.96/-9 895.96; mismatch 0 % |
| 4 | https://raw.githubusercontent.com/pranay123-stack/forex-mt5-strategies/HEAD/Forex_trading_strategies_EA_scripts/PPCorr_EA/ReportTester-52688756.html | mt5_tester_html (UTF-16) | read, matches | 175/175; -59.21/-59.21 |
| 5 | https://raw.githubusercontent.com/pranay123-stack/forex-mt5-strategies/HEAD/Forex_trading_strategies_EA_scripts/VB_EA/ReportTester-52688756.html | mt5_tester_html (UTF-16, hedging) | P&L mismatch 19.2 % | 390/390; -1 653.72/-1 653.72; mismatch 0 % |
| 6 | https://c.mql5.com/3/128/ReportTester_MACDSample.zip | mt5_tester_html (UTF-16, build 1596) | read, matches | 79/79; 393.26/393.26 |
| 7 | https://www.mql5.com/en/articles/download/5706.zip (Tester.html) | mt5_tester_html (RTS futures) | P&L mismatch 29 % | 44/44; 85.31/85.31; mismatch 0 % |
| 8 | https://www.mql5.com/en/articles/download/5913.zip (ReportTester-example_ru.html) | mt5_tester_html (Russian) | summary unread, 22 trades vs 16, mismatch 22 % | 16/16; 5 679.02/5 679.02; mismatch 0 % |
| 9 | https://www.mql5.com/en/articles/download/5436.zip (ReportTester-555849.html) | mt5_tester_html (build 1940, re-saved as UTF-8) | refused: balance reaches zero | 23/23; 17.74/17.74 |
| 10 | https://www.mql5.com/en/articles/download/5436.zip (ReportHistory-555849.html) | mt5_history_html | read, matches | 4/4; 3.41/3.41 |
| 11 | https://www.mql5.com/en/articles/download/5706.zip (ReportHistory.html) | mt5_history_html (UTF-16) | read, matches | 13/13; -33.27/-33.27 |
| 12 | https://www.mql5.com/en/articles/download/5436.zip (ReportOptimizer-555849.xml) | mt5_optimization_xml | 150 passes | 150 passes; audit with its report runs (deflated Sharpe uses 150 MEASURED trials) |
| 13 | https://raw.githubusercontent.com/geraked/metatrader5/HEAD/Test/3MACD/report.xlsx | mt5_tester_xlsx | refused: unknown format | 2518/2518; 71 112.05/71 112.05 |
| 14 | https://raw.githubusercontent.com/geraked/metatrader5/HEAD/Test/BBRSI/report.xlsx | mt5_tester_xlsx | refused: unknown format | 401/401; 36 877.30/36 877.30 |
| 15 | https://raw.githubusercontent.com/geraked/metatrader5/HEAD/Test/COT1/report.xlsx | mt5_tester_xlsx (28 crosses) | refused: unknown format | 283/283; 429 635.03/429 635.03; mismatch 0.1 % |
| 16 | https://huggingface.co/algorembrant/MT5report-parser/resolve/main/backend/%5B3%5D_Process/ReportTester-263254895.xlsx | mt5_tester_xlsx (hedging) | refused: unknown format | 361/361; 1 470.71/1 470.71; deposit 100 |
| 17 | https://www.mql5.com/en/articles/download/5706.zip (StrategyTester-ecn-1.htm) | mt4_tester_html | read, matches | 44/44; 20.14/20.14 (P&L includes ECN commission, so `TRADE_PNL_MISMATCH` 2.8 % is correct) |
| 18 | https://c.mql5.com/forextsd/forum/12/multilotscalper_1.htm | mt4_tester_html (2006) | read, matches | 3685/3685; 4 167 093.49/4 167 093.48 |
| 19 | https://c.mql5.com/forextsd/forum/2/strategytester.htm | mt4_tester_html (2005 layout) | read, matches | 16/16; 100.65/100.65 |
| 20 | https://c.mql5.com/forextsd/forum/10/sample_report.htm | mt4_statement_html (numbered, 15 columns) | refused: unknown format | 28 trades; balance 19 816.52/19 816.52 |
| 21 | https://c.mql5.com/forextsd/forum/56/detailedstatement_3.htm | mt4_statement_html (build 600+) | read, matches | 40/40; 335.77/335.77 |
| 22 | https://c.mql5.com/forextsd/forum/1/detailedstatement.htm | mt4_statement_html (2005, 13 columns) | refused: unknown format | 4/4; 36.51/36.51 |
| 23 | https://www.mql5.com/en/articles/download/1383/Bad_Trade_Report.zip | statement rewritten by a third-party script (no lots column) | refused | still refused, as intended: not a terminal export |
| 24 | https://github.com/freqtrade/freqtrade/tree/develop/tests/testdata/backtest_results | freqtrade backtest JSON | refused | not supported (not a claimed format) |
| 25 | https://huggingface.co/datasets/johnlprice82/trading-bot-backtesting/resolve/main/backtests_csv/00bjrhju.csv | Gunbot backtest CSV | refused | not supported (not a claimed format) |

No public TradingView "List of trades", NinjaTrader, QuantConnect,
backtesting.py or vectorbt export was found; those importers remain tested
with synthetic files only.

## What was fixed

1. **MetaTrader 5 XLSX export** (files 13 to 16). The terminal's
   "Open XML (MS Office Excel)" report was refused. It is now read as the
   same rows as the HTML report: labels and values spread over merged cells
   are joined, and deal rows with an empty trailing Comment are padded.
   New formats `mt5_tester_xlsx` and `mt5_history_xlsx`.
2. **Hedging accounts** (files 3, 5, 8, 16). One closing deal produced one
   trade per entry it touched, so the trade count exceeded "Total Trades",
   and first-in first-out paired closes with the wrong entry, so the audit
   raised a false `TRADE_PNL_MISMATCH` (up to 19 %). Now one closing deal is
   one trade, and a close takes the open entry of its own volume whose price
   explains its profit, using the contract size of a first pass.
3. **Conversion drift** (files 7, 8, 15). A symbol quoted in another
   currency than the account's pays a profit converted at each close's
   rate, so one contract size cannot reproduce it. When one size misses a
   symbol's gross P&L by more than 1 %, that symbol is sized per trade from
   its profit (within 0.8x to 1.25x), with a warning.
4. **Build 1940 deal headers** (file 9). "Trade" and "Profit Column" left
   every profit at zero and the balance fell to zero. Header aliases added.
5. **Russian and Spanish summary labels** (file 8). The Russian report's
   summary (deposit, net profit, totals, drawdowns) was ignored, so no
   cross-check ran. Russian labels come from the real file; Spanish ones
   from the Spanish MetaTrader 5 help and have not yet been seen in a real
   file.
6. **Older and numbered MT4 statements** (files 20, 22). Only the build
   600+ 14-column layout was read. Columns now come from the header row, so
   the 13-column layout without Taxes and the numbered layout with a
   comment column are read too.
7. **Balance drawdown cross-check**. The tester's "Balance Drawdown
   Maximal" matched the deepest fall of its Balance column in all 13 real
   MT5 tester reports, so a mismatch now produces a warning (an edited
   report shows up).

## Limits of this check

- The files are public examples, mostly demo accounts and article samples;
  none is a client upload.
- mql5.com rate-limited the search after about 2,400 requests, so more old
  MT4 reports exist there than were fetched.
- Verdict classes were C or D for every file. That is a statement about
  these backtests (short samples, grid or martingale patterns, no declared
  costs), not a test of the importer.
