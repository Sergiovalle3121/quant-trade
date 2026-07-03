import json

from quant_trade.evidence.config import EvidenceConfig
from quant_trade.evidence.ingest import ingest_path
from quant_trade.evidence.search import search


def test_search_finds_metadata(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text("weights: {}\n", encoding="utf-8")
    cfg = EvidenceConfig(tmp_path / "evidence.sqlite", tmp_path / "outputs", policy)
    root = tmp_path / "outputs"
    root.mkdir()
    (root / "research.json").write_text(
        json.dumps({"strategy_id": "s1", "note": "drawdown checked"}), encoding="utf-8"
    )
    ingest_path(cfg, root)
    assert search(cfg.database_path, "drawdown")[0]["strategy_id"] == "s1"
