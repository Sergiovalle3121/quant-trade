# Cash-and-Carry / Funding — Results

Research-only. No orders were placed on any venue. No real funds moved.

## Real-data campaign

**`TRADING_EDGE (cash-and-carry): NOT-RUN — REAL DATA REQUIRED`**

No real funding/spot/perp history was available in this environment (outbound
exchange access is proxied and unauthenticated). The pipeline, contracts,
synthetic fixtures, validators, and a read-only import path are all in place; the
real campaign is a single command away once a versioned snapshot file exists (see
`docs/CASH_AND_CARRY_PREREGISTRATION.md`).

## Synthetic campaign (machinery exercise only — never a GO)

Config: `configs/carry/cash_and_carry_synthetic.yaml`
(180 snapshots, 8h funding, seed 7). Fixture:
`examples/data/carry/synthetic_funding_snapshots.json`.

| Metric | Value |
| --- | --- |
| Decision | **NOT-RUN** (synthetic) |
| Net total return (per-interval compounded) | −1.28% |
| Sharpe (per period) | −0.17 |
| Observations | 180 |
| Active intervals | 46 |
| Per-snapshot economic GO fraction | 0.000 |
| Block-bootstrap total-return lower bound positive | No |
| Purged walk-forward windows | 9 |

The synthetic funding process is small and mean-reverting, so even before the
provenance guard the campaign shows no carry (negative net return, zero GO
fraction). This is the intended honest outcome: **a synthetic simulation is
never presented as demonstrated profitability.**

## What real data must show for a GO

- Positive net annualized carry after the full cost stack.
- Carry that survives 2× and 3× cost stress.
- A block-bootstrap lower bound on total return above zero.
- Per-snapshot gates passing (basis, liquidation distance/probability, staleness,
  favourable funding sign).
- A stable purged walk-forward, not a single lucky window.

Even then, a GO means only "advance to a supervised paper trial". It never
authorizes real money — `REAL_MONEY: NO-GO` stands.

## Risk reminders (why this is not free money)

Funding can flip sign or revert; basis can gap; a perp leg can be liquidated in a
sharp move; an exchange can halt withdrawals or de-peg a quote asset; and both
legs can partially fill, leaving unhedged delta. The two-leg execution state
machine models the unhedged-risk window, the timeout, bounded retries, and the
simulated emergency unwind; the risk gates model the market scenarios.
