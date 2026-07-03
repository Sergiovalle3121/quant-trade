from quant_trade.cloud.monitoring import JobSummary, MetricEvent, structured_log


def test_metric_serializes():
    assert MetricEvent(name="equity", value=1.5).model_dump()["value"] == 1.5


def test_summary():
    assert JobSummary(run_id="r", job_name="j", status="success", started_at_utc="t").run_id == "r"


def test_logs_redact(capsys):
    structured_log("x", api_key="secret")
    assert "secret" not in capsys.readouterr().out
