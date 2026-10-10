"""Which prop firm's challenge a daily history fits best.

A trader who is about to pay for a challenge wants to know, before paying,
under which firm's rules their own history would most often have passed,
and whether a pass would have kept inside the firm's best-day
(consistency) rule, which is behind many refused payouts. This module runs
the challenge simulator (``analytics.simulate_challenge``) once per
published preset, on the same resampled paths (same seed), and ranks them.

Only presets with a published source are compared, never the generic
reference. Every figure is MEASURED from the uploaded daily returns under
the simulator's stated assumptions; the rules are each firm's page on its
``as_of`` date. No class change, no recommendation to buy a challenge.

Each row carries the rules it was simulated with (``rules``, one entry per
phase, copied from ``prop_presets``). A program whose page names the markets
it allows (``ChallengeRules.markets``) and that does not take every symbol the
history trades (:func:`symbol_venues`) is not simulated: it goes last, with
``market`` saying what it allows and which of the history's symbols and
markets it does not take, and no figure that could be ranked against the
others. The report's chosen program is the exception: it is simulated (its
section already was) and keeps its figures, with the same ``market``.

:func:`scenario_columns` adds the ladder's out-of-sample and cost rungs to
every row, so the chosen program's figures are the ladder's own.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.analytics import simulate_challenge
from quant_trade.audit.crises import symbol_market, traded_markets
from quant_trade.audit.prop_presets import PRESETS
from quant_trade.audit.schema import measured, not_measured

#: Samples per preset; the ranking needs less precision than the chosen firm.
SAMPLES = 2000
#: When every program is at or above this, or at or below the low mark, the
#: ranking says nothing and the report says so in one sentence.
UNIFORM_HIGH = 0.99
UNIFORM_LOW = 0.01
#: Presets that stand for several identical phases in a row.
REPEATS = {"the5ers-bootcamp-step": 3}

NOTE = (
    "every published preset simulated on the same resampled daily paths, rules as each "
    "firm's page stated them on its as_of date; a program's phases are taken as fresh "
    "starts, so the chance of passing them all is the product of each phase's"
)

_FAILS = ("fail_daily_loss", "fail_total_loss", "unfinished")
#: How a program ends, phase by phase, for :func:`program_outcomes`.
OUTCOME_NOTE = (
    "share of the resampled paths that end the program this way: each phase is a fresh "
    "start reached only by passing the phases before it"
)


#: The rule fields each row repeats from ``prop_presets``, phase by phase.
RULE_FIELDS = (
    "phase",
    "profit_target",
    "max_daily_loss",
    "daily_loss_basis",
    "max_total_loss",
    "total_loss_type",
    "min_trading_days",
    "time_limit_days",
    "best_day_limit",
    "best_day_basis",
)
#: The program markets (``prop_presets.MARKETS``) that can carry a symbol of
#: each market ``crises.symbol_market`` names. A pair against a currency, such
#: as ``EURUSD``, ``XAUUSD`` or ``BTCUSD`` (:data:`COIN_PAIRS`), is spot or CFD,
#: never an exchange future (those are ``6E``, ``GC`` or ``MBT``); an index
#: name, a bare coin root or a perpetual can be either (``NQ`` is the future,
#: ``BTC`` a root of both), so it fits futures too.
SYMBOL_MARKETS: dict[str, frozenset[str]] = {
    "fx": frozenset({"fx"}),
    "metal": frozenset({"metals"}),
    "us_equity": frozenset({"indices", "futures"}),
    "crypto": frozenset({"crypto", "futures"}),
}
#: A coin written against a currency or a stablecoin is a pair, spot or CFD,
#: like gold's ``XAUUSD``: ``BTCUSD``, ``BTCUSDT``, ``XBTUSD`` (not a perpetual).
COIN_PAIRS = ("BTCUSD", "XBTUSD")
#: How many of the symbols a program does not take its ``market`` names.
MARKET_SYMBOLS = 4
#: The ladder rungs the firm table repeats for every program, in its order.
SCENARIO_COLUMNS = ("out_of_sample", "reference_cost")
SCENARIO_NOTE = (
    "the ladder's rung for every program: the same series, simulator, seed and rules; the "
    "chosen program's figure is the ladder's own"
)


def history_markets(symbols: Sequence[str] | None) -> list[str] | None:
    """The markets the history's symbols trade, or ``None`` when one of them
    is not certain (or there are none): then no program is left out."""
    names = [str(name) for name in symbols or [] if name]
    found = traded_markets(names) if names else None
    return sorted(found) if found else None


def symbol_venues(name: str) -> frozenset[str] | None:
    """The program markets (``prop_presets.MARKETS``) that can carry one
    symbol, or ``None`` when its name says nothing certain."""
    market = symbol_market(name)
    if market is None:
        return None
    text = "".join(ch for ch in str(name).rsplit(":", 1)[-1].upper() if ch.isalnum())
    if market == "crypto" and text.startswith(COIN_PAIRS) and "PERP" not in text:
        return frozenset({"crypto"})
    return SYMBOL_MARKETS[market]


def market_fit(key: str, symbols: Sequence[str] | None) -> dict[str, Any] | None:
    """Why ``key``'s program does not take the history's symbols, or ``None``
    when it takes them all (or when its page or one of the symbols does not say).

    ``history`` and ``symbols`` are only what the program does not take (the
    most traded symbols first, at most :data:`MARKET_SYMBOLS`, out of
    ``symbol_count``); ``spot`` says that every one of them is a spot or CFD
    pair, never an exchange future."""
    rules = PRESETS[key]
    counts = Counter(str(name) for name in symbols or [] if name)
    if rules.markets is None or not counts:
        return None
    venues = {name: symbol_venues(name) for name in counts}
    if any(found is None for found in venues.values()):
        return None
    allowed = set(rules.markets)
    misfits = sorted(
        (name for name, found in venues.items() if not (found or frozenset()) & allowed),
        key=lambda name: (-counts[name], name),
    )
    if not misfits:
        return None
    return {
        "allowed": list(rules.markets),
        "history": sorted({str(symbol_market(name)) for name in misfits}),
        "symbols": misfits[:MARKET_SYMBOLS],
        "symbol_count": len(misfits),
        "spot": all("futures" not in (venues[name] or frozenset()) for name in misfits),
        "source_url": rules.markets_source,
        "as_of": rules.markets_as_of,
    }


def markets_of(key: str) -> dict[str, Any] | None:
    """What ``key``'s program lets the trader trade, its page and reading
    date, or ``None`` when no page read says."""
    rules = PRESETS[key]
    if rules.markets is None:
        return None
    return {
        "allowed": list(rules.markets),
        "source_url": rules.markets_source,
        "as_of": rules.markets_as_of,
    }


def rules_of(keys: Sequence[str]) -> list[dict[str, Any]]:
    """The simulated rules of each phase, as ``prop_presets`` states them."""
    out: list[dict[str, Any]] = []
    for key in keys:
        rules = PRESETS[key].to_dict()
        out.append({field: rules[field] for field in RULE_FIELDS})
    return out


def _main_risk(probability: dict[str, Any]) -> str:
    """The failure that ends most paths, or "none" when no path fails."""
    worst = max(_FAILS, key=lambda k: float(probability[k]["value"]))
    return worst if float(probability[worst]["value"]) > 0 else "none"


def _payable(row: dict[str, Any]) -> float:
    """The figure that matters for getting paid: within the best-day rule when
    the firm has one."""
    return float((row.get("pass_within_best_day") or row["pass"])["value"])


def _program(results: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """One program: its phases' pass chances multiplied, the weakest phase's risk."""
    rules = results[0][1]["rules"]
    passing = clean = 1.0
    with_rule = False
    weakest: dict[str, Any] | None = None
    for key, result in results:
        probability = result["probability"]
        repeats = REPEATS.get(key, 1)
        phase_pass = float(probability["pass"]["value"])
        passing *= phase_pass**repeats
        best_day = result.get("best_day")
        if best_day:
            with_rule = True
            clean *= float(best_day["pass_within"]["value"]) ** repeats
        else:
            clean *= phase_pass**repeats
        if weakest is None or phase_pass < float(weakest["pass"]["value"]):
            weakest = probability
    assert weakest is not None
    keys = [key for key, _ in results]
    row: dict[str, Any] = {
        "keys": keys,
        "firm": rules["firm"],
        "program": rules["program"],
        "phases": sum(REPEATS.get(key, 1) for key, _ in results),
        "source_url": rules["source_url"],
        "as_of": rules["as_of"],
        "pass": measured(passing, NOTE),
        "main_risk": _main_risk(weakest),
        "rules": rules_of(keys),
    }
    if with_rule:
        row["pass_within_best_day"] = measured(clean, NOTE)
    markets = markets_of(keys[0])
    if markets is not None:
        row["markets"] = markets
    return row


def _left_out(keys: list[str], market: dict[str, Any]) -> dict[str, Any]:
    """A program that does not take the history's markets: its rules, no figure."""
    rules = PRESETS[keys[0]]
    return {
        "keys": keys,
        "firm": rules.firm,
        "program": rules.program,
        "phases": sum(REPEATS.get(key, 1) for key in keys),
        "source_url": rules.source_url,
        "as_of": rules.as_of,
        "rules": rules_of(keys),
        "markets": markets_of(keys[0]),
        "market": market,
    }


def program_keys(key: str) -> list[str]:
    """The presets of ``key``'s program (same firm and program), in ``PRESETS`` order.

    The generic reference has no siblings, so it returns only itself."""
    rules = PRESETS[key]
    return [
        k
        for k, other in PRESETS.items()
        if (other.firm, other.program) == (rules.firm, rules.program)
    ]


def _phase_results(
    daily_returns: pd.Series | np.ndarray | Sequence[float],
    key: str,
    *,
    samples: int,
    seed: int,
    known: dict[str, dict[str, Any]] | None,
) -> tuple[list[tuple[str, dict[str, Any]]], str | None]:
    """Each phase of ``key``'s program simulated, or why one could not be."""
    results: list[tuple[str, dict[str, Any]]] = []
    for phase in program_keys(key):
        result = (known or {}).get(phase) or simulate_challenge(
            daily_returns,
            PRESETS[phase],
            samples=samples if phase == key else min(samples, SAMPLES),
            seed=seed,
        )
        if not result.get("method"):
            return [], str(result["probability"]["pass"].get("note", "not measured"))
        results.append((phase, result))
    return results, None


def _outcomes(results: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """The share of paths each failure ends the whole program with.

    A phase is reached only by passing the ones before it (fresh starts, as
    the pass chance takes them), so its failures count in proportion to the
    chance of getting there; with the program's pass chance they sum to one."""
    reach = 1.0
    shares = dict.fromkeys(_FAILS, 0.0)
    for key, result in results:
        probability = result["probability"]
        for _ in range(REPEATS.get(key, 1)):
            for fail in _FAILS:
                shares[fail] += reach * float(probability[fail]["value"])
            reach *= float(probability["pass"]["value"])
    return {fail: measured(share, OUTCOME_NOTE) for fail, share in shares.items()}


def program_pass(
    daily_returns: pd.Series | np.ndarray | Sequence[float],
    key: str,
    *,
    samples: int,
    seed: int,
    known: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Every phase of ``key``'s program on one history, as one row of :func:`firm_fit`.

    ``key`` is simulated with ``samples`` paths and its sibling phases with
    ``min(samples, SAMPLES)``, as :func:`firm_fit` does next to a chosen firm,
    so with ``known={key: result}`` the row is the same as that program's row
    in the firm table."""
    results, reason = _phase_results(daily_returns, key, samples=samples, seed=seed, known=known)
    if reason is not None:
        return {"status": "NOT_MEASURED", "reason": reason}
    return {"status": "MEASURED", **_program(results)}


def program_outcomes(
    daily_returns: pd.Series | np.ndarray | Sequence[float],
    key: str,
    *,
    samples: int,
    seed: int,
    known: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """:func:`program_pass` plus how the program ends when it is not passed.

    The row is :func:`program_pass`'s, unchanged, with ``fail_daily_loss``,
    ``fail_total_loss`` and ``unfinished`` over every phase (see
    :func:`_outcomes`); with ``pass`` they sum to one."""
    results, reason = _phase_results(daily_returns, key, samples=samples, seed=seed, known=known)
    if reason is not None:
        return {"status": "NOT_MEASURED", "reason": reason}
    return {"status": "MEASURED", **_program(results), **_outcomes(results)}


def firm_fit(
    daily_returns: pd.Series | np.ndarray | Sequence[float],
    *,
    samples: int = SAMPLES,
    seed: int = 0,
    known: dict[str, dict[str, Any]] | None = None,
    symbols: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Every published program on the same paths, best pass odds first.

    ``known`` maps a preset key to a result already simulated on the same
    history and seed (the report's chosen firm), so that firm's row shows the
    same figure as its own section. With ``symbols`` (the history's), a
    program that does not take them is not simulated and is listed last
    (:func:`market_fit`), except the program of a ``known`` preset: its
    section was simulated, so its row keeps its figures and its ``market``."""
    history = history_markets(symbols)
    chosen = {key for known_key in known or {} for key in program_keys(known_key)}
    programs: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
    marked: dict[tuple[str, str], dict[str, Any]] = {}
    left_out: dict[tuple[str, str], tuple[list[str], dict[str, Any]]] = {}
    for key, rules in PRESETS.items():
        if not rules.source_url.startswith("https://"):
            continue
        name = (rules.firm, rules.program)
        market = market_fit(key, symbols)
        if market is not None and key not in chosen:
            left_out.setdefault(name, ([], market))[0].append(key)
            continue
        if market is not None:
            marked.setdefault(name, market)
        result = (known or {}).get(key) or simulate_challenge(
            daily_returns, rules, samples=samples, seed=seed
        )
        if not result.get("method"):
            reason = result["probability"]["pass"].get("note", "not measured")
            return {"status": "NOT_MEASURED", "reason": reason}
        programs.setdefault(name, []).append((key, result))
    rows = [
        {**_program(results), **({"market": marked[name]} if name in marked else {})}
        for name, results in programs.items()
    ]
    rows.sort(key=lambda row: (-_payable(row), row["firm"], row["program"]))
    out: dict[str, Any] = {
        "status": "MEASURED",
        "note": NOTE,
        "samples": samples,
        "seed": seed,
        "firms": rows + [_left_out(keys, market) for keys, market in left_out.values()],
    }
    if history is not None:
        out["history_markets"] = history
    figures = [_payable(row) for row in rows]
    if figures and min(figures) >= UNIFORM_HIGH:
        out["uniform"] = "all_pass"
    elif figures and max(figures) <= UNIFORM_LOW:
        out["uniform"] = "all_fail"
        risks = [row["main_risk"] for row in rows if row["main_risk"] != "none"]
        out["common_risk"] = max(sorted(set(risks)), key=risks.count) if risks else "none"
    return out


def _figures(program: dict[str, Any]) -> dict[str, Any]:
    """The figures of one program on one rung, as the ladder keeps them."""
    if program.get("status") != "MEASURED" or not program.get("pass"):
        return {"pass": not_measured(str(program.get("reason") or "not measured"))}
    out: dict[str, Any] = {"pass": program["pass"], "main_risk": program["main_risk"]}
    if program.get("pass_within_best_day"):
        out["pass_within_best_day"] = program["pass_within_best_day"]
    return out


def scenario_columns(
    fit: dict[str, Any],
    rungs: dict[str, dict[str, Any]],
    series: dict[str, pd.Series | None],
    key: str,
    *,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    """``fit`` with the ladder's out-of-sample and cost rungs for every program.

    ``rungs`` are the ladder's rows for the chosen program ``key`` by name,
    and ``series`` the daily returns each was simulated on (``None`` when it
    was not). A rung the ladder could not measure is not measured here
    either, with the ladder's reason. Otherwise the chosen program's figures
    are the ladder's own and every other program is simulated on the same
    series (``program_pass`` with ``samples`` paths per phase). Programs left
    out for their markets (no ``pass``) get no figure."""
    if fit.get("status") != "MEASURED":
        return fit
    chosen = program_keys(key)
    columns: list[dict[str, Any]] = []
    rows = [dict(row) for row in fit.get("firms") or []]
    for name in SCENARIO_COLUMNS:
        rung = rungs.get(name)
        if not rung:
            continue
        drop = ("key", "pass", "pass_within_best_day", "main_risk")
        extra = {k: v for k, v in rung.items() if k not in drop}
        figure = rung.get("pass") or {}
        daily = series.get(name)
        if figure.get("evidence") != "MEASURED" or daily is None:
            reason = figure if figure else not_measured("not measured")
            columns.append({"key": name, **extra, "pass": reason})
            continue
        columns.append({"key": name, **extra, "status": "MEASURED", "samples": samples})
        for row in rows:
            if not row.get("pass"):
                continue
            keys = list(row.get("keys") or [])
            if keys == chosen:
                figures = _figures({"status": "MEASURED", **rung})
            else:
                figures = _figures(program_pass(daily, keys[0], samples=samples, seed=seed))
            row["scenarios"] = {**(row.get("scenarios") or {}), name: figures}
    return {**fit, "firms": rows, "scenarios": columns, "scenario_note": SCENARIO_NOTE}


__all__ = [
    "COIN_PAIRS",
    "MARKET_SYMBOLS",
    "OUTCOME_NOTE",
    "REPEATS",
    "RULE_FIELDS",
    "SAMPLES",
    "SCENARIO_COLUMNS",
    "SCENARIO_NOTE",
    "SYMBOL_MARKETS",
    "firm_fit",
    "history_markets",
    "market_fit",
    "markets_of",
    "program_keys",
    "program_outcomes",
    "program_pass",
    "rules_of",
    "scenario_columns",
    "symbol_venues",
]
