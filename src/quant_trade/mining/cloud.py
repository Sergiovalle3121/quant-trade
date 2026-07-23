Exit code: 0
Wall time: 0.8 seconds
Output:
"""Cloud artifact publishing with an injectable offline storage boundary."""

from __future__ import annotations

from typing import Any, Protocol


class JsonStorage(Protocol):
    def write_json(self, uri: str, data: Any) -> None: ...


def publish_report(
    report: dict[str, Any],
    artifact_uri: str,
    storage: JsonStorage | None = None,
) -> None:
    """Publish to S3 through the existing cloud adapter or to an injected fake."""
    if not artifact_uri.startswith("s3://"):
        raise ValueError("artifact_uri must use s3://")
    if storage is None:
        from quant_trade.cloud.storage import backend_for_uri

        storage = backend_for_uri(artifact_uri)
    storage.write_json(artifact_uri, report)

