# Backtest audit: the service, what it measures, and how to run it

The audit is the repository's validation engine pointed at a file a client
uploads. It answers one question in six parts: *is this track record
statistically real, and what would change that answer?* It is research
tooling sold as a second opinion. It is not investment advice, it executes
nothing, it holds no funds and no keys, and it never claims that money was
or will be made. The profit-claim guard refuses any report that does.

The public name is **Rigor** (the same word in Spanish and English: statistical
rigor is what the audit sells). It replaced "Contraprueba" on 2026-09-24.
`seo.BRAND` and `seo.TAGLINE` hold it; it shows in every page head, report
title and badge. A new name must pass the
guard in both languages and must not suggest verification, certification,
approval, earnings or passing a challenge (`tests/test_audit_brand.py`).

## What the client uploads

| File | Required | Columns (aliases accepted, case-insensitive) |
|---|---|---|
| Platform report | this or the equity file | The file as the platform writes it; see "Importers" below. One file gives both the closed trades and the balance curve. |
| MT5 optimisation export | no | The XML the MT5 optimiser exports. Its passes become the MEASURED number of trials in the deflated Sharpe. |
| Live account statement | no | A real or demo account running the robot, in any format a platform report can have. Read for its closed trades only and compared with the backtest (see "Backtest against the live account"); it changes no other figure. |
| Equity or returns | this or a report | `timestamp` + `equity` (or `return`). `Date`/`NAV`, `%` returns, `;` separators and epoch timestamps are understood. |
| Closed trades | no | `entry_time, exit_time, quantity, entry_price, exit_price`, optional `side`, optional `pnl`. |
| Benchmark | no | same shape as the equity file. |
| Variants | no | one return column per parameter variant tried, same rows. |

Plus four declarations: trials tried before choosing this version, cost per
side in basis points, an out-of-sample start date, and whether a benchmark
applies. Trials and cost may be left blank on the web form: blank trials
means "not declared" (1 is assumed and tagged NOT_MEASURED), blank cost means
no extra cost beyond what the uploaded report already lists (there is no
hidden default). Limits: 5 MB and 200,000 rows per file, 50,000 trades, 500 variants,
at least 30 return observations.

A platform report dropped in the equity field by mistake (an `.htm`,
`.html` or `.xlsx` name, or HTML content, UTF-16 included) is read as the
report instead of failing as a malformed CSV. A CSV the parser cannot read
is explained in the form's language (header row, same number of columns),
without the parser's English message.

### Importers and their limits

`audit/importers.py` detects the format by content (standard library only)
and reads: MetaTrader 5 tester and account-history reports as HTML (UTF-16 is
common) or as the terminal's XLSX export, MetaTrader 4 tester reports and
statements (build 600+ with a Taxes column, older 13-column ones, and the
numbered layout with a comment column), TradingView "List of trades" CSV and
XLSX, and the trade exports of NinjaTrader, QuantConnect, backtesting.py and
vectorbt. MetaTrader 5 summary labels are also read in Russian (from a real
report), in Spanish, Italian, Portuguese, Chinese and Czech, and MetaTrader
4 tester labels in Russian (cp1251 without a charset) and Portuguese
(checked against 19 real public reports; see
`docs/research/audit_iteration4/mt_languages_check.md`) and as build 1940
wrote them ("Net profit", "Trade", "Profit Column"). A figure written with a
decimal comma (`1 234,56`, `1.234,56`) is read as 1234.56; `1,234` stays a
thousands separator. The importers were checked against 23 real public
MetaTrader files; see `docs/research/audit_iteration4/real_reports_check.md`.

Account histories from tracking sites are read too, so an investor can
review a trader from the export alone: Myfxbook's history CSV (`Profit` is
net, so the gross adds commission and swap back; `Deposit`/`Withdrawal`
rows are cash flows; the "Open Trades" section is left out of the trades
and its summed Profit is kept as the DECLARED floating result), the history
or positions CSV of an MQL5.com signal (`;`, repeated `Time`/`Price`
columns, `Balance` rows are cash flows, cancelled pending orders skipped)
and FX Blue's orders CSV (`sep=,` first line, `Closed position` rows are
trades, `Deposit`/`Withdrawal` rows are flows; a file holding several
accounts is read for the one with the most closed trades, with a warning).
All three count as account histories, so they get the "El dinero real de la
cuenta" review. Checked against 15 real public exports; see
`docs/research/audit_iteration4/tracking_exports_check.md`.

Limits, each written into the report as a reading warning:

- The balance curve is rebuilt from closed trades. It cannot show floating
  (open-trade) drawdown, so the real drawdown was at least as deep.
- Report times carry no timezone; they are read as UTC.
- Contract sizes are inferred from the reported profit when the file does
  not state them. When one size misses the reported gross P&L of a symbol
  by more than 1 % (`CONVERSION_DRIFT_SHARE`: a pair quoted in another
  currency than the account's, such as USDJPY in a USD account), that
  symbol is sized per trade from its own profit, within 0.8x to 1.25x of
  the symbol's size (`CONVERSION_DRIFT_BAND`), with a warning. A size of
  one is kept when it reproduces every reported profit to the precision
  the file prints it (`schema.printed_step`: TradingView prints a
  one-unit forex profit of 0.00127 as 0.001), and `TRADE_PNL_MISMATCH`
  ignores per-trade differences within half that printed step.
- One closing deal is one trade, as the tester counts "Total Trades". A
  hedging report does not say which entry a close belongs to: the close
  takes the open entry of its own volume whose price explains its profit
  (first in, first out among equals), so entry price and holding time are
  approximate while the money stays exact.
- The MT5 tester's own totals are cross-checked against the rows: Total
  Trades, Total Net Profit and Balance Drawdown Maximal (the deepest fall
  of the Balance column). A mismatch is a warning, never a silent repair.
- A report without a starting balance uses the one the client declares,
  else 10,000 with a warning.
- A CSV line longer than 32 KB (`MAX_CSV_LINE_BYTES`) is refused: no real
  export has one, and pandas takes minutes on a 5 MB line of fields.
- XML (the optimisation export and every XLSX member) is refused when it
  declares a document type, in any encoding; a damaged, encrypted or
  size-lying workbook gets a plain "could not be read" message.
- A workbook cell past column XFD, or past column 256
  (`MAX_XLSX_COLUMNS`), is ignored, and a sheet whose rows spread over more
  than 5,000,000 cells (`MAX_XLSX_CELLS`) is refused as too large: one cell
  at column ZZZZZZZZ used to ask for a row of hundreds of millions of cells.
- An HTML report is parsed once; detecting its format no longer reads it a
  second time.
- An equity curve that reaches zero or a negative value, or a return file
  with a return of -100 % or worse, is refused before the audit with the
  first date it happens (`equity_not_positive`, `return_below_total_loss`):
  the audit needs the account balance, not a cumulative profit that starts
  at 0. Values such as `inf` or `1e400` count as unreadable rows.
- The grid and concurrency scan over trades is one sweep in entry order, so
  a 50,000-trade upload is scanned in well under a second (it was quadratic:
  about a minute for 20,000 trades).
- The MT5 optimisation pass count is what the optimiser tried; a genetic
  optimisation lists only the passes it evaluated. The deflated Sharpe uses
  the largest of the declared trials, the uploaded variants and the passes.

### Charts and printing

The report embeds four SVG figures without JavaScript (`audit/charts.py`):
equity, drawdown, the resampled scenario fan and the monthly return map,
each with its evidence tag. "What it means for you" gives two plain
sentences per dimension. The "Print / save PDF" button uses the print
stylesheet, which hides the buttons and the forms. Axis labels always
differ from each other: a narrow range (an account that moved a few
dollars) is written in full with the decimals it needs, never "10k, 10k",
and one axis uses one unit (8k, 10k, 12k, not 8,000 next to 10k). On phones
the charts keep a readable size and scroll sideways.
Red-flag severities and the platform's declared fields are shown in the
report's language (Grave / Aviso; Bróker, Beneficio neto total…).

### Executive summary

The report opens with up to eight key figures, each shown only when it was
measured: total return, maximum drawdown, resampled one-year drawdown p95,
annualised Sharpe, profit factor, trades and win rate, the extra cost per
side that takes the trades to zero (red below 3x the reference, the costs
bar) and the result without the best 5 trades and the best 5 periods (red
at zero or below). An unpaid report in paid mode shows the tiles' names
with no values.

### Comparing two reports

`/comparar` (Spanish) and `/compare` (English) take the links of two of the
customer's own reports and show them side by side: class, period and file
format, the six dimensions and the executive-summary figures, with the
figures that differ in bold (`audit/compare.py`). Every unlocked report has
a small form that fills in its own link. Rules:

- the links travel in a POST body, never in a URL, so no token reaches a
  log line; the id and token are read from the pasted address and checked
  exactly like the report page (wrong token: 404, same report twice or an
  unreadable link: 400);
- only paid reports (or any report in free mode) can be compared: a locked
  one gets 402 and the unlocked figures are never shown;
- the page is private (`noindex`), passes the profit-claim guard and says
  that a class difference shows which tests changed, not that one version
  will work better.

### Stress tests without the best outcomes

`audit/stress.py` removes the best outcomes from what was uploaded and
reports what is left (the JSON's `stress` block, MEASURED; older results
have none and the section says so). Nothing is resampled or forecast.

| Family | Scenarios | Result |
|---|---|---|
| Curve (`stress.returns`, always) | without the best 1 % of periods (at least one), the best 5 and the best 10 periods, and the best calendar month | compounded total return of the remaining periods |
| Trades (`stress.trades`, with closed trades) | without the best trade, the best 5, the best 10 % (rounded up), and the best exit month | net result of the remaining trades minus the whole reported fees |

Each row carries the change from the original and whether it stays above
zero; the section counts the scenarios that end at zero or below.
`top5_share` is the best five trades over the net result when that is
positive. A row that would remove as many periods or trades as exist is
left out. Fees cannot be attributed per trade, so removing trades keeps
them whole, which errs on the strict side. These rows set no threshold and
do not change the class.

### What each class requires

Every report, locked or paid, and `/ejemplo` show a short table
(`report.CLASS_LADDER`, ES and EN) with the rule `verdict.overall_class`
applies for each class, and mark the report's own. It adds no threshold; it
restates the existing ones so a buyer can see what a better class would take
without implying a result.

### When it wins and when it loses

`audit/timing.py` groups the closed trades by the weekday and the four-hour
block of their entry, as the file states them (platform or server time), and
reports each group's count, net result before itemised fees and hit rate
(the JSON's `timing` block, MEASURED). The report names the weekday and the
block with the largest net result and their share of the total when the
total is positive. It needs at least `MIN_TRADES` = 20 closed trades
(NOT_MEASURED below that); the time-of-day table is left out when every
entry has the same clock time (daily data). It sets no threshold and does
not change the class.

### Backtest against the live account

`audit/live.py` answers one question when the client also uploads a live
(or demo) account statement: if the live trades had come from the
backtest's own trades, how unusual would the live result be? It draws
`SAMPLES` = 5,000 histories of as many backtest trades as the statement
holds (with replacement, fixed seed) and places the live net result, hit
rate and deepest fall among them (the JSON's `live` block, MEASURED; the
expected range is the 5th to 95th percentile of the draws).

- Outcome: `INCONSISTENT` when the live net result is at or below fewer
  than `OUT_TAIL` = 1 % of the draws, or its fall is at least as deep in
  fewer than 1 %; `EDGE` for the same test at `EDGE_TAIL` = 5 %; `ABOVE`
  when the live net result is at or above fewer than 1 % of the draws (the
  files may not share a configuration, size or account); otherwise
  `CONSISTENT`. The outcome does not change the class.
- Sizes: when the median live volume is outside 0.8 to 1.25 times the
  backtest's, each live trade is scaled to the backtest's median size and
  the report says so. Costs itemised per trade are subtracted on both sides.
- Also reported: trades per month (a line when the live pace is outside 0.5
  to 2 times the backtest's), live dates inside the backtest period (the
  backtest may have been fitted on them), and live symbols the backtest
  lacks (a broker suffix such as `EURUSD.m` counts as the same symbol).
- Same dates, trade by trade (the JSON's `live.pairing`, `null` when the
  files share no dates): each live trade on the shared dates is paired with
  the unused backtest trade of the same side and symbol whose entry is
  nearest and at most `MATCH_WINDOW` = 60 minutes away. Reported: live
  trades found in the backtest and their share, backtest trades without
  their live trade, the median entry and exit price difference in basis
  points (positive when worse for the account), and the result difference
  of the paired trades with each live trade scaled to its backtest trade's
  size (total and per trade). The price and result figures need
  `MIN_MATCHED` = 5 paired trades (NOT_MEASURED below that). When at least
  5 live trades fall on the shared dates and fewer than `MATCH_LOW` = 50 %
  are found, the report says it is probably not the same configuration.
  Times are compared as the files state them: two servers in different time
  zones pair poorly.
- Needs at least `MIN_BACKTEST_TRADES` = 30 backtest trades and
  `MIN_LIVE_TRADES` = 10 live trades (NOT_MEASURED below that).
- Limits: trades are drawn independently, so streaks and regime changes are
  not preserved; the comparison says whether the files are alike, never
  what the account will do next.

The `/ejemplo` report carries a synthetic live account (120 business days
after the backtest, a fifth of its size, a thinner edge) so a visitor sees
the section; it comes out "En el borde".

### Plan to reach a better class

`audit/plan.py` turns the verdict into one step per dimension that did not
pass (FAIL, WEAK or NOT_MEASURED), rebuilt from the stored JSON so older
audits get it too. Each step has a fixed title, a finding with the result's
own figures and the actions the audit would need to see:

- data quality: every red flag with a hint (`FLAG_HINTS`, one per flag code
  in both languages; a new flag needs its hint, which a test enforces);
- significance: observations still needed for PSR 0.95 (the minimum track
  record length minus what was uploaded) as a rough calendar span;
- multiplicity: DSR at the trials used, the trial count at which it falls
  below 0.5 and the PBO when measured;
- costs: the break-even extra cost per side against 3x the reference;
- out of sample and benchmark: what to declare or upload, and the class cap
  when they are missing (B without a holdout or without trades).

`class_if_passed` is the class rule applied to that one dimension at PASS
with the rest unchanged, shown only when it differs from the current class.
Steps that change the class on their own come first, then FAIL, WEAK and
NOT_MEASURED. The plan never says a strategy will work: a better class means
the files answer more of the audit's questions. An unpaid report in paid
mode shows only the step titles; the figures are in the paid detail.

## What is measured, and from where

Every leaf value in the JSON carries an evidence tag:

- `MEASURED`: computed from the uploaded bytes.
- `DECLARED`: asserted by the client (trials, cost, out-of-sample start,
  the reference cost assumed when the client declares zero). Not verifiable.
- `NOT_MEASURED`: could not be computed from what was supplied; the reason
  is stated next to it.

| Section | Estimator | Source module |
|---|---|---|
| Performance | annualised return, volatility, Sharpe, Sortino, max drawdown | `metrics/performance.py` |
| Significance | PSR, skew, kurtosis, minimum track record length | `metrics/statistics.py` |
| Multiplicity | DSR at 1, 5, 20, 100 and the declared trials; trials-to-half | `metrics/statistics.py` |
| Bootstrap | stationary block bootstrap p5/p50/p95 of the per-period Sharpe and total return | `research/bootstrap.py` |
| Out-of-sample | Sharpe and PSR on each side of the declared date, and the gap | `research/splits.py` |
| Costs | the trade ledger at 0x/1x/2x/3x the reference cost and the exact break-even cost per side | `backtest/costs.py` |
| Benchmark | excess return, tracking error, information ratio, drawdown ratio | `research/benchmarks.py` |
| CSCV | probability of backtest overfitting over the variants matrix | `research/overfitting.py` |
| Red flags | fourteen data-quality checks, each with a FAIL or WARN severity | `audit/redflags.py` |
| Seal | the dataset digest and, with a declared out-of-sample start, a `HoldoutSeal` | `research/holdout_seal.py` |

Three details a buyer reading a real MetaTrader report asked about:

- One Sharpe: the headline, the executive summary, the significance
  section and the `IMPLAUSIBLE_SHARPE` flag all use the same annualised
  Sharpe (sample standard deviation, the audit's periods per year). The
  platform's own Sharpe is shown apart, as DECLARED, and can differ (MT5
  computes it another way).
- Drawdown with open trades: a report rebuilt from closed trades cannot see
  open losses. When the file prints the platform's equity drawdown (MT5
  "Equity Drawdown Maximal/Relative", in any language the importer reads),
  the deepest percentage is `performance.platform_equity_drawdown`
  (DECLARED). The executive summary shows it next to the measured drawdown
  when it is at least half a point deeper. The prop-firm section adds a line
  when it is at or beyond the preset's total loss limit: the closed-trade
  simulation cannot see those losses. Neither changes the class.
- Costs in pips: when every trade is on one six-letter pair of USD, EUR,
  GBP, JPY, CHF, AUD, NZD or CAD (a broker suffix is ignored), the break-even
  and reference costs are also given in pips per side at the median entry
  price (`costs.break_even_pips`, `costs.reference_pips`, `costs.pip_symbol`;
  a pip is 0.01 on yen pairs, else 0.0001). Metals, indices and mixed
  symbols stay in basis points only.

### The variance policy behind the deflated Sharpe

DSR needs the variance of Sharpe estimates across the trials that were run.
A client rarely uploads them, so the audit uses
`max(observed across uploaded variants, sampling-variance floor)` where the
floor is the sampling variance of the Sharpe estimator itself,
`(1 − skew·SR + (kurt−1)/4·SR²)/(n−1)`: unskilled trials disagree at least by
sampling error. With this floor, the best of 100 unskilled random walks has
a PSR near 0.99 and a DSR near 0.5 at 100 declared trials, which is the
behaviour the test suite pins.

### Trade analytics, resampled risk and prop-firm challenges

`audit/analytics.py` and `audit/prop_presets.py` (iteration 4; the engine
and report wire them in during the integration step):

- `trade_statistics`: win rate, gross profit and loss, net after reported
  fees, profit factor, expectancy, average win and loss, payoff ratio,
  largest-win share, longest win and loss streaks (trades ordered by exit),
  mean and median holding hours, SQN (`sqrt(min(N, 100))·mean/std` of per-
  trade gross pnl), trades per month and a long/short split. MEASURED, or
  NOT_MEASURED with the reason (no trades, no losses, a single side).
- `drawdown_risk`: stationary block bootstrap (expected block 5 periods) of
  the uploaded returns over one year, 2,000 paths by default, capped at
  2,000,000 resampled cells. A curve finer than 10,000 periods a year
  (`MAX_RISK_PATH_PERIODS`, about hourly around the clock) is first
  compounded into consecutive blocks so a path stays that short
  (`method.periods_per_step`), and the time under water and the fan are
  reported back in the uploaded periods; when too few blocks remain the
  figures are NOT_MEASURED ("the history is too short to resample a year at
  this frequency"). Before this, a curve logged every second asked for
  gigabytes. Maximum drawdown p50/p95/p99, the share of
  paths reaching 10/20/30/50 %, the longest time under water p50/p95, and a
  p5–p95 fan of at most 120 points. Every figure is noted "resampled from
  the uploaded history, not a forecast".
- `simulate_challenge`: the same bootstrap over daily closes, 5,000 paths by
  default, checked each day for the daily floor, then the total floor, then
  the target with the minimum days (every day with a non-zero return counts
  as a trading day). Pass, daily-loss failure, total-loss failure and
  unfinished sum to one, with a Wilson 95 % interval and days to target.
  Calendar time limits become business days at 5/7. Daily data cannot see
  intraday floating drawdown, so the estimate is optimistic; fixed notes in
  Spanish and English say so, and that it is not a prediction.
- `vendor_questions`: neutral questions for the seller of a robot, driven by
  the red flags and the missing inputs, in Spanish and English. It never
  says whether to buy.

Challenge presets (`quant-trade audit presets` after integration), each a
transcription of the official page on its `as_of` date with its
`source_url`; rules the simulator cannot model are in `notes`:

| Key | Target | Daily loss | Max loss | Min days | Source (re-read 2026-09-25) |
|---|---|---|---|---|---|
| `generic-2step-phase1` (default) | 10 % | 5 % of initial | 10 % static | 4 | this plan |
| `ftmo-2step-phase1` / `-phase2` | 10 % / 5 % | 5 % of initial | 10 % static | 4 | ftmo.com/en/trading-objectives |
| `ftmo-1step` | 10 % | 3 % of initial | 10 % trailing EOD | 0 | same |
| `fundednext-stellar-2step-phase1` / `-phase2` | 8 % / 5 % | 5 % of initial | 10 % static | 5 | fundednext.com/general-rules/cfds/trading-objectives |
| `fundednext-stellar-1step` | 10 % | 3 % of initial | 6 % static | 2 | same |
| `fundednext-stellar-lite-phase1` / `-phase2` | 8 % / 4 % | 4 % of initial | 8 % static | 5 | same |
| `the5ers-high-stakes-step1` / `-step2` | 10 % / 5 % | 5 % of previous close | 10 % static | 3 | the5ers.com/high-stakes |
| `the5ers-hyper-growth` | 10 % | pause only, not simulated | 6 % static | 0 | the5ers.com/hyper-growth |
| `the5ers-bootcamp-step` | 6 % | none | 5 % static | 0 | the5ers.com/bootcamp |
| `topstep-50k/100k/150k-combine` | 6 % | optional, not simulated | USD 2,000 / 3,000 / 4,500 trailing EOD, locks at start | 2 | help.topstep.com (maximum loss limit) |

Re-check on 2026-09-25: every target, loss limit and minimum above still
matches the official pages. The5ers' Hyper Growth now sits under a "Growth"
page whose table lists 3 minimum profitable days while its text says there is
no minimum; the preset keeps none and says so in its notes. The upload form
shows the date the rules were read, and each report cites the source page.

Trade-pattern red flags (`redflags.scan_trade_patterns`, on closed trades):

| Code | WARN | FAIL |
|---|---|---|
| `MARTINGALE_SIZING` | median size after a loss ≥ 1.25x the median after a win (at least 5 of each) | ≥ 1.6x and ≥ 60 % of post-loss trades larger than the loss |
| `GRID_AVERAGING` | ≥ 5 trades and ≥ 20 % opened against an open same-side position on the same symbol at a worse price | ≥ 10 trades and ≥ 40 % |
| `MANY_CONCURRENT_POSITIONS` | ≥ 5 positions open at once on one symbol | — |
| `HIDDEN_FLOATING_DRAWDOWN` | a balance-only curve while positions overlapped | — |
| `NEGATIVE_PAYOFF_HIGH_WINRATE` | ≥ 20 trades, win rate > 85 % and average loss ≥ 3x average win | — |
| `NO_STOP_EVIDENCE` | ≥ 10 losses and the largest loss (or adverse excursion) ≥ 8x the average loss | — |

Trades against an uploaded equity curve (`redflags.scan_trades_against_equity`;
skipped when the curve was rebuilt from the same report):

| Code | WARN | FAIL |
|---|---|---|
| `TRADES_OUTSIDE_EQUITY` | > 10 % of trade exits fall outside the curve's dates (± 1 day) | — |
| `TRADES_EQUITY_UNRELATED` | ≥ 6 months with trade exits and the monthly realised pnl correlates < 0.2 with the monthly equity change | — |

### The account's real money (`audit/account.py`)

For investors checking someone else's track record. Only for account
histories (MT5 history HTML/XLSX, MT4 statement); a backtest shows the
section as NOT_MEASURED. The importer lists every deposit and withdrawal
(`ImportedReport.cash_flows`), and the section puts side by side: the
time-weighted percentage gain (deposits and withdrawals taken out, as
track-record sites compute it), the money the closed trades made after
commission and swap, the result on the money deposited, the share withdrawn,
each deposit made after trading began with the balance before it and the
flow-adjusted drawdown on the day before, and the platform's own floating
result (DECLARED). Nothing is checked with the broker.

| Code | WARN | FAIL |
|---|---|---|
| `GAIN_INFLATED_BY_FLOWS` | percentage gain ≥ 10 % while the trading result is ≤ 0 or below a third of the gain on the money deposited | — |
| `DEPOSIT_DURING_DRAWDOWN` | a deposit after the first trade while the flow-adjusted drawdown is ≥ 20 % | — |
| `FLOATING_LOSS_AT_END` | the declared floating result is a loss ≥ 10 % of the balance | ≥ 30 % |

Limitations: broker credit and bonus rows of an MT5 history count as flows;
the floating result is the platform's figure at print time, not a history
of floating losses; a history printed after the open losers close shows
none of it.

Trials: the deflated Sharpe uses the larger of the declared trials and what
the files prove (columns of the variants matrix, passes of an MT5
optimisation export, variants in a vectorbt report); the latter is tagged
MEASURED. `TRIALS_BELOW_VARIANTS` warns when the declaration is lower; it
stays silent when the customer left trials blank, since nothing was declared.

File reading check ("Lectura de tu archivo"): when the uploaded report
prints its own totals (MT5 Tester: Total Trades, Total Net Profit), the report
opens with a table comparing them to what the audit re-counted from the rows
(`report.READING_CHECKS`: trades exactly, net result to the cent) and says
"Coincide" or "No coincide". It is shown before payment too: these are the
customer's own totals. The profit factor is left out because platforms treat
commission and swap in it differently. A mismatch points to the reading notes
and to the refund promise's contact route.

PDF download: an unlocked report (paid, or any report in free mode) offers
"Descargar el informe en PDF" at `/audits/{id}/pdf?token=…`, a locked one
answers 402. `audit/pdf.py` lays out the same report page with WeasyPrint
(needs Pango: `Dockerfile.web` installs it) and serves only the site's own
fonts and `data:` URIs to the renderer; every other URL is refused, so a
PDF never reaches the network. At most `MAX_CONCURRENT_PDFS = 2` render at
once; a download waits up to `PDF_WAIT_SECONDS = 25` for a free slot (a
double click or a second customer waits its turn), then a busy or missing
renderer answers 503 with a hint to use print. `HEAD` is answered like
`GET` without the body, so link-preview bots and uptime checks do not get
a 405.
The response is `private, no-store` and `noindex`. The sample report offers the same
download at `/ejemplo.pdf` and `/sample.pdf`, built once per language and
cached, so a buyer sees the deliverable before paying.

Annual return: the compound annual return is NOT_MEASURED when the history
spans less than a year (`engine.MIN_CAGR_DAYS = 365`); compounding a few
good weeks into a year prints a return nobody earned, and the total return
already says what happened.

## The verdict

Six dimensions, each PASS, WEAK, FAIL, NOT_MEASURED or NOT_APPLICABLE, and a
class A to D that is a fixed function of them. Thresholds are recorded in
every JSON under `verdict.thresholds`.

| Dimension | PASS | WEAK | FAIL |
|---|---|---|---|
| Statistical significance | PSR ≥ 0.95 and bootstrap p5 Sharpe > 0 | PSR ≥ 0.80 or p5 > 0 | otherwise |
| Multiplicity | DSR(declared) ≥ 0.95 and PBO < 0.5 if measured | DSR ≥ 0.50 | DSR < 0.50 or PBO ≥ 0.5 |
| Costs | net pnl at 3x the reference cost > 0 | net at 1x > 0 | net at 1x ≤ 0 |
| Out-of-sample | OOS Sharpe ≥ 0.5 and IS−OOS gap ≤ 1.0 | OOS Sharpe > 0 | OOS Sharpe ≤ 0 |
| Data quality | no flags | WARN flags only | any FAIL flag |
| Benchmark | excess > 0, drawdown ratio ≤ 1, IR > 0 | excess > 0 | excess ≤ 0 |

Class: **D** if data quality or significance fails, or two or more
dimensions fail. **C** if exactly one fails, or significance or
multiplicity is WEAK. **B** if significance and multiplicity pass and any of
costs, out-of-sample or benchmark is WEAK or NOT_MEASURED. **A** only when
all six pass (benchmark may be declared not applicable). Without trades or
without a declared holdout the best possible class is B, on purpose.

Class A is worded as "no evidence of overfitting found in what was
supplied". It is not a prediction.

## Assumptions and limitations

- No market data is used. The audit sees only what the client uploads; a
  fabricated equity curve with plausible statistics passes the statistics.
  The red flags catch the common accidents, not a determined forger.
- The out-of-sample start is declared. The `HoldoutSeal` embedded in the
  report records the declaration against the file digests; it cannot show
  that the client never looked at those dates.
- Trials are declared. A client who tried 500 variants and declares 1 gets
  a DSR that flatters them; the sensitivity table at 5, 20 and 100 trials
  and `trials_to_half` show how fast that flattery disappears.
- Costs are re-applied only to uploaded closed trades, as a percentage per
  side on entry and exit notional. Funding, borrow, financing and market
  impact are not modelled. With zero declared cost a 10 bps per side
  reference is assumed and labelled as such.
- When a platform report itemises commission, swap or fees (MT5, MT4
  history, NinjaTrader, QuantConnect, backtesting.py, vectorbt), those
  per-trade costs are MEASURED and sit in every row of the cost table, the
  0x row included; the multiples add cost on top of them. A tester fills at
  bid/ask, so the spread is already in the prices, and with zero declared
  cost the reference on top is 0.5 bps per side of assumed slippage (about
  half a pip on EURUSD at 1.10; 10 bps would be 11 pips per side). The
  break-even is the extra cost per side on top of the reported fees, and
  `ZERO_DECLARED_COSTS` is not raised because the costs were measured. A
  cost the client declares is charged on top of the reported fees.
- CSCV needs the variants matrix; without it the PBO is NOT_MEASURED and
  multiplicity relies on the DSR alone.
- The bootstrap is per period and does not annualise; its block size is
  `min(20, n/10)`.
- Nothing here is a forecast. A strategy that passes every dimension has a
  track record that is hard to explain by luck, data errors or costs alone.
  That is all the audit says.

## Running it

### By command line (the whole product without a browser)

```
python -m pip install -e ".[dev]"
quant-trade audit run --equity examples/audit/sample_equity.csv \
  --trades examples/audit/sample_trades.csv --trials 20 --cost-bps 5 \
  --oos-start 2023-01-01 --output-dir outputs/audit_demo
```

Writes `audit.json` (canonical record), `report.html` (self-contained page)
and `holdout_seal.json` when an out-of-sample start was declared.
`--preview` (default) watermarks the page; `--paid` does not. `make
audit-demo` runs the example.

### As a web service

```
python -m pip install -e ".[dev,web]"
quant-trade audit serve --port 8000      # or: make audit-serve
curl -f localhost:8000/health
curl -i -F equity=@examples/audit/sample_equity.csv -F trials=20 -F cost_bps=5 \
  -F consent=on localhost:8000/audits
```

Routes:

| Route | What it does |
|---|---|
| `GET /` | Landing (how it works, prices, FAQ, link to the sample) and the form; `?lang=en`. `GET /en` is the English landing, a short address to share. |
| `POST /audits` | Upload. An optional `access_code` field redeems a code (paid mode with codes on). |
| `GET /audits/{id}?token=…` | The report, in the language chosen at upload; `&lang=en` or `&lang=es` shows it in the other one. `GET /audits/{id}.json?token=…` the record (402 while locked). |
| `POST /audits/{id}/checkout?token=…` | Stripe Checkout (503 without Stripe). Form field `plan=single` (default) or `plan=pack`; the return link `?session_id=…` is confirmed with Stripe before anything unlocks. |
| `POST /audits/{id}/redeem?token=…` | Unlock an existing preview with an access code. |
| `POST /audits/{id}/publish?token=…` | Create (or return) the public verification page. Paid audits, or any audit in free mode; 402 otherwise. |
| `POST /audits/{id}/unpublish?token=…` | Remove the public page. |
| `GET /v/{public_id}` | Public verification page. `GET /v/{public_id}/badge.svg` its badge. Survives the retention purge (only the shown fields are kept); 404 once unpublished. |
| `GET /ejemplo`, `GET /sample` | A full report of synthetic data, Spanish and English. |
| `GET /terminos`, `GET /terms` | Terms of service (`audit/legal.py`), Spanish and English; either answers `?lang=`. |
| `GET /privacidad`, `GET /privacy` | Privacy policy, Spanish and English. |
| `POST /webhooks/stripe`, `POST /waitlist`, `GET /health` | Payment confirmation, waiting list, health check. |

Languages. Spanish is the default on every route, and the Spanish URLs and
texts are the ones already shared. Every page (landing, form, preview, full
report, `/v/{id}` and its badge, sample, terms, privacy, error pages) has an
English version and a link to switch. The report's language is chosen at
upload and can be switched later with `&lang=`: the verdict sentence is
rebuilt from its fixed templates in that language and the result JSON does
not change. The engine, the importers and the red flags write their notes
and file-reading warnings in English, which is what the JSON keeps as the
evidence record; a Spanish page translates them with the fixed rules in
`audit/i18n.py`. A sentence with no rule stays in English rather than
disappearing, and `tests/test_audit_i18n.py` fails when any importer fixture
or test scenario produces one, so a new warning needs its Spanish rule.

Every private URL carries a per-audit secret token; a wrong token is a 404.
Every response is `Cache-Control: no-store` except the two `/v/` routes,
which are `public, max-age=300`.

Configuration is by environment only (`.env.example` lists every variable
with an empty value):

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///state/audit/audit.db` | SQLite file or Railway Postgres (`postgres://` is normalised to `postgresql+psycopg://`). |
| `AUDIT_BASE_URL` | `http://localhost:8000` | Public URL used in Stripe success and cancel links, canonical and Open Graph links, the badge snippet, `robots.txt` and `sitemap.xml`. While it is left at the default, those links use the address the request reached (`https` when `AUDIT_TRUSTED_PROXY_HOPS` > 0). Set it to your domain in production. |
| `AUDIT_FREE_MODE` | `true` | Serve watermarked reports with nothing locked. Forced `true` unless both Stripe secrets are set or `AUDIT_ACCESS_CODES=true`. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | empty | Both are needed for card payments: a secret (`sk_…`) or restricted (`rk_…`) key and the webhook signing secret (`whsec_…`). A publishable key (`pk_…`) leaves card payments off. `/health` shows `card_mode` (`off`, `test`, `live`) from the key's prefix, never the key. |
| `STRIPE_PRICE_ID` | empty | Optional. Without it Checkout charges `AUDIT_PRICE_USD_CENTS` (and the pack `AUDIT_PACK_PRICE_USD_CENTS`) in USD with no Stripe product to create. |
| `AUDIT_ACCESS_CODES` | `false` | Sell with access codes. With `AUDIT_FREE_MODE=false` it turns on paid mode without Stripe. |
| `AUDIT_CONTACT_URL` | empty | Where a client asks for a code (for example a `https://wa.me/…` link or a `mailto:`). Only `https://` and `mailto:` are shown. |
| `AUDIT_PRICE_USD_CENTS` | `4900` | The price shown on the landing and on the pay button; with Stripe, the Stripe price object decides what is charged. |
| `AUDIT_PACK_PRICE_USD_CENTS` | `6900` | A 3-credit access code (`PACK_CREDITS`), shown on the pricing card, the locked report and the terms only when codes are sold and it costs less than three single audits; `0` hides it. Create the code with 3 credits on `/panel` or `audit codes create --credits 3`. |
| `AUDIT_MAX_UPLOAD_BYTES` | `5000000` | Per file. A whole request over six files' worth plus 1 MiB (`UPLOAD_FIELDS`, `FORM_OVERHEAD_BYTES`) is refused with 413 before it is written to disk. |
| `AUDIT_MAX_UPLOADS_PER_HOUR_PER_IP` | `10` | 429 above it. Attempts that fail to parse count too, up to three times this number (`UPLOAD_ATTEMPTS_PER_UPLOAD`); waitlist sign-ups are limited to 5 per hour per address (`WAITLIST_PER_HOUR_PER_IP`). |
| `AUDIT_MAX_CONCURRENT_AUDITS` | `2` | Uploads parsed and audited at the same time. Each one can use a few hundred MB on a long intraday curve. |
| `AUDIT_QUEUE_SECONDS` | `30` | How long an upload waits for a free slot before it gets a 503 "busy, try again in a minute" page. |
| `AUDIT_RETENTION_DAYS` | `30` | Shown on the form and the privacy page; the automatic purge uses it. A manual `audit purge --days` should use the same number. |
| `AUDIT_AUTO_PURGE` | `false` | `true` runs the retention purge inside the service at startup and every 24 hours. Turning it on is the explicit confirmation the retention delete needs. |
| `AUDIT_BOOTSTRAP_SAMPLES` | `1000` | Fewer samples make the service faster and the bands coarser. Above 10 million cells (samples x returns, `BOOTSTRAP_MAX_CELLS`) the samples are reduced to fit, never below 50; the report records both counts. |
| `AUDIT_OPERATOR_NAME` | empty | Legal name of whoever runs the service, shown on the terms and privacy pages. |
| `AUDIT_OPERATOR_CONTACT` | empty | Contact for privacy and deletion requests (an e-mail address). |
| `AUDIT_OPERATOR_ADDRESS` | empty | Postal address of the operator. |
| `AUDIT_JURISDICTION` | empty | Governing law and courts, for example "Leyes de México; tribunales de la Ciudad de México". |
| `AUDIT_ADMIN_KEY` | empty | Secret for the owner panel at `/panel` (create, list and disable codes from a phone). Shorter than 32 characters or empty turns the panel off (404). |
| `AUDIT_TRUSTED_PROXY_HOPS` | `0` | Reverse proxies in front of the service. `0` ignores `X-Forwarded-For` (it is client-controlled) and rate-limits the socket address; `N` takes the N-th entry from the right. Railway needs `1`. |

### Deploying on Railway

1. Create a service from this repository. `railway.json` selects
   `Dockerfile.web` and the `/health` check; the container listens on
   `$PORT`.
2. Storage: either add the Railway Postgres plugin and reference its
   variable from the service (`DATABASE_URL=${{Postgres.DATABASE_URL}}`), or
   mount a volume at `/data` and set `DATABASE_URL=sqlite:////data/audit.db`.
   The image runs as the non-root user `quant` and Railway mounts volumes
   owned by root, so with a volume also set `RAILWAY_RUN_UID=0`; otherwise
   SQLite cannot create the file and every upload fails. Postgres is the
   simpler choice; the in-service purge (`AUDIT_AUTO_PURGE`) works with either.
3. Set `AUDIT_BASE_URL` to the public domain Railway assigns or to the
   custom domain you attach (it is also the address in the badge embed code
   of `/v/…` pages), and `AUDIT_TRUSTED_PROXY_HOPS=1` so the
   hourly limit counts the visitor's address and not Railway's proxy.
4. Leave `AUDIT_FREE_MODE=true` until the first paid audit is wanted. To
   sell with access codes only (no Stripe), set `AUDIT_ACCESS_CODES=true`,
   `AUDIT_FREE_MODE=false`, `AUDIT_PRICE_USD_CENTS` and optionally
   `AUDIT_CONTACT_URL`, then create codes from a shell inside the service
   (`railway ssh`, or the service's shell in the dashboard; see "Selling
   with access codes"). A client without a code sees the price and the
   `AUDIT_CONTACT_URL` link on the landing and under the locked report. For card payments see "Card payments with Stripe" below.
   Locally: `stripe listen --forward-to localhost:8000/webhooks/stripe`
   then `stripe trigger checkout.session.completed`.
5. Retention: set `AUDIT_AUTO_PURGE=true`. The service then runs the
   purge itself, once at startup and every 24 hours, with
   `AUDIT_RETENTION_DAYS`, which is the number `/privacidad` shows. Setting
   the variable is the owner's explicit confirmation of the retention
   delete; without it nothing is deleted automatically and
   `quant-trade audit purge --days N --yes` remains the manual way.
   `/health` reports `auto_purge`. Unpaid uploads, reports and the client's
   description are deleted; id, digests and class are kept so the record
   stays verifiable. The upload IP address of every audit past the window,
   paid ones too, is cleared in the same run. A published audit keeps only
   what its verification page shows (see "Public verification page and
   badge").
6. Set the four `AUDIT_OPERATOR_*`/`AUDIT_JURISDICTION` variables. Until
   they are set, `/terminos` and `/privacidad` show "[sin configurar]" and a
   warning, and `/health` reports `"legal_configured": false`.

### Testing a deployment on Railway

1. Open `https://<domain>/health`: `free_mode`, `stripe_enabled` and
   `access_codes` say which mode the variables produced. Selling with codes
   shows `"free_mode": false, "access_codes": true`.
   `version` is the short commit Railway deployed (`RAILWAY_GIT_COMMIT_SHA`);
   compare it with the latest commit on `main` to see whether a merge is live.
2. Open `/ejemplo`: a full report of synthetic data renders with charts.
3. Upload an MT5 tester report (`Report.html` as the terminal saves it) and,
   if you have it, the optimisation XML. The report shows the class, the
   charts and, under the file format, the passes counted.
4. In free mode, or after unlocking, press "Publish a public verification"
   at the bottom of the report and open the `/v/…` page and its
   `badge.svg`. Check it shows no file, trade or description.
5. With codes on: in the service shell (`railway ssh`) run
   `quant-trade audit codes create --credits 1 --note test` and copy the
   code (it is printed once). Upload a file with that code in the "Access
   code" field and check the report is complete and says the code was
   applied. Upload again with the same code: you get the preview with the
   notice that the code could not be applied, and under it the price and
   your `AUDIT_CONTACT_URL` link. `quant-trade audit codes list` shows the
   credit as used.
6. Without a code: upload, check the preview shows the verdict, charts and
   plain-language text but no numbers of the locked sections (view the
   page source), then redeem a new code in the box at the bottom and check
   the full report appears.
7. Open the pages on a phone: tables scroll sideways inside the page and
   nothing else overflows.

### Card payments with Stripe

1. In the Stripe dashboard (test mode first) copy the secret key and put it
   in the service variables as `STRIPE_SECRET_KEY`. Never paste it anywhere
   else.
2. Developers > Webhooks > Add endpoint: `https://<domain>/webhooks/stripe`,
   events `checkout.session.completed` and
   `checkout.session.async_payment_succeeded`. Copy its signing secret into
   `STRIPE_WEBHOOK_SECRET`.
3. Keep `AUDIT_FREE_MODE=false`. `AUDIT_ACCESS_CODES=true` can stay on: the
   card button becomes the main action and WhatsApp plus the code field
   stay under it as the alternative.
4. `/health` shows `"card_mode": "test"`. Pay a report with the test card
   `4242 4242 4242 4242`, any future date and any CVC: the page comes back
   unlocked with "Pago recibido". Buy the pack from another report: that
   report unlocks and shows an access code with 2 credits.
5. When the Stripe account is activated, swap both variables for the live
   ones (a live endpoint has its own signing secret); `card_mode` turns
   `live`.

How it works: the checkout carries `metadata.audit_id` and `metadata.plan`.
The payment is confirmed by the signed webhook and, when the buyer comes
back, by asking Stripe for the session in the return link; either one is
enough and both are idempotent (`audit/payments.py`, `fulfil`). A session
unlocks only the audit named in its own metadata, and only when Stripe
reports it `paid`. The pack's code is derived with HMAC from the session id
and the webhook secret, so only its hash is stored and the paid report can
still show it, with its credits left, to whoever holds the report token.
Rotating the webhook secret hides earlier pack codes from their reports
(the codes keep working). Refunds are made from the Stripe dashboard and do
not lock a report again; disable a pack code from `/panel` if needed.

### Selling with access codes

For clients who pay by bank transfer, Mercado Pago or WhatsApp:

```
quant-trade audit codes create --credits 3 --note "Juan, transfer 2026-09-24" --expires-days 90
quant-trade audit codes list              # ids, notes, credits; never the codes
quant-trade audit codes disable <id>      # a leaked or refunded code
```

- A code looks like `AUD-XXXX-XXXX-XXXX` (31 letters and digits, no 0/O or
  1/I/L), is printed once, and only its SHA-256 is stored. Case, spaces and
  dashes are ignored when the client types it.
- Redemption is one conditional `UPDATE` (`credits_used < credits_total`,
  not disabled, not expired) inside the transaction that inserts the audit
  or unlocks it, so a credit is never spent twice or for nothing. The paid
  audit's reference is `code:<id>`.
- An invalid, used-up or expired code gives the preview with a message that
  does not say which of the three it was. Redeem attempts count toward the
  hourly per-IP limit together with uploads (attempt counting is in memory,
  per process).
- In free mode codes are ignored and nothing is spent.

Without a terminal, the owner panel does the same from a browser: set
`AUDIT_ADMIN_KEY` to a random secret of at least 32 characters, open
`/panel` and type it. The panel creates a code (shown once), lists ids, notes
and credits (never a code or its hash) and disables a code. The key travels
only in POST bodies, never in a URL, so it is not in the access log; it is
compared in constant time, and five wrong keys from one address in an hour
lock that address out for the hour (in memory, per process). Pages are
`no-store` and `noindex`. The panel is for the owner, so it is Spanish only.
Tests: `tests/test_audit_owner_panel.py`.

### Public verification page and badge

The owner of an audit (whoever holds its token) can publish it. The page at
`/v/{public_id}` uses a random id unrelated to the audit id and shows only:
the class and its fixed one-line explanation, the audit and publication
dates, the six dimension statuses with their plain-language text, the input
hashes and `dataset_digest`, the source format, the engine version, the
declared trials and the trials used, the SHA-256 of the result, and a fixed
notice. It never shows the files, the trades, the description or the token.
The retention purge does not take a published page down: for a published
unpaid audit it keeps, in the `publication_views` table, only the fields the
page reads (class, dimension statuses, input hashes, source format, engine
name and version, declared and used trials, the audit date) and the SHA-256
of the full result, so the page, its result hash and an embedded badge stay
exactly as they were. The description, client text findings, series,
trades, statistics and files are deleted as for any other audit. The page
goes away (404) when the owner unpublishes it (the private link still works
for `unpublish` after the purge), when the operator runs
`quant-trade audit unpublish ID` or `audit delete ID --yes`; an unpublished
audit that was purged answers 410 on its private report.

The badge (`/v/{public_id}/badge.svg`, `?lang=en` for English) shows the
class, the id, the date and the fixed words:

- es: "Auditoría estadística de datos aportados – no verificados con el
  bróker – no garantiza resultados"
- en: "Statistical audit of supplied data – not verified with a broker – not
  a performance guarantee"

It never shows growth, return or profit. MQL5 Market forbids third-party
certificates in product listings, so the badge is for the seller's own site,
Telegram, forums and videos. The guard refuses "verificado", "certificado",
"aprobado", "pasarás", "certified", "approved" and "verified track record"
unless directly negated, which is what lets the fixed wording through.

### Export guides, search engines and link previews

Every platform the importers read has a short export guide in Spanish and
English (`audit/guides.py`), written from
`docs/research/audit_iteration4/formats_*.json`: `/guias` and `/guides` list
them, and each lives at `/guias/<slug>` and `/guides/<slug>` (`mt5`,
`mt5-optimization`, `mt4`, `tradingview`, `ninjatrader`, `quantconnect`,
`backtesting-py`, `vectorbt`). The upload form links the right guide under
the report and optimisation fields, the landing page links the list, and
error pages link it too. A guide states only what the importer really
does; change it when the importer changes.

`audit/seo.py` gives every public page (landing, sample, guides, terms,
privacy, in both languages) a title, a meta description, a canonical URL,
`hreflang` alternates and Open Graph tags. `/robots.txt` disallows
`/audits/` (report URLs carry the owner's token), `/webhooks/` and
`/health`, and points to `/sitemap.xml`, which lists exactly those public
pages in both languages and nothing else. Client reports, unpaid previews
and error pages carry `<meta name="robots" content="noindex, nofollow">`,
and `/audits/`, `/webhooks/`, `/health` and every error response also send
the `X-Robots-Tag` header. A shared `/v/{id}` link previews its class, audit
date and the fixed badge notice, built from the same allow-list as the page;
the page itself is `noindex` so that an unpublished audit does not stay in
search results. No page sets `og:image`: the badge is SVG, which most chat
apps do not preview. Every new page must pass the guard in both languages
(`tests/test_audit_guides_seo.py`).

### Terms and privacy

Refund promise (sergio's decision, 2026-09-24): in paid mode the pricing
section and the terms say that a full report that misreads the file
(trades, balance or dates that do not match the platform) and cannot be
fixed is refunded or replaced by a new credit. The operator honours it by
hand (`quant-trade audit codes create --credits 1` or a transfer back).

`/terminos` (`/terms`) and `/privacidad` (`/privacy`) are rendered by
`audit/legal.py` from the running configuration: the price, whether card
payments (Stripe) or access codes are on, the retention window and the
upload limit. Every page links both, and the upload form links them next to
the consent box, whose text now reads the configured retention. The date of
the wording is `legal.LEGAL_UPDATED`; change it with the text.

The operator's name, contact, address and jurisdiction come only from the
variables above; no default looks like a real person or company.
`docs/AUDIT_TERMS_TEMPLATE.md` is the template the texts were written from.

**Have a lawyer in the jurisdiction where the service is sold review both
texts before charging anyone.** They are an honest description of what the
code does, not legal advice. Points to check in particular: the refund
policy (a report already unlocked is not refunded unless the law says
otherwise), the 30-day answer to privacy requests, the liability cap,
international hosting, and whether consumer or data-protection law in the
client's country requires more (for example a data-processing register or a
named representative).

What the privacy page promises, and how the operator keeps each promise:

| Promise | How |
|---|---|
| Unpaid audits' files, report, declarations and description are deleted after `AUDIT_RETENTION_DAYS` | `AUDIT_AUTO_PURGE=true` (in-service, at startup and daily); manually `quant-trade audit purge --days N --yes` |
| The upload IP is deleted after the same window, paid audits too | the same purge run |
| A published page keeps only what it shows, until withdrawn | the same purge run; `quant-trade audit unpublish ID` or the owner's `unpublish` link |
| A client gets a copy of their data | `quant-trade audit export AUDIT_ID [--out DIR]` (writes to `outputs/`, git-ignored) |
| A client's audit is deleted completely on request (files, report, hashes, class, verification page) | `quant-trade audit delete AUDIT_ID --yes` (without `--yes` it only shows what would go) |
| A client leaves the updates list | `quant-trade audit waitlist-remove EMAIL --yes` |
| A client withdraws a verification page | `POST /audits/{id}/unpublish?token=…` from the report |
| No broker or exchange keys, no card data, no cookies, no third-party analytics | the code asks for none and sets none |

Before acting on an export or delete request, ask for the report's private
link: the audit id alone does not prove the audit is the requester's. The
link carries the token, which only its owner holds.

### Verifying a report

`audit.json` carries `inputs.digests` (sha256 of each uploaded file), the
`dataset_digest` over them, the engine version and seed, and the thresholds.
Recomputing the sha256 of the original file and re-running the audit with
the same seed reproduces the JSON byte for byte.

## Look and feel

Long pages (terms, privacy, each export guide) show a sticky "En esta
página" index beside the text on wide screens; `app.js` marks the section
being read. It is hidden on narrow screens and in print.

The report opens its verdict with the first sentence as a headline and the
rest as detail, and a sticky row of section links sits under the hero
(summary, meaning, charts, red flags, each detail section or the unlock box,
inputs). The active link follows the reader; the row scrolls sideways on
phones and is left out of print and the PDF.

"Lectura de tu archivo" shows each platform total beside the one re-counted
from the rows as a card per figure (`=` when they match, a red `≠` and border
when they do not), in the section row as its own link and in the PDF.

Metric tables share fixed columns (metric, value, evidence, note) so values
line up from one table to the next; values are right-aligned in the text
face. On phones each table scrolls sideways inside its box, never the page.
Table headers sit in `<thead>`, so a table split across PDF pages repeats them.

"Cuándo gana y cuándo pierde" leads with the best day's and time block's share
of the net result as large figures, and each row draws its net result as a
bar (dark for a gain, red for a loss, scaled to the largest group). Phones
hide the bars and keep the numbers.

The stress-test tables follow the same columns: the original result sits on a
grey first row with its evidence label, what remains is bold and turns red at
zero or below, and the change is muted.

On phones the landing's long statement drops to body-like size, and the
class range ("A a D", "A to D") is joined with non-breaking spaces so it never
splits across lines.

In code-sale mode the locked report's unlock box leads with a price card: the
single price in large type, the pack of 3 under it, and the WhatsApp button
(prefilled with the report id). The field for a code already bought comes
after it, with a secondary button.

Shared links show a 1200x630 preview image in the page language
(`static/og-es.png`, `static/og-en.png`: the mark, the landing headline, the A
to D scale with no class singled out, and the three evidence labels). The
`og:image` tag needs an absolute URL, so it is only emitted when
`AUDIT_BASE_URL` is set; private report pages never get one. Regenerate the
images with `python tools/make_og_images.py` after changing the headline.

Once a report is chosen, the upload zone turns green, swaps its arrow for a
check, hides the platform list and shows the file name and size as a pill.

A locked preview's header offers "Desbloquear" (a jump to the unlock box)
instead of printing a watermarked page; unlocked reports keep the print or PDF
button. On phones the engine and seed chips are hidden so the verdict comes
first; they stay on wide screens and in the PDF.

"Qué pide cada clase" is a list of four cards, one per class, each with its
letter in the class colour; the report's own class is filled in and labelled
"Tu informe". In print the four cards stay on one page.

With card payment on, both unlock buttons share one height, the card button
carries a card icon, the Stripe note a lock, and the bank-transfer alternative
is a quiet row with a chat icon under the price card.

Guide steps wrap long code such as
`pf.trades.records_readable.to_csv('trades.csv')` instead of widening the
page on phones.

On a locked preview each executive-summary tile shows a lock and a grey
placeholder bar (a slow shimmer, off under reduced motion) where the figure
will be; no stand-in number is ever drawn.

"Backtest frente a cuenta real" opens with its verdict as a callout edged in
the verdict's colour, shows the two shares of resampled histories as
big-figure cards, and below 900px turns its table into one card per row, each
value named by its column.

Every page shares one visual system in `audit/theme.py`: a monochrome,
high-contrast design that alternates black and light-grey sections, with one
sans-serif family for everything (Inter, tight tracking at display sizes) and
JetBrains Mono for labels and identifiers. Both are self-hosted (SIL Open Font
License, files and licences in `audit/static/fonts/`). Colour is kept for
meaning only: the class ring and the PASS/WEAK/FAIL and
MEASURED/DECLARED/NOT_MEASURED labels. Motion is CSS-only and honours
`prefers-reduced-motion`: sections fade in as they scroll, the landing's report
illustration settles into place and the long statement lights up line by line
where the browser supports scroll-driven animations (elsewhere it is simply
shown). The stylesheet is inlined so a report saved to disk keeps its look (it
falls back to system fonts offline). `/static/app.js` is the only script: it
adds drag-and-drop and file names on the upload fields, scroll reveals, the
count-up of the landing's key figures, a "working" overlay while an audit runs
and a copy button for the badge code. Every page works without it. `/static/`
serves only the files listed in `theme.STATIC_FILES`. Printing always gets a
light, static page. The landing's report illustration, including its three
figures, is labelled as synthetic data.

## Security

The security and robustness review of the web service, the importers and the
store is in `docs/AUDIT_SECURITY_REVIEW.md`: what was checked, what was
changed, and what the operator sets on Railway. Every response carries a
Content Security Policy (no script except the site's own `/static/app.js`
and the print button's handler, allowed by its hash; fonts only from the
site itself), `X-Frame-Options: DENY` and, when `AUDIT_BASE_URL` is
`https`, HSTS. The access log redacts `token=` and `code=`.

## Safety rules for this code

- Uploads, the database and generated reports are never committed
  (`state/`, `outputs/` are git-ignored).
- No secret has a default; Stripe keys live in Railway variables only.
- The service never executes, recommends or custodies anything.
- Every verdict summary, page and report passes the profit-claim guard in
  English and Spanish; a new sentence that fails the guard is a bug.
- Web tests use `TestClient` with Stripe simulated; nothing here reaches the
  network in tests.
- A new red flag or threshold needs a test and a line in this document.
- A new English warning, note or red-flag detail needs its Spanish rule in
  `audit/i18n.py`; the Spanish text passes the guard too.
- Badge, verification and challenge texts never imply future results;
  changing their fixed wording needs a test.
- Access codes are stored hashed and printed once; `codes list` never shows
  them.
- The terms and privacy pages pass the guard in both languages; anything the
  privacy page promises needs a command that does it and a test.
