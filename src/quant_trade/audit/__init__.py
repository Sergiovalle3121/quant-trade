"""Backtest audit: a statistical second opinion on a client-supplied backtest.

Research-only. The audit reads an equity curve (and optionally trades, a
benchmark and a parameter-variant matrix) that the client uploads, and
reports whether the track record is statistically distinguishable from
noise, how much of it survives the number of trials the client declares,
how it degrades under trading costs, and whether the data itself looks
plausible. Every number carries an evidence class: MEASURED from the file,
DECLARED by the client, or NOT_MEASURED with the reason.

It is not investment advice, it executes nothing, it holds no keys and no
funds, and it never claims that money was or will be made. Nothing in this
package is imported eagerly so the core CLI keeps working without the ``web``
extra installed.
"""
