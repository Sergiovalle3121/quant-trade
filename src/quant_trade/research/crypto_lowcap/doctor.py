"""Pre-flight for the campaign: what is missing, what would refuse, how long.

Every check is read-only. The report never writes into the experiment
directory, because a diagnostic that leaves files behind changes the thing it
diagnosed. Each failing check carries the exact command that fixes it, with
the operator's own paths, so the runbook does not have to be re-read.

The runtime estimate is an ASSUMPTION and says so: it scales two constants
measured on one synthetic panel (688k rows: ~7 s per signal generation, ~1 s
per evaluation) by the row count of the panel on disk.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.data.panel_digest import DigestInputs, panel_content_sha256
from quant_trade.data.universe import UniverseCollectorError, read_journal, verify_journal_chain
from quant_trade.evidence.canonical_json import load_json
from quant_trade.research.crypto_lowcap.campaign import (
    PANEL_VERIFICATION_FILENAME,
    CampaignError,
    fold_windows,
    iso_days,
    load_panel,
)
from quant_trade.research.crypto_lowcap.config import (
    CampaignConfigError,
    TrialsConfig,
    load_trials_config,
    read_lock,
)
from quant_trade.research.crypto_lowcap.report import programme_state
from quant_trade.research.holdout_seal import (
    HoldoutSeal,
    HoldoutSealError,
    load_seal,
    read_reveals,
)
from quant_trade.research.preregistration import PreregistrationError, load_preregistration

#: Measured once on a 300-symbol x 2,295-day synthetic panel (2026-09-21).
#: ASSUMPTION for any other machine; declared in every report that uses it.
EST_SIGNAL_SECONDS_AT_REF = 7.0
EST_EVAL_SECONDS_AT_REF = 1.0
REF_ROWS = 688_000

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DoctorReport:
    experiment_dir: str
    generated_at_utc: str
    checks: list[Check] = field(default_factory=list)
    panel: dict[str, Any] = field(default_factory=dict)
    seal: dict[str, Any] = field(default_factory=dict)
    lock: dict[str, Any] = field(default_factory=dict)
    runtime_estimate: dict[str, Any] = field(default_factory=dict)
    programme_state: str = "NOT_RUN"
    reveals_used: int = 0

    @property
    def overall(self) -> str:
        return FAIL if any(c.status == FAIL for c in self.checks) else PASS

    def missing_inputs(self) -> list[dict[str, str]]:
        return [
            {"name": c.name, "command": c.fix} for c in self.checks if c.status == FAIL and c.fix
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": "DOCTOR",
            "generated_at_utc": self.generated_at_utc,
            "experiment_dir": self.experiment_dir,
            "programme_state": self.programme_state,
            "reveals_used": self.reveals_used,
            "overall": self.overall,
            "checks": [c.to_dict() for c in self.checks],
            "panel": self.panel,
            "seal": self.seal,
            "lock": self.lock,
            "runtime_estimate": self.runtime_estimate,
            "missing_inputs": self.missing_inputs(),
        }


def count_work(
    config: TrialsConfig, seal: HoldoutSeal, *, n_candidates_for_reveal: int = 2
) -> dict[str, int]:
    """How many signal generations and evaluations `select` and `reveal` make.

    Mirrors the loops in `campaign.run_select` and `reveal.run_reveal`: every
    variant is generated once, every control once (or once per hypothesis when
    shared), every benchmark with a strategy once; each trial is evaluated at
    both delisting assumptions over every cost multiplier plus its control,
    and walked forward over F folds twice (train and test) at both recoveries.
    """
    folds = len(
        fold_windows(
            seal, list(config.walk_forward["test_years"]), int(config.walk_forward["embargo_days"])
        )
    )
    multipliers = len(config.common.cost_multipliers)
    signals = 0
    evaluations = 0
    for spec in config.hypotheses:
        variants = len(spec.variants)
        signals += variants + (1 if spec.control_shared else variants)
        evaluations += 2 * variants * (2 * folds + multipliers + 1)
    benchmarks_with_strategy = sum(1 for b in config.benchmarks.values() if "strategy" in b)
    signals += benchmarks_with_strategy
    evaluations += 2 * len(config.benchmarks)
    reveal_signals = 2 * n_candidates_for_reveal + benchmarks_with_strategy
    reveal_evaluations = 2 * n_candidates_for_reveal * (multipliers + 1) + 2 * len(
        config.benchmarks
    )
    return {
        "select_signal_generations": signals,
        "select_evaluations": evaluations,
        "reveal_signal_generations": reveal_signals,
        "reveal_evaluations": reveal_evaluations,
    }


def runtime_estimate(work: dict[str, int], rows: int) -> dict[str, Any]:
    scale = max(rows, 1) / REF_ROWS
    select_seconds = (
        work["select_signal_generations"] * EST_SIGNAL_SECONDS_AT_REF
        + work["select_evaluations"] * EST_EVAL_SECONDS_AT_REF
    ) * scale
    reveal_seconds = (
        work["reveal_signal_generations"] * EST_SIGNAL_SECONDS_AT_REF
        + work["reveal_evaluations"] * EST_EVAL_SECONDS_AT_REF
    ) * scale
    total = select_seconds + reveal_seconds
    return {
        "evidence_class": "ASSUMPTION",
        "basis": {
            "ref_rows": REF_ROWS,
            "signal_seconds_at_ref": EST_SIGNAL_SECONDS_AT_REF,
            "eval_seconds_at_ref": EST_EVAL_SECONDS_AT_REF,
            "measured_on": "one synthetic panel, one machine, single process",
        },
        "rows_scale": scale,
        "select": {
            "signal_generations": work["select_signal_generations"],
            "evaluations": work["select_evaluations"],
            "seconds": select_seconds,
        },
        "reveal": {
            "signal_generations": work["reveal_signal_generations"],
            "evaluations": work["reveal_evaluations"],
            "seconds": reveal_seconds,
        },
        "total_seconds": total,
        "total_human": f"{total / 60:.0f} min",
    }


def _verify_command(exp: Path, inputs: DigestInputs) -> str:
    venues = " ".join(
        f"--venue-dir {name}={path}" for name, path in sorted(inputs.venue_dirs.items())
    )
    return (
        f"quant-trade crypto-lowcap verify-panel --experiment-dir {exp} "
        f"--panel {inputs.panel_path} --universe-dir {inputs.universe_dir} "
        f"--deathlist-dir {inputs.deathlist_dir} {venues} --explain"
    )


def _recollect_hint(exp: Path) -> str:
    return (
        "re-collect per docs/CRYPTO_LOWCAP_DATASET.md § Reproduction, rebuild the panel, then "
        f"`quant-trade crypto-lowcap panel-digest --experiment-dir {exp}_rebuilt --panel ...` "
        f"and `reseal --from-dir {exp} --to-dir {exp}_rebuilt --panel ...` (runbook § 5)"
    )


def run_doctor(
    experiment_dir: str | Path,
    inputs: DigestInputs,
    trials_path: str | Path,
    *,
    at_utc: str,
) -> DoctorReport:
    exp = Path(experiment_dir)
    report = DoctorReport(experiment_dir=str(exp), generated_at_utc=at_utc)
    checks = report.checks

    # 1. seal
    seal: HoldoutSeal | None = None
    try:
        seal = load_seal(exp)
        report.seal = {
            "seal_id": seal.seal_id,
            "panel_digest": seal.dataset_digest,
            "selection_window": [seal.selection_start, seal.selection_end],
            "holdout_window": [seal.holdout_start, seal.holdout_end],
        }
        checks.append(Check("seal", PASS, f"{seal.seal_id} sealed at {seal.sealed_at_utc}"))
    except HoldoutSealError as exc:
        checks.append(Check("seal", FAIL, str(exc), _recollect_hint(exp)))

    # 2. pre-registrations
    prereg_dirs = (
        sorted(p for p in exp.iterdir() if (p / "preregistration.json").is_file())
        if exp.is_dir()
        else []
    )
    if not prereg_dirs:
        checks.append(
            Check(
                "preregistrations", FAIL, "no sealed pre-registration found", _recollect_hint(exp)
            )
        )
    for directory in prereg_dirs:
        try:
            prereg = load_preregistration(directory)
        except PreregistrationError as exc:
            checks.append(Check(f"preregistration:{directory.name}", FAIL, str(exc)))
            continue
        bound = prereg.universe[0].split("@", 1)[-1]
        if seal is not None and bound != seal.dataset_digest:
            checks.append(
                Check(
                    f"preregistration:{directory.name}",
                    FAIL,
                    "registered against a different panel digest than the seal",
                    "register the hypothesis against this seal's digest (reseal clones "
                    "declarations)",
                )
            )
        else:
            checks.append(
                Check(
                    f"preregistration:{directory.name}",
                    PASS,
                    f"max_trials {prereg.max_trials}, seal {prereg.seal()[:12]}...",
                )
            )

    # 3. panel
    rows = 0
    panel_sha = ""
    if not inputs.panel_path.is_file():
        checks.append(
            Check("panel", FAIL, f"no panel at {inputs.panel_path}", _recollect_hint(exp))
        )
    else:
        try:
            frame = load_panel(inputs.panel_path)
            days = iso_days(frame)
            rows = int(len(frame))
            panel_sha = panel_content_sha256(inputs.panel_path)
            report.panel = {
                "path": str(inputs.panel_path),
                "rows": rows,
                "symbols": int(frame["symbol"].nunique()),
                "first_day": days[0],
                "last_day": days[-1],
                "content_sha256": panel_sha,
            }
            status, detail = (
                PASS,
                f"{rows} rows, {report.panel['symbols']} symbols, {days[0]} -> {days[-1]}",
            )
            if seal is not None and days[-1] < seal.holdout_end:
                status, detail = (
                    WARN,
                    detail + f"; ends before the sealed holdout end {seal.holdout_end}",
                )
            checks.append(Check("panel", status, detail))
        except (CampaignError, ValueError) as exc:
            checks.append(Check("panel", FAIL, str(exc), _recollect_hint(exp)))

    # 4. dataset directories
    journals = {
        "universe": inputs.universe_dir,
        **{f"venue:{k}": v for k, v in sorted(inputs.venue_dirs.items())},
    }
    for name, directory in journals.items():
        path = Path(directory) / "journal.jsonl"
        if not path.is_file():
            checks.append(
                Check(f"dataset:{name}", FAIL, f"no journal at {path}", _recollect_hint(exp))
            )
            continue
        try:
            records = read_journal(path)
            verify_journal_chain(records)
            checks.append(
                Check(f"dataset:{name}", PASS, f"{len(records)} journal records, chain intact")
            )
        except (UniverseCollectorError, ValueError) as exc:
            checks.append(
                Check(f"dataset:{name}", FAIL, f"journal chain: {exc}", _recollect_hint(exp))
            )
    death = Path(inputs.deathlist_dir) / "deathlist.json"
    if death.is_file():
        checks.append(Check("dataset:deathlist", PASS, str(death)))
    else:
        checks.append(Check("dataset:deathlist", FAIL, f"no {death}", _recollect_hint(exp)))

    # 5. panel verification
    verification = exp / PANEL_VERIFICATION_FILENAME
    fix = _verify_command(exp, inputs)
    if not verification.is_file():
        checks.append(Check("verification", FAIL, "panel_verification.json absent", fix))
    else:
        payload = load_json(verification)
        problems = []
        if payload.get("status") != "PASS":
            problems.append(f"status {payload.get('status')}")
        if seal is not None and payload.get("expected_digest") != seal.dataset_digest:
            problems.append("verified against a different seal")
        if panel_sha and payload.get("panel_content_sha256") != panel_sha:
            problems.append("panel bytes changed since verification")
        if problems:
            checks.append(Check("verification", FAIL, "; ".join(problems), fix))
        else:
            checks.append(
                Check("verification", PASS, f"verified at {payload.get('verified_at_utc')}")
            )

    # 6. trials config and gates
    config: TrialsConfig | None = None
    try:
        config = load_trials_config(trials_path)
        missing_gates = [p for p in config.gate_paths().values() if not Path(p).is_file()]
        if missing_gates:
            checks.append(Check("trials_config", FAIL, f"missing gate files: {missing_gates}"))
        else:
            checks.append(
                Check(
                    "trials_config",
                    PASS,
                    f"{config.declared_trials} declared trials across {len(config.hypotheses)} "
                    f"hypotheses, sha {config.sha256[:12]}...",
                )
            )
        etf = config.deflated_sharpe.get("etf_ledger")
        if etf and not Path(etf).is_file():
            checks.append(
                Check("etf_ledger", WARN, f"{etf} absent; combined DSR will be NOT_MEASURED")
            )
    except CampaignConfigError as exc:
        checks.append(Check("trials_config", FAIL, str(exc)))

    # 7. lock
    lock = read_lock(exp) if exp.is_dir() else None
    if lock is None:
        report.lock = {"present": False}
        checks.append(Check("lock", SKIP, "no campaign lock yet; select will write it"))
    else:
        matches = config is not None and lock.get("trials_config_sha256") == config.sha256
        report.lock = {
            "present": True,
            "trials_config_sha256": lock.get("trials_config_sha256"),
            "matches_current": matches,
        }
        checks.append(
            Check(
                "lock",
                PASS if matches else WARN,
                "matches the trials file"
                if matches
                else "trials file differs from the lock; select would refuse",
            )
        )

    # 8. programme state
    state = programme_state(exp) if exp.is_dir() else "NOT_RUN"
    report.programme_state = state
    report.reveals_used = len(read_reveals(exp)) if exp.is_dir() else 0
    checks.append(Check("programme_state", PASS, f"{state}, reveals used {report.reveals_used}"))

    # 9. runtime
    if config is not None and seal is not None:
        try:
            report.runtime_estimate = runtime_estimate(count_work(config, seal), rows or REF_ROWS)
            checks.append(
                Check(
                    "runtime_estimate",
                    PASS,
                    f"about {report.runtime_estimate['total_human']} (ASSUMPTION)",
                )
            )
        except CampaignError as exc:
            checks.append(Check("runtime_estimate", WARN, str(exc)))
    return report


def doctor_exit_code(report: DoctorReport) -> int:
    return 1 if report.overall == FAIL else 0


__all__ = [
    "EST_EVAL_SECONDS_AT_REF",
    "EST_SIGNAL_SECONDS_AT_REF",
    "REF_ROWS",
    "Check",
    "DoctorReport",
    "count_work",
    "doctor_exit_code",
    "run_doctor",
    "runtime_estimate",
]
