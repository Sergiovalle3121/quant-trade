"""CLI tests for cloud-rental evaluation over the shipped example configs."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from quant_trade.cloud_rental.cli import cloud_rental_app

runner = CliRunner()

AWS_CP = "configs/cloud_rental/aws_control_plane.example.yaml"
AWS_HW = "configs/cloud_rental/aws_hashing_worker.example.yaml"
ALI_CP = "configs/cloud_rental/alibaba_control_plane.example.yaml"
ALI_HW = "configs/cloud_rental/alibaba_hashing_worker.example.yaml"
NOW = "2026-07-24T12:00:00Z"


def test_quote_command_shows_and_checks_freshness():
    result = runner.invoke(
        cloud_rental_app, ["quote", "--config", AWS_CP, "--evaluated-at-utc", NOW]
    )
    assert result.exit_code == 0, result.output
    assert "quote is fresh" in result.output
    assert "aws_resources_created=false" in result.output


def test_evaluate_aws_hashing_is_blocked_pending_approval():
    result = runner.invoke(
        cloud_rental_app, ["evaluate", "--config", AWS_HW, "--evaluated-at-utc", NOW]
    )
    assert result.exit_code == 1  # blocked
    assert "BLOCKED_PENDING_WRITTEN_APPROVAL" in result.output


def test_evaluate_alibaba_hashing_is_blocked_by_policy():
    result = runner.invoke(
        cloud_rental_app, ["evaluate", "--config", ALI_HW, "--evaluated-at-utc", NOW]
    )
    assert result.exit_code == 1
    assert "BLOCKED_PROVIDER_POLICY" in result.output


def test_compare_builds_the_four_row_matrix(tmp_path):
    out_json = tmp_path / "matrix.json"
    out_md = tmp_path / "matrix.md"
    result = runner.invoke(
        cloud_rental_app,
        [
            "compare",
            "--config", AWS_CP, "--config", AWS_HW,
            "--config", ALI_CP, "--config", ALI_HW,
            "--output", str(out_json), "--markdown", str(out_md),
            "--evaluated-at-utc", NOW,
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(out_json.read_text())
    statuses = {(r["provider"], r["purpose"]): r["status"] for r in payload["rows"]}
    assert statuses[("aws", "control_plane")] == "PAPER_CONTROL_PLANE_CANDIDATE"
    assert statuses[("aws", "hashing_worker")] == "BLOCKED_PENDING_WRITTEN_APPROVAL"
    assert statuses[("alibaba", "control_plane")] == "PAPER_CONTROL_PLANE_CANDIDATE"
    assert statuses[("alibaba", "hashing_worker")] == "BLOCKED_PROVIDER_POLICY"
    assert payload["safety"]["external_spend_authorized"] is False
    markdown = out_md.read_text()
    assert "| Provider | Purpose |" in markdown
