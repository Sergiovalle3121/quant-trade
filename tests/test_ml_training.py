from quant_trade.ml.config import MLConfig
from quant_trade.ml.training import run_ml_workflow


def test_ml_training_writes_research_artifacts(tmp_path):
    cfg = MLConfig(
        run_id="test_run",
        output_root=str(tmp_path),
        start="2020-01-01",
        end="2020-04-01",
    )
    result = run_ml_workflow(cfg)
    assert result["metrics_test"]["real_money_ready"] is False
    assert (tmp_path / "test_run" / "model_card.md").exists()
