"""Smoke tests guarding top-level CLI subcommand registration."""

from __future__ import annotations

from typer.testing import CliRunner

from quant_trade.cli import app

runner = CliRunner()


def test_top_level_help_lists_command_groups():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for group in ("mining", "carry", "research", "paper", "selection"):
        assert group in result.output


def test_mining_help_lists_v2_commands():
    result = runner.invoke(app, ["mining", "--help"])
    assert result.exit_code == 0
    for command in ("project", "hashprice", "project-scenarios"):
        assert command in result.output


def test_carry_help_lists_commands():
    result = runner.invoke(app, ["carry", "--help"])
    assert result.exit_code == 0
    assert "research" in result.output
    assert "scenarios" in result.output


def test_selection_and_research_expose_v2_commands():
    selection = runner.invoke(app, ["selection", "--help"])
    assert selection.exit_code == 0
    assert "promote-v2" in selection.output
    research = runner.invoke(app, ["research", "--help"])
    assert research.exit_code == 0
    assert "ledger-report" in research.output
