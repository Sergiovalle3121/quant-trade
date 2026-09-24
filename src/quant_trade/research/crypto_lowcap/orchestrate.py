"""`run-all`: the campaign as one command, running only what is missing.

Each step is the same library function its CLI command calls, so nothing here
can behave differently from the runbook's four commands. The planner reads the
programme's state from artifacts and decides which steps are still needed; a
failing step marks the rest SKIPPED and the run stops, because a report
rendered after a failed reveal would describe a state that does not exist.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from quant_trade.data.panel_digest import DigestInputs, verify_panel_digest
from quant_trade.research.crypto_lowcap.campaign import (
    CampaignError,
    record_panel_verification,
    require_verified_panel,
    run_select,
)
from quant_trade.research.crypto_lowcap.report import programme_state, write_report
from quant_trade.research.crypto_lowcap.reveal import run_reveal, verdict_path
from quant_trade.research.holdout_seal import load_seal

PENDING, SKIPPED, OK, FAILED = "PENDING", "SKIPPED", "OK", "FAILED"


@dataclass
class Step:
    name: str
    needed: bool
    reason: str
    status: str = PENDING
    detail: str = ""
    seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OrchestrationError(RuntimeError):
    """Raised when run-all cannot start honestly."""


def plan_steps(experiment_dir: str | Path, panel_path: str | Path) -> list[Step]:
    exp = Path(experiment_dir)
    seal = load_seal(exp)
    try:
        require_verified_panel(exp, panel_path, seal)
        verify = Step("verify-panel", False, "panel already verified against this seal")
    except CampaignError as exc:
        verify = Step("verify-panel", True, str(exc))
    state = programme_state(exp)
    select = Step(
        "select",
        state == "NOT_RUN",
        "selection has not run" if state == "NOT_RUN" else f"programme state is {state}",
    )
    revealed = verdict_path(exp).is_file()
    reveal = Step(
        "reveal", not revealed, "no holdout verdict yet" if not revealed else "verdict exists"
    )
    report = Step("report", True, "always rendered from the artifacts")
    return [verify, select, reveal, report]


def run_all(
    experiment_dir: str | Path,
    inputs: DigestInputs,
    trials_path: str | Path,
    *,
    reason: str,
    output: str | Path,
    dry_run: bool,
    at_utc: str,
    code_sha: str,
) -> dict[str, Any]:
    exp = Path(experiment_dir)
    steps = plan_steps(exp, inputs.panel_path)
    state_before = programme_state(exp)
    reveal_needed = next(s for s in steps if s.name == "reveal").needed
    if reveal_needed and not reason.strip():
        raise OrchestrationError(
            "the holdout would be revealed by this run and no --reason was given; a reveal "
            "must state its reason, forever"
        )
    result: dict[str, Any] = {
        "artifact": "RUN_ALL",
        "dry_run": dry_run,
        "reason": reason,
        "state_before": state_before,
        "state_after": state_before,
        "steps": [],
        "failed_step": None,
    }
    if dry_run:
        for step in steps:
            step.status = PENDING if step.needed else SKIPPED
        result["steps"] = [s.to_dict() for s in steps]
        return result

    failed = False
    for step in steps:
        if failed or not step.needed:
            step.status = SKIPPED
            continue
        started = time.perf_counter()
        try:
            if step.name == "verify-panel":
                verification = verify_panel_digest(exp, inputs)
                record_panel_verification(
                    exp, verification, panel_path=inputs.panel_path, at_utc=at_utc
                )
                if verification.status != "PASS":
                    raise CampaignError("; ".join(verification.reasons))
                step.detail = "PASS"
            elif step.name == "select":
                selected = run_select(
                    exp, trials_path, inputs.panel_path, evaluated_at_utc=at_utc, code_sha=code_sha
                )
                frozen = selected["frozen"]
                step.detail = (
                    f"{len(selected['trials'])} trials; primary "
                    f"{frozen['primary_trial_id'] or 'none'}"
                )
            elif step.name == "reveal":
                verdict = run_reveal(
                    exp,
                    inputs.panel_path,
                    reason=reason,
                    evaluated_at_utc=at_utc,
                    code_sha=code_sha,
                )
                step.detail = str(verdict["state"])
            else:
                step.detail = str(write_report(exp, output))
            step.status = OK
        except Exception as exc:  # noqa: BLE001 - every failure must be reported, none swallowed
            step.status = FAILED
            step.detail = f"{type(exc).__name__}: {exc}"
            result["failed_step"] = step.name
            failed = True
        finally:
            step.seconds = time.perf_counter() - started
    result["steps"] = [s.to_dict() for s in steps]
    result["state_after"] = programme_state(exp)
    return result


__all__ = [
    "FAILED",
    "OK",
    "PENDING",
    "SKIPPED",
    "OrchestrationError",
    "Step",
    "plan_steps",
    "run_all",
]
