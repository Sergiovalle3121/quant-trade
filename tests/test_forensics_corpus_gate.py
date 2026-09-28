"""A failed corpus read must never certify a zero-signal calibration run."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import forensics_corpus as corpus
import pytest

from quant_trade.audit import importers

FIXTURE = Path(__file__).parent / "fixtures" / "audit_imports" / "mt5_history.html"


def _manifest(tmp_path: Path, *, path: str, sha256: str) -> Path:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "path": path,
                    "url": "https://example.invalid/synthetic",
                    "sha256": sha256,
                    "format": importers.MT5_HISTORY_HTML,
                    "group": "synthetic-account",
                    "genuine": True,
                }
            ]
        )
    )
    return manifest


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_hash_mismatched_file_fails_cli_and_pytest_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: bool
) -> None:
    path = "missing.html" if missing else FIXTURE.name
    sha = hashlib.sha256(FIXTURE.read_bytes()).hexdigest() if missing else "0" * 64
    manifest = _manifest(tmp_path, path=path, sha256=sha)
    root = tmp_path if missing else FIXTURE.parent
    result = corpus.run(manifest, root, which="all")
    assert result["selected_files"] == 1
    assert result["table"] == []
    assert len(corpus.run_errors(result)) == 1
    assert corpus.main([str(manifest), str(root), "--all"]) == 1

    monkeypatch.setattr(corpus, "MANIFEST", str(manifest))
    monkeypatch.setattr(corpus, "ROOT", str(root))
    monkeypatch.setattr(
        corpus, "FROZEN_MANIFEST_SHA256", hashlib.sha256(manifest.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(corpus, "FROZEN_GENUINE_FILES", 1)
    with pytest.raises(AssertionError):
        corpus.test_no_signal_on_genuine_files()


def test_empty_manifest_is_not_a_successful_zero_signal_run(tmp_path: Path) -> None:
    manifest = tmp_path / "empty.json"
    manifest.write_text("[]")
    result = corpus.run(manifest, tmp_path, which="all")
    assert result["selected_files"] == 0
    assert corpus.run_errors(result) == ["no genuine files selected"]
    assert corpus.main([str(manifest), str(tmp_path), "--all"]) == 1


def test_complete_synthetic_fixture_passes_corpus_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _manifest(
        tmp_path, path=FIXTURE.name, sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    )
    result = corpus.run(manifest, FIXTURE.parent, which="all")
    assert result["selected_files"] == len(result["files"]) == 1
    assert corpus.run_errors(result) == []
    assert corpus.main([str(manifest), str(FIXTURE.parent), "--all"]) == 0

    monkeypatch.setattr(corpus, "MANIFEST", str(manifest))
    monkeypatch.setattr(corpus, "ROOT", str(FIXTURE.parent))
    monkeypatch.setattr(
        corpus, "FROZEN_MANIFEST_SHA256", hashlib.sha256(manifest.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(corpus, "FROZEN_GENUINE_FILES", 1)
    corpus.test_no_signal_on_genuine_files()
