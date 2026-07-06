from __future__ import annotations

import csv
import json
from pathlib import Path

from .exceptions import TrialDataMissingError
from .models import DailyTrialRecord, TrialConfig, utc_now

SECRET_WORDS = ("secret", "api_key", "token", "password", "credential")
FIELDS = list(DailyTrialRecord.__annotations__.keys())


def validate_daily_records(records: list[DailyTrialRecord]) -> list[str]:
    warnings = []
    seen = set()
    for r in records:
        if r.date in seen:
            raise ValueError(f"duplicate daily record date: {r.date}")
        seen.add(r.date)
        text = json.dumps(r.to_dict()).lower()
        if any(w in text for w in SECRET_WORDS):
            raise ValueError("possible secret in daily record")
        if r.heartbeat_status != "ok":
            warnings.append(f"stale heartbeat on {r.date}")
    return warnings


def append_daily_record(record: DailyTrialRecord, output_path: Path | str) -> Path:
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    exists = p.exists()
    if exists:
        current = load_trial_timeseries(record.trial_id, p)
        if any(r.date == record.date for r in current):
            raise ValueError("duplicate daily record date")
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            w.writeheader()
        w.writerow(record.to_dict())
    return p


def load_trial_timeseries(trial_id: str, path: Path | str | None = None) -> list[DailyTrialRecord]:
    p = Path(path) if path else Path("outputs/trials") / trial_id / "daily_records.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return [DailyTrialRecord.from_dict(r) for r in csv.DictReader(f)]


def collect_daily_records(
    trial_config: TrialConfig,
    artifact_roots: list[Path] | None = None,
    state_roots: list[Path] | None = None,
) -> list[DailyTrialRecord]:
    """Load REAL daily records for a trial; fail closed when none exist.

    A trial process that invents data when records are missing manufactures
    exactly the false confidence it exists to prevent. Export records from a
    paper session first: `quant-trade trials export-daily-records ...`.
    """
    del state_roots
    records = []
    roots = artifact_roots or [Path("outputs/trials")]
    for root in roots:
        p = root / f"{trial_config.trial_id}_daily_records.csv"
        if p.exists():
            with p.open(encoding="utf-8") as f:
                records = [
                    DailyTrialRecord.from_dict(
                        {
                            **r,
                            "trial_id": trial_config.trial_id,
                            "paper_session_id": trial_config.paper_session_id,
                        }
                    )
                    for r in csv.DictReader(f)
                ]
            break
    if not records:
        searched = ", ".join(str(r) for r in roots)
        raise TrialDataMissingError(
            f"no daily records found for trial {trial_config.trial_id} (searched: {searched}); "
            "export them from a paper session with "
            "'quant-trade trials export-daily-records' - trial data is never fabricated"
        )
    validate_daily_records(records)
    out = Path("outputs/trials") / trial_config.trial_id
    out.mkdir(parents=True, exist_ok=True)
    csvp = out / "daily_records.csv"
    with csvp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        [w.writerow(r.to_dict()) for r in records]
    (out / "trial_state.json").write_text(
        json.dumps(
            {
                "trial_id": trial_config.trial_id,
                "records": len(records),
                "real_money_ready": False,
                "updated_at_utc": utc_now(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    with (out / "trial_events.jsonl").open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "event": "collect_daily_records",
                    "count": len(records),
                    "created_at_utc": utc_now(),
                }
            )
            + "\n"
        )
    return records
