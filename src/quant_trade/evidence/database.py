"""SQLite database layer for strategy evidence."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

TABLES = [
    "strategies",
    "research_runs",
    "paper_trials",
    "trial_reviews",
    "ops_runs",
    "stress_tests",
    "allocation_runs",
    "decisions",
    "incidents",
    "alerts",
    "artifacts",
    "evidence_links",
    "scorecards",
]

DOMAIN_TABLES = [
    t for t in TABLES if t not in {"strategies", "artifacts", "evidence_links", "scorecards"}
]


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database(database_path: Path) -> None:
    with connect(database_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS strategies ("
            "strategy_id TEXT PRIMARY KEY, "
            "first_seen TEXT DEFAULT CURRENT_TIMESTAMP, "
            "metadata_json TEXT NOT NULL DEFAULT '{}')"
        )
        for table in DOMAIN_TABLES:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "strategy_id TEXT NOT NULL, "
                "artifact_path TEXT NOT NULL, "
                "metadata_json TEXT NOT NULL DEFAULT '{}', "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS artifacts ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "path TEXT UNIQUE NOT NULL, "
            "artifact_type TEXT NOT NULL, "
            "sha256 TEXT NOT NULL, "
            "strategy_id TEXT NOT NULL, "
            "metadata_json TEXT NOT NULL DEFAULT '{}', "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS evidence_links ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "strategy_id TEXT NOT NULL, "
            "source_path TEXT NOT NULL, "
            "target_path TEXT NOT NULL, "
            "relation TEXT NOT NULL, "
            "metadata_json TEXT NOT NULL DEFAULT '{}')"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS scorecards ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "strategy_id TEXT NOT NULL, "
            "overall_score REAL NOT NULL, "
            "overall_status TEXT NOT NULL, "
            "real_money_ready INTEGER NOT NULL DEFAULT 0, "
            "scorecard_json TEXT NOT NULL, "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.commit()


def upsert_strategy(
    conn: sqlite3.Connection, strategy_id: str, metadata: dict[str, Any] | None = None
) -> None:
    conn.execute(
        "INSERT INTO strategies(strategy_id, metadata_json) VALUES (?, ?) "
        "ON CONFLICT(strategy_id) DO NOTHING",
        (strategy_id, json.dumps(metadata or {}, sort_keys=True)),
    )


def insert_artifact(conn: sqlite3.Connection, artifact: Any) -> None:
    upsert_strategy(conn, artifact.strategy_id)
    metadata_json = json.dumps(artifact.metadata, sort_keys=True)
    conn.execute(
        "INSERT OR IGNORE INTO artifacts("
        "path, artifact_type, sha256, strategy_id, metadata_json"
        ") VALUES (?, ?, ?, ?, ?)",
        (
            artifact.path,
            artifact.artifact_type,
            artifact.sha256,
            artifact.strategy_id,
            metadata_json,
        ),
    )
    table = _table_for_type(artifact.artifact_type)
    if table:
        conn.execute(
            f"INSERT INTO {table}(strategy_id, artifact_path, metadata_json) VALUES (?, ?, ?)",
            (artifact.strategy_id, artifact.path, metadata_json),
        )


def _table_for_type(artifact_type: str) -> str | None:
    return {
        "research": "research_runs",
        "paper_trial": "paper_trials",
        "trial_review": "trial_reviews",
        "ops": "ops_runs",
        "stress": "stress_tests",
        "allocation": "allocation_runs",
        "decision": "decisions",
        "incident": "incidents",
        "alert": "alerts",
    }.get(artifact_type)


def fetch_artifacts(conn: sqlite3.Connection, strategy_id: str | None = None) -> list[sqlite3.Row]:
    if strategy_id:
        return list(
            conn.execute(
                "SELECT * FROM artifacts WHERE strategy_id = ? ORDER BY created_at, path",
                (strategy_id,),
            )
        )
    return list(conn.execute("SELECT * FROM artifacts ORDER BY created_at, path"))


def list_strategies(database_path: Path) -> list[str]:
    with connect(database_path) as conn:
        return [
            str(row[0])
            for row in conn.execute("SELECT strategy_id FROM strategies ORDER BY strategy_id")
        ]
