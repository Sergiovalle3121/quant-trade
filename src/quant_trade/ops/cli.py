from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from .alerts import JsonlNotifier, acknowledge_alert, load_alerts, make_alert
from .archive import apply_retention_policy, archive_run_artifacts
from .config import OpsConfig, load_ops_config
from .dashboard import generate_dashboard
from .drills import generate_drill_report, run_all_drills
from .fill_analysis import analyze_fills, generate_fill_report
from .incidents import Incident, list_incidents, save_incident, update_incident
from .inspect import inspect_run
from .inspect import inspect_session as inspect_session_payload
from .readiness import ReadinessPolicy, evaluate_ops_readiness, generate_readiness_report
from .reconciliation import generate_reconciliation_report, reconcile_broker_artifacts
from .reliability import (
    calculate_reliability_metrics,
    collect_run_summaries,
    generate_reliability_report,
)
from .reports import run_id, utc_now_iso, write_json, write_md
from .sessions import (
    PaperOpsSession,
    SessionRegistry,
    find_latest_session_artifacts,
    get_session,
    list_sessions,
    load_session_registry,
)
from .validation import generate_validation_report, validate_artifacts

ops_app = typer.Typer(help="Paper-only operations validation and monitoring.")
dashboard_app = typer.Typer(help="Static dashboard commands.")
alerts_app = typer.Typer(help="Alert commands.")
incidents_app = typer.Typer(help="Incident commands.")
drill_app = typer.Typer(help="Safety drill commands.")
ops_app.add_typer(dashboard_app, name="dashboard")
ops_app.add_typer(alerts_app, name="alerts")
ops_app.add_typer(incidents_app, name="incidents")
ops_app.add_typer(drill_app, name="drill")
console = Console()


def _load(config: Path) -> tuple[OpsConfig, SessionRegistry]:
    cfg = load_ops_config(config)
    registry = load_session_registry(cfg.session_registry_path)
    return cfg, registry


def _out(cfg: OpsConfig, rid: str) -> Path:
    return cfg.reports_output_dir / cfg.ops_name / rid


def _latest_run(session: PaperOpsSession, cfg: OpsConfig) -> Path:
    return find_latest_session_artifacts(session, cfg.artifact_roots) or Path(".missing")


def _validation_payload(
    cfg: OpsConfig, registry: SessionRegistry, rid: str
) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for session in list_sessions(registry):
        report = validate_artifacts(
            _latest_run(session, cfg),
            session.session_id,
            rid,
            cfg.max_allowed_drawdown_pct,
            cfg.max_rejected_orders_per_day,
        )
        reports.append(asdict(report))
    return reports


@ops_app.command("list-sessions")
def list_sessions_cmd(config: Annotated[Path, typer.Option()]) -> None:
    cfg, registry = _load(config)
    for session in list_sessions(registry):
        console.print(f"{session.session_id}: {session.status} ({session.display_name})")
    console.print(f"Config: {cfg.ops_name}; Paper trading / dry-run only. No live trading.")


@ops_app.command("validate")
def validate_cmd(config: Annotated[Path, typer.Option()]) -> None:
    cfg, registry = _load(config)
    rid = run_id("validation")
    out = _out(cfg, rid)
    reports = _validation_payload(cfg, registry, rid)
    write_json(out / "validation_report.json", reports)
    write_md(out / "validation_report.md", "Ops Validation Report", {"reports": reports})
    status = "fail" if any(report["status"] == "fail" for report in reports) else "pass"
    console.print(f"Status: {status} Output: {out}")


@ops_app.command("validate-session")
def validate_session_cmd(
    config: Annotated[Path, typer.Option()], session: Annotated[str, typer.Option()]
) -> None:
    cfg, registry = _load(config)
    selected = get_session(registry, session)
    rid = run_id("validation")
    out = _out(cfg, rid)
    report = validate_artifacts(
        _latest_run(selected, cfg),
        selected.session_id,
        rid,
        cfg.max_allowed_drawdown_pct,
        cfg.max_rejected_orders_per_day,
    )
    generate_validation_report(report, out)
    console.print(f"Status: {report.status} Output: {out}")


@ops_app.command("reliability")
def reliability_cmd(config: Annotated[Path, typer.Option()]) -> None:
    cfg, _ = _load(config)
    rid = run_id("reliability")
    out = _out(cfg, rid)
    summaries = collect_run_summaries([cfg.reports_output_dir, *cfg.artifact_roots])
    metrics = calculate_reliability_metrics(summaries)
    generate_reliability_report(metrics, out)
    console.print(f"Status: pass Output: {out}")


@ops_app.command("fill-analysis")
def fill_cmd(
    config: Annotated[Path, typer.Option()], session: Annotated[str, typer.Option()]
) -> None:
    cfg, registry = _load(config)
    selected = get_session(registry, session)
    rid = run_id("fills")
    out = _out(cfg, rid)
    generate_fill_report(analyze_fills(_latest_run(selected, cfg)), out)
    console.print(f"Status: pass Output: {out}")


@ops_app.command("reconcile")
def reconcile_cmd(
    config: Annotated[Path, typer.Option()], session: Annotated[str, typer.Option()]
) -> None:
    cfg, registry = _load(config)
    selected = get_session(registry, session)
    rid = run_id("reconcile")
    out = _out(cfg, rid)
    report = reconcile_broker_artifacts(_latest_run(selected, cfg))
    generate_reconciliation_report(report, out)
    console.print(f"Status: {report.status} Output: {out}")


@dashboard_app.command("generate")
def dashboard_generate(config: Annotated[Path, typer.Option()]) -> None:
    cfg, registry = _load(config)
    rid = run_id("dashboard")
    metrics = calculate_reliability_metrics(collect_run_summaries([cfg.reports_output_dir]))
    index = generate_dashboard(
        cfg.dashboard_output_dir / cfg.ops_name / rid,
        list_sessions(registry),
        {**asdict(metrics), "status": "pass"},
        load_alerts(Path("outputs/alerts/alerts.jsonl")),
        [asdict(incident) for incident in list_incidents(cfg.incident_output_dir)],
    )
    console.print(f"Status: pass Output: {index.parent}")


@dashboard_app.command("open")
def dashboard_open(config: Annotated[Path, typer.Option()]) -> None:
    cfg, _ = _load(config)
    console.print(cfg.dashboard_output_dir / cfg.ops_name)


@ops_app.command("readiness")
def readiness_cmd(
    config: Annotated[Path, typer.Option()], session: Annotated[str, typer.Option()]
) -> None:
    cfg, registry = _load(config)
    rid = run_id("readiness")
    out = _out(cfg, rid)
    selected = get_session(registry, session)
    metrics = calculate_reliability_metrics(collect_run_summaries([cfg.reports_output_dir]))
    report = evaluate_ops_readiness(
        selected,
        [],
        metrics,
        [asdict(incident) for incident in list_incidents(cfg.incident_output_dir)],
        [],
        ReadinessPolicy(),
    )
    generate_readiness_report(report, out)
    console.print(f"Status: {report.readiness_status} real_money_ready=false Output: {out}")


@drill_app.command("all")
def drill_all(config: Annotated[Path, typer.Option()]) -> None:
    cfg, _ = _load(config)
    rid = run_id("drills")
    out = _out(cfg, rid)
    results = run_all_drills(cfg)
    generate_drill_report(results, out)
    status = "pass" if all(result.status == "pass" for result in results) else "fail"
    console.print(f"Status: {status} Output: {out}")


@drill_app.command("kill-switch")
def drill_kill(config: Annotated[Path, typer.Option()]) -> None:
    drill_all(config)


@drill_app.command("stale-heartbeat")
def drill_stale(config: Annotated[Path, typer.Option()]) -> None:
    drill_all(config)


@drill_app.command("live-endpoint-rejection")
def drill_live(config: Annotated[Path, typer.Option()]) -> None:
    drill_all(config)


@ops_app.command("alert-test")
def alert_test(config: Annotated[Path, typer.Option()]) -> None:
    load_ops_config(config)
    JsonlNotifier(Path("outputs/alerts/alerts.jsonl")).notify(make_alert())
    console.print("Status: pass Output: outputs/alerts/alerts.jsonl")


@alerts_app.command("list")
def alerts_list(config: Annotated[Path, typer.Option()]) -> None:
    load_ops_config(config)
    console.print(json.dumps(load_alerts(Path("outputs/alerts/alerts.jsonl")), indent=2))


@alerts_app.command("acknowledge")
def alerts_ack(
    alert_id: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()],
    notes: Annotated[str, typer.Option()] = "reviewed",
) -> None:
    load_ops_config(config)
    acknowledge_alert(alert_id, notes, Path("outputs/alerts/acknowledgements.jsonl"))
    console.print("Status: pass Output: outputs/alerts/acknowledgements.jsonl")


@incidents_app.command("list")
def incidents_list(config: Annotated[Path, typer.Option()]) -> None:
    cfg, _ = _load(config)
    console.print(
        json.dumps([asdict(incident) for incident in list_incidents(cfg.incident_output_dir)])
    )


@incidents_app.command("create")
def incidents_create(
    config: Annotated[Path, typer.Option()],
    title: Annotated[str, typer.Option()],
    severity: Annotated[str, typer.Option()] = "warning",
) -> None:
    cfg, _ = _load(config)
    incident = Incident(
        f"incident_{run_id()}",
        utc_now_iso(),
        utc_now_iso(),
        "manual",
        severity,
        "open",
        title,
        title,
    )
    save_incident(cfg.incident_output_dir, incident)
    console.print(f"Status: pass Output: {cfg.incident_output_dir}")


@incidents_app.command("resolve")
def incidents_resolve(
    config: Annotated[Path, typer.Option()],
    incident_id: Annotated[str, typer.Option()],
    notes: Annotated[str, typer.Option()] = "resolved",
) -> None:
    cfg, _ = _load(config)
    update_incident(cfg.incident_output_dir, incident_id, "resolved", notes)
    console.print("Status: pass")


@ops_app.command("inspect-run")
def inspect_run_cmd(run_dir: Annotated[Path, typer.Option()]) -> None:
    console.print_json(data=inspect_run(run_dir))


@ops_app.command("inspect-session")
def inspect_session_cmd(
    config: Annotated[Path, typer.Option()], session: Annotated[str, typer.Option()]
) -> None:
    cfg, registry = _load(config)
    selected = get_session(registry, session)
    console.print_json(
        data=inspect_session_payload(
            selected, find_latest_session_artifacts(selected, cfg.artifact_roots)
        )
    )


@ops_app.command("archive")
def archive_cmd(
    config: Annotated[Path, typer.Option()], run_dir: Annotated[Path, typer.Option()]
) -> None:
    cfg, _ = _load(config)
    path = archive_run_artifacts(run_dir, cfg.archive_output_dir)
    console.print(f"Status: pass Output: {path}")


@ops_app.command("retention-plan")
def retention_plan(config: Annotated[Path, typer.Option()]) -> None:
    cfg, _ = _load(config)
    console.print_json(data=apply_retention_policy(cfg.reports_output_dir, 10, 30, False))


@ops_app.command("retention-apply")
def retention_apply(
    config: Annotated[Path, typer.Option()], confirm_delete: Annotated[bool, typer.Option()] = False
) -> None:
    cfg, _ = _load(config)
    console.print_json(data=apply_retention_policy(cfg.reports_output_dir, 10, 30, confirm_delete))


@ops_app.command("run-cycle")
def run_cycle(config: Annotated[Path, typer.Option()]) -> None:
    cfg, registry = _load(config)
    rid = run_id("cycle")
    out = _out(cfg, rid)
    sessions = list_sessions(registry)
    validation = _validation_payload(cfg, registry, rid)
    metrics = calculate_reliability_metrics(collect_run_summaries([cfg.reports_output_dir]))
    generate_reliability_report(metrics, out)

    if sessions:
        latest = _latest_run(sessions[0], cfg)
        generate_fill_report(analyze_fills(latest), out)
        generate_reconciliation_report(reconcile_broker_artifacts(latest), out)
        readiness = evaluate_ops_readiness(
            sessions[0], validation, metrics, [], run_all_drills(cfg), ReadinessPolicy()
        )
        generate_readiness_report(readiness, out)

    dashboard_dir = cfg.dashboard_output_dir / cfg.ops_name / rid
    generate_dashboard(dashboard_dir, sessions, {**asdict(metrics), "status": "pass"})
    summary = {
        "run_id": rid,
        "sessions": [session.session_id for session in sessions],
        "validation": validation,
        "dashboard": str(dashboard_dir),
        "real_money_ready": False,
    }
    write_json(out / "cycle_summary.json", summary)
    write_md(out / "cycle_summary.md", "Ops Cycle Summary", summary)
    console.print(f"Status: pass Output: {out}")
