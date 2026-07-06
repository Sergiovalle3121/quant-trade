from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Protocol

from quant_trade.cloud.exceptions import StorageError


class StorageBackend(Protocol):
    def write_text(self, uri: str, text: str) -> None: ...
    def read_text(self, uri: str) -> str: ...
    def exists(self, uri: str) -> bool: ...
    def list(self, uri: str) -> list[str]: ...
    def copy_file(self, local_path: Path, uri: str) -> None: ...
    def download_file(self, uri: str, local_path: Path) -> None: ...
    def write_json(self, uri: str, data: Any) -> None:
        self.write_text(uri, json.dumps(data, indent=2, sort_keys=True))

    def read_json(self, uri: str) -> Any:
        return json.loads(self.read_text(uri))


def parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise StorageError(f"not an S3 URI: {uri}")
    rest = uri[5:]
    if "/" not in rest or not rest.split("/", 1)[0]:
        raise StorageError("S3 URI must be s3://bucket/key")
    bucket, key = rest.split("/", 1)
    if not key:
        raise StorageError("S3 URI must include a key")
    return bucket, key.strip("/")


class LocalStorageBackend:
    def _path(self, uri: str) -> Path:
        if uri.startswith("s3://"):
            raise StorageError("S3 URI passed to local storage")
        return Path(uri)

    def write_text(self, uri: str, text: str) -> None:
        path = self._path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def read_text(self, uri: str) -> str:
        return self._path(uri).read_text(encoding="utf-8")

    def exists(self, uri: str) -> bool:
        return self._path(uri).exists()

    def list(self, uri: str) -> list[str]:
        path = self._path(uri)
        if not path.exists():
            return []
        if path.is_file():
            return [str(path)]
        return sorted(str(p) for p in path.rglob("*") if p.is_file())

    def copy_file(self, local_path: Path, uri: str) -> None:
        path = self._path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, path)

    def download_file(self, uri: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._path(uri), local_path)

    def write_json(self, uri: str, data: Any) -> None:
        self.write_text(uri, json.dumps(data, indent=2, sort_keys=True))

    def read_json(self, uri: str) -> Any:
        return json.loads(self.read_text(uri))


class S3StorageBackend:
    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                import boto3
            except ModuleNotFoundError as exc:
                raise StorageError(
                    "boto3 is required for s3:// URIs; install with "
                    'python -m pip install -e ".[cloud]"'
                ) from exc
            self._client = boto3.client("s3")
        return self._client

    def write_text(self, uri: str, text: str) -> None:
        b, k = parse_s3_uri(uri)
        self.client.put_object(Bucket=b, Key=k, Body=text.encode(), ContentType="text/plain")

    def read_text(self, uri: str) -> str:
        b, k = parse_s3_uri(uri)
        return self.client.get_object(Bucket=b, Key=k)["Body"].read().decode()

    def exists(self, uri: str) -> bool:
        """True/False only for a definitive answer; storage failures raise.

        Swallowing IAM/network errors here previously reported the kill-switch
        file as absent (inactive) exactly when infrastructure was degraded —
        safety mechanisms built on exists() must fail closed, not open.
        """
        b, k = parse_s3_uri(uri)
        try:
            self.client.head_object(Bucket=b, Key=k)
            return True
        except Exception as exc:
            status = getattr(exc, "response", {}).get("ResponseMetadata", {}).get(
                "HTTPStatusCode"
            )
            error_code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if status == 404 or error_code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise StorageError(f"cannot determine existence of {uri}: {exc}") from exc

    def list(self, uri: str) -> list[str]:
        b, k = parse_s3_uri(uri)
        resp = self.client.list_objects_v2(Bucket=b, Prefix=k)
        return [f"s3://{b}/{x['Key']}" for x in resp.get("Contents", [])]

    def copy_file(self, local_path: Path, uri: str) -> None:
        b, k = parse_s3_uri(uri)
        self.client.upload_file(str(local_path), b, k)

    def download_file(self, uri: str, local_path: Path) -> None:
        b, k = parse_s3_uri(uri)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(b, k, str(local_path))

    def write_json(self, uri: str, data: Any) -> None:
        self.write_text(uri, json.dumps(data, indent=2, sort_keys=True))

    def read_json(self, uri: str) -> Any:
        return json.loads(self.read_text(uri))


def backend_for_uri(uri: str) -> StorageBackend:
    return S3StorageBackend() if uri.startswith("s3://") else LocalStorageBackend()
