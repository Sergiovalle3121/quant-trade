"""Append-only trial ledger with honest hypothesis/attempt identity.

Every backtest evaluation — each research run, every grid-search combination,
every walk-forward window fit, and every *discarded* or *failed* candidate —
appends one line here. Without an honest record of how many things were tried,
the deflated Sharpe multiple-testing correction cannot exist.

The v2 schema separates three identities:

- ``hypothesis_id`` — deterministic over (strategy, params, dataset SHA, split
  policy, feature version). The same economic idea on the same data always
  hashes to the same hypothesis, so re-tuning a knob is recognisably a *new*
  hypothesis, not a free re-roll.
- ``attempt_id`` — unique per execution. Two runs of the same hypothesis are
  two attempts.
- ``content_fingerprint`` — deterministic over (hypothesis, code SHA, dataset
  SHA, config SHA, seed). Two attempts with the same fingerprint are a
  *reproducible rerun* of an identical computation; a different fingerprint
  means something material changed.

Old flat rows remain readable (``schema_version`` absent). Corrupt lines are
**never silently dropped from the integrity decision**: :func:`read_ledger`
surfaces them with line numbers and :func:`ledger_integrity_report` fails the
ledger, so a promotion gate can refuse to trust a damaged record.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_trade.metrics.statistics import sharpe_variance_across_trials

LEDGER_FILENAME = "trial_ledger.jsonl"
SCHEMA_VERSION = 2


def ledger_path(outputs_dir: str | Path) -> Path:
    return Path(outputs_dir) / LEDGER_FILENAME


# --- hashing / identity ---------------------------------------------------


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))


def sha256_hex(obj: Any) -> str:
    return hashlib.sha256(_canonical_json(obj).encode("utf-8")).hexdigest()


def compute_hypothesis_id(
    strategy: str,
    params: dict[str, Any],
    dataset_sha: str,
    split_policy: str,
    feature_version: str,
) -> str:
    digest = sha256_hex(
        {
            "strategy": strategy,
            "params": params,
            "dataset_sha": dataset_sha,
            "split_policy": split_policy,
            "feature_version": feature_version,
        }
    )
    return f"hyp_{digest[:16]}"


def content_fingerprint(
    hypothesis_id: str,
    code_sha: str,
    dataset_sha: str,
    config_sha: str,
    seed: int | None,
) -> str:
    digest = sha256_hex(
        {
            "hypothesis_id": hypothesis_id,
            "code_sha": code_sha,
            "dataset_sha": dataset_sha,
            "config_sha": config_sha,
            "seed": seed,
        }
    )
    return f"fp_{digest[:16]}"


def new_attempt_id() -> str:
    return f"att_{uuid.uuid4().hex[:16]}"


def resolve_code_sha(start: str | Path | None = None) -> str:
    """Best-effort current commit SHA for audit; ``"unknown"`` if unavailable."""
    for env in ("QUANT_TRADE_CODE_SHA", "GIT_COMMIT", "GITHUB_SHA"):
        value = os.environ.get(env)
        if value:
            return value.strip()
    root = Path(start or Path.cwd())
    for base in [root, *root.parents]:
        git_dir = base / ".git"
        head = git_dir / "HEAD"
        if not head.exists():
            continue
        try:
            content = head.read_text(encoding="utf-8").strip()
        except OSError:
            return "unknown"
        if not content.startswith("ref:"):
            return content  # detached HEAD
        ref = content.split(" ", 1)[1].strip()
        ref_file = git_dir / ref
        if ref_file.exists():
            return ref_file.read_text(encoding="utf-8").strip()
        packed = git_dir / "packed-refs"
        if packed.exists():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line.endswith(ref):
                    return line.split(" ", 1)[0].strip()
        return "unknown"
    return "unknown"


# --- structured record ----------------------------------------------------


@dataclass
class TrialRecord:
    """One evaluated, failed, or discarded trial (v2 schema)."""

    hypothesis_id: str
    attempt_id: str
    run_id: str
    status: str  # "evaluated" | "failed" | "discarded"
    source: str
    strategy: str
    strategy_params: dict[str, Any]
    dataset_sha: str = ""
    config_sha: str = ""
    code_sha: str = ""
    seed: int | None = None
    split_policy: str = ""
    feature_version: str = ""
    execution_policy_hash: str = ""
    costs: dict[str, Any] = field(default_factory=dict)
    train_range: list[str] | None = None
    test_range: list[str] | None = None
    test_sharpe_per_period: float | None = None
    test_sharpe: float | None = None
    test_total_return: float | None = None
    trade_count: int | None = None
    content_fingerprint: str = ""
    error: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.status not in ("evaluated", "failed", "discarded"):
            raise ValueError(f"invalid trial status {self.status!r}")

    def to_entry(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}


def build_trial_record(
    *,
    source: str,
    strategy: str,
    strategy_params: dict[str, Any],
    run_id: str,
    status: str = "evaluated",
    dataset_sha: str = "",
    config_sha: str = "",
    code_sha: str | None = None,
    seed: int | None = None,
    split_policy: str = "",
    feature_version: str = "",
    execution_policy_hash: str = "",
    costs: dict[str, Any] | None = None,
    train_range: list[str] | None = None,
    test_range: list[str] | None = None,
    test_sharpe_per_period: float | None = None,
    test_sharpe: float | None = None,
    test_total_return: float | None = None,
    trade_count: int | None = None,
    error: str | None = None,
) -> TrialRecord:
    """Assemble a :class:`TrialRecord`, deriving identity fields."""
    resolved_code_sha = resolve_code_sha() if code_sha is None else code_sha
    hypothesis_id = compute_hypothesis_id(
        strategy, strategy_params, dataset_sha, split_policy, feature_version
    )
    return TrialRecord(
        hypothesis_id=hypothesis_id,
        attempt_id=new_attempt_id(),
        run_id=run_id,
        status=status,
        source=source,
        strategy=strategy,
        strategy_params=strategy_params,
        dataset_sha=dataset_sha,
        config_sha=config_sha,
        code_sha=resolved_code_sha,
        seed=seed,
        split_policy=split_policy,
        feature_version=feature_version,
        execution_policy_hash=execution_policy_hash,
        costs=costs or {},
        train_range=train_range,
        test_range=test_range,
        test_sharpe_per_period=test_sharpe_per_period,
        test_sharpe=test_sharpe,
        test_total_return=test_total_return,
        trade_count=trade_count,
        content_fingerprint=content_fingerprint(
            hypothesis_id, resolved_code_sha, dataset_sha, config_sha, seed
        ),
        error=error,
    )


# --- writing --------------------------------------------------------------


def append_trial(outputs_dir: str | Path, entry: dict[str, Any]) -> Path:
    """Append a raw entry (legacy flat schema stays supported)."""
    path = ledger_path(outputs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"recorded_at_utc": datetime.now(UTC).isoformat(), **entry}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return path


def append_trial_record(outputs_dir: str | Path, record: TrialRecord) -> Path:
    return append_trial(outputs_dir, record.to_entry())


# --- reading --------------------------------------------------------------


@dataclass
class LedgerReadResult:
    records: list[dict[str, Any]]
    corrupt_lines: list[tuple[int, str]]  # (1-based line number, raw text)


def read_ledger(outputs_dir: str | Path) -> LedgerReadResult:
    """Read every line, keeping corrupt lines instead of dropping them silently."""
    path = ledger_path(outputs_dir)
    if not path.exists():
        return LedgerReadResult(records=[], corrupt_lines=[])
    records: list[dict[str, Any]] = []
    corrupt: list[tuple[int, str]] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            corrupt.append((i, raw))
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
        else:
            corrupt.append((i, raw))
    return LedgerReadResult(records=records, corrupt_lines=corrupt)


def read_trials(outputs_dir: str | Path) -> list[dict[str, Any]]:
    """Lenient read (skips corrupt lines). For integrity decisions use
    :func:`ledger_integrity_report`, which never hides corruption."""
    return read_ledger(outputs_dir).records


def ledger_stats(outputs_dir: str | Path) -> tuple[int, float]:
    """(trial count, cross-trial variance of per-period test Sharpes).

    Counts every recorded evaluation, not just the winners — using only
    surviving runs would understate the search and inflate the deflated Sharpe.
    """
    trials = read_trials(outputs_dir)
    sharpes = [
        float(t["test_sharpe_per_period"])
        for t in trials
        if t.get("test_sharpe_per_period") is not None
    ]
    return len(trials), sharpe_variance_across_trials(sharpes)


# --- integrity report -----------------------------------------------------


@dataclass
class LedgerIntegrityReport:
    path: str
    exists: bool
    total_lines: int
    valid_records: int
    corrupt_lines: int
    corrupt_line_numbers: list[int]
    structured_records: int
    legacy_records: int
    n_hypotheses: int
    n_attempts: int
    n_valid_observations: int
    n_evaluated: int
    n_failed: int
    n_discarded: int
    reproducible_rerun_groups: int
    sharpe_variance: float
    effective_trial_count: int
    effective_trial_basis: str
    trial_correlation_assumption: str
    is_intact: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ledger_integrity_report(outputs_dir: str | Path) -> LedgerIntegrityReport:
    """Audit the ledger: counts, corruption, and a conservative DSR trial count.

    Effective-trial policy: we count every recorded evaluation with a usable
    per-period Sharpe as one trial and **assume independence** (no correlation
    shrinkage). Correlated trials have a smaller effective count, which would
    *lower* the expected-max-Sharpe threshold; assuming independence keeps the
    threshold as high as the data supports, which is the conservative choice for
    an approval gate. When trial correlation cannot be estimated we therefore
    use the full count rather than an unvalidated shrinkage estimator.
    """
    path = ledger_path(outputs_dir)
    read = read_ledger(outputs_dir)
    records = read.records
    corrupt = read.corrupt_lines

    structured = [r for r in records if r.get("schema_version")]
    legacy = [r for r in records if not r.get("schema_version")]
    hypotheses = {r["hypothesis_id"] for r in structured if r.get("hypothesis_id")}
    attempts = {r["attempt_id"] for r in structured if r.get("attempt_id")}
    fingerprints: dict[str, int] = {}
    for r in structured:
        fp = r.get("content_fingerprint")
        if fp:
            fingerprints[fp] = fingerprints.get(fp, 0) + 1
    rerun_groups = sum(1 for count in fingerprints.values() if count > 1)

    def _status(r: dict[str, Any]) -> str:
        return str(r.get("status", "evaluated"))

    n_evaluated = sum(1 for r in records if _status(r) == "evaluated")
    n_failed = sum(1 for r in records if _status(r) == "failed")
    n_discarded = sum(1 for r in records if _status(r) == "discarded")
    observations = [
        float(r["test_sharpe_per_period"])
        for r in records
        if r.get("test_sharpe_per_period") is not None and _status(r) != "discarded"
    ]
    n_valid_observations = len(observations)
    variance = sharpe_variance_across_trials(observations)

    notes: list[str] = []
    if corrupt:
        notes.append(
            f"{len(corrupt)} corrupt line(s) at {[n for n, _ in corrupt]}; "
            "ledger is not trustworthy until repaired"
        )
    if legacy:
        notes.append(
            f"{len(legacy)} legacy row(s) without hypothesis identity are counted "
            "as trials but cannot be grouped by hypothesis"
        )
    if n_valid_observations < 2:
        notes.append(
            "fewer than 2 usable observations; cross-trial Sharpe variance is 0 "
            "and the deflated-Sharpe threshold degrades to PSR-vs-zero"
        )

    return LedgerIntegrityReport(
        path=str(path),
        exists=path.exists(),
        total_lines=len(records) + len(corrupt),
        valid_records=len(records),
        corrupt_lines=len(corrupt),
        corrupt_line_numbers=[n for n, _ in corrupt],
        structured_records=len(structured),
        legacy_records=len(legacy),
        n_hypotheses=len(hypotheses),
        n_attempts=len(attempts),
        n_valid_observations=n_valid_observations,
        n_evaluated=n_evaluated,
        n_failed=n_failed,
        n_discarded=n_discarded,
        reproducible_rerun_groups=rerun_groups,
        sharpe_variance=variance,
        effective_trial_count=n_valid_observations,
        effective_trial_basis=(
            "one trial per recorded evaluation with a usable per-period Sharpe "
            "(discarded rows excluded)"
        ),
        trial_correlation_assumption=(
            "independent trials (no correlation shrinkage); conservative for an "
            "approval gate when correlation cannot be estimated"
        ),
        is_intact=(len(corrupt) == 0),
        notes=notes,
    )
