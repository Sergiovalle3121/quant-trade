"""Tests for reproducing the per-component digest a holdout seal binds to.

The committed first-seal digest recorded six hashes and no recipe. These tests
pin the behaviour that makes that survivable: a recipe-less digest is probed
and resolved or it fails closed; a digest written from now on names its recipe;
and a single changed byte anywhere in the dataset is a verification failure.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from quant_trade.data.panel_digest import (
    DIGEST_FILENAME,
    RECIPE_V2,
    DigestInputs,
    PanelDigestError,
    components_under_recipe,
    load_panel_digest,
    probe_components,
    resolve_recipe,
    verify_panel_digest,
    write_panel_digest,
)
from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    sha256_of_file,
    sha256_of_text,
)
from quant_trade.research.holdout_seal import (
    HoldoutSeal,
    dataset_digest,
    load_seal,
    seal_holdout,
    verify_against_dataset,
)


def _journal(directory: Path, tag: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    records = [{"type": "header", "policy_sha256": tag, "previous_sha256": ""}]
    records.append(
        {
            "type": "day",
            "date": "2020-01-01",
            "previous_sha256": sha256_of_text(canonical_dumps(records[0])),
        }
    )
    with (directory / "journal.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(canonical_dumps(record) + "\n")


def _dataset(root: Path) -> DigestInputs:
    _journal(root / "universe", "u")
    _journal(root / "bybit", "b")
    _journal(root / "binance", "n")
    death = root / "deathlist"
    death.mkdir()
    atomic_write_json(death / "deathlist.json", {"raw_sha256": "a" * 64, "inactive_symbols": []})
    (death / "receipts.jsonl").write_text('{"raw_sha256": "a"}\n', encoding="utf-8")
    experiment = root / "experiment"
    experiment.mkdir()
    atomic_write_json(experiment / "panel_build_report.json", {"rows_in_panel": 3})
    with gzip.open(experiment / "panel.csv.gz", "wb") as handle:
        handle.write(b"timestamp,symbol,close\n2020-01-01,A:1,1.0\n")
    return DigestInputs(
        universe_dir=root / "universe",
        venue_dirs={"bybit": root / "bybit", "binance": root / "binance"},
        deathlist_dir=death,
        build_report_path=experiment / "panel_build_report.json",
        panel_path=experiment / "panel.csv.gz",
    )


def _seal(experiment: Path, digest: str) -> None:
    seal_holdout(
        experiment,
        HoldoutSeal(
            seal_id="fixture",
            dataset_id="fixture_panel",
            dataset_digest=digest,
            selection_start="2018-01-01",
            selection_end="2021-12-31",
            holdout_start="2022-01-01",
            holdout_end="2022-12-31",
            rationale="fixture 70/30",
            sealed_at_utc="2026-01-01T00:00:00Z",
        ),
    )


def test_a_written_digest_names_its_recipe_and_verifies(tmp_path: Path) -> None:
    inputs = _dataset(tmp_path)
    experiment = tmp_path / "experiment"
    payload = write_panel_digest(
        experiment, inputs, rows=3, symbols=1, window=("2020-01-01", "2020-01-01")
    )
    assert payload["recipe"] == RECIPE_V2
    assert payload["digest"] == dataset_digest(payload["components"])
    assert load_panel_digest(experiment)["digest"] == payload["digest"]
    _seal(experiment, payload["digest"])
    verification = verify_panel_digest(experiment, inputs)
    assert verification.status == "PASS", verification.reasons
    assert set(verification.recipe_by_component) == set(payload["components"])
    verify_against_dataset(load_seal(experiment), payload["components"])
    with pytest.raises(PanelDigestError, match="never rewritten"):
        write_panel_digest(experiment, inputs, rows=3, symbols=1, window=("a", "b"))


def test_recipe_v2_hashes_panel_content_not_gzip_frames(tmp_path: Path) -> None:
    inputs = _dataset(tmp_path)
    first = components_under_recipe(inputs, RECIPE_V2)["panel/csv"]
    # Recompress the identical bytes with a different gzip mtime.
    with gzip.open(inputs.panel_path, "rb") as handle:
        content = handle.read()
    with (
        open(inputs.panel_path, "wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=123456789) as handle,
    ):
        handle.write(content)
    assert components_under_recipe(inputs, RECIPE_V2)["panel/csv"] == first
    assert sha256_of_file(inputs.panel_path) != first


def test_one_changed_byte_fails_verification(tmp_path: Path) -> None:
    inputs = _dataset(tmp_path)
    experiment = tmp_path / "experiment"
    payload = write_panel_digest(
        experiment, inputs, rows=3, symbols=1, window=("2020-01-01", "2020-01-01")
    )
    _seal(experiment, payload["digest"])
    journal = inputs.venue_dirs["bybit"] / "journal.jsonl"
    journal.write_text(journal.read_text(encoding="utf-8") + " ", encoding="utf-8")
    verification = verify_panel_digest(experiment, inputs)
    assert verification.status == "FAIL"
    assert any("journal/bybit" in reason for reason in verification.reasons)
    assert any("changed after sealing" in reason for reason in verification.reasons)
    with pytest.raises(Exception, match="changed after sealing"):
        verify_against_dataset(load_seal(experiment), components_under_recipe(inputs, RECIPE_V2))


def test_a_recipe_less_digest_is_probed_and_resolved(tmp_path: Path) -> None:
    """The committed first seal recorded hashes without saying how. Probe them."""
    inputs = _dataset(tmp_path)
    experiment = tmp_path / "experiment"
    # Recorded under a mix of recipes, the way an ad hoc script might have.
    components = {
        "journal/universe": sha256_of_file(inputs.universe_dir / "journal.jsonl"),
        "journal/bybit": sha256_of_file(inputs.venue_dirs["bybit"] / "journal.jsonl"),
        "journal/binance": sha256_of_file(inputs.venue_dirs["binance"] / "journal.jsonl"),
        "journal/deathlist": sha256_of_file(inputs.deathlist_dir / "receipts.jsonl"),
        "panel/build_report": sha256_of_file(inputs.build_report_path),
        "panel/csv": sha256_of_file(inputs.panel_path),
    }
    atomic_write_json(
        experiment / DIGEST_FILENAME,
        {"components": components, "digest": dataset_digest(components), "rows": 3},
    )
    _seal(experiment, dataset_digest(components))
    resolution = resolve_recipe(components, probe_components(inputs))
    assert resolution.resolved
    assert resolution.recipe_by_component["journal/deathlist"] == "receipts"
    assert resolution.recipe_by_component["panel/csv"] == "file"
    verification = verify_panel_digest(experiment, inputs, explain=True)
    assert verification.status == "PASS", verification.reasons
    assert verification.probe is not None
    assert set(verification.probe["panel/build_report"]) == {"file", "canonical", "pretty"}


def test_an_unreproducible_digest_fails_closed_with_the_probe(tmp_path: Path) -> None:
    """No candidate recipe matching means the seal is unverifiable, not passed."""
    inputs = _dataset(tmp_path)
    experiment = tmp_path / "experiment"
    components = {
        component: "f" * 64
        for component in (
            "journal/universe",
            "journal/bybit",
            "journal/binance",
            "journal/deathlist",
            "panel/build_report",
            "panel/csv",
        )
    }
    atomic_write_json(
        experiment / DIGEST_FILENAME,
        {"components": components, "digest": dataset_digest(components)},
    )
    verification = verify_panel_digest(experiment, inputs, explain=True)
    assert verification.status == "FAIL"
    assert verification.actual_digest == ""
    assert any("no candidate recipe reproduces" in r for r in verification.reasons)
    assert any("seal a new seal_id" in r for r in verification.reasons)
    resolution = resolve_recipe(components, probe_components(inputs))
    assert not resolution.resolved
    assert len(resolution.unmatched) == 6


def test_an_edited_digest_file_is_rejected(tmp_path: Path) -> None:
    inputs = _dataset(tmp_path)
    experiment = tmp_path / "experiment"
    write_panel_digest(experiment, inputs, rows=3, symbols=1, window=("a", "b"))
    path = experiment / DIGEST_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["components"]["panel/csv"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PanelDigestError, match="edited after it was written"):
        load_panel_digest(experiment)


def test_a_missing_input_under_a_declared_recipe_is_an_error(tmp_path: Path) -> None:
    inputs = _dataset(tmp_path)
    experiment = tmp_path / "experiment"
    write_panel_digest(experiment, inputs, rows=3, symbols=1, window=("a", "b"))
    inputs.panel_path.unlink()
    verification = verify_panel_digest(experiment, inputs)
    assert verification.status == "FAIL"
    assert any("missing on this machine" in r for r in verification.reasons)
