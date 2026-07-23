# Mining economics conventions

All calculations use daily USD values unless a field says otherwise. They are
deterministic projections from supplied assumptions, not forecasts.

## Snapshot provenance and freshness

Market/network inputs are point-in-time evidence. The default policy rejects
manual, illustrative, replacement, unknown, or placeholder sources; missing
or invalid UTC capture times; observations older than 24 hours; and timestamps
too far in the future. These checks are configurable but should not be relaxed
to obtain a `GO`.

Reports bind the complete market snapshot with a SHA-256 fingerprint and
record its source, capture time, age, and evaluation time. Use CLI
`--as-of-utc` for reproducible historical evaluation. See
`docs/VALIDATION_EVIDENCE_V3.md`.

## Production and revenue

Expected daily coin is the rig's share of network hash rate multiplied by block
reward, blocks per day, and uptime. Realized coin applies
`1 - stale_reject_rate`. Gross revenue is realized coin times coin price; pool
fees are deducted from gross revenue.

Energy uses:

```text
kWh/day = power_kW * 24 * uptime * PUE
```

Set `electricity_included: true` only when an infrastructure hourly price
already includes electricity. That prevents double charging AWS/cloud
electricity. Monthly demand charge is normalized over 30 days.

Installed CAPEX is hardware plus shipping, import, and installation.
Straight-line depreciation uses installed CAPEX less residual value over useful
life. Depreciation affects accounting profit but is added back to daily cash
profit.

Tax is a configurable simplified rate applied only to positive accounting
profit. It is not tax advice and does not model loss carryforwards,
jurisdictional rules, VAT, or accelerated depreciation.

## Decision metrics

- `net_profit_usd`: after pool, facility, maintenance, depreciation, and the
  configured simplified tax.
- `net_cash_profit_usd`: net profit plus non-cash depreciation.
- `break_even_coin_price_usd`: coin price that covers full economic cost,
  including depreciation, after the configured pool fee.
- `break_even_hashprice_usd_per_th_day`: required gross hashprice adjusted for
  uptime, rejected shares, and pool fee.
- `production_cost_usd_per_coin`: current full cost divided by realized coin.
- `npv_usd`: installed CAPEX at time zero plus a level daily after-tax cash
  projection and terminal residual value over `analysis_horizon_days`.
- `irr_annual_rate`: annualized discount rate that makes that same projection's
  NPV zero. It is `null` when no economically meaningful root exists.
- `payback_days` and annualized ROI use cash profit, not accounting profit.

NPV and IRR intentionally assume level cash flow; scenarios expose sensitivity
instead of pretending a precise path is known. A positive NPV does not make a
project safe or profitable in reality.

## Scenario matrix

The built-in scenarios change explicit multipliers only: price, network
hashrate, uptime, electricity, cloud hourly cost, and temperature. The extreme
scenario combines all downside multipliers. Scenario values are policy inputs,
not estimated probabilities, and are kept fixed so regression tests remain
reproducible.

The dated S21 XP example uses only hardware characteristics from Bitmain's
[S21 XP specification](https://support.bitmain.com/hc/en-us/articles/35383015643673-S21-XP-Specifications).
Its market, tariff, CAPEX, and FX values are clearly labelled illustrative and
must not be treated as current evidence.

