"""Render the campaign's JSON artifacts as a results document, and nothing else.

The document is derived, never authored: every number comes from an artifact
on disk and carries the evidence class that artifact declared. Absent
artifacts render as NOT_RUN sections rather than being omitted, so the
document always says where the programme stands. Before it is written, the
text is scanned with the V9 profit-claim patterns and refused on any match;
a results document that says "profitable" about a backtest is the failure
mode this repository has already retracted once.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import atomic_write_text, load_json
from quant_trade.research.crypto_lowcap.campaign import (
    FROZEN_FILENAME,
    PANEL_VERIFICATION_FILENAME,
    RECOVERIES,
    RESULTS_FILENAME,
    SELECTION_DIRNAME,
    STRESS_RECOVERY,
)
from quant_trade.research.crypto_lowcap.config import LOCK_FILENAME
from quant_trade.research.crypto_lowcap.reveal import STATE_REVEALED, verdict_path
from quant_trade.research.holdout_seal import SEAL_FILENAME, load_seal, read_reveals
from quant_trade.v9.economic_status import PROFIT_CLAIM_PATTERNS

COMMON_PARAMS = ("order_notional_usd", "turnover_multiple", "liquidity_window")


class ProfitClaimError(RuntimeError):
    """Raised when a rendered document asserts money was or will be made."""


def assert_no_profit_claims(text: str) -> None:
    lowered = text.lower()
    hits = [pattern for pattern in PROFIT_CLAIM_PATTERNS if re.search(pattern, lowered)]
    if hits:
        raise ProfitClaimError(
            "the rendered document contains profit-claim language that no artifact in this "
            f"programme can support: {hits}"
        )


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "NOT_MEASURED"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | float):
        return f"{value:.{digits}f}"
    return str(value)


def _pct(value: Any) -> str:
    return "NOT_MEASURED" if value is None else f"{float(value) * 100:+.1f}%"


def _range(values: Any) -> str:
    if not values:
        return "NOT_MEASURED"
    return f"[{values[0]:.2f}, {values[1]:.2f}]"


def _short(digest: Any, n: int = 16) -> str:
    return f"`{str(digest)[:n]}…`"


def _optional(path: Path) -> dict[str, Any] | None:
    return load_json(path) if path.is_file() else None


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def programme_state(experiment_dir: str | Path) -> str:
    exp = Path(experiment_dir)
    verdict = _optional(verdict_path(exp))
    if verdict is not None and verdict.get("state") == STATE_REVEALED:
        return "REVEALED"
    frozen = _optional(exp / FROZEN_FILENAME)
    if frozen is not None:
        return "SELECTED_CANDIDATE_FROZEN" if frozen.get("primary") else "SELECTED_NO_CANDIDATE"
    if (exp / SELECTION_DIRNAME / RESULTS_FILENAME).is_file():
        return "SELECTED"
    return "NOT_RUN"


def _section_seal(exp: Path, verification: dict[str, Any] | None) -> list[str]:
    lines = ["## 1. Seal and dataset", ""]
    if not (exp / SEAL_FILENAME).is_file():
        lines.append("NOT_RUN: no sealed holdout in this directory.")
        return [*lines, ""]
    seal = load_seal(exp)
    reveals = read_reveals(exp)
    lines.append(f"- seal id `{seal.seal_id}`, seal {_short(seal.seal())} (MEASURED)")
    lines.append(f"- panel digest {_short(seal.dataset_digest)}")
    lines.append(f"- selection window {seal.selection_start} → {seal.selection_end}")
    lines.append(
        f"- holdout window {seal.holdout_start} → {seal.holdout_end}, reveals used: {len(reveals)}"
    )
    if verification is None:
        lines.append("- panel verification: NOT_RUN (`verify-panel` has not been run here)")
    else:
        lines.append(
            f"- panel verification: `{verification['status']}` at "
            f"{verification['verified_at_utc']} (panel content sha "
            f"{_short(verification['panel_content_sha256'])})"
        )
    return [*lines, ""]


def _section_programme(lock: dict[str, Any] | None, results: dict[str, Any] | None) -> list[str]:
    lines = ["## 2. Declared programme", ""]
    if lock is None:
        lines.append("NOT_RUN: no campaign lock; `select` has not been run.")
    else:
        lines.append(
            f"- trials config `{lock['trials_config_path']}` sha "
            f"{_short(lock['trials_config_sha256'])}"
        )
        lines.append(
            f"- first run {lock['first_run_at_utc']} at code `{lock['code_sha_first_run'][:12]}`"
        )
        for name, sha in sorted(lock.get("gate_shas", {}).items()):
            lines.append(f"- gate `{name}` sha {_short(sha)}")
    if results is not None:
        d = results["deflated_sharpe"]
        lines.append(
            f"- deflated Sharpe: N declared {d['n_trials_declared']}, spent "
            f"{d['n_trials_spent']}, variance floor {d['sharpe_variance_floor']:.7f}, "
            f"used {d['sharpe_variance_used']:.7f} (ASSUMPTION: floor)"
        )
        for budget in results["budgets"]:
            lines.append(
                f"- `{budget['experiment_id']}`: {budget['trials_spent']} of "
                f"{budget['max_trials']} declared trials"
            )
    return [*lines, ""]


def _trial_line(row: dict[str, Any]) -> str:
    s = row[f"recovery_{STRESS_RECOVERY}"]
    full = row["recovery_1.0"]
    gates = s["gates"]
    params = ", ".join(
        f"{k}={v}" for k, v in row["strategy_params"].items() if k not in COMMON_PARAMS
    )
    return _row(
        [
            f"`{row['trial_id']}`",
            params,
            _fmt(s["sharpe"], 2),
            _pct(s["excess_vs_primary_benchmark"]),
            _fmt(s["drawdown_ratio"], 2),
            _fmt(s["turnover_gate_basis"], 2),
            _fmt(s["cost_drag_bps_per_year"], 0),
            str(s["executed_legs"]),
            _fmt(s["psr"], 2),
            _fmt(s["dsr_declared"], 3),
            _fmt(s["walk_forward_pbo"], 2),
            _fmt(s["beats_control"]),
            _fmt(gates.get(row["primary_gate"])),
            _fmt(gates.get("conservative")),
            _fmt(full["sharpe"], 2),
        ]
    )


def _section_selection(results: dict[str, Any] | None) -> list[str]:
    lines = ["## 3. Selection window (MEASURED, in-sample by construction)", ""]
    if results is None:
        lines.append("NOT_RUN: `select` has not been run.")
        return [*lines, ""]
    wf = results["walk_forward"]
    lines.append(
        f"OOS-of-walk-forward window {results['oos_window'][0]} → {results['oos_window'][1]}; "
        f"{len(wf['folds'])} calendar-year folds, embargo {wf['embargo_days']} days. "
        f"Turnover on the gate basis `{results['turnover_basis']['basis']}`. Values below at "
        f"delisting recovery {STRESS_RECOVERY} (the stress case); recovery 1.0 Sharpe in the "
        "last column."
    )
    lines.append("")
    for name, by_rec in results["benchmarks"].items():
        m = by_rec.get(STRESS_RECOVERY)
        if m is None:
            lines.append(f"- benchmark `{name}`: NOT_MEASURED")
        else:
            lines.append(
                f"- benchmark `{name}`: return {_pct(m['total_return'])}, Sharpe "
                f"{_fmt(m['sharpe'], 2)}, max drawdown {_pct(m['max_drawdown'])}"
            )
    lines.append("")
    lines.append(
        _row(
            [
                "trial",
                "params",
                "Sharpe",
                "excess vs EW B&H",
                "DD ratio",
                "turnover (gate)",
                "drag bps/yr",
                "legs",
                "PSR",
                "DSR decl.",
                "WF-PBO",
                "beats control",
                "primary gate",
                "ETF gate",
                "Sharpe @1.0",
            ]
        )
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---:|")
    for row in results["trials"]:
        lines.append(_trial_line(row))
    lines.append("")
    lines.append("Gate reasons for the stress case, per trial:")
    lines.append("")
    for row in results["trials"]:
        s = row[f"recovery_{STRESS_RECOVERY}"]
        reasons = s["gate_reasons"].get(row["primary_gate"], [])
        verdict = "passes" if not reasons else "; ".join(reasons)
        lines.append(f"- `{row['trial_id']}`: {verdict}")
    lines.append("")
    pooled = results.get("cscv_pooled", {})
    if pooled.get("status") == "MEASURED":
        lines.append(
            f"CSCV over all {pooled['parameter_variants']} sealed trials: PBO "
            f"{_fmt(pooled['pbo'], 3)} ({pooled['decision']})."
        )
    else:
        lines.append(f"CSCV pooled: NOT_MEASURED ({pooled.get('reason', 'n/a')}).")
    return [*lines, ""]


def _section_frozen(frozen: dict[str, Any] | None) -> list[str]:
    lines = ["## 4. Frozen selection", ""]
    if frozen is None:
        lines.append("NOT_RUN: nothing frozen.")
    elif frozen.get("primary") is None:
        lines.append(f"No candidate: {frozen.get('no_candidate_reason')}")
    else:
        p = frozen["primary"]
        lines.append(
            f"- primary `{p['trial_id']}` ({p['strategy']}, {p['strategy_params']}), declared "
            f"DSR at recovery 0 {_fmt(p['declared_dsr_at_recovery_0'], 3)}, frozen sha "
            f"{_short(frozen['sha256'])}"
        )
        for s in frozen["secondaries"]:
            lines.append(f"- secondary `{s['trial_id']}` ({s['strategy']}, {s['strategy_params']})")
        lines.append(f"- criterion: {frozen['criterion']}")
    return [*lines, ""]


def _candidate_lines(cand: dict[str, Any]) -> list[str]:
    lines = []
    for rec in RECOVERIES:
        b = cand["by_recovery"][rec]
        r = b["sharpe_range"]
        gates = b["gates"]
        lines.append(
            _row(
                [
                    f"`{cand['trial_id']}` ({cand['role']})",
                    rec,
                    _fmt(r.get("sharpe_annualised"), 2),
                    _range(r.get("range_1se")),
                    _range(r.get("range_95")),
                    r.get("verdict_class", "NOT_MEASURED"),
                    _pct(b["comparison_test"].get("excess_return")),
                    _fmt(b["refutation"]["beats_control"]),
                    _fmt(b["refutation"]["beats_btc"]),
                    _fmt(gates.get(cand["gate"], {}).get("pass")),
                    _fmt(gates.get("conservative", {}).get("pass")),
                ]
            )
        )
    return lines


def _section_holdout(verdict: dict[str, Any] | None) -> list[str]:
    lines = ["## 5. Holdout verdict", ""]
    if verdict is None:
        lines.append("NOT_RUN: the holdout is sealed and has not been revealed.")
        return [*lines, ""]
    if verdict.get("state") != STATE_REVEALED:
        lines.append(f"`{verdict['state']}`: {verdict.get('reason')}")
        lines.append("")
        lines.append(verdict.get("note", ""))
        return [*lines, ""]
    prog = verdict["program"]
    window = verdict["holdout_window"]
    lines.append(
        f"Revealed once at {verdict['reveal']['at_utc']} for: {verdict['reveal']['reason']}. "
        f"Window {window[0]} → {window[1]}."
    )
    lines.append("")
    lines.append(f"Declared power limit: {verdict['declared_power_limit']}.")
    lines.append("")
    gate0 = "passes" if prog["primary_gate_pass_at_recovery_0"] else "fails"
    gate1 = "passes" if prog["primary_gate_pass_at_recovery_1"] else "fails"
    lines.append(
        f"**Primary `{prog['primary_trial_id']}`: {prog['verdict_class_at_recovery_0']} at "
        f"recovery 0, {prog['verdict_class_at_recovery_1']} at recovery 1.0; primary gate "
        f"{gate0} at recovery 0, {gate1} at recovery 1.0.**"
    )
    lines.append("")
    lines.append(
        _row(
            [
                "candidate",
                "recovery",
                "Sharpe",
                "±1 SE",
                "95% range",
                "class",
                "excess vs EW B&H",
                "beats control",
                "beats BTC",
                "primary gate",
                "ETF gate",
            ]
        )
    )
    lines.append("|---|---|---:|---|---|---|---:|---|---|---|---|")
    for cand in verdict["candidates"]:
        lines.extend(_candidate_lines(cand))
    lines.append("")
    lines.append(verdict.get("note", ""))
    return [*lines, ""]


NOT_MEASURED_ITEMS = (
    "historical spread and depth: the cost model is one live cross-section (2026-08-05); "
    "that it resembles 2018 is an ASSUMPTION",
    "what a delisted position is worth: reported at recovery 1.0 and 0.0 because neither "
    "is the truth",
    "venue fees: ASSUMPTION-class retail defaults; the fee pages are bot-walled",
    "anything about the holdout, until the single reveal; and after it, anything beyond "
    "one draw over one window the seal declares flatters long-only strategies",
    "realised money: none was placed; the profit-claim guard refuses the vocabulary",
)


def _horizon_row(row: dict[str, Any]) -> str:
    if row.get("evidence_class") == "NOT_MEASURED":
        return _row(
            [
                f"`{row['name']}`",
                str(row.get("recovery") or "-"),
                "NOT_MEASURED",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )
    ytt = row["years_to_target"]
    reach = row.get("p_reach_by_years", {})
    return _row(
        [
            f"`{row['name']}`",
            str(row.get("recovery") or "-"),
            row["evidence_class"],
            _pct(row.get("cagr_holdout")),
            _fmt(row.get("constant_return_years_to_target"), 1),
            f"{_fmt(ytt['p50'], 1)} [{_fmt(ytt['p5'], 1)}, {_fmt(ytt['p95'], 1)}]",
            _fmt(reach.get("10"), 2),
            _fmt(row.get("p_50pct_drawdown_before_target"), 2),
            f"{row['median_terminal_wealth_usd']:,.0f}",
        ]
    )


def _section_horizon(exp: Path) -> list[str]:
    from quant_trade.research.crypto_lowcap.horizon import horizon_path

    lines = ["## 8. What this implies for capital", ""]
    horizon = _optional(horizon_path(exp))
    if horizon is None:
        lines.append("NOT_RUN: `quant-trade crypto-lowcap horizon` has not been run.")
        return [*lines, ""]
    inputs = horizon["inputs"]
    lines.append(
        f"State `{horizon['state']}`. Capital {inputs['capital_usd']:,.0f}, target "
        f"{inputs['target_usd']:,.0f}, monthly contribution "
        f"{inputs['monthly_contribution_usd']:,.0f}, horizon {inputs['years']} years, "
        f"{inputs['samples']} resampled paths (stationary bootstrap, expected block "
        f"{inputs['expected_block_size']:g} days, seed {inputs['seed']})."
    )
    lines.append("")
    if horizon["state"] == "NOT_MEASURED":
        lines.append(f"NOT_MEASURED: {horizon.get('reason')}")
        return [*lines, ""]
    rows = list(horizon.get("rows", []))
    if horizon.get("assumed"):
        rows = list(horizon["assumed"]["rows"])
        lines.append(
            f"ASSUMPTION: annual return {horizon['assumed']['annual_return']:+.1%}, annual "
            f"volatility {horizon['assumed']['annual_volatility']:.1%}, "
            f"{horizon['assumed']['model']}. Nothing measured enters these rows."
        )
        lines.append("")
    lines.append(
        _row(
            [
                "series",
                "recovery",
                "evidence",
                "holdout CAGR",
                "constant-CAGR years",
                "years to target p50 [p5, p95]",
                "P(reach in 10y)",
                "P(halve first)",
                "median terminal",
            ]
        )
    )
    lines.append("|---|---|---|---:|---:|---|---:|---:|---:|")
    for row in rows:
        lines.append(_horizon_row(row))
    lines.append("")
    cap = horizon.get("capacity")
    if cap:
        lines.append(
            f"Capacity at this capital: `{cap['status']}`"
            + (
                f" (leg {cap['leg_notional_usd']:,.0f} against a calibrated maximum of "
                f"{cap['max_calibrated_notional_usd']:,.0f} and a fully executable maximum of "
                f"{cap['max_fully_executable_notional_usd']:,.0f} per leg)"
                if "leg_notional_usd" in cap
                else f": {cap.get('reason', '')}"
            )
        )
        lines.append("")
    lines.append("Declared limits of every row above:")
    lines.append("")
    for item in horizon.get("declared_limits", []):
        lines.append(f"- {item}")
    return [*lines, ""]


def _section_reproduction(exp: Path) -> list[str]:
    panel = f"{exp}/panel.csv.gz"
    cmd = "quant-trade crypto-lowcap"
    return [
        "## 6. What is NOT measured",
        "",
        *[f"- {item}" for item in NOT_MEASURED_ITEMS],
        "",
        "## 7. Reproduction",
        "",
        "```bash",
        f"{cmd} verify-panel --experiment-dir {exp} --panel {panel} --explain",
        f"{cmd} select --experiment-dir {exp} --panel {panel} \\",
        "    --trials configs/research/crypto_lowcap_trials.yaml",
        f'{cmd} reveal --experiment-dir {exp} --panel {panel} --reason "final evaluation"',
        f"{cmd} report --experiment-dir {exp} --output docs/CRYPTO_LOWCAP_RESULTS.md",
        f"{cmd} horizon --experiment-dir {exp} --capital 10000 --target 1000000",
        f"{cmd} doctor --experiment-dir {exp}   # or: make crypto-lowcap-run",
        "```",
        "",
        "See `docs/CRYPTO_LOWCAP_RUNBOOK.md` for the dataset re-collection and re-seal paths.",
        "",
    ]


def render_results_markdown(experiment_dir: str | Path) -> str:
    exp = Path(experiment_dir)
    state = programme_state(exp)
    verification = _optional(exp / PANEL_VERIFICATION_FILENAME)
    lock = _optional(exp / LOCK_FILENAME)
    results = _optional(exp / SELECTION_DIRNAME / RESULTS_FILENAME)
    frozen = _optional(exp / FROZEN_FILENAME)
    verdict = _optional(verdict_path(exp))

    lines = [
        "# Low/mid-cap crypto campaign: results",
        "",
        f"**Programme state: `{state}`.** Research-only. No orders, no funds, no keys.",
        "",
        "This document is rendered from the JSON artifacts in the experiment directory by "
        "`quant-trade crypto-lowcap report`. Every number carries the evidence class its "
        "artifact declared: MEASURED (computed from bytes on disk), ASSUMPTION (a declared "
        "choice), NOT_MEASURED (absent, never approximated). Nothing here is a claim about "
        "realised money.",
        "",
        *_section_seal(exp, verification),
        *_section_programme(lock, results),
        *_section_selection(results),
        *_section_frozen(frozen),
        *_section_holdout(verdict),
        *_section_reproduction(exp),
        *_section_horizon(exp),
    ]
    text = "\n".join(lines)
    assert_no_profit_claims(text)
    return text


def write_report(experiment_dir: str | Path, output: str | Path) -> Path:
    text = render_results_markdown(experiment_dir)
    return atomic_write_text(output, text)


__all__ = [
    "ProfitClaimError",
    "assert_no_profit_claims",
    "programme_state",
    "render_results_markdown",
    "write_report",
]
