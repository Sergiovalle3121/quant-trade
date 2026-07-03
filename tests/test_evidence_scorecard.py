import json

from quant_trade.evidence.config import EvidenceConfig
from quant_trade.evidence.ingest import ingest_path
from quant_trade.evidence.scorecard import build_scorecard


def test_scorecard_blocks_missing_evidence_and_never_real_money_ready(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text("minimum_pass_score: 70\nweights: {}\n", encoding="utf-8")
    cfg = EvidenceConfig(tmp_path / "evidence.sqlite", tmp_path / "outputs", policy)
    root = tmp_path / "research"
    root.mkdir()
    (root / "metrics.json").write_text(json.dumps({"strategy_id": "s1"}), encoding="utf-8")
    ingest_path(cfg, root)
    scorecard = build_scorecard(cfg, "s1")
    assert scorecard.real_money_ready is False
    assert scorecard.blocking_issues
    assert scorecard.overall_status != "pass"
