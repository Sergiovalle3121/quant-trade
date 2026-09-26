# File consistency ("Coherencia del archivo"): the forensics battery

`src/quant_trade/audit/forensics/` is a battery of arithmetic and structural
checks that runs over the file a client uploads, a second time and read-only,
after the importers have already turned it into trades. It asks whether the
rows still carry the traces a trading platform leaves when it writes them:
running balances that add up, tickets in the server's order, prices printed
with one precision per symbol, no trade stamped inside the weekend closure.
Its public names are "Coherencia del archivo" (Spanish, the default),
"File consistency" (English) and "Coerência do arquivo" (Portuguese).

Status on 2026-09-26: the battery, its calibration table and the seeded
alteration lab are in the repository (`METHOD_VERSION = "forensics-1"`,
freeze date 2026-09-26). The customer page is not: `forensics_web.FORENSICS_ENABLED`
is `False`, so nothing is mounted and every path of the page answers 404.
Sections marked *planned* describe work that is specified but not merged.

This code is research and backtesting tooling. It executes nothing, holds no
funds or keys, connects to no broker, and never claims that money was or will
be made. Every count in this document is MEASURED on the run of 2026-09-26
over the public corpus of Appendix A unless it is marked DECLARED (a value
the file or the design states) or "unsourced".

## 1. What it is and is not

- It is a battery of 23 checks, each an identity the platform's own output
  satisfies by construction (`review.CHECK_ORDER`). Each check answers one of
  four statuses and a set of figures; nothing else.
- It detects careless edits: a row deleted without re-summing the totals, a
  profit rewritten without its balance, a close time moved into a Saturday.
  It does not detect the careful editor, who rewrites every copy of a figure
  (section 6.5 lists the moves it cannot see). The method is public.
- It never says a file is original or edited. `SIGNAL` means "a trace was
  found and this check is calibrated on this format"; `CLEAN` means "the
  traces reviewed were not found", which proves nothing about the file's
  origin. The wording contract (section 7) forbids the words that would turn
  a status into a verdict.
- It never affects the verdict class. `engine.py`, `verdict.py`, `schema.py`,
  `report.py` and `importers.py` are not modified by it (design §0, binding
  constraints); the battery reads the file, writes a result, and the audit's
  class is computed exactly as before.
- Paying changes no status. The result is the same whether the report is
  free or paid; what payment changes is only where the page is shown
  (section 8).
- It measures the file, not the account. A file exported from a terminal whose
  trades were fabricated upstream is internally consistent by construction
  and every check answers `CLEAN` on it.

## 2. Contract

`forensics.review(data, *, source_format, imported_warnings=(), monthly=None, currency=None) -> ForensicResult`
(`review.py`). The result is a frozen dataclass (`results.py`).

### 2.1 Statuses and the one rule

Every check returns a `RawOutcome(hits, figures, examples, not_measured, reason)`
and `review.decide(check_id, family, raw)` turns it into a status. No check
can bypass it (design D1):

```
NOT_MEASURED  raw.not_measured (a reason code from review.REASONS)
CLEAN         raw.hits == 0, calibrated or not (D2)
SIGNAL        raw.hits > THRESHOLDS.get((check, family), 0)
              and the check is in calibration.SIGNAL_CAPABLE
              and CALIBRATION[(check, family)].granted
INFO          otherwise (a hit on a cell that is not granted, or on a
              descriptive check)
```

`Cell.granted` (`calibration.py`) is true only when the cell is frozen, holds
`n >= CALIBRATION_MIN_FILES` (20) calibration files from
`groups >= CALIBRATION_MIN_GROUPS` (10) distinct accounts or strategies, and
`unexplained == 0` (`thresholds.py`). `THRESHOLDS` is empty in this freeze:
any hit on a granted cell is a `SIGNAL`.

`SIGNAL_CAPABLE` (15 checks): `TOTALS_VS_ROWS`, `SUMMARY_IDENTITIES`,
`BALANCE_CHAIN`, `DEAL_SEQUENCE`, `TESTER_NUMBERING`, `DUPLICATE_TICKET`,
`TICKET_LINKS`, `CROSS_COPIES`, `SLTP_FILL`, `PNL_SIGN`, `PRICE_PRECISION`,
`TIME_SANITY`, `MARKET_HOURS`, `HIDDEN_CONTENT`, `ROW_ORDER`. The other eight
(`FILE_TRACE`, `STATEMENT_PERIOD`, `TICKET_ORDER`, `PRICE_IMPLIED_PNL`,
`VOLUME_IN_OUT`, `TV_INVARIANTS`, `NT_INVARIANTS`, `MONTHLY_DIGITS`) are
descriptive: `CLEAN` or `INFO`, never `SIGNAL`.

### 2.2 Evidence tags

Every figure is `(key, value_as_text, evidence)` with evidence in
`results.EVIDENCE = ("MEASURED", "DECLARED", "NOT_MEASURED")`. `MEASURED` is
computed from the rows; `DECLARED` is a value the file states (a summary
label, the header date, the `sat13_sun08` window constant, an order key the
rule picked); `NOT_MEASURED` is a figure the family cannot produce, emitted as
`0` so every check carries one key set whatever the family. A declared value
never renders as measured and no status derives from a declared value alone.

### 2.3 Determinism and versioning

`review` is pure: no clock (`TIME_SANITY` uses the file's own header date),
no randomness, no network, no I/O beyond `data`; it never re-imports
(`import_report` is not called). Two calls with equal inputs return equal
`as_dict()`. Money is `Decimal` from the printed text; no float reaches a
result; sorts have explicit keys with raw-row index as the tie-breaker.

`METHOD_VERSION = "forensics-1"` (`review.py`) is bumped on any change that
can move a status or a figure. `thresholds.py` and `calibration.py` are
SHA-256 pinned by `tests/test_forensics_review.py::test_frozen_modules_are_pinned_to_the_method_version`
(pins for `forensics-1`: thresholds `94ecda0106a8…a075d9`, calibration
`e86f40f0c235…4927d8`); editing either module fails the test until the
version moves and new pins are written (D5).

### 2.4 What is stored

`ForensicResult.as_dict()` holds only strings, ints, bools and lists: the
method version, the source format, the family, every check's status, figures,
examples, reason and calibration line, the status counts, `rows_read`,
`truncated` and `header_present`. No text from the file enters it (D16):
generator names, symbols, tickets and comments become codes or counts, and
`examples` are at most five raw-row indexes (0-based, lowest first). The
account number is never a field, not even hashed; `header_present` is the
only trace that a header was seen. A test greps every fixture's serialised
result for the fixture's account number, trader name, broker and EA name.

### 2.5 Language-free codes

Check ids are `UPPER_SNAKE`; statuses, reason codes (`review.REASONS`,
Appendix B) and figure keys are ASCII codes. The sentences live in the web
layer (section 7), never in the battery.

### 2.6 Caps

`rows.load` stops a table at `schema.MAX_ROWS` and sets `truncated=True`;
`review` then answers `NOT_MEASURED("truncated")` for every order-sensitive
check (`review.ORDER_SENSITIVE`: `BALANCE_CHAIN`, `DEAL_SEQUENCE`,
`TESTER_NUMBERING`, `TICKET_ORDER`, `ROW_ORDER`, `VOLUME_IN_OUT`,
`TV_INVARIANTS`, `NT_INVARIANTS`). `ReportFormatError` from the importers'
readers propagates unchanged: such a file was already refused at upload.

## 3. Families and what the reader sees

### 3.1 Families (`families.py`)

The calibration cell of a check is `(check_id, family)`. HTML and XLSX
exports of one MetaTrader table are one family because the importer's sheet
reader yields the same rows; tester and account families are never pooled
(a live account carries corrections, dividends and credits a tester never
prints).

| family | `source_format` values | corpus files (public, Appendix A) |
|---|---|---|
| `mt4_statement` | `mt4_statement_html` | 70 |
| `mt5_history` | `mt5_history_html`, `mt5_history_xlsx` | 13 (10 HTML, 3 XLSX) |
| `mt5_tester` | `mt5_tester_html`, `mt5_tester_xlsx` | 39 (35 HTML, 4 XLSX) |
| `mt4_tester` | `mt4_tester_html` | 22 |
| `myfxbook` | `myfxbook_csv` | 20 |
| `mql5_signal` | `mql5_signal_csv` | 28 |
| `fxblue` | `fxblue_csv` | 5 |
| `tradingview` | `tradingview_csv`, `tradingview_xlsx` | 0 (repo fixtures only) |
| `ninjatrader` | `ninjatrader_csv` | 0 (repo fixture only) |
| `monthly` | a `factsheet.MonthlyGrid` passed as `monthly=` | 0 |
| `other` | every other importer format, or `source_format=None` | 0 |

`families.XLSX_FORMATS` marks the spreadsheet formats whose cells lost their
printed zeros; `TESTER_FAMILIES` and `HTML_FAMILIES` / `CSV_FAMILIES` are the
groupings the checks branch on.

### 3.2 The reader (`rows.py`)

`rows.load(data, source_format) -> RawTable` reads the file again through the
importers' own readers (`unwrap`, `decode_text`, `read_xlsx`, `_read_html`,
`_read_delimited`), without mutating them, and hands out frozen tuples:
`RawRow(index, texts, cells, section, kind, header_row)` and
`RawCell(text, hidden, title)`. Nothing in the reader interprets a number. A
public reader is requested from the importers' owner (section 8); until it
lands, the private names used here are pinned by a test.

Sections: `header`, `closed`, `open`, `working`, `positions`,
`open_positions`, `orders`, `deals`, `tester`, `summary`, `csv`, `other`.
Row kinds: `mt4_trade`, `mt4_cash`, `mt4_credit`, `mt4_cancelled`,
`mt4_pending`, `mt4_open`, `mt4_working`, `mt5_deal`, `mt5_position`,
`mt5_order`, `mt5_open_position`, `mt4_tester`, `csv`, `header`, `title`,
`label`, `footer`, `other`; decided with the importers' own predicates.
`RawTable` also carries `generator`, `encoding`, `line_endings`, `markers`,
`labels` (`Label: value` pairs of header and summary), `truncated` and, for
delimited files, `header` and `delimiter`. `header.read_header` reads the
currency, the report date and its source, the margin mode (`hedge`,
`netting`, `exchange`) and the account type from the labels; the number and
the name are never fields.

Real-file facts that shaped the reader and the checks:

- Localised headers. Summary labels of tester and history reports appear in
  Spanish, Italian, Portuguese, Russian, Chinese and Czech in the corpus;
  `totals._MT5_EXTRA_ALIASES` lists them beside the importers' alias tables
  (source: `docs/research/audit_iteration4/mt_languages_check.md` and the
  corpus). An MT5 Orders row's fill-time and state columns come from its
  header when the header is in English, else from the eleven-column layout
  (`times._mt5_order_cells`).
- MT4 statement layouts: the 13-column (2005) and 14-column (build 600+,
  with Taxes) closed tables and the 15-column numbered layout with a
  Comment column (DECLARED from the design §2.1; the 14-column layout is the
  one measured on the two user-sorted statements of section 4.16). Older
  statements print the header date as MT time with a suffix
  (`header._MT4_DATE_OLD`, 2006 form) rather than "2024 March 8, 18:30".
- 2009 comment rows. Older MT4 builds print a trade's comment as a separate
  single-text row right after the trade instead of a `title` attribute on
  the ticket cell; `tickets._mt4_comment`, `links._mt4_comment` and
  `prices._mt4_comment` read the title, else the Comment column, else that
  row. A title equal to the ticket is the numbered layout's tooltip, not a
  comment.
- Old MT5 builds without a Positions table. Three of the 11 calibration
  `mt5_history` files and one reserved file print no Positions table:
  `PNL_SIGN` and `PRICE_IMPLIED_PNL` answer `no_table` there, `CROSS_COPIES`
  `no_table` on one, and `VOLUME_IN_OUT` cannot seed pre-period volume
  (`balance._pre_period_volume` returns `None`). Older MT5 builds also wrote
  "MetaTrader 5" as the generator (`metatrader` code, native).
- Header-less MT5 XLSX deal rows. A workbook may store one blank trailing
  cell past the comment; `RawTable.layout_widths` keeps, per section, the
  widest deal row once trailing blanks are dropped, so a header-less row with
  no comment keeps its layout (added after the reserved run, section 5.6).
- Re-save markers. Every MetaTrader HTML export (137 of 137 corpus files)
  styles its cells with an `mso-number-format` rule so Excel reads the
  numbers; `rows.resave_markers` counts that rule as one `mso-` marker and
  `FILE_TRACE` treats one marker as the platform's own. 51 of 70 MT4
  statements and 8 of 22 MT4 tester reports carry no `generator` meta at all,
  so `none` is native for the MT4 families; MT5 exports always name their
  terminal or tester.
- FX Blue exports may list several accounts; the importer reads the one with
  the most closed positions, and so do `STATEMENT_PERIOD` and
  `PRICE_IMPLIED_PNL`; `TICKET_ORDER` and `DUPLICATE_TICKET` decline such a
  file (`several_accounts`). All five corpus FX Blue files list two accounts.
- A genuine MT5 export hides only empty cells (the Positions filler, the
  Deals' `Cost` column) plus the `Cost` label of the Deals header, which is
  why `HIDDEN_CONTENT` leaves header rows outside its rule.
- Two corpus MT4 statements (successive exports of one account) are row
  misaligned between `edit.rows_of` (97 and 48 blocks) and `rows.load` (98
  and 50 rows). The battery reads them like any other file; the forgery lab
  refuses to edit them by row index (section 6.4). The cause is not yet
  found (open question for the owners of `edit.py` / `rows.py`).

## 4. The 23 checks

Conventions shared by every check (design §3): rows come from `rows.load`;
money is `Decimal` from the printed text with `MONEY_TOLERANCE = 0.011` per
comparison of two printed cells (`0.011 × n` over a column of `n` rows);
"printed decimals" are the digits after the decimal point as printed;
balance-type rows, cancelled pending rows and tester `end of test` / `close
at stop` rows are excluded from every price, time and market check unless a
check says otherwise; each check emits `n_rows` and `n_hits`; `examples` are
the lowest five raw-row indexes of hits. Figures marked `0` with
`NOT_MEASURED` are keys the family cannot fill (section 2.2). The full key
list per check is in Appendix B.

Summary (SC = `SIGNAL_CAPABLE`; granted = cells that may answer `SIGNAL`
in `forensics-1`, section 5):

| # | check | module | families measured | SC | granted cells |
|---|---|---|---|---|---|
| 1 | `FILE_TRACE` | `checks/trace.py` | all | no | – |
| 2 | `TOTALS_VS_ROWS` | `checks/totals.py` | MT4/MT5 statement, history and testers, TradingView, NinjaTrader | yes | `mt5_tester` |
| 3 | `SUMMARY_IDENTITIES` | `checks/totals.py` | `mt4_statement`, `mt5_history`, `mt5_tester`, `mt4_tester` | yes | `mt5_tester` |
| 4 | `BALANCE_CHAIN` | `checks/balance.py` | `mt5_history`, `mt5_tester`, `mt4_tester` | yes | `mt5_tester` |
| 5 | `DEAL_SEQUENCE` | `checks/tickets.py` | `mt5_history`, `mt5_tester` | yes | `mt5_tester` |
| 6 | `TESTER_NUMBERING` | `checks/tickets.py` | `mt5_tester`, `mt4_tester` | yes | `mt5_tester` |
| 7 | `TICKET_ORDER` | `checks/tickets.py` | `mt4_statement`, `myfxbook`, `fxblue` | no | – |
| 8 | `DUPLICATE_TICKET` | `checks/tickets.py` | `mt4_statement`, MT5 families, `myfxbook`, `fxblue`, `tradingview`, `ninjatrader` | yes | `mt5_tester` |
| 9 | `TICKET_LINKS` | `checks/links.py` | `mt4_statement` | yes | – (n = 0) |
| 10 | `CROSS_COPIES` | `checks/links.py` | `mt5_history` (hedge) | yes | – |
| 11 | `SLTP_FILL` | `checks/prices.py` | `mt4_statement`, `mt5_history`, `mt5_tester` | yes | `mt5_tester` |
| 12 | `PNL_SIGN` | `checks/prices.py` | `mt4_statement`, `mt5_history`, `myfxbook`, `mql5_signal`, `fxblue`, `tradingview` (G3b), `ninjatrader` | yes | `mql5_signal` |
| 13 | `PRICE_IMPLIED_PNL` | `checks/prices.py` | `mt4_statement`, `mt5_history`, `myfxbook`, `mql5_signal`, `fxblue`, `tradingview` | no | – |
| 14 | `PRICE_PRECISION` | `checks/prices.py` | `mt4_statement`, `mt4_tester`, `mt5_history` HTML, `mt5_tester` HTML | yes | `mt5_tester` |
| 15 | `TIME_SANITY` | `checks/times.py` | all with timestamps | yes | `mt5_tester`, `mql5_signal` |
| 16 | `ROW_ORDER` | `checks/times.py` | all with timestamps | yes | `mt5_tester`, `mql5_signal` |
| 17 | `MARKET_HOURS` | `checks/times.py` | all with timestamps and a listed pair | yes | – |
| 18 | `HIDDEN_CONTENT` | `checks/trace.py` | `mt5_history` HTML, `mt5_tester` HTML | yes | `mt5_tester` |
| 19 | `VOLUME_IN_OUT` | `checks/balance.py` | `mt5_history`, `mt5_tester` | no | – |
| 20 | `STATEMENT_PERIOD` | `checks/trace.py` | `mt4_statement`, `mt5_history`, `myfxbook`, `mql5_signal`, `fxblue` | no | – |
| 21 | `TV_INVARIANTS` | `checks/platforms.py` | `tradingview` | no | – |
| 22 | `NT_INVARIANTS` | `checks/platforms.py` | `ninjatrader` | no | – |
| 23 | `MONTHLY_DIGITS` | `checks/monthly.py` | `monthly` | no | – |

### 4.1 `FILE_TRACE` (descriptive)

What the file says about its own making: `encoding` (re-derived with
`decode_text`'s rules: `utf16le_bom`, `utf16be_bom`, `utf8_bom`, `utf8`,
`cp1251`, `cp1252`, `latin1`), `line_endings` (`crlf`, `lf`, `mixed`),
`generator` (`metaquotes`, `client_terminal`, `strategy_tester`,
`metatrader`, `excel`, `word`, `mshtml`, `other`, `none`), `generator_native`,
`resave_markers`, `platform_markers`, `title_attrs`, `hidden_cells`,
`decimal_comma` and a `sections` bitmask. `CLEAN` when the generator is native
for the family and no marker beyond the platform's own is present, else
`INFO`. Scoping from the corpus: the `mso-number-format` rule of every
MetaTrader page is one native marker; `none` is native for the MT4 families
(51 of 70 statements, 8 of 22 tester reports have no generator meta); the
MT5 optimizer's Excel XML carries three native markers. Calibration INFO
count: 3 `mt4_tester` files (one re-saved by a browser, `mshtml`; two with
the MetaQuotes generator kept but one re-save marker and `cp1251` encoding),
0 elsewhere.

### 4.2 `TOTALS_VS_ROWS` (SC)

The importer's own comparisons, not re-implemented (D11): each
`"<what>: the report states X but the rows add up to Y"` line of
`imported_warnings` becomes a hit with `declared` (DECLARED) and `measured`
(MEASURED) as text and a `what_code`; the importer's "N Balance cell(s)"
line becomes `importer_balance_breaks`. Tolerance is the importer's:
`0.011 × n` on money, so a +1.00 edit on a 331-row statement stays inside it
(section 6.3). `NOT_MEASURED("no_declared_totals")` when the format carries
no summary (every Myfxbook, MQL5 signal and FX Blue export; one reserved
`mt4_statement` without a summary block; two `mt5_history` files).

### 4.3 `SUMMARY_IDENTITIES` (SC)

Label against label, never label against rows: `mt4_statement`
`Balance = Deposit/Withdrawal + Closed Trade P/L` (only when the first cash
row is a deposit dated at or before the first trade, i.e. a full-history
export; a period export is `no_qualifying_row` for that identity) and
`Equity = Balance + Credit + Floating P/L`; `mt5_history`
`Total Net Profit = Gross Profit + Gross Loss`, `Equity = Balance + Floating
P/L`, `Free Margin = Equity − Margin` when printed; `mt5_tester` the net
profit identity, `Total Trades = Profit Trades + Loss Trades` and the profit
factor to two decimals; `mt4_tester` the net profit identity and
`Total trades = Short + Long`. Figures per identity: the key with its status
and `_left` / `_right` DECLARED values. Scoping from the corpus: the MT4
statement never gets `Free Margin = Equity − Margin` (a real export showed
free margin 14.24 below equity with nothing open and `Margin: 0.00`; the
server's free-margin mode is a setting the statement does not print); labels
unknown to the alias tables make that identity `NOT_MEASURED`, never a hit.
CSV families are `format_not_covered`.

### 4.4 `BALANCE_CHAIN` (SC)

Every MT5 deal and every MT4 tester close prints the balance after it, so
each balance must be the previous balance plus the row's money (commission,
fee, swap, profit, plus a number in a hidden `Cost` cell when a broker fills
it). Deal types other than `buy`, `sell` and `balance` (credit, correction,
bonus, dividend…) restart the chain (`restarts`); two same-second deals
printed out of execution order are forgiven when swapping them closes both
gaps (`ties_fixed`); the first row seeds the chain (`skipped_first`);
`initial_balance_implied` is the first balance minus the first amount. Other
figures: `first_break_row`, `largest_gap`, `hidden_cost_rows`. MT4
statements and CSV families have no running balance (`no_column`). The one
corpus hit (reserved third, an XLSX history) is recorded in section 5.6.

### 4.5 `DEAL_SEQUENCE` (SC)

An MT5 server hands out deal tickets in time order: among `buy` / `sell`
deals in file order, tickets strictly increase and times never decrease
(`ticket_inversions`, `time_inversions`); order tickets increase with
placement time (`order_inversions`). A deal whose order is absent from the
Orders table is `orders_missing_for_deals`, a figure only (an order placed
before a custom period is absent legitimately, D10). Only the MT5 families.

### 4.6 `TESTER_NUMBERING` (SC)

`mt4_tester`: the `#` column must be `1..N` consecutive in file order
(`gaps`, `duplicates`, `out_of_order` all count) and each order number should
appear at least twice unless the run ended with it open
(`orders_single_row`, figure only). `mt5_tester`: deal numbers strictly
increasing with no duplicates, order numbers with no duplicates; `deal_gaps`
and `order_gaps` are figures, not hits, because the shared-counter
hypothesis (D18) is unverified. Every corpus tester's first deal is its
initial deposit numbered 1 (`tickets._MT5_TESTER_FIRST_DEAL`).

### 4.7 `TICKET_ORDER` (descriptive)

MT4-style tickets against open and close times: rows sorted by ticket,
adjacent pairs whose open time runs backwards by more than 60 s
(`inversions_open_time` = `n_hits`), the same on close time
(`inversions_close_time`), and the largest backwards step in seconds. INFO by
design: MT4 assigns the ticket at placement but prints the activation time of
a filled pending order, so the file cannot say which inversions are
legitimate. Rows marked `from #` or `swap open` keep an older open time under
a newer ticket and are excluded. Calibration INFO count: the two
`mt4_statement` files of one account whose closed table was sorted by the
T/P column (section 4.16); FX Blue files with two accounts are
`several_accounts`; Myfxbook exports without a ticket column are `no_column`.

### 4.8 `DUPLICATE_TICKET` (SC)

No id printed twice within its table: MT4 tickets across Closed
Transactions, Open Trades and Working Orders; MT5 deal ids, order ids within
Orders and position ids within Positions (never the Deals' `Order` column,
which repeats on partial fills); Myfxbook and FX Blue `Ticket`; TradingView
trade numbers whose row group is not two rows (an open last trade with one
row is `open_last_trade`); NinjaTrader trade numbers. `identical_rows`
(identical visible text tuples) is a figure only: copy-trading masters and
grid EAs repeat trades under different tickets. MT4 tester order numbers
repeat by construction, so the family is `format_not_covered` here (its `#`
column belongs to `TESTER_NUMBERING`).

### 4.9 `TICKET_LINKS` (SC, n = 0)

MT4 `to #N` / `from #M` references of partial closes, read from the ticket
cell's `title` (or the Comment column, or the 2009 comment row): the linked
row must exist, carry the reverse reference and share symbol, side, open
time and open price. A reference whose ticket is not in the file is
`links_unresolved`, never a hit (closed outside a custom period, or a
remainder still open). The corpus holds no partial close at all (0 rows with
`to #` / `from #` across the 70 MT4 statements, 69 of which carry comment
titles), so every file is `no_qualifying_row`, no cell exists and the check
stays `INFO` by mechanism until real files with partial closes are added.

### 4.10 `CROSS_COPIES` (SC)

An MT5 history report prints every closed position in three tables. For each
Positions row: its entry deals (`in` deals whose Order is the position id)
must share symbol, time, price and total volume; its exit deals (`out` /
`out by` at the same symbol, close time and close price) must sum to its
volume, summed per (symbol, time, price) group so positions closed together
by one order compare as one; when the Orders table exists, the orders those
deals name must share the symbol, have a fill time within `ORDER_FILL_DRIFT`
(1 s) of the deal and state `filled`. Hedge accounts only: a netting or
unknown margin mode is `netting_or_unknown_margin_mode` (two of the
calibration histories). Scoping from a real file: a position closed in parts
prints one row with the last exit's time and the volume-weighted exit price,
which no single deal repeats: `exits_partial`, never a hit. Positions opened
before the first deal (`positions_before_period`) and orders placed before
the period (`orders_unresolved`) are figures, never hits.

### 4.11 `SLTP_FILL` (SC)

A take-profit fills at its level or better, a stop-loss at its level or
worse (D8, inequalities): MT4 rows whose comment carries `[tp]` / `[sl]`
against their S/L and T/P cells; MT5 deals whose comment matches
`[tp 1.08700]` / `sl 1.09900` against the price in the comment. A statement
row whose level cell reads zero was cleared after the fill and is
`levels_cleared`, not measured. Scoping from the corpus: on a live account
under market execution a triggered stop fills at the market, and real
statements show it a few points better than the level, so stop fills are
judged on `mt5_tester` only (`prices._SL_JUDGED_FAMILIES`) and elsewhere a
better stop fill is `sl_better_fills`, never a hit. Files with no marked
close are `no_qualifying_row` (51 of 65 calibration MT4 statements, 4 of 11
histories, 3 of 26 testers).

### 4.12 `PNL_SIGN` (SC)

The sign of each closed trade's gross result against the sign of its price
move (`move = (exit − entry) × (+1 long / −1 short)`); zero-result legs (an
MT4 `close by` books the result on one ticket) and zero moves are skipped
(`n_zero_gross`, `n_zero_move`, `rows_unparsed`). Gross: MT4 `Profit`; MT5
Positions `Profit`; Myfxbook `Profit − Commission − Swap`; MQL5 signal and
FX Blue `Profit`; TradingView G3b `Net PnL + Commission` (G1 has no commission
column: `no_column`); NinjaTrader `Profit + Commission + fees`. Never the
testers: an MT4 tester's Profit is net of swap and commission and an MT5
tester needs deal pairing. `mt5_history` files without a Positions table are
`no_table`.

### 4.13 `PRICE_IMPLIED_PNL` (descriptive, D9)

Per symbol whose quote currency equals the account currency (or gold and
silver on a USD account), the gross result of every closed trade against the
price move times the volume times the one contract multiplier
(`CONTRACT_MULTIPLIERS = 1 … 100000`) that fits most rows; a symbol whose best
multiplier explains fewer than two thirds of its rows (`IMPLIED_PNL_MIN_FIT`)
is `symbols_no_fit`, a single-row symbol `symbols_single_row`, never hits.
Myfxbook, MQL5 signal and FX Blue exports carry no account currency, so they
are `quote_currency_differs`; only 17 of the 65 calibration MT4 statements
(from 7 accounts) had a measurable symbol. An FX Blue file with several
accounts is read for the busiest one. INFO by design in v1.

### 4.14 `PRICE_PRECISION` (SC)

Per symbol as printed (suffix variants are distinct symbols), the histogram
of printed decimals over open price, close price and non-zero S/L and T/P
(MT4 tester: Price, S/L, T/P of every row of the run's single symbol). A
symbol printed with two or more digit counts is a hit; its rows outside the
mode are the examples (`n_rows_off_mode`). Scoping: on a live account's
record (`mt4_statement`, `mt5_history`) a clean one-time gain of digits is
`split_symbols` (a broker's 4-to-5-digit migration inside the period), not a
hit; on the MT4 tester a `swap open` row and the `modify` rows of the order
it reopened carry a swap-adjusted price beyond the symbol's digits and are
excluded. XLSX exports lost their zeros (`xlsx_precision_lost`: 1 + 2
histories, 3 + 1 testers); Myfxbook, FX Blue, TradingView, NinjaTrader and
the MQL5 signal CSV trim them (`variable_precision_format`; the MQL5 export
prints floats as written, down to `2084.6` and sixteen-decimal float noise).

### 4.15 `TIME_SANITY` (SC)

Hits: `unparseable` (a time-shaped cell `_one_time` cannot parse),
`close_before_open_over_1h` (`CLOSE_BEFORE_OPEN_ALLOWED` = 60 min) and
`after_report_date` (a row later than the report's own date by more than
`AFTER_REPORT_DATE_ALLOWED` = 14 h + 60 s: server clocks run up to 14 h ahead
of the terminal's). Figures only: `backwards_within_1h` (a DST fall-back),
`zero_duration`, `report_date` and `report_date_source` (DECLARED: `header`
for the MT4 first-row date or the MT5 `Date:` label, `period_end` for a
tester's period end, whose rows may fall anywhere on that day),
`max_ahead_seconds`. CSV formats have no header date: the first two hits are
still measured and `after_report_date` is `NOT_MEASURED` as a figure.

### 4.16 `ROW_ORDER` (SC)

MT5 deals and MT4 tester rows are written in time order: `time_inversions`
in file order are hits (ties unordered). Statements and exports take the
direction of the majority of their steps (`direction`, `direction_rule`).
An MT4 statement is compared under the best of three platform keys (ticket,
open time, close time: `order_key`, DECLARED); a grouped statement with
"Total for" subtotal lines, or a change of account, starts a new chain and
rows of different chains are never compared. Ties are counted (`ties`).

Scoping rule added in the calibration pass (commit `8f115ca`,
`times._sorted_column`, `KEY_COLUMN = "column"`): the MT4 Account History
grid can be sorted by clicking any column header and "Save as Report" writes
the rows as displayed. Two calibration files of one account (sha256
`351c3bdf0f89…`, `4be413bde568…`; 145 and 71 trade rows) had about 37 %
adjacent inversions on ticket, open and close time alike (57, 58, 59 of 144
steps; 26, 27, 26 of 70), while their T/P column (header index 7) had 0
inversions ascending (115 and 62 distinct values) and inside every T/P tie
the tickets rose (30 of 30 and 9 of 9 tie steps): a stable sort of the
ticket-ordered grid by one column. The rule, for `mt4_statement` only and
only when ticket, open and close keys all still show hits: a printed numeric
column of the closed table (Size, open Price, S/L, T/P, close Price,
Commission, Swap, Profit) is the order key when every trade row prints a
number in it, it has 0 inversions against its majority direction, at least
one step is not a tie, and inside every tie the tickets keep their own
direction. The outcome then reports `order_key=column`, `sorted_column=7`
and 0 hits. Its unit test
(`tests/test_forensics_times.py::test_row_order_statement_sorted_by_a_printed_column`)
covers ascending, descending, ties against the ticket direction (still a
hit) and a non-numeric cell (still a hit). The rule's price: on a four-row
statement a swap of two rows can leave some printed column monotone and go
unseen (section 6.3).

### 4.17 `MARKET_HOURS` (SC)

The 28 pairs of USD, EUR, GBP, JPY, CHF, AUD, CAD and NZD
(`symbols.FOREX_PAIRS`), after normalisation (`symbols.normalise_pair`:
upper-case, strip a parenthesis, first six letters, a known suffix). Forex
closes Friday 22:00 UTC (winter) and reopens 48 h later; with server offsets
in [−12 h, +14 h] and both DST regimes the core closed window is
[Sat 12:00, Sun 09:00) server time (`WEEKEND_CORE`); hits are counted one
hour inside it, [Sat 13:00, Sun 08:00) (`WEEKEND_COUNTED`, code
`sat13_sun08`, DECLARED). Rows: open and close times of `buy` / `sell` rows
of listed symbols; excluded: balance and credit rows, cancelled or expired
pending rows, `swap close` / `swap open`, `end of test`; on the MT4 tester
only fills are events (`close`, `t/p`, `s/l`, `close by`). Figures:
`symbols_measured`, `timestamps_measured`, `core_hits`,
`inferred_offset_minutes` (the 30-minute-step offset that puts the fewest
stamps inside the full closure; INFO only), `holiday_hits` (Dec 25, Jan 1;
figure only). Files with no listed symbol are `no_listed_symbol` (49 of 65
calibration MT4 statements, 16 of 26 MT5 testers, 13 of 20 MQL5 signals,
9 of 11 histories): metals, indices, crypto and synthetic symbols are not
examined. No cell reaches 20 files: the check answers `INFO` on a hit
everywhere.

### 4.18 `HIDDEN_CONTENT` (SC)

MT5 HTML exports hide empty cells (the Deals' `Cost`, the Positions filler)
with the `hidden` class. Hits: a hidden cell carrying text other than a
number in `Cost` (which `BALANCE_CHAIN` consumes as `hidden_cost_rows`) and a
row whose every cell is hidden (`hidden_nonempty`, `hidden_rows`,
`n_hidden_cells`). The header's own hidden `Cost` label is outside the rule.
XLSX exports have no hidden cells (`no_column`). The reader honours the
`hidden` class only: a row hidden by `style="display:none"` is read like any
other row, so the audit sees and reports it (section 6.5).

### 4.19 `VOLUME_IN_OUT` (descriptive)

Per symbol of the MT5 deals in file order: `in` adds volume, `out` / `out
by` remove it, `in/out` closes everything and opens the remainder; a symbol
that goes negative is a hit (`first_negative_row`). Scoping from the corpus:
a history exported for a period after positions were opened starts with
`out` deals, so the volume of Positions rows opened before the first deal is
seeded first (`pre_period_positions`); without a Positions table (old builds)
nothing can be seeded. INFO by design.

### 4.20 `STATEMENT_PERIOD` (descriptive, never a finding)

`first_row_at`, `last_row_at` (ISO), `opens_with_deposit`, `n_accounts` and
the DECLARED `report_date`, over the closed record only (the closed section of
an MT4 statement, the Deals of an MT5 history, the rows before Myfxbook's
"Open Trades" block). Always `CLEAN` with figures, or `no_qualifying_row`
when no row is dated: a chosen period leaves no trace inside one file.

### 4.21 `TV_INVARIANTS` (descriptive, n = 0 real files)

TradingView "List of trades": trade numbers without gaps (`numbering_gaps`,
`numbering_start`, `rows_without_number`); one entry and one exit row per
trade repeating the trade-level values (`pair_shape`, `pair_values`);
cumulative P&L at a flat moment equal to the sum of trades closed by then
within `0.006 × k + 0.01` (`cumulative`); `Size (value)` = entry price ×
quantity × one multiplier per file (`size_value`, `size_multiplier`);
`Return %` = net over that value (`return_pct`); no exit before its entry.
The trade closed last may be an end-of-data close and is excluded from the
value identities (`last_trade_excluded`). Column names come from the
importers' own readers.

### 4.22 `NT_INVARIANTS` (descriptive, n = 0)

NinjaTrader "Trades" grid: trade numbers without gaps or repeats,
`Cum. net profit` the running sum of `Profit` across the grid (also over
several accounts, `n_accounts`), `ETD == MFE − Profit` within 0.011, no exit
before its entry. Profit is net of commission, so no price identity is
asserted on it.

### 4.23 `MONTHLY_DIGITS` (descriptive, n = 0)

On a `factsheet.MonthlyGrid` of at least `MONTHLY_MIN_VALUES` (60) values:
the reconstructed printed precision, the chi-square of the last printed digit
(`last_digit_chi2`, descriptive only, D17), values repeated
`MONTHLY_REPEAT_MIN` (3) times or more, `max_multiplicity`, `rounding_grid`,
`zero_months` and the grid's own `year_mismatch` count. Scoping: on a
rounding grid (every value on a 0.1-point grid) nothing counts as a hit,
since rounding alone repeats values and moves about one real year in six past
the grid's tolerance. Fewer values: `too_few_values`.

## 5. Calibration

### 5.1 Procedure

1. Corpus. 197 public files with `genuine=true` in `genuine_manifest.json`
   (sha256 `3fcf50a65cbe40159fc643c4a4124f5376eaa11e5de09216855ca4d2536838c9`),
   122 groups (an account or strategy exported more than once is one group).
   The files live outside the repository and are never committed; Appendix A
   lists their URLs and SHA-256 only.
2. Split before any check runs. Per family, groups sorted by their smallest
   SHA-256; positions 2, 5, 8, … (0-based) are the reserved third
   (`tests/forensics_corpus.py::split`, identical to the sealed `split.json`).
   Calibration 157 files, reserved 40. Per family (files / groups):
   calibration fxblue 5/2, mql5_signal 20/16, mt4_statement 65/8, mt4_tester
   15/15, mt5_history 11/6, mt5_tester 26/26, myfxbook 15/11; reserved
   mql5_signal 8/8, mt4_statement 5/3, mt4_tester 7/7, mt5_history 2/2,
   mt5_tester 13/13, myfxbook 5/5, fxblue 0.
3. Calibration two thirds. `python tests/forensics_corpus.py MANIFEST ROOT --out …`
   ran `review` on each file the way the service will (importer warnings and
   currency fed in). Every hit on a `SIGNAL_CAPABLE` check was listed; run 1
   had one hit cell, `ROW_ORDER × mt4_statement` (two files of one account),
   explained as platform behaviour and scoped by the row-shape rule of
   section 4.16 with a unit test (D3: a scoping rule, never a nudged
   threshold). Run 2 after the rule: zero hits on every `SIGNAL_CAPABLE`
   cell. No file failed to run.
4. Freeze. `calibration.CALIBRATION` was written with `n` (calibration files
   on which the check measured, `CLEAN` or `INFO`), `groups`, `unexplained`
   and `frozen = FREEZE_DATE` (2026-09-26, `thresholds.py`); `THRESHOLDS` is
   empty. 55 cells: every `SIGNAL_CAPABLE` check × family with at least one
   measured file. Cells with no measured file (`TICKET_LINKS` everywhere,
   `CROSS_COPIES` outside `mt5_history`, every `tradingview`, `ninjatrader`,
   `monthly` and `other` cell) are not written and answer `INFO` at most.
5. Reserved third, opened once, with the frozen table imported. One hit:
   `BALANCE_CHAIN × mt5_history` on one of the two reserved files. Recorded
   as `unexplained = 1`, not scoped, no check module changed after the run;
   `n_reserved` set per cell (section 5.6).
6. Grant. `Cell.granted` (section 2.1) decides; the independence rule
   (`CALIBRATION_MIN_GROUPS = 10`) was added after the run because
   `mt4_statement`'s 65 calibration files come from 8 accounts (47 from one,
   8 from another): "20 real files" is read as 20 files that are not
   re-exports of one account. This keeps the design's D6 (account-statement
   checks stay `INFO` in v1) without a family-specific exception. Without the
   rule 21 cells would have been granted; with it, 14.
7. Gate. The `--all` run and
   `FORENSICS_CORPUS_MANIFEST=… FORENSICS_CORPUS_DIR=… python -m pytest tests/forensics_corpus.py`
   show no `SIGNAL` on any of the 197 files.
8. Pins. `thresholds.py` and `calibration.py` are pinned as literal SHA-256
   strings under `forensics-1` (section 2.3). The previous pin computed both
   sides at runtime and could never fail; it is now literal.

Clopper-Pearson: the two-sided 95 % upper bound of the false-signal rate,
`BetaInv(0.975, x + 1, n − x)`, exactly `1 − 0.025^(1/n)` for `x = 0`
(`calibration.clopper_pearson_upper_pct`): 0/5 → 52.2 %, 0/13 → 24.7 %,
0/20 → 16.8 %, 0/26 → 13.2 %, 0/39 → 9.0 %, 0/65 → 5.5 %.

The page's calibration line prints `n` (calibration files), `groups` (accounts
or strategies among them), `unexplained` (hits without an explanation, reserved
hits included) and the bound computed on `min(n, groups)`: the binomial assumes
independent trials and the independent unit is the account or strategy, so 65
MT4 statements from 8 accounts publish 0/8 → 36.9 %, the 20 MQL5 signal files
from 16 strategies 0/16 → 20.6 %, and the MT5 tester cells (one file per
strategy) keep 0/26 → 13.2 %. Counting reserved hits in `unexplained` while
`n` counts calibration files only is conservative (1/11 → 41.3 % rather than
1/13 → 36.0 %) and is kept so. These are in-sample bounds: the page says, in
the three languages, that the accounts were used to tune the method and that
the false-signal rate could be as high as the bound (math review, 2026-09-26).

### 5.2 Honesty note

During development the author of each check module smoke-ran the module over
the whole corpus, calibration and reserved files alike, and derived scoping
rules from what they saw (the modules' docstrings record them). The reserved
third is therefore not blind to the module authors. It is blind to the final
calibration pass, the only pass whose numbers are written into
`calibration.py`: nothing in that pass changed after the reserved run was
produced. The one reserved hit shows the earlier smoke runs did not remove
every discrepancy, which is some evidence that the modules were not tuned
file by file; still, the bounds below are bounds on files already seen by
the authors, not on unseen files. They are false-signal rates on real files,
never detection rates; 0 of 39 still leaves 9.0 %.

The one blind figure: across the reserved third, 1 of 40 files produced a hit
on a `SIGNAL_CAPABLE` check (the reader defect of section 5.6): 1/40, 95 %
upper bound 13.2 %. It is the only out-of-sample evidence and belongs next
to the in-sample bounds above.

### 5.3 Results: `SIGNAL_CAPABLE` check × family

`n` = calibration files measured, `g` = groups, `r` = reserved files,
`hits` = hits in run 1 (scoped / unexplained), `res` = reserved hits, cp95 =
upper bound on calibration files only and on calibration + reserved,
`granted` per the live table (`unexplained` counts reserved hits).

| check | family | n | g | r | hits run 1 | res | cp95 n | cp95 n+r | granted |
|---|---|---|---|---|---|---|---|---|---|
| TOTALS_VS_ROWS | mt4_statement | 65 | 8 | 4 | 0 (0/0) | 0 | 5.5 % | 5.2 % | no (g < 10) |
| TOTALS_VS_ROWS | mt4_tester | 15 | 15 | 7 | 0 | 0 | 21.8 % | 15.4 % | no |
| TOTALS_VS_ROWS | mt5_history | 10 | 6 | 1 | 0 | 0 | 30.8 % | 28.5 % | no |
| TOTALS_VS_ROWS | mt5_tester | 26 | 26 | 13 | 0 | 0 | 13.2 % | 9.0 % | yes |
| SUMMARY_IDENTITIES | mt4_statement | 65 | 8 | 4 | 0 | 0 | 5.5 % | 5.2 % | no (g < 10) |
| SUMMARY_IDENTITIES | mt4_tester | 15 | 15 | 7 | 0 | 0 | 21.8 % | 15.4 % | no |
| SUMMARY_IDENTITIES | mt5_history | 11 | 6 | 2 | 0 | 0 | 28.5 % | 24.7 % | no |
| SUMMARY_IDENTITIES | mt5_tester | 26 | 26 | 13 | 0 | 0 | 13.2 % | 9.0 % | yes |
| BALANCE_CHAIN | mt4_tester | 15 | 15 | 7 | 0 | 0 | 21.8 % | 15.4 % | no |
| BALANCE_CHAIN | mt5_history | 11 | 6 | 2 | 0 | 1 | 41.3 % (1/11) | 36.0 % (1/13) | no |
| BALANCE_CHAIN | mt5_tester | 26 | 26 | 13 | 0 | 0 | 13.2 % | 9.0 % | yes |
| DEAL_SEQUENCE | mt5_history | 11 | 6 | 2 | 0 | 0 | 28.5 % | 24.7 % | no |
| DEAL_SEQUENCE | mt5_tester | 26 | 26 | 13 | 0 | 0 | 13.2 % | 9.0 % | yes |
| TESTER_NUMBERING | mt4_tester | 15 | 15 | 7 | 0 | 0 | 21.8 % | 15.4 % | no |
| TESTER_NUMBERING | mt5_tester | 26 | 26 | 13 | 0 | 0 | 13.2 % | 9.0 % | yes |
| DUPLICATE_TICKET | mt4_statement | 65 | 8 | 5 | 0 | 0 | 5.5 % | 5.1 % | no (g < 10) |
| DUPLICATE_TICKET | mt5_history | 11 | 6 | 2 | 0 | 0 | 28.5 % | 24.7 % | no |
| DUPLICATE_TICKET | mt5_tester | 26 | 26 | 13 | 0 | 0 | 13.2 % | 9.0 % | yes |
| DUPLICATE_TICKET | myfxbook | 13 | 9 | 3 | 0 | 0 | 24.7 % | 20.6 % | no |
| CROSS_COPIES | mt5_history | 8 | 4 | 1 | 0 | 0 | 36.9 % | 33.6 % | no |
| SLTP_FILL | mt4_statement | 14 | 6 | 1 | 0 | 0 | 23.2 % | 21.8 % | no |
| SLTP_FILL | mt5_history | 7 | 3 | 2 | 0 | 0 | 41.0 % | 33.6 % | no |
| SLTP_FILL | mt5_tester | 23 | 23 | 12 | 0 | 0 | 14.8 % | 10.0 % | yes |
| PNL_SIGN | fxblue | 5 | 2 | 0 | 0 | 0 | 52.2 % | 52.2 % | no |
| PNL_SIGN | mql5_signal | 20 | 16 | 8 | 0 | 0 | 16.8 % | 12.3 % | yes |
| PNL_SIGN | mt4_statement | 65 | 8 | 5 | 0 | 0 | 5.5 % | 5.1 % | no (g < 10) |
| PNL_SIGN | mt5_history | 8 | 4 | 1 | 0 | 0 | 36.9 % | 33.6 % | no |
| PNL_SIGN | myfxbook | 15 | 11 | 5 | 0 | 0 | 21.8 % | 16.8 % | no |
| PRICE_PRECISION | mt4_statement | 65 | 8 | 5 | 0 | 0 | 5.5 % | 5.1 % | no (g < 10) |
| PRICE_PRECISION | mt4_tester | 15 | 15 | 7 | 0 | 0 | 21.8 % | 15.4 % | no |
| PRICE_PRECISION | mt5_history | 10 | 6 | 0 | 0 | 0 | 30.8 % | 30.8 % | no |
| PRICE_PRECISION | mt5_tester | 23 | 23 | 12 | 0 | 0 | 14.8 % | 10.0 % | yes |
| TIME_SANITY | fxblue | 5 | 2 | 0 | 0 | 0 | 52.2 % | 52.2 % | no |
| TIME_SANITY | mql5_signal | 20 | 16 | 8 | 0 | 0 | 16.8 % | 12.3 % | yes |
| TIME_SANITY | mt4_statement | 65 | 8 | 5 | 0 | 0 | 5.5 % | 5.1 % | no (g < 10) |
| TIME_SANITY | mt4_tester | 15 | 15 | 7 | 0 | 0 | 21.8 % | 15.4 % | no |
| TIME_SANITY | mt5_history | 11 | 6 | 2 | 0 | 0 | 28.5 % | 24.7 % | no |
| TIME_SANITY | mt5_tester | 26 | 26 | 13 | 0 | 0 | 13.2 % | 9.0 % | yes |
| TIME_SANITY | myfxbook | 15 | 11 | 5 | 0 | 0 | 21.8 % | 16.8 % | no |
| ROW_ORDER | fxblue | 5 | 2 | 0 | 0 | 0 | 52.2 % | 52.2 % | no |
| ROW_ORDER | mql5_signal | 20 | 16 | 8 | 0 | 0 | 16.8 % | 12.3 % | yes |
| ROW_ORDER | mt4_statement | 65 | 8 | 5 | 2 (2/0) | 0 | 5.5 % | 5.1 % | no (g < 10) |
| ROW_ORDER | mt4_tester | 15 | 15 | 7 | 0 | 0 | 21.8 % | 15.4 % | no |
| ROW_ORDER | mt5_history | 11 | 6 | 2 | 0 | 0 | 28.5 % | 24.7 % | no |
| ROW_ORDER | mt5_tester | 26 | 26 | 13 | 0 | 0 | 13.2 % | 9.0 % | yes |
| ROW_ORDER | myfxbook | 15 | 11 | 5 | 0 | 0 | 21.8 % | 16.8 % | no |
| MARKET_HOURS | fxblue | 5 | 2 | 0 | 0 | 0 | 52.2 % | 52.2 % | no |
| MARKET_HOURS | mql5_signal | 7 | 6 | 4 | 0 | 0 | 41.0 % | 28.5 % | no |
| MARKET_HOURS | mt4_statement | 16 | 6 | 3 | 0 | 0 | 20.6 % | 17.6 % | no |
| MARKET_HOURS | mt4_tester | 14 | 14 | 6 | 0 | 0 | 23.2 % | 16.8 % | no |
| MARKET_HOURS | mt5_history | 2 | 2 | 1 | 0 | 0 | 84.2 % | 70.8 % | no |
| MARKET_HOURS | mt5_tester | 10 | 10 | 6 | 0 | 0 | 30.8 % | 20.6 % | no |
| MARKET_HOURS | myfxbook | 13 | 9 | 5 | 0 | 0 | 24.7 % | 18.5 % | no |
| HIDDEN_CONTENT | mt5_history | 10 | 6 | 0 | 0 | 0 | 30.8 % | 30.8 % | no |
| HIDDEN_CONTENT | mt5_tester | 23 | 23 | 12 | 0 | 0 | 14.8 % | 10.0 % | yes |

Descriptive checks, INFO counts on calibration files (every other cell 0):
`FILE_TRACE × mt4_tester` 3 of 15 (section 4.1); `TICKET_ORDER ×
mt4_statement` 2 of 65 (the two user-sorted files of section 4.16, 1 hit
each, `inversions_close_time` 9 and 5, `max_backwards_seconds` 263700).
Reserved: 0 everywhere. `PRICE_IMPLIED_PNL × mt4_statement` measured 17
files, 0 INFO; `VOLUME_IN_OUT` 11 + 26 files, 0 INFO.

### 5.4 Granted cells (14)

`mt5_tester`: `TOTALS_VS_ROWS`, `SUMMARY_IDENTITIES`, `BALANCE_CHAIN`,
`DEAL_SEQUENCE`, `TESTER_NUMBERING`, `DUPLICATE_TICKET`, `TIME_SANITY`,
`ROW_ORDER` (n = 26 files, 26 strategies, 13 reserved) and `SLTP_FILL`,
`PRICE_PRECISION`, `HIDDEN_CONTENT` (n = 23 HTML files, 23 strategies, 12
reserved: the XLSX testers lost their printed digits and hidden cells).
`mql5_signal`: `PNL_SIGN`, `TIME_SANITY`, `ROW_ORDER` (n = 20, 16 groups, 8
reserved). `tests/test_forensics_review.py::test_the_shipped_calibration_table_is_frozen_and_consistent`
lists these 14 and asserts the grant rule cell by cell.

Not granted, and why: every `mt4_statement` cell (65 files but 8 accounts);
`mt4_tester` (15 calibration files; `Cell.granted` counts calibration files
only, so 15 + 7 reserved does not reach 20, a conservative reading of the
design's "n_total"); `mt5_history` (at most 11, and `BALANCE_CHAIN` with
`unexplained = 1`); `myfxbook` (at most 15); `fxblue` (5); every
`MARKET_HOURS` cell (at most 16), `CROSS_COPIES` (8), non-tester `SLTP_FILL`
(14, 7) and `TICKET_LINKS` (0).

### 5.5 Limits

- Groups. Only `mt5_tester` and `mt4_tester` have one group per file. A bound
  on `mt4_statement` counts files and overstates the evidence for that
  family (8 + 3 accounts); `myfxbook` is 15 files from 11 groups,
  `mql5_signal` 20 from 16, `mt5_history` 11 from 6.
- Families under 20 files in every cell are never granted: `mt4_tester`,
  `mt5_history`, `myfxbook`, `fxblue`. Formats with no real file
  (`tradingview` CSV and XLSX, `ninjatrader`, `monthly`, `other`) have no
  cell: every check answers `INFO` at most on them.
- XLSX: the 3 `mt5_history_xlsx` and 4 `mt5_tester_xlsx` files sit inside
  their HTML families (D4); precision checks skip them, so the
  `PRICE_PRECISION`, `HIDDEN_CONTENT` and `SLTP_FILL` cells of `mt5_tester`
  count 23 + 12 HTML files.
- Entries, not bytes. The split works on manifest entries grouped by
  account or strategy; 5 of the 40 reserved entries carry bytes that also
  sit in the calibration third under another entry (the same file reached
  through two URLs, one standalone and one in a group: mql5_signal 3,
  mt5_history 1, myfxbook 1). Only 35 of the reserved third's 40 distinct
  files are absent from the calibration third, and the corpus holds 179
  distinct files among its 197 entries; the bounds of section 5.3 count
  entries as the runner does.
- The single scoping rule was derived from one account (two exports). Its
  conditions are strict, so a statement sorted by a column whose ties are not
  in ticket order, or by a text column, still reports hits; the reserved
  third (5 MT4 statements, 3 accounts) produced no such case.
- All 55 cells carry `frozen = FREEZE_DATE`, granted or not (the design set
  `frozen` on granted cells only); `granted` still needs the file, group and
  unexplained conditions, so the difference changes no status, only the
  calibration line shown for an ungranted cell.
- The bounds are false-signal rates on real files already seen by the module
  authors (section 5.2), never detection rates.

### 5.6 The reserved hit

`BALANCE_CHAIN × mt5_history`, on one of the two reserved files of that
family (an XLSX export, `mt5_history_xlsx`; the file is not named here so
that no hit is tied to a file, an author or a link):
`n_rows 122`, `n_hits 55`, `first_break_row 216` (the first trade deal after
the deposit), `largest_gap 15598.97`, `initial_balance_implied 15000`,
`restarts 0`, `hidden_cost_rows 0`; `VOLUME_IN_OUT` 0 hits; `TOTALS_VS_ROWS`
`CLEAN` with `importer_balance_breaks 0`. Row shape: Positions 60, Orders
144, Deals 122 rows of 15 cells with the last cell always blank and no header
attached to the deal rows; margin mode hedge.

Per the protocol the frozen table keeps `unexplained = 1` on that cell (it
was not granted in any case: n = 11) and no check module was changed after
the reserved run. Traced afterwards, the hit is a row-reader defect, not the
file: `rows.mt5_columns` trimmed trailing blank cells and, on the 40 deals
whose comment is empty, fell to the 13-column tester map (profit at 10,
balance at 11); with the 14-column map (fee at 9, profit at 11, balance at
12) the chain closes on 121 of 121 steps, as the importer's own balance check
already said. The fix (`RawTable.layout_widths`: the widest trimmed deal row
of the section decides the layout, commit `8f115ca`) makes the file `CLEAN`
(`n_rows 122`, `n_hits 0`). It is a code change after the freeze: the next
`METHOD_VERSION` re-runs the whole procedure with it in place, and until
then a client's header-less MT5 XLSX history with the same shape is read
correctly by the code but the cell stays `INFO` (n = 11) whatever it finds.

### 5.7 Test, lint and type status (2026-09-26)

`python -m pytest tests/test_forensics_*.py tests/test_forgery_lab.py -q`:
607 passed (9.1 s). `tests/forensics_corpus.py` is skipped without the two
environment variables and passed with them (1 passed, about 65 s). `ruff
check` and `ruff format --check` on the package and its tests, and `mypy
src/quant_trade/audit/forensics`, are clean per the calibration and lab
reports.

## 6. Seeded alterations (forgery lab)

`tests/forgery_lab.py` (library and CLI) applies one hand edit ("seed") to
a file and asks which check finds it; `tests/test_forgery_lab.py` (13 tests)
asserts the fixture matrix. HTML families are edited through
`forensics/edit.py` row blocks (the file's own bytes and codec), delimited
families by rewriting one physical line, the monthly seed on a DataFrame. A
check "finds" a seed when, between the original and the altered bytes, its
status moves from `CLEAN` / `NOT_MEASURED` to `INFO` / `SIGNAL` or its
`n_hits` rises; whether it says `INFO` or `SIGNAL` is the calibration
table's business, not the file's. The battery is fed as the service feeds it
(importer warnings and currency when the import succeeds, none when it
refuses). An identity edit (rewriting a row with itself) is found by nothing
on every fixture, as a control. Outputs hold counts, check ids, manifest
paths, SHA-256 prefixes and figures only.

### 6.1 The 26 seeds

| seed | edit | expected finder (main families) |
|---|---|---|
| `delete_losing_row` | the closed row with the largest loss removed | `TOTALS_VS_ROWS`; MT5: `BALANCE_CHAIN` (+ `CROSS_COPIES` on histories); MT4 tester: + `TESTER_NUMBERING` |
| `profit_plus_cent` | the largest result moved by +0.01 | none (documented limit); TradingView `TV_INVARIANTS` |
| `profit_plus_unit` | the largest result moved by +1.00 | `TOTALS_VS_ROWS`; MT5 / MT4 tester `BALANCE_CHAIN`; MT4 statement + `PRICE_IMPLIED_PNL` |
| `profit_sign_flip` | the largest loss written as a win of the same size | `PNL_SIGN`; MT5 / testers `BALANCE_CHAIN`, `TOTALS_VS_ROWS` |
| `close_price_mirror` | the close price reflected around the open (same digits) | `PNL_SIGN`; MT5 history + `CROSS_COPIES`; MT4 tester: none |
| `sltp_fill_violation` | a `[tp]` fill moved ten ticks past its level (MT5 tester: or `[sl]` nearer) | `SLTP_FILL` |
| `close_price_dropped_zero` | one close price with a trailing zero dropped | `PRICE_PRECISION` |
| `duplicate_new_ticket` | the winning row with the lowest ticket copied under ticket max+1 | `TOTALS_VS_ROWS` / `TICKET_ORDER` (MT4, Myfxbook, FX Blue); MT5: `BALANCE_CHAIN`, `DEAL_SEQUENCE`, `ROW_ORDER`, … |
| `duplicate_same_ticket` | the same row copied verbatim after itself | `DUPLICATE_TICKET` (+ chain and totals checks) |
| `drop_withdrawal`, `drop_deposit` | the last withdrawal / deposit row removed (MT5: one with deals on both sides) | MT5: `BALANCE_CHAIN`; MT4 statement and CSV: none (limit) |
| `summary_total_edit` | the declared net result moved by +100.00 | `TOTALS_VS_ROWS`, `SUMMARY_IDENTITIES` |
| `header_date_backwards` | the report's own date set one day before the first closed row | `TIME_SANITY` |
| `hide_row_class` | every cell of the largest losing row given `class=hidden` | `HIDDEN_CONTENT` (MT5); MT4: `TOTALS_VS_ROWS` (+ `TESTER_NUMBERING`, `BALANCE_CHAIN` on the tester) |
| `hide_row_style` | the same row given `style=display:none` | none (the reader ignores styles; control) |
| `fill_hidden_text`, `fill_hidden_number` | a hidden cell filled with text / a deal's hidden Cost filled with 5.00 | `HIDDEN_CONTENT` / `BALANCE_CHAIN` |
| `move_to_open` | the largest losing trade re-listed under Open Trades | `TOTALS_VS_ROWS` |
| `swap_adjacent_rows` | two adjacent closed rows exchanged | `ROW_ORDER` (+ `DEAL_SEQUENCE`, `BALANCE_CHAIN`, `TESTER_NUMBERING` on MT5 / testers) |
| `symbol_change_row` | one row's symbol replaced by another of the file printed with other digits | `PRICE_PRECISION` (MT5 history + `CROSS_COPIES`); CSV: none |
| `deal_number_change` | the first trade deal's number replaced by max+1 | `DEAL_SEQUENCE` (+ `TESTER_NUMBERING` on the tester) |
| `order_number_change` | an order's number replaced by max+1 | `TESTER_NUMBERING` (tester); history: `CROSS_COPIES` (see 6.3) |
| `close_time_weekend` | a listed pair's close time moved to the next Saturday 15:00 | `MARKET_HOURS` |
| `close_time_within_hours` | a close time moved one minute later, order kept | none (limit); MT5 history `CROSS_COPIES` |
| `close_time_after_report` | a close time moved two days past the report's date | `TIME_SANITY` |
| `monthly_value` | one month of a factsheet grid raised by one point | `MONTHLY_DIGITS` |

Two seeds beyond the design's list (`close_price_dropped_zero`,
`hide_row_style`) and the hidden-cell seed split in text / number were added
by the lab; three synthetic inline samples (Myfxbook, MQL5 signal, FX Blue;
no account, name or broker) stand in for the fixtures the repository lacks.

### 6.2 Detection on the fixtures

7 repository fixtures + 3 inline samples + the monthly grid, 26 seeds: 124
applied (seed, file) pairs; 90 found by an expected check; 34 under a
documented limit (empty expectation: +0.01 everywhere but TradingView,
`display:none` rows, CSV families without an account currency, MT4 cash-row
removal, the MT4 tester mirror, `close_time_within_hours` outside the MT5
history); 0 misses with an expectation. A hard assertion in the tests; the
run is 1.5 s and byte-identical across two runs.

### 6.3 Detection on the corpus

`--all`: 197 files, 189 run, 8 skipped over 2 MB (6 `mt4_tester_html`, 2
`mt4_statement_html`), 0 errors, 760 s. Over every (seed, family) cell with
an expected check: applicable 1909, found 1882, missed 27, rate 0.986 (a
plain ratio, no interval); 764 further applications under documented limits
(0 found, as documented; unexpected finders logged); counting those too,
1882 of 2673 applications were found (70.4 %), and both figures belong
together: of the edits the method is built to see it found 98.6 %, of all
the edits tried, 70 %. The seeds are a designed set, not a sample of real
forgeries, so the ratios carry no interval; they count one edit at a time,
on public files, HTML and delimited text only. Every (seed × family)
cell is 1.000 except:

| seed × family | found | why the misses |
|---|---|---|
| `close_time_within_hours × mt5_history` | 8/10 | two netting accounts: `CROSS_COPIES` is `netting_or_unknown_margin_mode`, no copy to compare |
| `delete_losing_row × mt4_statement` | 64/65 | one statement without a summary block (`no_declared_totals`): nothing to disagree with the rows |
| `hide_row_class × mt4_statement` | 64/65 | the same file |
| `profit_plus_unit × mt4_statement` | 64/66 | that file, and a 331-row statement where the importer's tolerance (0.011 per row = 3.64) swallows +1.00 |
| `swap_adjacent_rows × mt4_statement` | 62/63 | a four-row table: after the swap a printed numeric column is monotone and the sorted-column fallback of section 4.16 accepts it |
| `duplicate_new_ticket`, `duplicate_same_ticket × fxblue` | 0/5 each | all five FX Blue files list two accounts: `TICKET_ORDER` and `DUPLICATE_TICKET` decline them (`several_accounts`) |
| `order_number_change × mt5_history` | 0/10 | a renumbered order becomes `orders_unresolved`, never a hit (two files netting) |

Zero-applicable cells: `drop_deposit` / `drop_withdrawal` on the MT5
families (every cash row of the corpus is the first deal or the last row),
`fill_hidden_number` on both MT5 families and `fill_hidden_text` on
`mt5_tester` (no corpus deal row carries a hidden cell; the histories'
hidden cells sit on Positions rows, which `fill_hidden_text` uses: 8 of 8
found). `symbol_change_row` applies to 3 MT4 statements only (it needs a
second symbol with other digits and a row strictly inside that symbol's
rows; at an end `PRICE_PRECISION` reads the change as a migration). XLSX
files are `not_editable` (the editor works on HTML only).

What the design's §7.2 table got wrong, measured: `TICKET_LINKS` and
`CROSS_COPIES` never count an unresolved reference as a hit, so a deletion or
renumbering is invisible to them; `TESTER_NUMBERING` on the MT5 tester
ignores gaps (D18); `PRICE_IMPLIED_PNL` needs the account currency, which
Myfxbook, MQL5 and FX Blue exports lack; MT4 statement cash rows are compared
with nothing (58 deposit and 4 withdrawal removals, 0 found; the importer
refuses only when the balance reaches zero); +0.01 is inside
`MONEY_TOLERANCE` everywhere except TradingView's `pair_values`, and the
totals tolerance scales with row count; `ROW_ORDER` on MT4 statements takes
the best of three keys plus the column fallback, and ties make swaps
invisible; `MARKET_HOURS` on the MT4 tester judges fills only;
`HIDDEN_CONTENT` honours the `hidden` class only; `PNL_SIGN` never runs on
testers and needs a commission column on TradingView; `VOLUME_IN_OUT` fires
on every MT5 duplicate. Unexpected finders seen and logged: `CROSS_COPIES` on
most MT5 history edits, `ROW_ORDER` on time moves, `SLTP_FILL` on 6 mirrored
MT4 closes (the mirrored price crosses the row's own level), `FILE_TRACE`
on one MT4 tester edit, `PRICE_IMPLIED_PNL` on 8 MT4 stop violations.

### 6.4 Finding for the owners of `edit.py` / `rows.py`

On the two row-misaligned statements of section 3.2 an `edit.set_cell` /
`delete_row` by row index lands on a different row than the one `rows.load`
numbers; the lab refuses every HTML edit on such a file
(`not_applicable:rows_misaligned`) instead of editing the wrong row. Not
fixed by the lab.

### 6.5 The forger's moves the method does not catch (public limit)

The lab applies one edit and asks whether one invariant breaks. A file whose
visible figures agree with each other passes every check, and no
calibration changes that:

1. Re-summed totals: delete or change a row and rewrite every summary label
   (MT4 statement and MT4 tester are found through the summary only).
2. Re-chained balances: the same edit plus a rewrite of every later Balance
   cell (and the Positions / Orders copies of a history).
3. Regenerated files: a history exported from a terminal whose trades were
   fabricated upstream (a demo account, a copied signal, a tester run on
   invented inputs) is consistent by construction. The battery measures the
   file, not the account, and nothing proves the broker issued the file.
4. Edits inside the money tolerance (+0.01 on one profit): the tolerance
   exists for the platforms' own rounding and cannot be tightened without
   hits on real files.
5. A row hidden by inline style or a CSS class other than `hidden`: read like
   any other row; the report shows its figures.
6. End-of-table deletions and the first deposit on the MT5 families; on
   TradingView the last trade's cumulative is excluded; on NinjaTrader the
   last cumulative is the running sum of what remains.
7. MT4 statement cash rows: removing a Deposit or Withdrawal row is compared
   with nothing (the footer sums and the `Deposit/Withdrawal` label are
   requested from the importer's owner, D11).
8. Delimited exports without an account currency (Myfxbook, MQL5 signal, FX
   Blue): a rewritten profit, symbol or price is found only when it flips
   the sign of the result or the order of the tickets; a deleted row is found
   by nothing (no total, no running balance).
9. Ticket-preserving deletions: `TICKET_LINKS` never counts an unresolved
   reference; the MT5 tester's numbering ignores gaps.
10. Time edits that keep the order (a close time moved a few minutes, open
    times, comments, magic numbers, S/L and T/P levels no fill refers to).
11. Consistent price edits: a close price rewritten together with the profit
    it implies (and the Positions copy on a history) stays inside the
    two-thirds fit rule.
12. Another file type: screenshots, PDFs and hand-retyped spreadsheets carry
    none of the terminal's hidden cells, links or copies; the audit reports
    those formats with fewer measured checks.
13. XLSX files were never edited (`not_editable`): there is no detection
    figure for the XLSX variants of the MT5 families.
14. The 8 corpus files over 2 MB were skipped by the lab.
15. TradingView, NinjaTrader and monthly grids were seeded on synthetic
    fixtures only (no public file of those families in the corpus).
16. Editing more than a third of one symbol's rows makes `PRICE_IMPLIED_PNL`
    answer `symbols_no_fit`: nothing is flagged.
17. The totals tolerance grows as 0.011 × rows, so an edit smaller than that
    passes (+1.00, or +3.64, on a 331-row statement).

Also outside the method: excluding another account (the battery does not
see other accounts); a statement exported for a chosen period (only the
continuity comparison across uploads, `track_seal.py`, sees it); digit
distribution tests (Benford, last digit) are not used as signal material
(D17: with five-digit forex at whole lots every profit is a whole dollar).

## 7. Wording contract (design §8)

Sentences will live in the web layer's copy for `es`, `en` and `pt` with
equal key sets, keyed by `(check_id, status)` plus one sentence per
`NOT_MEASURED` reason code, formatted only from figures; every rendered
sentence must pass `guard.find_claims` in the three languages, and a
wording test will render every template with extreme figures. *Planned*:
`forensics_web.py` holds no copy yet (section 8); the sentences below are
the contract the page must meet, checked against the guard on 2026-09-26.

Pattern for `SIGNAL`: the measured fact, then the fixed tail.

| | Spanish (default) | English | Portuguese |
|---|---|---|---|
| `SIGNAL` (example: `BALANCE_CHAIN`) | En {n_hits} de {n_rows} filas el saldo impreso no es el saldo anterior más el resultado de la fila (primera: fila {first_break_row}). Puede tener explicaciones legítimas; conviene aclararlo con quien generó el archivo. | In {n_hits} of {n_rows} rows the printed balance is not the previous balance plus the row's result (first: row {first_break_row}). It may have legitimate explanations; it is worth clarifying with whoever generated the file. | Em {n_hits} de {n_rows} linhas o saldo impresso não é o saldo anterior mais o resultado da linha (primeira: linha {first_break_row}). Pode ter explicações legítimas; convém esclarecer com quem gerou o arquivo. |
| `INFO` (uncalibrated cell): the measured fact, then | Este chequeo aún no está calibrado con suficientes archivos reales de este formato (n = {n}); no cuenta como señal. | This check is not yet calibrated on enough real files of this format (n = {n}); it does not count as a signal. | Esta verificação ainda não está calibrada com arquivos reais suficientes deste formato (n = {n}); não conta como sinal. |
| `INFO` (descriptive check) | Es una cifra descriptiva; no cuenta como señal. | It is a descriptive figure; it does not count as a signal. | É um número descritivo; não conta como sinal. |
| `CLEAN`, per check | Sin huellas en este chequeo. | No traces in this check. | Sem vestígios nesta verificação. |
| No signal or info at all | No encontramos las huellas que revisamos; eso no prueba que el archivo sea original. | We did not find the traces we look for; that does not prove the file is original. | Não encontramos os vestígios que revisamos; isso não prova que o arquivo seja original. |
| Always present, every page | El método es público: detecta ediciones descuidadas, no a quien lo estudie. | The method is public: it detects careless edits, not someone who has studied it. | O método é público: detecta edições descuidadas, não quem o estude. |
| `NOT_MEASURED` (example: `no_listed_symbol`) | No se pudo medir: los símbolos del archivo no están en la lista de horarios conocidos. | Could not be measured: the file's symbols are not in the list of known market hours. | Não foi possível medir: os símbolos do arquivo não estão na lista de horários conhecidos. |
| Calibration line, per check | {n} archivos reales de este formato; señales sin explicar: {unexplained}; cota superior 95 %: {cp95_upper_pct} %. | {n} real files of this format; unexplained signals: {unexplained}; 95 % upper bound: {cp95_upper_pct} %. | {n} arquivos reais deste formato; sinais sem explicação: {unexplained}; limite superior de 95 %: {cp95_upper_pct} %. |
| Continuity (`track_seal`, same page) | Esta carga no coincide con la anterior en {count} operaciones; puede ser un ajuste del bróker o una edición. | This upload does not match the previous one in {count} operations; it may be a broker adjustment or an edit. | Este envio não coincide com o anterior em {count} operações; pode ser um ajuste da corretora ou uma edição. |

Every page also shows `METHOD_VERSION`. Raw reason codes and check ids
appear only in a details block, never as a headline.

Forbidden anywhere on the page, tested with word boundaries over every text
in the three languages: limpio, auténtico, genuino, verificado, falso,
manipulado, inalterable, "sello" on screen, "para siempre", "demuestra";
"real" as a predicate of the history or the file ("es real", "historial
real", "archivo real"; "archivos reales" for the corpus and the existing
notices' "dinero real" are allowed by exact phrase); imperatives (detén,
pausa, copia, invierte, compra, vende); and their English and Portuguese
twins (clean, authentic, genuine as a verdict, verified, fake, manipulated,
tamper-proof, "proves", …). "Detects fraud" is never written: the battery
detects careless edits. `guard.find_claims` (profit, endorsement and
pass-the-challenge language) applies on top.

Where the page will live (*planned*, PR B): a private page for the owner of
the report, token or session, paid check server-side, under the same slot
and attempt limits the panel already uses; the result cached in process only
(an LRU of 256 entries keyed by audit id, method version and the report
bytes' SHA-256); no new table, so retention, export and purge are untouched.
Everything rendered from figures goes through `pages._e`; figures are ints,
ISO dates and codes, so nothing from the file reaches the HTML.

## 8. Hooks and launch switches

- `forensics_web.FORENSICS_ENABLED = False` (`src/quant_trade/audit/forensics_web.py`).
  A constant, not a Railway variable: the page ships hidden and is turned on
  by a change in the repository after its reviews. `web.create_app` calls
  `forensics_web.register(app, **hooks)` once with the app's own closures
  (report loading, sessions, cross-site check, signed-in actions, the
  panel's attempt log, settings, store, slots), so no security logic is
  copied; while the switch is off `register` returns `False`, nothing is
  mounted and every path answers 404. `tests/test_audit_store_hooks.py`
  asserts the switch is off.
- `track_seal.py` and `track_seal_pages.py` (the continuity method of the
  design's §6) share `forensics.rows`, `edit`, `families`, `header`, `money`
  and `METHOD_VERSION`; they are outside this document.

Owner-side items pending, listed plainly:

| owner | item | where |
|---|---|---|
| VALUE | a link to the file-consistency page from the rendered report, and its Portuguese twin | `report.render` (`report.py`) and `report_pt.py` |
| ACCOUNTS | a link from the account's report page | `web._report_html` (`web.py`) |
| ANY PLATFORM | a public read-only row function `importers.raw_rows(data, filename)` returning the table reader's rows with cells, hidden flags and attributes (HTML and MT5 workbooks) or `(header, rows, delimiter)` for delimited files, after `unwrap` and the same caps; `rows.py` then shrinks to a re-export plus the section and kind classification | `importers.py` (design §4.4) |
| ANY PLATFORM | fold into the importer's own comparisons: the unlabeled totals row of MT4 statements and MT5 Deals, MT4 `Deposit/Withdrawal:` against the balance rows, MT5 history `Balance:` against the last deal's balance; until then these are not measured anywhere (D11) | `importers.py` |
| forensics | bump `METHOD_VERSION`, re-run sections 5.1 steps 3 to 7 with the `layout_widths` fix in place, re-pin | `review.py`, `calibration.py` |
| edit / rows | the two row-misaligned MT4 statements (section 3.2) | `edit.py`, `rows.py` |
| MATH | review of section 5 before any granted cell reaches a client (design §5, §9 step 4) | this document |

## Appendix A. The corpus

The 197 manifest entries with `genuine=true`, as run on 2026-09-26; every
count in this document counts entries as the manifest and the runner do.
Columns: the row number; the family and `source_format`; the third the
split assigned (`calibration` or `reserved`); the group (an account or
strategy exported more than once, `-` when the entry stands alone); the
SHA-256 of the bytes; the public URL it was downloaded from. Some entries
share their SHA-256 with another entry (the same bytes reached through two
URLs, once listed alone and once under a group; the count is given after the
table). Nothing else from the files is listed: no account number, name,
broker, comment or cell.

| # | family | format | third | group | SHA-256 | source |
|---|---|---|---|---|---|---|
| 1 | fxblue | fxblue_csv | calibration | - | `38afc32081795f7cfd6ce997929f3e5e8a5380ea916539588ba43967212f8b6e` | https://raw.githubusercontent.com/andrewbitlab/deusquant-site/HEAD/data/forward/_orders-deusfund-sqx1-13.csv |
| 2 | fxblue | fxblue_csv | calibration | fxblue_deusfund_forward | `04bb43819373a93f7093258409e110fd1bb723e130a4b223d25a2b404d2e4c41` | https://raw.githubusercontent.com/andrewbitlab/deusquant-site/7e6940d292cc40fc44f8d766991cff5768001818/data/forward/orders-deusfund-sqx1-2_17-10-2025.csv |
| 3 | fxblue | fxblue_csv | calibration | fxblue_deusfund_forward | `38afc32081795f7cfd6ce997929f3e5e8a5380ea916539588ba43967212f8b6e` | https://raw.githubusercontent.com/andrewbitlab/deusquant-site/88fc2ea034ab6df8835989797b10d2a08e2515d9/data/forward/orders-deusfund-sqx1-13.csv |
| 4 | fxblue | fxblue_csv | calibration | fxblue_deusfund_forward | `9ef616d754b9192de5cbec6fd6a2b8a7064f3df0144c0265e7a1dfa0cc11148c` | https://raw.githubusercontent.com/andrewbitlab/deusquant-site/8aec9354d0bb1124c0b034201dcfae303ad92daf/data/forward/orders-deusfund-sqx1-13.csv |
| 5 | fxblue | fxblue_csv | calibration | fxblue_deusfund_forward | `bf5e3283fa740df0b1d2eff1133e0c53ba1083df4f2bc6cd7fae1b268f4debaf` | https://raw.githubusercontent.com/andrewbitlab/deusquant-site/81f067d88d88a718571b287df2b87796426905e2/data/forward/orders-deusfund-sqx1-2_8-10-2025.csv |
| 6 | mql5_signal | mql5_signal_csv | calibration | - | `1fe91e964f3dcbba082de9fc9e1d2bf772fa0f2b9758e6695d82e15c632d38f6` | https://raw.githubusercontent.com/ForexFearClinicElite/Signals/HEAD/2265877.positions.csv |
| 7 | mql5_signal | mql5_signal_csv | reserved | - | `33ee00e3a3d27dcc37d36badcf6c41047d44fac050df44868d32a1e742f2a1ee` | https://raw.githubusercontent.com/bmcclanahan/forex/HEAD/notebooks/Part4_Materials/Oanda/strategies/copy_strategies/2049959.history.csv |
| 8 | mql5_signal | mql5_signal_csv | calibration | - | `3615b90ff56a292272614fc4651616981255adfb524ef07369ace3e539d2d1ac` | https://raw.githubusercontent.com/py-pixel-9/my-first-video/HEAD/mt4-ea/2356509.history.csv |
| 9 | mql5_signal | mql5_signal_csv | reserved | - | `3698fad1d1694111162a83f1a54622afde7e9c5410e7a6906c498e904fbed15d` | https://raw.githubusercontent.com/tnickel/MqlKiScanner/HEAD/data/raw/goldwave_2339082_positions.csv |
| 10 | mql5_signal | mql5_signal_csv | calibration | - | `42f739e239e070ff24a3e5d5aefe74d75f1b554348a2a88fcda7eede57df9afc` | https://raw.githubusercontent.com/tnickel/MqlKiScanner/HEAD/data/raw/gold_spike_mt4_2349227_ORDERBOOK.csv |
| 11 | mql5_signal | mql5_signal_csv | calibration | - | `591bf955dac7634fd3de2ea1170dbbed6cfd2cd989df6a03262bfd8c30c47eb0` | https://raw.githubusercontent.com/ASK158/follow_trader/HEAD/src/data/signal-2329290.positions.csv |
| 12 | mql5_signal | mql5_signal_csv | reserved | - | `5b93a94b047c37b91d99f8fa623028ab0bfe1820e543d995b12b333dcfe43b39` | https://raw.githubusercontent.com/tnickel/MqlKiScanner/HEAD/data/raw/gold_reaper_2265877_positions.csv |
| 13 | mql5_signal | mql5_signal_csv | calibration | - | `62fb9b80c6cae441391a386f6d1bb33e0b321ac3c2d4f6a193157e180e595968` | https://raw.githubusercontent.com/ASK158/follow_trader/HEAD/src/data/signal-2339082.positions.csv |
| 14 | mql5_signal | mql5_signal_csv | calibration | - | `6f873b9d09333d579e0e20021d7b6fe786a9aff67cf5054dbd1d753a9d0b1dac` | https://raw.githubusercontent.com/ASK158/follow_trader/HEAD/src/data/signal-2351091.positions.csv |
| 15 | mql5_signal | mql5_signal_csv | reserved | - | `75ef891433660f308bc5fe9f3b06b161500b8833aa40e51b0f6a3a492a40d62f` | https://raw.githubusercontent.com/tnickel/MqlKiScanner/HEAD/data/raw/gold_spike_mt5_2375480_positions.csv |
| 16 | mql5_signal | mql5_signal_csv | calibration | - | `773ec4f075079d46540e0067fb547898f7ce31a8b9a457bf19438db6f58e4970` | https://raw.githubusercontent.com/ASK158/follow_trader/HEAD/src/data/signal-2304847.positions.csv |
| 17 | mql5_signal | mql5_signal_csv | reserved | - | `a39aa19e3ab3006e2c2ad009f1c887988134755eabfc73d85710194e0d042e04` | https://raw.githubusercontent.com/dryousufmesalm/Experts/HEAD/mql5/890367.positions.csv |
| 18 | mql5_signal | mql5_signal_csv | calibration | - | `b144bba803cbd0bcc87e269387a3142a7d05568b6f3a2a601c4b6d1419e3d138` | https://raw.githubusercontent.com/tnickel/MqlKiScanner/HEAD/data/raw/msc_gold_2231030_positions.csv |
| 19 | mql5_signal | mql5_signal_csv | calibration | - | `ba8a2c58233dc1fe3430b6bc3fc53b70cdc8c66ac99b92c411ea03fcb4b18a02` | https://raw.githubusercontent.com/tnickel/MqlKiScanner/HEAD/data/raw/kiracat_2342895_positions.csv |
| 20 | mql5_signal | mql5_signal_csv | reserved | - | `bfa115efc5675dd6ba1085c42cdbf2ef3d0aeef1ead75f4fa2e15873660874d1` | https://raw.githubusercontent.com/tnickel/MqlKiScanner/HEAD/data/raw/puregold_2362868_positions.csv |
| 21 | mql5_signal | mql5_signal_csv | calibration | - | `db4eb3a33b46d17d50b1d070c84018cfa62e887ab21da821c0b9265d371c1952` | https://raw.githubusercontent.com/ASK158/follow_trader/HEAD/src/data/signal-2379208.positions.csv |
| 22 | mql5_signal | mql5_signal_csv | calibration | - | `ec02e3bc5854ec0ab83067990a15d9aeb9d56401565d2325889f4ec54b2dd4ea` | https://raw.githubusercontent.com/ASK158/follow_trader/HEAD/src/data/signal-2265877.positions.csv |
| 23 | mql5_signal | mql5_signal_csv | reserved | - | `ed6bc2a8f3e8bdf9b07c8fef7e4fb0555b359200408ec0503573da0bb0c2060e` | https://raw.githubusercontent.com/akhfzl/TurnkeyId-tech/HEAD/Sell%20and%20Buy.csv |
| 24 | mql5_signal | mql5_signal_csv | calibration | - | `efbcbad3985c65836c58854a571f727a85965d81088331951393931048637585` | https://raw.githubusercontent.com/amirayat/Copyfx-Scraper-Analysis/HEAD/backtrader_samp/890367.positions.csv |
| 25 | mql5_signal | mql5_signal_csv | calibration | - | `f702e87aa4c7011ee41fae30b840be4f90089a6c105a742fe9b479fdb01240c7` | https://raw.githubusercontent.com/tnickel/MqlKiScanner/HEAD/data/raw/goldwhisper_2364821_positions.csv |
| 26 | mql5_signal | mql5_signal_csv | reserved | - | `f838e12cf3bb733b8d2383c676f25d22ebafb8c31206d71b3126401fae0c42cd` | https://raw.githubusercontent.com/coler07/mql5-format/HEAD/2341644.history.csv |
| 27 | mql5_signal | mql5_signal_csv | reserved | mql5_signal_audcross_swing | `a39aa19e3ab3006e2c2ad009f1c887988134755eabfc73d85710194e0d042e04` | https://raw.githubusercontent.com/dryousufmesalm/Experts/46d787809cd0c923dafb6744e50ed3f21aad8a83/mql5/890367.positions.csv |
| 28 | mql5_signal | mql5_signal_csv | calibration | mql5_signal_audcross_swing | `efbcbad3985c65836c58854a571f727a85965d81088331951393931048637585` | https://raw.githubusercontent.com/amirayat/Copyfx-Scraper-Analysis/5e672b3d174ca07d29e179e2a612ced99b6ba55b/backtrader_samp/890367.positions.csv |
| 29 | mql5_signal | mql5_signal_csv | calibration | mql5_signal_goldreaper_xauusd | `1fe91e964f3dcbba082de9fc9e1d2bf772fa0f2b9758e6695d82e15c632d38f6` | https://raw.githubusercontent.com/ForexFearClinicElite/Signals/4fe1536a64592e41ae67abf0de5a8d2035507164/2265877.positions.csv |
| 30 | mql5_signal | mql5_signal_csv | reserved | mql5_signal_goldreaper_xauusd | `5b93a94b047c37b91d99f8fa623028ab0bfe1820e543d995b12b333dcfe43b39` | https://raw.githubusercontent.com/tnickel/MqlKiScanner/675457fd4199b6522ba8f8114c71db130c0ac0bd/data/raw/gold_reaper_2265877_positions.csv |
| 31 | mql5_signal | mql5_signal_csv | calibration | mql5_signal_goldreaper_xauusd | `ec02e3bc5854ec0ab83067990a15d9aeb9d56401565d2325889f4ec54b2dd4ea` | https://raw.githubusercontent.com/ASK158/follow_trader/f6b31fc2a55c8f69ca270d801957881b2996a18e/src/data/signal-2265877.positions.csv |
| 32 | mql5_signal | mql5_signal_csv | reserved | mql5_signal_goldwave_xauusd | `3698fad1d1694111162a83f1a54622afde7e9c5410e7a6906c498e904fbed15d` | https://raw.githubusercontent.com/tnickel/MqlKiScanner/675457fd4199b6522ba8f8114c71db130c0ac0bd/data/raw/goldwave_2339082_positions.csv |
| 33 | mql5_signal | mql5_signal_csv | calibration | mql5_signal_goldwave_xauusd | `62fb9b80c6cae441391a386f6d1bb33e0b321ac3c2d4f6a193157e180e595968` | https://raw.githubusercontent.com/ASK158/follow_trader/f6b31fc2a55c8f69ca270d801957881b2996a18e/src/data/signal-2339082.positions.csv |
| 34 | mt4_statement | mt4_statement_html | calibration | - | `1b368326670e8fa9d8e55668af564498660bfd3d5dea60b6c28ed9a4b53354f2` | https://c.mql5.com/forextsd/forum/56/detailedstatement_3.htm |
| 35 | mt4_statement | mt4_statement_html | reserved | - | `abd8f01fc81e9abe53b5db423f55c2ebd47f306780ff7883a2a6f0b8c2a8cf22` | https://c.mql5.com/forextsd/forum/10/sample_report.htm |
| 36 | mt4_statement | mt4_statement_html | calibration | - | `c7bb298efc96278a53e3374167c059de3390cc66b36bee8af184f3ed4dea9a9e` | https://c.mql5.com/forextsd/forum/1/detailedstatement.htm |
| 37 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_alexanvl | `833e00d62e754a448257d8753df18907d5d4d9d38c75aefff1b7dfb90186dbab` | https://raw.githubusercontent.com/alexanvl/scalper/92bee12a4e626b29849fa4c8b42c73c2d05f3d4f/res/DetailedStatement.htm |
| 38 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_alexanvl | `db1216cb98f86da6911b13be11bf4a442eba7f8fbbfdf2b803e88af7ccb1a9d9` | https://raw.githubusercontent.com/alexanvl/scalper/3fe2b5920adb75aa94cb443890ba0dea75ce11c3/res/DetailedStatement.htm |
| 39 | mt4_statement | mt4_statement_html | reserved | mt4_stmt_fujunzibo_acctA | `18a09d9dbc2f1919cc83b953b18ba1c4eca892658a96722d7ae850ad2882dc0f` | https://raw.githubusercontent.com/fujunzibo/mt4/a8a710253b12b66e151cd6cff6a2ce48782bc6e7/test/DetailedStatement2.htm |
| 40 | mt4_statement | mt4_statement_html | reserved | mt4_stmt_fujunzibo_acctA | `ef8f01f7c58d4b5b0302a2cab49264a6004276d6ff6ffaf6ec981bb1da7b5975` | https://raw.githubusercontent.com/fujunzibo/mt4/807ab0e2dfd5335b797eb4813f1101ee5b8eb15f/test/DetailedStatement2.htm |
| 41 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_fujunzibo_acctB | `d78c78d757f460eb71f21ba5af8dec8dd5f36ff2c4edbbef9404ddcee30d0212` | https://raw.githubusercontent.com/fujunzibo/mt4/a8a710253b12b66e151cd6cff6a2ce48782bc6e7/test/DetailedStatement.htm |
| 42 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_fujunzibo_acctB | `f40e9c336ed392a1f8bbb9533d2e97e0e23000d381041a9b7a539e7191198cd5` | https://raw.githubusercontent.com/fujunzibo/mt4/807ab0e2dfd5335b797eb4813f1101ee5b8eb15f/test/DetailedStatement.htm |
| 43 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_iwabuchiken | `03f3609c0b2cc4c7c7a03cb6b8ff0b9e7a85f0d4b9cbde0b0090461b4f7ec0bd` | https://raw.githubusercontent.com/iwabuchiken/MQL4_Indicators-EAs/33316ba3e2eaedad3ad0888e2851573f6191b091/Files/Report_Trades/DetailedStatement.%2820190114_130029%29.%28e-j%2CM1%29.htm |
| 44 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_iwabuchiken | `1e18e1c96936f604643c7d037087e671549dd98eadd605d8d4fc8e015543c5ab` | https://raw.githubusercontent.com/iwabuchiken/MQL4_Indicators-EAs/ca48b834c27aec25b7b5ff06664c46aed982c387/Files/Report_Trades/DetailedStatement.%5B20190207_184152%5D.%28e-j%2CM1%29.htm |
| 45 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_iwabuchiken | `33a0d37a3a516d920b1dd304f571b14e55034439ee6e5bf09dd0aa34a5baaded` | https://raw.githubusercontent.com/iwabuchiken/MQL4_Indicators-EAs/6443905b137df54998124ab0ca670a6f372a9b83/Files/Report_Trades/DetailedStatement.%2820190115_223628%29.%28e-j%2CM1%29.htm |
| 46 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_iwabuchiken | `779eafb88c309251e7b28ded742c1d26c10cf8f203e8c624fc31abb99be37e4a` | https://raw.githubusercontent.com/iwabuchiken/MQL4_Indicators-EAs/6443905b137df54998124ab0ca670a6f372a9b83/Files/Report_Trades/DetailedStatement.%2820190117_231722%29.%28e-j%2CM1%29.htm |
| 47 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_iwabuchiken | `b43cba0de465065a2eb74e05786998b696e00b1c3dd477e6946abdcebaaf1386` | https://raw.githubusercontent.com/iwabuchiken/MQL4_Indicators-EAs/6443905b137df54998124ab0ca670a6f372a9b83/Files/Report_Trades/DetailedStatement.%2820190115_000717%29.%28e-j%2CM1%29.htm |
| 48 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_iwabuchiken | `b4c8646e6e196ca84afc1c1224d56f1d5c1ec5b805601f987d9c496c855a068b` | https://raw.githubusercontent.com/iwabuchiken/MQL4_Indicators-EAs/33316ba3e2eaedad3ad0888e2851573f6191b091/Files/Report_Trades/DetailedStatement.%2820190114_210538%29.%28e-j%2CM1%29.htm |
| 49 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_iwabuchiken | `e81d031c51a1c4e331c3101b1067a6ad07331cb33053a4f2e095ad570fb0a843` | https://raw.githubusercontent.com/iwabuchiken/MQL4_Indicators-EAs/33316ba3e2eaedad3ad0888e2851573f6191b091/Files/Report_Trades/DetailedStatement.%2820190115_084743%29.%28e-j%2CM1%29.htm |
| 50 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_iwabuchiken | `eaea26c18527a6e795e3ab525a2ee4b3dbdb7a586c61308bc3aa7406816e246b` | https://raw.githubusercontent.com/iwabuchiken/MQL4_Indicators-EAs/6443905b137df54998124ab0ca670a6f372a9b83/Files/Report_Trades/DetailedStatement.%2820190122_230530%29.%28e-j%2CM1%29.htm |
| 51 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_jackk1 | `351c3bdf0f899419533be75028c84e3073383d8ff2128b9fd74eda6ccf69e5d3` | https://raw.githubusercontent.com/Jack-K1/GUHTMLST/280a0d08da2c3f57554cd17987dcdaa1bd466840/Notional_GU_Algo_Full_Report.html |
| 52 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_jackk1 | `4be413bde568414841883b971100de873282f5934862f620c8df6ce195f5d830` | https://raw.githubusercontent.com/Jack-K1/GUHTMLST/280a0d08da2c3f57554cd17987dcdaa1bd466840/Notional_GU_Algo.html |
| 53 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `08bb6abe36c57f4b3eaffcd37325ffd9f6f9fb3a091ec69b6bfe25119fc4ddf9` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/8536ff2c92aafc88cdbdfb0f6bea125a85aa3774/public/data/statement.htm |
| 54 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `1a245dfb01c76cf4a71435950c4b6969cfe0e2a127686599d91d60211c5c63b9` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/fabfdea1039ca40793bd9635963c8c9a012e2fd0/public/data/statement.htm |
| 55 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `1bb0c3b662c6627485f08e61f620fefda15498fcf9734f761b96487c298fd7c5` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/167f562adc222cab0e393e302dd9275031a907f7/public/data/statement.htm |
| 56 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `1cda2c2d3bf136eb10fe6373b61c425f38e6f827d839466520db0ae13df2df0a` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/273445eb02a925fd8ab4a8168de41fee0ad29f3f/public/data/statement.htm |
| 57 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `20ade2e938aa54d46e6257fda1bdbc14b483fbe2d9e876bf3ee54c0169c5496b` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/ba7dd023dd1fc16dfef69b935380ae70423bbf8d/public/data/statement.htm |
| 58 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `2f370f2f081556869f86d403079f9d142f446a0e915e5db17bcea199a94cc5df` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/73d4181b16512aa2eccc64ed32f969ee3a823612/public/data/statement.htm |
| 59 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `349ba06d783429722582b372d729b2dae6f8072f2c73356c26fe1bbb0a54ca2a` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/90e829e8ae875df00b3b738519bb35242db82c48/public/data/statement.htm |
| 60 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `36c5df36344356dd30f800c9cb27c9e585d2fe54c477bd1477ceae14cf019ecd` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/42d77f61aecba0423178ce63bf765c0e4754ff57/public/data/statement.htm |
| 61 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `382895f31544c39f1bf625ca2af1b0c4e98143732111a646e6c052f5e2cd1002` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/a25ca27914f7fc3405bf99465536dd5df63cf02a/public/data/statement.htm |
| 62 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `395d9cb9820cb123327211b1d4c6af9f628861ec1f20e80a7ad84d1b51ccd50b` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/c8d7f4aa8927ccc6c54b23e394c56228704ded12/public/data/statement.htm |
| 63 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `3a55b3fa0300b8cd8a0abc72eb09f82309f179c7442fe92711fc2d1cdb2f9bdf` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/6648951ce932571a9767a25cdcab40805d4c5b3a/public/data/statement.htm |
| 64 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `3bc0160165bc411f1a7f3d9b89729abc4191bd67a289ae3bf5c173e0b3582c9b` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/00193d24c3cdf880c54fa3d2baced77c02549b1e/public/data/statement.htm |
| 65 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `3fef2515751b9d58630fafbd7c2bb1746858296ab38e5669a3a5bb2c1d99427c` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/cc68e7fcd432d27c687547362ed1f5a8afde8cc7/public/data/statement.htm |
| 66 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `443da3fe3ea704841aad2388b8a8686a5bd8fa77f0a91f115ce5e13e61110e45` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/06580ca7193825c3e04b2e9496913cf566f2b8c7/public/data/statement.htm |
| 67 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `49e99f46d9db826a590741ebac662ca52cae65da97ded0ef7ba4ae4f5ae2cb7a` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/337d35f5601fc805917be0d83c5bea73d2fa1dc9/public/data/statement.htm |
| 68 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `5373293fd4720f1facf0f30f68c2bdc9bb6fb4362ba88eccafeee9ec750f9aff` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/319e63ec402a1ac8278269babb5468de0d068ad1/public/data/statement.htm |
| 69 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `5a9a461be28a21838b617e812f2a1553f70b39b77c83c67f762c2c6a09e5dce7` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/e510bfaa6a5b6f637abd5eb837158e0ab426e7e5/public/data/statement.htm |
| 70 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `5e4d22e060576306f43826c8506692a0cbbdd677f5eae34e2a9bc713175735dc` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/62fc094e5546b74478523c2c8b08c36118b532cb/public/data/statement.htm |
| 71 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `62470c9d5bad257e0c186b126aa6e4a8bb7ed1ce3319c7cfbde65b4ae18c0b0a` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/6bff9c4c7ce158c507872755bf961f2f61bbb264/public/data/statement.htm |
| 72 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `624b06a7c7a22bc482cae41f14c67fd1e26185f8c8023fe7fc485d3de94582e2` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/f0938e71a69a22096369901ab6f0b214495084b8/public/data/statement.htm |
| 73 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `66a9f8cbeee9821dcf8ae552d4626dce3ce66f242c103a7b076cfa8efb908866` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/c81e345d9be20d90947514aca3fca2333dbe2a7d/public/data/statement.htm |
| 74 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `6765c82562ca029a7b6411a4c279d35469ddcadd8046d5490288059809ca532d` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/9d6a6eb99da9f19af8559d57c93ce0d9b7de4e2b/public/data/statement.htm |
| 75 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `701c9afb82bf96fd78ef0c7c3c8b27190c27989971fe6f3199cf0d4de07a035e` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/a9a157f1183320e912d17c352d302061f35294c7/public/data/statement.htm |
| 76 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `77a420968fb56a41010315722417bde5e6f1e982ef37344ba7d4a7730d935d68` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/9ddcd30e1337a0e8f8e4007aef68e71828d18efc/public/data/statement.htm |
| 77 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `787df70a7be740c16785379b1101c1fc0eece3d68c5eaba2c6aaf4e91b25a34d` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/709355f6425831442912c9d9ff2f7bb138a4db28/public/data/statement.htm |
| 78 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `7edda6a551149067ee44641098f826121e8c4ac8127c5a8463d3d42e60153025` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/3be58f58b2002b85864f726b8a4652d8ad09206f/public/data/statement.htm |
| 79 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `87dadfe2f65d2ffb0e6b59138635f588926dad5726312f796a1e9fc5912f0e2e` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/41a6180c147ca9ad056f53b386e740dabd6cf1e5/public/data/statement.htm |
| 80 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `8d2bb755037d815f5d4c289f8356da522396745915514aa469cc71ae5166ac91` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/888bd723e8dfa25126f121facd89f61971633cf7/public/data/statement.htm |
| 81 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `999a48dc85a78685828af94b792216f12fbe50c653a4b1cd96daf71495eadabb` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/dd854a206a111b2e345f4105a3540fda32461ea2/public/data/statement.htm |
| 82 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `abc06a8439d423600af6433b9e08728fb1c598085c8157e15a08d4c776e13463` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/5816043f781ba3ec541227ee0e94ca47ceeef9d0/public/data/statement.htm |
| 83 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `aef18117c8295ef553e3110dc54c071bfe346ab2ae8842a41774137760a206d6` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/9382da13be0521d807afde427614c8ff32dfa0e6/public/data/statement.htm |
| 84 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `b6b8f10bcac853d264a6f6bf5b0dac1b58495fe20943d8a5d6b70819ec32cc5f` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/15c4fd9fc03eea50cb74b5c06e94b73a07642657/public/data/statement.htm |
| 85 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `b6cfa72801fbca5f419cd9e779af6c183d26a3ecf3fab5bc2edc1536feaa4531` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/dd164b8f15363bd585d16dc2a2083b023fda0212/public/data/statement.htm |
| 86 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `b784713bb7ab004a8843d80d2e844bd3d5c9c2b1c54275e7ff57b14acf47acb4` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/a3dbda56b0fc7033fc8868d07b412c36a915340b/public/data/statement.htm |
| 87 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `b8b34b1712707e9ad3bf90e98f7c18e5330add8b3db86f226fa43427fd57dd2c` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/772a20cddaac88cce7a951d05e29db1b35680e73/public/data/statement.htm |
| 88 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `be586b3244dc33e8acd3e70f7aacbf6822972588cdb210b1306ee55c9744dcf6` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/0718d639c872254f27cf606e053a3ae0e3af9324/public/data/statement.htm |
| 89 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `c9a11dd9e3c85496e9498588e5423de782fdc918e2b9bede0fc6ceff5cc28822` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/c7a26b9d2162e3265ed52e206a1ee1982bd1cec8/public/data/statement.htm |
| 90 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `d0423dbc0265325203ca3b973fe86b3e757d27c182f021c81f49b6966dfcbbf6` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/738cd9878da47b4f325e51ffd113a510e6821c08/public/data/statement.htm |
| 91 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `d1810042de8094d9b2adb907887081267061fe6e60497ecb4f139758517c9daf` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/c12072acd1dad3040713abbcbaa1fd12d9b0f501/public/data/statement.htm |
| 92 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `d37bc55f6a1c45b46cbd26f2e43ed8be0781c1a4e5ee925a12f5171a6fe77631` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/d92391f2d3cc5ce61ff2e5d71eef31c205957c9d/public/data/statement.htm |
| 93 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `d38fec16ebd375d5ea8f26ed47e45b7e46f5cb8e216ebaf15138a83813c960ba` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/8d94b5418205a80bec5f3af2fd4173523f218c36/public/data/statement.htm |
| 94 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `d61d7419da8585b201642d368bbf30a54eaca6edfcf2d1518a0a95e0abf37665` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/fbdf713ff6e33cc4a51c71c0e2306b5abbc2c078/public/data/statement.htm |
| 95 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `db54adca82324a25ec6c57b9a0ce445d3666b952b7b89e592ea1dd33c35ba4c7` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/034f7bc16967dbc3169043087e0d5bcd64174e80/public/data/statement.htm |
| 96 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `dffa80b0b6b4befafa239dcb86c5c6265a383886ff1e5351b5cd44b42ca60b3f` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/69a59b2262b203ce841f3a80abd8f0484e71ba46/public/data/statement.htm |
| 97 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `e24df2c3527054252edf15946900ad2dc44cf776f2e1c6097d409c441839da1a` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/1a46b5663ce62ac67fc387ed59bd3a91fae14b9d/public/data/statement.htm |
| 98 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `feaccda5322ce09d6039c1dcb88548da21d907c62373fd7d8d5e73390ff57fdb` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/d954a6d5348461d623bf7628b758803e8db45246/public/data/statement.htm |
| 99 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_paulhil | `ff28d4ab87db60d927b3a7687d491335dba9239060d2c548f543d1b59c2263c7` | https://raw.githubusercontent.com/Paul-Hil/mt4-history/5e82a528edc62864da9b9b335ff569057ef1f9d8/public/data/statement.htm |
| 100 | mt4_statement | mt4_statement_html | reserved | mt4_stmt_polopopeye_fbs | `401a808eebbbf4bcb99e8353ed6f08fe8c948d828443e17578a04e225631a2ef` | https://raw.githubusercontent.com/polopopeye/EAK-Project-SBC/17ee607f5bda3929b5deacf68a7a795f6bbf2ec9/EAK1/2/FBS%203%20Semanas.htm |
| 101 | mt4_statement | mt4_statement_html | reserved | mt4_stmt_polopopeye_fbs | `d4eb5cd47ffbcd214539a160e2eb5978a36b7cd6885c91416ae3e37723be8999` | https://raw.githubusercontent.com/polopopeye/EAK-Project-SBC/17ee607f5bda3929b5deacf68a7a795f6bbf2ec9/EAK1/2/FBS%204%20Semanas.htm |
| 102 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_queenofparts | `5d07c4118bc35a68f98ddadf0a7c6d555a9eb7df7784ca2500d12696d08757ab` | https://raw.githubusercontent.com/QueenofParts/Project2-Room2/18352cefa83e66b286b9ed873f84a6f47787e9c6/resources/html/DetailedStatement_gold.html |
| 103 | mt4_statement | mt4_statement_html | calibration | mt4_stmt_queenofparts | `871c4332e148770744cd4a93911b7bc07e0e1ee9428587695d276f86245a64e0` | https://raw.githubusercontent.com/QueenofParts/Project2-Room2/18352cefa83e66b286b9ed873f84a6f47787e9c6/resources/html/EATesting_All_Assest.html |
| 104 | mt4_tester | mt4_tester_html | calibration | - | `13c53a9820a258ef0e0f2ecd76676248729448c66850c1e480b2f785b78b2451` | https://raw.githubusercontent.com/joaotorresmarques/mql4/ae010cc4c59be57bceaac52b52439f496335b3ef/Experts/EAS%20Codigo/40%20ROB%C3%94S%20FOREX/ea-strategy/Strategy%20Tester%20ea-strategy.htm |
| 105 | mt4_tester | mt4_tester_html | calibration | - | `2a0f0457c3cbcd994c449575f8bb08d35e9bc2584d5c0bd45aa6fb788de3adb1` | https://raw.githubusercontent.com/joaotorresmarques/mql4/ae010cc4c59be57bceaac52b52439f496335b3ef/Experts/EAS%20Codigo/40%20ROB%C3%94S%20FOREX/EuroW/StrategyTester-EuroW.htm |
| 106 | mt4_tester | mt4_tester_html | reserved | - | `2db2a83cda14063451a2703401b28c0fb5e729d9e88783e93ba017cc3ee9dbe0` | https://www.mql5.com/en/articles/download/5706.zip |
| 107 | mt4_tester | mt4_tester_html | calibration | - | `2eace53b49f77ec40b4c611a2e8df741cced8f797b835b1edf2937bdd4e956ed` | https://raw.githubusercontent.com/DiogoRolo19/mql4/922de56791fdd3f6eaacc7aa22d358e95610d849/mql4/3-Tuga%20and%20Wickoff/Wickoff/StrategyTester.htm |
| 108 | mt4_tester | mt4_tester_html | calibration | - | `41d2ab77ecbb5f993c2ffae2690d0bae446291ef96f6500892472e00038ddd2d` | https://c.mql5.com/forextsd/forum/12/multilotscalper_1.htm |
| 109 | mt4_tester | mt4_tester_html | reserved | - | `4334e326f8462667f8fd0c0727a8aa60e472f890420efe8c5637e081b6bbf489` | https://raw.githubusercontent.com/DiogoRolo19/mql4/922de56791fdd3f6eaacc7aa22d358e95610d849/mql4/7-Bias/StrategyTester.htm |
| 110 | mt4_tester | mt4_tester_html | calibration | - | `4b3a0365673a34a6d0de773245073e10c4530092231e77f91327b61c103706e0` | https://raw.githubusercontent.com/joaotorresmarques/mql4/ae010cc4c59be57bceaac52b52439f496335b3ef/Experts/EAS%20Codigo/40%20ROB%C3%94S%20FOREX/EuroQ/StrategyTester-EuroQ.htm |
| 111 | mt4_tester | mt4_tester_html | calibration | - | `4c20d01b0049b59e4ead1d965f0d98dca268e7702096ff7050cecbd10b56ee23` | https://c.mql5.com/forextsd/forum/2/strategytester.htm |
| 112 | mt4_tester | mt4_tester_html | reserved | - | `5e2aaa99d5ca63c95b2f3ad187c308c3459c6a53f5a578798d202180b50ffa78` | https://raw.githubusercontent.com/DiogoRolo19/mql4/922de56791fdd3f6eaacc7aa22d358e95610d849/mql4/5-AoT/AoT_FTB/StrategyTester.htm |
| 113 | mt4_tester | mt4_tester_html | calibration | - | `7a7b32ea52a57daff3fa5484e31352e294d503f0276beda98be4c231c50cf9ae` | https://raw.githubusercontent.com/joaotorresmarques/mql4/ae010cc4c59be57bceaac52b52439f496335b3ef/Experts/EAS%20Codigo/40%20ROB%C3%94S%20FOREX/cash_hammer/ch200-seti/ch200-novee/24/24prosadka--ch20--lock--true--001lot.htm |
| 114 | mt4_tester | mt4_tester_html | calibration | - | `832acfcaf6778271286114338764d9404df72c1d72b103859cc043e3e70b67dc` | https://raw.githubusercontent.com/joaotorresmarques/mql4/ae010cc4c59be57bceaac52b52439f496335b3ef/Experts/EAS%20Codigo/40%20ROB%C3%94S%20FOREX/JapanMoney/StrategyTester-JapanMoney.htm |
| 115 | mt4_tester | mt4_tester_html | reserved | - | `83409b79732bedb23dde1f68cbaf76715b3d146720b83695d2ff97a5b89364fd` | https://raw.githubusercontent.com/PanPip/MQL4_experts/f1f127d67ba94412e26ca85900d164d8bfb756ce/StrategyTester.htm |
| 116 | mt4_tester | mt4_tester_html | calibration | - | `864a32d3e6d3adcabd4ac3ae81dc7d07fba16adeed9de10dbbfce24463c0bbae` | https://raw.githubusercontent.com/DiogoRolo19/mql4/922de56791fdd3f6eaacc7aa22d358e95610d849/mql4/2-Mama/Mama.htm |
| 117 | mt4_tester | mt4_tester_html | calibration | - | `86883fe71005c5bee8288174360f295f79578ac66749648b6d5bf8b91d783176` | https://raw.githubusercontent.com/joaotorresmarques/mql4/ae010cc4c59be57bceaac52b52439f496335b3ef/Experts/EAS%20Codigo/40%20ROB%C3%94S%20FOREX/cash_hammer/ch200-seti/ch200-novee/21/ch--20--prosadka21--x2.2--za6mesytsev.htm |
| 118 | mt4_tester | mt4_tester_html | reserved | - | `8cc341f1cc6bcfccda7b6c328442498ae6d21611b9579128a7aa27ab690a75e5` | https://raw.githubusercontent.com/joaotorresmarques/mql4/ae010cc4c59be57bceaac52b52439f496335b3ef/Experts/EAS%20Codigo/40%20ROB%C3%94S%20FOREX/cash_hammer/ch200-seti/ch200-novee/first--tut/ch-20-lutshiy--lock--true--150usd--001.htm |
| 119 | mt4_tester | mt4_tester_html | calibration | - | `9f66f0b5374b102511b84a4283db27f6da5016342d93425a2ff51562d0566f35` | https://raw.githubusercontent.com/DiogoRolo19/mql4/922de56791fdd3f6eaacc7aa22d358e95610d849/mql4/5-AoT/AoT_DailyBreakout/StrategyTester.htm |
| 120 | mt4_tester | mt4_tester_html | calibration | - | `a52b23cb341f34c75abf0bd0ba73537b3a592a49b2febf2ec826353f6db35c1c` | https://raw.githubusercontent.com/joaotorresmarques/mql4/ae010cc4c59be57bceaac52b52439f496335b3ef/Experts/EAS%20Codigo/40%20ROB%C3%94S%20FOREX/Auto-profit/StrategyTester-AutoProfit.htm |
| 121 | mt4_tester | mt4_tester_html | reserved | - | `b65429d7d9608e784484b03883d164337a29b5cf8e64a6fef69fa42a6a979198` | https://raw.githubusercontent.com/DiogoRolo19/mql4/922de56791fdd3f6eaacc7aa22d358e95610d849/mql4/1-PriceAction/Mitigation.htm |
| 122 | mt4_tester | mt4_tester_html | calibration | - | `b73e9a012aea50076541c0e1e883607b163d703ff80cc02ec1978a53b0fd954b` | https://raw.githubusercontent.com/DiogoRolo19/mql4/922de56791fdd3f6eaacc7aa22d358e95610d849/mql4/5-AoT/AoT_PinbarStrategy/StrategyTester.htm |
| 123 | mt4_tester | mt4_tester_html | calibration | - | `b9e08f454abede61234d5c063bad3a16052556c0e7668df70a2d764cb3fbd434` | https://raw.githubusercontent.com/joaotorresmarques/mql4/ae010cc4c59be57bceaac52b52439f496335b3ef/Experts/EAS%20Codigo/40%20ROB%C3%94S%20FOREX/cash_hammer/ch200-seti/ch200-novee/18--200usd/200usd--ch20.htm |
| 124 | mt4_tester | mt4_tester_html | reserved | - | `c9c08a53d0f7f3b6d16ac3b72c07fdf85bb07a4e6761638dab408e451cf2d660` | https://raw.githubusercontent.com/DiogoRolo19/mql4/922de56791fdd3f6eaacc7aa22d358e95610d849/mql4/5-AoT/AoT_RSIStrategy/StrategyTester.htm |
| 125 | mt4_tester | mt4_tester_html | calibration | - | `c9d735af409aa86780a6d9762e074a22d75c9693b7fc36dc187a4f31d5ddede5` | https://raw.githubusercontent.com/joaotorresmarques/mql4/ae010cc4c59be57bceaac52b52439f496335b3ef/Experts/EAS%20Codigo/40%20ROB%C3%94S%20FOREX/cash_hammer/ch200-seti/ch200-novee/20.85/ch20--150usd--20prosadka.htm |
| 126 | mt5_history | mt5_history_html | calibration | - | `07c318b17c09734abc435805513848a3a97aa77b53a1217470944850e47fe60e` | https://www.mql5.com/en/articles/download/5436.zip |
| 127 | mt5_history | mt5_history_xlsx | reserved | - | `809d2f67a8ccb11142a7c6b2e9bc0dd2c8abd5ed2cd9442974d2736c112f281e` | https://raw.githubusercontent.com/DaraGaloX233/MQL5_TradeRecord/0c68febe67bfc6c224ae4b1468ef5c7ee7bc5378/TRADE_31_8_2020/ReportHistory-23_30_8_2020.xlsx |
| 128 | mt5_history | mt5_history_html | calibration | - | `837842784500ad404f10019d4484cd488a5aeee90ee976cf48877635bd1384fe` | https://raw.githubusercontent.com/DaraGaloX233/MQL5_TradeRecord/0c68febe67bfc6c224ae4b1468ef5c7ee7bc5378/TRADE2782020/2782020.html |
| 129 | mt5_history | mt5_history_html | calibration | - | `92e5b13b5abfdc6740ed34c089efa9939ca8816ebce50b9eb2935241548f2386` | https://www.mql5.com/en/articles/download/5706.zip |
| 130 | mt5_history | mt5_history_xlsx | reserved | - | `a6c61a80f2432615b49eba0df619efc8e6bba8d166852f1e0fbf629871ecd9bb` | https://raw.githubusercontent.com/svopex/forex-MT5-report/cda04bd7095353542df19ba1d58afbf8b0555d37/ReportHistory-498754.xlsx |
| 131 | mt5_history | mt5_history_html | calibration | - | `c1f37fe0d2ba43252c2706b551218cbd48ac28bd3a1615ea0d3bd12d5298304f` | https://raw.githubusercontent.com/DaraGaloX233/MQL5_TradeRecord/0c68febe67bfc6c224ae4b1468ef5c7ee7bc5378/TRADE_3_9_2020/ReportHistory-50367453.html |
| 132 | mt5_history | mt5_history_html | calibration | - | `e86d2c547a5923cc1b0ef81b3fba6c6b224a5dd54a25d6c77478de5ceae44ff3` | https://raw.githubusercontent.com/DaraGaloX233/MQL5_TradeRecord/0c68febe67bfc6c224ae4b1468ef5c7ee7bc5378/TRADE28_8_2020/ReportHistory-50367453.html |
| 133 | mt5_history | mt5_history_html | calibration | mt5_hist_dara | `0ed4cce608343c0b38aadf38b5d0ddbf68983b7aa2e09c9921189e7ae5d43ab9` | https://raw.githubusercontent.com/DaraGaloX233/MQL5_TradeRecord/be9f78f048b93a65507197d2bcec383eb3a47c4f/TRADE28_8_2020/ReportHistory-50367453.html |
| 134 | mt5_history | mt5_history_html | calibration | mt5_hist_dara | `4967400fa073ff93dcefff305645ce5c3d39d2c3a0e192897be66b315060ad86` | https://raw.githubusercontent.com/DaraGaloX233/MQL5_TradeRecord/ac473ea978c1b7a10504c2fb35cc34747f53b221/TRADE2782020/2782020.html |
| 135 | mt5_history | mt5_history_xlsx | reserved | mt5_hist_dara | `809d2f67a8ccb11142a7c6b2e9bc0dd2c8abd5ed2cd9442974d2736c112f281e` | https://raw.githubusercontent.com/DaraGaloX233/MQL5_TradeRecord/5bdabfbd9e116f1c2bdfbb0c5ade167c9c3b5d81/TRADE_31_8_2020/ReportHistory-23_30_8_2020.xlsx |
| 136 | mt5_history | mt5_history_html | calibration | mt5_hist_dara | `837842784500ad404f10019d4484cd488a5aeee90ee976cf48877635bd1384fe` | https://raw.githubusercontent.com/DaraGaloX233/MQL5_TradeRecord/55c04dca3f1eccd67f643add83d0b7501ebc1fd2/TRADE2782020/2782020.html |
| 137 | mt5_history | mt5_history_html | calibration | mt5_hist_dara | `c1f37fe0d2ba43252c2706b551218cbd48ac28bd3a1615ea0d3bd12d5298304f` | https://raw.githubusercontent.com/DaraGaloX233/MQL5_TradeRecord/0c68febe67bfc6c224ae4b1468ef5c7ee7bc5378/TRADE_3_9_2020/ReportHistory-50367453.html |
| 138 | mt5_history | mt5_history_html | calibration | mt5_hist_dara | `e86d2c547a5923cc1b0ef81b3fba6c6b224a5dd54a25d6c77478de5ceae44ff3` | https://raw.githubusercontent.com/DaraGaloX233/MQL5_TradeRecord/625b576a98940fd7c87f78fc360be78103ba34e1/TRADE28_8_2020/ReportHistory-50367453.html |
| 139 | mt5_tester | mt5_tester_xlsx | calibration | - | `047d75ce9839ef1e4ec4b9a005705b9e8d97db5bd23952b4ed9f736ae19578d4` | https://raw.githubusercontent.com/geraked/metatrader5/HEAD/Test/BBRSI/report.xlsx |
| 140 | mt5_tester | mt5_tester_html | calibration | - | `048a84deaa7c3d1803bdb42168ca283387fea0ee1db3c70cc740e03812cc9eb7` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_default_params/random_forest/ReportTester-7101049.html |
| 141 | mt5_tester | mt5_tester_html | reserved | - | `0841aa4b9db86e169b818ed2d8a1ccef88236fc990bd9c0435e9e3db00e6c881` | https://raw.githubusercontent.com/abiodunaremu/openea/HEAD/reports/v1_1/feb2025_default/ReportTester-v1_gbpusd_feb2025.html |
| 142 | mt5_tester | mt5_tester_html | calibration | - | `091777dc5a002508331a494fe914367a76869f8a12d180923380892b2c911b87` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_adx22/baseline_only/ReportTester-7101049.html |
| 143 | mt5_tester | mt5_tester_html | calibration | - | `096f7cbee9629f9a9cdf1054c016a4c7bf6a041e71773d49ddae02764ce4866b` | https://raw.githubusercontent.com/kecoma1/Trading_BOT/851aae6cbd7ce63849cfae8bc58de1bb220b64e6/mql5/profitable/MACD_RSI_STOCH/MACD_RSI_STOCH_V3/ReportTester-54232522.html |
| 144 | mt5_tester | mt5_tester_html | reserved | - | `0c2972f198191dd5afb1379871c30f209943328799823c13515a279d6b8af820` | https://www.mql5.com/en/articles/download/5436.zip |
| 145 | mt5_tester | mt5_tester_html | calibration | - | `16356e65811db69346c3890420e333c7e1189b0be98e52286d5194f55eda13bb` | https://raw.githubusercontent.com/pranay123-stack/forex-mt5-strategies/HEAD/Forex_trading_strategies_EA_scripts/LiquidityMarketMap_EA/ReportTester-52688756.html |
| 146 | mt5_tester | mt5_tester_html | calibration | - | `17be2af556e613dd60864a6afddaf6585283dba17b5c60e1b530bc9372e954d2` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_iAD_filter/lstm/ReportTester-7101049.html |
| 147 | mt5_tester | mt5_tester_html | reserved | - | `242b54d2fb3bf03ccf3da9021e430c8b911de98370337f566e17c6eaf5aa35dc` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_ema6-24/baseline_only/ReportTester-7101049.html |
| 148 | mt5_tester | mt5_tester_xlsx | calibration | - | `263a664900c136e029058dac5ee2874b491a5b436e4e5d2953dffdefc73091e1` | https://raw.githubusercontent.com/geraked/metatrader5/HEAD/Test/COT1/report.xlsx |
| 149 | mt5_tester | mt5_tester_html | calibration | - | `2832d481703a9af3d2a65ea929fed951a0190a84ab6237ecdce75fbc141a4a1c` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_iAD_filter/baseline_only/ReportTester-7101049.html |
| 150 | mt5_tester | mt5_tester_xlsx | reserved | - | `28a67ddd75ca09a7ba8410113f8cc1e21a1a03aad126a94628b0227abf48f002` | https://raw.githubusercontent.com/geraked/metatrader5/HEAD/Test/3MACD/report.xlsx |
| 151 | mt5_tester | mt5_tester_html | calibration | - | `29df3a52ee9c34c09898f7b40ffbd625e330b80ed154f7098aa76a66c2333b02` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_default_params/lstm/ReportTester-7101049.html |
| 152 | mt5_tester | mt5_tester_html | calibration | - | `2d4163bb2deab6fef64b0673373b953e764ca7449f4555e39a5fbcb5efb86ac9` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_default_params/xgboost/ReportTester-7101049.html |
| 153 | mt5_tester | mt5_tester_html | reserved | - | `31173744e5ef51c7203944c5623af6e3a16cf8f68fc5584f53d24c4c419ecccc` | https://raw.githubusercontent.com/pranay123-stack/forex-mt5-strategies/HEAD/Forex_trading_strategies_EA_scripts/PPCorr_EA/ReportTester-52688756.html |
| 154 | mt5_tester | mt5_tester_html | calibration | - | `3f6a85fc01b282c6013e1d3c7d5d84328aae75f81309ff1a856f806788f8b277` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_ema6-24/lstm/ReportTester-7101049.html |
| 155 | mt5_tester | mt5_tester_html | calibration | - | `43de8be2181e31f5a80b6fee765a369c3940d21e3449748bf5acbdb36af4c8eb` | https://c.mql5.com/3/128/ReportTester_MACDSample.zip |
| 156 | mt5_tester | mt5_tester_html | reserved | - | `5baadd9f2f8585f56cb3d60b7eb49fc69ca314156701e6b5a9134c0f1967fd8a` | https://raw.githubusercontent.com/William-Brandao/Trade-mql5/2c595e9c1ebebfcc066b1654faf00fb8549ea1d8/resultados%20OUT%20OF%20SAMPLE/RSI%20oos/brkm5%20vendido%20out%20of%20sample%20rsi.html |
| 157 | mt5_tester | mt5_tester_html | calibration | - | `728197c0cd1df84bc1c3b8ded3c2dfdc0f93ef89be83df669e08dbaf5dc144f9` | https://raw.githubusercontent.com/Jason767445898/QA_SQX/950e56a4f6aee2158b1804f4a29cbbeb2103dece/ex_MT5_reports/ReportTester-10011356247.html |
| 158 | mt5_tester | mt5_tester_html | calibration | - | `7854d131b7474e3bc963bde720f3a450a912516619118c798282d9977286465d` | https://raw.githubusercontent.com/kecoma1/Trading_BOT/851aae6cbd7ce63849cfae8bc58de1bb220b64e6/mql5/profitable/MACD_RSI_STOCH/MACD_RSI_STOCH_V1/ReportTester-54232522.html |
| 159 | mt5_tester | mt5_tester_html | reserved | - | `7f766e1d51a7466bd2b434fe0e83dc66d47b75cdbae6b0125c9acadd2b36a7e1` | https://raw.githubusercontent.com/William-Brandao/Trade-mql5/2c595e9c1ebebfcc066b1654faf00fb8549ea1d8/resultados%20otimiza%C3%A7%C3%A3o%20IN%20SAMPLE/BDB%20is/cmig4%20comprado%20in%20sample.html |
| 160 | mt5_tester | mt5_tester_html | calibration | - | `815806d3a7ff34582778006740e222fb117149895df1bc791b29ff04ac6eee4f` | https://raw.githubusercontent.com/kecoma1/Trading_BOT/851aae6cbd7ce63849cfae8bc58de1bb220b64e6/mql5/profitable/MACD_RSI_STOCH/MACD_RSI_STOCH_V5/ReportTester-54232522.html |
| 161 | mt5_tester | mt5_tester_xlsx | calibration | - | `8296fb5a8bd05942b08503751919dc3e33fb64f50bf1db28b5062e6c3b20c9e5` | https://huggingface.co/algorembrant/MT5report-parser/resolve/main/backend/%5B3%5D_Process/ReportTester-263254895.xlsx |
| 162 | mt5_tester | mt5_tester_html | reserved | - | `8eb108e012f9117cdacf450b80c19acf2a2c317ccc2cf38f8bf0800d2c04f58e` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_ema6-24/random_forest/ReportTester-7101049.html |
| 163 | mt5_tester | mt5_tester_html | calibration | - | `984133af9e31700ee130520d80fdc2438ae2058e39549d6e90b2a5c5eed8a65a` | https://raw.githubusercontent.com/pranay123-stack/forex-mt5-strategies/HEAD/Forex_trading_strategies_EA_scripts/ButterflyOscillator_EA/ReportTester-52688756.html |
| 164 | mt5_tester | mt5_tester_html | calibration | - | `9882c486b10e136a7cc4e2c156870f1a61b515c39aa4449e1b9f3fed08e06baa` | https://raw.githubusercontent.com/kecoma1/Trading_BOT/851aae6cbd7ce63849cfae8bc58de1bb220b64e6/mql5/profitable/MACD_RSI_STOCH/MACD_RSI_STOCH_V2_LOT_1/ReportTester-54232522.html |
| 165 | mt5_tester | mt5_tester_html | reserved | - | `b0c225557f0fe21e6d8d7f1d3e40aeb432045e4b685c7039e8cfeab7da345536` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_iAD_filter/xgboost/ReportTester-7101049.html |
| 166 | mt5_tester | mt5_tester_html | calibration | - | `b685ce0ddf0eaa0c0d2e84cc30a50b1b329c8e8fbddbd98cca31b6fd55e3883a` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_iAD_filter/random_forest/ReportTester-7101049.html |
| 167 | mt5_tester | mt5_tester_html | calibration | - | `baac7b6a139273c99e662ec94f406ff3cd0563d6b9a650840f8bb723a024a086` | https://raw.githubusercontent.com/kecoma1/Trading_BOT/851aae6cbd7ce63849cfae8bc58de1bb220b64e6/mql5/profitable/MACD_RSI_STOCH/MACD_RSI_STOCH_V2/ReportTester-54232522.html |
| 168 | mt5_tester | mt5_tester_html | reserved | - | `cc5435bff3f4964b4204267fd1f8b2531ee3af540b043bd4859d2e0222947a69` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_adx22/lstm/ReportTester-7101049.html |
| 169 | mt5_tester | mt5_tester_html | calibration | - | `cdef63d1ecdc5a6df9dcb2cb98c738e35d667c2422aca909966e983ff4ff5fe7` | https://www.mql5.com/en/articles/download/5706.zip |
| 170 | mt5_tester | mt5_tester_html | calibration | - | `d2996ab408c560a827c57d7ec421c2d3382901a8fccf3f9c24c6e0e3ebaf3451` | https://raw.githubusercontent.com/William-Brandao/Trade-mql5/2c595e9c1ebebfcc066b1654faf00fb8549ea1d8/resultados%20OUT%20OF%20SAMPLE/BDB%20oos/cmig4%20comprado%20out%20of%20sample.html |
| 171 | mt5_tester | mt5_tester_html | reserved | - | `d5a18762e8639e9a6b7fd6e22d8d27bc569b3218363ba4d691a6c241224196b3` | https://www.mql5.com/en/articles/download/5913.zip |
| 172 | mt5_tester | mt5_tester_html | calibration | - | `e2d3fd0ea082cb7752fd40584aac8de6053dacad4ee14ca35c08deec6fd8daee` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_adx22/random_forest/ReportTester-7101049.html |
| 173 | mt5_tester | mt5_tester_html | calibration | - | `e878e5ef4589c7ac4245b4e82d61226601b7d2f4955618b34ed10ac59b6ffd80` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_adx22/xgboost/ReportTester-7101049.html |
| 174 | mt5_tester | mt5_tester_html | reserved | - | `f06d660ecce1bd66f86365b767713226af2f68500b130bd586156a0b82906c75` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_default_params/baseline_only/ReportTester-7101049.html |
| 175 | mt5_tester | mt5_tester_html | calibration | - | `f323d70cb6e9385c11708f442cbb57aed68e54deb8363eb7c16d9e2e37e40a8b` | https://raw.githubusercontent.com/pranay123-stack/forex-mt5-strategies/HEAD/Forex_trading_strategies_EA_scripts/VB_EA/ReportTester-52688756.html |
| 176 | mt5_tester | mt5_tester_html | calibration | - | `fd8b0431f385136ac779dbb9632e26ee1fa225ef1aee46ce37737d524d565728` | https://raw.githubusercontent.com/Marco210210/AI-Enhanced-HFT/eae695fc6bb89b580f893f81b83c812643e90e99/backtest_ema6-24/xgboost/ReportTester-7101049.html |
| 177 | mt5_tester | mt5_tester_html | reserved | - | `fe9095e9cc640f5c69f0d4d403c7d91a2530cf601518c600eb3f9c3cd69be394` | https://raw.githubusercontent.com/kecoma1/Trading_BOT/851aae6cbd7ce63849cfae8bc58de1bb220b64e6/mql5/profitable/MACD_RSI_STOCH/MACD_RSI_STOCH_V4/ReportTester-54232522.html |
| 178 | myfxbook | myfxbook_csv | calibration | - | `0dfa5d4d50b139977977ac530c4368f87a3249c2f79876caec076d95fb26edd5` | https://raw.githubusercontent.com/JustinGuese/python_tradingbot_framework/HEAD/data/ZenbotZero.csv |
| 179 | myfxbook | myfxbook_csv | reserved | - | `1dd75ece71340b24db679ddb6434e8cd2999466fb866b762da50aebd15ae2db8` | https://raw.githubusercontent.com/Eric-Lingren/ParseFolio/HEAD/data/raw_data/statement.csv |
| 180 | myfxbook | myfxbook_csv | calibration | - | `2a722dc072c53368bba842cc7093efb73b3e823473342ba7004a6a6d62ddd838` | https://raw.githubusercontent.com/Eric-Lingren/ParseFolio/HEAD/data/raw_data/Dec2023Testing.csv |
| 181 | myfxbook | myfxbook_csv | calibration | - | `3bce88a5f81f18a00ea70c769a16fe9e1bf834078c6ae96744926a3e988460eb` | https://raw.githubusercontent.com/cruzntym/forex-DashBoard/HEAD/data/statement6231db41a228040279cdf4d768bb5cd0.csv |
| 182 | myfxbook | myfxbook_csv | reserved | - | `4a3be9d806f01ea7f7d1c96770a3797cab14f17380c7bbab08f8a16ff775447c` | https://raw.githubusercontent.com/Deniskurs/DEC/HEAD/src/data/performance/statement.csv |
| 183 | myfxbook | myfxbook_csv | calibration | - | `6849a2bf8a2073a6c1c63eee5ff99c1ef5d4f07f539e1f1c524c0568298f2dcb` | https://raw.githubusercontent.com/Eric-Lingren/ParseFolio/HEAD/data/raw_data/pairs_test.csv |
| 184 | myfxbook | myfxbook_csv | reserved | - | `7cf859830a0ec25e4f18f9050b51b18673bf7853d08d5a59ddf67198288f3fb6` | https://raw.githubusercontent.com/allaparthinaveen/ExecutionHub/HEAD/trading_engine/data/statement.csv |
| 185 | myfxbook | myfxbook_csv | calibration | - | `8d973b728fb893185b62a5218c4aec98955582338cdc198ebdb5fb2fadc9d2ce` | https://raw.githubusercontent.com/cruzntym/forex-DashBoard/HEAD/data/statementecea4b2366f360ffedb3b7b8cbeb87d4.csv |
| 186 | myfxbook | myfxbook_csv | calibration | - | `9bb56a44aebdc65e891ea6c80e6c6cee124cfffe69fe72e40f4bc05152c08aae` | https://raw.githubusercontent.com/gibeongideon/chemingin/HEAD/strategy/happyforex_311_trades_773.csv |
| 187 | myfxbook | myfxbook_csv | reserved | - | `a9d0cb2019b3f29d7925c3a16735c8f19e0570ff6c3d0a1c44dcfa674db241c4` | https://raw.githubusercontent.com/MikePapinski/DeepLearning/HEAD/PredictCandlestick/CandleSTick%20patterns%20prediction/BOOM_strategy.csv |
| 188 | myfxbook | myfxbook_csv | calibration | - | `ad34251718407df898f637347db279d4de67d3d24a7fea31e81ceb8e640ce838` | https://raw.githubusercontent.com/Eric-Lingren/ParseFolio/HEAD/data/raw_data/live.csv |
| 189 | myfxbook | myfxbook_csv | calibration | - | `b4330708297faa9c6038d1d642874115a1b4eea1418419928218167a7ff0097a` | https://raw.githubusercontent.com/Eric-Lingren/ParseFolio/HEAD/data/raw_data/pairs_test_old.csv |
| 190 | myfxbook | myfxbook_csv | reserved | - | `ede2f6cf92901a3abf0820264fca609d7c24a4d322836551072ad947ce013614` | https://raw.githubusercontent.com/pablosierrafernandez/Financial-Asset-Analysis/HEAD/9d832a941b1b626204ebc608e2788e271.csv |
| 191 | myfxbook | myfxbook_csv | calibration | - | `f91b5709ab01377261d2f3613f261571c21fb7cca096aebad8297e4b76548ddd` | https://raw.githubusercontent.com/cruzntym/forex-DashBoard/HEAD/data/statement1e1ee36cf9536fa2f581c553705839b6.csv |
| 192 | myfxbook | myfxbook_csv | calibration | - | `f91b5709ab01377261d2f3613f261571c21fb7cca096aebad8297e4b76548ddd` | https://raw.githubusercontent.com/cruzntym/forex-DashBoard/HEAD/statement1e1ee36cf9536fa2f581c553705839b6.csv |
| 193 | myfxbook | myfxbook_csv | reserved | myfx_parsefolio_dec2023 | `1dd75ece71340b24db679ddb6434e8cd2999466fb866b762da50aebd15ae2db8` | https://raw.githubusercontent.com/Eric-Lingren/ParseFolio/6c8df94c32f4c94fc4660e2fa757271102c7f460/data/raw_data/statement.csv |
| 194 | myfxbook | myfxbook_csv | calibration | myfx_parsefolio_dec2023 | `2a722dc072c53368bba842cc7093efb73b3e823473342ba7004a6a6d62ddd838` | https://raw.githubusercontent.com/Eric-Lingren/ParseFolio/f0cd18ac4b1285978b68c48a55a797ae68a63987/data/raw_data/Dec2023Testing.csv |
| 195 | myfxbook | myfxbook_csv | calibration | myfx_parsefolio_pairs_test | `6849a2bf8a2073a6c1c63eee5ff99c1ef5d4f07f539e1f1c524c0568298f2dcb` | https://raw.githubusercontent.com/Eric-Lingren/ParseFolio/9443821f1acca56dd9e0131dbdb853e687a9ee43/data/raw_data/pairs_test.csv |
| 196 | myfxbook | myfxbook_csv | calibration | myfx_parsefolio_pairs_test | `b4330708297faa9c6038d1d642874115a1b4eea1418419928218167a7ff0097a` | https://raw.githubusercontent.com/Eric-Lingren/ParseFolio/ef369e96d818512fad2bba220ec8b29221e59399/data/raw_data/pairs_test_old.csv |
| 197 | myfxbook | myfxbook_csv | calibration | myfx_parsefolio_pairs_test | `b4330708297faa9c6038d1d642874115a1b4eea1418419928218167a7ff0097a` | https://raw.githubusercontent.com/Eric-Lingren/ParseFolio/9ead625557f3281e909a2d0ef8ab9d9a04c15b59/data/raw_data/pairs_test.csv |

The table has 197 rows; 17 SHA-256 values appear more than once (35 rows),
the same bytes reached through two URLs. The `third` column of 5 rows
disagrees with the runner's own split (`tests/forensics_corpus.py::split`,
which is what the calibration numbers of section 5 count): rows 27, 30, 32, 135, 193
are `calibration` in the runner and `reserved` in the table (every
row of the table was matched to its manifest entry by URL, SHA-256 and
group). Five reserved entries share their bytes with a calibration entry
(section 5.5). The table is pasted as delivered;
the runner's assignment is the one that stands. Per family the runner
assigns (calibration / reserved) fxblue 5 / 0, mql5_signal 20 / 8,
mt4_statement 65 / 5, mt4_tester 15 / 7, mt5_history 11 / 2, mt5_tester
26 / 13, myfxbook 15 / 5.

## Appendix B. Reason codes and figure keys

### B.1 `NOT_MEASURED` reason codes (`review.REASONS`, closed list)

| code | meaning | typical checks |
|---|---|---|
| `format_not_covered` | the check has no rule for this family | every check outside its families |
| `no_table` | the table the check reads is absent (an old MT5 build without Positions, no Orders table) | `PNL_SIGN`, `PRICE_IMPLIED_PNL`, `CROSS_COPIES` on `mt5_history`; platform checks |
| `no_column` | the column is absent (no running balance, no ticket column, no commission column, no hidden cells in XLSX) | `BALANCE_CHAIN`, `TICKET_ORDER`, `DUPLICATE_TICKET`, `PNL_SIGN`, `HIDDEN_CONTENT` |
| `no_qualifying_row` | no row the check can examine (no `[tp]` / `[sl]` close, no partial close, no dated row, no measurable symbol) | `SLTP_FILL`, `TICKET_LINKS`, `PRICE_IMPLIED_PNL`, `STATEMENT_PERIOD` |
| `no_listed_symbol` | none of the 28 major pairs in the file | `MARKET_HOURS` |
| `xlsx_precision_lost` | a spreadsheet export whose cells lost their printed zeros | `PRICE_PRECISION` |
| `variable_precision_format` | an export that trims trailing zeros | `PRICE_PRECISION` |
| `no_header_date` | the file states no report date | `TIME_SANITY` (reserved; CSV formats measure without a date) |
| `no_declared_totals` | no summary line the importer could compare with the rows | `TOTALS_VS_ROWS`, `SUMMARY_IDENTITIES` |
| `netting_or_unknown_margin_mode` | the MT5 account is not declared hedge | `CROSS_COPIES` |
| `no_orders_table` | reserved (the Orders table is a figure, `no_orders_table = 0/1`, in `forensics-1`) | `CROSS_COPIES` |
| `several_accounts` | an FX Blue export listing more than one account | `TICKET_ORDER`, `DUPLICATE_TICKET`, `TOTALS_VS_ROWS` |
| `too_few_values` | fewer than `MONTHLY_MIN_VALUES` monthly values | `MONTHLY_DIGITS` |
| `quote_currency_differs` | no symbol quoted in the account currency, or no account currency in the file | `PRICE_IMPLIED_PNL` |
| `truncated` | a table hit `schema.MAX_ROWS` | every order-sensitive check |
| `caps_hit` | reserved | – |

Each code will have one sentence in `es`, `en` and `pt` on the page
(section 7, *planned*).

### B.2 Figure keys per check

Keys as emitted on the repository fixtures on 2026-09-26; evidence in
brackets where a key is ever other than `MEASURED` (`D` = `DECLARED`,
`NM` = `NOT_MEASURED` when the family cannot fill it). `n_rows` and
`n_hits` are on every check.

| check | figure keys |
|---|---|
| `FILE_TRACE` | `encoding`, `line_endings`, `generator`, `generator_native`, `resave_markers`, `platform_markers`, `title_attrs`, `hidden_cells`, `decimal_comma`, `sections` |
| `TOTALS_VS_ROWS` | `importer_balance_breaks`; per hit `what_code`, `declared` [D], `measured` |
| `SUMMARY_IDENTITIES` | `n_identities`; per identity `<key>` [MEASURED or NM], `<key>_left` [D], `<key>_right` [D] with keys `balance_flows_pnl`, `closed_pnl_summary`, `equity_balance_floating`, `free_margin_equity_margin`, `net_profit_gross`, `profit_factor_gross`, `trades_profit_loss`, `trades_short_long` |
| `BALANCE_CHAIN` | `first_break_row` [NM when none], `largest_gap`, `restarts` [NM], `ties_fixed` [NM], `hidden_cost_rows` [NM], `skipped_first`, `initial_balance_implied` [NM on the MT4 tester] |
| `DEAL_SEQUENCE` | `n_deals`, `n_orders`, `ticket_inversions`, `time_inversions`, `order_inversions`, `orders_missing_for_deals` |
| `TESTER_NUMBERING` | `expected_max`, `seen`, `duplicates`, `out_of_order`, `gaps` [NM on MT5], `deal_gaps` [NM on MT4], `order_gaps` [NM on MT4], `orders_single_row` [NM on MT5] |
| `TICKET_ORDER` | `inversions_open_time`, `inversions_close_time`, `max_backwards_seconds`, `max_backwards_seconds_close` |
| `DUPLICATE_TICKET` | `n_ids`, `identical_rows`, `accounts_in_file` [NM outside FX Blue], `open_last_trade` [NM outside TradingView] |
| `TICKET_LINKS` | `n_links`, `links_inconsistent`, `links_unresolved` |
| `CROSS_COPIES` | `n_positions`, `positions_before_period`, `copies_compared`, `entries_inconsistent`, `exits_inconsistent`, `exits_partial`, `orders_inconsistent`, `orders_unresolved`, `no_orders_table` |
| `SLTP_FILL` | `n_tp`, `n_sl`, `tp_hits`, `sl_hits`, `sl_better_fills`, `levels_cleared` |
| `PNL_SIGN` | `n_zero_gross`, `n_zero_move`, `rows_unparsed` |
| `PRICE_IMPLIED_PNL` | `n_symbols_measured`, `symbols_no_fit`, `symbols_single_row`, `symbols_quote_differs`, `accounts_in_file` |
| `PRICE_PRECISION` | `n_symbols`, `n_rows_off_mode`, `split_symbols` |
| `TIME_SANITY` | `unparseable`, `close_before_open_over_1h`, `after_report_date` [NM without a date], `backwards_within_1h`, `zero_duration`, `max_ahead_seconds` [NM], `report_date` [D / NM], `report_date_source` [D / NM] |
| `ROW_ORDER` | `direction`, `direction_rule` [D], `order_key` [D], `ties`; on a user-sorted MT4 statement also `sorted_column` |
| `MARKET_HOURS` | `symbols_measured`, `timestamps_measured`, `core_hits`, `inferred_offset_minutes`, `holiday_hits`, `window` [D, `sat13_sun08`] |
| `HIDDEN_CONTENT` | `n_hidden_cells`, `hidden_nonempty`, `hidden_rows` |
| `VOLUME_IN_OUT` | `n_symbols`, `first_negative_row` [NM when none], `pre_period_positions` [NM without Positions] |
| `STATEMENT_PERIOD` | `first_row_at`, `last_row_at`, `opens_with_deposit`, `n_accounts`, `report_date` [D] |
| `TV_INVARIANTS` | `n_trades`, `n_closed`, `n_open`, `numbering_start`, `numbering_gaps`, `rows_without_number`, `pair_shape`, `pair_values`, `cumulative`, `cumulative_examined`, `size_value`, `size_value_examined`, `size_multiplier`, `return_pct`, `return_pct_examined`, `exit_before_entry`, `time_examined`, `last_trade_excluded` |
| `NT_INVARIANTS` | `n_trades`, `n_accounts`, `numbering_start`, `numbering_gaps`, `numbering_duplicates`, `rows_without_number`, `cumulative`, `cumulative_examined`, `etd`, `etd_examined`, `exit_before_entry`, `time_examined` |
| `MONTHLY_DIGITS` | `decimals`, `last_digit_chi2`, `values_repeated_3plus`, `max_multiplicity`, `rounding_grid`, `zero_months`, `year_mismatch` (from the module docstring; no monthly fixture in the repository) |

The calibration line attached to every check with a cell:
`n`, `n_reserved`, `unexplained`, `cp95_upper_pct`, `frozen`
(`review.calibration_line`); `()` when the cell does not exist.
