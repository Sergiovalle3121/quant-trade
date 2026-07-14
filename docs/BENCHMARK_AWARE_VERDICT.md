# Benchmark-Aware Allocations Verdict: the Open Door Is Now Closed

**Verdict: NO-GO. None of the three low-turnover, benchmark-aware allocations
improves on the equal-weight benchmark on real data. Zero of three pass the
conservative selection gate; the door left open by
[REAL_DATA_VERDICT.md](REAL_DATA_VERDICT.md) is closed.**

This phase tested the one hypothesis the baseline validation left standing:
that a cheap-to-hold, ~fully-invested allocation might beat equal-weight where
the de-risking baselines could not. Three classic candidates were defined and
parameterized **before any result was observed** (pre-registered in the
approved plan), run on the same sha256-pinned real panel, same 5/5/2 bps
costs, same split and gate, with the shared trial ledger carrying all prior
search history (58 → 109 trials, never reset).

## The three pre-registered questions, answered first

**(a) Does any candidate beat equal-weight (excess > 0)?** No. Single-split
OOS excess: inverse_volatility **−6.8%**, equal_weight_quarterly **−6.0%**,
vol_targeted_equal_weight **−37.4%**. Walk-forward compounded excess over 16
OOS years: **−12.6%**, **−90.8%**, **−150.7%** respectively. The best,
inverse_volatility, beat equal-weight in 7 of 16 walk-forward years — the
closest to benchmark parity anything in this project has come, and still a
net loser to it.

**(b) Does turnover finally clear the gate (≤ 3.0)?** Once, yes:
**equal_weight_quarterly passes with total test-window turnover 2.17** — the
only strategy in the entire project (8 gated so far) to clear that gate.
inverse_volatility (5.96) and vol_targeted_equal_weight (5.81) still fail.
Monthly rebalancing of even a slow-moving weight vector costs more turnover
than the gate tolerates.

**(c) What happened to drawdown around COVID?** All three candidates took a
COVID drawdown essentially equal to the benchmark's: −20.1% to −20.8% versus
−21.4% for equal-weight (Feb–Dec 2020 window). Volatility targeting did
**not** dodge the crash: a 63-day window rebalanced monthly reacts weeks too
late for a three-week collapse; it capped the *2022* bear instead (its max
drawdown, −20.8%, is the COVID trough, while every fully-invested portfolio's
max drawdown — including the benchmark's — is **2022-10-14**, the joint
bond/equity crash). Sobering corollary: the equal-weight benchmark itself
drew down **−25.7%**, meaning *even the strategy this project cannot beat
would itself fail the gate's ≤ 20% drawdown bar* on this era.
Full analysis: [allocation_drawdown_analysis.json](real_data_evidence/allocation_drawdown_analysis.json).

## Candidates (definitions fixed pre-hoc)

| Candidate | Definition | Fixed params |
| --- | --- | --- |
| `inverse_volatility` | w ∝ 1/σ(63d), normalized to fully invested, monthly | vol_window 63, cap 0.35 |
| `vol_targeted_equal_weight` | equal weight × min(1, 10% / realized 63d vol), monthly | target 10%, vol_window 63, cap 0.25 |
| `equal_weight_quarterly` | 0.20 each, reset first trading day of Jan/Apr/Jul/Oct | cap 0.25 |

Implemented in `src/quant_trade/research/signals/allocation.py` (causal,
truncation-invariance tested in `tests/test_allocation_signals.py`); no
engine, cost, split, or gate code was touched.

## Main results — OOS 2019-04-03 → 2024-12-31, net of 5/5/2 bps

Benchmark = daily-refreshed equal weight of the same universe, same costs
(+83.8% over the window).

| Candidate | OOS return | Excess | Sharpe | PSR | Max DD | Turnover | Trades |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| inverse_volatility | +77.0% | **−6.8%** | 0.85 | 0.978 | −24.6% | 5.96 | 340 |
| equal_weight_quarterly | +77.9% | **−6.0%** | 0.79 | 0.969 | −26.1% | **2.17** | 110 |
| vol_targeted_equal_weight | +46.4% | **−37.4%** | 0.65 | 0.937 | −20.8% | 5.81 | 340 |

### Gate outcome (conservative_daily.yaml, 109-trial ledger)

| Gate | inverse_vol | ew_quarterly | vol_target |
| --- | :-: | :-: | :-: |
| Test Sharpe ≥ 0.5 | ✅ 0.85 | ✅ 0.79 | ✅ 0.65 |
| Beats benchmark | ❌ | ❌ | ❌ |
| Max DD ≤ 20% | ❌ 24.6% | ❌ 26.1% | ❌ 20.8% |
| Turnover ≤ 3.0 | ❌ 5.96 | ✅ 2.17 | ❌ 5.81 |
| Train/test Sharpe gap ≤ 1.0 | ✅ | ✅ | ✅ |
| OOS months ≥ 12 | ✅ ~69 | ✅ ~69 | ✅ ~69 |
| Cost sensitivity | ✅ | ✅ | ✅ |
| Trades ≥ 30 | ✅ | ✅ | ✅ |
| PSR ≥ 0.90 | ✅ 0.978 | ✅ 0.969 | ✅ 0.937 |
| **Deflated Sharpe ≥ 0.5** | ❌ 0.002 | ❌ 0.001 | ❌ 0.000 |
| **Selected** | **NO** | **NO** | **NO** |

All three pass PSR — as allocations should, since they inherit the era's
market beta — but with 109 recorded trials the deflated-Sharpe bar sits at an
expected-best of ≈ **2.07 annualized** Sharpe, and nothing here approaches
it. Selection artifacts:
[selection_benchmark_aware/](real_data_evidence/selection_benchmark_aware/).

## Walk-forward (16 rolling OOS windows, ≈2008 → 2024, no parameter grid)

Params were fixed, so each window is pure rolling OOS with zero per-window
selection.

| Candidate | OOS Sharpe | PSR | Positive windows | Beat EW | Compounded vs EW |
| --- | ---: | ---: | ---: | ---: | ---: |
| inverse_volatility | 0.88 | 1.000 | 14/16 | **7/16** | +314% vs +326% (**−12.6 pts**) |
| equal_weight_quarterly | 0.72 | 0.998 | 14/16 | 5/16 | +236% vs +326% (**−90.8 pts**) |
| vol_targeted_equal_weight | 0.71 | 0.997 | 13/16 | 2/16 | +176% vs +326% (**−150.7 pts**) |

Details: [wf_benchmark_comparison_allocations.json](real_data_evidence/wf_benchmark_comparison_allocations.json).

## Measurement artifacts, disclosed

- **Quarterly boundary cash-drag.** Weights are generated on the full panel
  and sliced; the OOS window starts 2019-04-03, two days after a quarter
  start, so `equal_weight_quarterly` sits in cash for its first 62 test bars
  while the benchmark earned **+4.57%** — roughly three-quarters of its −6.0%
  single-split excess is this boundary artifact, not economics. The same
  effect recurs at each walk-forward window start (up to ~63 bars per
  252-bar window), so its WF comparison (−90.8 pts) materially *understates*
  the strategy. The direction is conservative (never inflates a candidate),
  and the friction question it was built to answer is settled by its turnover
  number (2.17 vs the benchmark's implicit daily refresh) rather than by the
  drag-contaminated excess.
- **The DD gate is unpassable for this class on this era.** The benchmark
  itself (−25.7% in 2022) violates the ≤ 20% bar. Any ~fully-invested
  allocation on this universe fails it in any window containing 2022 (or
  COVID). That gate is doing its job — flagging that these portfolios carry
  full market risk — but it means "fully invested + this universe + this
  decade" can never be selected regardless of relative skill.
- **Ledger accounting.** 109 trials = 58 prior + 3 research runs + 48
  walk-forward windows. Nothing was reset; the DSR for these candidates
  carries the entire project's search history, as pre-registered.

## Bottom line

- **Binary answer: NO.** No low-turnover, benchmark-aware allocation improves
  on equal-weight after realistic costs on this panel. The open door from the
  baseline validation is closed.
- The full ranking after two phases, by compounded 16-year walk-forward OOS:
  **equal-weight benchmark (+326%) > inverse_volatility (+314%) >
  equal_weight_quarterly (+236%) > vol_targeted (+176%) > ma_trend (+239%¹) >
  vol_momentum (+114%) > tsmom (+100%)** — the do-nothing diversified
  portfolio remains undefeated. ¹ma_trend's window dates differ (embargo
  200); not strictly comparable.
- inverse_volatility is the only strategy in the project that has ever come
  within noise distance of the benchmark (−0.5% mean excess per WF year). It
  is a risk-profile variant of equal-weight, not evidence of edge — and the
  gate correctly refuses it.
- **Nothing here is a paper-trial candidate.** Two phases of honest
  validation converge on one conclusion for this universe and era: hold the
  diversified portfolio; no tested overlay adds value after costs.

*Reproducible from the committed configs + the dataset with sha256
`b7d6ec8a…5184745`; artifacts under `docs/real_data_evidence/`.
Research/backtesting only; not investment advice; no live trading.*
