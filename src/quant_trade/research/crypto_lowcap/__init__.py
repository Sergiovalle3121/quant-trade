"""The crypto low/mid-cap campaign: run what was sealed, reveal once, report.

`quant_trade.research.signals.crypto_lowcap` holds the hypotheses and
`quant_trade.research.crypto_evaluator` prices them, but nothing before this
package ran them. It is the driver: a declared trial grid that is locked on
first use, a selection-window campaign that never reads a holdout date, a
hash-chained ledger that counts every trial against its pre-registered budget,
a freeze of at most one primary candidate, and a holdout reveal that can happen
exactly once. Every number it writes is labelled with its evidence class, and
the report it renders refuses profit language.
"""
