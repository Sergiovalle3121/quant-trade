from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from quant_trade.personal_paper.cli import app
from quant_trade.personal_paper.config import PersonalPaperError, file_hash
from quant_trade.personal_paper.demo import create_demo
from quant_trade.personal_paper.worker import (
    _cached_snapshot,
    budget_review,
    run_once,
    worker_lease,
)


def test_worker_exclusive_lease_releases_after_exception(tmp_path):
    path = tmp_path / "worker.lock"
    with pytest.raises(RuntimeError), worker_lease(path):
        with pytest.raises(PersonalPaperError, match="another private worker"), worker_lease(path):
            pass
        raise RuntimeError("crash")
    with worker_lease(path):
        pass


def test_budget_and_missing_coverage_are_explicit(tmp_path):
    now = pd.Timestamp("2026-10-05T00:00:00Z")
    assert budget_review(None, now, 500)["status"] == "UNOBSERVED"
    path = tmp_path / "expenses.csv"
    pd.DataFrame(
        [
            {
                "start": "2026-10-01T00:00:00Z",
                "end": "2026-11-01T00:00:00Z",
                "category": "infrastructure",
                "amount_mxn": 501,
            }
        ]
    ).to_csv(path, index=False)
    assert budget_review(path, now, 500)["status"] == "OVER_BUDGET"
    with pytest.raises(PersonalPaperError):
        pd.DataFrame(
            [
                {
                    "start": "2026-10-01",
                    "end": "2026-11-01",
                    "category": "infrastructure",
                    "amount_mxn": float("inf"),
                }
            ]
        ).to_csv(path, index=False)
        budget_review(path, now, 500)


def test_worker_over_budget_does_not_fetch_or_create_state(tmp_path, monkeypatch):
    from quant_trade.personal_paper import fetch

    def forbidden(*args, **kwargs):
        pytest.fail("over-budget worker must not fetch")

    monkeypatch.setattr(fetch, "fetch_snapshot", forbidden)
    now = pd.Timestamp(datetime.now(UTC))
    path = tmp_path / "expenses.csv"
    pd.DataFrame(
        [
            {
                "start": now.replace(day=1).isoformat(),
                "end": (now + pd.Timedelta(days=40)).isoformat(),
                "category": "infrastructure",
                "amount_mxn": 501,
            }
        ]
    ).to_csv(path, index=False)
    database = tmp_path / "paper.sqlite"
    result = run_once(
        Path("configs/personal/etf_private_v1.yaml"), database, tmp_path / "cache", expenses=path
    )
    assert result["status"] == "BUDGET_PAUSED"
    assert not result["real_money_approved"] and not database.exists()


def test_snapshot_hash_edit_is_refused(tmp_path):
    cache = tmp_path / "cache"
    paths = create_demo(cache / "snapshot", 65)
    (cache / "latest.txt").write_text(str(paths["data"].parent.resolve()), encoding="utf-8")
    now = pd.Timestamp(datetime.now(UTC))
    manifest = {
        "files_sha256": {paths["data"].name: file_hash(paths["data"])},
        "retrieved_at_utc": now.isoformat(),
    }
    (paths["data"].parent / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    paths["data"].write_text("tampered", encoding="utf-8")
    with pytest.raises(PersonalPaperError, match="hash mismatch"):
        _cached_snapshot(cache, now)


def test_cli_exposes_private_commands():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("worker", "run", "status", "pause", "resume", "economic-review", "fetch-data"):
        assert name in result.stdout


def test_worker_rejects_runtime_mismatch_before_network_or_state(tmp_path, monkeypatch):
    from quant_trade.personal_paper import config, fetch

    monkeypatch.setattr(
        config, "runtime_versions", lambda: {**config.PROSPECTIVE_RUNTIME, "tzdata": "future"}
    )

    def forbidden(*args, **kwargs):
        pytest.fail("a changed runtime must not fetch")

    monkeypatch.setattr(fetch, "fetch_snapshot", forbidden)
    database = tmp_path / "paper.sqlite"
    with pytest.raises(PersonalPaperError, match="runtime differs from frozen protocol"):
        run_once(Path("configs/personal/etf_private_v1.yaml"), database, tmp_path / "cache")
    assert not database.exists()
    assert not database.with_suffix(".worker.lock").exists()
