# Backtest audit, iteration 4: build plan

Status: approved by the owner, not yet built. Iteration 3 (the audit engine,
report, CLI, web service and Railway deploy) is on `main`. This document is
the complete brief for the next iteration, written so that a fresh session
can execute it without the conversation that produced it.

Research inputs, committed next to this file:

- `docs/research/audit_iteration4/formats_metatrader.json`: verbatim layouts
  of MT5 tester and history reports (HTML and XML), MT4 tester report and
  detailed statement, and the MT5 optimisation XML, with pairing rules,
  equity reconstruction, sample snippets and sources.
- `docs/research/audit_iteration4/formats_other_platforms.json`: TradingView
  "List of trades" CSV (every header generation 2021-2026) and XLSX,
  cTrader, NinjaTrader 8, QuantConnect, backtesting.py, vectorbt, backtrader.
- `docs/research/audit_iteration4/market_competitors.json`: scored feature
  ideas, competitor prices and rule conflicts, with sources.
- Not finished: current prop-firm challenge rules. Research them again
  (official FAQ pages, cite URL and date) before building the presets.

## 1. What the market research changed

Direct competitors already exist and are cheap:

| Product | Offer | Price |
|---|---|---|
| EA Verdict | six-dimension verdict, Monte Carlo fan, ruin, prop-rule replay, martingale forensics | USD 19 per audit |
| EA X-Ray | free instant 0-100 score from an MT5 report | EUR 29 verified audit |
| AntiOverfit | private robustness score | EUR 97; EUR 390 private audit |
| QuantAnalyzer / StrategyQuant X / Build Alpha | desktop suites | USD 349 to 2,900 |
| Prop-firm pass calculators | TradeZella, Tanto, Prop Firm Pal, LuxAlgo (open source) | free |

Consequences for this iteration:

- Import of the file traders already have (MT4/MT5 report, TradingView
  list of trades) is table stakes; without it the product loses on the
  first click.
- The prop-firm simulator is not sellable on its own (free elsewhere); it is
  a feature inside the audit and a hook for content.
- Differentiators to protect and make visible: Spanish first, deflated
  Sharpe at the real number of trials (the MT5 optimisation XML gives the
  true pass count), CSCV/PBO, evidence tags on every number, verifiable
  hashes, and honest limitation text.
- Pricing (a business decision, not code in this iteration): a free instant
  class (the current watermarked preview), a cheap buyer check around
  USD 19, the full report at USD 49, a seller page with badge, and a
  developer subscription. The verdict must be identical across tiers; only
  the visible sections differ.

## 2. Scope

Build, in this order. Out of scope: B2B API, e-mail delivery, version
comparison, launch guide.

### 2.1 Production fixes (blocking for launch)

- `audit/web.py`: `POST /audits` is `async` and calls `build_inputs`,
  `run_audit`, `render` and the `Store` synchronously, which blocks the
  event loop for every audit. Run them through
  `starlette.concurrency.run_in_threadpool`.
- Rate-limit IP: `_client_ip` trusts `X-Forwarded-For` unconditionally, so
  the hourly limit is bypassed by spoofing the header. Add
  `AUDIT_TRUSTED_PROXY_HOPS` (default 0: ignore the header and use the socket
  address; N > 0: take the N-th entry from the right). Railway needs 1.
- Localised errors: `schema.ParseError` gains an optional code and a Spanish
  message; the web shows the message in the form's locale. The web's own
  errors (consent, size, rate limit, missing file) are translated too.

### 2.2 Importers (new `src/quant_trade/audit/importers.py`)

Detect by content and parse, with the standard library `html.parser` only
(no lxml or bs4), decoding by BOM, then utf-8, utf-16, cp1252:

- MT5 Strategy Tester HTML report (often UTF-16 LE with BOM; Deals table,
  in/out/inout pairing, partial closes, hedging and netting), MT5 account
  history report, MT4 tester report, MT4 detailed statement.
- TradingView list of trades CSV (all header generations in the research)
  and XLSX (import `openpyxl` lazily; check the uncompressed size first to
  refuse zip bombs; otherwise ask for CSV).
- CSV dialects: NinjaTrader 8 trades, QuantConnect trades, backtesting.py
  `_trades`, vectorbt trade records.
- MT5 optimisation XML: number of passes (the true trial count) and
  parameter names.

Public API:

```python
@dataclass(frozen=True)
class ImportedReport:
    source_format: str            # mt5_tester_html, mt5_history_html, mt4_tester_html,
                                  # mt4_statement_html, tradingview_csv, tradingview_xlsx,
                                  # ninjatrader_csv, quantconnect_trades_csv,
                                  # backtestingpy_csv, vectorbt_csv
    trades: ParsedTrades          # from schema.py
    equity_csv: bytes             # "timestamp,equity" balance curve
    initial_balance: float | None
    currency: str | None
    fees: dict[str, float]        # {"commission": ..., "swap": ...}
    warnings: list[str]
    metadata: dict[str, str]      # symbol, period, strategy, broker, dates

def detect_format(data: bytes, filename: str | None = None) -> str | None: ...
def import_report(data: bytes, filename: str | None = None) -> ImportedReport: ...

@dataclass(frozen=True)
class OptimizationSummary:
    source_format: str
    passes: int
    parameters: list[str]
    warnings: list[str]

def parse_optimization(data: bytes, filename: str | None = None) -> OptimizationSummary: ...
```

Semantics:

- One `core.models.Trade` per closed round trip; partial closes become
  separate round trips. Platform P&L in account currency is authoritative:
  `Trade.pnl` and `client_pnl` = reported gross profit (without commission
  and swap).
- MetaTrader volume is in lots, so `Trade.quantity = lots * multiplier`, the
  multiplier per symbol being the median of
  `|profit| / (|exit - entry| * lots)` over trades with a price move
  (fallback 1.0). Warn "contract size inferred from reported profit".
- `equity_csv`: end-of-day balance (the report's Balance column when
  present), one row per business day (calendar days if any trade closes on
  a weekend), from the day before the first trade to the last exit, starting
  at the initial deposit (else warn and use 10000). Always warn that a
  balance curve from closed trades does not show floating drawdown.
- Never copy account numbers or personal names into `metadata`.
- Limits: `schema.MAX_UPLOAD_BYTES` and `MAX_TRADES`; a plain `ParseError`
  that names what was expected when no trades table is found.

### 2.3 Analytics (new `audit/analytics.py` and `audit/prop_presets.py`)

- `trade_statistics(trades, sides, *, fees_total=0.0)`: win rate, profit
  factor, expectancy, average win and loss, payoff ratio, largest-win share,
  max consecutive wins and losses, mean and median holding hours, SQN,
  long/short split, trades per month. MEASURED; NOT_MEASURED without
  trades.
- Martingale / grid / averaging-down red flags (highest value-to-effort in
  the market research): volume increasing after losses, many open positions
  on one symbol at once, no stop (large adverse excursions when available).
  Add them to `redflags.py` with tests.
- `drawdown_risk(returns, *, periods_per_year, samples=2000, seed, ...)`:
  stationary block bootstrap (`research/bootstrap.py::stationary_bootstrap_indices`)
  over one year: max drawdown p50/p95/p99, probability of exceeding
  10/20/30/50 %, time under water, and a fan (p5/p25/p50/p75/p95 of the
  equity path, at most 120 points) for the charts. Note on every figure:
  resampled from the uploaded history, not a forecast.
- Prop-firm challenge simulator: `ChallengeRules(key, firm, program, phase,
  profit_target, max_daily_loss, daily_loss_basis, max_total_loss,
  total_loss_type, min_trading_days, time_limit_days, notes, source_url,
  as_of)`, `PRESETS` from freshly researched official rules (FTMO,
  FundedNext, The5ers, Topstep at least) plus `generic-2step-phase1`
  (10 % target, 5 % daily, 10 % static, 4 minimum days, no time limit) as
  the default. `simulate_challenge(daily_returns, rules, *, samples=5000,
  seed, block_size=5.0, max_days=250)` walks resampled daily paths and
  returns pass / fail-daily / fail-total / unfinished probabilities (summing
  to 1) and days to pass. Fixed notes: daily data cannot see intraday
  floating drawdown, so the estimate is optimistic; it assumes the future
  resembles the history; it is not a prediction.
- A "questions to ask the vendor" checklist for EA buyers, driven by the
  red flags and missing inputs.

### 2.4 Charts and a report people understand (new `audit/charts.py`)

- Inline SVG, no JavaScript, escaped text, `role="img"` and `<title>`:
  equity curve, drawdown (underwater), resampled fan, monthly returns
  heatmap table, and `downsample()` that keeps extremes.
- `AuditResult` gains optional `series`, `trade_stats`, `risk`, `challenge`
  and `inputs.source_format`; `SCHEMA_VERSION` becomes 2.
- "What this means for you": two plain sentences per dimension and status,
  Spanish and English, fixed templates that pass the guard.
- Print CSS and a "Print / save PDF" button.
- In paid mode the verdict, charts and explanations stay visible in the
  free preview; the detail sections are the ones locked.
- CLI: `audit run --report`, `--optimization`, `--challenge`; `--equity`
  optional when `--report` is given; new `audit presets` command.

### 2.5 Selling without Stripe: access codes

- New table `access_codes` (sha256 of the code, credits total and used,
  note, created, optional expiry, disabled). Codes look like
  `AUD-XXXX-XXXX-XXXX`, are printed once and never stored in clear.
- Atomic redemption (`UPDATE … WHERE credits_used < credits_total AND not
  expired AND not disabled`); the audit becomes paid with reference
  `code:<id>`. An invalid code still yields a preview and never reveals
  whether the code exists. Attempts count toward the per-IP limit.
- CLI: `audit codes create --credits N --note TEXT [--expires-days D]` and
  `audit codes list` (never prints codes).
- This lets the owner sell by bank transfer, Mercado Pago or WhatsApp and
  hand out a code.

### 2.6 Shareable verification (growth)

- Owner opt-in with the token: `POST /audits/{id}/publish` creates a
  `public_id` in a new `publications` table (idempotent; paid audits or free
  mode only).
- `GET /v/{public_id}`: class, date, six dimension statuses with their
  plain-language text, input digests, source format, engine version,
  declared trials, and a fixed notice. Never the files, the description,
  trades or the token. 410 when purged.
- `GET /v/{public_id}/badge.svg`: class, id, date and the words
  "Statistical audit of supplied data – not verified with a broker – not a
  performance guarantee" / "Auditoría estadística de datos aportados – no
  verificados con el bróker – no garantiza resultados". Never growth,
  return or profit. Cache-Control public for these two routes only.
- Extend the guard with the patterns the research names ("verified track
  record", "certified", "certificado de rentabilidad", "aprobado",
  "pasarás") and test them. MQL5 Market forbids third-party certificates in
  listings, so the badge's reach is the seller's own site, Telegram, forums
  and YouTube; the terms template must forbid using it in return claims.
- `GET /ejemplo` and `/sample`: a full unwatermarked report from the
  synthetic examples, generated once at startup, with a banner saying the
  data is synthetic; linked from the landing page, which also gains a short
  how-it-works, pricing and FAQ block.

### 2.7 Documentation

`docs/AUDIT_SAAS.md` (importers and their limits, optimisation passes,
trade statistics, resampled risk, challenge presets with sources and dates,
charts and printing, access codes, verification pages and badge wording,
`AUDIT_TRUSTED_PROXY_HOPS`), `.env.example`, `AGENTS.md` Phase 16 additions
(badge, verification and challenge text never imply future results; presets
carry source and as_of; access codes stored hashed and printed once),
`docs/AUDIT_TERMS_TEMPLATE.md` (badge usage), README.

## 3. Rules that always apply

- Everything in `AGENTS.md`, especially Phase 16: research-only, no
  execution, custody or keys; every sentence passes `audit/guard.py` in
  Spanish and English; every number carries MEASURED, DECLARED or
  NOT_MEASURED; no secret has a default; tests are offline.
- Tooling: run `python -m pytest`, `python -m ruff check .`,
  `python -m ruff format` on new files, `python -m mypy src`. The bare
  `pytest` binary may point at another interpreter.
- pandas 3: never assign strings into float columns; timestamps `utc=True`.
- Python 3.11 in CI: never nest the same quote type inside an f-string.
- FastAPI parameters use `Annotated[...]` (ruff B008). `web.py` must not use
  `from __future__ import annotations` (FastAPI resolves signatures at import).

## 4. Acceptance

```
python -m pip install -e ".[dev,web]"
python -m ruff check . && python -m mypy src && python -m compileall -q src tests && git diff --check
python -m pytest -q tests/test_audit_*.py && python -m pytest -q
python -m quant_trade.evidence.provenance_guard --repo-root .   # no new findings
quant-trade audit run --report <synthetic MT5 fixture> --challenge generic-2step-phase1 --output-dir outputs/audit_mt5
quant-trade audit codes create --credits 3 --note demo
quant-trade audit serve   # /ejemplo, upload an MT5 report, publish, open /v/{id} and badge.svg
```

Render the report and `/ejemplo` in headless Chromium
(`executable_path=/opt/pw-browsers/chromium`) to check the charts. The
iteration is done when CI is green on the pull request and it is merged into
`main`; the owner has authorised merging.
