from quant_trade.research.multi_asset_runner import (
    load_multi_asset_config,
    run_multi_asset_research_experiment,
)


def test_runner_artifacts(tmp_path):
    cfg = load_multi_asset_config("configs/research/equal_weight_synthetic.yaml")
    cfg["output_dir"] = str(tmp_path)
    cfg["robustness"] = {}
    res = run_multi_asset_research_experiment(cfg)
    out = __import__("pathlib").Path(res["output_dir"])
    assert (
        (out / "metrics_test.json").exists()
        and (out / "summary.md").exists()
        and (out / "target_weights_test.csv").exists()
    )
