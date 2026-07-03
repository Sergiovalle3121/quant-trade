from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from .reports import redact, utc_now_iso

SEVERITIES = {"info", "warning", "critical"}
CATEGORIES = {
    "job_failure",
    "stale_heartbeat",
    "kill_switch",
    "drawdown",
    "rejected_orders",
    "missing_artifacts",
    "reconciliation",
    "secret_leak_risk",
    "broker_error",
    "data_quality",
}


class HttpPost(Protocol):
    def __call__(self, url: str, **kwargs: Any) -> Any: ...


@dataclass
class Alert:
    alert_id: str
    created_at_utc: str
    severity: str
    category: str
    session_id: str
    title: str
    message: str
    details: dict[str, Any]
    recommended_action: str
    run_id: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"Invalid alert severity: {self.severity}")
        if self.category not in CATEGORIES:
            raise ValueError(f"Invalid alert category: {self.category}")
        self.details = redact(self.details)


def make_alert(
    alert_id: str = "alert_test",
    severity: str = "info",
    category: str = "job_failure",
    session_id: str = "ops",
) -> Alert:
    return Alert(
        alert_id=alert_id,
        created_at_utc=utc_now_iso(),
        severity=severity,
        category=category,
        session_id=session_id,
        title="Paper ops alert test",
        message="Synthetic alert; no live trading.",
        details={},
        recommended_action="Review dashboard.",
    )


class ConsoleNotifier:
    def notify(self, alert: Alert) -> None:
        print(json.dumps(redact(asdict(alert)), sort_keys=True))


class FileNotifier:
    def __init__(self, path: Path) -> None:
        self.path = path

    def notify(self, alert: Alert) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(redact(asdict(alert)), indent=2), encoding="utf-8")


class JsonlNotifier:
    def __init__(self, path: Path) -> None:
        self.path = path

    def notify(self, alert: Alert) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(redact(asdict(alert))) + "\n")


class SnsNotifier:
    def __init__(self, topic_arn: str | None = None, client: Any | None = None) -> None:
        self.topic_arn = topic_arn
        self.client = client

    def notify(self, alert: Alert) -> None:
        if not self.topic_arn or self.client is None:
            return
        self.client.publish(TopicArn=self.topic_arn, Message=json.dumps(redact(asdict(alert))))


class SlackWebhookNotifier:
    def __init__(
        self, webhook_env: str = "OPS_SLACK_WEBHOOK_URL", post: HttpPost | None = None
    ) -> None:
        self.webhook = os.getenv(webhook_env)
        self.post = post

    def notify(self, alert: Alert) -> None:
        if not self.webhook or self.post is None:
            return
        self.post(self.webhook, json=redact(asdict(alert)), timeout=5)


def load_alerts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def acknowledge_alert(alert_id: str, notes: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"alert_id": alert_id, "notes": redact(notes), "acknowledged_at_utc": utc_now_iso()}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")
