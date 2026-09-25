# Importers against real exports from other platforms

Checked on 2026-09-25, after the MetaTrader check in
`real_reports_check.md`. The upload form and `/guias` also accept
TradingView (CSV, XLSX), NinjaTrader 8, QuantConnect, backtesting.py and
vectorbt exports, and until now those importers had only been tested on
synthetic files. A misread file now means a refund, so this check looked
for real exports their users had published and ran them through
`detect_format`, `import_report` and the full audit (Spanish and English
report, profit-claim guard, untranslated sentences).

The files were downloaded to a scratch directory outside the repository and
are **not committed**. The fix below has a synthetic test that reproduces
the structure, never the contents, in `tests/test_audit_importers.py`.

## What was found

| Platform | Real public files found | Notes |
|---|---|---|
| TradingView "List of trades" CSV | 5 | 3 in the newest layout (`Trade number`, `Date and time`, `Net PnL`, `Commission`, UTF-8 BOM, exit row before entry row) from the PineForge validation corpus; 2 in the 2024-25 layout (`Trade #`, `Net P&L`, `Run-up`) from the PyneCore test data, one with an open last trade, one a future with a x500 multiplier |
| TradingView XLSX | 0 | none published |
| NinjaTrader 8 Trades grid | 0 | only handmade two-row samples in journal apps |
| QuantConnect / LEAN | 0 | local LEAN runs write JSON; no downloaded CSV was published |
| backtesting.py `_trades` CSV | 0 | the header appears only in code and docs |
| vectorbt `records_readable` CSV | 0 | the header appears only in code and docs |
| cTrader | 0 | not a supported format; two candidates were fabricated (one with a real report structure but made-up trades) |

## Result on the five TradingView files

| File | Trades (own count) | Net result (own exit rows) | Read before | Read after |
|---|---|---|---|---|
| PineForge bracket TP/SL | 366 (366) | 84.34 (84.34) | match | match |
| PineForge pyramid, fractional size, commission | 790 (790) | 13,205.01 (13,205.01) | match; starting balance 1,000,000 inferred from the cumulative columns | match |
| PineForge stochastic RSI, long and short | 1,339 (1,339) | -2,722.80 (-2,722.80) | match | match |
| PyneCore Bollinger, EURUSD one unit | 578 (579, one open and excluded) | 0.081 (0.081 without the open trade) | false contract size x1.06 and a false `TRADE_PNL_MISMATCH` of 20.9 % | size 1, no mismatch |
| PyneCore futures | 294 (294) | 7,662.50 (7,662.50) | match; size x500 inferred | match |

Every full audit ran to a report that passes the guard in both languages,
with no untranslated sentence. All five are class D, a statement about
these backtests (no declared costs, short samples), not about the
importer. The pyramid file's `GRID_AVERAGING` flag is correct: the
strategy adds to positions at worse prices by design.

## What was fixed

1. **Rounded small profits** (Bollinger file). TradingView prints a
   one-unit EURUSD profit of 0.00127 as 0.001. The importer took that as
   a contract size of 1.06 and the audit raised a 20.9 % P&L mismatch. A
   size of one is now kept when it reproduces every profit to its printed
   precision (`schema.printed_step`), and the mismatch flag ignores
   differences within half that step.
2. **Starting-balance note in Spanish**. "initial balance ... taken from
   ..." showed its source in English on Spanish reports (for every
   platform); the six sources now have Spanish text, and the TradingView
   note no longer reads "taken from inferred from".

## Limits

- Only TradingView has real public exports; NinjaTrader, QuantConnect,
  backtesting.py and vectorbt remain checked on synthetic files only. A
  customer's first real file of those platforms is the real test; the
  refund clause covers a misread.
- No real TradingView XLSX, non-English or decimal-comma export was found.
