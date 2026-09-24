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
| Equity or returns | yes | `timestamp` + `equity` (or `return`). `Date`/`NAV`, `%` returns, `;` separators and epoch timestamps are understood. |
| Closed trades | no | `entry_time, exit_time, quantity, entry_price, exit_price`, optional `side`, optional `pnl`. |
| Benchmark | no | same shape as the equity file. |
| Variants | no | one return column per parameter variant tried, same rows. |

Plus four declarations: trials tried before choosing this version, cost per
side in basis points, an out-of-sample start date, and whether a benchmark
applies. Limits: 5 MB and 200,000 rows per file, 50,000 trades, 500 variants,
at least 30 return observations.

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

Routes: `GET /` landing and form (`?lang=en`), `POST /audits` upload,
`GET /audits/{id}?token=…` report, `GET /audits/{id}.json?token=…` record,
`POST /audits/{id}/checkout?token=…` Stripe Checkout (503 in free mode),
`POST /webhooks/stripe` payment confirmation, `POST /waitlist`, `GET /health`.
Every report URL carries a per-audit secret token; a wrong token is a 404.

Configuration is by environment only (`.env.example` lists every variable
with an empty value):

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///state/audit/audit.db` | SQLite file or Railway Postgres (`postgres://` is normalised to `postgresql+psycopg://`). |
| `AUDIT_BASE_URL` | `http://localhost:8000` | Public URL used in Stripe success and cancel links. |
| `AUDIT_FREE_MODE` | `true` | Serve watermarked reports and never create a checkout. Forced `true` when any Stripe variable is missing. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID` | empty | All three are needed for paid mode. |
| `AUDIT_PRICE_USD_CENTS` | `4900` | Shown on the page; the Stripe price object decides what is charged. |
| `AUDIT_MAX_UPLOAD_BYTES` | `5000000` | Per file. |
| `AUDIT_MAX_UPLOADS_PER_HOUR_PER_IP` | `10` | 429 above it. |
| `AUDIT_RETENTION_DAYS` | `30` | Used by `audit purge`. |
| `AUDIT_BOOTSTRAP_SAMPLES` | `1000` | Fewer samples make the service faster and the bands coarser. |
| `AUDIT_TRUSTED_PROXY_HOPS` | `0` | Reverse proxies in front of the service. `0` ignores `X-Forwarded-For` (it is client-controlled) and rate-limits the socket address; `N` takes the N-th entry from the right. Railway needs `1`. |

### Deploying on Railway

1. Create a service from this repository. `railway.json` selects
   `Dockerfile.web` and the `/health` check; the container listens on
   `$PORT`.
2. Storage: either add the Railway Postgres plugin (it injects
   `DATABASE_URL`) or mount a volume at `/data` and set
   `DATABASE_URL=sqlite:////data/audit.db`.
3. Set `AUDIT_BASE_URL` to the public domain Railway assigns or to the
   custom domain you attach, and `AUDIT_TRUSTED_PROXY_HOPS=1` so the
   hourly limit counts the visitor's address and not Railway's proxy.
4. Leave `AUDIT_FREE_MODE=true` until the first paid audit is wanted. For
   paid mode create a Stripe price, add the three Stripe variables, set
   `AUDIT_FREE_MODE=false`, and register the webhook endpoint
   `https://<domain>/webhooks/stripe` for `checkout.session.completed`.
   Locally: `stripe listen --forward-to localhost:8000/webhooks/stripe`
   then `stripe trigger checkout.session.completed`.
5. Retention: run `quant-trade audit purge --days 30` and confirm with
   `--yes` (a Railway cron service works). Unpaid uploads, reports and the
   client's description are deleted; id, digests and class are kept so the
   record stays verifiable.

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
