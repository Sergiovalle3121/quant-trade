# Backtest audit: the service, what it measures, and how to run it

The audit is the repository's validation engine pointed at a file a client
uploads. It answers one question in six parts: *is this track record
statistically real, and what would change that answer?* It is research
tooling sold as a second opinion. It is not investment advice, it executes
nothing, it holds no funds and no keys, and it never claims that money was
or will be made. The profit-claim guard refuses any report that does.

The public figure reader at /lectura, /en/reading and /pt/leitura accepts optional
declared figures through GET without an account. It reuses the owner's numeric
parser, PublicClaim and public_card_svg, with the same bounds and daily/normal
assumptions. The win_rate parameter is a percentage. Attribution is fixed to
the person using the tool; identity and language query parameters are ignored.
Missing inputs remain NOT_MEASURED. It creates no audit class or uploaded file.
SVG attachments (download=svg), inline cards, PNG previews and sharing text stay in memory.
The share link contains the validated numeric strings and ref=lectura. Its
recipients can read those figures; browser/proxy URL history can retain them.
Results offer a separate copy-link button and SVG download. PNG download uses
the same numeric strings and referral tag, and appears only when the renderer
probe and the card conversion succeed. The copy-link field starts hidden and
is revealed for manual selection if clipboard access is unavailable.
No declarations or cards are written to the database or disk. The existing
funnel cookie recognizes lectura, without new persisted visit counters.

The calculator page has no rate limit (only its share card does, below) and
the contact page has no POST form. The
reader uses the existing in-memory AttemptLog: 60 generation attempts per IP
per sliding hour, across languages, SVG downloads and PNG previews (including cache hits).
Invalid attempts count;
opening an empty form does not. Trusted-proxy IP rules remain unchanged. The
limit is per process and resets on restart. No statistical threshold changes.
Offline coverage lives in tests/test_audit_public_reading.py and tests/test_audit_reading_png*.py.

Each reader exposes a GET `card.png` child path with the same validated numeric
parameters. A valid card's `PageMeta.image_path` uses that path, without `ref`,
identity or unknown parameters, for Open Graph and Twitter previews. An empty
form keeps the site's static image. PNG responses are 1200×630: the entire
1200×675 card scales uniformly to 1120×630, with 40 px of matching background on
each side. No text, evidence labels or warnings are cropped or distorted.
Successful images have `Cache-Control: public, max-age=86400` and no referral
cookie. Invalid or missing parameters return an empty 404; all-empty numeric
fields are valid and retain NOT_MEASURED. Rate-limited requests return 429.

`audit/raster.py` imports CairoSVG lazily and returns `None` if loading or
conversion fails. The private owner-card tool shares this renderer. The reader
then keeps its static preview and serves a short localized 503 at `card.png`.
Only successful PNG bytes enter a thread-safe LRU of at most 256 entries per
app/process, keyed by a SHA-256 digest of the language and validated numeric
strings. Page rendering warms the same cache; failed conversions are retried.
The cache resets on restart, never writes files or database rows, and cannot
prevent downstream social services from retaining a previously fetched image.
The web extra installs CairoSVG; `Dockerfile.web` explicitly installs
`libcairo2` alongside the existing WeasyPrint native libraries. Real rendering
tests use `pytest.importorskip` when CairoSVG is absent and also skip if its
native Cairo library cannot load; mocked fallback and cache tests stay offline.

The luck calculator closes the same loop. A measured result at `/calculadora`,
`/calculator` or `/pt/calculadora` previews its own card
(`audit/calculator_card.py`): a 1200×675 SVG with the reader card's palette and
Arial, fitted to a 1200×630 PNG by the same `_social_svg` and served at the
page's `card.png` child path. Every figure on it comes from
`calculator.compute`, the call the page itself makes, so the preview and the
page agree; the four inputs (Sharpe, years, configurations, frequency) are
DECLARED, the outputs are computed from them, the footer is NOT_MEASURED and
the card says it is not an audit; no p-value is shown. `share_values` turns the
validated inputs into exact query strings (`repr` of each float), so the share
link reproduces the result, carries `ref=calculadora` (counted on /panel) and
"1.8" and "1.80" share one entry in a separate `ReadingPNGCache` of 256 images
keyed by those four fields. Card renders, from the page or from `card.png`,
share their own in-memory limit of 60 per IP and sliding hour
(`CARD_REQUESTS_PER_HOUR`). Past it the PNG answers 429 with
`Retry-After: 3600`, but the calculator page always answers 200 and simply
keeps the static `og-*.png`; a failed render does the same and the PNG answers
503. Invalid, repeated or unmeasured inputs give an empty 404. The PNG carries
`Cache-Control: public, max-age=86400` and never a referral or visit cookie;
nothing is written to the database or disk. Offline coverage lives in
tests/test_audit_calculator_card.py.

The free win-rate calculator (`audit/winrate.py`) lives at `/calculadora-aciertos`,
`/en/win-rate-calculator` and `/pt/calculadora-taxa-de-acerto`, all three in the
sitemap. Its GET form takes four DECLARED fields (`trades`, `win_rate` as a
percentage, `target_r`, `stop_r`) through `reading.claim_from_query`, so the
bounds and the localized 400 errors are the owner card's; repeated parameters
are refused. Every figure comes from the reader's functions:
`public_card._wilson` (the 95 % Wilson interval on the declared proportion,
trades assumed independent, a rounded rate kept as a proportion) and
`public_card.breakeven_rate`, `stop / (target + stop)`, which is the expression
the reader's card already used, extracted without change (the card's SVG is
byte-identical). The page compares the interval with break-even, says from
which size in 20–10,000 trades the lower bound clears it, and shows a table of
intervals at 30/100/300/1,000 trades and a fixed break-even table. That
"from N trades" sentence is left out when the declared sample is already above
break-even and N is larger than it (or no grid size clears it), so it never
reads as "not yet". It assumes every trade ends at the target or the stop and
measures no costs, slippage, streaks or whether the rule was fixed before the
results; missing inputs stay NOT_MEASURED. Nothing is stored: no database row,
file or browser storage. The share block (text, link and X intent) carries the
validated strings and `ref=aciertos` (a funnel tag) and appears only when both
the interval and break-even were computed, since its text names them; partial
inputs keep only the card link. A valid result's preview image and card link
reuse the reader's `card.png` and its 60-per-hour limit; the calculator itself
has no limit and renders no card. It is the second tool on the free tools page
(`tools_hub.TOOL_KEYS`, its JSON-LD `ItemList` and the landing band), and its
"Keep reading" list links back to that page.
Tests: `tests/test_audit_winrate.py`.

The public name is **Rigor** (the same word in Spanish and English: statistical
rigor is what the audit sells). It replaced "Contraprueba" on 2026-09-24.
`seo.BRAND` and `seo.TAGLINE` hold it; it shows in every page head, report
title and badge. A new name must pass the
guard in both languages and must not suggest verification, certification,
approval, earnings or passing a challenge (`tests/test_audit_brand.py`).

## Public figures card (`audit/public_card.py`)

`quant-trade audit public-card --json claim.json --out card.svg [--png]`
creates an accessible SVG for a public post in Spanish (default), English
or Portuguese. It does not fetch the source, inspect a backtest file, assign
an audit class, endorse the post or predict future results. All supplied
figures are `DECLARED`; calculations remain `DECLARED` and explicitly say
they are computed from declarations. Missing inputs and unsupported
approximations appear as `NOT_MEASURED` with a reason. Costs, out-of-sample
evidence and data quality remain unmeasured.

Empty source fields omit their visible attribution lines; with neither source,
one localized DECLARED line attributes the figures to the person using the tool.
The accessible source title remains. Each card includes the localized
rigorscore.com reader address at the lower right, within the 630 px preview area;
SVG dimensions and the PNG scaling described above remain unchanged.

The JSON fields are `source_handle`, `source_url`, `trades`, `win_rate`,
`profit_factor`, `sharpe` (annualised), `years`, `trials`, `target_r`,
`stop_r` and `locale` (`es`, `en`, `pt`). All numbers are optional; use a
proportion for `win_rate`, for example `0.71`, not `71`. Example:

```json
{"source_handle":"@example","source_url":"https://example.org/post","trades":45,"win_rate":0.71,"profit_factor":3.24,"sharpe":1.9,"years":3,"trials":100,"target_r":2,"stop_r":1,"locale":"es"}
```

Wilson uses the declared proportion directly, without inventing an integer
win count from a rounded post. Its interval assumes independent trades.
The coin comparison uses the same expected maximum of normals as `luck.py`,
for independent fair coins and assumed searches of 20 and 100; it requires
at least 20 trades (ten expected successes and failures). It is an
approximation, not an exact binomial maximum. Sharpe luck imports the
calculator's daily/normal assumptions and the existing sampling-variance
and expected-maximum functions: 252 observations/year, independent trials,
at least 0.1 years. It uses the declared Sharpe's dispersion when available;
otherwise it explicitly uses the zero-Sharpe null model's dispersion.
Break-even assumes each trade ends at the stated target or stop, before
costs. The 45-trade/0.71 example yields about 56.5–82.2% Wilson and 68.9%
best-of-100 coins; 100 trials over three years yields about 1.47 at declared
Sharpe 1.9, or 1.46 with null dispersion.

Inputs must be finite; counts are positive integers up to 10,000,000,
other magnitudes are bounded at 1,000,000, and years/target/stop must be
positive. Unknown or duplicate JSON fields and unsupported claim wording
in attribution are refused. Source text is escaped and never executed.
`--png` also writes a sibling PNG if CairoSVG and its native libraries are
available. Otherwise the SVG is kept and the command explains conversion
with Inkscape; no rasterizer is installed or started by the command.

Published verifications also expose `/v/{public_id}/card.svg`, using only
class, audit date, public ID and fixed copy from the verification allow-list.
The class sentence follows `report_kind` (`class_text(overall, locale,
kind=...)`), so an account history or a fund reads its own C and D wording;
the kind ("what was audited") and the data period's first and last dates go
only in the SVG's `<desc>`.
Their per-publication Open Graph/Twitter image URL is
`/v/{public_id}/card.png`. For a backtest it serves the existing class PNG for
compatibility with image consumers, without a runtime rasterizer. It contains
the class and fixed notice; the SVG additionally shows date and ID. The
Portuguese PNG retains the existing English class-asset fallback; the SVG is
Portuguese. The static class PNGs call the upload a backtest, so for an
account history or a fund's track record `card.png` renders the SVG above
with `raster.card_png` (optional CairoSVG, the render kept in a bounded
in-process cache) and, when no renderer is available, serves the site's
generic card (`og_image_name("", locale)`), which has no class sentence. The
cache headers are the same in every case. Both image routes
use the page's publication gate. As required by `AGENTS.md`, a published
verification survives retention purge; a missing retained view returns 410,
and a withdrawn publication returns 404. This deliberately follows the
repository lifecycle rather than making every purged publication return 410.

## The landing for someone about to pay (`pages.landing`)

The landing is short, for someone about to pay for a prop-firm challenge or a
robot: the first screen (headline, lead, button, the price after the free first
report from settings, "your file is never published"), the sample report's
finding, who it is for, how it works, the prices, "who is behind it", six
questions and the closing call. Its link to the questions page reads "more
questions": that page answers the landing's other questions
(`faq.landing_only_questions`), so none of them leaves the site. The first
screen never mentions a card: a card
check is offered only on a report whose free unlock was refused
(`account_pages.report_box`). The headline and the button are there from the
first paint; only the illustration rises in, and `[data-reveal]` fades in
without blur. The closing call keeps `id='subir'` for links shared as
`/#subir` and links the free tools; the footer links the institutional review.

"Who is behind it" (`pages._founder`) shows only when `AUDIT_OPERATOR_NAME` is
set and the founder's own photo is at `audit/static/fundador.jpg` (served only
while it is there, `theme.OPTIONAL_STATIC_FILES`): the photo is the founder's
approval of the text, so the repository ships none. Until then the questions
end with what Rigor does not do, one line with `AUDIT_OPERATOR_NAME` and
`AUDIT_OPERATOR_ADDRESS` (or its `_EN`/`_PT` wording) when both are set, and
the WhatsApp line with `AUDIT_CONTACT_URL` (`tests/test_audit_landing_compra.py`,
`tests/test_audit_landing_trust.py`). That line (`pages.OPERATOR_LINE`) reads
"Responsable del servicio", "Service operator" or "Responsável pelo serviço",
never the block's heading: without the photo, "who is behind it" is nowhere on
the page.

`/precios` shows the plans as cards (first report, one report and, when on
sale, the pack, each button to the upload page and none to a checkout) and one
list of what every full report includes; prices drop ".00" on the page and
keep two decimals in the Product JSON-LD.

## Portuguese pages (`audit/portuguese.py`, `/pt`)

The landing, its prices and its questions exist in Portuguese (Brazil and
Portugal) at `/pt`, and every case page at `/pt/para/<slug>` with its own
Portuguese slug (`Audience.slug_pt`; a Spanish or English slug under
`/pt/para/` moves there), and every export guide at `/pt/guias` and
`/pt/guias/<slug>` (`Guide.slug_pt`; the guides name the Portuguese form
fields). The language switch on these pages offers the other two languages.
The methodology (`/pt/metodologia`), the report check (`/pt/comprovar`) and
the comparison of two or three reports (`/pt/comparar`) have Portuguese pages, linked
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
A web page may hold at most 100,000 table rows (`MAX_HTML_ROWS`, two per
trade at the trade limit) and 1,500,000 table cells (`MAX_HTML_CELLS`; a
MetaTrader report at the size limit holds about a million); both are counted
before the page is parsed,
so a longer page is refused at once (`too_many_rows`, in ES, EN and PT). A
list with one trade per row counts the rows that have both times, a quantity,
both prices above zero and, when the file has them, a readable side and
result, before reading any date, and refuses with `too_many_trades`
when they pass 50,000; a 60,000-trade web table is now refused in about 6 s
instead of 9 s, most of it reading the page itself.
A larger optimisation export is refused with what to do instead: optimise
again with the genetic algorithm or narrower ranges, or upload the report alone
and type the pass count in "Configurations tried" (then DECLARED).
A forward export whose Forward Result cell is blank or not a number on some
passes is still read as a forward export: those passes are left out of the
forward review, and the plateau check never reads its Profit column.

A platform report dropped in the equity field by mistake (an `.htm`,
`.html` or `.xlsx` name, or HTML content, UTF-16 included) is read as the
report instead of failing as a malformed CSV; so is a Myfxbook, MQL5 or FX
Blue account CSV, and an account statement sent alone in the optional live
box is the main file (an empty one is named as the live statement). It is
promoted only when no file was chosen in the report or curve box: a report or
curve that arrived with a name and 0 bytes keeps its own "arrived empty"
refusal instead of being replaced by the statement. A CSV the parser cannot read
is explained in the form's language (header row, same number of columns),
without the parser's English message.

### Whose strategy it is (`audit/ownership.py`)

An optional field under the trials, "¿De quién es esta estrategia?" / "Whose
strategy is this?" / "De quem é esta estratégia?", offers four answers: "Es
mía (la desarrollé o la opero yo)", "La compré o la voy a comprar / copiar",
"Soy el proveedor y la muestro a otros" and "Prefiero no decirlo", the
default. An answer is stored as `declared.ownership` (`own`, `buyer` or
`provider`, tagged DECLARED, listed with the other declarations in the
report); "Prefiero no decirlo" declares nothing and the key is absent. A
refused upload keeps the answer like the other declarations (the form's
`carried` values and `mapping.CARRIED_FIELDS`). An unknown value is refused
as an invalid declaration.

The answer changes only to whom the sentences speak, never the order of the
sections, a figure, the class or a tag:

- `buyer`: the wording as it was, with the questions to put to the seller.
- `own`: developer actions. "Qué hacer ahora" asks to test the settings on
  data the optimiser never saw (reoptimise without the last months and
  declare the cut-off as the out-of-sample start: only a declared start
  measures that test, and a forward export has its own section in
  `forward.py`, so a forward export already uploaded is not asked for
  again); once a declared out-of-sample stretch was measured and fell short,
  to validate on later dates, since reoptimising on a stretch already seen
  does not make it unseen data. It asks to cut the trials in the next
  version only when more than one was declared or counted: an undeclared
  count was taken at 1, the most favourable case, so the step asks to
  declare it and says that a longer history, not fewer trials, can change
  the deflated Sharpe (`ownership.trials_step`). When the backtest has a
  trade list and no live comparison is measured, it asks to run the robot
  on demo until it has `MIN_LIVE_TRADES` closed trades and upload that
  history; with fewer than `MIN_BACKTEST_TRADES` closed trades in the
  backtest the step names both minimums of `live.compare_live` instead
  (`ownership.demo_step`). The questions section becomes "Preguntas que
  deja abiertas este informe", each question with what answers it.
- `provider`: what clients will ask on seeing the report ("Te van a
  preguntar…") and what to provide for each question (the equity curve with
  floating results, the closed accounts, the tester's HTML report, the
  optimisation XML...).
- no answer: a neutral wording that serves all three; the buyer's wording is
  never the default.

The voice covers "Qué hacer ahora" (and the PDF cover's first steps, a
fund's included), the questions section and its title in the lock box, the
plan's actions and titles that sent the reader to a provider or manager
(`ownership.PLAN`), the lines that named the seller (live account at the
edge, the pairing with too few matches, the crises, the luck table, the
account without a floating figure, the evidence legend) and the meanings
that sent the reader to someone: an unmeasured out-of-sample stretch on an
account history or a fund, and a weak multiplicity (with its wording for a
fund and for an undeclared count). Outside the buyer's voice the questions
list only what the files do not answer yet (`ownership.open_questions`): the
modelling question, asked of every backtest, goes when the tester report
already states a mode `testdata.py` recognises, asks about a rerun when a
red flag says the mode or the history's quality falls short, and asks for a
report that prints the mode when the uploaded one prints none we recognise;
the buyer still asks the seller to confirm the header. The landing describes
that section for every reader ("las preguntas que el informe deja
abiertas"), not as questions for a vendor. Each text keeps the buyer's wording
where it was and lists only the voices that differ, in Spanish, English and
Portuguese side by side; `tests/test_audit_ownership.py` checks that the
developer and neutral reports say neither "vendedor", "proveedor" nor "si
compraste" (nor their English and Portuguese), that figures, class and tags
are identical across voices, and that every new text passes the guard. The
public verification page and its cards never read the answer. The public
sample (`/ejemplo`) declares `own`, so it shows the developer's actions; the
signal sample (`/ejemplo-senal`) declares `buyer`, so it speaks to a copier.

#### The message for the seller (`audit/seller_message.py`)

A buyer of a signal asked for "the questions for the seller in a message ready
to copy into the MQL5 or Telegram chat, with the key figures and the costs in
pips". With `buyer` declared, the questions section of the full report ends
with a block "Mensaje para el vendedor" / "Message for the seller" /
"Mensagem para o vendedor" ("... para el gestor" for a fund's monthly
record): a read-only text area and a "Copiar mensaje" button that is the
site's `data-copy` button (`static/app.js`, hidden until the script runs; no
new script). The text is plain, in the report's language, and built only from
the report (`report._seller_message`):

- a neutral greeting ("Hola. Revisé los archivos de esta estrategia con Rigor y
  me quedaron algunas preguntas.");
- the class ("Clase del informe: C (A es la más alta, D la más baja).") and
  the dimensions that fail or are weak, by the report's names, with their
  status in words ("Costos (no supera), Número de configuraciones probadas
  (débil)"), or "ninguna", then the dimensions not measured ("Dimensiones sin
  medir: Costos, Fuera de muestra, Benchmark."; one that does not apply is not
  listed). A class B from a curve alone is B because pieces are missing; without
  that line it would read as "only one weak point";
- two to four key figures, each with its evidence tag in words
  (`report._seller_figures`): the break-even cost as the summary tile gives
  it (basis points per side, then the pips of PR 479 and the money per lot
  when measured, or "ya pierde sin costo extra"; a backtest without trades
  says "no medido" with the costs' reason; a fund and a table of gross and
  net period returns, which have no cost per trade, have no such line), the
  live account against its backtest when one was uploaded (its badge and both
  shares of backtest histories its section gives, net result as low or lower
  and fall as deep or deeper, since either decides the badge; a share short of
  none or of all reads "<1%" or ">99%", never "0%" or "100%"; or "no medido"
  with the reason), the trials used in the deflated Sharpe (an undeclared
  count says "no medido" with the engine's note, not the 1 it was computed
  with) and the maximum drawdown, with the platform's drawdown with open
  trades beside it ("según el informe de la plataforma", declared) whenever
  the summary shows that red tile. At least two lines carry a measured or
  declared figure: when the files gave fewer, the summary's Sharpe, total
  return or drawdown p95 complete them with their own tag, and past four
  lines the last "no medido" one makes room;
- the open questions (`ownership.open_questions`), numbered. The stored
  questions that speak to the buyer ("Pide el archivo de optimización", "¿Son
  los de su bróker?") are put to the seller in `seller_message.SELLER_ASK`
  ("¿Puedes enviar el archivo de optimización?"); the stored ones are
  unchanged and the section above keeps them;
- "Gracias de antemano.", the public page
  (`https://rigorscore.com/v/<id>?ref=vendedor`, with `lang=en`/`lang=pt`)
  only when the report is published, and "Informe hecho con Rigor
  (rigorscore.com)". `vendedor` is a tag of `funnel.REF_TAGS`, so `/panel`
  counts the visits the message brings.

The text stays under 4,000 characters as a chat counts them (UTF-16 code
units; Telegram takes 4,096). When the questions do not fit, the last ones
are left out, the text ends its list with "Quedan N preguntas más en el
informe." and a note under the text area says how many it carries. No
"verificado", "certificado", "aprobado" or promise: every text passes
`guard.find_claims`.

Only the buyer gets the block. The developer's and the neutral voice send
nobody to a seller, and the provider's questions section already reads, item
by item, "Te van a preguntar: «...» Aporta ...", which is what a "lo que te
van a preguntar" text would repeat, so the provider gets no second block.
The locked preview does not render it; its lock box lists "Un mensaje para el
vendedor con esas preguntas, listo para copiar" right after the questions,
for the buyer only. The block is `no-print`: the PDF (the page under the
print stylesheet) leaves it out and keeps the questions.
`tests/test_audit_seller_message.py` covers the three languages, the figures
against the report's own helpers (a badge decided by the fall, the tail
shares, the platform's drawdown, a curve alone, period returns), the
unmeasured dimensions, the other voices, the public link, the lock box, the
trimming, a fund and the PDF.

### Dates and numbers in a hand-made file

The curve, trades, benchmark and variants CSVs (`audit/schema.py`) and the
universal list of trades (`audit/universal.py`) read a customer's own
spreadsheet, so the order of day and month and the decimal mark are decided
from the whole file, never cell by cell:

- **Day and month.** A date written year first (`2024-03-15`), with a month
  name or as an epoch number is read as it always was. For numeric dates
  (`15/03/2024`, `15.03.2024 10:30`, `3-15-24`) the order is settled once per
  file (`schema._day_first`): a first number over 12 anywhere makes the file
  day/month/year, a second number over 12 makes it month/day/year, and a file
  holding both is refused (`mixed_date_order`) with the two cells named. When
  every date reads both ways (all days 12 or less), the order under which the
  dates stay in sequence and evenly spaced (largest gap at most `REGULAR_GAP`
  times the usual one) is taken only when the other order breaks them: its
  dates run backwards, or they fall into short runs with a jump of about a
  year between them (over `BROKEN_GAP` times the usual gap and at least
  `YEAR_JUMP_DAYS` days), which is what a monthly or quarterly series looks
  like read the wrong way round. Otherwise the file is refused
  (`ambiguous_date_order`) and asked for year-month-day: so are twelve
  monthly rows on the 1st, the first twelve days of one month, and a file
  with a few days a month whose holes would otherwise hand it to the wrong
  order (Mar 1-3, Apr 4-6, May 7-9, Jun 10-12 reads as a monthly series the
  other way round). Refusing beats guessing there, even when one order is the
  customary one. A list of trades decides from its entry and exit columns
  together, and an order under which a trade closes before it opens is out.
  A day-first column is read in one pass (the numeric day/month cells day
  first, every other cell as before); only a file whose every date reads
  both ways is parsed twice more to settle the order. The order taken is
  stated in the report's reading notes ("dates read as day/month/year",
  "fechas leídas como día/mes/año", "datas lidas como dia/mês/ano"), a
  factual note with no evidence tag. Platform exports keep their own readers
  (`importers._parse_times`, which asks for year-month-day when a day/month
  column is ambiguous and no other column settles it).
- **Decimal mark of a `;` file.** The universal list of trades used to take a
  decimal comma from the semicolon alone, which read `109.48` as `10948`. The
  mark now comes from the mapped amount columns (`universal._semicolon_decimal`):
  a cell that settles its mark by itself (`109.48`, `109,48`, `1.234,56`,
  `1,234.56`, `1.234.567`, `0,001`, `1234,567`) decides for the file, and a
  cell that reads both ways (`1.234`, `1,234`) takes the file's mark. Cells
  settling both marks refuse the file (`mixed_decimal_marks`); no settled mark
  while some cell reads both ways refuses it too (`ambiguous_decimal_mark`),
  with the ask to write numbers as `1234.56`. That second refusal also meets
  a `;` list whose every marked number reads both ways: index points with a
  thousands dot (`128.450`, as a WIN trader writes them) or a three-decimal
  price with a decimal comma (`149,123`), whole quantities and no other
  decimal cell. The semicolon alone used to make those a decimal comma
  (`128450`, `149.123`), which is the usual meaning; taking that prior back
  for `;` files when nothing settles the mark is one line in
  `_semicolon_decimal` and the owner's call, since it is a guess. Whole
  numbers need no mark. A
  comma- or tab-separated file is read as before (a decimal point, with a
  cell that plainly uses a decimal comma read as such). The curve reader's
  own column rule is unchanged (below, "Portuguese curves").
- **A ratio that could not be computed.** With fewer than three returns, or a
  zero variance, the performance table's Sharpe is `NOT_MEASURED` with the
  reason the significance section uses ("fewer than three returns", "zero
  variance"); the Sortino likewise with fewer than three returns, and the
  benchmark section's two Sharpe ratios the same way. Before, they printed
  a measured `0.00`. The class does not depend on them.

`tools/rigor_reading_regression.py compare --base-src <other checkout>/src`
(`--extra <folder>` adds a local folder of files) audits every file of the
repository (the importer fixtures, the example upload, every synthetic
generator of `tests/audit_fixtures.py`) plus the new reading cases under
two source trees and lists every field that differs;
`tests/test_audit_reading_rules.py` freezes what `main` at c6ce500 read
from each repository file and checks it still reads the same.

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
The MT5 Deals header is also read in Traditional Chinese (from a real XLSX
export). When a Deals header is in a language not read, the column layout
(with or without the Fee column) is the one whose Balance chains: each
Balance equals the previous one plus the row's profit, commission, fee and
swap. A row's width alone does not decide it, because a workbook can carry a
blank trailing column that would otherwise shift the Balance into the profit.

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
an OpenDocument spreadsheet (`.ods`, LibreOffice; recognised by its `mimetype`
member) is read like an Excel workbook, with the standard library only and the
same member, inflated-size and cell limits: numbers, currency and percentages
come from the cell's stored value, dates and times from its ISO value, and the
blank rows and cells a sheet repeats to its edge are never laid out (a repeated
row with values counts toward the cell limit). It goes through the same
detection and column screen as a workbook, so no layout is guessed. An
Excel 97-2003 workbook (`.xls`, an OLE2 compound file) is read the same way
with xlrd 2.x (the web extra; it reads only this format and never runs
macros), with no formatting, each sheet loaded on demand and unloaded after,
the same cell and column limits, and date cells turned into ISO text in the
workbook's own date system (1900 or 1904). If no importer knows the sheet,
the column screen offers its columns. Files that
cannot be read are refused with how to get one that can: an old binary
Excel workbook that is damaged, encrypted or not a workbook (`legacy_xls`:
save it as .xlsx or CSV), an OpenDocument file
that is not a spreadsheet (`opendocument_sheet`), a PDF statement whose table
cannot be read with confidence (`pdf_statement`: download the CSV, Excel or
HTML history), and a zip with none or several exports (`zip_contents`).

A PDF statement (`audit/pdf_tables.py`) is read only as a ruled table
(pdfplumber's line strategy, web extra) and only through the column screen:
it is never matched to a known platform, the upload is answered with
`pdf_columns` and the screen shows the rows with a notice (ES, EN, PT) that
they were rebuilt from a PDF and should be checked; a saved column choice is
never applied to a PDF without showing it. The audit read from it carries
`PDF_ROWS_WARNING`. The report, public verification details and comparison
cards label these PDF uploads as PDF even when their rows were mapped through
CSV columns; the public page receives only a PDF-origin flag, not parser
warnings. The extraction runs in a child process killed after
10 s, with 1 GB of memory and 10 s of CPU; at most 30 pages, 20,000
characters per page and 200,000 table cells in all. The table's pieces are joined across pages only when
they all have the same columns (a header repeated on each page is dropped);
a header with fewer than three named columns or a repeated name, text laid
out without rules, a scanned page, or any data row filling less than 60 % of
the named columns (a row cut by a page break) refuses the whole file with
`pdf_statement`: a refusal costs less than a misread trade. The rows are read
with a dot as the decimal mark, as a web page's are. An Interactive Brokers Flex Query statement in XML (its
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

Revolut's stocks account statement (`Date, Ticker, Type, Quantity, Price per
share, Total Amount, Currency, FX Rate`, rows as reproduced from a real file in
github.com/antonioaversa/taxes) is read by the universal fill reader:
`BUY - MARKET`/`SELL - LIMIT` are the sides, cash rows (top-ups, custody fees,
dividends) have no price and are dropped, and a `STOCK SPLIT` row
(`universal.SPLIT_WORDS`) rescales a long position's open lots by the shares it
adds or removes, keeping their cost (a 1-for-10 reverse split of 100 shares
arrives as -90); a split of shares not held changes nothing, and one that would
leave no shares is not applied and is counted in `SPLIT_EMPTIES_WARNING`. Prices in USD print without a sign, like every amount.

A column whose name holds `%` (`Profit %`, `% Profit`, `% chg`) never takes a
role in the universal reader: it is a ratio, and once normalised `Profit %`
would read as the money result.

An equity curve or return series (`schema.parse_equity_csv`) takes a return
column named with a `%` (`Return %`, `Rendimiento %`, `Retorno (%)`) and reads
it as percentages, whatever the size of its values (a money-market fund's
`0.03` is 0.03 %, as factsheet grids read it). `Data` is a Portuguese date
column, taken only when no `date` or `fecha` column exists. Spanish and
Portuguese curves are read by a fund's value per share (`Valor da cota`,
`Valor cuota`, `Valor cuotaparte`) or, without one, the balance column `Saldo`
(after the English names, so `equity` or `balance` wins when both exist).
`Patrimonio`/`Patrimônio` is not read on its own: in a fund file it is the net
assets, which move with subscriptions and redemptions, so it goes to the
column screen. A column whose
numbers plainly use a decimal comma (`10.000,50`, `1,5`) is read that way
throughout (one plainly decimal-comma cell decides the column, so a `1,234`
beside `1,5` reads 1.234); `10,000.50` and an ambiguous `10,000` keep the comma
as thousands.
A column that also holds a plain decimal dot (`10234.56`, `0.5`) keeps the dot
reading, and a cell there that plainly uses a decimal comma is left unread (an
unreadable row) rather than rescaling the column. Currency signs and codes
(`$`, `R$`, `US$`, `€`, `£`, `¥`, `₹`, `USD`), spaces and the Swiss `'` are
dropped; `(1,5)`, `1,5-` and a Unicode minus read as negatives.

Zerodha Console's tradebook (Reports > Tradebook, CSV: `symbol, isin,
trade_date, exchange, segment, series, trade_type, auction, quantity, price,
trade_id, order_id, order_execution_time`, header as checked by the open-source
github.com/prabusw/beancount-importers-india importer) is read by the universal
fill reader. Fills are timed by `order_execution_time`, ranked above the
date-only `trade_date`, so intraday trades pair in the order they happened
whatever the row order. A clock-only execution time joins `trade_date`, and a
blank one falls back to `trade_date` at the start of that day
(`universal.DATE_ONLY_FILLS_WARNING` counts those fills, since their order
within the day is unknown). No F&O lot multiplier is applied (the result is the
price move times the stated quantity, and the report says so). The XLSX
download is not named: its layout is unconfirmed.

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

### Comparing two or three reports

`/comparar` (Spanish), `/compare` (English) and `/pt/comparar` take the links
of two of the customer's own reports, plus an optional third (`link_c`, the
pack of three audited side by side), and show them one column per report:
class, period and file format, the six dimensions and the executive-summary
figures (`audit/compare.py`, `comparison_body(results, hrefs=..., locale=...)`,
two or three results, `compare.MAX_COMPARED = 3`). A figure is in bold
("distinta") when it is not the same in every report. Every unlocked report
has a small form that fills in its own link (the second field only). Rules:

- the links travel in a POST body, never in a URL, so no token reaches a
  log line; the id and token are read from each pasted address and checked
  exactly like the report page (wrong token: 404, the same report more than
  once or an unreadable link: 400; an empty third field compares two);
- only paid reports (or any report in free mode) can be compared: if any of
  the two or three is locked the answer is the same 402 and no figure is
  shown;
- the break-even row has one fixed name in every report, "Costo extra que lo
  lleva a cero (pb por lado)" (`compare._breakeven_row`), and each cell carries
  that report's own detail (`compare._breakeven_cell`): "8.00 · 12.3 pips" (a
  JPY pair's pip is another scale), "8.00" without pips, or "0 · ya pierde sin
  costo extra" when the report already loses before any extra cost, with the
  evidence of every number the cell shows. The report tile's name carries the
  pips; used as the row's key it split the row in one per report and tagged
  "No medido" figures that were measured;
- with two reports the body is otherwise byte for byte the two-column one it
  was (`tests/test_audit_compare_three.py` rebuilds the old layout and
  compares; the break-even row above is the one deliberate change); with
  three the cards, the dimension table and the figure table get a third
  column (`cmp3`; three cards in a row above 860 px, stacked below, and the
  tables scroll inside their box on a narrow phone), and the page title is
  "Tres informes, lado a lado";
- the change summary (`comparison_delta.change_summary`) is still between
  two reports. With two it follows the cards, as before. With three it is
  shown only when all three are versions of one strategy, which is how the
  code already says that reports are versions of one system: the signed-in
  account filed the three in the same strategy of "Mis estrategias"
  (`web._same_strategy`). Then there is one summary per consecutive pair,
  1 to 2 and 2 to 3 (`numbers=(1, 2)`, `(2, 3)`: "Qué cambió del informe 2
  al 3", report numbers in the reasons and unique section ids). Otherwise it
  is left out and a fixed line says why (`compare.COPY[*]['summary_three']`).
  Visitors who are not signed in, or whose account did not file the three
  together, see the three columns without it;
- the page is private (`noindex`), passes the profit-claim guard and says
  that a class difference shows which tests changed, not that one version
  will work better.

The existing account picker (`/cuenta/comparar`, `/account/comparar`,
`/pt/conta/comparar`) uses the signed-in customer's report list; it never exposes
tokens or consumes credits. It takes two or three ticked reports (`?id=` repeated,
in the order shown; the same id twice, four or more, or one not complete goes
back to the list with `compare_pick`), and that address, with the three ids,
is the one the language switch links and that opens the same comparison
again. A new stored-evidence summary shows the class change,
which dimensions changed result, and flags that appear or are absent in report 2.
An absent flag can reflect missing data, not a resolved risk. Classification and
tests retain their own reports' declarations, including attempts and costs.

Numeric differences are arithmetic (report 2 minus report 1), not significance
tests or predictions. Sharpe and drawdown differences require both figures to be
finite and `MEASURED`, the same timezone-aware start/end, positive measured
frequency within `1e-6` relative tolerance, the same frequency label, and the
same closed-balance/equity basis. Missing or incompatible context shows
`NOT_MEASURED` while retaining the side-by-side figures. Drawdown differences
use percentage points. All text exists in ES/EN/PT and passes the claim guard.
Paid/full-report rights remain readable if an email later becomes unconfirmed;
unconfirmed welcome previews and locked reports do not enter the comparison.

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
variety to show. The class stays C. Its header prints what an MT5 tester
report prints and the importer reads: "History Quality: 100% real ticks"
(`SAMPLE_HISTORY_QUALITY`; the test-data section shows real ticks and 100 %,
DECLARED, and the modelling question is answered for the developer) and
"Equity Drawdown Maximal" and "Relative", the drawdown with the open trade
counted: each trade's deepest floating loss is the low of a Brownian bridge
from its entry to its exit with the trades' 25-pip spread, drawn from its
own stream (`_floating_low`), so no trade, class, flag, challenge, ladder or
size figure changes. It reads 1 570.26 (5.78 %) and 8.76 % (1 008.99),
against 8.22 % on closed trades: the report adds "Drawdown con operaciones
abiertas (tu plataforma)" (DECLARED), the capital section shows the
platform's fall in money as a floor (below the resampled reference, so no
capital figure moves) with its open-loss line, and the rows read grow by
three.

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
  whose strategy it is, the reference cost assumed when the client declares
  zero). Not verifiable.
- `NOT_MEASURED`: could not be computed from what was supplied; the reason
  is stated next to it.

On the site's pages (landing, upload form, guides, methodology, verification,
contact, terms, privacy) and in the HTML and PDF reports a reader sees these tags as words in
the page's language: Medido / Declarado / No medido, Measured / Declared / Not
measured, Medido / Declarado / Não medido (`report.EVIDENCE_LABELS`). The codes
stay in the JSON, the Markdown report and the badge CSS classes.

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
  computes it another way). With fewer than three returns or a zero variance
  it is `NOT_MEASURED` (no figure), never a measured 0.
- Year by year: each calendar year starts from the previous year's last
  value, so the yearly returns compound to the total. A first year that
  holds only the starting point (a fund record's opening value dated
  31 December, or a curve that starts on a year's last day) has no return
  in it and is left out of the table (`engine._subperiods`); before, it
  showed as a year of 0.0 %.
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
  a pip is 0.01 on yen pairs, else 0.0001). Indices and other symbols stay in
  basis points only.
- Costs in pips by symbol: when the trades are on more than one symbol and
  at least one is such a pair, `costs.pips_by_symbol` lists each pair and
  each metal (`crises.symbol_market`: XAU, XAG, XPT or XPD against one of
  those currencies), most traded first: `{"note", "rows": [{"symbol",
  "trades", "median_entry_price", "pip_size", "break_even_pips",
  "reference_pips"}], "others"}`. An exchange prefix is dropped first
  (`OANDA:XAUUSD` is XAUUSD, `FX:EURUSD` is EURUSD, also for one pair).
  Each pair's figures are the same formula as for one pair
  (`bps / 10,000 × median entry price / pip`) with that pair's own median
  entry price: the break-even is the whole history's (`break_even_bps`),
  converted, not a break-even of that pair's trades alone, and the note says
  so. The repository defines no pip size for metals, so a metal's row has no
  `pip_size` and its two figures are NOT_MEASURED ("no pip size is defined for
  metals; this symbol's cost stays in bps"). Every other symbol traded
  (USDMXN, US30, BTCUSD...) is named in `others` (`{"symbols", "note"}`,
  most traded first), and the report prints that note under the table:
  "other symbols traded (USDMXN, US30) stay in bps: the audit defines no pip
  size for them". The key is absent with one pair (the three keys above say
  it) and when no pair is traded: a history of gold alone, or of gold and
  silver, has no figure in pips to show.
- Costs per lot: `costs.break_even_per_lot` is the extra cost per lot and
  side at which the ledger nets to zero, MEASURED only for the formats whose
  volume is the platform's lots and whose rows print each trade's result in
  money (`importers.LOT_FORMATS`: MT5 tester and history, HTML or XLSX; MT4
  tester and statement). It is the net the file prints for the closed trades
  (each row's profit after the commission and swap the report itemises, the
  same net as the stress tile's "with all") divided by twice the lots traded
  (each trade buys and sells its volume); the note gives both figures so it
  can be checked by hand against the file, and `costs.per_lot_currency` is the
  account currency (null when the file does not state it: the note then says
  "in file units"). Any other format is NOT_MEASURED ("the money per lot is
  given only for MetaTrader 4 and 5 reports, whose volume column is the
  platform's lots"): Myfxbook, FX Blue and MQL5 files print a volume too, but
  no contract size is assumed for them. The lots of several symbols are added
  only when every one is a pair of two of the currencies above (a broker
  usually quotes its commission per lot of any of them), and the note then adds "the
  lots of the 2 currency pairs are added as the platform prints them"; with a
  metal, an index, a coin or any other symbol among several it is
  NOT_MEASURED ("... a lot of gold is not a lot of EURUSD, so their lots are
  not added together").
- In the report, the executive summary's break-even tile reads "(bps per side;
  1.7 pips)" with one pair, "(bps per side; ≈ 4.3 pips on EURUSD / 5.0 pips on
  GBPUSD)" with several (the three most traded), and adds "52.54 USD per lot
  and side" when the per-lot figure is measured; the basis points stay the
  figure. The costs section adds a table "In pips, by symbol" under the
  re-costed ledger. The improvement plan's costs step quotes those figures
  when the break-even is above zero and then drops the generic "on EURUSD at
  1.10, 1 bp per side is about 1.1 pips": it names the table's symbols, metals
  included, when they are every symbol traded and no more than three, and
  says "on each symbol you trade" otherwise. With a break-even at or below
  zero it quotes no figure of its own and keeps the generic line.

### The variance policy behind the deflated Sharpe

DSR needs the variance of Sharpe estimates across the trials that were run.
A client rarely uploads them, so the audit uses
`max(observed across uploaded variants, sampling-variance floor)` where the
floor is the sampling variance of the Sharpe estimator itself,
`(1 − skew·SR + (kurt−1)/4·SR²)/(n−1)`: unskilled trials disagree at least by
sampling error. With this floor, the best of 100 unskilled random walks has
a PSR near 0.99 and a DSR near 0.5 at 100 declared trials, which is the
behaviour the test suite pins.
When neither a declaration nor an uploaded artifact supplies a trial count,
the one-trial DSR is only a favorable bound. It may still establish a weak or
failing result, but it cannot by itself pass the multiplicity dimension or
award class A; multiplicity stays `NOT_MEASURED` if that bound would pass.
An uploaded variant count is an observed lower bound, not proof that no other
configurations were tried.

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
- `drawdown_risk`: stationary block bootstrap of
  the uploaded returns (expected block: `resample_block`, see below) over one year, 2,000 paths by default, capped at
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
- `resample_block` (both simulations): the expected block is the larger of
  5 periods and the Politis–White (2004) block length with the Patton,
  Politis and White (2009) correction (`block_length`), measured on the
  file, when its returns cluster (flat-top long-run variance above the plain
  variance); returns that are independent or alternate keep 5, which keeps
  their numbers unchanged. The block is capped at a quarter of the history
  and recorded in `method.expected_block_size`. Before, a fixed 5-period
  block broke up the losing runs of trend-following daily curves and
  smoothed fund values, so their resampled drawdowns and challenge failure
  odds came out too mild. On AR(1) returns the measured block is within
  about 30 % of the theoretical optimum. Informational: neither simulation
  feeds the class. The seed is unchanged, so a file gives the same numbers
  on every run.
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
  gives way to one sentence (and, for all failing, the most common reason);
  with programs left out for their markets the sentence says "every
  simulated program" and the left-out programs are still listed under it,
  each with why. A program where no path fails reads "Nothing in the
  simulations". When the balance hides open losses, the table repeats that
  its figures are optimistic; and since each row carries its own rules, a
  row whose own total loss limit (the smallest of its phases) the
  platform's drawdown with open trades already reaches says so under the
  program's name, with the same comparison as the chosen program's
  open-loss line (`_row_open_loss`). On the public sample (-8.76 % with
  open trades) that marks The5ers Hyper Growth (6 %), FundedNext Stellar
  1-Step (6 %), Stellar Lite (8 %) and The5ers Bootcamp (5 %).
  MEASURED under the simulator's assumptions; it compares rules and never
  recommends buying a challenge. No class change.
  Each row carries `rules` (one entry per phase: target, daily loss and its
  basis, total loss and its type, minimum days, time limit, best-day rule,
  copied from `prop_presets`) and the report folds them under the program's
  name with "rules read on {as_of}" and a link to `source_url`; a field a
  program does not have is left out. The `<details>` is served open (a
  print, a saved page and a browser without script keep the rules) and
  `static/app.js` folds it on screen and opens it again before printing,
  as it does for the report's technical details. `ChallengeRules.markets` lists what a
  program lets the trader trade only when a page of the firm says so
  (`markets_source`, `markets_as_of`): Topstep is futures only ("Topstep is a
  Futures-only program", help article 8284206), The5ers High Stakes and Hyper
  Growth list their assets on their own pages; FTMO, FundedNext and Bootcamp
  pages read say nothing, so they are never restricted. What each symbol
  can be traded as comes from `crises.symbol_market` and
  `firmfit.symbol_venues` (`SYMBOL_MARKETS`: a pair against a currency,
  `EURUSD`, `XAUUSD` or `BTCUSD`, is spot or CFD and never a future, so
  gold and bitcoin pairs are treated alike; an index name, a bare coin root
  such as `BTC` or a perpetual can be either). When every symbol is known
  and a program does not take one of them, the program is not simulated
  and goes last with `market`: what the page allows and only the symbols
  (the most traded first, four at most, then "…") and markets it does not
  take, with `spot` when they are all spot or CFD pairs ("Only futures: the
  history trades spot or CFD forex (EURUSD, AUDUSD), which this program does
  not take according to its page; not simulated"); a forex and index
  history names the forex only. With symbols the audit cannot place,
  nothing is restricted. The chosen program is never left out: its section
  was simulated, so its row keeps its figures (the ladder's own) and says
  "it is simulated because you chose it, but its figures are those of rules
  that would not apply to this history" instead of "not simulated";
  `challenge.market` carries the same fit, and the challenge section, the
  ladder, the size table and the line under the verdict repeat it. `firmfit.scenario_columns`
  repeats the ladder's `out_of_sample` and `reference_cost` rungs for every
  program, named as the ladder names them: the chosen program's figures are
  the ladder's own, every other program runs `program_pass` on the same
  series at 2,000 paths per phase. A rung the ladder could not measure is
  one NOT_MEASURED line under the table with the ladder's reason. The note
  above the table says that "Passes" uses the full history with the costs
  the file already carries, without the declared or reference cost. Time
  measured with `time.perf_counter` at the production paths: about 0.8 s
  extra on the sample report and 0.6 s with FTMO 2-Step chosen (the three
  Topstep programs left out for a forex history are not simulated), under
  2 s, so the columns keep the firm table's 2,000 paths.
- `challenge.scenarios`, the challenge ladder ("¿Cuánto cambia con lo que
  encontró este informe?"): the chosen program (all its phases, through
  `firmfit.program_pass`; the generic preset is one phase) run again with
  the same simulator, seed, paths per phase and rules on other versions of
  the same history, so the full-history figure is never read alone. Each
  row keeps how many daily returns it used. The rows, in order:
  `full`, the whole history, identical to the program's row in the firm
  table (for a one-phase program, also the section's own figure; with more
  phases the row says it is the firm table's); `in_sample` and
  `out_of_sample`, the daily returns before and from the declared
  out-of-sample start, NOT_MEASURED with the holdout's own
  reason when it was not measured (no date declared, a date outside the
  series, a side too short); `reference_cost`, the curve with the cost
  section's reference cost per side (`costs.reference_bps`: the client's
  declared cost when one above zero was declared, and the row's name then
  reads "With the declared cost (N bps per side)" with a DECLARED badge;
  otherwise the assumed reference, named "With the reference cost"),
  charged with `costs.round_trip_cost` and taken off the
  balance from each trade's exit on, NOT_MEASURED without trades, when the
  curve is not money (deposits or withdrawals inside the history make it an
  index; otherwise the curve and the trades must reconcile, or the balance
  be rebuilt from the platform's deals) or when the charge takes the balance
  to zero. Only a reconciliation CONTRADICTION reads "the curve and the
  trades do not reconcile in money"; a reconciliation that was not measured
  reads "the curve was not shown to be money" followed by its own reason
  (trades outside the curve dates, an uncovered tail, a gap that flows,
  conversion or open positions could explain), and uploaded returns say
  they are not money; `luck_haircut`, the daily returns with their mean cut
  to the share of the Sharpe that the Harvey and Liu haircut of the luck
  section leaves (same spread, so the same volatility), NOT_MEASURED with
  the luck section's reason, with "fewer than 2 trials" when 1 trial was
  declared or counted in the files, and with "trial count not declared"
  when the client left it empty and no file counts it (the engine then
  computes with 1, the most favourable case, which says nothing about the
  search). A row the simulator cannot
  measure (too few daily returns) says why. The rows are scenarios of the
  same history, not predictions; the ladder is MEASURED, informational and
  changes neither the class, the dimensions, the challenge's own figures
  nor the firm table's full-history column; the firm table repeats the
  `out_of_sample` and `reference_cost` rungs for every program. The target
  column reads "Reaches the target" for a one-phase program and "Reaches the
  target in every phase" with more. When the client chose the challenge,
  one line under the verdict gives the full-history figure next to the
  lowest measured row and links to the section; when the section warns that
  the balance hides open losses (the platform's drawdown with open trades
  at or past the total loss limit, or the hidden floating drawdown flag),
  the line says its figures are optimistic too. No ladder figure reaches
  `/v`, the badge or the card. Every preset has `time_limit_days=None`, so
  "unfinished" reads as not reaching the target within the simulator's
  250 business days, the cap, never as a deadline the rules set.
- `challenge.sizing`, the size table ("¿A qué tamaño? El reto a 0.5x, 1x,
  1.5x y 2x", under the ladder): the ladder's `full` row again with every
  daily return of the history multiplied by 0.5, 1, 1.5 and 2
  (`SIZING_MULTIPLIERS`), through `firmfit.program_outcomes`, which is
  `program_pass` (same simulator, seed, paths per phase and rules, all the
  program's phases) plus how the program ends when it is not passed. JSON:
  `{"status", "program", "note", "starting_balance", "size_per_trade",
  "account_size", "rows"}`;
  each row is `{"key": "0.5x" | "1x" | "1.5x" | "2x", "multiplier", "days",
  "pass", "main_risk", "pass_within_best_day" (when the program has a
  best-day rule), "fail_daily_loss", "fail_total_loss", "unfinished"}`, all
  MEASURED. `pass` is the chance of passing every phase (the product, as in
  the firm table); the three failures count a phase's outcome weighted by
  the chance of reaching that phase (fresh starts, The5ers Bootcamp three
  times), so the four figures of a row sum to one. The 1x row is the ladder's
  `full` row itself (same `days`, `pass`, `main_risk` and
  `pass_within_best_day`). The `note` says the assumption: changing the size
  scales every daily return in the same proportion, as linear leverage does
  when the costs grow in proportion to the size (the same cost per lot) and
  the execution does not worsen with more volume. `starting_balance` is the
  balance the daily shares at 1x are measured on, as the capital section
  names it: DECLARED for a report's curve rebuilt from its trades (the
  report's balance, or the one declared on the form), MEASURED for a curve
  the client uploaded or built from chosen columns (its first value), and
  NOT_MEASURED with the value kept when the reader assumed 10,000 because the
  file states none (the importer's or the column mapping's "does not state a
  starting balance" warning on a curve built from it); the report then says
  the balance was assumed and that 1x scales with it. `size_per_trade`
  is the average lot per trade at 1x (MEASURED) when the costs section
  measured `break_even_per_lot` (MetaTrader lots that can be added): every
  trade's lots added and divided by the number of trades, which is half the
  "lots traded" the cost section divides by (it counts entries and exits);
  each row then has `average_lot`, that average times the size. Those lots
  are the balance's the shares at 1x are measured on (`starting_balance`),
  and the report says so ("0.50 lots on a 10,000 balance"): the same shares
  on another balance take the lots times that balance over this one. When
  the program names an account (`ACCOUNT_SIZES`) and the balance was not
  assumed, `size_per_trade_account` and each row's `average_lot_account`
  give the lots on that account (0.50 × 100,000 / 10,000 = 5.00 on Topstep
  100K for the sample) in a column of their own. Otherwise
  NOT_MEASURED, with the cost section's reason for mixed lots or with
  `SIZING_NO_SIZE` (lots are read only from MetaTrader 4 and 5 reports). No
  stop loss is read, so no risk per trade is given; 1x is "the size of the
  history you uploaded" (each simulated day gains or loses the same share of
  the balance as a day of the file). `account_size` is DECLARED only when
  the preset's program names one (`prop_presets.ACCOUNT_SIZES`: Topstep
  50K/100K/150K, whose dollar limits are shares of that account); otherwise
  NOT_MEASURED, and the report says the simulated rules fix no account size
  (they are shares of the starting balance or of the day's), so the table's
  shares do not depend on the account size, and, with the lots given, that
  the lots do (`SIZING_NO_ACCOUNT`). Results stored before the average lot
  keep the old `SIZING_NO_SIZE` and `SIZING_NO_ACCOUNT` sentences
  (`SIZING_NO_SIZE_BEFORE`, `SIZING_NO_ACCOUNT_BEFORE`): their translation
  rules stay, and the old reason keeps its old name ("Lot or risk per trade
  at 1x"). The intro counts every phase only for a program of several
  (`ch_size_intro_one` otherwise). The whole block is
  NOT_MEASURED, with the same reason, when the challenge or the ladder's
  `full` row is not measured, and with "uploaded returns are not money"
  (`RETURNS_NOT_MONEY`, the reconciliation's own reason) for a returns
  upload. The report shows one row per size with the chance of reaching the
  target in every phase, within the best-day rule when the program has one,
  of breaking the daily limit ("no rule" for programs without one), of
  breaking the total limit and of not reaching the target within the
  simulator's cap (the ladder's `unfinished_cap` words; "per phase" for a
  program of several phases, since each phase has 250 business days of its
  own), in the ladder's formats (`_firm_pct`). Without a deadline in the
  rules the intro adds that "reaches the target" counts only what gets there
  within that cap, so a smaller size moving simulations to "does not reach"
  is read as days running out, not as broken limits. It repeats the
  open-loss warning ("cifras optimistas") under the same condition as the
  ladder (`_challenge_optimistic`). It shows what changes with the size and
  advises none. In the locked preview its title is listed after the
  challenge simulator. Time measured with `time.perf_counter` at the
  production 5,000 paths: about 0.17 s extra on the sample report (generic
  preset) and 0.30 s with FTMO 2-Step (two phases), under 1 s, so every
  size keeps the ladder's paths. Informational: no class, dimension,
  challenge figure, ladder row or firm-table change, and nothing reaches
  `/v`, the badge or the card.
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

### Did the average return change at some point (`audit/breaks.py`)

`decay.py` compares fixed thirds of closed trades; the rolling and sub-period
views describe the curve without a test. This section asks one question of
every curve with 250 or more returns (`breaks.MIN_RETURNS`), trades or not:
is there a point where the average return shifted by more than the returns'
noise explains?

- Test: the CUSUM of the returns' deviations from their mean (Ploberger and
  Krämer, 1992), `max_k |S_k| / (sigma sqrt(n))`, with the Brownian bridge's
  (Kolmogorov) tail as the p-value. `sigma^2` is the cautious long-run
  variance: the largest of the plain one, Newey-West (Bartlett, the lag of
  `alpha.newey_west_lags`) and the plain one widened by `(1 + rho) / (1 - rho)`
  (Kendall-corrected, clipped to `[0, 0.9]`). On simulated AR(1) returns with
  t(5) shocks and no shift it passed 5 % in at most about 4.5 % of histories
  for autocorrelation 0, 0.3 and 0.6 (`tests/test_audit_breaks.py`).
- `clear` when `p <= 0.05` (`ALPHA_LEVEL`) and at least 30 returns
  (`MIN_SIDE`) lie on each side of the date; otherwise `edge` says the largest
  deviation sits too close to either end for a before and an after.
- The date is where the running sum strays furthest from its line; its
  range is Bai's (1997) 95 % interval, `11.03 sigma^2 / delta^2` returns on
  each side (`delta` the shift). On simulated shifts it covered the true date
  in about 95 % of detected cases.
- Before and after: each side's average return, annualised, with a 90 %
  band from its own cautious standard error. All MEASURED.

Informational: no flag, no class change. Limitations: a single shift is
assumed (several smaller ones read as one, a gradual drift as a date in its
middle); a small shift in a short history is often missed, which the "Sin
cambio claro" line says ("no prueba que no haya cambiado"); the date is where
the change shows most, not its cause; it describes the history only.

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

The same section lists the five deepest falls, the way a fund fact sheet
does: each runs from the last point at a high to its lowest point and ends on
the first date back at that high (or stays open at the file's end), with its
depth, the days down, the days back and the total. It also shows the Calmar
ratio over the whole file, with its span in years (the summary's compound
annual return over the depth of the deepest fall; from 365 days of history
and a deepest fall of at least 1 %, so a too-smooth curve never prints it in
the thousands), and the expected shortfall: the average of the worst 5 % of
daily returns (from 81 days, so the 5 % holds at least five, and only when
the curve has a point on most days) and of monthly returns (from 40 months,
at least two), always with how many it averages. On a fund record the
falls, the Calmar ratio and the monthly figure appear in the fund's own
section, in months. A first month that holds only the starting point (a fund
record's opening value) is the base, not a month with a return of zero. All
are MEASURED and informational: none enters a dimension, a flag or the class.

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
There it drops `ZERO_DECLARED_COSTS` (which no fund record raises now: its
trading costs are inside each month), the section shows the declaration as
DECLARED and says Rigor did not measure costs, and the report is titled
"Auditoría de historial de fondo". Anywhere else the box is ignored with a
warning and costs are checked as usual. The observation thresholds do not
change, and the costs dimension stays NOT_MEASURED.

A fund record in the verdict and the plan. With no out-of-sample start
declared, the out-of-sample reason reads "a fund's record does not say since
when its process has run unchanged" (`verdict.FUND_OOS_REASON`). The
dimension card, the summary and the plan ask the manager since when the
process has been unchanged and whether any stretch is simulated (pro forma),
not for an optimisation date or an unchanged robot. The costs step asks
whether the figures are net of the management and performance fees, instead
of a platform report. Undeclared trials read as how many funds or strategies
the same manager runs. The caps do not change: out of sample and costs stay
NOT_MEASURED, and the best class without them is B.

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
flatters a fund whose figures are before fees. When no benchmark file is
uploaded, the same index also feeds the benchmark dimension
(`engine._file_benchmark`): it is laid on the curve's own dates, the first
point is the base both start from, and it is used only when it gives a return
for every later point (else the dimension stays NOT_MEASURED). The section
then carries `source: "file"`, the overlap row says "the index the file
itself carries", and the plan step says the reference is the file's own
index. A fund that trails its own index fails the dimension like any other
upload. An uploaded benchmark file still wins, and a declared "no applicable
benchmark" still makes it NOT_APPLICABLE. A month in which the fund or its
index loses 100 % or more (most often a typo in a factsheet) leaves the
section NOT_MEASURED ("a month in the fund or its benchmark loses 100% or
more") instead of dividing by a compound growth of zero.
The index in the file is the one the manager chose to print, so a PASS
against it is not an independent check: `verdict.overall_class(own_index=True)`
lets it complete a B but never an A (a FAIL or WEAK counts as usual), and the
plan's "what would change the class" follows the same rule.

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
of the month before the window to the close of its last month, worked out
once from the month-end levels FRED shows (S&P 500 from 2016 on, the series'
start; Nasdaq Composite for every equity window; bitcoin on Coinbase for the
crypto one) and checked on `MARKET_AS_OF`. These are about a dozen fixed
historical facts about widely reported falls, cited with the FRED pages they
can be checked on; no index series is read at run time or shown beyond them
(S&P Dow Jones Indices, Nasdaq and Coinbase allow no reproduction of their
data without written permission, see "Data licences"). They never enter the
result JSON, a finding or the class. A note under the table says they are
fixed historical figures, that no other data of these indices is read or
shown, and that for a strategy trading another market (currencies,
commodities, another country) they are context, not its yardstick. For each window the
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
suffixes dropped), or a tester report names one of them, the market is
recognised but its closes are not read: FRED's `SP500`, `NASDAQ100` and
`CBBTCUSD` need the written permission of S&P Dow Jones Indices, Nasdaq and
Coinbase, and no public source we know of allows their reuse in a paid report
(`Asset.licensed` is false, so `MarketData` never downloads them). The
section is one NOT_MEASURED line: "no public source of this market's closes
that we know of has a licence that allows reuse in a paid report; to compare, upload its
closes as the benchmark file" (`holding.UNLICENSED`), or, when a benchmark
file was uploaded, that the benchmark section compares the strategy with it
(`UNLICENSED_WITH_BENCHMARK`). A benchmark column inside an equity or return
CSV (`schema.BENCHMARK_COLUMN`) is read only by the fund section; platform
statements carry no benchmark, so the separate benchmark upload is the way to
compare. The comparison below stays in the code for a market that gets a
licensed source. With one, the report puts the
strategy's closes beside the market's public closes on the same days: return, worst fall and
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
`refresh`; the service also downloads every licensed series in a background
thread when it starts (`warm`). A download reads with `read1`, so its total
deadline of 5 seconds (`TIMEOUT`) is checked after every receive and a server
that trickles bytes is cut off within about one more socket timeout; replies
are capped at 4 MB, redirects are refused (the address stays FRED's fixed
https one), and values that are not finite are dropped. Only one refresh of
a series runs at a time, and after a failure (down, slow, rate limited, not
a CSV) the series is not asked for again for 10 minutes (`RETRY_AFTER`). A network failure (a timeout or a reset connection) is read again up to twice, after 1.5 and 3 seconds, before it counts as failed (`READ_ATTEMPTS`, `READ_PAUSE`); a reply that arrives but cannot be read is not.
So that a rerun of the same file reads the same values, a reply never
replaces a kept copy it covers less of: one that ends earlier, or holds under
90 % of the kept copy's points inside the kept copy's span (`MIN_KEPT_SHARE`;
a short or truncated reply), is refused and the kept copy stays
(`_check_not_shorter`). A reply that starts later but keeps that share is
taken, so a publisher that trims its early years does not pin the kept copy
for good. Each refused or failed refresh logs one warning with the series key,
its provider and the error's class and message (at most 200 characters; no
reply body, address or key). Every monthly
series (US and local consumer prices, Brazil's Selic, the BIS policy rates;
`Asset.monthly`) must also hold each month from its first to its last once,
or the reply is refused (`_check_months`), except the gaps its publisher
leaves on purpose (`Asset.gaps`: October 2025 in US CPI, which BLS never
published, and `JAPAN_NO_POLICY_RATE`). A report built before a series is in
memory (the service's first minutes, or a series that never loaded) does not
only miss rows: an account in a currency whose own cash rate is missing, or
whose euro history is missing for pre-2019 dates, gets the US bill's cash
line and Jensen's alpha with the bill on both sides, so those figures
differ from a report built with the rate in memory.
When the closes are not in memory the section says so in one NOT_MEASURED
line and the audit goes on. The CLI's `--public-data` reads the series
first. The result JSON always carries a `holding` key: `null` when the file
trades none of these markets or public data is off.

The sample report (`/ejemplo`, `/sample`, `/pt/exemplo` and their PDFs) is
built with the same public series, so a visitor sees the lines an upload
gets without uploading a file. It reads only what is already in memory
(`MarketData.ready`) and never waits on the network: before the first
download lands, or with `AUDIT_PUBLIC_DATA=false`, it is the offline sample.
Each version is built once per language and set of series in memory and
kept. The public series move no figure of the sample, only add their lines.

The second sample, for whoever is about to copy a signal (`/ejemplo-senal`,
`/en/sample-signal`, `/pt/exemplo-sinal` and the same addresses with `.pdf`),
goes through the same route code, cache, notice, sign-up band and PDF record
(`/comprobar` answers it is the sample). Its input is the Myfxbook export of a
made-up account (`sample.synthetic_signal_statement`, seed `SIGNAL_SEED`):
twelve months of a grid robot on EURUSD and GBPUSD that adds 1.5 times the
lots every 20 pips against the basket (six entries at most), closes the
basket 10 pips past its average or 30 pips past its sixth entry, and doubles
the next basket after a loss. The market ranges most of the year and trends
against the open basket on the dates in `SIGNAL_TRENDS`; the last trend
leaves a full basket open in "Open Trades". A 1 000 deposit, a 4 000 top-up
the business day after the first losing basket and a 600 withdrawal complete
it. It is uploaded as a copier would (trials, cost and out-of-sample blank,
ownership `buyer`), and the current engine raises MARTINGALE_SIZING,
GRID_AVERAGING, DEPOSIT_DURING_DRAWDOWN, FLOATING_LOSS_AT_END and
GAIN_INFLATED_BY_FLOWS on it, all at WARN; `tests/test_audit_signal_sample.py`
checks each one and notes why none reaches FAIL and why the win-rate and
no-stop flags do not come out. The signal-copiers page opens it with its main
button, the Myfxbook, MQL5 and FX Blue guides link it under "What you get",
the first sample links it from its band, and the sitemap lists it with its
own date (`seo.SIGNAL_SAMPLE_PUBLISHED`).

Each sample also has the public page a publication of its report would get
(`audit/sample_publication.py`): `/v/ejemplo` (the backtest) and
`/v/ejemplo-senal` (the signal), with their `badge.svg`, `card.svg` and
`card.png`. They go through the `/v/{public_id}` routes, functions and caching
(`pages.verification_page`, badge, cards; `?lang=` and `noindex` as any `/v`),
from the view a retention purge keeps (`store.public_view`) of the sample's
Spanish report, built in memory once per set of public series from the same
run as the sample's report page and PDF, with the synthetic-data notice and a
link to the full sample on top. A publication has one hash, so the page shows
the Spanish report's in every language: its notice links that report, and in
English and Portuguese (whose reports are other results with other hashes) the
notice and the sample band say the page is made from the Spanish version.
Nothing is read from or written to the database. The two ids cannot be real
ones: a real id is `secrets.token_urlsafe(9)`, always 12 characters, and `/v`
answers the reserved ids before any lookup. Only what would pass a sample off
as someone's audit is said its own way (`sample_publication.sample_page`): the
tab title and link preview start with "Sample", the share text says what the
page is (never "I audited my...") under its own funnel tag (`v-ejemplo`, not
`share`), the badge code is shown as the sample's without a copy button, and
"Published" is the day the pages came out (`SAMPLE_PAGES_PUBLISHED`, a bare
date), never the audit's date. The report's publish block links the closest
sample (an account history or a fund's track record the signal's), the FAQ's
publishing and badge answers and the page for funds and signal providers link
both, and each sample links its own from its band. `/comprobar` answers a
sample's PDF as before. `tests/test_audit_sample_publication.py` compares each
page, badge and card with those of a real publication of the same report,
before and after a purge, with only those words different.

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

Cash in the account's own currency (`cashrate.LOCAL`, `market.LOCAL_CASH`).
When an imported report names the account currency and it is one of MXN,
BRL, EUR, GBP, JPY, CAD or CHF, the same line subtracts that currency's own
cash rate instead of the US bill's, each from its originator (the OECD copies
FRED carried are no longer read, see "Data licences"): the euro's €STR
(`ECBESTRVOLWGTTRMDMNRT` through FRED, daily, from October 2019; before it,
`EUR_CASH_HISTORY` fills only the earlier dates with three daily ECB policy
rates from the ECB's data API, each cut to its own dates: the main refinancing
operations (MRO) fixed rate `FM.D.U2.EUR.4F.KR.MRR_FR.LEV` until 27 June 2000,
the MRO minimum bid rate `FM.D.U2.EUR.4F.KR.MRR_MBR.LEV` of the variable-rate
tenders from 28 June 2000 to 14 October 2008 (the only days the ECB publishes
it; the fixed rate has no values then), and the deposit facility rate
`FM.D.U2.EUR.4F.KR.DFR.LEV` from 15 October 2008 until €STR starts; each series
is refused on the same rules as any rate reply and held to the daily 10-day
staleness limit, so a missing piece leaves its dates NOT_COVERED), sterling's SONIA
(`IUDSOIA` through FRED, daily), Canada's CORRA (Bank of Canada Valet
`AVG.INTWO`, daily, from 1997), Brazil's Selic accumulated in the month and
annualised on 252 business days (Banco Central do Brasil SGS 4189, monthly,
from January 1995: before the Real plan it ran in the thousands a year) and,
for the peso, the yen and the franc, the central bank's policy rate as the
BIS compiles it (`WS_CBPOL`, `M.MX`, `M.JP`, `M.CH`, monthly, end of
period). The same BIS series gives the cash rate of 22 more currencies
(`market.BIS_POLICY_AREAS`: AUD, NZD, INR, ZAR, KRW, SEK, NOK, DKK, PLN, CZK,
HUF, RON, ISK, TRY, ILS, SAR, IDR, THB, MYR, CLP, COP, PEN), each read whole on
26 September 2026 with every month present and within the rate bounds. Each
quote uses its overnight market's day count (`cashrate.BIS_BASIS`: 365 days
for AUD, NZD, INR, ZAR, KRW, NOK, PLN, ILS, THB, MYR and TRY, 360 for the rest; at
5 % the two differ by under a tenth of a point a year). Left out: the rouble
(210 % in 1993-94, above the bound), the Argentine peso (the BIS series stops in
mid-2025), the Philippine peso (missing months), the Singapore dollar (no
series; the MAS steers the exchange rate), the yuan (the BIS series is a
lending rate, above what cash earned) and the Hong Kong dollar (the base rate
is the discount window's penalty rate). A policy rate can sit away from what
overnight cash actually earned (Türkiye's corridor years, for one), which the
label's "policy rate" says. The BIS figures are official policy rates, not market rates, and so
are the ECB rates before €STR. The splice picks, for each era, the ECB rate
closest to what overnight cash earned: in the corridor years before
October 2008 overnight euro rates (EONIA) sat near the MRO rate, about a point
above the deposit rate, so the MRO rate is used; from 15 October 2008 the ECB
allotted its operations in full, excess liquidity pushed EONIA down to the
deposit rate floor, so the deposit rate is used. The remaining bias is small
and still leans the strategy's way: EONIA ran mostly a few basis points above
the MRO rate (the minimum bid, in the tender years) before October 2008, and
after it stayed between the deposit and MRO rates, closer to the deposit rate
once excess liquidity was large but up to a few tenths of a point above it in
parts of 2008-2011 when liquidity shrank; €STR has run about 10 bp below the
deposit rate. The labels
say "policy rate" and "before October 2019, the ECB's main refinancing rate
until October 2008 and its deposit rate after". Each quote becomes an annual yield
by its own convention: a simple overnight rate on a 360-day (MXN target rate,
EUR, CHF as SARON) or 365-day (GBP, JPY call rate, CAD) year, rolled over
for a year, `(1 + r/basis)^365 - 1`; Brazil's is already a compounded annual
yield and is used as it is. A daily rate may be 10 days old before a return's
start (`MAX_GAP_DAYS`; €STR and the ECB rates before it, SONIA, CORRA), a monthly one 75 days
(`MAX_MONTHLY_GAP_DAYS`): Brazil's monthly average sits on its month's first
day, the BIS's end-of-period value on the month's last day, so a point never
takes a month-end value before that month has ended. Both the BIS's monthly
series and the ECB's daily ones are filled for every period at the source (the
rate in force carries forward), so no step rule is needed, except that the
BIS has no Japanese value in three stretches when the Bank of Japan targeted
reserves or the monetary base instead of a rate (March 1999 to July 2000,
April 2001 to February 2006, May 2013 to August 2016;
`market.JAPAN_NO_POLICY_RATE`): a yen account with returns in those
stretches is not covered and gets no line (`NO_LOCAL_CASH`, below). Each reply is refused when a date
appears twice, a date or value is unreadable, or the reply is for another
series (the BIS's `REF_AREA`, the ECB's `KEY`, the Bank of Canada's column).
These series may be negative (the franc, euro and yen rates were); a reply
outside -5 % to 200 % a year (`MIN_LOCAL_RATE`, `MAX_LOCAL_RATE`; Brazil's
monthly Selic reached 85 % in April 1995) is taken as broken. An account in US dollars (`USD`, `USC`, `USDT`, `USDC`,
`currency.DOLLAR_CODES`) or with no named currency gets the US bill's line.
Another named currency with no series here (`ARS`, `HKD`, `CNY`…), or whose rates
cannot be read or do not cover the history, gets no line: the section is
`NOT_MEASURED` (`NO_LOCAL_CASH`), since the bill is not what cash in that
currency paid (for pesos argentinos the gap is tens of points a year). The
code is read like the currency section (trimmed, upper case, 8 characters),
so the three currency-aware pieces agree on it. Jensen's alpha takes the same local
rate for the strategy's side (the benchmark keeps the bill; see the benchmark
section).
It never changes the class.

Calm and turbulent markets (`audit/regime.py`). With public data on, every
report adds the section "How did it do in calm and in turbulent markets?".
Each return is placed by the VIX (Cboe, FRED `VIXCLS`, credited to both; read in the
background with the other series; a reply above 200, `MAX_VIX`, is taken as
broken) at the close of the last market day *before* the day its stretch
starts, at most 5 days old (`MAX_GAP_DAYS`), so the regime was known before
the return: calm below 20, turbulent at 20 or above (`TURBULENT_AT`; 20 is
close to the index's long-run average, and since 1990 it has closed at 20 or
more on about a third of the days). For each regime it shows the share of
the time, the returns counted, the return per month compounded over that
regime's days only (`exp(Σ log(1+r) · 30.44 / days) - 1`) and the Sharpe
ratio annualised like the headline one ("—" for a flat side). The two mean
returns are compared in a cautious standard error (`gap_error`, the largest
of Welch's, Newey-West's and Welch's widened by `(1 + rho) / (1 - rho)` for
the returns' autocorrelation; Welch's alone read a gap as clear about 10 %
of the time at an autocorrelation of 0.2 on simulated returns with none):
at 2 or more (`CLEAR_GAP`),
and only when that gap has the same sign as the difference of the two
monthly figures (volatility drag can flip them in a jumpy regime), the
report says in which regime it did better, otherwise that the gap is not
enough to say it behaves differently. It needs 90 days of history
(`MIN_SPAN_DAYS`), 20 returns in each regime (`MIN_RETURNS`) and VIX closes
covering the whole history; otherwise it is NOT_MEASURED with the reason in
words. The note says the VIX measures US equities and, for another market,
is read as a general gauge of fear. It never changes the class.

In your currency and after inflation (`audit/currency.py`). With public data
on, every report that is not a fund record adds the section "What was it in
your currency and after inflation?". The curve's dollar levels are converted
at the Federal Reserve's noon buying rate of each day (FRED H.10: `DEXMXUS`,
`DEXBZUS`, `DEXUSEU`, `DEXUSUK`, `DEXJPUS`, `DEXCAUS`, `DEXSZUS`; the euro
and the pound are quoted as dollars per unit and inverted), the last rate on
or before each point and at most 7 days old (`MAX_GAP_DAYS`), else that
currency is left out. Per currency it shows the total return, the return a
year compounded over the calendar days (only from one year of history,
`MIN_YEAR_DAYS`) and the worst fall in that currency. The dollar row is also
shown after US inflation: each point is divided by US consumer prices
(`CPIAUCNS`, not seasonally adjusted, as BLS recommends for deflating between
arbitrary dates) of its own month or the latest month published, at most 75 days
old (`MAX_CPI_GAP_DAYS`), with the inflation over the dates beside it. Each
currency's row is followed by the same figures after that currency's own
inflation (`market.LOCAL_CPI`): the levels in that currency divided by the
country's official consumer price index of each point's month, or the latest
month published, at most 75 days old (`MAX_CPI_GAP_DAYS`). FRED's copies of
these indexes stopped updating (2021-2025), so each comes from an official
publisher whose terms allow reuse in a paid service with attribution, read at
run time with no key: the euro area's HICP (Eurostat, through FRED,
`CP0000EZ19M086NEST`), Switzerland's HICP (Eurostat API, `prc_hicp_minr`,
`CH`), the UK's CPI (ONS time series `D7BT`, Open Government Licence v3.0),
Canada's CPI (Statistics Canada's, through the Bank of Canada's Valet API,
`V41690973`; the Bank asks paid services to say the data is free on its
site, and the credit line does) and Brazil's IPCA (IBGE's, through the Banco
Central do Brasil's SGS series 433, monthly changes chained into an index
from January 1995; a month beyond ±50 %, or a missing, repeated or unreadable
month, refuses the reply, since a broken link would leave its inflation out of
every later level), Mexico's INPC (INEGI's open-data zip of the 2018 base,
from January 2003; its terms allow commercial use with the credit "Fuente:
INEGI" and the product name; the zip is opened in memory and its table
refused above `MAX_BYTES`) and Japan's CPI (the Statistics Bureau's
long-term national file on e-Stat, file id `000040482943`, from 1970, base
2025, read as Shift_JIS; the Public Data License 1.0 and e-Stat's terms
allow commercial use, and the credit says the figures are edited from the
survey). The e-Stat file id is pinned: if e-Stat publishes later months under
a new id, the yen rows first say "prices through {month}" and then drop to
the row before inflation, and the id needs updating. A month that appears
twice in either file refuses the reply. The IMF's CPI dataset, which covers
every currency, needs written permission for commercial reuse, so it is not
used; Banxico's and INEGI's APIs need a registered key, while the files used
here do not. Each row after inflation credits
its source by name and link, as each licence asks; `/metodologia` lists
them too. Non-FRED providers get the User-Agent `PROVIDER_AGENT` (the ONS
refuses Python's default); FRED keeps the default. It runs for a dollar
account: an imported report that names `USD` or `USC` (or `USDT`/`USDC`,
read at one dollar per coin, which the note says), or a file that names no
currency, in which case a line says it is read as dollars. When a report
names EUR, GBP, CAD, CHF, BRL, MXN or JPY, the section shows the account in that
currency and after that currency's inflation, with the local inflation over
the dates; without those prices it is NOT_MEASURED with the reason. Another
named currency leaves it NOT_MEASURED. A price index reply below 1 or above
10,000,000, or with two consecutive months more than 3 times apart
(`MAX_PRICE_STEP`), is taken as broken. When the last point is more than 45
days past the start of the last price month used (`STALE_TAIL_DAYS`), the row
after inflation says "prices through {month}": the months after it are not
deflated. The same applies to the dollar row after US inflation.
Needs 90 days of history. A reply above 10,000 for any of these series is
taken as broken. It never changes the class.

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
and to the terms' contact route for a fix or a new credit.

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

### Data licences

The paid report uses outside data only when its licence allows commercial
reuse with attribution, and credits each source where it is shown and on
`/metodologia` (`method.COPY`, `report_pt.METHOD_COPY`). Checked on
2026-09-26:

- FRED (St. Louis Fed): US federal series in the public domain (`DTB3`,
  `CPIAUCNS`, the H.10 exchange rates `DEX*`), plus the ECB's €STR and the
  Bank of England's SONIA, which FRED republishes. FRED's own terms ask for
  consent for commercial use of the service; the risk is noted, and each
  series can be read from its originator instead if needed.
- VIX (`VIXCLS`): FRED tags it "Citation Required"; the regime line credits
  Cboe and FRED. Cboe's own site is for personal use, so it is kept under
  review.
- ECB (€STR, the main refinancing operations rates and the deposit facility
  rate): free reuse with the source quoted
  ("Source: ECB statistics"); the methodology page tells buyers the data is
  available free on the ECB's website, as the ECB's disclaimer asks.
- Bank of England (SONIA): Open Government Licence v3.0, with the credit
  "SONIA data licensed under the Open Government Licence v3.0 and copyright
  the Governor and Company of the Bank of England" on the methodology page.
- Bank of Canada (CPI, CORRA): reuse with credit; a paid product must say the
  data is available free at bankofcanada.ca, which the credit lines do.
- Banco Central do Brasil (IPCA, Selic SGS 4189): Open Database License
  (ODbL), credited by name.
- BIS policy rates (MXN, JPY, CHF and the 22 of `BIS_POLICY_AREAS`): "The use of the statistics is
  unrestricted, provided that ... the BIS must be cited ... as the source";
  their inclusion must not add a charge, and the report's price does not
  change with them. Cited as "Source: BIS".
- Eurostat, ONS (Open Government Licence), INEGI, e-Stat: see the section on
  currencies and inflation.
- Not used: FRED's `SP500`, `NASDAQ100` and `CBBTCUSD` (S&P Dow Jones
  Indices, Nasdaq and Coinbase: "Reproduction ... in any form is prohibited
  except with the prior written permission"), so the holding comparison is
  NOT_MEASURED for those markets and the crisis table keeps only a dozen fixed
  historical figures; the OECD's cash-rate copies (`IRSTCI01…M156N`,
  `IR3TIB01CHM156N`), whose terms reserve third parties' rights; the SNB's
  SARON (non-commercial); Banco de México's and the Bank of Japan's own rate
  files (terms unclear for a paid product). No openly licensed equity index
  was found: the BIS publishes none, the ECB's reuse policy excludes the
  third-party indices in its datasets, and the OECD's share-price indices
  carry the same third-party clause.

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

For multiplicity, a favorable DSR computed from one assumed trial is
`NOT_MEASURED` when no trial count was declared or observed; a measured bad
PBO or a weak/failing DSR still determines the weaker outcome.

Class: **D** if data quality or significance fails, or two or more
dimensions fail. **C** if exactly one fails, or significance or
multiplicity is WEAK. **B** if significance and multiplicity pass and any of
costs, out-of-sample or benchmark is WEAK or NOT_MEASURED. **A** only when
all six pass (benchmark may be declared not applicable). Without trades or
without a declared holdout the best possible class is B, on purpose. The same
holds when multiplicity is `NOT_MEASURED` only because no trial count was
declared or observed and the one-trial DSR clears the bar
(`verdict.trials_undeclared_only`): a missing count is a missing piece, not a
measured weakness, so the class is at most B and never A, and the B sentence
names the number of trials among the missing pieces.

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
  multiplicity relies on the DSR alone. Exact duplicate return columns count
  as one effective variant for CSCV, so repeated uploads cannot change PBO.
  When fewer than two distinct variants remain, PBO is `NOT_MEASURED`. This
  does not reduce the declared trial count used by DSR: a distinct parameter
  search is still a trial even if its returns happen to match another trial.
  The CSCV payload reports both `parameter_variants` (submitted columns) and
  `effective_variants` (distinct return paths used in its ranks).
- The bootstrap is per period and does not annualise; its block size is
  `min(20, n/10)`. The research bootstrap's maximum drawdown starts at unit
  initial wealth before the first resampled return, so a loss on the first
  period is included.
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
| `GET /` | Landing (how it works, prices, FAQ, link to the sample); `?lang=en`. `GET /en` is the English landing, a short address to share. Its closing call keeps `id='subir'`, and every start button links to the upload page; old `?extras=1` links redirect there. |
| `GET /auditar` | The upload form on its own page (`/en/audit`, `/pt/auditar`; `?extras=1` opens the extra files). Outside free mode a visitor without an account gets a 303 to sign-up with `next` back here (`/registro?next=/auditar`, `/signup?next=/en/audit`, `/pt/cadastro?next=/pt/auditar`), so nobody fills the form and loses it. A visitor who came with `?extras=1` keeps it (`next=/auditar%3Fextras%3D1`) and lands on the form with the extra files open after signing up or in; the language switch of the form and the "account first" answer to an upload that used an extra box keep it too. With `AUDIT_ANON_PREVIEW=true` there is no redirect: the form is served, and its note says that without an account the file's A to D class and red flags are shown, and that with an e-mail the first full report is free (`pages._COPY[...]["anon_preview_note"]`); under the paid offer (`AUDIT_WELCOME_FULL_REPORT=false`) the notes say instead the free preview, the price and the 7-day refund (`paid_offer.paid_text`); see "Preview without an account" and "Paid offer" below. |
| `GET /precios` | 301 to the landing's prices (`/#pricing`); `/pricing` and `/en/pricing` go to `/en#pricing`, `/pt/precos` to `/pt#pricing`. |
| `GET /contacto` | Contact page (`/en/contact`, `/pt/contato`; `/soporte`, `/contact`, `/support`, `/en/support`, `/pt/suporte` redirect there), linked from every footer. It shows only what the operator set: `AUDIT_OPERATOR_CONTACT` as a mail link and `AUDIT_CONTACT_URL` as the chat link; with neither it says no channel is published yet. It also says never to send a password, recovery key or card details. |
| `GET /acerca` | Who is behind Rigor (`/en/about`, `/pt/sobre`; `/about` and `/pt/about` redirect there; `about.py`). It shows only what the terms and the landing already publish, each from its setting: `AUDIT_OPERATOR_NAME`, the country (`AUDIT_OPERATOR_ADDRESS`, `_EN`, `_PT`), `AUDIT_OPERATOR_CONTACT` and `AUDIT_CONTACT_URL`; no photo. With none set it says the operator has not published them. `/sample-signal`, `/en/compare`, `/en/signup`, `/register` and `/pt-br` answer 301 to the page that exists. |
| `POST /audits` | Upload. An optional `access_code` field redeems a code (paid mode with codes on). With `AUDIT_ANON_PREVIEW=true`, an upload without an account and without a working code is stored as a locked preview and answers 303 to `/audits/{id}?token=…&acct=anon_preview` (201 with that `location` for JSON). |
| `GET /audits/{id}?token=…` | The report, in the language chosen at upload; `&lang=en` or `&lang=es` shows it in the other one. `GET /audits/{id}.json?token=…` the record (402 while locked). |
| `POST /audits/{id}/checkout?token=…` | Stripe Checkout (503 without Stripe). Form field `plan=single` (default) or `plan=pack`; the return link `?session_id=…` is confirmed with Stripe before anything unlocks. Needs a signed-in account: a visitor is sent to sign in and back to the report, a report on another account is refused (403), and the order is recorded on the buyer's account (`tests/test_audit_card_payments.py::test_checkout_needs_the_signed_in_account_that_owns_the_report`). |
| `POST /cuenta/comprar` (`/account/comprar`, `/pt/conta/comprar`) | Buy credits by card from "My account": `plan=single` (1 credit, the report price) or `plan=pack` (3 credits, the pack price), with `billing_country` from `AUDIT_APPROVED_MARKETS` and the required `final_sale=yes` box. Live Stripe only (no button and `?error=buy_off` in test mode, without markets or while new checkouts are paused). The order is a `checkout_orders` row whose `audit_id` is `account:<account id>`; the signed webhook puts the credits on an access code linked to the account and unlocks no report. A test-mode payment, another account, amount, plan or billing country grants nothing (`tests/test_audit_account_credit_purchase.py`). |
| `POST /audits/{id}/redeem?token=…` | Unlock an existing preview with an access code. |
| `POST /audits/{id}/account?token=…` | The account box of a report opened by its link, for a visitor without a session. Form field `go=signup` or `go=signin`; 404 without a valid token, 403 to a post from another site. It keeps the report's key in the cookie `rigor_report` (1 hour) and answers 303 to sign-up or sign-in with a `next` that names the report without its token. |
| `POST /audits/{id}/publish?token=…` | Create (or return) the public verification page. Paid audits, or any audit in free mode; 402 otherwise. |
| `POST /audits/{id}/unpublish?token=…` | Remove the public page. |
| `GET /v/{public_id}` | Public verification page. `GET /v/{public_id}/badge.svg` its badge. Survives the retention purge (only the shown fields are kept); 404 once unpublished. Without `?lang=` it is the Spanish page with its usual canonical, except for a browser whose `Accept-Language` asks for English or Portuguese: that one gets a 302 to `?lang=en` or `?lang=pt` (`Vary: Accept-Language`, the rest of the query such as `?ref=` kept). The language switch links Spanish as `?lang=es`, so the visitor's choice wins. |
| `GET /v/ejemplo`, `GET /v/ejemplo-senal` | The public page each sample's report would get, with the synthetic-data notice on top, and the same `badge.svg`, `card.svg` and `card.png`; built in memory, never stored. |
| `GET /ejemplo`, `GET /sample` | A full report of synthetic data, Spanish and English. |
| `GET /ejemplo-senal`, `/en/sample-signal`, `/pt/exemplo-sinal` | The signal sample: a full report of a made-up Myfxbook account, for a copier; each with its `.pdf`. |
| `GET /terminos`, `GET /terms` | Terms of service (`audit/legal.py`), Spanish and English; either answers `?lang=`. |
| `GET /privacidad`, `GET /privacy` | Privacy policy, Spanish and English. |
| `GET /en/terms`, `/en/privacy`, `/pt/terms`, `/pt/privacy` | 301 to the legal page in that language (guessed addresses). |
| `GET /herramientas` | The free tools page (`/en/tools`, `/pt/ferramentas`; `/tools` and `/pt/tools` redirect there): luck calculator, win-rate calculator, figure reader and report check. |
| `GET /en/calculator`, `/reading`, `/en/methodology`, `/en/articles`, `/en/guides`, `/en/sample`, `/en/check`, `/faq`, `/examples` | 301 to the page people meant (`/calculator`, `/en/reading`, `/methodology`, `/articles`, `/guides`, `/sample`, `/check`, `/en/faq`, `/en/examples`). The first two keep the query string. |
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
| `AUDIT_BASE_URL` | `http://localhost:8000` | Public URL used in Stripe success and cancel links, canonical and Open Graph links, the badge snippet, `robots.txt` and `sitemap.xml`. While it is left at the default, the page links (canonical, Open Graph, badge snippet, `robots.txt`, `sitemap.xml`) use the address the request reached (`https` when `AUDIT_TRUSTED_PROXY_HOPS` > 0). The Stripe return links do not: `audit/payments.py` always builds them from `AUDIT_BASE_URL`, so with the default a buyer would be sent back to `http://localhost:8000`. Set it to your domain in production. |
| `AUDIT_FREE_MODE` | `true` | Serve watermarked reports with nothing locked. Forced `true` unless both Stripe secrets are set or `AUDIT_ACCESS_CODES=true`. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | empty | Both are needed for card payments: a secret (`sk_…`) or restricted (`rk_…`) key and the webhook signing secret (`whsec_…`). A publishable key (`pk_…`) leaves card payments off. `/health` shows `card_mode` (`off`, `test`, `live`) from the key's prefix, never the key. |
| `STRIPE_PAYMENT_LINK_SINGLE`, `STRIPE_PAYMENT_LINK_PACK` | empty | Historical Payment Links (`https://buy.stripe.com/…`) for one audit and the pack. They do not create a frozen database order before payment. This branch no longer presents live links as a new buying path because they bypass country admission; signed webhooks for historical paid links remain accepted. |
| `AUDIT_LEGACY_PAYMENT_LINKS_ENABLED` | `false` | Compatibility switch for old link configuration; it does **not** deactivate externally accessible links in Stripe. Disable those links in Stripe Dashboard before opening live charges, then reconcile delayed historical paid sessions. |
| `AUDIT_APPROVED_MARKETS` | empty | Comma-separated reviewed ISO buyer countries among `MX,US,BR,ES`. Empty keeps live Checkout closed. The landing's card-payment line names exactly these countries in ES/EN/PT. The buyer selects a billing country before an order is reserved; it is frozen with the order in additive table `checkout_order_markets`. Checkout requires a billing address. A paid session with missing, unsupported or different Stripe billing country is recorded as `paid_review`/`manual_refund_review`, shown to the owner and **does not deliver**. This is a best-effort precharge gate: a false declaration can still result in a charge before Stripe reveals the billing country, so support/refund handling remains mandatory. Do not infer country from IP or language. |
| `AUDIT_STRIPE_TEST_AUDITS` | empty | Comma-separated audit ids that a test-mode payment may unlock. In test mode the card button shows only on these audits, and a test payment for any other audit is ignored, so Stripe's public test card never unlocks a real report. Leave empty in normal operation. |
| `STRIPE_PRICE_ID` | empty | Legacy direct-call option. The web Checkout now freezes the configured amount on a persisted order and sends an inline USD price, so this id cannot silently override the amount the buyer saw. |
| `AUDIT_ACCESS_CODES` | `false` | Offer manual access-code sales and typed-code redemption. With `AUDIT_FREE_MODE=false` it turns on paid mode without Stripe. Credits already on an account remain spendable when this is `false`. |
| `AUDIT_REFERRAL_REWARDS` | `true` | Set `false` to stop new invite rewards and hide the reward promise during an incident. Previously granted credits remain usable. |
| `AUDIT_REFERRAL_GLOBAL_MONTHLY_CAP` | `100` | Maximum rewarded invites across the whole service per UTC month, reserved transactionally in `referral_global_slots`. At one credit per invite this caps the new monthly credit obligation. `0` stops new rewards. |
| `AUDIT_ANON_PREVIEW` | `false` | Paid mode only. `true` lets a visitor without an account upload and see the file's class and red flags (a locked preview, `accounts.ANON_PREVIEWS_PER_NETWORK_PER_DAY = 2` per IPv6 /64 and `ANON_PREVIEWS_PER_IPV4_PER_DAY = 6` per IPv4 address a UTC day); signing up or in from that report puts it on the account and opens it as the free first full report under the usual limits (with `AUDIT_WELCOME_FULL_REPORT=false` it stays locked on the account, with the usual purchase). `false` keeps "account first": every page and route answers exactly as before. It changes the free tier's rule, so only the owner turns it on. |
| `AUDIT_WELCOME_FULL_REPORT` | `true` | Paid mode only (`AuditSettings.welcome_full_report`, default `accounts.WELCOME_FULL_REPORT`). `true`: a new account's first upload is a free full report under the usual limits. `false` (the paid offer, `audit/paid_offer.py`): every full report is paid from the first one; no path grants one free (upload, confirmed e-mail, card check, invite), access codes and credits work as always, and the pages say the free preview, the price from the settings and the terms' 7-day refund. Planned for production with `AUDIT_ANON_PREVIEW=true`. |
| `AUDIT_EMAIL_VERIFICATION_REQUIRED` | `false` | Migration default. When `true`, both addresses must be confirmed before an invite reward and a buyer's address before a new Checkout. Sign-up still works; the free first full report waits until the address is confirmed (earlier uploads are previews with reason `unverified`). **Public paid launch requires `true` and e-mail delivery (Resend's API or SMTP, see the next two rows) verified end to end.** |
| `AUDIT_EMAIL_TOKEN_SECRET`, `AUDIT_SMTP_HOST`, `AUDIT_SMTP_PORT`, `AUDIT_SMTP_USERNAME`, `AUDIT_SMTP_PASSWORD`, `AUDIT_SMTP_FROM`, `AUDIT_SMTP_SECURITY` | empty / `587` / `starttls` | Stable secret of at least 32 characters shared by replicas and encrypted SMTP transport. SMTP is one of two transports: when `AUDIT_RESEND_API_KEY` is set (next row but one) the mail goes through Resend's HTTPS API and the `AUDIT_SMTP_HOST`, port, user, password and security variables are not used; the sender is `AUDIT_EMAIL_FROM`, or `AUDIT_SMTP_FROM` when that is empty. `/ready` fails when verification is required but delivery is not configured. Test real delivery, retries and legacy account confirmation before launch. No usable token or link is stored in the outbox. |
| `AUDIT_SKIP_EMAIL_DNS` | `false` | `true` stops the sign-up DNS check that refuses domains taking no mail (for a staging copy without DNS). |
| `AUDIT_RESEND_API_KEY`, `AUDIT_EMAIL_FROM` | empty | Resend's HTTPS API, used instead of SMTP when the key (`re_…`) is set. Railway disables outbound SMTP below the Pro plan, so this is the transport that works there. `AUDIT_EMAIL_FROM` (alias of `AUDIT_SMTP_FROM`) must be an address on a domain verified in Resend; until a domain is verified Resend only delivers to the Resend account owner. When `AUDIT_EMAIL_TOKEN_SECRET` is empty, the token secret is derived from the Resend key (HMAC-SHA256), so rotating the key voids only links still pending (24 h at most). The Message-ID is sent as Resend's `Idempotency-Key`, so a retry after a lost reply is not delivered twice. The privacy page names Resend and links its policy while it carries the mail. |
| `AUDIT_CONTACT_URL` | empty | Where a client asks for a code (for example a `https://wa.me/…` link or a `mailto:`). Only `https://` and `mailto:` are shown. |
| `AUDIT_PRICE_USD_CENTS` | `2900` | New single-report Checkout price in USD cents; each order freezes this amount. Existing paid reports and credits are unchanged. |
| `AUDIT_PACK_PRICE_USD_CENTS` | `6900` | One Checkout for a three-report pack: the selected report plus two credits. It is offered when card payments or manual codes are enabled and the amount is below three singles; `0` hides it. An owner-created code with three credits is a separate, unverified manual issue until its payment is reconciled. |
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
| `AUDIT_OPERATOR_ADDRESS_EN` | empty | Optional. The address as the English pages print it (terms, privacy, "who is behind it"). Empty shows `AUDIT_OPERATOR_ADDRESS` as written. |
| `AUDIT_OPERATOR_ADDRESS_PT` | empty | Optional. The same for the Portuguese pages. |
| `AUDIT_JURISDICTION_EN` | empty | Optional. Governing law and courts as the English terms print them. Empty shows `AUDIT_JURISDICTION` as written. |
| `AUDIT_JURISDICTION_PT` | empty | Optional. The same for the Portuguese terms. |
| `AUDIT_OPERATOR_STREET_ADDRESS` | empty | Optional. Street, number, postal code and city, printed on the terms and privacy pages before the country (`AUDIT_OPERATOR_ADDRESS` in each language). A Mexican online seller must show a physical address before the sale (LFPC art. 76 BIS). The landing keeps showing only the country. |
| `AUDIT_OPERATOR_PHONE` | empty | Optional. A telephone printed after the contact in the provider's line of the terms and privacy pages (", tel. …" / ", phone …"). |
| `AUDIT_ADMIN_KEY` | empty | Secret for the owner panel at `/panel` (create, list and disable codes from a phone). Shorter than 32 characters or empty turns the panel off (404). |
| `AUDIT_PANEL_PATH` | `/panel` | Path of the owner panel. Must start with `/`, have 2 to 64 characters from `A-Z a-z 0-9 / _ -`, no `//`, no trailing slash, and a first segment that no public route uses (`/cuenta`, `/pt`, `/audits`, `/static`...). An invalid value falls back to `/panel` and the start-up log says so without printing the value. Never listed in `robots.txt` or the sitemap. |
| `AUDIT_TRUSTED_PROXY_HOPS` | `0` | Reverse proxies in front of the service. `0` ignores `X-Forwarded-For` (it is client-controlled) and rate-limits the socket address; `N` takes the N-th entry from the right. Railway needs `1`. |
| `AUDIT_GOOGLE_VERIFICATION_FILE` | empty | Google Search Console's HTML-file check, e.g. `google1a2b3c4d5e6f7a8b.html`. When set, that path answers with the line Google expects. Anything else is ignored. |
| `AUDIT_BING_SITE_AUTH` | empty | Bing Webmaster Tools' 32-character code, served as `/BingSiteAuth.xml`. Anything else is ignored. |
| `AUDIT_INDEXNOW_KEY` | `f5a5a16c542ab2277bfa9656ce368b3d` | The IndexNow key, public by design and served as `/<key>.txt`. Replaces the default (`indexnow.INDEXNOW_KEY`) when it has 8 to 128 characters from `A-Z a-z 0-9 -`; an empty or invalid value keeps the default. Set the same value where `quant-trade audit indexnow` runs. |

Checkout creates a database order before calling Stripe. The order freezes the
plan, USD amount and report id, and its id is the Stripe idempotency key. A
second click or a retry after restart reuses the same valid order and Checkout
URL. The signed paid webhook and the paid return path both settle through one
transaction: one `checkout_orders` row per paid session, one report delivery,
and, for a pack, two credits. If two distinct sessions were paid for one
report, the second row has `status=duplicate` and
`resolution=manual_refund_review`; it grants no second pack. The owner panel
shows that row for action. This status **does not issue a refund**.

`credit_grants.origin` records `purchase`, `referral`, or `unknown` for new
codes. A manually created code has `unknown` origin until its outside payment
is verified; its redemption is not counted as a card sale. The funnel counts
confirmed live paid sessions as purchases and pack rights separately. Its USD
gross amount is before refunds, payment fees and taxes, and is not a payout
balance. Signed Stripe refund events are kept by refund id; linked,
`succeeded`, live USD amounts (including partial refunds) appear separately
from gross. A later `failed` event removes that refund from the confirmed
total. Refunds without a confirmed link, in another currency or without
subscribed/delivered events are **NOT_MEASURED** in that USD figure. The
displayed gross minus observed USD refunds is only a ledger subtotal, not
net revenue, profit or payout. Disputes, provider fees, FX, taxes and bank
receipts still require manual reconciliation in Stripe and the bank.
The account outbox also queues a purchase/entitlement notice in the same
transaction as settlement when encrypted SMTP is configured and the buyer's
current address is verified. A second paid session queues a separate manual
review notice and no second right. The outbox id is the frozen order id, so
webhook replay cannot queue another notice. The message contains only the
order reference, charged amount, currency and plan, never a report token or
result. Delivery is at least once: monitor dead/retrying rows and verify real
SMTP in staging before promising an email to buyers.
`/ready` reports numeric `warnings.purchase_mail_dead`,
`warnings.purchase_mail_overdue` and `warnings.purchase_mail_probe_failed`
without turning an SMTP delivery failure into a service restart. Monitor
these fields externally. The owner panel lists only outbox id, kind, status,
attempts and timestamps (no address or report) and can requeue a dead buyer
notice. Requeue works only while the live order still has the matching
delivered/duplicate status and the account's current email remains verified;
it does not resend a sent row or create a new right. Investigate the SMTP
cause and the Stripe order before requeueing; a previously accepted SMTP
message can have been lost before the worker marked it sent.
First and repeat purchase counts use the account linked to the
report when there is one; that account is not verified as the cardholder.
Visits estimate browsers observed, not unique people, on the landing, the case
pages and the free calculator (`/calculadora`, `/calculator`, `/pt/calculadora`). Older card
unlocks predating `checkout_orders` need a reconciliation import from Stripe
before they can be included in purchase totals. Legacy Payment Links only
create their order when their paid webhook arrives, so they do not provide
pre-Checkout order reuse. Their historical USD 29/69 floor remains accepted
for paid callbacks after a price rise, so **retire active old links in the
Stripe Dashboard before changing prices**; do not claim the new price applies
to all buyers until old sessions are reconciled.

**No "your report is ready" e-mail (product decision, 2026-09-28).** The
report is produced on screen right after the upload and stays in "Mi
cuenta" ("My account", "Minha conta"), so there is nothing to wait for and
no separate e-mail announces it. The outbox knows six kinds and none is a
report notice: `verify`, `change`, `reset`, `purchase`, `charge_review` and
`market_review`. A purchase produces two messages: the service's own
purchase e-mail described above, and Stripe's automatic receipt (receipts
for successful payments are enabled in the Stripe account since
2026-09-28). The receipt is sent by Stripe to the address typed in Checkout;
the service neither sends nor stores it.

### Deploying on Railway

1. Create a service from this repository and set, in the service's
   Settings: Build, Dockerfile path `Dockerfile.web` (the repository root
   also holds the paper-trading `Dockerfile`, which is not this service);
   Deploy, healthcheck path `/ready` with a timeout of 120 s (`/health`
   stays as a liveness probe that does not query storage, see "Operator
   probes and incident admission"), restart policy "on failure" with 5
   retries. The container listens on `$PORT`.
   Every merge redeploys, and Railway's default draining time (SIGTERM to
   SIGKILL) is 0 s. Set the service's Draining time to 120 s (Settings, or
   the variable `RAILWAY_DEPLOYMENT_DRAINING_SECONDS=120`). The image
   `exec`s the server so it receives the SIGTERM and finishes the audits and
   PDFs in flight.
   These settings used to live in `railway.json`. Railway deprecated config
   as code (files stop being read on 2026-12-01), so the file was removed
   and the service's own settings are the only source.
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
   Moving `AUDIT_BASE_URL` to another domain later leaves existing passkeys
   behind (see "Passkeys" under customer accounts); sign-in by password,
   code and recovery key is unaffected.
   With an `https` `AUDIT_BASE_URL`, the redirect of an address written
   with a trailing slash (`/en/` to `/en`, 307) is built from
   `AUDIT_BASE_URL` on the site's own host, so it keeps `https` behind the
   proxy. No forwarded header is read for it.
   Keep the Railway address attached after the move: while `AUDIT_BASE_URL`
   is an `https` custom domain, a GET or HEAD on any `*.up.railway.app`
   host answers 308 to the same path and query on `AUDIT_BASE_URL`, so old
   report, verification and badge links keep working. The `www` name of
   that domain moves the same way, so a visitor keeps one address and one
   session. POSTs (the Stripe webhook, forms) and `/health`, `/ready` are
   served where they arrive.
   See "Moving to the custom domain" below for the whole move.
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

### Moving to the custom domain

The site's address is `https://rigorscore.com`. What the move consists of:

- **Canonical host.** `AUDIT_BASE_URL=https://rigorscore.com` on Railway. It
  is the address in canonical, Open Graph and `hreflang` tags, `robots.txt`,
  `sitemap.xml`, the badge snippet, the links in every e-mail and the passkey
  relying party. With `https` it also turns HSTS on.
- **Old address.** The Railway address stays attached to the service. A GET
  or HEAD on any `*.up.railway.app` host answers 308 to the same path and
  query on `AUDIT_BASE_URL` (`old_address` in `audit/web.py`), the icon files
  included. `https://www.rigorscore.com` is attached too and moves the same
  way. `/health` and `/ready` are never redirected, so Railway's own
  probe keeps answering where it looks.
- **Stripe webhook.** The endpoint is `POST /webhooks/stripe`. A POST is
  never redirected on either host, so an endpoint still registered in Stripe
  with the Railway address keeps delivering; register the one on
  `https://rigorscore.com/webhooks/stripe` and retire the old one once the new
  one has delivered.
- **Stripe return links.** The success and cancel links of every Checkout
  (report, account credit, card check) are built from `AUDIT_BASE_URL`
  (`audit/payments.py`), never from the address the request reached: a buyer
  who started on the old address comes back on the domain.
- **Passkeys** registered on the old host stop working (see "Passkeys" under
  customer accounts); password, code and recovery key are unaffected.

`tests/test_audit_domain_move.py` and `tests/test_audit_launch_basics.py`
cover the redirect, the posts that stay and the icons.

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
   events `checkout.session.completed`,
   `checkout.session.async_payment_succeeded`, `refund.created`,
   `refund.updated` and `refund.failed` in the matching test/live environment.
   Copy its signing secret into `STRIPE_WEBHOOK_SECRET`. A refund count of zero
   has no meaning until those events and their delivery are confirmed; test
   a signed partial refund event in staging without issuing a real refund.
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

#### Without a secret key: Payment Links (NO-GO for public launch)

Keep `STRIPE_PAYMENT_LINK_SINGLE` and `STRIPE_PAYMENT_LINK_PACK` empty in
production. A Payment Link cannot reserve a local order before redirecting
to Stripe, so this path does not meet the launch requirement for durable
pre-payment order tracking and Checkout retry reuse. The instructions below
describe legacy compatibility only. Public card sales require the secret-key
Checkout flow above. The service no longer presents **live** Payment Links as a
new buying path, even with the compatibility switch, because they bypass
market admission. A historical paid webhook is still fulfilled with the
switch off. Disable the links in Stripe **before opening live charges**: an
active old link remains externally accessible and can still charge its old
amount, while the service accepts its signed callback to protect that buyer.

1. For historical reconciliation, inspect existing Payment Links and retain
   their metadata (`app=rigor`, `plan=pack` where relevant) in the private
   Stripe record. Do not create new public Payment Links for this launch.
2. Keep the webhook endpoint as above and put its signing secret in
   `STRIPE_WEBHOOK_SECRET`.
3. For an isolated legacy migration test only, set
   `STRIPE_PAYMENT_LINK_SINGLE`, `STRIPE_PAYMENT_LINK_PACK`, and
   `AUDIT_LEGACY_PAYMENT_LINKS_ENABLED=true`, and leave `STRIPE_SECRET_KEY`
   empty. Turn the switch off and retire the links in Stripe before public launch.

Historically the locked report linked to them with
`client_reference_id=<audit id>` in a new tab. For an existing link payment,
the signed webhook remains the confirmation (the service has no key to ask
Stripe). The pack code remains keyed by the Checkout session the link created.

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

To serve the panel somewhere else, set `AUDIT_PANEL_PATH` (for example
`/oficina-7k2`) and redeploy; every form and link of the panel follows it,
and `/panel` then answers like any page that does not exist. Rules
(`settings.resolve_panel_path`): it starts with `/`, has 2 to 64 characters
from `A-Z a-z 0-9 / _ -`, no `//`, no trailing slash, and its first segment
is not the first segment of a public route. A value that breaks a rule
keeps `/panel`, and the start-up log has one warning that names the
variable, never the value. The path is not a secret that replaces the key:
it only keeps the login form away from scanners. It is never written in
`robots.txt` or the sitemap (that would reveal it); the panel's responses
carry `X-Robots-Tag: noindex, nofollow` and `Cache-Control: no-store`
themselves. Without a valid `AUDIT_ADMIN_KEY` the panel routes are not
mounted at all, so the path gives the ordinary localized 404 for GET, HEAD,
POST (with or without a key) and every other method: same status, body and
headers as an unknown page. With a key set the path can still be told from
an unknown page: 405 to other methods, 400 to a POST without the key field
or with a key that is too long, 307 to the path with a trailing slash. The
key field accepts at most 256 characters,
and the access log redacts `key=` like `token=` and `code=`, in case
someone types the key into a link by mistake.

### Customer accounts (`audit/accounts.py`, `/registro`, `/cuenta`)

A customer can create an account with an e-mail and a password to find, in
one place, the reports they uploaded or saved, the access codes they
redeemed or added (with the credits left), and what they paid for. The
free preview needs one (see "Free tier" below), and so does an upload or a
redeem with an access code: outside free mode an anonymous upload gets the
sign-in page (401) even with a working code, and `POST /audits/{id}/redeem`
sends an anonymous visitor to sign in first, so every paid report lands on an
account's list. A report's private link still opens without an account, and
an account never changes what a report says.

- **Free tier** (`accounts.FREE_PREVIEWS_PER_MONTH = 3`,
  `FREE_PREVIEWS_PER_IP_PER_MONTH = 10` per IPv6 /64,
  `FREE_PREVIEWS_PER_IPV4_PER_MONTH = 30` per IPv4 address; not in free
  mode). An upload
  needs a signed-in account, with or without an access code (401 page with
  "Crear cuenta gratis" otherwise; `{"error": "free_tier_signin"}` for JSON).
  Each account gets 3 free previews per calendar month (UTC), counted in
  the `free_previews` table; free previews are also capped per network
  address per month, across accounts. Past either limit, an account with
  credits gets a full report and spends one credit (`acct=upload_credit`);
  without credits the upload answers 402 with a link to buy. A code typed
  in the form that still has credits pays the upload with no account, as
  before. "Mi cuenta" shows the free previews left this month. The
  address in `free_previews` is cleared by the retention purge.
  What it does not stop while `AUDIT_EMAIL_VERIFICATION_REQUIRED=false`:
  someone can open several accounts with made-up addresses; the per-network
  cap and the 5 sign-ups per hour per network only slow that down. Enabling
  SMTP and verified-email gating closes the reward and new-Checkout paths.
- **Preview without an account** (`AUDIT_ANON_PREVIEW`, off by default; not
  in free mode). With the switch off, everything above holds unchanged:
  `/auditar` sends a visitor without an account to sign-up and an anonymous
  upload gets the 401 sign-in page. With it on, the free tier's rule becomes
  "see the class first, create the account to open it":
  - `/auditar` serves the form; its note says what is shown without an
    account and that the first full report is free with an e-mail.
  - `POST /audits` without a session and without a working code (a working
    code still asks for the account) keeps the cross-site check, the consent
    and the hourly limit, then takes one of the network's previews of the
    UTC day after parsing (`free_claims` keys
    `anon:ip:<network hash>:<day>:<n>`; `accounts.ANON_PREVIEWS_PER_NETWORK_PER_DAY
    = 2` per IPv6 /64, `ANON_PREVIEWS_PER_IPV4_PER_DAY = 6` per IPv4 address,
    `accounts.network_cap`). Past it the answer is the 401 sign-in page (JSON
    `free_tier_signin`) and nothing is stored. Otherwise the report is stored
    locked (`paid=False`), a `welcome_pending` row with `account_id = ""`
    keeps the upload's browser mark, file fingerprint and network, an
    `anon_previews` row counts it for `/panel`, and the answer goes to
    `/audits/{id}?token=…&acct=anon_preview` (the device cookie is set as for
    any upload). The in-page upload follows the same `location`.
  - The report says it is a preview without an account. While the account
    would open it (this same browser uploaded it, its device cookie hashing to
    the upload's mark; uploaded in the last `WELCOME_PENDING_DAYS` days;
    neither its browser, file nor network had their free report meanwhile;
    and, when confirmation is required, a confirmation e-mail can be sent),
    a visitor without a session sees `anon_preview` ("the full report and the
    PDF open with an account") and the box reads `anon_preview_box` with
    "Abrir mi informe completo gratis" (sign-up) and "Ya tengo cuenta".
    Otherwise (another browser with the link, a file or network that already
    had its free report, a signed-in visitor, no mail transport) the notice
    is `anon_preview_link`, without that promise, and the box is the usual
    `anon_box`. It stays `noindex`, opened only by its key.
  - Signing up or in (password, two-step code or passkey) with `next` on that
    report and its key in `REPORT_KEY_COOKIE` (checked as `_load` checks it),
    or "Guardar en mi cuenta" on it from an account made another way (the
    menu, the form's "Crear cuenta gratis"), runs `_anon_to_account`. Only the
    browser that uploaded it takes it: another browser with the link links
    nothing on signing up or in, and its "save" is the usual saved link,
    without the pending row, so it never gets the uploader's free report nor
    their network address or marks in "Descargar mis datos"; the uploader can
    still take it afterwards while no account holds it. For the uploader the
    report goes on the account as its own upload and the pending row is
    attached (`store.welcome_pending_attach`, only a row with
    `account_id = ""`). With no confirmation required, or an address already
    confirmed, `_grant_pending_welcome` opens it at once (`acct=welcome`);
    otherwise confirming the address opens it, as for any pending preview
    (the report shows `welcome_refused_unverified`). When the account,
    browser, file, inbox or network rule refuses the free report, the report
    counts as one of the month's free previews of the account and of the
    network (the same `preview:account:` and `preview:ip:` claims and
    `free_previews` row as an upload made signed in); past either cap it goes
    on the account as saved, not as its own upload. It stays locked, with the
    usual credit, code or card offer. No limit is relaxed: the free full
    report is still one per account, inbox, browser, file and card, and a few
    per network a month, and an account's own uploads still count against
    its 3 previews a month. One case is left as it is: a preview waiting for
    the address to be confirmed is not counted (confirming opens it as the
    free report, and a counted preview given back by `delete_free_preview`
    keeps its claim), so an account that never confirms can hold such
    previews as its own uploads, locked.
  - Retention: the locked preview follows the usual purge; its
    `welcome_pending` and `anon_previews` rows and the day's network claims go
    at the same cutoff, and with `delete_audit`.
  - `/panel` adds "Vistas previas sin cuenta" by tag: how many previews were
    uploaded without an account and how many went on an account afterwards
    (`funnel.STAGES` `anon_previews` and `anon_linked`).
  - **The terms and privacy pages** (2026-10-09, `LEGAL_UPDATED`; they were
    left open by the branch that added the switch). With the switch on,
    "Tu cuenta" (`legal._account_terms`) says that with an account there are
    3 free previews a calendar month, also counted per network; that without
    an account each network can see the class and red flags of
    `ANON_PREVIEWS_PER_NETWORK_PER_DAY` (2) files a day
    (`ANON_PREVIEWS_PER_IPV4_PER_DAY`, 6, from an IPv4 address, often shared);
    that the full report needs an account; and what moving one of those
    previews to an account does: with the free first report on, it can open
    as that report under the same limits, otherwise it takes one of the
    month's previews while any are left (the code counts it with
    `_claim_month_preview`, so the earlier proposal "those previews do not
    count among your account's 3" was not what the code does). The privacy
    policy (`legal._anon_keeps`) lists what such an upload keeps: the
    language, the link tag (`rigor_ref`), the date and when it moved to an
    account; the browser's identifier (hash only) and the network address
    and, only with the free first report on, the file's SHA-256 (under the
    paid offer `welcome_pending.file_sha256` is stored empty: nothing would
    ever check it); and a hash of the network per day for the daily count.
    All of it goes with the report or at the retention purge, except the
    network's daily count (`free_claims` `anon:ip:*`), which only the purge
    removes (`Store.delete_audit` leaves it, so deleting a report does not
    give its network a preview back); the policy says so.
    - The welcome box's promise (`anon_preview_box`) cannot know whether the
      inbox already had its free report: the address is only known on
      signing up, and the notice afterwards (`welcome_refused_email`) says
      why it stayed a preview. Under the paid offer the box never promises a
      free report (see "Paid offer" below).
- **Paid offer** (`AUDIT_WELCOME_FULL_REPORT=false`,
  `AuditSettings.welcome_full_report`; `audit/paid_offer.py`). Decided by the
  owner on 2026-10-09 and planned for production together with
  `AUDIT_ANON_PREVIEW=true` (the session that runs Railway sets both). The
  free tier's rule becomes "see the class first, pay for the full report":
  - Without an account (switch on), each network sees the class and red
    flags of 2 files a day (6 per IPv4 address); with a free account, 3
    previews a month as before. Every full report costs the price from the
    settings (`price_usd_cents`, the pack `pack_price_usd_cents`), from the
    first one, and the terms refund it on request within
    `paid_offer.REFUND_DAYS` (7) days of the payment (see "Terms and privacy").
  - No path grants a free full report: `_first_look` answers `off` (the
    upload is a preview, with no `acct=preview_*` notice), `_grantable_pending`
    finds nothing on confirming the e-mail, `_referrals_on` is off (no invite
    link, no reward), `_card_offer` is off (`off` is not a card refusal), and
    `_anon_to_account` puts a preview made without an account on the account
    as one of the month's previews (saved, past the cap), locked, with the
    usual purchase, never attaching its pending row. Access codes and credits
    open reports as always.
  - Every page says it with the same words (`paid_offer.COPY`, es/en/pt): free,
    without an account, the class and the red flags; the full report, with
    every figure and the PDF, costs USD 29; if it is no use, the money back
    when asked within 7 days of paying. The pages built around the offer take
    it as a parameter (`Offer`, from `paid_offer.offer_of(settings)`):
    `/precios` (a "Vista previa" card, the full report's and the pack's cards
    with their refund line next to the button, the closing call and the
    JSON-LD), the landing (the hero's line, "Cómo funciona", the price cards
    and the question «¿Y si el informe no me sirve?»), `/preguntas` (the
    price question and the refund question after it), `/auditar` (the notes),
    sign-up (the lead and "Así sigue"), the sample's band, the guides' "Lo
    que recibes" and the report's box. The box of a preview its own browser
    made without an account says «Crea tu cuenta y ábrelo completo por USD
    29» with the refund (`paid_offer.anon_box_text`); another browser with
    the link gets the usual box. The notice after signing up with a
    confirmation pending is `welcome_confirm_paid` (the link, and that
    confirming is needed to pay; nothing opens). "My account" takes the offer
    too (`account_page(offer=...)`): its e-mail card says confirming unlocks
    the purchases (`email_unverified_status_paid`,
    `email_delivery_unavailable_paid`), the confirmed notice names no rewards
    (`email_verified_paid`) and "What we keep" is `stores_paid`; a payment
    tried before confirming answers `email_checkout_required_paid`. The other
    public pages (articles and their closing calls, the
    audience pages, the examples, the tools, the calculators and the figure
    reader) keep their copy and are served through `web._offered`, which
    swaps each sentence that promised the free first report
    (`paid_offer.PROMISES`, regular expressions over the text, the
    descriptions and the JSON-LD) for the paid one. With the free first
    report on, nothing is rewritten: a test renders every sitemap page with
    it on and checks that each pattern still finds its sentence, and another
    renders every page, sign-up, the form, both kinds of report, "My account"
    before and after confirming and the refused payment with the paid offer
    and finds no promise of a free full report
    (`tests/test_audit_oferta_pago.py`).
  - The privacy policy and "What we keep" say what the free first report,
    its card check and the invites kept only of the accounts that had them,
    in the past ("cuando lo ofrecíamos", "when we offered it", "quando o
    oferecíamos"; "cuando había invitaciones"): their hashes stay. The
    browser mark (`rigor_device`) is described by what it does now: the
    browser that uploaded a preview without an account, and the notice of
    visits to "My account" (`legal._device_cookie_use`). The test allows a
    free report only in a sentence that carries that past marker.
- **Free first full report** (`AUDIT_WELCOME_FULL_REPORT=true`, the default
  `accounts.WELCOME_FULL_REPORT = True`;
  `WELCOME_REPORTS_PER_IP_PER_MONTH = 3` per IPv6 /64,
  `WELCOME_REPORTS_PER_IPV4_PER_MONTH = 10` per IPv4 address; not in free
  mode). Why IPv4 gets more (`accounts.network_cap`): mobile carriers in
  Mexico, Brazil and elsewhere put many customers behind one shared IPv4
  address (carrier-grade NAT), so a cap of 3 would turn a stranger's very
  first upload on a phone into a preview. The cost: someone on one IPv4
  connection who clears cookies and opens accounts with made-up addresses
  and different files can get up to 10 free reports a month instead of 3.
  E-mail confirmation (needs a mail provider) would close that. A signed-in
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
  file hashes stay. "Mi cuenta" shows it as Disponible/Usado, by the rule
  the upload applies: Usado when this account had it or when another account
  on the same inbox had it (`store.free_claim_taken(inbox.welcome_key(...))`),
  so the page never offers what the upload will refuse; an account without
  reports then reads "Subir un archivo" instead of "Subir mi primer archivo".
  The "file" is
  a fingerprint of what it says (`accounts.content_fingerprint`: timestamps
  and returns rounded to 5 decimals), so a trailing newline, other line
  endings or renamed columns do not make a new file. When the account's
  free report is unused but an upload becomes a preview for one of these
  reasons (browser, network), the preview says why
  (`account_pages.COPY["welcome_refused_*"]`).
  One per inbox (`audit/inbox.py`): the free report also takes the claim
  `welcome:inbox:<SHA-256 of the basic form>`, where the basic form is
  lower case, without a `+tag` and, for Gmail/Googlemail, without dots.
  Another account on the same inbox gets a preview with reason `email`.
  The claim stays after the account is deleted (hash only). While
  `AUDIT_EMAIL_VERIFICATION_REQUIRED=true`, an account with an unconfirmed
  address gets a preview with reason `unverified` and keeps its free
  report for after confirming. That preview is noted in `welcome_pending`
  (the upload's browser mark, file fingerprint and network) only if its file
  has not had a free report already (checked at upload with the fingerprint);
  confirming the address (`kind != "change"`) opens in full, from any device,
  the most recent one of the last `accounts.WELCOME_PENDING_DAYS` (7) days
  that the same account, inbox, browser, file, network and card rules still
  allow, gives the month's preview back and lands on
  `done=email_verified_report`; every pending row of the account goes either
  way, and with the report, the account or the retention purge. The preview's
  `acct=preview_unverified` notice is worked out when the page is shown:
  `welcome_refused_unverified` (this same report opens on confirming within
  the 7 days, if it is still the most recent upload that can get it) only
  while the owner is unconfirmed and this upload is the one confirming would
  open now; `welcome_pending_other` (which upload opens, with its conditions)
  for any other upload of an unconfirmed owner; `welcome_pending_confirmed`
  once the address is confirmed. `welcome_confirm` states the same rule. The
  account notice and the checkout refusal
  say so plainly (confirming unlocks the first free full report and
  purchases), and the notice after sign-up says a confirmation link was sent
  and to check spam (`welcome_confirm`, only while delivery is configured).
  While delivery is not ready (no provider, or the switch on with the mail
  not configured) the preview's notice is `welcome_refused_unverified_nomail`
  instead: confirmation is not available right now, and where to write
  (`AUDIT_OPERATOR_CONTACT` when it is an address, else the contact page);
  it never says a link was sent.
  A sign-up that returns to the upload page or to a report shows the same
  notice there (`?done=welcome_confirm`, `?acct=welcome_confirm`), only to a
  signed-in account whose address is still unconfirmed; a sign-up that
  returns anywhere else shows it on the account page only.
  Sign-up and e-mail change accept plain addresses only
  (`accounts.simple_email`, error `email_simple`): ASCII, one `@`, a name of
  1 to 64 characters from letters, digits and `._%+-` with no leading,
  trailing or doubled dot, and a domain of two labels or more (letters,
  digits, inner hyphens, 1 to 63 characters each) that ends in letters; no
  quotes, brackets, commas, spaces or IP addresses, 254 characters at most.
  Sign-in, recovery and the reset request keep the older, wider check, so an
  account made before the rule is never locked out. Sign-up and e-mail change refuse addresses
  on a list of 110 well-known temporary-inbox services and their mirror
  domains (`inbox.DISPOSABLE_DOMAINS`, exact or parent domain; error
  `email_disposable`): Guerrilla Mail (grr.la, pokemail.net, sharklasers.com…),
  Mailinator's public aliases, YOPmail's, 10minutemail, temp-mail, moakt,
  1secmail and the like; the list is not exhaustive.
  Sign-up and e-mail change also refuse reserved domains (example.com/net/org
  and `.example`, `.test`, `.invalid`, `.localhost`, `.local`) as `email_bad`
  when `AUDIT_ALLOW_RESERVED_EMAILS` is not `true` (the service default).
  They also refuse, as `email_no_domain`, an address whose domain DNS says
  takes no mail (`inbox.domain_takes_mail`): no such domain, a null MX
  (`0 .`), or neither MX nor A/AAAA records. Timeouts and any other DNS
  trouble let the address through (lookups give up after
  `inbox.DNS_LIFETIME_SECONDS`, 3 s), so a slow resolver never refuses a
  customer. On in the service; `AUDIT_SKIP_EMAIL_DNS=true` turns it off.
  Before those checks pass, sign-up asks «¿Quisiste decir ana@gmail.com?»
  (`email_typo`, ES/EN/PT) when the domain is one or two keystrokes from a
  well-known provider (`inbox.suggest_domain`: gmial.com, gmail.co,
  hotmal.com, outlok.com, yahooo.com, icloud.co…). Typo domains often have
  mail servers of a squatter's, so confirmation and recovery mail would
  reach a stranger. The form comes back with the corrected address; a box
  keeps the typed one, which still goes through every other check. Known
  providers (`inbox.COMMON_PROVIDERS`, e.g. mail.com, gmx.de) are never
  questioned, and neither are short names like aol or live beyond their
  ending (aon.com stays silent). The e-mail change asks the same question
  (`account_pages.email_typo_page`) once the current password is right and
  the two new addresses match: a page with the corrected address, the box
  that keeps the typed one, and the password again (it is never written on
  a page); the kept address goes through every other check, and the change
  itself (immediate, or pending confirmation) is unchanged.
  While e-mail confirmation is off, a shared IPv4 address gets
  `WELCOME_REPORTS_PER_IPV4_UNVERIFIED` (3) free reports a month instead of
  the carrier-sized `WELCOME_REPORTS_PER_IPV4_PER_MONTH` (10).
  **Card check, no charge.** When the free report is refused for a
  shared browser (`device`) or network (`network`) (`web.CARD_REFUSALS`),
  the card would clear every refusal (no other account on the same inbox
  had it, and the address is confirmed where confirmation is required) and
  live card sales are public (`card_public`), the owner's locked preview
  offers «Verificar tarjeta sin cargo» (`POST /audits/{id}/tarjeta`). It
  opens Stripe Checkout in setup mode (`payments.card_check_params`:
  `mode=setup`, card only, metadata `app=rigor`, `purpose=welcome_card`,
  `account_id`), which checks the card and charges nothing. The webhook
  branches on `mode=setup` before the paid path, so a setup session never
  unlocks a report; it and the return page (`card=checked&setup_session=`,
  signed-in owner only, same lookup limits as card payments) record the
  check only for Rigor's own finished session in the key's mode (a
  test-mode card never counts on a live key). Stripe's card fingerprint is
  read from the SetupIntent and kept only as a salted SHA-256 in
  `card_checks` (with the date) and as the claim `welcome:card:<sha256>`,
  so one card gives one free report ever: a second account gets
  `card_check_taken`. The account's next upload then skips the browser and
  network limits (and their claims) but keeps the account, inbox, file and
  e-mail confirmation rules. Without `card_public` (cards off, or a test
  key) nothing is recorded, and a post from another site is refused. The `card_checks` row goes with the account and is in «Descargar
  mis datos»; the claim stays, like the other free-report hashes. The
  preview itself stays locked: the customer uploads again.
  An invite is credited only once both the inviter's and the invitee's
  addresses are confirmed, whether or not confirmation is required
  elsewhere; with no mail service, no invite is credited.
  `/pt/registro` and `/pt/signup` answer 308 to `/pt/cadastro`, and a
  `next` may also be the upload pages `/auditar`, `/en/audit`, `/pt/auditar`.
- **Networks** (`accounts.network_address`): every free-tier limit that
  counts an address (free reports and previews per network, and their claim
  keys) counts an IPv6 address as its /64, since
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
  password hash, a session, reset or report token; the `not_included` note
  that says so is in the language of the page it was downloaded from
  (`export_not_included`), the keys of the file stay in English. Backs the "Qué
  guardamos" block and the right of access in /privacidad. A browser-flagged
  cross-site request is sent back to the account page; a report saved from
  someone else's link shows its description only once paid
  (`store.account_export`).
- **Mis estrategias** (`audit/strategies.py`, tables `strategies` and
  `strategy_reports`): an account names a strategy and files reports of its
  own list under it (one strategy per report, 50 strategies per account),
  from the form on "Mi cuenta" or after the fact; filing without a name, a
  report or a strategy comes back to the account with "Elige un informe de
  tu lista y una estrategia, o escribe un nombre" (`file_bad`), and the
  51st strategy with `strategy_full`, both read from `strategies.COPY`
  (`account_pages.STRATEGY_ERRORS`). `/cuenta/estrategias/<id>`
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
  `/pt/cadastro`) with copy, native share, WhatsApp, Telegram and Reddit
  actions, how many joined, how many wait for
  their first report and the credits received (this month out of the cap).
  A sign-up through the link is noted unless the token is unknown, the
  inviter is still signed in in that browser, or the browser carries the
  mark of the inviter's own free report. The inviter gets
  `accounts.REFERRAL_CREDITS` (1) full-report credit, as an access code no
  one sees linked to the inviter, only when the new account's free first
  report is granted, so the free tier's browser, file and address limits
  already held; it is refused as `self` when that upload's browser mark
  is one the inviter used (its free report, previews, own uploads),
  as `cap` past `accounts.REFERRAL_MONTHLY_CAP` (5) credited invites for that
  inviter in the calendar month, and as `budget` after the service-wide
  `AUDIT_REFERRAL_GLOBAL_MONTHLY_CAP` is spent. Both caps reserve unique slots
  in the same transaction, so simultaneous rewards cannot pass them.
  The inviter never sees who joined. Rows go with the inviter's account; an
  invitee's deletion drops a pending row and keeps a decided one (dates,
  outcome, slot) under a random id with no browser mark, so deleting
  credited invitees never frees the cap. They show in "Descargar mis datos".
  Set `AUDIT_REFERRAL_REWARDS=false` to stop new rewards; already earned
  credits remain usable. Off in free mode, without the free first report,
  and while e-mail delivery is not configured: a credit needs both addresses
  confirmed, so without mail the section and the invite link are not shown
  and no sign-up is noted as invited.
- **Email ownership and recovery** (`verified_emails`, `email_outbox`): new
  accounts and legacy accounts are unverified until they explicitly POST a
  confirmation form opened from their email. GET only renders the form, so
  mail-link previews do not consume it. A new address stays pending while the
  old address remains the account login; confirmation atomically changes it.
  Unknown and known addresses receive the same reset-request response; reset
  is one-use, valid for one hour and revokes sessions. The durable outbox keeps
  recipient, purpose, locale, state, attempts and expiry, but derives the
  usable link from a random id plus a stable HMAC secret only during sending.
  Failed SMTP attempts are retried after a lease, under one Message-ID (which
  is also the provider's idempotency key), so a retry is never delivered
  twice. A resend the customer asks for (at most one every ten minutes per
  challenge) keeps the challenge, its link and its expiry, starts its own
  eight tries and gets its own Message-ID (`mail.message_key`: the outbox id
  plus a mark made from the last delivery's time), so the provider delivers
  it. The same request revives a message whose tries ran out while it was
  still `queued`, or `sending` with its lease expired. The retention purge removes
  expired rows after a 30-day cleanup window when the scheduled purge is
  enabled or the operator runs it. No real messages are sent by the test suite.
  With `AUDIT_EMAIL_VERIFICATION_REQUIRED=false`, the older immediate email
  change remains for migration compatibility and is **not a verified flow**.
  Do not launch paid sales with this switch off; configure and test SMTP,
  enable the switch, and get existing accounts confirmed first.
- **Pages** (Spanish default, English paths): `/registro` `/signup`,
  `/entrar` `/login`, `/cuenta` `/account` ("Mis informes"), `/olvide`
  `/forgot`, `/restablecer` `/reset`; sign-out is a POST to `/salir` `/logout`.
  Every page links "Mi cuenta" from the navigation and the report header.
- **Mi cuenta in four parts** (`account_pages.ACCOUNT_PARTS`): one page, one
  address, four titled sections with fixed ids in every language:
  `#informes` (reports and strategies), `#creditos` (buying, access codes,
  purchases, invitations), `#seguridad` (e-mail confirmation, account
  protection, password, recovery key, two-step, passkeys, sessions,
  activity) and `#datos` (e-mail change, what the account keeps, data
  export, delete account). Four links stay under the top bar (CSS
  `position: sticky`, no script; they scroll sideways on a phone). The older
  ids (`#estrategias`, `#invitar`, `#verificar-correo`, `#proteccion`,
  `#recuperacion`, `#dos-pasos`, `#llaves`, `#sesiones`, `#actividad`,
  `#correo`) stay inside their part, so old links and redirects still land
  on their block. The page's message (`?done=`, `?error=`) is rendered in
  the same bar as the links, so it is in view wherever a redirect lands.
  The four parts always come in the order of the links; with no credits the
  "Créditos disponibles" counter links "Comprar créditos" to `#creditos`
  (only when there is a way to buy: chat, card or live card sales, and not
  in free mode), so buying stays one tap away. The counters read in the
  singular with 1 ("1 Informe", "1 Informe completo", "1 Crédito
  disponible"). Tests: `tests/test_audit_account_parts.py`,
  `tests/test_audit_account_polish.py`.
- **What lands on an account**: an upload made while signed in; a report
  opened by its link and saved with "Guardar en mi cuenta"; the code that
  unlocked a report while signed in; a code added by hand; a card purchase
  started while signed in (the report, and a pack's code with its credits).
  A report or a code belongs to one account at most. A code added by hand
  must still be usable (`store.code_usable`: not disabled, not expired,
  credits left); a disabled, expired or spent code is refused with
  `code_unusable` and not linked, and one already on the account keeps
  `code_already`.
- **Credits**: a locked report of a signed-in customer shows "Desbloquear con
  1 crédito de tu cuenta" when their codes have credits left. The code that
  expires first is spent first; the credit and the unlock share one
  transaction, as with a typed code.
- **From the list**: each full report links its PDF (`/audits/{id}/pdf`, opened
  by the owner's session without the token) and, when published, its public
  `/v/` page. Each row shows the date with the time (UTC, hours and minutes)
  and the first 8 characters of the report's id under it, so two reports of
  one day are told apart (the strategies form shows the same id); on a phone
  the line wraps under the date. The "¿Necesitas créditos?" box shows the
  single and pack prices from the settings and a WhatsApp link with the
  request typed, and says that the credit is delivered at once and that a
  refund can be asked within 7 days under the terms (`buy_final_sale_note`),
  as the card form's box does.
- **Comparing**: with two or more full reports, "Mis informes" lets the
  customer tick two or three and open `/cuenta/comparar` (`/account/comparar`),
  the same side-by-side view as `/comparar` without pasting private links. It
  is a read-only GET; every report must be on the signed-in account's list,
  not purged and unlocked (or free mode), and appear once; anything else goes
  back to the list.
- **Opening a report**: the owner opens `/audits/{id}` without the token; any
  other visitor still needs the token (a wrong one is a 404).
- **Security**: scrypt password hashes (N=2^14, r=8, p=1, 16-byte salt);
  at sign-up, password change and reset `accounts.common_password` refuses,
  offline, keyboard and digit runs, repeated units, digits only, common
  EN/ES/PT words or the e-mail's name (with or without its own digits) with
  digits or symbols around them, and the address itself however it is
  spaced or cased;
  sign-up and "Mi cuenta" list what the account keeps and how to delete it;
  session cookie `rigor_session`, 256-bit, `HttpOnly`, `SameSite=Lax`,
  `Secure` on https, 30 days, stored only as SHA-256; CSRF tokens on every
  form (double-submit cookie `rigor_csrf` before sign-in, the session's token
  after); a wrong current password on an account form (password, e-mail,
  delete, two-step, recovery key, passkeys) answers `wrong_current` ("La
  contraseña actual no coincide."), never the sign-in's "El correo o la
  contraseña no coinciden", and a refused new password says why
  (`password_short`, `password_long`, `password_bad`, `password_common`); 10 failed sign-ins per hour per (address, e-mail) pair, with
  ceilings of 50 per address and 50 per e-mail (a slow-down against guesses
  spread over many addresses; past the e-mail ceiling an address gets
  `SIGNIN_TRIES_PAST_EMAIL_CEILING = 2` tries on that e-mail, so a stranger
  who knows it cannot lock the owner out), and 5 sign-ups per hour per
  network (`MAX_SIGNUPS_PER_HOUR`): a sign-up is a form that passed every
  check, whether the account was created or the address turned out to be
  taken, so the limit still stops mass sign-ups and address probing. A form
  sent back (a wrong address or password, the «¿Quisiste decir…?» question)
  counts against its own ceiling of 30 per hour per network
  (`MAX_INVALID_SIGNUPS_PER_HOUR`), past which the form answers 429 before
  checking anything; a customer with a typo and a weak password never spends
  a sign-up. Both 429 answers carry `Retry-After: 3600`
  (`SIGNUP_RETRY_AFTER_SECONDS`). These counters and the panel's wrong-key limit live in the
  `attempts` table (keys hashed, rows older than the hour deleted), so a
  deploy does not reset them. A password change or reset signs out the other
  sessions; `next` only returns to `/audits/`, `/cuenta` paths or exactly
  `/` and `/en` (with an anchor), or an upload page, alone or with exactly
  `?extras=1`. A report's private key is never written inside `next`: a
  signed-out visitor leaves a report through `POST /audits/{id}/account`
  (or any report form), which names the report in `next` and keeps the key
  for up to an hour in the cookie `rigor_report` (HttpOnly, SameSite=Lax,
  Secure on https). After sign-in (password, second step or passkey) the
  cookie gives the key back to that same report only and is cleared; an
  older link with the key inside `next` is redirected to the clean address
  (sign-in, sign-up and second-step pages; the passkey page moves it to the
  cookie too). `POST /audits/{id}/account` answers 403 to a post from
  another site, like the upload.
  POST `/audits` answers 403 to a browser
  post from another site, a second layer beside the `SameSite=Lax` cookie:
  `Sec-Fetch-Site` decides when present (only `same-origin` and `none` pass;
  `same-site` is refused, as other apps on the parent domain count as same
  site); without it, the Origin (else Referer) must be this service. Our
  pages send `Referrer-Policy: no-referrer`, so a real form post carries
  `Origin: null`; that, like no header at all (scripts), is no signal.
- **E-mail configurable**. With `AUDIT_EMAIL_VERIFICATION_REQUIRED=true`,
  encrypted SMTP and a stable token secret, new and existing accounts confirm
  their addresses through one-use links; an unknown and a known address get
  the same reset-request response. The SMTP worker retries from a database
  outbox after restart. This migration switch defaults to false, so legacy
  immediate address changes remain possible until the operator explicitly
  enables confirmation. A customer can still use a recovery key or request
  an owner-issued one-time reset link through `/panel` or
  `quant-trade audit account-reset EMAIL`. A verified sending domain,
  transport credentials and delivery monitoring are operator requirements;
  no provider is configured or contacted by the tests.
- **Recovery key** (`recovery_keys` table, `/cuenta/recuperacion`, `POST
  /olvide`): so a customer who forgets the password needs no one, "Mi
  cuenta" makes a recovery key after the current password: 20 characters
  from 32 unambiguous ones (100 random bits, `accounts.new_recovery_key`),
  shown once with `Cache-Control: no-store`; only its SHA-256 and date are
  kept, and making a new one replaces the old. Mi cuenta nudges accounts
  without one. `/olvide` introduces what it offers in the order the page
  shows it: the e-mail link first when delivery is ready (`recover_lead_mail`),
  else the key and writing to the operator (`recover_lead`). On `/olvide`,
  e-mail + key + new password sets the password,
  spends the key (a delete that names its hash, so it works once) and signs
  out every session. Every try counts toward
  `accounts.MAX_RECOVERY_TRIES_PER_HOUR` (10) per network and per e-mail; an
  unknown e-mail and a wrong key give the same answer (someone spamming an
  e-mail can hold its recovery for an hour; the key itself is untouched and
  the owner's reset link still works). The key's date is in
  the data export; the row goes with the account. The account forms that ask
  for the current password (recovery key, password change, deletion) share
  `accounts.MAX_ACCOUNT_ACTIONS_PER_HOUR` per network and per account.
- **Two-step sign-in** (`two_step` and `two_step_challenges` tables,
  `/cuenta/dos-pasos`, `/entrar/codigo`, EN `/login/code`): optional, with an
  authenticator app (TOTP, RFC 6238: HMAC-SHA1, 6 digits, 30 s, one step of
  drift, `accounts.totp_match`). Turning it on asks for the password and needs
  a recovery key first; the page shows the 160-bit secret once, as a QR code
  drawn in the page (`segno`, inline SVG, nothing loaded from outside) and as
  text, and nothing changes until a first code confirms it (which also signs
  out the account's other browsers). After a correct
  password, a two-step account gets a 5-minute challenge cookie
  (`rigor_2step`, only its hash stored) instead of a session; the code page
  accepts a code only if its step is newer than the last one used (an
  update that names the step, so a code never works twice, even at once).
  Code tries count toward `accounts.MAX_TOTP_TRIES_PER_HOUR` (10) per network
  and per account. A lost phone: the recovery key on the code page (after
  the password) signs in once and turns two-step off. On `/olvide`, a
  two-step account needs the key and a current code (the key is checked
  first without being spent, so only its holder learns two-step is on), so
  the key alone never takes the account; a lost phone and a forgotten
  password go to the owner. Turning it off in Mi
  cuenta asks for a current code. The owner can turn it off with
  `quant-trade audit account-two-step-off EMAIL --yes` after checking the
  request. The secret is stored as is (a code check needs it); the export
  shows only when it was turned on.
- **Open sessions** (`session_info` table, "Sesiones abiertas" in Mi cuenta,
  `/cuenta/sesiones/cerrar` and `/cerrar-otras`): each session keeps a short
  device label (`accounts.device_label`, such as "Chrome · Windows"; the full
  browser string is never stored), its network (`accounts.network_address`)
  and its last use, updated at most every 10 minutes, with a random handle
  to sign it out by (never the token or its hash). The list marks this
  browser; signing out this browser's own row signs it out. Sessions opened
  before the table existed fill in on their next use. Rows go with their
  session (sign-out, "sign out the others", password change, expiry through
  `purge_sessions`) and with the account; the export lists each session's
  device, network and last use.
- **Recent activity** (`account_events` table, "Actividad reciente" in Mi
  cuenta): each sign-in (password only, with the app's code, or with the
  recovery key), sign-up, password change (in the account, with the recovery
  key or with an owner reset link), two-step on or off (also by the owner's
  `audit account-two-step-off`), new recovery key and session signed out,
  with its time, device label and network (the same values as "Sesiones
  abiertas"). The latest 50 per account are kept (`store.ACCOUNT_EVENT_MAX`);
  older than 90 days (`ACCOUNT_EVENT_DAYS`) they go with `purge_sessions`,
  which every sign-in runs. They go with the account, and the export lists
  them under `activity`.
- **Wrong-password lines** (`failed_signins` table, shown in "Actividad
  reciente" as "Contraseña incorrecta (N intentos)"): a wrong password for an
  existing account counts on one line per network and hour (device label and
  time of the last try; never the typed e-mail or password). The line is
  written by a background task after the reply is sent, so a real account
  answers as fast as an unknown e-mail (no account-existence timing signal).
  Their own cap, `store.FAILED_SIGNIN_MAX` (20 lines), keeps a flood from
  pushing real events out, and the card shows at most 5 beside 20 real
  events. They go after 90 days with `purge_sessions`, with the account, and
  the export lists them under `failed_signins`. Rate-limited tries (429) are
  not counted.
- **Since your last visit** (`account_seen` table, one row per account and
  browser, keyed by the hash of the browser's `rigor_device` cookie, minted
  on the first view when missing): each view of Mi cuenta marks the time for
  this browser (`store.take_visit_notice`) and, when something happened
  since its previous view, shows a notice on top once: wrong-password tries
  added since (each line's count at that view is kept in `failed_json`, so a
  line that spans it counts only the newer tries) and sign-ins from another
  device label the account had not used before that view. Per browser, so
  an intruder who signs in and opens Mi cuenta, even with the owner's
  label, never clears the owner's notice; a browser's first view shows
  nothing, so a newcomer learns nothing. At most `store.SEEN_DEVICES_MAX`
  rows: past it a newcomer is not stored rather than pushing anyone out;
  rows unseen for 90 days go with `purge_sessions`. Limits: clearing
  cookies makes the next view a first view; labels are coarse, so an
  intruder with the owner's label is never a "new device" (their tries
  still show); tabs opened at the same instant may each show it. The rows
  go with the account and the export lists device and time as
  `account_page_seen` (never the browser hash).
- **Cambiar correo** (`POST /cuenta/correo`): on Mi cuenta, the new
  sign-in e-mail typed twice plus the current password. With verification
  enabled, the old address remains active until a one-use link sent to the
  new address is explicitly confirmed by POST; GET only previews the action.
  In legacy mode the change remains immediate. An address another account
  uses is refused without saying whose it is. The other sessions are signed
  out when the change completes, and "Actividad reciente" gets an
  "E-mail changed" line (never either address). Passkeys stay bound to the
  account, though a device may show the former address as their name.
- **Protección de tu cuenta**: first in the security part of Mi cuenta, a card lists the recovery
  key, two-step sign-in and a passkey (only where passkeys work), each as
  on or with a link to its card, and counts how many are on. Two-step
  links to the recovery key while there is none, since it needs one. With
  everything on, it shrinks to one line. It reads existing rows only and
  stores nothing.
- **Passkeys** (`passkeys.py` on `webauthn`, py_webauthn by Duo Labs;
  `passkeys` and `passkey_challenges` tables): on Mi cuenta, "Llaves de
  acceso" adds one after the current password (`POST /cuenta/llaves`, then
  `/cuenta/llaves/guardar`) and removes one, also after the password
  (`/cuenta/llaves/quitar`); at
  most `passkeys.MAX_PER_ACCOUNT` (10). The sign-in page offers "Entrar con
  una llave de acceso" (`/entrar/llave`, EN `/login/passkey`, PT
  `/pt/entrar/chave`): a discoverable credential, so no e-mail is typed, and
  the device must check its owner (fingerprint, face or PIN, user
  verification required); device plus that check are two factors, so on a
  two-step account the passkey is enough. After a correct password, the
  code page also offers the account's passkeys in place of the code
  (`/entrar/codigo/llave`). Each passkey page stores a random 32-byte
  challenge for 5 minutes behind the `rigor_passkey` cookie (only its hash
  is the key), used once; `passkeys.MAX_STARTS_PER_HOUR` pages per network.
  The options are embedded in the page and `app.js` posts the device's
  answer in an ordinary form (no fetch; the CSP allows only
  `connect-src 'self'`, for the upload form). The
  store keeps the credential id, the public key, the counter (a counter
  that goes backwards is refused; synced passkeys report zero), the name,
  the host it was made for and dates; never a private key. Events
  `signin_passkey`, `passkey_added`, `passkey_removed`; the export lists
  name, site and dates as `passkeys`; the rows go with the account.
  The relying party is the host of `AUDIT_BASE_URL`, and the buttons show
  only on requests that reached that host. **Changing the domain**: a
  passkey is bound by the browser to the host it was made on, so after
  `AUDIT_BASE_URL` moves to a new domain the old passkeys stop working
  there. Nothing else changes: the password, the two-step code and the
  recovery key keep working, the card lists each old passkey as "Solo
  funciona en <old host>", and customers add a new one on the new domain
  and remove the old. Announce it before the switch; there is no way to
  move a passkey between domains.
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
dates, what was audited, the data period, the days between the last data
point and the audit, the six dimension statuses with their plain-language
text, the input hashes and `dataset_digest`, the source format, the engine
version, the declared trials and the trials used, the SHA-256 of the result,
and a fixed notice. It never shows the files, the trades, the description or
the token, and never a return, Sharpe, drawdown or other result figure.

The kind of upload (`report_kind`: backtest, account history or fund's track
record) is read once and drives the class sentence (`class_text(..., kind=)`),
the dimension cards (`meaning(..., account=, fund=)`, for example
`costs.FAIL.account` and `out_of_sample.NOT_MEASURED.account`) and the share
text, so an account's page never calls it a backtest. The details table (still
the page's second and last `<table class='kv'>`) gains three rows:

- "Qué se auditó" / "What was audited" / "O que foi auditado": Backtest,
  "Historial de cuenta real o demo" / "Live or demo account history" /
  "Histórico de conta real ou demo", or "Historial de un fondo" / "A fund's
  track record" / "Histórico de um fundo".
- "Periodo de los datos" / "Data period" / "Período dos dados": first and last
  dates (`inputs.first_timestamp`, `inputs.last_timestamp`) and the sampling
  frequency (`inputs.frequency_label`, in the report's `FREQUENCY_TEXT`). No
  count of observations or trades: the privacy policy and the terms
  (`legal.py`) list what the page shows and what the purge keeps (class,
  dimension statuses, hashes, dates, trials, engine version) and say it never
  shows the trades, so a count would need that text changed first.
- "Días entre el último dato y la auditoría" / "Days between the last data
  point and the audit" / "Dias entre o último dado e a auditoria": calendar
  days from the last data point to the audit date (`report.data_age_days`),
  with the `MEASURED` badge.

When the trials used carry `NOT_MEASURED` (never declared, computed at 1),
that row shows "—", its badge and "sin declarar; se calcula con 1, el caso
más favorable" instead of "1". A view kept before these rows existed has no
dates, and the page leaves those rows out.

The consent text next to the publish button (`publish_help`, es/en/pt) and
the FAQs (`faq.py` publishing answer, the home FAQ's "what happens to my
file") name what was audited and the data period alongside the class,
dimensions and hashes, so the owner knows the dates go public before
publishing.

The retention purge does not take a published page down: for a published
unpaid audit it keeps, in the `publication_views` table, only the fields the
page reads (class, dimension statuses, input hashes, source format, engine
name and version, declared and used trials, the audit date, whether it is a
fund track record, a single boolean, the first and last timestamps and the
frequency label; no number of observations and no trade count) and the
SHA-256 of the full result, so the page, its result hash and
an embedded badge stay exactly as they were. The description, client text findings, series,
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

The private report's hero also states the data period ("Datos" / "Data" /
"Dados", first → last date) and the days between the last data point and the
audit (`data_age`, in the singular for one day). An account history whose last
point is more than 30 days before the audit adds under the verdict: "Lo que
pasó después del último dato no está en este archivo." / "What happened after
the last data point is not in this file." / "O que aconteceu depois do último
dado não está neste arquivo." The data-quality `WEAK` sentence now points to
the full report's warnings instead of the red flags and vendor questions,
which `/v` does not show.

### File consistency page (`audit/forensics_web.py`, behind a switch)

Planned and hidden: `forensics_web.FORENSICS_ENABLED` is a constant in the
repository (not a Railway variable) and, while it is `False`, `register`
mounts nothing and every path answers 404. When on, `GET
/audits/{audit_id}/coherencia` (Spanish), `/consistency` (English) and
`/coerencia` (Portuguese; `?lang=` overrides the path's language as on the
report) shows the private "Coherencia del archivo" page: it opens exactly
like the report (its token or the signed-in owner, 404 for a stranger, 410
once purged) and only for a paid report or in free mode (402 otherwise),
re-reads the stored platform file (the `report.*` blob, else `live.*`, else
a monthly table uploaded as the equity file) after checking its SHA-256
against the digest recorded at upload, runs the battery
(`audit/forensics/review`) under an audit slot (503 with a retry note when
none is free), keeps results in an in-process LRU of 256 keyed by audit,
`METHOD_VERSION` and file hash, and limits uncached reviews to 30 per client
address and hour (429). The page shows the file's family, format and method
version, a summary (a sentence per SIGNAL or INFO check made of the measured
fact, "puede tener explicaciones legítimas; conviene aclararlo con quien
generó el archivo" and, for INFO, why it is not a signal; with no finding,
"no encontramos las huellas que revisamos; eso no prueba que el archivo sea
original"), the table of every check with its status chip ("Señal", "Dato",
"Sin hallazgo", "No medido"; never "limpio"), its figures with their
evidence tags, the reason of every `NOT_MEASURED` in words, the calibration
line per check, and the limits (a carefully edited file passes; nothing
proves the broker issued the file). Every sentence lives in
`audit/forensics/copy.py` with identical keys in es, en and pt and passes
the guard; figures are counts, codes, dates and row indexes, so no text of
the file reaches the page, and nothing here changes a class. The report's
link to the page is added by the report's owner later.

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

**IndexNow** (`audit/indexnow.py`, `tests/test_audit_indexnow.py`). The
[IndexNow protocol](https://www.indexnow.org/documentation) tells Bing (and
through it DuckDuckGo, Yahoo and ChatGPT's search), Yandex, Seznam and Naver
that a page exists, without waiting for their crawl. Google does not use it;
Search Console covers Google. The key is public by design: the site always
serves it as `text/plain` at `/<key>.txt` (today
`/f5a5a16c542ab2277bfa9656ce368b3d.txt`, with the site's security headers),
no other `.txt` is added (an unknown `/<name>.txt` is a 404 and
`/robots.txt` is unchanged), the file is not in the sitemap and `robots.txt`
does not close it. The default is `indexnow.INDEXNOW_KEY`;
`AUDIT_INDEXNOW_KEY` replaces it (see the variables table). The web service
never submits anything: the owner runs

```
quant-trade audit indexnow --dry-run                     # count and first 5 URLs, sends nothing
quant-trade audit indexnow                               # submit https://rigorscore.com
quant-trade audit indexnow --site https://rigorscore.com # same, explicit
```

after a deploy that adds or changes public pages. The URLs are the ones
`seo.sitemap_xml(site)` lists, built locally (nothing is downloaded), kept
only when they are `https` on the site's host (anything else, `www.`
included, is dropped and counted) and sent once each, in POSTs of at most
10,000 URLs to `https://api.indexnow.org/indexnow` with the JSON body
`{"host", "key", "keyLocation", "urlList"}`. Each batch prints its HTTP status
and the documentation's name for it: 200 (OK) and 202 (Accepted, key
validation pending) are accepted; 400 (Bad request), 403 (Forbidden: key file
missing or different), 422 (Unprocessable Entity: URL off the host or a key
outside the protocol), 429 (Too Many Requests) and any network failure (only
its kind is printed) are errors and the command exits 1. Run it after the new
key file is live, and with the same `AUDIT_INDEXNOW_KEY` as the server when
the variable is set there, or the engines answer 403.

Launch basics (2026-09-28, `tests/test_audit_launch_basics.py`):

- **Icon.** `/favicon.ico` (16, 32 and 48 px) and `/apple-touch-icon.png`
  (180 px) are files in `audit/static/`, drawn from the brand mark by
  `tools/make_favicon.py` with the standard library only. They are served
  from the static allow-list (`theme.ICON_PATHS`) with the static files'
  one-week `Cache-Control`, and every page links them next to the inline SVG
  icon. Both are same-origin images, which `img-src 'self' data:` allows.
- **Private by address, not by prefix.** `seo.is_private_path` decides the
  `X-Robots-Tag` header: a path is private when it is a `DISALLOWED_PATHS`
  entry or a page below it, so `/pt/contato` (contact) is no longer caught
  by `/pt/conta` (account). `robots.txt` rules match by prefix, so the file
  keeps `Disallow: /pt/conta` and adds `Allow: /pt/contato` before it: the
  longer rule wins. A test compares every route with every private prefix;
  `/pt/contato` is the only such pair.
- **Header-only pages.** `/comparar`, `/compare`, `/pt/comparar` and the
  e-mail confirmation pages (`/confirmar-correo`, `/confirm-email`,
  `/pt/confirmar-email`) send `X-Robots-Tag: noindex, nofollow`
  (`seo.NOINDEX_PATHS`). They are not in `robots.txt`: a crawler that is kept
  out of a page cannot read its `noindex`.
- **Sitemap.** The three contact pages and the Portuguese terms and privacy
  pages are in `PUBLIC_PAGES`, so they have canonical, `og:url`, `hreflang`
  and a sitemap entry like the other public pages.
- **Error pages by address.** Without `?lang=`, an error page is Portuguese
  under `/pt`, English under `/en` and under the English addresses that have
  no prefix (`web.ENGLISH_ROOTS`, read from `PUBLIC_PAGES`, the account and
  e-mail paths and the comparison path), and Spanish otherwise. A short
  address that forwards to an English page (`/pricing`, `/contact`,
  `/support`) counts as English too. `?lang=` still decides. The 413 and
  "busy" pages built before routing (`_scope_locale`) follow the same rule.
- **Short addresses.** The addresses that forward to a page (`/soporte`,
  `/contact`, `/pricing`, `/en/terms`...) and the icon addresses are
  handlers without parameters: the target and the file are fixed in the
  code, and a query string cannot change them. Two of them,
  `/en/calculator` and `/reading`, pass the query string along
  (`_forward(..., keep_query=True)`) so a shared calculator or reader link
  keeps its figures; their target path is still fixed in the code.
- **Sample title.** The tab title of `/ejemplo` and `/pt/exemplo` ends in
  "ejemplo" and "exemplo" instead of the report id "sample". The report and
  its numbers are untouched.

### Articles about backtests (`audit/articles.py`)

Short articles for readers who arrive from a search engine, at `/articulos`,
`/articles` and `/pt/artigos` (`ARTICLES_PATH`), one page per article under
them (`/articulos/<slug>`, `/articles/<slug>`, `/pt/artigos/<slug>`, each
language with its own slug). The copy lives in `ARTICLES_DATA`, a tuple of
plain dictionaries with the shape `{"key", "slug": {es, en, pt}, "title":
{..}, "summary": {..}, "intro": {..}, "sections": {es: [{"heading",
"paragraphs": [..]}], ..}, "faq": {es: [{"q", "a"}], ..}, "related":
[{"kind": "calculator"} | {"kind": "guide", "slug": ..} | {"kind":
"audience", "slug": ..} | {"kind": "method"}]}`; `Article.from_dict` builds
the dataclasses from it and refuses an unknown related kind or a guide or
audience slug that does not exist, so a typo fails at import, not on a
page. A page shows the intro, the sections as `h2` and paragraphs, the
questions as `h3`, the
related pages (the free calculator, an export guide, an audience page or
the method, each in the page's language) and a closing call worded without
a promise. The side button and the closing call follow the article's own
next step (`Article.next_step`, from `articles.ARTICLE_NEXT_STEPS`; see
"Conversion toward the first free report" below); an article missing from
that table keeps the free calculator and the free first report. The guides
index links the articles index in each language so crawlers reach it. The
three articles are `ea-sobreoptimizado` (how to tell whether an expert
advisor is overfitted before buying it), `backtest-costos-reales` (spread,
commission, slippage and swap, and the break-even cost) and
`leer-informe-probador-mt5` (reading the MT5 strategy tester report and
what it leaves out); every figure in them comes from the calculator's own
table (the best of N configurations with no edge), never from an outside
study.

To add an article: append one dictionary to `ARTICLES_DATA` with every text
in Spanish, English and Portuguese (no Spanish words on the Portuguese
page), slugs in the three languages and the related pages by their Spanish
slug; run `tests/test_audit_articles.py`, which checks the shape, runs the
profit-claim guard over every text and every rendered page, and checks the
metadata, the `hreflang` alternates, the 301 of a slug from another
language and the 404 of an unknown one. `seo.PUBLIC_PAGES` reads
`ARTICLES`, so the sitemap, the canonical links and `web.ENGLISH_ROOTS` pick
the new page up with no further change.

### Terms and privacy

A 7-day refund (Sergio's decision, 2026-10-09, replacing "all sales are
final" of 2026-09-28; `legal._refund`, ES/EN/PT): if a paid report, or a
single credit bought from "My account", is no use,
the buyer writes to the support contact within `paid_offer.REFUND_DAYS` (7)
days of the payment, with the report's or the purchase's id, and gets the
full amount back. A pack with no credit used in those 7 days is refunded in
full; with some used, the part of the unused credits (a pack bought by card
from a report has already used one: that report's). A duplicate charge or a
charge that delivered no report is always refunded. The operator refunds a
card payment by hand from the Stripe dashboard, to the same payment method
in the bank's times; a code paid outside the site, through the method it was
paid with. The terms keep the sentence that statutory rights are not
limited. Before Checkout the buyer must tick "the report opens at once and I
can ask for a refund within 7 days under the terms" (`final_sale=yes`,
ES/EN/PT; same field and logic as before, only the words changed); the
acceptance and the terms version (`legal.LEGAL_UPDATED`) are kept per order
in the additive table `checkout_order_terms`, as evidence for a chargeback.
A full report that misreads the file (trades, balance or dates that do not
match the platform) is fixed or replaced by a new credit (`quant-trade audit
codes create --credits 1`). What a refund does in the code: `refund.created`
(and `refund.updated`, `refund.failed`) is recorded with
`store.record_stripe_refund` for the owner panel; nothing locks the report
again and nothing removes credits, so the terms promise neither. After
refunding a pack or credits, disable the code by hand (below) so its unused
credits go too. `/precios` (next to the full report's and the pack's
buttons), `/preguntas` and the landing («¿Y si el informe no me sirve?»)
repeat it under the paid offer (`paid_offer.refund_text`,
`paid_offer.pack_refund_text`, `paid_offer.refund_question`).

Credits bought from "My account" follow the same rules: the same required
box (worded for a credit), stored in `checkout_order_terms`, and the same
7-day refund. The credits sit on a code derived from the Stripe session with the
webhook secret (`payments.credit_code`), linked to the buyer's account, so a
Stripe retry never grants twice and the buyer never has to type a code. A
paid session held for review (billing country) blocks a second purchase
from that account until the owner resolves it in `/panel`. A payment for an
account deleted before the webhook grants nothing and is listed there too. A
Stripe refund is only recorded; after refunding a credit order by hand, disable
its code (`quant-trade audit codes disable <id>`, or «Desactivar» in `/panel`) so
its unused credits go too.

An open Checkout session is reused only in the language it was opened in
(the reuse slot is plan plus language), so a buyer who switches to English or
Portuguese gets Stripe's page and product name in that language
(`tests/test_audit_account_credit_purchase.py::test_switching_language_opens_a_checkout_in_that_language`).

The session left open in the other language is then expired at Stripe
(`POST /v1/checkout/sessions/{id}/expire`), so the same purchase is not
payable twice for a day. Rules (`payments.expire_superseded`,
`tests/test_audit_checkout_language.py`):

- Only the same purchase: the same report, or the same account's credits,
  and the same plan, held by the reuse slot of another language. Another
  plan, another report and another account are left alone.
- Only an order made no later than the new one: a slow older request that
  finishes last never closes the session the buyer moved on to; both stay
  open, as before this rule.
- Only an order that is `open`, has a session id and is not past its expiry.
  An order that is `paid_review`, `delivered` or `duplicate` is never sent to
  Stripe, and Stripe itself refuses to expire a session that is complete, so
  a payment that got there first is never undone.
- Best effort, after the redirect: the call runs as a background task once
  the buyer has been sent to the new session, with one attempt and a
  10-second timeout (`payments.EXPIRE_TIMEOUT_SECONDS`). A refusal, a timeout
  or any error is logged with the session id and the error class only and
  changes nothing: the old order stays reusable in its language, as before
  this rule, and the next new session of that purchase tries again.
- When the expiry call fails, the session is read once with the same
  timeout: if Stripe already holds it as `expired` (the answer was lost, or
  another request expired it) the order is marked like any expired one. A
  session Stripe holds as `complete` or `open` is never marked. Until a later
  language switch repairs it, a session expired at Stripe but not marked
  here is still offered in its own language and shows Stripe's expired page.
- At most `payments.EXPIRIES_PER_HOUR` (6) expiry calls per purchase and per
  account in an hour, counted in memory per process. Past the limit the old
  session is left open and reused in its language, so switching back and
  forth opens at most two more sessions instead of one per click.
- The call uses the SDK's `StripeClient` (`stripe>=8.0`), through its `v1`
  namespace when the installed SDK has one.
- Once Stripe answers `expired`, the old order keeps its status `open`, its
  session id and its checkout URL, takes an expiry of now and
  `resolution=expired_language_change`. That is the state of a session that
  expired by itself, so the slot gives a new order the next time and the
  funnel count of started checkouts does not change.
- A paid webhook for such an order (a payment that raced the expiry) settles
  like any other: the report is delivered once, a second paid session for the
  same report is a `duplicate` for manual refund review, and each paid credit
  order puts its own credits on the account once.
- The no-charge card check (setup mode) is not covered: it charges nothing,
  keeps no order and no session id, and finishing any of its sessions records
  the same card once. Its open sessions expire by themselves at Stripe.
- Two language switches at the same moment can each expire the other's
  session; the buyer then sees Stripe's expired page and the next click opens
  a new session. Nothing is charged in that case.

`/terminos` (`/terms`) and `/privacidad` (`/privacy`) are rendered by
`audit/legal.py` from the running configuration: the price, whether card
payments (Stripe) or access codes are on, the retention window and the
upload limit. Every page links both, and the upload form links them next to
the consent box, whose text now reads the configured retention. The date of
the wording is `legal.LEGAL_UPDATED`; change it with the text.

The operator's name, contact, address and jurisdiction come only from the
variables above; no default looks like a real person or company.
The address and the jurisdiction are written in one language, so the English
and Portuguese pages can print their own wording: `AUDIT_OPERATOR_ADDRESS_EN`,
`AUDIT_OPERATOR_ADDRESS_PT`, `AUDIT_JURISDICTION_EN` and
`AUDIT_JURISDICTION_PT` (`AuditSettings.operator_address_for`,
`jurisdiction_for`). They are optional and have no default: an empty one
shows the base value, as before. They only reword a base value that is set,
so `legal_configured` in `/health` still means the four base variables, and
an override alone shows nothing. The terms, the privacy policy and "who is
behind it" on the landing are the three places that print these values;
e-mails and reports print neither (`tests/test_audit_customer_audit_fixes.py`).
`docs/AUDIT_TERMS_TEMPLATE.md` is the template the texts were written from.

**Have a lawyer in the jurisdiction where the service is sold review both
texts before charging anyone.** They are an honest description of what the
code does, not legal advice. Points to check in particular: the 7-day
refund policy (a paid report on request within 7 days, a pack's unused
credits, always a duplicate charge or one that delivered no report; a
misread report gets a fix or a new credit; statutory rights are not
limited), the 30-day answer to privacy requests, the liability cap,
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
fund a trader to the provider-account guide.

The free luck calculator (`/calculadora`, `/calculator`, `/pt/calculadora`,
`audit/calculator.py`) needs no account and no file: the visitor types an
annual Sharpe, the years it covers and the configurations tried, and the page
runs the report's luck section (`luck.luck_review`) on those numbers, assuming
daily returns (252 a year), no skew and normal tails. The inputs are labelled
Declared and the outputs carry no Measured badge; nothing is stored. It is in
the sitemap and every footer, and ends with a link to the upload form. On phones, each row of an
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
public verification page and a fix or a new credit when the report misreads the file.

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
`#canjear` (the JSON `location` too, which the in-place upload form follows), so
the page comes back at the field instead of at a banner at the top.
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

Redesign pass 56 opens the PDF on a one-page summary (`_pdf_cover` in `report.py`, print only, hidden on screen): the class in an SVG ring, the verdict's first sentence, each dimension with its badge, the first four key figures (when the platform's drawdown with open trades shows, it takes the resampled p95's place, not the Sharpe's: `_cover_kpis`, so the sample's cover keeps the 1.79 Sharpe the landing quotes) and up to three "what to do now" steps, then the evidence legend. It reuses the report's own labels and figures; nothing on it is new. A page notice (the sample's "synthetic data") repeats on the cover so the first page never passes for a real account, and a locked preview gets no cover. The class ring in the verdict also gets an SVG copy for print (`ring_svg` in `theme.py`), since WeasyPrint draws no conic gradient.

Redesign pass 58 styles "Mis estrategias". On the account page each strategy is a card with its latest class, name and version count; on a phone the count goes under the name and "Ver estrategia" spans the card. On a strategy's page the version table uses tabular figures, its "Quitar de la estrategia" buttons sit quietly at the right, and on a phone each version becomes a card with every figure under its column name (`data-label`). In "Qué cambió" each line ends in a chip coloured by its meaning only: green for "mejor", red for "peor", grey for "cambió", "igual" or "sin cambio claro". The wording and the rules behind each word are unchanged.

Pass 56 also gives each shared link its own preview card (`tools/make_og_images.py`, `OG_KINDS` in `seo.py`, 1200x630, about 25 KB each, served from `/static/`). A published verification page (`/v/...`) of a backtest shows the card for its class: the class ring, its fixed sentence and the fixed notice, nothing from the file. An account history or a fund's track record draws its own card instead, or the site card without a renderer (see `/v/{public_id}/card.png` above), because the class cards say "backtest". The sample shows a class C card marked as synthetic data, and each audience page shows its own title. The cards are static files in the package, so a preview makes no outside call and nothing about a client's report is ever drawn on one. Unknown kinds fall back to the site card.

Pass 56 also turns the prop-firm simulator table (`table.timing.firms`) into one card per challenge on a phone, each figure labelled: its four columns were 436 px wide on a 390 px screen and made the report pan sideways.

Brief 11 (2026-10-08) prepares Portuguese class A–D and sample preview markup in
`tools/make_og_images.py`, reusing `class_text` (whose Portuguese source is
`report_pt.py`), `BADGE_NOTICE`, `SAMPLE_BANNER` and the existing Portuguese UI labels.
The generator uses Playwright's installed Chromium instead of a Linux-specific path,
and imports it only when rendering. Offline tests validate the complete fixed copy
with the claim guard. The Windows environment has the bundled Inter/JetBrains Mono
fonts and Pillow, but no Playwright installation or Chromium cache; no browser or
download was started and no partial PNGs were added. `OG_PARTIAL_KINDS` therefore
continues to serve the English class/sample assets. Portuguese publication URLs
remain `/v/{public_id}?lang=pt`, with the publication-gated PNG URL
`/v/{public_id}/card.png?lang=pt`; the repository has no `/pt/v/...` route.

To finish rendering on a machine prepared with Pillow, Playwright and its Chromium
(`python -m pip install pillow playwright`, then `python -m playwright install chromium`),
set `PYTHONPATH=src` and run from the repository root:

```text
python tools/make_og_images.py outputs/og-pt --locale pt --kind class-A class-B class-C class-D sample
```

Review all five 1200×630 images for complete class sentences, fixed notices and
unclipped text, then copy the five PNGs into `src/quant_trade/audit/static/`.
Only after this review remove `pt` from `OG_PARTIAL_KINDS`, update the fallback
expectations in `test_audit_theme.py` and `test_audit_guides_seo.py` (including its
image count), and run those tests plus `test_audit_og_generator.py` and
`test_audit_verification_card.py`. They check sample/publication image URLs,
static HTTP 200 responses, PNG size and publication access rules. The generator
renders the entire selected batch before writing any image to the destination.

Redesign pass 57 styles the column-mapping page ("Dinos qué es cada columna"): each group of menus is a white card, the menus stack in one column on a phone so column names are not cut short, the file re-pick sits in a dashed box, and every file input's button matches the site's buttons. Cell rendering and escaping are unchanged. It also gives the account's "what we keep and how to delete it" card a shield and a green edge on /registro and /cuenta, makes the landing's secondary link monochrome, lets the price cards use the full width, stacks the sign-up buttons above the upload form on a phone, keeps the landing mock-up's address on one line, and tightens the timing tables below 380 px so they fit the screen. On the landing's "Trabajo real, no humo" section, each card's proof link sits at the card's foot with an arrow, so the six links line up. The one-year p95 drawdown tile now carries the same minus sign as the maximum drawdown beside it, in the report and on the PDF cover; the resampled-risk section still lists the depths as positive sizes of a fall. Portuguese gets its own site card (`og-pt.png`) and six audience cards (`og-for-*-pt.png`, first sales' texts); its verification and sample links keep the English card until there is a Portuguese class sentence and notice (`OG_PARTIAL_KINDS`).

Redesign pass 59 checks "¿Le gana a comprar y mantener el mercado?" on a phone and in the PDF. On a phone its row names ("Sharpe en los mismos 599 días…") now wrap instead of pushing both figure columns off the screen, and both worst falls show in red as in the crises table. The PDF already read well and is unchanged.

Redesign pass 60 keeps the sign-up and sign-in form in view on a desktop while the reader goes down "Qué guardamos y cómo borrarlo" beside it (sticky under the menu), and on a phone the "Crear cuenta" and "Entrar" buttons span the card.

Redesign pass 61 checks the Portuguese report (/pt/exemplo and its PDF) on a phone and on paper: both read well, and the cover still fits one page. On the way it found that on a 390 px phone (most iPhones) the last column of the day and hour tables ("Aciertos") was cut off in Spanish, and at 360 px in every language. Up to 420 px the timing tables now use tighter cell padding, unspaced headers and a slightly smaller type, and at 380 px or less a smaller one again, so every column fits.

Redesign pass 62 styles two new account pieces. The strategy summary PDF ("Descargar resumen en PDF") had a tiny title, a stray grey line left from the screen's glow and class letters off-centre, and ran two lines onto a second page; its title is now a clear heading, the line is gone, the letters sit in their circles and the summary fits one page. In "Invita a un colega" the personal link reads as a code in a quiet field, and on a phone the WhatsApp button spans the width and the third tile takes a full row.

Redesign pass 63 styles the report's new statistics blocks. The 95 % ranges ("¿Cuánto de esto podría ser azar?") showed each range at headline size, split over two lines; they now read on one line per card, smaller than the headline figures, with room before the trade table. The reading under the calm/turbulent market split, under the shuffled worst fall and under the ranges (break-even and wholly-below lines) is a ruled line that stands apart from the grey notes. The 2 % + 20 % row of the fund fee table is set off from the flat-rate rows. In the PDF, grey notes were set larger than the body text; they are now slightly smaller, which also saves a page.

Redesign pass 64 styles the currency section ("¿Cuánto valió la cuenta en tu moneda y después de la inflación?"). The account's own dollar row is shaded as the reference, and a rule separates the two dollar rows from the other currencies. On a phone, currency names had wrapped to four lines; they now keep a wider first column, as do the rows of the calm/turbulent market table. In the PDF the table is set smaller, so the section fits one page.

Redesign pass 65 comes from reading a full report on a 360 px phone as an outside customer would. Charts and wide tables that scroll sideways looked cut off with no sign there was more; they now fade at the right edge until scrolled to the end (only elements that actually scroll, and only in browsers with scroll-driven animations; others look as before). In the evidence rows (trade statistics, benchmark, declared values) the tag sat between the name and the value and squeezed names onto three lines; the value now sits beside the name and the tag goes underneath. Prop-firm cards now read the challenge name as the card's title, with the number of phases below it. The same pass styles the two-step pages: on /cuenta/dos-pasos the note's shield icon had no size and filled the screen; it is now icon-sized beside the note, the QR code sits on a white card, the six-digit code field reads as a code (monospaced, spaced, centred) on both that page and /entrar/codigo, and "¿Perdiste el teléfono?" opens from a card.

Redesign pass 66 styles the landing's feature cards after the three new ones (against cash, calm and agitated markets, your currency and inflation). With seven cards the two-column grid left an empty slot beside the last one; an odd last card now spans the row. On a phone each card puts its icon beside its title, so the list of seven reads much shorter.

Redesign pass 67 styles "Sesiones abiertas" in Mi cuenta. On a phone the five-column table scrolled sideways; each browser is now a card with its name as the title, network, last use and sign-in time as labelled lines, and a full-width "Cerrar" button; this browser's card is outlined. The card also gets the same space above it as the others. The same pass fixes two phone overflows in Mi cuenta seen in Portuguese: the account column no longer grows past the screen, and long dark buttons ("Criar minha chave de recuperação") wrap inside their card. "Actividad reciente" gets the same treatment: on a phone each event reads as what happened (in bold), then when, then the device and network, instead of a four-column table that scrolled sideways.

Redesign pass 68 styles the fund block "¿Cuánto es efectivo, cuánto es mercado y cuánto queda?". The yearly figures sit right-aligned, the fund's average return is a shaded total row set off by a rule, and the alpha's range and reading is a ruled line like the other readings. In the PDF the table and its introduction stay on one page instead of leaving the total row alone on the next. On a 360 px phone the fee table's "2 % + 20 %" label ran the page 15 px wide; it now wraps.

Redesign pass 69 is a phone walk of the longer report (Lo's Sharpe with the dependence line, Jensen's alpha on the account's rate, the fund split), the landing's new "¿Qué tan protegida está mi cuenta?" answer and the fund page's checks at 360 and 390 px. Nothing ran past the screen and no heading was stranded at a PDF page end. The tallest part was the evidence tables (trade statistics, significance, benchmark), where each row was its own card; on a phone each table is now one card with rules between rows, so the same figures take less scrolling and read as a list. Rendered with public data on (FRED), the crisis table gains an index column and ran 27 px past a 360 px screen; on a phone each crisis is now a card with its name, dates and labelled figures. The local-cash Sharpe line under the summary tiles gets a little space above it, and the landing's "Frente al efectivo" card fits at 360 and 390 px in all three languages. With each currency's own inflation (EUR, GBP, CAD, CHF, BRL), the currency table's figures keep a visible gap on narrow phones; the /metodologia list of public data sources uses the page's existing check list and fits at 360 px.

Redesign pass 70 walks the fund-record report after its fund-only sections landed, at 360 and 390 px in ES, EN and PT. The paired figure cards (the fund's own figures, its figures against the index, and a trading report's "Cómo se vivió este historial") were one tall card per figure on a phone; they now sit two per row, with the evidence label under each figure, so the same block takes about half the scroll. Screen only; the PDF keeps its two-per-row print layout.

Redesign pass 71 checks the new «¿Cambió su rentabilidad media en algún momento?» section at 360 and 390 px in ES, EN and PT, with and without a change found, and in the PDF. Its two figures use the paired cards from pass 70; the source line under them gets the same space above it as the line under the summary tiles.

Redesign pass 72 walks the fund report with its new verdict against the file's own index, at 360 and 390 px in ES, EN and PT and in the PDF. The screen needed nothing. In the PDF, the bootstrap table's header row sat alone at the foot of a page and the multiplicity section's opening line was split from its table; a table's first row and a section's opening line now stay with what follows, and the page count is unchanged.

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
client gets `{"error", "code", "columns", "category", "format",
"guidance_html", "problem", "fields_html"}`, where `fields_html` is only the
menus (`mapping.mapping_fields`, no form and no file field). With JavaScript
the upload form (`data-inplace`) posts with `fetch` (CSP `connect-src 'self'`)
and shows those menus and the refusal on the same page, so the second post
sends the file already chosen; a 401/402, a network error or an unreadable
answer falls back to the ordinary post. Without JavaScript nothing changes.
With `AUDIT_CONTACT_URL` set, the menus end with a line that offers to read
the file with the customer. An HTML report or anything else
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
- The significance section carries `dependence` (50 returns or more and a
  positive Sharpe): the probability that the true Sharpe is above zero and
  the returns needed for it to reach 0.95 with Mertens' variance of the
  Sharpe (the one the plain PSR uses) multiplied by `ratio`, the largest of
  1, the Newey-West long-run variance of each return's influence on the
  Sharpe (`z - SR / 2 (z^2 - 1)`, Bartlett weights, lag `floor(4
  (n/100)^(2/9))`) over its plain variance, and `(1 + rho) / (1 - rho)` for
  the returns' Kendall-corrected first-order autocorrelation clipped to
  `[0, 0.9]`. It never reads higher than the plain figure. On simulated
  returns with no edge and autocorrelation 0.4 the plain PSR passes 0.95
  about 12 % of the time and this one about 5 %; with independent returns
  both about 5 %. Informational: the class uses the plain PSR.
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
  When a report names an account currency with its own cash rate (the
  currencies of the cash-rate Sharpe) and that rate covers every period too,
  the strategy loses what cash in that currency paid instead (read by the
  same quote, staleness and euro history as the cash-rate Sharpe) and the
  benchmark, taken as priced in US dollars (the note and the line say so; a
  local index uploaded as the benchmark is not detected), the bill's: each side over its own
  currency's cash. `cash_currency` then names the currency and the line names
  both rates. Otherwise a dollar account's bill on both sides stays, and an
  account in another named currency has nothing subtracted (the line says
  so), never the bill. With
  the bill on both sides, a simulated account in reais holding Brazilian cash
  at 12 % and 0.2 of the index, with the bill at 5 %, showed about 7 % a year
  of alpha that was only Brazil's cash premium over the bill.
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
  (Treynor and Mazuy, 1966): a significant term reads as convexity, which
  timing or option-like positions give (selling options gives a negative
  one), never as timing alone. Standard errors are the largest of HC3,
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
  The report (ES, EN, PT) shows it in the fund-versus-index block as "How
  much is cash, how much is the market and what is left?": the three parts
  and the total in a table, the exposure share or why there is none, the
  alpha with its 95 % range, t and the usual reading of |t| against 2, and
  the months needed with "arithmetic, not a promise" (past 600 months it
  says even 50 years would not be enough). The lagged line shows only when
  the lag's t is 2 or more and the lagged beta is higher; the timing line
  only when |t| is 2 or more. With the split measured, it replaces the plain
  Jensen line there, since its alpha is after cash.
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
- Under Lo's line, the `dependence` probability and track record next to the
  plain ones when `ratio` is 1.1 or more (with one more sentence when the
  plain probability reaches 95 % and this one does not; a track record over
  ten times the history's length is not printed, only that ten times would
  not reach 95 %, and one within it says the history already reaches it),
  or one line saying
  dependence does not change it. The statistical dimension now uses the lower
  of the plain and dependence-adjusted PSR when the latter is measurable;
  the DSR floor and effective observation count are widened by the same
  dependence ratio. This rule is versioned in `engine.verdict_policy_version`.
- Under the benchmark table and in the fund-versus-index block, Jensen's
  alpha with beta, t and the periods, saying which cash it subtracted from
  each side (the account currency's own rate is named) or that it subtracts
  no cash rate; |t| of 2 or more reads as unlikely to
  be chance alone (with "it does not say it will repeat" for a positive
  alpha), below that as not distinguishable from chance.
- The fee table's last row is "2 % + 20 % of gains".
- In the risk section, "Is the file's worst fall normal for these returns?":
  the uploaded worst fall beside the 5th to 95th percentile of the same
  returns in random order, and one sentence for `TYPICAL`, `SHALLOWER`
  (losses rarely follow losses; the file's fall may understate the risk) or
  `DEEPER` (losses came in streaks). It says it is not the one-year fall
  above. Nothing shows when it is `NOT_MEASURED`.

## Monetary integrity and selection inputs (2026-09-27)

`reconciliation` records the equation in the report's account currency or
states that currency was not supplied: opening capital + post-opening cash
flows + gross closed-trade P&L − itemised costs = expected closing capital.
It prints the reported closing balance or independent uploaded curve's last
value, difference, and tolerance. Tolerance is the larger of 0.02 units,
0.011 units per closed trade plus one, and one basis point of the larger of
opening or expected capital. The equation does **not** prove the source was
authentic. Its `coverage` states whether a curve was rebuilt or uploaded,
how many trades were covered, and whether cash flows, currency and open
positions were supplied. A platform withdrawal after the last closed deal is
excluded from this observation window, matching the return curve. For a
separate CSV curve, its currency is shown as unknown even when the trade file
states USD; same units are an assumption, not verified conversion. Trades
outside the curve or an uncovered last 1 %
of its time span make the comparison `NOT_MEASURED`.
A platform file that prints no running balance of its own (Myfxbook, MQL5, FX
Blue, TradingView and other trade lists) has nothing independent to compare:
its curve is an index adjusted for deposits and withdrawals, rebuilt from the
same rows as the expected balance, so the equation is `NOT_MEASURED` ("No
printed balance to reconcile against"), with the observed balance and the
difference not measured and no red flag. MT4/MT5 files with a printed balance
(on each row, or in the MT4 statement's summary) keep the comparison.

The importer counts a printed Balance cell as a break only when it differs
from the previous balance plus the row's money by more than printing rounding:
the larger of 0.011 units (a cent plus float slack) and one part per million of
the printed balance (`importers.balance_rounding`). Within that rounding the
chain restarts from the printed cell, so sub-cent rounding of row amounts
(0.33 over thousands of MT4 tester rows) cannot add up to false breaks; an
edited cell is outside it, is counted once and is never adopted.

A platform Balance cell which differs materially from the deal-money chain
produces `MONETARY_RECONCILIATION_MISMATCH` (`FAIL` for data quality), and
the return uses the reconstructed deal amounts. When the importer reports a
position still open at the end, or a close whose money is in the balance but
not in the trade list, a gap against closed trades is `NOT_MEASURED` only if
the printed balance still agrees with the complete row-money chain; a broken
Balance cell remains a contradiction, so an open position cannot hide it. For an independently uploaded
curve, an unexplained difference leaves the equation `NOT_MEASURED` with the
reason shown, and raises **no** red flag and no data-quality penalty:
unreported deposits, floating P&L in the curve, conversion or a scaled index
could explain it, and genuine files with separate equity curves show the same
gap (7 of 40 in a real-file gate). `MONETARY_RECONCILIATION_UNEXPLAINED` is
no longer raised; its title and advice stay only so stored reports still
render. `MONETARY_RECONCILIATION_MISMATCH` (`FAIL`) remains the only
monetary-reconciliation flag, and it does not claim fraud. The calibrated forensic battery
is also run over the original platform bytes; a `BALANCE_CHAIN SIGNAL` adds
`FORENSIC_BALANCE_CHAIN_SIGNAL` (`WARN`) with method version and calibration,
without treating a heuristic as proof of alteration. The MT5 tester report
is altered in memory, with the committed clean fixture as its control.
An MT5 partial close can leave some entry commission with the open remainder;
the importer checks residual deal volume as well as unmatched rows before
classifying the closed-trade gap. A clean deal-money chain leaves that gap
`NOT_MEASURED`, while an independently altered Balance remains a
`CONTRADICTION`.
A 519-trade curve scaled only in its variation is covered in
`tests/test_audit_monetary_integrity.py` and through the persisted web report
in `tests/test_audit_money_web.py`.

The generic trades CSV accepts commission/fee as charges with either sign,
and a signed swap (positive credits the account). Its zero-extra-cost row
already includes these amounts; a declared `net_pnl` is compared with net,
`gross_pnl` with gross, and an ambiguous `pnl` with both while warning the
reader. Mixed currencies or unreadable costs are refused; other monetary
looking columns receive an explicit unused-column warning. No conversion
rate is invented. This is tested against a +1 gross, −9 net example.

Variant dates, when present, must parse, be unique, chronological, and match
the audited curve or its return rows before CSCV/PBO. A date-less matrix is
still accepted by row position but is labelled `NOT_MEASURED` for temporal
alignment and selected-variant provenance. A declared OOS start remains
`selection_verified=false`; the upload cannot prove it was chosen in advance.
Forensic report cells say they are calibrated for the file family only when
the corpus gate granted that calibration. The corpus runner exits unsuccessfully
for missing, malformed or empty expected fixtures rather than treating an
incomplete denominator as a passing calibration.
`run_audit` accepts an optional 40-hex `source_commit_sha` from its caller;
the web layer uses Railway's `RAILWAY_GIT_COMMIT_SHA` when a GitHub-triggered
deployment supplies it. The result labels it `DECLARED` rather than claiming
that a PDF hash authenticates the source code. Missing or malformed values
remain `NOT_MEASURED`; the local synthetic sample intentionally has no build
commit SHA.

## Operator probes and incident admission

`GET /live` checks only that the web process can answer. The legacy `GET
/health` exposes non-secret configuration and also remains a liveness probe;
it does **not** query storage. Route new traffic using `GET /ready`: it runs
`SELECT 1 FROM audits LIMIT 1` on the configured database and checks that WeasyPrint loaded with
its native PDF libraries. It returns 503 with only boolean check results when
either fails, never a connection string or error text. A deliberate incident
pause appears in the readiness JSON but does not make existing report and
webhook traffic unready.
When `AUDIT_EMAIL_VERIFICATION_REQUIRED=true`, readiness also checks that
HTTPS, the token secret, and encrypted SMTP delivery are configured. This is
a configuration check; it does not send a message or prove SMTP reachability.
Railway's `healthcheckPath` is `/ready`; the Docker build workflow probes
both `/live` and `/ready`. The Docker image installs Pango and HarfBuzz for
WeasyPrint, so a PDF dependency failure prevents a new deployment from being
marked ready.
Unsigned requests to the Stripe webhook are limited to 256 KiB before body
parsing; an oversized request returns 413.
On Windows, the local Python library also needs native Pango. Follow the
[WeasyPrint Windows installation guide](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation):
install the MSYS2 UCRT64 `mingw-w64-ucrt-x86_64-pango` package and set
`WEASYPRINT_DLL_DIRECTORIES` to that installation's `ucrt64\bin` before
starting the service or running PDF tests; `pip install weasyprint` alone is
not sufficient there.

Set `AUDIT_PAUSE_NEW_AUDITS=true` on **every** service replica and restart to
stop `POST /audits` before multipart parsing. This stops free audits and also
temporarily stops paid-credit/code uploads; existing reports and balances
remain available and a rejected upload consumes no free claim or credit. Set
`AUDIT_PAUSE_NEW_CHECKOUT=true` and restart to stop new card Checkout
sessions. Already created Checkout sessions, signed webhooks, paid-report
access, and payment reconciliation continue. Restore either flag to `false`
only after the incident is resolved. The values are read at process start,
so editing an environment variable without restarting has no effect.

At most `16 × AUDIT_MAX_CONCURRENT_AUDITS` audit request bodies can be in
multipart parsing or later audit processing per process. Additional requests
get a 503 before their bodies are read. An admitted body must arrive within
120 seconds, or the upload is cut off with a 408 and its admission slot is
freed, so a few slow or stalled clients cannot make every other upload busy.
An admitted body is still bounded by the existing total request limit and by
each field's size limit. The audit computation itself still runs at most
`AUDIT_MAX_CONCURRENT_AUDITS` at a time; a parsed upload waits up to
`AUDIT_QUEUE_SECONDS` for a slot before it is told the service is busy. This
is an admission guard, not a durable job queue; an upload rejected with 503 must be
sent again. Limits and attempt counters are per process, so adding replicas
requires shared admission and quota design before claiming greater capacity.
The controls and DB/PDF failure probes are exercised in
`tests/test_audit_ops.py`. That test also backs up and restores a synthetic
SQLite database and compares the account count, usable credits, frozen paid
order and report bytes. A PostgreSQL staging restore and a recovery drill
under live traffic still need their own environment and evidence. No
production load capacity follows from these functional tests.
Never replace a production database with an older snapshot without first
listing and reconciling card sessions and webhook deliveries that happened
after the snapshot; a database rollback alone can discard paid entitlements.

## Customer audit of the public texts (2026-09-28)

Wording, labels and links only; no figure, threshold, class or detection
changed. Tests: `tests/test_audit_customer_copy.py`.

- A report links the check page, the terms and the privacy policy of its own
  language (`seo.CHECK_PATH`, `legal.LEGAL_PATHS`), also in Portuguese.
- The Portuguese site says the report and its PDF come in Portuguese,
  Spanish or English.
- Spanish is Latin American Spanish: no "vosotros" form, "computadora",
  "videos", "tasas"; `og:locale` is `es_MX`. "costos" stays as it is.
- The platform table names four more fields in the three languages
  (`balance_chain_breaks`, `largest_balance_difference`,
  `reconstructed_final_balance`, `reported_final_balance`).
  `report.platform_value` shows the three amounts with 2 decimals and the
  count as an integer. The stored result keeps the importer's text.
- Brazil's inflation series (SGS 433) links its SGS page; the open-data
  portal has no page for it. The Selic link (SGS 4189) is unchanged.
- The landing writes decimals with a point, as the report does.
- The forgot-password pages show the operator's address
  (`AUDIT_OPERATOR_CONTACT`) before the chat link while automatic mail is
  off. No new variable.
- The sources of the methodology join their authors with "y", "and" or "e"
  by language (`method.references`).
- The sample PDF's title ends in "ejemplo" or "exemplo", as its page does.
- The stress count agrees in number when one scenario breaks
  (`stress_count_one`).
- The terms describe password recovery as the site does it.

## Customer audit: report wording, upload guidance and refusals (2026-09-29)

Words, page chrome and which fixed sentence is chosen; no figure, threshold,
class, evidence tag or reader changed. Tests: `tests/test_audit_report_polish.py`.

- **Trials not declared.** When the deflated Sharpe was computed at 1 trial
  and nobody declared a count (`verdict.trials_undeclared`: `trials_used`
  `NOT_MEASURED` with `dsr_at_trials_used` `MEASURED`), "what it means for
  you" and the plan say that the class cannot go above B because the number
  of configurations tried was not declared, and that declaring it (even 1)
  lets Rigor discount it (`MEANING["multiplicity.NOT_MEASURED.undeclared"]`,
  its `.fund` twin, `multiplicity.FAIL.undeclared` for the fund with one
  undeclared trial; `plan._multiplicity_step`). The public verification page
  uses the same sentence, before and after the purge: the kept public view
  stores the fact per dimension (`undeclared`, a boolean derived from the
  two evidence tags, `store.public_view`), never the inputs; a view kept
  before this change has no such fact and shows the general sentence. The
  old sentence ("significance was not measured") stays for the case it
  describes. The cap at B is unchanged.
- **Money reconciliation.** `RECON_REASONS` knows "closed trades do not cover
  the final part of the curve" in the three languages; a reason with no fixed
  sentence still goes through `localize`. The heading and the reason are two
  sentences ("No se pudo cerrar la conciliación. Las operaciones cerradas…").
- **Comparing from a Portuguese report** posts to `/pt/comparar` with the
  Portuguese label and button (`compare.COMPARE_PATH`, `compare.COPY`); the
  three comparison routes keep `lang=pt` Portuguese whatever the address.
- **All checks and their status** names each check for the reader in the
  page language (`forensics.copy.CHECK_NAMES`, else the red-flag title, else
  the key as words) with the key beside it in `<code>`.
- **Column page.** A fixed note, always shown, says that a fund's monthly
  table (a year per row, a month per column) goes in the curve box, with a
  link back to the upload page (`mapping.COPY["monthly"]`). Detection is
  unchanged. A table with fewer than two rows under its header is told so on
  that page (`mapping.COPY["one_row"]`) instead of being asked for columns
  first; the page and its status are the same.
- **Refusals that say what to fix.** A file that arrived with 0 bytes in the
  report or curve box is called empty (`MESSAGES["empty_upload"]`), not
  missing; "Falta el archivo" stays for no file at all. A picture in the
  curve box (PNG, JPEG, GIF or TIFF, `web.PICTURE_SIGNATURES`) is called a
  picture, not a table without a date column
  (`MESSAGES["curve_is_picture"]`). A PDF is not a picture here: a PDF
  statement's table still reaches the column screen as before. Both
  refusals keep 400; nothing new is accepted and nothing is refused that
  was not.
- **Limits.** The curve reader stops at 5 MB (`schema.MAX_UPLOAD_BYTES`)
  while the field accepts 10 MB so that a platform report dropped there is
  read as the report. Both refusals of a curve over 5 MB now say "5 MB, the
  most we accept for a curve" (`MESSAGES["curve_too_large"]`, 413 from the
  field, 400 from the reader); an over-10 MB file in the curve box whose
  name or first bytes are a platform report (`looks_like_platform_report`
  on `UploadTooLarge.filename` and `.head`) is told the report's 10 MB
  instead. Every box on the upload page states its limit: 5 MB for the
  curve, trades, benchmark and variants; 10 MB for the report, the live
  statement and the optimisation XML.
- **Own files.** The curve and trades boxes carry one line: dates as
  year-month-day (2026-03-31) and a decimal point read best; a file in
  day/month/year should say so in the description (`dates_hint`).
- **Challenge list.** The options are built for the page's own language
  (`_preset_options(locale)`), so the Portuguese page shows "fase 1" and the
  generic preset in Portuguese; the default option is unchanged.
- **Small wording.** "1 configuración probada" (singular in the three
  languages, `LABELS["passes_one"]`); the provider-account guide is named in
  one language at a time (`platform_en`); the Portuguese report uses
  "passagem/passagens" for an optimisation pass everywhere, as MetaTrader 5
  does; the badge code made from an English or Portuguese page links
  `/v/<id>?lang=<language>`.
- **Same file again.** A preview of a file the same account already
  audited shows a note with a link to the report it already has
  (`Store.earlier_audit_of_same_files`: same set of SHA-256 digests, an
  earlier upload linked to the same account, not purged, a full report
  first; the SQL prefilter uses the curve's digest, or the platform
  report's digest in `audit_files` when the upload has no curve of its
  own). Nothing changes in what is spent: the upload is a preview as
  before. The note appears only to the signed-in owner of both reports.

### Private operations and observed commercial costs (2026-10-05)

The owner panel adds 30-day upload/audit/queue/PDF counters and approximate
latency histograms, persistent retention attempt/success health (overdue after
36 hours), observed USD cost totals and a first-touch X acquisition cohort over
14 days. These are additive tables; public health and payment/rights contracts
remain unchanged. Customer requests buffer aggregate telemetry without SQL
writes, and failed telemetry cannot block delivery. Costs and contribution are
`DECLARED`; absent categories/windows remain `NOT_MEASURED`. See
[RIGOR_COMMERCIAL_OBSERVABILITY.md](RIGOR_COMMERCIAL_OBSERVABILITY.md) for exact
measurement definitions, privacy, staged rollout and additive rollback, and
[LOCAL_POSTGRES_QA.md](LOCAL_POSTGRES_QA.md) for isolated PostgreSQL evidence.
The public CTA now explains email confirmation in ES/EN/PT when that gate is
enabled. No audit dimension, red flag, threshold or verdict changes.

### Optional column preferences and report delivery (2026-10-06)

After creating an audit, remembering the customer's column mapping is optional.
A failure in that preference step no longer prevents the report's redirect or
JSON response, token delivery and account linkage after a code was redeemed.
The operator receives a fixed warning without exception text, SQL parameters or
customer data. Successful preferences remain reusable; parsing and audit-storage
failures keep their existing refusals. Credit rules, prices and permissions are
unchanged. Offline regression tests: `tests/test_audit_column_map_resilience.py`.
Reading a saved preference is optional too: if its lookup fails, the customer
can still name the columns in HTML or JSON, in ES/EN/PT, without spending a
credit or a free preview. An explicit selection then follows the existing audit
and payment path. The lookup warning also excludes exception text and SQL data.

### Owner panel and startup hardening (2026-10-07)

Private-panel and startup fixes only; no customer page, price, right, audit
dimension, red flag or verdict changes. The panel reads operations/retention
and costs as two independent blocks, so a failed cost query no longer hides the
36-hour retention warning. Retention with no success ever is overdue after the
process has run 36 hours; naive stored times read as UTC and unreadable ones as
no success. PostgreSQL startup creates tables under an advisory lock, and the
telemetry engine sets its timeouts per transaction instead of overriding the
URL's `options`. See
[RIGOR_COMMERCIAL_OBSERVABILITY.md](RIGOR_COMMERCIAL_OBSERVABILITY.md).

### Sharing, public examples and the completed-audit count (2026-10-07)

- **Active publications.** The public verification and its owner's published
  report offer localized suggested text, clipboard copying with a selection
  fallback, an X intent and the existing SVG card preview. `sharing.py` accepts
  only the class, public id and locale; it never receives a private report URL,
  token or client text. Shared links use `https://rigorscore.com/v/<id>?ref=share`
  (and `lang=en`/`lang=pt` as appropriate). A private or withdrawn report has no
  share block. Published views kept by the existing purge remain shareable.
  The retained view also keeps only `fund.track_record` as a boolean, so a
  fund's sharing text keeps its report kind after purge, without retaining
  fund figures. Previously purged views without that flag cannot recover it
  from deleted data and retain the existing fallback classification.
- **Attribution.** `share` and `ejemplos` are named tags in `funnel.REF_TAGS`
  (`vendedor` too: the link in the buyer's message for the seller).
  Adding these bare names requires this deploy: there is no runtime setting
  for arbitrary tags. Existing campaign-shaped names, such as `x-es-103`,
  already work without another deploy. Active `/v/<id>` HTML and the examples
  pages count like the calculator: people only, once per browser/day, first
  tag kept for 30 days; bots, prefetches and card/badge requests do not add
  visits. Public HTML uses `no-store` so caches cannot bypass attribution;
  images keep their existing short cache unless a response sets a cookie.
- **Public examples.** `/ejemplos`, `/en/examples` and `/pt/exemplos` are in the
  footer and multilingual sitemap. `examples.py` imports the SVG renderer and
  calculator arithmetic. No source is fetched and no audit class is assigned.
  All inputs and arithmetic derived from them remain `DECLARED`; unavailable
  evidence is `NOT_MEASURED`. Nine weeks is explicitly approximated as `9/52`
  years, and the calculator accepts fractional years. Three weeks of strategy
  development is not treated as backtest history. The first case has no
  declared Sharpe/history/trial count, so its calculator link does not invent
  those inputs. All calculator links carry `ref=ejemplos`.
- **Free tools page.** `/herramientas`, `/en/tools` and `/pt/ferramentas`
  (`tools_hub.py`, rendered by `pages.tools_page`) gather the tools that need
  no file: the luck calculator, the win-rate calculator, the figure reader and
  the report check (`tools_hub.TOOL_KEYS`). Each
  block says what the visitor enters and what comes back, without an account,
  and the page shows no figure of its own; a last block points to the upload
  form, the sample report and the articles. The page is in `PUBLIC_PAGES`
  (153 sitemap URLs with the win-rate calculator) with its canonical, `hreflang` alternates and a JSON-LD
  `ItemList` of free `WebApplication` entries (`seo.tools_structured_data`,
  price 0). The menu links it where it used to link the comparison; `/comparar`
  keeps its `noindex`, stays out of the sitemap and is still linked from the
  footer, from "My account" and from the reports. The footer also links the
  tools page and the articles. The landing shows the four tools under the
  cases (`_tools_band`, a 2 by 2 grid; the win-rate card uses the `percent`
  icon). The reader links the calculator, the win-rate article
  and the tools page, and ends, with or without a card, with what only the file
  can measure. The calculator links the deflated-Sharpe article and the reader;
  the examples link the reader; the prop-firm case and its article link each
  other, and the prop-firm, robot-buyer and signal-copier cases list their
  articles (`pages.AUDIENCE_ARTICLES`). Guessed addresses (`/tools`,
  `/pt/tools`, `/en/calculator`, `/reading`, `/en/methodology`, `/en/articles`,
  `/en/guides`, `/en/sample`, `/en/check`, `/faq`, `/examples`) answer 301 to
  the page they meant; each one gave a 404 before, and no address that already
  answered 200 changed. Offline regressions: `test_audit_tools_hub.py` and
  `test_audit_theme.py::test_navigation_has_a_phone_menu_and_links_the_free_tools`.
- **Conservative measured count.** Only completed customer uploads explicitly
  marked in the additive `audit_count_eligibility` table contribute. The engine
  and renderer must finish before that mark is written, in the audit insert's
  transaction. Samples, fixtures, incomplete records and configured operator
  test ids (`AUDIT_STRIPE_TEST_AUDITS`, read only) are excluded. Historical rows
  have no reliable test/customer provenance and are deliberately not backfilled.
  Manual test uploads through the public form must be identified in that
  existing exclusion list or run against an isolated test database; the site
  cannot infer that intent from a file. This is a conservative subset of the
  stored completions, not a historical lifetime total. Existing purged
  completions can count; deletion also removes the new eligibility metadata.
  No retention or account policy changes. One aggregate query is cached per
  application instance for 600 seconds, including failures. Failed reads hide
  the count. Below 25 nothing is rendered; at 25 or more the count carries
  `MEASURED`, displayed using the site's existing localized evidence labels.

Offline regressions: `test_audit_sharing.py`, `test_audit_share_funnel.py`,
`test_audit_examples.py`, `test_audit_completed_count.py`, plus the existing
public-page, card, calculator, funnel, SEO and report tests. On the Windows
laptop exclude `test_audit_pdf.py`, `test_audit_pdf_origin_label.py` and
`test_audit_pdf_statements.py`: native WeasyPrint dependencies are unavailable.

### Institutional period returns and private card form (2026-10-07)

CSV and XLSX uploads accept a dated `return` column, or `gross_return` and/or
`net_return`. Example with six **synthetic** monthly observations in fractions:

```csv
date,gross_return,net_return
2024-01-31,0.012,0.010
2024-02-29,-0.006,-0.008
2024-03-31,0.022,0.020
2024-04-30,0.004,0.002
2024-05-31,-0.013,-0.015
2024-06-30,0.017,0.015
```

- Upload through the main file or equity field; benchmark accepts the same
  shape. An explicit equity column retains the existing equity-curve path.
  The first return is included; the compounded index has an implicit unit
  opening value with **no invented opening date**. Net is used when supplied,
  otherwise `return`, otherwise gross. With both gross/net columns the report
  also presents each series and their sample-deviation annualised Sharpe.
- The form can confirm `return_frequency=daily|weekly|monthly` and
  `return_unit=fraction|percent`. Regular dates infer 252/52/12 periods per
  year respectively. Conflicting declarations are rejected. Unknown frequency
  needs a declaration. `%` markers or a percent header identify percentages;
  absent markers, median absolute values above 0.5 imply percent, otherwise
  fractions. This is a **DECLARED interpretation**, not measured provenance;
  use the form override for ambiguous small percentages or large fractions.
  Mixed marked/unmarked nonzero values are rejected. The report records unit,
  frequency, confirmation, gross/net basis and benchmark source as DECLARED.
- Calculations use every supplied return, with sample Sharpe scaled by the
  square root of 252/52/12. Luck uses that convention and period count divided
  by frequency for duration. The public calculator has the same selector,
  default 252, and accepts `periods_per_year=12` or `52` in links. Its inputs
  remain declarations, as do public-card assumptions. The existing minimum
  dated span for reporting CAGR remains conservative.
- Benchmark comparison checks frequency before an exact-date join and retains
  the existing 90% overlap threshold. Different frequencies are NOT_MEASURED;
  they are not resampled into agreement, including the fund section. Jensen
  alpha and analyses needing a period opening date or an intra-period path
  are NOT_MEASURED when only these period returns were supplied. No daily
  observations, trade counts or monetary P&L are reconstructed.
- Cost sensitivity compounds `gross - k*(gross - net)` for declared multipliers
  1, 2 and 3. The gross/net difference is a **declared cost reference**; resulting
  totals and Sharpes are MEASURED. Net above gross invalidates this interpretation;
  stress below a complete period loss is NOT_MEASURED. Without trades this does
  not satisfy the existing trade-cost audit dimension or change its thresholds.
- The existing private owner panel links to **Tarjeta pública**. The repository
  authenticates each panel POST with the owner key; it has no owner session.
  The new form preserves that mechanism, cross-site rejection and rate limits.
  It shares `PublicClaim` limits and the claims guard with the CLI, converts
  percentage hit rate to a fraction, and returns inline/downloadable SVG.
  Optional CairoSVG converts only the freshly generated SVG into PNG in memory;
  otherwise localized instructions explain external conversion. This operation
  writes neither database records nor files. No new login/session subsystem.
- The institutional landing block exists in ES/EN/PT and now links to the
  localized institutional review request described below.

Offline regression coverage: `test_audit_return_series.py`,
`test_audit_period_analysis.py`, `test_audit_frequency.py`,
`test_audit_series_ui.py`, `test_audit_series_integration.py`,
`test_audit_owner_card.py` and the related existing importer/engine/report tests.
Keep the three PDF exclusions above on the Windows laptop.

### Institutional review requests (7 October 2026)

`/revision-institucional`, `/en/institutional-review` and
`/pt/revisao-institucional` collect contact details and DECLARED strategy type,
series frequency, years of history, benchmark availability and approximate trial
count. No audit is run and no files are accepted. The home institutional block
and the funds/signal audience link here; the normal audit flow handles files later.

The repository's `inbox.py` validates email addresses; the existing contact page
publishes contact channels and has no POST form or stored inbox. Intake therefore
uses the existing SQLAlchemy `Store` and durable `mail.py` outbox, adding only an
`institutional_requests` table. The English audience retains its existing
canonical `/for/funds-and-signal-providers`, not the brief's `/en/for/...` path.

Limits: five attempts per IP per hour across languages, using the stored attempt
log (hashed IP key), 16 KiB request body, honeypot, same-origin checks, plain email
validation and the disposable/reserved-domain rules from `inbox.py`. HTML,
control characters, unknown/duplicate fields and multipart uploads are refused.
Names and organizations have 100/160-character limits; history is greater than
zero and at most 100 years with two decimal places; variants are integers from
zero to 999,999,999. These bounds protect input/storage, not an audit verdict.

Free text is at most 1,000 characters, scanned with `scan_client_text` and stored
verbatim with its findings. Claims in that text do not block intake: neither the
text nor its findings are rendered or emailed. Identity-field claims are refused.
Confirmation contains only static next steps and is noindex. No client data is
logged, exported, or written as files by this flow.

When existing mail delivery is ready and `AUDIT_OPERATOR_CONTACT` is a plain
email address, saving and enqueueing are atomic. The existing worker attempts the
notice on its next poll (ten seconds), with its existing eight-attempt/seven-day
limits and stable Message-ID. The notice contains only name, organization, email
and strategy type. No new credentials or transport are introduced. Without mail
configuration the request remains in the private panel, without a queued notice;
immediate notification depends on that configuration and transport availability.

The owner-key POST panel shows the latest 100 requests, their declared context
and contact details. Marking contacted persists its first timestamp and rejects
cross-site requests. No free text appears there. Audit retention, payments,
credits and calculation rules are unchanged; this PR adds no prospect purge
policy or new privacy promise. The one-business-day response is an operator
follow-up expectation, not an automated review or a result claim.

Offline coverage: `test_audit_institutional_intake.py`,
`test_audit_institutional_store_mail.py`, `test_audit_institutional_owner.py` and
`test_audit_professional_seo.py`, plus the existing mail/panel/public-page tests.
Windows commands use `D:\quant-trade\.venv\Scripts\python.exe`, a worktree-local
`--basetemp`, and exclude `tests/test_audit_pdf*.py` and
`tests/test_personal_paper*.py` as requested.

### Retail articles and public questions (7 October 2026)

`articles.py` adds articles about prop-firm attempt counts, MQL5/Myfxbook
signal histories and AI-generated bots in Spanish, English and Portuguese.
They retain the existing article renderer, free-report CTA, table of contents,
Article/BreadcrumbList JSON-LD, canonical and language alternates. The AI article
reuses `calculator.compute` for every cell of the search-size/history-length
table and links the existing public figure reader in each language.

The brief's proposed challenge title was changed to discuss attempts rather
than a challenge outcome. Its numerical-source restriction also conflicts with
the requested binary-win and attempt examples: neither `calculator.compute`
nor `luck.py` calculates those quantities. `retail_numbers.py` therefore holds
small deterministic editorial examples, separate from audit calculations, and
all displayed assumptions and results remain DECLARED. No audit criterion,
threshold, dimension, simulator or engine was added or changed.

The challenge example imports the generic preset, including its date and source.
It uses independent daily fixed-stake, equal-size wins/losses, static barriers,
no costs and no deadline; touching the loss barrier ends the attempt. The inverse
of the target probability is the mean count of independent identical attempts,
not a personal forecast, confidence interval, budget or full multi-phase
evaluation. The losing streak is illustrative, not an empirical typical streak.
The signal example uses a continuity-corrected normal binomial approximation;
its tail probability is not a probability of skill or a sample-size requirement.
Tests compare it with the exact binomial tail and check the barrier calculation
against a separate symmetric-barrier identity. Correlation, changing payoffs,
selection and real execution can invalidate these teaching assumptions.

`faq.py` serves eleven source-commented questions at `/preguntas`, `/en/faq` and
`/pt/perguntas`, listed in `PUBLIC_PAGES`, the sitemap and footer. Before the
contact question it also answers the landing's questions the landing does not
show (`faq.landing_only_questions`: markets, the MT5 optimisation XML, a
forgotten password, account protection, the badge and, in Portuguese, the
report's language), worded as in `pages._COPY`. Runtime settings
supply prices, public card markets, upload size, retention and contact channels.
It reuses the existing JSON-LD serializer; FAQPage answers match visible localized
answers. Privacy follows `legal.py`, including retention of the first free full
report like a paid report. This page adds no privacy promise or retention action.

Offline coverage: `test_audit_retail_articles.py`, `test_audit_retail_numbers.py`
and `test_audit_faq.py`, plus existing article, structured-data, SEO and public
reading tests. No customer files, market data, network calls, payment changes or
broker connectivity are involved.

### Public pricing (8 October 2026)

`pricing.py` serves `/precios`, `/en/pricing` and `/pt/precos`, with reciprocal
language links, canonical URLs and sitemap entries through `PUBLIC_PAGES`.
Navigation and footer prices links lead there; the landing retains `#pricing`
and adds a detail link. Both report columns describe the same six dimensions,
evidence labels, PDF, optional public page/card, comparison and contact channel.
Comparison requires two full reports and takes up to three ("Comparación de
hasta tres informes"); payment does not create missing evidence. The pack card
(`PRICING_COPY[*]['pack_text']`) says "Audita 3 robots y compáralos lado a
lado antes de comprar uno, o sigue tu cuenta 3 meses" (es/en/pt) while
`settings.PACK_CREDITS <= compare.MAX_COMPARED`; a larger pack would fall back
to `pack_text_plain`, the sentence without the comparison. Prices, credits and
the pack's content are unchanged.
The existing landing limitations text is reused without rewriting it.

Prices (including cents), discounted-pack availability and quantity come from
`AuditSettings.price_usd`, `pack_price_usd` and `settings.PACK_CREDITS`. Card
countries use `card_markets_line` only when `card_public` is true. The one-off
payment description follows the existing `mode="payment"` checkout builders;
no checkout, credit, account or e-mail behavior changes. E-mail confirmation is
mentioned when configured and support availability follows `operator_contact`.
The institutional link uses the existing intake form. The page closes with
`pricing.start_cta` ("Empieza por el informe gratis"), not with the articles'
calculator call; see "Conversion toward the first free report" below.

Paid pages serialize the visible single/pack offers as Product/Offer JSON-LD
through `seo._json_ld`, without ratings or reviews. In `free_mode` all full
reports are described as free, with the existing watermark note, and both
visible prices and structured offers are omitted. `test_audit_pricing.py`
covers the three languages and runtime settings; `test_audit_public_hygiene.py`
includes the new pages automatically. These are product descriptions, not
changes to audit criteria, thresholds or readiness decisions.

### Upload refusals and owner visibility (8 October 2026)

`upload_rejections.py` gives each rejected upload fixed Spanish, English and
Portuguese guidance: the cause, detected container, a short accepted-format
list linked to the existing export guides, and a concrete retry step. Existing
parser details remain visible. The column-choice page still returns 422;
ordinary parser/form refusals still return 400, size limits 413, rate limits
429, and admission limits 408/503. No import rule, engine calculation, audit
criterion, threshold or report dimension changed.

The categories are `format_unknown`, `image`, `pdf_no_trades`, `too_large`,
`too_few_rows`, `dates_unreadable`, `columns_missing`, `files_mismatch`, `rate_limited`,
`invalid_values`, `invalid_declaration`, `empty_file`, `invalid_upload`,
`upload_timeout` and `service_busy`. `pdf_no_trades` means the existing PDF
reader could not read a usable table; it does not assert that a corrupt,
encrypted, oversized or timed-out PDF contains no trades. Readable PDF tables
still reach column mapping. Detailed parser codes map to bounded categories;
unclassified parse failures use `invalid_upload` without logging exception text.
Unexpected parser exceptions log only their type, without a traceback. Error
codes across the audit package have an exhaustive mapping test, including
attribute calls, the factsheet helper and the return-series error dictionary.
Nonempty numeric cells discarded as unreadable use `invalid_values` with their
own message when fewer than two usable curve rows remain; empty cells,
genuinely short or duplicate-only curves retain `too_few_rows`.

`files_mismatch` groups `trades_and_report`, `trade_list_as_curve` and
`optimization_mismatch`: these are incompatible or misplaced files, not missing
columns. Guidance in all three languages explains that a platform report and a
trade list cannot be supplied together, a platform-exported list belongs in
the platform report field rather than the curve field, and an optimization
must match its report. This preserves the existing `trade_list_as_curve`
direction: platform lists/fills use the report importer; the optional closed
trades field accepts the canonical CSV schema. Directing all platform lists
to the closed trades field would contradict the existing reader and form.
The owner panel includes this category through the shared category allow-list.
`equity_required` stays in `columns_missing`: the required curve input is absent;
the error does not establish that a supplied file arrived empty.

Only a 4096-byte prefix is read from each posted file before the full read.
Strong image and unsupported ELF/RAR/7z/FLAC signatures reject immediately,
without format detection, table parsing or engine work. An unknown text prefix
cannot safely rule out later CSV/HTML tables or workbook contents; those use
the existing bounded readers. A PDF signature does not reveal whether a trade
table is present, so the existing isolated PDF extraction remains necessary.
Starlette has already received/spooled multipart before the route runs: this
avoids processing the whole file, not receiving it. Tests assert bounded reads
and no parser calls, rather than a machine-dependent timing threshold.
The detected-format line is omitted if no nonempty file prefix was inspected;
the counter still uses `unknown`. Image refusals in other upload fields never
describe the file as an equity curve.

After a parsed-form refusal the page preserves escaped declarations and column
choices, including return-series units/frequency. Browsers require file
selection again; the general retry form leaves the access code blank. Refusals
before multipart parsing (body limit, timeout, admission) cannot preserve fields
the server has not parsed. Nothing in this retry state is persisted or logged.
Default benchmark applicability and challenge selections do not open advanced
options or extras on retry; nondefault declarations still open their sections.

The additive `upload_rejection_counters` table aggregates UTC day, category,
detected format, detector and count, using strict allow-lists. Format denotes
the container recognized by the prefix (CSV, HTML, PDF, image, XML, ZIP/XLS or
unknown), not proof of platform compatibility. ZIP headers alone cannot
distinguish XLSX from other ZIP containers. No content, full filename, e-mail,
address or customer identifier enters these counters. The owner-key panel
shows the last seven UTC dates by category/format, plus attempted/accepted
upload requests in the existing 30-day funnel. Repeated requests are repeated
attempts; they are not unique people. An accepted request never increments a
rejection count. Account/payment denials and unexpected server failures retain
their existing separate operations outcomes.

The combined parser does not identify the failing auxiliary file on every
error. With several files supplied, an unattributed parser refusal therefore
uses `unknown` rather than assigning the primary file's format to that failure;
header and size checks and explicit column mapping identify their own input.
The page then omits the detected-format line instead of printing "not
recognised" for a report that was identified (for example an MT5 HTML report
posted with a separate trades CSV); the generic parser failure follows the
same rule. The `files_mismatch` next step names the form field for each file
(platform report, closed trades, equity curve or return series, MT5
optimisation export) instead of repeating the parser's "not both" alert.

Rejection counters use the existing optional asynchronous operations worker,
SQL timeouts and retry behavior, sharing its 4096 pending-key bound. A process
crash can lose unflushed counts; telemetry failures never change the upload
answer. New counts start at deployment and cannot explain earlier 422s.
Offline synthetic tests cover localized guidance and guard, preserved fields,
header fast paths, category aggregation, owner access and accepted exclusion.
The Windows verification environment for this change uses
`D:\wt\.venv-pp\Scripts\python.exe` with worktree `PYTHONPATH` and `--basetemp`,
without package installation; `test_audit_pdf*.py` and
`test_personal_paper*.py` are excluded as requested.

## Conversion toward the first free report (8 October 2026)

Four pages now lead a new visitor to the free first report instead of
ending at the calculator. Every step is read from the configuration; no
account, payment, credit, e-mail, legal or engine rule changed.

- **Pricing** (`pricing.start_cta`). `/precios`, `/en/pricing` and
  `/pt/precos` close with "Empieza por el informe gratis": the first full
  report is the same report as the paid ones, with the PDF, and needs an
  account and the file the platform exports. The main button ("Crear cuenta
  y pedir mi primer informe") goes to `audit_path(locale)`, which sends a
  visitor without an account to sign-up with `next` back to the form; links
  to the sample report and the export guides follow, and the luck calculator
  is a text link. With `AUDIT_EMAIL_VERIFICATION_REQUIRED` the existing
  e-mail note is added. In free mode the text says every full report is free
  and only the file is needed (the form asks for no account there). Without
  the free first report (`AUDIT_WELCOME_FULL_REPORT=false`, the paid offer)
  it reads "Empieza por la vista previa gratis": the free preview, the price
  and the 7-day refund (`paid_offer.paid_text`), with "Subir mi archivo".
- **Sample report** (`report.render(sample_cta=True, sample_offer=...)`, only
  from `web._sample_html`). Under the synthetic-data notice, a `no-print` band
  says the first report with one's own file is free with an account (free
  mode: every full report is free; `paid`: "Audita tu propio archivo de la
  misma forma." followed, with its price, by the paid offer's three
  sentences), with a button to
  the form and "¿Qué archivo produce un informe así?" linking the MT5 and MT5
  optimisation guides. The toolbar shows "Crear cuenta"
  (`/registro?next=/auditar`, `/signup?next=/en/audit`,
  `/pt/cadastro?next=/pt/auditar`) instead of "Mi cuenta". When the sample PDF
  route exists (`pdf_lib.available()`), a closing `no-print` block, "Compruébalo
  tú", links the PDF and `/comprobar`: the check page answers the sample PDF
  with "Es el informe de ejemplo de Rigor, sin cambios" (it is recorded under
  `check.SAMPLE_AUDIT_ID`), and a client's PDF or JSON with its issue date and,
  when recorded, its class. The block says exactly that. The sample PDF is
  rendered without any of it. With `sample_cta=False` (every client report)
  the HTML and JSON are byte for byte what they were: the band's styles live
  inside the band, not in the shared stylesheet.
- **Sign-up** (`account_pages.signup_page(email_verification=, offer=)`).
  When `next` is an upload page (`AUDIT_PATHS`), the side panel shows "Así
  sigue" instead of the account benefits: create the account; only with
  `email_verification_required`, open the e-mailed link (the free full report
  waits for it); upload the file the platform already exports, with the
  upload form's own list of platforms (`pages.PLATFORMS`) and a link to
  `/guias`; get the class (`strategies.CLASS_ORDER`), the
  `len(verdict.DIMENSION_ORDER)` checks with their evidence label and the PDF,
  the first one free (free mode: every full report free). A link to the sample
  report follows, then the existing "what we keep" card. No processing time is
  given. Any other `next`, or a configuration without a free first report,
  keeps the benefits. The "confirmation link sent" notice
  (`welcome_confirm`) on the upload page and on "Mi cuenta" adds "Mientras
  llega el correo, exporta tu archivo", linking `/guias`
  (`account_pages.welcome_confirm_guides`). The notice on a report page, where
  the file was already uploaded, is unchanged.
- **Each article's next step** (`articles.ARTICLE_NEXT_STEPS`,
  `next_step_links`, `next_step_call`). The first step is the side button
  and the closing button; the others, plus the free first report when it is
  not among them, are the closing call's links. `leer-informe-probador-mt5`:
  form and MT5 guide. `ea-sobreoptimizado` and `lo-eligio-el-optimizador`:
  form and MT5 optimisation guide. `backtest-costos-reales`: form.
  `copiar-senales-mql5-myfxbook`: Myfxbook guide, then the form.
  `cuantas-operaciones-porcentaje-aciertos`: the win-rate calculator opened
  with the article's declared example (`WIN_RATE_EXAMPLE_VALUES`, 45 trades at
  71 %). `cuantos-intentos-reto-prop-firm`: `/para/retos-prop-firm` (which
  already links back to the article). `sharpe-deflactado-track-record` and
  `bot-ia-backtest-suerte`: the luck calculator opened with
  `LUCK_EXAMPLE_INPUT`, the example both articles print.
  `auditoria-independiente-backtest`, `que-hacer-despues-del-backtest` and
  `auditar-cartera-modelo-senales`: form and sample report. `Article.from_dict`
  refuses an unknown kind, guide, audience page or example at import.

`tests/test_audit_conversion.py` reads every page over HTTP with
`TestClient` in the three languages: the pricing close and its configuration
variants, the sample's band, toolbar and closing block (and that its PDF
checks as the unchanged sample on `/comprobar`), a client's report identical
with `sample_cta=False` and equal to the `sample_cta=True` page minus the
three additions, the sign-up steps for each configuration and the guides link
of the confirmation notice, and, per article and language, that the side
button and the closing call follow the table above and that every link
answers 200. Every new text passes `find_claims` and avoids "verificado",
"certificado", "aprobado", "garantiza", "rentable" and processing times.

## Account and signal reports without contradictions (9 October 2026)

With the paid offer the signal sample is what a copier reads before paying,
so every figure it shows twice now reads the same both times. No figure,
threshold, class, stored evidence tag, simulator result, price or credit
changed (`tests/test_audit_informe_cuenta_coherente.py`, es/en/pt); what a
new result stores beyond its texts is listed under the fourth pass.

- **One name per PSR** (`psr_names`). Since policy 2026-09-27-dependence-1
  the statistical dimension uses the lower of the plain PSR and the
  dependence-adjusted one; the report still said "the class uses the plain
  count" and the plan quoted the plain figure. Results stored between the
  dependence figure's arrival (26 September, informational) and that policy
  (27 September) stored the adjusted figure but classified with the plain
  count. `class_psr(data)` reads which figure each stored dimension used and
  its track record; the plan, the technical detail ("PSR adjusted for
  dependence 0.677 < 0.8") and the significance table ("PSR (plain count)",
  plus a row for the adjusted figure) give each its name. The adjusted row's
  note ("the figure the class uses") and the dependence sentence ("the class
  uses the second figure") follow `class_psr`: a result that classified with
  the plain count keeps "it is informational: the class uses the plain
  count". The sentence says the dependence changes nothing only when both
  figures read the same in the table. The plain track record rows say
  "(plain count)".
- **Declared floating result in the reconciliation.** When the engine values
  no open position and the file declares a floating result
  (`report.declared_open_value`: the account review's DECLARED figure, else
  the platform summary), the "Open-position value" row shows it as Declared,
  with its note and why it stays out of the expected balance (closed trades
  only); the coverage line says the same. The expected balance is unchanged.
  Only the reconciled file's own review counts: an account history uploaded
  as the real account beside a backtest (`account.source == "live"`) has its
  own section, and its floating result never reaches the backtest's
  reconciliation or challenge (`report._own_account`).
- **Under a year is not 12 months.** The luck section gives the history in
  months with one decimal, or "almost 12 months", never rounded up to 12.
- **Annual figures below -100 %.** The mean-shift section shows any yearly
  average or band end below -100 % as "-100.0% or worse"; the stored band is
  unchanged.
- **Account wording.** On an account or signal history the out-of-sample
  meaning and plan step ask since when the account or signal has traded
  unchanged and whether it was reset or replaced a closed account; the
  multiplicity step and meaning count the accounts or signals behind it
  (no optimisation XML); the backtest to compare is "of the same strategy,
  if it has one"; "keep this report" speaks of the signal's settings or a
  new account. Every text has its own, provider and neutral voice
  (`ownership.PLAN["account_trials"]`, `["account_trials_undeclared"]`,
  `["title_account_multiplicity"]`, `MEANING["multiplicity.WEAK.account"]`,
  `["multiplicity.WEAK.undeclared.account"]`, `LABELS["next_keep_account"]`).
- **Challenge with an unseen open loss** (`report.unseen_open_loss`). With
  HIDDEN_FLOATING_DRAWDOWN, or FLOATING_LOSS_AT_END on a balance-only curve,
  the challenge section opens with a red callout: the open loss (its declared
  share of the balance, given with FLOATING_LOSS_AT_END or when it shows as at
  least 1 %, never "0%") already counts against the daily and total limits of
  any challenge, and the figures below do not see it. With
  HIDDEN_FLOATING_DRAWDOWN the callout also names the open losses the balance
  hid during the history (the flag's title), alone when no share is given. The
  outcome table, the ladder, the size table and the firms' table sit in
  `<details class='unseen-open'>` under that callout (the size and firms
  subsections each repeat a short line first). The simulator is unchanged;
  the PDF opens the folds (`pdf._expand_details_for_pdf`).
- **Two periods.** The header says "Curve data"; under the platform's figures
  a line says Start and End are the platform's period or its first and last
  trade, while the curve data run from the curve's first point (a deposit
  or the opening balance) to its last.
- **Net or gross.** The backtest-against-live table names its averages "net
  of fees" only when both files itemise fees per trade (`live.fees_itemised`,
  stored with the comparison; a result stored before it reads the backtest's
  from `win_rate_gross` and the live file's as unknown), else plain "Average
  win"; the trade table names its own "gross, before fees" when the file
  itemises fees per trade.
- **Account wording, second pass.** The multiplicity meaning and the summary
  of an account or signal with no trial count declared count accounts or
  signals, not configurations (`verdict` `multiplicity.FAIL.undeclared.account`,
  `NOT_MEASURED.undeclared.account`, and the summary's `.undeclared.account`
  templates; `ownership.MEANING` in every voice); the luck section asks how
  many accounts or signals stand behind it (`luck_uncounted_account`, no
  optimisation XML); the plan's new months are "data that was not used to
  choose them", not "data the optimiser never saw"; the backtest question is
  "of the same strategy, if it has one" in every voice, the seller message
  included, and a result stored with the old wording shows the new one
  (`analytics.question_now`).
- **Account wording, third pass.** On an account or signal the luck
  section's introduction, lines, table header and sources' note count the
  accounts or signals behind it and the history's length
  (`luck_*_account`), the challenge's luck row says the same
  (`ch_ladder_undeclared_account`), and the multiplicity dimension is
  "Number of accounts or signals behind it" in the list, the technical
  detail, the PDF cover, the seller message and the public page
  (`report.DIMENSION_TITLES_ACCOUNT`). The sizing and grid questions ask
  about "this account or signal" (`analytics.ACCOUNT_QUESTIONS`, stored for
  new account results and shown over older ones), and in every voice but
  the buyer's they are answered by the account's own trades
  (`ownership.ACCOUNT_QUESTIONS`, with the recent stretch's). The plan's data
  step asks for sizes, positions, the floating curve and a history at a fixed
  size or without averaging when one exists, never a backtest to upload, voice
  by voice (`plan.ACCOUNT_FLAG_HINTS`, `ownership.PLAN["account_flag_*"]`);
  "What to do now" and the instruments section name the account or signal.
  The backtest's answer says "if it has one" once. A backtest keeps its
  robot, configuration and optimiser wording; what does change on its page
  comes from the points above that apply to every report (the PSR names,
  "net" or "gross", "Curve data" and the drawdown's sign).
- **One reading per figure.** The challenge callout tags the open loss
  "(Declared)" as the account section does; each starting balance shows the
  tag it stores (fifth pass); the dependence sentence rounds the variance
  ratio as the multiplicity table does; the resampled one-year drawdowns carry
  the minus sign of the summary's tile; the mean-shift sentence says when its
  annual rates come from stretches under a year, and how long each lasts
  (`shift_short`); the seller message lists the dimensions that fail apart
  from the weak ones (`dimensions_weak`). Figures, classes and the simulator
  are unchanged.
- **Fourth pass (review of the third).**
  - The recent stretch's question of an account or signal asks whether its
    settings changed afterwards or it was restarted, not whether "the
    system was reoptimised" (`analytics.ACCOUNT_QUESTIONS["recent_period"]`,
    stored for new account results and shown over older ones, the seller
    message included); its answer names the date of any change or restart.
  - The reconciliation keeps the starting capital's stored tag, Measured:
    the engine rebuilds it from the file (the deposits it lists before the
    first trade, a Myfxbook statement's 1,000.00 among them), and the
    downloadable JSON's `reconciliation.initial_capital` says so. (This pass
    also showed the size table's balance with the reconciliation's tag; the
    fifth pass takes that back.)
  - The multiplicity detail and the CSCV row of an account or signal with no
    matrix uploaded speak of the histories of the other accounts or signals
    behind it, not "the variants you uploaded" (`variance_policy_account`,
    `no_variants_account`, `KEY_LABELS["observed_across_accounts"]`); a
    matrix that was uploaded keeps its row.
  - A comparison and "what changed" name the multiplicity dimension by the
    kinds of report shown (`report.shared_dimension_title`): an account's
    name when every report is an account or signal, "Number of trials" when
    one sits beside a backtest (`DIMENSION_TITLES_MIXED`), the backtest's
    otherwise.
  - The mean-shift sentence says each stretch's length as the luck section
    says the history's (`report._span_text`): "almost 12 months" when a
    stretch under a year rounds to 12.0, "1 month" for 1.0, years from a
    full year on.
  - Portuguese asks the "fornecedor" in the plan's account hints and the
    account section, as the rest of the report does.
  - The extreme jumps (MAD_SPIKES) of an account ask the provider whether
    they come from deposits, withdrawals or bad prices, in the buyer's voice
    (`plan.ACCOUNT_FLAG_HINTS`), and say what to upload, provide or read in
    the developer's, provider's and neutral ones
    (`ownership.PLAN["account_flag_MAD_SPIKES"]`); a backtest keeps "fix
    them".
  - When Start and End are not dates of the period the platform prints (a
    Myfxbook statement prints none), the line under the platform's figures
    says they are not stated by the platform but taken by Rigor from the
    first and last trade (`platform_period_trades`,
    `report._platform_states_period`); the table and its tag are as stored.
  - Stored results. `live.compare_live` stores `fees_itemised` with every
    comparison against a real account (display only: which side's averages
    are net of the fees it itemises), and a new account result stores the
    account wording of three questions. The public samples are rebuilt at
    start-up, so the sha256 of their JSON (on `/ejemplo`, `/ejemplo-senal`,
    their `/v/` pages, the English and Portuguese reports and the preview)
    changes once with this release; no test, cache or `/comprobar` record
    pins the earlier one, and a PDF downloaded before keeps the record it was
    issued with.
- **Fifth pass (the paid preview and the stored tags).**
  - The paid preview of an account or signal, what whoever copies it reads
    before paying USD 29 (an anonymous upload with `anon_preview=True` and
    `welcome_full_report=False` shows it too), lists the multiplicity section
    as "What is left after discounting the accounts or signals behind it"
    (`report.LOCKED_GAINS_ACCOUNT`, es/en/pt, every voice), the accounts or
    signals its dimension ("Number of accounts or signals behind it") and
    the plan's step count, not "the configurations tried". No other line of
    that preview speaks of configurations, robots or optimisers (the
    singular "configuración" and "configuração" of the Spanish and Portuguese "keep
    this report" line is the signal's settings). A backtest's preview keeps
    its line.
  - Each starting balance shows the tag it stores, as the downloadable JSON
    gives it: the reconciliation's starting capital Measured (the first
    point of the curve the engine rebuilds from the deposits the file
    lists), the size table's balance Declared
    (`challenge.sizing.starting_balance`). The display tag of the earlier
    passes is gone (`report.reconciled_starting_balance`, and before it
    `declared_initial_value`). On an account or signal the 1x line says in
    a few words where its figure comes from: "the starting balance the file
    declares (1,000)" (`ch_size_balance_declared`,
    `report.file_declares_balance`), so Declared there and Measured in the
    reconciliation read without contradiction. A balance the client declared
    on the form, an assumed one or a curve's first value keeps its own line.
    A backtest, `/ejemplo` and `/sample` included, reads both lines word for
    word as before this branch (e1df258).
  - Nothing stored changes: the samples' JSON and its sha256 are those of the
    fourth pass.
