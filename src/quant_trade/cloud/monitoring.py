from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from quant_trade.cloud.secrets import redact_secret_values


class MetricEvent(BaseModel):
    name: str
    value: float
    unit: str = "Count"
    dimensions: dict[str, str] = Field(default_factory=dict)
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_emf(self) -> dict[str, Any]:
        return {
            "_aws": {
                "Timestamp": int(datetime.now(UTC).timestamp() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "QuantTrade/CloudPaper",
                        "Dimensions": [list(self.dimensions)],
                        "Metrics": [{"Name": self.name, "Unit": self.unit}],
                    }
                ],
            },
            **self.dimensions,
            self.name: self.value,
        }


class JobSummary(BaseModel):
    run_id: str
    job_name: str
    status: str
    started_at_utc: str
    completed_at_utc: str | None = None
    duration_seconds: float = 0.0
    metrics: list[MetricEvent] = Field(default_factory=list)
    error: str | None = None


def structured_log(event: str, **fields: Any) -> None:
    payload = redact_secret_values(
        {"event": event, "timestamp_utc": datetime.now(UTC).isoformat(), **fields}
    )
    print(json.dumps(payload, sort_keys=True), file=sys.stdout)


def emit_metric(
    name: str,
    value: float,
    unit: str = "Count",
    dimensions: dict[str, str] | None = None,
    emf: bool = False,
) -> MetricEvent:
    metric = MetricEvent(name=name, value=value, unit=unit, dimensions=dimensions or {})
    print(json.dumps(metric.to_emf() if emf else metric.model_dump(), sort_keys=True))
    return metric
