from pathlib import Path

from typer.testing import CliRunner

from quant_trade.cli import app

runner = CliRunner()


def test_approvals_cli_offline(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.md"
    evidence.write_text("paper-only evidence", encoding="utf-8")
    cfg = tmp_path / "workflow.yaml"
    cfg.write_text(
        (
            f"run_id: test\noutput_dir: {tmp_path}\n"
            "default_ttl_hours: 24\nrequired_reviewers: [Sergio]\n"
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "approvals",
            "request",
            "--type",
            "paper_trial_continue",
            "--title",
            "Continue",
            "--evidence-path",
            str(evidence),
            "--config",
            str(cfg),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "real_money_approved" in result.output
    list_result = runner.invoke(app, ["approvals", "list", "--config", str(cfg)])
    assert list_result.exit_code == 0
    assert "pending_review" in list_result.output
    assert (
        "secret"
        not in (tmp_path / "test" / "approval_audit.jsonl").read_text(encoding="utf-8").lower()
    )
