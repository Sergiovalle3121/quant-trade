"""Smoke tests for ``quant-trade crypto-lowcap`` on the sealed fixture."""

from __future__ import annotations

import json
from pathlib import Path

from crypto_lowcap_fixture import AT, build_experiment
from typer.testing import CliRunner

from quant_trade.cli import app

runner = CliRunner()


def test_help_lists_every_command() -> None:
    result = runner.invoke(app, ["crypto-lowcap", "--help"])
    assert result.exit_code == 0
    for command in (
        "verify-panel",
        "panel-digest",
        "select",
        "reveal",
        "report",
        "reseal",
        "status",
    ):
        assert command in result.output


def test_verify_panel_passes_on_the_fixture_and_fails_after_a_byte_changes(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    args = [
        "crypto-lowcap",
        "verify-panel",
        "--experiment-dir",
        str(fx["experiment"]),
        "--panel",
        str(fx["panel"]),
        "--universe-dir",
        str(fx["inputs"].universe_dir),
        "--deathlist-dir",
        str(fx["inputs"].deathlist_dir),
        "--venue-dir",
        f"bybit={fx['inputs'].venue_dirs['bybit']}",
        "--at-utc",
        AT,
        "--explain",
    ]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert '"status": "PASS"' in result.output
    assert '"probe"' in result.output
    journal = fx["inputs"].venue_dirs["bybit"] / "journal.jsonl"
    journal.write_text(journal.read_text(encoding="utf-8") + " ", encoding="utf-8")
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert '"status": "FAIL"' in result.output


def test_select_reveal_report_and_status_through_the_cli(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    exp = str(fx["experiment"])
    common = [
        "--experiment-dir",
        exp,
        "--panel",
        str(fx["panel"]),
        "--evaluated-at-utc",
        AT,
        "--code-sha",
        "abc",
    ]
    result = runner.invoke(app, ["crypto-lowcap", "select", *common, "--trials", str(fx["trials"])])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["trials"] == 4
    result = runner.invoke(app, ["crypto-lowcap", "status", "--experiment-dir", exp])
    assert result.exit_code == 0
    assert "SELECTED_CANDIDATE_FROZEN" in result.output
    result = runner.invoke(
        app, ["crypto-lowcap", "reveal", *common, "--reason", "cli fixture reveal"]
    )
    assert result.exit_code == 0, result.output
    assert '"state": "REVEALED"' in result.output
    output = tmp_path / "RESULTS.md"
    result = runner.invoke(
        app, ["crypto-lowcap", "report", "--experiment-dir", exp, "--output", str(output)]
    )
    assert result.exit_code == 0, result.output
    assert output.read_text(encoding="utf-8").startswith("# Low/mid-cap crypto campaign: results")


def test_report_renders_the_committed_experiment_in_its_not_run_state(tmp_path: Path) -> None:
    committed = Path("data/experiments/crypto_lowcap_2026_08")
    if not (committed / "holdout_seal.json").is_file():  # pragma: no cover - checkout without it
        return
    output = tmp_path / "RESULTS.md"
    result = runner.invoke(
        app,
        ["crypto-lowcap", "report", "--experiment-dir", str(committed), "--output", str(output)],
    )
    assert result.exit_code == 0, result.output
    text = output.read_text(encoding="utf-8")
    assert "`NOT_RUN`" in text
    assert "e25722f13e730ddd" in text


def test_reseal_clones_the_declarations_under_a_new_digest(tmp_path: Path) -> None:
    fx = build_experiment(tmp_path)
    new_dir = tmp_path / "resealed"
    digest_args = [
        "--universe-dir",
        str(fx["inputs"].universe_dir),
        "--deathlist-dir",
        str(fx["inputs"].deathlist_dir),
        "--venue-dir",
        f"bybit={fx['inputs'].venue_dirs['bybit']}",
        "--build-report",
        str(fx["inputs"].build_report_path),
    ]
    result = runner.invoke(
        app,
        [
            "crypto-lowcap",
            "panel-digest",
            "--experiment-dir",
            str(new_dir),
            "--panel",
            str(fx["panel"]),
            *digest_args,
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app,
        [
            "crypto-lowcap",
            "reseal",
            "--from-dir",
            str(fx["experiment"]),
            "--to-dir",
            str(new_dir),
            "--panel",
            str(fx["panel"]),
            "--at-utc",
            AT,
            "--code-sha",
            "abc",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["seal_id"] == "resealed"
    assert len(payload["preregistrations"]) == 2
    assert (new_dir / "holdout_seal.json").is_file()
    cloned = json.loads(
        (new_dir / "crypto_lowcap_h3_rebalancing_premium" / "preregistration.json").read_text()
    )
    assert cloned["universe"][0].endswith(payload["panel_digest"])
    assert any("cloned verbatim" in note for note in cloned["notes"])
    result = runner.invoke(
        app,
        [
            "crypto-lowcap",
            "reseal",
            "--from-dir",
            str(fx["experiment"]),
            "--to-dir",
            str(new_dir),
            "--panel",
            str(fx["panel"]),
        ],
    )
    assert result.exit_code != 0  # never rewrites an existing seal


def test_seal_majors_binds_the_declaration_to_the_csv(tmp_path: Path) -> None:
    import pandas as pd

    days = pd.date_range("2020-01-01", periods=400, freq="D", tz="UTC")
    rows = []
    for symbol in ("BTC-USD", "ETH-USD"):
        for i, day in enumerate(days):
            price = 100.0 + i
            rows.append(
                {
                    "timestamp": day.isoformat(),
                    "symbol": symbol,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 1.0,
                }
            )
    csv = tmp_path / "majors.csv"
    pd.DataFrame(rows).to_csv(csv, index=False)
    target = tmp_path / "crypto_majors_trend_test"
    result = runner.invoke(
        app,
        [
            "crypto-lowcap",
            "seal-majors",
            "--data-path",
            str(csv),
            "--experiment-dir",
            str(target),
            "--at-utc",
            AT,
            "--code-sha",
            "abc",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    from quant_trade.data.manifest import file_sha256
    from quant_trade.research.holdout_seal import load_seal, verify_against_dataset
    from quant_trade.research.preregistration import load_preregistration

    sha = file_sha256(csv)
    assert payload["data_sha256"] == sha
    assert [p["experiment_id"] for p in payload["preregistrations"]] == [
        "crypto_majors_h6_trend_vol_target",
        "crypto_majors_h8_vol_target_derisk",
    ]
    prereg = load_preregistration(target / "crypto_majors_h6_trend_vol_target")
    assert prereg.universe[0].endswith(sha)
    assert prereg.max_trials == 4
    assert prereg.selection_criterion["holdout"]["holdout_window"] == payload["holdout_window"]
    h8 = load_preregistration(target / "crypto_majors_h8_vol_target_derisk")
    assert h8.max_trials == 3
    assert h8.universe[0] == prereg.universe[0]
    binding = json.loads((target / "dataset_binding.json").read_text(encoding="utf-8"))
    assert len(binding["preregistrations"]) == 2
    seal = load_seal(target)
    verify_against_dataset(seal, {"dataset/csv": sha})
    assert seal.selection_end < seal.holdout_start
    assert payload["selection_window"][1] == "2020-10-06"  # int(400 * 0.7) = 280 days
    again = runner.invoke(
        app,
        ["crypto-lowcap", "seal-majors", "--data-path", str(csv), "--experiment-dir", str(target)],
    )
    assert again.exit_code != 0
