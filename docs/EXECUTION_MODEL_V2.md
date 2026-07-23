# Bar execution model V2

This phase replaces the paper simulator's unconditional full fill with a
deterministic, auditable order lifecycle. It remains simulation-only and does
not add a broker endpoint.

## Causal timing

A target formed from bar `t` data is never actionable before bar `t+1`.
`additional_latency_bars` is added after that mandatory delay. A value of one
therefore makes the earliest fill `t+2`; it cannot pull execution backward.

## Order lifecycle

Orders move through explicit states:

```text
submitted -> deferred -> partially_filled -> filled
                  |              |
                  +-> expired <--+
                  +-> cancelled / rejected
```

Every fill records its order ID, sequence, bar, quantity, adverse fill price,
bar-volume participation, price impact, and transaction cost. Remainders stay
in `open_orders` until filled, expired, cancelled by a newer target, or
cancelled when the session ends. This state is serialized for audit and resume
workflows.

## Liquidity and price

When `max_volume_participation_rate` is configured:

```text
maximum fill quantity = bar volume * participation cap
```

The fill is rounded down to `lot_size`. Missing volume, zero executable
liquidity, or a missing open defers the order until `max_order_age_bars` and
then expires it. The default policy leaves participation unlimited to preserve
the existing regression; research intended to approximate deployability should
set an explicit conservative cap.

Price impact is linear and adverse:

```text
impact bps = configured full-participation impact * actual participation
buy fill  = open * (1 + impact bps / 10,000)
sell fill = open * (1 - impact bps / 10,000)
```

This impact is separate from the existing commission, spread, and slippage cost
model. Calibration must use paper fill evidence and must not be tuned merely to
make a strategy pass.

## Cash and risk invariants

Sells are attempted before buys. A proposed buy fill is rejected if price
impact and costs would breach the minimum cash reserve. Partial fills update
cash, positions, realized PnL, fill counts, and average execution price using
only information from the current eligible bar.

Reports now include quantity fill rate, partial/expired/cancelled order counts,
average participation, and average impact. These metrics flow into the existing
trial evidence process; they do not authorize live trading.

## Backtest and paper convergence

The multi-asset research backtester and simulated paper runner now use
`BarExecutionPolicy` and `BarOrderState`. Research YAML may include the same
latency, volume-participation, lot, age, and impact fields. Cost sensitivity
and walk-forward windows inherit that policy instead of silently reverting to
unlimited fills.

The backtest writes `order_events_train.csv` and `order_events_test.csv`, while
`results.json` includes a separate execution summary. Order-state diagnostics
are not mixed into return metrics, preserving metric contracts and golden
regression checks.

Default policy still preserves the earlier next-open/full-fill behavior so
existing experiments remain reproducible. This compatibility default is not a
claim that unlimited liquidity is realistic. Promotion-grade experiments
should use a conservative policy calibrated from paper evidence and compare
both the compatibility and constrained cases.

Promotion now fails closed when `results.json` lacks execution evidence, when
OOS quantity fill rate is below the configured minimum (90% by default), or
when partial/expired/cancelled order rate exceeds the configured maximum (10%
by default). These thresholds can be made stricter in the risk policy, but
must not be weakened merely to pass a candidate.

The two engines share execution semantics but retain separate portfolio
accounting implementations. Cross-engine replay parity and explicit exchange
calendar/session rules remain required before any real-money consideration.
Live trading remains `NO-GO`.


