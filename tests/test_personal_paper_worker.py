from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from quant_trade.personal_paper import worker
from quant_trade.personal_paper.cli import app
from quant_trade.personal_paper.config import PersonalPaperError, file_hash
from quant_trade.personal_paper.demo import create_demo
from quant_trade.personal_paper.worker import (
    _cached_snapshot,
    _publish_status,
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


@pytest.mark.parametrize("previous_status", [False, True])
def test_worker_over_budget_publishes_state_without_fetch_or_database(
    tmp_path, monkeypatch, previous_status: bool
):
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
    cache = tmp_path / "cache"
    if previous_status:
        cache.mkdir()
        (cache / "worker_status.json").write_text(
            json.dumps({"status": "WAITING_NEXT_SESSION"}), encoding="utf-8"
        )
    result = run_once(Path("configs/personal/etf_private_v1.yaml"), database, cache, expenses=path)
    assert result["status"] == "BUDGET_PAUSED"
    assert not result["real_money_approved"] and not database.exists()
    assert "worker" not in result and "manifest" not in result
    published = json.loads((cache / "worker_status.json").read_text(encoding="utf-8"))
    checked_at = pd.Timestamp(published.pop("checked_at_utc"))
    assert checked_at.tzinfo is not None and checked_at.utcoffset().total_seconds() == 0
    assert published == result
    assert not (cache / "worker_status.tmp").exists()


@pytest.mark.parametrize("coverage", ["empty_file", "headers_only", "past", "future"])
def test_month_without_declared_expenses_is_unobserved(tmp_path, coverage: str):
    path = tmp_path / "expenses.csv"
    if coverage == "empty_file":
        path.write_text("", encoding="utf-8")
    else:
        records = []
        if coverage in {"past", "future"}:
            month = "09" if coverage == "past" else "11"
            records.append(
                {
                    "start": f"2026-{month}-01T00:00:00Z",
                    "end": f"2026-{month}-15T00:00:00Z",
                    "category": "infrastructure",
                    "amount_mxn": 25,
                }
            )
        pd.DataFrame(records, columns=["start", "end", "category", "amount_mxn"]).to_csv(
            path, index=False
        )
    result = budget_review(path, pd.Timestamp("2026-10-05T00:00:00Z"), 500)
    assert result == {
        "status": "UNOBSERVED",
        "ceiling_mxn": 500,
        "note": "No declared expenses overlap the current UTC month; coverage is unobserved.",
    }
    assert "observed_mxn" not in result


def test_explicit_zero_for_current_month_is_observed(tmp_path):
    path = tmp_path / "expenses.csv"
    pd.DataFrame(
        [
            {
                "start": "2026-10-01T00:00:00Z",
                "end": "2026-11-01T00:00:00Z",
                "category": "infrastructure",
                "amount_mxn": 0,
            }
        ]
    ).to_csv(path, index=False)
    assert budget_review(path, pd.Timestamp("2026-10-05T00:00:00Z"), 500) == {
        "status": "WITHIN_DECLARED_BUDGET",
        "observed_mxn": 0.0,
        "ceiling_mxn": 500,
    }


def test_over_budget_pauses_existing_database_before_publishing(tmp_path, monkeypatch):
    database, cache = tmp_path / "paper.sqlite", tmp_path / "cache"
    sentinel = b"synthetic unopened database"
    database.write_bytes(sentinel)
    cache.mkdir()
    status_path = cache / "worker_status.json"
    status_path.write_text('{"status":"WAITING_NEXT_SESSION"}', encoding="utf-8")
    pauses = []
    monkeypatch.setattr(
        worker, "budget_review", lambda *args: {"status": "OVER_BUDGET", "observed_mxn": 501}
    )
    monkeypatch.setattr(worker.engine, "pause", lambda *args: pauses.append(args))

    def forbidden(*args, **kwargs):
        pytest.fail("budget pause must not fetch or run the engine")

    monkeypatch.setattr(worker.fetch, "fetch_snapshot", forbidden)
    monkeypatch.setattr(worker.engine, "run", forbidden)
    result = run_once(Path("configs/personal/etf_private_v1.yaml"), database, cache)
    assert pauses == [(database, "observed monthly budget exceeded")]
    assert database.read_bytes() == sentinel
    published = json.loads(status_path.read_text(encoding="utf-8"))
    assert published["status"] == result["status"] == "BUDGET_PAUSED"
    assert published["real_money_approved"] is False


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_atomic_status_failure_preserves_previous_observation(tmp_path, monkeypatch, failure: str):
    status_path = tmp_path / "worker_status.json"
    previous = b'{"status":"BUDGET_PAUSED","real_money_approved":false}'
    status_path.write_bytes(previous)
    original_write, original_replace = Path.write_text, Path.replace

    def interrupted_write(path, text, *args, **kwargs):
        if path.name == "worker_status.tmp":
            original_write(path, text[:20], *args, **kwargs)
            raise OSError("synthetic interrupted temporary write")
        return original_write(path, text, *args, **kwargs)

    def interrupted_replace(path, target):
        if path.name == "worker_status.tmp":
            raise OSError("synthetic failed atomic replace")
        return original_replace(path, target)

    monkeypatch.setattr(
        Path,
        "write_text" if failure == "write" else "replace",
        interrupted_write if failure == "write" else interrupted_replace,
    )
    with pytest.raises(OSError, match="synthetic"):
        _publish_status(
            tmp_path,
            {"status": "WAITING_NEXT_SESSION", "real_money_approved": False},
            pd.Timestamp("2026-10-05T00:00:00Z"),
        )
    assert status_path.read_bytes() == previous


def test_successful_worker_reuses_atomic_status_publisher(tmp_path, monkeypatch):
    snapshot = tmp_path / "verified-snapshot"
    cache = tmp_path / "cache"
    monkeypatch.setattr(worker, "_cached_snapshot", lambda *args: snapshot)
    monkeypatch.setattr(worker.fetch, "fetch_open_quotes", lambda *args: None)
    monkeypatch.setattr(
        worker.engine,
        "run",
        lambda *args, **kwargs: {"status": "WAITING_NEXT_SESSION", "real_money_approved": False},
    )
    result = run_once(
        Path("configs/personal/etf_private_v1.yaml"), tmp_path / "paper.sqlite", cache
    )
    published = json.loads((cache / "worker_status.json").read_text(encoding="utf-8"))
    checked_at = pd.Timestamp(published.pop("checked_at_utc"))
    assert checked_at.tzinfo is not None and checked_at.utcoffset().total_seconds() == 0
    assert published == result
    assert result["worker"]["quotes"] == "WAITING"


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
