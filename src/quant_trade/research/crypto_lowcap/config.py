"""The declared trial grid, and the lock that freezes it on first use.

The grid is a YAML file committed before any evaluation runs. Its sha256 is
written into ``campaign_lock.json`` on the first ``select``; every later run
must present the same file, the same panel digest and the same gate files, or
it is refused. That is the mechanism that turns "we declared four variants"
into something a reader can check: a fifth variant is a different file with a
different hash, and the lock says which one the results came from.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from quant_trade.evidence.canonical_json import atomic_write_json, load_json, sha256_of_file

SCHEMA_VERSION = 1
LOCK_FILENAME = "campaign_lock.json"

#: The declared program-wide bases a config must state. Each is a decision, and
#: a decision that is not written down can be re-made after the results.
REQUIRED_TOP_LEVEL = (
    "common",
    "walk_forward",
    "turnover",
    "deflated_sharpe",
    "gates",
    "hypotheses",
)


class CampaignConfigError(RuntimeError):
    """Raised when a trial grid is malformed or a lock is contradicted."""


@dataclass(frozen=True)
class CommonSettings:
    order_notional_usd: float = 1_000.0
    turnover_multiple: float = 50.0
    liquidity_window: int = 90
    initial_capital_usd: float = 1_000.0
    quantile: str = "p75"
    min_executable_fraction: float = 1.0
    cost_multipliers: tuple[float, ...] = (1.0, 2.0, 3.0)
    bootstrap_seed: int = 20260812
    bootstrap_samples: int = 1000
    bootstrap_block_size: float = 20.0
    cscv_partitions: int = 8

    def signal_params(self) -> dict[str, Any]:
        """The parameters every signal receives before its own variant."""
        return {
            "order_notional_usd": self.order_notional_usd,
            "turnover_multiple": self.turnover_multiple,
            "liquidity_window": self.liquidity_window,
        }


@dataclass(frozen=True)
class HypothesisSpec:
    experiment_id: str
    strategy: str
    gate: str
    variants: tuple[dict[str, Any], ...]
    control: dict[str, Any]
    control_strategy: str | None = None
    control_shared: bool = False
    refutation_checks: tuple[str, ...] = ("beats_control", "beats_ew_bh")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrialsConfig:
    path: str
    sha256: str
    common: CommonSettings
    walk_forward: dict[str, Any]
    turnover: dict[str, Any]
    deflated_sharpe: dict[str, Any]
    gates: dict[str, str]
    benchmarks: dict[str, Any]
    hypotheses: tuple[HypothesisSpec, ...]
    schema_version: int = SCHEMA_VERSION
    notes: list[str] = field(default_factory=list)

    @property
    def declared_trials(self) -> int:
        return sum(len(h.variants) for h in self.hypotheses)

    def hypothesis(self, experiment_id: str) -> HypothesisSpec:
        for spec in self.hypotheses:
            if spec.experiment_id == experiment_id:
                return spec
        raise CampaignConfigError(f"no hypothesis {experiment_id!r} in {self.path}")

    def gate_paths(self) -> dict[str, str]:
        """Every gate file the campaign scores against, by name."""
        paths = dict(self.gates)
        for spec in self.hypotheses:
            paths.setdefault(f"primary:{spec.experiment_id}", spec.gate)
        return paths


def _require_mapping(payload: Any, name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CampaignConfigError(f"{name} must be a mapping")
    return payload


def load_trials_config(path: str | Path) -> TrialsConfig:
    """Parse and validate the grid. Anything ambiguous is an error, not a default."""
    target = Path(path)
    if not target.is_file():
        raise CampaignConfigError(f"no trials config at {target}")
    raw = _require_mapping(yaml.safe_load(target.read_text(encoding="utf-8")) or {}, str(target))
    for key in REQUIRED_TOP_LEVEL:
        if key not in raw:
            raise CampaignConfigError(f"{target}: missing required section {key!r}")
    common_raw = _require_mapping(raw["common"], "common")
    known = {f for f in CommonSettings.__dataclass_fields__}
    unknown = sorted(set(common_raw) - known)
    if unknown:
        raise CampaignConfigError(f"{target}: unknown common settings {unknown}")
    if "cost_multipliers" in common_raw:
        common_raw = {
            **common_raw,
            "cost_multipliers": tuple(float(v) for v in common_raw["cost_multipliers"]),
        }
    common = CommonSettings(**common_raw)
    if 1.0 not in common.cost_multipliers:
        raise CampaignConfigError("cost_multipliers must include 1.0, the measured model itself")

    walk_forward = _require_mapping(raw["walk_forward"], "walk_forward")
    for key in ("scheme", "test_years", "embargo_days"):
        if key not in walk_forward:
            raise CampaignConfigError(f"walk_forward.{key} is required")
    turnover = _require_mapping(raw["turnover"], "turnover")
    if turnover.get("basis") not in ("annual_x_holdout_years", "raw_total"):
        raise CampaignConfigError("turnover.basis must be annual_x_holdout_years or raw_total")
    if turnover["basis"] == "annual_x_holdout_years" and "holdout_years" not in turnover:
        raise CampaignConfigError("turnover.holdout_years is required for annual_x_holdout_years")
    deflated = _require_mapping(raw["deflated_sharpe"], "deflated_sharpe")
    if "sharpe_variance_floor" not in deflated:
        raise CampaignConfigError("deflated_sharpe.sharpe_variance_floor is required")
    gates = {str(k): str(v) for k, v in _require_mapping(raw["gates"], "gates").items()}
    benchmarks = _require_mapping(raw.get("benchmarks", {}), "benchmarks")

    hypotheses: list[HypothesisSpec] = []
    for experiment_id, spec_raw in _require_mapping(raw["hypotheses"], "hypotheses").items():
        spec = _require_mapping(spec_raw, f"hypotheses.{experiment_id}")
        for key in ("strategy", "gate", "variants", "control"):
            if key not in spec:
                raise CampaignConfigError(f"hypotheses.{experiment_id}.{key} is required")
        variants = spec["variants"]
        if not isinstance(variants, list) or not variants:
            raise CampaignConfigError(
                f"hypotheses.{experiment_id}.variants must be a non-empty list"
            )
        for variant in variants:
            _require_mapping(variant, f"hypotheses.{experiment_id}.variants[]")
        seen = {tuple(sorted(v.items())) for v in variants}
        if len(seen) != len(variants):
            raise CampaignConfigError(
                f"hypotheses.{experiment_id}: duplicate variants would count one trial twice"
            )
        hypotheses.append(
            HypothesisSpec(
                experiment_id=str(experiment_id),
                strategy=str(spec["strategy"]),
                gate=str(spec["gate"]),
                variants=tuple(dict(v) for v in variants),
                control=dict(_require_mapping(spec["control"], "control")),
                control_strategy=(
                    str(spec["control_strategy"]) if spec.get("control_strategy") else None
                ),
                control_shared=bool(spec.get("control_shared", False)),
                refutation_checks=tuple(
                    str(c) for c in spec.get("refutation_checks", ("beats_control", "beats_ew_bh"))
                ),
            )
        )
    if not hypotheses:
        raise CampaignConfigError("at least one hypothesis is required")

    return TrialsConfig(
        path=str(target),
        sha256=sha256_of_file(target),
        common=common,
        walk_forward=dict(walk_forward),
        turnover=dict(turnover),
        deflated_sharpe=dict(deflated),
        gates=gates,
        benchmarks=dict(benchmarks),
        hypotheses=tuple(hypotheses),
        schema_version=int(raw.get("schema_version", SCHEMA_VERSION)),
        notes=[str(n) for n in raw.get("notes", [])],
    )


# --- the lock ---------------------------------------------------------------


def lock_payload(
    *,
    seal_id: str,
    panel_digest: str,
    panel_content_sha256: str,
    digest_recipe: dict[str, str],
    trials_config_path: str,
    trials_config_sha256: str,
    gate_shas: dict[str, str],
    code_sha: str,
    at_utc: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "seal_id": seal_id,
        "panel_digest": panel_digest,
        "panel_content_sha256": panel_content_sha256,
        "digest_recipe": dict(digest_recipe),
        "trials_config_path": trials_config_path,
        "trials_config_sha256": trials_config_sha256,
        "gate_shas": dict(gate_shas),
        "code_sha_first_run": code_sha,
        "first_run_at_utc": at_utc,
    }


def write_lock(experiment_dir: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(experiment_dir) / LOCK_FILENAME
    if path.exists():
        raise CampaignConfigError(f"{path} already exists; a lock is written once")
    atomic_write_json(path, payload)
    return path


def read_lock(experiment_dir: str | Path) -> dict[str, Any] | None:
    path = Path(experiment_dir) / LOCK_FILENAME
    if not path.exists():
        return None
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise CampaignConfigError(f"{path} is not a lock object")
    return payload


def assert_lock_matches(
    lock: dict[str, Any],
    *,
    panel_digest: str,
    panel_content_sha256: str,
    trials_config_sha256: str,
    gate_shas: dict[str, str],
) -> None:
    """Refuse a run whose inputs differ from the ones the first run locked."""
    problems: list[str] = []
    if lock.get("panel_digest") != panel_digest:
        problems.append("panel digest differs from the locked one")
    if lock.get("panel_content_sha256") != panel_content_sha256:
        problems.append("panel bytes differ from the locked ones")
    if lock.get("trials_config_sha256") != trials_config_sha256:
        problems.append(
            "trials config sha256 differs from the locked one: the declared grid was edited "
            "after the first run, which is a new search, not a continuation"
        )
    locked_gates = lock.get("gate_shas", {})
    for name, sha in gate_shas.items():
        if locked_gates.get(name) != sha:
            problems.append(f"gate {name!r} differs from the locked one")
    if problems:
        raise CampaignConfigError("campaign lock mismatch: " + "; ".join(problems))


__all__ = [
    "LOCK_FILENAME",
    "CampaignConfigError",
    "CommonSettings",
    "HypothesisSpec",
    "TrialsConfig",
    "assert_lock_matches",
    "load_trials_config",
    "lock_payload",
    "read_lock",
    "write_lock",
]
