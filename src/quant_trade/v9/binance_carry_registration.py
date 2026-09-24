"""Pre-registration of H1-BIN: the H1 carry, measured on Binance's archive.

Registered before any Binance panel was built or any ledger was run. Only the
file format was inspected beforehand (the first rows of two monthly files), to
write the parser; no return, funding average or backtest statistic had been
computed.

Why a new hypothesis and not "H1 on other data": H1 names Bybit. From this
research environment Bybit's API refuses the region, and OKX's REST funding
history reaches back only about three months, well below the 730-day floor.
Binance publishes a first-party archive of settled funding and hourly klines
since 2020, with a SHA-256 checksum per file. Running H1's rules on it is a
different venue and therefore a different experiment, so it is registered
here, counted as its own trials, and never reported as H1.

Everything that could be tuned is fixed below and hashed. The strategy, its
four variants, the gates and the V8 cost stack are H1's, unchanged. The split
and selection procedure are V9's (per-window out-of-sample selection, a sealed
holdout that is decisive), because V8's walk-forward was found to be in-sample
(erratum E5).
"""

from __future__ import annotations

from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text
from quant_trade.v8.preregistration import H1, PROMOTION_GATES

REGISTERED_AT_UTC = "2026-09-24T05:57:00Z"
#: The commit this registration was written on top of (main at the time).
REGISTERED_ON_TOP_OF_COMMIT = "0f5f0ae12c6044d14951bbe99412d408a49e5961"

HYPOTHESIS_ID = "H1-BIN"
VENUE = "binance"
SYMBOL = "BTC"

#: The data window, fixed before download: every full month the archive
#: publishes for all five series, from the first month of the USD-M funding
#: archive to the last complete month before registration.
SINCE_UTC = "2020-01-01T00:00:00Z"
UNTIL_UTC = "2026-08-31T23:00:00Z"
INTERVAL_MINUTES = 60

#: H1's four variants, renamed only in their prefix.
VARIANTS: tuple[dict[str, Any], ...] = tuple(
    {
        "variant_id": v.variant_id.replace("H1-", "H1-BIN-", 1),
        "parameters": dict(v.parameters),
    }
    for v in H1.variants
)

#: V9 procedure: 50/30/20 chronological; each walk-forward window selects on
#: bars strictly before ``test_start - purge - embargo`` and is scored on its
#: own test block only. Window sizes are V8's (720/240/240, purge 6,
#: embargo 1), in hourly bars.
SPLITS: dict[str, Any] = {
    "scheme": "chronological",
    "train_fraction": 0.50,
    "walk_forward_fraction": 0.30,
    "holdout_fraction": 0.20,
    "holdout_position": "most_recent",
    "walk_forward": {
        "min_selection_rows": 720,
        "test_size": 240,
        "step_size": 240,
        "purge_bars": 6,
        "embargo_bars": 1,
    },
    "selection_score": "net total return of the variant's causal ledger on the selection view",
    "final_selection_view": "all bars before holdout_start - purge - embargo",
}

#: How a variant's returns over a slice are obtained. Each variant runs as one
#: continuous causal ledger over the whole panel (the ledger only uses data up
#: to each bar), and a window reads that ledger's per-bar returns. When the
#: walk-forward switches variant between two windows, one full round trip
#: (four fills at the stack's per-fill cost) is charged on the first bar of
#: the new window whether or not the positions differed: conservative, and
#: never in the strategy's favour.
EXECUTION: dict[str, Any] = {
    "ledger": "quant_trade.carry.ledger_engine.run_carry_ledger",
    "initial_capital": 1.0,
    "perp_leverage": 3.0,
    "collateral_yield_annual": 0.0,
    "cost_stack": "conservative_cost_stack('binance')",
    "cost_multipliers": [1.0, 2.0, 3.0],
    "variant_switch_charge": "one four-fill round trip per switch",
}

#: Gates: H1's V8 gates plus V9's holdout rules. The holdout is decisive; a
#: positive full sample never rescues a negative holdout.
GATES: dict[str, Any] = {
    **PROMOTION_GATES,
    "require_positive_holdout": True,
    "require_positive_holdout_at_2x_costs": True,
    "require_per_window_oos_selection": True,
    "require_hash_chained_trial_ledger": True,
    "holdout_benchmarks": ["cash", "buy_and_hold_btc"],
}

BENCHMARKS: dict[str, Any] = {
    "cash": {"annual_yield": 0.04, "source": "V8 CASH_ANNUAL_YIELD"},
    "buy_and_hold_btc": "Binance BTCUSDT spot close, two fills at the stack's per-fill cost",
}

FALSIFIERS: tuple[str, ...] = (
    *H1.falsifiers,
    "holdout net return <= 0",
    "holdout net return <= 0 at 2x costs",
)

TRIAL_LEDGER_PATH = "data/v9_evidence/trials.jsonl"


def registration() -> dict[str, Any]:
    return {
        "artifact": "H1_BIN_PREREGISTRATION",
        "schema_version": 1,
        "registered_at_utc": REGISTERED_AT_UTC,
        "registered_on_top_of_commit": REGISTERED_ON_TOP_OF_COMMIT,
        "hypothesis_id": HYPOTHESIS_ID,
        "derived_from": H1.hypothesis_id,
        "title": "Binance BTC spot / USD-M perpetual cash-and-carry (official archive)",
        "thesis": H1.thesis.replace(
            "BTCUSDT linear perpetual on Bybit", "BTCUSDT USD-M perpetual on Binance"
        ),
        "signal": H1.signal,
        "venue": VENUE,
        "symbol": SYMBOL,
        "data": {
            "source": "https://data.binance.vision (venue-published archive, per-file SHA-256)",
            "since_utc": SINCE_UTC,
            "until_utc": UNTIL_UTC,
            "interval_minutes": INTERVAL_MINUTES,
            "series": ["spot", "perp", "mark", "index", "funding"],
        },
        "variants": list(VARIANTS),
        "splits": SPLITS,
        "execution": EXECUTION,
        "gates": GATES,
        "benchmarks": BENCHMARKS,
        "falsifiers": list(FALSIFIERS),
        "trial_ledger": TRIAL_LEDGER_PATH,
    }


def freeze_hash() -> str:
    """SHA-256 of the registration; it rides in every H1-BIN artifact."""
    return sha256_of_text(canonical_dumps(registration()))


#: Pinned at registration. A test fails if the registration moves.
FROZEN_HASH = "19bdbd03b91fcfe2d5ad3b6e1a2c2a8bc4d91d78effc64417e7feeaf40a701d7"

__all__ = [
    "FROZEN_HASH",
    "HYPOTHESIS_ID",
    "VARIANTS",
    "freeze_hash",
    "registration",
]
