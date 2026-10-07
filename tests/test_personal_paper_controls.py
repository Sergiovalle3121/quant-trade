"""Pause and resume never initialize or journal an empty or unregistered file."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quant_trade.personal_paper import engine, worker
from quant_trade.personal_paper.cli import app
from quant_trade.personal_paper.config import PersonalPaperError, UnregisteredPaperDatabase
from quant_trade.personal_paper.demo import create_demo
from quant_trade.personal_paper.store import PaperStore

REVIEW = "Reviewed data, budget and risk; continue simulated observations."
KINDS = ["zero_bytes", "empty_sqlite", "schema_only"]


def _unregistered(tmp_path: Path, kind: str) -> Path:
    path = tmp_path / f"{kind}.sqlite"
    if kind == "zero_bytes":
        path.touch()
    elif kind == "empty_sqlite":
        with closing(sqlite3.connect(path)) as db:
            db.execute("PRAGMA user_version=0")
    else:
        PaperStore(path).close()  # tables exist, but run never sealed a manifest
    return path


def _snapshot(path: Path) -> tuple[str, int]:
    wal = path.with_name(path.name + "-wal")
    return (
        hashlib.sha256(path.read_bytes()).hexdigest(),
        wal.stat().st_size if wal.exists() else 0,
    )


def _schema(path: Path) -> list[tuple[str, ...]]:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        return db.execute("SELECT type,name FROM sqlite_master ORDER BY name").fetchall()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("command", ["pause", "resume"])
def test_control_commands_refuse_unregistered_files_before_any_write(
    tmp_path: Path, kind: str, command: str
):
    path = _unregistered(tmp_path, kind)
    before, schema = _snapshot(path), _schema(path)
    with pytest.raises(UnregisteredPaperDatabase, match="empty or unregistered"):
        if command == "pause":
            engine.pause(path, "synthetic mistaken database path")
        else:
            engine.resume(path, REVIEW)
    assert _snapshot(path) == before
    assert _schema(path) == schema  # no tables created, no journal or WAL frames written


@pytest.mark.parametrize("command", ["pause", "resume"])
def test_cli_control_commands_report_the_refusal(tmp_path: Path, command: str):
    path = _unregistered(tmp_path, "zero_bytes")
    option = ["--reason", "synthetic reason"] if command == "pause" else ["--review", REVIEW]
    result = CliRunner().invoke(app, [command, "--database", str(path), *option])
    assert result.exit_code == 2
    assert f"Paper {command} refused" in result.output
    assert "empty or unregistered" in result.output
    assert path.read_bytes() == b""


def test_refused_pause_leaves_an_empty_file_usable_by_run(tmp_path: Path):
    path = _unregistered(tmp_path, "zero_bytes")
    with pytest.raises(UnregisteredPaperDatabase):
        engine.pause(path, "synthetic premature pause")
    data = create_demo(tmp_path / "synthetic-inputs", sessions=70)
    engine.run(Path("configs/personal/synthetic_demo.yaml"), data["data"], data["fx"], path)
    status = engine.status(path)
    assert status["manifest"]["experiment_id"] == "synthetic_plumbing_demo"
    engine.pause(path, "synthetic reviewed pause")
    assert all(book["paused"] for book in engine.status(path)["books"].values())


def test_absent_database_is_still_refused_without_creating_it(tmp_path: Path):
    path = tmp_path / "missing" / "paper.sqlite"
    with pytest.raises(PersonalPaperError, match="existing database"):
        engine.pause(path, "synthetic reason")
    with pytest.raises(PersonalPaperError, match="written review"):
        engine.resume(path, REVIEW)
    with pytest.raises(UnregisteredPaperDatabase, match="does not exist"):
        PaperStore(path, require_registration=True)
    assert not path.parent.exists()


@pytest.mark.parametrize("kind", KINDS)
def test_over_budget_worker_publishes_state_for_an_unregistered_file(
    tmp_path: Path, monkeypatch, kind: str
):
    path = _unregistered(tmp_path, kind)
    before = _snapshot(path)
    monkeypatch.setattr(
        worker, "budget_review", lambda *args: {"status": "OVER_BUDGET", "observed_mxn": 501}
    )

    def forbidden(*args, **kwargs):
        pytest.fail("over-budget worker must not fetch or run the engine")

    monkeypatch.setattr(worker.fetch, "fetch_snapshot", forbidden)
    monkeypatch.setattr(worker.engine, "run", forbidden)
    cache = tmp_path / "cache"
    result = worker.run_once(Path("configs/personal/etf_private_v1.yaml"), path, cache)
    assert result == {
        "status": "BUDGET_PAUSED",
        "budget": {"status": "OVER_BUDGET", "observed_mxn": 501},
        "real_money_approved": False,
    }
    published = json.loads((cache / "worker_status.json").read_text(encoding="utf-8"))
    assert published["status"] == "BUDGET_PAUSED"
    assert _snapshot(path) == before


def test_over_budget_worker_still_refuses_an_unrelated_database(tmp_path: Path, monkeypatch):
    path = tmp_path / "unrelated.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY)")
        db.commit()
    monkeypatch.setattr(
        worker, "budget_review", lambda *args: {"status": "OVER_BUDGET", "observed_mxn": 501}
    )
    with pytest.raises(PersonalPaperError, match="unrelated or incompatible schema") as caught:
        worker.run_once(Path("configs/personal/etf_private_v1.yaml"), path, tmp_path / "cache")
    assert not isinstance(caught.value, UnregisteredPaperDatabase)
    assert not (tmp_path / "cache" / "worker_status.json").exists()
