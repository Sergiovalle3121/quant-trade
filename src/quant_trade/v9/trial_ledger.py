"""The global trial ledger, and the multiplicity that follows from it.

The deflated Sharpe ratio only deflates if it knows how many things were
tried. V8 could pass ``trial_registry=None`` and a Sharpe variance of zero, at
which point DSR collapses to PSR and the correction for multiple testing
silently disappears — the single most convenient bug a research pipeline can
have.

V9 makes the ledger mandatory for anything promotable and computes the
variance from what is actually in it. Three rules give the count meaning:

* **Register before observing.** A trial is appended when it is *launched*, so
  a run that turns out badly cannot be quietly omitted.
* **A byte-identical reproduction is the same trial.** Same code, config and
  data means the same experiment run twice, not two experiments.
* **Anything else is a new trial.** A changed parameter, a re-pulled dataset,
  a different seed — each is another draw from the search, and each raises the
  bar the winner must clear.

The ledger is append-only and hash-chained, so a trial cannot be removed after
the fact without breaking every record that followed it.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text

TRIAL_STATUS_LAUNCHED = "launched"
TRIAL_STATUS_EVALUATED = "evaluated"
TRIAL_STATUS_FAILED = "failed"
TRIAL_STATUSES = (TRIAL_STATUS_LAUNCHED, TRIAL_STATUS_EVALUATED, TRIAL_STATUS_FAILED)

#: Record kinds. A reproduction is written down but does not raise the count.
RECORD_TRIAL = "trial"
RECORD_OUTCOME = "outcome"
RECORD_REPRODUCTION = "reproduction"


class TrialLedgerError(RuntimeError):
    """The ledger was asked to do something that would understate the search."""


@dataclass
class TrialRecord:
    """One attempt. Its identity is what makes it distinct from another."""

    trial_id: str
    hypothesis_id: str
    variant_id: str
    code_sha: str
    config_sha: str
    dataset_sha: str
    seed: int | None
    status: str = TRIAL_STATUS_LAUNCHED
    oos_sharpe: float | None = None
    oos_total_return: float | None = None
    registered_at_utc: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.status not in TRIAL_STATUSES:
            raise TrialLedgerError(f"status must be one of {TRIAL_STATUSES}")

    @property
    def identity(self) -> str:
        """What makes two runs the same experiment.

        Only a byte-identical reproduction — same code, same config, same data,
        same seed — collapses. Everything else is another draw.
        """
        return sha256_of_text(
            canonical_dumps(
                {
                    "hypothesis_id": self.hypothesis_id,
                    "variant_id": self.variant_id,
                    "code_sha": self.code_sha,
                    "config_sha": self.config_sha,
                    "dataset_sha": self.dataset_sha,
                    "seed": self.seed,
                }
            )
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["identity"] = self.identity
        return payload


@dataclass
class LedgerStats:
    total_records: int
    distinct_trials: int
    duplicate_reproductions: int
    evaluated_trials: int
    failed_trials: int
    sharpe_variance: float
    sharpes: list[float] = field(default_factory=list)
    chain_problems: list[str] = field(default_factory=list)

    @property
    def chain_intact(self) -> bool:
        return not self.chain_problems

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["chain_intact"] = self.chain_intact
        return payload


class GlobalTrialLedger:
    """Append-only, hash-chained record of every trial ever launched."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    def _append(self, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self._read()
        payload = dict(payload)
        payload["previous_sha256"] = str(existing[-1]["record_sha256"]) if existing else "0" * 64
        payload["record_sha256"] = sha256_of_text(canonical_dumps(payload))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_dumps(payload) + "\n")
        return payload

    def register(self, record: TrialRecord) -> dict[str, Any]:
        """Append a trial, or record a reproduction of one already known.

        A byte-identical rerun does not raise the trial count, but it is still
        written down as a ``reproduction``. Dropping it silently would leave no
        trace that the experiment was repeated, and "we ran it again and got
        the same thing" is evidence worth keeping.
        """
        identity = record.identity
        known = {
            str(r.get("identity"))
            for r in self._read()
            if r.get("kind") in (RECORD_TRIAL, RECORD_OUTCOME)
        }
        payload = record.to_dict()
        payload["kind"] = RECORD_REPRODUCTION if identity in known else RECORD_TRIAL
        return self._append(payload)

    def complete(
        self,
        record: TrialRecord,
        *,
        oos_sharpe: float | None,
        oos_total_return: float | None,
        status: str = TRIAL_STATUS_EVALUATED,
    ) -> dict[str, Any]:
        """Record a trial's outcome as a new chained entry.

        The result is appended rather than edited in place: rewriting the
        launch record would make the ledger a summary of what survived instead
        of a record of what was attempted.
        """
        completed = TrialRecord(
            trial_id=record.trial_id,
            hypothesis_id=record.hypothesis_id,
            variant_id=record.variant_id,
            code_sha=record.code_sha,
            config_sha=record.config_sha,
            dataset_sha=record.dataset_sha,
            seed=record.seed,
            status=status,
            oos_sharpe=oos_sharpe,
            oos_total_return=oos_total_return,
            registered_at_utc=record.registered_at_utc,
            notes=record.notes,
        )
        payload = completed.to_dict()
        payload["kind"] = RECORD_OUTCOME
        return self._append(payload)

    def verify_chain(self) -> list[str]:
        problems: list[str] = []
        previous = "0" * 64
        for line_number, record in enumerate(self._read(), start=1):
            if record.get("previous_sha256") != previous:
                problems.append(f"chain predecessor mismatch at line {line_number}")
            body = {k: v for k, v in record.items() if k != "record_sha256"}
            if sha256_of_text(canonical_dumps(body)) != record.get("record_sha256"):
                problems.append(f"content hash mismatch at line {line_number}")
            previous = str(record.get("record_sha256", ""))
        return problems

    def stats(self) -> LedgerStats:
        """Distinct-trial count and the real cross-trial Sharpe variance."""
        records = self._read()
        identities: dict[str, dict[str, Any]] = {}
        duplicates = 0
        for record in records:
            identity = str(record.get("identity", ""))
            if record.get("kind") == RECORD_REPRODUCTION:
                duplicates += 1
                continue
            # A later outcome supersedes the launch record for the same
            # identity, so both the status and the Sharpe are the observed ones.
            identities[identity] = record
        sharpes = [
            float(r["oos_sharpe"])
            for r in identities.values()
            if r.get("oos_sharpe") is not None and math.isfinite(float(r["oos_sharpe"]))
        ]
        return LedgerStats(
            total_records=len(records),
            distinct_trials=len(identities),
            duplicate_reproductions=duplicates,
            evaluated_trials=sum(
                1 for r in identities.values() if r.get("status") == TRIAL_STATUS_EVALUATED
            ),
            failed_trials=sum(
                1 for r in identities.values() if r.get("status") == TRIAL_STATUS_FAILED
            ),
            sharpe_variance=_variance(sharpes),
            sharpes=sorted(sharpes),
            chain_problems=self.verify_chain(),
        )

    def summary(self) -> dict[str, Any]:
        stats = self.stats()
        return {
            "artifact": "GLOBAL_TRIAL_LEDGER_SUMMARY",
            "schema_version": 1,
            "path": str(self.path),
            **stats.to_dict(),
            "multiplicity_rule": (
                "A byte-identical reproduction of code, config, data and seed is "
                "the same trial. Any other difference is a new draw from the "
                "search and raises the bar the winner must clear."
            ),
        }


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / (len(values) - 1)


def require_promotable_ledger(ledger: GlobalTrialLedger | None) -> LedgerStats:
    """Fail closed unless a real ledger backs the multiplicity correction."""
    if ledger is None:
        raise TrialLedgerError(
            "a promotable campaign requires a persistent trial ledger; without "
            "one the deflated Sharpe silently degenerates into the "
            "probabilistic Sharpe and the multiple-testing correction vanishes"
        )
    stats = ledger.stats()
    if stats.chain_problems:
        raise TrialLedgerError(
            "the trial ledger's hash chain is broken: " + "; ".join(stats.chain_problems[:3])
        )
    if stats.distinct_trials < 1:
        raise TrialLedgerError("the trial ledger is empty; nothing was registered")
    if stats.distinct_trials > 1 and stats.sharpe_variance <= 0 and len(stats.sharpes) > 1:
        raise TrialLedgerError(
            f"{stats.distinct_trials} distinct trials recorded but the "
            "cross-trial Sharpe variance is zero; a heterogeneous search cannot "
            "have identical outcomes"
        )
    return stats


def deflated_sharpe(
    sharpe: float,
    *,
    observations: int,
    trials: int,
    sharpe_variance: float,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Bailey & López de Prado's deflated Sharpe ratio.

    The expected maximum Sharpe from ``trials`` independent draws is subtracted
    before the significance test, so a Sharpe that would be impressive from one
    attempt stops being impressive from fifty.
    """
    from math import erf, exp, sqrt

    if observations < 2:
        return 0.0
    trials = max(1, int(trials))
    if trials == 1 or sharpe_variance <= 0:
        expected_max = 0.0
    else:
        euler = 0.5772156649015329
        # E[max] of `trials` standard normals, scaled by the cross-trial spread.
        z_first = _norm_ppf(1.0 - 1.0 / trials)
        z_second = _norm_ppf(1.0 - 1.0 / (trials * exp(1.0)))
        expected_max = sqrt(sharpe_variance) * ((1.0 - euler) * z_first + euler * z_second)
    excess = sharpe - expected_max
    denominator = sqrt(
        max(
            1e-18,
            1.0 - skew * sharpe + (kurtosis - 1.0) / 4.0 * sharpe**2,
        )
    )
    statistic = excess * sqrt(observations - 1) / denominator
    return 0.5 * (1.0 + erf(statistic / sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation)."""
    if not 0.0 < p < 1.0:
        return 0.0
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    low, high = 0.02425, 1 - 0.02425
    if p < low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > high:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    )


__all__ = [
    "TRIAL_STATUSES",
    "TRIAL_STATUS_EVALUATED",
    "TRIAL_STATUS_FAILED",
    "TRIAL_STATUS_LAUNCHED",
    "RECORD_OUTCOME",
    "RECORD_REPRODUCTION",
    "RECORD_TRIAL",
    "GlobalTrialLedger",
    "LedgerStats",
    "TrialLedgerError",
    "TrialRecord",
    "deflated_sharpe",
    "require_promotable_ledger",
]
