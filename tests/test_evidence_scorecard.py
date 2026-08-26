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


def test_scorecard_revalidates_artifact_digest(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text("minimum_pass_score: 70\nweights: {}\n", encoding="utf-8")
    cfg = EvidenceConfig(tmp_path / "evidence.sqlite", tmp_path / "outputs", policy)
    root = tmp_path / "research"
    root.mkdir()
    artifact = root / "metrics.json"
    artifact.write_text(json.dumps({"strategy_id": "s1", "sharpe": 1.0}), encoding="utf-8")
    ingest_path(cfg, root)

    artifact.write_text(json.dumps({"strategy_id": "s1", "sharpe": 99.0}), encoding="utf-8")
    scorecard = build_scorecard(cfg, "s1")

    assert any("digest mismatch" in issue for issue in scorecard.blocking_issues)
    research = next(c for c in scorecard.categories if c.name == "research_quality")
    assert research.status == "fail"
    assert research.evidence_paths == []


def test_scorecard_rejects_missing_indexed_artifact(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text("minimum_pass_score: 70\nweights: {}\n", encoding="utf-8")
    cfg = EvidenceConfig(tmp_path / "evidence.sqlite", tmp_path / "outputs", policy)
    root = tmp_path / "research"
    root.mkdir()
    artifact = root / "metrics.json"
    artifact.write_text(json.dumps({"strategy_id": "s1"}), encoding="utf-8")
    ingest_path(cfg, root)
    artifact.unlink()

    scorecard = build_scorecard(cfg, "s1")

    assert any("artifact is missing" in issue for issue in scorecard.blocking_issues)


def test_scorecard_accepts_unchanged_artifact_bytes(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text("minimum_pass_score: 70\nweights: {}\n", encoding="utf-8")
    cfg = EvidenceConfig(tmp_path / "evidence.sqlite", tmp_path / "outputs", policy)
    root = tmp_path / "research"
    root.mkdir()
    artifact = root / "metrics.json"
    artifact.write_text(json.dumps({"strategy_id": "s1"}), encoding="utf-8")
    ingest_path(cfg, root)

    scorecard = build_scorecard(cfg, "s1")

    research = next(c for c in scorecard.categories if c.name == "research_quality")
    assert research.evidence_paths == [str(artifact)]
    assert not any("artifact" in issue.lower() for issue in research.blocking_issues)


def test_reingestion_explicitly_accepts_intentional_artifact_change(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text("minimum_pass_score: 70\nweights: {}\n", encoding="utf-8")
    cfg = EvidenceConfig(tmp_path / "evidence.sqlite", tmp_path / "outputs", policy)
    root = tmp_path / "research"
    root.mkdir()
    artifact = root / "metrics.json"
    artifact.write_text(json.dumps({"strategy_id": "s1", "version": 1}), encoding="utf-8")
    ingest_path(cfg, root)
    artifact.write_text(json.dumps({"strategy_id": "s1", "version": 2}), encoding="utf-8")

    assert any("digest mismatch" in issue for issue in build_scorecard(cfg, "s1").blocking_issues)

    ingest_path(cfg, artifact)
    refreshed = build_scorecard(cfg, "s1")
    research = next(c for c in refreshed.categories if c.name == "research_quality")
    assert research.evidence_paths == [str(artifact)]
    assert not any("digest mismatch" in issue for issue in refreshed.blocking_issues)


def test_category_requires_semantic_metadata_not_just_a_matching_filename(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "minimum_pass_score: 70\n"
        "weights: {}\n"
        "metadata_requirements:\n"
        "  research_quality:\n"
        "    - [strategy_id, strategy]\n"
        "    - [dataset_binding, data_sha256]\n",
        encoding="utf-8",
    )
    cfg = EvidenceConfig(tmp_path / "evidence.sqlite", tmp_path / "outputs", policy)
    root = tmp_path / "research"
    root.mkdir()
    artifact = root / "metrics.json"
    artifact.write_text(json.dumps({"strategy_id": "s1"}), encoding="utf-8")
    ingest_path(cfg, root)

    incomplete = build_scorecard(cfg, "s1")
    category = next(c for c in incomplete.categories if c.name == "research_quality")
    assert category.status == "fail"
    assert any("lacks required metadata" in issue for issue in category.blocking_issues)

    artifact.write_text(
        json.dumps({"strategy_id": "s1", "dataset_binding": {"data_sha256": "abc"}}),
        encoding="utf-8",
    )
    ingest_path(cfg, artifact)
    complete = build_scorecard(cfg, "s1")
    category = next(c for c in complete.categories if c.name == "research_quality")
    assert category.status == "pass"
    assert category.evidence_paths == [str(artifact)]
