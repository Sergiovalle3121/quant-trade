"""The low-frequency paper bridge: from a positive verdict to a verifiable record.

The V9 canary gate (72 hours, 500 events) was written for eight-hour funding
settlements. A strategy that rebalances monthly or annually produces a handful
of fills per rebalance and would never reach it, so it needs a gate of its
own, and this is it: plan the next rebalance from the frozen candidate under
the measured cost model, let the operator execute it by hand (on a venue's
paper or test facility, or simply record what the book showed), record the
fills, and reconcile realised cost against the model. Nothing here talks to
a venue, holds a key, or places an order.

Three refusals carry the honesty:

- a plan inside the evaluated window is a backtest wearing a paper label, so
  ``as_of`` must fall after the sealed holdout end;
- a candidate whose verdict is not RANGE_ABOVE_ZERO with its primary gate
  passing at both delisting assumptions is not paper-eligible; the policy is
  declared in the runbook and enforced here;
- the record is a hash-chained journal (same construction as the collectors');
  a broken chain is a status of its own, never a silent skip.

``real_money_approved`` is false in every status this module writes, and the
module asserts it before writing. There is no branch that could set it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from quant_trade.costs.rebalance import rebalance_cost
from quant_trade.data.panel_digest import panel_content_sha256
from quant_trade.data.universe import UniverseCollectorError, read_journal, verify_journal_chain
from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    sha256_of_file,
    sha256_of_text,
)
from quant_trade.research.crypto_lowcap.campaign import (
    RESULTS_FILENAME,
    SELECTION_DIRNAME,
    generate_weights,
    iso_days,
    load_frozen,
    load_panel,
)
from quant_trade.research.crypto_lowcap.config import load_trials_config
from quant_trade.research.crypto_lowcap.reveal import STATE_REVEALED, verdict_path
from quant_trade.research.holdout_seal import load_seal

SCHEMA_VERSION = 1
DEFAULT_STATE_DIR = "data/paper/crypto_lowcap"
JOURNAL_FILENAME = "paper_journal.jsonl"
HOLDINGS_FILENAME = "holdings.json"
PLANS_DIRNAME = "plans"
STATUS_FILENAME = "PAPER_STATUS.json"

#: The declared low-frequency gate. ASSUMPTION class, stated in every status.
MAX_REALISED_TO_MODEL_COST_RATIO = 2.0
MAX_REFUSED_LEG_FRACTION = 0.1
MIN_REBALANCES = {"annual": 2, "quarterly": 2, "monthly": 3, "weekly": 3, "daily": 3}

STATUS_INCOMPLETE = "PAPER_INCOMPLETE"
STATUS_PASS = "PAPER_GATE_PASS"
STATUS_FAIL = "PAPER_GATE_FAIL"
STATUS_BROKEN = "JOURNAL_BROKEN"


class PaperBridgeError(RuntimeError):
    """Raised when the bridge cannot proceed honestly."""


# --- eligibility ------------------------------------------------------------


def assert_paper_eligible(verdict: dict[str, Any]) -> dict[str, bool]:
    """The declared policy: revealed, range above zero, primary gate at both recoveries."""
    program = verdict.get("program") or {}
    checks = {
        "revealed": verdict.get("state") == STATE_REVEALED,
        "range_above_zero_at_recovery_0": program.get("verdict_class_at_recovery_0")
        == "RANGE_ABOVE_ZERO",
        "primary_gate_at_recovery_0": bool(program.get("primary_gate_pass_at_recovery_0")),
        "primary_gate_at_recovery_1": bool(program.get("primary_gate_pass_at_recovery_1")),
    }
    if not all(checks.values()):
        failed = sorted(name for name, ok in checks.items() if not ok)
        raise PaperBridgeError(
            f"the frozen candidate is not paper-eligible; failed: {failed}. The policy is "
            "declared in docs/CRYPTO_LOWCAP_RUNBOOK.md § 8 and is not adjustable here."
        )
    return checks


def infer_rebalance_frequency(weights: pd.DataFrame) -> str:
    """Measured from the candidate's own rebalance dates, never assumed."""
    stamps = sorted(pd.to_datetime(weights["timestamp"].unique()))
    if len(stamps) < 2:
        return "annual"
    gaps = sorted((b - a).days for a, b in zip(stamps[:-1], stamps[1:], strict=True))
    median = gaps[len(gaps) // 2]
    if median >= 300:
        return "annual"
    if median >= 80:
        return "quarterly"
    if median >= 25:
        return "monthly"
    if median >= 6:
        return "weekly"
    return "daily"


# --- journal ----------------------------------------------------------------


def journal_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / JOURNAL_FILENAME


def _self_sha(record: dict[str, Any]) -> str:
    return sha256_of_text(canonical_dumps({k: v for k, v in record.items() if k != "entry_sha256"}))


def read_paper_journal(state_dir: str | Path) -> list[dict[str, Any]]:
    """Every record, with the chain AND each record's own digest verified.

    The collectors' chain proves that no record was edited once a successor
    exists. A paper journal's most recent record has no successor yet, and it
    is exactly the one an operator would be tempted to touch, so every record
    also carries its own digest and the tail is checked like the rest.
    """
    path = journal_path(state_dir)
    records = read_journal(path)
    try:
        verify_journal_chain(records)
    except UniverseCollectorError as exc:
        raise PaperBridgeError(f"paper journal chain broken: {exc}") from exc
    for index, record in enumerate(records):
        if record.get("entry_sha256") != _self_sha(record):
            raise PaperBridgeError(
                f"paper journal chain broken: record {index} ({record.get('type')}) was edited"
            )
    return records


def append_paper_record(state_dir: str | Path, record: dict[str, Any]) -> dict[str, Any]:
    records = read_paper_journal(state_dir)
    if not records and record.get("type") != "header":
        raise PaperBridgeError("a paper journal must begin with a header record")
    record = dict(record)
    record["previous_sha256"] = sha256_of_text(canonical_dumps(records[-1])) if records else ""
    record["entry_sha256"] = _self_sha(record)
    path = journal_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_dumps(record) + "\n")
    return record


def _holdings(state_dir: str | Path) -> dict[str, Any]:
    path = Path(state_dir) / HOLDINGS_FILENAME
    if not path.is_file():
        return {"quantities": {}, "cash_usd": None, "as_of": None, "plan_sha256": None}
    return load_json(path)


def _plan_sha(plan: dict[str, Any]) -> str:
    return sha256_of_text(canonical_dumps({k: v for k, v in plan.items() if k != "sha256"}))


# --- plan -------------------------------------------------------------------


def plan_rebalance(
    experiment_dir: str | Path,
    panel_path: str | Path,
    *,
    capital_usd: float,
    as_of: str,
    state_dir: str | Path = DEFAULT_STATE_DIR,
    at_utc: str,
    code_sha: str,
) -> dict[str, Any]:
    exp = Path(experiment_dir)
    state = Path(state_dir)
    if capital_usd <= 0:
        raise PaperBridgeError("capital_usd must be positive")
    vpath = verdict_path(exp)
    if not vpath.is_file():
        raise PaperBridgeError("no holdout verdict; nothing has been revealed to paper-trade")
    verdict = load_json(vpath)
    checks = assert_paper_eligible(verdict)
    frozen = load_frozen(exp)
    if frozen is None or frozen.get("primary") is None:
        raise PaperBridgeError("no frozen primary candidate")
    primary = frozen["primary"]
    seal = load_seal(exp)
    if as_of <= seal.holdout_end:
        raise PaperBridgeError(
            f"as_of {as_of} is not after the sealed holdout end {seal.holdout_end}; a rebalance "
            "inside the evaluated window is a backtest, not a paper record"
        )
    results_path = exp / SELECTION_DIRNAME / RESULTS_FILENAME
    results = load_json(results_path)
    config = load_trials_config(results["trials_config"]["path"])
    if config.sha256 != results["trials_config"]["sha256"]:
        raise PaperBridgeError("the trials config changed after selection; the bridge refuses it")
    common = config.common

    journal = read_paper_journal(state) if journal_path(state).is_file() else []
    if journal:
        header = journal[0]
        if header.get("frozen_selection_sha256") != frozen["sha256"]:
            raise PaperBridgeError(
                f"{state} belongs to a different frozen selection; use a new state directory"
            )

    panel = load_panel(panel_path)
    weights = generate_weights(panel, primary["strategy"], primary["strategy_params"])
    if weights.empty:
        raise PaperBridgeError("the frozen candidate produced no targets on this panel")
    stamps = sorted(set(weights["timestamp"].dt.strftime("%Y-%m-%d")))
    eligible_dates = [d for d in stamps if seal.holdout_end < d <= as_of]
    if not eligible_dates:
        raise PaperBridgeError(
            f"no rebalance date of the frozen candidate falls in ({seal.holdout_end}, {as_of}]"
        )
    rebalance_date = eligible_dates[-1]
    if any(r.get("type") == "plan" and r.get("rebalance_date") == rebalance_date for r in journal):
        raise PaperBridgeError(f"a plan for {rebalance_date} is already journaled")
    frequency = infer_rebalance_frequency(weights)

    day_rows = panel[panel["timestamp"].dt.strftime("%Y-%m-%d") == rebalance_date]
    closes = {str(s): float(c) for s, c in zip(day_rows["symbol"], day_rows["close"], strict=True)}
    caps = {
        str(s): float(c)
        for s, c in zip(day_rows["symbol"], day_rows["market_cap_usd"], strict=True)
    }
    on_date = weights[weights["timestamp"].dt.strftime("%Y-%m-%d") == rebalance_date]
    target = {
        str(s): float(w)
        for s, w in zip(on_date["symbol"], on_date["target_weight"], strict=True)
        if w > 0
    }

    holdings = _holdings(state)
    quantities = {str(k): float(v) for k, v in holdings.get("quantities", {}).items()}
    first_plan = holdings.get("cash_usd") is None
    cash = float(capital_usd) if first_plan else float(holdings["cash_usd"])
    held_value = {s: q * closes.get(s, 0.0) for s, q in quantities.items()}
    portfolio_value = cash + sum(held_value.values())
    if portfolio_value <= 0:
        raise PaperBridgeError("portfolio value is not positive; nothing to rebalance")
    before = {s: v / portfolio_value for s, v in held_value.items() if v > 0}
    unpriced_holdings = sorted(s for s, q in quantities.items() if q > 0 and s not in closes)

    cost = rebalance_cost(
        before,
        target,
        {s: caps.get(s, 0.0) for s in set(before) | set(target)},
        portfolio_value_usd=portfolio_value,
        quantile=common.quantile,
        min_executable_fraction=common.min_executable_fraction,
    )
    legs: list[dict[str, Any]] = []
    for leg in cost.legs:
        side = "buy" if target.get(leg.symbol, 0.0) > before.get(leg.symbol, 0.0) else "sell"
        price = closes.get(leg.symbol)
        legs.append(
            {
                "symbol": leg.symbol,
                "side": side,
                "tier": leg.tier,
                "reference_price": price,
                "requested_notional_usd": leg.requested_notional_usd,
                "executed_notional_usd": leg.executed_notional_usd,
                "quantity": (leg.executed_notional_usd / price) if price else 0.0,
                "cost_bps_of_leg": leg.cost_bps_of_leg,
                "cost_usd": leg.cost_usd,
                "executable": leg.executable,
                "reason": leg.reason,
            }
        )
    plan: dict[str, Any] = {
        "artifact": "PAPER_PLAN",
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": at_utc,
        "code_sha": code_sha,
        "experiment_dir": str(exp),
        "seal_id": seal.seal_id,
        "frozen_selection_sha256": frozen["sha256"],
        "verdict_sha256": sha256_of_file(vpath),
        "trial_id": primary["trial_id"],
        "strategy": primary["strategy"],
        "strategy_params": primary["strategy_params"],
        "rebalance_frequency": frequency,
        "policy_checks": checks,
        "panel": {
            "path": str(panel_path),
            "content_sha256": panel_content_sha256(panel_path),
            "last_bar": iso_days(panel)[-1],
        },
        "as_of": as_of,
        "rebalance_date": rebalance_date,
        "portfolio_value_usd": portfolio_value,
        "cash_before_usd": cash,
        "capital_usd": capital_usd,
        "holdings_before": {
            s: {"quantity": quantities[s], "price": closes.get(s), "weight": before.get(s, 0.0)}
            for s in sorted(quantities)
            if quantities[s] > 0
        },
        "unpriced_holdings": unpriced_holdings,
        "target_weights": target,
        "achieved_weights": dict(cost.achieved_weights),
        "legs": legs,
        "refused_legs": cost.refused_legs,
        "capped_legs": cost.capped_legs,
        "unpriceable_legs": cost.unpriceable_legs,
        "turnover": cost.turnover,
        "cost_usd": cost.cost_usd,
        "cost_bps_of_portfolio": cost.cost_bps_of_portfolio,
        "note": (
            "A paper order ticket. Execute by hand on a venue's paper or test facility, or record "
            "what the book showed; then `paper-record` the fills. No order is placed by this tool."
        ),
    }
    plan["sha256"] = _plan_sha(plan)
    plans_dir = state / PLANS_DIRNAME
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_file = plans_dir / f"{rebalance_date}_{plan['sha256'][:12]}.json"
    atomic_write_json(plan_file, plan)
    if not journal:
        append_paper_record(
            state,
            {
                "type": "header",
                "schema_version": SCHEMA_VERSION,
                "started_at_utc": at_utc,
                "experiment_dir": str(exp),
                "seal_id": seal.seal_id,
                "frozen_selection_sha256": frozen["sha256"],
                "trial_id": primary["trial_id"],
                "rebalance_frequency": frequency,
                "policy": {
                    "min_rebalances_recorded": MIN_REBALANCES.get(frequency, 3),
                    "max_realised_to_model_cost_ratio": MAX_REALISED_TO_MODEL_COST_RATIO,
                    "max_refused_leg_fraction": MAX_REFUSED_LEG_FRACTION,
                    "evidence_class": "ASSUMPTION",
                },
            },
        )
    append_paper_record(
        state,
        {
            "type": "plan",
            "at_utc": at_utc,
            "plan_path": str(plan_file),
            "plan_sha256": plan["sha256"],
            "rebalance_date": rebalance_date,
            "planned_legs": len(legs),
            "executable_legs": sum(1 for leg in legs if leg["executed_notional_usd"] > 0),
            "refused_legs": cost.refused_legs,
            "capped_legs": cost.capped_legs,
            "unpriceable_legs": cost.unpriceable_legs,
            "planned_cost_usd": cost.cost_usd,
        },
    )
    if first_plan:
        atomic_write_json(
            state / HOLDINGS_FILENAME,
            {"quantities": {}, "cash_usd": cash, "as_of": None, "plan_sha256": None},
        )
    plan["plan_path"] = str(plan_file)
    return plan


# --- fills ------------------------------------------------------------------


def record_fills(
    state_dir: str | Path,
    plan_path: str | Path,
    fills_path: str | Path,
    *,
    at_utc: str,
) -> dict[str, Any]:
    state = Path(state_dir)
    plan = load_json(plan_path)
    if plan.get("sha256") != _plan_sha(plan):
        raise PaperBridgeError(
            f"{plan_path} was edited after it was written; its sha256 no longer matches"
        )
    fills = load_json(fills_path)
    if fills.get("plan_sha256") != plan["sha256"]:
        raise PaperBridgeError("fills.plan_sha256 does not name this plan")
    journal = read_paper_journal(state)
    if not any(r.get("type") == "plan" and r.get("plan_sha256") == plan["sha256"] for r in journal):
        raise PaperBridgeError("this plan is not in the journal of this state directory")
    if any(r.get("type") == "fills" and r.get("plan_sha256") == plan["sha256"] for r in journal):
        raise PaperBridgeError("fills for this plan are already recorded; a plan is filled once")

    executable = {
        leg["symbol"]: leg for leg in plan["legs"] if float(leg["executed_notional_usd"]) > 0
    }
    legs_out: list[dict[str, Any]] = []
    seen: set[str] = set()
    realised_cost_usd = 0.0
    for fill in fills.get("fills", []):
        symbol = str(fill["symbol"])
        leg = executable.get(symbol)
        if leg is None:
            raise PaperBridgeError(f"fill for {symbol!r} is not an executable leg of this plan")
        if str(fill["side"]) != leg["side"]:
            raise PaperBridgeError(f"fill side for {symbol!r} contradicts the plan ({leg['side']})")
        if symbol in seen:
            raise PaperBridgeError(f"two fills for {symbol!r}; aggregate them into one")
        seen.add(symbol)
        quantity = float(fill["quantity"])
        price = float(fill["price"])
        fee = float(fill.get("fee_usd", 0.0))
        if quantity <= 0 or price <= 0 or fee < 0:
            raise PaperBridgeError(
                f"fill for {symbol!r} has a non-positive quantity/price or negative fee"
            )
        notional = quantity * price
        reference = float(leg["reference_price"])
        deviation = (
            (price - reference) / reference
            if leg["side"] == "buy"
            else (reference - price) / reference
        )
        realised_bps = deviation * 10_000.0 + fee / notional * 10_000.0
        planned_bps = float(leg["cost_bps_of_leg"])
        realised_cost_usd += realised_bps / 10_000.0 * notional
        legs_out.append(
            {
                "symbol": symbol,
                "side": leg["side"],
                "planned_notional_usd": float(leg["executed_notional_usd"]),
                "realised_notional_usd": notional,
                "planned_cost_bps": planned_bps,
                "realised_cost_bps": realised_bps,
                "ratio": (realised_bps / planned_bps) if planned_bps > 0 else None,
                "fee_usd": fee,
                "quantity": quantity,
                "price": price,
                "executed_at_utc": str(fill.get("executed_at_utc", "")),
            }
        )
    unfilled = sorted(set(executable) - seen)
    record = append_paper_record(
        state,
        {
            "type": "fills",
            "at_utc": at_utc,
            "plan_sha256": plan["sha256"],
            "rebalance_date": plan["rebalance_date"],
            "venue": str(fills.get("venue", "")),
            "legs": legs_out,
            "unfilled": unfilled,
            "planned_cost_usd": float(plan["cost_usd"]),
            "realised_cost_usd": realised_cost_usd,
        },
    )
    # Holdings are a cache of the journal; rebuild from the plan's opening state.
    quantities = {s: float(h["quantity"]) for s, h in plan["holdings_before"].items()}
    cash = float(plan["cash_before_usd"])
    for leg in legs_out:
        if leg["side"] == "buy":
            quantities[leg["symbol"]] = quantities.get(leg["symbol"], 0.0) + leg["quantity"]
            cash -= leg["realised_notional_usd"] + leg["fee_usd"]
        else:
            quantities[leg["symbol"]] = quantities.get(leg["symbol"], 0.0) - leg["quantity"]
            cash += leg["realised_notional_usd"] - leg["fee_usd"]
    atomic_write_json(
        state / HOLDINGS_FILENAME,
        {
            "quantities": {s: q for s, q in quantities.items() if abs(q) > 1e-12},
            "cash_usd": cash,
            "as_of": plan["rebalance_date"],
            "plan_sha256": plan["sha256"],
        },
    )
    return record


# --- status -----------------------------------------------------------------


def paper_status(state_dir: str | Path, *, now_utc: str) -> dict[str, Any]:
    state = Path(state_dir)
    payload: dict[str, Any] = {
        "artifact": "PAPER_STATUS",
        "schema_version": SCHEMA_VERSION,
        "evaluated_at_utc": now_utc,
        "real_money_approved": False,
        "state_dir": str(state),
    }
    try:
        journal = read_paper_journal(state)
    except PaperBridgeError as exc:
        payload.update({"status": STATUS_BROKEN, "reason": str(exc)})
        _write_status(state, payload)
        return payload
    if not journal:
        payload.update({"status": STATUS_INCOMPLETE, "reason": "no plans journaled yet"})
        _write_status(state, payload)
        return payload
    header = journal[0]
    plans = [r for r in journal if r.get("type") == "plan"]
    fills = [r for r in journal if r.get("type") == "fills"]
    planned_cost = sum(float(r.get("planned_cost_usd", 0.0)) for r in fills)
    realised_cost = sum(float(r.get("realised_cost_usd", 0.0)) for r in fills)
    planned_legs = sum(int(r.get("planned_legs", 0)) for r in plans)
    refused = sum(int(r.get("refused_legs", 0)) + int(r.get("unpriceable_legs", 0)) for r in plans)
    ratio = (realised_cost / planned_cost) if planned_cost > 0 else None
    refused_fraction = (refused / planned_legs) if planned_legs > 0 else 0.0
    started = datetime.fromisoformat(str(header["started_at_utc"]).replace("Z", "+00:00"))
    now = datetime.fromisoformat(now_utc.replace("Z", "+00:00"))
    policy = header.get("policy", {})
    min_rebalances = int(
        policy.get(
            "min_rebalances_recorded", MIN_REBALANCES.get(str(header.get("rebalance_frequency")), 3)
        )
    )
    max_ratio = float(
        policy.get("max_realised_to_model_cost_ratio", MAX_REALISED_TO_MODEL_COST_RATIO)
    )
    max_refused = float(policy.get("max_refused_leg_fraction", MAX_REFUSED_LEG_FRACTION))
    reasons: list[str] = []
    if len(fills) < min_rebalances:
        status = STATUS_INCOMPLETE
        reasons.append(f"{len(fills)} of {min_rebalances} required rebalances recorded")
    else:
        if ratio is not None and ratio > max_ratio:
            reasons.append(f"realised cost is {ratio:.2f}x the model, above {max_ratio:.1f}x")
        if refused_fraction > max_refused:
            reasons.append(
                f"{refused_fraction:.0%} of planned legs were refused, above {max_refused:.0%}"
            )
        status = STATUS_FAIL if reasons else STATUS_PASS
    payload.update(
        {
            "status": status,
            "started_at_utc": header["started_at_utc"],
            "days_elapsed": max(0, (now - started).days),
            "trial_id": header.get("trial_id"),
            "rebalance_frequency": header.get("rebalance_frequency"),
            "rebalances_planned": len(plans),
            "rebalances_recorded": len(fills),
            "planned_cost_usd": planned_cost,
            "realised_cost_usd": realised_cost,
            "realised_to_model_cost_ratio": ratio,
            "refused_leg_fraction": refused_fraction,
            "gate": {
                "min_rebalances_recorded": min_rebalances,
                "max_realised_to_model_cost_ratio": max_ratio,
                "max_refused_leg_fraction": max_refused,
                "evidence_class": "ASSUMPTION",
                "reasons": reasons,
            },
            "per_rebalance": [
                {
                    "rebalance_date": r.get("rebalance_date"),
                    "planned_cost_usd": r.get("planned_cost_usd"),
                    "realised_cost_usd": r.get("realised_cost_usd"),
                    "unfilled": r.get("unfilled", []),
                    "legs": len(r.get("legs", [])),
                }
                for r in fills
            ],
            "note": (
                "A passing gate supports at most a human decision about a small real allocation; "
                "it authorises nothing by itself, and this tool has no path to place an order."
            ),
        }
    )
    _write_status(state, payload)
    return payload


def _write_status(state: Path, payload: dict[str, Any]) -> None:
    assert payload["real_money_approved"] is False
    atomic_write_json(state / STATUS_FILENAME, payload)


__all__ = [
    "DEFAULT_STATE_DIR",
    "HOLDINGS_FILENAME",
    "JOURNAL_FILENAME",
    "MAX_REALISED_TO_MODEL_COST_RATIO",
    "MAX_REFUSED_LEG_FRACTION",
    "MIN_REBALANCES",
    "STATUS_BROKEN",
    "STATUS_FAIL",
    "STATUS_INCOMPLETE",
    "STATUS_PASS",
    "PaperBridgeError",
    "append_paper_record",
    "assert_paper_eligible",
    "infer_rebalance_frequency",
    "journal_path",
    "paper_status",
    "plan_rebalance",
    "read_paper_journal",
    "record_fills",
]
