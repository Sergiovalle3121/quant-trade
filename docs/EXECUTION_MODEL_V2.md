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

## Remaining convergence work

`BarExecutionPolicy` and `BarOrderState` are shared execution-domain types, but
the multi-asset research backtester still needs to adopt their persistent
order lifecycle. Until that convergence is complete, paper results with
participation/latency controls are deliberately more conservative than the
legacy backtest. Live trading remains `NO-GO`.

