from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from quant_trade.cloud.config import load_cloud_config
from quant_trade.cloud.health import run_health_check
from quant_trade.cloud.heartbeat import write_heartbeat
from quant_trade.cloud.jobs import _heartbeat, new_run_id, run_job
from quant_trade.cloud.kill_switch import (
    activate_kill_switch,
    clear_kill_switch,
    get_kill_switch_status,
)
from quant_trade.cloud.storage import backend_for_uri

cloud_app = typer.Typer(help="Cloud paper deployment commands (paper-only).")
kill_app = typer.Typer(help="Cloud kill switch commands.")
cloud_app.add_typer(kill_app, name="kill-switch")


@cloud_app.command("validate-config")
def validate_config(config: Annotated[Path, typer.Option(help="Cloud YAML config")]) -> None:
    cfg = load_cloud_config(config)
    typer.echo(json.dumps(cfg.to_safe_dict(), indent=2))


@cloud_app.command("run-job")
def run_job_cmd(
    config: Annotated[Path, typer.Option(help="Cloud YAML config")],
    job: Annotated[str, typer.Option(help="Cloud job name")],
) -> None:
    summary = run_job(config, job)
    typer.echo(summary.model_dump_json(indent=2))


@cloud_app.command("heartbeat")
def heartbeat_cmd(config: Annotated[Path, typer.Option(help="Cloud YAML config")]) -> None:
    cfg = load_cloud_config(config)
    hb = _heartbeat(cfg, new_run_id(), "ok")
    write_heartbeat(backend_for_uri(cfg.heartbeat_uri), cfg.heartbeat_uri, hb)
    typer.echo(hb.model_dump_json(indent=2))


@cloud_app.command("health")
def health_cmd(config: Annotated[Path, typer.Option(help="Cloud YAML config")]) -> None:
    cfg = load_cloud_config(config)
    typer.echo(json.dumps(run_health_check(cfg), indent=2))


@kill_app.command("status")
def kill_status(config: Annotated[Path, typer.Option(help="Cloud YAML config")]) -> None:
    cfg = load_cloud_config(config)
    typer.echo(get_kill_switch_status(cfg).model_dump_json(indent=2))


@kill_app.command("activate")
def kill_activate(
    config: Annotated[Path, typer.Option(help="Cloud YAML config")],
    reason: Annotated[str, typer.Option(help="Reason")],
    actor: Annotated[str, typer.Option(help="Actor")] = "manual",
) -> None:
    cfg = load_cloud_config(config)
    typer.echo(activate_kill_switch(cfg, reason, actor).model_dump_json(indent=2))


@kill_app.command("clear")
def kill_clear(
    config: Annotated[Path, typer.Option(help="Cloud YAML config")],
    reason: Annotated[str, typer.Option(help="Reason")],
    actor: Annotated[str, typer.Option(help="Actor")] = "manual",
) -> None:
    cfg = load_cloud_config(config)
    typer.echo(clear_kill_switch(cfg, reason, actor).model_dump_json(indent=2))
