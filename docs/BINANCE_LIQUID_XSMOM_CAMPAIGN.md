# Binance liquid cross-sectional momentum campaign

Status: **DECLARATION BLOCKED — INSUFFICIENT EVIDENCE — RESEARCH ONLY**

`binance_liquid_xsmom_30d_top20_weekly_v1` is a new, isolated one-trial
campaign. It does not alter H1-H4 or the retired monthly and weekly momentum
campaigns, and it is not registered in a runner, CLI, strategy registry,
broker adapter, or live route. A separate development-only evaluator now
checks the offline contract, but its real-data path fails closed before
opening market JSONL while these declaration blockers remain.

The canonical declaration is
`configs/experiments/binance_liquid_xsmom_30d_top20_weekly_v1.yaml`, sealed as:

```text
906e9dd5a0bd449dbc344921aea033456976132a3487a88f8b8fe1ce85010fdf
```

The rule and seal first exist in an uncommitted working tree. A content seal
detects edits but is not an independent preregistration timestamp. No
development or holdout window is active, and no economic result may be
calculated from this declaration until the data blockers below are resolved
and the declaration has independent provenance.

## Why this is a distinct trial

The two previous campaigns were time-series rules: each asset's own past
return determined its exposure. This trial is cross-sectional: it ranks one
causally observable cohort against itself. Published crypto factor research
contains both positive momentum findings and substantial sensitivity to
sample, liquidity, microcaps, costs, and implementation. The declaration
therefore records the evidence as **mixed** and explicitly says this research
rule is not an exact replication of any paper.

That distinction does not reset the history of failed searches. The campaign
ledger preserves both earlier `NO_GO` strategy IDs. With only this one new
trial, PBO is not identifiable and the maximum possible verdict remains
`INSUFFICIENT_EVIDENCE`.

## Exact causal decision

At Thursday `00:00 UTC`, only fully closed daily bars that started Wednesday
`00:00 UTC` or earlier may be read. For every instrument, the signal requires
31 exact, gapless daily closes from `t-30` through `t`, where `t` is the latest
Wednesday bar:

```text
momentum = close(t) / close(t - 30 calendar days) - 1
liquidity window = venue_turnover_usd(t - 29) ... venue_turnover_usd(t)
```

An instrument passes the liquidity floor only when quote turnover is at least
US$5 million on at least 15 of those exact 30 days. The score used to construct
the parent cohort is the median turnover in that window.

The latest point-in-time row must also establish all of the following by the
decision timestamp:

- identity `CMC:<cmc_id>`, exact `venue=Binance`, `market=Spot`, a causally
  bound and unique Binance USDT symbol, and `data_status=VALID` on all 31 bars;
- market capitalization inside US$10M–US$1B, inclusive;
- `eligible_to_open=true` and `tradable=true`;
- stablecoin, wrapped, leveraged, derivative and rebase flags are actual
  booleans and all false;
- universe facts, classification interval/publication time, and symbol rules
  were publicly known by Thursday `00:00 UTC`;
- the US$9.50 research leg passes the observed symbol's preliminary
  minimum-notional screen.

Missing, null, string-like or future-known booleans/facts fail closed. A
snapshot's effective date is never substituted for its public availability
time.

Eligible names are sorted by median liquidity descending, then numeric
`cmc_id` ascending. Exactly the first 100 form the parent cohort. Fewer than
100 produces no signal. Inside that frozen cohort:

- candidate: momentum descending, numeric `cmc_id` ascending, first 20;
- control: liquidity descending, numeric `cmc_id` ascending, first 20.

Both portfolios carry the same canonical cohort, score and target-set digests.
Those digests bind the schema, decision timestamp, strategy seal, stable IDs,
venue symbols, liquidity and momentum scores, selections and weights. Each
selected asset has a 4.75% target, for 95% gross exposure and 5% cash reserved
for costs. If any selected candidate or control leg fails the US$9.50
minimum-notional precheck, the paired decision is rejected. Asset 21 is never
substituted and weights are never redistributed.

Passing that precheck does **not** establish executability. Tick size, step
size, minimum and maximum quantity, all applicable notional filters, Friday
price, rounding, fee and available balance remain unverified. Every target is
therefore stamped `PENDING_EXECUTION_VALIDATION`. The development evaluator
can exercise those outcomes only on explicitly synthetic contract fixtures;
it cannot turn them into economic evidence.

## Timing and benchmarks

Thursday's output is an intention, not an order. Its sole permissible
execution instant is Friday `00:00 UTC` open. If that exact bar is absent, the
intention expires at that instant: there is no Saturday retry or “next observed
bar” fallback. The development evaluator enforces this timing, filters and
cost accounting in synthetic mode; the real path remains blocked before data
loading, so the declaration still does not pretend that an intention was
executed in the market.

Any future activated evaluation must compare identical dates, costs and
execution rules against:

1. the top-20 liquidity control from the exact same top-100 cohort;
2. BTC/USDT buy-and-hold at 95% plus 5% cash for like-for-like exposure;
3. full BTC/USDT buy-and-hold because the project-wide gate requires it.

The control changes only the ranking score. It cannot use a different cohort,
availability timestamp, fill rule, or fee model.

## Blocking evidence

This is deliberately not ready to backtest or trade:

- the existing 893-coin panel is marked `INVALID_LOOKAHEAD`;
- its point-in-time stablecoin classification remains `UNKNOWN`;
- the panel does not yet provide the required public-known-at classification
  facts and historical Binance symbol rules;
- the sealed preliminary screen names Binance `minNotional` as USD even though
  the venue rule is denominated in USDT; no economic evaluation may activate
  until a superseding declaration binds point-in-time USDT/USD evidence (or a
  separately reviewed par policy) and preserves this v1 declaration unchanged;
- Binance Gate 0 has not been approved;
- account- and symbol-specific fees, spread and impact are not bound;
- weekly rebalancing conflicts with the project's current annual-frequency
  economic cost evidence;
- one trial cannot identify PBO;
- no independent preregistration timestamp exists before a reviewed commit.

Consequently the code can only return research targets or `NO_SIGNAL`.
`real_money_authorized` is always false. No result from this campaign can
authorize depositing or trading US$200.

The public immutable output objects repeat the same fail-closed contract:
timestamps must be timezone-aware UTC, cohort scores must remain in their
liquidity/numeric-ID order, both selected sets must retain a passing
minimum-notional precheck, and an invalid classification interval end cannot
masquerade as an intentionally open-ended null.

## Acceptance tests

Offline tests cover the immutable seal, tampering, Thursday boundary, exact
31/30-day windows, 14-versus-15 liquidity threshold, gaps, fewer than 100
eligible names, numeric `CMC:2` versus `CMC:10` ties, strict classification
booleans, future-known facts, prefix invariance to future Thursday data,
identical cohort digests, US$9.50 minimum-notional rejection, 95% gross
weights, exact Friday expiry, and disabled live/registry/network paths.
