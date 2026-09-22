"""Reproduce, probe and write the per-component digest a holdout seal binds to.

`research.holdout_seal.dataset_digest` commits to a dataset through a map of
component names to content hashes. It deliberately says nothing about how each
component's hash is produced, and that gap is what this module closes: the
committed ``panel_digest.json`` for the first crypto low-cap seal records six
components and no recipe, and the repository holds no code that reproduces
them. A seal whose components cannot be recomputed is a number, not evidence.

Two consequences shape the design:

**Probe, then resolve.** For a digest recorded without a recipe, every
declared candidate recipe is computed per component and the one reproducing
the recorded hash is reported. Exactly one recipe per component must match or
the digest is UNRESOLVED and verification fails closed. Nothing here guesses.

**Declare the recipe from now on.** ``write_panel_digest`` records which
recipe produced each component (``RECIPE_V2``) so the next seal never needs
the probe. Recipe v2 hashes the panel's uncompressed content: gzip frames
carry a timestamp, so two byte-identical panels compressed a minute apart
would otherwise disagree about their own identity.

pandas-free.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    canonical_dumps,
    load_json,
    pretty_dumps,
    sha256_of_bytes,
    sha256_of_file,
    sha256_of_text,
)
from quant_trade.research.holdout_seal import dataset_digest

SCHEMA_VERSION = 2

#: Filename the per-component digest is written under inside an experiment dir.
DIGEST_FILENAME = "panel_digest.json"

#: Journal filename shared by the universe and venue collectors.
JOURNAL_FILENAME = "journal.jsonl"
DEATHLIST_FILENAME = "deathlist.json"
RECEIPTS_FILENAME = "receipts.jsonl"

COMPONENT_UNIVERSE = "journal/universe"
COMPONENT_DEATHLIST = "journal/deathlist"
COMPONENT_BUILD_REPORT = "panel/build_report"
COMPONENT_PANEL = "panel/csv"


class PanelDigestError(RuntimeError):
    """Raised when a digest cannot be reproduced, resolved, or read."""


@dataclass(frozen=True)
class DigestInputs:
    """Where the dataset's members live on this machine."""

    universe_dir: Path
    venue_dirs: dict[str, Path]
    deathlist_dir: Path
    build_report_path: Path
    panel_path: Path

    def components(self) -> list[str]:
        venues = [f"journal/{venue}" for venue in sorted(self.venue_dirs)]
        return [
            COMPONENT_UNIVERSE,
            *venues,
            COMPONENT_DEATHLIST,
            COMPONENT_BUILD_REPORT,
            COMPONENT_PANEL,
        ]

    def directory_for(self, component: str) -> Path | None:
        if component == COMPONENT_UNIVERSE:
            return self.universe_dir
        if component == COMPONENT_DEATHLIST:
            return self.deathlist_dir
        if component.startswith("journal/"):
            return self.venue_dirs.get(component.split("/", 1)[1])
        return None


# --- candidate recipes ------------------------------------------------------


def _file_or_none(path: Path) -> str | None:
    return sha256_of_file(path) if path.is_file() else None


def _journal_file(inputs: DigestInputs, component: str) -> str | None:
    directory = inputs.directory_for(component)
    return None if directory is None else _file_or_none(directory / JOURNAL_FILENAME)


def _journal_chain_head(inputs: DigestInputs, component: str) -> str | None:
    """Digest of the last journal record's canonical bytes: the chain head."""
    directory = inputs.directory_for(component)
    if directory is None:
        return None
    path = directory / JOURNAL_FILENAME
    if not path.is_file():
        return None
    last = ""
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                last = line.strip()
    if not last:
        return None
    return sha256_of_text(canonical_dumps(json.loads(last)))


def _deathlist_file(inputs: DigestInputs, component: str) -> str | None:
    return _file_or_none(inputs.deathlist_dir / DEATHLIST_FILENAME)


def _deathlist_receipts(inputs: DigestInputs, component: str) -> str | None:
    return _file_or_none(inputs.deathlist_dir / RECEIPTS_FILENAME)


def _deathlist_raw(inputs: DigestInputs, component: str) -> str | None:
    path = inputs.deathlist_dir / DEATHLIST_FILENAME
    if not path.is_file():
        return None
    payload = load_json(path)
    raw = payload.get("raw_sha256") if isinstance(payload, dict) else None
    return str(raw) if raw else None


def _report_file(inputs: DigestInputs, component: str) -> str | None:
    return _file_or_none(inputs.build_report_path)


def _report_canonical(inputs: DigestInputs, component: str) -> str | None:
    if not inputs.build_report_path.is_file():
        return None
    return sha256_of_text(canonical_dumps(load_json(inputs.build_report_path)))


def _report_pretty(inputs: DigestInputs, component: str) -> str | None:
    if not inputs.build_report_path.is_file():
        return None
    return sha256_of_text(pretty_dumps(load_json(inputs.build_report_path)) + "\n")


def _panel_file(inputs: DigestInputs, component: str) -> str | None:
    return _file_or_none(inputs.panel_path)


def panel_content_sha256(path: str | Path) -> str:
    """Digest of a panel file's uncompressed bytes, so gzip headers cannot fork it."""
    target = Path(path)
    if target.suffix != ".gz":
        return sha256_of_bytes(target.read_bytes())
    try:
        with gzip.open(target, "rb") as handle:
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
            return digest.hexdigest()
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise PanelDigestError(f"{target} is not a readable gzip stream: {exc}") from exc


def _panel_content(inputs: DigestInputs, component: str) -> str | None:
    if not inputs.panel_path.is_file():
        return None
    return panel_content_sha256(inputs.panel_path)


Recipe = Callable[[DigestInputs, str], str | None]

#: Candidate recipes per component family, in preference order. The first
#: recipe reproducing a recorded hash is the one reported.
RECIPES: dict[str, dict[str, Recipe]] = {
    "journal": {"file": _journal_file, "chain_head": _journal_chain_head},
    "deathlist": {
        "file": _deathlist_file,
        "receipts": _deathlist_receipts,
        "raw": _deathlist_raw,
    },
    "build_report": {
        "file": _report_file,
        "canonical": _report_canonical,
        "pretty": _report_pretty,
    },
    "panel": {"content": _panel_content, "file": _panel_file},
}


def family_of(component: str) -> str:
    if component == COMPONENT_DEATHLIST:
        return "deathlist"
    if component.startswith("journal/"):
        return "journal"
    if component == COMPONENT_BUILD_REPORT:
        return "build_report"
    if component == COMPONENT_PANEL:
        return "panel"
    raise PanelDigestError(f"unknown digest component {component!r}")


#: The declared recipe for every digest written from now on.
RECIPE_V2: dict[str, str] = {
    "journal": "file",
    "deathlist": "file",
    "build_report": "canonical",
    "panel": "content",
}


def compute_component(inputs: DigestInputs, component: str, recipe: str) -> str:
    family = family_of(component)
    try:
        function = RECIPES[family][recipe]
    except KeyError as exc:
        raise PanelDigestError(
            f"no recipe {recipe!r} for {component!r}; known: {sorted(RECIPES[family])}"
        ) from exc
    value = function(inputs, component)
    if value is None:
        raise PanelDigestError(
            f"{component!r} cannot be computed under recipe {recipe!r}: its input is "
            "missing on this machine"
        )
    return value


def components_under_recipe(
    inputs: DigestInputs, recipe_by_family: dict[str, str]
) -> dict[str, str]:
    """Every component hashed under one declared recipe per family."""
    return {
        component: compute_component(inputs, component, recipe_by_family[family_of(component)])
        for component in inputs.components()
    }


# --- probing an undeclared digest ------------------------------------------


def probe_components(inputs: DigestInputs) -> dict[str, dict[str, str | None]]:
    """Every component under every candidate recipe; ``None`` = input absent."""
    probe: dict[str, dict[str, str | None]] = {}
    for component in inputs.components():
        family = family_of(component)
        probe[component] = {
            name: function(inputs, component) for name, function in RECIPES[family].items()
        }
    return probe


@dataclass(frozen=True)
class RecipeResolution:
    """Which recipe reproduces each recorded component, or why none does."""

    resolved: bool
    recipe_by_component: dict[str, str] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)
    missing_from_record: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_recipe(
    recorded_components: dict[str, str], probe: dict[str, dict[str, str | None]]
) -> RecipeResolution:
    """Match recorded hashes against the probe. Fails closed on any gap."""
    recipe_by_component: dict[str, str] = {}
    unmatched: list[str] = []
    missing = sorted(set(recorded_components) - set(probe))
    for component, candidates in probe.items():
        expected = recorded_components.get(component)
        if expected is None:
            unmatched.append(component)
            continue
        matches = [name for name, value in candidates.items() if value == expected]
        if not matches:
            unmatched.append(component)
            continue
        recipe_by_component[component] = matches[0]
    resolved = not unmatched and not missing
    return RecipeResolution(
        resolved=resolved,
        recipe_by_component=recipe_by_component if resolved else {},
        unmatched=sorted(unmatched),
        missing_from_record=missing,
    )


# --- reading and writing ----------------------------------------------------


def load_panel_digest(experiment_dir: str | Path) -> dict[str, Any]:
    path = Path(experiment_dir) / DIGEST_FILENAME
    if not path.is_file():
        raise PanelDigestError(f"no {DIGEST_FILENAME} at {path}")
    payload = load_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("components"), dict):
        raise PanelDigestError(f"{path} does not carry a components map")
    claimed = str(payload.get("digest", ""))
    actual = dataset_digest({str(k): str(v) for k, v in payload["components"].items()})
    if claimed != actual:
        raise PanelDigestError(
            f"{path}: recorded digest {claimed[:12]}... does not hash from its own "
            f"components ({actual[:12]}...); the file was edited after it was written"
        )
    return payload


def write_panel_digest(
    experiment_dir: str | Path,
    inputs: DigestInputs,
    *,
    rows: int,
    symbols: int,
    window: tuple[str, str],
    recipe_by_family: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Write a digest that names its own recipe. Refuses to overwrite."""
    out = Path(experiment_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / DIGEST_FILENAME
    if path.exists():
        raise PanelDigestError(
            f"{path} already exists; a digest a seal was bound to is never rewritten. "
            "Write the new panel's digest into a new experiment directory."
        )
    recipe = dict(RECIPE_V2 if recipe_by_family is None else recipe_by_family)
    components = components_under_recipe(inputs, recipe)
    payload = {
        "components": components,
        "digest": dataset_digest(components),
        "recipe": recipe,
        "rows": int(rows),
        "schema_version": SCHEMA_VERSION,
        "symbols": int(symbols),
        "window": [window[0], window[1]],
    }
    atomic_write_json(path, payload)
    return payload


# --- verification -----------------------------------------------------------


@dataclass(frozen=True)
class PanelVerification:
    status: str  # "PASS" | "FAIL"
    expected_digest: str
    actual_digest: str
    recipe_by_component: dict[str, str]
    reasons: list[str]
    probe: dict[str, dict[str, str | None]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def verify_panel_digest(
    experiment_dir: str | Path,
    inputs: DigestInputs,
    *,
    explain: bool = False,
) -> PanelVerification:
    """Reproduce the recorded digest from bytes on disk, or say exactly why not.

    A recorded recipe is used as declared. A digest recorded without one is
    probed; every component must be reproduced by some candidate recipe or the
    verification fails, and ``explain`` returns the full probe so the reader can
    see which hashes were tried.
    """
    recorded = load_panel_digest(experiment_dir)
    expected = str(recorded["digest"])
    recorded_components = {str(k): str(v) for k, v in recorded["components"].items()}
    reasons: list[str] = []
    probe = probe_components(inputs) if explain or "recipe" not in recorded else None

    if isinstance(recorded.get("recipe"), dict):
        recipe_by_family = {str(k): str(v) for k, v in recorded["recipe"].items()}
        try:
            components = components_under_recipe(inputs, recipe_by_family)
        except PanelDigestError as exc:
            return PanelVerification("FAIL", expected, "", {}, [str(exc)], probe)
        recipe_by_component = {c: recipe_by_family[family_of(c)] for c in components}
    else:
        assert probe is not None
        resolution = resolve_recipe(recorded_components, probe)
        if not resolution.resolved:
            if resolution.unmatched:
                reasons.append(
                    "no candidate recipe reproduces the recorded hash for: "
                    + ", ".join(resolution.unmatched)
                )
            if resolution.missing_from_record:
                reasons.append(
                    "components present on disk but absent from the record: "
                    + ", ".join(resolution.missing_from_record)
                )
            reasons.append(
                "the recorded digest cannot be reproduced from these bytes; the seal "
                "bound to it is unverifiable here and must not be evaluated against. "
                "Rebuild the panel, write a digest that declares its recipe, and seal "
                "a new seal_id against it."
            )
            return PanelVerification("FAIL", expected, "", {}, reasons, probe)
        recipe_by_component = resolution.recipe_by_component
        components = {c: str(probe[c][r]) for c, r in recipe_by_component.items()}

    actual = dataset_digest(components)
    if set(components) != set(recorded_components):
        reasons.append(
            "component sets differ: recorded "
            f"{sorted(recorded_components)} vs computed {sorted(components)}"
        )
    for component, value in components.items():
        if recorded_components.get(component) != value:
            reasons.append(
                f"{component}: recorded {recorded_components.get(component, '')[:12]}... "
                f"computed {value[:12]}... under recipe {recipe_by_component[component]!r}"
            )
    if actual != expected:
        reasons.append(
            f"dataset digest {actual[:12]}... does not match the recorded "
            f"{expected[:12]}...; the panel changed after sealing"
        )
    status = "PASS" if not reasons else "FAIL"
    return PanelVerification(status, expected, actual, recipe_by_component, reasons, probe)


__all__ = [
    "COMPONENT_BUILD_REPORT",
    "COMPONENT_DEATHLIST",
    "COMPONENT_PANEL",
    "COMPONENT_UNIVERSE",
    "DIGEST_FILENAME",
    "RECIPES",
    "RECIPE_V2",
    "DigestInputs",
    "PanelDigestError",
    "PanelVerification",
    "RecipeResolution",
    "components_under_recipe",
    "compute_component",
    "family_of",
    "load_panel_digest",
    "panel_content_sha256",
    "probe_components",
    "resolve_recipe",
    "verify_panel_digest",
    "write_panel_digest",
]
