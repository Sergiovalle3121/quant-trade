"""Local BYOD audit runner.

The runner reads bounded CSV/JSON/JSONL evidence.  It never imports customer
modules, evaluates expressions, shells out, or makes a network request.
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeGuard

import yaml

from quant_trade.audit.models import (
    AuditBundle,
    AuditCheck,
    AuditInput,
    AuditJob,
    AuditStatus,
    AuditVerdict,
    FindingClass,
)
from quant_trade.audit.render import render_html
from quant_trade.evidence.canonical_json import (
    atomic_write_json,
    atomic_write_text,
    canonical_dumps,
    sha256_of_file,
    sha256_of_text,
)

_DATASET_SUFFIXES = {".csv", ".json", ".jsonl"}
_EVIDENCE_SUFFIXES = {".json"}
_HARD_MAX_FILE_BYTES = 100_000_000
_LOOKAHEAD_TOKENS = (
    "future_",
    "forward_",
    "next_return",
    "next_period",
    "lead_",
    "target_return",
    "tomorrow_",
)


def _parse_utc(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include an explicit UTC offset")
    return parsed.astimezone(UTC)


def _is_finite_number(value: object) -> TypeGuard[int | float]:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _require_mapping(payload: object, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain an object")
    return {str(key): value for key, value in payload.items()}


def _contained_path(root: Path, raw_path: str, *, label: str, suffixes: set[str]) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label} does not exist or cannot be resolved") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the declared root directory") from exc
    if not resolved.is_file():
        raise ValueError(f"{label} must be a regular file")
    if resolved.suffix.lower() not in suffixes:
        allowed = ", ".join(sorted(suffixes))
        raise ValueError(f"{label} format is not allowed; expected one of {allowed}")
    return resolved


def _optional_contained_path(
    root: Path, raw_path: object, *, label: str, suffixes: set[str]
) -> str | None:
    if raw_path is None or str(raw_path).strip() == "":
        return None
    return str(_contained_path(root, str(raw_path), label=label, suffixes=suffixes))


def load_audit_input(config_path: str | Path) -> AuditInput:
    """Load a small trusted YAML config and resolve every evidence path safely."""
    config = Path(config_path).resolve(strict=True)
    if config.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("audit config must be YAML")
    if config.stat().st_size > 1_000_000:
        raise ValueError("audit config exceeds the 1 MB safety limit")
    payload = _require_mapping(yaml.safe_load(config.read_text(encoding="utf-8")), "config")

    raw_root = Path(str(payload.get("root_dir", ".")))
    if not raw_root.is_absolute():
        raw_root = config.parent / raw_root
    root = raw_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("root_dir must be a directory")
    # A config may narrow its trust root, but cannot silently widen it outside
    # the directory in which the operator placed the config.
    try:
        root.relative_to(config.parent.resolve())
    except ValueError as exc:
        raise ValueError("root_dir must be contained by the config directory") from exc

    raw_max_bytes = payload.get("max_file_size_bytes", 25_000_000)
    if isinstance(raw_max_bytes, bool) or not isinstance(raw_max_bytes, int):
        raise ValueError("max_file_size_bytes must be an integer")
    max_bytes = raw_max_bytes
    if max_bytes <= 0 or max_bytes > _HARD_MAX_FILE_BYTES:
        raise ValueError("max_file_size_bytes must be between 1 and 100000000")
    cutoff = str(payload.get("evaluation_cutoff_utc", "")).strip()
    if not cutoff:
        raise ValueError("evaluation_cutoff_utc is required")
    _parse_utc(cutoff)
    required = payload.get("required_columns", [])
    if (
        not isinstance(required, list)
        or not required
        or not all(isinstance(column, str) and column.strip() for column in required)
    ):
        raise ValueError("required_columns must be a non-empty list of names")

    dataset = _contained_path(
        root, str(payload.get("dataset_path", "")), label="dataset_path", suffixes=_DATASET_SUFFIXES
    )
    results = _contained_path(
        root,
        str(payload.get("results_path", "")),
        label="results_path",
        suffixes=_EVIDENCE_SUFFIXES,
    )
    manifest = _optional_contained_path(
        root, payload.get("manifest_path"), label="manifest_path", suffixes=_EVIDENCE_SUFFIXES
    )
    ledger = _optional_contained_path(
        root,
        payload.get("trial_ledger_path"),
        label="trial_ledger_path",
        suffixes=_EVIDENCE_SUFFIXES,
    )
    return AuditInput(
        root_dir=str(root),
        dataset_path=str(dataset),
        results_path=str(results),
        manifest_path=manifest,
        trial_ledger_path=ledger,
        evaluation_cutoff_utc=cutoff,
        required_columns=tuple(str(column).strip() for column in required),
        timestamp_column=str(payload.get("timestamp_column", "timestamp")).strip(),
        max_file_size_bytes=max_bytes,
        symbol_column=str(payload.get("symbol_column", "symbol")).strip(),
    )


def _validate_runtime_paths(audit_input: AuditInput) -> dict[str, Path]:
    root = Path(audit_input.root_dir).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("audit root is not a directory")
    raw_paths = {
        "dataset": (audit_input.dataset_path, _DATASET_SUFFIXES),
        "results": (audit_input.results_path, _EVIDENCE_SUFFIXES),
    }
    if audit_input.manifest_path:
        raw_paths["manifest"] = (audit_input.manifest_path, _EVIDENCE_SUFFIXES)
    if audit_input.trial_ledger_path:
        raw_paths["trial_ledger"] = (audit_input.trial_ledger_path, _EVIDENCE_SUFFIXES)
    resolved: dict[str, Path] = {}
    for label, (raw, suffixes) in raw_paths.items():
        path = _contained_path(root, raw, label=label, suffixes=suffixes)
        if path.stat().st_size > audit_input.max_file_size_bytes:
            raise ValueError(f"{label} exceeds max_file_size_bytes")
        resolved[label] = path
    return resolved


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    return _require_mapping(payload, label)


def _rows_from_payload(payload: object) -> list[dict[str, Any]]:
    candidate = payload
    if isinstance(payload, dict):
        for key in ("rows", "records", "data", "snapshots"):
            if key in payload:
                candidate = payload[key]
                break
    if not isinstance(candidate, list) or not candidate:
        raise ValueError("dataset JSON must contain a non-empty row list")
    if not all(isinstance(row, dict) for row in candidate):
        raise ValueError("every dataset row must be an object")
    return [{str(key): value for key, value in row.items()} for row in candidate]


def _load_dataset(path: Path) -> list[dict[str, Any]]:
    try:
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                csv_rows = [dict(row) for row in csv.DictReader(handle)]
            if not csv_rows:
                raise ValueError("dataset CSV has no rows")
            return csv_rows
        if path.suffix.lower() == ".jsonl":
            jsonl_rows: list[dict[str, Any]] = []
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"dataset JSONL row {number} is not an object")
                jsonl_rows.append({str(key): value for key, value in row.items()})
            if not jsonl_rows:
                raise ValueError("dataset JSONL has no rows")
            return jsonl_rows
        return _rows_from_payload(json.loads(path.read_text(encoding="utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("dataset is not valid UTF-8 structured data") from exc


def _check(
    code: str,
    category: str,
    status: AuditStatus,
    summary: str,
    *evidence: str,
    finding_class: FindingClass = FindingClass.DEFECT,
) -> AuditCheck:
    return AuditCheck(code, category, status, summary, tuple(evidence), finding_class)


def _schema_checks(rows: list[dict[str, Any]], audit_input: AuditInput) -> list[AuditCheck]:
    columns = {column for row in rows for column in row}
    missing = sorted(set(audit_input.required_columns) - columns)
    if missing:
        schema = _check(
            "DATASET_SCHEMA",
            "data_integrity",
            AuditStatus.NO_GO,
            "Dataset is missing required columns.",
            f"missing={','.join(missing)}",
        )
    else:
        schema = _check(
            "DATASET_SCHEMA",
            "data_integrity",
            AuditStatus.PASS,
            "Dataset contains every declared required column.",
            f"rows={len(rows)}",
            f"columns={len(columns)}",
        )
    suspicious = sorted(
        column
        for column in columns
        if any(token in column.strip().lower() for token in _LOOKAHEAD_TOKENS)
    )
    if suspicious:
        leakage = _check(
            "LOOKAHEAD_COLUMNS",
            "causality",
            AuditStatus.NO_GO,
            "Column names indicate future information in the research dataset.",
            f"columns={','.join(suspicious)}",
        )
    else:
        leakage = _check(
            "LOOKAHEAD_COLUMNS",
            "causality",
            AuditStatus.PASS,
            "No basic future/lead/target-return column signature was found.",
        )
    return [schema, leakage]


def _timestamp_checks(rows: list[dict[str, Any]], audit_input: AuditInput) -> list[AuditCheck]:
    column = audit_input.timestamp_column
    if not column or any(column not in row for row in rows):
        return [
            _check(
                "TIMESTAMP_CAUSALITY",
                "causality",
                AuditStatus.INSUFFICIENT_EVIDENCE,
                "The declared timestamp column is missing from one or more rows.",
                f"timestamp_column={column}",
            )
        ]
    cutoff = _parse_utc(audit_input.evaluation_cutoff_utc)
    # A panel is causal when each instrument's own history moves forward.  Real
    # exports are almost always sorted by (symbol, timestamp), which is not
    # globally ascending; grouping first is what stops that from reading as a
    # look-ahead defect.  Within a group, a timestamp going backwards still is.
    symbol_column = audit_input.symbol_column
    grouped = bool(symbol_column) and all(symbol_column in row for row in rows)
    parsed_by_series: dict[str, list[datetime]] = {}
    invalid = 0
    future = 0
    availability_violations = 0
    availability_columns = ("feature_available_at", "available_at", "published_at")
    for row in rows:
        try:
            event_time = _parse_utc(str(row[column]))
        except (TypeError, ValueError):
            invalid += 1
            continue
        series = str(row[symbol_column]) if grouped else ""
        parsed_by_series.setdefault(series, []).append(event_time)
        if event_time > cutoff:
            future += 1
        for available_column in availability_columns:
            raw_available = row.get(available_column)
            if raw_available in (None, ""):
                continue
            try:
                if event_time < _parse_utc(str(raw_available)):
                    availability_violations += 1
            except (TypeError, ValueError):
                invalid += 1
    if invalid or future or availability_violations:
        return [
            _check(
                "TIMESTAMP_CAUSALITY",
                "causality",
                AuditStatus.NO_GO,
                "Timestamps are invalid, after the audit cutoff, or precede feature availability.",
                f"invalid={invalid}",
                f"after_cutoff={future}",
                f"availability_violations={availability_violations}",
            )
        ]
    unordered = sorted(
        series for series, values in parsed_by_series.items() if values != sorted(values)
    )
    if unordered:
        scope = f"{symbol_column}={','.join(unordered[:5])}" if grouped else "whole dataset"
        return [
            _check(
                "TIMESTAMP_CAUSALITY",
                "causality",
                AuditStatus.NO_GO,
                "Dataset rows are not ordered causally by the declared timestamp.",
                f"unordered_series={len(unordered)}",
                scope,
            )
        ]
    return [
        _check(
            "TIMESTAMP_CAUSALITY",
            "causality",
            AuditStatus.PASS,
            "All timestamps are parseable, ordered, and on or before the declared cutoff.",
            f"cutoff={audit_input.evaluation_cutoff_utc}",
            f"series={len(parsed_by_series)}" if grouped else "series=whole dataset",
        )
    ]


def _manifest_check(
    path: Path | None,
    dataset: Path,
    dataset_hash: str,
    evaluation_cutoff_utc: str,
) -> AuditCheck:
    if path is None:
        return _check(
            "MANIFEST_PROVENANCE",
            "provenance",
            AuditStatus.INSUFFICIENT_EVIDENCE,
            "No dataset manifest was supplied.",
        )
    manifest = _load_json_object(path, "manifest")
    declared_hash = str(manifest.get("byte_sha256") or manifest.get("dataset_sha256") or "")
    if declared_hash != dataset_hash:
        return _check(
            "MANIFEST_PROVENANCE",
            "provenance",
            AuditStatus.NO_GO,
            "Manifest is not bound to the supplied dataset bytes.",
            f"declared_sha256={declared_hash or '<missing>'}",
            f"actual_sha256={dataset_hash}",
        )
    declared_size = manifest.get("size_bytes")
    if declared_size is not None and (
        isinstance(declared_size, bool)
        or not isinstance(declared_size, int)
        or declared_size != dataset.stat().st_size
    ):
        return _check(
            "MANIFEST_PROVENANCE",
            "provenance",
            AuditStatus.NO_GO,
            "Manifest size does not match the supplied dataset.",
        )
    required = ("source_name", "data_source", "captured_at_utc")
    missing = [name for name in required if not str(manifest.get(name, "")).strip()]
    has_usage_basis = any(
        str(manifest.get(name, "")).strip()
        for name in ("provenance_notes", "terms_url", "license", "usage_rights")
    )
    if missing or not has_usage_basis:
        details = [f"missing={','.join(missing)}"] if missing else []
        if not has_usage_basis:
            details.append("missing=usage_rights_or_provenance_notes")
        return _check(
            "MANIFEST_PROVENANCE",
            "provenance",
            AuditStatus.INSUFFICIENT_EVIDENCE,
            "Dataset bytes match, but provenance metadata is incomplete.",
            *details,
        )
    try:
        captured_at = _parse_utc(str(manifest["captured_at_utc"]))
    except (TypeError, ValueError):
        return _check(
            "MANIFEST_PROVENANCE",
            "provenance",
            AuditStatus.NO_GO,
            "Manifest capture time is invalid or lacks an explicit timezone offset.",
        )
    if captured_at > _parse_utc(evaluation_cutoff_utc):
        return _check(
            "MANIFEST_PROVENANCE",
            "provenance",
            AuditStatus.NO_GO,
            "Manifest capture time is after the declared evaluation cutoff.",
            f"captured_at_utc={manifest['captured_at_utc']}",
            f"evaluation_cutoff_utc={evaluation_cutoff_utc}",
        )
    return _check(
        "MANIFEST_PROVENANCE",
        "provenance",
        AuditStatus.PASS,
        "Manifest hash, size, source, capture time, and usage provenance are declared.",
        f"dataset_sha256={dataset_hash}",
    )


def _results_binding_check(results: dict[str, Any], dataset_hash: str) -> AuditCheck:
    declared = str(results.get("dataset_sha256", ""))
    if not declared:
        return _check(
            "RESULT_DATASET_BINDING",
            "reproducibility",
            AuditStatus.INSUFFICIENT_EVIDENCE,
            "Results do not declare the dataset SHA-256.",
        )
    if declared != dataset_hash:
        return _check(
            "RESULT_DATASET_BINDING",
            "reproducibility",
            AuditStatus.NO_GO,
            "Results were not produced from the supplied dataset bytes.",
            f"declared_sha256={declared}",
            f"actual_sha256={dataset_hash}",
        )
    return _check(
        "RESULT_DATASET_BINDING",
        "reproducibility",
        AuditStatus.PASS,
        "Results are bound to the supplied dataset bytes.",
    )


def _execution_check(results: dict[str, Any]) -> AuditCheck:
    execution = results.get("execution")
    if not isinstance(execution, dict) or "signal_lag_bars" not in execution:
        return _check(
            "NEXT_BAR_EXECUTION",
            "execution",
            AuditStatus.INSUFFICIENT_EVIDENCE,
            "Execution evidence does not declare signal_lag_bars.",
        )
    raw_lag = execution["signal_lag_bars"]
    lag = raw_lag if isinstance(raw_lag, int) and not isinstance(raw_lag, bool) else -1
    if lag < 1:
        return _check(
            "NEXT_BAR_EXECUTION",
            "execution",
            AuditStatus.NO_GO,
            "Signals are executed on the same bar or use an invalid lag.",
            f"signal_lag_bars={lag}",
        )
    return _check(
        "NEXT_BAR_EXECUTION",
        "execution",
        AuditStatus.PASS,
        "Signals execute at least one bar after observation.",
        f"signal_lag_bars={lag}",
    )


def _cost_check(results: dict[str, Any]) -> AuditCheck:
    costs = results.get("costs")
    if not isinstance(costs, dict):
        return _check(
            "COSTS_DECLARED",
            "economics",
            AuditStatus.INSUFFICIENT_EVIDENCE,
            "No cost model is declared.",
        )
    applied = costs.get("applied") is True
    cost_values = [costs.get(key) for key in ("total_cost_bps", "fee_bps", "slippage_bps")]
    if any(isinstance(value, bool) for value in cost_values):
        return _check(
            "COSTS_DECLARED",
            "economics",
            AuditStatus.NO_GO,
            "Boolean values are not valid numeric costs.",
        )
    finite = [value for value in cost_values if _is_finite_number(value)]
    if not applied or not finite or any(float(value) < 0 for value in finite):
        return _check(
            "COSTS_DECLARED",
            "economics",
            AuditStatus.NO_GO,
            "Costs are absent, not applied, negative, or non-finite.",
        )
    return _check(
        "COSTS_DECLARED",
        "economics",
        AuditStatus.PASS,
        "Applied fees/slippage are explicitly declared.",
    )


def _benchmark_values(raw: object) -> list[tuple[str, float]]:
    values: list[tuple[str, float]] = []
    if isinstance(raw, dict):
        iterable: Iterable[tuple[object, object]] = raw.items()
        for name, value in iterable:
            if _is_finite_number(value):
                values.append((str(name), float(value)))
            elif isinstance(value, dict):
                metric = value.get("net_return")
                if _is_finite_number(metric):
                    values.append((str(name), float(metric)))
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            metric = item.get("net_return")
            if _is_finite_number(metric):
                values.append((str(item.get("name", "benchmark")), float(metric)))
    return values


def _benchmark_checks(results: dict[str, Any]) -> list[AuditCheck]:
    raw_benchmarks = results.get("benchmarks")
    invalid_boolean = False
    if isinstance(raw_benchmarks, dict):
        invalid_boolean = any(
            isinstance(value, bool)
            or (isinstance(value, dict) and isinstance(value.get("net_return"), bool))
            for value in raw_benchmarks.values()
        )
    elif isinstance(raw_benchmarks, list):
        invalid_boolean = any(
            isinstance(item, dict) and isinstance(item.get("net_return"), bool)
            for item in raw_benchmarks
        )
    values = _benchmark_values(raw_benchmarks)
    if invalid_boolean:
        return [
            _check(
                "BENCHMARKS_DECLARED",
                "economics",
                AuditStatus.NO_GO,
                "Boolean values are not valid benchmark returns.",
            ),
            _check(
                "NET_BENCHMARK_RESULT",
                "economics",
                AuditStatus.INSUFFICIENT_EVIDENCE,
                "Economic comparison is invalid because a benchmark return is boolean.",
            ),
        ]
    if not values:
        return [
            _check(
                "BENCHMARKS_DECLARED",
                "economics",
                AuditStatus.INSUFFICIENT_EVIDENCE,
                "No benchmark with a finite net return is declared.",
            ),
            _check(
                "NET_BENCHMARK_RESULT",
                "economics",
                AuditStatus.INSUFFICIENT_EVIDENCE,
                "Economic superiority cannot be evaluated without benchmarks.",
            ),
        ]
    declared = _check(
        "BENCHMARKS_DECLARED",
        "economics",
        AuditStatus.PASS,
        "At least one finite net benchmark result is declared.",
        f"benchmarks={','.join(name for name, _ in values)}",
    )
    strategy_return = results.get("strategy_net_return")
    if not _is_finite_number(strategy_return):
        comparison = _check(
            "NET_BENCHMARK_RESULT",
            "economics",
            AuditStatus.INSUFFICIENT_EVIDENCE,
            "A finite strategy_net_return is required for comparison.",
        )
    elif float(strategy_return) <= max(value for _, value in values):
        # Still blocking, and deliberately labelled RESULT: losing to the
        # benchmark is a correctly measured outcome, not a flaw in the method.
        comparison = _check(
            "NET_BENCHMARK_RESULT",
            "economics",
            AuditStatus.NO_GO,
            "Net strategy return does not exceed every declared benchmark.",
            f"strategy_net_return={float(strategy_return)}",
            f"best_benchmark_net_return={max(value for _, value in values)}",
            finding_class=FindingClass.RESULT,
        )
    else:
        comparison = _check(
            "NET_BENCHMARK_RESULT",
            "economics",
            AuditStatus.PASS,
            "Net strategy return exceeds every declared benchmark.",
            f"strategy_net_return={float(strategy_return)}",
            f"best_benchmark_net_return={max(value for _, value in values)}",
            finding_class=FindingClass.RESULT,
        )
    return [declared, comparison]


def _ledger_check(path: Path | None, results: dict[str, Any]) -> AuditCheck:
    if path is None:
        return _check(
            "TRIAL_LEDGER",
            "governance",
            AuditStatus.INSUFFICIENT_EVIDENCE,
            "No trial ledger was supplied.",
        )
    ledger = _load_json_object(path, "trial ledger")
    trials = ledger.get("trials")
    if (
        not isinstance(trials, list)
        or not trials
        or not all(isinstance(item, dict) for item in trials)
    ):
        return _check(
            "TRIAL_LEDGER",
            "governance",
            AuditStatus.NO_GO,
            "Trial ledger must contain a non-empty list of trial objects.",
        )
    ids = [str(item.get("trial_id", "")).strip() for item in trials]
    if any(not trial_id for trial_id in ids) or len(set(ids)) != len(ids):
        return _check(
            "TRIAL_LEDGER",
            "governance",
            AuditStatus.NO_GO,
            "Trial identifiers are missing or duplicated.",
        )
    actual_hash = sha256_of_file(path)
    declared_hash = str(results.get("trial_ledger_sha256", ""))
    if not declared_hash:
        return _check(
            "TRIAL_LEDGER",
            "governance",
            AuditStatus.INSUFFICIENT_EVIDENCE,
            "Results do not bind themselves to the supplied trial ledger.",
            f"actual_sha256={actual_hash}",
        )
    if declared_hash != actual_hash:
        return _check(
            "TRIAL_LEDGER",
            "governance",
            AuditStatus.NO_GO,
            "Results reference different trial-ledger bytes.",
            f"declared_sha256={declared_hash}",
            f"actual_sha256={actual_hash}",
        )
    return _check(
        "TRIAL_LEDGER",
        "governance",
        AuditStatus.PASS,
        "Trial ledger is non-empty, uniquely identified, and byte-bound to results.",
        f"trials={len(trials)}",
    )


def _aggregate(checks: tuple[AuditCheck, ...]) -> AuditVerdict:
    no_go = tuple(check.code for check in checks if check.status is AuditStatus.NO_GO)
    insufficient = tuple(
        check.code for check in checks if check.status is AuditStatus.INSUFFICIENT_EVIDENCE
    )
    passed = sum(check.status is AuditStatus.PASS for check in checks)
    if no_go:
        status = AuditStatus.NO_GO
        reasons = tuple(f"blocking:{code}" for code in no_go)
    elif insufficient:
        status = AuditStatus.INSUFFICIENT_EVIDENCE
        reasons = tuple(f"missing:{code}" for code in insufficient)
    else:
        status = AuditStatus.PASS
        reasons = ("all_declared_research_checks_passed",)
    return AuditVerdict(
        status=status,
        reasons=reasons,
        pass_count=passed,
        no_go_count=len(no_go),
        insufficient_evidence_count=len(insufficient),
        real_money_authorized=False,
    )


def run_audit(audit_input: AuditInput, *, redact: bool = False) -> AuditBundle:
    """Evaluate local evidence and return a deterministic, fail-closed bundle.

    With ``redact`` the emitted bundle carries file names instead of absolute
    paths, so a delivered report does not disclose either party's directory
    layout.  Files are still read from the real paths; only what is written out
    changes, and the bundle stays verifiable from its own bytes.
    """
    _parse_utc(audit_input.evaluation_cutoff_utc)
    if (
        isinstance(audit_input.max_file_size_bytes, bool)
        or not isinstance(audit_input.max_file_size_bytes, int)
        or audit_input.max_file_size_bytes <= 0
        or audit_input.max_file_size_bytes > _HARD_MAX_FILE_BYTES
    ):
        raise ValueError("invalid max_file_size_bytes")
    paths = _validate_runtime_paths(audit_input)
    input_hashes = tuple((name, sha256_of_file(path)) for name, path in sorted(paths.items()))
    hash_map = dict(input_hashes)
    rows = _load_dataset(paths["dataset"])
    results = _load_json_object(paths["results"], "results")

    checks: list[AuditCheck] = [
        _check(
            "INPUT_BYTES",
            "reproducibility",
            AuditStatus.PASS,
            "Every supplied input was read as bounded local bytes and hashed.",
            f"files={len(paths)}",
        )
    ]
    checks.extend(_schema_checks(rows, audit_input))
    checks.extend(_timestamp_checks(rows, audit_input))
    checks.append(
        _manifest_check(
            paths.get("manifest"),
            paths["dataset"],
            hash_map["dataset"],
            audit_input.evaluation_cutoff_utc,
        )
    )
    checks.append(_results_binding_check(results, hash_map["dataset"]))
    checks.append(_execution_check(results))
    checks.append(_cost_check(results))
    checks.extend(_benchmark_checks(results))
    checks.append(_ledger_check(paths.get("trial_ledger"), results))
    checks.append(
        _check(
            "SAFETY_BOUNDARY",
            "safety",
            AuditStatus.PASS,
            "Audit was local-only, executed no customer code, and cannot authorize real money.",
            "network_accessed=false",
            "customer_code_executed=false",
            "real_money_authorized=false",
        )
    )
    checks_tuple = tuple(checks)
    reported_input = audit_input.redacted() if redact else audit_input
    job_seed = canonical_dumps(
        {"audit_input": reported_input.to_dict(), "input_hashes": dict(input_hashes)}
    )
    job = AuditJob(job_id=f"audit-{sha256_of_text(job_seed)[:20]}")
    return AuditBundle(
        audit_input=reported_input,
        job=job,
        input_hashes=input_hashes,
        checks=checks_tuple,
        verdict=_aggregate(checks_tuple),
    )


def write_audit_bundle(bundle: AuditBundle, output_dir: str | Path) -> tuple[Path, Path]:
    """Write byte-stable JSON plus an escaped, deterministic HTML report."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_target = target / "audit.json"
    html_target = target / "audit.html"
    if json_target.exists() or html_target.exists():
        raise FileExistsError("refusing to overwrite an existing audit.json or audit.html")
    json_path = atomic_write_json(json_target, bundle.to_dict(), pretty=False)
    html_path = atomic_write_text(html_target, render_html(bundle))
    return json_path, html_path
