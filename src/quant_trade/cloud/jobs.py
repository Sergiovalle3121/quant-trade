from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

import yaml

from quant_trade.cloud.config import CloudConfig, load_cloud_config
from quant_trade.cloud.exceptions import SafetyGateError
from quant_trade.cloud.health import run_health_check
from quant_trade.cloud.heartbeat import Heartbeat, read_heartbeat, write_heartbeat
from quant_trade.cloud.kill_switch import assert_not_killed, get_kill_switch_status
from quant_trade.cloud.locks import DynamoDbLock, LocalFileLock
from quant_trade.cloud.monitoring import JobSummary, emit_metric, structured_log
from quant_trade.cloud.secrets import AwsSecretsManagerProvider, EnvSecretsProvider
from quant_trade.cloud.storage import backend_for_uri


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]


def _base_uri(config: CloudConfig, run_id: str) -> str:
    return (
        f"{config.artifact_uri.rstrip('/')}/cloud/"
        f"{config.deployment_name}/{config.job_name}/{run_id}"
    )


def _heartbeat(
    config: CloudConfig, run_id: str, status: str, summary: dict | None = None
) -> Heartbeat:
    return Heartbeat(
        deployment_name=config.deployment_name,
        job_name=config.job_name,
        run_id=run_id,
        status=status,
        started_at_utc=datetime.now(UTC).isoformat(),
        mode=config.mode,
        broker_provider=config.broker_provider,
        paper_submission_enabled=config.allow_paper_order_submission,
        kill_switch_active=get_kill_switch_status(config).active,
        summary=summary or {},
    )


def _write_artifacts(
    config: CloudConfig,
    run_id: str,
    summary: JobSummary,
    events: list[dict],
    extra_files: list[str] | None = None,
) -> None:
    storage = backend_for_uri(config.artifact_uri)
    base = _base_uri(config, run_id)
    storage.write_text(
        f"{base}/cloud_config_used.yaml", yaml.safe_dump(config.to_safe_dict(), sort_keys=False)
    )
    storage.write_json(f"{base}/job_summary.json", summary.model_dump(mode="json"))
    storage.write_text(
        f"{base}/job_summary.md",
        f"# Cloud Job Summary\n\nStatus: {summary.status}\nRun: {run_id}\n",
    )
    hb = _heartbeat(config, run_id, summary.status, {"duration_seconds": summary.duration_seconds})
    storage.write_json(f"{base}/heartbeat.json", hb.model_dump(mode="json"))
    storage.write_json(f"{base}/metrics.json", [m.model_dump(mode="json") for m in summary.metrics])
    storage.write_text(
        f"{base}/events.jsonl", "\n".join(json.dumps(e, sort_keys=True) for e in events) + "\n"
    )
    storage.write_json(
        f"{base}/artifacts_index.json",
        {
            "base_uri": base,
            "files": [
                "cloud_config_used.yaml",
                "job_summary.json",
                "job_summary.md",
                "heartbeat.json",
                "metrics.json",
                "events.jsonl",
                "artifacts_index.json",
                *(extra_files or []),
            ],
        },
    )


def validate_broker_submit_gates(config: CloudConfig) -> None:
    if config.mode != "alpaca_paper_submit":
        raise SafetyGateError("mode must be alpaca_paper_submit")
    if not config.allow_paper_order_submission:
        raise SafetyGateError("paper order submission disabled")
    if config.allow_live_trading or config.real_money_enabled:
        raise SafetyGateError("live/real-money flags must be false")
    if config.broker_provider != "alpaca_paper":
        raise SafetyGateError("broker provider must be alpaca_paper")
    assert_not_killed(config)
    provider = (
        EnvSecretsProvider()
        if config.secrets.provider == "env"
        else AwsSecretsManagerProvider(secret_id=config.secrets.alpaca_paper_secret_id)
    )
    provider.get_alpaca_paper_credentials()
    structured_log("broker_paper_submission_allowed", provider=config.broker_provider)


def _heartbeat_age_seconds(storage, config: CloudConfig) -> float:
    """Age of the PREVIOUS heartbeat; -1 when none exists or it is unreadable."""
    try:
        hb = read_heartbeat(storage, config.heartbeat_uri)
        last = datetime.fromisoformat(hb.last_update_utc)
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - last).total_seconds())
    except Exception:
        return -1.0


def _select_lock(config: CloudConfig):
    if config.locking.provider == "dynamodb":
        if not config.locking.table_name:
            raise SafetyGateError("dynamodb locking requires locking.table_name")
        import boto3

        return DynamoDbLock(config.locking.table_name, client=boto3.client("dynamodb"))
    return LocalFileLock(Path(str(config.state_uri).replace("s3://", "state/cloud/")) / "locks")


def _notify_failure(config: CloudConfig, run_id: str, error: str) -> None:
    if not config.monitoring.alert_on_job_failure or not config.monitoring.sns_topic_arn:
        return
    try:
        import boto3

        boto3.client("sns").publish(
            TopicArn=config.monitoring.sns_topic_arn,
            Subject=f"quant-trade job failure: {config.job_name}",
            Message=f"deployment={config.deployment_name} run={run_id} error={error[:500]}",
        )
        structured_log("job_failure_notified", run_id=run_id)
    except Exception as exc:  # never let alerting break the artifact trail
        structured_log("job_failure_notification_failed", run_id=run_id, reason=str(exc))


def run_job(config_path: Path | str, job_name: str | None = None) -> JobSummary:
    config = load_cloud_config(config_path)
    config.job_name = job_name or config.job_name
    run_id = new_run_id()
    start = monotonic()
    events: list[dict[str, Any]] = [
        {"event": "cloud_job_started", "run_id": run_id, "job": config.job_name}
    ]
    structured_log("cloud_job_started", run_id=run_id, job=config.job_name)
    storage = backend_for_uri(config.heartbeat_uri)
    # Measure staleness BEFORE overwriting the previous heartbeat, or the
    # metric can only ever observe its own fresh write.
    previous_heartbeat_age = _heartbeat_age_seconds(storage, config)
    write_heartbeat(storage, config.heartbeat_uri, _heartbeat(config, run_id, "running"))
    emf = config.monitoring.emit_cloudwatch_embedded_metrics
    metrics = []
    extra_artifacts: list[str] = []
    status = "success"
    error = None
    try:
        if config.job_name == "health_check":
            run_health_check(config)
        elif config.job_name == "mining_evaluation":
            if not config.mining_config_path:
                raise SafetyGateError("mining_evaluation requires mining_config_path")
            assert_not_killed(config)
            from quant_trade.mining.config import load_mining_config
            from quant_trade.mining.profitability import evaluate_all

            rigs, markets, policy = load_mining_config(Path(config.mining_config_path))
            evaluations = evaluate_all(rigs, markets, policy)
            go_count = sum(item.decision == "GO" for item in evaluations)
            report: dict[str, Any] = {
                "evaluations": [item.to_dict() for item in evaluations],
                "go_count": go_count,
                "authorized_to_start_miner": False,
                "cloud_resources_created": False,
            }
            filename = "mining_profitability_report.json"
            storage.write_json(f"{_base_uri(config, run_id)}/{filename}", report)
            extra_artifacts.append(filename)
            best_stressed = max(item.stressed_net_profit_usd for item in evaluations)
            metrics.extend(
                [
                    emit_metric(
                        "mining_go_count",
                        float(go_count),
                        dimensions={"job": config.job_name},
                        emf=emf,
                    ),
                    emit_metric(
                        "mining_best_stressed_profit_usd",
                        best_stressed,
                        "None",
                        dimensions={"job": config.job_name},
                        emf=emf,
                    ),
                    emit_metric(
                        "mining_authorized_to_start",
                        0,
                        dimensions={"job": config.job_name},
                        emf=emf,
                    ),
                ]
            )
            events.append(
                {
                    "event": "mining_evaluation_completed",
                    "go_count": go_count,
                    "authorized_to_start_miner": False,
                }
            )
        elif config.job_name == "heartbeat":
            metrics.append(
                emit_metric(
                    "heartbeat_age_seconds",
                    previous_heartbeat_age,
                    "Seconds",
                    dimensions={"job": config.job_name},
                    emf=emf,
                )
            )
        elif config.job_name == "simulated_paper_run":
            if not config.paper_config_path:
                raise SafetyGateError("simulated_paper_run requires paper_config_path")
            from quant_trade.paper.simulator import PaperTradingSimulator

            out = PaperTradingSimulator(Path(config.paper_config_path)).run()
            final = json.loads((out / "final_state.json").read_text(encoding="utf-8"))
            metrics.append(
                emit_metric(
                    "equity", float(final["equity"]), dimensions={"job": config.job_name}, emf=emf
                )
            )
            metrics.append(
                emit_metric(
                    "max_drawdown",
                    float(final["max_drawdown"]),
                    dimensions={"job": config.job_name},
                    emf=emf,
                )
            )
            metrics.append(
                emit_metric(
                    "kill_switch_active",
                    1.0 if final.get("kill_switch_active") else 0.0,
                    dimensions={"job": config.job_name},
                    emf=emf,
                )
            )
        elif config.job_name == "broker_plan":
            metrics.append(
                emit_metric(
                    "paper_orders_planned",
                    0,
                    dimensions={"deployment": config.deployment_name},
                    emf=emf,
                )
            )
        elif config.job_name == "broker_submit_paper":
            validate_broker_submit_gates(config)
            lock = _select_lock(config)
            rec = lock.acquire_lock("broker_submit_paper", run_id, config.locking.ttl_minutes)
            try:
                # Submission remains fail-closed unless wired to a reviewed plan.
                raise SafetyGateError(
                    "cloud paper submission requires a reviewed broker plan; "
                    "no auto-submit is implemented"
                )
            finally:
                lock.release_lock(rec.lock_name, run_id)
        elif config.job_name in {"data_refresh", "research_run"}:
            metrics.append(
                emit_metric(
                    "stale_data_warning", 0, dimensions={"job": config.job_name}, emf=emf
                )
            )
        else:
            raise SafetyGateError(f"unknown cloud job: {config.job_name}")
    except Exception as exc:
        status = "failure"
        error = str(exc)
        metrics.append(
            emit_metric("job_failure", 1, dimensions={"job": config.job_name}, emf=emf)
        )
        events.append({"event": "cloud_job_failed", "error": error})
        _notify_failure(config, run_id, error)
    duration = monotonic() - start
    metrics.append(
        emit_metric(
            "job_success",
            1 if status == "success" else 0,
            dimensions={"job": config.job_name},
            emf=emf,
        )
    )
    metrics.append(
        emit_metric("job_duration_seconds", duration, "Seconds", {"job": config.job_name}, emf=emf)
    )
    summary = JobSummary(
        run_id=run_id,
        job_name=config.job_name,
        status=status,
        started_at_utc=datetime.now(UTC).isoformat(),
        completed_at_utc=datetime.now(UTC).isoformat(),
        duration_seconds=duration,
        metrics=metrics,
        error=error,
    )
    events.append(
        {
            "event": "cloud_job_completed" if status == "success" else "cloud_job_failed",
            "run_id": run_id,
            "status": status,
        }
    )
    write_heartbeat(
        storage,
        config.heartbeat_uri,
        _heartbeat(config, run_id, status, {"error": error} if error else {}),
    )
    _write_artifacts(config, run_id, summary, events, extra_artifacts)
    structured_log(
        "cloud_job_completed" if status == "success" else "cloud_job_failed",
        run_id=run_id,
        status=status,
        error=error,
    )
    if status != "success":
        raise SafetyGateError(error or "cloud job failed")
    return summary

