"""Moving to an own domain: Railway's address forwards reads, keeps posts."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

OLD = "https://rigor.up.railway.app"


def _client(tmp_path: Path, base_url: str) -> TestClient:
    cfg = AuditSettings(database_url=f"sqlite:///{tmp_path}/move.db", base_url=base_url)
    app = create_app(cfg, make_store(cfg.database_url))
    return TestClient(app, base_url=OLD)


def test_old_railway_address_forwards_reads_to_the_domain(tmp_path: Path) -> None:
    client = _client(tmp_path, "https://rigor.example")
    response = client.get("/audits/abc?token=t&lang=en", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == "https://rigor.example/audits/abc?token=t&lang=en"
    assert client.get("/", follow_redirects=False).headers["location"] == "https://rigor.example/"


def test_posts_and_health_stay_on_the_old_address(tmp_path: Path) -> None:
    client = _client(tmp_path, "https://rigor.example")
    assert client.get("/health").status_code == 200
    assert client.post("/webhooks/stripe", content=b"{}").status_code != 308


def test_no_move_while_the_railway_address_is_the_site(tmp_path: Path) -> None:
    client = _client(tmp_path, OLD)
    assert client.get("/", follow_redirects=False).status_code == 200


def test_other_hosts_are_not_redirected(tmp_path: Path) -> None:
    client = _client(tmp_path, "https://rigor.example")
    response = client.get("/", headers={"host": "rigor.example"}, follow_redirects=False)
    assert response.status_code == 200
