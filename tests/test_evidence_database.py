from quant_trade.evidence.database import TABLES, connect, initialize_database, insert_artifact
from quant_trade.evidence.models import EvidenceArtifact


def test_evidence_database_initializes(tmp_path):
    db = tmp_path / "evidence.sqlite"
    initialize_database(db)
    with connect(db) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(TABLES).issubset(names)


def test_reingestion_updates_the_indexed_digest(tmp_path):
    db = tmp_path / "evidence.sqlite"
    initialize_database(db)
    first = EvidenceArtifact("artifact.json", "research", "a" * 64, "s1", {"version": 1})
    second = EvidenceArtifact("artifact.json", "research", "b" * 64, "s1", {"version": 2})
    with connect(db) as conn:
        insert_artifact(conn, first)
        insert_artifact(conn, second)
        conn.commit()
        row = conn.execute(
            "SELECT sha256, metadata_json FROM artifacts WHERE path = ?", ("artifact.json",)
        ).fetchone()
    assert row["sha256"] == "b" * 64
    assert '"version": 2' in row["metadata_json"]
