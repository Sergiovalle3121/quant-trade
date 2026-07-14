# Real-Data Verdict: Baseline Strategies on 20 Years of ETF Data

**Verdict: NO-GO. No baseline shows evidence of edge on real data. Zero of five
strategies pass the conservative selection gate; none is a paper-trial
candidate.**

Every baseline that was rejected on synthetic data is also rejected on 20
years of real, total-return-adjusted ETF data, out-of-sample, net of
conservative costs. The failure is not marginal: every strategy loses to the
equal-weight benchmark of its own universe, and every strategy's deflated
Sharpe ratio is statistically indistinguishable from zero after accounting for
the full recorded search.

---

## 1. Dataset

| Field | Value |
| --- | --- |
| Universe | SPY, QQQ, IWM, TLT, GLD (fixed, 5 ETFs) |
| Span | 2005-01-03 → 2024-12-31, daily bars (5,033 per symbol, 25,165 rows) |
| Source | yfinance, `auto_adjust=True` (total-return: dividends + splits) |
| sha256 | `b7d6ec8ad2a6b80360057ed14e1fed0233c48b6b7f6d530a0bd3151205184745` |
| Quality | Repo validators passed: 0 missing values, 0 duplicates, 0 invalid OHLC rows, 0 zero-volume rows, 0 gaps, 0 spikes ([data_quality_report.json](real_data_evidence/data_quality_report.json)) |
| Sanity | Extremes match known history: SPY +14.52% (2008-10-13), SPY −10.94% (2020-03-16), GLD −8.78% (2013-04-15). CAGRs 2005–2024: SPY +10.3%, QQQ +14.5%, IWM +7.9%, GLD +9.0%, TLT +3.1% |

Session egress policy blocks market-data hosts, so the panel was downloaded by
the repository owner and delivered by file upload. The raw CSV is **not**
committed (`data/real_input/` is gitignored); every run binds to the sha256
above ([dataset_manifest.json](real_data_evidence/dataset_manifest.json)).

## 2. Protocol

- **Strategies:** the 5 registry baselines, parameters **verbatim** from their
  committed synthetic configs — no parameter search on the main runs.
- **Costs:** the repo's conservative default profile — 5 bps commission,
  5 bps slippage, 2 bps spread per side (not the lighter 2/1 synthetic values).
- **Split:** chronological 70/30 with `embargo_bars` = each signal's longest
  lookback (63/63/50/60/63). Test window ≈ 2019-03 → 2024-12 (~69 months OOS).
- **Walk-forward:** for the three strategies with single-split test Sharpe
  ≥ 0.5, rolling validation (train 756 / embargo ≥ max grid lookback / test
  252 / step 252, 16 windows ≈ 2008 → 2024) with a small textbook grid
  selected on train only per window.
- **Ledger:** one shared append-only `trial_ledger.jsonl`, never reset:
  5 research runs + 48 walk-forward windows + 5 single-asset diagnostics =
  **58 recorded trials** feeding the deflated Sharpe.
- **Gate:** `configs/selection/conservative_daily.yaml`, unmodified.

## 3. Main results — out-of-sample, net of costs (2019-03/04 → 2024-12)

Benchmark = equal-weight of the same universe, same costs.

| Strategy | OOS return | Benchmark | Excess | Sharpe | PSR | Max DD | Turnover (total) | Trades | Train Sharpe |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| time_series_momentum | +52.7% | +83.8% | **−31.1%** | 0.76 | 0.964 | −15.1% | 23.9 | 259 | 0.70 |
| volatility_scaled_momentum | +52.1% | +83.8% | **−31.8%** | 0.81 | 0.972 | −13.7% | 23.5 | 259 | 0.69 |
| moving_average_trend_filter | +35.1% | +85.9% | **−50.9%** | 0.53 | 0.896 | −25.6% | 32.3 | 276 | 0.52 |
| cross_sectional_momentum | +22.0% | +83.8% | **−61.9%** | 0.46 | 0.865 | −20.4% | 26.9 | 188 | 0.75 |
| simple_mean_reversion_etf | +8.4% | +83.9% | **−75.5%** | 0.37 | 0.811 | −9.6% | 49.7 | 215 | 0.06 |

Full artifacts per run in [real_data_evidence/runs/](real_data_evidence/runs/).

### Gate outcome per strategy (final selection, 58-trial ledger)

`✅` = passes that gate, `❌` = fails it.

| Gate (threshold) | tsmom | vol_mom | ma_trend | xs_mom | mean_rev |
| --- | :-: | :-: | :-: | :-: | :-: |
| Test Sharpe ≥ 0.5 | ✅ 0.76 | ✅ 0.81 | ✅ 0.53 | ❌ 0.46 | ❌ 0.37 |
| Beats benchmark (excess > 0) | ❌ −31.1% | ❌ −31.8% | ❌ −50.9% | ❌ −61.9% | ❌ −75.5% |
| Max DD ≤ 20% | ✅ 15.1% | ✅ 13.7% | ❌ 25.6% | ❌ 20.4% | ✅ 9.6% |
| Turnover ≤ 3.0 | ❌ 23.9 | ❌ 23.5 | ❌ 32.3 | ❌ 26.9 | ❌ 49.7 |
| Train/test Sharpe gap ≤ 1.0 | ✅ | ✅ | ✅ | ✅ | ✅ |
| OOS months ≥ 12 | ✅ ~69 | ✅ ~69 | ✅ ~69 | ✅ ~69 | ✅ ~69 |
| Cost sensitivity (profitable at high cost) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Trades ≥ 30 | ✅ 259 | ✅ 259 | ✅ 276 | ✅ 188 | ✅ 215 |
| PSR ≥ 0.90 | ✅ 0.964 | ✅ 0.972 | ❌ 0.896 | ❌ 0.865 | ❌ 0.811 |
| **Deflated Sharpe ≥ 0.5** | ❌ 0.004 | ❌ 0.006 | ❌ 0.001 | ❌ 0.000 | ❌ 0.000 |
| **Selected** | **NO** | **NO** | **NO** | **NO** | **NO** |

Selection artifacts: [real_data_evidence/selection/](real_data_evidence/selection/).

**Reading the deflated Sharpe.** With 58 recorded trials and the observed
cross-trial Sharpe variance (0.0026 per-period), the expected best Sharpe of
that many *unskilled* trials is ≈ 0.119 per period ≈ **1.9 annualized**. The
best observed OOS Sharpe (0.81) sits far below that bar, so the DSR — the
probability the true Sharpe beats the luck-of-the-best threshold — is ~0 for
every strategy. Point estimates of 0.7–0.8 after this much search are
consistent with noise.

**Note on the turnover gate.** The criteria compare *total* test-window
turnover against 3.0; over a 5.75-year test window that is ≈ 0.52×/year —
much stricter than on the short synthetic windows the config was written for.
The conclusion does not depend on it: these baselines turn over ~4–9×/year, so
they fail under an annualized reading too, and each already fails
benchmark-relative and deflated-Sharpe gates independently.

## 4. Walk-forward (16 rolling OOS windows, ≈2008 → 2024)

| Strategy | OOS Sharpe (stitched) | PSR | Positive windows | Windows beating equal-weight | Compounded OOS vs EW |
| --- | ---: | ---: | ---: | ---: | ---: |
| wf_ma_trend | 0.82 | 0.999 | 13/16 | 5/16 | +239% vs +467% (**−228 pts**) |
| wf_vol_momentum | 0.54 | 0.983 | 13/16 | 3/16 | +114% vs +362% (**−248 pts**) |
| wf_tsmom | 0.46 | 0.965 | 13/16 | 3/16 | +100% vs +362% (**−262 pts**) |

Artifacts: [real_data_evidence/walk_forward/](real_data_evidence/walk_forward/)
and [wf_benchmark_comparison.json](real_data_evidence/wf_benchmark_comparison.json).

The walk-forward confirms the single-split story over a much longer OOS span
that includes 2008, 2011, 2020 and 2022: absolute returns are positive and
PSR-vs-zero is high (these strategies do make money in absolute terms after
costs), but they **surrender 228–262 points of compounded return to a
do-nothing equal-weight portfolio** and beat it in at most 5 of 16 years.
De-risking into cash during drawdowns costs these long-only baselines far more
in missed recoveries than it saves in avoided losses, and turnover costs
compound the gap. PSR here measures Sharpe > 0, not skill vs. benchmark, and
the walk-forward aggregates are not gated by selection — they are supporting
evidence only.

## 5. sma_crossover — separate single-asset diagnostic (not gate-comparable)

The legacy single-asset path emits no `results.json`/PSR and its engine caps
any position at 25% of equity with 10%-of-equity buys (`RiskManager`
defaults), so absolute returns are not comparable with the multi-asset lab and
this strategy cannot be scored by the selection gate. Both the strategy and
its buy-and-hold benchmark run under identical sizing, so the *relative*
result is meaningful. Sample-config params (fast 3 / slow 8), costs 5/5/2 bps,
embargo 8, same 70/30 split:

| Symbol | OOS Sharpe | OOS return | Buy-and-hold (same engine) | Alpha | Trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| SPY | 0.26 | +1.8% | +15.0% | −13.1% | 100 |
| QQQ | 0.24 | +2.2% | +23.2% | −21.0% | 106 |
| IWM | −0.34 | −3.4% | +6.7% | −10.1% | 102 |
| TLT | −0.29 | −2.0% | −1.6% | −0.4% | 111 |
| GLD | 0.05 | +0.3% | +9.8% | −9.5% | 105 |

Negative alpha versus same-engine buy-and-hold on **all five symbols**; ~100
round trips each paying costs. A 3/8-day SMA crossover on daily ETF bars is
whipsaw that transfers equity to costs. Verdict: no edge, consistent with the
multi-asset result. Artifacts:
[sma_crossover_diagnostic.json](real_data_evidence/sma_crossover_diagnostic.json)
and [real_data_evidence/sma_crossover/](real_data_evidence/sma_crossover/).

## 6. Honest limitations

- **One universe, one asset class.** Five liquid US-listed ETFs chosen with
  hindsight of their liquidity and longevity. A different universe (futures,
  broader cross-section, crypto) could behave differently — this verdict
  covers *these baselines on this universe*.
- **Benchmark regime.** 2019–2024 (and 2008–2024 for walk-forward) was
  exceptionally kind to diversified buy-and-hold. That is precisely the bar a
  long-only strategy must clear to be worth trading, but it means "no edge vs
  equal-weight" is partly a statement about the era.
- **Ledger accounting.** The multi-asset walk-forward appends one ledger entry
  per window (the selected combo) and records `trials_in_window=3` as
  metadata; counting every combo would raise N from 58 to ~154 and push the
  deflated Sharpe even lower. The reported DSR ≈ 0 is therefore the *generous*
  reading.
- **Simplified fills.** Next-open execution with flat bps costs; no borrowing,
  shorting, intraday, or market impact. Real trading would be worse, not
  better, for high-turnover baselines.

## 7. Bottom line

- **Binary answer: none of the six baselines shows evidence of edge on real
  data.** All five gated strategies were rejected by
  `conservative_daily.yaml`; sma_crossover fails its own diagnostic.
- The strongest signals in absolute terms (volatility-scaled and plain
  time-series momentum: OOS Sharpe 0.76–0.81, PSR > 0.96; ma_trend walk-forward
  Sharpe 0.82 over 16 years) still (a) lose to equal-weight in ~80% of
  walk-forward years, and (b) have deflated Sharpe ≈ 0 after the recorded
  search. They are absolute-return survivors, not alpha.
- **Nothing here is a paper-trial candidate.** If this line of research
  continues, the honest next question is not "which baseline to tune" but
  whether any *cheap-to-hold* (low-turnover, benchmark-aware) variant can
  clear an equal-weight bar — a new research question, out of scope for this
  validation.

*Generated from committed artifacts under `docs/real_data_evidence/`; every
run is reproducible from its config + the dataset with sha256
`b7d6ec8a…5184745`. Research/backtesting only; not investment advice; no live
trading.*
