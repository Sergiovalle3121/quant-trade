# Cash-and-Carry / Funding — Pre-Registration

Registered **before** looking at any real results, so the analysis cannot be
tuned to a favourable outcome. Research-only: no orders, no live venues, no
funds movement. Wallets (if ever used) are watch-only.

## Hypothesis

A delta-neutral two-leg position — **long spot, short perpetual** of the same
underlying — earns positive net carry from perpetual funding when funding is
persistently positive, after *all* frictions. This is **not** risk-free
arbitrage: it carries funding-reversion, basis, liquidation, exchange, and
execution risk, each gated explicitly.

## Causality

The position at time `t` is decided only from funding **realized and published
at or before `t`** (a trailing mean of `realized_funding_rate`). The schema
keeps `predicted_funding_rate` as a separate, clearly labelled field that is
never sourced from future realized funding and never feeds the decision.

## Decision rule

Enter the carry when the trailing-mean realized funding exceeds
`entry_threshold`; otherwise hold flat. Each interval earns the next interval's
realized funding minus a per-turn transaction cost (half a round trip) and a
per-interval carrying cost.

## Cost stack (all subtracted before any GO)

Taker fees + half-spread + slippage + market impact on each of the four fills of
a round trip; conversion/withdrawal fees (amortized); annual spot custody, perp
margin, and borrow costs. Expected carry additionally applies a
`funding_reversion_haircut` to positive carry and never assumes an adverse carry
reverts in our favour.

## Pre-registered parameter matrix (small on purpose)

| Parameter | Values |
| --- | --- |
| `symbol` | BTC, ETH |
| `entry_threshold` (per 8h) | 0.00005, 0.0001 |
| `trailing_window` (intervals) | 3, 6 |

Eight combinations per venue. No large grids — the trial ledger records every
combination (evaluated / discarded / failed) so the deflated Sharpe accounts for
the full breadth.

## Risk gates (fail closed)

Min net annualized carry; min carry after 2× and 3× costs; max |basis|; min
liquidation distance and max liquidation-probability proxy; max exchange
exposure; max unhedged notional/duration; funding sign flip; stale data;
simulated exchange-outage, depeg, withdrawal-freeze, and extreme-spread
scenarios; and a fill-rate gate. The two-leg execution state machine enforces a
maximum unhedged notional, a timeout, bounded retries, and a simulated emergency
unwind, and reconciles notional and delta.

## Verdict policy

- **Synthetic data ⇒ `NOT-RUN — REAL DATA REQUIRED`, always.** A synthetic
  campaign can never emit GO regardless of paper numbers.
- **Real data ⇒ GO** only if net carry is positive, the block-bootstrap lower
  bound on total return is positive, and the per-snapshot economic gate passes;
  otherwise **NO-GO**.
- A GO here means "worth a supervised paper trial", never real money.

## How to import real data (public, read-only, no keys)

```bash
python -c "from quant_trade.carry.data import load_real_adapter, write_snapshots_json; \
  a = load_real_adapter({'exchange': 'binanceusdm'}); \
  write_snapshots_json('data/carry/btc_real_snapshots.json', \
    a.fetch_snapshots('BTC','binanceusdm'))"
# then:
python -c "import yaml; from quant_trade.carry.research import run_carry_research, write_carry_artifacts; \
  cfg = yaml.safe_load(open('configs/carry/cash_and_carry_real_template.yaml')); \
  r = run_carry_research(cfg); write_carry_artifacts('outputs/carry_real', cfg, r); print(r.decision)"
```

The adapter uses only public market-data endpoints (tickers, funding rate) with
a timeout, bounded retries, staleness accounting, and attribution.
