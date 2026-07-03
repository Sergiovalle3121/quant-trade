import json

from quant_trade.evidence.config import EvidenceConfig
from quant_trade.evidence.database import connect
from quant_trade.evidence.ingest import ingest_path


def cfg(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text("weights: {}\n", encoding="utf-8")
    return EvidenceConfig(tmp_path / "evidence.sqlite", tmp_path / "outputs", policy)


def test_ingests_artifacts_and_redacts_secret_files(tmp_path):
    root = tmp_path / "outputs"
    root.mkdir()
    (root / "research_metrics.json").write_text(
        json.dumps({"strategy_id": "s1", "sharpe": 1.0}), encoding="utf-8"
    )
    (root / "bad.json").write_text("{bad", encoding="utf-8")
    (root / "api_key.txt").write_text("api_key=SECRET", encoding="utf-8")
    report = ingest_path(cfg(tmp_path), root)
    assert report.artifacts_ingested == 2
    assert report.malformed_artifacts
    assert report.skipped_secret_artifacts
    with connect(tmp_path / "evidence.sqlite") as conn:
        rows = list(conn.execute("SELECT * FROM artifacts WHERE strategy_id='s1'"))
    assert rows
