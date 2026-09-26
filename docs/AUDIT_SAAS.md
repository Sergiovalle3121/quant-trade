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

## Why trust it (`pages.TRUST_COPY`, landing `#confianza`)

The landing has a section for a first-time visitor, "Trabajo real, no humo"
(Real work, not hype), in Spanish, English and Portuguese. Every point links
to the page that proves it: the full sample report, the methodology and its
papers, the check page for a report's SHA-256, the privacy policy (a file is
never published, is deleted after the retention days if unpaid, and an account
can be deleted) and the terms (refund when the report misreads the file). One
point says Rigor sells no bots or signals and that the guard stops any text
promising results. "Who is behind it" shows `AUDIT_OPERATOR_NAME` and
`AUDIT_OPERATOR_ADDRESS` only when both are set, and the WhatsApp line only
with `AUDIT_CONTACT_URL` (`tests/test_audit_landing_trust.py`).

## Portuguese pages (`audit/portuguese.py`, `/pt`)

The landing, its prices and its questions exist in Portuguese (Brazil and
Portugal) at `/pt`, and every case page at `/pt/para/<slug>` with its own
Portuguese slug (`Audience.slug_pt`; a Spanish or English slug under
`/pt/para/` moves there), and every export guide at `/pt/guias` and
`/pt/guias/<slug>` (`Guide.slug_pt`; the guides name the Portuguese form
fields). The language switch on these pages offers the other two languages.
The methodology (`/pt/metodologia`), the report check (`/pt/comprovar`) and
the comparison of two reports (`/pt/comparar`) have Portuguese pages, linked
from every Portuguese page and offered in the language bar of their Spanish and
English twins (`tests/test_audit_trust_pages_pt.py`). Pages not translated yet
(the terms and the privacy policy, until the Spanish ones have had their legal
review, and the public verification page) open in English from a Portuguese
page, never in Spanish. The profit-claim guard reads Portuguese too
(`guard.PORTUGUESE_CLAIM_PATTERNS`: lucrativo, rentável, garantido, sem risco,
"vai ganhar", aprovado…, with "não", "nem" and "sem" as negations), and
`tests/test_audit_portuguese.py` runs it over the page and opens every link on it.

An upload from `/pt` is refused in Portuguese: `ParseError.localized("pt")`
reads the English message through the rules of `audit/errors_pt.py` (the
file and field names inside a message are translated from its small tables,
values from the file are kept), the service's own messages have their
Portuguese in `portuguese.MESSAGES_PT`, and the error page, a missing page
under `/pt/` and any error with `?lang=pt` are Portuguese, with "O que fazer:"
for the fix. A message no rule knows stays in English, never half-translated;
`tests/test_audit_errors_pt.py` walks every refusal the importers write, so a
new one needs its Portuguese rule.

## What the client uploads

| File | Required | Columns (aliases accepted, case-insensitive) |
|---|---|---|
| Platform report | this or the equity file | The file as the platform writes it; see "Importers" below. One file gives both the closed trades and the balance curve. |
| MT5 optimisation export | no | The XML the MT5 optimiser exports. Its passes become the MEASURED number of trials in the deflated Sharpe. MT5 names its columns in the terminal's language; Pass, Result, Profit, Trades and the other standard columns are read in English, Spanish, Russian, Portuguese, German, French, Chinese and Japanese (names from the MT5 help in each language). A translated forward pair is named only when its own words say forward and back. Nothing past the first EA input is renamed, so inputs called Drawdown, Symbol or Custom stay inputs. A header in another language is refused with the ask to export it with the terminal in English or Spanish (View > Languages). |
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
at least 30 return observations. Platform reports and the MT5 optimisation export
may be 10 MB (about 11,000 optimisation passes at some 900 bytes each).
A larger optimisation export is refused with what to do instead: optimise
again with the genetic algorithm or narrower ranges, or upload the report alone
and type the pass count in "Configurations tried" (then DECLARED).
A forward export whose Forward Result cell is blank or not a number on some
passes is still read as a forward export: those passes are left out of the
forward review, and the plateau check never reads its Profit column.

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

NinjaTrader's Trades export is read with English or French headers ("Pos.
marché.", "Prix d'entrée", "Longue"/"Courte") and with the `90.00 $` amount
suffix. Its Executions export (`Instrument;Action;Quantity;Price;Time;...;E/X`,
European decimals) has no profit per trade, so fills are paired first in,
first out per account and instrument and priced with the contract's point
value from `FUTURES_POINT_VALUE_USD` (CME contract specifications,
cmegroup.com, as of 2026-09-25: ES 50, MES 5, NQ 20, MNQ 2, CL 1000, GC 100
and the rest listed in the code); the commission of each fill is spread over
its contracts. A contract missing from that table is refused
(`ninjatrader_executions_symbol`) with a request for the Trades tab, and
positions still open at the end are left out with a warning. Compact contract
codes (`MNQZ6`, `ESH25`) resolve to their root. The Account Performance
Trades export, which has no "Trade number" column, is read like the
Strategy Analyzer one (`Profit` is net of the itemised commission). A file
that holds several accounts (a copy-trading export repeats each trade on
every account) is read for the account with the most closed trades, with
the same warning as FX Blue, since adding the accounts up would mix
balances. Layouts were taken from public importers of NinjaTrader files
(tradetally, deltalytix, LuxAlgo trade-journal's copy-trading fixture);
tests use synthetic rows (`tests/test_audit_ninjatrader_exports.py`).

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

Any other platform (`audit/universal.py`, guide `/guias/csv-universal`,
`/guides/universal-csv`): a CSV or Excel table that no importer above claims
is read by its column names, in English, Spanish, Portuguese, French, German
and Italian (`universal.SYNONYMS`, normalised without accents, brackets or
punctuation, the most specific name first: `Side` before `Type`, `Executed`
before `Amount`). Up to 15 title lines above the header are skipped. Two
shapes are read:

- one closed trade per row (`universal_trades_csv`): entry and exit time,
  quantity, entry and exit price are required; side, profit, commission (all
  fee columns added up), swap, symbol and account are optional;
- one fill per row (`universal_fills_csv`): time, quantity and price are
  required; fills are paired first in, first out per account and symbol,
  and positions still open at the end are left out with a warning.

Each assumption is a reading warning: a profit column that the price moves
explain better once commission is added back is read as net; with no side
column the side comes from the quantity's sign (or the profit's); with no
profit column the result is price move x quantity x the `Multiplier` column
(1 without one); fees charged in another coin than the price (`0.0002 BNB`
on `BTCUSDT`) are left out of the costs. Unix times in seconds or
milliseconds are read. The report lists which column was read as what
(`column_*` keys under the platform's fields). A table that names some of
the columns but not enough gets `universal_columns_missing`, which names
the missing ones and the columns found. `import_report(..., columns=...)`
takes the customer's own role-to-column mapping; the upload form asks for
it under "¿Tu plataforma no aparece o su archivo da error? Indica sus
columnas" (fields `col_<role>`, 200 characters each with control
characters such as NUL dropped, only used with a report file), and `app.js`
suggests the file's own header names in a datalist when a CSV is picked
(nothing is uploaded until the form is sent). A named column missing from
the header is listed in the error, and one column chosen for two fields
(entry and exit time, say) gets `universal_column_twice` naming both. An equity curve
(`timestamp,equity`) is not a trade list and still gets `unknown_format`.
Refusals say what is wrong: a trade list put in the equity-curve box gets
`trade_list_as_curve` (upload it as the platform report), a file where every
exit comes before its entry gets `exits_before_entries` (the time columns may
be swapped), and a fill list that never closes a position gets
`no_closed_trades` with the number of positions left open (a fill list in
the curve box gets `trade_list_as_curve` too). A column the customer mapped
that holds no numbers (or no dates, for a time) gets
`universal_column_unreadable`, naming the column and its role. Format codes
never appear in customer text (`tests/test_audit_import_messages.py`).
A table with entry and exit prices but a single time (Bybit's Closed P&L)
gets `universal_close_time_only`: without opening times holding time and
entry timing cannot be measured, so it asks for the executions export (Bybit
Trade History) instead. A `Contracts` column names the instrument when no
symbol column exists and `Exec Qty` is the size.
Rows repeated in every column are counted once when the table has an id
column (Position, Ticket, Deal, Transaction ID, Trade number...; never an
order id, which an order's partial fills share, nor a bare ID) and the row's
id is filled in, as when two exports
are pasted together (`universal.drop_repeated_rows`, for the universal reader
and every delimited named format); the report says how many. Rows that share
an id but differ (partial closes) are all kept, and a table without an id
keeps identical rows, since two identical fills can be real.
Tests use synthetic rows (`tests/test_audit_universal_import.py`).

Platform exports the universal reader is checked against
(`tests/test_audit_platform_catalog.py`, synthetic rows in each platform's
public column layout, as the open-source journal tradetally reads real
files): Tradovate Performance (a buy fill paired with a sell fill per row;
whichever came first opened the trade) and Orders, TopstepX/ProjectX
trades, Interactive Brokers Flex Trades and the Activity Statement (its
`Trades,Header`/`Trades,Data,Order` lines merged by column name; subtotal
lines dropped), Charles Schwab Realized Gain/Loss and Transactions,
Webull orders (the fill price, not the limit), thinkorswim's Account Trade
History section, TradeStation (a clock-only `Exec Time` joined to `T/D`),
tastytrade (multiplier column), Fidelity ("YOU BOUGHT ..."), E*TRADE, eToro
closed positions, XTB xStation 5 closed position history (CSV, or the XLSX with account
rows above the header and an empty first column; the `Total` row is skipped by
`universal.without_totals` and a second financing column such as `Rollover`
is added to the costs), DEGIRO Transactions in English, Spanish, Portuguese,
French, Dutch or German (the quantity's sign is the side; the date and the
clock-only time column are joined; the transaction and AutoFX costs, in euros,
are subtracted as they are even on shares quoted in another currency),
Trading 212 history (`Market buy`/`Limit sell` in `Action`; deposit and
dividend rows have no price and are dropped; `Result` is in the account
currency, so the contract size inferred from it absorbs the exchange rate),
KuCoin filled orders (`Avg. Filled Price`, `Filled Amount`), cTrader History
(`07 Aug 2026 21:50:45.162` dates, a `Net AUD`/`Net EUR`/… result in the
account currency), Rithmic Completed Orders (`B`/`S`, `Qty Filled`,
`Avg Fill Price`, `Update Time (EDT)`: a zone abbreviation in brackets in the
column name applies like an offset), Binance
(with `Fee Coin`), Kraken, Coinbase and Sierra Chart's Trade Activity Log (only
`Fills` rows). A zone stated in a time column's name (`Filled Time(UTC+02:00)`,
`Transaction Time(UTC+10)`, `Date(UTC)`) applies to every cell that carries
none, so those times are no longer reported as naive; `+0530` reads as five and a
half hours, and an offset no clock uses (outside -12 to +14 hours) is ignored and
the times stay naive. A blank clock next to its date reads as midnight. A row
left out for an unreadable time, with a readable price and quantity, is named
in the warnings (its symbol and the time as written, five rows at most, then a
count), because the trade it opened or closed is missing from the results. A `Contracts` column is
taken as the instrument only when there is no symbol column and its cells are
not numbers. A side named by the position (`Open Long`, `Close Long`,
`Open Short`, `Close Short`, as Bybit's and Bitget's derivatives exports write
it) is that trade's direction on a closed-trade row; on a fill, closing a long
sells and closing a short buys. `Fees Paid` and `Exec Fee` are costs. Time styles read:
`20260115;093000`, `2026-01-15, 09:30:00`, two-digit years, a zone
abbreviation (`EST`, `CET`) or offset after a day/month date, and a month
name in English, Spanish, Portuguese, French, German or Italian (`07 Aug
2026`, `02-Jan-2026`, `15 ene 2026`, `09 out 2026`, `03 août 2026`, `06 Okt
2026`, `07 ott 2026`). When a file has several `Net <currency>` columns, the
one in the currency of its `Balance <currency>` column is the result. A zone
word in a column name (`EDT`, `CST`) is a fixed offset for every row: a
Rithmic export that prints the zone at export time reads winter trades one
hour off under `EDT` (limitation, not corrected). Day/month
order that no day past 12 settles is taken from a year-first column of the
same rows (Tradovate's `Trade Date`) or another day/month column of the file;
otherwise the `ambiguous_dates` error stands. A file listed newest first
keeps its order reversed among fills with the same time. Without a profit
or multiplier column, a CME contract code (`ESZ6`, `MNQ DEC26`, `ESZ6.CME`;
never a bare root, which may be a share ticker) is priced with
`FUTURES_POINT_VALUE_USD`, with a warning. Eurex and ICE codes are priced
the same way from `FUTURES_POINT_VALUE_OTHER` (the exchanges' contract
specifications, as_of 2026-09-25), which also records each contract's
currency: FDAX x25, FDXM x5, FDXS x1, FESX x10, FSXE x1, FVS x100 and the
Schatz/Bobl/Bund/Buxl futures x1,000 in EUR, FSMI x10 in CHF; ICE Brent (B)
x1,000, Gasoil (G) x100, Sugar No. 11 (SB) x1,120 per cent, Coffee (KC) x375,
Cotton (CT) x500, Cocoa (CC) x10, Orange juice (OJ) x150 and the US Dollar
Index (DX) x1,000 in USD; B3 (Brazil, its "Contract Point Value" sheet)
Ibovespa (IND) x1, Mini Ibovespa (WIN) x0.2, US Dollar (DOL) x50 and Mini US
Dollar (WDO) x10 in BRL; MexDer (Mexico, its terms and conditions) S&P/BMV
IPC (IPC) x10, "MINI" IPC (MIP) x2 and the US dollar (DA, USD 10,000 quoted in
pesos) x10,000 in MXN, read in MexDer's series codes (`IPC DC26`, `MIP MR27`,
`DA19 DC16`: the Spanish month's first letter and next consonant). The report prints amounts without a currency sign,
so a file in euros or reais is not shown as dollars. The warning names a non-USD currency, and a file
that mixes currencies is told the results were added without conversion.
Other single-letter ICE roots (FTSE 100 `Z`, WTI `T`) are left out because
they would read CME codes such as `ZNZ6` as another contract. NinjaTrader
executions stay CME-only. A profit that fits either net or
gross reading exactly (one trade per symbol) is read the way that gives a
round contract size. Fees in another coin than an exchange pair's quote
currency are left out; fees of shares or futures always count.

Containers (`importers.unwrap`, used by the import, format detection and
the column screen): a zip that is not a workbook is opened when it holds
exactly one CSV, TXT, TSV, HTML or Excel file (`__MACOSX/` copies and hidden
files are ignored; the file inside obeys the same size limit). A web page
that is not a MetaTrader report is read as a trade or fill table with the
universal reader, which covers the tables brokers save with a `.xls` name;
if no importer knows it, the column screen offers its columns. Files that
cannot be read are refused with how to get one that can: an old binary
Excel workbook (`legacy_xls`: save it as .xlsx or CSV), an OpenDocument sheet
(`opendocument_sheet`), a PDF statement (`pdf_statement`: download the CSV,
Excel or HTML history), and a zip with none or several exports
(`zip_contents`). An Interactive Brokers Flex Query statement in XML (its
default format, `<FlexQueryResponse>`) is read as the Flex CSV: one row per
`<Trade>` at `EXECUTION` level with the attribute names as columns
(order-level and summary rows are ignored; parsed with the same no-DOCTYPE
guard as workbooks); a statement with no executions is refused with
`flex_no_trades`, naming the Trades section to add; one with more than
`MAX_FLEX_COLUMNS` (200) attribute names, more than `MAX_ROWS` trades, or a
table past the report size limit is refused with `flex_too_large`. A member is unpacked in bounded chunks and never past
the limit, whatever size it declares, and only stored or deflated members
are opened (the same holds for workbook members). A web page is parsed once
per import; the column screen offers a web table only up to
`mapping.MAX_HTML_ROWS` rows and `MAX_HTML_CELLS` cells. The upload pickers offer `.htm .html .csv .txt .tsv .xlsx
.xls .zip` (`pages.REPORT_ACCEPT`).

B3's Área do Investidor Negociação extract is read by column name only
(`tests/test_audit_b3.py`): `Data do Negócio` is the fill time and always day
first (`universal.DAY_FIRST_NAMES`), `Tipo de Movimentação` the side
(Compra/Venda), `Código de Negociação` the ticker (ranked above `Mercado`,
which holds Mercado à Vista or Fracionário), and a fractional-market ticker
with a trailing F (`PETR4F`) pairs with `PETR4`
(`universal.whole_lot_tickers`, only with B3's own column names). The first
two names and the F come from open-source importers of real files; the rest
is inferred, so B3 is not a named platform or guide until a real export
confirms it. A wrong guess falls back to the column screen.

Robinhood's Account Activity report (`robinhood_csv`, the columns `Activity
Date`, `Instrument`, `Description`, `Trans Code`, `Quantity`, `Price`,
`Amount`, as Robinhood's help centre and open-source importers describe it;
tests in `tests/test_audit_robinhood.py` use synthetic rows) is read by
`importers._parse_robinhood`. `Buy`/`Sell` trade shares and
`BTO`/`STO`/`BTC`/`STC` trade options, paired first in, first out per share
symbol or per option contract (the contract is taken from the Description,
"SPY 3/15/2024 Call $500.00", at `OPTION_MULTIPLIER` = 100 shares). Cash rows
(deposits `ACH`, dividends `CDIV`, interest, fees) are not trades. An option
that expires (`OEXP`), is assigned (`OASGN`) or exercised (`OEXER`) closes at
no premium; its record shows `EXPIRED_OPTION_PRICE` (0.01) as the exit price
because a trade needs a positive price, and its result is computed at zero.
Contract sizes are stated, not inferred (`_Draft.known_sizes`: 100 per option
contract, 1 per share), so an expiry never changes an option's size and no
currency-drift warning applies. Open lots are queues, and pairing stops with
`too_many_trades` as soon as it passes `MAX_TRADES`.
The shares an assignment delivers come on their own row, opened at the
strike, so the total is right but the win rate and average trade count one
position as two (`ROBINHOOD_ASSIGNED_WARNING`; expiries have their own
`ROBINHOOD_EXPIRED_WARNING`). When no share trade in the underlying at the
strike (within 0.5 % or a cent) falls within `_DELIVERY_DAYS` (4) days of the
assignment, `ROBINHOOD_UNDELIVERED_WARNING` says the stock move is missing.
Share rows are indexed by symbol and day, so the check stays linear. Regulatory fees are
the gap between `Amount` and the fill's value, as commission. A split
(`SPR`) or symbol exchange (`SXCH`), whose leaving shares carry an `S`
("200S"), rescales the lots held. Assumptions and limits, each warned in the
report: Robinhood shares are read as long only, so a `Sell` (or `STC`/`BTC`)
beyond the open position closes something opened before the file starts and
is left out (`ROBINHOOD_UNOPENED_WARNING`); other share movements
(transfers `ACATI`, mergers) are left out (`ROBINHOOD_MOVES_WARNING`). Dates
carry no clock, so holding times are in whole days. Within a day, opens come
before closes and expiries last.

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
- When the rebuilt balance reaches zero or below, the error asks for the real
  starting balance only when 10,000 was assumed; when the file or the client
  gave it, it says the account lost all its money on that date and asks for
  the history up to that day.
- A CSV line longer than 32 KB (`MAX_CSV_LINE_BYTES`) is refused: no real
  export has one, and pandas takes minutes on a 5 MB line of fields.
- An optimisation export whose title names another robot, symbol or
  timeframe than the MT5 tester report, or whose optimised inputs share no
  name with the report's inputs, is refused (`optimization_mismatch`): its
  passes would count as the report's trials and its neighbours would judge
  another strategy. A broker suffix (`EURUSD.m`) still matches.
- An optimisation export cell placed past column 4,096 by `ss:Index`
  (`MAX_OPTIMIZATION_COLUMNS`) ends its row: a 200-byte crafted index
  would otherwise pad one row with hundreds of millions of empty cells.
- An account value over 10^15 (`MAX_ACCOUNT_VALUE`), or a return over
  10^6 in one period (`MAX_PERIOD_RETURN`), is refused (`value_too_large`):
  a 1e308 profit overflowed every later sum and the report page failed.
  The capital section is not measured when its reference fall is not a
  finite number.
- A date more than a day after the upload (`FUTURE_SLACK`, for time
  zones) is refused in the equity, report, trades, benchmark and live files
  (`future_dates`, ES and EN): a record in 2150 is a damaged file. A monthly
  series may hold this month (dated by its last day), and a fund table's
  months that have not happened yet are dropped when they are blank, a
  dash or 0; a future month that moves the account is still refused.
- NUL characters are dropped when a report is decoded (`decode_text`) and
  from the stored report page: PostgreSQL refuses text holding one, so a
  stray NUL in a robot's name failed the upload with a server error. A
  waitlist address with a space or control character, and an owner-panel
  note with a control character, are refused for the same reason, and an
  id holding a NUL in a URL (`/v/%00`) is simply not found (`_usable_key`).
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
Tiles named with a trader's term (total return, drawdown, drawdown p95,
Sharpe, profit factor, break-even cost) carry one plain line under the name,
for example "lo ganado por cada 1 perdido" under the profit factor; locked
tiles show the name only.

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

The `/ejemplo` backtest trades two pairs, EURUSD and AUDUSD (`SAMPLE_SYMBOLS`,
the pair drawn from its own random stream, so no result changes), and holds
each trade between 1 and 7 hours (`SAMPLE_HOLD_HOURS`, also its own stream),
so the per-instrument and "Cómo se comporta al perder" sections have real
variety to show. The class stays C.

"Qué hacer ahora" / "What to do now" follows "Qué significa para ti": up to
three checks for whoever runs the robot, from the live comparison, serious
data flags, costs, trials and out-of-sample, then the seller questions and
keeping the report, each linked to its section. They are questions and
checks, never a trading instruction. A line under the verdict explains the
MEASURED / DECLARED / NOT_MEASURED tags. Generic prop-firm rules show no
preset id and no "published on the date shown" assumption, and the
simulator's column reads "En las simulaciones del historial".

When a live account is uploaded, one line under the verdict gives its
comparison badge (Coherente, En el borde, No coherente, Revisar) and the
account's trading result against the money deposited, linked to the
comparison section: the class grades the backtest, and a buyer should not
have to scroll to learn the real account lost money. Locked reports keep it
back. The "Plan para subir de clase" says on which side of each threshold a
number falls, and no longer asks for the optimisation export when the trial
count already comes from the files.

The `/ejemplo` report carries a synthetic live account, a Myfxbook CSV
export built in `audit/sample.py` (0.1 lots, a fifth of the backtest's
size). It trades the backtest's last 60 business days too, skipping about
one signal in eight and adding four trades of its own. That lets "Mismas
fechas, operación por operación" pair 55 of 59 trades with slightly worse
fills. It then trades 120 business days after the backtest with a thinner
edge and a losing stretch. It carries a 500 top-up after that stretch
(DEPOSIT_DURING_DRAWDOWN), a 300 withdrawal and an open position with a
35.00 floating loss, so "El dinero real de la cuenta" shows every part. Next
to almost five years of backtest it comes out "No coherente"; the dates
overlap, and the report says so.
The sample backtest also starts with 782 business days from a random stream
of their own (from 2 January 2020, `SAMPLE_LEAD_DAYS`), so its trades span
almost five years: "¿Cómo le fue en las crisis conocidas?" covers the covid
fall and both 2022 windows in full, and "¿Sigue funcionando en el periodo
reciente?" reads "Se mantiene". With 120 passes counted, its Sharpe beats
the luck of the search without the margin the multiplicity dimension asks
(DSR 0.91 against 0.95), so the luck section reads "Supera a la suerte, sin
margen": beating the luck is a DSR of 0.5, passing the dimension is 0.95,
and a Sharpe between the two gets that third state instead of a plain
"Supera". Its optimisation file is a
normal export, so the plateau section is shown; that section ends with a
line saying that a forward export adds "¿Aguanta en el periodo forward?".

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
  When the file itemises each trade's commission and swap, the win rate
  (headline tile, trade table, long/short split) counts a trade as won only
  after its own fees, the same rule as the weekday, hour, instrument and
  losing-streak tables; the gross share stays as "Aciertos antes de
  comisiones", and the annualised table no longer repeats the win rate.
  The long/short net results use the same fees, so they add up to the
  trades' net. The cost table recomputes each trade from price and size;
  when its no-extra-cost row differs from the trades' net, a note gives the
  gap (price rounding, currency conversion). The resampled time under the
  peak reads "median" and "in 1 of every 20" instead of p50/p95, and the
  header names the engine version and simulation seed in words.
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
  A preset with a best-day (consistency) rule (`best_day_limit`,
  `best_day_basis`: FTMO 1-Step, best day at most 50 % of the positive days'
  gain; Topstep, best day at most 55 % of the profit target) is checked at
  the pass on daily closes: `best_day.pass_within` is the share of all paths
  that pass with the best day inside the rule, and `breach_share_of_passes`
  the share of passes that break it. The report says it in one line: many
  refused payouts come from this rule.
- `firmfit.firm_fit` ("¿Con qué firma encaja tu historial?"): every
  published preset (never the generic one) on the same resampled paths and
  seed, 2,000 paths each, grouped by firm and program. A program's pass
  chance is the product of its phases' (phases taken as fresh starts; The5ers
  Bootcamp counts its preset three times), with the same product within the
  best-day rule when a phase has one, and the weakest phase's main failure.
  Ranked by the figure that matters for a payout (within the best-day rule
  where the firm has one), ties by name. Figures read "≥99%" at the top.
  When every program is at or above 99 % or at or below 1 %, the table
  gives way to one sentence (and, for all failing, the most common reason).
  A program where no path fails reads "Nothing in the simulations". When
  the balance hides open losses, the table repeats that its figures are
  optimistic. MEASURED under the simulator's assumptions; it compares rules
  and never recommends buying a challenge. No class change.
- `vendor_questions`: neutral questions for the seller of a robot, driven by
  the red flags and the missing inputs, in Spanish and English. It never
  says whether to buy.
  The report's own findings add questions too: one instrument carrying the
  result (`one_carries`, `mostly_one`), losers held longer, re-entering fast
  or doing worse after losses, a recent average per trade under half the
  earlier one, and a cost dimension that is WEAK or FAIL (the costs question
  then shows even when the file lists fees).
  For an account history the backtest questions (modelling, trials, held-out
  period, assumed costs, "is there a live account") give way to two for an
  investor: whether other accounts of the same strategy were closed or
  restarted, and asking for the backtest of the same robot to compare trade
  by trade. The class sentence then says "account history" instead of
  "backtest" (C and D). The out-of-sample explanation and plan step no longer
  ask an investor for "the date the optimisation ends": they ask the provider
  since when the robot has run with unchanged settings (declared as the
  out-of-sample start) and for the matching backtest.

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
| `PROFIT_CONCENTRATION` | ≥ 10 trades with a net gain after fees; the best 1, 2, 3 or 5 trades carry ≥ 33, 50, 65 or 80 % of the winning trades' total and removing them with as many worst losses takes ≥ 50 % of the net result | ≥ 20 trades (from 10, only one trade carrying ≥ 90 % of the gains and taking ≥ 90 % of the net result with it); the best 1, 2 or 3 carry ≥ 50, 65 or 80 % and removing them with as many worst losses takes ≥ 80 % of the net result |

`PROFIT_CONCENTRATION` needs both conditions. The share of the winning trades'
total keeps a thin net over many noisy trades from reading as concentration (on
simulated normal trades it fails in about 0.1 % of 20-trade histories and never
from 30 on; on very heavy-tailed ones about 9 % at 20 trades, 4 % at 30 and
1 % at 60). The net-result condition keeps a big winner cancelled by a big
loser (the net then comes from the other trades) from failing. Splitting the
big trade in two or three does not escape it, and shares print rounded down
to one decimal, so 49.8 % never reads as 50 %. A history whose result rests on
a few trades says little about the rest of the system, and one outsized trade
is what a data error looks like, so it fails the data dimension (class D).
Found by the bug hunt: an MQL5-signal file with one trade of 1e9 on a 10,000
deposit was class B.

When `HIDDEN_FLOATING_DRAWDOWN` fires, the resampled risk, the prop simulator
(and the capital section, when it still shows figures)
open with an "Open losses" callout saying their figures leave those losses out and
come out optimistic. On any balance-only file the summary tiles read "Maximum
drawdown (closed trades only)", and a fall under 0.05 % prints as 0.0 %, never -0.0 %.
A clean account review vouches for "no large open loss" only when the file states
the floating result; otherwise it asks for the equity curve with floating results.
A file that already loses before any extra cost shows its break-even tile as 0
with "already negative before any extra cost", never a negative cost, and large
percentages carry thousands separators (+191,136.0 %).
Ratios and break-even pips carry them too (877,194.39). No share prints as -0.0 %
or -0 % (a month in the monthly table that rounds to zero reads 0.0 %),
and a share short of a whole (-99.7 %) never rounds to -100 %: it gets one more
decimal, and past that it reads as a bound (>99.99 %). Every fact
card (risk, account, plateau, timing, capital and its trade pace) shows its
MEASURED / DECLARED / NOT_MEASURED tag beside the number.
Percentages in the metrics, yearly and rolling tables that are smaller than
0.01 % keep two significant digits (-0.000012 % on a history in tiny units),
never -0.00 %. Money amounts in the trade statistics and the other tables
keep four significant digits under 1 (0.004123, -0.00312), never -0.00.
The stress table and its tiles follow the same rule (0.0 %, 0.00), and contract
sizes in the reading warnings print as plain numbers (5,000,000, never 5e+06).
Cost reasons carry thousands separators, and the class plan says in plain Spanish
what the class would be if the dimension passed. The vendor question on a live
record asks for "at least N months" only up to 24 months; past that it asks for
auditable history and says how many months it would take to tell the Sharpe
apart from chance. MT4 header fields (initial deposit, modelling, modelling
quality, chart errors, parameter values, spread) have Spanish and English names.

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

The flow-adjusted curve is chained around each deposit and withdrawal at the
moment it happened (a time-weighted return): trading before the money moved
is measured on the balance before it, trading after on the balance after it.
An account emptied by a withdrawal and refilled later is read; trading on a
zero or negative balance is refused as before. A trade that closes on what a
withdrawal left, for more than that whole remainder, was opened on the balance
before the withdrawal and is measured on it; the file-reading notes name the
first such day. The account section then adds a "Para preguntar" line with
that date and the number of such days: the account was traded almost empty,
a percentage on almost nothing explodes, and the buyer should ask why almost
everything was withdrawn and trading went on with what was left (`account.near_empty`,
MEASURED; the reader writes the count to the report metadata, which the
report never lists as the platform's own figures). Informational: no flag,
no class change. Real-file check (40 files): one signal export shows it.

| Code | WARN | FAIL |
|---|---|---|
| `GAIN_INFLATED_BY_FLOWS` | percentage gain ≥ 10 % while the trading result is ≤ 0 or below a third of the gain on the money deposited | — |
| `DEPOSIT_DURING_DRAWDOWN` | a deposit after the first trade while the flow-adjusted drawdown is ≥ 20 % | — |
| `FLOATING_LOSS_AT_END` | the declared floating result is a loss ≥ 10 % of the balance | ≥ 30 % |

Limitations: broker credit and bonus rows of an MT5 history count as flows;
the floating result is the platform's figure at print time, not a history
of floating losses; a history printed after the open losers close shows
none of it.

A history whose first trade comes before any deposit (no deposit on or
before the first entry) gets an informational line in the account section,
"Para preguntar": the start may have been cut, the % gain is measured from
the file's first balance, and the buyer should ask for the export from the
day the account opened (`starts_with_deposit`, `first_trade`). It is not a
red flag and does not change the class. Real Myfxbook export
Eric-Lingren ParseFolio shows it; the other five do not.

### Lone peak or plateau (`audit/plateau.py`)

For buyers of an optimised robot. Needs the MT5 optimisation export (at
least 10 passes with a Profit column and a parameter that varies). The
Result column is never read as a profit: it is the optimisation criterion,
by default the final balance, so an export without Profit is NOT_MEASURED. The importer keeps each pass's numeric cells
(`OptimizationSummary.table`) and the tester report's inputs as
`input_values`. The chosen pass is the one matching those inputs, or else
the most profitable pass (the section says which). Its neighbours are the
passes one step away on a single parameter (the next lower or higher value
tried), every other parameter unchanged. MEASURED from the export's rows:
passes, share of passes with a profit, the chosen pass's top share, the
neighbours found, the share of neighbours with a profit and the share of the
chosen profit their median keeps.

| Code | WARN | FAIL |
|---|---|---|
| `ISOLATED_OPTIMUM` | at least 2 neighbours, a positive chosen profit, and fewer than half the neighbours with a profit or a median keeping under half of the chosen profit | — |

Limitations: the profits are the optimiser's, not re-computed trades; a
genetic or sparse optimisation may not have tried the neighbours (the
section then shows them as NOT_MEASURED and raises nothing); only the MT5
tester report's English "Inputs:" rows are matched.

### Does it hold in the forward period (`audit/forward.py`)

For buyers and developers of an optimised robot. MT5 can run every pass of
an optimisation again on a later "forward" period the optimiser did not
rank on; its forward export (Forward Results tab, Export to XML) has a
"Forward Result" and a "Back Result" column for each pass (the criterion in
the forward and in the main period, per the MT5 help and MQL5 article
14549), and its Profit, Trades and other columns are the forward period's.
The same upload field takes it; the plateau section then steps aside
(NOT_MEASURED: its Profit would be the forward one). Needs at least 20
passes. MEASURED from the rows: the Spearman rank correlation between back
and forward results, how often the best tenth of the passes by back result
(at least five) end the forward period with a profit against all passes,
their median forward profits, and where the pass matching the tester
report's inputs lands in the forward period.

| Code | WARN | FAIL |
|---|---|---|
| `FORWARD_NOT_HELD` | ≥ 20 passes and a rank correlation ≤ 0, or the best backtest passes end the forward period with a profit less than half the time and no more often than all passes | — |

The columns are matched by their English names. A file with two unknown
columns between Pass and Profit (the forward layout, from a terminal in
another language, for example) is not read as a plain export: both this
section and the plateau section say NOT_MEASURED and ask for an export from a
terminal set to English, because its Profit column would be the forward
period's.

Limitations: one forward window, chosen by whoever ran the optimisation;
the criterion is compared by rank, so a custom criterion works too; a
genetic optimisation lists only the passes it evaluated.

### Does it still work in the recent period (`audit/decay.py`)

For buyers of a robot or a signal with a long history: "the total looks
good, but does the last stretch still add up?". Needs at least 60 closed
trades over at least two years. The span from the first entry to the last
exit is cut in three equal stretches of time; the trades that exit in the
last one are the recent period (at least 20), the rest the earlier one (at
least 20). MEASURED for each period: trade count, net result after the fees
the file itemises, average net per trade and hit rate; the Welch distance
between the two averages in standard errors; and a table of each calendar
year of exit (trades, net result, hit rate).

| Code | WARN | FAIL |
|---|---|---|
| `EDGE_FADING` | the earlier trades average a profit, the recent ones zero or a loss, and the recent average sits 2 or more standard errors below the earlier one | — |

Without the flag, a recent average per trade under half the earlier one
(`decay.WEAKER_SHARE`, still above zero or within chance) shows as "Más
débil" / "Weaker" instead of "Se mantiene", with the two averages and the
change. Display and seller question only; no flag and no class change.

Limitations: the thirds are cut by time, so a history whose pace changed
has periods of different sizes; trades are treated as independent, which
understates the noise of a strategy whose trades cluster; it describes the
history and says nothing about later periods.

### What is left once luck is discounted (`audit/luck.py`)

The deflated Sharpe gives a probability; this section restates the same
evidence in three numbers a buyer can read. It uses the trial count and the
Sharpe spread of the multiplicity dimension, so it never disagrees with it:

- **Sharpe from luck**: E[max Sharpe] of the counted configurations with no
  skill (Bailey & López de Prado), annualised. It is the deflated Sharpe's
  threshold, so "beats luck" holds exactly when DSR ≥ 0.5.
- **Years of history needed**: `span × (luck / observed)²`, the minimum
  backtest length of Bailey, Borwein, López de Prado and Zhu (2014): the
  unskilled spread shrinks as 1 / years.
- **Sharpe after the haircut**: Harvey & Liu (2015) with Bonferroni: the
  one-sided p-value times the trial count, turned back into a Sharpe with
  the same standard error. It is zero whenever the Sharpe does not beat the
  luck.

When the files count no configurations (nothing declared, no optimisation
export or variants), the section shows a table for 10, 100 and 1,000
configurations instead and asks the buyer to put that question to the
vendor. Needs a positive Sharpe, 20 returns and 28 days of history; under a
year it adds a line that annualised Sharpe ratios move a lot. Above 100
years the page prints "más de 100 años". Informational: the class comes from
the multiplicity dimension as before. Real-file check (40 files): classes
unchanged; values from under 1 month to over 100 years, both shown in words.

### What living through the history was like (`audit/ride.py`)

From the equity curve in calendar days: the longest stretch below a previous
high (to the day it is regained, or open at the file's end), the deepest
fall's days from high to low and back, the worst day (only when the curve
has a point on most days, median gap ≤ 4 days), the worst calendar month,
the share of months that end up and the longest run of losing months. Needs
20 points; months need 3. A curve rebuilt from closed trades carries a note
that open losses do not show. Hidden on fund records, whose own section
already shows months and time under water. The depth itself is not repeated:
the summary tiles show it.

### Losing streaks next to chance (`audit/streaks.py`)

The trade statistics put the longest losing run next to the one chance
gives at the same share of losing trades: the exact distribution of the
longest run for independent trades (Feller's recurrence), with its median,
the run reached one time in twenty, and the chance of a run at least as long
as the observed one. Below 5 % the page adds a plain line that the losses
came closer together than chance explains, which usually points to losses
that depend on the kind of market or to positions open at the same time.
Needs 20 closed trades with losing and other trades, at most 100,000.
Informational: no flag, no class change. Real-file check (40 files): classes
and every other figure unchanged; 7 files show the line.

### How it behaves after losing (`audit/behaviour.py`)

What traders pay a trading journal to tell them, and what a buyer of a robot
wants to know about its logic. Needs at least 30 closed trades with at least
10 winners and 10 losers (net of the fees the file itemises). MEASURED:

- the median time a losing trade stays open against a winning one; a
  finding when losers last 1.5 times longer or more and a Mann-Whitney test
  puts the difference beyond chance (p < 0.05): a far, moved or missing stop;
- the share of trades opened within 15 minutes of a losing exit against a
  winning one; a finding when it is 20 % or more and twice the share after
  wins: re-entering to win the money back;
  NOT_MEASURED when every entry and exit time sits at midnight (a file with
  dates only cannot see minutes);
- the hit rate of trades that follow two losses in a row (at least 15 of
  them) against the whole history; a finding when it is 15 points lower.

No red flag and no class change: each finding is a question to ask the
seller. Limitations: trades are ordered by entry time and overlapping trades
give no pause to measure; the tests treat trades as independent; daily files
measure hold times in whole days.

### Fund track records (`audit/factsheet.py`, `audit/fund.py`)

For investors and allocators judging a fund, a managed account or any
monthly track record. Besides a dated NAV or return series, the equity file
may be a factsheet's year-by-month table: a year column (values 1900-2199),
twelve month columns (headers in English, Spanish, Portuguese, French,
German or Italian, or 1 to 12) and an optional year-total column (`YTD`,
`YTD %`, `Total`, `Full Year`, `Yearly`, `Año`..., matched on its letters,
even when it repeats the year column's header). Cells may carry `%`, a
decimal comma, parentheses for a loss or a Unicode minus. Rows with no
readable month (a footnote such as "Source: fund administrator", an empty
separator, a year not yet started) are skipped; a month cell that cannot be
read (`abc`, `inf`) is left out and named in a warning (`2017-03`). A grid
whose rows with returns lack a year, or that lists a year twice, is refused
with a message about the table, not about a date column.

The scale: values are percentages when any cell has `%` (an Excel cell
formatted as a percentage counts: Excel stores 1.23 % as 0.0123, and the
reader keeps its `%`). Otherwise the year totals decide: the reading whose
months, compounded, miss the stated totals by less than half the other's
miss wins (summing cannot tell the two apart). Without that, a grid is read
as fractions when at least 80 % of its months are written with four or more
decimals (`factsheet.FRACTION_PLACES`, `FRACTION_SHARE`), none reaches 1 and
the median month is under 0.1 (`FRACTION_MEDIAN`, so a low-volatility
`0.3456` percent grid stays in percent); the warning still asks to check one
month. Factsheets round percentages to two decimals, a fraction needs four to
show a hundredth of a percent. A money-market percent grid written with four
decimals (`0.0300`) is the remaining misread, and the warning names it.
Otherwise, when neither reading clearly wins, the grid is read as percentages, as
factsheets publish, and the warning asks the customer to check one month
against the factsheet. The total column's own scale is settled apart (its
`%`, else the reading its years match best), so Excel months shown as
1.23 % beside a General 0.07 total read as one. A money-market fund's `0.03` is therefore 0.03 %,
not 3 % (the old median rule read it as a fraction, a 100x misread). A
year whose stated total matches neither its months compounded nor summed
(beyond 0.15 points) is listed in a warning: an edited month usually leaves
its year total behind.

For a file with 13 or fewer periods a year and at least 24 monthly returns,
the section "Lo que revisaría quien invierte en un fondo" shows, MEASURED:
the calendar table with each year compounded, the compound annual return,
the annual volatility, the share of positive months, the worst and best
month, the deepest fall and the longest run of months below a previous high
(marked when not yet recovered). Two findings, as questions:

- `smoothed`: first-order autocorrelation of the monthly returns of 0.2 or
  more and above 1.96/sqrt(n) (Getmansky, Lo and Makarov, 2004); the
  volatility is then also shown unsmoothed, from
  `(r_t - rho r_{t-1}) / (1 - rho)` (Geltner, 1993);
- `few_small_losses`: months in [-sd/2, 0) against the two neighbouring
  bins, (0, sd/2] and [-sd, -sd/2), with at least 10 months in those two
  (the discontinuity at zero of Bollen and Pool, 2009). Given the months in
  the three bins, the small-loss count is tested one-sided against the
  binomial share that a normal curve with the record's own mean and
  deviation gives that bin; the finding needs p below 0.01. The earlier test
  (Poisson against the neighbours' plain average) ignored the neighbours'
  own noise and the curve's slope near zero: on simulated normal months with
  a mean of 3 % and a deviation of 2 % it fired 5.7 % of the time over 240
  months instead of 1 %; the binomial share fires 0.5 %. Over every rolling
  window of the US market (Fama-French market return, 1926-2026) it fires on
  8 of 1,143 five-year windows (was 14), 3 of 1,083 ten-year windows (was 9)
  and none of the twenty-year windows. Peaked, fat-tailed months (Laplace)
  still fire more often than 1 %: the finding stays a question, never a flag.
- Months: a return is measured only between two consecutive calendar months
  that both have a level, so a month missing from the file is a hole
  (`missing_months`), never one "month" spanning two. A file with a row every
  quarter or year is not a monthly record and the section is not measured. A
  daily benchmark's final month is left out when it ends more than 7 days
  before the month's end.

Net of fees (DECLARED). A fund's returns are its own figures after its
fees, so the upload form has a box for it ("Son rentabilidades de un fondo,
ya netas de sus comisiones"). It is honoured only for a fund track record: a
hand-made return or NAV file (or factsheet table) at 13 or fewer periods a
year, with no trades, platform report or live history (`engine.fund_record`).
There it drops `ZERO_DECLARED_COSTS`, the section shows the declaration as
DECLARED and says Rigor did not measure costs, and the report is titled
"Auditoría de historial de fondo". Anywhere else the box is ignored with a
warning and costs are checked as usual. The observation thresholds do not
change, and the costs dimension stays NOT_MEASURED.

Against its benchmark. Factsheets print the benchmark's months next to the
fund's, so the equity file may carry it:

- a dated file: a column named `benchmark`, `bench`, `bmk`, `index`,
  `indice`, `índice` or `referencia` (optionally with a suffix, e.g.
  `benchmark_return`), read like the fund's own column (returns beside
  returns, levels beside levels). A `%` in the column's own cells means
  percent returns, even beside a curve of levels; bare returns take the
  scale (as is or divided by 100) whose median size is nearer the fund's.
  A period above 1,000 % leaves the column out. A column of
  row numbers (0, 1, 2...) is not a benchmark.
- a factsheet table: rows whose label names the benchmark ("Benchmark",
  "Index", "Índice", or an index family such as MSCI, S&P, FTSE, STOXX,
  Russell, Nasdaq, IBEX, DAX, Bloomberg, HFRI, IPC...) in a label column, in
  a row under the fund's year with no year of its own, or in a block opened
  by a short heading row naming the benchmark. A heading opens a block only
  when the next unlabelled row repeats a year already listed (a block
  repeats the years, in either order); a new year there means the label row
  was an empty benchmark row, so the fund's rows go on as the fund's. A label naming the fund
  ("Fund", "Fondo", "Portfolio", "Cartera", "Strategy"...) wins, so "Acme
  Index Fund" stays the fund. Rows of differences ("Excess", "Relative",
  "Difference", "Alpha", "+/-", "Diferencia"...) are left out and counted in
  a warning. A year repeated within the fund's rows, or within the
  benchmark's, is still refused.

An uploaded benchmark file is used instead when there is one. Over the
months both share (at least 24), MEASURED: each one's compound annual
return and the difference, the share of months the fund beat the
benchmark, the annual tracking error and information ratio, beta and
correlation, and up and down capture (Morningstar's definition: geometric
mean monthly return in the benchmark's up, or down, months over the
benchmark's; each needs 6 such months). Findings, as questions:

- `trails`: the fund's compound annual return is below the benchmark's;
- `index_like`: correlation 0.95 or more and tracking error under 3 % a
  year, the closet-indexing pattern (Cremers and Petajisto, 2009);
- `worse_both_ways`: up capture under 100 % and down capture over 100 %.

No index data is bundled: the benchmark is the customer's, as supplied, and
the note says Rigor did not check it against the index. When the fund's
figures are not declared net of fees, the section says the comparison
flatters a fund whose figures are before fees. It never feeds the benchmark
dimension (that reads only the uploaded benchmark file, as before), so the
class does not move.

What fees would take (`fund.fee_drag`). On a fund record not declared net
of fees, a table shows the yearly return and total growth with a yearly fee
of 1, 1.5, 2 and 2.5 % taken out month by month (MEASURED), beside the
figures as given. With an index comparison it adds the break-even fee: the
yearly fee at which the fund would only match its index over the months
they share, or says the fund already trails before any fee. No class
change; hidden when the record is declared net.

Through the known crises (`audit/crises.py`). A fixed list of calendar
windows, each the peak-to-trough months of a fall on the public record: the
dot-com bust (2000-09 to 2002-09), the 2008 financial crisis (2007-11 to
2009-02), the euro debt crisis (2011-05 to 2011-09), China and the oil fall
(2015-06 to 2016-02), late 2018 (2018-10 to 2018-12), the covid crash
(2020-02 to 2020-03), inflation and rates in 2022 (2022-01 to 2022-09) and
the 2022 crypto winter (2021-11 to 2022-12). Equity windows follow US
equities, the crypto one bitcoin; they are fixed in advance and never fitted
to the file. Beside each window the table shows what public indices did over
the same months, as context only (`crises.MARKET`): the change from the close
of the month before the window to the close of its last month, computed once
from FRED's daily closes (S&P 500 from 2016 on, the series' start; Nasdaq
Composite for every equity window; bitcoin on Coinbase for the crypto one),
read on `MARKET_AS_OF`. These are a handful of fixed figures with their
source URLs, not a data file; they never enter the result JSON, a finding or
the class. A note under the table names the sources and says plainly that for
a strategy trading another market (currencies, commodities, another country)
they are context, not its yardstick. For each window the
record covers in full, MEASURED: the fund's compounded return and, when a
benchmark is present, the benchmark's. With 24 months or more, the worst and
best 12-month return and the share of rolling 12-month periods that ended
positive. One finding, as a question: `fell_more_in_crises` when, over at
least two windows with a benchmark, the fund did worse in two thirds or more
of them. No red flag and no class change.

Against holding the market it trades (`audit/holding.py`, `audit/market.py`).
When at least two thirds of a file's trades are on the S&P 500, the Nasdaq 100
or bitcoin (by symbol name: `US500`, `SPX500`, `ES` futures; `US100`,
`USTEC`, `NAS100`, `NQ` futures; `BTCUSD`, `BTCUSDT`, `XBTUSD`; broker
suffixes dropped), or a tester report names one of them, the report puts the
strategy's closes beside the market's public closes from FRED
(`SP500`, `NASDAQ100`, `CBBTCUSD`) on the same days: return, worst fall and
Sharpe ratio for both, plus correlation and beta. The two are paired on the
sparser calendar, taking the other side's last level on or before each day:
a strategy that also moves on weekends is read on the market's trading days
(weekend moves roll into Monday), a weekday strategy beside bitcoin on its
own days. The strategy's Sharpe here is on those shared days only
(`strategy_sharpe_shared_days`, labelled "on the same N days"), not the
headline Sharpe. Correlation and beta use Friday-to-Friday weekly returns,
because a file's day ends at its last stamp (often broker time read as UTC)
while FRED closes at the market's close, and that offset pulls daily figures
toward zero. It needs 60 shared days (`MIN_DAYS`) spanning 90 calendar days
(`MIN_SPAN_DAYS`) and 12 weekly returns (`MIN_WEEKS`); a market close more
than 5 days before a strategy day is not paired (`MAX_GAP_DAYS`). One
finding, as a question, no red flag and no class change: `rides_the_market`
when the weekly correlation is 0.7 or more (`CLOSE_MOVE`) and the strategy's
Sharpe is not at least 2 standard errors (`EDGE_SE`) above holding's, the
standard error of the difference of two correlated Sharpe ratios (Jobson and
Korkie with Memmel's correction) on the weekly returns (`sharpe_gap_se`,
`sharpe_gap_in_se`). A gap inside the noise reads as "no clear edge", never
as "worse"; without the finding (low correlation), a gap under 2 standard
errors still gets one line under the table saying the higher Sharpe is not
enough to say the strategy beats the market. Sharpe is used because it does not change with position
size, so a leveraged copy of the index scores the same as the index. Neither
Sharpe subtracts a cash rate. On a balance-only file a line says the
strategy's correlation and worst fall read short. The closes are read at
run time (`MarketData`, kept in memory for six hours, Python's default
User-Agent because FRED stalls custom ones), never stored in the repository;
the service reads them unless `AUDIT_PUBLIC_DATA=false`, the CLI only with
`--public-data`, and the tests block the download (`tests/conftest.py`).
The public data can never hold a report back: an audit never downloads.
`MarketData.closes` answers at once from memory (or with nothing) and, when
the copy is missing or older than six hours, starts one background
`refresh`; the service also downloads the three series in a background
thread when it starts (`warm`). A download reads with `read1`, so its total
deadline of 5 seconds (`TIMEOUT`) is checked after every receive and a server
that trickles bytes is cut off within about one more socket timeout; replies
are capped at 4 MB, redirects are refused (the address stays FRED's fixed
https one), and values that are not finite are dropped. Only one refresh of
a series runs at a time, and after a failure (down, slow, rate limited, not
a CSV) the series is not asked for again for 10 minutes (`RETRY_AFTER`).
When the closes are not in memory the section says so in one NOT_MEASURED
line and the audit goes on. The CLI's `--public-data` reads the three series
first. The result JSON always carries a `holding` key: `null` when the file
trades none of these markets or public data is off.

The sample report (`/ejemplo`, `/sample`, `/pt/exemplo` and their PDFs) is
built with the same public series, so a visitor sees the lines an upload
gets without uploading a file. It reads only what is already in memory
(`MarketData.ready`) and never waits on the network: before the first
download lands, or with `AUDIT_PUBLIC_DATA=false`, it is the offline sample.
Each version is built once per language and set of series in memory and
kept. The public series move no figure of the sample, only add their lines.

Sharpe after the cash rate (`audit/cashrate.py`). With public data on, the
report adds one line under the key figures: the Sharpe ratio of the returns
after subtracting what the 3-month US Treasury bill paid over the same days
(FRED `DTB3`, read in the background with the market closes; zeros are
real rates and kept, and a reply with a rate above 25 % a year, `MAX_RATE`,
is taken as broken). FRED quotes a bank-discount rate `d`, so it is turned
into the yield a 91-day bill compounds to over a year,
`(1 - d·91/360)^(-365/91) - 1` (5.234 % for `d` = 5 %). Each return spans
the days from the previous point to its own, and the bill's rate on or before
the start of that stretch (at most 10 days old, `MAX_GAP_DAYS`) is
compounded over those days; the result is annualised like the headline
Sharpe, which stays as it is and subtracts nothing. The line also gives the
average rate over the history and says it is a dollar rate (another
currency's own cash rate is the fair one). When the strategy's compound return a year is below the
average rate, or the excess Sharpe is below -3 (`BELOW_CASH_SHARPE`, a curve
that barely moves), the line says in words that it earned less than cash
(both yearly figures) instead of printing a large negative Sharpe
(`below_cash`). It needs 10 returns and rates
covering the whole history, otherwise it is NOT_MEASURED and not shown. It
never changes the class.

Calm and turbulent markets (`audit/regime.py`). With public data on, every
report adds the section "How did it do in calm and in turbulent markets?".
Each return is placed by the VIX (CBOE, FRED `VIXCLS`, read in the
background with the other series; a reply above 200, `MAX_VIX`, is taken as
broken) at the close of the last market day *before* the day its stretch
starts, at most 5 days old (`MAX_GAP_DAYS`), so the regime was known before
the return: calm below 20, turbulent at 20 or above (`TURBULENT_AT`; 20 is
close to the index's long-run average, and since 1990 it has closed at 20 or
more on about a third of the days). For each regime it shows the share of
the time, the returns counted, the return per month compounded over that
regime's days only (`exp(Σ log(1+r) · 30.44 / days) - 1`) and the Sharpe
ratio annualised like the headline one ("—" for a flat side). The two mean
returns are compared in Welch standard errors: at 2 or more (`CLEAR_GAP`),
and only when that gap has the same sign as the difference of the two
monthly figures (volatility drag can flip them in a jumpy regime), the
report says in which regime it did better, otherwise that the gap is not
enough to say it behaves differently. It needs 90 days of history
(`MIN_SPAN_DAYS`), 20 returns in each regime (`MIN_RETURNS`) and VIX closes
covering the whole history; otherwise it is NOT_MEASURED with the reason in
words. The note says the VIX measures US equities and, for another market,
is read as a general gauge of fear. It never changes the class.

The same windows apply to any dated curve that is not a fund record (a
daily backtest, a platform report, a trade history), in their own section
"How did it do in the known crises?". The curve is taken at month ends. On
a curve rebuilt from a report's trades a month with no point carries the
previous level (nothing closed); on an uploaded curve it stays missing, so a
hole in the data never covers a window. The first month counts when the
curve starts in its first week, the last when it reaches its final week, so
no window is covered by a month seen in part. On a curve rebuilt from trades, a window
with no trade closed in any of its months reads "no trades closed in the
window" instead of 0.0 %. A curve that never moves 0.1 % from its start
(for example a trade list in price points on a large base) is NOT_MEASURED
and the section is left out. The benchmark
is the uploaded file or the curve's own benchmark column. A curve that covers
no window in full is NOT_MEASURED and the section is left out. A trade
history with no stated starting balance inherits the assumed-balance warning.

No red flag and no class change. Limitations: a short record has few
months per bin; smoothing can also come from a genuinely
trending strategy; a factsheet may round or restate months; returns are
taken as the file states them, usually after the fund's fees.

### Does it work on each instrument (`audit/instruments.py`)

For buyers of a robot or signal that trades several pairs or markets: "is
this a portfolio, or one market carrying the rest?". Needs at least 30
closed trades on at least two instruments, with the file naming each
trade's instrument. MEASURED per instrument with 10 or more trades (the
twelve busiest; the rest share an "Others" row): trade count, net result
after the fees the file itemises and hit rate. When the total is a gain and
at least two instruments have 10 trades:

- `one_carries`: without the instrument with the best net result, all the
  others together net zero or a loss;
- `mostly_one`: otherwise, the best instrument still brings two thirds or
  more of the net result (the section never calls that spread out);
- `most_lose`: more than half of those instruments net zero or a loss.

No red flag and no class change: each finding is a question to ask.
Limitations: instruments are compared by net money at the file's own sizes,
so a pair traded at larger size weighs more; a few instruments with few
trades each say little on their own.
Instrument names come from the file, so a name the profit-claim guard
refuses (here and in the live comparison's new-symbols note) is shown as
withheld promotional wording, like report metadata, instead of stopping the
audit with an error page.
Names keep the file's own case (a broker suffix like `EURUSD.m` is not
uppercased); trades are grouped regardless of case, and a row shows the
name as the file first writes it.

### How much capital it needs, at what size (`audit/sizing.py`)

For anyone about to run or copy a strategy: "with my account, at what size
does a bad year stay within X %?". Needs at least 30 closed trades spread
over at least 90 days (`MIN_SPAN_DAYS`): a shorter file stretched to a year
gives capital figures too uncertain to act on, so the figures are held back:
the section still shows, marked NOT_MEASURED with the reason and what to upload
(30 closed trades over 3 months or more), so a buyer of a short file knows why.
Under a year it opens with a visible warning giving the days covered. The net result of each trade (after the costs the
file itemises), in money and at the backtest's own sizes, is resampled with
replacement into one year of trades (the history's pace, 20 to 20 000
trades) `risk_samples` times with the audit's seed. The reference fall is
the larger of the 95th percentile of the deepest fall in money and the
history's own deepest fall in trade order, so the resampling (which breaks
streaks) never understates a real losing streak. When a MetaTrader report
prints its maximal drawdown in money with open trades (MT5 "Equity Drawdown
Maximal", MT4 "Maximal drawdown"), that DECLARED figure is a floor too,
since closed trades alone miss open losses. Money figures are at the sizes
the file used; the relative size is on its starting balance, without later
deposits (an account topped up many times shows a lower percentage in the
risk section, which is flow-adjusted). The section shows, for
loss limits of 10, 20, 30 and 50 %, the capital needed at the backtest's
size (reference fall / limit) and the share of the backtest's size that fits
the file's starting balance (limit x balance / reference fall), all
MEASURED. When the history is shorter than a year, the trades-per-year note
says so. When the reference fall is under 0.5 % of the starting balance
(`MIN_FALL_SHARE`) the section is NOT_MEASURED: dividing by an almost-zero
fall prints capitals near zero and sizes in the millions. A size share above
10x (`MAX_SIZE_SHARE`) prints as "more than 10x" / "más de 10x".
It raises no flag and does not change the class. Assumptions
printed with it: fixed sizes (no compounding), independent trades, the
uploaded costs, not a forecast. It is in money on closed trades, so it is a
different measure from the percentage drawdown of the resampled risk
section (equity curve, block bootstrap) and does not replace it.
Because it sees closed trades only, it carries an "Open losses" callout
with both figures when the platform prints an open-trade drawdown at least
half a point deeper than the closed-trade one (a real MT5 GBPUSD report:
40.5 % against 29.0 %), and a plain note when the curve is a closed-trade
balance. For an account history the sizes read as "the size the account
used" instead of the backtest's.
When `GRID_AVERAGING` or `HIDDEN_FLOATING_DRAWDOWN` fires, closed trades
understate the fall (a grid closes its baskets in profit and hides the open
losses: a real MQL5 grid signal showed a closed-trade fall of 112 on a 5,000
balance, which read as 3.8x the size at a 10 % limit). The figures are then
held back as NOT_MEASURED unless a fall that includes open trades is
available as a floor: the platform's open-trade drawdown, or an uploaded
equity curve (not rebuilt from closed trades) that starts within 10 % of the
stated balance, whose deepest fall in money is shown as `fall_curve`
(MEASURED), and only when that curve covers the trades from the first entry to
the last exit (one day of slack) with no gap over 4 days between its points
while the trades run, so a curve of the first few days, its two ends, or a
weekly sample cannot stand in for the whole history. The reason tells the client what to upload. A history
whose closed trades end with a net loss after fees gets no capital figures
(NOT_MEASURED): a size at which a losing history may be run is not given.

### What data the test ran on (`audit/testdata.py`)

For buyers of a robot. Only for MetaTrader tester reports (MT4 HTML, MT5
HTML/XLSX); account histories skip the section. The report header states the
modelling mode (MT4 "Model"; MT5 "real ticks" in History Quality), the data
quality (MT4 "Modelling quality", MT5 "History Quality"), MT4's mismatched
chart errors and spread, and the requested dates: all shown as DECLARED. The
audit counts, as MEASURED, the trades that open or close outside those dates
(one day of slack each side). Model names are recognised in English,
Russian, Portuguese and Spanish; an unknown one stays NOT_MEASURED. A damaged
header value stays NOT_MEASURED too: a negative data quality, or a mismatched
chart error count below 0 or above one billion (`MAX_CHART_ERRORS`).

| Code | WARN | FAIL |
|---|---|---|
| `COARSE_TICK_MODEL` | MT4 "Control points" or "Open prices only" | — |
| `TEST_DATA_QUALITY_LOW` | data quality below 90 % (not raised for a coarse model, which prints a low figure by design) | below 50 % |
| `REPORT_HEADER_MISMATCH` | MT4 prints more than 90 % modelling quality with a coarse model, or trades fall outside the stated dates | — |

The vendor questions add "modelling" and, for a header mismatch, a request
for the original, unedited MetaTrader file. Limitations: the header is read
as uploaded, so an edit that stays consistent with itself and with the
trades is not caught; "Open prices only" is a sound choice for robots that
trade only at the bar's open, which the warning's hint says; the MT5 report
prints no modelling mode apart from "real ticks".

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
once; a download waits up to `PDF_WAIT_SECONDS = 60` for a free slot (ten
customers downloading at once all get their PDF), and the last
`PDF_CACHE_SIZE = 16` finished PDFs are kept in memory so a double click
does not render twice; then a busy or missing
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

The verdict sentence speaks to a buyer first and keeps the measure's name in
brackets: significance reads "as a single test, too consistent to be explained
by chance alone (Sharpe ratio distinguishable from zero)" (the next sentence,
and the luck section, then discount the configurations tried), the held-out check reads "the
period held back for checking (out of sample)", and "deflated Sharpe" reads
"the Sharpe adjusted for those trials". The thresholds are unchanged.

Each dimension is explained once for a buyer ("Qué significa para ti" and the
plan). The threshold table ("Detalle técnico de cada dimensión" / "Technical
detail by dimension") now opens the technical tables, after the seller
questions, instead of repeating the verdict between the plan and the findings;
the multiplicity dimension is titled "Número de configuraciones probadas" /
"Number of settings tried".

### The report in Portuguese

The report, the verdict sentence, the class plan, the charts and the PDF
footer also read in Brazilian Portuguese (`locale="pt"`).
`audit/report_pt.py` holds the Portuguese of every Spanish-and-English table
(labels, figure names, dimension titles, red-flag titles, plan hints, chart
words) and `report_pt.install` adds it under `"pt"`, over the English, so a
text still missing in Portuguese reads in English, never blank. The engine's
English notes, the verdict's reasons (one `; `-separated part at a time) and
the seller questions and assumptions a result stores in Spanish and English
are translated when the page is rendered, as the Spanish ones are: the stored
result, and so its hash, is the same whatever language reads it.

Limits: the Portuguese was written for this report and checked for its
placeholders and by the profit-claim guard, not by a native reviewer; the
comparison page and the account screens have no Portuguese yet and send a
Portuguese reader to their English pages. Tests
(`tests/test_audit_portuguese_report.py`) fail when an English label has no
Portuguese, and `i18n.untranslated` now reports a note that lacks a Spanish
or a Portuguese rule.

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
- An account history (MT5/MT4 account statement, Myfxbook, MQL5 signal or
  FX Blue export) gets the same 0.5 bps per side slippage reference even when
  it itemises no fee: its prices are the broker's real fills, so the spread is
  already in each result. `ZERO_DECLARED_COSTS` is not raised for it. Before
  this, a Myfxbook export without Commission and Swap columns (a real XAUUSD
  scalping account, 773 trades) was charged 10 bps per side, about USD 4.80
  an ounce of gold per side, and failed the cost dimension on a cost it had
  already paid.
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
or test scenario produces one, so a new warning needs its Spanish rule. A sentence that
carries a count `{n}` with an `item(s)` word also needs its singular in
`_SINGULAR` (English and Spanish), so a page reads "1 deposit arrived" and
"3 deposits arrived", never "deposit(s)"; the JSON keeps the `(s)` form.

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
| `STRIPE_PAYMENT_LINK_SINGLE`, `STRIPE_PAYMENT_LINK_PACK` | empty | Payment Links (`https://buy.stripe.com/…`) for one audit and for the pack. With `STRIPE_WEBHOOK_SECRET` they turn card payment on without any secret key on the service; ignored when `STRIPE_SECRET_KEY` is set. A link with `/test_` is test mode. `/health` shows `card_via` (`checkout`, `links`, `off`). |
| `AUDIT_STRIPE_TEST_AUDITS` | empty | Comma-separated audit ids that a test-mode payment may unlock. In test mode the card button shows only on these audits, and a test payment for any other audit is ignored, so Stripe's public test card never unlocks a real report. Leave empty in normal operation. |
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
| `AUDIT_BOOTSTRAP_SAMPLES` | `1000` | Fewer samples make the service faster and the bands coarser. Above 10 million cells (samples x returns, `BOOTSTRAP_MAX_CELLS`) the samples are reduced to fit, never below 50; the report records both counts. The per-path statistics are summarised a million cells at a time (`_SUMMARY_CHUNK_CELLS` in `research/bootstrap.py`), with the same numbers: the largest report accepted (10 MB, 12,500 trades) peaks at about 290 MB instead of 520 MB. |
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
   Every merge redeploys, and Railway's default draining time (SIGTERM to
   SIGKILL) is 0 s. Set the service's Draining time to 120 s (Settings, or
   the variable `RAILWAY_DEPLOYMENT_DRAINING_SECONDS=120`); `railway.json`
   carries `drainingSeconds: 120` too, but services created after Railway
   deprecated config as code may not read it. The image `exec`s the server so
   it receives the SIGTERM and finishes the audits and PDFs in flight.
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

Test mode on the live site: card payments stay hidden from visitors and
the legal pages do not mention them; list the audits you will pay in
`AUDIT_STRIPE_TEST_AUDITS`, pay them, then empty the variable. A payment
Stripe reports with `livemode: false` never unlocks any other audit.

#### Without a secret key: Payment Links

1. Create two Payment Links in Stripe: one for a report (USD 29) with
   metadata `app=rigor` and one for the pack (USD 69) with metadata
   `app=rigor` and `plan=pack`, card only and no promotion codes. Leave the confirmation
   page as Stripe's own; the buyer comes back to the report tab.
2. Create the webhook endpoint as above and put its signing secret in
   `STRIPE_WEBHOOK_SECRET`.
3. Set `STRIPE_PAYMENT_LINK_SINGLE` and `STRIPE_PAYMENT_LINK_PACK`, and leave
   `STRIPE_SECRET_KEY` empty.

The locked report links to them with `client_reference_id=<audit id>` in a
new tab. The signed webhook is the only confirmation (the service has no key
to ask Stripe), and "Ya pagué: ver mi informe" reloads the report. The pack
code works as below, keyed by the Checkout session the link created.

How it works: the checkout carries `metadata.audit_id` and `metadata.plan`.
The payment is confirmed by the signed webhook and, when the buyer comes
back, by asking Stripe for the session in the return link; either one is
enough and both are idempotent (`audit/payments.py`, `fulfil`). A session
unlocks only the audit named in its own metadata, and only when Stripe
reports it `paid` (a 100%-off `no_payment_required` session never unlocks;
free reports go through access codes), in `usd`, for at least the plan's
price (`AUDIT_PRICE_USD_CENTS`, or `AUDIT_PACK_PRICE_USD_CENTS` for a pack),
and with metadata `app=rigor`. The buyer controls `client_reference_id`
through the link URL and the webhook hears every Checkout on the Stripe
account, so a cheaper link, another app's link on the same account or a
single-report payment tagged as a pack unlocks nothing. Sessions the service
creates carry `app=rigor` themselves; Payment Links must carry it in their
metadata, in test and live mode alike. A buyer who pays in their own currency
through Stripe's Adaptive Pricing still unlocks: since API 2025-03-31 the
session stays in USD (the local amount is under `presentment_details`), and
on older API versions the USD amount is read from `currency_conversion`. The pack's code is derived with HMAC from the session id
and the webhook secret, so only its hash is stored and the paid report can
still show it, with its credits left, to whoever holds the report token.
Rotating the webhook secret hides earlier pack codes from their reports
(the codes keep working). Refunds are made from the Stripe dashboard and do
not lock a report again; disable a pack code from `/panel` if needed.
A paid session that does not unlock (wrong amount, currency or marker, an
unlisted test audit, an unknown audit) is logged as a warning with the
session id, the audit id and the reason, never an amount or an email, so a
charged buyer who stays locked can be found and refunded or unlocked. Live
ones are also listed on `/panel` ("Pagos con tarjeta que no abrieron un
informe": date, Stripe session id, audit id, reason), and the retention purge
deletes those rows; test-mode ones stay in the log only, since anyone can pay a
test link with Stripe's public card. Only sessions that name an audit or carry
`app=rigor` are listed, so a sale from another app on the same Stripe account
never shows there. The return page asks Stripe about a session at most 10 times
an hour per address and per audit (`CARD_LOOKUPS_PER_HOUR`) and does not ask
again within the hour about a session that did not unlock, so looping the
return URL cannot use up the account's API rate; the webhook needs no lookup.

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

### Customer accounts (`audit/accounts.py`, `/registro`, `/cuenta`)

A customer can create an account with an e-mail and a password to find, in
one place, the reports they uploaded or saved, the access codes they
redeemed or added (with the credits left), and what they paid for. The
free preview needs one (see "Free tier" below); each report's private link
and a report paid with an access code work without one, and an account never
changes what a report says.

- **Free tier** (`accounts.FREE_PREVIEWS_PER_MONTH = 3`,
  `FREE_PREVIEWS_PER_IP_PER_MONTH = 10`; not in free mode). An upload
  without a working access code needs a signed-in account (401 page with
  "Crear cuenta gratis" otherwise; `{"error": "free_tier_signin"}` for JSON).
  Each account gets 3 free previews per calendar month (UTC), counted in
  the `free_previews` table; free previews are also capped per network
  address per month, across accounts. Past either limit, an account with
  credits gets a full report and spends one credit (`acct=upload_credit`);
  without credits the upload answers 402 with a link to buy. A code typed
  in the form that still has credits pays the upload with no account, as
  before. "Mi cuenta" shows the free previews left this month. The
  address in `free_previews` is cleared by the retention purge.
  What it does not stop: without e-mail verification, someone can open
  several accounts with made-up addresses; the per-network cap and the
  5 sign-ups per hour per address only slow that down. E-mail confirmation
  (needs a mail provider) would close it.
- **Free first full report** (`accounts.WELCOME_FULL_REPORT = True`,
  `WELCOME_REPORTS_PER_IP_PER_MONTH = 3`; not in free mode). A signed-in
  account's first upload comes out as a full report with PDF and a
  publishable verification page, paid with the reference `welcome:<id>`
  (`paid_with = "welcome"`, `acct=welcome` shows the notice). It does not
  use a monthly preview. It is refused (the upload falls back to the
  free-preview rules) when the account already had it, when this browser
  already gave one (a `rigor_device` cookie holding a random id, stored as
  its SHA-256), when the same file (SHA-256 of the upload) already got one
  on any account, or when the network address reached the monthly cap. The
  `welcome_reports` row outlives the account, so deleting and signing up
  again does not repeat it. The purge clears the address; the device and
  file hashes stay. "Mi cuenta" shows it as Disponible/Usado. The "file" is
  a fingerprint of what it says (`accounts.content_fingerprint`: timestamps
  and returns rounded to 5 decimals), so a trailing newline, other line
  endings or renamed columns do not make a new file. When the account's
  free report is unused but an upload becomes a preview for one of these
  reasons (file, browser, network), the preview says why
  (`account_pages.COPY["welcome_refused_*"]`).
- **Networks** (`accounts.network_address`): every free-tier limit that
  counts an address (free reports and previews per network, their claim
  keys, and the invite self-check) counts an IPv6 address as its /64, since
  a customer can rotate addresses inside it at will; an IPv4 address (or an
  IPv4-mapped IPv6 one) counts as itself. The hourly sign-up limit and the
  hourly upload and code-redeem limit count the same network. The free-tier
  tables and each upload keep that network, not the exact IPv6 address.
- **Limits under simultaneous uploads** (`free_claims` table). The checks
  above are a first look that answers at once; after parsing, the upload
  takes its claims in one transaction, all or nothing: the free report takes
  `welcome:account:`, `welcome:device:`, `welcome:file:` and one numbered
  per-network slot of the month; a free preview takes one of the account's
  3 numbered slots of the month and one of the network's 10. A claim that
  is taken sends the upload down the next rule (preview, credit, 402 with
  no audit kept). A failed upload gives its claims back. Network keys hold
  a hash of the address and the retention purge deletes them.

- **Descargar mis datos**: `/cuenta/datos` (EN `/account/datos`, PT
  `/pt/conta/datos`), a GET for the signed-in account only, returns a JSON
  file (`no-store`) with the account's e-mail, language and dates, session
  dates, reports (class, payment, description, upload IP while kept),
  codes (never the code or the owner's note), strategies, free previews,
  the free first report's hashes and IP, and the column maps. Never the
  password hash, a session, reset or report token. Backs the "Qué
  guardamos" block and the right of access in /privacidad. A browser-flagged
  cross-site request is sent back to the account page; a report saved from
  someone else's link shows its description only once paid
  (`store.account_export`).
- **Mis estrategias** (`audit/strategies.py`, tables `strategies` and
  `strategy_reports`): an account names a strategy and files reports of its
  own list under it (one strategy per report, 50 strategies per account),
  from the form on "Mi cuenta" or after the fact. `/cuenta/estrategias/<id>`
  (EN `/account/strategies/<id>`) lists the versions oldest first with the
  class, annualised Sharpe, deflated Sharpe and max drawdown (full reports
  only; a preview shows its class and the way to unlock). Next to each
  version, "Qué cambió frente a la versión N": the class (better or worse),
  each dimension whose ranked result changed (pass, weak, fail; not
  measured is never compared), said as "cambió" because each report carries
  its own declarations, and the Sharpe, called better or worse only when the
  bootstrap 5-95 % bands do not overlap, "sin cambio claro" otherwise, "no
  comparable" across data frequencies (the frequency label; periods per year
  within 10 % without one) and "periodos distintos" when the shared dates
  cover under 80 % of the shorter history. With two or more versions the
  page says that picking the best of N counts as N trials. Per-test detail needs both versions
  complete. Rename, remove a version and delete the strategy (its reports
  stay); deleting the account or a report removes its rows. Nothing here
  unlocks anything, so nothing new can be farmed. "Descargar resumen en
  PDF" (`/cuenta/estrategias/<id>/pdf`) prints the same page without forms
  or buttons, with the date it was made and the fixed research-not-advice
  notice; only the signed-in owner gets it (another account gets 404), sent
  `private, no-store`, in the account page's language (es, en, pt). It
  carries no links. The same summary on the same day is served from memory;
  an account renders at most 10 in 10 minutes (then 429), since they share
  the report PDFs' render slots.
- **Invita a un colega** (`store.invite_*`, `record_referral`,
  `reward_referral`; tables `invite_links` and `referrals`): "Mi cuenta"
  shows a personal link `/registro?invita=<token>` (EN `/signup`, PT
  `/pt/cadastro`) with a WhatsApp share, how many joined, how many wait for
  their first report and the credits received (this month out of the cap).
  A sign-up through the link is noted unless the token is unknown, the
  inviter is still signed in in that browser, or the browser carries the
  mark of the inviter's own free report. The inviter gets
  `accounts.REFERRAL_CREDITS` (1) full-report credit, as an access code no
  one sees linked to the inviter, only when the new account's free first
  report is granted, so the free tier's browser, file and address limits
  already held; it is refused as `self` when that upload's browser mark or
  address is one the inviter used (its free report, previews, own uploads),
  and as `cap` past `accounts.REFERRAL_MONTHLY_CAP` (5) credited invites in
  the calendar month (unique slots, so simultaneous rewards cannot pass it).
  The inviter never sees who joined. Rows go with the inviter's account; an
  invitee's deletion drops a pending row and keeps a decided one (dates,
  outcome, slot) under a random id with no browser mark, so deleting
  credited invitees never frees the cap. They show in "Descargar mis datos". Off in free mode or without the free first
  report.
- **Pages** (Spanish default, English paths): `/registro` `/signup`,
  `/entrar` `/login`, `/cuenta` `/account` ("Mis informes"), `/olvide`
  `/forgot`, `/restablecer` `/reset`; sign-out is a POST to `/salir` `/logout`.
  Every page links "Mi cuenta" from the navigation and the report header.
- **What lands on an account**: an upload made while signed in; a report
  opened by its link and saved with "Guardar en mi cuenta"; the code that
  unlocked a report while signed in; a code added by hand; a card purchase
  started while signed in (the report, and a pack's code with its credits).
  A report or a code belongs to one account at most.
- **Credits**: a locked report of a signed-in customer shows "Desbloquear con
  1 crédito de tu cuenta" when their codes have credits left. The code that
  expires first is spent first; the credit and the unlock share one
  transaction, as with a typed code.
- **From the list**: each full report links its PDF (`/audits/{id}/pdf`, opened
  by the owner's session without the token) and, when published, its public
  `/v/` page. The "¿Necesitas créditos?" box shows the single and pack prices
  from the settings and a WhatsApp link with the request typed; with no
  credits left it sits above the list.
- **Comparing**: with two or more full reports, "Mis informes" lets the
  customer tick two and open `/cuenta/comparar` (`/account/comparar`), the
  same side-by-side view as `/comparar` without pasting private links. It is
  a read-only GET; both reports must be on the signed-in account's list, not
  purged and unlocked (or free mode); anything else goes back to the list.
- **Opening a report**: the owner opens `/audits/{id}` without the token; any
  other visitor still needs the token (a wrong one is a 404).
- **Security**: scrypt password hashes (N=2^14, r=8, p=1, 16-byte salt);
  at sign-up, password change and reset `accounts.common_password` refuses,
  offline, keyboard and digit runs, repeated units, digits only, and common
  EN/ES/PT words or the e-mail's name with digits or symbols around them;
  sign-up and "Mi cuenta" list what the account keeps and how to delete it;
  session cookie `rigor_session`, 256-bit, `HttpOnly`, `SameSite=Lax`,
  `Secure` on https, 30 days, stored only as SHA-256; CSRF tokens on every
  form (double-submit cookie `rigor_csrf` before sign-in, the session's token
  after); 10 failed sign-ins per hour per (address, e-mail) pair, with
  ceilings of 50 per address and 50 per e-mail (a slow-down against guesses
  spread over many addresses; past the e-mail ceiling an address gets
  `SIGNIN_TRIES_PAST_EMAIL_CEILING = 2` tries on that e-mail, so a stranger
  who knows it cannot lock the owner out), and 5 sign-ups per hour per
  address. These counters and the panel's wrong-key limit live in the
  `attempts` table (keys hashed, rows older than the hour deleted), so a
  deploy does not reset them. A password change or reset signs out the other
  sessions; `next` only returns to `/audits/`, `/cuenta` paths or exactly
  `/` and `/en` (with an anchor). POST `/audits` answers 403 to a browser
  post from another site, a second layer beside the `SameSite=Lax` cookie:
  `Sec-Fetch-Site` decides when present (only `same-origin` and `none` pass;
  `same-site` is refused, as other apps on the parent domain count as same
  site); without it, the Origin (else Referer) must be this service. Our
  pages send `Referrer-Policy: no-referrer`, so a real form post carries
  `Origin: null`; that, like no header at all (scripts), is no signal.
- **No e-mail service yet**. Nothing sends e-mail and addresses are not
  confirmed. A customer who forgets the password writes to the owner
  (WhatsApp link on `/olvide`); after checking the request comes from the
  account's address, the owner creates a one-time reset link (24 hours) in
  `/panel` or with `quant-trade audit account-reset EMAIL`. To add e-mail
  confirmation and reset by e-mail later, the owner needs a transactional
  mail provider (for example Resend, Postmark or Amazon SES), a verified
  sending domain, and its API key as a Railway variable; the hooks are listed
  in `accounts.EMAIL_HOOKS`.
- **Deletion**: the customer deletes the account from `/cuenta` (password
  required), optionally with the reports they uploaded while signed in; a
  report saved or paid for from someone else's link is only unlinked; the owner does it with
  `quant-trade audit account-delete EMAIL [--with-reports] --yes`. Deleting an
  audit (`audit delete ID --yes`) also removes it from its account.
- **Storage**: five new tables (`accounts`, `account_sessions`,
  `account_audits`, `account_codes`, `account_resets`), created on start; no
  column is added to an existing table.

### Sales funnel for the owner (`audit/funnel.py`, `/panel`)

`/panel` shows, for the last 30 days, per link tag and per day and language:
visits, accounts created, free first full reports, free previews and paid
reports (by code and by card). It answers "which of my posts brings
customers" without any third-party analytics.

- **Tags.** A link carries `?ref=<tag>`. Only tags listed in
  `funnel.REF_TAGS` count (the playbook template ids and a few channels);
  anything missing, malformed or unlisted is "directo". The first listed tag
  a browser arrives with is kept for 30 days in the `rigor_ref` cookie, which
  holds only the tag, and stored in `account_refs` when an account is created.
  The row goes with `delete_account`.
- **Visits.** A `GET` answered 200 on the landing (`/`, `/en`, `/pt`) or a
  case page (`/para`, `/for`, `/pt/para`) adds one to a counter keyed by day,
  language and tag (`funnel_visits`). A browser counts once a day: the
  `rigor_seen` cookie holds only the date. No address or user agent is
  stored. Link previews, robots, prefetches and `HEAD` requests do not count.
  A request only adds to an in-memory counter (`funnel.VisitCounter`); a
  background thread writes the totals every minute, `/panel` flushes before
  it reads, and shutdown flushes the rest, so a slow or failing database
  never holds up a page. Counts that fail to write are kept for the next
  flush.
- **The other stages** are read from the tables the service already keeps
  (`accounts`, `welcome_reports`, `free_previews`, and paid `audits` with
  their payment reference), with the language and tag of the account
  involved. An event with no account shows language `-`.
- **Limits.** Visits count browsers per day, not people. A report deleted by the
  retention purge stops counting. A tag counts only if the owner used it in
  the link.

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

Every footer links the public methodology ("Cómo auditamos", `/metodologia`,
`/methodology` in English), as do the pricing section and the report footer.
The methodology page shows the six questions as cards with their pass rule,
the A-D ladder as coloured class cards, the evidence labels as real badges,
the red flags as chips and the limits with a red dash. The landing's
"¿Vas a copiar o invertir con alguien?" card sends people about to copy or
fund a trader to the provider-account guide. On phones, each row of an
evidence table (`table.metrics.ev`) becomes a card with its name and value,
then its label and note; the account section's flags are cards too.

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

The prop-firm simulator shows its 95 % range and its days to target as two
fact cards with one evidence tag each. When the platform's open-trade drawdown
already passes the challenge's total loss limit, that warning is a red-edged
callout above the table. The break-even cost tile shows one number (basis points
per side) and puts the pips in its label, so the figure does not wrap.

The guides index lists backtest guides and live-account guides (the provider's
account, Myfxbook, MQL5 signals, FX Blue) under two headings. The landing's
platform strip is capped in width so its names wrap into two even rows.

An error page shows the problem as a card with a red edge and a warning icon.
The card names the upload field, states the problem in one line and lists the
expected formats under "Se espera" / "Expected". When the account review or the
test-data review finds nothing, its closing line is a green-edged callout.

Every buy box on a locked report, whether card payments are on or not, ends
with four checks listing what the payment unlocks: every figure, the PDF, the
public verification page and the refund when the report misreads the file.

"Qué capital necesita y a qué tamaño" shows one card per loss limit (10, 20, 30
and 50 %): the capital needed at the backtest's size, then the size fraction on
the file's balance. The cards sit two to a row on phones, four on desktop and in
the PDF.

On phones the stress tables and the day and hour tables read as one card per
row, with each figure labelled, instead of scrolling sideways. A lone last key
figure spans the row.

The public /v page shows each dimension as the same card the report uses. On
phones, its hash and audit-detail tables stack the label above the value. An
undeclared trial count reads "—" and not "None".

On phones the deposit list in "El dinero real de la cuenta" also reads as cards.
In the PDF, fact cards sit three to a row.

"¿Pico aislado o meseta?" answers its question under its two key figures:
a green "Meseta" callout, or an amber "Pico aislado" callout that points to the red flag.
On a lone peak those two figures and the losing neighbours show in red.
The chosen settings read as chips.
The capital warning for a history under a year is an amber callout.
On desktop the upload form pairs the language and access-code fields, so no field sits alone.

In "El dinero real de la cuenta", a negative percent gain, a negative money result and the open loss show in red.
Reading notes from the file importer read as a short list, not one run-on sentence.
A capital section held back for a short history reads as a grey card with the reason and what to upload.

Accessibility: secondary grey text, the green and amber state colours meet 4.5:1 on the page and card backgrounds in light and dark areas.
Every form label and help text is tied to its field.
File drop zones show a visible keyboard focus ring.
The phone menu button and the report header buttons have 44 px tap areas.
On a slow phone (150 ms latency, 1.6 Mbps, 4x CPU) the landing's first screen paints in about 0.7 s and /ejemplo in about 1.5 s; production serves pages gzipped.

The resampled risk shows its p50, p95 and p99 one-year drawdowns as three fact cards; on phones a value and its evidence tag stay on one line in the small tables.
"No large open loss" keeps its green tone only when the file states the open result; otherwise the note is grey.

When an upload error ends with the fix ("…: sube la optimización del mismo robot…"), the error card shows the problem, then the fix on its own line under "Qué hacer:" / "What to do:".

Key figure tiles step their font down for long values (9+ and 12+ characters) so a figure like +10,000,004.6% stays inside a 360 px tile. The cost multiplier table scrolls inside its own box on tablets, and in the PDF it keeps every column on the page with smaller type.

When capital is held back because the trades overlap as a grid or hide open losses, the grey card states the reason and puts what to upload on its own "Qué hacer:" line.

Very large figures stay on the page: chart axes switch to T and then to powers of ten (2.0e18) and widen their left margin to fit the longest label, and in the PDF the monthly returns table shrinks its type, with the widest cells (+10,300,003.0%) set smaller still, so the Total column is never cut. When capital is held back because the trades lose in total, the grey card reads as one capitalised sentence.

In the full report the red flags are cards, gravest first: severity badge, the flag's name in the customer's language, the detail as a sentence and the code in small type underneath (the old three-column table cut the detail off on phones). The "No medido" / "Not measured" list is one card with each check's name in bold over its reason. A not-measured section no longer adds "none" under its reason, the declared holdout seal names its rows in plain words, and a declared midnight date shows as the day (2024-06-03, not 2024-06-03T00:00:00Z). In the PDF a huge figure (95,766,086,888,191,808.00%) wraps inside its table cell instead of running off the page; label columns keep whole words.

The report ends with one tidy footer: the notice card, the audit JSON fingerprint in small monospace type, then a single bar with the brand on the left and "Cómo auditamos", terms and privacy on the right (in the PDF the method link is dropped and the other two sit on one line).

The landing's report mockup always settles flat and sharp: the hero clips with `overflow:clip` so the scroll-driven tilt follows the page scroll (with `overflow:hidden` the hero became its scroller and the mockup stayed tilted and soft), and the entrance fade no longer animates a blur. With reduced motion the mockup is flat from the start.

The forward section answers first ("Aguanta" / "No aguanta" callout under the intro), then shows its four figures as a two-by-two grid on screens wider than a phone and two per row in the PDF, so no card is left alone on a row.

Refusals read calm: the error card and the page's eyebrow dot are amber (a fix to make, not an alarm), size limits read in MB or KB instead of bytes, every refusal ends with a period, and a fix after a colon or semicolon (sube, exporta, revisa, upload, export, check...) goes on its own "Qué hacer:" / "What to do:" line. The size and value-too-large refusals now say what to do (a smaller file; check the exported values). On the public /v page the audit details read as plain words, the trial counts carry their evidence badge (120 DECLARED) instead of "120 (DECLARED)" in code type, and only the result hash keeps the code style.

Redesign pass 36, the pay step. A wrong, used or expired access code is answered
under the code field itself, in amber, with what to do next (copy the code as it
arrived and redeem it again, or message us with the button above); the field is
marked invalid for screen readers. The redeem form and the upload redirect carry
`#canjear`, so the page comes back at the field instead of at a banner at the top.
A payment or code that worked shows a green "done" notice instead of the blue
informational one. The optimisation XML refusal also states its limit in MB and
splits into the problem and "What to do".

Redesign pass 37, the full report on a phone. Metric cards put the MEASURED,
DECLARED or NOT_MEASURED badge on the label's line, so a card without a note is one
line. "Reasons per dimension" becomes one card per dimension. "When it wins and
when it loses" stays a compact four-column table instead of eleven tall cards. An
empty red-flag list reads "No red flags in the audited files." with a check
instead of a bare "none". The out-of-sample keys `sharpe_annualised` and `gap`
have readable names, reason and note text starts with a capital, and the fan
chart legend no longer overlaps. The sample report on a phone is about 3,000 px
shorter; print is unchanged. The recent-period section (#179) was checked in both
cases (holds and fades) on a phone, a desktop and the PDF. It reuses the polished
verdict callout, fact pairs and year table; its closing note now starts with a capital.

Redesign pass 38, before a buyer pays (landing, upload, preview), checked on a
phone in Spanish and English. The main upload field says in one line what to
upload ("as your platform saves it: HTML, XLSX or CSV, up to 10 MB"); the full
list of formats and the export guides open under "Which file do I export?". On a
phone, "How it works" puts each number beside its text, joined by a line. The
footer names the tagline and the legal pages once instead of twice. The preview's
red flags use the same cards as the full report, the gravest first, without the
detail that the payment unlocks.

Redesign pass 39 styles the report check (`/comprobar`, `/check`): the file
goes into the same drop zone as the upload, the button spans the card, "How
it works" reads as three icon steps, and the answer is a tinted card with a
mark (green check when the bytes match, amber caution when Rigor has no
record, since an unmatched file may simply predate the recording). The page
is linked from every footer's Product column, from a note on the public /v
page ("Were you sent this report's PDF or JSON?") and from a line under the
report's PDF download.

Redesign pass 40 styles "How it behaves after losing": each finding reads as
what the trades show (bold) and, on its own line with a speech mark, the
question to put to the seller (`report._behaviour_ask`, `.beh-asks`), in the
screen and in the PDF.

Redesign pass 41 gives "Does it work on each instrument?" the same finding
layout as the behaviour section (finding in bold, then the question) and lays a
section's single headline figure out as a row beside its sentence on screens
(`.facts>.fact:only-child`), so a lone figure no longer fills a full-width
tile. Print keeps the tile.

Redesign pass 42 sets the live-account line under the verdict (`.verdict-live`)
apart with a hairline and a dot in the outcome's tone (green holds, amber on the
edge, red does not hold), keeps its link muted, and prints it black at the
verdict's size in the PDF.

Redesign pass 43 styles the fund calendar from #202. On a phone the table scrolls inside its own frame and the year column stays fixed, so every row keeps its year. The last column is headed "Total" ("Full year" in English) and sits apart with a rule and a light fill. Missing months are hatched. In the PDF the table drops its screen width and fits the page at a smaller size.

Redesign pass 44 turns the column lines from #203 into a column map. For a CSV or Excel file from any platform, the report used to repeat "Column read as …" once per column inside the platform table. It now shows one block, "How each column of your file was read", with each of the customer's column names beside what Rigor read it as, in a trader's order (symbol, side, size, times, prices, result, costs). Three columns on a desktop, one on a phone, two in the PDF.

The same pass styles the buyer's "What to do now" box from #207. Each step is a card with its number in a dark disc and the link to its section in bold with an arrow. The last step (keep the report and its id) is dashed and quieter. The MEASURED/DECLARED/NOT_MEASURED legend under the verdict sits in smaller print. The PDF keeps the cards at 9 pt.

Redesign pass 45 gives the four audience pages from #206 (/para/… and /for/…) more shape without changing their words or order. The problems are cards with an amber warning icon. "What Rigor checks" is a grid of cards, two per row on a desktop, each with its name in bold. The price sits in a panel with its buttons. "Other cases" are link cards with an arrow. A check whose name is a question no longer gets an extra full stop ("¿Pico aislado o meseta?.").

Redesign pass 46 tidies the "Name its columns" step from #212 on the upload form. The twelve fields sit in three labelled groups: one row per trade, one row per fill, and either way. On a phone they sit two per row. Once a CSV is picked, the file's own column names show as chips above the fields (read in the browser by `app.js`, the same header row that feeds the suggestions), so the customer can copy them without opening the file.

Redesign pass 47 polishes the screens from the first-sales rewrite (#223). In the locked preview, each padlock sits beside the first line of its item instead of floating between two lines. On a phone the WhatsApp button wraps to two roomy lines, and "Redeem code" fills its row. On the landing, the "And it reads the export format of…" line keeps a quiet underline that brightens on hover. The price cards needed nothing.

Redesign pass 48 styles the account screens from #205. On sign-up and sign-in, the form sits in a white card beside the tinted list of what an account gives. On "My account", the three counts are white tiles, three across even on a phone. On a phone each report is a card with its class, date and "Open" on one row and its status and description below. "Delete my account" is outlined and titled in red, so it does not read like the password card beside it. On sign-up, the words "terms of service" and "privacy policy" are themselves the links to those pages; the line used to link only a lone "›" and left privacy unlinked.

Redesign pass 49 checks the upload form after #230 (report first, extras in a closed "Add more files" box) and the pricing line about the optional account; both needed nothing on a phone or desktop. It adds a quiet "or" rule between the platform report and the equity curve, so it reads that one of the two is enough.

Redesign pass 50 checks the account's side-by-side screen (`/cuenta/comparar`, two reports picked from "My reports"). On a phone the dimension and figure tables now use tighter cells and smaller badges, so a "Fails" badge in the second report no longer spills past the card. It also checks the fund benchmark block and the plain lines under the headline figures on /ejemplo; both read well and needed nothing.

Redesign pass 51 styles the PDF link while the PDF is made ("Generando tu PDF… (unos segundos)"): the button keeps its full colour, shows a small spinning ring like the upload loader, and keeps a progress cursor; on a phone the report's PDF button spans the width so the longer label fits on one line.

Redesign pass 52 checks the two new report sections on screen, on a phone and in the PDF. The "history needed" table in "¿Cuánto queda al descontar la suerte?" (`table.luck`) turns into one card per row on a phone, each figure under its column name, and its yes/no answer is green or red. In the PDF a block of figures may now split across pages (orphans and widows 1), so a heading such as "Cómo se vivió este historial" no longer sits alone above half a blank page; subsection headings stay with what follows.

Redesign pass 53 checks the screens that landed after pass 51 on a phone first. The line naming the 20 recognised platforms under the landing's platform row is no longer one long underlined link: the names stay in a lighter grey, the link ends in an arrow and underlines on hover. "¿Cómo le fue en las crisis conocidas?" (`table.timing.crises`) now spans the card on a phone, wraps the crisis name, shows losses in red and wraps "sin operaciones cerradas en la ventana" instead of running off the screen. /para/copiar-senales and the longer verdict on /ejemplo read well and needed nothing.

Redesign pass 54 walks the free tier's path on a phone first: upload without an account, sign up, first full report, locked preview, "Mi cuenta". The "create your account" screen puts its two buttons in a card, full width on a phone. On a report saved to the account, the tick beside "Guardado en tu cuenta" is icon sized; before, it filled the box. In "Mi cuenta" the free first report comes first while it is unused, in a green tile across the row on a phone, followed by the month's previews and the credits; the tiles sit two across on a phone and in one row on a desktop. On the price cards a long note under the price (the free card's) drops below it whole instead of splitting beside it.

Redesign pass 55 makes each locked figure in a preview's summary a link to the unlock box (`a.kpi.locked`, `href='#unlock'`, labelled with the figure's name and "Desbloquear"), so tapping what someone wants to see takes them to how to see it. The tile looks the same; on hover or focus its border darkens.

Redesign pass 56 opens the PDF on a one-page summary (`_pdf_cover` in `report.py`, print only, hidden on screen): the class in an SVG ring, the verdict's first sentence, each dimension with its badge, the first four key figures and up to three "what to do now" steps, then the evidence legend. It reuses the report's own labels and figures; nothing on it is new. A page notice (the sample's "synthetic data") repeats on the cover so the first page never passes for a real account, and a locked preview gets no cover. The class ring in the verdict also gets an SVG copy for print (`ring_svg` in `theme.py`), since WeasyPrint draws no conic gradient.

Redesign pass 58 styles "Mis estrategias". On the account page each strategy is a card with its latest class, name and version count; on a phone the count goes under the name and "Ver estrategia" spans the card. On a strategy's page the version table uses tabular figures, its "Quitar de la estrategia" buttons sit quietly at the right, and on a phone each version becomes a card with every figure under its column name (`data-label`). In "Qué cambió" each line ends in a chip coloured by its meaning only: green for "mejor", red for "peor", grey for "cambió", "igual" or "sin cambio claro". The wording and the rules behind each word are unchanged.

Pass 56 also gives each shared link its own preview card (`tools/make_og_images.py`, `OG_KINDS` in `seo.py`, 1200x630, about 25 KB each, served from `/static/`). A published verification page (`/v/...`) shows the card for its class: the class ring, its fixed sentence and the fixed notice, nothing from the file. The sample shows a class C card marked as synthetic data, and each audience page shows its own title. The cards are static files in the package, so a preview makes no outside call and nothing about a client's report is ever drawn on one. Unknown kinds fall back to the site card.

Pass 56 also turns the prop-firm simulator table (`table.timing.firms`) into one card per challenge on a phone, each figure labelled: its four columns were 436 px wide on a 390 px screen and made the report pan sideways.

Redesign pass 57 styles the column-mapping page ("Dinos qué es cada columna"): each group of menus is a white card, the menus stack in one column on a phone so column names are not cut short, the file re-pick sits in a dashed box, and every file input's button matches the site's buttons. Cell rendering and escaping are unchanged. It also gives the account's "what we keep and how to delete it" card a shield and a green edge on /registro and /cuenta, makes the landing's secondary link monochrome, lets the price cards use the full width, stacks the sign-up buttons above the upload form on a phone, keeps the landing mock-up's address on one line, and tightens the timing tables below 380 px so they fit the screen. On the landing's "Trabajo real, no humo" section, each card's proof link sits at the card's foot with an arrow, so the six links line up. The one-year p95 drawdown tile now carries the same minus sign as the maximum drawdown beside it, in the report and on the PDF cover; the resampled-risk section still lists the depths as positive sizes of a fall. Portuguese gets its own site card (`og-pt.png`) and six audience cards (`og-for-*-pt.png`, first sales' texts); its verification and sample links keep the English card until there is a Portuguese class sentence and notice (`OG_PARTIAL_KINDS`).

Redesign pass 59 checks "¿Le gana a comprar y mantener el mercado?" on a phone and in the PDF. On a phone its row names ("Sharpe en los mismos 599 días…") now wrap instead of pushing both figure columns off the screen, and both worst falls show in red as in the crises table. The PDF already read well and is unchanged.

Redesign pass 60 keeps the sign-up and sign-in form in view on a desktop while the reader goes down "Qué guardamos y cómo borrarlo" beside it (sticky under the menu), and on a phone the "Crear cuenta" and "Entrar" buttons span the card.

Redesign pass 61 checks the Portuguese report (/pt/exemplo and its PDF) on a phone and on paper: both read well, and the cover still fits one page. On the way it found that on a 390 px phone (most iPhones) the last column of the day and hour tables ("Aciertos") was cut off in Spanish, and at 360 px in every language. Up to 420 px the timing tables now use tighter cell padding, unspaced headers and a slightly smaller type, and at 380 px or less a smaller one again, so every column fits.

Redesign pass 62 styles two new account pieces. The strategy summary PDF ("Descargar resumen en PDF") had a tiny title, a stray grey line left from the screen's glow and class letters off-centre, and ran two lines onto a second page; its title is now a clear heading, the line is gone, the letters sit in their circles and the summary fits one page. In "Invita a un colega" the personal link reads as a code in a quiet field, and on a phone the WhatsApp button spans the width and the third tile takes a full row.

Redesign pass 63 styles the report's new statistics blocks. The 95 % ranges ("¿Cuánto de esto podría ser azar?") showed each range at headline size, split over two lines; they now read on one line per card, smaller than the headline figures, with room before the trade table. The reading under the calm/turbulent market split, under the shuffled worst fall and under the ranges (break-even and wholly-below lines) is a ruled line that stands apart from the grey notes. The 2 % + 20 % row of the fund fee table is set off from the flat-rate rows. In the PDF, grey notes were set larger than the body text; they are now slightly smaller, which also saves a page.

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

## Check a report file (`audit/check.py`, `/comprobar`, `/check`)

A buyer usually gets a Rigor report from the seller, as the PDF or the JSON
result. Every PDF and JSON the service hands out (a paid report's downloads
and the sample PDF) has its SHA-256 recorded in `issued_files` with the
audit id, the kind and the first issue date; the file itself is never kept.
On `/comprobar` (Spanish) and `/check` (English) anyone uploads the file
they were given: the server hashes it as it streams in (up to 20 MB,
60 checks per address and hour), discards it, and says either that those
exact bytes came from Rigor on that date for a report of that class (with
the link to its public page when the owner published one), or that Rigor has no
record of them (edited, from elsewhere, never recorded because the database
failed at download time, or issued before 25 September 2026,
when recording started; the page never says Rigor did not produce them). The wording says only whether the file changed since Rigor
produced it, never anything about the strategy, and passes the guard.
These two paths have their own request body limit (20 MB plus 1 MB of form),
so a bigger upload gets the page's 413 message before the server receives
and spools it, instead of after, under the whole-service limit.

A hash, not a digital signature, was chosen on purpose: it needs no key to
keep secret and no Railway variable, and the buyer checks on the site in two
clicks instead of with a tool. The records survive the retention purge like
the audit's other hashes and go with `audit delete ID --yes`. A PDF printed
again, a screenshot or any re-save never matches.

A fifth audience page, for signal copiers (`/para/copiar-senales`, `/for/signal-copiers`), names the risks a copy-trading percentage hides and points each at a live check: martingale sizing, grid averaging, no sign of a stop loss, many small wins with large losses, many positions open at once, hidden floating drawdown, positions still open at the end, and gains inflated by deposits. It asks for the account's exported history, because a screenshot cannot be audited. The landing keeps its four cards and links the fifth page in a line under them, so `AUDIENCE_PAGES` keeps the four card pages first.

### Naming the columns of a file no importer knows (`audit/mapping.py`)

The screen speaks the upload's language: Spanish, English, or Portuguese
(`mapping.COPY["pt"]`) for an upload sent from `/pt`, whose "back" link
returns to `/pt#subir`; a test keeps every Portuguese text on its English
placeholders and through the guard.

Some uploads are tables that no importer recognises: `unknown_format`,
`universal_columns_missing`, a column the customer named that is unreadable
or missing, or one column chosen twice. For these, the upload now answers
with HTTP 422 and a page instead of a refusal. The page shows the file's
header and its first three rows, as read. Each field gets a menu listing the
file's columns with an example value, preselected with the reader's guess or
the customer's earlier choice. The page also carries the first upload's form
fields (starting balance, trials, costs, code, consent), and asks for the same
file again, because the service keeps no file before auditing it. A JSON
client gets `{"error", "code", "columns"}`. An HTML report or anything else
that is not a table keeps the plain error.

Nothing is spent on the mapping step. It is not an audit, so the free first
report, the month's previews and credits are untouched, which the
`test_audit_column_mapping_screen.py` tests check.

When a mapped upload succeeds for a signed-in customer, the choice is saved
in `column_maps`. That table keeps only the account id, the SHA-256 of the
header's normalised names and the column names. The next upload of a file
with the same header that the importers do not recognise is read with that
choice. A recognised format is never overridden. A saved choice that no
longer reads the file brings the mapping page back, preselected.
`Store.delete_account` deletes the account's column maps.

Two columns are enough on their own. A date (the page's "Fecha" menu, or the
exit or fill time) with each trade's result becomes an equity curve: the
results are chained from the declared starting balance (else
`DEFAULT_INITIAL_BALANCE`, with the importers' own warning), from the day
before the first result. A date with the balance or equity column is read as
the curve itself. Either way the file's own SHA-256 is the recorded digest,
and a warning says the trade-level checks cannot be measured (`MAPPED_PROFIT_WARNING`
and `MAPPED_BALANCE_WARNING`, with Spanish rules). Rows without a readable date
or figure are counted in a warning; results that bring the balance to zero or
less are refused with a request to declare the starting balance
(`mapped_results_below_zero`). Fewer than two readable rows bring
the page back (`mapped_curve_unreadable`). A choice that still lacks fields
is answered on the page itself, naming the missing fields for the way the
choice points to (one row per trade, per fill, date and result, or date and
balance).

Columns named on the form are applied before any automatic reader, and a
file sent with them in the curve field is read as the report. A lone file
whose "curve" reaches zero (`equity_not_positive`) and whose figures change
sign at least three times and on 5 % of the rows (`looks_like_results`) is a
list of results: it gets this page, with its first date column and first other
numeric column preselected as the date and the result. A balance that falls below zero
once, or a cumulative profit that starts at 0, keeps the plain refusal
asking for the account balance. A curve-field file
with no date or value column the curve reader knows (`missing_timestamp`,
`missing_value`) gets the page too, with the date and a `Saldo`/`Balance`/
`Equity` column preselected. A cell with both marks, a repeated mark or a lone
mark not followed by three digits is read with the mark it settles; only
`1.234`-like cells follow the column's vote, so a hand-typed column mixing
`12.34` and `-5,60` is never read a hundred times too large. A repeated mark
is a thousands separator only when groups of exactly three digits follow it
(`1.234.567`); `1.2.3`, `1,,2` or `1.234.56` are unreadable and counted with
the rows left out.

A list with no header row whose first row holds a date (an exported P&L list
often has none) is shown with numbered columns (`Col. 1`, `Col. 2`...), in
the report and in the curve field, and read with a date and a result or a
balance chosen among them; a row with a date in it is never taken for the
header. A semicolon file whose first lines all hold the same number of `;`
is split on `;` with comma decimals, so a European export with its header
stripped gets the page too. When the only other column is a number, it is
preselected: as the result when a sample is negative (with the "parece una
lista de resultados" line), else as the balance. The page preselects a date and a `Saldo`/`Balance`/`Equity`/`Capital`
column in the report field too. When the file has no price column and either a balance column or
fewer than two date columns, the date-and-balance-or-result group comes first
and alone is preselected (a `Volumen` column is not guessed as a trade's
quantity); a trade list keeps the trade fields first. The decimal mark of a named figure column comes from its cells
(`12.34` in a semicolon file is twelve), not from the delimiter alone.

A header wider than 500 columns (`universal.WIDEST_HEADER`) is never searched
for roles and gets the plain refusal, so a 200,000-column file is turned down
in about a second instead of rendering a multi-megabyte page. The preview
shows at most 80 columns (`MAX_COLUMNS`) with a count of the rest. The
access code the customer typed travels as a hidden field of this page only;
the page is `no-store` and goes only to the person who typed it.

A sixth audience page, for retail investors (`/para/inversores-particulares`, `/for/retail-investors`), covers people who invest on their own through DEGIRO, Trading 212, Interactive Brokers or XTB. It names only live checks: significance, an optional benchmark CSV, double and triple costs, the result without the best trades and months, the fixed crisis windows and the recent third. It states the reader's limit: a trade history counts only closed positions (open ones and dividends are left out), so a buy-and-hold investor should upload the portfolio's value or return over time. The landing's "Otro caso" line links it too.

The prop-firm audience page (`/para/retos-prop-firm`, `/for/prop-firm-challenges`) now names the firm-fit table as a check ("¿Con qué firma encaja tu historial?"), and it adds a fourth pain: a pass whose payout is held up by the best-day (consistency) rule. The wording says it compares rules and does not recommend buying a challenge.

## Ranges and adjusted figures (math review, 2026-09-26)

Informational only: none of these moves a class, a dimension or a red flag.

- Trade statistics carry `intervals` (10 trades or more): 95 % ranges for the
  win rate (Wilson), the average per trade (Student's t on the per-trade
  results after itemised fees, centred on the reported expectancy) and the
  profit factor (2,000 resamples of the trades with a fixed seed, fewer on
  very long lists; the upper end is NOT_MEASURED when some resamples have no
  losing trade). Each trade is taken as an independent draw; clustered
  trades would widen the ranges.
- The significance section carries `autocorrelation_adjusted` (50 returns or
  more): Lo's (2002) annualised Sharpe, `q / sqrt(q + 2 sum (q-k) rho_k)`
  times the per-period Sharpe, with `q` the periods a year and the sum cut
  at 10 lags or a fifth of the sample. Smoothed returns (AR(1) at 0.5)
  inflate the plain figure by about 1.7x; this one removes it.
- The benchmark section and the fund-versus-index comparison carry `jensen`
  (24 shared periods or more): Jensen's alpha from regressing the
  strategy's period returns on the benchmark's, annualised, with a
  Newey-West t-statistic (lag `floor(4 (n/100)^(2/9))`), beta and R squared.
  When public data is on and FRED's DTB3 covers every period, what the
  3-month US Treasury bill paid over each period (the rate on or before its
  start, at most 10 days old, converted to an annual yield) is subtracted
  from both sides first; the fund comparison uses the month's mean rate.
  Without it nothing is subtracted, `cash_subtracted` is false and the note
  says so, because then a strategy with beta `b` shows `(1 - b)` times what
  cash paid as alpha.
- The fund fee table carries `two_and_twenty`: 2 % a year taken month by
  month and 20 % of each year's gain above the high-water mark taken at the
  year's end and at the last month.
- The fund comparison carries `skill` (36 shared months or more;
  `audit/skill.py`): where the fund's return came from. Each month's fund
  and index returns over cash are regressed: `r_f - c = alpha + beta (r_b -
  c)` splits the average yearly return into cash, exposure and alpha, which
  add up exactly. The exposure share is given only when beta is at least two
  standard errors from zero. `lagged` adds last month's index return (Dimson,
  1979): smoothed or late-priced funds hide exposure from the plain beta,
  and it turns up as alpha. `timing` adds the squared index return over cash
  (Treynor and Mazuy, 1966). Standard errors are the largest of HC3,
  Newey-West and, for the alpha, the plain error widened by `(1 + rho) /
  (1 - rho)` for the misses' autocorrelation (Kendall-corrected). On
  simulated funds with no skill, `|t| > 2` then comes up about 4 % of the
  time, and 5 % to 8 % when the misses are strongly autocorrelated; Newey-West
  alone gave up to 12 %. The alpha has a 95 % Student-t range and, when
  positive but under two standard errors, `months_needed = n (2 / t)^2`.
  Cash is FRED DTB3, the month's mean converted to an annual yield and
  compounded over the month's days, read once per audit through the same
  lookup as the cash-rate Sharpe. Without it, cash is zero and `cash_basis`
  says so. Informational: no flag, no class, no headline.
- The risk section carries `versus_shuffle` (the same 30-return floor as the
  resampled risk, and at least five losing periods): the uploaded maximum
  drawdown against up to 1,000 random orders of the same returns (seed
  20260926). A shuffle keeps the Sharpe, the volatility and the final
  result exactly, so the random orders show the drawdown this Sharpe and
  volatility usually bring over this many periods. `position` is
  `SHALLOWER` when at most 5 % of orders fall no deeper than the upload
  (losses rarely follow losses, as in smoothed or averaged-down curves),
  `DEEPER` when at most 5 % fall at least as deep (losses cluster), and
  `TYPICAL` otherwise. The upload counts as one of the orders. Curves longer
  than 10,000 periods are compounded into blocks first. When more than half
  of the orders tie the uploaded fall (a few losses fall the same in any
  order), it is `NOT_MEASURED` rather than `TYPICAL`, so a smoothed curve is
  never called normal. Informational: it
  moves no flag and no class.

How the report shows them (ES, EN and PT):

- "How much of this could be chance?" under the trade statistics: the three
  ranges side by side, and one line when the range of the average per trade
  includes zero or the profit factor's includes one (either is enough, so a
  disagreement between them never stays silent in the file's favour). When a
  range lies wholly below break-even (and neither straddles it), one line says
  the system loses per trade with these trades and chance does not explain it. The
  intro calls it a 95 % range of values consistent with the trades, not a
  prediction.
- Under the significance table, Lo's Sharpe only when it is lower than the
  plain one by more than a tenth (with the first-order autocorrelation when
  it is 0.1 or more). A higher corrected figure is never printed: with small
  samples it mostly adds noise and would flatter the file. The report says
  the plain figure is not inflated instead.
- Under the benchmark table and in the fund-versus-index block, Jensen's
  alpha with beta, t and the periods, saying it subtracts no cash rate; |t| of 2 or more reads as unlikely to
  be chance alone (with "it does not say it will repeat" for a positive
  alpha), below that as not distinguishable from chance.
- The fee table's last row is "2 % + 20 % of gains".
- In the risk section, "Is the file's worst fall normal for these returns?":
  the uploaded worst fall beside the 5th to 95th percentile of the same
  returns in random order, and one sentence for `TYPICAL`, `SHALLOWER`
  (losses rarely follow losses; the file's fall may understate the risk) or
  `DEEPER` (losses came in streaks). It says it is not the one-year fall
  above. Nothing shows when it is `NOT_MEASURED`.
