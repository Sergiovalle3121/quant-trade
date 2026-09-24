# Backtest audit: the service, what it measures, and how to run it

The audit is the repository's validation engine pointed at a file a client
uploads. It answers one question in six parts: *is this track record
statistically real, and what would change that answer?* It is research
tooling sold as a second opinion. It is not investment advice, it executes
nothing, it holds no funds and no keys, and it never claims that money was
or will be made. The profit-claim guard refuses any report that does.

## What the client uploads

| File | Required | Columns (aliases accepted, case-insensitive) |
|---|---|---|
| Platform report | this or the equity file | The file as the platform writes it; see "Importers" below. One file gives both the closed trades and the balance curve. |
| MT5 optimisation export | no | The XML the MT5 optimiser exports. Its passes become the MEASURED number of trials in the deflated Sharpe. |
| Equity or returns | this or a report | `timestamp` + `equity` (or `return`). `Date`/`NAV`, `%` returns, `;` separators and epoch timestamps are understood. |
| Closed trades | no | `entry_time, exit_time, quantity, entry_price, exit_price`, optional `side`, optional `pnl`. |
| Benchmark | no | same shape as the equity file. |
| Variants | no | one return column per parameter variant tried, same rows. |

Plus four declarations: trials tried before choosing this version, cost per
side in basis points, an out-of-sample start date, and whether a benchmark
applies. Limits: 5 MB and 200,000 rows per file, 50,000 trades, 500 variants,
at least 30 return observations.

### Importers and their limits

`audit/importers.py` detects the format by content (standard library only)
and reads: MetaTrader 5 tester and account-history HTML reports (UTF-16 is
common), MetaTrader 4 tester reports and detailed statements, TradingView
"List of trades" CSV and XLSX, and the trade exports of NinjaTrader,
QuantConnect, backtesting.py and vectorbt. Limits, each written into the
report as a reading warning:

- The balance curve is rebuilt from closed trades. It cannot show floating
  (open-trade) drawdown, so the real drawdown was at least as deep.
- Report times carry no timezone; they are read as UTC.
- Contract sizes are inferred from the reported profit when the file does
  not state them.
- A report without a starting balance uses the one the client declares,
  else 10,000 with a warning.
- The MT5 optimisation pass count is what the optimiser tried; a genetic
  optimisation lists only the passes it evaluated. The deflated Sharpe uses
  the largest of the declared trials, the uploaded variants and the passes.

### Charts and printing

The report embeds four SVG figures without JavaScript (`audit/charts.py`):
equity, drawdown, the resampled scenario fan and the monthly return map,
each with its evidence tag. "What it means for you" gives two plain
sentences per dimension. The "Print / save PDF" button uses the print
stylesheet, which hides the buttons and the forms.

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
  2,000,000 resampled cells. Maximum drawdown p50/p95/p99, the share of
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

| Key | Target | Daily loss | Max loss | Min days | Source (read 2026-09-24) |
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

Trials: the deflated Sharpe uses the larger of the declared trials and what
the files prove (columns of the variants matrix, passes of an MT5
optimisation export, variants in a vectorbt report); the latter is tagged
MEASURED. `TRIALS_BELOW_VARIANTS` warns when the declaration is lower.

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
| `GET /` | Landing (how it works, prices, FAQ, link to the sample) and the form; `?lang=en`. |
| `POST /audits` | Upload. An optional `access_code` field redeems a code (paid mode with codes on). |
| `GET /audits/{id}?token=…` | The report. `GET /audits/{id}.json?token=…` the record (402 while locked). |
| `POST /audits/{id}/checkout?token=…` | Stripe Checkout (503 without Stripe). |
| `POST /audits/{id}/redeem?token=…` | Unlock an existing preview with an access code. |
| `POST /audits/{id}/publish?token=…` | Create (or return) the public verification page. Paid audits, or any audit in free mode; 402 otherwise. |
| `POST /audits/{id}/unpublish?token=…` | Remove the public page. |
| `GET /v/{public_id}` | Public verification page. `GET /v/{public_id}/badge.svg` its badge. 410 once purged. |
| `GET /ejemplo`, `GET /sample` | A full report of synthetic data, Spanish and English. |
| `GET /terminos`, `GET /terms` | Terms of service (`audit/legal.py`), Spanish and English; either answers `?lang=`. |
| `GET /privacidad`, `GET /privacy` | Privacy policy, Spanish and English. |
| `POST /webhooks/stripe`, `POST /waitlist`, `GET /health` | Payment confirmation, waiting list, health check. |

Every private URL carries a per-audit secret token; a wrong token is a 404.
Every response is `Cache-Control: no-store` except the two `/v/` routes,
which are `public, max-age=300`.

Configuration is by environment only (`.env.example` lists every variable
with an empty value):

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///state/audit/audit.db` | SQLite file or Railway Postgres (`postgres://` is normalised to `postgresql+psycopg://`). |
| `AUDIT_BASE_URL` | `http://localhost:8000` | Public URL used in Stripe success and cancel links. |
| `AUDIT_FREE_MODE` | `true` | Serve watermarked reports with nothing locked. Forced `true` unless all three Stripe variables are set or `AUDIT_ACCESS_CODES=true`. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID` | empty | All three are needed for card payments. |
| `AUDIT_ACCESS_CODES` | `false` | Sell with access codes. With `AUDIT_FREE_MODE=false` it turns on paid mode without Stripe. |
| `AUDIT_CONTACT_URL` | empty | Where a client asks for a code (for example a `https://wa.me/…` link or a `mailto:`). Only `https://` and `mailto:` are shown. |
| `AUDIT_PRICE_USD_CENTS` | `4900` | The price shown on the landing and on the pay button; with Stripe, the Stripe price object decides what is charged. |
| `AUDIT_MAX_UPLOAD_BYTES` | `5000000` | Per file. |
| `AUDIT_MAX_UPLOADS_PER_HOUR_PER_IP` | `10` | 429 above it. |
| `AUDIT_RETENTION_DAYS` | `30` | Shown on the form and the privacy page. `audit purge --days` must use the same number. |
| `AUDIT_BOOTSTRAP_SAMPLES` | `1000` | Fewer samples make the service faster and the bands coarser. |
| `AUDIT_OPERATOR_NAME` | empty | Legal name of whoever runs the service, shown on the terms and privacy pages. |
| `AUDIT_OPERATOR_CONTACT` | empty | Contact for privacy and deletion requests (an e-mail address). |
| `AUDIT_OPERATOR_ADDRESS` | empty | Postal address of the operator. |
| `AUDIT_JURISDICTION` | empty | Governing law and courts, for example "Leyes de México; tribunales de la Ciudad de México". |
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
   simpler choice and the only one a separate cron service can share.
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
   `AUDIT_CONTACT_URL` link on the landing and under the locked report. For card payments create a Stripe price, add the three Stripe variables, set
   `AUDIT_FREE_MODE=false`, and register the webhook endpoint
   `https://<domain>/webhooks/stripe` for `checkout.session.completed`.
   Locally: `stripe listen --forward-to localhost:8000/webhooks/stripe`
   then `stripe trigger checkout.session.completed`.
5. Retention: run `quant-trade audit purge --days 30 --yes` every day (a
   Railway cron service with the same variables works with Postgres; with a
   SQLite volume run it from `railway ssh`, since a volume attaches to one
   service only), with the same number of days as `AUDIT_RETENTION_DAYS`.
   The privacy page promises it, and nothing runs it automatically. Unpaid
   uploads, reports and the client's description are deleted; id, digests
   and class are kept so the record stays verifiable. The upload IP address
   of every audit past the window, paid ones too, is cleared in the same run.
6. Set the four `AUDIT_OPERATOR_*`/`AUDIT_JURISDICTION` variables. Until
   they are set, `/terminos` and `/privacidad` show "[sin configurar]" and a
   warning, and `/health` reports `"legal_configured": false`.

### Testing a deployment on Railway

1. Open `https://<domain>/health`: `free_mode`, `stripe_enabled` and
   `access_codes` say which mode the variables produced. Selling with codes
   shows `"free_mode": false, "access_codes": true`.
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

### Public verification page and badge

The owner of an audit (whoever holds its token) can publish it. The page at
`/v/{public_id}` uses a random id unrelated to the audit id and shows only:
the class and its fixed one-line explanation, the audit and publication
dates, the six dimension statuses with their plain-language text, the input
hashes and `dataset_digest`, the source format, the engine version, the
declared trials and the trials used, the SHA-256 of the result, and a fixed
notice. It never shows the files, the trades, the description or the token.
Once the audit is purged the page and badge answer 410.

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

### Terms and privacy

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
| Unpaid audits' files, report, declarations and description are deleted after `AUDIT_RETENTION_DAYS` | `quant-trade audit purge --days N --yes`, daily |
| The upload IP is deleted after the same window, paid audits too | the same purge run |
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
- Badge, verification and challenge texts never imply future results;
  changing their fixed wording needs a test.
- Access codes are stored hashed and printed once; `codes list` never shows
  them.
- The terms and privacy pages pass the guard in both languages; anything the
  privacy page promises needs a command that does it and a test.
