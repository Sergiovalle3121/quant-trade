from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .capital_ramp import write_capital_ramp
from .checklist import write_checklist
from .dashboard import write_dashboard
from .dossier import write_dossier
from .loss_limits import write_loss_limits
from .risk_of_ruin import write_risk_of_ruin

readiness_app = typer.Typer(help="Paper-only readiness dossier commands.")


@readiness_app.command("dossier")
def dossier_cmd(config: Annotated[Path, typer.Option(help="Readiness dossier YAML")]) -> None:
    d = write_dossier(config)
    typer.echo(f"wrote dossier for {d.run_id}: {d.final_status}; real_money_ready=false")


@readiness_app.command("capital-ramp")
def capital_ramp_cmd(config: Annotated[Path, typer.Option(help="Capital ramp YAML")]) -> None:
    rows = write_capital_ramp(config)
    typer.echo(f"wrote {len(rows)} paper capital ramp rows; real_money_ready=false")


@readiness_app.command("risk-of-ruin")
def risk_of_ruin_cmd(config: Annotated[Path, typer.Option(help="Risk-of-ruin YAML")]) -> None:
    r = write_risk_of_ruin(config)
    typer.echo(
        f"drawdown breach probability={r.probability_drawdown_breach:.3f}; real_money_ready=false"
    )


@readiness_app.command("checklist")
def checklist_cmd(config: Annotated[Path, typer.Option(help="Readiness policy YAML")]) -> None:
    r = write_checklist(config)
    typer.echo(f"checklist passed={r.passed}; real_money_ready=false")


@readiness_app.command("dashboard")
def dashboard_cmd(config: Annotated[Path, typer.Option(help="Readiness dossier YAML")]) -> None:
    p = write_dashboard(config)
    typer.echo(f"wrote {p}; real_money_ready=false")


@readiness_app.command("loss-limits")
def loss_limits_cmd(config: Annotated[Path, typer.Option(help="Readiness YAML")]) -> None:
    write_loss_limits(config)
    typer.echo("wrote paper loss limits; real_money_ready=false")
