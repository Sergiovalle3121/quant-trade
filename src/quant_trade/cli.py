"""Command line interface for research backtests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.table import Table

from quant_trade.backtest.engine import BacktestEngine
from quant_trade.cloud.entrypoint import cloud_app
from quant_trade.config import get_settings
from quant_trade.data.cache import list_cache, write_cache
from quant_trade.data.csv_loader import load_ohlcv_csv
from quant_trade.data.providers import get_data_provider
from quant_trade.data.quality import generate_quality_report
from quant_trade.data.requests import HistoricalDataRequest
from quant_trade.data.validation import validate_ohlcv
from quant_trade.logging_config import configure_logging
from quant_trade.ops.cli import ops_app
from quant_trade.research.experiment_config import load_experiment_config
from quant_trade.research.grid_search import run_grid_search
from quant_trade.research.runner import run_experiment
from quant_trade.research.walk_forward import run_walk_forward
from quant_trade.strategies import STRATEGY_REGISTRY, get_strategy

app = typer.Typer(help="Research-only quantitative trading tooling.")
data_app = typer.Typer(help="Historical data ingestion and validation.")
research_app = typer.Typer(help="Multi-asset research lab commands.")
selection_app = typer.Typer(help="Strategy candidate selection commands.")
paper_app = typer.Typer(help="Local simulated paper-trading commands.")
broker_app = typer.Typer(help="Safe paper broker integration commands.")

app.add_typer(data_app, name="data")
app.add_typer(research_app, name="research")
app.add_typer(selection_app, name="selection")
app.add_typer(paper_app, name="paper")
app.add_typer(broker_app, name="broker")
app.add_typer(cloud_app, name="cloud")
app.add_typer(ops_app, name="ops")
console = Console()


def _strategy_help() -> str:
    return "Strategy name: " + ", ".join(sorted(STRATEGY_REGISTRY))


def _print_metrics(
    title: str,
    strategy_name: str,
    initial_cash: float,
    final_equity: float,
    metrics,
):
    table = Table(title=title)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Strategy", strategy_name)
    table.add_row("Initial cash", f"${initial_cash:,.2f}")
    table.add_row("Final equity", f"${final_equity:,.2f}")
    table.add_row("Total return", f"{metrics['total_return']:.2%}")
    table.add_row("Sharpe", f"{metrics['sharpe']:.2f}")
    table.add_row("Max drawdown", f"{metrics['max_drawdown']:.2%}")
    table.add_row("Trade count", str(metrics["trade_count"]))
    console.print(table)


def _request_from_options(
    provider: str,
    symbols: list[str],
    start: str,
    end: str,
    interval: str,
    adjusted: bool,
    output_dir: str,
    force_refresh: bool,
    config: Path | None,
) -> HistoricalDataRequest:
    payload = {
        "provider": provider,
        "symbols": symbols,
        "start": start,
        "end": end,
        "interval": interval,
        "adjusted": adjusted,
        "output_dir": output_dir,
        "force_refresh": force_refresh,
    }
    if config is not None:
        loaded = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        payload.update(loaded)
    return HistoricalDataRequest(**payload)


@data_app.command("fetch")
def data_fetch(
    provider: Annotated[
        str, typer.Option(help="Provider: csv, synthetic, yfinance, polygon")
    ] = "synthetic",
    symbol: Annotated[
        list[str] | None, typer.Option("--symbol", help="Symbol; repeat for multiple symbols")
    ] = None,
    start: Annotated[str, typer.Option(help="Start date YYYY-MM-DD")] = "2020-01-01",
    end: Annotated[str, typer.Option(help="End date YYYY-MM-DD")] = "2020-12-31",
    interval: Annotated[str, typer.Option(help="Bar interval")] = "1d",
    adjusted: Annotated[bool, typer.Option("--adjusted/--no-adjusted")] = True,
    output_dir: Annotated[str, typer.Option(help="Cache output directory")] = "data/cache",
    force_refresh: Annotated[bool, typer.Option(help="Overwrite existing cache file")] = False,
    config: Annotated[Path | None, typer.Option(help="YAML config path")] = None,
) -> None:
    """Fetch, normalize, validate, and cache historical data."""
    request = _request_from_options(
        provider,
        symbol or ["SPY"],
        start,
        end,
        interval,
        adjusted,
        output_dir,
        force_refresh,
        config,
    )
    data = get_data_provider(request.provider).fetch_ohlcv(request)
    report = generate_quality_report(data)
    path = write_cache(data, request, report.warnings)
    console.print(f"Cached {len(data)} rows: {path}")


@data_app.command("validate")
def data_validate(path: Annotated[Path, typer.Option(help="CSV dataset path")]) -> None:
    """Validate a cached or local canonical OHLCV dataset."""
    data = validate_ohlcv(load_ohlcv_csv(path))
    console.print(f"Validation passed: {len(data)} rows")


@data_app.command("info")
def data_info(path: Annotated[Path, typer.Option(help="CSV dataset path")]) -> None:
    """Print dataset metadata and quality summary."""
    data = load_ohlcv_csv(path)
    console.print(json.dumps(generate_quality_report(data).to_dict(), indent=2))


@data_app.command("list-cache")
def data_list_cache(
    provider: Annotated[str | None, typer.Option(help="Optional provider filter")] = None,
    output_dir: Annotated[str, typer.Option(help="Cache root")] = "data/cache",
) -> None:
    """List cached CSV datasets."""
    for path in list_cache(output_dir, provider):
        console.print(path)


@app.command()
def backtest(
    strategy: Annotated[str, typer.Option(help=_strategy_help())],
    data: Annotated[Path, typer.Option(help="Path to OHLCV CSV data")],
    initial_cash: Annotated[float, typer.Option(help="Initial cash for the simulation")] = 10_000.0,
) -> None:
    """Run a deterministic long-only sample backtest."""
    configure_logging(get_settings().log_level)
    frame = load_ohlcv_csv(data)
    try:
        strategy_instance = get_strategy(strategy)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    result = BacktestEngine(initial_cash=initial_cash).run(frame, strategy_instance)
    _print_metrics(
        "Quant Trade Backtest Summary",
        strategy_instance.name,
        initial_cash,
        float(result.equity_curve["equity"].iloc[-1]),
        result.metrics,
    )


@app.command("run-experiment")
def run_experiment_command(
    config: Annotated[Path, typer.Option(help="Experiment YAML/JSON")],
) -> None:
    """Run an experiment config and write artifacts."""
    result = run_experiment(load_experiment_config(config))
    console.print(f"Experiment complete. Output directory: {result['output_dir']}")
    console.print(f"Test total return: {result['test_metrics']['total_return']:.2%}")


@app.command("grid-search")
def grid_search_command(
    config: Annotated[Path, typer.Option(help="Grid search YAML/JSON")],
) -> None:
    """Run a parameter-grid research sweep and write artifacts."""
    result = run_grid_search(load_experiment_config(config))
    console.print(f"Grid search complete. Output directory: {result['output_dir']}")
    console.print(f"Best parameters: {result['best_params']}")


@app.command("walk-forward")
def walk_forward_command(
    config: Annotated[Path, typer.Option(help="Walk-forward YAML/JSON")],
) -> None:
    """Run walk-forward validation and write artifacts."""
    result = run_walk_forward(load_experiment_config(config))
    console.print(f"Walk-forward complete. Output directory: {result['output_dir']}")
    console.print(f"Windows evaluated: {len(result['windows'])}")


@research_app.command("list-strategies")
def research_list_strategies() -> None:
    """List available multi-asset research signal models."""
    from quant_trade.research.strategy_registry import list_research_signal_models

    table = Table(title="Research signal models")
    table.add_column("Name")
    for name in list_research_signal_models():
        table.add_row(name)
    console.print(table)


def _run_research_config(config: Path) -> dict:
    from quant_trade.research.multi_asset_runner import (
        load_multi_asset_config,
        run_multi_asset_research_experiment,
    )

    result = run_multi_asset_research_experiment(load_multi_asset_config(config))
    console.print(f"Experiment complete: {config}")
    console.print(f"Symbols: {', '.join(result['symbols'])}")
    console.print(f"Train range: {result['train_range'][0]} to {result['train_range'][1]}")
    console.print(f"Test range: {result['test_range'][0]} to {result['test_range'][1]}")
    console.print(f"Strategy return: {result['test_metrics']['total_return']:.2%}")
    console.print(f"Benchmark return: {result['comparison_test']['benchmark_total_return']:.2%}")
    console.print(f"Excess return: {result['comparison_test']['excess_return']:.2%}")
    console.print(f"Sharpe: {result['test_metrics']['sharpe']:.2f}")
    console.print(f"Max drawdown: {result['test_metrics']['max_drawdown']:.2%}")
    console.print(f"Output directory: {result['output_dir']}")
    return result


@research_app.command("run")
def research_run(config: Annotated[Path, typer.Option(help="Multi-asset research YAML")]) -> None:
    """Run a multi-asset research experiment."""
    _run_research_config(config)


@research_app.command("compare")
def research_compare(
    config: Annotated[Path, typer.Option(help="Multi-asset research YAML")],
) -> None:
    """Run an experiment and print benchmark comparison."""
    _run_research_config(config)


@research_app.command("robustness")
def research_robustness(
    config: Annotated[Path, typer.Option(help="Multi-asset research YAML")],
) -> None:
    """Run configured robustness diagnostics for an experiment."""
    _run_research_config(config)


@selection_app.command("run")
def selection_run(
    outputs_dir: Annotated[Path, typer.Option(help="Research outputs root")] = Path("outputs"),
    criteria: Annotated[Path, typer.Option(help="Selection criteria YAML")] = Path(
        "configs/selection/conservative_daily.yaml"
    ),
) -> None:
    """Select conservative paper-trading candidates from local research artifacts."""
    from quant_trade.research.candidate import SelectionCriteria
    from quant_trade.research.selection import run_selection

    out = run_selection(outputs_dir, SelectionCriteria.from_yaml(criteria))
    console.print(f"Selection complete: {out}")


@selection_app.command("promote")
def selection_promote(
    candidate_file: Annotated[Path, typer.Option(help="candidates.json path")],
    candidate_id: Annotated[str | None, typer.Option(help="Candidate id")] = None,
    approval_notes: Annotated[str, typer.Option(help="Human approval notes")] = "",
) -> None:
    """Evaluate whether a candidate can become simulated paper-ready."""
    from quant_trade.research.candidate import CandidateStrategy
    from quant_trade.research.promotion import evaluate_promotion, save_promotion_report

    items = json.loads(candidate_file.read_text(encoding="utf-8"))
    raw = next(
        (x for x in items if candidate_id is None or x["candidate_id"] == candidate_id), None
    )
    if raw is None:
        raise typer.BadParameter("candidate_id not found")
    raw["approval_notes"] = approval_notes or raw.get("approval_notes", "")
    cand = CandidateStrategy.from_dict(raw)
    risk_config = {
        "kill_switch_enabled": True,
        "max_gross_exposure": cand.max_gross_exposure,
        "max_weight_per_asset": cand.max_weight_per_asset,
    }
    report = evaluate_promotion(cand, Path(cand.research_run_dir), risk_config)
    if report.overall_status == "pass":
        raw["status"] = "paper_ready"
    save_promotion_report(candidate_file.parent / f"promotion_{cand.candidate_id}.json", report)
    console.print(f"Promotion status: {report.overall_status}")


@paper_app.command("init")
def paper_init(config: Annotated[Path, typer.Option(help="Paper config YAML")]) -> None:
    from quant_trade.paper.config import load_paper_config
    from quant_trade.paper.models import PaperSessionState
    from quant_trade.paper.state import save_state

    cfg = load_paper_config(config)
    state = PaperSessionState(
        cash=cfg.initial_cash, equity=cfg.initial_cash, high_water_mark=cfg.initial_cash
    )
    path = Path(cfg.state_dir) / cfg.paper_session_name / "latest_state.json"
    save_state(path, state)
    console.print(f"Initialized simulated session {cfg.paper_session_name}. State path: {path}")


@paper_app.command("run")
def paper_run(config: Annotated[Path, typer.Option(help="Paper config YAML")]) -> None:
    from quant_trade.paper.simulator import PaperTradingSimulator

    out = PaperTradingSimulator(config).run()
    final = json.loads((out / "final_state.json").read_text(encoding="utf-8"))
    console.print(f"Session output: {out}")
    console.print(
        f"Final equity: {final['equity']:.2f}; "
        f"max drawdown: {final['max_drawdown']:.2%}; "
        f"kill switch: {final['kill_switch_active']}"
    )


@paper_app.command("status")
def paper_status(
    session: Annotated[str, typer.Option(help="Paper session name")],
    state_dir: Annotated[Path, typer.Option(help="State root")] = Path("state/paper"),
) -> None:
    path = state_dir / session / "latest_state.json"
    if not path.exists():
        raise typer.BadParameter(f"state not found: {path}")
    console.print(path.read_text(encoding="utf-8"))


def _set_session(
    session: str, status: str | None = None, kill: bool | None = None, reason: str = ""
) -> None:
    from quant_trade.paper.state import load_state, save_state

    path = Path("state/paper") / session / "latest_state.json"
    st = load_state(path)
    if status:
        st.status = status  # type: ignore[assignment]
    if kill is not None:
        st.kill_switch_active = kill
    save_state(path, st)
    console.print(f"Updated {session}: {status or ''} {reason}")


@paper_app.command("pause")
def paper_pause(session: Annotated[str, typer.Option(help="Paper session name")]) -> None:
    _set_session(session, "paused")


@paper_app.command("resume")
def paper_resume(session: Annotated[str, typer.Option(help="Paper session name")]) -> None:
    _set_session(session, "running", False)


@paper_app.command("kill-switch")
def paper_kill_switch(
    session: Annotated[str, typer.Option(help="Paper session name")],
    reason: Annotated[str, typer.Option(help="Reason")],
) -> None:
    _set_session(session, "paused", True, reason)


@paper_app.command("report")
def paper_report(
    session: Annotated[str, typer.Option(help="Paper session name")],
    output_dir: Annotated[Path, typer.Option(help="Output root")] = Path("outputs/paper"),
) -> None:
    runs = sorted((output_dir / session).glob("*/paper_summary.md"))
    if not runs:
        raise typer.BadParameter("no paper report found")
    console.print(runs[-1].read_text(encoding="utf-8"))


@paper_app.command("from-candidate")
def paper_from_candidate(
    candidate_file: Annotated[Path, typer.Option(help="candidates.json")],
    candidate_id: Annotated[str, typer.Option(help="Candidate id")],
    data_path: Annotated[Path, typer.Option(help="Local data path")],
    initial_cash: Annotated[float, typer.Option(help="Initial cash")] = 100000.0,
) -> None:
    from quant_trade.paper.config import write_yaml

    items = json.loads(candidate_file.read_text(encoding="utf-8"))
    raw = next((x for x in items if x["candidate_id"] == candidate_id), None)
    if raw is None:
        raise typer.BadParameter("candidate_id not found")
    payload = {
        "paper_session_name": f"{raw['name']}_paper",
        "mode": "simulated",
        "candidate_id": candidate_id,
        "data_path": str(data_path),
        "strategy": raw["strategy_name"],
        "strategy_params": raw["strategy_params"],
        "universe": {"symbols": raw["universe"]},
        "initial_cash": initial_cash,
        "costs": {
            "fixed_commission": 0.0,
            "percentage_commission": 0.0005,
            "slippage_bps": 2.0,
            "spread_bps": 1.0,
        },
        "risk_limits": {
            "max_gross_exposure": 1.0,
            "max_weight_per_asset": raw.get("max_weight_per_asset", 0.25),
            "max_daily_loss_pct": 0.02,
            "max_total_drawdown_pct": 0.10,
            "max_turnover_per_rebalance": 0.50,
            "min_cash_pct": 0.01,
            "max_orders_per_day": 50,
            "allow_short": False,
            "allow_leverage": False,
            "kill_switch_enabled": True,
        },
        "execution": {
            "rebalance_frequency": "monthly",
            "execution_price": "next_open",
            "fractional_shares": True,
        },
        "state_dir": "state/paper",
        "output_dir": "outputs/paper",
    }
    path = Path("configs/paper") / f"{payload['paper_session_name']}.yaml"
    write_yaml(path, payload)
    console.print(f"Created simulated paper config: {path}")


def _broker_from_config(config_path: Path, confirm: bool = False):
    from quant_trade.execution.alpaca_paper import AlpacaPaperBroker
    from quant_trade.execution.config import load_broker_config
    from quant_trade.execution.simulated_broker import SimulatedBroker

    cfg = load_broker_config(config_path)
    if cfg.provider == "simulated":
        return cfg, SimulatedBroker()
    return cfg, AlpacaPaperBroker(cfg, confirm_paper_order=confirm)


@broker_app.command("check")
def broker_check(config: Annotated[Path, typer.Option(help="Broker YAML config")]) -> None:
    from quant_trade.execution.config import load_broker_config

    cfg = load_broker_config(config)
    missing = []
    if cfg.provider == "alpaca_paper":
        import os

        for name in ("ALPACA_PAPER_API_KEY", "ALPACA_PAPER_SECRET_KEY"):
            if not os.getenv(name):
                missing.append(name)
    console.print(
        json.dumps(
            {
                "ok": True,
                "provider": cfg.provider,
                "mode": cfg.mode,
                "paper": True,
                "missing_credentials": missing,
            },
            indent=2,
        )
    )


@broker_app.command("account")
def broker_account(config: Annotated[Path, typer.Option(help="Broker YAML config")]) -> None:
    _, broker = _broker_from_config(config)
    console.print(json.dumps(broker.get_account().to_dict(), indent=2))


@broker_app.command("positions")
def broker_positions(config: Annotated[Path, typer.Option(help="Broker YAML config")]) -> None:
    _, broker = _broker_from_config(config)
    console.print(json.dumps([p.to_dict() for p in broker.get_positions()], indent=2))


@broker_app.command("orders")
def broker_orders(config: Annotated[Path, typer.Option(help="Broker YAML config")]) -> None:
    _, broker = _broker_from_config(config)
    console.print(json.dumps([o.to_dict() for o in broker.get_open_orders()], indent=2))


@broker_app.command("cancel-all")
def broker_cancel_all(
    config: Annotated[Path, typer.Option(help="Broker YAML config")],
    confirm_paper_cancel: Annotated[bool, typer.Option("--confirm-paper-cancel")] = False,
) -> None:
    if not confirm_paper_cancel:
        raise typer.BadParameter("--confirm-paper-cancel is required")
    _, broker = _broker_from_config(config)
    broker.cancel_all_orders()
    console.print("Paper cancel-all completed")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


@broker_app.command("plan")
def broker_plan(
    paper_config: Annotated[Path, typer.Option(help="Existing simulated paper config")],
    broker_config: Annotated[Path, typer.Option(help="Broker YAML config")],
) -> None:
    import csv
    import uuid
    from datetime import UTC, datetime

    from quant_trade.execution.broker import BrokerAccount
    from quant_trade.execution.config import load_broker_config
    from quant_trade.execution.order_mapper import paper_order_to_broker_order_request
    from quant_trade.execution.safety import validate_order_safety
    from quant_trade.paper.config import load_paper_config
    from quant_trade.paper.models import PaperOrder

    pcfg = load_paper_config(paper_config)
    bcfg = load_broker_config(broker_config)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    out = Path("outputs/broker_plans") / pcfg.paper_session_name / run_id
    symbol = (bcfg.universe or pcfg.universe.get("symbols") or ["SPY"])[0]
    paper_order = PaperOrder(
        order_id=uuid.uuid4().hex,
        timestamp=run_id,
        symbol=symbol,
        side="buy",
        quantity=1.0,
        reason="phase6 dry-run plan sample",
    )
    req = paper_order_to_broker_order_request(paper_order, bcfg)
    account = BrokerAccount(
        bcfg.provider,
        "local****",
        "USD",
        pcfg.initial_cash,
        pcfg.initial_cash,
        pcfg.initial_cash,
        "planning",
        True,
    )
    risk = validate_order_safety(req, bcfg, account)
    _write_json(out / "proposed_orders.json", [req.to_dict()])
    _write_json(out / "risk_checks.json", [risk])
    _write_json(
        out / "dry_run_results.json",
        [{"client_order_id": req.client_order_id, "status": "dry_run"}],
    )
    (out / "broker_config_used.yaml").write_text(
        yaml.safe_dump(bcfg.to_dict(), sort_keys=False), encoding="utf-8"
    )
    with (out / "proposed_orders.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(req.to_dict()))
        writer.writeheader()
        writer.writerow(req.to_dict())
    (out / "plan_summary.md").write_text(
        f"# Broker Plan\n\nRun: {run_id}\n\nDry-run only; no broker network calls.\n",
        encoding="utf-8",
    )
    print(f"Broker plan created: {out}")


@broker_app.command("submit-plan")
def broker_submit_plan(
    plan_dir: Annotated[Path, typer.Option(help="Plan directory")],
    broker_config: Annotated[Path, typer.Option(help="Broker YAML config")],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    confirm_paper_order: Annotated[bool, typer.Option("--confirm-paper-order")] = False,
    execute_paper: Annotated[bool, typer.Option("--execute-paper")] = False,
) -> None:
    import csv
    import uuid
    from datetime import UTC, datetime

    from quant_trade.execution.broker import BrokerOrderRequest

    if not plan_dir.exists() or not (plan_dir / "proposed_orders.json").exists():
        raise typer.BadParameter("invalid plan directory")
    if not dry_run and not (confirm_paper_order and execute_paper):
        raise typer.BadParameter("use --dry-run or both --confirm-paper-order and --execute-paper")
    cfg, broker = _broker_from_config(broker_config, confirm=confirm_paper_order)
    rows = json.loads((plan_dir / "proposed_orders.json").read_text(encoding="utf-8"))
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    out = Path("outputs/broker_submissions") / plan_dir.parent.name / run_id
    submitted = []
    rejected = []
    for row in rows:
        row["dry_run"] = bool(dry_run)
        req = BrokerOrderRequest(**row)
        try:
            submitted.append(broker.submit_order(req).to_dict())
        except Exception as exc:
            rejected.append({"client_order_id": req.client_order_id, "reason": str(exc)})
    _write_json(out / "submitted_orders.json", submitted)
    _write_json(out / "rejected_orders.json", rejected)
    _write_json(out / "broker_responses.json", {"submitted": submitted, "rejected": rejected})
    _write_json(out / "submission_audit.jsonl", {"provider": cfg.provider, "dry_run": dry_run})
    with (out / "submitted_orders.csv").open("w", newline="", encoding="utf-8") as fh:
        if submitted:
            writer = csv.DictWriter(fh, fieldnames=list(submitted[0]))
            writer.writeheader()
            writer.writerows(submitted)
    (out / "submission_summary.md").write_text(
        f"# Broker Submission\n\nSubmitted: {len(submitted)}\nRejected: {len(rejected)}\n",
        encoding="utf-8",
    )
    print(f"Broker submission artifacts: {out}")


@broker_app.command("reconcile")
def broker_reconcile(
    config: Annotated[Path, typer.Option(help="Broker YAML config")],
    state_path: Annotated[Path, typer.Option(help="Local paper latest_state.json")],
) -> None:
    import uuid
    from datetime import UTC, datetime

    from quant_trade.execution.reconciliation import reconcile_paper_state_with_broker
    from quant_trade.paper.state import load_state

    _, broker = _broker_from_config(config)
    report = reconcile_paper_state_with_broker(
        load_state(state_path), broker.get_account(), broker.get_positions()
    )
    out = Path("outputs/reconciliation") / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    )
    _write_json(out / "reconciliation.json", report.to_dict())
    (out / "reconciliation_summary.md").write_text(
        f"# Reconciliation\n\nPassed: {report.passed}\n", encoding="utf-8"
    )
    print(f"Reconciliation artifacts: {out}")


if __name__ == "__main__":
    app()
