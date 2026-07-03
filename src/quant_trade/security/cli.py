from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from quant_trade.security.audit_review import review_audit_logs
from quant_trade.security.config import load_yaml
from quant_trade.security.dashboard import write_dashboard
from quant_trade.security.models import ensure_output_dir
from quant_trade.security.permissions import check_config_safety
from quant_trade.security.reports import (
    compliance_markdown,
    threat_model_markdown,
    write_controls_matrix,
    write_json,
)
from quant_trade.security.secret_scan import scan_from_config

security_app = typer.Typer(help="Offline security, compliance, and audit checks.")


def _out() -> Path:
    return ensure_output_dir()


@security_app.command("scan-secrets")
def scan_secrets(config: Annotated[Path, typer.Option(help="Secret scan policy YAML")]) -> None:
    out = _out()
    report = scan_from_config(config)
    write_json(out / "secret_scan_report.json", report)
    typer.echo(f"secret_scan_status={report.status} output={out}")
    if report.status == "fail":
        raise typer.Exit(1)


@security_app.command("check-configs")
def check_configs(config: Annotated[Path, typer.Option(help="Security policy YAML")]) -> None:
    cfg = load_yaml(config)
    paths = [Path(p) for p in cfg.get("config_paths", ["configs", "deploy", ".github/workflows"])]
    out = _out()
    report = check_config_safety(paths)
    write_json(out / "config_safety_report.json", report)
    typer.echo(f"config_safety_status={report.status} output={out}")
    if report.status == "fail":
        raise typer.Exit(1)


@security_app.command("audit-review")
def audit_review(config: Annotated[Path, typer.Option(help="Audit review policy YAML")]) -> None:
    cfg = load_yaml(config)
    paths = [Path(p) for p in cfg.get("audit_paths", ["outputs", "state"])]
    out = _out()
    report = review_audit_logs(paths)
    write_json(out / "audit_review_report.json", report)
    typer.echo(f"audit_review_status={report.status} output={out}")
    if report.status == "fail":
        raise typer.Exit(1)


@security_app.command("threat-model")
def threat_model(config: Annotated[Path, typer.Option(help="Security policy YAML")]) -> None:
    _ = load_yaml(config)
    out = _out()
    (out / "threat_model.md").write_text(threat_model_markdown(), encoding="utf-8")
    typer.echo(f"threat_model={out / 'threat_model.md'}")


@security_app.command("compliance-report")
def compliance_report(config: Annotated[Path, typer.Option(help="Security policy YAML")]) -> None:
    _ = load_yaml(config)
    out = _out()
    (out / "compliance_report.md").write_text(compliance_markdown(), encoding="utf-8")
    write_controls_matrix(out / "controls_matrix.csv")
    typer.echo(f"compliance_report={out / 'compliance_report.md'}")


@security_app.command("dashboard")
def dashboard(config: Annotated[Path, typer.Option(help="Security policy YAML")]) -> None:
    _ = load_yaml(config)
    out = _out()
    write_dashboard(out / "dashboard", "paper-only")
    typer.echo(f"dashboard={out / 'dashboard/index.html'}")


@security_app.command("scan")
def scan(config: Annotated[Path, typer.Option(help="Security policy YAML")]) -> None:
    cfg = load_yaml(config)
    out = _out()
    secret_policy = cfg.get("secret_scan_policy", "configs/security/secret_scan_policy.yaml")
    secret_report = scan_from_config(Path(secret_policy))
    config_paths = cfg.get("config_paths", ["configs", "deploy", ".github/workflows"])
    config_report = check_config_safety([Path(p) for p in config_paths])
    audit_report = review_audit_logs(
        [Path(p) for p in cfg.get("audit_paths", ["outputs", "state"])]
    )
    write_json(out / "secret_scan_report.json", secret_report)
    write_json(out / "config_safety_report.json", config_report)
    write_json(out / "audit_review_report.json", audit_report)
    (out / "threat_model.md").write_text(threat_model_markdown(), encoding="utf-8")
    write_controls_matrix(out / "controls_matrix.csv")
    (out / "compliance_report.md").write_text(compliance_markdown(), encoding="utf-8")
    summary_path = out / "security_summary.md"
    summary_path.write_text("# Security Summary\n\nreal_money_ready=false\n", encoding="utf-8")
    overall_pass = secret_report.status == config_report.status == audit_report.status == "pass"
    write_dashboard(out / "dashboard", "pass" if overall_pass else "review")
    typer.echo(f"security_scan_output={out}")
    if not overall_pass:
        raise typer.Exit(1)
