from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from quant_trade.approvals.config import load_workflow_config
from quant_trade.approvals.dashboard import write_dashboard
from quant_trade.approvals.models import ApprovalRequestType
from quant_trade.approvals.policy import evaluate_request
from quant_trade.approvals.reports import write_summary
from quant_trade.approvals.requests import create_request, get_request, load_requests, save_request
from quant_trade.approvals.reviewers import approve_request, reject_request

approvals_app = typer.Typer(help="Local human approval workflow and control gates.")
console = Console()


def _cfg(path: Path):
    return load_workflow_config(path)


@approvals_app.command("request")
def request_approval(
    request_type: Annotated[ApprovalRequestType, typer.Option("--type")],
    title: Annotated[str, typer.Option()],
    evidence_path: Annotated[list[Path] | None, typer.Option("--evidence-path")] = None,
    config: Annotated[Path, typer.Option()] = Path(
        "configs/approvals/approval_workflow_local.yaml"
    ),
    explicit_paper_only: Annotated[bool, typer.Option("--explicit-paper-only")] = False,
    explicit_delete_confirmed: Annotated[bool, typer.Option("--explicit-delete-confirmed")] = False,
) -> None:
    cfg = _cfg(config)
    req = create_request(request_type, title, [str(p) for p in evidence_path or []], cfg)
    req.explicit_paper_only = explicit_paper_only
    req.explicit_delete_confirmed = explicit_delete_confirmed
    save_request(req, cfg, "updated_request_controls")
    console.print(json.dumps(req.to_json_dict(), indent=2))
    console.print(f"Output path: {cfg.artifact_dir}")


@approvals_app.command("list")
def list_approvals(
    config: Annotated[Path, typer.Option()] = Path(
        "configs/approvals/approval_workflow_local.yaml"
    ),
) -> None:
    cfg = _cfg(config)
    table = Table(title="Local paper-only approvals")
    for col in ["ID", "Type", "Status", "Real money approved"]:
        table.add_column(col)
    for req in load_requests(cfg):
        table.add_row(req.approval_id, req.request_type.value, req.status.value, "false")
    console.print(table)


@approvals_app.command("show")
def show_approval(
    approval_id: Annotated[str, typer.Option("--approval-id")],
    config: Annotated[Path, typer.Option()] = Path(
        "configs/approvals/approval_workflow_local.yaml"
    ),
) -> None:
    console.print(json.dumps(get_request(_cfg(config), approval_id).to_json_dict(), indent=2))


@approvals_app.command("approve")
def approve_approval(
    approval_id: Annotated[str, typer.Option("--approval-id")],
    reviewer: Annotated[str, typer.Option()],
    notes: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()] = Path(
        "configs/approvals/approval_workflow_local.yaml"
    ),
) -> None:
    cfg = _cfg(config)
    req = approve_request(get_request(cfg, approval_id), reviewer, notes)
    save_request(req, cfg, "approved" if req.status.value == "approved" else "approval_blocked")
    console.print(json.dumps(req.to_json_dict(), indent=2))


@approvals_app.command("reject")
def reject_approval(
    approval_id: Annotated[str, typer.Option("--approval-id")],
    reviewer: Annotated[str, typer.Option()],
    notes: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()] = Path(
        "configs/approvals/approval_workflow_local.yaml"
    ),
) -> None:
    cfg = _cfg(config)
    req = reject_request(get_request(cfg, approval_id), reviewer, notes)
    save_request(req, cfg, "rejected")
    console.print(json.dumps(req.to_json_dict(), indent=2))


@approvals_app.command("verify")
def verify_approval_cmd(
    approval_id: Annotated[str, typer.Option("--approval-id")],
    config: Annotated[Path, typer.Option()] = Path(
        "configs/approvals/approval_workflow_local.yaml"
    ),
) -> None:
    req = evaluate_request(get_request(_cfg(config), approval_id))
    ok = req.status.value == "approved" and not req.blocking_issues and not req.real_money_approved
    console.print(
        json.dumps(
            {
                "approval_id": approval_id,
                "valid": ok,
                "status": req.status.value,
                "blocking_issues": req.blocking_issues,
                "real_money_approved": False,
            },
            indent=2,
        )
    )
    if not ok:
        raise typer.Exit(1)


@approvals_app.command("dashboard")
def dashboard_cmd(
    config: Annotated[Path, typer.Option()] = Path(
        "configs/approvals/approval_workflow_local.yaml"
    ),
) -> None:
    cfg = _cfg(config)
    reqs = load_requests(cfg)
    write_summary(cfg.artifact_dir / "approval_summary.md", reqs)
    out = write_dashboard(cfg.artifact_dir / "dashboard", reqs)
    console.print(f"Output path: {out / 'index.html'}")
