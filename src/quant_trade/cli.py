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
from quant_trade.datalake.cli import app as datalake_app
from quant_trade.logging_config import configure_logging
from quant_trade.mining.cli import mining_app
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
stress_app = typer.Typer(help="Simulation-only stress testing commands.")

app.add_typer(data_app, name="data")
app.add_typer(research_app, name="research")
app.add_typer(selection_app, name="selection")
app.add_typer(paper_app, name="paper")
app.add_typer(broker_app, name="broker")
app.add_typer(cloud_app, name="cloud")
app.add_typer(ops_app, name="ops")
app.add_typer(datalake_app, name="datalake")
app.add_typer(mining_app, name="mining")
app.add_typer(stress_app, name="stress")
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
        str,
        typer.Option(
            help="Provider: ccxt-<exchange> (e.g. ccxt-kraken), csv, synthetic, yfinance, polygon"
        ),
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
    data_provider = get_data_provider(request.provider)
    if not data_provider.supports_interval(request.interval):
        raise typer.BadParameter(
            f"provider {request.provider} does not support interval {request.interval}"
        )
    data = data_provider.fetch_ohlcv(request)
    report = generate_quality_report(
        data,
        expected_interval=request.interval,
        always_open=request.provider.startswith("ccxt"),
    )
    for warning in report.warnings:
        console.print(f"[yellow]warning:[/yellow] {warning}")
    path = write_cache(data, request, report.warnings)
    console.print(f"Cached {len(data)} rows: {path}")


@data_app.command("fetch-funding")
def data_fetch_funding(
    provider: Annotated[
        str, typer.Option(help="ccxt provider with derivatives, e.g. ccxt-binance")
    ] = "ccxt-binance",
    symbol: Annotated[
        list[str] | None,
        typer.Option("--symbol", help="Perpetual symbol BASE-QUOTE-PERP; repeat for multiple"),
    ] = None,
    start: Annotated[str, typer.Option(help="Start date YYYY-MM-DD")] = "2023-01-01",
    end: Annotated[str, typer.Option(help="End date YYYY-MM-DD")] = "2023-12-31",
    output_dir: Annotated[str, typer.Option(help="Cache output directory")] = "data/cache",
    force_refresh: Annotated[bool, typer.Option(help="Overwrite existing cache file")] = False,
) -> None:
    """Fetch perpetual funding-rate history (research-only, public endpoints)."""
    from datetime import date as date_type

    from quant_trade.data.providers.ccxt_provider import CcxtProvider

    data_provider = get_data_provider(provider)
    if not isinstance(data_provider, CcxtProvider):
        raise typer.BadParameter("funding rates require a ccxt-<exchange> provider")
    symbols = [s.strip().upper() for s in (symbol or ["BTC-USDT-PERP"])]
    start_date = date_type.fromisoformat(start)
    end_date = date_type.fromisoformat(end)
    if start_date >= end_date:
        raise typer.BadParameter("start must be before end")
    frame = data_provider.fetch_funding_rates(symbols, start_date, end_date)
    name = f"{'_'.join(symbols)}_{start}_{end}_funding.csv"
    path = Path(output_dir) / data_provider.name / "funding" / name
    if path.exists() and not force_refresh:
        raise typer.BadParameter(f"funding cache already exists (use --force-refresh): {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    console.print(f"Cached {len(frame)} funding rows: {path}")


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


@research_app.command("walk-forward-multi")
def research_walk_forward_multi(
    config: Annotated[Path, typer.Option(help="Multi-asset walk-forward YAML")],
) -> None:
    """Rolling out-of-sample validation on the multi-asset engine."""
    import yaml as _yaml

    from quant_trade.research.walk_forward_multi import run_multi_asset_walk_forward

    raw = _yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    raw.setdefault("experiment_name", config.stem)
    result = run_multi_asset_walk_forward(raw)
    agg = result["aggregate_metrics"]
    console.print(f"Windows: {agg.get('windows')}")
    console.print(f"OOS Sharpe: {agg.get('sharpe'):.3f}  PSR: {agg.get('psr'):.3f}")
    console.print(f"Positive window rate: {agg.get('positive_window_rate'):.2%}")
    console.print(f"Output directory: {result['output_dir']}")


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
        "max_drawdown": 0.20,
        "max_turnover": 3.0,
        "min_net_excess_return": 0.0,
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


@paper_app.command("loop")
def paper_loop(
    config: Annotated[Path, typer.Option(help="Paper loop config YAML (mode: paper_loop)")],
    max_cycles: Annotated[int, typer.Option(help="Cycles to run (bounded; 0 = forever)")] = 1,
    interval_seconds: Annotated[float, typer.Option(help="Sleep between cycles")] = 3600.0,
) -> None:
    """Run the paper-only live loop: fetch bars, execute the pending target at
    the newest bar's open, decide the next target, persist state + heartbeat."""
    from quant_trade.live.loop import LoopConfig, PaperLoopRunner

    runner = PaperLoopRunner(LoopConfig.from_yaml(config))
    results = runner.run_forever(
        interval_seconds=interval_seconds, max_cycles=max_cycles if max_cycles > 0 else None
    )
    console.print(json.dumps(results[-1], indent=2, default=str))


@paper_app.command("export-session")
def paper_export_session(
    config: Annotated[Path, typer.Option(help="Paper loop config YAML (mode: paper_loop)")],
    output_dir: Annotated[str, typer.Option(help="Export root")] = "outputs/paper_loop_exports",
) -> None:
    """Materialize the standard paper artifact set (six CSVs, paper_metrics.json,
    final_state.json) from a 24/7 loop session so ops/trials can consume it."""
    from dataclasses import asdict
    from datetime import UTC, datetime

    from quant_trade.live.loop import LoopConfig
    from quant_trade.paper.models import PaperTradingConfig
    from quant_trade.paper.reports import write_csvs, write_report
    from quant_trade.paper.state import load_state

    cfg = LoopConfig.from_yaml(config)
    root = Path(cfg.state_dir) / cfg.session_name
    state_path = root / "latest_state.json"
    if not state_path.exists():
        raise typer.BadParameter(f"loop session state not found: {state_path}")
    state = load_state(state_path)

    def _read_jsonl(name: str) -> list[dict]:
        path = root / name
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    snapshots = _read_jsonl("snapshots.jsonl")
    orders = _read_jsonl("orders.jsonl")
    events = _read_jsonl("events.jsonl")
    fills = [f.to_dict() for f in state.fills]
    positions = [asdict(p) for p in state.positions.values()]
    # Halt events double as risk events so ops alerting sees breaker trips.
    risk_events = [e for e in events if e.get("severity") == "critical"]
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(output_dir) / cfg.session_name / run_id
    out.mkdir(parents=True, exist_ok=True)
    pcfg = PaperTradingConfig(
        paper_session_name=cfg.session_name,
        mode="paper_loop_export",
        data_path=f"…5681 tokens truncated…ption(help="Allocation YAML config")],
) -> None:
    from quant_trade.allocation.config import load_allocation_config
    from quant_trade.allocation.registry import eligible_candidates

    cfg = load_allocation_config(config)
    candidates, rejected, _ = eligible_candidates(cfg["registry_path"])
    table = Table(title="Paper allocation candidates (real_money_ready=false)")
    table.add_column("Strategy ID")
    table.add_column("Status")
    table.add_column("Result")
    for c in candidates:
        table.add_row(c.strategy_id, c.status, "eligible")
    for sid, reason in rejected.items():
        table.add_row(sid, "rejected", reason)
    console.print(table)


@allocation_app.command("run")
def allocation_run(config: Annotated[Path, typer.Option(help="Allocation YAML config")]) -> None:
    from quant_trade.allocation.run import run_allocation

    out, result, _, rejected = run_allocation(config)
    console.print(f"Allocation artifacts: {out}")
    selected = len(result.allocation.allocations)
    console.print(f"Selected: {selected} Rejected: {len(rejected)} real_money_ready=false")


@allocation_app.command("risk-report")
def allocation_risk_report(
    config: Annotated[Path, typer.Option(help="Allocation YAML config")],
) -> None:
    from quant_trade.allocation.run import run_allocation

    out, result, _, _ = run_allocation(config)
    console.print(json.dumps(result.risk_report.to_dict(), indent=2))
    console.print(f"Output path: {out / 'risk_budget_report.json'}")


@allocation_app.command("dashboard")
def allocation_dashboard(
    config: Annotated[Path, typer.Option(help="Allocation YAML config")],
) -> None:
    from quant_trade.allocation.run import run_allocation

    out, _, _, _ = run_allocation(config)
    console.print(f"Dashboard: {out / 'dashboard' / 'index.html'}")


@allocation_decision_app.command("record")
def allocation_decision_record(
    config: Annotated[Path, typer.Option(help="Allocation YAML config")],
    strategy_id: Annotated[str, typer.Option()],
    decision: Annotated[str, typer.Option()],
    human_notes: Annotated[str, typer.Option()] = "",
) -> None:
    from quant_trade.allocation.config import load_allocation_config
    from quant_trade.allocation.governance import record_decision
    from quant_trade.allocation.registry import eligible_candidates

    cfg = load_allocation_config(config)
    candidates, _, _ = eligible_candidates(cfg["registry_path"])
    evidence = next((c.evidence_paths for c in candidates if c.strategy_id == strategy_id), [])
    path = record_decision("manual", strategy_id, decision, evidence, human_notes)
    console.print(f"Recorded paper-only allocation decision: {path}; real_money_approved=false")


if __name__ == "__main__":
    app()

trials_app = typer.Typer(help="Paper-only trial management commands.")
review_trials_app = typer.Typer(help="Generate trial review packs.")
decision_trials_app = typer.Typer(help="Recommend and record paper-only trial decisions.")
trials_app.add_typer(review_trials_app, name="review")
trials_app.add_typer(decision_trials_app, name="decision")
app.add_typer(trials_app, name="trials")


def _load_trial_and_policy(config: Path, trial_id: str):
    from quant_trade.trials.config import load_trial_policy
    from quant_trade.trials.registry import get_trial, load_trial_registry

    reg = load_trial_registry(config)
    return reg, get_trial(reg, trial_id), load_trial_policy(reg.get("policy_path"))


@trials_app.command("list")
def trials_list(
    config: Annotated[Path, typer.Option(help="Trial registry YAML")] = Path(
        "configs/trials/trial_registry.yaml"
    ),
) -> None:
    from quant_trade.trials.registry import list_trials, load_trial_registry

    reg = load_trial_registry(config)
    table = Table(title="Paper-only strategy trials (real_money_ready=false)")
    for col in ["Trial", "Status", "Strategy", "Session"]:
        table.add_column(col)
    for t in list_trials(reg):
        table.add_row(t.trial_id, t.status, t.strategy_name, t.paper_session_id)
    console.print(table)
    console.print("Registry snapshot: outputs/trials/registry/trial_registry_snapshot.json")


@trials_app.command("show")
def trials_show(
    trial_id: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    _, t, _ = _load_trial_and_policy(config, trial_id)
    console.print(json.dumps(t.to_dict(), indent=2, default=str))
    console.print("real_money_ready=false")


@trials_app.command("status")
def trials_status(
    trial_id: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    _, t, _ = _load_trial_and_policy(config, trial_id)
    console.print(f"{t.trial_id}: {t.status}; paper-only; real_money_ready=false")


@trials_app.command("collect")
def trials_collect(
    trial_id: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    from quant_trade.trials.tracker import collect_daily_records

    _, t, _ = _load_trial_and_policy(config, trial_id)
    rec = collect_daily_records(t)
    console.print(
        f"Collected {len(rec)} records. Output path: outputs/trials/{trial_id}/daily_records.csv"
    )


@trials_app.command("export-daily-records")
def trials_export_daily_records(
    run_dir: Annotated[Path, typer.Option(help="Paper session run directory")],
    trial_id: Annotated[str, typer.Option(help="Trial ID the records belong to")],
    paper_session_id: Annotated[str, typer.Option(help="Paper session ID")],
    output_root: Annotated[Path, typer.Option(help="Trials output root")] = Path(
        "outputs/trials"
    ),
    benchmark_data: Annotated[
        Path | None, typer.Option(help="Canonical OHLCV CSV for the benchmark leg")
    ] = None,
    benchmark_symbol: Annotated[
        str | None, typer.Option(help="Benchmark symbol, e.g. BTC-USD")
    ] = None,
) -> None:
    """Bridge a real paper run into the trial system's daily-record format."""
    from quant_trade.trials.export import export_daily_records_from_paper_run

    path = export_daily_records_from_paper_run(
        run_dir,
        trial_id,
        paper_session_id,
        output_root,
        benchmark_data=benchmark_data,
        benchmark_symbol=benchmark_symbol,
    )
    console.print(f"Exported daily records: {path}")


@trials_app.command("performance")
def trials_performance(
    trial_id: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    from quant_trade.trials.performance import calculate_trial_performance
    from quant_trade.trials.tracker import collect_daily_records

    _, t, _ = _load_trial_and_policy(config, trial_id)
    perf = calculate_trial_performance(collect_daily_records(t))
    console.print(json.dumps(perf, indent=2, default=str))
    console.print(f"Output path: outputs/trials/{trial_id}/daily_records.csv")


@trials_app.command("drift")
def trials_drift(
    trial_id: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    from quant_trade.trials.drift import analyze_drift, write_drift_report
    from quant_trade.trials.expectations import load_expectations_from_research_artifacts
    from quant_trade.trials.performance import calculate_trial_performance
    from quant_trade.trials.tracker import collect_daily_records

    _, t, _ = _load_trial_and_policy(config, trial_id)
    rep = analyze_drift(
        t,
        calculate_trial_performance(collect_daily_records(t)),
        load_expectations_from_research_artifacts(t.research_run_dir),
    )
    p = write_drift_report(rep, Path("outputs/trials") / trial_id / "drift_report.json")
    console.print(json.dumps(rep.to_dict(), indent=2))
    console.print(f"Output path: {p}")


def _review_cmd(kind: str, trial_id: str, config: Path) -> None:
    from quant_trade.trials.review import generate_review_pack

    _, t, pol = _load_trial_and_policy(config, trial_id)
    out = generate_review_pack(
        t, f"{kind}_review" if kind != "final" else "final_trial_review", pol
    )
    console.print(f"Generated paper-only review pack. Output path: {out}")


@review_trials_app.command("weekly")
def trials_review_weekly(
    trial_id: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    _review_cmd("weekly", trial_id, config)


@review_trials_app.command("monthly")
def trials_review_monthly(
    trial_id: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    _review_cmd("monthly", trial_id, config)


@review_trials_app.command("final")
def trials_review_final(
    trial_id: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    _review_cmd("final", trial_id, config)


@decision_trials_app.command("recommend")
def trials_decision_recommend(
    trial_id: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    from quant_trade.trials.decisions import recommend_decision, record_decision
    from quant_trade.trials.drift import analyze_drift
    from quant_trade.trials.performance import calculate_trial_performance
    from quant_trade.trials.tracker import collect_daily_records

    _, t, pol = _load_trial_and_policy(config, trial_id)
    perf = calculate_trial_performance(collect_daily_records(t))
    dec = recommend_decision(
        {
            "trial_id": trial_id,
            "performance_summary": perf,
            "drift_report": analyze_drift(t, perf).to_dict(),
            "evidence_paths": [],
        },
        pol,
    )
    p = record_decision(dec)
    console.print(json.dumps(dec.to_dict(), indent=2))
    console.print(f"Output path: {p}")


@decision_trials_app.command("record")
def trials_decision_record(
    trial_id: Annotated[str, typer.Option()],
    decision: Annotated[str, typer.Option()],
    human_notes: Annotated[str, typer.Option()] = "",
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    from quant_trade.trials.decisions import DecisionRecord, record_decision

    _, t, _ = _load_trial_and_policy(config, trial_id)
    rec = DecisionRecord(
        f"manual_{trial_id}",
        t.trial_id,
        decision,
        "Human paper-only decision.",
        [],
        [],
        [],
        t.reviewer,
        human_notes,
        real_money_approved=False,
    )
    p = record_decision(rec)
    console.print(f"Recorded decision real_money_approved=false. Output path: {p}")


@trials_app.command("due")
def trials_due(
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    from datetime import date

    from quant_trade.trials.registry import load_trial_registry
    from quant_trade.trials.schedule import reviews_due

    reg = load_trial_registry(config)
    due = reviews_due(reg, date.today())
    console.print(json.dumps([t.trial_id for t in due], indent=2))
    console.print("real_money_ready=false")


@trials_app.command("calendar")
def trials_calendar(
    trial_id: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    from quant_trade.trials.schedule import generate_review_calendar

    _, t, _ = _load_trial_and_policy(config, trial_id)
    p = generate_review_calendar(t)
    console.print(f"Output path: {p}")


@trials_app.command("evidence")
def trials_evidence(
    trial_id: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    from quant_trade.trials.evidence import build_evidence_index, write_evidence_index

    _, t, _ = _load_trial_and_policy(config, trial_id)
    p = write_evidence_index(build_evidence_index(t), Path("outputs/trials") / trial_id)
    console.print(f"Output path: {p}")


@trials_app.command("dashboard")
def trials_dashboard(
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    from quant_trade.trials.dashboard import generate_trial_dashboard
    from quant_trade.trials.registry import load_trial_registry

    p = generate_trial_dashboard(load_trial_registry(config))
    console.print(f"Output path: {p}/index.html")


@trials_app.command("archive")
def trials_archive(
    trial_id: Annotated[str, typer.Option()],
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    from quant_trade.trials.archive import archive_trial

    _load_trial_and_policy(config, trial_id)
    p = archive_trial(trial_id)
    console.print(f"Output path: {p}")


@trials_app.command("run-review-cycle")
def trials_run_review_cycle(
    config: Annotated[Path, typer.Option()] = Path("configs/trials/trial_registry.yaml"),
) -> None:
    import csv

    from quant_trade.trials.dashboard import generate_trial_dashboard
    from quant_trade.trials.decisions import recommend_decision
    from quant_trade.trials.drift import analyze_drift
    from quant_trade.trials.models import utc_now
    from quant_trade.trials.performance import calculate_trial_performance
    from quant_trade.trials.registry import find_trials_by_status, load_trial_registry
    from quant_trade.trials.review import generate_review_pack
    from quant_trade.trials.tracker import collect_daily_records

    reg = load_trial_registry(config)
    run_id = utc_now().replace(":", "").split(".")[0]
    out = Path("outputs/trials/review_cycles") / run_id
    out.mkdir(parents=True, exist_ok=True)
    processed = []
    decisions = []
    reviews = []
    warnings: list[str] = []
    for t in find_trials_by_status(reg, "active"):
        perf = calculate_trial_performance(collect_daily_records(t))
        dr = analyze_drift(t, perf)
        dec = recommend_decision(
            {
                "trial_id": t.trial_id,
                "performance_summary": perf,
                "drift_report": dr.to_dict(),
                "evidence_paths": [],
            },
            __import__("quant_trade.trials.models", fromlist=["TrialPolicy"]).TrialPolicy(),
        )
        rp = generate_review_pack(t, "weekly_review")
        processed.append(t.trial_id)
        decisions.append(dec.to_dict())
        reviews.append(str(rp))
    dash = generate_trial_dashboard(reg)
    (out / "review_cycle_summary.json").write_text(
        json.dumps(
            {
                "trials_processed": processed,
                "decisions_recommended": decisions,
                "reviews_generated": reviews,
                "dashboard": str(dash),
                "real_money_ready": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (out / "review_cycle_summary.md").write_text(
        "# Review Cycle Summary\n\nPaper-only. real_money_ready=false.\n", encoding="utf-8"
    )
    for name, rows in [("trials_processed.csv", processed), ("reviews_generated.csv", reviews)]:
        with (out / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["value"])
            [w.writerow([x]) for x in rows]
    (out / "decisions_recommended.csv").write_text(
        "trial_id,decision,real_money_approved\n"
        + "\n".join(f"{d['trial_id']},{d['decision']},false" for d in decisions),
        encoding="utf-8",
    )
    (out / "warnings.json").write_text(json.dumps(warnings), encoding="utf-8")
    console.print(f"Output path: {out}/review_cycle_summary.json")


evidence_app = typer.Typer(help="Local strategy evidence database commands.")
app.add_typer(evidence_app, name="evidence")


@evidence_app.command("init")
def evidence_init(config: Annotated[Path, typer.Option(help="Evidence YAML config path")]) -> None:
    from quant_trade.evidence.config import load_evidence_config
    from quant_trade.evidence.database import initialize_database

    cfg = load_evidence_config(config)
    initialize_database(cfg.database_path)
    console.print(f"Initialized evidence database: {cfg.database_path}")


@evidence_app.command("ingest")
def evidence_ingest(
    config: Annotated[Path, typer.Option(help="Evidence YAML config path")],
    path: Annotated[Path, typer.Option(help="Artifact root path")],
) -> None:
    from quant_trade.evidence.config import load_evidence_config
    from quant_trade.evidence.ingest import ingest_path

    report = ingest_path(load_evidence_config(config), path)
    console.print(
        "Ingested "
        f"{report.artifacts_ingested}/{report.artifacts_seen} artifacts: "
        f"{report.output_path}"
    )


@evidence_app.command("list-strategies")
def evidence_list_strategies(
    config: Annotated[Path, typer.Option(help="Evidence YAML config path")],
) -> None:
    from quant_trade.evidence.config import load_evidence_config
    from quant_trade.evidence.database import list_strategies

    for strategy_id in list_strategies(load_evidence_config(config).database_path):
        console.print(strategy_id)


@evidence_app.command("scorecard")
def evidence_scorecard(
    config: Annotated[Path, typer.Option(help="Evidence YAML config path")],
    strategy_id: Annotated[str, typer.Option(help="Strategy id")],
) -> None:
    import time

    from quant_trade.evidence.config import load_evidence_config
    from quant_trade.evidence.scorecard import build_scorecard, persist_scorecard

    cfg = load_evidence_config(config)
    scorecard = build_scorecard(cfg, strategy_id)
    path = persist_scorecard(cfg, scorecard, f"scorecard_{int(time.time())}")
    console.print(f"Scorecard written: {path}")
    console.print(f"real_money_ready={str(scorecard.real_money_ready).lower()}")


@evidence_app.command("search")
def evidence_search(
    config: Annotated[Path, typer.Option(help="Evidence YAML config path")],
    query: Annotated[str, typer.Option(help="Search query")],
) -> None:
    from quant_trade.evidence.config import load_evidence_config
    from quant_trade.evidence.search import search

    for row in search(load_evidence_config(config).database_path, query):
        console.print(f"{row['strategy_id']}\t{row['artifact_type']}\t{row['path']}")


@evidence_app.command("lineage")
def evidence_lineage(
    config: Annotated[Path, typer.Option(help="Evidence YAML config path")],
    strategy_id: Annotated[str, typer.Option(help="Strategy id")],
) -> None:
    import time

    from quant_trade.evidence.config import load_evidence_config
    from quant_trade.evidence.lineage import export_lineage

    path = export_lineage(load_evidence_config(config), strategy_id, f"lineage_{int(time.time())}")
    console.print(f"Lineage written: {path}")


@evidence_app.command("dashboard")
def evidence_dashboard(
    config: Annotated[Path, typer.Option(help="Evidence YAML config path")],
) -> None:
    from quant_trade.evidence.config import load_evidence_config
    from quant_trade.evidence.dashboard import build_dashboard

    path = build_dashboard(load_evidence_config(config))
    console.print(f"Dashboard written: {path}")

