"""A committed artifact must be what its generator emits, on any platform.

V7 had this check and V8/V9 did not, which is how honest generators and lying
artifacts coexisted in main: the source retracted fourteen fabricated claims
while the committed JSON kept publishing them, and nothing went red.

The platform half matters as much as the drift half. Both generators used to
serialise paths with ``str()``, so a regeneration on Windows rewrote
``data/v8_evidence`` as ``data\\v8_evidence`` and forked the artifacts from what
CI produces. These tests run on Linux in CI and on Windows locally, and assert
the same bytes either way.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from quant_trade.evidence.canonical_json import sha256_of_file
from quant_trade.v8.artifacts import generate_v8_artifacts
from quant_trade.v9.artifacts import generate_v9_artifacts

REPO = Path(".")


def _committed(version: str) -> Path:
    return REPO / "artifacts" / version


def _regenerate_beside(version: str, tmp_path: Path) -> Path:
    """Copy the committed set, then regenerate over it.

    Both generators read recorded inputs (network probes, marketplace scans)
    from their own output directory, so regenerating into an empty directory
    silently produces a different, plausible artifact instead of failing.
    """
    out = tmp_path / version
    out.mkdir(parents=True)
    for path in _committed(version).glob("*.json"):
        shutil.copy2(path, out / path.name)
    return out


def _manifest_sha(version: str) -> str:
    manifest = json.loads(
        (_committed(version) / "REGENERATION_MANIFEST.json").read_text(encoding="utf-8")
    )
    return str(manifest["source_commit_sha"])


@pytest.mark.parametrize("version", ["v8", "v9"])
def test_committed_artifacts_match_their_generator(version: str, tmp_path: Path) -> None:
    out = _regenerate_beside(version, tmp_path)
    sha = _manifest_sha(version)
    if version == "v8":
        generate_v8_artifacts(
            REPO,
            evidence_root=REPO / "data/v8_evidence",
            out_dir=out,
            source_commit_sha=sha,
        )
    else:
        generate_v9_artifacts(
            REPO,
            evidence_root=REPO / "data/v9_evidence",
            out_dir=out,
            source_commit_sha=sha,
        )

    drifted = []
    for committed in sorted(_committed(version).glob("*.json")):
        fresh = out / committed.name
        if not fresh.exists():
            continue
        if sha256_of_file(committed) != sha256_of_file(fresh):
            drifted.append(committed.name)
    assert not drifted, (
        f"{version}: committed artifacts no longer match their generator: {drifted}. "
        f"Regenerate them in the same commit as the source change."
    )


@pytest.mark.parametrize("version", ["v7", "v8", "v9"])
def test_no_artifact_carries_a_windows_path_separator(version: str) -> None:
    """Paths must be serialised with as_posix(), never str()."""
    offenders = []
    for path in sorted(_committed(version).glob("*.json")):
        text = path.read_text(encoding="utf-8")
        # A JSON-escaped backslash before a path-ish token.
        if "\\\\" in text and any(
            token in text for token in ("data\\\\", "artifacts\\\\", "configs\\\\")
        ):
            offenders.append(path.name)
    assert not offenders, (
        f"{version}: platform separators found in {offenders}. Serialise paths with "
        f"Path.as_posix() so Linux and Windows produce identical bytes."
    )
