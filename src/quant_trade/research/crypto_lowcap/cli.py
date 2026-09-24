"""``quant-trade crypto-lowcap``: verify, select, reveal, report, reseal.

What this interface lacks is deliberate. There is no flag that skips panel
verification, none that lowers a gate, none that re-opens a revealed holdout,
and none that runs a selection twice into the same experiment. Each absence
closes a way a previous sprint's numbers were made to look better than the
evidence supported.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from quant_trade.evidence.canonical_json import atomic_write_json, load_json

crypto_lowcap_app = typer.Typer(
    help="Low/mid-cap crypto campaign: sealed hypotheses, one holdout reveal. Research-only."
)

DEFAULT_EXPERIMENT_DIR = "data/experiments/crypto_lowcap_2026_08"
DEFAULT_TRIALS = "configs/research/crypto_lowcap_trials.yaml"
DEFAULT_UNIVERSE_DIR = "data/cache/crypto_universe/v1"
DEFAULT_DEATHLIST_DIR = "data/cache/crypto_universe/deathlist"
DEFAULT_VENUE_DIRS = (
    "bybit=data/cache/venue_klines/bybit",
    "binance=data/cache/venue_klines/binance",
)


def _now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _echo(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _code_sha(value: str | None) -> str:
    from quant_trade.research.ledger import resolve_code_sha

    return value or resolve_code_sha()


def _venue_dirs(values: list[str]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for item in values:
        if "=" not in item:
            raise typer.BadParameter(f"--venue-dir expects name=path, got {item!r}")
        name, path = item.split("=", 1)
        out[name.strip()] = Path(path.strip())
    return out


@crypto_lowcap_app.callback()
def _main() -> None:
    """Keep `crypto-lowcap` a command group."""


@crypto_lowcap_app.command("verify-panel")
def verify_panel(
    experiment_dir: Annotated[Path, typer.Option(help="Sealed experiment directory")] = Path(
        DEFAULT_EXPERIMENT_DIR
    ),
    panel: Annotated[Path | None, typer.Option(help="Built panel (.csv.gz/.csv/.parquet)")] = None,
    universe_dir: Annotated[Path, typer.Option(help="Point-in-time universe dir")] = Path(
        DEFAULT_UNIVERSE_DIR
    ),
    deathlist_dir: Annotated[Path, typer.Option(help="External death-list dir")] = Path(
        DEFAULT_DEATHLIST_DIR
    ),
    venue_dir: Annotated[list[str] | None, typer.Option(help="name=path, repeatable")] = None,
    build_report: Annotated[Path | None, typer.Option(help="panel_build_report.json")] = None,
    explain: Annotated[bool, typer.Option(help="Print every candidate recipe hash")] = False,
    at_utc: Annotated[str | None, typer.Option(help="Timestamp to record")] = None,
) -> None:
    """Reproduce the sealed panel digest from bytes on disk. Fails closed."""
    from quant_trade.data.panel_digest import DigestInputs, verify_panel_digest
    from quant_trade.research.crypto_lowcap.campaign import record_panel_verification

    panel_path = panel or experiment_dir / "panel.csv.gz"
    inputs = DigestInputs(
        universe_dir=universe_dir,
        venue_dirs=_venue_dirs(list(venue_dir or DEFAULT_VENUE_DIRS)),
        deathlist_dir=deathlist_dir,
        build_report_path=build_report or experiment_dir / "panel_build_report.json",
        panel_path=panel_path,
    )
    verification = verify_panel_digest(experiment_dir, inputs, explain=explain)
    payload = record_panel_verification(
        experiment_dir, verification, panel_path=panel_path, at_utc=at_utc or _now_utc()
    )
    if explain:
        payload = {**payload, "probe": verification.probe}
    _echo(payload)
    if verification.status != "PASS":
        raise typer.Exit(code=1)


@crypto_lowcap_app.command("panel-digest")
def panel_digest(
    experiment_dir: Annotated[Path, typer.Option(help="Target experiment directory (new)")],
    panel: Annotated[Path, typer.Option(help="Built panel to digest")],
    universe_dir: Annotated[Path, typer.Option()] = Path(DEFAULT_UNIVERSE_DIR),
    deathlist_dir: Annotated[Path, typer.Option()] = Path(DEFAULT_DEATHLIST_DIR),
    venue_dir: Annotated[list[str] | None, typer.Option(help="name=path, repeatable")] = None,
    build_report: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Write a panel digest that declares its recipe (v2), for a new seal."""
    from quant_trade.data.panel_digest import DigestInputs, write_panel_digest
    from quant_trade.research.crypto_lowcap.campaign import iso_days, load_panel

    frame = load_panel(panel)
    days = iso_days(frame)
    inputs = DigestInputs(
        universe_dir=universe_dir,
        venue_dirs=_venue_dirs(list(venue_dir or DEFAULT_VENUE_DIRS)),
        deathlist_dir=deathlist_dir,
        build_report_path=build_report or experiment_dir / "panel_build_report.json",
        panel_path=panel,
    )
    payload = write_panel_digest(
        experiment_dir,
        inputs,
        rows=int(len(frame)),
        symbols=int(frame["symbol"].nunique()),
        window=(days[0], days[-1]),
    )
    _echo(payload)


@crypto_lowcap_app.command("select")
def select(
    experiment_dir: Annotated[Path, typer.Option()] = Path(DEFAULT_EXPERIMENT_DIR),
    trials: Annotated[Path, typer.Option(help="Declared trial grid YAML")] = Path(DEFAULT_TRIALS),
    panel: Annotated[Path | None, typer.Option()] = None,
    evaluated_at_utc: Annotated[str | None, typer.Option()] = None,
    code_sha: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Run every declared trial over the selection window and freeze at most one candidate."""
    from quant_trade.research.crypto_lowcap.campaign import run_select

    results = run_select(
        experiment_dir,
        trials,
        panel or experiment_dir / "panel.csv.gz",
        evaluated_at_utc=evaluated_at_utc or _now_utc(),
        code_sha=_code_sha(code_sha),
    )
    _echo(
        {
            "trials": len(results["trials"]),
            "frozen": results["frozen"],
            "deflated_sharpe": results["deflated_sharpe"],
            "results": str(experiment_dir / "selection" / "SELECTION_RESULTS.json"),
        }
    )


@crypto_lowcap_app.command("reveal")
def reveal(
    reason: Annotated[str, typer.Option(help="Why the holdout is being read, recorded forever")],
    experiment_dir: Annotated[Path, typer.Option()] = Path(DEFAULT_EXPERIMENT_DIR),
    panel: Annotated[Path | None, typer.Option()] = None,
    evaluated_at_utc: Annotated[str | None, typer.Option()] = None,
    code_sha: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Read the holdout exactly once, for the frozen candidates only."""
    from quant_trade.research.crypto_lowcap.reveal import run_reveal

    verdict = run_reveal(
        experiment_dir,
        panel or experiment_dir / "panel.csv.gz",
        reason=reason,
        evaluated_at_utc=evaluated_at_utc or _now_utc(),
        code_sha=_code_sha(code_sha),
    )
    _echo({k: v for k, v in verdict.items() if k not in ("candidates", "benchmarks")})


@crypto_lowcap_app.command("report")
def report(
    experiment_dir: Annotated[Path, typer.Option()] = Path(DEFAULT_EXPERIMENT_DIR),
    output: Annotated[Path, typer.Option()] = Path("docs/CRYPTO_LOWCAP_RESULTS.md"),
) -> None:
    """Render the results document from the artifacts. Refuses profit language."""
    from quant_trade.research.crypto_lowcap.report import programme_state, write_report

    path = write_report(experiment_dir, output)
    _echo({"state": programme_state(experiment_dir), "written": str(path)})


@crypto_lowcap_app.command("reseal")
def reseal(
    from_dir: Annotated[Path, typer.Option(help="Experiment whose declarations to clone")],
    to_dir: Annotated[Path, typer.Option(help="New experiment dir holding panel_digest.json")],
    panel: Annotated[Path, typer.Option(help="The rebuilt panel, for the 70/30 split")],
    seal_id: Annotated[str | None, typer.Option(help="Defaults to the directory name")] = None,
    at_utc: Annotated[str | None, typer.Option()] = None,
    code_sha: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Seal a rebuilt panel under a NEW seal id, cloning the hypotheses verbatim.

    The old seal is never edited. A panel that does not reproduce the sealed
    digest is a different dataset, and a different dataset gets its own seal,
    its own pre-registrations and its own budget.
    """
    from quant_trade.data.panel_digest import load_panel_digest
    from quant_trade.research.crypto_lowcap.campaign import iso_days, load_panel
    from quant_trade.research.holdout_seal import HoldoutSeal, load_seal, seal_holdout
    from quant_trade.research.preregistration import (
        ExperimentPreregistration,
        load_preregistration,
        seal_preregistration,
    )

    stamp = at_utc or _now_utc()
    commit = _code_sha(code_sha)
    old_seal = load_seal(from_dir)
    digest = load_panel_digest(to_dir)
    new_digest = str(digest["digest"])
    days = iso_days(load_panel(panel))
    cut = max(1, int(len(days) * 0.7))
    if cut >= len(days):
        raise typer.BadParameter("panel too short to split 70/30")
    new_id = seal_id or to_dir.name
    seal = HoldoutSeal(
        seal_id=new_id,
        dataset_id=old_seal.dataset_id,
        dataset_digest=new_digest,
        selection_start=days[0],
        selection_end=days[cut - 1],
        holdout_start=days[cut],
        holdout_end=days[-1],
        rationale=old_seal.rationale,
        sealed_at_utc=stamp,
        sealed_at_commit=commit,
        notes=[*old_seal.notes, f"resealed from {old_seal.seal_id} ({old_seal.seal()[:12]}...)"],
    )
    _, seal_digest = seal_holdout(to_dir, seal)
    cloned: list[dict[str, Any]] = []
    for prereg_dir in sorted(
        p for p in Path(from_dir).iterdir() if (p / "preregistration.json").is_file()
    ):
        old = load_preregistration(prereg_dir)
        universe = [f"{old.universe[0].split('@', 1)[0]}@{new_digest}", *old.universe[1:]]
        criterion = json.loads(json.dumps(old.selection_criterion))
        holdout = criterion.get("holdout")
        if isinstance(holdout, dict):
            holdout["holdout_window"] = [seal.holdout_start, seal.holdout_end]
            holdout["selection_window"] = [seal.selection_start, seal.selection_end]
        new = ExperimentPreregistration(
            experiment_id=old.experiment_id,
            hypothesis=old.hypothesis,
            universe=universe,
            start_date=days[0],
            end_date=days[-1],
            selection_criterion=criterion,
            max_trials=old.max_trials,
            refutation=old.refutation,
            registered_at_utc=stamp,
            registered_at_commit=commit,
            notes=[*old.notes, f"cloned verbatim from {old.experiment_id}@{old.seal()[:12]}..."],
        )
        _, new_seal = seal_preregistration(to_dir / prereg_dir.name, new)
        cloned.append({"experiment_id": old.experiment_id, "seal": new_seal})
    _echo(
        {
            "seal_id": new_id,
            "seal": seal_digest,
            "panel_digest": new_digest,
            "preregistrations": cloned,
        }
    )


def _majors_declaration(
    raw: dict[str, Any],
    *,
    sha: str,
    days: list[str],
    cut: int,
    stamp: str,
    commit: str,
) -> Any:
    from quant_trade.research.preregistration import ExperimentPreregistration

    universe = [f"crypto_majors_kraken_daily@{sha}", *[str(u) for u in raw["universe"][1:]]]
    criterion = dict(raw["selection_criterion"])
    criterion["holdout"] = {
        "selection_window": [days[0], days[cut - 1]],
        "holdout_window": [days[cut], days[-1]],
        "seal": "quant_trade.research.holdout_seal",
        "revealed": "once, after selection is frozen",
    }
    criterion["variants"] = raw["variants"]
    return ExperimentPreregistration(
        experiment_id=str(raw["experiment_id"]),
        hypothesis=str(raw["hypothesis"]).strip(),
        universe=universe,
        start_date=days[0],
        end_date=days[-1],
        selection_criterion=criterion,
        max_trials=int(raw["max_trials"]),
        refutation=str(raw["refutation"]).strip(),
        registered_at_utc=stamp,
        registered_at_commit=commit,
        notes=[str(n) for n in raw.get("notes", [])],
    )


DEFAULT_MAJORS_DECLARATIONS = (
    "configs/research/crypto_majors_trend_preregistration.yaml",
    "configs/research/crypto_majors_voltarget_preregistration.yaml",
)


@crypto_lowcap_app.command("seal-majors")
def seal_majors(
    data_path: Annotated[Path, typer.Option(help="The fetched canonical CSV")],
    experiment_dir: Annotated[Path, typer.Option(help="New experiment dir (must not exist)")],
    declaration: Annotated[
        list[Path] | None, typer.Option(help="Unsealed declaration YAML, repeatable")
    ] = None,
    train_fraction: Annotated[float, typer.Option(help="Same cut as the research config")] = 0.7,
    at_utc: Annotated[str | None, typer.Option()] = None,
    code_sha: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Seal the majors declarations (H6, H8) and one holdout against the CSV's sha256.

    The declarations are committed unsealed because a seal must bind to bytes
    and only a machine with egress has them. This binds them: the CSV's sha256
    enters every universe line, the 70/30 cut is the research config's, and
    the holdout seal's dataset digest is computed over that same sha256. Each
    declaration is sealed under its own experiment_id, the low-cap layout.
    """
    import pandas as pd
    import yaml

    from quant_trade.data.manifest import file_sha256
    from quant_trade.research.holdout_seal import HoldoutSeal, dataset_digest, seal_holdout
    from quant_trade.research.preregistration import seal_preregistration

    if experiment_dir.exists():
        raise typer.BadParameter(f"{experiment_dir} exists; a seal is never written over one")
    if not data_path.is_file():
        raise typer.BadParameter(f"no dataset at {data_path}")
    declarations = [Path(p) for p in (declaration or DEFAULT_MAJORS_DECLARATIONS)]
    stamp = at_utc or _now_utc()
    commit = _code_sha(code_sha)
    sha = file_sha256(data_path)
    frame = pd.read_csv(data_path, usecols=["timestamp"])
    days = sorted({str(pd.Timestamp(v).date()) for v in frame["timestamp"]})
    cut = int(len(days) * train_fraction)
    if cut <= 0 or cut >= len(days):
        raise typer.BadParameter("dataset too short to split")
    sealed: list[dict[str, Any]] = []
    for path in declarations:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        prereg = _majors_declaration(raw, sha=sha, days=days, cut=cut, stamp=stamp, commit=commit)
        target = experiment_dir / prereg.experiment_id
        _, prereg_seal = seal_preregistration(target, prereg)
        sealed.append(
            {"experiment_id": prereg.experiment_id, "seal": prereg_seal, "path": str(target)}
        )
    components = {"dataset/csv": sha}
    seal = HoldoutSeal(
        seal_id=experiment_dir.name,
        dataset_id="crypto_majors_kraken_daily",
        dataset_digest=dataset_digest(components),
        selection_start=days[0],
        selection_end=days[cut - 1],
        holdout_start=days[cut],
        holdout_end=days[-1],
        rationale=(
            f"{train_fraction:.0%} chronological on unique timestamps, the cut the research "
            "config uses; the last 30% is reserved and revealed once. Crypto cycles run about "
            "four years, so the holdout may hold one regime only; the verdict is a range."
        ),
        sealed_at_utc=stamp,
        sealed_at_commit=commit,
        notes=[f"dataset {data_path} sha256 {sha}"],
    )
    _, holdout_seal = seal_holdout(experiment_dir, seal)
    atomic_write_json(
        experiment_dir / "dataset_binding.json",
        {
            "data_path": str(data_path),
            "data_sha256": sha,
            "components": components,
            "preregistrations": sealed,
        },
    )
    _echo(
        {
            "experiment_dir": str(experiment_dir),
            "preregistrations": sealed,
            "holdout_seal": holdout_seal,
            "data_sha256": sha,
            "selection_window": [days[0], days[cut - 1]],
            "holdout_window": [days[cut], days[-1]],
        }
    )


def _inputs(
    experiment_dir: Path,
    panel: Path | None,
    universe_dir: Path,
    deathlist_dir: Path,
    venue_dir: list[str] | None,
    build_report: Path | None,
) -> Any:
    from quant_trade.data.panel_digest import DigestInputs

    return DigestInputs(
        universe_dir=universe_dir,
        venue_dirs=_venue_dirs(list(venue_dir or DEFAULT_VENUE_DIRS)),
        deathlist_dir=deathlist_dir,
        build_report_path=build_report or experiment_dir / "panel_build_report.json",
        panel_path=panel or experiment_dir / "panel.csv.gz",
    )


@crypto_lowcap_app.command("doctor")
def doctor(
    experiment_dir: Annotated[Path, typer.Option()] = Path(DEFAULT_EXPERIMENT_DIR),
    trials: Annotated[Path, typer.Option()] = Path(DEFAULT_TRIALS),
    panel: Annotated[Path | None, typer.Option()] = None,
    universe_dir: Annotated[Path, typer.Option()] = Path(DEFAULT_UNIVERSE_DIR),
    deathlist_dir: Annotated[Path, typer.Option()] = Path(DEFAULT_DEATHLIST_DIR),
    venue_dir: Annotated[list[str] | None, typer.Option(help="name=path, repeatable")] = None,
    build_report: Annotated[Path | None, typer.Option()] = None,
    at_utc: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Read-only pre-flight: what is missing, what would refuse, how long it takes."""
    from quant_trade.research.crypto_lowcap.doctor import doctor_exit_code, run_doctor

    inputs = _inputs(experiment_dir, panel, universe_dir, deathlist_dir, venue_dir, build_report)
    report = run_doctor(experiment_dir, inputs, trials, at_utc=at_utc or _now_utc())
    _echo(report.to_dict())
    raise typer.Exit(code=doctor_exit_code(report))


@crypto_lowcap_app.command("run-all")
def run_all_command(
    reason: Annotated[str, typer.Option(help="Recorded if the holdout is revealed")] = "",
    experiment_dir: Annotated[Path, typer.Option()] = Path(DEFAULT_EXPERIMENT_DIR),
    trials: Annotated[Path, typer.Option()] = Path(DEFAULT_TRIALS),
    panel: Annotated[Path | None, typer.Option()] = None,
    universe_dir: Annotated[Path, typer.Option()] = Path(DEFAULT_UNIVERSE_DIR),
    deathlist_dir: Annotated[Path, typer.Option()] = Path(DEFAULT_DEATHLIST_DIR),
    venue_dir: Annotated[list[str] | None, typer.Option(help="name=path, repeatable")] = None,
    build_report: Annotated[Path | None, typer.Option()] = None,
    output: Annotated[Path, typer.Option()] = Path("docs/CRYPTO_LOWCAP_RESULTS.md"),
    dry_run: Annotated[bool, typer.Option(help="Print the steps and run nothing")] = False,
    evaluated_at_utc: Annotated[str | None, typer.Option()] = None,
    code_sha: Annotated[str | None, typer.Option()] = None,
) -> None:
    """verify-panel, select, reveal, report: only the steps still missing."""
    from quant_trade.research.crypto_lowcap.orchestrate import run_all

    inputs = _inputs(experiment_dir, panel, universe_dir, deathlist_dir, venue_dir, build_report)
    result = run_all(
        experiment_dir,
        inputs,
        trials,
        reason=reason,
        output=output,
        dry_run=dry_run,
        at_utc=evaluated_at_utc or _now_utc(),
        code_sha=_code_sha(code_sha),
    )
    for step in result["steps"]:
        typer.echo(f"{step['name']:<14} {step['status']:<8} {step['detail']}")
    _echo(result)
    if result["failed_step"]:
        raise typer.Exit(code=1)


@crypto_lowcap_app.command("horizon")
def horizon(
    capital: Annotated[float, typer.Option(help="Starting capital, USD")],
    target: Annotated[float, typer.Option(help="Target wealth, USD")],
    experiment_dir: Annotated[Path, typer.Option()] = Path(DEFAULT_EXPERIMENT_DIR),
    monthly_contribution: Annotated[float, typer.Option()] = 0.0,
    years: Annotated[int, typer.Option()] = 30,
    samples: Annotated[int, typer.Option()] = 2000,
    seed: Annotated[int, typer.Option()] = 20260921,
    assume_annual_return: Annotated[
        float | None, typer.Option(help="ASSUMPTION; with volatility")
    ] = None,
    assume_annual_volatility: Annotated[
        float | None, typer.Option(help="ASSUMPTION; with return")
    ] = None,
    at_utc: Annotated[str | None, typer.Option()] = None,
    code_sha: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Years to a target from the revealed holdout, as a distribution with its limits."""
    from quant_trade.research.crypto_lowcap.horizon import run_horizon

    payload = run_horizon(
        experiment_dir,
        capital=capital,
        target=target,
        monthly_contribution=monthly_contribution,
        years=years,
        samples=samples,
        seed=seed,
        assume_annual_return=assume_annual_return,
        assume_annual_volatility=assume_annual_volatility,
        at_utc=at_utc or _now_utc(),
        code_sha=_code_sha(code_sha),
    )
    _echo({k: v for k, v in payload.items() if k != "declared_limits"})


@crypto_lowcap_app.command("majors-overlap")
def majors_overlap(
    candidate_run: Annotated[Path, typer.Option(help="H8 research run directory")],
    reference_run: Annotated[Path, typer.Option(help="H6 research run directory")],
    threshold: Annotated[float, typer.Option()] = 0.9,
    output: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """H8's declared subsumption test against the frozen H6 candidate."""
    from quant_trade.research.crypto_lowcap.majors import overlap

    payload = overlap(candidate_run, reference_run, threshold=threshold)
    if output is not None:
        atomic_write_json(output, payload)
    _echo(payload)


@crypto_lowcap_app.command("paper-plan")
def paper_plan(
    capital_usd: Annotated[float, typer.Option(help="Paper capital for the first plan")],
    as_of: Annotated[str, typer.Option(help="YYYY-MM-DD; must follow the sealed holdout end")],
    experiment_dir: Annotated[Path, typer.Option()] = Path(DEFAULT_EXPERIMENT_DIR),
    panel: Annotated[Path | None, typer.Option(help="A panel extended past the holdout")] = None,
    state_dir: Annotated[Path, typer.Option()] = Path("data/paper/crypto_lowcap"),
    at_utc: Annotated[str | None, typer.Option()] = None,
    code_sha: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Write the next rebalance ticket for the frozen candidate. Places no order."""
    from quant_trade.research.crypto_lowcap.paper_bridge import plan_rebalance

    plan = plan_rebalance(
        experiment_dir,
        panel or experiment_dir / "panel.csv.gz",
        capital_usd=capital_usd,
        as_of=as_of,
        state_dir=state_dir,
        at_utc=at_utc or _now_utc(),
        code_sha=_code_sha(code_sha),
    )
    _echo({k: v for k, v in plan.items() if k not in ("holdings_before", "achieved_weights")})


@crypto_lowcap_app.command("paper-record")
def paper_record(
    plan: Annotated[Path, typer.Option(help="The plan JSON written by paper-plan")],
    fills: Annotated[Path, typer.Option(help="Operator-authored fills JSON")],
    state_dir: Annotated[Path, typer.Option()] = Path("data/paper/crypto_lowcap"),
    at_utc: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Reconcile reported fills against a plan and journal them."""
    from quant_trade.research.crypto_lowcap.paper_bridge import record_fills

    _echo(record_fills(state_dir, plan, fills, at_utc=at_utc or _now_utc()))


@crypto_lowcap_app.command("paper-status")
def paper_status_command(
    state_dir: Annotated[Path, typer.Option()] = Path("data/paper/crypto_lowcap"),
    now_utc: Annotated[str | None, typer.Option()] = None,
) -> None:
    """The low-frequency paper gate, from the journal alone. Never approves real money."""
    from quant_trade.research.crypto_lowcap.paper_bridge import STATUS_BROKEN, paper_status

    payload = paper_status(state_dir, now_utc=now_utc or _now_utc())
    _echo(payload)
    if payload["status"] == STATUS_BROKEN:
        raise typer.Exit(code=1)


@crypto_lowcap_app.command("status")
def status(
    experiment_dir: Annotated[Path, typer.Option()] = Path(DEFAULT_EXPERIMENT_DIR),
) -> None:
    """Where the programme stands, from the artifacts alone."""
    from quant_trade.research.crypto_lowcap.campaign import FROZEN_FILENAME
    from quant_trade.research.crypto_lowcap.report import programme_state
    from quant_trade.research.holdout_seal import read_reveals

    frozen_path = experiment_dir / FROZEN_FILENAME
    _echo(
        {
            "state": programme_state(experiment_dir),
            "reveals_used": len(read_reveals(experiment_dir)),
            "frozen": load_json(frozen_path).get("primary") if frozen_path.is_file() else None,
        }
    )


__all__ = ["crypto_lowcap_app"]
